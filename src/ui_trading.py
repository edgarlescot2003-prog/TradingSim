"""Contenu de l'onglet Trading : thème clair scopé (voir theme.inject_light,
comme l'onglet Portefeuille) — page d'accueil avec encadrés d'actifs cliquables
tant qu'aucun actif n'est sélectionné, recherche unifiée avec historique par
utilisateur, fiche prix/graphique (mécanique inchangée : fragment 30s,
sélecteur de période), formulaire d'ordre avec récapitulatif (coût/marge/
liquidation/simulation P&L).

Layout de la fiche d'un actif sélectionné, façon Hyperliquid (voir
ts_trading_layout_row dans render()) : 2 colonnes sur desktop (graphique à
gauche, panneau d'ordre + TP/SL à droite, non sticky), 1 colonne empilée sur
mobile (media query dans theme.py). Les explications pédagogiques
(_render_explanations) vivent dans une zone séparée sous ce bloc, pas dans le
panneau d'ordre lui-même.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
import streamlit as st

from . import db
from . import kraken_data
from . import market_data as md
from . import search_history
from . import storage
from . import theme
from . import tp_sl
from . import valuation

# -- Univers d'actifs "vitrine" de la page d'accueil -------------------------
# 5 actifs par encadré (Indices/Top capitalisation) : FTSE 100 et Meta
# retirés pour désencombrer la page (CAC 40 + DAX + Nikkei 225 gardent une
# couverture Europe/Asie, S&P 500 + Nasdaq les US ; NVDA/AAPL/MSFT/GOOGL/AMZN
# restent la sélection la plus large en styles de business).
INDICES = [
    ("^FCHI", "CAC 40"), ("^GDAXI", "DAX"), ("^GSPC", "S&P 500"),
    ("^IXIC", "Nasdaq"), ("^N225", "Nikkei 225"),
]
TOP_CAP = [
    ("AAPL", "Apple"), ("MSFT", "Microsoft"), ("NVDA", "Nvidia"),
    ("GOOGL", "Alphabet"), ("AMZN", "Amazon"),
]
CRYPTO = [
    ("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum"), ("SOL-USD", "Solana"), ("XRP-USD", "XRP"),
]
# 5 paires majeures pour la vitrine — 10 autres paires majeures/croisées
# restent disponibles via la recherche (voir valuation.category_for, qui
# détecte le quoteType "CURRENCY" générique de yfinance, pas une liste figée
# de tickers) : GBPUSD=X, USDJPY=X, USDCHF=X, USDCAD=X, NZDUSD=X, EURJPY=X,
# EURCHF=X, GBPJPY=X, AUDJPY=X, EURAUD=X, GBPCHF=X, CHFJPY=X — toutes
# vérifiées disponibles (prix + historique) avant intégration.
FOREX = [
    ("EURUSD=X", "EUR/USD"), ("GBPUSD=X", "GBP/USD"), ("USDJPY=X", "USD/JPY"),
    ("USDCHF=X", "USD/CHF"), ("AUDUSD=X", "AUD/USD"),
]
COMMODITIES = [
    ("GC=F", "Or"), ("SI=F", "Argent"), ("CL=F", "Pétrole WTI"),
    ("BZ=F", "Pétrole Brent"), ("NG=F", "Gaz naturel"),
]
# ETF obligataires (voir valuation.BOND_ETF_TICKERS) : les tickers de
# rendement d'État bruts (^TNX, ^TYX...) ne sont PAS des prix négociables,
# incompatibles avec le système de marge/P&L/liquidation — voir la doc de
# conception d'origine de ce chantier.
BONDS = [
    ("TLT", "Treasury 20+ ans"), ("IEF", "Treasury 7-10 ans"), ("BND", "Obligations US (total market)"),
    ("AGG", "Obligations US (agrégé)"), ("SHY", "Treasury 1-3 ans"),
]
# Suggestions par défaut de la recherche quand l'utilisateur n'a pas encore
# d'historique de recherche (ticker, nom, catégorie — pour le badge coloré).
DEFAULT_SUGGESTIONS = (
    [(t, n, "Actions") for t, n in TOP_CAP[:4]] + [(t, n, "Crypto") for t, n in CRYPTO[:2]]
)

ASSET_ROW_COLUMNS = [
    {"key": "ticker", "label": "Symbole", "kind": "ticker_badge", "width": 0.9},
    {"key": "name", "label": "Nom", "kind": "link", "width": 1.0},
    {"key": "price", "label": "Prix", "kind": "mono_text", "width": 1.5},
    {"key": "change_pct", "label": "Var. jour", "kind": "signed_pct", "width": 1.0},
    {"key": "change_30d_pct", "label": "Var. 30j", "kind": "signed_pct", "width": 1.0},
]
SEARCH_RESULT_COLUMNS = [
    {"key": "ticker", "label": "Symbole", "kind": "ticker_badge"},
    {"key": "name", "label": "Nom", "kind": "link"},
]

MAX_LEVERAGE = 20.0

# Durée d'affichage du toast de confirmation d'ordre (st.toast, voir
# _render_order_form) : un simple st.success() ici disparaîtrait quasi
# instantanément à cause du st.rerun() qui suit immédiatement pour
# rafraîchir le reste de la page (positions, cash...) — st.toast est le seul
# mécanisme Streamlit qui survit à ce rerun et s'efface tout seul après un
# délai réel, indépendamment de toute interaction utilisateur.
ORDER_CONFIRMATION_TOAST_SECONDS = 6

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
    "Vendre": "vente",
    "Vendre à découvert (position courte)": "ouverture short",
    "Vendre plus à découvert": "ouverture short",
    "Racheter (clôturer)": "rachat short",
}


# -- Cotations pour la page d'accueil -----------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def _fetch_quotes(tickers: tuple[str, ...]) -> dict[str, dict]:
    """Prix + variation du jour pour chaque ticker, récupérés en parallèle
    (comme leaderboard.py) et mis en cache 60s : la page d'accueil affiche une
    vitrine d'une vingtaine d'actifs, un appel séquentiel serait trop lent, et
    ces chiffres n'ont pas besoin d'être aussi frais que le prix de l'actif
    réellement sélectionné (qui a son propre rafraîchissement 30s)."""
    def fetch_one(ticker: str):
        try:
            quote = md.get_quote(ticker)
        except md.MarketDataError:
            return ticker, None
        change_pct = None
        previous_close = quote.get("previous_close")
        if previous_close:
            change_pct = (quote["price"] - previous_close) / previous_close * 100
        return ticker, {"price": quote["price"], "currency": quote["currency"], "change_pct": change_pct}

    out: dict[str, dict] = {}
    if not tickers:
        return out
    with ThreadPoolExecutor(max_workers=min(8, len(tickers))) as executor:
        for ticker, data in executor.map(fetch_one, tickers):
            if data is not None:
                out[ticker] = data
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_30d_changes(tickers: tuple[str, ...]) -> dict[str, float | None]:
    """Variation sur 30 jours glissants pour chaque ticker, mise en cache 1h :
    contrairement au prix (fast_info, quasi gratuit), ce calcul nécessite de
    récupérer tout un historique, plus coûteux ; et une tendance sur 30 jours
    ne bouge de toute façon pas d'une minute à l'autre, un cache plus long
    que celui du prix n'y perd donc rien en fraîcheur perçue."""
    def fetch_one(ticker: str):
        try:
            hist = md.get_history(ticker, period="1mo", interval="1d")
        except md.MarketDataError:
            return ticker, None
        closes = hist["Close"]
        if len(closes) < 2 or not closes.iloc[0]:
            return ticker, None
        return ticker, float((closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0] * 100)

    out: dict[str, float | None] = {}
    if not tickers:
        return out
    with ThreadPoolExecutor(max_workers=min(8, len(tickers))) as executor:
        for ticker, change_pct in executor.map(fetch_one, tickers):
            out[ticker] = change_pct
    return out


def _format_price(ticker: str, price: float, currency: str) -> str:
    if ticker.startswith("^"):
        return f"{price:,.2f} pts"
    return f"{price:,.2f} {currency}"


def _render_asset_detail(row: dict) -> None:
    """Contenu de l'expander "Détails" sous une ligne compacte mobile d'un
    encadré d'actifs (voir theme.render_compact_list) : la var. 30j, qui n'a
    pas sa place dans la ligne compacte (déjà 2 valeurs : prix + var. jour),
    et un moyen d'ouvrir la fiche de l'actif — sans lui, une ligne compacte
    mobile (contrairement à sa version desktop, un vrai st.button cliquable)
    n'a aucune interaction du tout, donc aucun moyen d'atteindre le
    formulaire d'ordre depuis cette liste sur mobile (repéré en vérifiant le
    rendu mobile du prompt 13 : impossible d'ouvrir un actif à partir des
    encadrés d'accueil sur un écran étroit)."""
    change_30d = row.get("change_30d_pct")
    if change_30d is not None:
        color = theme.LIGHT_GREEN if change_30d >= 0 else theme.LIGHT_RED
        sign = "+" if change_30d >= 0 else ""
        st.markdown(
            f"Variation 30j : {theme.mono(f'{sign}{change_30d:.2f}%', color=color)}", unsafe_allow_html=True,
        )
    else:
        st.caption("Variation 30j indisponible.")
    if st.button("Voir la fiche →", key=f"mobile_goto_asset_{row['ticker']}", use_container_width=True):
        theme.go_to_trading(row["ticker"], row.get("nav_name", row["name"]))


def _render_asset_box(card_key: str, title: str, assets: list[tuple[str, str]],
                       quotes: dict, category: str) -> None:
    with st.container(key=f"ts_card_{card_key}"):
        st.markdown(f"##### {title}")
        rows = []
        for ticker, name in assets:
            q = quotes.get(ticker)
            rows.append({
                "ticker": ticker,
                "name": name,
                "category": category,
                "price": _format_price(ticker, q["price"], q["currency"]) if q else None,
                "change_pct": q["change_pct"] if q else None,
                "change_30d_pct": q.get("change_30d_pct") if q else None,
            })

        table_key = f"compact_{card_key}"
        # Rendu double (desktop table / mobile liste compacte) : auparavant
        # seul le rendu desktop existait, donc chaque ligne (5 colonnes)
        # s'empilait en grosse carte sur mobile plutôt qu'en une ligne
        # resserrée façon Kraken/TradingView — repéré au test réel ("chiffres
        # qui se chevauchent" : la var. jour d'une ligne chevauchait le
        # libellé de prix de la ligne suivante une fois les cartes tassées).
        with st.container(key=f"tslight_desktop_wrap_{table_key}"):
            theme.render_table_light(rows, ASSET_ROW_COLUMNS, row_key="ticker", table_key=table_key)

        compact_rows = [{
            **row,
            "primary": row["price"] or "—",
            "secondary": f"{row['change_pct']:+.2f}%" if row["change_pct"] is not None else "—",
            "secondary_color": (
                (theme.LIGHT_GREEN if row["change_pct"] >= 0 else theme.LIGHT_RED)
                if row["change_pct"] is not None else theme.LIGHT_TEXT
            ),
        } for row in rows]
        theme.render_compact_list(compact_rows, table_key=table_key, detail=_render_asset_detail)


def _render_home_boxes() -> None:
    universe = INDICES + TOP_CAP + CRYPTO + FOREX + COMMODITIES + BONDS
    tickers = tuple(t for t, _ in universe)
    quotes = _fetch_quotes(tickers)
    changes_30d = _fetch_30d_changes(tickers)
    for ticker, data in quotes.items():
        data["change_30d_pct"] = changes_30d.get(ticker)

    # Conteneur dédié : sert d'ancrage CSS pour forcer le passage à 1 colonne
    # sur mobile (voir le media query dans theme.py), sans dépendre du seul
    # comportement natif de Streamlit.
    with st.container(key="ts_home_grid"):
        row1 = st.columns(2)
        with row1[0]:
            _render_asset_box("home_indices", "Indices majeurs", INDICES, quotes, category="Indices/ETF")
        with row1[1]:
            _render_asset_box("home_topcap", "Top capitalisation", TOP_CAP, quotes, category="Actions")

        row2 = st.columns(2)
        with row2[0]:
            _render_asset_box("home_crypto", "Crypto les plus suivies", CRYPTO, quotes, category="Crypto")
        with row2[1]:
            _render_asset_box("home_forex", "Forex", FOREX, quotes, category="Forex")

        row3 = st.columns(2)
        with row3[0]:
            _render_asset_box(
                "home_commodities", "Matières premières", COMMODITIES, quotes, category="Matières premières",
            )
        with row3[1]:
            _render_asset_box("home_bonds", "Obligations (ETF)", BONDS, quotes, category="Obligations")


# -- Recherche -----------------------------------------------------------------

def _search_tradable_assets(query: str) -> list[dict]:
    try:
        results = md.search_assets(query)
    except md.MarketDataError as e:
        st.error(str(e))
        return []
    return results


def _render_search_result_detail(row: dict) -> None:
    """Contenu de l'expander "Détails" sous une ligne compacte mobile d'une
    liste de recherche (voir _render_search_result_list) : pas d'info
    supplémentaire à afficher ici (ticker+nom seulement, pas de prix), donc
    uniquement le bouton d'ouverture de la fiche — sans lui, une ligne
    compacte mobile n'a aucun moyen d'atteindre le formulaire d'ordre."""
    if st.button("Voir la fiche →", key=f"mobile_goto_search_{row['ticker']}", use_container_width=True):
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
    theme.render_compact_list(rows, table_key=table_key, detail=_render_search_result_detail)


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
                placeholder="Nom ou ticker : Apple, AAPL, Bitcoin, CAC 40...",
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


@st.cache_data(ttl=20, show_spinner=False)
def _fetch_chart_history(ticker: str, quote_type: str, period_key: str):
    """Récupère l'historique pour le graphique, en choisissant la source
    (Kraken pour la crypto, Yahoo sinon) et en appliquant le repli
    automatique d'intervalle. Retourne (DataFrame, intervalle_effectif, source).

    Mis en cache 20s (comme get_quote) : sans ça, changer de période/type de
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


@st.fragment(run_every=30)
def _render_price_and_chart(ticker: str, quote_type: str) -> None:
    """Prix + graphique de `ticker`, isolés dans leur propre fragment : se
    rafraîchissent seuls toutes les 30 secondes (run_every), sans recharger
    le reste de la page (portefeuille, autres onglets, formulaire d'ordre
    ci-dessous). Comme un fragment ne peut pas faire vivre une valeur "live"
    en dehors de lui, le prix converti est déposé dans st.session_state pour
    que le formulaire d'ordre (hors fragment) puisse s'en servir.
    """
    try:
        with st.spinner(f"Chargement de {ticker}..."):
            quote = md.get_quote(ticker)
    except md.MarketDataError as e:
        st.error(str(e))
        st.session_state.trading_price_eur = None
        return

    price_native, currency = quote["price"], quote["currency"]
    try:
        price_eur = md.convert_to_eur(price_native, currency)
    except md.MarketDataError as e:
        st.error(f"Conversion en euros impossible : {e}")
        st.session_state.trading_price_eur = None
        return

    st.session_state.trading_price_eur = price_eur
    st.session_state.trading_currency = currency

    previous_close = quote.get("previous_close")
    day_up = previous_close is None or price_native >= previous_close

    col1, col2 = st.columns(2)
    col1.metric(f"Prix actuel ({currency})", f"{price_native:,.2f}")
    col2.metric("Prix actuel (€)", f"{price_eur:,.2f}")
    st.caption(
        "Prix légèrement différé (source : Yahoo Finance) · actualisation automatique toutes les 30 secondes "
        f"· dernière actualisation : {datetime.now().strftime('%H:%M:%S')}"
    )

    col_a, col_b = st.columns([3, 1])
    period_key = col_a.radio(
        "Période", list(PERIOD_INTERVAL.keys()), horizontal=True, index=4, key="chart_period_radio",
    )
    chart_type = col_b.radio("Type", ["Courbe", "Chandeliers"], key="chart_type_radio")

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
    fig.update_layout(**theme.plotly_layout(height=450, margin=dict(l=10, r=10, t=20, b=10),
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

    # scrollZoom=False : désactive le zoom à la molette/pinch (jugé peu
    # pratique, pas la fenêtre par défaut ci-dessus, mais l'INTERACTION de
    # zoom continue) — le sélecteur de période reste le seul moyen de
    # changer l'échelle affichée. Le survol (hover) et le double-clic pour
    # réinitialiser le zoom restent actifs (gérés par Plotly indépendamment
    # de ce flag) ; même flag côté Plotly.js pour le pinch tactile, pas de
    # réglage séparé à faire pour le mobile.
    # theme.PLOTLY_CONFIG (displaylogo + modebar allégée) fusionné avec le
    # scrollZoom désactivé ci-dessus : le zoom/pan/reset restent disponibles.
    st.plotly_chart(fig, use_container_width=True, config={**theme.PLOTLY_CONFIG, "scrollZoom": False})

    fallback_note = "" if effective_interval == PERIOD_INTERVAL[period_key] else " (repli, plage trop longue)"
    st.caption(
        f"{len(hist)} bougies chargées · intervalle {effective_interval}{fallback_note} · source {source}"
    )
    st.caption(theme.PLOTLY_ZOOM_HINT)


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


def _render_side_toggle(options: list[str], key: str) -> str:
    """Remplace st.radio par deux boutons cliquables côte à côte, dans
    l'esprit Buy/Sell d'un terminal de trading pro (Hyperliquid) — pas de
    bouton rond à cocher. Couleur déterminée par le SENS de l'action
    (ACTION_BY_ORDER_TYPE), pas par la position dans la liste : achat/rachat
    short = vert (GREEN), vente/ouverture short = rouge (RED) — cohérent
    dans les 3 contextes où ce sélecteur apparaît (aucune position, position
    longue existante, position courte existante), y compris quand "vendre"
    sert à clôturer un long plutôt qu'à ouvrir un short. L'option active a un
    fond plein, l'inactive un simple contour — dans sa propre couleur, pas
    l'orange ACCENT (seul le sens Long/Short fait exception à la règle des
    boutons oranges, voir le prompt "Retouches formulaire/benchmark")."""
    current = st.session_state.get(key)
    if current not in options:
        current = options[0]

    # Deux passes : d'abord rendre les boutons et repérer un clic éventuel
    # (qui met à jour `current` tout de suite), PUIS calculer les styles à
    # partir de ce `current` final — sinon un clic sur le bouton inactif ne
    # changeait la couleur qu'au rerun SUIVANT (le style de CETTE passe était
    # déjà calculé avec l'ancienne sélection avant que le clic soit détecté).
    cols = st.columns(len(options))
    btn_keys = [f"{key}_opt_{i}" for i in range(len(options))]
    for option, btn_key, col in zip(options, btn_keys, cols):
        if col.button(option, key=btn_key, use_container_width=True):
            current = option
    st.session_state[key] = current

    style_rules = []
    for option, btn_key in zip(options, btn_keys):
        action = ACTION_BY_ORDER_TYPE[option]
        color = theme.GREEN if action in ("achat", "rachat short") else theme.RED
        # Sélecteur à 3 classes (ts_light + la clé du bouton + stElementContainer,
        # puis .stButton > button) — même technique que badge_color/
        # _render_action_tabs : la règle générique ".st-key-ts_light .stButton
        # > button" (2 classes) a une spécificité plus élevée qu'un simple
        # ".st-key-{btn_key} button" (1 classe) et l'emportait sur la couleur
        # voulue ici malgré le !important (bug latent découvert en vérifiant
        # au pixel près le rendu du prompt 13 — les boutons ressortaient tous
        # dans le même style neutre, sans vert/rouge).
        selector_base = f'.st-key-ts_light .st-key-{btn_key}.stElementContainer .stButton > button'
        if option == current:
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


def _render_action_tabs(key: str, buy_enabled: bool, sell_enabled: bool, short_enabled: bool,
                         sell_help: str = "", short_help: str = "") -> str:
    """3 actions distinctes, TOUJOURS affichées (contrairement à l'ancien
    sélecteur à 2 options dont le libellé changeait selon le contexte, ex.
    "Acheter (position longue)" puis "Acheter plus") : Acheter / Vendre /
    Short, chacune avec son propre texte et sa propre couleur (voir prompt
    "Distinction claire Acheter / Vendre / Short"). Vendre et Short sont
    DÉSACTIVÉS (pas masqués : la raison reste visible en infobulle) quand
    l'action n'est pas possible sur la position actuelle — Long et Short
    sont mutuellement exclusifs sur un même ticker (voir Portfolio.buy/
    open_short, qui le refusent déjà côté métier ; ce composant ne fait que
    refléter cette règle existante, jamais l'inverse).

    Retourne "acheter" | "vendre" | "short".
    """
    options = [
        ("acheter", "Acheter", theme.GREEN, buy_enabled, ""),
        ("vendre", "Vendre", theme.SELL_NEUTRAL, sell_enabled, sell_help),
        ("short", "Short", theme.RED, short_enabled, short_help),
    ]

    current = st.session_state.get(key)
    enabled_by_value = {value: enabled for value, _, _, enabled, _ in options}
    if current not in enabled_by_value or not enabled_by_value[current]:
        # Repli sur la première option disponible : ex. après une clôture
        # totale qui fait passer l'actif de "long" à "aucune position", le
        # choix "Vendre" n'est plus valide — pas de raison de rester bloqué
        # dessus (le bouton est de toute façon désactivé, donc plus
        # cliquable) plutôt que de basculer proprement sur Acheter.
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


def _render_order_form(portfolio, ticker: str, name: str | None, price_eur: float, currency: str,
                        quote_type: str = "") -> None:
    with st.container(key="ts_card_order"):
        st.markdown("##### Passer un ordre")

        uses_amount_input = _uses_amount_input(ticker, quote_type)
        existing = portfolio.positions.get(ticker)
        has_long = existing is not None and existing.side == "long"
        has_short = existing is not None and existing.side == "short"

        action_choice = _render_action_tabs(
            key="order_action_tab",
            buy_enabled=not has_short,
            sell_enabled=has_long,
            short_enabled=not has_long,
            sell_help=(
                "" if has_long else f"Aucune position longue détenue sur {ticker} : rien à vendre."
            ),
            short_help=(
                "" if not has_long
                else f"Position longue déjà ouverte sur {ticker} : vends-la d'abord (onglet Vendre)."
            ),
        )

        if action_choice == "acheter":
            if existing is None:
                st.caption(f"Aucune position ouverte sur {ticker}.")
                order_type = "Acheter (position longue)"
            else:
                st.caption(f"Position actuelle : {existing.quantity:g} {ticker} en position longue "
                           f"(prix moyen {existing.avg_price_eur:,.2f} €).")
                _render_maintenance_indicator(existing, price_eur)
                order_type = "Acheter plus"
        elif action_choice == "vendre":
            # Exigence explicite du prompt "Distinction claire Acheter/Vendre/
            # Short" : la quantité détenue doit ressortir clairement, pour que
            # l'utilisateur sache combien il peut vendre au maximum — avant,
            # cette information était noyée dans une phrase générique
            # ("Position actuelle : ..."), pas mise en avant comme un plafond.
            st.caption(f"Tu détiens : {theme.mono(f'{existing.quantity:g} {ticker}')} en position longue "
                       f"(prix moyen {existing.avg_price_eur:,.2f} €).", unsafe_allow_html=True)
            _render_maintenance_indicator(existing, price_eur)
            order_type = "Vendre"
        else:  # short
            if existing is None:
                st.caption(f"Aucune position ouverte sur {ticker}.")
                order_type = "Vendre à découvert (position courte)"
            else:
                st.caption(f"Position actuelle : {existing.quantity:g} {ticker} en position courte "
                           f"(prix moyen {existing.avg_price_eur:,.2f} €).")
                _render_maintenance_indicator(existing, price_eur)
                # Sous-choix propre au short déjà ouvert (renforcer / racheter) :
                # ce sont deux actions différentes que l'onglet Short doit
                # toutes les deux couvrir (comportement déjà existant, juste
                # déplacé ici plutôt que d'être le sélecteur de premier niveau).
                order_type = _render_side_toggle(
                    ["Vendre plus à découvert", "Racheter (clôturer)"], key="order_type_short_sub",
                )

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
        else:
            default_qty = existing.quantity if order_type in ("Vendre", "Racheter (clôturer)") else 1.0
            quantity = col_qty.number_input(
                "Quantité", min_value=0.0, value=float(default_qty), step=1.0, key="order_qty",
                width=ORDER_INPUT_WIDTH,
            )

        if is_opening and quantity > 0:
            _render_order_summary(ref_price, quantity, leverage, side_for_pnl)
        elif not is_opening and quantity > 0:
            exposure_str = f"{quantity * ref_price:,.2f} €"
            cash_str = f"{portfolio.cash:,.2f} €"
            st.caption(
                f"Exposition : {theme.mono(exposure_str)} · Cash disponible : {theme.mono(cash_str)}",
                unsafe_allow_html=True,
            )

        tp_sl_tiers = (
            _render_tp_sl_at_order_form(order_mode, ref_price) if is_opening and existing is None else []
        )

        if order_mode == "Ordre au marché":
            if st.button("Valider l'ordre", type="primary", key="submit_market_order"):
                try:
                    if action == "achat":
                        portfolio.buy(ticker, name or ticker, quantity, price_eur, currency, leverage=leverage)
                        msg = f"Achat exécuté : {quantity:g} x {ticker} à {price_eur:,.2f} € (levier x{leverage:g})."
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
                    created = _create_tp_sl_tiers(portfolio, ticker, tp_sl_tiers) if tp_sl_tiers else 0
                    storage.save_portfolio(portfolio)
                    if created:
                        msg += f" {created} palier(s) TP/SL créé(s)."
                    st.toast(msg, duration=ORDER_CONFIRMATION_TOAST_SECONDS)
                    st.rerun()

        else:  # Ordre à cours limité
            trigger_hint = "descend à" if action in ("achat", "rachat short") else "monte à"
            st.caption(f"L'ordre s'exécutera automatiquement quand le prix {trigger_hint} {ref_price:,.2f} €.")

            if st.button("Placer l'ordre à cours limité", type="primary", key="submit_limit_order"):
                try:
                    portfolio.place_limit_order(
                        ticker=ticker, name=name or ticker, action=action, quantity=quantity,
                        limit_price_eur=ref_price, currency=currency, leverage=leverage,
                    )
                except ValueError as e:
                    st.error(str(e))
                else:
                    storage.save_portfolio(portfolio)
                    st.toast(
                        f"Ordre à cours limité placé : {quantity:g} x {ticker} à {ref_price:,.2f} €.",
                        duration=ORDER_CONFIRMATION_TOAST_SECONDS,
                    )
                    st.rerun()


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

        if active_orders:
            tp_sl_widths = [1.1, 1, 1.3, 1, 0.8]
            # Mêmes clés de conteneur que render_table_light (theme.py) : même
            # style de ligne/séparateur ET conversion en cartes empilées sur
            # mobile, sans quoi ce tableau à la main resterait tassé sur petit
            # écran (voir le media query dans theme.py).
            with st.container(key="tslight_table_tpsl"):
                with st.container(key="tslight_header_tpsl"):
                    header_cols = st.columns(tp_sl_widths)
                    for col, label in zip(header_cols, ["Type", "Prix cible", "Quantité", "Créé le", ""]):
                        col.markdown(f'<div class="ts-light-col-label">{label}</div>', unsafe_allow_html=True)
                for o in active_orders:
                    cols = st.columns(tp_sl_widths)
                    color = theme.LIGHT_GREEN if o.kind == tp_sl.KIND_TAKE_PROFIT else theme.LIGHT_RED
                    cols[0].markdown(
                        f'<span class="ts-cell-mobile-label">Type</span>'
                        f'<span style="color:{color};font-weight:600">{tp_sl.KIND_LABELS[o.kind]}</span>',
                        unsafe_allow_html=True,
                    )
                    cols[1].markdown(
                        f'<span class="ts-cell-mobile-label">Prix cible</span>'
                        f'<span class="ts-light-num">{o.target_price_eur:,.2f} €</span>',
                        unsafe_allow_html=True,
                    )
                    cols[2].markdown(
                        f'<span class="ts-cell-mobile-label">Quantité</span>'
                        f'<span class="ts-light-num">{o.quantity_pct:g}% ({o.trigger_quantity:g} {ticker})</span>',
                        unsafe_allow_html=True,
                    )
                    cols[3].caption(
                        f'<span class="ts-cell-mobile-label">Créé le</span>{o.created_at[:10]}',
                        unsafe_allow_html=True,
                    )
                    if cols[4].button("Annuler", key=f"cancel_tp_sl_{o.id}"):
                        with db.get_session() as session:
                            tp_sl.cancel_tp_sl(session, o.id, st.session_state.user_id)
                        st.rerun()
        else:
            st.caption("Aucun palier actif sur cet actif pour l'instant.")

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
                    st.success("Palier créé.")
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


def _render_pending_orders(portfolio) -> None:
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
            "action": o.action.capitalize(),
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
        _render_search()

        ticker = st.session_state.get("selected_ticker")
        name = st.session_state.get("selected_name")
        quote_type = st.session_state.get("selected_quote_type", "")

        if not ticker:
            _render_home_boxes()
            return

        if st.session_state.get("_last_recorded_search") != ticker:
            try:
                search_history.record(st.session_state.user_id, ticker, name or ticker, quote_type)
            except Exception:
                pass  # l'historique de recherche est un confort, jamais bloquant
            st.session_state["_last_recorded_search"] = ticker

        if st.button("← Retour à l'accueil", key="back_to_trading_home"):
            st.session_state.selected_ticker = None
            st.rerun()

        # Nom/ticker de l'actif consulté, absent jusqu'ici en haut de la fiche
        # (seul le prix, plus bas, permettait de confirmer quel actif était
        # affiché). Nom en titre + ticker à part quand il diffère du nom
        # (cas courant : "Apple Inc." / AAPL) ; juste le ticker sinon (repli
        # manuel sans nom connu, voir _render_search).
        title = f"{name}  ·  `{ticker}`" if name and name != ticker else ticker
        st.markdown(f"### {title}")

        # Layout façon Hyperliquid (desktop) : graphique à gauche (majorité de
        # la largeur), panneau d'ordre à droite — repasse en 1 colonne empilée
        # (graphique en haut, panneau en dessous) sur mobile, voir le media
        # query dans theme.py. Panneau volontairement PAS sticky : défile
        # normalement avec le reste de la page au scroll.
        with st.container(key="ts_trading_layout_row"):
            col_chart, col_order = st.columns([2.2, 1])
            with col_chart:
                _render_price_and_chart(ticker, quote_type)

            # Déposé en session par le fragment ci-dessus (voir sa docstring) :
            # il a déjà tourné une fois de façon synchrone à ce stade du
            # script, cette valeur est donc à jour pour ce rerun.
            price_eur = st.session_state.get("trading_price_eur")
            currency = st.session_state.get("trading_currency")

            with col_order:
                if price_eur is not None:
                    _render_order_form(portfolio, ticker, name, price_eur, currency, quote_type)
                    _render_tp_sl_section(portfolio, ticker)

        if price_eur is None:
            return  # l'erreur a déjà été affichée par le fragment

        _render_explanations()
        _render_pending_orders(portfolio)
