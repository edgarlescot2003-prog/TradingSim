"""Test d'interface (streamlit AppTest) de la pause d'actualisation
automatique de la fiche actif après inactivité : pendant la pause, les
fragments sont rendus SANS minuteur (run_every=None) et aucune requête de
prix n'est faite ; « Actualiser » relance tout.

AppTest ne sait pas simuler un tic de minuteur côté navigateur (chaque run
est un rechargement complet) : le déclenchement de la pause par un tic et
l'arrêt réel des tics dans un navigateur sont couverts séparément (fonction
pure dans test_live_quote.py, vérification Playwright manuelle documentée
dans le rapport de la phase 1).

yfinance simulé, graphique simulé, sockets piégés, base non configurée :
jamais de réseau, jamais Supabase.
Exécutable directement : python tests/test_auto_refresh_pause.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "postgresql://blocked:blocked@127.0.0.1:1/blocked"

from streamlit.testing.v1 import AppTest


def _pause_app():
    import socket
    import time
    from unittest.mock import patch

    import pandas as pd
    import streamlit as st

    from src import db, market_data as md, market_store as ms, search_history, storage, ui_trading
    from src.portfolio import Portfolio

    def _forbidden(*args, **kwargs):
        raise AssertionError("ACCÈS INTERDIT dans ce test (réseau ou base réelle).")

    class _Ticker:
        def __init__(self, ticker):
            pass

        @property
        def fast_info(self):
            st.session_state["_yahoo_calls"] = st.session_state.get("_yahoo_calls", 0) + 1
            return {"lastPrice": 200.0, "currency": "USD", "previousClose": 198.0, "quoteType": "EQUITY"}

    def _chart(ticker, quote_type, period_key):
        index = pd.date_range("2026-06-01", periods=30, freq="D", tz="UTC")
        values = [100.0 + i for i in range(30)]
        return pd.DataFrame({"Open": values, "High": values, "Low": values, "Close": values}, index=index), "1d", "Test"

    real_fragment = st.fragment

    def _spy_fragment(func=None, *, run_every=None, **kwargs):
        st.session_state.setdefault("_run_every", {})[getattr(func, "__name__", "?")] = run_every
        return real_fragment(func, run_every=run_every, **kwargs)

    if "portfolio" not in st.session_state:
        ms.configure(None)
        for d in (ms._state, ms._state_synced_at, ms._known_memory, ms._known_written_at, ms._known_db_read,
                  md._QUOTE_CACHE, md._QUOTE_ERROR_CACHE):
            d.clear()
        patch.object(socket.socket, "connect", _forbidden).start()
        patch.object(md.yf, "Ticker", _Ticker).start()
        patch.object(md, "get_fx_rate_info", lambda currency, allow_stale=False: (0.9, time.time())).start()
        patch.object(ui_trading, "_fetch_chart_history", _chart).start()
        patch.object(ui_trading, "_render_tp_sl_section", lambda *a, **k: None).start()
        patch.object(ui_trading, "render_pending_orders", lambda *a, **k: None).start()
        patch.object(search_history, "record", lambda *a, **k: None).start()
        patch.object(search_history, "get_recent", lambda *a, **k: []).start()
        patch.object(db, "get_session", _forbidden).start()
        patch.object(db, "get_engine", _forbidden).start()
        patch.object(storage, "save_portfolio", lambda *a, **k: None).start()
        patch.object(st, "fragment", _spy_fragment).start()
        st.session_state["portfolio"] = Portfolio(initial_capital=10_000.0, cash=10_000.0)
        st.session_state["user_id"] = "test-user-pause"
        st.session_state["selected_ticker"] = "AAPL"
        st.session_state["selected_name"] = "Apple"

    if st.session_state.pop("_expire_cache", False):
        md._QUOTE_CACHE.clear()
    ui_trading.render(st.session_state["portfolio"])


def _texts(at):
    parts = [str(m.value) for m in at.markdown if "<style>" not in str(m.value)]
    return " ".join(parts + [str(c.value) for c in at.caption])


def test_pause_stops_timers_and_requests_then_resumes():
    at = AppTest.from_function(_pause_app, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["_yahoo_calls"] == 1
    assert at.session_state["_run_every"] == {"_price_and_chart_body": 90}, \
        at.session_state["_run_every"]
    assert at.session_state["_trading_last_interaction_at"] is not None
    text = _texts(at)
    # Gros prix en euros (200 USD x 0,9), petit prix en devise d'origine, taux de change.
    assert 'tsnav-live-price">180.00 <span class="tsnav-live-ccy">€' in text, text[:1500]
    assert 'tsnav-live-eur">200.00 USD' in text and "1 USD = 0,9000 €" in text
    for expected in ("Variation du jour", "Clôture précédente", "Taux de change", "exécuté au prix affiché",
                     "toutes les 90 s", ">Actions<"):
        assert expected in text, (expected, text[:1500])

    # Ce que fait un tic de minuteur après 10 min sans interaction : pause +
    # rechargement complet marqué comme NON interactif.
    at.session_state["_auto_refresh_paused"] = True
    at.session_state["_auto_refresh_pause_rerun"] = True
    at.session_state["_expire_cache"] = True  # toute cotation serait une vraie requête
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["_yahoo_calls"] == 1, "pause : aucune requête de prix"
    assert at.session_state["_run_every"] == {"_price_and_chart_body": None}, \
        at.session_state["_run_every"]
    assert at.session_state["_auto_refresh_paused"] is True
    assert "Actualisation en pause" in _texts(at), _texts(at)[:800]
    assert abs(at.session_state["trading_price_eur"] - 180.0) < 1e-9, "le dernier prix reste affiché"

    at.button(key="resume_auto_refresh").click().run()
    assert not at.exception, at.exception
    assert not at.session_state["_auto_refresh_paused"] if "_auto_refresh_paused" in at.session_state else True
    assert at.session_state["_yahoo_calls"] == 2, "reprise : le prix est de nouveau actualisé"
    assert at.session_state["_run_every"] == {"_price_and_chart_body": 90}
    print("OK: pause -> minuteurs arrêtés, zéro requête, dernier prix affiché ; Actualiser -> reprise")


def test_full_reload_counts_as_interaction():
    at = AppTest.from_function(_pause_app, default_timeout=60)
    at.run()
    at.session_state["_auto_refresh_paused"] = True  # pause, puis un vrai clic ailleurs (rechargement complet)
    at.run()
    assert not at.exception, at.exception
    assert "_auto_refresh_paused" not in at.session_state or not at.session_state["_auto_refresh_paused"]
    assert at.session_state["_run_every"]["_price_and_chart_body"] == 90
    print("OK: un rechargement complet provoqué par l'utilisateur lève la pause")


if __name__ == "__main__":
    test_pause_stops_timers_and_requests_then_resumes()
    test_full_reload_counts_as_interaction()
    print("Tous les tests de la pause d'actualisation sont passés.")
