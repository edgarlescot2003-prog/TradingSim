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

import time
from datetime import datetime, timezone

import pandas as pd
import requests

from .market_data import MarketDataError

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


def _to_kraken_pair(yf_ticker: str) -> str:
    base, _, quote = yf_ticker.partition("-")
    base = _SYMBOL_OVERRIDES.get(base.upper(), base.upper())
    return f"{base}{quote.upper() or 'USD'}"


def _fetch_page(pair: str, minutes: int, since: int) -> tuple[list, int | None]:
    try:
        resp = requests.get(OHLC_URL, params={"pair": pair, "interval": minutes, "since": since}, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        raise MarketDataError(f"API Kraken indisponible pour '{pair}' : {e}") from e

    if payload.get("error"):
        raise MarketDataError(f"Kraken a refusé la requête pour '{pair}' : {payload['error']}")

    result = payload.get("result", {})
    candles = next((v for k, v in result.items() if k != "last"), None)
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
