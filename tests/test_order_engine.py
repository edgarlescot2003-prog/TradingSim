"""Tests autonomes du moteur d'ordres à cours limité (order_engine), sur des
bougies simulées : aucun appel réseau, aucune base.

Exécutable directement : python tests/test_order_engine.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src import market_data as md
from src import order_engine
from src.portfolio import Portfolio


def _bars(minutes_ago_list, low, high):
    """Bougies 5 min dont la plus récente a `minutes_ago_list[-1]` min."""
    now = datetime.now(timezone.utc)
    index = pd.DatetimeIndex([now - timedelta(minutes=m) for m in minutes_ago_list])
    return pd.DataFrame({"Open": low, "High": high, "Low": low, "Close": low}, index=index)


def _portfolio_with_limit_buy(limit_price, placed_minutes_ago=60):
    p = Portfolio(initial_capital=10_000, cash=10_000)
    p.place_limit_order("MC.PA", "LVMH", "achat", 1, limit_price, "EUR")
    order = p.pending_orders[0]
    order.last_checked_at = (datetime.now(timezone.utc) - timedelta(minutes=placed_minutes_ago)).isoformat()
    return p, order


def test_delayed_quotes_still_execute():
    """Cotation différée de 15 min (cas Yahoo pour Euronext) : l'ancien
    garde-fou de 5 min bloquait l'exécution, plus maintenant."""
    p, _ = _portfolio_with_limit_buy(390.0)
    hist = _bars([40, 30, 20, 15], low=[395, 392, 389, 391], high=[396, 393, 390, 392])
    with patch.object(md, "get_history", return_value=hist), patch.object(md, "get_fx_rate_to_eur", return_value=1.0):
        messages = order_engine.process_pending_orders(p)
    assert len(messages) == 1, messages
    assert "MC.PA" in p.positions and p.positions["MC.PA"].avg_price_eur == 390.0  # au prix limite
    assert not p.pending_orders
    print("OK: ordre limite exécuté malgré 15 min de retard de cotation, au prix limite")


def test_checkpoint_advances_to_last_bar_when_not_triggered():
    p, order = _portfolio_with_limit_buy(300.0)
    hist = _bars([40, 30, 20, 15], low=[395, 392, 389, 391], high=[396, 393, 390, 392])
    with patch.object(md, "get_history", return_value=hist), patch.object(md, "get_fx_rate_to_eur", return_value=1.0):
        order_engine.process_pending_orders(p)
    checkpoint = datetime.fromisoformat(order.last_checked_at)
    latest_bar = hist.index.max().to_pydatetime()
    assert abs((checkpoint - latest_bar).total_seconds()) < 1, (checkpoint, latest_bar)
    assert p.pending_orders
    print("OK: point de contrôle avancé jusqu'à la dernière bougie reçue (plus jamais coincé)")


def test_old_order_uses_hourly_bars_and_is_not_stuck():
    """Ordre non vérifié depuis 10 jours : bougies d'1 h dont la dernière a
    40 min — auparavant bloqué indéfiniment."""
    p, order = _portfolio_with_limit_buy(300.0, placed_minutes_ago=10 * 24 * 60)
    captured = {}

    def fake_history(ticker, interval, start):
        captured["interval"] = interval
        return _bars([180, 120, 60, 40], low=[395] * 4, high=[396] * 4)

    with patch.object(md, "get_history", side_effect=fake_history), patch.object(md, "get_fx_rate_to_eur", return_value=1.0):
        order_engine.process_pending_orders(p)
    assert captured["interval"] == "1h"
    assert datetime.now(timezone.utc) - datetime.fromisoformat(order.last_checked_at) < timedelta(hours=1)
    print("OK: vieil ordre (bougies 1 h) : point de contrôle avancé, revient ensuite aux bougies 5 min")


def test_fetch_failure_keeps_checkpoint():
    p, order = _portfolio_with_limit_buy(300.0)
    before = order.last_checked_at
    with patch.object(md, "get_history", side_effect=md.MarketDataError("Cotations Yahoo en pause")), \
         patch.object(md, "get_fx_rate_to_eur", return_value=1.0):
        order_engine.process_pending_orders(p)
    assert order.last_checked_at == before and p.pending_orders
    print("OK: source en pause -> ordre conservé, fenêtre non avancée (rien de manqué)")


if __name__ == "__main__":
    test_delayed_quotes_still_execute()
    test_checkpoint_advances_to_last_bar_when_not_triggered()
    test_old_order_uses_hourly_bars_and_is_not_stuck()
    test_fetch_failure_keeps_checkpoint()
    print("Tous les tests du moteur d'ordres limites sont passés.")
