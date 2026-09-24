"""Tests autonomes du batch de l'accueil Trading (market_data.get_quotes_batch).

Base SQLite temporaire, yfinance mocké : aucun appel réseau, jamais Supabase.
Exécutable directement : python tests/test_quotes_batch.py
"""
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from sqlalchemy import create_engine

from src import market_data as md
from src import market_store as ms


class YFRateLimitError(Exception):
    pass


class _History:
    def __init__(self, meta):
        self._history_metadata = meta


class _Ticker:
    calls: list = []
    rate_limited_after = None  # nombre d'appels réussis avant un 429
    currencies = {"MC.PA": "EUR", "USDJPY=X": "JPY", "EURGBP=X": "GBP"}

    def __init__(self, ticker):
        self.ticker = ticker
        self._price_history = None

    def history(self, period, interval):
        type(self).calls.append(self.ticker)
        if self.rate_limited_after is not None and len(self.calls) > self.rate_limited_after:
            raise YFRateLimitError("Too Many Requests. Rate limited. Try after a while.")
        now = datetime.now(timezone.utc)
        index = pd.DatetimeIndex([now - timedelta(days=d) for d in (30, 1, 0)])
        self._price_history = _History({
            "currency": self.currencies.get(self.ticker, "USD"), "instrumentType": "EQUITY",
            "regularMarketTime": time.time() - 60,
        })
        return pd.DataFrame({"Close": [80.0, 95.0, 100.0]}, index=index)


def _reset():
    engine = create_engine(f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'b.db')}")
    ms.configure(lambda: engine)
    for d in (ms._state, ms._state_synced_at, ms._known_memory, ms._known_written_at, ms._known_db_read):
        d.clear()
    ms._db_unavailable_until = 0.0
    _Ticker.calls = []
    _Ticker.rate_limited_after = None


def test_all_stale_fetches_everything_with_real_currency():
    _reset()
    with patch.object(md.yf, "Ticker", _Ticker):
        result = md.get_quotes_batch(("AAPL", "MC.PA", "USDJPY=X", "EURGBP=X"))
    assert _Ticker.calls == ["AAPL", "MC.PA", "USDJPY=X", "EURGBP=X"]
    assert result["MC.PA"]["currency"] == "EUR" and result["EURGBP=X"]["currency"] == "GBP"
    assert round(result["AAPL"]["change_pct"], 2) == 5.26 and result["AAPL"]["change_30d_pct"] == 25.0
    assert not any(q["stale"] for q in result.values())
    print("OK: tout périmé -> 1 requête par actif, devise réelle (plus de table en dur)")


def test_partial_reuses_recent_prices_from_database():
    _reset()
    with patch.object(md.yf, "Ticker", _Ticker):
        md.get_quotes_batch(("AAPL", "MC.PA"))
        # Autre processus / redémarrage : mémoire vidée, la base subsiste.
        ms._known_memory.clear()
        ms._known_db_read.clear()
        _Ticker.calls = []
        result = md.get_quotes_batch(("AAPL", "MC.PA", "NVDA"))
    assert _Ticker.calls == ["NVDA"], _Ticker.calls  # seuls les actifs absents/périmés
    assert set(result) == {"AAPL", "MC.PA", "NVDA"}
    print("OK: batch partiel -> seuls les actifs périmés sont redemandés à Yahoo")


def test_paused_source_makes_no_call_and_flags_stale():
    _reset()
    with patch.object(md.yf, "Ticker", _Ticker):
        md.get_quotes_batch(("AAPL",))
    ms._known_memory["AAPL"]["fetched_at"] -= 3600  # vieux d'une heure
    ms.record_rate_limit(md.YAHOO, YFRateLimitError("x"))
    _Ticker.calls = []
    with patch.object(md.yf, "Ticker", _Ticker):
        result = md.get_quotes_batch(("AAPL", "NVDA"))
    assert _Ticker.calls == []
    assert result["AAPL"]["stale"] is True and "NVDA" not in result
    print("OK: source en pause -> aucun appel, derniers prix connus marqués datés")


def test_stops_at_first_429():
    _reset()
    _Ticker.rate_limited_after = 2
    tickers = tuple(f"T{i}" for i in range(29))
    with patch.object(md.yf, "Ticker", _Ticker):
        result = md.get_quotes_batch(tickers)
    assert len(_Ticker.calls) == 3, len(_Ticker.calls)  # 2 succès + le 429, puis arrêt net
    assert len(result) == 2
    assert ms.blocked_remaining(md.YAHOO) > 290
    print("OK: arrêt net au premier 429 (3 requêtes au lieu de 29)")


if __name__ == "__main__":
    test_all_stale_fetches_everything_with_real_currency()
    test_partial_reuses_recent_prices_from_database()
    test_paused_source_makes_no_call_and_flags_stale()
    test_stops_at_first_429()
    print("Tous les tests du batch d'accueil sont passés.")
