"""Historique de prix crypto via l'API publique de Kraken.

Constat vérifié empiriquement : l'endpoint public /OHLC de Kraken plafonne à
~720 bougies les PLUS RÉCENTES par paire/intervalle, quel que soit `since` —
demander un historique plus profond que ce plafond ne remonte pas plus loin
dans le passé (`since` ne fait qu'affiner tant que la fenêtre implicite tient
dans ces ~720 bougies). Il n'existe donc pas de vraie pagination vers le passé
sur cet endpoint gratuit, contrairement à Yahoo dont la limite dépend
seulement de l'intervalle : au-delà, on utilise le même principe de repli que
market_data.get_history_with_fallback (intervalle immédiatement moins précis)
plutôt que de prétendre couvrir une plage qu'on ne peut pas obtenir. La
boucle de pagination ci-dessous reste utile pour rattraper le présent quand
un premier appel ne l'atteint pas encore.
"""

import threading
import time
from datetime import datetime, timezone

import pandas as pd
import requests

from .market_data import MarketDataError
from . import diag_log, market_store

# Même coupe-circuit que Yahoo (voir market_store.py) : le chargement d'un
# graphique crypto peut enchaîner jusqu'à 20 pages par intervalle et
# plusieurs intervalles en cas d'échec — risque de rafale comparable.
KRAKEN = "kraken"

OHLC_URL = "https://api.kraken.com/0/public/OHLC"

# (intervalle en minutes, plafond approximatif de couverture en jours pour un
# appel = ~720 bougies) — du plus fin au plus grossier.
_INTERVAL_LADDER = [
    ("1m", 1), ("5m", 5), ("15m", 15), ("30m", 30),
    ("1h", 60), ("4h", 240), ("1d", 1440), ("1w", 10080),
]
_MINUTES_BY_LABEL = dict(_INTERVAL_LADDER)

# Kraken utilise des codes d'actifs historiques irréguliers (XBT pour BTC...).
_SYMBOL_OVERRIDES = {"BTC": "XBT"}
_ERROR_CACHE: dict[tuple[str, int], tuple[str, float]] = {}
_ERROR_COOLDOWN_SECONDS = 30


def _to_kraken_pair(yf_ticker: str) -> str:
    base, _, quote = yf_ticker.partition("-")
    base = _SYMBOL_OVERRIDES.get(base.upper(), base.upper())
    return f"{base}{quote.upper() or 'USD'}"


def _fetch_page(pair: str, minutes: int, since: int) -> tuple[list, int | None]:
    remaining = market_store.blocked_remaining(KRAKEN)
    if remaining > 0:
        diag_log.log("circuit_open", "Kraken", "OHLC", pair, "individual", 0.0)
        raise MarketDataError(
            f"API Kraken en pause (limite de requêtes atteinte) : reprise dans {max(1, round(remaining / 60))} min."
        )

    error_key = (pair, minutes)
    error_cached = _ERROR_CACHE.get(error_key)
    if error_cached and (time.time() - error_cached[1]) < _ERROR_COOLDOWN_SECONDS:
        diag_log.log("cooldown", "Kraken", "OHLC", pair, "individual", 0.0, error_cached[0])
        raise MarketDataError(error_cached[0])

    started = time.perf_counter()
    try:
        resp = requests.get(OHLC_URL, params={"pair": pair, "interval": minutes, "since": since}, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        diag_log.log("error", "Kraken", "OHLC", pair, "individual", time.perf_counter() - started, repr(e), True)
        if market_store.is_rate_limit_error(e):
            market_store.record_rate_limit(KRAKEN, e)
        message = f"API Kraken indisponible pour '{pair}' : {e}"
        _ERROR_CACHE[error_key] = (message, time.time())
        raise MarketDataError(message) from e

    if payload.get("error"):
        diag_log.log("error", "Kraken", "OHLC", pair, "individual", time.perf_counter() - started, repr(payload["error"]), True)
        if market_store.is_rate_limit_error(payload["error"]):
            market_store.record_rate_limit(KRAKEN, payload["error"])
        message = f"Kraken a refusé la requête pour '{pair}' : {payload['error']}"
        _ERROR_CACHE[error_key] = (message, time.time())
        raise MarketDataError(message)

    result = payload.get("result", {})
    candles = next((v for k, v in result.items() if k != "last"), None)
    _ERROR_CACHE.pop(error_key, None)
    market_store.record_success(KRAKEN)
    diag_log.log("success", "Kraken", "OHLC", pair, "individual", time.perf_counter() - started, real_request=True)
    return candles or [], result.get("last")


def _fetch_interval(pair: str, minutes: int, since_ts: int) -> pd.DataFrame:
    """Récupère l'historique depuis `since_ts`, en re-paginant tant que la
    page reçue avance réellement (utile quand un premier appel n'atteint pas
    encore le présent) ; s'arrête dès qu'il n'y a plus de progrès, ce qui est
    le cas dès que le plafond des ~720 bougies les plus récentes est atteint.
    """
    all_candles = []
    since = since_ts
    seen = set()
    for _ in range(20):
        candles, last = _fetch_page(pair, minutes, since)
        if not candles:
            break
        all_candles.extend(candles)
        if last is None or last in seen or last <= since:
            break
        seen.add(last)
        since = last
        if candles[-1][0] >= time.time() - minutes * 60:
            break

    if not all_candles:
        raise MarketDataError(f"Aucun historique Kraken disponible pour '{pair}'.")

    df = pd.DataFrame(all_candles, columns=["time", "Open", "High", "Low", "Close", "vwap", "Volume", "count"])
    df = df.drop_duplicates(subset="time").sort_values("time")
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    for col in ("Open", "High", "Low", "Close"):
        df[col] = df[col].astype(float)
    return df.set_index("time")[["Open", "High", "Low", "Close"]]


# -- Prix en direct (endpoint public Ticker) ----------------------------------------
#
# Fiche actif crypto : UNE requête Ticker (plusieurs paires possibles, séparées
# par des virgules) au lieu d'un fast_info Yahoo (~3 requêtes internes).
# Champs utilisés : c[0] = dernier prix échangé, o = prix d'ouverture du jour
# (00:00 UTC, équivalent de la clôture de la veille utilisée par Yahoo pour
# une crypto). Kraken ne renvoie pas d'heure de cotation : market_time=None.

TICKER_URL = "https://api.kraken.com/0/public/Ticker"
_TICKER_CACHE: dict[str, tuple[dict, float]] = {}
_TICKER_ERROR_CACHE: dict[str, tuple[str, float]] = {}
_UNKNOWN_PAIR_COOLDOWN_SECONDS = 3600  # paire absente de Kraken : pas la peine de redemander avant 1 h
_TICKER_LOCK = threading.Lock()


def _normalize_result_key(key: str) -> str:
    """Kraken répond avec ses codes historiques pour les anciennes paires
    (XXBTZUSD pour la paire demandée XBTUSD, XETHZUSD pour ETHUSD) : retire
    les préfixes X/Z de ce format à 8 caractères pour retrouver la paire."""
    if len(key) == 8 and key[0] in "XZ" and key[4] in "XZ":
        return key[1:4] + key[5:]
    return key


def get_ticker_quotes(yf_tickers, max_age: float = 30) -> dict[str, dict]:
    """Prix en direct de plusieurs cryptos (tickers au format Yahoo, ex.
    BTC-USD) en UNE requête. Même format que market_data.get_quote
    (source="kraken"). Prix de moins de `max_age` s réutilisés sans
    requête. Tickers absents de Kraken : absents du résultat. Lève
    MarketDataError si la source est en pause ou indisponible."""
    tickers = list(dict.fromkeys(yf_tickers))
    now = time.time()
    result: dict[str, dict] = {}
    with _TICKER_LOCK:  # rafraîchissement mutualisé entre sessions
        to_fetch = []
        for ticker in tickers:
            cached = _TICKER_CACHE.get(ticker)
            if cached and now - cached[1] < max_age:
                diag_log.log("cache_hit", "Kraken", "Ticker", ticker, "individual", 0.0)
                result[ticker] = cached[0]
                continue
            error = _TICKER_ERROR_CACHE.get(ticker)
            if error and now < error[1]:
                diag_log.log("cooldown", "Kraken", "Ticker", ticker, "individual", 0.0, error[0])
                continue
            to_fetch.append(ticker)
        if not to_fetch:
            return result
        remaining = market_store.blocked_remaining(KRAKEN)
        if remaining > 0:
            diag_log.log("circuit_open", "Kraken", "Ticker", ",".join(to_fetch), "individual", 0.0)
            raise MarketDataError(
                f"API Kraken en pause (limite de requêtes atteinte) : reprise dans {max(1, round(remaining / 60))} min."
            )
        pairs = {_to_kraken_pair(t): t for t in to_fetch}
        label = ",".join(pairs)
        started = time.perf_counter()
        try:
            resp = requests.get(TICKER_URL, params={"pair": label}, timeout=10)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            diag_log.log("error", "Kraken", "Ticker", label, "individual", time.perf_counter() - started, repr(e), True)
            if market_store.is_rate_limit_error(e):
                market_store.record_rate_limit(KRAKEN, e)
            raise MarketDataError(f"API Kraken indisponible pour '{label}' : {e}") from e
        errors = payload.get("error") or []
        if errors:
            diag_log.log("error", "Kraken", "Ticker", label, "individual", time.perf_counter() - started,
                         repr(errors), True)
            if market_store.is_rate_limit_error(errors):
                market_store.record_rate_limit(KRAKEN, errors)
            elif any("Unknown asset pair" in str(e) for e in errors) and len(to_fetch) == 1:
                _TICKER_ERROR_CACHE[to_fetch[0]] = (str(errors), now + _UNKNOWN_PAIR_COOLDOWN_SECONDS)
            raise MarketDataError(f"Kraken a refusé la requête pour '{label}' : {errors}")

        data_by_key = payload.get("result") or {}
        fetched_at = time.time()
        fresh = []
        for key, data in data_by_key.items():
            ticker = pairs.get(key) or pairs.get(_normalize_result_key(key))
            if ticker is None and len(pairs) == 1 and len(data_by_key) == 1:
                ticker = next(iter(pairs.values()))  # une seule paire demandée, une seule reçue
            try:
                price = float(data["c"][0])
                opening = float(data["o"])
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            if ticker is None or not price > 0:
                continue
            quote = {
                "price": price, "currency": quote_currency(ticker),
                "previous_close": opening if opening > 0 else None, "quote_type": "CRYPTOCURRENCY",
                "fetched_at": fetched_at, "market_time": None, "market_open": True,
                "stale": False, "source": "kraken",
            }
            _TICKER_CACHE[ticker] = (quote, fetched_at)
            _TICKER_ERROR_CACHE.pop(ticker, None)
            result[ticker] = quote
            fresh.append({"ticker": ticker, **quote})
        market_store.record_success(KRAKEN)
        diag_log.log("success", "Kraken", "Ticker", label, "individual", time.perf_counter() - started,
                     real_request=True)
    market_store.remember_prices(fresh)
    return result


def get_ticker_quote(yf_ticker: str, max_age: float = 30) -> dict:
    """Prix en direct d'une crypto (voir get_ticker_quotes) ; lève
    MarketDataError si la paire est absente de Kraken ou la source
    indisponible."""
    quote = get_ticker_quotes([yf_ticker], max_age=max_age).get(yf_ticker)
    if quote is None:
        raise MarketDataError(f"Paire '{_to_kraken_pair(yf_ticker)}' absente de Kraken.")
    return quote


def quote_currency(yf_ticker: str) -> str:
    """Devise de cotation d'une paire crypto au format Yahoo (BTC-USD -> USD)."""
    return (yf_ticker.partition("-")[2] or "USD").upper()


def get_daily_closes(yf_ticker: str, days: int = 70) -> dict:
    """UNE requête Kraken OHLC en bougies quotidiennes (prix indicatifs des
    pages de liste, daily_snapshot.py). Même format que
    market_data.get_daily_closes : {"candles": [(date UTC, clôture)],
    "currency", "today"}. La dernière bougie Kraken est celle du jour en
    cours (non close) : c'est à l'appelant de ne garder que la veille."""
    pair = _to_kraken_pair(yf_ticker)
    candles, _ = _fetch_page(pair, 1440, int(time.time()) - days * 86400)
    if not candles:
        raise MarketDataError(f"Aucune bougie quotidienne Kraken pour '{pair}'.")
    parsed = [
        (datetime.fromtimestamp(int(c[0]), tz=timezone.utc).date(), float(c[4])) for c in candles
    ]
    return {"candles": sorted(parsed), "currency": quote_currency(yf_ticker),
            "today": datetime.now(timezone.utc).date()}


def get_history_with_fallback(yf_ticker: str, interval: str, start) -> tuple:
    """Équivalent Kraken de market_data.get_history_with_fallback : essaie
    l'intervalle demandé, et se rabat sur le suivant dans l'échelle tant que
    la couverture obtenue ne remonte pas suffisamment près de `start`
    (conséquence du plafond documenté ci-dessus). Retourne
    (DataFrame, intervalle_effectivement_utilisé).
    """
    pair = _to_kraken_pair(yf_ticker)
    since_ts = int(start.timestamp()) if hasattr(start, "timestamp") else int(start)

    try:
        start_idx = [label for label, _ in _INTERVAL_LADDER].index(interval)
    except ValueError:
        start_idx = 0

    last_error = None
    for label, minutes in _INTERVAL_LADDER[start_idx:]:
        try:
            df = _fetch_interval(pair, minutes, since_ts)
        except MarketDataError as e:
            last_error = e
            if market_store.blocked_remaining(KRAKEN) > 0:
                break  # source en pause : inutile d'essayer les intervalles suivants
            continue

        start_dt = start if isinstance(start, datetime) else datetime.fromtimestamp(since_ts, tz=timezone.utc)
        required_span = datetime.now(timezone.utc) - start_dt
        actual_span = df.index.max().to_pydatetime() - df.index.min().to_pydatetime()
        # Tolérance relative (90 %) plutôt qu'un nombre de jours fixe : sur une
        # période courte (1 jour), une marge absolue d'un jour laisserait
        # passer une couverture deux fois trop courte sans le détecter.
        covers_request = required_span.total_seconds() <= 0 or actual_span >= required_span * 0.9

        if covers_request or (label, minutes) == _INTERVAL_LADDER[-1]:
            return df, label
        last_error = MarketDataError(
            f"Couverture insuffisante à {label} pour '{pair}' (plafond Kraken atteint)."
        )

    raise last_error or MarketDataError(f"Aucun historique Kraken disponible pour '{pair}'.")
