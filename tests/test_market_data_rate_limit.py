"""Tests autonomes du cooldown anti-rate-limit de market_data.

Exécutable directement : python tests/test_market_data_rate_limit.py
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import market_data as md


class _FailingTicker:
    calls = 0

    @property
    def fast_info(self):
        type(self).calls += 1
        raise RuntimeError("Too Many Requests")


def test_quote_error_is_cooled_down():
    md._QUOTE_CACHE.clear()
    md._QUOTE_ERROR_CACHE.clear()
    _FailingTicker.calls = 0

    with patch.object(md.yf, "Ticker", return_value=_FailingTicker()):
        for _ in range(2):
            try:
                md.get_quote("CL=F")
            except md.MarketDataError:
                pass
            else:
                raise AssertionError("Une erreur de cotation était attendue")

    assert _FailingTicker.calls == 1
    print("OK: une erreur répétée de cotation ne relance pas l'API pendant le cooldown")


def test_execution_freshness_window():
    now = 100_000.0
    live = {"stale": False, "fetched_at": now - 10, "market_time": now - 15 * 60, "market_open": True}
    assert md.is_fresh_for_automation(live, now)  # cotation différée de 15 min : acceptée
    assert not md.is_fresh_for_automation({**live, "market_time": now - 31 * 60}, now)  # flux figé
    assert md.is_fresh_for_automation({**live, "market_time": now - 16 * 3600, "market_open": False}, now)
    assert not md.is_fresh_for_automation({**live, "fetched_at": now - 301}, now)
    assert not md.is_fresh_for_automation({**live, "stale": True}, now)  # prix daté : jamais
    print("OK: TP/SL et liquidation n'acceptent que des prix frais (jamais de prix daté)")


if __name__ == "__main__":
    test_quote_error_is_cooled_down()
    test_execution_freshness_window()