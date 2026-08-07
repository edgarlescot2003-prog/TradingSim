"""Contenu de l'onglet Cours : ajout, liste filtrable/groupée par thème,
recherche, consultation, modification et suppression — sans API externe,
tout le contenu est saisi manuellement.

Contenu partagé entre tous les comptes : tout le monde consulte tout.
Ajout : n'importe quel compte connecté. Modification : l'auteur du cours ou
l'Admin. Suppression : Admin uniquement, même sur ses propres cours (voir
auth.can_add_course / can_edit_course / can_delete_course). Les mêmes
règles s'appliqueront tel quel à un futur onglet News (can_write_news).
"""

import streamlit as st

from . import auth, course_storage
from .course import Course

NEW_THEME_OPTION = "+ Nouveau thème..."


def _existing_themes(courses: list[Course]) -> list[str]:
    return sorted({c.theme for c in courses})


def _theme_picker(label: str, courses: list[Course], current: str | None, key: str) -> str:
    """Selectbox thème existant + option pour en saisir un nouveau."""
    options = _existing_themes(courses)
    if current and current not in options:
        options = sorted(options + [current])
    options = options + [NEW_THEME_OPTION]
    default_index = options.index(current) if current in options else 0

    choice = st.selectbox(label, options, index=default_index, key=f"{key}_select")
    if choice == NEW_THEME_OPTION:
        return st.text_input("Nom du nouveau thème", key=f"{key}_new").strip()
    return choice


def _render_add_form(courses: list[Course], user_id: str) -> None:
    with st.expander("➕ Ajouter un cours", expanded=not courses):
        theme = _theme_picker("Thème / matière", courses, None, key="add_course_theme")

        with st.form("add_course_form", clear_on_submit=True):
            title = st.text_input("Titre du cours")
            content = st.text_area(
                "Contenu", height=300,
                placeholder="Colle ici le résumé (texte dense, exemples, etc.)",
            )
            submitted = st.form_submit_button("Enregistrer le cours")

        if submitted:
            if not title.strip():
                st.error("Le titre est obligatoire.")
            elif not theme:
                st.error("Le thème est obligatoire.")
            elif not content.strip():
                st.error("Le contenu ne peut pas être vide.")
            else:
                course_storage.add_course(Course(title=title.strip(), theme=theme, content=content), user_id)
                st.success(f"Cours « {title.strip()} » ajouté.")
                st.rerun()


def _render_list(courses: list[Course]) -> None:
    st.subheader("Cours")
    if not courses:
        st.info("Aucun cours pour l'instant.")
        return

    col1, col2 = st.columns([2, 1])
    query = col1.text_input("Rechercher (titre ou mot-clé dans le contenu)", key="course_search")
    themes = _existing_themes(courses)
    theme_filter = col2.selectbox("Filtrer par thème", ["Tous les thèmes"] + themes, key="course_theme_filter")

    filtered = courses
    if theme_filter != "Tous les thèmes":
        filtered = [c for c in filtered if c.theme == theme_filter]
    if query.strip():
        q = query.strip().lower()
        filtered = [c for c in filtered if q in c.title.lower() or q in c.content.lower()]

    if not filtered:
        st.caption("Aucun cours ne correspond à la recherche/au filtre.")
        return

    grouped: dict[str, list[Course]] = {}
    for c in filtered:
        grouped.setdefault(c.theme, []).append(c)

    for theme in sorted(grouped):
        with st.expander(f"{theme} ({len(grouped[theme])})", expanded=(theme_filter != "Tous les thèmes")):
            for c in sorted(grouped[theme], key=lambda c: c.title.lower()):
                if st.button(c.title, key=f"select_{c.id}", use_container_width=True):
                    st.session_state.selected_course_id = c.id
                    st.session_state.editing_course = False
                    st.session_state.confirm_delete_course = False


def _render_view_mode(course: Course, role: str, user_id: str) -> None:
    st.subheader(course.title)
    st.caption(f"Thème : {course.theme} — dernière modification : {course.updated_at[:16].replace('T', ' ')}")
    st.markdown(course.content)

    can_edit = auth.can_edit_course(role, course.author_id, user_id)
    can_delete = auth.can_delete_course(role)
    if not can_edit and not can_delete:
        return

    c1, c2, _ = st.columns([1, 1, 4])
    if can_edit and c1.button("Modifier"):
        st.session_state.editing_course = True
        st.rerun()
    if can_delete and c2.button("Supprimer", type="primary"):
        st.session_state.confirm_delete_course = True

    if st.session_state.get("confirm_delete_course"):
        st.warning(f"Confirmer la suppression de « {course.title} » ? Cette action est irréversible.")
        cc1, cc2, _ = st.columns([1, 1, 4])
        if cc1.button("Oui, supprimer définitivement"):
            course_storage.delete_course(course.id)
            st.session_state.selected_course_id = None
            st.session_state.confirm_delete_course = False
            st.rerun()
        if cc2.button("Annuler"):
            st.session_state.confirm_delete_course = False
            st.rerun()


def _render_edit_mode(course: Course, courses: list[Course]) -> None:
    new_title = st.text_input("Titre", value=course.title, key=f"edit_title_{course.id}")
    new_theme = _theme_picker("Thème / matière", courses, course.theme, key=f"edit_theme_{course.id}")
    new_content = st.text_area("Contenu", value=course.content, height=300, key=f"edit_content_{course.id}")

    c1, c2, _ = st.columns([1, 1, 4])
    if c1.button("Enregistrer les modifications", type="primary"):
        if not new_title.strip():
            st.error("Le titre est obligatoire.")
        elif not new_theme:
            st.error("Le thème est obligatoire.")
        elif not new_content.strip():
            st.error("Le contenu ne peut pas être vide.")
        else:
            course.title = new_title.strip()
            course.theme = new_theme
            course.content = new_content
            course_storage.update_course(course)
            st.session_state.editing_course = False
            st.success("Cours mis à jour.")
            st.rerun()
    if c2.button("Annuler"):
        st.session_state.editing_course = False
        st.rerun()


def _render_detail(courses: list[Course], role: str, user_id: str) -> None:
    selected_id = st.session_state.get("selected_course_id")
    if not selected_id:
        return

    course = next((c for c in courses if c.id == selected_id), None)
    if course is None:
        st.session_state.selected_course_id = None
        return

    st.divider()
    can_edit = auth.can_edit_course(role, course.author_id, user_id)
    if can_edit and st.session_state.get("editing_course"):
        _render_edit_mode(course, courses)
    else:
        _render_view_mode(course, role, user_id)


def render(courses: list[Course], role: str, user_id: str) -> None:
    if not auth.can_delete_course(role):
        st.caption("Les cours que tu ajoutes ou modifies sont visibles par tous. "
                   "Seul un Admin peut supprimer un cours.")

    _render_add_form(courses, user_id)
    st.divider()
    _render_list(courses)
    _render_detail(courses, role, user_id)
