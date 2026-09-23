"""Tableau de bord Admin News, alimenté uniquement par Supabase."""

import streamlit as st

from . import admin_news, theme

ASSET_COLUMNS = [
    {"key": "name", "label": "Actif", "kind": "text"},
    {"key": "ticker", "label": "Ticker", "kind": "ticker_badge"},
    {"key": "category", "label": "Catégorie", "kind": "text"},
    {"key": "price_eur", "label": "Prix actuel", "kind": "eur"},
    {"key": "change_pct", "label": "Variation", "kind": "signed_pct"},
]

PARTICIPANT_COLUMNS = [
    {"key": "username", "label": "Participant", "kind": "text"},
    {"key": "current_value", "label": "Valeur actuelle", "kind": "eur"},
    {"key": "change_pct", "label": "Progression", "kind": "signed_pct"},
]

TRADE_COLUMNS = [
    {"key": "date", "label": "Date", "kind": "text"},
    {"key": "username", "label": "Participant", "kind": "text"},
    {"key": "ticker", "label": "Ticker", "kind": "ticker_badge"},
    {"key": "action", "label": "Action", "kind": "text"},
    {"key": "quantity", "label": "Quantité", "kind": "num", "decimals": 4},
    {"key": "price_eur", "label": "Prix", "kind": "eur"},
    {"key": "volume_eur", "label": "Volume", "kind": "eur"},
    {"key": "importance", "label": "Signal", "kind": "text"},
]


def _asset_rows(rows: list[dict], descending: bool) -> list[dict]:
    return sorted(rows, key=lambda row: row["change_pct"], reverse=descending)[:5]


def _participant_rows(rows: list[dict], descending: bool) -> list[dict]:
    return sorted(rows, key=lambda row: row["change_pct"], reverse=descending)[:5]


def _render_asset_section(title: str, rows: list[dict], descending: bool) -> None:
    st.markdown(f"**{title}**")
    selected = _asset_rows(rows, descending)
    if selected:
        theme.render_table(selected, ASSET_COLUMNS, row_key="ticker", table_key=title.lower().replace(" ", "_"))
    else:
        st.caption("Pas encore assez de snapshots pour cette période.")


def _render_participant_section(title: str, rows: list[dict]) -> None:
    st.markdown(f"**{title}**")
    selected = _participant_rows(rows, True)
    if selected:
        theme.render_table(selected, PARTICIPANT_COLUMNS, row_key="portfolio_id", table_key=title.lower().replace(" ", "_"))
    else:
        st.caption("Pas encore assez de snapshots pour cette période.")


def render() -> None:
    st.subheader("Admin News")
    st.caption(
        "Tableau de bord réservé à l'administration. Les variations et les trades "
        "proviennent des snapshots enregistrés par le workflow périodique; aucun appel "
        "de marché n'est effectué ici."
    )

    with st.spinner("Lecture des snapshots enregistrés..."):
        dashboard = admin_news.load_dashboard()

    st.markdown("### Actifs")
    st.caption("Top 5 des mouvements parmi les actifs suivis par l'application.")
    with st.container(horizontal=True):
        _render_asset_section("Hausses 24h", dashboard["assets_24h"], True)
        _render_asset_section("Baisses 24h", dashboard["assets_24h"], False)
    with st.container(horizontal=True):
        _render_asset_section("Hausses 7j", dashboard["assets_7d"], True)
        _render_asset_section("Baisses 7j", dashboard["assets_7d"], False)

    st.markdown("### Participants")
    st.caption("Portefeuilles officiels uniquement; les variations sont calculées en pourcentage.")
    with st.container(horizontal=True):
        _render_participant_section("Progressions 24h", dashboard["participants_24h"])
        _render_participant_section("Progressions 7j", dashboard["participants_7d"])

    st.markdown("### Trades des dernières 24h")
    trades = dashboard["trades"]
    if trades:
        average_volume = sum(row["volume_eur"] for row in trades) / len(trades)
        for row in trades:
            row["importance"] = "Gros volume" if row["volume_eur"] >= average_volume * 1.5 else ""
        st.caption("Les volumes au moins 1,5 fois supérieurs à la moyenne sont signalés comme importants.")
        theme.render_table(trades, TRADE_COLUMNS, row_key="id", table_key="admin_news_trades")
    else:
        st.info("Aucun trade enregistré dans les dernières 24 heures.")