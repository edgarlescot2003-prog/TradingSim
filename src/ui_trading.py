"""Contenu de l'onglet Trading : thème clair scopé (voir theme.inject_light,
comme l'onglet Portefeuille) — page d'accueil SANS aucun prix (recherche,
recherches récentes, cases de catégories), pages de liste par catégorie (prix
indicatifs lus en base), recherche unifiée avec historique par
utilisateur, fiche prix/graphique (seul endroit en direct : fragment
actualisé selon la durée de cache de la classe d'actif, pause après
inactivité — voir live_quote.py), formulaire d'ordre avec récapitulatif
(coût/marge/liquidation/simulation P&L) exécuté au prix affiché.

Layout de la fiche d'un actif sélectionné, façon Hyperliquid (voir
ts_trading_layout_row dans render()) : 3 colonnes sur desktop large (>=1100px,
graphique à gauche, carnet d'ordre simulé — prompt 20, purement décoratif,
voir _render_order_book/src/orderbook_sim.py — au centre en colonne fine,
panneau d'ordre + TP/SL à droite, non sticky), carnet masqué entre 641px et
1099px (graphique + panneau restent côte à côte, sans compression), 1 colonne
empilée en dessous de 640px (media query dans theme.py). Les explications
pédagogiques (_render_explanations) vivent dans une zone séparée sous ce
bloc, pas dans le panneau d'ordre lui-même.
"""

import html as html_lib
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from . import asset_universe
from . import daily_snapshot
from . import db
from . import kraken_data
from . import live_quote
from . import market_data as md
from . import market_store
from . import orderbook_sim
from . import search_history
from . import storage
from . import theme
from . import tp_sl
from . import trading_nav_config
from . import ui_cards
from . import ui_trading_nav
from . import valuation

# -- Univers d'actifs de l'accueil (voir asset_universe.py) -----------------
# Suggestions par défaut de la recherche quand l'utilisateur n'a pas encore
# d'historique de recherche (ticker, nom, catégorie — pour le badge coloré).
DEFAULT_SUGGESTIONS = (
    [(t, n, asset_universe.ACTIONS) for t, n in asset_universe.ASSETS_BY_CATEGORY[asset_universe.ACTIONS][:4]]
    + [(t, n, asset_universe.CRYPTO) for t, n in asset_universe.ASSETS_BY_CATEGORY[asset_universe.CRYPTO][:2]]
)

SEARCH_RESULT_COLUMNS = [
    {"key": "ticker", "label": "Symbole", "kind": "ticker_badge"},
    {"key": "name", "label": "Nom", "kind": "link"},
]

MAX_LEVERAGE = 20.0

# Durée d'affichage du pop-up de confirmation d'ordre (prompt 21, point 1 —
# voir theme.render_order_confirmation_popup). Un simple st.success() ici
# disparaîtrait quasi instantanément à cause du st.rerun() qui suit
# immédiatement l'action (rafraîchir positions/cash...) : le message transite
# donc par st.session_state["_order_confirmation_message"], posé ICI juste
# avant le rerun, et n'est affiché qu'au tout début du prochain rendu de
# _render_order_panel (voir ce fragment) — jamais au moment de l'action.
ORDER_CONFIRMATION_POPUP_SECONDS = 5

# Largeur (px) des champs numériques du formulaire d'ordre (Levier, Montant
# à risquer, Quantité, Prix cible) : sans elle, st.number_input s'étire par
# défaut sur toute la largeur de sa colonne, laissant beaucoup de vide
# inutile autour d'une valeur qui tient sur quelques caractères.
ORDER_INPUT_WIDTH = 220

# Nombre max de paliers TP/SL proposables directement dans le formulaire
# d'ordre (voir _render_tp_sl_at_order_form) : garde le formulaire gérable ;
# des paliers supplémentaires restent ajoutables après coup depuis la fiche
# de la position (section Take Profit / Stop Loss, sans cette limite).
MAX_ORDER_TP_SL_TIERS = 3
TP_SL_KIND_LABELS = [tp_sl.KIND_LABELS[tp_sl.KIND_TAKE_PROFIT], tp_sl.KIND_LABELS[tp_sl.KIND_STOP_LOSS]]

# Période affichée -> intervalle demandé. Poussé au maximum autorisé par les
# APIs ; get_history_with_fallback (Yahoo) / kraken_data (crypto) se rabattent
# automatiquement sur un intervalle moins précis si celui-ci dépasse la
# fenêtre disponible pour la plage demandée.
PERIOD_INTERVAL = {
    "1J": "1m",
    "1S": "5m",
    "1M": "15m",
    "3M": "1h",
    "6M": "1h",
    "YTD": "1h",
    "1A": "1h",
    "5A": "1d",
    "Tout": "1d",
}

# Ordres qui ouvrent/augmentent une position (par opposition à ceux qui la
# réduisent/ferment) : seuls ceux-là ont un levier à choisir.
OPENING_ORDER_TYPES = (
    "Acheter (position longue)", "Acheter plus",
    "Vendre à découvert (position courte)", "Vendre plus à découvert",
)
LONG_OPENING_TYPES = ("Acheter (position longue)", "Acheter plus")

# Libellé affiché -> action canonique utilisée par Portfolio/order_engine.
ACTION_BY_ORDER_TYPE = {
    "Acheter (position longue)": "achat",
    "Acheter plus": "achat",
    "Vendre à découvert (position courte)": "ouverture short",
    "Vendre plus à découvert": "ouverture short",
}


# -- Accueil : cases de catégories, SANS aucun prix -------------------------
# L'accueil ne fait plus AUCUNE requête Yahoo/Kraken (avant : ~29 requêtes
# history_1mo à chaque chargement à froid, la rafale qui a précédé le 429 du
# 24/09). Les prix vivent désormais sur les pages de liste (prix indicatifs
# lus en base, voir _render_category_list) et sur la fiche actif (seul
# endroit en direct). Garde : tests/test_trading_home_no_network.py.

LIST_ROW_COLUMNS = [
    {"key": "ticker", "label": "Symbole", "kind": "ticker_badge", "width": 0.9},
    {"key": "name", "label": "Actif", "kind": "link", "width": 1.5},
    {"key": "place", "label": "Pays / zone", "kind": "text", "width": 1.0},
    {"key": "price_html", "label": "Prix indicatif", "kind": "html", "width": 1.3},
    {"key": "change_html", "label": "Var. 30 j", "kind": "html", "width": 1.1},
]
LIST_PAGE_SIZE = 20
_LIST_SORTS = ["Nom (A → Z)", "Variation 30 j : meilleure d'abord", "Variation 30 j : moins bonne d'abord"]


def _format_list_price(price: float | None, currency: str | None) -> str | None:
    if price is None:
        return None
    decimals = 4 if price < 10 else 2  # paires de devises (1,1234) comme actions
    return f"{price:,.{decimals}f} {currency or ''}".strip()


def _age_label(seconds: float) -> str:
    if seconds < 3600:
        return f"{max(1, round(seconds / 60))} min"
    return f"{round(seconds / 3600)} h"


def _place_label(row: dict) -> str:
    country, zone = row.get("country"), row.get("zone")
    if country in trading_nav_config.PAYS:
        return trading_nav_config.PAYS[country]["nom"]
    if zone in trading_nav_config.ZONES:
        return trading_nav_config.ZONES[zone]["nom"]
    return "—"


def _sort_and_filter(rows: list[dict], query: str, sort: str) -> list[dict]:
    query = (query or "").strip().lower()
    if query:
        rows = [r for r in rows if query in r["ticker"].lower() or query in r["name"].lower()]
    if sort == _LIST_SORTS[0]:
        return sorted(rows, key=lambda r: r["name"].lower())
    best_first = sort == _LIST_SORTS[1]
    # Actifs sans variation connue toujours en fin de liste.
    known = sorted((r for r in rows if r.get("change_30d_pct") is not None),
                   key=lambda r: r["change_30d_pct"], reverse=best_first)
    return known + [r for r in rows if r.get("change_30d_pct") is None]


def _render_category_list(category: str, zone: str | None = None, country: str | None = None,
                          group: str | None = None) -> None:
    """Page de liste d'une catégorie : prix INDICATIFS lus en base
    (daily_snapshot, clôture de la veille + variation 30 j), JAMAIS de
    requête Yahoo/Kraken depuis l'affichage. Les lignes de plus de 24 h
    sont rafraîchies en arrière-plan (daily_snapshot.start_refresh_if_due),
    la liste s'affiche immédiatement avec ce qui est en base. Filtre et tri
    calculés localement sur les lignes lues (aucune requête)."""
    label = asset_universe.CATEGORY_LABELS.get(category, category)
    ui_trading_nav.render_breadcrumb(ui_trading_nav.current())
    if country:
        title = trading_nav_config.PAYS[country]["nom"]
    elif zone:
        title = trading_nav_config.WIDE_ZONE_LABELS[zone]
    else:
        title = ui_trading_nav.group_label(category, group) or label
    ui_cards.page_header(label, title)

    snapshot_rows = daily_snapshot.list_assets(category, zone=zone, country=country)
    if snapshot_rows is not None and group:
        snapshot_rows = [r for r in snapshot_rows if ui_trading_nav.group_contains(category, group, r["ticker"])]
    if snapshot_rows is None:
        # Jamais silencieux (incident du 25/09) : une fois par catégorie et par session.
        if st.session_state.get("_list_unavailable_logged") != category:
            st.session_state["_list_unavailable_logged"] = category
            market_store.log_event("daily_list_unavailable", category=category,
                                   store_configured=market_store.is_configured())
        # Base indisponible : liste des actifs sans prix, fiche toujours accessible.
        st.caption("Prix indicatifs momentanément indisponibles. Ouvre la fiche d'un actif pour son prix en direct.")
        snapshot_rows = [{"ticker": t, "name": n, "category": category}
                         for t, n in asset_universe.ASSETS_BY_CATEGORY.get(category, [])
                         if ui_trading_nav.group_contains(category, group, t)]
        status = "unavailable"
    else:
        status = daily_snapshot.start_refresh_if_due(category, rows=snapshot_rows)
    refreshing = status in ("started", "busy") and daily_snapshot.is_refreshing(category)

    now = time.time()
    filled = [r for r in snapshot_rows if r.get("close_price") is not None]
    if filled:
        dates = sorted({r["as_of_date"] for r in filled})
        fmt = [datetime.fromisoformat(d).strftime("%d/%m") for d in (dates[0], dates[-1])]
        closing = f"Clôture du {fmt[0]}" if fmt[0] == fmt[1] else f"Clôtures du {fmt[0]} au {fmt[-1]}"
        oldest = min(daily_snapshot.from_iso(r["updated_at"]) or now for r in filled)
        st.markdown(ui_cards.status_badge(f"{closing} · mis à jour il y a {_age_label(now - oldest)}"),
                    unsafe_allow_html=True)
    if len(filled) < len(snapshot_rows) and status != "unavailable":
        st.caption("Certaines données sont en cours de chargement (—).")
    if refreshing:
        ui_cards.state_banner("updating", "Les prix manquants apparaissent au fur et à mesure (quelques secondes).",
                              title="Liste en cours de mise à jour")
        if st.button("Afficher les derniers prix", key="reload_category_list"):
            st.rerun()

    table_key = f"compact_category_{theme._safe_key_part(category)}"
    col_filter, col_sort = st.columns([2, 1])
    query = col_filter.text_input("Filtrer", key=f"list_filter_{table_key}", label_visibility="collapsed",
                                  placeholder="Filtrer par nom ou ticker")
    sort = col_sort.selectbox("Trier", _LIST_SORTS, key=f"list_sort_{table_key}", label_visibility="collapsed")
    ordered = _sort_and_filter(snapshot_rows, query, sort)
    limit_key = f"list_limit_{table_key}"
    limit = st.session_state.get(limit_key, LIST_PAGE_SIZE)
    shown = ordered[:limit]

    def _price_html(r: dict) -> str:
        price = _format_list_price(r.get("close_price"), r.get("currency"))
        if price:
            return f'<span class="ts-light-num">{html_lib.escape(price)}</span>'
        return ui_cards.skeleton() if refreshing else "—"

    rows = [{
        "ticker": r["ticker"],
        "name": r["name"],
        "category": category,
        "place": _place_label(r),
        "price": _format_list_price(r.get("close_price"), r.get("currency")),
        "price_html": _price_html(r),
        "change_30d_pct": r.get("change_30d_pct"),
        "change_html": ui_cards.change_pill(r.get("change_30d_pct")) if r.get("change_30d_pct") is not None else "—",
    } for r in shown]
    if not rows:
        st.caption("Aucun actif ne correspond à ce filtre.")
    with st.container(key=f"tslight_desktop_wrap_{table_key}"):
        theme.render_table_light(rows, LIST_ROW_COLUMNS, row_key="ticker", table_key=table_key)
    compact_rows = [{
        **row,
        "primary": row["price"] or "—",
        "secondary": (f"{'▲ +' if row['change_30d_pct'] >= 0 else '▼ −'}"
                      f"{ui_cards._fr_number(row['change_30d_pct'], 2)} % (30 j)"
                      if row["change_30d_pct"] is not None else "—"),
        "secondary_color": (
            (theme.LIGHT_GREEN if row["change_30d_pct"] >= 0 else theme.LIGHT_RED)
            if row["change_30d_pct"] is not None else theme.LIGHT_TEXT
        ),
    } for row in rows]
    theme.render_compact_list(compact_rows, table_key=table_key,
                              detail=lambda row: _render_search_result_detail(row, table_key))
    if len(ordered) > limit:
        if st.button(f"Afficher plus ({len(ordered) - limit} restants)", key=f"list_more_{table_key}"):
            st.session_state[limit_key] = limit + LIST_PAGE_SIZE
            st.rerun()
    ui_cards.footnote("Prix indicatifs : clôture de la veille dans la devise de l'actif, mise à jour une fois par "
                      "jour. Le prix en direct et les ordres sont sur la fiche de chaque actif.")


# -- Recherche -----------------------------------------------------------------

@st.cache_data(ttl=600, show_spinner=False)
def _cached_search(query: str) -> list[dict]:
    """Une requête Yahoo Search par texte recherché et par 10 min (partagé
    entre sessions) : sans ce cache, la recherche était relancée à CHAQUE
    rerun de l'onglet tant que le texte restait dans le champ. Un échec
    (exception) n'est jamais mis en cache."""
    return md.search_assets(query)


def _search_tradable_assets(query: str) -> list[dict]:
    try:
        results = _cached_search(query.strip().lower())
    except md.MarketDataError as e:
        st.error(str(e))
        return []
    return results


def _render_search_result_detail(row: dict, table_key: str = "search") -> None:
    """Contenu de l'expander "Détails" sous une ligne compacte mobile d'une
    liste de recherche (voir _render_search_result_list) : pas d'info
    supplémentaire à afficher ici (ticker+nom seulement, pas de prix), donc
    uniquement le bouton d'ouverture de la fiche — sans lui, une ligne
    compacte mobile n'a aucun moyen d'atteindre le formulaire d'ordre."""
    # Clé préfixée par la liste : un même ticker peut apparaître dans deux
    # listes de la même page (suggestions + page de liste Crypto...).
    if st.button("Voir la fiche →", key=f"mobile_goto_{table_key}_{row['ticker']}", use_container_width=True):
        theme.go_to_trading(row["ticker"], row.get("nav_name", row["name"]))


def _render_search_result_list(rows: list[dict], table_key: str) -> None:
    """Rendu double (desktop table / mobile liste compacte) pour une liste à
    2 colonnes ticker+nom seulement (résultats de recherche, récents,
    suggestions) : même principe que les encadrés d'actifs (_render_asset_box)
    et Positions/Historique (ui_portfolio.py) — sans lui, chaque élément
    s'empilait en grosse carte sur mobile ("gros rectangles peu esthétiques",
    repéré au test réel) au lieu d'une ligne compacte par élément."""
    with st.container(key=f"tslight_desktop_wrap_{table_key}"):
        theme.render_table_light(rows, SEARCH_RESULT_COLUMNS, row_key="ticker",
                                  table_key=table_key, show_header=False)
    theme.render_compact_list(rows, table_key=table_key,
                              detail=lambda row: _render_search_result_detail(row, table_key))


def _render_search() -> None:
    with st.container(key="ts_card_search"):
        st.markdown("##### Rechercher un actif")
        # Champ + résultats dans un st.form plutôt qu'un simple st.text_input
        # "live" : sans ça, CHAQUE frappe déclenche un rerun qui reconstruit
        # les boutons de résultat, et cliquer sur l'un d'eux juste après avoir
        # tapé fait courir ce clic contre le rerun encore en cours du champ de
        # texte (son "commit" de valeur) -- le clic arrivait alors sur une
        # instance de bouton déjà en train d'être remplacée côté serveur et
        # était silencieusement perdu, d'où le besoin systématique d'un 2e
        # clic pour ouvrir la fiche d'un actif (repéré au stress test, confirmé
        # en isolant : cliquer un ticker des vitrines d'accueil, hors recherche,
        # fonctionnait lui du premier coup). Avec st.form, la recherche ne se
        # relance qu'à la soumission (Entrée ou bouton) : au moment où les
        # boutons de résultat apparaissent, le champ de texte n'a plus aucun
        # rerun en attente, donc plus de course possible avec le clic suivant.
        with st.form("ts_search_form", border=False):
            col_input, col_submit = st.columns([5, 1])
            col_input.text_input(
                "Rechercher un actif", key="search_query", label_visibility="collapsed",
                placeholder="Nom ou ticker : Apple, AAPL, Bitcoin, Or...",
            )
            col_submit.form_submit_button("Rechercher", use_container_width=True)

        query = st.session_state.get("search_query", "")
        if query:
            results = _search_tradable_assets(query)
            if results:
                rows = [{
                    "ticker": r["symbol"],
                    "name": f"{r['name']} · {r['exchange']}" if r["exchange"] else r["name"],
                    "nav_name": r["name"],  # sans la bourse : c'est ce nom qui atterrit sur les trades/positions
                    "category": valuation.category_for(r.get("type", ""), r["symbol"]),
                } for r in results[:8]]
                _render_search_result_list(rows, "compact_search_results")
            else:
                st.caption("Aucun résultat. Tu peux saisir le ticker exact ci-dessous.")
                with st.form("ts_manual_ticker_form", border=False):
                    mcol_input, mcol_submit = st.columns([5, 1])
                    manual = mcol_input.text_input(
                        "Ticker exact", key="manual_ticker_input", label_visibility="collapsed",
                        placeholder="ex : SAN.PA",
                    )
                    manual_submitted = mcol_submit.form_submit_button(
                        "Rechercher ce ticker", use_container_width=True,
                    )
                if manual_submitted and manual:
                    theme.go_to_trading(manual.strip().upper(), manual.strip().upper())
            return

        user_id = st.session_state.user_id
        # Limité aux 3 plus récentes (get_recent trie déjà du plus récent au
        # plus ancien) : au-delà, la liste de suggestions perdait son intérêt
        # de raccourci rapide.
        recent = search_history.get_recent(user_id, limit=3)
        if recent:
            st.markdown(
                '<div class="ts-light-col-label" style="margin-bottom:0.5rem;">Recherches récentes</div>',
                unsafe_allow_html=True,
            )
            rows = [
                {
                    "ticker": r["ticker"], "name": r["name"],
                    "category": valuation.category_for(r["quote_type"], r["ticker"]),
                }
                for r in recent
            ]
            _render_search_result_list(rows, "compact_recent_searches")
        else:
            st.markdown(
                '<div class="ts-light-col-label" style="margin-bottom:0.5rem;">Suggestions</div>',
                unsafe_allow_html=True,
            )
            rows = [{"ticker": t, "name": n, "category": c} for t, n, c in DEFAULT_SUGGESTIONS]
            _render_search_result_list(rows, "compact_suggested_searches")


# -- Prix + graphique (mécanique inchangée) -----------------------------------

def _is_crypto(ticker: str, quote_type: str) -> bool:
    """Détermine la source du graphique (Kraken si crypto, Yahoo sinon).
    Délègue à valuation.category_for, qui sait retrouver la classe d'actif
    par la syntaxe du ticker (ex. BTC-USD) quand quote_type est inconnu —
    le cas courant ici, voir theme.go_to_trading."""
    return valuation.category_for(quote_type, ticker) == "Crypto"


# Classes d'actifs négociées par "montant à risquer" (marge en €) plutôt que
# par quantité brute d'unités dans le formulaire d'ordre (voir
# _render_order_form) : la taille de position se déduit automatiquement
# (montant × levier / prix), comme sur les plateformes de trading à effet de
# levier usuelles. Actions/ETF/indices restent en quantité entière (une
# action ne se fractionne pas dans la réalité) ; Forex/Matières premières/
# Obligations rejoignent ici la Crypto, qui avait déjà ce comportement —
# même simplification pour les 3, par cohérence avec l'existant plutôt que
# de modéliser des tailles de contrat/lots réelles (hors scope, voir la doc
# de conception d'origine de ce chantier).
_FRACTIONAL_AMOUNT_CATEGORIES = {"Crypto", "Forex", "Matières premières", "Obligations"}


def _uses_amount_input(ticker: str, quote_type: str) -> bool:
    return valuation.category_for(quote_type, ticker) in _FRACTIONAL_AMOUNT_CATEGORIES


def _period_start(period_key: str) -> datetime:
    now = datetime.now(timezone.utc)
    if period_key == "YTD":
        return datetime(now.year, 1, 1, tzinfo=timezone.utc)
    days = {
        "1J": 1, "1S": 7, "1M": 30, "3M": 90, "6M": 182, "1A": 365, "5A": 365 * 5,
    }.get(period_key)
    if days is None:  # "Tout"
        return datetime(2000, 1, 1, tzinfo=timezone.utc)
    return now - timedelta(days=days)


def _execution_price_error() -> str | None:
    """Refus (message) si le prix affiché est trop ancien pour un ordre
    manuel — règles d'âge maximal centralisées dans valuation
    (MAX_ORDER_PRICE_AGE_SECONDS / _CRYPTO_SECONDS). L'âge part de l'heure
    d'obtention réelle du prix auprès de la source (quote["fetched_at"],
    déposée par _render_price_and_chart), jamais du taux de change : un
    taux en cache 5 min provoquait des refus à tort toutes les 5 min."""
    fetched_at = st.session_state.get("trading_price_fetched_at")
    ticker = st.session_state.get("trading_price_ticker") or ""
    quote_type = st.session_state.get("trading_quote_type") or ""
    age = None if fetched_at is None else max(0.0, time.time() - fetched_at)
    error = valuation.order_price_age_error(age, ticker, quote_type)
    if error:
        market_store.log_event("order_refused_stale_price", ticker=ticker,
                               age_s=round(age) if age is not None else None,
                               source=st.session_state.get("trading_price_source"))
    return error


def _tag_last_trade(portfolio, ticker: str) -> None:
    """Traçabilité (règle 3) : âge et source du prix utilisé, posés sur le
    trade que Portfolio.buy/sell/... vient d'ajouter en fin d'historique."""
    fetched_at = st.session_state.get("trading_price_fetched_at")
    if not portfolio.history or portfolio.history[-1].ticker != ticker or fetched_at is None:
        return
    trade = portfolio.history[-1]
    trade.price_age_seconds = round(max(0.0, time.time() - fetched_at), 1)
    trade.price_source = st.session_state.get("trading_price_source")
    if trade.price_source == "last_known":
        market_store.log_event("order_on_stale_price", ticker=ticker, action=trade.action,
                               age_s=round(trade.price_age_seconds))


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_chart_history(ticker: str, quote_type: str, period_key: str):
    """Récupère l'historique pour le graphique, en choisissant la source
    (Kraken pour la crypto, Yahoo sinon) et en appliquant le repli
    automatique d'intervalle. Retourne (DataFrame, intervalle_effectif, source).

    Mis en cache 60s : sans ça, changer de période/type de
    graphique ou revenir peu après sur le même actif refait un appel réseau
    complet à chaque fois. Sans lien avec le bug du double-clic (voir
    _render_search) : ce cache et le st.spinner posé à l'appel, plus bas,
    améliorent juste le retour visuel pendant un premier chargement.
    """
    interval = PERIOD_INTERVAL[period_key]
    start = _period_start(period_key)

    if _is_crypto(ticker, quote_type):
        try:
            hist, effective = kraken_data.get_history_with_fallback(ticker, interval, start)
            return hist, effective, "Kraken"
        except md.MarketDataError:
            pass  # repli sur Yahoo si Kraken échoue (paire non reconnue, indisponible...)

    hist, effective = md.get_history_with_fallback(ticker, interval, start)
    return hist, effective, "Yahoo Finance"


# Marqueurs d'ouverture/clôture de position sur le graphique de prix
# (prompt 24) : action (achat/ouverture short = ouverture, vente/rachat short
# = clôture) -> couleur ; sens de la position -> lettre.
_OPENING_TRADE_ACTIONS = ("achat", "ouverture short")
# Plafond d'affichage : les N ordres les plus RÉCENTS seulement (garde le
# graphique lisible et le rendu léger, même avec un long historique de trades).
MAX_TRADE_MARKERS = 10
_TRADE_ACTION_LABELS = {
    "achat": "Ouverture Long", "ouverture short": "Ouverture Short",
    "vente": "Clôture Long", "rachat short": "Clôture Short",
}


def _trade_markers_trace(trades: list, ticker: str, hist, fx_rate: float):
    """Trace Plotly des marqueurs de trades de `ticker` (ouvertes ET
    clôturées, sans filtrage autre que la plage de temps du graphique) :
    rond vert = ouverture, rouge = clôture (totale ou partielle), lettre L/S =
    sens de la position. Retourne None s'il n'y a rien à afficher.

    Le prix du trade est stocké en EUR : converti dans la devise du graphique
    (`fx_rate` = prix natif / prix EUR ACTUELS), donc approximatif pour un actif
    non-EUR dont le change a bougé depuis le trade — le change historique
    n'est pas conservé avec le trade. L'horodatage est naïf (heure du serveur
    au moment de l'ordre, voir Portfolio._log_trade), interprété en fuseau
    local puis converti dans celui de l'historique de prix.
    """
    if len(hist.index) == 0:
        return None
    xs, ys, colors, letters, hovers = [], [], [], [], []
    start, end = hist.index.min(), hist.index.max()
    # Filtre par ticker AVANT tout calcul de date (le portefeuille peut avoir
    # des centaines de trades sur d'autres actifs), puis garde les plus
    # récents : les dates ISO se trient chronologiquement en texte.
    ticker_trades = sorted(
        (t for t in trades if t.ticker == ticker and t.action in _TRADE_ACTION_LABELS),
        key=lambda t: t.date,
    )
    for t in ticker_trades[-MAX_TRADE_MARKERS * 3:]:
        try:
            ts = pd.Timestamp(t.date)
            if ts.tzinfo is None:
                ts = ts.tz_localize(datetime.now().astimezone().tzinfo)
            ts = ts.tz_convert(hist.index.tz) if hist.index.tz is not None else ts.tz_localize(None)
        except (ValueError, TypeError):
            continue
        if ts < start or ts > end:
            continue
        price = t.price_eur * fx_rate
        xs.append(ts)
        ys.append(price)
        colors.append(theme.LIGHT_GREEN if t.action in _OPENING_TRADE_ACTIONS else theme.LIGHT_RED)
        letters.append("L" if t.side == "long" else "S")
        hovers.append(
            f"{_TRADE_ACTION_LABELS[t.action]}<br>{t.quantity:g} à {t.price_eur:,.2f} €"
            f"<br>{ts.strftime('%d/%m/%Y %H:%M')}"
        )
    if not xs:
        return None
    xs, ys, colors, letters, hovers = (
        seq[-MAX_TRADE_MARKERS:] for seq in (xs, ys, colors, letters, hovers)
    )
    return go.Scatter(
        x=xs, y=ys, mode="markers+text", name="Ordres", showlegend=False,
        text=letters, textfont=dict(color="#0A2A33", size=10, family=theme.FONT_SANS),
        textposition="middle center",
        marker=dict(size=18, color=colors, line=dict(color="rgba(255,255,255,0.85)", width=1)),
        hovertext=hovers, hoverinfo="text",
    )


_SOURCE_LABELS = {"yahoo": "Yahoo Finance", "kraken": "Kraken", "last_known": "dernier prix connu"}


def _load_display_quote(ticker: str, quote_type: str) -> tuple[dict, float]:
    """(cotation affichée, taux de change -> EUR). Lève MarketDataError."""
    quote = live_quote.get_display_quote(ticker, quote_type)
    fx_rate, _ = md.get_fx_rate_info(quote["currency"], allow_stale=True)
    return quote, fx_rate


def _store_displayed_quote(ticker: str, quote_type: str, quote: dict, fx_rate: float) -> None:
    """Dépose le prix AFFICHÉ (et son heure d'obtention) en session : c'est
    exactement ce prix que le formulaire d'ordre relit au moment du clic
    (voir _displayed_price) — jamais une nouvelle cotation."""
    st.session_state.trading_price_eur = quote["price"] * fx_rate
    st.session_state.trading_price_native = quote["price"]
    st.session_state.trading_currency = quote["currency"]
    st.session_state.trading_price_fetched_at = quote["fetched_at"]
    st.session_state.trading_price_source = quote["source"]
    st.session_state.trading_price_ticker = ticker
    st.session_state.trading_quote_type = quote.get("quote_type") or quote_type


def _displayed_price(ticker: str) -> tuple[float, str] | None:
    """(prix affiché en €, devise) pour `ticker`, lu en session au moment
    de l'appel. Le fragment du formulaire d'ordre se relance seul à chaque
    clic avec les ARGUMENTS du dernier rechargement complet de la page : sans
    cette relecture, un ordre partait sur le prix de ce rechargement, parfois
    plus ancien que celui affiché (mis à jour entre-temps par le fragment prix),
    alors que le contrôle d'âge, lui, lisait l'heure du prix le plus récent."""
    if st.session_state.get("trading_price_ticker") != ticker:
        return None
    price_eur = st.session_state.get("trading_price_eur")
    if price_eur is None:
        return None
    return price_eur, st.session_state.get("trading_currency")


def _refresh_price_before_order(ticker: str, quote_type: str) -> bool:
    """Garde-fou d'âge du prix affiché (live_quote.displayed_price_too_old) :
    si le prix affiché est trop ancien au clic, le rafraîchit, l'affiche et
    demande une nouvelle validation (l'ordre n'est PAS exécuté). Retourne
    False si l'ordre peut être exécuté sur le prix affiché. Si le
    rafraîchissement échoue (source en pause), le prix daté obtenu à la
    place est affiché et ce sont les règles du mode « prix daté » qui
    s'appliqueront au clic suivant."""
    fetched_at = st.session_state.get("trading_price_fetched_at")
    source = st.session_state.get("trading_price_source")
    if not live_quote.displayed_price_too_old(fetched_at, source, ticker, quote_type):
        return False
    age = time.time() - fetched_at
    try:
        quote, fx_rate = _load_display_quote(ticker, quote_type)
    except md.MarketDataError as e:
        st.error(f"Prix indisponible, ordre non exécuté : {e}")
        return True
    _store_displayed_quote(ticker, quote_type, quote, fx_rate)
    new_price = quote["price"] * fx_rate
    market_store.log_event("order_price_refreshed", ticker=ticker, displayed_age_s=round(age),
                           new_source=quote["source"])
    if quote["source"] == "last_known":
        notice = (f"Le prix affiché datait de {age / 60:.0f} min et la source est indisponible : dernier prix "
                  f"connu affiché ({new_price:,.2f} €). Vérifie puis valide à nouveau.")
    else:
        notice = (f"Le prix affiché datait de {age / 60:.0f} min : il vient d'être actualisé "
                  f"({new_price:,.2f} €). Vérifie puis valide à nouveau.")
    st.session_state["_price_refresh_notice"] = notice
    st.rerun(scope="app")
    return True


# -- Pause de l'actualisation automatique après inactivité ----------------------
#
# Mécanisme (vérifié dans le code de Streamlit 1.61) : un fragment run_every
# n'enregistre son minuteur côté navigateur que lorsqu'il est rendu pendant
# un rechargement COMPLET de la page, et chaque rechargement complet efface
# tous les minuteurs avant de réenregistrer ceux des fragments rendus. Pour
# une vraie pause (plus aucune relance, donc plus aucune requête), un tic du
# minuteur qui constate l'inactivité relance donc toute la page une fois, et
# ce rechargement rend les fragments SANS run_every. Seules les vraies
# interactions (rechargement complet, clic dans le formulaire d'ordre,
# changement de période) mettent à jour l'heure de dernière interaction.

def _is_fragment_rerun() -> bool:
    """Vrai si l'exécution en cours est la relance d'un fragment seul (tic
    de minuteur ou clic dans un fragment), faux pour un rechargement complet."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx()
        return bool(ctx is not None and ctx.fragment_ids_this_run)
    except Exception:
        return False


def _note_interaction() -> bool:
    """Enregistre une interaction de l'utilisateur. Retourne True si elle
    vient de lever la pause (l'appelant doit alors recharger la page pour
    réenregistrer les minuteurs)."""
    st.session_state["_trading_last_interaction_at"] = time.time()
    if st.session_state.pop("_auto_refresh_paused", False):
        market_store.log_event("auto_refresh_resumed", ticker=st.session_state.get("selected_ticker"))
        return True
    return False


def _auto_refresh_is_paused() -> bool:
    return bool(st.session_state.get("_auto_refresh_paused"))


def _pause_if_inactive(ticker: str) -> None:
    """Appelé à chaque relance du fragment prix : met l'actualisation en
    pause après live_quote.AUTO_REFRESH_PAUSE_INACTIVITE_S sans interaction."""
    if _auto_refresh_is_paused() or not _is_fragment_rerun():
        return
    last = st.session_state.get("_trading_last_interaction_at")
    if not live_quote.auto_refresh_paused(last):
        return
    st.session_state["_auto_refresh_paused"] = True
    st.session_state["_auto_refresh_pause_rerun"] = True  # ce rechargement n'est pas une interaction
    market_store.log_event("auto_refresh_paused", ticker=ticker, inactive_s=round(time.time() - last))
    st.rerun(scope="app")


def _render_paused_price(ticker: str) -> None:
    """Fiche en pause : dernier prix et dernier graphique gardés en session,
    AUCUNE requête. « Actualiser » (ou tout autre clic) relance."""
    price_eur = st.session_state.get("trading_price_eur")
    if st.session_state.get("trading_price_ticker") == ticker and price_eur is not None:
        currency = st.session_state.get("trading_currency")
        fetched = st.session_state.get("trading_price_fetched_at")
        when = datetime.fromtimestamp(fetched).strftime("%H:%M:%S") if fetched else "?"
        ui_cards.live_price(st.session_state.get("trading_price_native", 0.0), currency, price_eur,
                            f"Prix obtenu à {when} · actualisation automatique en pause")
        ui_cards.state_banner(
            "paused",
            f"Aucune activité depuis {live_quote.AUTO_REFRESH_PAUSE_INACTIVITE_S // 60} min : le prix n'est plus "
            f"actualisé (obtenu à {when}). Clique sur « Actualiser » ou n'importe où pour reprendre.",
            title="Actualisation en pause",
        )
    if st.button("Actualiser", key="resume_auto_refresh", type="primary"):
        _note_interaction()
        st.rerun(scope="app")
    last_chart = st.session_state.get("_trading_last_chart")
    if last_chart and last_chart["ticker"] == ticker:
        with st.container(key=theme.TRADING_CHART_KEY):
            st.plotly_chart(last_chart["fig"], use_container_width=True, config=theme.PLOTLY_CONFIG)


def _render_price_and_chart(ticker: str, quote_type: str, trades: list) -> None:
    """Prix + graphique de `ticker`, isolés dans leur propre fragment : se
    rafraîchissent seuls (run_every), sans recharger le reste de la page
    (formulaire d'ordre, carnet...). Fréquence = durée de cache du prix de
    la classe d'actif (live_quote.PRICE_CACHE_SECONDS : 90 s Yahoo, 30 s
    Kraken) — relancer plus vite ne ferait que relire le cache. Fragment
    créé à l'appel (et non par décorateur) pour que cette fréquence dépende
    de l'actif et s'arrête pendant la pause d'inactivité ; son identifiant
    Streamlit reste stable (nom de la fonction + position dans la page)."""
    run_every = None if _auto_refresh_is_paused() else live_quote.price_cache_seconds(ticker, quote_type)
    st.fragment(_price_and_chart_body, run_every=run_every)(ticker, quote_type, trades)


def _price_and_chart_body(ticker: str, quote_type: str, trades: list) -> None:
    """Corps du fragment prix + graphique (voir _render_price_and_chart).
    Comme un fragment ne peut pas faire vivre une valeur "live" en dehors de
    lui, le prix affiché est déposé dans st.session_state : le formulaire
    d'ordre (autre fragment) et le carnet simulé le relisent de là."""
    _pause_if_inactive(ticker)
    if _auto_refresh_is_paused():
        _render_paused_price(ticker)
        return
    try:
        with st.spinner(f"Chargement de {ticker}..."):
            # Si la source est en pause : dernier prix connu (avec sa vraie
            # devise) plutôt qu'une page vide — ordres possibles sous
            # conditions d'âge (voir _execution_price_error).
            quote, fx_rate = _load_display_quote(ticker, quote_type)
    except md.MarketDataError as e:
        st.error(str(e))
        st.session_state.trading_price_eur = None
        st.session_state.trading_price_fetched_at = None
        return

    price_native, currency = quote["price"], quote["currency"]
    price_eur = price_native * fx_rate
    _store_displayed_quote(ticker, quote_type, quote, fx_rate)

    previous_close = quote.get("previous_close")
    day_up = previous_close is None or price_native >= previous_close

    source_label = _SOURCE_LABELS.get(quote.get("source"), quote.get("source"))
    age_s = max(0, round(time.time() - quote["fetched_at"]))
    age_text = f"{age_s} s" if age_s < 120 else f"{age_s // 60} min"
    refresh_s = live_quote.price_cache_seconds(ticker, quote_type)
    ui_cards.live_price(price_native, currency, price_eur,
                        f"Obtenu il y a {age_text} · Auto · toutes les {refresh_s} s · source : {source_label}")
    if quote["stale"]:
        age_min = max(0, (time.time() - quote["fetched_at"]) / 60)
        limit_min = valuation.max_order_price_age_seconds(ticker, st.session_state.trading_quote_type) // 60
        ui_cards.state_banner(
            "dated",
            f"Prix daté de {age_min:.0f} min : source de cotation en pause, dernier prix connu affiché. "
            f"Ordres possibles tant que le prix a moins de {limit_min} min.",
        )
        if st.session_state.get("_stale_mode_logged") != ticker:
            st.session_state["_stale_mode_logged"] = ticker
            market_store.log_event("stale_price_mode", ticker=ticker, age_s=round(age_min * 60))
    else:
        st.session_state.pop("_stale_mode_logged", None)

    col_a, col_b = st.columns([3, 1])
    period_key = col_a.radio(
        "Période", list(PERIOD_INTERVAL.keys()), horizontal=True, index=4, key="chart_period_radio",
        on_change=_note_interaction,
    )
    chart_type = col_b.radio("Type", ["Courbe", "Chandeliers"], key="chart_type_radio",
                             on_change=_note_interaction)

    try:
        with st.spinner(f"Chargement du graphique {ticker}..."):
            hist, effective_interval, source = _fetch_chart_history(ticker, quote_type, period_key)
    except md.MarketDataError as e:
        st.error(str(e))
        return

    fig = go.Figure()
    if chart_type == "Courbe":
        # Couleur (et remplissage en dégradé sous la courbe) alignés sur le sens
        # de la variation du jour (comme Google Finance), plutôt qu'une couleur fixe.
        color = theme.LIGHT_GREEN if day_up else theme.LIGHT_RED
        fig.add_trace(go.Scatter(
            x=hist.index, y=hist["Close"], mode="lines", name=ticker,
            line=dict(color=color, width=2),
            fill="tozeroy", fillgradient=theme.plotly_area_fillgradient(color),
        ))
    else:
        fig.add_trace(go.Candlestick(
            x=hist.index, open=hist["Open"], high=hist["High"],
            low=hist["Low"], close=hist["Close"], name=ticker,
            increasing_line_color=theme.LIGHT_GREEN, increasing_fillcolor=theme.LIGHT_GREEN,
            decreasing_line_color=theme.LIGHT_RED, decreasing_fillcolor=theme.LIGHT_RED,
        ))
    markers = _trade_markers_trace(trades, ticker, hist, price_native / price_eur if price_eur else 1.0)
    if markers is not None:
        fig.add_trace(markers)
    # 600px (au lieu de 450 avant ce correctif) : comble le vide sous le
    # graphique/carnet, le panneau d'ordre à droite (TP/SL, récapitulatif...)
    # étant naturellement plus haut que les 2 autres colonnes (mesuré à
    # ~811px de haut sur une position sans TP/SL existant, contre 450 pour
    # le graphique) — largeur inchangée, le graphique colle déjà au bord
    # gauche de la page, rien à gagner de ce côté sans rogner le carnet/le
    # panneau d'ordre. Voir aussi .ts-ob-wrap dans theme.py (carnet aligné
    # sur cette même valeur).
    fig.update_layout(**theme.plotly_layout(height=600, margin=dict(l=10, r=10, t=20, b=10),
                                             xaxis_rangeslider_visible=False))
    if chart_type == "Courbe":
        # autorange=False : sans ça, le remplissage tirerait l'axe jusqu'à 0 et
        # écraserait la courbe (voir theme.plotly_area_range) — inutile pour les
        # chandeliers, qui n'ont pas de remplissage.
        fig.update_yaxes(range=theme.plotly_area_range(hist["Close"]), autorange=False)

    # Zoom par défaut à l'ouverture : les 3 derniers mois de données
    # chargées (pas tout l'historique compressé façon "1A"/"5A"/"Tout"),
    # façon Kraken/Binance. Les données complètes correspondant à la
    # période choisie restent chargées : l'utilisateur peut double-cliquer
    # sur le graphique pour réinitialiser le zoom et les retrouver, seule la
    # fenêtre affichée à l'ouverture change. Sans effet quand la période
    # sélectionnée est déjà plus courte que 3 mois (1J/1S/1M) : la fenêtre
    # se cale alors sur les données disponibles, jamais plus large que ce
    # que l'utilisateur a explicitement demandé.
    if len(hist.index) > 0:
        data_end = hist.index.max()
        default_start = max(hist.index.min(), data_end - timedelta(days=90))
        # autorange=False explicite + dates en ISO (pas des Timestamp pandas
        # bruts) : sans ça, le composant Plotly du navigateur recalculait son
        # propre autorange au premier resize (déclenché par
        # use_container_width) et ignorait la plage demandée ici.
        fig.update_xaxes(range=[default_start.isoformat(), data_end.isoformat()], autorange=False)

    # Zoom molette/pinch désactivé (scrollZoom=False) et zoom/pan par glisser
    # désactivé (dragmode=False, voir theme.plotly_layout ci-dessus) : le
    # sélecteur de période reste le seul moyen de changer l'échelle affichée,
    # desktop et mobile. Les deux réglages vivent dans theme.PLOTLY_CONFIG /
    # theme.plotly_layout depuis le prompt 18, communs à tous les graphiques
    # Plotly de l'app (plus de config ad hoc ici). Le survol (hover) et le
    # double-clic pour réinitialiser le zoom restent actifs, indépendants de
    # ces deux réglages côté Plotly.js.
    # Prompt 24 : zoom molette + glisser réactivé, mais bloqué hors plein
    # écran par theme.render_fullscreen_zoom_gate (voir son commentaire).
    theme.render_fullscreen_zoom_gate()
    fig.update_layout(dragmode="zoom")
    with st.container(key=theme.TRADING_CHART_KEY):
        st.plotly_chart(fig, use_container_width=True, config={**theme.PLOTLY_CONFIG, "scrollZoom": True})
    st.session_state["_trading_last_chart"] = {"ticker": ticker, "fig": fig}  # réaffiché pendant la pause

    fallback_note = "" if effective_interval == PERIOD_INTERVAL[period_key] else " (repli, plage trop longue)"
    st.caption(
        f"{len(hist)} bougies chargées · intervalle {effective_interval}{fallback_note} · source {source}"
    )
    st.caption(theme.PLOTLY_FULLSCREEN_ZOOM_HINT)
    # Trois chiffres tirés de la cotation DÉJÀ obtenue (aucune requête de plus).
    day_change = (price_native / previous_close - 1) * 100 if previous_close else None
    ui_cards.stat_cards([
        ("Variation du jour", ui_cards.change_pill(day_change)),
        ("Clôture précédente", f"{ui_cards.format_price(previous_close)} {html_lib.escape(currency)}"
         if previous_close else "—"),
        ("Prix en euros", f"{ui_cards.format_price(price_eur)} €"),
    ])


# -- Carnet d'ordre simulé (prompt 20) ----------------------------------------
# PUREMENT DÉCORATIF (voir src/orderbook_sim.py pour la logique de
# génération) : donne à la fiche Trading l'apparence d'un marché vivant,
# SANS AUCUNE vraie donnée de marché. N'appelle et ne doit JAMAIS appeler
# get_quote/_fetch_chart_history/kraken_data.* ni aucune fonction réseau —
# lecture pure de st.session_state.trading_price_eur, déjà peuplé par
# _render_price_and_chart ci-dessus. Voir tests/test_orderbook_no_network.py,
# garde explicite contre une régression future qui reconnecterait ce carnet
# à une vraie source par erreur.

# Rafraîchissement visuel du carnet : totalement DÉCOUPLÉ du timer du
# fragment prix (30s, run_every de _render_price_and_chart) — ce timer ne
# déclenche jamais le moindre appel réseau, juste un nouveau tirage
# aléatoire local (voir orderbook_sim), donc aucun impact sur le nombre
# d'appels API réels quelle que soit sa fréquence.
_ORDERBOOK_REFRESH_SECONDS = 1.5


def _render_order_book(ticker: str) -> None:
    """Crée le fragment du carnet simulé ; son animation s'arrête elle aussi
    pendant la pause d'inactivité (aucun appel réseau dans tous les cas)."""
    run_every = None if _auto_refresh_is_paused() else _ORDERBOOK_REFRESH_SECONDS
    st.fragment(_order_book_body, run_every=run_every)(ticker)


def _order_book_body(ticker: str) -> None:
    """Carnet d'ordre simulé, isolé dans son propre fragment (comme
    _render_price_and_chart et _render_order_panel) : son timer ne
    redéclenche jamais le reste de la page, et une interaction ailleurs
    (formulaire d'ordre, changement d'onglet) ne le redéclenche pas non
    plus. Lit uniquement `st.session_state.trading_price_eur` (déjà déposé
    par le fragment prix) — ne fait AUCUN appel réseau propre.
    """
    with st.container(key="ts_card_orderbook"):
        reference_price = st.session_state.get("trading_price_eur")
        if reference_price is None:
            st.caption("Carnet indisponible.")
            return

        # État précédent gardé par ticker (session_state, pas un fichier/DB :
        # purement visuel, aucune raison de persister au-delà de la session)
        # pour savoir si le prix réel caché vient de bouger (nouveau tick ->
        # on régénère les niveaux) ou non (on anime juste les quantités).
        state_key = f"_orderbook_state_{ticker}"
        previous_state = st.session_state.get(state_key)

        if previous_state is None or previous_state["reference_price"] != reference_price:
            previous_price = previous_state["reference_price"] if previous_state else None
            snapshot = orderbook_sim.generate_snapshot(reference_price, previous_price=previous_price)
        else:
            snapshot = orderbook_sim.apply_noise(previous_state["snapshot"])

        st.session_state[state_key] = {"reference_price": reference_price, "snapshot": snapshot}

        _render_order_book_rows(snapshot, reference_price)


def _render_order_book_rows(snapshot: dict, reference_price: float) -> None:
    """Construit le HTML du carnet (asks empilés au-dessus du centre,
    bids en dessous) à partir d'un snapshot déjà généré — aucun calcul de
    simulation ici, seulement de la mise en forme (voir orderbook_sim pour
    la génération des niveaux)."""
    asks = orderbook_sim.with_cumulative(snapshot["asks"])
    bids = orderbook_sim.with_cumulative(snapshot["bids"])
    max_cumulative = max(asks[-1]["cumulative"], bids[-1]["cumulative"], 1e-9)

    def _row(level: dict, side: str) -> str:
        depth_pct = min(level["cumulative"] / max_cumulative * 100, 100)
        return (
            f'<div class="ts-ob-row ts-ob-{side}">'
            f'<div class="ts-ob-depth" style="width:{depth_pct:.1f}%"></div>'
            f'<span class="ts-ob-price">{level["price"]:,.2f}</span>'
            f'<span class="ts-ob-qty">{level["quantity"]:.3f}</span>'
            f'<span class="ts-ob-total">{level["cumulative"]:.3f}</span>'
            f'</div>'
        )

    # Asks générés du plus proche du prix (index 0) au plus loin ; affichés
    # dans l'ordre INVERSE (plus loin en haut, plus proche juste au-dessus
    # du centre) — voir la disposition demandée dans le prompt d'origine.
    asks_html = "".join(_row(lvl, "ask") for lvl in reversed(asks))
    bids_html = "".join(_row(lvl, "bid") for lvl in bids)

    best_ask, best_bid = asks[0]["price"], bids[0]["price"]
    spread_bps = (best_ask - best_bid) / reference_price * 10_000 if reference_price else 0.0

    # .ts-ob-wrap force la hauteur totale du carnet à coller à celle du
    # graphique (450px, voir _render_price_and_chart ligne ~550) ; .ts-ob-side
    # étire chaque groupe (asks/bids) en flex column avec justify-content
    # pour répartir les paliers sur toute la hauteur dispo plutôt que de
    # laisser un vide en bas de colonne (carnet visuellement trop petit avant
    # ce correctif). Div propre (pas une enveloppe Streamlit), donc aucun
    # risque du piège display:contents déjà rencontré ailleurs (prompt 19).
    st.markdown(
        f'<div class="ts-ob-wrap">'
        f'<div class="ts-ob-side ts-ob-asks">{asks_html}</div>'
        f'<div class="ts-ob-center">'
        f'<span class="ts-ob-center-price">{reference_price:,.2f} €</span>'
        f'<span class="ts-ob-center-spread">spread {spread_bps:.1f} bps</span>'
        f'</div>'
        f'<div class="ts-ob-side ts-ob-bids">{bids_html}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# -- Récapitulatif d'ordre -----------------------------------------------------

def _render_order_summary(price: float, quantity: float, leverage: float, side: str) -> None:
    notional = quantity * price
    margin = notional / leverage if leverage else notional
    liq_price = valuation.liquidation_price_eur(price, leverage, side)

    with st.container(key="ts_card_order_summary"):
        st.markdown("###### Récapitulatif")
        c1, c2, c3 = st.columns(3)
        c1.metric("Coût total", f"{notional:,.2f} €")
        c2.metric("Marge requise", f"{margin:,.2f} €")
        c3.metric("Liquidation auto. estimée", f"{liq_price:,.2f} €" if liq_price else "—")
        if liq_price:
            st.caption(
                f"Position liquidée automatiquement si le prix atteint ce niveau (perte latente = "
                f"{valuation.MAINTENANCE_LOSS_RATIO * 100:.0f}% de ta marge engagée), vérifié toutes les "
                "15 minutes même si l'app est fermée."
            )

        st.caption("Simulation de gain/perte si le prix évolue de :")
        scenarios = [-10, -5, 5, 10]
        cols = st.columns(len(scenarios))
        for col, pct in zip(cols, scenarios):
            new_price = price * (1 + pct / 100)
            pnl_eur = (new_price - price) * quantity if side == "long" else (price - new_price) * quantity
            pnl_pct_margin = (pnl_eur / margin * 100) if margin else 0.0
            color = theme.LIGHT_GREEN if pnl_eur >= 0 else theme.LIGHT_RED
            sign = "+" if pct >= 0 else ""
            col.markdown(
                f"""
                <div style="text-align:center;">
                    <div class="ts-light-col-label">{sign}{pct}%</div>
                    <div style="color:{color};font-weight:700;font-family:{theme.FONT_MONO};font-size:0.95rem;">
                        {pnl_eur:+,.2f} €
                    </div>
                    <div style="color:{color};font-size:0.72rem;font-family:{theme.FONT_MONO};">
                        {pnl_pct_margin:+.1f}% marge
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


# -- Formulaire d'ordre ---------------------------------------------------------

def _render_tp_sl_at_order_form(order_mode: str, ref_price: float) -> list[tuple[str, float, float]]:
    """Paliers Take Profit / Stop Loss à créer juste après l'exécution d'un
    ordre D'OUVERTURE (achat ou short) au marché — voir tp_sl.py. Retourne
    une liste de (libellé du type, prix cible €, % de la position).

    Non proposé pour un ordre à cours limité : la position n'existe pas
    encore au moment du placement, impossible d'y poser un palier avant
    qu'elle existe — une fois l'ordre limité rempli, la section Take Profit
    / Stop Loss (déjà disponible sur toute position ouverte) permet de le
    faire après coup, sans limite de paliers celle-là.

    Non proposé non plus pour renforcer une position déjà existante (Acheter
    plus / Vendre plus à découvert) : la section Take Profit / Stop Loss
    dédiée (_render_tp_sl_section) est alors déjà affichée juste en dessous
    pour cette même position, avec les mêmes champs (Type/Prix cible/%) —
    l'appelant restreint donc l'appel à `existing is None`. Sans cette
    restriction, les deux blocs quasi identiques apparaissaient l'un sous
    l'autre dans le panneau d'ordre (layout Hyperliquid, prompt 10),
    donnant l'impression à tort d'une fonctionnalité dupliquée alors que
    l'un porte sur le nouvel ordre et l'autre sur la position déjà détenue.

    Champs toujours visibles et actifs dès l'ouverture du formulaire (pas de
    case à cocher préalable à activer) : un palier est proposé par défaut,
    prêt à être rempli directement — prix cible par défaut décalé de 10%
    dans le sens cohérent avec le type de palier (au-dessus du prix de
    référence pour un Take Profit, en-dessous pour un Stop Loss), plutôt que
    calé exactement sur le prix de référence : un palier laissé à son
    défaut sans y toucher se déclencherait alors quasiment tout de suite,
    ce que la case à cocher (une action volontaire) empêchait de fait.

    "Nombre de paliers" descend jusqu'à 0 (pas de minimum à 1) : pour ouvrir
    une position SANS aucun palier, il suffit de le mettre à 0 avec le "-"
    — sans ce 0, il était impossible de refuser un palier une fois la case à
    cocher supprimée (prompt 9), un palier par défaut se retrouvait alors
    créé silencieusement à chaque ouverture de position (repéré par Edgar).
    """
    if order_mode != "Ordre au marché":
        return []

    tiers = []
    with st.container(key="ts_card_order_tp_sl"):
        st.markdown("###### Take Profit / Stop Loss")
        tier_count = st.number_input(
            "Nombre de paliers", min_value=0, max_value=MAX_ORDER_TP_SL_TIERS, value=1, step=1,
            key="order_tp_sl_count",
            help="Laisse à 0 si tu ne veux ni Take Profit ni Stop Loss maintenant — tu pourras "
                 "toujours en ajouter un après coup depuis la section dédiée, sans limite de paliers.",
        )
        if tier_count == 0:
            st.caption("Aucun palier ne sera créé avec cet ordre.")
        for i in range(int(tier_count)):
            st.markdown(f"**Palier {i + 1}**")
            c1, c2, c3 = st.columns(3)
            kind_label = c1.segmented_control(
                "Type", TP_SL_KIND_LABELS, default=TP_SL_KIND_LABELS[0], required=True,
                key=f"order_tp_sl_kind_{i}", label_visibility="collapsed",
            )
            is_take_profit = kind_label == TP_SL_KIND_LABELS[0]
            default_price = ref_price * 1.10 if is_take_profit else ref_price * 0.90
            target_price = c2.number_input(
                "Prix cible (€)", min_value=0.01, value=float(round(default_price, 2)), step=0.5,
                key=f"order_tp_sl_price_{i}",
            )
            quantity_pct = c3.slider(
                "% de la position", min_value=1, max_value=100, value=50, key=f"order_tp_sl_pct_{i}",
            )
            tiers.append((kind_label, target_price, float(quantity_pct)))
    return tiers


def _create_tp_sl_tiers(portfolio, ticker: str, tiers: list[tuple[str, float, float]]) -> int:
    """Crée les paliers définis dans le formulaire, juste après l'exécution
    réussie de l'ordre d'ouverture qui vient de créer/augmenter la position
    (donc sur la quantité fraîchement mise à jour — voir tp_sl.create_tp_sl,
    qui fige la quantité initiale au moment de CET appel). Retourne le
    nombre de paliers effectivement créés : un palier invalide n'annule pas
    l'ordre déjà exécuté, juste ignoré avec un avertissement.
    """
    position = portfolio.positions.get(ticker)
    if position is None or not tiers:
        return 0

    created = 0
    with db.get_session() as session:
        for kind_label, target_price, quantity_pct in tiers:
            kind = tp_sl.KIND_TAKE_PROFIT if kind_label == TP_SL_KIND_LABELS[0] else tp_sl.KIND_STOP_LOSS
            try:
                tp_sl.create_tp_sl(
                    session, portfolio.id, st.session_state.user_id, position, kind, target_price, quantity_pct,
                )
                created += 1
            except ValueError as e:
                st.warning(f"Palier ignoré : {e}")
    return created


def _render_maintenance_indicator(position, current_price_eur: float) -> None:
    """Jauge de proximité de la liquidation automatique par marge de
    maintenance (voir valuation.MAINTENANCE_LOSS_RATIO,
    scripts/check_liquidation.py) — rien n'est affiché pour une position sans
    levier (jamais liquidée automatiquement, voir valuation.is_liquidatable).
    """
    pct = valuation.maintenance_margin_pct(position, current_price_eur)
    if pct is None:
        return

    leverage = valuation.position_leverage(position)
    liq_price = valuation.liquidation_price_eur(position.avg_price_eur, leverage, position.side)
    threshold = valuation.MAINTENANCE_LOSS_RATIO * 100
    ratio = min(pct / threshold, 1.0) if threshold else 0.0
    message = (
        f"Marge de maintenance : {pct:.0f}% de ta marge engagée déjà perdue "
        f"(liquidation automatique à {threshold:.0f}%, prix ≈ {liq_price:,.2f} €)."
    )
    if ratio >= 0.75:
        st.error(message)
    elif ratio >= 0.4:
        st.warning(message)
    else:
        st.caption(message)


def _render_action_tabs(key: str, buy_enabled: bool, short_enabled: bool,
                         short_help: str = "", buy_help: str = "") -> str:
    """2 actions distinctes, TOUJOURS affichées : Long / Short, chacune avec
    sa propre couleur. Depuis le prompt 22, il n'y a plus d'onglet "Vendre"
    séparé : la clôture d'une position existante se fait DANS l'onglet du
    sens détenu (voir _render_close_panel) — clôturer un long depuis Long,
    un short depuis Short. Le sens opposé est DÉSACTIVÉ (pas masqué : la
    raison reste visible en infobulle) — Long et Short sont mutuellement
    exclusifs sur un même ticker (voir Portfolio.buy/open_short, qui le
    refusent déjà côté métier ; ce composant ne fait que refléter cette règle
    existante, jamais l'inverse). Valeur interne "acheter" inchangée (voir
    prompt 18).

    Retourne "acheter" | "short".
    """
    options = [
        ("acheter", "Long", theme.GREEN, buy_enabled, buy_help),
        ("short", "Short", theme.RED, short_enabled, short_help),
    ]

    current = st.session_state.get(key)
    enabled_by_value = {value: enabled for value, _, _, enabled, _ in options}
    if current not in enabled_by_value or not enabled_by_value[current]:
        # Repli sur la première option disponible : ex. après une clôture
        # totale qui fait passer l'actif de "long" à "aucune position", le
        # choix "Vendre" n'est plus valide — pas de raison de rester bloqué
        # dessus (le bouton est de toute façon désactivé, donc plus
        # cliquable) plutôt que de basculer proprement sur Long.
        current = next((value for value, _, _, enabled, _ in options if enabled), options[0][0])

    cols = st.columns(len(options))
    btn_keys = [f"{key}_opt_{value}" for value, _, _, _, _ in options]
    for (value, label, _color, enabled, help_text), btn_key, col in zip(options, btn_keys, cols):
        if col.button(label, key=btn_key, use_container_width=True, disabled=not enabled,
                       help=help_text or None):
            current = value
    st.session_state[key] = current

    style_rules = []
    for (value, _label, color, enabled, _help_text), btn_key in zip(options, btn_keys):
        # Sélecteur à 3 classes (ts_light + la clé du bouton + stElementContainer,
        # puis .stButton > button) — même technique que badge_color plus haut :
        # la règle générique ".st-key-ts_light .stButton > button" (2 classes)
        # a une spécificité plus élevée qu'un simple ".st-key-{btn_key} button"
        # (1 classe) et l'emportait sur la couleur voulue ici malgré le
        # !important (à spécificité égale ou supérieure, !important ne suffit
        # pas à lui seul — repéré au test réel : les 3 boutons ressortaient
        # tous avec le même style neutre, sans vert/rouge/gris distinctifs).
        selector_base = f'.st-key-ts_light .st-key-{btn_key}.stElementContainer .stButton > button'
        if not enabled:
            style_rules.append(
                f'{selector_base}, {selector_base}:disabled {{ '
                f'background:transparent !important; border-color:{theme.BORDER} !important; '
                f'color:{theme.MUTED} !important; }}'
            )
        elif value == current:
            style_rules.append(
                f'{selector_base}, {selector_base}:active, {selector_base}:focus {{ '
                f'background:{color} !important; border-color:{color} !important; '
                f'color:#ffffff !important; }}'
            )
        else:
            style_rules.append(
                f'{selector_base}, {selector_base}:active, {selector_base}:focus {{ '
                f'background:transparent !important; border-color:{color} !important; '
                f'color:{color} !important; }}'
            )
    st.markdown(f"<style>{''.join(style_rules)}</style>", unsafe_allow_html=True)
    return current


@st.fragment
def _render_order_panel(portfolio, ticker: str, name: str | None, price_eur: float, currency: str,
                         quote_type: str = "") -> None:
    # Un clic dans le formulaire est une interaction (pause d'inactivité) ;
    # s'il lève la pause, la page est rechargée APRÈS le traitement du clic
    # (jamais avant : l'action demandée serait perdue).
    resumed = _is_fragment_rerun() and _note_interaction()
    _order_panel_body(portfolio, ticker, name, price_eur, currency, quote_type)
    if resumed:
        st.rerun(scope="app")


def _order_panel_body(portfolio, ticker: str, name: str | None, price_eur: float, currency: str,
                      quote_type: str = "") -> None:
    # Affiché une seule fois (.pop) tout en haut du fragment : couvre les 2
    # sous-fonctions ci-dessous (formulaire d'ordre ET section TP/SL), qui
    # posent toutes deux le message dans session_state juste avant leur
    # propre st.rerun() plutôt que d'appeler theme.render_order_confirmation_popup
    # directement (voir le commentaire de cette fonction, theme.py).
    confirmation_msg = st.session_state.pop("_order_confirmation_message", None)
    if confirmation_msg:
        theme.render_order_confirmation_popup(confirmation_msg, seconds=ORDER_CONFIRMATION_POPUP_SECONDS)
    refresh_notice = st.session_state.pop("_price_refresh_notice", None)
    if refresh_notice:
        ui_cards.state_banner("revalidate", refresh_notice, title="Ordre à revalider")

    # Prix AFFICHÉ, relu à chaque exécution du fragment (voir _displayed_price) ;
    # les arguments ne servent que de repli.
    displayed = _displayed_price(ticker)
    if displayed is not None:
        price_eur, currency = displayed

    # Prompt 23 : quand le formulaire renforce une position existante, il
    # affiche lui-même la section TP/SL AVANT son bouton "Valider l'ordre"
    # (retourne True) ; sinon (clôture, ou aucune position), elle reste
    # affichée ici, sous le formulaire, comme avant.
    if not _render_order_form(portfolio, ticker, name, price_eur, currency, quote_type):
        _render_tp_sl_section(portfolio, ticker)


def _render_close_panel(portfolio, ticker: str, existing, price_eur: float) -> None:
    """Clôture d'une position ouverte (prompt 22), commune à Long (vente) et
    Short (rachat). Toujours au marché, au prix affiché à l'écran.

    - Clôture TOTALE : un seul bouton, aucune saisie — priorité du prompt.
    - Clôture PARTIELLE : montant saisi en EUROS, converti en quantité au
      moment du clic sur Valider, avec `price_eur` (le prix affiché et utilisé
      pour la valeur de position ci-dessous, pas un prix recalculé). Le moteur
      (Portfolio.sell/cover_short) reste en quantité, inchangé. Un montant qui
      dépasse la valeur de la position est plafonné à la clôture totale.
    "Valeur de la position" = quantité x prix affiché (exposition), la même
    base que la conversion euros -> quantité.
    """
    is_long = existing.side == "long"
    position_value = existing.quantity * price_eur

    def close(quantity: float) -> None:
        if _refresh_price_before_order(ticker, st.session_state.get("trading_quote_type") or ""):
            return
        price_error = _execution_price_error()
        if price_error:
            st.error(price_error)
            return
        try:
            if is_long:
                pnl = portfolio.sell(ticker, quantity, price_eur)
                msg = (f"Position clôturée : {quantity:g} x {ticker} vendu à {price_eur:,.2f} € "
                       f"(P&L réalisé : {pnl:+,.2f} €).")
            else:
                pnl = portfolio.cover_short(ticker, quantity, price_eur)
                msg = (f"Position clôturée : {quantity:g} x {ticker} racheté à {price_eur:,.2f} € "
                       f"(P&L réalisé : {pnl:+,.2f} €).")
        except ValueError as e:
            st.error(str(e))
            return
        _tag_last_trade(portfolio, ticker)
        storage.save_portfolio(portfolio)
        storage.invalidate_valuation_cache()
        st.session_state["_order_confirmation_message"] = msg
        st.rerun(scope="app")

    if st.button("Clôturer toute la position", type="primary", key="close_full_position",
                 use_container_width=True):
        close(existing.quantity)

    with st.expander("Clôturer une partie"):
        amount = st.number_input(
            "Montant à clôturer (€)", min_value=0.0, value=round(position_value / 2, 2), step=50.0,
            key="close_partial_amount", width=ORDER_INPUT_WIDTH,
        )
        value_str = f"{position_value:,.2f} €"
        st.caption(f"Valeur actuelle de la position : {theme.mono(value_str)}", unsafe_allow_html=True)
        if st.button("Valider la clôture partielle", key="close_partial_position"):
            if amount <= 0:
                st.error("Le montant doit être supérieur à 0.")
            elif amount >= position_value - 1e-9:
                close(existing.quantity)  # plafonné : clôture totale
            else:
                close(round(amount / price_eur, 6))


def _render_order_form(portfolio, ticker: str, name: str | None, price_eur: float, currency: str,
                        quote_type: str = "") -> bool:
    """Retourne True si le formulaire a déjà rendu lui-même la section TP/SL
    de la position existante (avant le bouton de validation, prompt 23)."""
    with st.container(key="ts_card_order"):
        st.markdown("##### Passer un ordre")

        uses_amount_input = _uses_amount_input(ticker, quote_type)
        existing = portfolio.positions.get(ticker)
        has_long = existing is not None and existing.side == "long"
        has_short = existing is not None and existing.side == "short"

        action_choice = _render_action_tabs(
            key="order_action_tab",
            buy_enabled=not has_short,
            short_enabled=not has_long,
            buy_help=(
                f"Position courte ouverte sur {ticker} : clôture-la d'abord (onglet Short)."
                if has_short else ""
            ),
            short_help=(
                f"Position longue ouverte sur {ticker} : clôture-la d'abord (onglet Long)."
                if has_long else ""
            ),
        )

        # Position déjà ouverte dans le sens de l'onglet actif : sous-choix
        # Clôturer / Renforcer (prompt 22 — remplace l'ancien onglet Vendre).
        # Clôturer est proposé en premier (et par défaut) : c'est le geste à
        # rendre le plus simple possible.
        held_here = (action_choice == "acheter" and has_long) or (action_choice == "short" and has_short)
        if held_here:
            side_label = "longue" if has_long else "courte"
            st.caption(f"Position actuelle : {existing.quantity:g} {ticker} en position {side_label} "
                       f"(prix moyen {existing.avg_price_eur:,.2f} €).")
            _render_maintenance_indicator(existing, price_eur)
            add_label = "Renforcer" if has_long else "Vendre plus à découvert"
            sub_choice = st.segmented_control(
                "Action sur la position", ["Clôturer", add_label], default="Clôturer", required=True,
                key=f"order_close_or_add_{action_choice}", label_visibility="collapsed",
            )
            if sub_choice == "Clôturer":
                _render_close_panel(portfolio, ticker, existing, price_eur)
                return False
            order_type = "Acheter plus" if has_long else "Vendre plus à découvert"
        elif action_choice == "acheter":
            st.caption(f"Aucune position ouverte sur {ticker}.")
            order_type = "Acheter (position longue)"
        else:  # short
            st.caption(f"Aucune position ouverte sur {ticker}.")
            order_type = "Vendre à découvert (position courte)"

        action = ACTION_BY_ORDER_TYPE[order_type]
        is_opening = order_type in OPENING_ORDER_TYPES
        if order_type in LONG_OPENING_TYPES:
            side_for_pnl = "long"
        elif is_opening:
            side_for_pnl = "short"
        else:
            side_for_pnl = existing.side if existing else "long"

        # Mode d'exécution et prix de référence déterminés AVANT la
        # quantité : pour un ordre d'ouverture, la quantité se déduit
        # maintenant du montant à risquer ET du prix (voir plus bas), il
        # faut donc déjà connaître ce prix de référence (marché ou cours
        # limité choisi) à ce stade.
        order_mode = st.radio("Mode d'exécution", ["Ordre au marché", "Ordre à cours limité"], horizontal=True)

        if order_mode == "Ordre à cours limité":
            ref_price = st.number_input(
                "Prix cible (€)", min_value=0.01, value=float(round(price_eur, 2)), step=0.5, key="limit_price",
                width=ORDER_INPUT_WIDTH,
            )
        else:
            ref_price = price_eur

        col_lev, col_qty = st.columns(2)
        if is_opening:
            leverage = col_lev.number_input(
                "Levier (x)", min_value=1.0, max_value=MAX_LEVERAGE, value=1.0, step=1.0,
                format="%.0f", key="order_leverage",
                help=f"De x1 à x{MAX_LEVERAGE:g}.", width=ORDER_INPUT_WIDTH,
            )
        else:
            leverage = 1.0
            with col_lev:
                st.caption("Clôturer une position ne fait pas intervenir de nouveau levier : "
                           "la marge déjà engagée est simplement libérée.")

        if is_opening and uses_amount_input:
            # Saisie par montant à risquer (= marge engagée) plutôt que par
            # quantité brute, à l'image des plateformes de trading à effet
            # de levier usuelles (Binance Futures, eToro...) : l'utilisateur
            # part de ce qu'il accepte d'engager, la taille de position s'en
            # déduit — pas l'inverse. Taille de position = montant × levier ;
            # quantité = taille de position / prix de référence. Réservé à
            # Crypto/Forex/Matières premières/Obligations (voir
            # _FRACTIONAL_AMOUNT_CATEGORIES) : une action/ETF classique ne se
            # divise pas dans la réalité, voir la branche ci-dessous.
            amount_at_risk = col_qty.number_input(
                "Montant à risquer (€)", min_value=0.0, max_value=float(max(portfolio.cash, 0.0)),
                value=float(min(1000.0, portfolio.cash)), step=50.0, key="order_amount_at_risk",
                help="La marge que tu acceptes d'engager sur cet ordre — jamais plus que ton cash disponible.",
                width=ORDER_INPUT_WIDTH,
            )
            notional = amount_at_risk * leverage
            # Arrondi à 6 décimales : large marge pour les fractions de
            # crypto (ex : BTC), sans laisser un bruit de calcul flottant
            # visible sur les actifs à prix élevé.
            quantity = round(notional / ref_price, 6) if ref_price > 0 else 0.0
            st.caption(
                f"Taille de position : {notional:,.2f} € → {quantity:g} {ticker} au prix de référence "
                f"({ref_price:,.2f} €)."
            )
        elif is_opening:
            # Actions/ETF/indices : pas de fraction possible (impossible
            # d'acheter 2,28 actions dans la réalité) — l'utilisateur choisit
            # directement un nombre entier de titres, comportement historique
            # inchangé pour cette classe d'actif. Le coût total/la marge s'en
            # déduisent normalement, affichés juste en dessous par
            # _render_order_summary (fonds insuffisants -> ValueError au
            # moment de valider l'ordre, même garde-fou que pour la crypto).
            quantity = float(col_qty.number_input(
                "Quantité", min_value=1, value=1, step=1, format="%d", key="order_qty_shares",
                help="Nombre entier de titres : une action/ETF ne se fractionne pas.",
                width=ORDER_INPUT_WIDTH,
            ))
        if is_opening and quantity > 0:
            _render_order_summary(ref_price, quantity, leverage, side_for_pnl)

        tp_sl_tiers = (
            _render_tp_sl_at_order_form(order_mode, ref_price) if is_opening and existing is None else []
        )

        # Prompt 23 : TP/SL AVANT la validation, pas après. Nouvelle position
        # au marché : paliers du formulaire (ci-dessus, créés à l'exécution).
        # Renforcement d'une position existante : section dédiée à cette
        # position, affichée ici plutôt que sous le bouton. Ordre à cours
        # limité sur une position à créer : rien à configurer avant (la
        # position n'existe pas encore, voir _render_tp_sl_at_order_form).
        tp_sl_section_rendered = existing is not None
        if tp_sl_section_rendered:
            _render_tp_sl_section(portfolio, ticker)

        if order_mode == "Ordre au marché":
            st.markdown('<div class="tsnav-order-note">L\'ordre est exécuté au prix affiché.</div>',
                        unsafe_allow_html=True)
            if st.button("Valider l'ordre", type="primary", key="submit_market_order"):
                if _refresh_price_before_order(ticker, quote_type):
                    return tp_sl_section_rendered
                price_error = _execution_price_error()
                if price_error:
                    st.error(price_error)
                    return tp_sl_section_rendered
                try:
                    if action == "achat":
                        portfolio.buy(ticker, name or ticker, quantity, price_eur, currency, leverage=leverage)
                        # "Position longue ouverte" (pas "Achat exécuté") : même formulation que
                        # "Position courte ouverte" ci-dessous depuis le renommage du bouton
                        # Acheter -> Long (prompt 18) ; message inchangé qu'il s'agisse d'une
                        # ouverture ou d'un renforcement, comme pour le short.
                        msg = f"Position longue ouverte : {quantity:g} x {ticker} à {price_eur:,.2f} € (levier x{leverage:g})."
                    elif action == "vente":
                        pnl = portfolio.sell(ticker, quantity, price_eur)
                        msg = (f"Vente exécutée : {quantity:g} x {ticker} à {price_eur:,.2f} € "
                               f"(P&L réalisé : {pnl:+,.2f} €).")
                    elif action == "ouverture short":
                        portfolio.open_short(ticker, name or ticker, quantity, price_eur, currency, leverage=leverage)
                        msg = f"Position courte ouverte : {quantity:g} x {ticker} à {price_eur:,.2f} € (levier x{leverage:g})."
                    else:  # rachat short
                        pnl = portfolio.cover_short(ticker, quantity, price_eur)
                        msg = (f"Position courte rachetée : {quantity:g} x {ticker} à {price_eur:,.2f} € "
                               f"(P&L réalisé : {pnl:+,.2f} €).")
                except ValueError as e:
                    st.error(str(e))
                else:
                    _tag_last_trade(portfolio, ticker)
                    created = _create_tp_sl_tiers(portfolio, ticker, tp_sl_tiers) if tp_sl_tiers else 0
                    storage.save_portfolio(portfolio)
                    storage.invalidate_valuation_cache()
                    if created:
                        msg += f" {created} palier(s) TP/SL créé(s)."
                    st.session_state["_order_confirmation_message"] = msg
                    st.rerun(scope="app")

        else:  # Ordre à cours limité
            trigger_hint = "descend à" if action in ("achat", "rachat short") else "monte à"
            st.caption(f"L'ordre s'exécutera automatiquement quand le prix {trigger_hint} {ref_price:,.2f} €.")

            if st.button("Placer l'ordre à cours limité", type="primary", key="submit_limit_order"):
                price_error = _execution_price_error()
                if price_error:
                    st.error(price_error)
                    return tp_sl_section_rendered
                try:
                    portfolio.place_limit_order(
                        ticker=ticker, name=name or ticker, action=action, quantity=quantity,
                        limit_price_eur=ref_price, currency=currency, leverage=leverage,
                    )
                except ValueError as e:
                    st.error(str(e))
                else:
                    storage.save_portfolio(portfolio)
                    storage.invalidate_valuation_cache()
                    st.session_state["_order_confirmation_message"] = (
                        f"Ordre à cours limité placé : {quantity:g} x {ticker} à {ref_price:,.2f} €."
                    )
                    st.rerun(scope="app")
    return tp_sl_section_rendered


def render_active_tp_sl_table(
    active_orders: list, container_key: str, empty_message: str, show_ticker: bool = False,
) -> None:
    """Table des paliers TP/SL actifs — factorisée (prompt 21, point 3) entre
    la fiche Trading d'un actif (`show_ticker=False`, le ticker est déjà
    donné par le contexte de la page) et le récapitulatif portefeuille
    entier de ui_portfolio.py (`show_ticker=True`, plusieurs tickers
    mélangés -> colonne Symbole en plus, cliquable comme dans
    render_pending_orders). `container_key` distinct à chaque appel : les
    deux emplacements ne s'affichent jamais dans le même rendu (onglets
    mutuellement exclusifs), mais autant éviter toute clé de conteneur
    dupliquée si ça change un jour."""
    if not active_orders:
        st.caption(empty_message)
        return

    widths = [0.9, 1.1, 1, 1.3, 1, 0.8] if show_ticker else [1.1, 1, 1.3, 1, 0.8]
    labels = (
        ["Symbole", "Type", "Prix cible", "Quantité", "Créé le", ""] if show_ticker
        else ["Type", "Prix cible", "Quantité", "Créé le", ""]
    )
    # Mêmes clés de conteneur que render_table_light (theme.py) : même style
    # de ligne/séparateur ET conversion en cartes empilées sur mobile, sans
    # quoi ce tableau à la main resterait tassé sur petit écran (voir le
    # media query dans theme.py).
    with st.container(key=container_key):
        with st.container(key=f"{container_key}_header"):
            header_cols = st.columns(widths)
            for col, label in zip(header_cols, labels):
                col.markdown(f'<div class="ts-light-col-label">{label}</div>', unsafe_allow_html=True)
        for o in active_orders:
            cols = st.columns(widths)
            i = 0
            if show_ticker:
                bg, fg = theme.badge_color(None)  # catégorie inconnue ici (pas de quote_type stocké)
                key = f"tslight_ticker_tpsl_{o.id}"
                st.markdown(
                    f"<style>.st-key-ts_light .st-key-{key}.stElementContainer .stButton > button "
                    f"{{ background:{bg} !important; color:{fg} !important; }}</style>",
                    unsafe_allow_html=True,
                )
                if cols[0].button(o.ticker, key=key):
                    theme.go_to_trading(o.ticker, o.name)
                i = 1
            color = theme.LIGHT_GREEN if o.kind == tp_sl.KIND_TAKE_PROFIT else theme.LIGHT_RED
            cols[i].markdown(
                f'<span class="ts-cell-mobile-label">Type</span>'
                f'<span style="color:{color};font-weight:600">{tp_sl.KIND_LABELS[o.kind]}</span>',
                unsafe_allow_html=True,
            )
            cols[i + 1].markdown(
                f'<span class="ts-cell-mobile-label">Prix cible</span>'
                f'<span class="ts-light-num">{o.target_price_eur:,.2f} €</span>',
                unsafe_allow_html=True,
            )
            cols[i + 2].markdown(
                f'<span class="ts-cell-mobile-label">Quantité</span>'
                f'<span class="ts-light-num">{o.quantity_pct:g}% ({o.trigger_quantity:g} {o.ticker})</span>',
                unsafe_allow_html=True,
            )
            cols[i + 3].caption(
                f'<span class="ts-cell-mobile-label">Créé le</span>{o.created_at[:10]}',
                unsafe_allow_html=True,
            )
            if cols[i + 4].button("Annuler", key=f"cancel_tp_sl_{container_key}_{o.id}"):
                with db.get_session() as session:
                    tp_sl.cancel_tp_sl(session, o.id, st.session_state.user_id)
                st.rerun()


def render_all_active_tp_sl(portfolio) -> None:
    """Récapitulatif de TOUS les paliers TP/SL actifs du portefeuille, tous
    tickers confondus (prompt 21, point 3 — "ordres en cours" affichés en
    plus dans l'onglet Portefeuille, en plus de leur emplacement actuel sur
    la fiche Trading de chaque actif, voir _render_tp_sl_section)."""
    with db.get_session() as session:
        active_orders = tp_sl.list_for_portfolio(session, portfolio.id, statuses=(tp_sl.STATUS_ACTIVE,))
    with st.container(key="ts_card_tp_sl_summary"):
        st.markdown("##### Paliers Take Profit / Stop Loss actifs")
        render_active_tp_sl_table(
            active_orders, container_key="tslight_table_tpsl_summary",
            empty_message="Aucun palier actif pour l'instant.", show_ticker=True,
        )


def _render_tp_sl_section(portfolio, ticker: str) -> None:
    """Paliers Take Profit / Stop Loss sur la position courante de `ticker`.
    Rien à afficher sans position ouverte : un palier se pose toujours sur
    une position EXISTANTE (voir tp_sl.py) — pour en ajouter un juste après
    un nouvel achat, il suffit de valider l'achat d'abord : la position
    existe alors immédiatement et cette section apparaît juste en dessous au
    rerun suivant, pas besoin d'un formulaire combiné plus complexe.
    """
    position = portfolio.positions.get(ticker)
    if position is None:
        return

    with st.container(key="ts_card_tp_sl"):
        st.markdown("##### Take Profit / Stop Loss")
        st.caption(
            "Vend automatiquement une partie de cette position quand le prix atteint un seuil "
            "exact que tu choisis — même si tu n'as pas l'app ouverte (vérifié toutes les 15 minutes)."
        )

        with db.get_session() as session:
            orders = tp_sl.list_for_portfolio(session, portfolio.id)
        ticker_orders = [o for o in orders if o.ticker == ticker]
        active_orders = [o for o in ticker_orders if o.status == tp_sl.STATUS_ACTIVE]
        past_orders = [o for o in ticker_orders if o.status != tp_sl.STATUS_ACTIVE]

        render_active_tp_sl_table(
            active_orders, container_key="tslight_table_tpsl",
            empty_message="Aucun palier actif sur cet actif pour l'instant.",
        )

        with st.expander("+ Ajouter un palier"):
            kind_labels = [tp_sl.KIND_LABELS[tp_sl.KIND_TAKE_PROFIT], tp_sl.KIND_LABELS[tp_sl.KIND_STOP_LOSS]]
            kind_label = st.segmented_control(
                "Type", kind_labels, default=kind_labels[0], required=True, key="tp_sl_kind_radio",
            )
            kind = tp_sl.KIND_TAKE_PROFIT if kind_label == kind_labels[0] else tp_sl.KIND_STOP_LOSS

            col_price, col_pct = st.columns(2)
            target_price = col_price.number_input(
                "Prix cible (€)", min_value=0.01, value=float(round(position.avg_price_eur, 2)),
                step=0.5, key="tp_sl_target_price",
            )
            quantity_pct = col_pct.slider(
                "% de la position actuelle", min_value=1, max_value=100, value=50, key="tp_sl_quantity_pct",
            )
            trigger_qty = position.quantity * quantity_pct / 100
            st.caption(
                f"Déclenchement : vente de {trigger_qty:g} {ticker} sur les {position.quantity:g} "
                f"détenus actuellement (figé à la création, ne bougera pas même si la position "
                "change ensuite)."
            )

            if st.button("Créer le palier", type="primary", key="submit_tp_sl"):
                try:
                    with db.get_session() as session:
                        tp_sl.create_tp_sl(
                            session, portfolio.id, st.session_state.user_id, position,
                            kind, target_price, float(quantity_pct),
                        )
                except ValueError as e:
                    st.error(str(e))
                else:
                    st.session_state["_order_confirmation_message"] = "Palier créé."
                    st.rerun()

        if past_orders:
            with st.expander(f"Historique des paliers sur {ticker} ({len(past_orders)})"):
                for o in past_orders:
                    status_label = "Exécuté" if o.status == tp_sl.STATUS_EXECUTED else "Annulé"
                    line = f"{tp_sl.KIND_LABELS[o.kind]} à {o.target_price_eur:,.2f} € ({o.quantity_pct:g}%) — **{status_label}**"
                    if o.executed_at:
                        line += f" le {o.executed_at[:10]}"
                    st.markdown(f"- {line}")


# -- Explications pédagogiques ---------------------------------------------

# Contenu condensé à partir de ui_tutorial.py (chapitres 4/5/6 et "Take Profit
# / Stop Loss") : mêmes notions, reformulées en 2-3 phrases chacune plutôt que
# reprises telles quelles (le tutoriel détaille avec des exemples chiffrés,
# cette zone sert de pense-bête rapide pendant que l'utilisateur trade).
def _render_explanations() -> None:
    """Zone pédagogique séparée sous le graphique/panneau d'ordre : reprend
    en version courte les mécanismes déjà détaillés dans l'onglet Tutoriel
    (Marché/Limite, Long/Short, levier, TP/SL, liquidation) — volontairement
    hors du panneau d'ordre (point 3 du prompt layout Hyperliquid) pour ne
    pas l'alourdir pendant que l'utilisateur passe un ordre. Peut être
    consultée à part, repliée par défaut (st.expander) pour rester discrète.
    """
    with st.container(key="ts_card_explanations"):
        st.markdown("##### Comprendre les mécanismes")
        with st.expander("Ordre au marché vs ordre à cours limité"):
            st.markdown(
                "- **Marché** : exécution immédiate, au prix affiché à l'instant T.\n"
                "- **Cours limité** : tu fixes un prix cible, l'ordre s'exécute automatiquement "
                "seulement quand le marché atteint ce niveau (visible et annulable depuis "
                "\"Ordres en attente\" tant qu'il n'est pas exécuté)."
            )
        with st.expander("Position longue (Long) vs position courte (Short)"):
            st.markdown(
                "- **Long** : tu achètes en pariant sur une **hausse** du prix — le réflexe classique.\n"
                "- **Short** : tu paries sur une **baisse**, sans posséder l'actif au départ. Tu gagnes "
                "si le prix baisse, tu perds s'il monte : c'est l'inverse du Long."
            )
        with st.expander("Effet de levier et marge"):
            st.markdown(
                "Le **levier** te permet de contrôler une position plus grosse que l'argent réellement "
                "engagé (la **marge**) : par exemple 100 € engagés à levier x10 contrôlent une position "
                "de 1000 €. Gains ET pertes sont amplifiés dans les mêmes proportions, dans les deux sens."
            )
        with st.expander("Take Profit / Stop Loss"):
            st.markdown(
                "Des paliers de sortie automatique posés sur une position détenue : un **prix cible "
                "exact** et un **% de la position** à vendre une fois ce prix atteint. Vérifiés et "
                "exécutés automatiquement toutes les 15 minutes, même app fermée — annulables tant "
                "qu'ils ne se sont pas déclenchés."
            )
        with st.expander("Liquidation automatique par marge de maintenance"):
            st.markdown(
                f"Une position à levier (x2 ou plus, jamais x1) est fermée automatiquement dès que sa "
                f"perte latente atteint {valuation.MAINTENANCE_LOSS_RATIO * 100:.0f}% de la marge "
                "engagée — ta perte ne peut donc jamais dépasser ce seuil, même si tu n'as pas "
                "l'application ouverte (vérifié toutes les 15 minutes)."
            )


def render_pending_orders(portfolio) -> None:
    """Ordres à cours limité en attente (portefeuille entier, pas scopé à un
    ticker) — sans underscore : appelé aussi depuis ui_portfolio.py (prompt
    21, point 3, "ordres en cours" affichés en plus dans l'onglet
    Portefeuille), pas seulement ici en bas de la fiche Trading."""
    with st.container(key="ts_card_pending"):
        st.markdown("##### Ordres en attente")
        if not portfolio.pending_orders:
            st.caption("Aucun ordre en attente.")
            return

        buy_side = ("achat", "rachat short")
        rows = [{
            "ticker": o.id,  # row_key : l'id d'ordre, unique (plusieurs ordres possibles sur le même ticker)
            "symbol": o.ticker,
            "name": o.name,
            "action": theme.action_label(o.action),
            "quantity": o.quantity,
            "limit_price": o.limit_price_eur,
            "leverage": f"x{o.leverage:g}",
            "_action_kind": o.action,
            "_order_id": o.id,
        } for o in portfolio.pending_orders]

        widths = [1, 2, 1, 1.2, 0.8, 1]
        # Conteneurs tslight_table_/tslight_header_ : mêmes clés que
        # render_table_light (theme.py), pour hériter du même style de ligne/
        # séparateur ET de la conversion en cartes empilées sur mobile (voir
        # le media query dans theme.py) — sans quoi ce tableau, à la main,
        # resterait tassé sur 6 colonnes sur petit écran.
        with st.container(key="tslight_table_pending"):
            with st.container(key="tslight_header_pending"):
                header_cols = st.columns(widths)
                for col, label in zip(header_cols, ["Symbole", "Action", "Quantité", "Prix limite", "Levier", ""]):
                    col.markdown(f'<div class="ts-light-col-label">{label}</div>', unsafe_allow_html=True)

            for row in rows:
                cols = st.columns(widths)
                bg, fg = theme.badge_color(None)  # catégorie inconnue ici (pas de quote_type stocké)
                key = f"tslight_ticker_pending_{row['_order_id']}"
                st.markdown(
                    f"<style>.st-key-ts_light .st-key-{key}.stElementContainer .stButton > button "
                    f"{{ background:{bg} !important; color:{fg} !important; }}</style>",
                    unsafe_allow_html=True,
                )
                if cols[0].button(row["symbol"], key=key):
                    theme.go_to_trading(row["symbol"], row["name"])
                color = theme.LIGHT_GREEN if row["_action_kind"] in buy_side else theme.LIGHT_RED
                cols[1].markdown(
                    f'<span class="ts-cell-mobile-label">Action</span>'
                    f'<span style="color:{color};font-weight:600">{row["action"]}</span> '
                    f'<span class="ts-light-col-label">{row["name"]}</span>',
                    unsafe_allow_html=True,
                )
                cols[2].markdown(
                    f'<span class="ts-cell-mobile-label">Quantité</span>'
                    f'<span class="ts-light-num">{row["quantity"]:g}</span>',
                    unsafe_allow_html=True,
                )
                cols[3].markdown(
                    f'<span class="ts-cell-mobile-label">Prix limite</span>'
                    f'<span class="ts-light-num">{row["limit_price"]:,.2f} €</span>',
                    unsafe_allow_html=True,
                )
                cols[4].markdown(
                    f'<span class="ts-cell-mobile-label">Levier</span>'
                    f'<span class="ts-light-num">{row["leverage"]}</span>',
                    unsafe_allow_html=True,
                )
                if cols[5].button("Annuler", key=f"cancel_{row['_order_id']}"):
                    portfolio.cancel_order(row["_order_id"])
                    storage.save_portfolio(portfolio)
                    st.rerun()


# -- Point d'entrée -------------------------------------------------------------

def render(portfolio) -> None:
    theme.inject_light()
    # À consommer avant de recréer le widget search_query ci-dessous (voir la
    # docstring de theme.go_to_trading : la remise à zéro ne peut pas se faire
    # après coup dans le même run que celui qui l'a demandée).
    if st.session_state.pop("_clear_search_query", False):
        st.session_state["search_query"] = ""

    with st.container(key="ts_light"):
        ui_cards.inject_css()
        ticker = st.session_state.get("selected_ticker")
        name = st.session_state.get("selected_name")
        quote_type = st.session_state.get("selected_quote_type", "")

        if not ticker:
            nav = ui_trading_nav.current()
            view = (nav or {}).get("view", "list")
            if not nav:
                # Accueil : en-tête, recherche (+ récents), cartes de catégories.
                ui_trading_nav.render_home_header()
                _render_search()
                ui_trading_nav.render_home_categories()
            elif view == "zones":
                ui_trading_nav.render_zones()
            elif view == "countries" and nav.get("zone") in trading_nav_config.ZONES:
                ui_trading_nav.render_countries(nav["zone"])
            elif view == "currencies":
                ui_trading_nav.render_currencies()
            else:
                _render_category_list(nav["category"], nav.get("zone"), nav.get("country"), nav.get("group"))
            return

        # Rechargement complet = interaction, sauf celui qui déclenche la
        # pause d'inactivité lui-même (voir _pause_if_inactive).
        if not st.session_state.pop("_auto_refresh_pause_rerun", False):
            _note_interaction()

        if st.session_state.get("_last_recorded_search") != ticker:
            try:
                search_history.record(st.session_state.user_id, ticker, name or ticker, quote_type)
            except Exception:
                pass  # l'historique de recherche est un confort, jamais bloquant
            st.session_state["_last_recorded_search"] = ticker

        ui_trading_nav.render_asset_breadcrumb(ticker, name, quote_type)

        # Nom/ticker de l'actif consulté, absent jusqu'ici en haut de la fiche
        # (seul le prix, plus bas, permettait de confirmer quel actif était
        # affiché). Nom en titre + ticker à part quand il diffère du nom
        # (cas courant : "Apple Inc." / AAPL) ; juste le ticker sinon (repli
        # manuel sans nom connu, voir _render_search).
        category = ui_trading_nav.asset_category(ticker, quote_type)
        place = None
        places = trading_nav_config.ASSET_PLACES.get(ticker)
        if places and places[1] in trading_nav_config.PAYS:
            place = trading_nav_config.PAYS[places[1]]["nom"]
        ui_cards.asset_header(name or ticker, ticker, category, place)

        # Layout façon Hyperliquid (desktop) : graphique à gauche (majorité de
        # la largeur), carnet d'ordre simulé (prompt 20, colonne fine, PUREMENT
        # décoratif — voir _render_order_book) au centre, panneau d'ordre à
        # droite — repasse en 1 colonne empilée (graphique en haut, panneau en
        # dessous, carnet masqué) sur mobile ET sur les largeurs intermédiaires
        # <1100px (voir le media query dans theme.py : le carnet ne doit
        # jamais compresser le graphique ou le formulaire, ce sont les 2
        # éléments prioritaires de la page — il se masque avant eux si la
        # place manque). Panneau volontairement PAS sticky : défile
        # normalement avec le reste de la page au scroll.
        with st.container(key="ts_trading_layout_row"):
            col_chart, col_book, col_order = st.columns([2.0, 0.55, 1])
            with col_chart:
                _render_price_and_chart(ticker, quote_type, portfolio.history)

            with col_book:
                _render_order_book(ticker)

            # Déposé en session par le fragment ci-dessus (voir sa docstring) :
            # il a déjà tourné une fois de façon synchrone à ce stade du
            # script, cette valeur est donc à jour pour ce rerun.
            price_eur = st.session_state.get("trading_price_eur")
            currency = st.session_state.get("trading_currency")

            with col_order:
                if price_eur is not None:
                    _render_order_panel(portfolio, ticker, name, price_eur, currency, quote_type)

        if price_eur is None:
            return  # l'erreur a déjà été affichée par le fragment

        _render_explanations()
        render_pending_orders(portfolio)
