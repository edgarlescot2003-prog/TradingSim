"""Contenu de l'onglet Portefeuille : positions (longues/courtes, avec
levier), gain/perte, poids, historique des trades, courbe de valeur et
comparaison à un indice de référence.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from . import benchmark, market_data as md, storage, theme

POSITION_COLUMNS = [
    {"key": "ticker", "label": "Ticker", "kind": "link", "mono": True},
    {"key": "name", "label": "Nom", "kind": "link"},
    {"key": "side", "label": "Sens", "kind": "side"},
    {"key": "leverage", "label": "Levier", "kind": "text"},
    {"key": "quantity", "label": "Quantité", "kind": "num", "decimals": 4},
    {"key": "avg_price", "label": "Prix moyen", "kind": "eur"},
    {"key": "current_price", "label": "Prix actuel", "kind": "eur"},
    {"key": "margin", "label": "Marge engagée", "kind": "eur"},
    {"key": "exposure", "label": "Exposition", "kind": "eur"},
    {"key": "pnl_eur", "label": "Gain/Perte", "kind": "signed_eur"},
    {"key": "pnl_pct", "label": "Gain/Perte %", "kind": "signed_pct"},
    {"key": "weight", "label": "Poids", "kind": "pct"},
    {"key": "entry_date", "label": "Entrée", "kind": "text"},
]

HISTORY_COLUMNS = [
    {"key": "date", "label": "Date", "kind": "text"},
    {"key": "ticker", "label": "Ticker", "kind": "link", "mono": True},
    {"key": "name", "label": "Nom", "kind": "link"},
    {"key": "side", "label": "Sens", "kind": "side"},
    {"key": "action", "label": "Action", "kind": "text"},
    {"key": "quantity", "label": "Quantité", "kind": "num", "decimals": 4},
    {"key": "price", "label": "Prix", "kind": "eur"},
    {"key": "leverage", "label": "Levier", "kind": "text"},
    {"key": "realized_pnl", "label": "P&L réalisé", "kind": "signed_eur"},
]


def _render_positions(portfolio, total_value: float, snapshots: list[dict]) -> None:
    for s in snapshots:
        if s["error"]:
            st.warning(
                f"Prix indisponible pour {s['position'].ticker} ({s['error']}) — "
                "prix d'achat utilisé à la place pour cette ligne."
            )

    col1, col2, col3 = st.columns(3)
    col1.metric("Valeur totale du portefeuille", f"{total_value:,.2f} €")
    col2.metric("Cash disponible", f"{portfolio.cash:,.2f} €")

    total_pnl = sum(s["pnl_eur"] for s in snapshots)
    total_pnl_base = sum(s["pnl_base_eur"] for s in snapshots)
    total_pnl_pct = (total_pnl / total_pnl_base * 100) if total_pnl_base else 0.0
    col3.metric("Gain/Perte latent total", f"{total_pnl:+,.2f} €", delta=f"{total_pnl_pct:+.2f} %")

    if not snapshots:
        st.info("Aucune position pour l'instant. Rends-toi dans l'onglet Trading pour passer ton premier ordre.")
        return

    rows = []
    for s in snapshots:
        pos = s["position"]
        rows.append({
            "ticker": pos.ticker,
            "name": pos.name,
            "side": "Long" if pos.side == "long" else "Short",
            "leverage": f"x{s['leverage']:g}" if s["leverage"] else "—",
            "quantity": pos.quantity,
            "avg_price": pos.avg_price_eur,
            "current_price": s["current_price_eur"],
            "margin": pos.margin_eur,
            "exposure": s["current_exposure_eur"],
            "pnl_eur": s["pnl_eur"],
            "pnl_pct": s["pnl_pct"],
            "weight": (s["equity_contribution_eur"] / total_value * 100) if total_value else 0.0,
            "entry_date": pos.entry_date,
        })

    theme.render_table(rows, POSITION_COLUMNS, row_key="ticker", table_key="positions")


def _render_history(portfolio) -> None:
    if not portfolio.history:
        return

    with st.expander(f"Historique des trades ({len(portfolio.history)})"):
        rows = [{
            "_row_id": f"{i}_{t.date}",  # Trade n'a pas d'id propre ; index + date suffit à être unique
            "date": t.date[:16].replace("T", " "),
            "ticker": t.ticker,
            "name": t.name,
            "side": "Long" if t.side == "long" else "Short",
            "action": t.action.capitalize(),
            "quantity": t.quantity,
            "price": t.price_eur,
            "leverage": f"x{t.leverage:g}",
            "realized_pnl": t.realized_pnl_eur,
        } for i, t in enumerate(reversed(portfolio.history))]

        theme.render_table(rows, HISTORY_COLUMNS, row_key="_row_id", table_key="history")


def _dark_layout(**overrides) -> dict:
    layout = dict(
        height=400,
        margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor=theme.PANEL,
        plot_bgcolor=theme.PANEL,
        font=dict(family=theme.FONT_SANS, color=theme.TEXT),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(gridcolor=theme.BORDER, linecolor=theme.BORDER),
        yaxis=dict(gridcolor=theme.BORDER, linecolor=theme.BORDER),
    )
    layout.update(overrides)
    return layout


def _render_performance(portfolio) -> None:
    st.subheader("Évolution de la valeur du portefeuille")

    if len(portfolio.value_history) < 2:
        st.caption(
            "Pas encore assez d'historique pour tracer une courbe : un point est enregistré "
            "par jour d'utilisation de l'application. Reviens après quelques jours d'activité "
            "pour voir l'évolution se dessiner."
        )
        return

    benchmark_label = st.selectbox("Comparer à un indice", ["Aucun"] + list(benchmark.BENCHMARKS.keys()))

    fig = go.Figure()

    if benchmark_label == "Aucun":
        df = pd.DataFrame(portfolio.value_history)
        df["date"] = pd.to_datetime(df["date"])
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["value_eur"], mode="lines+markers", name="Portefeuille",
            line=dict(color=theme.GREEN, width=2),
        ))
        fig.update_layout(**_dark_layout(yaxis_title="Valeur (€)"))
        st.plotly_chart(fig, use_container_width=True)
        return

    try:
        comparison_df = benchmark.build_comparison(portfolio.value_history, benchmark_label)
    except md.MarketDataError as e:
        st.warning(f"Comparaison indisponible : {e}")
        return

    colors = [theme.GREEN, theme.TEXT]
    for i, column in enumerate(comparison_df.columns):
        fig.add_trace(go.Scatter(
            x=comparison_df.index, y=comparison_df[column], mode="lines+markers", name=column,
            line=dict(color=colors[i % len(colors)], width=2),
        ))
    fig.update_layout(**_dark_layout(yaxis_title="Base 100"))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Les deux courbes sont indexées à 100 sur leur premier point commun, "
               "pour comparer leur performance relative.")


def _render_reset(portfolio) -> None:
    with st.expander("Réinitialiser ce portefeuille"):
        st.warning(
            "Cette action efface toutes les positions, l'historique des trades, les ordres "
            "en attente et la courbe de valeur, puis remet le cash au capital de départ "
            f"({portfolio.initial_capital:,.2f} €). Elle est irréversible."
        )
        confirmed = st.checkbox(
            "Je confirme vouloir réinitialiser ce portefeuille", key=f"confirm_reset_{portfolio.id}"
        )
        if st.button("Réinitialiser", type="primary", disabled=not confirmed, key=f"reset_btn_{portfolio.id}"):
            portfolio.reset()
            storage.save_portfolio(portfolio)
            st.success("Portefeuille réinitialisé.")
            st.rerun()


def render(portfolio, total_value: float, snapshots: list[dict]) -> None:
    _render_positions(portfolio, total_value, snapshots)
    _render_performance(portfolio)
    _render_history(portfolio)
    _render_reset(portfolio)
