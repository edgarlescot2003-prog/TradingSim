"""Tests autonomes du coupe-circuit des APIs de marché (market_store).

Base SQLite temporaire (jamais Supabase), yfinance entièrement mocké : aucun
appel réseau. Exécutable directement : python tests/test_market_circuit.py
"""
import os
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

from src import market_data as md
from src import market_store as ms


class YFRateLimitError(Exception):
    """Même nom que l'exception yfinance (détectée par son nom de classe)."""


class _Ticker:
    """Faux yf.Ticker : compte les appels réseau simulés."""
    calls = 0
    behaviour = "ok"  # "ok" | "429" | "notfound"

    def __init__(self, ticker):
        self.ticker = ticker

    @property
    def fast_info(self):
        type(self).calls += 1
        if self.behaviour == "429":
            raise YFRateLimitError("Too Many Requests. Rate limited. Try after a while.")
        if self.behaviour == "notfound":
            raise KeyError("symbol not found")
        return {"lastPrice": 100.0, "currency": "USD", "previousClose": 99.0, "quoteType": "EQUITY"}


def _fresh_engine():
    path = os.path.join(tempfile.mkdtemp(), "circuit.db")
    return create_engine(f"sqlite:///{path}")


def _reset(engine=None):
    ms.configure((lambda: engine) if engine is not None else None)
    ms._state.clear()
    ms._state_synced_at.clear()
    ms._db_unavailable_until = 0.0
    md._QUOTE_CACHE.clear()
    md._QUOTE_ERROR_CACHE.clear()
    _Ticker.calls = 0
    _Ticker.behaviour = "ok"


def _simulate_other_process():
    """Oublie tout l'état mémoire : seul ce qui est en base subsiste."""
    ms._state.clear()
    ms._state_synced_at.clear()


def test_pause_progression():
    assert [ms.pause_seconds(n) for n in (1, 2, 3, 4, 5, 12)] == [300, 600, 1200, 1800, 1800, 1800]
    print("OK: pause 5 -> 10 -> 20 -> 30 -> 30 min (plafond)")


def test_rate_limit_detection():
    assert ms.is_rate_limit_error(YFRateLimitError("x"))
    assert ms.is_rate_limit_error(RuntimeError("429 Client Error: Too Many Requests for url"))
    assert ms.is_rate_limit_error(["EAPI:Rate limit exceeded"])
    assert not ms.is_rate_limit_error(KeyError("symbol not found"))
    assert not ms.is_rate_limit_error(RuntimeError("Ticker 'X4290' introuvable"))
    print("OK: seul un vrai rate limit déclenche le coupe-circuit")


def test_429_blocks_all_yahoo_calls_and_persists():
    engine = _fresh_engine()
    _reset(engine)
    _Ticker.behaviour = "429"
    with patch.object(md.yf, "Ticker", _Ticker):
        for ticker in ("CL=F", "SOL-USD", "AAPL"):
            try:
                md.get_quote(ticker)
            except md.MarketDataError:
                pass
            else:
                raise AssertionError("erreur attendue")
    assert _Ticker.calls == 1, _Ticker.calls  # un seul appel réel, puis plus rien
    remaining = ms.blocked_remaining(md.YAHOO)
    assert 295 < remaining <= 300, remaining

    _simulate_other_process()  # redémarrage / autre processus : l'état vient de la base
    assert ms.blocked_remaining(md.YAHOO) > 290
    with engine.connect() as conn:
        failures = conn.execute(text("SELECT consecutive_failures FROM api_circuit_state WHERE source='yahoo'")).scalar()
    assert failures == 1
    print("OK: un 429 bloque tous les appels Yahoo, état partagé via la base")


def test_consecutive_429_double_the_pause_and_success_resets():
    engine = _fresh_engine()
    _reset(engine)
    for expected in (300, 600, 1200, 1800, 1800):
        ms.record_rate_limit(md.YAHOO, YFRateLimitError("x"))
        remaining = ms.blocked_remaining(md.YAHOO)
        assert expected - 5 < remaining <= expected, (expected, remaining)

    # Fin de pause simulée : le prochain appel est autorisé et réussit.
    ms._state[md.YAHOO]["blocked_until"] = time.time() - 1
    ms._state_synced_at[md.YAHOO] = time.time()
    with patch.object(md.yf, "Ticker", _Ticker):
        md.get_quote("AAPL")
    assert ms.blocked_remaining(md.YAHOO) == 0
    _simulate_other_process()
    ms.blocked_remaining(md.YAHOO)
    assert ms._state[md.YAHOO]["failures"] == 0
    print("OK: 5 -> 10 -> 20 -> 30 -> 30 min, remise à zéro dès un succès")


def test_not_found_does_not_block_source():
    _reset(_fresh_engine())
    _Ticker.behaviour = "notfound"
    with patch.object(md.yf, "Ticker", _Ticker):
        try:
            md.get_quote("NOPE")
        except md.MarketDataError:
            pass
        _Ticker.behaviour = "ok"
        md.get_quote("AAPL")  # autre ticker : pas bloqué
    assert ms.blocked_remaining(md.YAHOO) == 0
    assert _Ticker.calls == 2
    print("OK: un ticker introuvable ne bloque pas toute la source")


def test_database_down_falls_back_to_memory():
    def broken_engine():
        raise RuntimeError("connection refused")

    _reset()
    ms.configure(broken_engine)
    _Ticker.behaviour = "429"
    with patch.object(md.yf, "Ticker", _Ticker):
        for _ in range(3):
            try:
                md.get_quote("CL=F")
            except md.MarketDataError:
                pass
    assert _Ticker.calls == 1
    assert ms.blocked_remaining(md.YAHOO) > 290
    print("OK: base injoignable -> coupe-circuit en mémoire, aucun plantage")


def test_missing_table_is_created():
    engine = _fresh_engine()  # base vierge, aucune table
    _reset(engine)
    ms.record_rate_limit("kraken", RuntimeError("EAPI:Rate limit exceeded"))
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM api_circuit_state")).scalar() == 1
    print("OK: table absente créée automatiquement (CREATE TABLE IF NOT EXISTS)")


def test_kraken_circuit():
    from src import kraken_data

    _reset(_fresh_engine())

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"error": ["EAPI:Rate limit exceeded"]}

    calls = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        return _Resp()

    kraken_data._ERROR_CACHE.clear()
    with patch.object(kraken_data.requests, "get", fake_get):
        for _ in range(3):
            try:
                kraken_data._fetch_page("XBTUSD", 5, 0)
            except md.MarketDataError:
                pass
    assert len(calls) == 1
    assert ms.blocked_remaining("kraken") > 290
    assert ms.blocked_remaining(md.YAHOO) == 0  # sources indépendantes
    print("OK: Kraken a son propre coupe-circuit, indépendant de Yahoo")


if __name__ == "__main__":
    test_pause_progression()
    test_rate_limit_detection()
    test_429_blocks_all_yahoo_calls_and_persists()
    test_consecutive_429_double_the_pause_and_success_resets()
    test_not_found_does_not_block_source()
    test_database_down_falls_back_to_memory()
    test_missing_table_is_created()
    test_kraken_circuit()
    print("Tous les tests du coupe-circuit sont passés.")
