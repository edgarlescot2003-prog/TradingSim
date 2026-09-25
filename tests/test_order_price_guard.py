"""Test d'interface (streamlit AppTest) : un ordre au marché s'exécute sur le
prix AFFICHÉ, et le garde-fou d'âge de ce prix (live_quote,
FACTEUR_AGE_MAX_PRIX_AFFICHE x durée de cache) rafraîchit d'abord le prix et
demande une nouvelle validation quand il est trop ancien.

yfinance simulé (compte les requêtes), sockets piégés, base SQLite
temporaire, sauvegarde neutralisée : jamais de réseau, jamais Supabase.
Exécutable directement : python tests/test_order_price_guard.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "postgresql://blocked:blocked@127.0.0.1:1/blocked"

from streamlit.testing.v1 import AppTest


def _guard_app():
    import os
    import socket
    import tempfile
    import time
    from unittest.mock import patch

    import streamlit as st
    from sqlalchemy import create_engine

    from src import db, market_data as md, market_store as ms, storage, ui_trading
    from src.portfolio import Portfolio

    def _forbidden(*args, **kwargs):
        raise AssertionError("ACCÈS INTERDIT dans ce test (réseau ou base réelle).")

    class _Ticker:
        """Faux yf.Ticker : 200 USD, puis +10 USD à chaque nouvelle requête."""
        def __init__(self, ticker):
            pass

        @property
        def fast_info(self):
            st.session_state["_yahoo_calls"] = st.session_state.get("_yahoo_calls", 0) + 1
            if st.session_state.get("_yahoo_down"):
                raise RuntimeError("Too Many Requests")
            price = 200.0 + 10 * (st.session_state["_yahoo_calls"] - 1)
            return {"lastPrice": price, "currency": "USD", "previousClose": 198.0, "quoteType": "EQUITY"}

    if "portfolio" not in st.session_state:
        engine = create_engine(f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'guard.db')}")
        ms.configure(lambda: engine)
        for d in (ms._state, ms._state_synced_at, ms._known_memory, ms._known_written_at, ms._known_db_read,
                  md._QUOTE_CACHE, md._QUOTE_ERROR_CACHE):
            d.clear()
        patch.object(socket.socket, "connect", _forbidden).start()
        patch.object(md.yf, "Ticker", _Ticker).start()
        patch.object(md, "get_fx_rate_info", lambda currency, allow_stale=False: (0.9, time.time())).start()
        patch.object(db, "get_session", _forbidden).start()
        patch.object(db, "get_engine", _forbidden).start()
        patch.object(ui_trading, "_create_tp_sl_tiers", lambda *a, **k: 0).start()
        patch.object(ui_trading, "_render_tp_sl_section", lambda *a, **k: None).start()
        patch.object(storage, "save_portfolio", lambda *a, **k: None).start()
        patch.object(storage, "invalidate_valuation_cache", lambda *a, **k: None).start()
        st.session_state["portfolio"] = Portfolio(initial_capital=10_000.0, cash=10_000.0)
        st.session_state["user_id"] = "test-user-guard"

    # Simule une fiche restée ouverte sans actualisation (pause d'inactivité) :
    # le fragment prix n'est plus rendu, le prix affiché vieillit.
    if not st.session_state.get("_freeze_display"):
        ui_trading._render_price_and_chart("AAPL", "EQUITY", st.session_state["portfolio"].history)
    age = st.session_state.pop("_age_displayed_price", None)
    if age is not None:
        st.session_state["trading_price_fetched_at"] = time.time() - age
        md._QUOTE_CACHE.clear()  # le cache a expiré lui aussi
    if st.session_state.pop("_open_yahoo_circuit", False):
        ms.record_rate_limit(md.YAHOO, RuntimeError("Too Many Requests"))
    # Prix d'argument volontairement FAUX : l'ordre doit utiliser le prix affiché.
    ui_trading._render_order_panel(st.session_state["portfolio"], "AAPL", "Apple", 999.0, "USD", "EQUITY")


def _start():
    at = AppTest.from_function(_guard_app, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def _click(at):
    at.button(key="submit_market_order").click().run()
    assert not at.exception, at.exception
    return at


def _texts(at):
    return " ".join(str(m.value) for m in at.markdown if "<style>" not in str(m.value))


def test_order_uses_displayed_price():
    at = _start()
    assert abs(at.session_state["trading_price_eur"] - 180.0) < 1e-9
    _click(at)
    trade = at.session_state["portfolio"].history[-1]
    assert abs(trade.price_eur - 180.0) < 1e-9, f"prix d'exécution {trade.price_eur} au lieu du prix affiché 180"
    assert trade.price_source == "yahoo" and at.session_state["_yahoo_calls"] == 1
    print("OK: ordre exécuté au prix affiché (180 €), sans nouvelle cotation au clic")


def test_old_displayed_price_refreshed_then_revalidated():
    at = _start()
    at.session_state["_freeze_display"] = True
    at.session_state["_age_displayed_price"] = 181  # > 2 x 90 s
    _click(at)
    assert not at.session_state["portfolio"].history, "premier clic : aucun ordre exécuté"
    assert at.session_state["_yahoo_calls"] == 2, "le prix a été rafraîchi une fois"
    assert abs(at.session_state["trading_price_eur"] - 189.0) < 1e-9  # 210 USD x 0,9
    assert "Ordre à revalider" in _texts(at) and "valide à nouveau" in _texts(at), _texts(at)[:800]
    _click(at)
    trade = at.session_state["portfolio"].history[-1]
    assert abs(trade.price_eur - 189.0) < 1e-9 and at.session_state["_yahoo_calls"] == 2, trade
    print("OK: prix affiché > 3 min -> rafraîchi et affiché, ordre exécuté seulement à la 2e validation")


def test_recent_displayed_price_not_refreshed():
    at = _start()
    at.session_state["_freeze_display"] = True
    at.session_state["_age_displayed_price"] = 170  # < 2 x 90 s
    _click(at)
    assert at.session_state["portfolio"].history and at.session_state["_yahoo_calls"] == 1
    print("OK: prix affiché de 170 s -> exécuté directement, sans requête")


def test_refresh_blocked_falls_back_to_dated_price_rules():
    at = _start()
    at.session_state["_freeze_display"] = True
    at.session_state["_age_displayed_price"] = 400
    at.session_state["_open_yahoo_circuit"] = True
    _click(at)
    assert not at.session_state["portfolio"].history
    assert at.session_state["trading_price_source"] == "last_known"
    assert "source est indisponible" in _texts(at), _texts(at)[:800]
    _click(at)  # prix daté de ~7 min < 60 min : règles du mode prix daté -> accepté
    trade = at.session_state["portfolio"].history[-1]
    assert trade.price_source == "last_known" and abs(trade.price_eur - 180.0) < 1e-9, trade
    assert at.session_state["_yahoo_calls"] == 1, "coupe-circuit ouvert : aucune requête Yahoo"
    print("OK: rafraîchissement impossible -> prix daté affiché, puis règles du mode prix daté")


if __name__ == "__main__":
    test_order_uses_displayed_price()
    test_old_displayed_price_refreshed_then_revalidated()
    test_recent_displayed_price_not_refreshed()
    test_refresh_blocked_falls_back_to_dated_price_rules()
    print("Tous les tests du garde-fou d'âge du prix affiché sont passés.")
