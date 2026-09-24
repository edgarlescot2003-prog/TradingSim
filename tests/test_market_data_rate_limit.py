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
    now = 1_000.0
    assert md.is_fresh(now - md.MAX_EXECUTION_PRICE_AGE_SECONDS, now)
    assert not md.is_fresh(now - md.MAX_EXECUTION_PRICE_AGE_SECONDS - 0.001, now)
    print("OK: un prix dépasse le seuil d'exécution après 5 minutes")


if __name__ == "__main__":
    test_quote_error_is_cooled_down()
    test_execution_freshness_window()