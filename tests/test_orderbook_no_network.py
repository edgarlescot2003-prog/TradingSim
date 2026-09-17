"""Test de garde EXPLICITE (demandé par le prompt d'origine du carnet
d'ordre simulé, prompt 20) : le fragment `ui_trading._render_order_book`
est PUREMENT DÉCORATIF (voir src/orderbook_sim.py) et ne doit JAMAIS
appeler la moindre fonction réseau (`market_data.get_quote`,
`market_data.get_history_with_fallback`, `kraken_data.get_quote`,
`kraken_data.get_history_with_fallback`, `ui_trading._fetch_chart_history`)
— seulement lire `st.session_state.trading_price_eur`, déjà déposé par le
fragment prix (`_render_price_and_chart`).

Ce test mocke ces fonctions avec un "tripwire" qui fait échouer le test
IMMÉDIATEMENT si l'une d'elles est appelée pendant le rendu ou le
rafraîchissement du carnet — sur plusieurs "ticks" simulés (plusieurs
`AppTest.run()`), y compris un tick où le prix caché change entre-temps
(le cas qui déclenche une RÉGÉNÉRATION complète des niveaux, pas juste une
animation de bruit) — pour détecter tout de suite une régression future si
un prompt ultérieur reconnecte ce carnet à une vraie source par erreur.

Exécutable directement : python tests/test_orderbook_no_network.py
"""
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit.testing.v1 import AppTest


def _network_forbidden_app():
    # AppTest.from_function ré-exécute le CODE SOURCE de cette fonction dans
    # un espace de noms isolé (un fichier temporaire, voir la trace en cas
    # d'erreur) : les imports du fichier de test englobant (patch, sys.path)
    # ne sont PAS repris automatiquement, d'où ces imports refaits ici — le
    # sys.path modifié en tête de ce fichier de test reste lui valide (même
    # process Python, exec() dans un module différent, pas un sous-processus).
    from unittest.mock import patch

    import streamlit as st
    from src.portfolio import Portfolio
    from src import ui_trading, db, market_data, kraken_data, storage, tp_sl

    def _tripwire(qualified_name):
        def _raise(*args, **kwargs):
            raise AssertionError(
                f"APPEL RÉSEAU INTERDIT pendant le rendu du carnet d'ordre (purement "
                f"décoratif) : {qualified_name}() a été appelée."
            )
        return _raise

    # Patchs PERSISTANTS (jamais stoppés, .start() sans .stop()) : un
    # rerun scopé au fragment ne réexécute pas forcément ce bloc de code
    # (voir la découverte du prompt 17 sur les fragments Streamlit), donc
    # un simple `with patch(...):` autour du premier appel ne protégerait
    # pas les ticks suivants du fragment carnet.
    if not getattr(db, "_ts_orderbook_guard_patched", False):
        patch.object(market_data, "get_quote", _tripwire("market_data.get_quote")).start()
        patch.object(market_data, "get_history_with_fallback", _tripwire("market_data.get_history_with_fallback")).start()
        # kraken_data n'a pas de get_quote (Kraken ne sert jamais de prix
        # courant dans cette app, seulement l'historique intrajournalier des
        # graphiques — voir CLAUDE.md) : seul get_history_with_fallback existe.
        patch.object(kraken_data, "get_history_with_fallback", _tripwire("kraken_data.get_history_with_fallback")).start()
        patch.object(ui_trading, "_fetch_chart_history", _tripwire("ui_trading._fetch_chart_history")).start()
        db._ts_orderbook_guard_patched = True

    if "portfolio" not in st.session_state:
        st.session_state["portfolio"] = Portfolio(initial_capital=10000.0, cash=10000.0)
        st.session_state["user_id"] = "test-user-orderbook-guard"
        # Simule ce que _render_price_and_chart (le VRAI fragment prix,
        # jamais appelé dans ce test) aurait déjà déposé en cache — le
        # carnet ne doit lire QUE cette valeur, jamais la recalculer.
        st.session_state["trading_price_eur"] = 150.0

    ui_trading._render_order_book("AAPL")


def test_no_network_calls_across_multiple_ticks():
    """Simule plusieurs rafraîchissements successifs du fragment carnet
    (comme le ferait son run_every en conditions réelles) : le prix caché
    NE CHANGE PAS entre les ticks (cas "apply_noise", le plus fréquent)."""
    at = AppTest.from_function(_network_forbidden_app, default_timeout=30)
    for tick in range(6):
        at.run()
        assert not at.exception, f"Exception au tick {tick}: {at.exception}"
    print("OK: 6 ticks simulés (prix caché stable) — aucun appel réseau, aucune exception")


def test_no_network_calls_when_cached_price_changes():
    """Même garde, mais en simulant un changement du prix caché entre deux
    ticks — le cas qui déclenche generate_snapshot (régénération complète)
    plutôt qu'apply_noise. Toujours aucun appel réseau attendu : le nouveau
    prix est simplement LU depuis session_state, jamais recalculé ici."""
    at = AppTest.from_function(_network_forbidden_app, default_timeout=30)
    at.run()
    assert not at.exception, f"Exception au 1er tick: {at.exception}"

    at.session_state["trading_price_eur"] = 151.75
    at.run()
    assert not at.exception, f"Exception après changement du prix caché: {at.exception}"

    at.session_state["trading_price_eur"] = None  # cas "carnet indisponible"
    at.run()
    assert not at.exception, f"Exception avec prix caché absent: {at.exception}"
    print("OK: changement du prix caché (et absence de prix) simulés — toujours aucun appel réseau")


if __name__ == "__main__":
    test_no_network_calls_across_multiple_ticks()
    test_no_network_calls_when_cached_price_changes()
    print("\nTOUS LES TESTS DE GARDE (carnet d'ordre, zéro appel réseau) SONT PASSES.")
