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

    from src import daily_snapshot as ds, db, market_store as ms, search_history, ui_trading
    from src.portfolio import Portfolio

    calls = st.session_state.setdefault("_network_calls", [])

    def _trip(name):
        def _fail(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"APPEL RÉSEAU INTERDIT : {name}")
        return _fail

    if "portfolio" not in st.session_state:
        engine = create_engine(f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'home.db')}")
        if st.session_state.get("_test_db_down"):
            ms.configure(None)
        else:
            ms.configure(lambda: engine)
        ds._ready_engine = None
        triggers = st.session_state.setdefault("_refresh_triggers", [])
        # Le rafraîchissement (réseau) tourne en arrière-plan, hors du rendu :
        # ici on vérifie seulement qu'il est bien DÉCLENCHÉ par la page.
        patch.object(ds, "start_refresh_if_due",
                     lambda category, now=None, rows=None: triggers.append(category) or "fresh").start()
        if st.session_state.get("_test_fill"):
            from datetime import date, timedelta
            from sqlalchemy import text
            ds._engine()
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            with engine.begin() as conn:
                conn.execute(text(
                    "UPDATE asset_daily_snapshot SET close_price = 65432.1, currency = 'USD', "
                    "change_30d_pct = -3.5, as_of_date = :d, updated_at = :u WHERE ticker = 'BTC-USD'"),
                    {"d": yesterday, "u": ds.iso(__import__("time").time() - 2 * 3600)})
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
        assert f"Explorer {expected}" in labels, labels
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
    crypto = next(b for b in at.button if b.label == "Explorer Crypto")
    crypto.click().run()
    assert not at.exception, at.exception
    _assert_no_network(at)
    assert any(b.label == "BTC-USD" for b in at.button), [b.label for b in at.button]
    assert at.session_state["_refresh_triggers"] == ["Crypto"], "le rafraîchissement doit être déclenché"
    next(b for b in at.button if b.label == "Trading").click().run()  # fil d'Ariane
    assert not at.exception, at.exception
    _assert_no_network(at)
    print("OK: page de liste Crypto ouverte puis fermée, zéro requête réseau")


def _open_crypto(**state):
    at = _run(**state)
    next(b for b in at.button if b.label == "Explorer Crypto").click().run()
    assert not at.exception, at.exception
    _assert_no_network(at)
    return at


def test_category_list_shows_indicative_prices():
    from datetime import date, timedelta
    at = _open_crypto(_test_fill=True)
    text = " ".join(str(m.value) for m in at.markdown) + " " + " ".join(str(c.value) for c in at.caption)
    assert "65,432.10 USD" in text, text[:1500]
    assert "▼" in text and "−3,50 %" in text, "variation en pastille avec flèche"
    assert f"Clôture du {(date.today() - timedelta(days=1)).strftime('%d/%m')}" in text, text[:1500]
    assert "mis à jour il y a 2 h" in text
    assert "en cours de chargement" in text  # les 3 autres cryptos n'ont pas encore de données
    # Filtre et tri locaux (aucune requête).
    at.text_input(key="list_filter_compact_category_Crypto").input("eth").run()
    assert not at.exception, at.exception
    _assert_no_network(at)
    tickers = [b.label for b in at.button if b.label.endswith("-USD")]
    assert tickers == ["ETH-USD"], tickers
    at.text_input(key="list_filter_compact_category_Crypto").input("").run()
    at.selectbox(key="list_sort_compact_category_Crypto").select("Variation 30 j : moins bonne d'abord").run()
    assert [b.label for b in at.button if b.label.endswith("-USD")][0] == "BTC-USD", "variation connue d'abord"
    _assert_no_network(at)
    print("OK: liste Crypto lue en base (prix indicatif, devise, var. 30 j, date de clôture, âge)")


def test_category_list_database_down():
    at = _open_crypto(_test_db_down=True)
    captions = " ".join(str(c.value) for c in at.caption)
    assert "momentanément indisponibles" in captions, captions
    assert any(b.label == "BTC-USD" for b in at.button)
    assert at.session_state["_refresh_triggers"] == [], "pas de rafraîchissement sans base"
    print("OK: base indisponible -> message neutre, actifs toujours accessibles, aucune erreur")


def _click(at, label):
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, at.exception
    _assert_no_network(at)


def test_actions_zones_countries_list_make_no_request():
    at = _run()
    _click(at, "Explorer Actions")
    labels = [b.label for b in at.button]
    text = " ".join(str(m.value) for m in at.markdown if "<style>" not in str(m.value))
    assert "Choisir une zone" in text and "S&amp;P 500" in text and "Nikkei 225" in text, text[:600]
    assert "Explorer la zone Amérique" in labels, labels
    assert "Explorer la zone Europe" not in labels and "Explorer la zone Asie" not in labels,         "zones sans actif : « Bientôt », non cliquables"
    assert text.count("Bientôt") >= 2
    _click(at, "Explorer la zone Amérique")
    labels = [b.label for b in at.button]
    assert "Explorer États-Unis" in labels and "Explorer Canada" not in labels, labels
    assert "Voir toute la liste : Toute l'Amérique" in labels
    _click(at, "Explorer États-Unis")
    tickers = {b.label for b in at.button}
    assert {"AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"} <= tickers, tickers
    assert not {"TLT", "BTC-USD"} & tickers, "liste filtrée sur les actions des États-Unis"
    assert at.session_state["_refresh_triggers"] == ["Actions"]
    _click(at, "Amérique")  # fil d'Ariane
    assert "Explorer États-Unis" in [b.label for b in at.button]
    _click(at, "Voir toute la liste : Toute l'Amérique")
    _click(at, "Actions")
    assert "Explorer la zone Amérique" in [b.label for b in at.button]
    print("OK: Actions -> zones -> pays -> liste (+ fil d'Ariane), Bientôt non cliquable, zéro requête réseau")


def test_forex_by_currency_makes_no_request():
    at = _run()
    _click(at, "Explorer Forex/Monnaies")
    labels = [b.label for b in at.button]
    expected = {f"Explorer les paires en {n}" for n in
                ("Euro", "Dollar américain", "Livre sterling", "Yen japonais", "Franc suisse", "Dollar australien")}
    assert expected <= set(labels), labels
    text = " ".join(str(m.value) for m in at.markdown if "<style>" not in str(m.value))
    assert "Banque centrale européenne" in text and "taux" not in text.lower(), "banque centrale, jamais de taux"
    _click(at, "Explorer les paires en Euro")
    tickers = [b.label for b in at.button if b.label.endswith("=X")]
    assert tickers == ["EURUSD=X"], tickers
    _click(at, "Forex/Monnaies")  # fil d'Ariane
    _click(at, "Explorer les paires en Dollar américain")
    assert len([b.label for b in at.button if b.label.endswith("=X")]) == 5
    print("OK: Forex -> devises (banque centrale, sans taux) -> paires de la devise, zéro requête réseau")


def test_bonds_by_maturity_makes_no_request():
    at = _run()
    _click(at, "Explorer Obligations")
    labels = [b.label for b in at.button]
    for group in ("court terme", "moyen terme", "long terme", "diversifiés"):
        assert f"Explorer les obligations {group}" in labels, labels
    text = " ".join(str(m.value) for m in at.markdown if "<style>" not in str(m.value))
    assert "aucune donnée réelle" in text and "investment grade" in text
    _click(at, "Explorer les obligations court terme")
    assert [b.label for b in at.button if b.label in {"SHY", "IEF", "TLT", "BND", "AGG"}] == ["SHY"]
    _click(at, "Obligations")  # fil d'Ariane
    _click(at, "Explorer les obligations diversifiés")
    assert sorted(b.label for b in at.button if b.label in {"SHY", "IEF", "TLT", "BND", "AGG"}) == ["AGG", "BND"]
    print("OK: Obligations -> maturités (courbe stylisée) -> fonds de la maturité, zéro requête réseau")


if __name__ == "__main__":
    test_home_makes_no_request()
    test_recent_searches_make_no_request()
    test_category_navigation_makes_no_request()
    test_category_list_shows_indicative_prices()
    test_category_list_database_down()
    test_actions_zones_countries_list_make_no_request()
    test_forex_by_currency_makes_no_request()
    test_bonds_by_maturity_makes_no_request()
    print("Tous les tests 'accueil sans requête' sont passés.")
