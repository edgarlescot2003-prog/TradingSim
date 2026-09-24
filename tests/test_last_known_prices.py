"""Tests autonomes du dernier prix connu (market_store.remember_prices /
get_last_known) et du repli `allow_stale` de market_data.

Base SQLite temporaire, yfinance mocké : aucun appel réseau, jamais Supabase.
Exécutable directement : python tests/test_last_known_prices.py
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
    pass


class _Ticker:
    calls = 0
    behaviour = "ok"
    prices = {"AAPL": (200.0, "USD"), "MC.PA": (400.0, "EUR"), "USDEUR=X": (0.9, "EUR")}

    def __init__(self, ticker):
        self.ticker = ticker

    @property
    def fast_info(self):
        type(self).calls += 1
        if self.behaviour == "429":
            raise YFRateLimitError("Too Many Requests. Rate limited. Try after a while.")
        price, currency = self.prices[self.ticker]
        return {"lastPrice": price, "currency": currency, "previousClose": price * 0.99, "quoteType": "EQUITY"}


def _reset():
    path = os.path.join(tempfile.mkdtemp(), "known.db")
    engine = create_engine(f"sqlite:///{path}")
    ms.configure(lambda: engine)
    for d in (ms._state, ms._state_synced_at, ms._known_memory, ms._known_written_at, ms._known_db_read):
        d.clear()
    ms._db_unavailable_until = 0.0
    for d in (md._QUOTE_CACHE, md._QUOTE_ERROR_CACHE, md._FX_CACHE, md._FX_ERROR_CACHE):
        d.clear()
    _Ticker.calls = 0
    _Ticker.behaviour = "ok"
    return engine


def _forget_memory():
    """Autre processus / redémarrage : seule la base subsiste."""
    for d in (ms._state, ms._state_synced_at, ms._known_memory, ms._known_db_read):
        d.clear()
    for d in (md._QUOTE_CACHE, md._QUOTE_ERROR_CACHE, md._FX_CACHE, md._FX_ERROR_CACHE):
        d.clear()


def _block_yahoo():
    ms.record_rate_limit(md.YAHOO, YFRateLimitError("x"))


def test_success_is_written_and_read_back_when_blocked():
    engine = _reset()
    with patch.object(md.yf, "Ticker", _Ticker):
        md.get_quote("AAPL")
        md.get_fx_rate_info("USD")
    with engine.connect() as conn:
        row = conn.execute(text("SELECT price, currency, fetched_at FROM last_known_prices WHERE ticker='AAPL'")).first()
    assert row[0] == 200.0 and row[1] == "USD" and row[2].endswith("+00:00"), row  # ISO 8601 UTC

    _forget_memory()
    _block_yahoo()
    calls_before = _Ticker.calls
    with patch.object(md.yf, "Ticker", _Ticker):
        quote = md.get_quote("AAPL", allow_stale=True)
        rate, _ = md.get_fx_rate_info("USD", allow_stale=True)
    assert _Ticker.calls == calls_before  # aucun appel réseau pendant la pause
    assert quote["stale"] is True and quote["source"] == "last_known"
    assert quote["price"] == 200.0 and quote["currency"] == "USD"  # vraie devise, pas "EUR"
    assert rate == 0.9
    print("OK: prix frais mémorisé en base, relu avec sa vraie devise pendant la pause")


def test_strict_mode_never_returns_stale():
    _reset()
    with patch.object(md.yf, "Ticker", _Ticker):
        md.get_quote("AAPL")
    _forget_memory()
    _block_yahoo()
    try:
        md.get_quote("AAPL")  # allow_stale=False par défaut (TP/SL, liquidation, snapshots)
    except md.MarketDataError:
        pass
    else:
        raise AssertionError("un prix daté ne doit jamais sortir sans allow_stale=True")
    print("OK: sans allow_stale, jamais de prix daté (TP/SL/liquidation protégés)")


def test_write_throttle_one_per_five_minutes():
    engine = _reset()
    statements = []
    from sqlalchemy import event

    @event.listens_for(engine, "before_cursor_execute")
    def _count(conn, cursor, statement, *args):
        if statement.startswith("INSERT INTO last_known_prices"):
            statements.append(statement)

    with patch.object(md.yf, "Ticker", _Ticker):
        md.get_quote("AAPL")
        md._QUOTE_CACHE.clear()  # force un 2e appel réel juste après
        md.get_quote("AAPL")
    assert _Ticker.calls == 2
    assert len(statements) == 1, len(statements)
    print("OK: au plus une écriture par ticker toutes les 5 min")


def test_empty_or_missing_table_and_db_down():
    _reset()
    assert ms.get_last_known(["AAPL"]) == {}  # table vide

    def broken():
        raise RuntimeError("db down")

    ms.configure(broken)
    ms._known_memory.clear()
    ms._known_db_read.clear()
    ms._db_unavailable_until = 0.0
    assert ms.get_last_known(["AAPL"]) == {}
    ms.remember_prices([{"ticker": "AAPL", "price": 1.0, "currency": "USD", "fetched_at": time.time()}])
    assert ms.get_last_known(["AAPL"])["AAPL"]["price"] == 1.0  # repli mémoire
    with patch.object(md.yf, "Ticker", _Ticker):  # ZZZ inconnu du faux Ticker -> KeyError
        try:
            md.get_quote("ZZZ", allow_stale=True)
        except md.MarketDataError:
            pass  # aucun prix connu : erreur normale, pas de plantage
    print("OK: table vide, base coupée : aucun plantage, repli mémoire")


def test_failure_never_overwrites_good_price():
    engine = _reset()
    with patch.object(md.yf, "Ticker", _Ticker):
        md.get_quote("AAPL")
    ms.remember_prices([{"ticker": "AAPL", "price": None, "currency": "USD", "fetched_at": time.time()}])
    old = time.time() - 3600
    ms._known_written_at.clear()
    ms.remember_prices([{"ticker": "AAPL", "price": 1.0, "currency": "USD", "fetched_at": old}])
    with engine.connect() as conn:
        price = conn.execute(text("SELECT price FROM last_known_prices WHERE ticker='AAPL'")).scalar()
    assert price == 200.0
    print("OK: un échec ou un prix plus ancien ne remplace jamais un bon prix")


if __name__ == "__main__":
    test_success_is_written_and_read_back_when_blocked()
    test_strict_mode_never_returns_stale()
    test_write_throttle_one_per_five_minutes()
    test_empty_or_missing_table_and_db_down()
    test_failure_never_overwrites_good_price()
    print("Tous les tests du dernier prix connu sont passés.")
