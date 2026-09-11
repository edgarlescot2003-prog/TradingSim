"""Page d'administration (Admin uniquement — app.py ne l'affiche que pour ce
rôle) : liste des comptes, activation/désactivation, suppression, promotion
d'un compte standard en Contributeur (droit de publier des news) ou en Admin
(à sens unique, voir auth.py).
"""

import streamlit as st

from . import auth, theme


def _render_header() -> None:
    with st.container(key="ts_admin_header"):
        cols = st.columns([2, 1.4, 1, 1.1, 1.3, 1.3])
        for col, label in zip(cols, ["IDENTIFIANT", "RÔLE", "STATUT", "", "", ""]):
            col.markdown(
                f'<span style="font-size:0.68rem;font-weight:600;letter-spacing:0.04em;'
                f'color:{theme.MUTED};">{label}</span>',
                unsafe_allow_html=True,
            )


def _render_official_portfolio_picker(user) -> None:
    """Désignation ponctuelle du portefeuille officiel (compté pour le
    classement) d'un compte préexistant à l'introduction de ce statut —
    n'importe quel rôle, y compris Admin (mon propre compte a besoin de
    cette même migration, voir le prompt d'origine). Ne s'affiche que si ce
    compte a au moins un portefeuille et n'a pas encore de portefeuille
    officiel : une fois désigné, ce choix est définitif (auth.set_official_
    portfolio refuse tout second appel), inutile de laisser le contrôle
    affiché indéfiniment ensuite.
    """
    portfolios = auth.list_portfolios_for_user(user.id)
    if not portfolios or any(p.is_official for p in portfolios):
        return

    with st.container(key=f"ts_admin_official_{user.id}"):
        with st.expander(f"Désigner le portefeuille officiel de « {user.username} »"):
            st.caption(
                "Le portefeuille officiel est le seul compté pour le classement. Ce choix est "
                "définitif : impossible à modifier ensuite depuis l'interface."
            )
            options = {p.id: p.name for p in portfolios}
            choice = st.selectbox(
                "Portefeuille", options=list(options.keys()), format_func=lambda pid: options[pid],
                key=f"official_pick_{user.id}",
            )
            if st.button("Désigner comme officiel", key=f"official_confirm_{user.id}", type="primary"):
                auth.set_official_portfolio(user.id, choice)
                st.success(f"« {options[choice]} » est maintenant le portefeuille officiel de {user.username}.")
                st.rerun()


def _render_row(user, current_user_id: str) -> None:
    is_self = user.id == current_user_id
    is_admin_row = user.role == auth.ROLE_ADMIN
    is_standard_row = user.role == auth.ROLE_STANDARD

    with st.container(key=f"ts_admin_row_{user.id}"):
        c1, c2, c3, c4, c5, c6 = st.columns([2, 1.4, 1, 1.1, 1.3, 1.3])

        c1.markdown(theme.mono(user.username), unsafe_allow_html=True)
        c2.write(auth.ROLE_LABELS[user.role])

        status_color = theme.GREEN if user.is_active else theme.RED
        status_label = "Actif" if user.is_active else "Désactivé"
        c3.markdown(f'<span style="color:{status_color};font-weight:600">{status_label}</span>',
                    unsafe_allow_html=True)

        if is_admin_row:
            c4.caption("—")
            c5.caption("—")
            c6.caption("—")
        else:
            toggle_label = "Désactiver" if user.is_active else "Réactiver"
            if c4.button(toggle_label, key=f"toggle_{user.id}", disabled=is_self, use_container_width=True):
                auth.set_active(user.id, not user.is_active)
                st.rerun()

            if is_standard_row:
                if c5.button("Promouvoir contributeur", key=f"promote_contrib_{user.id}", use_container_width=True):
                    st.session_state[f"confirm_promote_contrib_{user.id}"] = True
            else:
                c5.caption("—")

            if c6.button("Promouvoir Admin", key=f"promote_{user.id}", use_container_width=True):
                st.session_state[f"confirm_promote_{user.id}"] = True

    _render_official_portfolio_picker(user)

    if is_standard_row and st.session_state.get(f"confirm_promote_contrib_{user.id}"):
        st.warning(f"Confirmer la promotion de « {user.username} » en Contributeur ? "
                   "Ce compte pourra alors publier des news librement (sans validation).")
        with st.container(key=f"ts_admin_confirm_contrib_{user.id}"):
            cc1, cc2, _ = st.columns([1, 1, 4])
            if cc1.button("Oui, promouvoir", key=f"confirm_promote_contrib_yes_{user.id}", type="primary"):
                auth.promote_to_contributor(user.id)
                st.session_state[f"confirm_promote_contrib_{user.id}"] = False
                st.rerun()
            if cc2.button("Annuler", key=f"confirm_promote_contrib_no_{user.id}"):
                st.session_state[f"confirm_promote_contrib_{user.id}"] = False
                st.rerun()

    if not is_admin_row and st.session_state.get(f"confirm_promote_{user.id}"):
        st.warning(f"Confirmer la promotion de « {user.username} » en Admin ? "
                   "Ce compte aura alors accès total (gestion des comptes, tous les cours).")
        with st.container(key=f"ts_admin_confirm_promote_{user.id}"):
            cc1, cc2, _ = st.columns([1, 1, 4])
            if cc1.button("Oui, promouvoir", key=f"confirm_promote_yes_{user.id}", type="primary"):
                auth.promote_to_admin(user.id)
                st.session_state[f"confirm_promote_{user.id}"] = False
                st.rerun()
            if cc2.button("Annuler", key=f"confirm_promote_no_{user.id}"):
                st.session_state[f"confirm_promote_{user.id}"] = False
                st.rerun()

    if not is_admin_row:
        if st.button("Supprimer le compte", key=f"delete_{user.id}", disabled=is_self):
            st.session_state[f"confirm_delete_user_{user.id}"] = True

        if st.session_state.get(f"confirm_delete_user_{user.id}"):
            st.warning(
                f"Confirmer la suppression définitive du compte « {user.username} » et de toutes ses "
                "données (portefeuilles, positions, historique) ? Ses cours et news publiés sont conservés."
            )
            with st.container(key=f"ts_admin_confirm_delete_{user.id}"):
                cc1, cc2, _ = st.columns([1, 1, 4])
                if cc1.button("Oui, supprimer", key=f"confirm_del_yes_{user.id}", type="primary"):
                    auth.delete_user(user.id)
                    st.session_state[f"confirm_delete_user_{user.id}"] = False
                    st.rerun()
                if cc2.button("Annuler", key=f"confirm_del_no_{user.id}"):
                    st.session_state[f"confirm_delete_user_{user.id}"] = False
                    st.rerun()


def render(current_user_id: str) -> None:
    st.subheader("Administration des comptes")
    users = auth.list_users()

    _render_header()
    for user in users:
        _render_row(user, current_user_id)
        st.divider()
