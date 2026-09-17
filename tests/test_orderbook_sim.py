"""Tests fonctionnels de src/orderbook_sim.py (carnet d'ordre simulé,
prompt 20) : logique pure, sans Streamlit ni réseau. Pour le test de garde
qui vérifie spécifiquement l'ABSENCE de tout appel réseau côté fragment
Streamlit, voir tests/test_orderbook_no_network.py — c'est celui-là le
"test de garde explicite" demandé par le prompt d'origine, pas celui-ci.

Exécutable directement : python tests/test_orderbook_sim.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import orderbook_sim as ob


def test_generate_snapshot_structure():
    snap = ob.generate_snapshot(100.0, previous_price=None, seed=42)
    assert len(snap["asks"]) == ob.LEVELS_PER_SIDE
    assert len(snap["bids"]) == ob.LEVELS_PER_SIDE
    assert all(a["price"] > 100.0 for a in snap["asks"]), "un ask doit toujours être au-dessus du prix de référence"
    assert all(b["price"] < 100.0 for b in snap["bids"]), "un bid doit toujours être en dessous du prix de référence"
    assert all(a["quantity"] > 0 for a in snap["asks"] + snap["bids"]), "aucune quantité négative ou nulle"
    print("OK: generate_snapshot produit une structure valide")


def test_generate_snapshot_ordering():
    """Prix générés du plus proche (index 0) au plus loin (dernier index),
    pour CHAQUE côté — voir ui_trading._render_order_book_rows, qui inverse
    les asks à l'affichage mais compte sur cet ordre de génération."""
    snap = ob.generate_snapshot(250.0, seed=7)
    ask_prices = [a["price"] for a in snap["asks"]]
    assert ask_prices == sorted(ask_prices), "asks doivent être croissants (index 0 = plus proche du prix)"
    bid_prices = [b["price"] for b in snap["bids"]]
    assert bid_prices == sorted(bid_prices, reverse=True), "bids doivent être décroissants (index 0 = plus proche du prix)"
    print("OK: ordre de génération des paliers correct (proche -> loin)")


def test_apply_noise_preserves_prices_and_reference():
    snap = ob.generate_snapshot(100.0, seed=1)
    noisy = ob.apply_noise(snap, seed=2)
    assert noisy["reference_price"] == snap["reference_price"], "apply_noise ne doit jamais changer le prix de référence"
    assert [a["price"] for a in noisy["asks"]] == [a["price"] for a in snap["asks"]], "apply_noise ne doit jamais changer les prix"
    assert [b["price"] for b in noisy["bids"]] == [b["price"] for b in snap["bids"]]
    assert [a["quantity"] for a in noisy["asks"]] != [a["quantity"] for a in snap["asks"]], "apply_noise doit changer les quantités"
    assert all(a["quantity"] > 0 for a in noisy["asks"] + noisy["bids"]), "le bruit ne doit jamais produire une quantité <= 0"
    print("OK: apply_noise anime les quantités sans jamais toucher aux prix/référence")


def test_with_cumulative_is_monotonic():
    snap = ob.generate_snapshot(100.0, seed=3)
    cum = ob.with_cumulative(snap["asks"])
    cumulatives = [c["cumulative"] for c in cum]
    assert cumulatives == sorted(cumulatives), "le cumulé doit être strictement croissant (jamais négatif)"
    expected_total = sum(a["quantity"] for a in snap["asks"])
    assert abs(cum[-1]["cumulative"] - expected_total) < 1e-9
    print("OK: with_cumulative croissant et exact")


def test_trend_bias_reflects_price_direction():
    """Cosmétique uniquement (voir la docstring du module) : une hausse de
    prix doit légèrement accentuer la profondeur bid et atténuer la
    profondeur ask, et inversement pour une baisse — sans quoi le biais de
    tendance n'aurait aucun effet visible."""
    up = ob.generate_snapshot(101.0, previous_price=100.0, seed=42)
    flat = ob.generate_snapshot(101.0, previous_price=None, seed=42)
    down = ob.generate_snapshot(99.0, previous_price=100.0, seed=42)

    bids_up = sum(b["quantity"] for b in up["bids"])
    bids_flat = sum(b["quantity"] for b in flat["bids"])
    bids_down = sum(b["quantity"] for b in down["bids"])
    assert bids_up > bids_flat > bids_down, "la profondeur bid doit croître avec une hausse de prix"

    asks_up = sum(a["quantity"] for a in up["asks"])
    asks_flat = sum(a["quantity"] for a in flat["asks"])
    asks_down = sum(a["quantity"] for a in down["asks"])
    assert asks_up < asks_flat < asks_down, "la profondeur ask doit décroître avec une hausse de prix"
    print("OK: biais directionnel cosmétique cohérent avec le sens du mouvement")


def test_extreme_price_does_not_crash_or_flip_sides():
    """Un mouvement de prix énorme (repli) ne doit jamais faire déborder le
    biais au point d'inverser le sens attendu ou de produire une quantité
    invalide — voir le clamp dans generate_snapshot."""
    snap = ob.generate_snapshot(1000.0, previous_price=1.0, seed=5)  # +99900% de mouvement
    assert all(a["quantity"] > 0 for a in snap["asks"])
    assert all(b["quantity"] > 0 for b in snap["bids"])
    assert all(a["price"] > 1000.0 for a in snap["asks"])
    assert all(b["price"] < 1000.0 for b in snap["bids"])
    print("OK: mouvement de prix extrême géré sans crash ni inversion de sens")


if __name__ == "__main__":
    test_generate_snapshot_structure()
    test_generate_snapshot_ordering()
    test_apply_noise_preserves_prices_and_reference()
    test_with_cumulative_is_monotonic()
    test_trend_bias_reflects_price_direction()
    test_extreme_price_does_not_crash_or_flip_sides()
    print("\nTOUS LES TESTS orderbook_sim SONT PASSES.")
