"""Page de connexion / inscription, affichée avant tout accès au reste de
l'app (voir la garde en tête d'app.py)."""

import streamlit as st

from . import auth


def _login_user(user) -> None:
    st.session_state.auth_user = {"id": user.id, "username": user.username, "role": user.role}


def _render_login() -> None:
    with st.form("login_form"):
        username = st.text_input("Identifiant")
        password = st.text_input("Mot de passe", type="password")
        submitted = st.form_submit_button("Se connecter", type="primary")

    if not submitted:
        return

    status, user = auth.authenticate(username.strip(), password)
    if status == auth.STATUS_OK:
        _login_user(user)
        st.rerun()
    elif status == auth.STATUS_DISABLED:
        st.error("Compte désactivé.")
    else:
        st.error("Identifiant ou mot de passe incorrect.")


def _render_signup() -> None:
    with st.form("signup_form"):
        username = st.text_input("Choisis un identifiant")
        password = st.text_input("Choisis un mot de passe (8 caractères minimum)", type="password")
        password_confirm = st.text_input("Confirme le mot de passe", type="password")
        submitted = st.form_submit_button("Créer mon compte", type="primary")

    if not submitted:
        return

    if password != password_confirm:
        st.error("Les mots de passe ne correspondent pas.")
        return

    try:
        user = auth.create_user(username, password)
    except ValueError as e:
        st.error(str(e))
    else:
        _login_user(user)
        st.success(f"Compte créé, bienvenue {user.username} !")
        st.rerun()


def render() -> None:
    st.title("Trading Simulator")
    st.caption("Connecte-toi ou crée un compte pour accéder à ton portefeuille.")

    tab_login, tab_signup = st.tabs(["Connexion", "Inscription"])
    with tab_login:
        _render_login()
    with tab_signup:
        _render_signup()
