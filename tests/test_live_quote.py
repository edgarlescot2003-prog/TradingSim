"""Tests autonomes du prix en direct de la fiche actif (live_quote) : durée de
cache par classe, rafraîchissement mutualisé.

yfinance/Kraken entièrement simulés, toute connexion socket piégée, base de
données non configurée (repli mémoire) : jamais de réseau, jamais Supabase.
Exécutable directement : python tests/test_live_quote.py
"""
import os
import socket
import sys
import threading
import time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "postgresql://blocked:blocked@127.0.0.1:1/blocked"

from src import live_quote, market_data as md, market_store as ms


def _no_network(*args, **kwargs):
    raise AssertionError("APPEL RÉSEAU INTERDIT dans ce test")


patch.object(socket.socket, "connect", _no_network).start()
patch.object(socket, "create_connection", _no_network).start()


class _Ticker:
    """Faux yf.Ticker : compte les requêtes fast_info simulées."""
    calls = 0
    delay = 0.0

    def __init__(self, ticker):
        self.ticker = ticker

    @property
    def fast_info(self):
        type(self).calls += 1
        time.sleep(self.delay)
        return {"lastPrice": 100.0 + type(self).calls, "currency": "USD", "previousClose": 99.0,
                "quoteType": "EQUITY"}


def _reset():
    ms.configure(None)
    for d in (ms._state, ms._state_synced_at, ms._known_memory, ms._known_written_at, ms._known_db_read,
              md._QUOTE_CACHE, md._QUOTE_ERROR_CACHE):
        d.clear()
    _Ticker.calls = 0
    _Ticker.delay = 0.0


def test_cache_durations_by_class():
    assert live_quote.PRICE_CACHE_SECONDS == {"yahoo": 90, "kraken": 30}
    for ticker, quote_type in (("AAPL", ""), ("MC.PA", "EQUITY"), ("GC=F", ""), ("EURUSD=X", ""), ("TLT", "ETF")):
        assert live_quote.live_source(ticker, quote_type) == "yahoo", ticker
        assert live_quote.price_cache_seconds(ticker, quote_type) == 90, ticker
    for ticker, quote_type in (("BTC-USD", ""), ("ETH-EUR", ""), ("DOGE-USD", "CRYPTOCURRENCY")):
        assert live_quote.live_source(ticker, quote_type) == "kraken", ticker
        assert live_quote.price_cache_seconds(ticker, quote_type) == 30, ticker
    print("OK: cache 90 s Yahoo (actions, matières premières, forex, ETF obligataires), 30 s Kraken (crypto)")


def test_yahoo_display_quote_reused_for_90_seconds():
    _reset()
    with patch.object(md.yf, "Ticker", _Ticker):
        first = live_quote.get_display_quote("AAPL")
        cached_at = md._QUOTE_CACHE["AAPL"][1]
        with patch.object(md.time, "time", lambda: cached_at + 89):
            assert live_quote.get_display_quote("AAPL") is first and _Ticker.calls == 1
            # Le reste de l'app (Portefeuille...) garde son propre délai de 30 s.
            md.get_quote("AAPL")
            assert _Ticker.calls == 2
        with patch.object(md.time, "time", lambda: md._QUOTE_CACHE["AAPL"][1] + 91):
            live_quote.get_display_quote("AAPL")
            assert _Ticker.calls == 3
    print("OK: prix de la fiche réutilisé 90 s (Yahoo), nouvelle requête au-delà")


def test_concurrent_viewers_share_one_request():
    _reset()
    _Ticker.delay = 0.2
    results = []
    barrier = threading.Barrier(10)

    def viewer():
        barrier.wait()
        results.append(live_quote.get_display_quote("NVDA")["price"])

    with patch.object(md.yf, "Ticker", _Ticker):
        threads = [threading.Thread(target=viewer) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert _Ticker.calls == 1 and len(set(results)) == 1 and len(results) == 10, (_Ticker.calls, results)
    print("OK: 10 participants simultanés sur la même fiche -> 1 seule requête")


if __name__ == "__main__":
    test_cache_durations_by_class()
    test_yahoo_display_quote_reused_for_90_seconds()
    test_concurrent_viewers_share_one_request()
    print("Tous les tests du prix en direct de la fiche sont passés.")
