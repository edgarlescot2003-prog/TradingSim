"""Contenu de l'onglet Trading : thème clair scopé (voir theme.inject_light,
comme l'onglet Portefeuille) — page d'accueil avec encadrés d'actifs cliquables
tant qu'aucun actif n'est sélectionné, recherche unifiée avec historique par
utilisateur, fiche prix/graphique (mécanique inchangée : fragment 30s,
sélecteur de période), formulaire d'ordre avec récapitulatif (coût/marge/
liquidation/simulation P&L).
"""

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
import streamlit as st

from . import kraken_data
from . import market_data as md
from . import search_history
from . import storage
from . import theme

# -- Univers d'actifs "vitrine" de la page d'accueil -------------------------
INDICES = [
    ("^FCHI", "CAC 40"), ("^GDAXI", "DAX"), ("^GSPC", "S&P 500"),
    ("^IXIC", "Nasdaq"), ("^N225", "Nikkei 225"), ("^FTSE", "FTSE 100"),
]
TOP_CAP = [
    ("AAPL", "Apple"), ("MSFT", "Microsoft"), ("NVDA", "Nvidia"),
    ("GOOGL", "Alphabet"), ("AMZN", "Amazon"), ("META", "Meta"),
]
CRYPTO = [("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum"), ("SOL-USD", "Solana")]
FOREX_COMMODITIES = [
    ("EURUSD=X", "EUR/USD"), ("EURGBP=X", "EUR/GBP"), ("GC=F", "Or"), ("CL=F", "Pétrole"),
]
# Affichage seul : pas de bouton Trader, pas d'ouverture de position (chantier
# séparé plus tard) — voir la vérification dans render().
NON_TRADABLE_TICKERS = {t for t, _ in FOREX_COMMODITIES}
# "Tendances du jour" classe cet univers par variation % — pas une liste figée
# de gagnants/perdants, mais un calcul sur tout ce que la page couvre déjà
# (hors forex/matières, classe à part avec sa propre logique d'affichage).
TRENDING_UNIVERSE = INDICES + TOP_CAP + CRYPTO
# Suggestions par défaut de la recherche quand l'utilisateur n'a pas encore
# d'historique de recherche.
DEFAULT_SUGGESTIONS = TOP_CAP[:4] + CRYPTO[:2]

ASSET_ROW_COLUMNS = [
    {"key": "ticker", "label": "Symbole", "kind": "ticker_badge", "width": 0.9},
    {"key": "name", "label": "Nom", "kind": "link", "width": 1.0},
    {"key": "price", "label": "Prix", "kind": "text", "width": 1.5},
    {"key": "change_pct", "label": "Var. jour", "kind": "signed_pct", "width": 1.0},
    {"key": "change_30d_pct", "label": "Var. 30j", "kind": "signed_pct", "width": 1.0},
]
SEARCH_RESULT_COLUMNS = [
    {"key": "ticker", "label": "Symbole", "kind": "ticker_badge"},
    {"key": "name", "label": "Nom", "kind": "link"},
]
# yfinance renvoie aussi des devises/futures dans ses résultats de recherche :
# hors périmètre pour l'instant (forex/matières premières restent dans leur
# encadré dédié, non recherchables ici — voir la demande initiale).
_EXCLUDED_SEARCH_TYPES = {"CURRENCY", "FUTURE"}

MAX_LEVERAGE = 20.0

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

_CRYPTO_TICKER_RE = re.compile(r"^[A-Z0-9]{2,10}-[A-Z]{3,4}$")

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


def _render_asset_box(card_key: str, title: str, assets: list[tuple[str, str]],
                       quotes: dict, tradable: bool = True) -> None:
    with st.container(key=f"ts_card_{card_key}"):
        st.markdown(f"##### {title}")
        rows = []
        for ticker, name in assets:
            q = quotes.get(ticker)
            rows.append({
                "ticker": ticker,
                "name": name,
                "price": _format_price(ticker, q["price"], q["currency"]) if q else None,
                "change_pct": q["change_pct"] if q else None,
                "change_30d_pct": q.get("change_30d_pct") if q else None,
            })
        theme.render_table_light(rows, ASSET_ROW_COLUMNS, row_key="ticker", table_key=card_key)
        if not tradable:
            st.caption("Cours en lecture seule : le trading sur ces actifs n'est pas encore disponible.")


def _render_trending_box(quotes: dict) -> None:
    with st.container(key="ts_card_home_trending"):
        st.markdown("##### Tendances du jour")
        ranked = [
            (ticker, name, quotes[ticker]) for ticker, name in TRENDING_UNIVERSE
            if quotes.get(ticker) and quotes[ticker]["change_pct"] is not None
        ]
        if not ranked:
            st.caption("Données de variation indisponibles pour l'instant.")
            return

        ranked.sort(key=lambda r: r[2]["change_pct"], reverse=True)
        top_n = 3
        picked, seen = [], set()
        for ticker, name, q in ranked[:top_n] + ranked[-top_n:]:
            if ticker in seen:
                continue
            seen.add(ticker)
            picked.append((ticker, name, q))

        rows = [{
            "ticker": ticker, "name": name,
            "price": _format_price(ticker, q["price"], q["currency"]),
            "change_pct": q["change_pct"],
            "change_30d_pct": q.get("change_30d_pct"),
        } for ticker, name, q in picked]
        theme.render_table_light(rows, ASSET_ROW_COLUMNS, row_key="ticker", table_key="home_trending")


def _render_home_boxes() -> None:
    universe = INDICES + TOP_CAP + CRYPTO + FOREX_COMMODITIES
    tickers = tuple(t for t, _ in universe)
    quotes = _fetch_quotes(tickers)
    changes_30d = _fetch_30d_changes(tickers)
    for ticker, data in quotes.items():
        data["change_30d_pct"] = changes_30d.get(ticker)

    row1 = st.columns(2)
    with row1[0]:
        _render_asset_box("home_indices", "Indices majeurs", INDICES, quotes)
    with row1[1]:
        _render_asset_box("home_topcap", "Top capitalisation", TOP_CAP, quotes)

    row2 = st.columns(2)
    with row2[0]:
        _render_trending_box(quotes)
    with row2[1]:
        _render_asset_box("home_crypto", "Crypto les plus suivies", CRYPTO, quotes)

    _render_asset_box("home_forex", "Forex & Matières premières", FOREX_COMMODITIES, quotes, tradable=False)


# -- Recherche -----------------------------------------------------------------

def _search_tradable_assets(query: str) -> list[dict]:
    try:
        results = md.search_assets(query)
    except md.MarketDataError as e:
        st.error(str(e))
        return []
    return [r for r in results if (r.get("type") or "").upper() not in _EXCLUDED_SEARCH_TYPES]


def _render_search() -> None:
    with st.container(key="ts_card_search"):
        st.markdown("##### 🔍 Rechercher un actif")
        query = st.text_input(
            "Rechercher un actif", key="search_query", label_visibility="collapsed",
            placeholder="Nom ou ticker : Apple, AAPL, Bitcoin, CAC 40...",
        )

        if query:
            results = _search_tradable_assets(query)
            if results:
                rows = [{
                    "ticker": r["symbol"],
                    "name": f"{r['name']} · {r['exchange']}" if r["exchange"] else r["name"],
                    "nav_name": r["name"],  # sans la bourse : c'est ce nom qui atterrit sur les trades/positions
                } for r in results[:8]]
                theme.render_table_light(rows, SEARCH_RESULT_COLUMNS, row_key="ticker",
                                          table_key="search_results", show_header=False)
            else:
                st.caption("Aucun résultat. Tu peux saisir le ticker exact ci-dessous.")
                manual = st.text_input(
                    "Ticker exact", key="manual_ticker_input", label_visibility="collapsed",
                    placeholder="ex : SAN.PA",
                )
                if manual and st.button("Rechercher ce ticker", key="manual_ticker_go"):
                    theme.go_to_trading(manual.strip().upper(), manual.strip().upper())
            return

        user_id = st.session_state.user_id
        recent = search_history.get_recent(user_id)
        if recent:
            st.markdown('<div class="ts-light-col-label">Recherches récentes</div>', unsafe_allow_html=True)
            rows = [{"ticker": r["ticker"], "name": r["name"]} for r in recent]
            theme.render_table_light(rows, SEARCH_RESULT_COLUMNS, row_key="ticker",
                                      table_key="recent_searches", show_header=False)
        else:
            st.markdown('<div class="ts-light-col-label">Suggestions</div>', unsafe_allow_html=True)
            rows = [{"ticker": t, "name": n} for t, n in DEFAULT_SUGGESTIONS]
            theme.render_table_light(rows, SEARCH_RESULT_COLUMNS, row_key="ticker",
                                      table_key="suggested_searches", show_header=False)


# -- Prix + graphique (mécanique inchangée) -----------------------------------

def _is_crypto(ticker: str, quote_type: str) -> bool:
    if quote_type:
        return quote_type.upper() == "CRYPTOCURRENCY"
    return bool(_CRYPTO_TICKER_RE.match(ticker))


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


def _fetch_chart_history(ticker: str, quote_type: str, period_key: str):
    """Récupère l'historique pour le graphique, en choisissant la source
    (Kraken pour la crypto, Yahoo sinon) et en appliquant le repli
    automatique d'intervalle. Retourne (DataFrame, intervalle_effectif, source).
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
        hist, effective_interval, source = _fetch_chart_history(ticker, quote_type, period_key)
    except md.MarketDataError as e:
        st.error(str(e))
        return

    fig = go.Figure()
    if chart_type == "Courbe":
        fig.add_trace(go.Scatter(x=hist.index, y=hist["Close"], mode="lines", name=ticker))
    else:
        fig.add_trace(go.Candlestick(
            x=hist.index, open=hist["Open"], high=hist["High"],
            low=hist["Low"], close=hist["Close"], name=ticker,
        ))
    fig.update_layout(
        height=450, margin=dict(l=10, r=10, t=30, b=10), xaxis_rangeslider_visible=False,
        paper_bgcolor=theme.LIGHT_SURFACE, plot_bgcolor=theme.LIGHT_SURFACE,
        font=dict(family=theme.FONT_SANS, color=theme.LIGHT_TEXT),
        xaxis=dict(gridcolor=theme.LIGHT_GRIDLINE, linecolor=theme.LIGHT_GRIDLINE),
        yaxis=dict(gridcolor=theme.LIGHT_GRIDLINE, linecolor=theme.LIGHT_GRIDLINE),
    )
    if chart_type == "Courbe":
        # Couleur de la ligne alignée sur le sens de la variation du jour
        # (comme Google Finance), plutôt qu'une couleur fixe.
        fig.update_traces(line=dict(color=theme.LIGHT_GREEN if day_up else theme.LIGHT_RED, width=2))
    else:
        fig.update_traces(
            increasing_line_color=theme.LIGHT_GREEN, increasing_fillcolor=theme.LIGHT_GREEN,
            decreasing_line_color=theme.LIGHT_RED, decreasing_fillcolor=theme.LIGHT_RED,
        )
    st.plotly_chart(fig, use_container_width=True)

    fallback_note = "" if effective_interval == PERIOD_INTERVAL[period_key] else " (repli, plage trop longue)"
    st.caption(
        f"{len(hist)} bougies chargées · intervalle {effective_interval}{fallback_note} · source {source}"
    )


# -- Récapitulatif d'ordre -----------------------------------------------------

def _render_order_summary(price: float, quantity: float, leverage: float, side: str) -> None:
    notional = quantity * price
    margin = notional / leverage if leverage else notional
    if leverage > 1:
        liq_price = price * (1 - 1 / leverage) if side == "long" else price * (1 + 1 / leverage)
    else:
        liq_price = None

    with st.container(key="ts_card_order_summary"):
        st.markdown("###### Récapitulatif")
        c1, c2, c3 = st.columns(3)
        c1.metric("Coût total", f"{notional:,.2f} €")
        c2.metric("Marge requise", f"{margin:,.2f} €")
        c3.metric("Liquidation estimée", f"{liq_price:,.2f} €" if liq_price else "—")

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
                    <div style="color:{color};font-size:0.72rem;">{pnl_pct_margin:+.1f}% marge</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


# -- Formulaire d'ordre ---------------------------------------------------------

def _render_order_form(portfolio, ticker: str, name: str | None, price_eur: float, currency: str) -> None:
    with st.container(key="ts_card_order"):
        st.markdown("##### Passer un ordre")

        existing = portfolio.positions.get(ticker)
        if existing is None:
            st.caption(f"Aucune position ouverte sur {ticker}.")
            order_type = st.radio(
                "Type d'ordre", ["Acheter (position longue)", "Vendre à découvert (position courte)"],
                horizontal=True,
            )
        elif existing.side == "long":
            st.caption(f"Position actuelle : {existing.quantity:g} {ticker} en position longue "
                       f"(prix moyen {existing.avg_price_eur:,.2f} €).")
            order_type = st.radio("Type d'ordre", ["Acheter plus", "Vendre"], horizontal=True)
        else:
            st.caption(f"Position actuelle : {existing.quantity:g} {ticker} en position courte "
                       f"(prix moyen {existing.avg_price_eur:,.2f} €).")
            order_type = st.radio("Type d'ordre", ["Vendre plus à découvert", "Racheter (clôturer)"], horizontal=True)

        action = ACTION_BY_ORDER_TYPE[order_type]
        is_opening = order_type in OPENING_ORDER_TYPES
        if order_type in LONG_OPENING_TYPES:
            side_for_pnl = "long"
        elif is_opening:
            side_for_pnl = "short"
        else:
            side_for_pnl = existing.side if existing else "long"

        col_lev, col_qty = st.columns(2)
        if is_opening:
            leverage = col_lev.number_input(
                "Levier (x)", min_value=1.0, max_value=MAX_LEVERAGE, value=1.0, step=1.0,
                format="%.0f", key="order_leverage",
                help=f"De x1 à x{MAX_LEVERAGE:g}.",
            )
        else:
            leverage = 1.0
            with col_lev:
                st.caption("Clôturer une position ne fait pas intervenir de nouveau levier : "
                           "la marge déjà engagée est simplement libérée.")

        default_qty = existing.quantity if (existing and order_type in ("Vendre", "Racheter (clôturer)")) else 1.0
        quantity = col_qty.number_input(
            "Quantité", min_value=0.0, value=float(default_qty), step=1.0, key="order_qty",
        )

        order_mode = st.radio("Mode d'exécution", ["Ordre au marché", "Ordre à cours limité"], horizontal=True)

        if order_mode == "Ordre à cours limité":
            ref_price = st.number_input(
                "Prix cible (€)", min_value=0.01, value=float(round(price_eur, 2)), step=0.5, key="limit_price",
            )
        else:
            ref_price = price_eur

        if is_opening and quantity > 0:
            _render_order_summary(ref_price, quantity, leverage, side_for_pnl)
        elif not is_opening and quantity > 0:
            st.caption(f"Exposition : {quantity * ref_price:,.2f} € · Cash disponible : {portfolio.cash:,.2f} €")

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
                    storage.save_portfolio(portfolio)
                    st.success(msg)
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
                    st.success(f"Ordre à cours limité placé : {quantity:g} x {ticker} à {ref_price:,.2f} €.")
                    st.rerun()


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

        for row in rows:
            cols = st.columns([1, 2, 1, 1.2, 0.8, 1])
            bg, fg = theme.badge_color(row["symbol"])
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
                f'<span style="color:{color};font-weight:600">{row["action"]}</span> '
                f'<span class="ts-light-col-label">{row["name"]}</span>',
                unsafe_allow_html=True,
            )
            cols[2].markdown(f'<span class="ts-light-num">{row["quantity"]:g}</span>', unsafe_allow_html=True)
            cols[3].markdown(f'<span class="ts-light-num">{row["limit_price"]:,.2f} €</span>', unsafe_allow_html=True)
            cols[4].markdown(f'<span class="ts-light-num">{row["leverage"]}</span>', unsafe_allow_html=True)
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

        _render_price_and_chart(ticker, quote_type)

        # Déposé en session par le fragment ci-dessus (voir sa docstring) : il a
        # déjà tourné une fois de façon synchrone à ce stade du script, cette
        # valeur est donc à jour pour ce rerun.
        price_eur = st.session_state.get("trading_price_eur")
        currency = st.session_state.get("trading_currency")
        if price_eur is None:
            return  # l'erreur a déjà été affichée par le fragment

        if ticker in NON_TRADABLE_TICKERS:
            st.info("Cet actif est affiché à titre informatif : le trading dessus n'est pas encore disponible.")
        else:
            _render_order_form(portfolio, ticker, name, price_eur, currency)

        _render_pending_orders(portfolio)
