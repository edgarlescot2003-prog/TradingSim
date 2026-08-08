"""Contenu de l'onglet Trading : recherche d'actif, prix, graphique, achat."""

import re
from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
import streamlit as st

from . import kraken_data
from . import market_data as md
from . import storage
from . import theme

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

LEVERAGE_OPTIONS = [1, 2, 5, 10, 20]

# Ordres qui ouvrent/augmentent une position (par opposition à ceux qui la
# réduisent/ferment) : seuls ceux-là ont un levier à choisir.
OPENING_ORDER_TYPES = (
    "Acheter (position longue)", "Acheter plus",
    "Vendre à découvert (position courte)", "Vendre plus à découvert",
)

# Libellé affiché -> action canonique utilisée par Portfolio/order_engine.
ACTION_BY_ORDER_TYPE = {
    "Acheter (position longue)": "achat",
    "Acheter plus": "achat",
    "Vendre": "vente",
    "Vendre à découvert (position courte)": "ouverture short",
    "Vendre plus à découvert": "ouverture short",
    "Racheter (clôturer)": "rachat short",
}


def _resolve_ticker(query: str) -> tuple[str | None, str | None, str]:
    """Cherche l'actif correspondant à `query` et laisse l'utilisateur choisir
    parmi les résultats. Retourne (ticker, nom, quote_type) ; quote_type est
    vide si saisi manuellement (aucune métadonnée de recherche disponible).
    """
    try:
        results = md.search_assets(query)
    except md.MarketDataError as e:
        st.error(str(e))
        return None, None, ""

    if results:
        options = {
            f"{r['symbol']} — {r['name']} ({r['exchange']})": r for r in results
        }
        choice = st.selectbox("Résultats de recherche", list(options.keys()))
        selected = options[choice]
        return selected["symbol"], selected["name"], selected["type"]

    st.warning("Aucun résultat pour cette recherche. Tu peux saisir le ticker exact ci-dessous.")
    manual_ticker = st.text_input("Ticker exact (ex : AAPL, SAN.PA, BTC-USD)", key="manual_ticker")
    if not manual_ticker:
        return None, None, ""
    return manual_ticker.strip().upper(), manual_ticker.strip().upper(), ""


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
        paper_bgcolor=theme.PANEL, plot_bgcolor=theme.PANEL,
        font=dict(family=theme.FONT_SANS, color=theme.TEXT),
        xaxis=dict(gridcolor=theme.BORDER, linecolor=theme.BORDER),
        yaxis=dict(gridcolor=theme.BORDER, linecolor=theme.BORDER),
    )
    if chart_type == "Courbe":
        fig.update_traces(line=dict(color=theme.GREEN, width=2))
    else:
        fig.update_traces(
            increasing_line_color=theme.GREEN, increasing_fillcolor=theme.GREEN,
            decreasing_line_color=theme.RED, decreasing_fillcolor=theme.RED,
        )
    st.plotly_chart(fig, use_container_width=True)

    fallback_note = "" if effective_interval == PERIOD_INTERVAL[period_key] else " (repli, plage trop longue)"
    st.caption(
        f"{len(hist)} bougies chargées · intervalle {effective_interval}{fallback_note} · source {source}"
    )


def render(portfolio) -> None:
    st.subheader("Rechercher un actif")
    query = st.text_input("Nom ou ticker (ex : Apple, AAPL, Sanofi, BTC-USD)", key="search_query")

    if query:
        resolved_ticker, resolved_name, resolved_type = _resolve_ticker(query)
        if resolved_ticker:
            st.session_state.selected_ticker = resolved_ticker
            st.session_state.selected_name = resolved_name
            st.session_state.selected_quote_type = resolved_type

    # L'actif affiché reste en session (pas juste dans la recherche) pour
    # pouvoir être fixé depuis ailleurs (clic sur un actif dans l'onglet
    # Portefeuille) et survivre aux reruns suivants (clic sur un bouton, etc.).
    ticker = st.session_state.get("selected_ticker")
    name = st.session_state.get("selected_name")
    quote_type = st.session_state.get("selected_quote_type", "")

    if not ticker:
        st.info(
            "Recherche un actif ci-dessus, ou clique sur un actif depuis l'onglet Portefeuille "
            "pour afficher son prix et son graphique."
        )
        return

    _render_price_and_chart(ticker, quote_type)

    # Déposé en session par le fragment ci-dessus (voir sa docstring) : il a
    # déjà tourné une fois de façon synchrone à ce stade du script, cette
    # valeur est donc à jour pour ce rerun.
    price_eur = st.session_state.get("trading_price_eur")
    currency = st.session_state.get("trading_currency")
    if price_eur is None:
        return  # l'erreur a déjà été affichée par le fragment

    st.subheader("Passer un ordre")

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

    if is_opening:
        leverage = st.select_slider("Levier", options=LEVERAGE_OPTIONS, value=1)
    else:
        leverage = 1.0
        st.caption("Clôturer une position ne fait pas intervenir de nouveau levier : "
                    "la marge déjà engagée est simplement libérée.")

    default_qty = existing.quantity if (existing and order_type in ("Vendre", "Racheter (clôturer)")) else 1.0
    quantity = st.number_input("Quantité", min_value=0.0, value=float(default_qty), step=1.0, key="order_qty")

    order_mode = st.radio("Mode d'exécution", ["Ordre au marché", "Ordre à cours limité"], horizontal=True)

    if order_mode == "Ordre au marché":
        notional = quantity * price_eur
        margin = notional / leverage
        st.markdown(
            f"Exposition totale : {theme.mono(f'{notional:,.2f} €')}"
            f"&nbsp;&nbsp;—&nbsp;&nbsp;Marge nécessaire (levier x{leverage:g}) : "
            f"{theme.mono(f'{margin:,.2f} €')}"
            f"&nbsp;&nbsp;—&nbsp;&nbsp;Cash disponible : {theme.mono(f'{portfolio.cash:,.2f} €')}",
            unsafe_allow_html=True,
        )

        if st.button("Valider l'ordre", type="primary"):
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
        limit_price = st.number_input(
            "Prix cible (€)", min_value=0.01, value=float(round(price_eur, 2)), step=0.5, key="limit_price"
        )
        notional = quantity * limit_price
        margin = notional / leverage
        trigger_hint = "descend à" if action in ("achat", "rachat short") else "monte à"
        st.markdown(
            f"L'ordre s'exécutera automatiquement quand le prix {trigger_hint} "
            f"{theme.mono(f'{limit_price:,.2f} €')}. "
            f"Marge qui sera engagée (levier x{leverage:g}) : {theme.mono(f'{margin:,.2f} €')}.",
            unsafe_allow_html=True,
        )

        if st.button("Placer l'ordre à cours limité", type="primary"):
            try:
                portfolio.place_limit_order(
                    ticker=ticker, name=name or ticker, action=action, quantity=quantity,
                    limit_price_eur=limit_price, currency=currency, leverage=leverage,
                )
            except ValueError as e:
                st.error(str(e))
            else:
                storage.save_portfolio(portfolio)
                st.success(f"Ordre à cours limité placé : {quantity:g} x {ticker} à {limit_price:,.2f} €.")
                st.rerun()

    _render_pending_orders(portfolio)


def _render_pending_orders(portfolio) -> None:
    st.subheader("Ordres en attente")
    if not portfolio.pending_orders:
        st.caption("Aucun ordre en attente.")
        return

    header = st.columns([1.5, 2, 1, 1.3, 1, 1])
    for col, label in zip(header, ["TICKER", "ACTION", "QTÉ", "PRIX CIBLE", "LEVIER", ""]):
        col.markdown(
            f'<span style="font-size:0.68rem;font-weight:600;letter-spacing:0.04em;'
            f'color:{theme.MUTED};">{label}</span>',
            unsafe_allow_html=True,
        )

    buy_side = ("achat", "rachat short")
    for order in portfolio.pending_orders:
        c1, c2, c3, c4, c5, c6 = st.columns([1.5, 2, 1, 1.3, 1, 1])
        if c1.button(order.ticker, key=f"navorder_{order.id}"):
            theme.go_to_trading(order.ticker, order.name)
        action_color = theme.GREEN if order.action in buy_side else theme.RED
        c2.markdown(
            f'<span style="color:{action_color};font-weight:600">{order.action.capitalize()}</span>',
            unsafe_allow_html=True,
        )
        c3.markdown(theme.mono(f"{order.quantity:g}"), unsafe_allow_html=True)
        c4.markdown(theme.mono(f"{order.limit_price_eur:,.2f} €"), unsafe_allow_html=True)
        c5.markdown(theme.mono(f"x{order.leverage:g}"), unsafe_allow_html=True)
        if c6.button("Annuler", key=f"cancel_{order.id}"):
            portfolio.cancel_order(order.id)
            storage.save_portfolio(portfolio)
            st.rerun()
