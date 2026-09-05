"""Contenu de l'onglet Portefeuille : thème clair scopé (voir theme.inject_light
et theme.render_table_light), inspiré de l'interface "portefeuille" de Google
Finance — pastilles de portefeuille en haut de page, carte "Points clés"
(gain du jour, gain total, répartition par catégorie d'actif), tableau de
positions simplifié, courbe de valeur avec filtre de période + comparaison à
un indice de référence, historique des trades et réinitialisation.

Le sélecteur de portefeuille du panneau latéral (app.py) reste inchangé et
continue de fonctionner en parallèle : les pastilles ci-dessous ne sont
qu'une seconde façon, plus visible, de changer de portefeuille depuis cette
page (utile tant que les autres onglets n'ont pas leur propre refonte).
"""

import html as html_lib

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from . import auth, benchmark, market_data as md, storage, theme, valuation
from .portfolio import Portfolio

LIGHT_POSITION_COLUMNS = [
    {"key": "ticker", "label": "Symbole", "kind": "ticker_badge"},
    {"key": "name", "label": "Nom", "kind": "link"},
    {"key": "price", "label": "Prix", "kind": "eur"},
    {"key": "quantity", "label": "Quantité", "kind": "num", "decimals": 4},
    {"key": "day_pnl_eur", "label": "Gain du jour", "kind": "signed_eur"},
    {"key": "day_pnl_pct", "label": "Gain du jour %", "kind": "signed_pct"},
    {"key": "value", "label": "Valeur", "kind": "eur"},
]

HISTORY_COLUMNS = [
    {"key": "date", "label": "Date", "kind": "text"},
    {"key": "ticker", "label": "Symbole", "kind": "ticker_badge"},
    {"key": "name", "label": "Nom", "kind": "link"},
    {"key": "side", "label": "Sens", "kind": "text"},
    {"key": "action", "label": "Action", "kind": "text"},
    {"key": "quantity", "label": "Quantité", "kind": "num", "decimals": 4},
    {"key": "price", "label": "Prix", "kind": "eur"},
    {"key": "leverage", "label": "Levier", "kind": "text"},
    {"key": "realized_pnl", "label": "P&L réalisé", "kind": "signed_eur"},
]

# (label, jours en arrière ; "ytd" -> depuis le 1er janvier ; None -> tout
# l'historique). Filtre une plage de dates sur l'historique quotidien existant
# (un point/jour) — pas de granularité intraday, l'app n'en enregistre pas.
PERIODS = [
    ("1J", 1), ("1S", 7), ("1M", 30), ("3M", 90), ("6M", 182),
    ("YTD", "ytd"), ("1A", 365), ("5A", 1825), ("Tout", None),
]


def _render_portfolio_pills(user_id: str) -> None:
    portfolios = st.session_state.portfolios
    active_id = st.session_state.active_id

    with st.container(key="ts_portfolio_pills", horizontal=True):
        for pid, p in portfolios.items():
            if pid == active_id:
                st.markdown(
                    f'<div class="ts-light-pill-active">{html_lib.escape(p.name)}</div>',
                    unsafe_allow_html=True,
                )
            elif st.button(p.name, key=f"portfolio_pill_{pid}"):
                st.session_state.active_id = pid
                auth.set_active_portfolio(user_id, pid)
                st.rerun()

        with st.popover("+ Nouveau portefeuille"):
            with st.form("ts_new_portfolio_pill_form"):
                new_name = st.text_input("Nom", value="Nouveau portefeuille")
                new_capital = st.number_input(
                    "Capital de départ (€)", min_value=1.0, value=10_000.0, step=100.0,
                )
                submitted = st.form_submit_button("Créer", type="primary")
            if submitted:
                new_portfolio = Portfolio(
                    name=new_name or "Nouveau portefeuille", initial_capital=new_capital, cash=new_capital,
                )
                storage.save_portfolio(new_portfolio)
                portfolios[new_portfolio.id] = new_portfolio
                st.session_state.active_id = new_portfolio.id
                auth.set_active_portfolio(user_id, new_portfolio.id)
                st.rerun()


def _render_highlights(portfolio, total_value: float, snapshots: list[dict]) -> None:
    day_pnl_eur, day_pnl_pct = valuation.daily_pnl(portfolio, total_value)
    total_pnl_eur = sum(s["pnl_eur"] for s in snapshots)
    total_pnl_base = sum(s["pnl_base_eur"] for s in snapshots)
    total_pnl_pct = (total_pnl_eur / total_pnl_base * 100) if total_pnl_base else 0.0

    with st.container(key="ts_card_highlights"):
        st.markdown("##### Points clés du portefeuille")
        c1, c2, c3 = st.columns([1, 1, 1.4])
        c1.metric("Gain du jour", f"{day_pnl_eur:+,.2f} €", delta=f"{day_pnl_pct:+.2f} %")
        c2.metric("Gain total", f"{total_pnl_eur:+,.2f} €", delta=f"{total_pnl_pct:+.2f} %")

        with c3:
            st.markdown(
                '<div class="ts-light-col-label">Répartition par catégorie</div>',
                unsafe_allow_html=True,
            )
            by_category: dict[str, float] = {}
            for s in snapshots:
                by_category[s["category"]] = by_category.get(s["category"], 0.0) + s["current_exposure_eur"]

            if not by_category or not total_value:
                st.caption("Pas encore de position.")
            else:
                for label in ("Actions", "Crypto", "Indices/ETF", "Autres"):
                    amount = by_category.get(label, 0.0)
                    if amount <= 0:
                        continue
                    pct = amount / total_value * 100
                    color = theme.CATEGORY_COLORS.get(label, theme.LIGHT_FAINT)
                    st.markdown(
                        f"""
                        <div class="ts-cat-row">
                            <span class="ts-cat-dot" style="background:{color}"></span>
                            <span class="ts-cat-label">{html_lib.escape(label)}</span>
                            <span class="ts-cat-pct">{pct:.1f}%</span>
                        </div>
                        <div class="ts-cat-bar-track">
                            <div class="ts-cat-bar-fill" style="width:{min(pct, 100):.1f}%;background:{color}"></div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )


def _render_positions_table(snapshots: list[dict]) -> None:
    with st.container(key="ts_card_positions"):
        st.markdown("##### Positions")

        for s in snapshots:
            if s["error"]:
                st.warning(
                    f"Prix indisponible pour {s['position'].ticker} ({s['error']}) — "
                    "prix d'achat utilisé à la place pour cette ligne."
                )

        if not snapshots:
            st.info("Aucune position pour l'instant. Rends-toi dans l'onglet Trading pour passer ton premier ordre.")
            return

        rows = []
        for s in snapshots:
            pos = s["position"]
            rows.append({
                "ticker": pos.ticker,
                "name": pos.name,
                "category": s["category"],
                "price": s["current_price_eur"],
                "quantity": pos.quantity,
                "day_pnl_eur": s["day_pnl_eur"],
                "day_pnl_pct": s["day_pnl_pct"],
                "value": s["current_exposure_eur"],
            })
        rows.sort(key=lambda r: r["value"], reverse=True)

        theme.render_table_light(rows, LIGHT_POSITION_COLUMNS, row_key="ticker", table_key="positions")


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

        theme.render_table_light(rows, HISTORY_COLUMNS, row_key="_row_id", table_key="history")


def _light_layout(**overrides) -> dict:
    layout = dict(
        height=380,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor=theme.LIGHT_SURFACE,
        plot_bgcolor=theme.LIGHT_SURFACE,
        font=dict(family=theme.FONT_SANS, color=theme.LIGHT_TEXT),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(gridcolor=theme.LIGHT_GRIDLINE, linecolor=theme.LIGHT_GRIDLINE),
        yaxis=dict(gridcolor=theme.LIGHT_GRIDLINE, linecolor=theme.LIGHT_GRIDLINE),
    )
    layout.update(overrides)
    return layout


def _filter_value_history(value_history: list[dict], period_label: str) -> list[dict]:
    spec = dict(PERIODS).get(period_label)
    if spec is None:
        return value_history

    now = pd.Timestamp.now()
    cutoff = pd.Timestamp(year=now.year, month=1, day=1) if spec == "ytd" else now - pd.Timedelta(days=spec)
    filtered = [p for p in value_history if pd.to_datetime(p["date"]) >= cutoff]
    return filtered or value_history


def _render_performance(portfolio) -> None:
    with st.container(key="ts_card_performance"):
        st.markdown("##### Évolution de la valeur du portefeuille")

        if len(portfolio.value_history) < 2:
            st.caption(
                "Pas encore assez d'historique pour tracer une courbe : un point est enregistré "
                "par jour d'utilisation de l'application. Reviens après quelques jours d'activité "
                "pour voir l'évolution se dessiner."
            )
            return

        period_label = st.session_state.get("ts_portfolio_period", "Tout")
        with st.container(key="ts_period_pills", horizontal=True):
            for label, _ in PERIODS:
                if label == period_label:
                    st.markdown(f'<div class="ts-period-active">{label}</div>', unsafe_allow_html=True)
                elif st.button(label, key=f"ts_period_{label}"):
                    st.session_state.ts_portfolio_period = label
                    st.rerun()

        filtered_history = _filter_value_history(portfolio.value_history, period_label)
        if len(filtered_history) < 2:
            st.caption("Pas assez de points sur cette période pour tracer une courbe.")
            return

        benchmark_label = st.selectbox(
            "Comparer à un indice", ["Aucun"] + list(benchmark.BENCHMARKS.keys()), key="ts_benchmark_select",
        )

        fig = go.Figure()

        if benchmark_label == "Aucun":
            df = pd.DataFrame(filtered_history)
            df["date"] = pd.to_datetime(df["date"])
            fig.add_trace(go.Scatter(
                x=df["date"], y=df["value_eur"], mode="lines", name="Portefeuille",
                line=dict(color=theme.LIGHT_BLUE, width=2),
            ))
            fig.update_layout(**_light_layout(yaxis_title="Valeur (€)"))
            st.plotly_chart(fig, use_container_width=True)
            return

        try:
            comparison_df = benchmark.build_comparison(filtered_history, benchmark_label)
        except md.MarketDataError as e:
            st.warning(f"Comparaison indisponible : {e}")
            return

        if comparison_df is None:
            st.caption("Pas assez de points sur cette période pour comparer à un indice.")
            return

        colors = [theme.LIGHT_BLUE, theme.LIGHT_FAINT]
        for i, column in enumerate(comparison_df.columns):
            fig.add_trace(go.Scatter(
                x=comparison_df.index, y=comparison_df[column], mode="lines", name=column,
                line=dict(color=colors[i % len(colors)], width=2),
            ))
        fig.update_layout(**_light_layout(yaxis_title="Base 100"))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "Les deux courbes sont indexées à 100 sur leur premier point commun de la période "
            "sélectionnée, pour comparer leur performance relative."
        )


def _render_portfolio_actions(portfolio) -> None:
    """Réinitialiser / supprimer ce portefeuille : deux boutons simples, pas
    de menu déroulant. Chaque bouton demande une confirmation en un second
    clic (son propre libellé change) plutôt qu'une case à cocher séparée ou
    un expander."""
    reset_armed_key = f"confirm_reset_{portfolio.id}"
    delete_armed_key = f"confirm_delete_{portfolio.id}"

    col1, col2 = st.columns(2)

    with col1:
        if st.session_state.get(reset_armed_key):
            st.caption("Remet le cash au capital de départ et efface positions/historique.")
            if st.button("Confirmer la réinitialisation", type="primary", key=f"reset_btn_{portfolio.id}"):
                portfolio.reset()
                storage.save_portfolio(portfolio)
                st.session_state[reset_armed_key] = False
                st.success("Portefeuille réinitialisé.")
                st.rerun()
        else:
            if st.button("Réinitialiser ce portefeuille", key=f"reset_btn_{portfolio.id}"):
                st.session_state[reset_armed_key] = True
                st.rerun()

    with col2:
        if st.session_state.get(delete_armed_key):
            st.caption(f"Supprime définitivement « {portfolio.name} » et toutes ses données.")
            if st.button("Confirmer la suppression", type="primary", key=f"delete_btn_{portfolio.id}"):
                storage.delete_portfolio(portfolio.id)
                portfolios = st.session_state.portfolios
                portfolios.pop(portfolio.id, None)
                remaining_id = next(iter(portfolios), None)
                st.session_state.active_id = remaining_id
                if remaining_id is not None:
                    auth.set_active_portfolio(st.session_state.user_id, remaining_id)
                st.session_state[delete_armed_key] = False
                st.success("Portefeuille supprimé.")
                st.rerun()
        else:
            if st.button("Supprimer ce portefeuille", key=f"delete_btn_{portfolio.id}"):
                st.session_state[delete_armed_key] = True
                st.rerun()


def render(portfolio, total_value: float, snapshots: list[dict]) -> None:
    theme.inject_light()
    with st.container(key="ts_light"):
        _render_portfolio_pills(st.session_state.user_id)
        _render_highlights(portfolio, total_value, snapshots)
        _render_positions_table(snapshots)
        _render_performance(portfolio)
        _render_portfolio_actions(portfolio)
        _render_history(portfolio)
