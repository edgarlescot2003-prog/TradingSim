"""Accès aux données de marché (prix, historique, recherche, taux de change).

Source : Yahoo Finance via la librairie yfinance. Couvre actions, ETF, indices
et les principales paires crypto (ex : BTC-USD), ce qui suffit pour la Phase 1.
Une source dédiée (Kraken/ccxt) pourra être ajoutée plus tard si une couverture
crypto plus fine est nécessaire.
"""

import time

import pandas as pd
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


MAX_EXECUTION_PRICE_AGE_SECONDS = 5 * 60


def is_fresh(fetched_at: float, now: float | None = None) -> bool:
    """Vrai si un prix est assez récent pour une décision d'exécution.

    Cinq minutes est un compromis : deux minutes bloqueraient trop souvent
    sur le simple retard d'une API, tandis que dix minutes augmente trop le
    risque d'exécuter un ordre sur un marché déjà déplacé. Ce seuil ne rend
    jamais un prix périmé utilisable pour l'affichage : il sert uniquement
    aux décisions d'ordre, TP/SL et liquidation.
    """
    current_time = time.time() if now is None else now
    return current_time - fetched_at <= MAX_EXECUTION_PRICE_AGE_SECONDS


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


def get_quotes_batch(tickers: tuple[str, ...]) -> dict[str, dict]:
    """Récupère les prix et variations en un seul téléchargement Yahoo."""
    if not tickers or market_store.blocked_remaining(YAHOO) > 0:
        return {}
    started = time.perf_counter()
    try:
        data = yf.download(
            tickers=list(tickers), period="1mo", interval="1d", group_by="ticker",
            auto_adjust=False, threads=False, progress=False,
        )
    except Exception as error:
        diag_log.log("error", "Yahoo", "download", ",".join(tickers), "batch", time.perf_counter() - started, repr(error), True)
        _note_yahoo_error(error)
        return {}
    # yf.download avale les erreurs par ticker (dont les 429) dans shared._ERRORS.
    rate_limited = [e for e in getattr(yf.shared, "_ERRORS", {}).values() if market_store.is_rate_limit_error(e)]
    if rate_limited:
        _note_yahoo_error(RuntimeError(rate_limited[0]))
    if data is None or data.empty:
        diag_log.log("empty", "Yahoo", "download", ",".join(tickers), "batch", time.perf_counter() - started, real_request=True)
        return {}

    result = {}
    for ticker in tickers:
        try:
            closes = data[ticker]["Close"] if isinstance(data.columns, pd.MultiIndex) else data["Close"]
            closes = closes.dropna()
            if closes.empty:
                continue
            price = float(closes.iloc[-1])
            previous_close = float(closes.iloc[-2]) if len(closes) >= 2 else None
        except (KeyError, TypeError, ValueError):
            continue
        currency = "pts" if ticker.startswith("^") else {
            "USDJPY=X": "JPY", "USDCHF=X": "CHF",
        }.get(ticker, "USD")
        change_30d_pct = (
            (price - float(closes.iloc[0])) / float(closes.iloc[0]) * 100
            if len(closes) >= 2 and closes.iloc[0]
            else None
        )
        result[ticker] = {
            "price": price, "currency": currency,
            "previous_close": previous_close, "change_pct": (
                (price - previous_close) / previous_close * 100
                if previous_close else None
            ),
            "change_30d_pct": change_30d_pct,
        }
    diag_log.log("success", "Yahoo", "download", ",".join(tickers), "batch", time.perf_counter() - started, real_request=True)
    return result


def get_quote(ticker: str) -> dict:
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
        info = yf.Ticker(ticker).fast_info
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
    quote = {
        "price": float(price),
        "currency": currency,
        "previous_close": float(previous_close) if previous_close is not None else None,
        "quote_type": quote_type,
        "fetched_at": fetched_at,
    }
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


def get_fx_rate_info(currency: str) -> tuple[float, float]:
    """Retourne (taux, heure de récupération) pour `currency` -> EUR."""
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
    _FX_ERROR_CACHE.pop(currency, None)
    market_store.record_success(YAHOO)
    diag_log.log("success", "Yahoo", "fx", pair, "individual", time.perf_counter() - started, real_request=True)
    return _FX_CACHE[currency]


def get_fx_rate_to_eur(currency: str) -> float:
    """Taux de conversion 1 unité de `currency` -> EUR, avec cache 5 minutes."""
    return get_fx_rate_info(currency)[0]


def convert_to_eur(amount: float, currency: str) -> float:
    return amount * get_fx_rate_to_eur(currency)
