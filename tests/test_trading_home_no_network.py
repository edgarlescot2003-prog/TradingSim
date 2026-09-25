"""Garde (phase 1) : l'accueil de l'onglet Trading, les recherches récentes et
les pages de liste par catégorie ne font AUCUNE requête Yahoo/Kraken.

Pièges : toute ouverture de connexion réseau (socket), yfinance et requests
lèvent une erreur ET sont comptés — le test échoue au moindre appel, même
avalé par un try/except de l'app. La base est une SQLite temporaire (jamais
Supabase) : db.get_session/get_engine sont piégés.

Exécutable directement : python tests/test_trading_home_no_network.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "postgresql://blocked:blocked@127.0.0.1:1/blocked"

from streamlit.testing.v1 import AppTest


def _home_app():
    import os
    import socket
    import tempfile
    from unittest.mock import patch

    import requests
    import streamlit as st
    import yfinance as yf
    from sqlalchemy import create_engine

    from src import db, market_store as ms, search_history, ui_trading
    from src.portfolio import Portfolio

    calls = st.session_state.setdefault("_network_calls", [])

    def _trip(name):
        def _fail(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"APPEL RÉSEAU INTERDIT : {name}")
        return _fail

    if "portfolio" not in st.session_state:
        engine = create_engine(f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'home.db')}")
        ms.configure(lambda: engine)
        for d in (ms._state, ms._state_synced_at, ms._known_memory, ms._known_written_at, ms._known_db_read):
            d.clear()
        for target, attr in ((socket.socket, "connect"), (socket, "create_connection"),
                             (requests.sessions.Session, "request"), (yf, "Ticker"), (yf, "Search"),
                             (yf, "download")):
            patch.object(target, attr, _trip(f"{getattr(target, '__name__', target)}.{attr}")).start()
        patch.object(db, "get_session", _trip("db.get_session")).start()
        patch.object(db, "get_engine", _trip("db.get_engine")).start()
        recent = st.session_state.get("_test_recent", [])
        patch.object(search_history, "get_recent", lambda user_id, limit=8: recent[:limit]).start()
        st.session_state["portfolio"] = Portfolio(initial_capital=10_000.0, cash=10_000.0)
        st.session_state["user_id"] = "test-user-home"
        st.session_state["selected_ticker"] = None

    ui_trading.render(st.session_state["portfolio"])


def _run(**state):
    at = AppTest.from_function(_home_app, default_timeout=60)
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    assert not at.exception, at.exception
    return at


def _assert_no_network(at):
    calls = at.session_state["_network_calls"]
    assert calls == [], f"Requêtes réseau détectées : {calls}"


def test_home_makes_no_request():
    at = _run()
    _assert_no_network(at)
    labels = [b.label for b in at.button]
    for expected in ("Actions", "Crypto", "Obligations", "Forex/Monnaies", "Matières premières"):
        assert any(label.startswith(expected) for label in labels), labels
    text = " ".join(str(m.value) for m in at.markdown if "<style>" not in str(m.value))
    assert "CAC 40" not in text and "Indices" not in text, "les indices ne doivent plus apparaître"
    print("OK: accueil rendu (5 catégories, aucun indice), zéro requête réseau")


def test_recent_searches_make_no_request():
    at = _run(_test_recent=[{"ticker": "AAPL", "name": "Apple", "quote_type": "EQUITY"},
                            {"ticker": "BTC-USD", "name": "Bitcoin", "quote_type": ""}])
    _assert_no_network(at)
    assert any(b.label == "AAPL" for b in at.button), [b.label for b in at.button]
    print("OK: recherches récentes affichées, zéro requête réseau")


def test_category_navigation_makes_no_request():
    at = _run()
    crypto = next(b for b in at.button if b.label.startswith("Crypto"))
    crypto.click().run()
    assert not at.exception, at.exception
    _assert_no_network(at)
    assert any(b.label == "BTC-USD" for b in at.button), [b.label for b in at.button]
    at.button(key="back_from_category").click().run()
    assert not at.exception, at.exception
    _assert_no_network(at)
    print("OK: page de liste Crypto ouverte puis fermée, zéro requête réseau")


if __name__ == "__main__":
    test_home_makes_no_request()
    test_recent_searches_make_no_request()
    test_category_navigation_makes_no_request()
    print("Tous les tests 'accueil sans requête' sont passés.")
