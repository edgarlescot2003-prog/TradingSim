"""Page Historique : détail chronologique des ordres et métriques de
performance/risque du portefeuille officiel d'un utilisateur, accessible en
cliquant sur son nom depuis le Classement.

Page PUBLIQUE : n'importe quel participant connecté peut consulter
l'historique détaillé et les métriques de risque de n'importe quel autre —
choix assumé pour la crédibilité/traçabilité du concours (voir la doc de
conception d'origine de cette fonctionnalité), pas à remettre en question ici.
"""

import csv
import io

import streamlit as st

from . import history, theme

COLUMNS = [
    {"key": "date", "label": "Date et heure", "kind": "text"},
    {"key": "asset", "label": "Actif", "kind": "text"},
    {"key": "action", "label": "Sens", "kind": "text"},
    {"key": "quantity", "label": "Quantité", "kind": "num", "decimals": 4},
    {"key": "price", "label": "Prix d'exécution", "kind": "eur"},
    {"key": "total", "label": "Montant total", "kind": "eur"},
    {"key": "origin", "label": "Origine", "kind": "text"},
]

CSV_HEADER = [
    "Date et heure", "Actif", "Sens", "Quantité", "Prix d'exécution (EUR)", "Montant total (EUR)", "Origine",
]


def _render_metrics(metrics: dict) -> None:
    st.markdown("##### Métriques de performance")

    if not metrics.get("available"):
        st.info(
            "Pas encore assez d'historique de valorisation pour calculer ces métriques "
            "(au moins deux jours de données sont nécessaires)."
        )
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rendement annualisé", f"{metrics['annualized_return'] * 100:+.2f} %")
    c2.metric("Volatilité annualisée", f"{metrics['annualized_volatility'] * 100:.2f} %")
    sharpe = metrics["sharpe"]
    c3.metric("Ratio de Sharpe", f"{sharpe:.2f}" if sharpe is not None else "—")
    c4.metric("Max drawdown", f"-{metrics['max_drawdown'] * 100:.2f} %")

    if not metrics["reliable"]:
        st.caption(
            f"Basé sur seulement {metrics['n_days']} jour(s) de données : ces métriques "
            "annualisées ne sont pas encore représentatives à ce stade du concours, à "
            "interpréter avec prudence."
        )
    else:
        st.caption(
            f"Calculé sur {metrics['n_days']} jours de données. Taux sans risque utilisé pour "
            f"le ratio de Sharpe : {metrics['risk_free_rate'] * 100:.2f} % par an "
            "(Euribor 3 mois, valeur fixe pour la durée du concours)."
        )


def _order_rows(trades: list[dict]) -> list[dict]:
    rows = []
    for i, t in enumerate(trades):
        rows.append({
            "_row_id": f"{i}_{t['date']}",
            "date": t["date"][:16].replace("T", " "),
            "asset": f"{t['ticker']} · {t['name']}",
            "action": theme.action_label(t["action"]),
            "quantity": t["quantity"],
            "price": t["price_eur"],
            "total": t["quantity"] * t["price_eur"],
            "origin": (
                "Liquidation auto" if t.get("is_liquidation")
                else "Auto (TP/SL)" if t.get("tp_sl_order_id") else "Manuel"
            ),
        })
    return rows


def _render_orders(trades: list[dict], username: str) -> None:
    st.markdown(f"##### Détail des ordres ({len(trades)})")

    if not trades:
        st.info("Aucun ordre passé pour l'instant sur ce portefeuille officiel.")
        return

    rows = _order_rows(trades)
    theme.render_table(rows, COLUMNS, row_key="_row_id", table_key="history_orders")

    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(CSV_HEADER)
    for r in rows:
        writer.writerow(
            [r["date"], r["asset"], r["action"], r["quantity"], r["price"], r["total"], r["origin"]]
        )

    st.download_button(
        "Exporter en CSV",
        data=csv_buffer.getvalue().encode("utf-8-sig"),
        file_name=f"historique_{username}.csv",
        mime="text/csv",
    )


def render(target_user_id: str, current_user_id: str) -> None:
    if st.button("← Retour au classement", key="history_back"):
        st.session_state.active_tab = "classement"
        st.rerun()

    detail = history.get_user_history(target_user_id)
    if detail is None:
        st.warning("Cet utilisateur n'a pas (encore) de portefeuille officiel désigné.")
        return

    title = detail["username"] + ("  (toi)" if target_user_id == current_user_id else "")
    st.subheader(f"Historique — {title}")
    st.caption(
        f"Portefeuille officiel « {detail['portfolio_name']} » — capital de départ "
        f"{detail['initial_capital']:,.2f} €. Page publique, visible par tous les participants "
        "connectés."
    )

    _render_metrics(detail["metrics"])
    _render_orders(detail["trades"], detail["username"])
