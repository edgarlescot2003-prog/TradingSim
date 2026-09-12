"""Contenu de l'onglet Classement : P&L de tous les utilisateurs, du
meilleur au moins bon.
"""

import streamlit as st

from . import leaderboard, theme

COLUMNS = [
    {"key": "rank", "label": "Rang", "kind": "text"},
    {"key": "username", "label": "Utilisateur", "kind": "user_link"},
    {"key": "initial_capital", "label": "Capital de départ", "kind": "eur"},
    {"key": "current_value", "label": "Valeur actuelle", "kind": "eur"},
    {"key": "pnl_eur", "label": "P&L", "kind": "signed_eur"},
    {"key": "pnl_pct", "label": "P&L %", "kind": "signed_pct"},
]


def render(current_user_id: str) -> None:
    st.subheader("Classement")
    st.caption(
        "Seul le portefeuille officiel de chaque utilisateur compte pour le classement "
        "(revalorisé en direct à chaque consultation) — ses éventuels autres portefeuilles "
        "fun/test n'y apparaissent pas. Clique sur un nom pour voir son historique détaillé "
        "d'ordres et ses métriques de performance."
    )

    with st.spinner("Calcul des positions de tous les portefeuilles officiels en direct..."):
        rankings = leaderboard.compute_rankings()
    if not rankings:
        st.info("Aucun portefeuille officiel désigné pour l'instant.")
        return

    rows = []
    for i, r in enumerate(rankings, start=1):
        username = r["username"]
        if r["user_id"] == current_user_id:
            username += "  (toi)"
        rows.append({
            "rank": f"#{i}",
            "username": username,
            "nav_username": r["username"],
            "user_id": r["user_id"],
            "initial_capital": r["initial_capital"],
            "current_value": r["current_value"],
            "pnl_eur": r["pnl_eur"],
            "pnl_pct": r["pnl_pct"],
        })

    theme.render_table(rows, COLUMNS, row_key="rank", table_key="leaderboard")
