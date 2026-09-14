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
from .portfolio import MAX_PORTFOLIOS_PER_USER, Portfolio

LIGHT_POSITION_COLUMNS = [
    {"key": "ticker", "label": "Symbole", "kind": "ticker_badge"},
    {"key": "name", "label": "Nom", "kind": "link"},
    {"key": "side", "label": "Sens", "kind": "text"},
    {"key": "price", "label": "Prix", "kind": "eur"},
    {"key": "quantity", "label": "Quantité", "kind": "num", "decimals": 4},
    {"key": "day_pnl", "label": "Gain du jour", "kind": "signed_eur_pct", "width": 1.8},
    {"key": "total_pnl", "label": "Gain total", "kind": "signed_eur_pct", "width": 1.8},
    {"key": "value", "label": "Valeur", "kind": "eur"},
]

# Récapitulatif compact affiché à côté de la courbe de performance (voir
# _render_positions_summary) : mêmes colonnes que LIGHT_POSITION_COLUMNS,
# réduites (pas de Nom/Gain du jour/Valeur) pour rester étroit à côté du
# graphique.
COMPACT_POSITION_COLUMNS = [
    {"key": "ticker", "label": "Symbole", "kind": "ticker_badge"},
    {"key": "side", "label": "Sens", "kind": "text"},
    {"key": "price", "label": "Prix", "kind": "eur"},
    {"key": "quantity", "label": "Quantité", "kind": "num", "decimals": 4},
    {"key": "total_pnl", "label": "Gain", "kind": "signed_eur_pct", "width": 1.6},
]

HISTORY_COLUMNS = [
    {"key": "date", "label": "Date", "kind": "text"},
    {"key": "ticker", "label": "Symbole", "kind": "ticker_badge"},
    {"key": "name", "label": "Nom", "kind": "link"},
    {"key": "side", "label": "Sens", "kind": "text"},
    {"key": "action", "label": "Action", "kind": "text"},
    {"key": "quantity", "label": "Quantité", "kind": "num", "decimals": 4},
    {"key": "price", "label": "Prix", "kind": "eur"},
    {"key": "leverage", "label": "Levier", "kind": "mono_text"},
    {"key": "realized_pnl", "label": "P&L réalisé", "kind": "signed_eur"},
    {"key": "origin", "label": "Origine", "kind": "text"},
]

# (label, jours en arrière ; "ytd" -> depuis le 1er janvier ; None -> tout
# l'historique). Filtre une plage de dates sur l'historique quotidien existant
# (un point/jour) — pas de granularité intraday, l'app n'en enregistre pas.
PERIODS = [
    ("1J", 1), ("1S", 7), ("1M", 30), ("3M", 90), ("6M", 182),
    ("YTD", "ytd"), ("1A", 365), ("5A", 1825), ("Tout", None),
]


def _display_name(p) -> str:
    """Nom d'un portefeuille pour affichage, avec le badge Officiel s'il y a
    lieu (pastilles ici, sélecteur du panneau latéral dans app.py)."""
    return p.name + (" (Officiel)" if p.is_official else "")


def _render_portfolio_pills(user_id: str) -> None:
    portfolios = st.session_state.portfolios
    active_id = st.session_state.active_id

    with st.container(key="ts_portfolio_pills", horizontal=True):
        for pid, p in portfolios.items():
            if pid == active_id:
                st.markdown(
                    f'<div class="ts-light-pill-active">{html_lib.escape(_display_name(p))}</div>',
                    unsafe_allow_html=True,
                )
            elif st.button(_display_name(p), key=f"portfolio_pill_{pid}"):
                st.session_state.active_id = pid
                auth.set_active_portfolio(user_id, pid)
                st.rerun()

        with st.popover("+ Nouveau portefeuille"):
            if len(portfolios) >= MAX_PORTFOLIOS_PER_USER:
                st.caption(f"Limite de {MAX_PORTFOLIOS_PER_USER} portefeuilles par compte atteinte.")
            else:
                with st.form("ts_new_portfolio_pill_form", border=False):
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


def _official_portfolio_progress(active_portfolio, active_total_value: float) -> dict | None:
    """Variation du portefeuille OFFICIEL de l'utilisateur depuis le début du
    concours (capital de départ -> valeur actuelle) — pas forcément celle du
    portefeuille actuellement affiché/sélectionné (voir "Portefeuille
    officiel" dans CLAUDE.md), qui peut être un portefeuille fun/test.

    Ne déclenche AUCUN appel API : si le portefeuille officiel est celui déjà
    affiché, on réutilise sa valorisation déjà calculée (active_total_value,
    gratuite) ; sinon on retombe sur le dernier point connu de sa courbe de
    valeur (déjà en mémoire, voir st.session_state.portfolios), forcément
    plus rapide à afficher mais possiblement daté de la dernière fois où ce
    portefeuille-là a été ouvert (`live=False` dans le résultat)."""
    official = next((p for p in st.session_state.portfolios.values() if p.is_official), None)
    if official is None:
        return None

    if official.id == active_portfolio.id:
        current_value, live, as_of = active_total_value, True, None
    elif official.value_history:
        last_point = official.value_history[-1]
        current_value, live, as_of = last_point["value_eur"], False, last_point["date"]
    else:
        current_value, live, as_of = official.cash, False, official.created_at

    pnl_eur = current_value - official.initial_capital
    pnl_pct = (pnl_eur / official.initial_capital * 100) if official.initial_capital else 0.0
    return {
        "portfolio_name": official.name, "initial_capital": official.initial_capital,
        "current_value": current_value, "pnl_eur": pnl_eur, "pnl_pct": pnl_pct,
        "live": live, "as_of": as_of,
    }


def _render_contest_progress(active_portfolio, active_total_value: float) -> None:
    progress = _official_portfolio_progress(active_portfolio, active_total_value)

    with st.container(key="ts_card_contest_progress"):
        st.markdown("##### Depuis le début du concours")
        if progress is None:
            st.caption("Pas encore de portefeuille officiel désigné pour ton compte.")
            return

        color = theme.LIGHT_GREEN if progress["pnl_eur"] >= 0 else theme.LIGHT_RED
        sign = "+" if progress["pnl_eur"] >= 0 else ""
        c1, c2 = st.columns([1, 2])
        c1.metric(
            f"Variation ({progress['portfolio_name']})",
            f"{sign}{progress['pnl_eur']:,.2f} €", delta=f"{sign}{progress['pnl_pct']:.2f} %",
        )
        with c2:
            initial_str = f"{progress['initial_capital']:,.2f} €"
            current_str = f"{progress['current_value']:,.2f} €"
            st.markdown(
                f"Capital de départ : {theme.mono(initial_str)} → "
                f"valeur {'actuelle' if progress['live'] else 'au dernier calcul'} : "
                f"{theme.mono(current_str, color=color)}",
                unsafe_allow_html=True,
            )
            if not progress["live"] and progress["as_of"]:
                st.caption(
                    f"Portefeuille officiel non actif en ce moment — valeur au "
                    f"{progress['as_of'][:16].replace('T', ' ')} (pas de nouvel appel de prix pour l'actualiser)."
                )


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


def _signed_eur_pct(eur_value: float, pct_value: float) -> str:
    sign = "+" if eur_value >= 0 else ""
    pct_sign = "+" if pct_value >= 0 else ""
    return f"{sign}{eur_value:,.2f} € ({pct_sign}{pct_value:.1f}%)"


def _render_position_detail(row: dict) -> None:
    """Contenu de l'expander "Détails" sous une ligne compacte mobile (voir
    theme.render_compact_list) : les champs qui n'ont pas leur place dans la
    ligne compacte (Quantité, Gain total, Valeur)."""
    total_color = theme.LIGHT_GREEN if row["total_pnl"][0] >= 0 else theme.LIGHT_RED
    quantity_str = f"{row['quantity']:g}"
    value_str = f"{row['value']:,.2f} €"
    st.markdown(
        f"Quantité : {theme.mono(quantity_str)}  \n"
        f"Gain total : {theme.mono(_signed_eur_pct(*row['total_pnl']), color=total_color)}  \n"
        f"Valeur : {theme.mono(value_str)}",
        unsafe_allow_html=True,
    )
    if st.button("Voir sur Trading", key=f"mobile_goto_position_{row['ticker']}"):
        theme.go_to_trading(row["ticker"], row["name"])


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
                "side": "Long" if pos.side == "long" else "Short",
                "price": s["current_price_eur"],
                "quantity": pos.quantity,
                "day_pnl": (s["day_pnl_eur"], s["day_pnl_pct"]),
                "total_pnl": (s["pnl_eur"], s["pnl_pct"]),
                "value": s["current_exposure_eur"],
            })
        rows.sort(key=lambda r: r["value"], reverse=True)

        with st.container(key="tslight_desktop_wrap_positions"):
            theme.render_table_light(rows, LIGHT_POSITION_COLUMNS, row_key="ticker", table_key="positions")

        compact_rows = [{
            **row,
            "primary": f"{row['price']:,.2f} €",
            "secondary": _signed_eur_pct(*row["day_pnl"]),
            "secondary_color": theme.LIGHT_GREEN if row["day_pnl"][0] >= 0 else theme.LIGHT_RED,
        } for row in rows]
        theme.render_compact_list(compact_rows, table_key="positions", detail=_render_position_detail)


def _render_history(portfolio) -> None:
    if not portfolio.history:
        return

    # Visible directement, sans repli à ouvrir (l'historique complet des
    # trades est une information consultée assez souvent pour ne pas mériter
    # un accordéon fermé par défaut).
    with st.container(key="ts_card_history"):
        st.markdown(f"##### Historique des trades ({len(portfolio.history)})")
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
            "origin": (
                "Liquidation auto" if t.is_liquidation
                else "Auto (TP/SL)" if t.tp_sl_order_id else "Manuel"
            ),
        } for i, t in enumerate(reversed(portfolio.history))]

        theme.render_table_light(rows, HISTORY_COLUMNS, row_key="_row_id", table_key="history")


def _filter_value_history(value_history: list[dict], period_label: str) -> list[dict]:
    spec = dict(PERIODS).get(period_label)
    if spec is None:
        return value_history

    now = pd.Timestamp.now()
    cutoff = pd.Timestamp(year=now.year, month=1, day=1) if spec == "ytd" else now - pd.Timedelta(days=spec)
    filtered = [p for p in value_history if pd.to_datetime(p["date"]) >= cutoff]
    return filtered or value_history


def _render_positions_summary(snapshots: list[dict]) -> None:
    """Récapitulatif compact des positions ouvertes, affiché à côté de la
    courbe de performance (voir _render_performance) plutôt qu'en dessous —
    pour que le graphique n'occupe plus toute la largeur disponible sur
    desktop. Redondant avec le tableau Positions complet plus haut sur la
    page (voir _render_positions_table) : volontaire, pour un coup d'œil
    rapide sans avoir à remonter jusqu'au graphique."""
    with st.container(key="ts_card_portfolio_positions"):
        st.markdown("##### Positions ouvertes")
        if not snapshots:
            st.caption("Aucune position ouverte.")
            return
        rows = [{
            "ticker": s["position"].ticker,
            "name": s["position"].name,
            "category": s["category"],
            "side": "Long" if s["position"].side == "long" else "Short",
            "price": s["current_price_eur"],
            "quantity": s["position"].quantity,
            "total_pnl": (s["pnl_eur"], s["pnl_pct"]),
        } for s in snapshots]
        theme.render_table_light(
            rows, COMPACT_POSITION_COLUMNS, row_key="ticker", table_key="portfolio_chart_positions",
        )


def _render_performance(portfolio, snapshots: list[dict]) -> None:
    with st.container(key="ts_card_performance"):
        st.markdown("##### Évolution de la valeur du portefeuille")

        # Conteneur dédié : ancrage CSS pour repasser en 1 colonne sur mobile
        # (voir le media query dans theme.py), le graphique gardant alors
        # toute la largeur — la densité qui justifie la colonne recap n'a de
        # sens que sur desktop. La colonne recap est rendue en premier : elle
        # doit s'afficher même si le graphique lui-même n'a pas encore assez
        # de données (portefeuille tout neuf, ci-dessous).
        with st.container(key="ts_portfolio_chart_row"):
            col_chart, col_positions = st.columns([2.3, 1])
            with col_positions:
                _render_positions_summary(snapshots)

            with col_chart:
                if len(portfolio.value_history) < 2:
                    st.caption(
                        "Pas encore assez d'historique pour tracer une courbe : un point est "
                        "enregistré par jour d'utilisation de l'application. Reviens après "
                        "quelques jours d'activité pour voir l'évolution se dessiner."
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
                    "Comparer à un indice", ["Aucun"] + list(benchmark.BENCHMARKS.keys()),
                    key="ts_benchmark_select",
                )

                fig = go.Figure()

                if benchmark_label == "Aucun":
                    df = pd.DataFrame(filtered_history)
                    df["date"] = pd.to_datetime(df["date"])
                    # Vert si la valeur a progressé sur la période affichée, rouge sinon —
                    # même principe hausse/baisse que partout ailleurs dans l'app.
                    positive = df["value_eur"].iloc[-1] >= df["value_eur"].iloc[0]
                    color = theme.LIGHT_GREEN if positive else theme.LIGHT_RED
                    fig.add_trace(go.Scatter(
                        x=df["date"], y=df["value_eur"], mode="lines", name="Portefeuille",
                        line=dict(color=color, width=2),
                        fill="tozeroy", fillgradient=theme.plotly_area_fillgradient(color),
                    ))
                    fig.update_layout(**theme.plotly_layout(yaxis_title="Valeur (€)"))
                    # autorange=False : sans ça, le remplissage tirerait l'axe jusqu'à 0 et
                    # écraserait la courbe (voir theme.plotly_area_range).
                    fig.update_yaxes(range=theme.plotly_area_range(df["value_eur"]), autorange=False)
                    st.plotly_chart(fig, use_container_width=True, config=theme.PLOTLY_CONFIG)
                    st.caption(theme.PLOTLY_ZOOM_HINT)
                    return

                try:
                    comparison_df = benchmark.build_comparison(filtered_history, benchmark_label)
                except md.MarketDataError as e:
                    st.warning(f"Comparaison indisponible : {e}")
                    return

                if comparison_df is None:
                    st.caption("Pas assez de points sur cette période pour comparer à un indice.")
                    return

                # Courbe du portefeuille : même logique vert/rouge que ci-dessus, avec
                # remplissage. La courbe de comparaison reste nette et neutre (MUTED),
                # sans remplissage, pour ne pas rivaliser visuellement avec la principale.
                portfolio_series = comparison_df["Portefeuille"]
                positive = portfolio_series.iloc[-1] >= portfolio_series.iloc[0]
                color = theme.LIGHT_GREEN if positive else theme.LIGHT_RED
                fig.add_trace(go.Scatter(
                    x=comparison_df.index, y=portfolio_series, mode="lines", name="Portefeuille",
                    line=dict(color=color, width=2),
                    fill="tozeroy", fillgradient=theme.plotly_area_fillgradient(color),
                ))
                fig.add_trace(go.Scatter(
                    x=comparison_df.index, y=comparison_df[benchmark_label], mode="lines", name=benchmark_label,
                    line=dict(color=theme.LIGHT_MUTED, width=2),
                ))
                fig.update_layout(**theme.plotly_layout(yaxis_title="Base 100"))
                fig.update_yaxes(
                    range=theme.plotly_area_range(portfolio_series, comparison_df[benchmark_label]),
                    autorange=False,
                )
                st.plotly_chart(fig, use_container_width=True, config=theme.PLOTLY_CONFIG)
                st.caption(
                    "Les deux courbes sont indexées à 100 sur leur premier point commun de la période "
                    "sélectionnée, pour comparer leur performance relative."
                )
                st.caption(theme.PLOTLY_ZOOM_HINT)


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
        if portfolio.is_official:
            st.caption(
                "Le portefeuille officiel ne peut pas être supprimé (il compte pour le classement)."
            )
        elif st.session_state.get(delete_armed_key):
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
        _render_contest_progress(portfolio, total_value)
        _render_highlights(portfolio, total_value, snapshots)
        _render_positions_table(snapshots)
        _render_performance(portfolio, snapshots)
        _render_portfolio_actions(portfolio)
        _render_history(portfolio)
