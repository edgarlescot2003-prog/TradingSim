"""Contenu de l'onglet News : publication (Admin/Contributeur) et grille de
cartes d'aperçu (Admin/Contributeur/Standard, lecture seule pour ce
dernier), du plus récent au plus ancien. Cliquer sur une carte ouvre
l'article complet en modal (st.dialog). Suppression réservée à l'Admin —
voir auth.can_write_news / can_delete_news.

Un lien externe reconnu comme un tweet (twitter.com/x.com) est affiché en
embed visuel complet dans la modal (voir _render_tweet_embed) ; tout autre
lien reste un aperçu compact cliquable (favicon + domaine, _render_link_preview).

Gabarit de carte unique (titre, texte, image(s), action), quelle que soit
l'origine (résumé automatique ou post libre) : les images (upload en data
URI ET images collées en markdown/URL brute dans le contenu, voir
_display_images/_extract_images) sont TOUJOURS affichées à part, dans une
grille régulière après le texte — jamais laissées inline dans le contenu
markdown, ce qui produirait un collage de tailles disparates dès que
plusieurs images se suivent. `image_couverture` (voir news.py) reste
résolu à la publication comme avant (choix explicite si plusieurs visuels
candidats), mais n'est plus le seul visuel affiché : c'est juste une image
supplémentaire ajoutée à cette même grille.

Pas de modification en place (V1, voir la roadmap) : un article publié se
supprime, il ne s'édite pas.
"""

import base64
import html as html_lib
import re
from urllib.parse import urlparse

import streamlit as st
import streamlit.components.v1 as components

from . import auth, news_storage, theme
from .news import NewsItem

# Taille max d'une image envoyée : stockée telle quelle (encodée base64) dans
# la colonne image_couverture, pas de stockage de fichiers dédié (Supabase
# Storage) dans cette version — reste raisonnable pour une colonne texte.
_MAX_UPLOAD_BYTES = 2 * 1024 * 1024

# https://twitter.com/user/status/123... ou https://x.com/user/status/123...
# (l'ancien domaine twitter.com reste accepté, largement encore partagé).
_TWEET_URL_RE = re.compile(r"^https?://(?:www\.)?(?:twitter\.com|x\.com)/\w+/status/\d+")

# Image markdown ![alt](url) ou simple URL brute se terminant par une
# extension d'image courante — les deux façons dont un auteur est
# susceptible de coller une image dans le champ Contenu (texte libre, pas
# d'upload de fichier dans cette version).
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((https?://\S+?)\)")
_BARE_IMAGE_URL_RE = re.compile(r"https?://\S+?\.(?:png|jpg|jpeg|gif|webp)(?:\?\S*)?", re.IGNORECASE)

# Sentinel stocké dans image_couverture quand la couverture choisie est
# l'aperçu du lien externe plutôt qu'une image du contenu.
_LINK_COVER = "__LINK__"


def _is_tweet_url(url: str) -> bool:
    return bool(_TWEET_URL_RE.match(url.strip()))


def _images_in_content(content: str) -> list[str]:
    """Images détectées dans le texte libre de l'article, dans l'ordre
    d'apparition, sans doublon."""
    found = _MARKDOWN_IMAGE_RE.findall(content) + _BARE_IMAGE_URL_RE.findall(content)
    seen, ordered = set(), []
    for url in found:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def _cover_candidates(content: str, link: str) -> list[tuple[str, str]]:
    """Visuels candidats pour la couverture de carte : (label, valeur), où
    valeur est soit une URL d'image, soit le sentinel _LINK_COVER pour le
    lien externe."""
    candidates = [(f"Image du contenu : {url}", url) for url in _images_in_content(content)]
    if link:
        candidates.append((f"Aperçu du lien : {link}", _LINK_COVER))
    return candidates


def _render_tweet_embed(url: str, height: int = 550) -> None:
    """Embed visuel d'un tweet via le script client officiel de X (widgets.js) :
    aucune clé API/appel serveur nécessaire, le rendu se fait entièrement dans
    le navigateur du visiteur. Hauteur fixe + scroll : la hauteur réelle d'un
    tweet varie (texte, image, citation...) et n'est connue qu'une fois rendu
    côté client, donc pas moyen de la calculer à l'avance côté serveur."""
    components.html(
        f"""
        <blockquote class="twitter-tweet" data-dnt="true"><a href="{url}"></a></blockquote>
        <script async src="https://platform.twitter.com/widgets.js" charset="utf-8"></script>
        """,
        height=height, scrolling=True,
    )


def _render_link_preview(link: str) -> None:
    """Aperçu compact et cliquable d'un lien externe : favicon + domaine.
    Volontairement léger (pas de vrai embed de tweet ici) — afficher un
    tweet complet par carte serait lourd pour une grille qui peut en
    contenir beaucoup ; l'embed complet (voir _render_tweet_embed) reste
    réservé à la modal, pour les liens X/Twitter uniquement."""
    domain = urlparse(link).netloc or link
    favicon_url = f"https://www.google.com/s2/favicons?sz=64&domain={html_lib.escape(domain)}"
    st.markdown(
        f"""
        <a href="{html_lib.escape(link)}" target="_blank" rel="noopener" style="text-decoration:none;">
            <div style="display:flex;align-items:center;gap:0.5rem;padding:0.5rem 0.75rem;
                         border-radius:8px;background:{theme.LIGHT_SURFACE};margin:0.5rem 0;">
                <img src="{favicon_url}" width="20" height="20" style="border-radius:4px;flex-shrink:0;">
                <span style="font-family:{theme.FONT_SANS};font-size:0.8rem;color:{theme.LIGHT_MUTED};
                             overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                    {html_lib.escape(domain)}
                </span>
            </div>
        </a>
        """,
        unsafe_allow_html=True,
    )


def _extract_images(content: str) -> tuple[str, list[str]]:
    """(texte sans les images embarquées, images trouvées dans l'ordre
    d'apparition). Les images ne sont jamais laissées inline dans le texte —
    st.markdown les rendrait alors à leur taille native à l'endroit où elles
    apparaissent, produisant un collage de tailles disparates dès que
    plusieurs images sont collées à la suite. Affichées à part (voir
    _render_image_grid), dans une grille régulière, après le texte."""
    images = _images_in_content(content)
    stripped = _MARKDOWN_IMAGE_RE.sub("", content)
    stripped = _BARE_IMAGE_URL_RE.sub("", stripped)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped).strip()
    return stripped, images


def _display_images(item: NewsItem, content_images: list[str]) -> list[str]:
    """Images à afficher pour cet article : l'éventuelle image envoyée
    (upload, data URI — jamais dans le texte donc jamais dans
    content_images) en premier, puis celles détectées dans le contenu, sans
    doublon. Le sentinel _LINK_COVER n'est pas une image (voir
    _render_link_preview, affiché séparément)."""
    images = list(content_images)
    cover = item.image_couverture
    if cover and cover != _LINK_COVER and cover not in images:
        images.insert(0, cover)
    return images


def _render_image_grid(images: list[str], max_images: int | None = None) -> None:
    """Grille régulière (colonnes égales, tuiles carrées recadrées) — jamais
    une juxtaposition de tailles/formats disparates, que l'image vienne d'un
    upload (data URI) ou d'une URL externe collée dans le texte."""
    if not images:
        return
    shown = images[:max_images] if max_images else images
    tiles = "".join(
        f'<div style="aspect-ratio:1/1;overflow:hidden;border-radius:8px;'
        f'background:{theme.LIGHT_SURFACE};">'
        f'<img src="{html_lib.escape(url)}" style="width:100%;height:100%;'
        f'object-fit:cover;display:block;">'
        f"</div>"
        for url in shown
    )
    st.markdown(
        f'<div style="display:grid;grid-template-columns:repeat({min(len(shown), 3)},1fr);'
        f'gap:0.5rem;margin:0.5rem 0;">{tiles}</div>',
        unsafe_allow_html=True,
    )


def _excerpt(content: str, limit: int = 280) -> tuple[str, bool]:
    content = content.strip()
    if len(content) <= limit:
        return content, False
    return content[:limit].rsplit(" ", 1)[0] + "…", True


# -- Publication ---------------------------------------------------------

def _uploaded_image_data_uri(uploaded_file) -> str | None:
    """Convertit le fichier envoyé en data URI (base64), ou None + message
    d'erreur affiché si le fichier dépasse la taille max autorisée."""
    data = uploaded_file.getvalue()
    if len(data) > _MAX_UPLOAD_BYTES:
        st.error(f"Image trop lourde ({len(data) / 1_000_000:.1f} Mo, max {_MAX_UPLOAD_BYTES // 1_000_000} Mo).")
        return None
    mime = uploaded_file.type or "image/png"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _render_form(user_id: str) -> None:
    with st.expander("📝 Publier une news", expanded=False):
        title = st.text_input("Titre", key="news_form_title")
        content = st.text_area(
            "Contenu", height=200, key="news_form_content",
            placeholder="Analyse, commentaire de marché, ou partage d'un tweet/article...",
        )
        link_raw = st.text_input("Lien externe (optionnel)", key="news_form_link", placeholder="https://...")
        link = link_raw.strip().split()[0] if link_raw.strip() else ""
        if link_raw.strip() and " " in link_raw.strip():
            st.caption("⚠️ Un seul lien à la fois : seul le premier a été retenu, le reste est ignoré.")

        uploaded_file = st.file_uploader(
            "Image (optionnelle)", type=["png", "jpg", "jpeg", "gif", "webp"], key="news_form_upload",
            help="Clique pour parcourir, ou glisse-dépose un fichier image (2 Mo max).",
        )
        upload_uri = _uploaded_image_data_uri(uploaded_file) if uploaded_file is not None else None

        candidates = _cover_candidates(content, link)
        if upload_uri:
            candidates = [(f"Image envoyée : {uploaded_file.name}", upload_uri)] + candidates

        cover_value = candidates[0][1] if len(candidates) == 1 else None
        if len(candidates) > 1:
            st.caption("Plusieurs visuels détectés : choisis celui à utiliser comme couverture de carte.")
            labels = [label for label, _ in candidates]
            choice = st.radio("Image de couverture", labels, key="news_form_cover_choice", label_visibility="collapsed")
            cover_value = dict(candidates)[choice] if choice else None
            for label, value in candidates:
                if value != _LINK_COVER and choice == label:
                    st.image(value, width=200)

        if st.button("Publier", type="primary", key="news_form_submit"):
            if not title.strip():
                st.error("Le titre est obligatoire.")
            elif not content.strip():
                st.error("Le contenu ne peut pas être vide.")
            elif uploaded_file is not None and upload_uri is None:
                st.error("Corrige ou retire l'image envoyée avant de publier.")
            else:
                news_storage.add_news(
                    NewsItem(
                        title=title.strip(), content=content.strip(), link=link or None,
                        image_couverture=cover_value,
                    ),
                    user_id,
                )
                for key in (
                    "news_form_title", "news_form_content", "news_form_link",
                    "news_form_upload", "news_form_cover_choice",
                ):
                    st.session_state.pop(key, None)
                st.success(f"News « {title.strip()} » publiée.")
                st.rerun()


# -- Modal (article complet) ----------------------------------------------

def _close_dialog() -> None:
    st.session_state.open_news_id = None
    st.rerun()


@st.dialog("Article", width="large")
def _render_article_dialog(item: NewsItem, author_name: str, can_delete: bool) -> None:
    st.markdown(f"### {item.title}")
    st.caption(f"{author_name} · {item.created_at[:16].replace('T', ' ')}")

    clean_content, content_images = _extract_images(item.content)
    st.markdown(clean_content if clean_content else "_(Sans texte)_")
    _render_image_grid(_display_images(item, content_images))

    if item.link:
        if _is_tweet_url(item.link):
            _render_tweet_embed(item.link)
        else:
            _render_link_preview(item.link)

    if can_delete:
        if st.button("Supprimer", key=f"delete_news_{item.id}"):
            st.session_state[f"confirm_delete_news_{item.id}"] = True

        if st.session_state.get(f"confirm_delete_news_{item.id}"):
            st.warning(f"Confirmer la suppression définitive de « {item.title} » ?")
            cc1, cc2 = st.columns(2)
            if cc1.button("Oui, supprimer", key=f"confirm_del_news_yes_{item.id}", type="primary"):
                news_storage.delete_news(item.id)
                st.session_state[f"confirm_delete_news_{item.id}"] = False
                _close_dialog()
            if cc2.button("Annuler", key=f"confirm_del_news_no_{item.id}"):
                st.session_state[f"confirm_delete_news_{item.id}"] = False
                st.rerun()

    if st.button("Fermer", key=f"close_news_{item.id}"):
        _close_dialog()


# -- Grille d'aperçu -------------------------------------------------------

def _render_card(item: NewsItem, author_name: str, can_delete: bool) -> None:
    # Un seul gabarit pour toute origine (résumé automatique ou post libre) :
    # titre, texte, image(s) si présentes, puis l'action "Lire l'article" —
    # seulement si le texte est effectivement tronqué (voir _excerpt).
    with st.container(key=f"ts_card_news_{item.id}"):
        st.markdown(f"**{item.title}**")
        st.caption(f"{author_name} · {item.created_at[:10]}")

        clean_content, content_images = _extract_images(item.content)
        excerpt, truncated = _excerpt(clean_content)
        st.markdown(excerpt if excerpt else "_(Sans texte)_")

        _render_image_grid(_display_images(item, content_images), max_images=4)
        if item.link and not _is_tweet_url(item.link):
            _render_link_preview(item.link)

        if truncated:
            if st.button("Lire l'article →", key=f"open_news_{item.id}", use_container_width=True):
                st.session_state.open_news_id = item.id
                st.rerun()


def _author_name(item: NewsItem, usernames: dict[str, str]) -> str:
    if item.is_system:
        return "Résumé automatique"
    return usernames.get(item.author_id, "(compte supprimé)")


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

    # Conteneur dédié : sert d'ancrage CSS pour forcer le passage à 1 colonne
    # sur mobile (voir le media query dans theme.py).
    with st.container(key="ts_news_grid"):
        columns = st.columns(3)
        for i, item in enumerate(items):
            with columns[i % 3]:
                _render_card(item, _author_name(item, usernames), can_delete)

    open_id = st.session_state.get("open_news_id")
    if open_id:
        opened = next((it for it in items if it.id == open_id), None)
        if opened is None:
            st.session_state.open_news_id = None
        else:
            _render_article_dialog(opened, _author_name(opened, usernames), can_delete)
