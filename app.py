"""Point d'entrée de l'application Trading Simulator."""

import streamlit as st

from src import (
    auth, db, order_engine, storage, theme,
    ui_admin, ui_auth, ui_leaderboard, ui_news, ui_portfolio, ui_trading, ui_tutorial, valuation,
)
from src.portfolio import Portfolio

st.set_page_config(page_title="Trading Simulator", layout="wide")
theme.inject()

# Crée les tables manquantes si besoin (mis en cache, ne s'exécute qu'une
# fois par processus serveur, pas à chaque session).
if "db_ready" not in st.session_state:
    db.bootstrap()
    st.session_state.db_ready = True

# Porte d'authentification : rien d'autre ne s'affiche tant que l'utilisateur
# n'est pas connecté.
if "auth_user" not in st.session_state:
    ui_auth.render()
    st.stop()

auth_user = st.session_state.auth_user
user_id = auth_user["id"]
role = auth_user["role"]
# storage.py lit l'utilisateur courant depuis ici :
# toute requête aux portefeuilles/positions/historique est donc filtrée par
# ce user_id, qui ne provient que de l'authentification (jamais d'un
# paramètre d'URL ou d'une valeur modifiable côté client).
st.session_state.user_id = user_id

with st.sidebar:
    st.markdown(
        f"**{auth_user['username']}** · {auth.ROLE_LABELS[role]}",
    )
    if st.button("Se déconnecter", use_container_width=True):
        for key in ("auth_user", "user_id", "portfolios", "active_id"):
            st.session_state.pop(key, None)
        st.rerun()
    st.divider()

# Navigation : st.tabs ne peut pas être piloté par code, donc l'onglet actif
# et l'actif sélectionné dans Trading vivent dans st.session_state (mis à
# jour par de vrais st.button — voir theme.render_tab_bar / go_to_trading —
# jamais par un lien <a href>, qui rechargerait la page et perdrait la
# session, y compris l'authentification).
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "portefeuille"

if "portfolios" not in st.session_state:
    st.session_state.portfolios, first_id = storage.load_all()
    saved_active_id = auth.get_active_portfolio_id(user_id)
    st.session_state.active_id = (
        saved_active_id if saved_active_id in st.session_state.portfolios else first_id
    )

portfolios = st.session_state.portfolios

if not portfolios:
    st.title("Trading Simulator")
    st.subheader("Bienvenue — configure ton premier portefeuille")
    with st.form("setup_form"):
        name = st.text_input("Nom du portefeuille", value="Portefeuille principal")
        capital = st.number_input("Capital de départ (€)", min_value=1.0, value=10_000.0, step=100.0)
        submitted = st.form_submit_button("Créer mon portefeuille")
    if submitted:
        new_portfolio = Portfolio(name=name or "Portefeuille principal", initial_capital=capital, cash=capital)
        storage.save_portfolio(new_portfolio)
        portfolios[new_portfolio.id] = new_portfolio
        st.session_state.active_id = new_portfolio.id
        auth.set_active_portfolio(user_id, new_portfolio.id)
        st.rerun()
    st.stop()

with st.sidebar:
    st.subheader("Portefeuilles")
    names_by_id = {pid: p.name for pid, p in portfolios.items()}
    ids = list(names_by_id.keys())
    current_index = ids.index(st.session_state.active_id) if st.session_state.active_id in ids else 0
    selected_id = st.selectbox(
        "Portefeuille actif", options=ids, index=current_index, format_func=lambda pid: names_by_id[pid],
    )
    if selected_id != st.session_state.active_id:
        st.session_state.active_id = selected_id
        auth.set_active_portfolio(user_id, selected_id)
        st.rerun()

    with st.expander("Créer un nouveau portefeuille"):
        with st.form("new_portfolio_form"):
            new_name = st.text_input("Nom", value="Nouveau portefeuille")
            new_capital = st.number_input("Capital de départ (€)", min_value=1.0, value=10_000.0, step=100.0)
            create_submitted = st.form_submit_button("Créer")
        if create_submitted:
            new_portfolio = Portfolio(
                name=new_name or "Nouveau portefeuille", initial_capital=new_capital, cash=new_capital,
            )
            storage.save_portfolio(new_portfolio)
            portfolios[new_portfolio.id] = new_portfolio
            st.session_state.active_id = new_portfolio.id
            auth.set_active_portfolio(user_id, new_portfolio.id)
            st.rerun()

portfolio = portfolios[st.session_state.active_id]

executed_messages = order_engine.process_pending_orders(portfolio)
if executed_messages:
    storage.save_portfolio(portfolio)

total_value, snapshots = valuation.total_value(portfolio)
portfolio.record_value_snapshot(total_value)
storage.save_portfolio(portfolio)
pnl_eur, pnl_pct = valuation.daily_pnl(portfolio, total_value)

theme.render_topbar(portfolio.name, total_value, pnl_eur, pnl_pct)

for msg in executed_messages:
    st.success(msg)

tabs = list(theme.DEFAULT_TABS)
if auth.is_admin(role):
    tabs.append(("administration", "Administration"))
theme.render_tab_bar(st.session_state.active_tab, tabs)

if st.session_state.active_tab == "trading":
    ui_trading.render(portfolio)
elif st.session_state.active_tab == "cours":
    ui_tutorial.render()
elif st.session_state.active_tab == "classement":
    ui_leaderboard.render(user_id)
elif st.session_state.active_tab == "news":
    ui_news.render(role, user_id)
elif st.session_state.active_tab == "administration" and auth.is_admin(role):
    ui_admin.render(user_id)
else:
    ui_portfolio.render(portfolio, total_value, snapshots)
