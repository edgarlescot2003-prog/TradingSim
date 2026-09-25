"""Tests des sous-unités de devise (pence « GBp », cents « USX ») : tout prix
sortant de market_data est ramené à l'unité principale, sinon une action de
Londres à 2 664 pence serait comptée 2 664 livres (x100).

yfinance simulé, sockets piégés, base non configurée : jamais de réseau,
jamais Supabase. Exécutable directement : python tests/test_currency_subunits.py
"""
import os
import socket
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "postgresql://blocked:blocked@127.0.0.1:1/blocked"


def _no_network(*args, **kwargs):
    raise AssertionError("APPEL RÉSEAU INTERDIT dans ce test")


patch.object(socket.socket, "connect", _no_network).start()

import pandas as pd

from src import kraken_data, market_data as md, market_store as ms, order_engine, valuation


def _history_frame(values, end=None):
    end = end or pd.Timestamp.now(tz="Europe/London").normalize()
    index = pd.date_range(end=end, periods=len(values), freq="D")
    return pd.DataFrame({"Open": values, "High": values, "Low": values, "Close": values}, index=index)


def _fake_ticker(currency: str, price: float, history_values):
    class _History:
        _history_metadata = {"currency": currency}

    class _Ticker:
        def __init__(self, ticker):
            self._price_history = _History()

        @property
        def fast_info(self):
            return {"lastPrice": price, "currency": currency, "previousClose": price * 0.99, "quoteType": "EQUITY"}

        def history(self, **kwargs):
            return _history_frame(history_values)

    return _Ticker


def _reset():
    ms.configure(None)
    for d in (ms._state, ms._state_synced_at, ms._known_memory, ms._known_written_at, ms._known_db_read,
              md._QUOTE_CACHE, md._QUOTE_ERROR_CACHE, md._HISTORY_ERROR_CACHE):
        d.clear()


def test_normalize_currency():
    assert md.normalize_currency("GBp") == ("GBP", 100.0)
    assert md.normalize_currency("USX") == ("USD", 100.0)
    assert md.normalize_currency("GBP") == ("GBP", 1.0), "des livres ne sont jamais divisées"
    assert md.normalize_currency("EUR") == ("EUR", 1.0) and md.normalize_currency(None) == (None, 1.0)
    print("OK: GBp -> GBP ÷100, USX -> USD ÷100, GBP/EUR inchangés")


def test_all_price_paths_in_main_unit():
    _reset()
    with patch.object(md.yf, "Ticker", _fake_ticker("GBp", 2664.0, [2500.0 + i for i in range(45)])):
        quote = md.get_quote("III.L")
        hist = md.get_history("III.L", interval="1d", start=datetime.now(timezone.utc) - timedelta(days=60))
        daily = md.get_daily_closes("III.L")
        batch = md.get_quotes_batch(("III.L",))["III.L"]
    assert quote["currency"] == "GBP" and abs(quote["price"] - 26.64) < 1e-9, quote
    assert abs(quote["previous_close"] - 26.3736) < 1e-9
    assert abs(hist["Close"].iloc[-1] - 25.44) < 1e-9 and abs(hist["Low"].iloc[0] - 25.0) < 1e-9, hist.tail(1)
    assert daily["currency"] == "GBP" and abs(daily["candles"][-1][1] - 25.44) < 1e-9
    assert batch["currency"] == "GBP" and abs(batch["price"] - 25.44) < 1e-9, batch
    assert ms.get_last_known(["III.L"])["III.L"]["currency"] == "GBP", "dernier prix connu en livres"

    _reset()
    with patch.object(md.yf, "Ticker", _fake_ticker("USX", 452.25, [450.0] * 45)):
        corn = md.get_quote("ZC=F")
    assert corn["currency"] == "USD" and abs(corn["price"] - 4.5225) < 1e-9, corn

    _reset()
    with patch.object(md.yf, "Ticker", _fake_ticker("GBP", 12.5, [12.0] * 45)):
        pounds = md.get_quote("XYZ.L")
    assert pounds["currency"] == "GBP" and pounds["price"] == 12.5
    print("OK: prix en direct, historique, clôtures des listes et lot Admin en livres/dollars (÷100)")


def test_limit_order_on_london_stock_uses_pounds():
    """Ordre d'achat limite à 26 € (1 GBP = 1,16 €) : l'historique en pence
    (2 500 → 2 544) ne doit PAS déclencher un achat à 26 € quand le vrai
    prix est ~29 € ; il se déclenche quand le prix descend vraiment sous la
    limite."""
    from types import SimpleNamespace

    since = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    order = SimpleNamespace(ticker="III.L", last_checked_at=since, action="achat", limit_price_eur=26.0)
    _reset()
    with patch.object(md.yf, "Ticker", _fake_ticker("GBp", 2544.0, [2500.0, 2520.0, 2544.0])):
        trigger, _ = order_engine._find_trigger(order, fx_rate=1.16, now=datetime.now(timezone.utc))
    assert trigger is None, "25,00 GBP x 1,16 = 29 € > 26 € : pas de déclenchement"
    _reset()
    with patch.object(md.yf, "Ticker", _fake_ticker("GBp", 2200.0, [2500.0, 2200.0])):
        trigger, _ = order_engine._find_trigger(order, fx_rate=1.16, now=datetime.now(timezone.utc))
    assert trigger is not None and trigger[1] == 26.0, "22,00 GBP x 1,16 = 25,52 € <= 26 € : déclenché"
    print("OK: ordre à cours limité sur une action de Londres comparé en livres, pas en pence")


def test_kraken_mapping_and_new_asset_classes():
    assert kraken_data._to_kraken_pair("DOGE-USD") == "XDGUSD"
    assert kraken_data._to_kraken_pair("UNI7083-USD") == "UNIUSD"
    assert kraken_data._to_kraken_pair("BTC-USD") == "XBTUSD" and kraken_data._to_kraken_pair("SOL-USD") == "SOLUSD"
    for ticker in ("SGOV", "IEI", "TLH", "GOVT", "TIP", "LQD", "HYG", "JNK", "BNDX", "EMB", "MUB"):
        assert valuation.category_for("ETF", ticker) == "Obligations", ticker
    assert valuation.category_for("ETF", "SPY") != "Obligations"
    for ticker, sector in (("HG=F", "Métaux industriels"), ("PL=F", "Métaux précieux"), ("RB=F", "Énergie"),
                           ("ZC=F", "Agriculture"), ("CC=F", "Agriculture")):
        assert valuation.sector_for("Matières premières", ticker) == sector, ticker
    print("OK: Kraken DOGE -> XDG et UNI7083 -> UNI ; nouveaux ETF obligataires et matières premières reconnus")


if __name__ == "__main__":
    test_normalize_currency()
    test_all_price_paths_in_main_unit()
    test_limit_order_on_london_stock_uses_pounds()
    test_kraken_mapping_and_new_asset_classes()
    print("Tous les tests des sous-unités de devise sont passés.")
