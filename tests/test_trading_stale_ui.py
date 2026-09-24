"""Test d'interface (streamlit AppTest) de la fiche Trading quand Yahoo est
en pause : bandeau "Prix daté", vraie devise, ordre accepté sous 60 min et
tracé (âge + source), refusé au-delà. Base SQLite temporaire pour l'état du
coupe-circuit / derniers prix connus, sauvegarde du portefeuille neutralisée :
aucun appel réseau, jamais Supabase.

Exécutable directement : python tests/test_trading_stale_ui.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Filet de sécurité supplémentaire : adresse de base factice (load_dotenv ne
# remplace jamais une variable déjà définie), en plus des pièges ci-dessous.
os.environ["DATABASE_URL"] = "postgresql://blocked:blocked@127.0.0.1:1/blocked"

from streamlit.testing.v1 import AppTest


def _stale_trading_app():
    import os
    import tempfile
    import time
    from unittest.mock import patch

    import streamlit as st
    from sqlalchemy import create_engine

    from src import db, market_data as md, market_store as ms, storage, ui_trading
    from src.portfolio import Portfolio

    def _db_forbidden(*args, **kwargs):
        raise AssertionError("ACCÈS BASE INTERDIT dans ce test (la base réelle serait Supabase).")

    age_minutes = st.session_state.get("_test_age_minutes", 30)
    if "portfolio" not in st.session_state:
        engine = create_engine(f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ui.db')}")
        ms.configure(lambda: engine)
        for d in (ms._state, ms._state_synced_at, ms._known_memory, ms._known_written_at, ms._known_db_read):
            d.clear()
        fetched_at = time.time() - age_minutes * 60
        ms.remember_prices([
            {"ticker": "AAPL", "price": 200.0, "currency": "USD", "previous_close": 198.0,
             "quote_type": "EQUITY", "fetched_at": fetched_at},
            {"ticker": "FX:USD", "price": 0.9, "currency": "EUR", "fetched_at": fetched_at},
        ])
        ms.record_rate_limit(md.YAHOO, RuntimeError("Too Many Requests"))
        # Aucun accès possible à la vraie base : db.get_session/get_engine
        # piégés (le .env local pointe sur Supabase), paliers TP/SL neutralisés.
        patch.object(db, "get_session", _db_forbidden).start()
        patch.object(db, "get_engine", _db_forbidden).start()
        patch.object(ui_trading, "_create_tp_sl_tiers", lambda *a, **k: 0).start()
        patch.object(ui_trading, "_render_tp_sl_section", lambda *a, **k: None).start()
        patch.object(storage, "save_portfolio", lambda *a, **k: None).start()
        patch.object(storage, "invalidate_valuation_cache", lambda *a, **k: None).start()
        st.session_state["portfolio"] = Portfolio(initial_capital=10_000.0, cash=10_000.0)
        st.session_state["user_id"] = "test-user-stale-ui"
        st.session_state["selected_ticker"] = "AAPL"

    portfolio = st.session_state["portfolio"]
    ui_trading._render_price_and_chart("AAPL", "EQUITY", portfolio.history)
    price_eur = st.session_state.get("trading_price_eur")
    if price_eur is not None:
        ui_trading._render_order_panel(portfolio, "AAPL", "Apple", price_eur,
                                       st.session_state.get("trading_currency"), "EQUITY")


def _run(age_minutes):
    at = AppTest.from_function(_stale_trading_app, default_timeout=60)
    at.session_state["_test_age_minutes"] = age_minutes
    at.run()
    assert not at.exception, at.exception
    return at


def _all_text(at):
    return " ".join(str(m.value) for m in at.markdown) + " " + " ".join(str(e.value) for e in at.error)


def test_stale_price_display_and_order_accepted():
    at = _run(30)
    text = _all_text(at)
    assert "Prix daté de 30 min" in text, text[:500]
    assert at.session_state["trading_currency"] == "USD"  # vraie devise, plus "EUR" forcé
    assert abs(at.session_state["trading_price_eur"] - 180.0) < 1e-9
    at.button(key="submit_market_order").click().run()
    assert not at.exception, at.exception
    portfolio = at.session_state["portfolio"]
    assert "AAPL" in portfolio.positions, _all_text(at)[:800]
    trade = portfolio.history[-1]
    assert trade.price_source == "last_known" and 1790 < trade.price_age_seconds < 1830, trade
    assert trade.currency == "USD"
    print("OK: prix daté affiché (bandeau, vraie devise), ordre à 30 min accepté et tracé")


def test_order_refused_beyond_60_minutes():
    at = _run(61)
    at.button(key="submit_market_order").click().run()
    assert not at.exception, at.exception
    assert "AAPL" not in at.session_state["portfolio"].positions
    assert any("au-delà de 60 min" in str(e.value) for e in at.error), [e.value for e in at.error]
    print("OK: ordre refusé à 61 min avec un message clair")


if __name__ == "__main__":
    test_stale_price_display_and_order_accepted()
    test_order_refused_beyond_60_minutes()
    print("Tous les tests d'interface prix daté sont passés.")
