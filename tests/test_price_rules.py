"""Tests autonomes des règles métier "prix daté" (décidées par Edgar) :
ordres manuels jusqu'à 60 min (15 min crypto), traçabilité, TP/SL et
liquidation sur prix frais uniquement. Aucun appel réseau, jamais Supabase.

Exécutable directement : python tests/test_price_rules.py
"""
import os
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine

from src import market_data as md
from src import market_store as ms
from src import valuation
from src.db_models import TradeRow
from src.portfolio import Portfolio, Trade


def test_manual_order_age_limits():
    assert valuation.order_price_age_error(59 * 60, "AAPL", "EQUITY") is None
    assert "60 min" in valuation.order_price_age_error(61 * 60, "AAPL", "EQUITY")
    assert valuation.order_price_age_error(59 * 60, "GC=F") is None  # matières premières : 60 min
    assert valuation.order_price_age_error(14 * 60, "BTC-USD", "CRYPTOCURRENCY") is None
    assert "15 min" in valuation.order_price_age_error(16 * 60, "BTC-USD", "CRYPTOCURRENCY")
    assert "15 min" in valuation.order_price_age_error(16 * 60, "SOL-USD")  # crypto reconnue par le ticker
    assert valuation.order_price_age_error(None, "AAPL") is not None
    print("OK: ordre accepté à 59 min / refusé à 61 min ; crypto refusée à 16 min")


def test_traceability_fields():
    p = Portfolio(initial_capital=10_000, cash=10_000)
    p.buy("AAPL", "Apple", 1, 100.0, "USD")
    trade = p.history[-1]
    assert trade.price_age_seconds is None and trade.price_source is None  # champs présents, vides par défaut
    trade.price_age_seconds, trade.price_source = 1800.0, "last_known"
    restored = Portfolio.from_dict(p.to_dict()).history[-1]
    assert (restored.price_age_seconds, restored.price_source) == (1800.0, "last_known")
    assert {"price_age_seconds", "price_source"} <= set(TradeRow.__table__.columns.keys())
    assert "price_age_seconds" in Trade.__dataclass_fields__
    print("OK: âge et source du prix enregistrables sur chaque trade (colonnes nullables)")


def _reset_store():
    engine = create_engine(f"sqlite:///{os.path.join(tempfile.mkdtemp(), 's.db')}")
    ms.configure(lambda: engine)
    for d in (ms._state, ms._state_synced_at, ms._known_memory, ms._known_written_at, ms._known_db_read):
        d.clear()
    ms._db_unavailable_until = 0.0
    for d in (md._QUOTE_CACHE, md._QUOTE_ERROR_CACHE, md._FX_CACHE, md._FX_ERROR_CACHE):
        d.clear()


def test_tp_sl_and_liquidation_refuse_stale_price():
    from scripts import check_liquidation, check_tp_sl

    _reset_store()
    # Un prix connu très récent existe, mais Yahoo est en pause : il ne doit
    # JAMAIS servir à une exécution automatique.
    ms.remember_prices([{"ticker": "AAPL", "price": 100.0, "currency": "USD", "fetched_at": time.time() - 30}])
    ms.record_rate_limit(md.YAHOO, RuntimeError("Too Many Requests"))
    for script in (check_tp_sl, check_liquidation):
        assert script._fetch_price_eur("AAPL") == ("AAPL", None)

    # Prix live mais flux figé pendant la séance (cotation vieille de 40 min).
    frozen = {"price": 100.0, "currency": "EUR", "previous_close": None, "quote_type": "EQUITY",
              "fetched_at": time.time(), "market_time": time.time() - 40 * 60, "market_open": True,
              "stale": False, "source": "yahoo"}
    with patch.object(md, "get_quote", return_value=frozen):
        for script in (check_tp_sl, check_liquidation):
            assert script._fetch_price_eur("MC.PA") == ("MC.PA", None)

    # Cotation différée de 15 min (Euronext) : acceptée.
    delayed = {**frozen, "market_time": time.time() - 15 * 60}
    with patch.object(md, "get_quote", return_value=delayed):
        ticker, info = check_tp_sl._fetch_price_eur("MC.PA")
        assert info is not None and info[0] == 100.0
    print("OK: TP/SL et liquidation refusent tout prix daté ou figé, acceptent le différé Yahoo")


if __name__ == "__main__":
    test_manual_order_age_limits()
    test_traceability_fields()
    test_tp_sl_and_liquidation_refuse_stale_price()
    print("Tous les tests des règles de prix sont passés.")
