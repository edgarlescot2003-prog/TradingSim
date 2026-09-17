"""Point d'entrée de l'application Trading Simulator."""

import time

import streamlit as st

from src import (
    auth, db, order_engine, storage, theme,
    ui_admin, ui_auth, ui_history, ui_leaderboard, ui_news, ui_portfolio, ui_reglement, ui_trading,
    ui_tutorial, valuation, weekly_summary,
)
from src.portfolio import MAX_PORTFOLIOS_PER_USER, Portfolio

# initial_sidebar_state="collapsed" : replié par défaut sur desktop aussi
# (pas seulement mobile, déjà replié par défaut nativement) — la navigation
# de l'app passe par sa propre barre d'onglets, pas par ce panneau natif
# Streamlit, qui n'a donc plus besoin de s'ouvrir en grand au chargement.
# Reste entièrement dépliable/repliable via l'icône native (jamais masquée,
# voir theme.py) : "Se déconnecter" et le sélecteur de portefeuille y
# vivent toujours, à un clic près.
st.set_page_config(page_title="Trading Simulator", layout="wide", initial_sidebar_state="collapsed")
theme.inject()

# Crée les tables manquantes si besoin (mis en cache, ne s'exécute qu'une
# fois par processus serveur, pas à chaque session).
if "db_ready" not in st.session_state:
    db.bootstrap()
    st.session_state.db_ready = True

# Résumé hebdomadaire automatique (onglet News) : vérifié à chaque démarrage
# serveur plutôt qu'à heure fixe (pas de vrai scheduler dans ce projet), mais
# mis en cache 1h (voir weekly_summary.check_and_generate) pour ne pas
# refaire ces quelques requêtes DB à chaque rerun de chaque session.
weekly_summary.check_and_generate()

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
        # Tout premier portefeuille d'un compte fraîchement créé -> devient
        # automatiquement son portefeuille officiel (compté pour le
        # classement), définitivement. Un compte préexistant à l'introduction
        # de ce statut n'a lui aucun portefeuille officiel par défaut : voir
        # auth.set_official_portfolio, action ponctuelle depuis l'Admin.
        new_portfolio = Portfolio(
            name=name or "Portefeuille principal", initial_capital=capital, cash=capital, is_official=True,
        )
        storage.save_portfolio(new_portfolio)
        portfolios[new_portfolio.id] = new_portfolio
        st.session_state.active_id = new_portfolio.id
        auth.set_active_portfolio(user_id, new_portfolio.id)
        st.rerun()
    st.stop()

with st.sidebar:
    st.subheader("Portefeuilles")
    names_by_id = {
        pid: p.name + (" (Officiel)" if p.is_official else "") for pid, p in portfolios.items()
    }
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
        if len(portfolios) >= MAX_PORTFOLIOS_PER_USER:
            st.caption(f"Limite de {MAX_PORTFOLIOS_PER_USER} portefeuilles par compte atteinte.")
        else:
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

# Onglet actif résolu et rendu AVANT tout calcul coûteux (vérif. des
# ordres, revalorisation, sauvegarde), pas après. render_tab_bar déclenche
# un st.rerun() immédiat au clic -- nécessaire : une fois les boutons de
# la barre d'onglets dessinés avec l'ANCIEN onglet actif, Streamlit ne
# permet pas de corriger après coup lequel apparaît surligné dans la même
# exécution (les éléments déjà envoyés au navigateur ne peuvent pas être
# réécrits a posteriori) -- seul un rerun complet règle correctement le
# surlignage. Mais comme rien de coûteux n'a encore tourné à ce stade,
# cette exécution "perdue" ne coûte presque rien (juste l'auth + le
# panneau latéral, mesuré <0.3s) plutôt que de refaire aussi la vérif. des
# ordres + la revalorisation + la sauvegarde Supabase une seconde fois
# pour rien (c'était le cas avant : ces 3 étapes tournaient AVANT la barre
# d'onglets, donc payées deux fois à chaque clic de navigation).
# st.empty() réserve la position visuelle de la barre de valeur et des
# messages de succès (qui doivent rester AU-DESSUS de la barre d'onglets)
# tout en les remplissant seulement après coup, une fois les calculs faits.
tabs = list(theme.DEFAULT_TABS)
if auth.is_admin(role):
    tabs.append(("administration", "Administration"))
topbar_slot = st.empty()
messages_slot = st.empty()
theme.render_tab_bar(st.session_state.active_tab, tabs)

# Vérification des ordres à cours limité : appel réseau non caché
# (historique de prix) par ordre en attente. Throttlé à 1x/15s plutôt qu'à
# chaque rerun -- un ordre n'a pas besoin d'être revérifié à la
# milliseconde près, 15s reste largement sous le rythme de navigation
# normal. Si le délai n'est pas écoulé, on garde simplement la fenêtre de
# vérification non avancée (order.last_checked_at inchangé) : c'est déjà
# le comportement existant en cas d'échec réseau (voir order_engine.py),
# rien de nouveau à gérer côté fraîcheur.
_ORDER_CHECK_THROTTLE_SECONDS = 15
now_ts = time.time()
last_order_check_ts = st.session_state.get("_last_order_check_ts", 0.0)
if portfolio.pending_orders and (now_ts - last_order_check_ts) >= _ORDER_CHECK_THROTTLE_SECONDS:
    executed_messages = order_engine.process_pending_orders(portfolio)
    st.session_state["_last_order_check_ts"] = now_ts
else:
    executed_messages = []
if executed_messages:
    storage.save_portfolio(portfolio)
    # Un ordre à cours limité vient de s'exécuter automatiquement (cash/
    # positions modifiés) : invalide le cache de valorisation pour ne pas
    # réafficher la valeur d'avant son exécution le temps que le TTL expire.
    storage.invalidate_valuation_cache()

total_value, snapshots = storage.get_cached_total_value(portfolio)
portfolio.record_value_snapshot(total_value)

# Sauvegarde Supabase : ne sert ici qu'à persister le point QUOTIDIEN de
# la courbe de valeur (déjà dédupliqué à 1 point/jour en mémoire, voir
# Portfolio.record_value_snapshot) -- tout achat/vente/clôture est de
# toute façon déjà sauvegardé immédiatement à sa source (ui_trading.py,
# ui_portfolio.py), donc aucune donnée de trade ne dépend de cet appel.
# Throttlé à 1x/60s au lieu d'un aller-retour DB complet (delete+insert
# positions/trades/ordres/historique) à chaque interaction, y compris sur
# des onglets sans rapport avec le portefeuille (Cours/Classement/News/
# Admin) -- invisible pour l'utilisateur vu la granularité quotidienne de
# la courbe, mais toujours sauvegardé immédiatement si un ordre vient de
# s'exécuter (executed_messages), pour ne jamais perdre cette exécution.
_SAVE_THROTTLE_SECONDS = 60
last_save_ts = st.session_state.get("_last_portfolio_save_ts", 0.0)
if executed_messages or (now_ts - last_save_ts) >= _SAVE_THROTTLE_SECONDS:
    storage.save_portfolio(portfolio)
    st.session_state["_last_portfolio_save_ts"] = now_ts
pnl_eur, pnl_pct = valuation.daily_pnl(portfolio, total_value)

with topbar_slot.container():
    theme.render_topbar(portfolio.name, total_value, pnl_eur, pnl_pct, portfolio.cash)

with messages_slot.container():
    for msg in executed_messages:
        st.success(msg)
    # Alerte de variation de prix : construite à partir des snapshots déjà
    # calculés juste au-dessus (valuation.total_value), donc sans aucun appel
    # API de prix supplémentaire — voir valuation.large_movers.
    theme.render_movers_alert(valuation.large_movers(snapshots))

if st.session_state.active_tab == "trading":
    ui_trading.render(portfolio)
elif st.session_state.active_tab == "cours":
    ui_tutorial.render()
elif st.session_state.active_tab == "classement":
    ui_leaderboard.render(user_id)
elif st.session_state.active_tab == "historique":
    ui_history.render(st.session_state.get("history_user_id", user_id), user_id)
elif st.session_state.active_tab == "news":
    ui_news.render(role, user_id)
elif st.session_state.active_tab == "reglement":
    ui_reglement.render()
elif st.session_state.active_tab == "administration" and auth.is_admin(role):
    ui_admin.render(user_id)
else:
    ui_portfolio.render(portfolio, total_value, snapshots)
