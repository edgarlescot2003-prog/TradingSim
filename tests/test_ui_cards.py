"""Tests des composants visuels de la navigation Trading (ui_cards) : format
des pastilles de performance, carte « Bientôt » non cliquable, carte
disponible = vrai bouton libellé, contour en data URI.

Aucun réseau (sockets piégés), aucune base. Exécutable directement :
python tests/test_ui_cards.py
"""
import os
import socket
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "postgresql://blocked:blocked@127.0.0.1:1/blocked"


def _no_network(*args, **kwargs):
    raise AssertionError("APPEL RÉSEAU INTERDIT dans ce test")


patch.object(socket.socket, "connect", _no_network).start()

from streamlit.testing.v1 import AppTest

from src import ui_cards


def test_perf_pill_format():
    up = ui_cards.perf_pill(16.4, 1, year=2025)
    assert "2025" in up and "▲" in up and "+16,4 %" in up and "tsnav-perf-up" in up, up
    assert 'aria-label="2025 en hausse de +16,4' in up
    down = ui_cards.perf_pill(-3.4, 1)
    assert "▼" in down and "−3,4 %" in down and "tsnav-perf-down" in down, down
    approx = ui_cards.perf_pill(17.0, 0, approx=True, year=2025)
    assert "≈ +17 %" in approx, approx
    assert "—" in ui_cards.perf_pill(None, year=2025) and "tsnav-perf-none" in ui_cards.perf_pill(None)
    assert "+10,4" in ui_cards.perf_pill(10.42, 1), "1 décimale affichée pour 10,42"
    print("OK: pastilles de performance (flèche + couleur + format français, ≈, —)")


def test_outline_css_is_data_uri():
    css = ui_cards.outline_css("tsnav_card_on_large_x", {"w": 10, "h": 5, "d": "M0 0 L10 5Z"}, "large")
    assert 'background-image: url("data:image/svg+xml,' in css and "%3Csvg" in css
    assert "http://" not in css.split("data:image/svg+xml,")[0], "aucune ressource externe"
    assert ui_cards.outline_css("k", None, "large") == ""
    print("OK: contour posé en data URI SVG (aucune ressource externe)")


def _cards_app():
    import streamlit as st

    from src import ui_cards

    with st.container(key="ts_light"):
        ui_cards.inject_css()
        if ui_cards.nav_card("amerique", "<div class='tsnav-name'>Amérique</div>", aria_label="Explorer Amérique"):
            st.session_state["clicked"] = "amerique"
        ui_cards.nav_card("asie", "<div class='tsnav-name'>Asie</div>" + ui_cards.soon_pill(), available=False,
                          aria_label="Explorer Asie")
        target = ui_cards.breadcrumb([("Trading", "home"), ("Actions", "actions"), ("Zones", None)])
        if target:
            st.session_state["crumb"] = target


def test_cards_clickable_or_soon():
    at = AppTest.from_function(_cards_app, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    labels = [b.label for b in at.button]
    assert "Explorer Amérique" in labels, labels
    assert "Explorer Asie" not in labels, "une carte « Bientôt » n'a aucun bouton (non cliquable)"
    next(b for b in at.button if b.label == "Explorer Amérique").click().run()
    assert at.session_state["clicked"] == "amerique"
    next(b for b in at.button if b.label == "Actions").click().run()
    assert at.session_state["crumb"] == "actions"
    assert not any(b.label == "Zones" for b in at.button), "l'écran courant du fil d'Ariane n'est pas un bouton"
    print("OK: carte disponible = vrai bouton libellé ; carte Bientôt sans bouton ; fil d'Ariane cliquable")


if __name__ == "__main__":
    test_perf_pill_format()
    test_outline_css_is_data_uri()
    test_cards_clickable_or_soon()
    print("Tous les tests des composants visuels sont passés.")
