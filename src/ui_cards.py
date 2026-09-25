"""Composants visuels de la navigation Trading (cartes de catégories, de
zones, de pays, pastilles, fil d'Ariane), construits UNIQUEMENT avec les
jetons du thème du site (theme.py) : fond dégradé sombre, surfaces PANEL,
bordure BORDER, accent orange, vert/rouge de hausse/baisse, Inter + JetBrains
Mono (déjà chargées par le site, aucune ressource externe ajoutée).

Navigation sans perte de session : une carte cliquable est un vrai
st.container(key="tsnav_card_…") dont TOUTE la surface est recouverte par un
vrai st.button transparent (clé "tsnav_hit_…") — jamais un lien <a href>, qui
rechargerait la page. Le bouton reste un vrai bouton : atteignable au clavier
(Tab + Entrée), libellé lu par les lecteurs d'écran, contour de focus visible
sur la carte.

Contour géographique : SVG en data URI dans un `background-image` CSS (le
HTML de st.markdown est filtré, un <svg> en ligne n'y survit pas de façon
fiable), en trait fin et faible opacité, ancré en bas à droite et rogné par
la carte (overflow: hidden).
"""

import html
from urllib.parse import quote

import streamlit as st

from . import theme

# Tailles de carte : clé -> classe de hauteur (voir _CSS).
SIZES = ("category", "large", "country", "wide")

# Pastille d'icône des catégories (caractères simples, masqués aux lecteurs
# d'écran : le nom de la catégorie est toujours écrit à côté).
CATEGORY_ICONS = {
    "Actions": "↗", "Crypto": "₿", "Obligations": "%", "Forex": "⇄", "Matières premières": "◆",
}

_OUTLINE_STROKE = "#FFFFFF"
_OUTLINE_OPACITY = 0.22

_CSS = f"""
<style>
.tsnav-eyebrow {{
    font-family: {theme.FONT_SANS}; font-size: 0.72rem; font-weight: 600; letter-spacing: 0.14em;
    text-transform: uppercase; color: {theme.MUTED}; margin: 0.4rem 0 0.2rem 0;
}}
.tsnav-title {{
    font-family: {theme.FONT_SANS}; font-size: 2rem; font-weight: 700; color: {theme.TEXT};
    line-height: 1.15; margin: 0 0 0.35rem 0;
}}
.tsnav-lead {{ font-family: {theme.FONT_SANS}; color: {theme.MUTED}; font-size: 0.95rem; margin: 0 0 1rem 0; }}
.tsnav-footnote {{ font-family: {theme.FONT_SANS}; color: {theme.MUTED}; font-size: 0.78rem; margin-top: 0.6rem; }}

/* Carte cliquable (ou « Bientôt ») */
.st-key-ts_light [class*="st-key-tsnav_card_"] {{
    position: relative; overflow: hidden;
    background-color: {theme.PANEL}; background-repeat: no-repeat;
    border: 1px solid {theme.BORDER}; border-radius: 12px;
    padding: 1.25rem 1.25rem 1.1rem 1.25rem;
    transition: border-color 0.15s ease, transform 0.15s ease;
}}
.st-key-ts_light [class*="st-key-tsnav_card_"]:hover {{ border-color: {theme.ACCENT}; transform: translateY(-2px); }}
.st-key-ts_light [class*="st-key-tsnav_card_"]:focus-within {{ outline: 2px solid {theme.ACCENT}; outline-offset: 2px; }}
.st-key-ts_light [class*="st-key-tsnav_card_soon_"] {{ border-style: dashed; }}
.st-key-ts_light [class*="st-key-tsnav_card_soon_"]:hover {{ border-color: {theme.BORDER}; transform: none; }}
.st-key-ts_light [class*="st-key-tsnav_card_"][class*="_category_"] {{ min-height: 18.75rem; }}
.st-key-ts_light [class*="st-key-tsnav_card_"][class*="_large_"] {{ min-height: 30rem; }}
.st-key-ts_light [class*="st-key-tsnav_card_"][class*="_country_"] {{ min-height: 20rem; }}
.st-key-ts_light [class*="st-key-tsnav_card_"][class*="_wide_"] {{ min-height: 11.9rem; }}

/* Bouton transparent qui recouvre toute la carte */
.st-key-ts_light [class*="st-key-tsnav_card_"] [class*="st-key-tsnav_hit_"] {{
    position: absolute !important; inset: 0 !important; z-index: 3; margin: 0 !important;
    width: 100% !important; height: 100% !important;
}}
.st-key-ts_light [class*="st-key-tsnav_card_"] [class*="st-key-tsnav_hit_"] .stButton,
.st-key-ts_light [class*="st-key-tsnav_card_"] [class*="st-key-tsnav_hit_"] .stButton > button {{
    width: 100% !important; height: 100% !important;
}}
.st-key-ts_light [class*="st-key-tsnav_card_"] [class*="st-key-tsnav_hit_"] .stButton > button {{
    background: transparent !important; border: none !important; border-radius: 12px !important;
    color: transparent !important; box-shadow: none !important; cursor: pointer;
}}

/* Contenu des cartes */
.tsnav-body {{ position: relative; z-index: 1; font-family: {theme.FONT_SANS}; color: {theme.TEXT};
               display: flex; flex-direction: column; gap: 0.55rem; }}
.tsnav-name {{ font-size: 1.35rem; font-weight: 700; line-height: 1.2; }}
.tsnav-card-large .tsnav-name, .tsnav-card-wide .tsnav-name {{ font-size: 1.9rem; }}
.tsnav-desc {{ color: {theme.MUTED}; font-size: 0.88rem; line-height: 1.45; }}
.tsnav-countries {{ color: {theme.MUTED}; font-size: 0.85rem; }}
.tsnav-index-label {{ color: {theme.MUTED}; font-size: 0.7rem; font-weight: 600; letter-spacing: 0.12em;
                      text-transform: uppercase; margin-top: 0.4rem; }}
.tsnav-index-row {{ display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; font-size: 0.92rem; }}
.tsnav-index-note {{ color: {theme.MUTED}; font-size: 0.75rem; }}
.tsnav-cta {{ color: {theme.ACCENT}; font-weight: 600; font-size: 0.9rem; margin-top: 0.3rem; }}
.tsnav-soon-body {{ opacity: 0.72; }}
.tsnav-icon {{ display: inline-flex; align-items: center; justify-content: center; width: 2.6rem; height: 2.6rem;
               border-radius: 999px; font-size: 1.25rem; font-weight: 700; color: {theme.BADGE_DARK_TEXT}; }}

/* Pastilles */
.tsnav-perf {{ display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.15rem 0.6rem; border-radius: 999px;
               font-family: {theme.FONT_MONO}; font-size: 0.8rem; font-weight: 600; white-space: nowrap; }}
.tsnav-perf-up {{ color: {theme.GREEN}; background: rgba(74, 222, 128, 0.14); border: 1px solid rgba(74, 222, 128, 0.35); }}
.tsnav-perf-down {{ color: {theme.RED}; background: rgba(248, 113, 113, 0.14); border: 1px solid rgba(248, 113, 113, 0.35); }}
.tsnav-perf-none {{ color: {theme.MUTED}; border: 1px solid {theme.BORDER}; }}
.tsnav-soon {{ display: inline-block; padding: 0.15rem 0.65rem; border-radius: 999px; font-size: 0.75rem;
               font-weight: 700; letter-spacing: 0.04em; color: {theme.TEXT}; background: rgba(255, 255, 255, 0.10);
               border: 1px dashed rgba(255, 255, 255, 0.55); width: fit-content; }}

/* Fil d'Ariane */
.st-key-ts_light [class*="st-key-tsnav_crumbs"] {{ gap: 0.15rem !important; align-items: center !important;
                                                   margin-bottom: 0.2rem; }}
.st-key-ts_light [class*="st-key-tsnav_crumbs"] .stButton > button {{
    border: none !important; background: transparent !important; color: {theme.MUTED} !important;
    padding: 0.1rem 0.35rem !important; min-height: 0 !important; font-size: 0.85rem !important;
}}
.st-key-ts_light [class*="st-key-tsnav_crumbs"] .stButton > button:hover {{ color: {theme.ACCENT} !important; }}
.tsnav-crumb-sep, .tsnav-crumb-current {{ font-family: {theme.FONT_SANS}; font-size: 0.85rem; }}
.tsnav-crumb-sep {{ color: {theme.MUTED}; padding: 0 0.1rem; }}
.tsnav-crumb-current {{ color: {theme.TEXT}; font-weight: 600; padding: 0 0.35rem; }}

@media (max-width: 640px) {{
    .tsnav-title {{ font-size: 1.5rem; }}
    .st-key-ts_light [class*="st-key-tsnav_card_"][class*="_category_"] {{ min-height: 0; }}
    .st-key-ts_light [class*="st-key-tsnav_card_"][class*="_large_"] {{ min-height: 16rem; }}
    .st-key-ts_light [class*="st-key-tsnav_card_"][class*="_country_"] {{ min-height: 11rem; }}
    .st-key-ts_light [class*="st-key-tsnav_card_"][class*="_wide_"] {{ min-height: 10rem; }}
    .tsnav-card-large .tsnav-name, .tsnav-card-wide .tsnav-name {{ font-size: 1.5rem; }}
}}
</style>
"""


def inject_css() -> None:
    """À appeler une fois par rendu de l'onglet Trading."""
    st.markdown(_CSS, unsafe_allow_html=True)


def _fr_number(value: float, decimals: int) -> str:
    return f"{abs(value):,.{decimals}f}".replace(",", " ").replace(".", ",")


def perf_pill(perf: float | None, decimals: int = 1, approx: bool = False, year: int | None = None) -> str:
    """Pastille de performance : flèche ▲/▼ ET couleur (la couleur seule ne
    suffit pas), nombre à la française. `perf` None -> « — »."""
    prefix = f"{year} " if year else ""
    if perf is None:
        return f'<span class="tsnav-perf tsnav-perf-none">{prefix}—</span>'
    up = perf >= 0
    arrow, sign, css = ("▲", "+", "up") if up else ("▼", "−", "down")
    label = f'{"≈ " if approx else ""}{sign}{_fr_number(perf, decimals)} %'
    spoken = f'{"en hausse" if up else "en baisse"} de {label}'
    return (f'<span class="tsnav-perf tsnav-perf-{css}" aria-label="{html.escape(prefix + spoken)}">'
            f'{prefix}<span aria-hidden="true">{arrow}</span> {html.escape(label)}</span>')


def soon_pill() -> str:
    return '<span class="tsnav-soon" aria-label="Bientôt disponible">Bientôt</span>'


def outline_css(card_key: str, outline: dict | None, size: str) -> str:
    """Règle CSS posant le contour `outline` ({"w", "h", "d"}, voir
    geo_outlines.py) en fond de la carte `card_key`, en bas à droite, rogné."""
    if not outline:
        return ""
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {outline["w"]} {outline["h"]}">'
           f'<path d="{outline["d"]}" fill="none" stroke="{_OUTLINE_STROKE}" stroke-opacity="{_OUTLINE_OPACITY}" '
           f'stroke-width="1.4" stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg>')
    width = {"large": "92%", "country": "88%", "wide": "34%", "category": "70%"}.get(size, "80%")
    position = "right 1.25rem center" if size == "wide" else "right -12% bottom -10%"
    mobile_width = {"wide": "45%"}.get(size, "60%")
    return (f'.st-key-ts_light .st-key-{card_key} {{ background-image: url("data:image/svg+xml,{quote(svg)}"); '
            f'background-size: {width} auto; background-position: {position}; }}'
            f'@media (max-width: 640px) {{ .st-key-ts_light .st-key-{card_key} {{ background-size: {mobile_width} auto; }} }}')


def nav_card(card_id: str, body_html: str, *, size: str = "large", available: bool = True,
             aria_label: str = "", outline: dict | None = None, extra_css: str = "") -> bool:
    """Grande carte de navigation. Retourne True si elle vient d'être
    cliquée. `available=False` : carte « Bientôt », visible mais sans bouton
    (non cliquable, non focalisable). `body_html` : contenu déjà échappé."""
    assert size in SIZES, size
    safe_id = theme._safe_key_part(card_id)
    card_key = f"tsnav_card_{'on' if available else 'soon'}_{size}_{safe_id}"
    css = outline_css(card_key, outline, size) + extra_css
    clicked = False
    with st.container(key=card_key):
        if css:
            st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
        body_class = "tsnav-body" if available else "tsnav-body tsnav-soon-body"
        st.markdown(f'<div class="{body_class} tsnav-card-{size}">{body_html}</div>', unsafe_allow_html=True)
        if available:
            clicked = st.button(aria_label or card_id, key=f"tsnav_hit_{safe_id}", use_container_width=True)
    return clicked


def category_body(category: str, label: str, description: str, count: int) -> str:
    bg, fg = theme.badge_color(category)
    icon = CATEGORY_ICONS.get(category, "•")
    return (f'<span class="tsnav-icon" style="background:{bg};color:{fg}" aria-hidden="true">{html.escape(icon)}</span>'
            f'<div class="tsnav-name">{html.escape(label)}</div>'
            f'<div class="tsnav-desc">{html.escape(description)}</div>'
            f'<div class="tsnav-countries">{count} actif{"s" if count > 1 else ""}</div>'
            f'<div class="tsnav-cta">Explorer →</div>')


def breadcrumb(parts: list[tuple[str, str | None]], key: str = "tsnav_crumbs") -> str | None:
    """Fil d'Ariane : `parts` = [(libellé, identifiant de retour ou None pour
    l'écran courant)]. Retourne l'identifiant cliqué, sinon None."""
    clicked = None
    with st.container(key=key, horizontal=True):
        for i, (label, target) in enumerate(parts):
            if i:
                st.markdown('<span class="tsnav-crumb-sep" aria-hidden="true">›</span>', unsafe_allow_html=True)
            if target is None:
                st.markdown(f'<span class="tsnav-crumb-current" aria-current="page">{html.escape(label)}</span>',
                            unsafe_allow_html=True)
            elif st.button(label, key=f"{key}_{i}_{theme._safe_key_part(target)}", type="tertiary"):
                clicked = target
    return clicked


def page_header(eyebrow: str, title: str, lead: str = "") -> None:
    st.markdown(
        f'<div class="tsnav-eyebrow">{html.escape(eyebrow)}</div>'
        f'<h2 class="tsnav-title">{html.escape(title)}</h2>'
        + (f'<p class="tsnav-lead">{html.escape(lead)}</p>' if lead else ""),
        unsafe_allow_html=True,
    )


def footnote(text: str) -> None:
    st.markdown(f'<div class="tsnav-footnote">{html.escape(text)}</div>', unsafe_allow_html=True)
