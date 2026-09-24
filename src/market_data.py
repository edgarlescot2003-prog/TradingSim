"""Accès aux données de marché (prix, historique, recherche, taux de change).

Source : Yahoo Finance via la librairie yfinance. Couvre actions, ETF, indices
et les principales paires crypto (ex : BTC-USD), ce qui suffit pour la Phase 1.
Une source dédiée (Kraken/ccxt) pourra être ajoutée plus tard si une couverture
crypto plus fine est nécessaire.
"""

import time

import yfinance as yf

from . import diag_log, market_store


class MarketDataError(Exception):
    """Erreur métier lisible, à afficher telle quelle à l'utilisateur."""


# Coupe-circuit (voir market_store.py) : après un vrai 429 de Yahoo, plus
# aucun appel Yahoo pendant la pause, quel que soit le processus. Le cooldown
# de 30 s PAR TICKER plus bas reste en complément : il couvre les erreurs
# qui ne sont PAS des rate limits (ticker introuvable, erreur ponctuelle),
# qui ne doivent pas bloquer toute la source mais ne doivent pas non plus
# être retentées à chaque rerun.
YAHOO = "yahoo"


def _ensure_yahoo_available(operation: str, ticker: str) -> None:
    remaining = market_store.blocked_remaining(YAHOO)
    if remaining > 0:
        diag_log.log("circuit_open", "Yahoo", operation, ticker, "individual", 0.0)
        raise MarketDataError(
            f"Cotations Yahoo en pause (limite de requêtes atteinte) : reprise dans "
            f"{max(1, round(remaining / 60))} min."
        )


def _note_yahoo_error(error: Exception) -> None:
    if market_store.is_rate_limit_error(error):
        market_store.record_rate_limit(YAHOO, error)


# Exécutions AUTOMATIQUES (TP/SL, liquidation) : prix frais uniquement, jamais
# de prix daté — une liquidation sur un prix faux pénaliserait injustement un
# participant. Deux conditions (voir is_fresh_for_automation) :
# - le prix vient d'être obtenu de la source live (moins de 5 min) ;
# - pendant une séance ouverte, l'heure de cotation réelle annoncée par Yahoo
#   a moins de 30 min. Assez large pour les places cotées en différé
#   (Euronext 15 min, futures 10 min — mesuré le 24/09), assez strict pour
#   écarter un flux figé. Marché fermé : le dernier cours officiel reste un
#   prix exact (il ne bouge plus), donc accepté.
AUTOMATION_MAX_FETCH_AGE_SECONDS = 5 * 60
AUTOMATION_MAX_MARKET_DELAY_SECONDS = 30 * 60


def is_fresh_for_automation(quote: dict, now: float | None = None) -> bool:
    """Vrai si `quote` (résultat de get_quote) peut déclencher un TP/SL ou
    une liquidation. Faux pour tout prix daté (repli sur le dernier prix
    connu), même récent."""
    current_time = time.time() if now is None else now
    if quote.get("stale") or quote.get("fetched_at") is None:
        return False
    if current_time - quote["fetched_at"] > AUTOMATION_MAX_FETCH_AGE_SECONDS:
        return False
    market_time = quote.get("market_time")
    if quote.get("market_open") and market_time is not None:
        return current_time - market_time <= AUTOMATION_MAX_MARKET_DELAY_SECONDS
    return True


_FX_CACHE: dict[str, tuple[float, float]] = {}
_FX_CACHE_TTL_SECONDS = 300
_FX_ERROR_CACHE: dict[str, tuple[str, float]] = {}
_FX_ERROR_COOLDOWN_SECONDS = 30

# Cache court sur le prix courant : la revalorisation du Portefeuille (et du
# Classement) refait cet appel à chaque interaction, sans aucun cache
# jusqu'ici — un enchaînement rapide de clics pouvait donc envoyer une rafale
# de requêtes sur le même ticker et déclencher le rate-limit "Too Many
# Requests" de l'API gratuite de Yahoo. 30s correspond au rythme de
# rafraîchissement de la fiche Trading et reste largement assez frais pour
# un prix qui n'est de toute façon pas temps réel (voir get_quote).
_QUOTE_CACHE: dict[str, tuple[dict, float]] = {}
_QUOTE_CACHE_TTL_SECONDS = 30
_QUOTE_ERROR_CACHE: dict[str, tuple[str, float]] = {}
_QUOTE_ERROR_COOLDOWN_SECONDS = 30


def search_assets(query: str, max_results: int = 8) -> list[dict]:
    """Recherche des actifs par nom ou ticker. Retourne une liste de dicts
    {symbol, name, exchange, type}, éventuellement vide si rien ne correspond.
    """
    query = (query or "").strip()
    if not query:
        return []
    _ensure_yahoo_available("Search", query)
    started = time.perf_counter()
    try:
        results = yf.Search(query, max_results=max_results)
    except Exception as e:
        _note_yahoo_error(e)
        diag_log.log("error", "Yahoo", "Search", query, "individual", time.perf_counter() - started, repr(e), True)
        raise MarketDataError(
            f"Recherche impossible pour '{query}' (API indisponible : {e})."
        ) from e
    diag_log.log("success", "Yahoo", "Search", query, "individual", time.perf_counter() - started, real_request=True)
    market_store.record_success(YAHOO)

    assets = []
    for quote in results.quotes:
        symbol = quote.get("symbol")
        if not symbol:
            continue
        assets.append({
            "symbol": symbol,
            "name": quote.get("shortname") or quote.get("longname") or symbol,
            "exchange": quote.get("exchange", ""),
            "type": quote.get("quoteType", ""),
        })
    return assets


# Accueil Trading (~29 actifs) : un prix déjà obtenu il y a moins de 5 min
# (par n'importe quel processus, via last_known_prices) est réutilisé tel
# quel ; la variation 30 j, qui demande un historique, jusqu'à 1 h (même
# durée que l'ancien cache dédié _fetch_30d_changes).
BATCH_PRICE_REUSE_SECONDS = 5 * 60
BATCH_CHANGE_30D_REUSE_SECONDS = 60 * 60


def get_quotes_batch(tickers: tuple[str, ...]) -> dict[str, dict]:
    """Prix, variation du jour et variation 30 j pour une liste d'actifs
    (vitrine de l'accueil Trading, snapshot Admin). Retourne
    {ticker: {price, currency, previous_close, change_pct, change_30d_pct,
    fetched_at, stale}} ; un ticker sans aucune donnée est absent.

    Réduit la rafale à froid (29 requêtes d'un coup à chaque redémarrage) :
    1. lit d'abord les derniers prix connus en base (une seule requête SQL) ;
    2. n'appelle Yahoo QUE pour les actifs périmés, un par un, et s'arrête
       net au premier 429 (coupe-circuit) — yf.download continuait les 28
       autres tickers sur une IP déjà bloquée et avalait le 429 ;
    3. complète avec le dernier prix connu (stale=True) ce qui n'a pas pu
       être rafraîchi.
    Une requête par actif rafraîchi (historique 1 mois/1 j), comme
    yf.download(threads=False) avant, mais la devise vient maintenant des
    métadonnées Yahoo de l'actif au lieu d'une table codée en dur.
    """
    if not tickers:
        return {}
    now = time.time()
    known = market_store.get_last_known(tickers)
    result: dict[str, dict] = {}
    to_fetch = []
    for ticker in tickers:
        entry = known.get(ticker)
        reusable = (
            entry is not None
            and now - (entry.get("fetched_at") or 0) <= BATCH_PRICE_REUSE_SECONDS
            and entry.get("change_30d_at") is not None
            and now - entry["change_30d_at"] <= BATCH_CHANGE_30D_REUSE_SECONDS
        )
        if reusable:
            result[ticker] = _batch_entry(entry, stale=False)
        else:
            to_fetch.append(ticker)

    fetched = []
    for ticker in to_fetch:
        if market_store.blocked_remaining(YAHOO) > 0:
            break  # source en pause : plus aucun appel, repli sur les prix connus
        try:
            entry = _fetch_daily_summary(ticker)
        except MarketDataError:
            continue
        fetched.append(entry)
        result[ticker] = _batch_entry(entry, stale=False)
    market_store.remember_prices(fetched)  # une seule transaction pour le lot

    for ticker in tickers:
        if ticker not in result and ticker in known:
            result[ticker] = _batch_entry(known[ticker], stale=True)
    return result


def _batch_entry(entry: dict, stale: bool) -> dict:
    price, previous_close = entry["price"], entry.get("previous_close")
    return {
        "price": price, "currency": entry["currency"], "previous_close": previous_close,
        "change_pct": (price - previous_close) / previous_close * 100 if previous_close else None,
        "change_30d_pct": entry.get("change_30d_pct"), "fetched_at": entry.get("fetched_at"),
        "stale": stale,
    }


def _fetch_daily_summary(ticker: str) -> dict:
    """UNE requête Yahoo (historique 1 mois / 1 jour) : prix, clôture
    précédente, variation 30 j, devise réelle et heure de cotation."""
    _ensure_yahoo_available("history_1mo", ticker)
    started = time.perf_counter()
    try:
        tkr = yf.Ticker(ticker)
        hist = tkr.history(period="1mo", interval="1d")
    except Exception as e:
        diag_log.log("error", "Yahoo", "history_1mo", ticker, "batch", time.perf_counter() - started, repr(e), True)
        _note_yahoo_error(e)
        raise MarketDataError(f"Historique indisponible pour '{ticker}' ({e}).") from e
    closes = hist["Close"].dropna() if hist is not None and "Close" in hist else None
    if closes is None or closes.empty:
        diag_log.log("empty", "Yahoo", "history_1mo", ticker, "batch", time.perf_counter() - started, real_request=True)
        raise MarketDataError(f"Aucun historique disponible pour '{ticker}'.")
    meta = getattr(getattr(tkr, "_price_history", None), "_history_metadata", None) or {}
    currency = meta.get("currency")
    if not currency:
        diag_log.log("empty", "Yahoo", "history_1mo", ticker, "batch", time.perf_counter() - started,
                     "missing_currency", True)
        raise MarketDataError(f"Devise inconnue pour '{ticker}'.")
    market_store.record_success(YAHOO)
    diag_log.log("success", "Yahoo", "history_1mo", ticker, "batch", time.perf_counter() - started, real_request=True)
    now = time.time()
    price = float(closes.iloc[-1])
    first = float(closes.iloc[0])
    market_time, market_open = _market_timing(tkr)
    return {
        "ticker": ticker, "price": price, "currency": currency,
        "previous_close": float(closes.iloc[-2]) if len(closes) >= 2 else None,
        "quote_type": meta.get("instrumentType") or "", "market_time": market_time,
        "market_open": market_open, "fetched_at": now,
        "change_30d_pct": (price - first) / first * 100 if len(closes) >= 2 and first else None,
        "change_30d_at": now,
    }


def get_quote(ticker: str, allow_stale: bool = False) -> dict:
    """Retourne {price, currency, previous_close, quote_type, fetched_at,
    market_time, market_open, stale, source} pour le ticker donné, ou lève
    MarketDataError.

    - `price`/`currency` : prix dans la devise RÉELLE de l'actif.
    - `fetched_at` : heure (epoch) d'obtention du prix auprès de la source
      live — pour un prix daté, celle de son obtention d'origine.
    - `market_time` : heure de cotation réelle annoncée par Yahoo (peut
      précéder fetched_at de 10-15 min pour les places à cotation différée),
      None si inconnue. `market_open` : séance régulière en cours (None si
      inconnu).
    - `stale` : True si le prix vient du dernier prix connu
      (market_store.get_last_known) faute de source disponible ; ne se
      produit QUE si l'appelant passe `allow_stale=True` (affichage, ordres
      manuels sous conditions). Par défaut, un échec lève MarketDataError :
      TP/SL, liquidation et snapshots n'utilisent jamais de prix daté.
    """
    try:
        return _get_live_quote(ticker)
    except MarketDataError:
        if allow_stale:
            stale = _stale_quote(ticker)
            if stale is not None:
                return stale
        raise


def _stale_quote(ticker: str) -> dict | None:
    entry = market_store.get_last_known([ticker]).get(ticker)
    if entry is None or entry.get("fetched_at") is None:
        return None
    return {
        "price": float(entry["price"]), "currency": entry["currency"],
        "previous_close": entry.get("previous_close"), "quote_type": entry.get("quote_type") or "",
        "fetched_at": entry["fetched_at"], "market_time": entry.get("market_time"),
        "market_open": None, "stale": True, "source": "last_known",
    }


def _market_timing(tkr) -> tuple[float | None, bool | None]:
    """(heure de cotation réelle, séance en cours ?) lues dans les
    métadonnées DÉJÀ reçues avec fast_info — jamais via
    Ticker.get_history_metadata(), qui peut relancer une requête (période
    5 j/1 h) pour obtenir les horaires de séance. Attribut privé de
    yfinance, d'où la lecture entièrement défensive : (None, None) si absent."""
    try:
        meta = getattr(getattr(tkr, "_price_history", None), "_history_metadata", None) or {}
        market_time = meta.get("regularMarketTime")
        market_time = float(market_time) if isinstance(market_time, (int, float)) else None
        regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
        start, end = regular.get("start"), regular.get("end")
        market_open = None
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            market_open = start <= time.time() <= end
        return market_time, market_open
    except Exception:
        return None, None


def _get_live_quote(ticker: str) -> dict:
    """Retourne {price, currency, previous_close, quote_type} pour le ticker
    donné, ou lève MarketDataError. `previous_close` (peut être None si
    indisponible) sert au calcul du gain du jour ; `quote_type` (EQUITY/ETF/
    INDEX/CRYPTOCURRENCY/...) à la catégorisation par classe d'actif. Les deux
    viennent du même appel fast_info que le prix, donc sans coût réseau
    supplémentaire.

    Résultat mis en cache _QUOTE_CACHE_TTL_SECONDS secondes (voir plus haut) :
    un échec n'est jamais mis en cache, pour ne pas rester bloqué sur une
    erreur passagère plus longtemps que nécessaire.
    """
    cached = _QUOTE_CACHE.get(ticker)
    if cached and (time.time() - cached[1]) < _QUOTE_CACHE_TTL_SECONDS:
        diag_log.log("cache_hit", "Yahoo", "fast_info", ticker, "individual", 0.0)
        return cached[0]

    error_cached = _QUOTE_ERROR_CACHE.get(ticker)
    if error_cached and (time.time() - error_cached[1]) < _QUOTE_ERROR_COOLDOWN_SECONDS:
        diag_log.log("cooldown", "Yahoo", "fast_info", ticker, "individual", 0.0, error_cached[0])
        raise MarketDataError(error_cached[0])

    _ensure_yahoo_available("fast_info", ticker)
    started = time.perf_counter()
    try:
        tkr = yf.Ticker(ticker)
        info = tkr.fast_info
        price = info.get("last_price") or info.get("lastPrice")
        currency = info.get("currency")
        previous_close = info.get("previous_close") or info.get("previousClose")
        quote_type = info.get("quote_type") or info.get("quoteType") or ""
    except Exception as e:
        diag_log.log("error", "Yahoo", "fast_info", ticker, "individual", time.perf_counter() - started, repr(e), True)
        _note_yahoo_error(e)
        message = f"Ticker '{ticker}' introuvable ou API indisponible ({e})."
        _QUOTE_ERROR_CACHE[ticker] = (message, time.time())
        raise MarketDataError(message) from e

    if price is None or currency is None:
        diag_log.log("error", "Yahoo", "fast_info", ticker, "individual", time.perf_counter() - started, "missing_price_or_currency", True)
        message = f"Aucune donnée de prix disponible pour '{ticker}'."
        _QUOTE_ERROR_CACHE[ticker] = (message, time.time())
        raise MarketDataError(message)
    fetched_at = time.time()
    market_time, market_open = _market_timing(tkr)
    quote = {
        "price": float(price),
        "currency": currency,
        "previous_close": float(previous_close) if previous_close is not None else None,
        "quote_type": quote_type,
        "fetched_at": fetched_at,
        "market_time": market_time,
        "market_open": market_open,
        "stale": False,
        "source": "yahoo",
    }
    market_store.remember_prices([{"ticker": ticker, **quote}])
    _QUOTE_CACHE[ticker] = (quote, fetched_at)
    _QUOTE_ERROR_CACHE.pop(ticker, None)
    market_store.record_success(YAHOO)
    diag_log.log("success", "Yahoo", "fast_info", ticker, "individual", time.perf_counter() - started, real_request=True)
    return quote


# Secteur/pays ne changent quasiment jamais pour une action/ETF donnée
# (contrairement au prix) : cache TTL très long, uniquement pour limiter les
# appels à `.info` (endpoint yfinance nettement plus lourd que `.fast_info`
# utilisé par get_quote, jamais appelé ailleurs dans l'app).
_PROFILE_CACHE: dict[str, tuple[dict, float]] = {}
_PROFILE_CACHE_TTL_SECONDS = 12 * 3600
_HISTORY_ERROR_CACHE: dict[tuple[str, str], tuple[str, float]] = {}
_HISTORY_ERROR_COOLDOWN_SECONDS = 30


def get_company_profile(ticker: str) -> dict:
    """Retourne {"sector": str|None, "country": str|None} pour une action/ETF,
    utilisé uniquement par le camembert de diversification secteur/géographique
    de l'onglet Portefeuille (voir valuation.sector_for/country_for). NE LÈVE
    JAMAIS : un ticker introuvable, une erreur réseau ou un champ manquant/vide
    renvoie simplement None pour ce champ — c'est à l'appelant de retomber sur
    "Non défini" dans tous ces cas, jamais de faire planter le calcul du
    camembert pour une seule position en erreur.
    """
    cached = _PROFILE_CACHE.get(ticker)
    if cached and (time.time() - cached[1]) < _PROFILE_CACHE_TTL_SECONDS:
        return cached[0]

    if market_store.blocked_remaining(YAHOO) > 0:
        return {"sector": None, "country": None}  # pas mis en cache : retenté après la pause
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as e:
        if market_store.is_rate_limit_error(e):
            _note_yahoo_error(e)
            return {"sector": None, "country": None}  # pas mis en cache 12 h sur un 429
        info = {}

    profile = {
        "sector": info.get("sector") or None,
        "country": info.get("country") or None,
    }
    _PROFILE_CACHE[ticker] = (profile, time.time())
    return profile


def get_history(ticker: str, period: str = "6mo", interval: str = "1d", start=None):
    """Retourne un DataFrame OHLC (colonnes Open/High/Low/Close) ou lève MarketDataError.

    Si `start` est fourni (date ou Timestamp), il prime sur `period`.
    """
    error_key = (ticker, interval)
    error_cached = _HISTORY_ERROR_CACHE.get(error_key)
    if error_cached and (time.time() - error_cached[1]) < _HISTORY_ERROR_COOLDOWN_SECONDS:
        diag_log.log("cooldown", "Yahoo", "history", ticker, "individual", 0.0, error_cached[0])
        raise MarketDataError(error_cached[0])

    _ensure_yahoo_available("history", ticker)
    started = time.perf_counter()
    try:
        if start is not None:
            hist = yf.Ticker(ticker).history(start=start, interval=interval)
        else:
            hist = yf.Ticker(ticker).history(period=period, interval=interval)
    except Exception as e:
        diag_log.log("error", "Yahoo", "history", ticker, "individual", time.perf_counter() - started, repr(e), True)
        _note_yahoo_error(e)
        message = f"Historique indisponible pour '{ticker}' ({e})."
        _HISTORY_ERROR_CACHE[error_key] = (message, time.time())
        raise MarketDataError(message) from e

    if hist is None or hist.empty:
        diag_log.log("empty", "Yahoo", "history", ticker, "individual", time.perf_counter() - started, real_request=True)
        message = f"Aucun historique disponible pour '{ticker}'."
        _HISTORY_ERROR_CACHE[error_key] = (message, time.time())
        raise MarketDataError(message)
    _HISTORY_ERROR_CACHE.pop(error_key, None)
    market_store.record_success(YAHOO)
    diag_log.log("success", "Yahoo", "history", ticker, "individual", time.perf_counter() - started, real_request=True)
    return hist


# Du plus fin au plus grossier. yfinance refuse silencieusement (DataFrame
# vide) une plage trop longue pour un intervalle donné (~8 jours pour 1m,
# ~60 jours pour 5m/15m/30m, ~730 jours pour 1h) : en cas d'échec, on retente
# avec l'intervalle immédiatement moins précis plutôt que de planter.
INTERVAL_LADDER = ["1m", "5m", "15m", "30m", "1h", "1d"]


def get_history_with_fallback(ticker: str, interval: str, start) -> tuple:
    """Comme get_history, mais se rabat automatiquement sur un intervalle
    moins précis si l'intervalle demandé échoue pour la plage demandée.
    Retourne (DataFrame, intervalle_effectivement_utilisé).
    """
    try:
        start_idx = INTERVAL_LADDER.index(interval)
    except ValueError:
        start_idx = len(INTERVAL_LADDER) - 1

    last_error = None
    for candidate in INTERVAL_LADDER[start_idx:]:
        try:
            hist = get_history(ticker, interval=candidate, start=start)
            return hist, candidate
        except MarketDataError as e:
            last_error = e
            if market_store.blocked_remaining(YAHOO) > 0:
                break  # source en pause : inutile d'essayer les intervalles suivants
    raise last_error or MarketDataError(f"Aucun historique disponible pour '{ticker}'.")


def get_fx_rate_info(currency: str, allow_stale: bool = False) -> tuple[float, float]:
    """Retourne (taux, heure de récupération) pour `currency` -> EUR.
    `allow_stale` : même principe que get_quote (dernier taux connu si la
    source est indisponible, uniquement si l'appelant l'accepte)."""
    try:
        return _get_live_fx_rate(currency)
    except MarketDataError:
        if allow_stale:
            key = _fx_key(currency)
            entry = market_store.get_last_known([key]).get(key)
            if entry is not None and entry.get("fetched_at") is not None:
                return float(entry["price"]), entry["fetched_at"]
        raise


def _fx_key(currency: str) -> str:
    return f"FX:{currency.upper()}"


def _get_live_fx_rate(currency: str) -> tuple[float, float]:
    currency = currency.upper()
    if currency == "EUR":
        return 1.0, time.time()

    cached = _FX_CACHE.get(currency)
    if cached and (time.time() - cached[1]) < _FX_CACHE_TTL_SECONDS:
        return cached

    error_cached = _FX_ERROR_CACHE.get(currency)
    if error_cached and (time.time() - error_cached[1]) < _FX_ERROR_COOLDOWN_SECONDS:
        diag_log.log("cooldown", "Yahoo", "fx", currency, "individual", 0.0, error_cached[0])
        raise MarketDataError(error_cached[0])

    pair = f"{currency}EUR=X"
    _ensure_yahoo_available("fx", pair)
    started = time.perf_counter()
    try:
        info = yf.Ticker(pair).fast_info
        rate = info.get("last_price") or info.get("lastPrice")
    except Exception as e:
        diag_log.log("error", "Yahoo", "fx", pair, "individual", time.perf_counter() - started, repr(e), True)
        _note_yahoo_error(e)
        message = f"Taux de change {currency}->EUR indisponible ({e})."
        _FX_ERROR_CACHE[currency] = (message, time.time())
        raise MarketDataError(message) from e

    if rate is None:
        diag_log.log("error", "Yahoo", "fx", pair, "individual", time.perf_counter() - started, "missing_rate", True)
        message = f"Taux de change {currency}->EUR indisponible."
        _FX_ERROR_CACHE[currency] = (message, time.time())
        raise MarketDataError(message)

    rate = float(rate)
    _FX_CACHE[currency] = (rate, time.time())
    market_store.remember_prices([{
        "ticker": _fx_key(currency), "price": rate, "currency": "EUR", "fetched_at": _FX_CACHE[currency][1],
    }])
    _FX_ERROR_CACHE.pop(currency, None)
    market_store.record_success(YAHOO)
    diag_log.log("success", "Yahoo", "fx", pair, "individual", time.perf_counter() - started, real_request=True)
    return _FX_CACHE[currency]


def get_fx_rate_to_eur(currency: str, allow_stale: bool = False) -> float:
    """Taux de conversion 1 unité de `currency` -> EUR, avec cache 5 minutes."""
    return get_fx_rate_info(currency, allow_stale=allow_stale)[0]


def convert_to_eur(amount: float, currency: str, allow_stale: bool = False) -> float:
    return amount * get_fx_rate_to_eur(currency, allow_stale=allow_stale)
