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
_OUTLINE_OPACITY = 0.2

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
    margin-bottom: 1rem;
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
.st-key-ts_light [class*="st-key-tsnav_card_"] [class*="st-key-tsnav_hit_"] .stButton > button,
.st-key-ts_light [class*="st-key-tsnav_card_"] [class*="st-key-tsnav_hit_"] .stButton > button:hover,
.st-key-ts_light [class*="st-key-tsnav_card_"] [class*="st-key-tsnav_hit_"] .stButton > button:focus {{
    background: transparent !important; border: none !important; border-radius: 12px !important;
    color: transparent !important; box-shadow: none !important; outline: none !important; cursor: pointer;
}}
/* Libellé présent pour les lecteurs d'écran, jamais visible (Streamlit
   l'enveloppe dans un <p> qui a sa propre couleur). */
.st-key-ts_light [class*="st-key-tsnav_card_"] [class*="st-key-tsnav_hit_"] .stButton > button * {{
    color: transparent !important;
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
.tsnav-code {{ font-family: {theme.FONT_SANS}; font-size: 0.85rem; font-weight: 600; color: {theme.MUTED};
               letter-spacing: 0.06em; margin-left: 0.3rem; }}
.tsnav-cta {{ color: {theme.ACCENT}; font-weight: 600; font-size: 0.9rem; margin-top: 0.3rem; }}
.tsnav-soon-body {{ opacity: 0.72; }}
.tsnav-icon {{ display: inline-flex; align-items: center; justify-content: center; width: 2.6rem; height: 2.6rem;
               border-radius: 999px; font-size: 1.25rem; font-weight: 700; color: {theme.BADGE_DARK_TEXT}; }}

/* Pastilles */
.tsnav-perf {{ display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.15rem 0.6rem; border-radius: 999px;
               font-family: {theme.FONT_MONO}; font-size: 0.8rem; font-weight: 600; white-space: nowrap; }}
/* !important : les règles génériques du texte de l'onglet (scope ts_light)
   imposent sinon leur blanc à tout <span> de st.markdown. */
.st-key-ts_light .tsnav-perf-up, .st-key-ts_light .tsnav-perf-up * {{ color: {theme.GREEN} !important; }}
.st-key-ts_light .tsnav-perf-down, .st-key-ts_light .tsnav-perf-down * {{ color: {theme.RED} !important; }}
.st-key-ts_light .tsnav-perf-none {{ color: {theme.MUTED} !important; }}
.tsnav-perf-up {{ background: rgba(74, 222, 128, 0.14); border: 1px solid rgba(74, 222, 128, 0.35); }}
.tsnav-perf-down {{ background: rgba(248, 113, 113, 0.14); border: 1px solid rgba(248, 113, 113, 0.35); }}
.tsnav-perf-none {{ border: 1px solid {theme.BORDER}; }}
.tsnav-soon {{ display: inline-block; padding: 0.15rem 0.65rem; border-radius: 999px; font-size: 0.75rem;
               font-weight: 700; letter-spacing: 0.04em; color: {theme.TEXT}; background: rgba(255, 255, 255, 0.10);
               border: 1px dashed rgba(255, 255, 255, 0.55); width: fit-content; }}

/* Liste */
.tsnav-badge {{ display: inline-block; padding: 0.25rem 0.75rem; border-radius: 999px; font-family: {theme.FONT_SANS};
                font-size: 0.8rem; color: {theme.TEXT}; background: rgba(255, 255, 255, 0.08);
                border: 1px solid {theme.BORDER}; margin: 0 0 0.75rem 0; }}
.tsnav-skeleton {{ display: inline-block; width: 5.5rem; height: 0.8rem; border-radius: 4px; vertical-align: middle;
                   background: linear-gradient(90deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.22) 50%,
                   rgba(255,255,255,0.08) 100%); background-size: 200% 100%;
                   animation: tsnav-shimmer 1.4s ease-in-out infinite; }}
@keyframes tsnav-shimmer {{ 0% {{ background-position: 200% 0; }} 100% {{ background-position: -200% 0; }} }}
@media (prefers-reduced-motion: reduce) {{ .tsnav-skeleton {{ animation: none; }} }}

/* Fiche actif */
.tsnav-asset-head {{ display: flex; flex-wrap: wrap; align-items: center; gap: 0.6rem; margin: 0.2rem 0 0.9rem 0;
                     font-family: {theme.FONT_SANS}; }}
.tsnav-asset-name {{ font-size: 1.9rem; font-weight: 700; color: {theme.TEXT}; line-height: 1.15; margin-right: 0.3rem; }}
.tsnav-asset-class {{ padding: 0.15rem 0.6rem; border-radius: 999px; font-size: 0.75rem; font-weight: 700; }}
.tsnav-asset-ticker {{ font-family: {theme.FONT_MONO}; font-size: 0.9rem; color: {theme.MUTED}; }}
.tsnav-live {{ font-family: {theme.FONT_SANS}; margin-bottom: 0.6rem; }}
.tsnav-live-price {{ font-family: {theme.FONT_MONO}; font-size: 2.6rem; font-weight: 700; color: {theme.TEXT};
                     line-height: 1.1; }}
.tsnav-live-ccy {{ font-size: 1.1rem; font-weight: 600; color: {theme.MUTED}; }}
.tsnav-live-eur {{ font-family: {theme.FONT_MONO}; font-size: 1rem; color: {theme.MUTED}; margin-top: 0.15rem; }}
.tsnav-meta {{ font-size: 0.8rem; color: {theme.MUTED}; margin-top: 0.35rem; }}
.tsnav-stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: 0.75rem;
                margin: 0.4rem 0 1rem 0; }}
.tsnav-stat {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; border-radius: 12px; padding: 0.75rem 1rem;
               font-family: {theme.FONT_SANS}; }}
.tsnav-stat-label {{ font-size: 0.7rem; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase;
                     color: {theme.MUTED}; margin-bottom: 0.3rem; }}
.tsnav-stat-value {{ font-family: {theme.FONT_MONO}; font-size: 1.05rem; font-weight: 600; color: {theme.TEXT}; }}
.tsnav-order-note {{ font-family: {theme.FONT_SANS}; font-size: 0.8rem; color: {theme.MUTED}; margin-top: 0.3rem; }}
@media (max-width: 640px) {{ .tsnav-live-price {{ font-size: 2rem; }} .tsnav-asset-name {{ font-size: 1.5rem; }} }}

/* Bandeaux d'état (prix daté, pause, mise à jour, ordre à revalider) */
.tsnav-state {{ display: flex; gap: 0.7rem; align-items: flex-start; padding: 0.7rem 1rem; margin: 0.3rem 0 0.8rem 0;
                border-radius: 12px; border: 1px solid {theme.BORDER}; background: rgba(255, 255, 255, 0.06);
                font-family: {theme.FONT_SANS}; font-size: 0.88rem; color: {theme.TEXT}; line-height: 1.45; }}
.tsnav-state-icon {{ font-size: 1.05rem; line-height: 1.3; flex-shrink: 0; }}
.tsnav-state-title {{ font-weight: 700; display: block; }}
.tsnav-state-dated, .tsnav-state-revalidate {{ border-left: 4px solid {theme.ACCENT}; }}
.tsnav-state-revalidate {{ background: rgba(249, 115, 22, 0.14); }}
.tsnav-state-paused {{ border-left: 4px solid {theme.MUTED}; }}
.tsnav-state-updating {{ border-left: 4px solid {theme.CATEGORY_COLORS["Forex"]}; }}

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
    .st-key-ts_light [class*="st-key-tsnav_card_"][class*="_large_"] {{ min-height: 21rem; }}
    .st-key-ts_light [class*="st-key-tsnav_card_"][class*="_country_"] {{ min-height: 14rem; }}
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
    width = _outline_width_pct(outline, size)
    position = "right 1.5rem center" if size == "wide" else "right -4% bottom -5%"
    # Téléphone : contour réduit, logé dans le coin bas-droit libéré par
    # la hauteur minimale des cartes (voir le media query de _CSS).
    mobile_width = min(width, 40.0) if size == "wide" else min(width * 0.5, 42.0)
    return (f'.st-key-ts_light .st-key-{card_key} {{ background-image: url("data:image/svg+xml,{quote(svg)}"); '
            f'background-size: {width:.0f}% auto; background-position: {position}; }}'
            f'@media (max-width: 640px) {{ .st-key-ts_light .st-key-{card_key} {{ '
            f'background-size: {mobile_width:.0f}% auto; }} }}')


# Boîte réservée au contour, en fraction de la carte (largeur, hauteur) et
# rapport largeur/hauteur approximatif de la carte (composition de la
# maquette) : le contour tient dans la moitié basse, sous le texte, qu'il
# soit haut (Amérique, Royaume-Uni) ou large (Asie, États-Unis).
_OUTLINE_BOX = {
    "large": (0.95, 0.52, 368 / 480),
    "country": (0.95, 0.46, 214 / 320),
    "category": (0.8, 0.4, 214 / 300),
    "wide": (0.30, 0.9, 1180 / 190),
}


def _outline_width_pct(outline: dict, size: str) -> float:
    """Largeur CSS (% de la carte) pour que le contour tienne dans sa boîte."""
    box_w, box_h, card_ratio = _OUTLINE_BOX.get(size, (0.8, 0.5, 1.0))
    aspect = outline["w"] / outline["h"]
    # largeur imposée par la hauteur de la boîte, ramenée en % de la largeur de carte
    width_from_height = box_h / card_ratio * aspect
    return 100 * min(box_w, width_from_height)


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


def change_pill(value: float | None, decimals: int = 2) -> str:
    """Variation (liste) : même pastille que la performance, sans année."""
    return perf_pill(value, decimals)


def status_badge(text: str) -> str:
    return f'<span class="tsnav-badge">{html.escape(text)}</span>'


def skeleton(label: str = "Chargement en cours") -> str:
    return f'<span class="tsnav-skeleton" role="status" aria-label="{html.escape(label)}"></span>'


def asset_header(name: str, ticker: str, category: str, place: str | None = None) -> None:
    bg, fg = theme.badge_color(category)
    place_html = f'<span class="tsnav-asset-ticker">· {html.escape(place)}</span>' if place else ""
    st.markdown(
        f'<div class="tsnav-asset-head"><h2 class="tsnav-asset-name">{html.escape(name)}</h2>'
        f'<span class="tsnav-asset-class" style="background:{bg};color:{fg}">{html.escape(category)}</span>'
        f'<span class="tsnav-asset-ticker">{html.escape(ticker)}</span>{place_html}</div>',
        unsafe_allow_html=True,
    )


def format_price(value: float) -> str:
    """Même format de prix que le reste de la fiche (4 décimales sous 10)."""
    return f"{value:,.{4 if abs(value) < 10 else 2}f}"


def live_price(price_native: float, currency: str, price_eur: float, meta: str) -> None:
    """Prix en direct : en GROS en euros (la devise des portefeuilles, dans
    laquelle les ordres sont passés), en petit dans la devise de cotation
    d'origine (masqué si l'actif est déjà coté en euros), puis la ligne
    d'information (âge, fréquence, source). `meta` : texte brut."""
    native = ("" if currency == "EUR" else
              f'<div class="tsnav-live-eur">{format_price(price_native)} {html.escape(currency)}</div>')
    st.markdown(
        f'<div class="tsnav-live"><div class="tsnav-live-price">{format_price(price_eur)} '
        f'<span class="tsnav-live-ccy">€</span></div>{native}'
        f'<div class="tsnav-meta">{html.escape(meta)}</div></div>',
        unsafe_allow_html=True,
    )


def stat_cards(items: list[tuple[str, str]]) -> None:
    """Cartes de chiffres : [(libellé, valeur HTML déjà échappée)]."""
    cells = "".join(f'<div class="tsnav-stat"><div class="tsnav-stat-label">{html.escape(label)}</div>'
                    f'<div class="tsnav-stat-value">{value}</div></div>' for label, value in items)
    st.markdown(f'<div class="tsnav-stats">{cells}</div>', unsafe_allow_html=True)


_STATE_ICONS = {"dated": "⏱", "paused": "⏸", "updating": "↻", "revalidate": "⚠"}


def state_banner(kind: str, message: str, title: str | None = None) -> None:
    """Bandeau d'état de l'onglet Trading (`kind` : dated, paused, updating,
    revalidate). Simple information : n'ajoute ni ne retire aucune règle."""
    icon = _STATE_ICONS.get(kind, "ℹ")
    title_html = f'<span class="tsnav-state-title">{html.escape(title)}</span>' if title else ""
    st.markdown(
        f'<div class="tsnav-state tsnav-state-{kind}" role="status">'
        f'<span class="tsnav-state-icon" aria-hidden="true">{icon}</span>'
        f'<div>{title_html}{html.escape(message)}</div></div>',
        unsafe_allow_html=True,
    )


def page_header(eyebrow: str, title: str, lead: str = "") -> None:
    st.markdown(
        f'<div class="tsnav-eyebrow">{html.escape(eyebrow)}</div>'
        f'<h2 class="tsnav-title">{html.escape(title)}</h2>'
        + (f'<p class="tsnav-lead">{html.escape(lead)}</p>' if lead else ""),
        unsafe_allow_html=True,
    )


def footnote(text: str) -> None:
    st.markdown(f'<div class="tsnav-footnote">{html.escape(text)}</div>', unsafe_allow_html=True)
