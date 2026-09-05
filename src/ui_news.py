"""Contenu de l'onglet News : publication (Admin/Contributeur) et fil
chronologique public (Admin/Contributeur/Standard, lecture seule pour ce
dernier), du plus récent au plus ancien. Suppression réservée à l'Admin —
voir auth.can_write_news / can_delete_news.

Pas de modification en place (V1, voir la roadmap) : un article publié se
supprime, il ne s'édite pas.
"""

import streamlit as st

from . import auth, news_storage
from .news import NewsItem


def _render_form(user_id: str) -> None:
    with st.expander("📝 Publier une news", expanded=False):
        with st.form("add_news_form", clear_on_submit=True):
            title = st.text_input("Titre")
            content = st.text_area(
                "Contenu", height=200,
                placeholder="Analyse, commentaire de marché, ou partage d'un tweet/article...",
            )
            link = st.text_input("Lien externe (optionnel)", placeholder="https://...")
            submitted = st.form_submit_button("Publier")

        if submitted:
            if not title.strip():
                st.error("Le titre est obligatoire.")
            elif not content.strip():
                st.error("Le contenu ne peut pas être vide.")
            else:
                news_storage.add_news(
                    NewsItem(title=title.strip(), content=content.strip(), link=link.strip() or None),
                    user_id,
                )
                st.success(f"News « {title.strip()} » publiée.")
                st.rerun()


def _render_item(item: NewsItem, author_name: str, can_delete: bool) -> None:
    with st.container(border=True):
        st.markdown(f"##### {item.title}")
        st.caption(f"{author_name} · {item.created_at[:16].replace('T', ' ')}")
        st.markdown(item.content)
        if item.link:
            st.markdown(f"🔗 {item.link}")

        if not can_delete:
            return

        if st.button("Supprimer", key=f"delete_news_{item.id}"):
            st.session_state[f"confirm_delete_news_{item.id}"] = True

        if st.session_state.get(f"confirm_delete_news_{item.id}"):
            st.warning(f"Confirmer la suppression définitive de « {item.title} » ?")
            cc1, cc2, _ = st.columns([1, 1, 4])
            if cc1.button("Oui, supprimer", key=f"confirm_del_news_yes_{item.id}", type="primary"):
                news_storage.delete_news(item.id)
                st.session_state[f"confirm_delete_news_{item.id}"] = False
                st.rerun()
            if cc2.button("Annuler", key=f"confirm_del_news_no_{item.id}"):
                st.session_state[f"confirm_delete_news_{item.id}"] = False
                st.rerun()


def render(role: str, user_id: str) -> None:
    st.subheader("News")

    if auth.can_write_news(role):
        _render_form(user_id)
    else:
        st.caption("Lecture seule : seuls l'Admin et les contributeurs peuvent publier ici.")

    items = news_storage.load_news()
    if not items:
        st.info("Aucune news pour l'instant.")
        return

    usernames = {u.id: u.username for u in auth.list_users()}
    can_delete = auth.can_delete_news(role)
    for item in items:
        author_name = usernames.get(item.author_id, "(compte supprimé)")
        _render_item(item, author_name, can_delete)
