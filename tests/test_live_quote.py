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


# -- Crypto via Kraken Ticker (étape 5b) --------------------------------------

from src import kraken_data


class _KrakenResp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class _KrakenApi:
    """Faux endpoint public Ticker : compte les requêtes et répond comme
    Kraken (codes historiques XXBTZUSD, paires récentes SOLUSD)."""

    KNOWN = {"XBTUSD": "XXBTZUSD", "ETHUSD": "XETHZUSD", "SOLUSD": "SOLUSD", "XBTEUR": "XXBTZEUR"}

    def __init__(self, error=None):
        self.requests, self.error = [], error

    def __call__(self, url, params, timeout):
        assert url == kraken_data.TICKER_URL, url
        self.requests.append(params["pair"])
        if self.error:
            return _KrakenResp({"error": [self.error], "result": {}})
        pairs = params["pair"].split(",")
        unknown = [p for p in pairs if p not in self.KNOWN]
        if unknown:
            return _KrakenResp({"error": ["EQuery:Unknown asset pair"], "result": {}})
        return _KrakenResp({"error": [], "result": {
            self.KNOWN[p]: {"c": [str(1000.0 + i), "0.1"], "o": "990.0"} for i, p in enumerate(pairs)
        }})


def _reset_kraken():
    _reset()
    kraken_data._TICKER_CACHE.clear()
    kraken_data._TICKER_ERROR_CACHE.clear()


def test_kraken_symbol_mapping():
    assert kraken_data._to_kraken_pair("BTC-USD") == "XBTUSD"
    assert kraken_data._to_kraken_pair("ETH-EUR") == "ETHEUR"
    assert kraken_data._to_kraken_pair("SOL-USD") == "SOLUSD"
    assert kraken_data._normalize_result_key("XXBTZUSD") == "XBTUSD"
    assert kraken_data._normalize_result_key("XETHZUSD") == "ETHUSD"
    assert kraken_data._normalize_result_key("SOLUSD") == "SOLUSD"
    assert kraken_data.quote_currency("BTC-EUR") == "EUR"
    print("OK: correspondance BTC-USD <-> XBTUSD (réponse XXBTZUSD), devise de cotation")


def test_crypto_display_quote_uses_kraken_ticker_with_30s_cache():
    _reset_kraken()
    api = _KrakenApi()
    with patch.object(kraken_data.requests, "get", api), patch.object(md.yf, "Ticker", _Ticker):
        quote = live_quote.get_display_quote("BTC-USD")
        assert quote["source"] == "kraken" and quote["price"] == 1000.0 and quote["currency"] == "USD", quote
        assert quote["previous_close"] == 990.0 and not quote["stale"]
        assert live_quote.get_display_quote("BTC-USD") is quote  # < 30 s : aucune requête
        cached_at = kraken_data._TICKER_CACHE["BTC-USD"][1]
        with patch.object(kraken_data.time, "time", lambda: cached_at + 31):
            live_quote.get_display_quote("BTC-USD")
    assert api.requests == ["XBTUSD", "XBTUSD"] and _Ticker.calls == 0, (api.requests, _Ticker.calls)
    assert ms.get_last_known(["BTC-USD"])["BTC-USD"]["price"] == 1000.0, "alimente le dernier prix connu"
    print("OK: fiche crypto via Kraken Ticker (1 requête, cache 30 s), plus aucun fast_info Yahoo")


def test_kraken_several_pairs_in_one_request():
    _reset_kraken()
    api = _KrakenApi()
    with patch.object(kraken_data.requests, "get", api):
        quotes = kraken_data.get_ticker_quotes(["BTC-USD", "ETH-USD", "SOL-USD"])
    assert api.requests == ["XBTUSD,ETHUSD,SOLUSD"], api.requests
    assert set(quotes) == {"BTC-USD", "ETH-USD", "SOL-USD"}, quotes
    print("OK: plusieurs paires regroupées en une seule requête Ticker")


def test_unknown_kraken_pair_falls_back_to_yahoo_once_per_hour():
    _reset_kraken()
    api = _KrakenApi()
    with patch.object(kraken_data.requests, "get", api), patch.object(md.yf, "Ticker", _Ticker):
        quote = live_quote.get_display_quote("PEPE24478-USD")
        assert quote["source"] == "yahoo" and _Ticker.calls == 1, quote
        md._QUOTE_CACHE.clear()
        live_quote.get_display_quote("PEPE24478-USD")
    assert api.requests == ["PEPE24478USD"], "paire inconnue : Kraken n'est plus interrogé pendant 1 h"
    assert _Ticker.calls == 2
    print("OK: paire absente de Kraken -> secours Yahoo, sans redemander à Kraken pendant 1 h")


def test_kraken_rate_limit_opens_its_own_circuit():
    _reset_kraken()
    api = _KrakenApi(error="EAPI:Rate limit exceeded")
    with patch.object(kraken_data.requests, "get", api), patch.object(md.yf, "Ticker", _Ticker):
        assert live_quote.get_display_quote("ETH-USD")["source"] == "yahoo"
        kraken_data._TICKER_CACHE.clear()
        md._QUOTE_CACHE.clear()
        live_quote.get_display_quote("ETH-USD")
    assert api.requests == ["ETHUSD"], "Kraken en pause : plus aucune requête Kraken"
    assert ms.blocked_remaining(kraken_data.KRAKEN) > 0 and ms.blocked_remaining(md.YAHOO) == 0
    print("OK: 429 Kraken -> coupe-circuit Kraken seul, secours Yahoo")


if __name__ == "__main__":
    test_cache_durations_by_class()
    test_yahoo_display_quote_reused_for_90_seconds()
    test_concurrent_viewers_share_one_request()
    test_kraken_symbol_mapping()
    test_crypto_display_quote_uses_kraken_ticker_with_30s_cache()
    test_kraken_several_pairs_in_one_request()
    test_unknown_kraken_pair_falls_back_to_yahoo_once_per_hour()
    test_kraken_rate_limit_opens_its_own_circuit()
    print("Tous les tests du prix en direct de la fiche sont passés.")
