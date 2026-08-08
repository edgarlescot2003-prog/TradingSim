"""Contenu de l'onglet Classement : P&L de tous les utilisateurs, du
meilleur au moins bon.
"""

import streamlit as st

from . import leaderboard, theme

COLUMNS = [
    {"key": "rank", "label": "Rang", "kind": "text"},
    {"key": "username", "label": "Utilisateur", "kind": "text"},
    {"key": "n_portfolios", "label": "Portefeuilles", "kind": "num", "decimals": 0},
    {"key": "initial_capital", "label": "Capital de départ", "kind": "eur"},
    {"key": "current_value", "label": "Valeur actuelle", "kind": "eur"},
    {"key": "pnl_eur", "label": "P&L", "kind": "signed_eur"},
    {"key": "pnl_pct", "label": "P&L %", "kind": "signed_pct"},
]


def render(current_user_id: str) -> None:
    st.subheader("Classement")
    st.caption(
        "Basé sur la dernière valeur connue du/des portefeuille(s) de chacun, mise à jour "
        "à chaque fois que son propriétaire ouvre l'application — pas en temps réel pour "
        "tout le monde à chaque consultation de ce classement."
    )

    rankings = leaderboard.compute_rankings()
    if not rankings:
        st.info("Aucun portefeuille pour l'instant.")
        return

    rows = []
    for i, r in enumerate(rankings, start=1):
        username = r["username"]
        if r["user_id"] == current_user_id:
            username += "  (toi)"
        rows.append({
            "rank": f"#{i}",
            "username": username,
            "n_portfolios": r["n_portfolios"],
            "initial_capital": r["initial_capital"],
            "current_value": r["current_value"],
            "pnl_eur": r["pnl_eur"],
            "pnl_pct": r["pnl_pct"],
        })

    theme.render_table(rows, COLUMNS, row_key="rank", table_key="leaderboard")
