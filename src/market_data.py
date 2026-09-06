"""Accès aux données de marché (prix, historique, recherche, taux de change).

Source : Yahoo Finance via la librairie yfinance. Couvre actions, ETF, indices
et les principales paires crypto (ex : BTC-USD), ce qui suffit pour la Phase 1.
Une source dédiée (Kraken/ccxt) pourra être ajoutée plus tard si une couverture
crypto plus fine est nécessaire.
"""

import time

import yfinance as yf


class MarketDataError(Exception):
    """Erreur métier lisible, à afficher telle quelle à l'utilisateur."""


_FX_CACHE: dict[str, tuple[float, float]] = {}
_FX_CACHE_TTL_SECONDS = 300

# Cache court sur le prix courant : la revalorisation du Portefeuille (et du
# Classement) refait cet appel à chaque interaction, sans aucun cache
# jusqu'ici — un enchaînement rapide de clics pouvait donc envoyer une rafale
# de requêtes sur le même ticker et déclencher le rate-limit "Too Many
# Requests" de l'API gratuite de Yahoo. 20s reste largement assez frais pour
# un prix qui n'est de toute façon pas temps réel (voir get_quote).
_QUOTE_CACHE: dict[str, tuple[dict, float]] = {}
_QUOTE_CACHE_TTL_SECONDS = 20


def search_assets(query: str, max_results: int = 8) -> list[dict]:
    """Recherche des actifs par nom ou ticker. Retourne une liste de dicts
    {symbol, name, exchange, type}, éventuellement vide si rien ne correspond.
    """
    query = (query or "").strip()
    if not query:
        return []
    try:
        results = yf.Search(query, max_results=max_results)
    except Exception as e:
        raise MarketDataError(
            f"Recherche impossible pour '{query}' (API indisponible : {e})."
        ) from e

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
        return cached[0]

    try:
        info = yf.Ticker(ticker).fast_info
        price = info.get("last_price") or info.get("lastPrice")
        currency = info.get("currency")
        previous_close = info.get("previous_close") or info.get("previousClose")
        quote_type = info.get("quote_type") or info.get("quoteType") or ""
    except Exception as e:
        raise MarketDataError(f"Ticker '{ticker}' introuvable ou API indisponible ({e}).") from e

    if price is None or currency is None:
        raise MarketDataError(f"Aucune donnée de prix disponible pour '{ticker}'.")
    quote = {
        "price": float(price),
        "currency": currency,
        "previous_close": float(previous_close) if previous_close is not None else None,
        "quote_type": quote_type,
    }
    _QUOTE_CACHE[ticker] = (quote, time.time())
    return quote


def get_history(ticker: str, period: str = "6mo", interval: str = "1d", start=None):
    """Retourne un DataFrame OHLC (colonnes Open/High/Low/Close) ou lève MarketDataError.

    Si `start` est fourni (date ou Timestamp), il prime sur `period`.
    """
    try:
        if start is not None:
            hist = yf.Ticker(ticker).history(start=start, interval=interval)
        else:
            hist = yf.Ticker(ticker).history(period=period, interval=interval)
    except Exception as e:
        raise MarketDataError(f"Historique indisponible pour '{ticker}' ({e}).") from e

    if hist is None or hist.empty:
        raise MarketDataError(f"Aucun historique disponible pour '{ticker}'.")
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
    raise last_error or MarketDataError(f"Aucun historique disponible pour '{ticker}'.")


def get_fx_rate_to_eur(currency: str) -> float:
    """Taux de conversion 1 unité de `currency` -> EUR, avec cache 5 minutes."""
    currency = currency.upper()
    if currency == "EUR":
        return 1.0

    cached = _FX_CACHE.get(currency)
    if cached and (time.time() - cached[1]) < _FX_CACHE_TTL_SECONDS:
        return cached[0]

    pair = f"{currency}EUR=X"
    try:
        info = yf.Ticker(pair).fast_info
        rate = info.get("last_price") or info.get("lastPrice")
    except Exception as e:
        raise MarketDataError(f"Taux de change {currency}->EUR indisponible ({e}).") from e

    if rate is None:
        raise MarketDataError(f"Taux de change {currency}->EUR indisponible.")

    rate = float(rate)
    _FX_CACHE[currency] = (rate, time.time())
    return rate


def convert_to_eur(amount: float, currency: str) -> float:
    return amount * get_fx_rate_to_eur(currency)
