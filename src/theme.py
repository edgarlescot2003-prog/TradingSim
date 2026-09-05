"""Identité visuelle "terminal de trading" de l'application : palette,
polices, CSS injecté, barre de valeur fixe en haut de page, et rendu de
tableaux (nombres en police monospace, en s'appuyant sur st.columns plutôt
que st.dataframe — qui se rend en canvas WebGL et échappe donc entièrement
au CSS — ou du HTML brut, qui ne peut pas contenir de vrais widgets).

Navigation (onglets, clic sur un actif) : entièrement via st.session_state
+ st.rerun, jamais via des liens <a href="?...">. Un lien HTML déclenche une
vraie navigation navigateur, donc une NOUVELLE session Streamlit — ce qui
réinitialise st.session_state en entier (auth_user compris). C'est ce qui
causait la déconnexion à chaque clic avant ce correctif.
"""

import html as html_lib
import re

import streamlit as st

# Palette globale de l'appli : claire partout (plus de thème sombre séparé —
# la démarcation entre un onglet Portefeuille clair et le reste en sombre
# était jugée trop dérangeante). Les noms de variables (BG/PANEL/...) restent
# génériques : ce sont "les couleurs du thème actuel", pas littéralement
# "sombre" — inutile de les renommer. Valeurs reprises de la palette claire
# validée (contraste + daltonisme) par la skill dataviz du projet.
BG = "#f9f9f7"
PANEL = "#fcfcfb"
BORDER = "rgba(11,11,11,0.10)"
TEXT = "#0b0b0b"
MUTED = "#52514e"
GREEN = "#006300"
RED = "#d03b3b"
ACCENT = "#2a78d6"  # bleu discret : boutons, liens, onglet actif — jamais le gain/perte (vert/rouge)

FONT_SANS = "'Inter', -apple-system, sans-serif"
FONT_MONO = "'JetBrains Mono', 'Courier New', monospace"

# -- Alias pour l'onglet Portefeuille (theme.inject_light() / render_table_light()) --
# Historiquement une palette séparée le temps que le reste de l'appli restait
# sombre ; désormais identique à la palette globale ci-dessus, gardée comme
# alias pour ne pas devoir toucher ui_portfolio.py.
LIGHT_PAGE = "#f9f9f7"
LIGHT_SURFACE = "#fcfcfb"
LIGHT_BORDER = "rgba(11,11,11,0.10)"
LIGHT_GRIDLINE = "#e1e0d9"
LIGHT_TEXT = "#0b0b0b"
LIGHT_MUTED = "#52514e"
LIGHT_FAINT = "#898781"
LIGHT_BLUE = "#2a78d6"
LIGHT_GREEN = "#006300"
LIGHT_RED = "#d03b3b"

CATEGORY_COLORS = {
    "Actions": "#2a78d6",
    "Crypto": "#eb6834",
    "Indices/ETF": "#1baf7a",
    "Autres": LIGHT_FAINT,
}

# Couleurs de badge par ticker (identité visuelle façon "chip" Google
# Finance) : vert/rouge volontairement exclus pour ne jamais entrer en
# conflit visuel avec le code couleur gain/perte utilisé ailleurs sur la page.
_BADGE_PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7"]
_BADGE_DARK_TEXT = {"#eda100", "#e87ba4"}  # contraste insuffisant en texte blanc


def badge_color(ticker: str) -> tuple[str, str]:
    """Couleur de fond + couleur de texte lisible pour le badge d'un ticker,
    déterministe (même ticker -> même couleur à chaque rendu)."""
    bg = _BADGE_PALETTE[sum(ord(c) for c in ticker) % len(_BADGE_PALETTE)]
    fg = LIGHT_TEXT if bg in _BADGE_DARK_TEXT else "#ffffff"
    return bg, fg

_CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

:root {{
    --ts-bg: {BG};
    --ts-panel: {PANEL};
    --ts-border: {BORDER};
    --ts-text: {TEXT};
    --ts-muted: {MUTED};
    --ts-green: {GREEN};
    --ts-red: {RED};
    --ts-accent: {ACCENT};
}}

html, body, .stApp {{
    /* Sans ça, Streamlit/BaseWeb laisse le navigateur en color-scheme: dark
       (hérité de son thème par défaut) : les <input> natifs se peignent alors
       avec le fond sombre propre au navigateur (scrollbars, cases à cocher...
       idem) MÊME SI leur background-color CSS est transparent — ça ne dépend
       pas de nos propres règles de couleur, d'où les champs de connexion
       restés noirs malgré une palette entièrement repassée en clair. */
    color-scheme: light !important;
    background-color: var(--ts-bg) !important;
    color: var(--ts-text) !important;
    font-family: {FONT_SANS} !important;
}}

h1, h2, h3, h4, h5, h6,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 {{
    font-family: {FONT_SANS} !important;
    font-weight: 600 !important;
    letter-spacing: -0.01em;
}}

/* Densité : marges et espacements réduits. padding-top minime : la barre de
   valeur (.ts-topbar) est en flux normal (position: sticky, pas fixed), donc
   n'a plus besoin d'espace réservé au-dessus d'elle — juste de quoi ne pas
   coller sous la barre d'outils native de Streamlit (stToolbar, en haut à
   droite). */
.block-container {{
    padding-top: 1rem !important;
    padding-bottom: 2rem !important;
    max-width: 100% !important;
}}
[data-testid="stVerticalBlock"] {{ gap: 0.55rem !important; }}
[data-testid="stHorizontalBlock"] {{ gap: 0.75rem !important; }}

/* Header natif Streamlit masqué : remplacé par notre barre fixe */
[data-testid="stHeader"] {{
    background: transparent !important;
    height: 0 !important;
}}
[data-testid="stToolbar"] {{ top: 0.4rem !important; }}

/* Barre de valeur : `position: sticky` (pas `fixed`) et confinée au volet de
   contenu principal (elle est injectée à l'intérieur de stMain, à droite du
   panneau latéral dans la mise en page de Streamlit) plutôt qu'ancrée au
   viewport entier. Avec `fixed`, la barre s'étend sur toute la largeur et
   entre en conflit de superposition avec le panneau latéral : soit elle le
   recouvre (bouton pour le replier inutilisable), soit elle passe dessous et
   c'est le panneau (opaque) qui la recouvre à son tour (logo/nom de
   portefeuille invisibles quand le panneau est ouvert). `sticky` reste
   épinglée en haut au défilement sans jamais se superposer géométriquement
   au panneau, donc plus besoin de bataille de z-index avec lui. */
.ts-topbar {{
    position: sticky;
    top: 0;
    z-index: 100;
    background: var(--ts-panel);
    border-bottom: 1px solid var(--ts-border);
    /* padding-right généreux : réserve la place de la barre d'outils native
       Streamlit (stToolbar, Share/étoile/crayon...) qui flotte au-dessus en
       haut à droite du viewport et recouvrait sinon le P&L. */
    padding: 0.65rem 7.5rem 0.65rem 1.75rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    row-gap: 0.35rem;
}}
.ts-topbar-left {{ display: flex; align-items: center; gap: 0.6rem; }}
/* Quand le panneau latéral est replié, Streamlit affiche un bouton pour le
   rouvrir (stExpandSidebarButton) en haut à gauche, au même endroit que notre
   logo : on décale le logo pour que le bouton reste visible et lisible. */
body:has([data-testid="stExpandSidebarButton"]) .ts-topbar-left {{
    margin-left: 2.2rem;
}}
.ts-topbar-logo {{
    font-family: {FONT_SANS};
    font-weight: 700;
    font-size: 0.85rem;
    letter-spacing: 0.06em;
    color: var(--ts-text);
}}
.ts-topbar-sep {{ color: var(--ts-border); }}
.ts-topbar-portfolio {{
    font-family: {FONT_SANS};
    font-size: 0.85rem;
    color: var(--ts-muted);
}}
.ts-topbar-right {{ display: flex; align-items: center; gap: 2rem; }}
.ts-topbar-item {{ display: flex; flex-direction: column; align-items: flex-end; line-height: 1.25; }}
.ts-topbar-label {{
    font-family: {FONT_SANS};
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    color: var(--ts-muted);
}}
.ts-topbar-value {{
    font-family: {FONT_MONO};
    font-variant-numeric: tabular-nums;
    font-size: 1.15rem;
    font-weight: 600;
    color: var(--ts-text);
}}

/* Boutons */
.stButton > button, .stFormSubmitButton > button {{
    font-family: {FONT_SANS} !important;
    font-weight: 600 !important;
    border-radius: 3px !important;
    border: 1px solid var(--ts-border) !important;
    background: var(--ts-panel) !important;
    color: var(--ts-text) !important;
}}
.stButton > button:hover, .stFormSubmitButton > button:hover {{
    border-color: var(--ts-accent) !important;
    color: var(--ts-accent) !important;
}}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {{
    background: var(--ts-accent) !important;
    border-color: var(--ts-accent) !important;
    color: #ffffff !important;
}}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {{
    filter: brightness(1.1);
    color: #ffffff !important;
}}

/* Champs de saisie */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea,
[data-baseweb="select"] * {{
    font-family: {FONT_SANS} !important;
    border-radius: 3px !important;
}}
/* background/color posés directement sur l'<input>/<textarea>, pas seulement
   sur son div englobant (voir color-scheme plus haut — certains navigateurs
   peignent un fond natif propre à l'input qui ignore le fond d'un ancêtre
   transparent). Pas sur [data-baseweb="select"] * (trop large : peindrait
   aussi l'icône et le texte sélectionné comme des pastilles séparées). */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea {{
    background-color: var(--ts-panel) !important;
    color: var(--ts-text) !important;
}}
[data-testid="stNumberInput"] input {{
    font-family: {FONT_MONO} !important;
    font-variant-numeric: tabular-nums;
}}
/* Bouton "afficher le mot de passe" (l'œil) : un <button> natif de BaseWeb,
   pas un .stButton, donc pas couvert par la règle de bouton générique. Son
   fond à lui est transparent, mais il vit dans stTextInputRootElement, un
   wrapper interne à Streamlit avec SON PROPRE fond sombre codé en dur
   (#131417, ni dérivé de --ts-panel ni touché par la règle `> div`
   ci-dessous, qui ne cible que le premier niveau d'enfant) : sans cette
   règle, le contour du champ + l'icône œil restaient sombres malgré tout le
   reste de la palette repassé en clair. */
[data-testid*="RootElement"] {{
    background: var(--ts-panel) !important;
}}
[data-testid="stTextInput"] button[aria-label="Show password"],
[data-testid="stTextInput"] button[aria-label="Hide password"] {{
    background: transparent !important;
    color: var(--ts-muted) !important;
}}
[data-testid="stTextInput"] > div,
[data-testid="stNumberInput"] > div,
[data-testid="stTextArea"] > div,
[data-baseweb="select"] > div {{
    background: var(--ts-panel) !important;
    border-color: var(--ts-border) !important;
    border-radius: 3px !important;
}}

/* Métriques */
[data-testid="stMetricValue"] {{
    font-family: {FONT_MONO} !important;
    font-variant-numeric: tabular-nums;
    font-weight: 600 !important;
}}
[data-testid="stMetricLabel"] {{
    font-family: {FONT_SANS} !important;
    font-size: 0.7rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--ts-muted) !important;
}}
[data-testid="stMetricDelta"] {{
    font-family: {FONT_MONO} !important;
    font-variant-numeric: tabular-nums;
}}

/* Onglets natifs (repli, si jamais utilisés) */
[data-testid="stTabs"] [role="tablist"] {{ border-bottom: 1px solid var(--ts-border); gap: 1.5rem; }}
[data-testid="stTabs"] button {{
    font-family: {FONT_SANS} !important;
    font-weight: 600 !important;
    font-size: 0.85rem;
    color: var(--ts-muted) !important;
}}
[data-testid="stTabs"] button[aria-selected="true"] {{
    color: var(--ts-accent) !important;
}}

/* Barre d'onglets custom (de vrais st.button pilotés par session_state,
   pas des liens : voir le commentaire en tête de fichier) */
.st-key-ts_tabbar {{
    gap: 1.75rem !important;
    border-bottom: 1px solid var(--ts-border);
    margin-bottom: 0.9rem;
    align-items: center !important;
}}
.ts-tab {{
    font-family: {FONT_SANS};
    font-weight: 600;
    font-size: 0.85rem;
    letter-spacing: 0.02em;
    color: var(--ts-accent);
    padding: 0.55rem 0.05rem;
    border-bottom: 2px solid var(--ts-accent);
}}
[class*="st-key-navtab_"] button {{
    background: transparent !important;
    border: none !important;
    border-radius: 0 !important;
    border-bottom: 2px solid transparent !important;
    padding: 0.55rem 0.05rem !important;
    color: var(--ts-muted) !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    width: auto !important;
}}
[class*="st-key-navtab_"] button:hover {{
    color: var(--ts-text) !important;
    border-color: var(--ts-border) !important;
}}

/* Boutons de navigation vers un actif (tableaux, historique, ordres) :
   de vrais st.button stylés pour ressembler à un lien discret */
[class*="st-key-navcell_"] button, [class*="st-key-navorder_"] button {{
    background: transparent !important;
    border: none !important;
    border-bottom: 1px dashed var(--ts-border) !important;
    border-radius: 0 !important;
    padding: 0.1rem 0 !important;
    color: var(--ts-text) !important;
    font-weight: 400 !important;
    width: auto !important;
}}
[class*="st-key-navcell_"] button:hover, [class*="st-key-navorder_"] button:hover {{
    color: var(--ts-accent) !important;
    border-color: var(--ts-accent) !important;
}}
[class*="st-key-navcell_ticker_"] button, [class*="st-key-navorder_"] button {{
    font-family: {FONT_MONO} !important;
    font-variant-numeric: tabular-nums;
}}

/* Expanders, séparateurs, sidebar */
[data-testid="stExpander"] {{
    background: var(--ts-panel) !important;
    border: 1px solid var(--ts-border) !important;
    border-radius: 3px !important;
}}
hr {{ border-color: var(--ts-border) !important; }}
[data-testid="stSidebar"] {{
    background: var(--ts-panel) !important;
    border-right: 1px solid var(--ts-border) !important;
}}

/* Alertes : texte coloré + bordure fine plutôt que pastille pleine */
[data-testid="stAlert"] {{
    background: var(--ts-panel) !important;
    border: 1px solid var(--ts-border) !important;
    border-radius: 3px !important;
    font-family: {FONT_SANS} !important;
}}

/* Tableaux (positions, historique) : de vrais st.columns par ligne (pas du
   HTML brut), pour pouvoir y placer de vrais boutons de navigation. */
[class*="st-key-tstable_"] {{
    border: 1px solid var(--ts-border);
    border-radius: 3px;
    padding: 0.3rem 0.75rem;
    margin: 0.4rem 0 1rem 0;
}}
[class*="st-key-tstable_"] [data-testid="stHorizontalBlock"] {{
    border-bottom: 1px solid var(--ts-border);
    padding-bottom: 0.35rem;
    margin-bottom: 0.35rem;
    align-items: center;
}}
[class*="st-key-tstable_"] [data-testid="stHorizontalBlock"]:hover {{
    background: rgba(11,11,11,0.025);
}}
.ts-col-label {{
    color: var(--ts-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-family: {FONT_SANS};
    font-size: 0.68rem;
    font-weight: 600;
}}
.ts-row-cell {{
    font-family: {FONT_SANS};
    font-size: 0.83rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.ts-num {{
    font-family: {FONT_MONO} !important;
    font-variant-numeric: tabular-nums;
    text-align: right;
}}
"""


def inject() -> None:
    st.markdown(f"<style>{_CSS}</style>", unsafe_allow_html=True)


_LIGHT_CSS = f"""
.st-key-ts_light {{
    background: {LIGHT_PAGE} !important;
    border-radius: 12px;
    padding: 1.25rem 1.5rem 1.75rem !important;
    margin: -0.5rem -0.25rem 0 !important;
}}
.st-key-ts_light,
.st-key-ts_light p, .st-key-ts_light span, .st-key-ts_light div,
.st-key-ts_light label, .st-key-ts_light li {{
    color: {LIGHT_TEXT};
}}
/* font-family PAS sur les <span> : ça écraserait la police à glyphes des
   icônes Material de Streamlit (data-testid="stIconMaterial" est un span),
   qui s'afficheraient alors en texte brut ("expand_less" au lieu du chevron). */
.st-key-ts_light, .st-key-ts_light p, .st-key-ts_light div,
.st-key-ts_light label, .st-key-ts_light li {{
    font-family: {FONT_SANS};
}}
.st-key-ts_light h1, .st-key-ts_light h2, .st-key-ts_light h3,
.st-key-ts_light h4, .st-key-ts_light h5,
.st-key-ts_light [data-testid="stMarkdownContainer"] h1,
.st-key-ts_light [data-testid="stMarkdownContainer"] h2,
.st-key-ts_light [data-testid="stMarkdownContainer"] h3,
.st-key-ts_light [data-testid="stMarkdownContainer"] h4,
.st-key-ts_light [data-testid="stMarkdownContainer"] h5 {{
    color: {LIGHT_TEXT} !important;
    font-weight: 600 !important;
}}
.st-key-ts_light [data-testid="stCaptionContainer"] {{
    color: {LIGHT_FAINT} !important;
}}
.st-key-ts_light hr {{ border-color: {LIGHT_GRIDLINE} !important; }}

/* Cartes (points clés, tableaux, graphique, encadrés d'actifs...) : de vrais
   st.container(key="ts_card_xxx"), jamais un <div> ouvert/fermé à cheval sur
   plusieurs st.markdown (les widgets natifs intercalés ne se retrouveraient
   pas dedans). Convention de clé partagée par tout l'onglet Portefeuille ET
   Trading : préfixer un nouveau container par "ts_card_" lui donne
   automatiquement ce style, sans toucher à ce fichier. */
[class*="st-key-ts_card_"] {{
    background: {LIGHT_SURFACE};
    border: 1px solid {LIGHT_BORDER};
    border-radius: 10px;
    padding: 1rem 1.25rem;
    margin-bottom: 1rem;
}}

/* Boutons (pastilles portefeuille, pastilles de période...) */
.st-key-ts_light .stButton > button,
.st-key-ts_light .stFormSubmitButton > button {{
    font-family: {FONT_SANS} !important;
    font-weight: 500 !important;
    border-radius: 999px !important;
    border: 1px solid {LIGHT_BORDER} !important;
    background: {LIGHT_SURFACE} !important;
    color: {LIGHT_MUTED} !important;
}}
.st-key-ts_light .stButton > button:hover,
.st-key-ts_light .stFormSubmitButton > button:hover {{
    border-color: {LIGHT_BLUE} !important;
    color: {LIGHT_BLUE} !important;
}}
.st-key-ts_light .stButton > button[kind="primary"],
.st-key-ts_light .stFormSubmitButton > button[kind="primary"] {{
    background: {LIGHT_BLUE} !important;
    border-color: {LIGHT_BLUE} !important;
    color: #ffffff !important;
}}
.st-key-ts_portfolio_pills, .st-key-ts_period_pills {{
    gap: 0.5rem !important;
    align-items: center !important;
    flex-wrap: wrap;
    margin-bottom: 0.85rem !important;
}}
.ts-light-pill-active {{
    display: inline-flex;
    align-items: center;
    padding: 0.4rem 1rem;
    border-radius: 999px;
    background: {LIGHT_BLUE};
    color: #ffffff !important;
    font-weight: 600;
    font-size: 0.85rem;
    white-space: nowrap;
}}
.st-key-ts_period_pills .stButton > button {{
    padding: 0.2rem 0.7rem !important;
    font-size: 0.78rem !important;
    min-height: 0 !important;
}}
.ts-period-active {{
    display: inline-flex;
    align-items: center;
    padding: 0.2rem 0.7rem;
    border-radius: 999px;
    background: {LIGHT_BLUE};
    color: #ffffff !important;
    font-weight: 600;
    font-size: 0.78rem;
}}

/* Popover (création de portefeuille) : le déclencheur reste dans le scope
   (donc stylable normalement), mais son contenu ouvert (stPopoverBody) est
   téléporté par Streamlit en dehors de .st-key-ts_light (portail au niveau
   du document) — les règles ci-dessous ne l'atteignent donc jamais ; il
   garde le style clair par défaut de Streamlit, déjà lisible en pratique. */
.st-key-ts_light [data-testid="stPopoverButton"] {{
    font-family: {FONT_SANS} !important;
    font-weight: 500 !important;
    border-radius: 999px !important;
    border: 1px solid {LIGHT_BORDER} !important;
    background: {LIGHT_SURFACE} !important;
    color: {LIGHT_MUTED} !important;
}}
.st-key-ts_light [data-testid="stPopoverButton"]:hover {{
    border-color: {LIGHT_BLUE} !important;
    color: {LIGHT_BLUE} !important;
}}
.st-key-ts_light [data-testid="stPopoverBody"] {{
    background: {LIGHT_SURFACE} !important;
    border: 1px solid {LIGHT_BORDER} !important;
}}
.st-key-ts_light [data-testid="stTextInput"] input,
.st-key-ts_light [data-testid="stNumberInput"] input,
.st-key-ts_light [data-baseweb="select"] * {{
    font-family: {FONT_SANS} !important;
    color: {LIGHT_TEXT} !important;
}}
.st-key-ts_light [data-testid="stTextInput"] > div,
.st-key-ts_light [data-testid="stNumberInput"] > div,
.st-key-ts_light [data-baseweb="select"] > div {{
    background: {LIGHT_SURFACE} !important;
    border-color: {LIGHT_BORDER} !important;
    border-radius: 6px !important;
}}
/* Barre de recherche de l'onglet Trading : c'est l'action principale de la
   page, elle doit se voir — plus grande que les champs de saisie habituels
   du formulaire d'ordre. */
.st-key-ts_card_search [data-testid="stTextInput"] input {{
    font-size: 1.05rem !important;
    padding-top: 0.7rem !important;
    padding-bottom: 0.7rem !important;
}}
.st-key-ts_card_search [data-testid="stTextInput"] > div {{
    border-width: 1.5px !important;
}}
.st-key-ts_card_search [data-testid="stTextInput"] > div:focus-within {{
    border-color: {LIGHT_BLUE} !important;
}}

/* Métriques (points clés) */
.st-key-ts_light [data-testid="stMetricValue"] {{
    color: {LIGHT_TEXT} !important;
    font-family: {FONT_MONO} !important;
}}
.st-key-ts_light [data-testid="stMetricLabel"] {{
    color: {LIGHT_FAINT} !important;
}}

/* Répartition par catégorie (points clés) */
.ts-cat-row {{ display: flex; align-items: center; gap: 0.45rem; margin-top: 0.5rem; }}
.ts-cat-dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
.ts-cat-label {{ font-size: 0.8rem; color: {LIGHT_MUTED}; flex: 1; }}
.ts-cat-pct {{
    font-family: {FONT_MONO}; font-variant-numeric: tabular-nums;
    font-size: 0.8rem; font-weight: 600; color: {LIGHT_TEXT};
}}
.ts-cat-bar-track {{
    height: 5px; border-radius: 3px; background: {LIGHT_GRIDLINE};
    margin: 0.25rem 0 0 0; overflow: hidden;
}}
.ts-cat-bar-fill {{ height: 100%; border-radius: 3px; }}

/* Tableau (positions / historique) : mêmes principes que le tableau sombre
   (de vrais st.columns par ligne pour de vrais boutons de navigation). */
.st-key-ts_light [class*="st-key-tslight_table_"] {{
    border: 1px solid {LIGHT_BORDER};
    border-radius: 10px;
    padding: 0.3rem 0.9rem;
    background: {LIGHT_SURFACE};
    margin-bottom: 1rem;
}}
.st-key-ts_light [class*="st-key-tslight_table_"] [data-testid="stHorizontalBlock"] {{
    border-bottom: 1px solid {LIGHT_GRIDLINE};
    padding-bottom: 0.4rem;
    margin-bottom: 0.4rem;
    align-items: center;
}}
.st-key-ts_light [class*="st-key-tslight_table_"] [data-testid="stHorizontalBlock"]:last-child {{
    border-bottom: none; margin-bottom: 0;
}}
.st-key-ts_light [class*="st-key-tslight_table_"] [data-testid="stHorizontalBlock"]:hover {{
    background: rgba(11,11,11,0.025);
}}
.ts-light-col-label {{
    color: {LIGHT_FAINT};
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: 0.68rem;
    font-weight: 600;
}}
.ts-light-cell {{
    font-size: 0.83rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.ts-light-num {{
    font-family: {FONT_MONO} !important;
    font-variant-numeric: tabular-nums;
    text-align: right;
}}
.st-key-ts_light [class*="st-key-tslight_ticker_"] button {{
    border-radius: 999px !important;
    border: none !important;
    font-family: {FONT_MONO} !important;
    font-weight: 700 !important;
    font-size: 0.72rem !important;
    padding: 0.15rem 0.65rem !important;
    width: auto !important;
    min-height: 0 !important;
}}
.st-key-ts_light [class*="st-key-tslight_name_"] button {{
    background: transparent !important;
    border: none !important;
    padding: 0 !important;
    min-height: 0 !important;
    color: {LIGHT_TEXT} !important;
    font-weight: 400 !important;
    width: auto !important;
}}
.st-key-ts_light [class*="st-key-tslight_name_"] button:hover {{
    color: {LIGHT_BLUE} !important;
    text-decoration: underline;
}}

/* Expanders (historique, réinitialisation) et alertes */
.st-key-ts_light [data-testid="stExpander"] {{
    background: {LIGHT_SURFACE} !important;
    border: 1px solid {LIGHT_BORDER} !important;
    border-radius: 10px !important;
}}
.st-key-ts_light [data-testid="stAlert"] {{
    background: {LIGHT_SURFACE} !important;
    border: 1px solid {LIGHT_BORDER} !important;
    border-radius: 8px !important;
    color: {LIGHT_TEXT} !important;
}}
"""


def inject_light() -> None:
    """Injecte le CSS du thème clair, entièrement scopé sous .st-key-ts_light
    (voir le commentaire en tête de _LIGHT_CSS). N'a aucun effet tant que le
    contenu n'est pas rendu à l'intérieur de `with st.container(key="ts_light")`.
    Sans effet sur le thème sombre global ni les autres onglets."""
    st.markdown(f"<style>{_LIGHT_CSS}</style>", unsafe_allow_html=True)


def render_topbar(portfolio_name: str, total_value: float, pnl_eur: float, pnl_pct: float) -> None:
    color = GREEN if pnl_eur >= 0 else RED
    sign = "+" if pnl_eur >= 0 else ""
    st.markdown(
        f"""
        <div class="ts-topbar">
            <div class="ts-topbar-left">
                <span class="ts-topbar-logo">TRADING SIMULATOR</span>
                <span class="ts-topbar-sep">/</span>
                <span class="ts-topbar-portfolio">{html_lib.escape(portfolio_name)}</span>
            </div>
            <div class="ts-topbar-right">
                <div class="ts-topbar-item">
                    <span class="ts-topbar-label">VALEUR TOTALE</span>
                    <span class="ts-topbar-value">{total_value:,.2f} €</span>
                </div>
                <div class="ts-topbar-item">
                    <span class="ts-topbar-label">P&amp;L JOUR</span>
                    <span class="ts-topbar-value" style="color:{color}">
                        {sign}{pnl_eur:,.2f} € ({sign}{pnl_pct:.2f}%)
                    </span>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def go_to_trading(ticker: str, name: str | None = None) -> None:
    """Bascule vers l'onglet Trading avec `ticker` pré-sélectionné, entièrement
    via st.session_state + st.rerun (pas de navigation navigateur, donc la
    session — et l'authentification — n'est jamais perdue).

    La remise à zéro de la recherche est différée (drapeau `_clear_search_query`,
    consommé par ui_trading.render() avant de recréer le widget) plutôt
    qu'assignée ici directement : cette fonction est aussi appelée depuis
    l'intérieur même de l'onglet Trading (clic sur un actif d'un encadré ou
    d'un résultat de recherche), où le widget `search_query` a déjà été
    instancié plus tôt dans CE MÊME run — Streamlit refuse d'écrire dans
    st.session_state["search_query"] après coup et lève une exception.
    """
    st.session_state.selected_ticker = ticker
    st.session_state.selected_name = name or ticker
    st.session_state.selected_quote_type = ""
    st.session_state["_clear_search_query"] = True
    st.session_state.active_tab = "trading"
    st.rerun()


DEFAULT_TABS = [
    ("portefeuille", "Portefeuille"), ("trading", "Trading"),
    ("cours", "Cours"), ("classement", "Classement"),
]


def render_tab_bar(active_tab: str, tabs: list[tuple[str, str]] | None = None) -> None:
    """Barre d'onglets faite de vrais st.button (l'onglet actif est affiché
    en texte simple, pas cliquable). `tabs` par défaut : Portefeuille/
    Trading/Cours ; un appelant peut passer une liste différente
    (ex : + Administration)."""
    tabs = tabs or DEFAULT_TABS
    with st.container(key="ts_tabbar", horizontal=True):
        for key, label in tabs:
            if key == active_tab:
                st.markdown(f'<div class="ts-tab">{html_lib.escape(label)}</div>', unsafe_allow_html=True)
            elif st.button(label, key=f"navtab_{key}"):
                st.session_state.active_tab = key
                st.rerun()


def mono(text: str, color: str | None = None, weight: int = 600) -> str:
    """Span en police monospace, pour incruster un nombre dans du texte
    st.markdown (hors st.metric / tableau, déjà stylés globalement)."""
    style = f"font-family:{FONT_MONO};font-variant-numeric:tabular-nums;font-weight:{weight};"
    if color:
        style += f"color:{color};"
    return f'<span style="{style}">{html_lib.escape(text)}</span>'


def _cell_content(col: dict, value) -> str:
    """HTML intérieur d'une cellule non cliquable (sans wrapper)."""
    kind = col.get("kind", "text")
    decimals = col.get("decimals", 2)

    if value is None:
        return "—"
    if kind == "text":
        return html_lib.escape(str(value))
    if kind == "num":
        return f'<span class="ts-num">{value:,.{decimals}f}</span>'
    if kind == "eur":
        return f'<span class="ts-num">{value:,.{decimals}f} €</span>'
    if kind == "signed_eur":
        color = GREEN if value >= 0 else RED
        sign = "+" if value >= 0 else ""
        return f'<span class="ts-num" style="color:{color}">{sign}{value:,.{decimals}f} €</span>'
    if kind == "pct":
        return f'<span class="ts-num">{value:,.{decimals}f}%</span>'
    if kind == "signed_pct":
        color = GREEN if value >= 0 else RED
        sign = "+" if value >= 0 else ""
        return f'<span class="ts-num" style="color:{color}">{sign}{value:,.{decimals}f}%</span>'
    if kind == "side":
        color = GREEN if str(value).strip().lower() == "long" else RED
        return f'<span style="color:{color};font-weight:600">{html_lib.escape(str(value))}</span>'
    return html_lib.escape(str(value))


def render_table(rows: list[dict], columns: list[dict], row_key: str = "id", table_key: str = "table") -> None:
    """Tableau rendu avec de vrais widgets Streamlit (st.columns par ligne),
    pas du HTML brut : une colonne de type "link" devient un vrai st.button
    qui navigue via go_to_trading (jamais un <a href>, qui rechargerait la
    page et perdrait la session). Les nombres restent en police monospace.

    `columns` : liste de {"key", "label", "kind": "text"|"num"|"eur"|
    "signed_eur"|"pct"|"signed_pct"|"side"|"link", "decimals": int (optionnel),
    "mono": bool (optionnel, police monospace pour une colonne "link")}.
    Une colonne "link" utilise `row["ticker"]`/`row["name"]` pour la
    navigation, quelle que soit la colonne qui la porte.
    `row_key` : clé (présente dans chaque row) servant d'identifiant stable
    et unique par ligne. `table_key` : identifiant unique de CE tableau,
    pour distinguer ses clés de widgets de celles d'un autre tableau affiché
    sur la même page.
    """
    numeric_kinds = {"num", "eur", "signed_eur", "pct", "signed_pct"}
    widths = [1.3 if col.get("kind") in numeric_kinds else 1.0 for col in columns]

    with st.container(key=f"tstable_{table_key}"):
        header_cols = st.columns(widths)
        for col, hcol in zip(columns, header_cols):
            align = "right" if col.get("kind") in numeric_kinds else "left"
            hcol.markdown(
                f'<div class="ts-col-label" style="text-align:{align}">{html_lib.escape(col["label"])}</div>',
                unsafe_allow_html=True,
            )

        for row in rows:
            rid = row.get(row_key, row.get("ticker", ""))
            row_cols = st.columns(widths)
            for col, cell in zip(columns, row_cols):
                kind = col.get("kind", "text")
                value = row.get(col["key"])

                if kind == "link":
                    ticker = row.get("ticker", "")
                    name = row.get("name", ticker)
                    label = "—" if value is None else str(value)
                    key_prefix = "navcell_ticker" if col.get("mono") else "navcell_name"
                    if cell.button(label, key=f"{key_prefix}_{col['key']}_{rid}"):
                        go_to_trading(ticker, name)
                    continue

                align = "right" if kind in numeric_kinds else "left"
                cell.markdown(
                    f'<div class="ts-row-cell" style="text-align:{align}">{_cell_content(col, value)}</div>',
                    unsafe_allow_html=True,
                )


def _light_cell_content(col: dict, value) -> str:
    """Équivalent de _cell_content pour le thème clair (vert/rouge adaptés au
    contraste sur fond blanc)."""
    kind = col.get("kind", "text")
    decimals = col.get("decimals", 2)

    if value is None:
        return "—"
    if kind == "text":
        return html_lib.escape(str(value))
    if kind == "num":
        return f'<span class="ts-light-num">{value:,.{decimals}f}</span>'
    if kind == "eur":
        return f'<span class="ts-light-num">{value:,.{decimals}f} €</span>'
    if kind == "signed_eur":
        color = LIGHT_GREEN if value >= 0 else LIGHT_RED
        sign = "+" if value >= 0 else ""
        return f'<span class="ts-light-num" style="color:{color}">{sign}{value:,.{decimals}f} €</span>'
    if kind == "pct":
        return f'<span class="ts-light-num">{value:,.{decimals}f}%</span>'
    if kind == "signed_pct":
        color = LIGHT_GREEN if value >= 0 else LIGHT_RED
        sign = "+" if value >= 0 else ""
        return f'<span class="ts-light-num" style="color:{color}">{sign}{value:,.{decimals}f}%</span>'
    return html_lib.escape(str(value))


def _safe_key_part(value: str) -> str:
    """Rend `value` sûr à utiliser à la fois comme `key=` de widget Streamlit
    et dans le sélecteur CSS `.st-key-<key>` construit pour ce même widget.

    Streamlit assainit lui-même les caractères spéciaux d'un `key=` pour
    fabriquer sa classe CSS (ex : ":"/"." -> "-"), mais notre CSS est généré
    à partir de la valeur BRUTE de `key` : avec un `row_key` contenant un
    timestamp ISO (ex : "0_2026-09-04T19:03:30.760392" pour l'historique des
    trades), le sélecteur injecté ne correspondait plus à la classe réelle
    du bouton (":"/"." ne sont pas des caractères valides tels quels dans un
    sélecteur de classe) et la couleur du badge ne s'appliquait jamais. En
    pré-assainissant nous-mêmes (alphanumérique/tiret/underscore uniquement),
    la valeur passée à `key=` est déjà propre et Streamlit n'a plus rien à
    changer : les deux côtés restent garantis identiques.
    """
    return re.sub(r"[^a-zA-Z0-9_-]", "_", str(value))


def render_table_light(
    rows: list[dict], columns: list[dict], row_key: str = "id", table_key: str = "table",
    show_header: bool = True,
) -> None:
    """Équivalent de render_table pour le thème clair (onglet Portefeuille) :
    même technique (de vrais st.columns par ligne, de vrais st.button pour la
    navigation), avec en plus un type de colonne "ticker_badge" qui rend le
    ticker comme une pastille colorée cliquable (couleur déterministe par
    ticker, voir badge_color) plutôt qu'un simple lien texte.

    `show_header=False` masque la ligne d'en-têtes (listes compactes façon
    encadré d'actifs, où les libellés de colonne n'apportent rien).
    """
    numeric_kinds = {"num", "eur", "signed_eur", "pct", "signed_pct"}
    widths = [
        col["width"] if "width" in col else (1.3 if col.get("kind") in numeric_kinds else 1.0)
        for col in columns
    ]

    badge_rules = []
    with st.container(key=f"tslight_table_{table_key}"):
        header_cols = st.columns(widths) if show_header else [None] * len(columns)
        for col, hcol in zip(columns, header_cols):
            if hcol is None:
                continue
            align = "right" if col.get("kind") in numeric_kinds else "left"
            hcol.markdown(
                f'<div class="ts-light-col-label" style="text-align:{align}">{html_lib.escape(col["label"])}</div>',
                unsafe_allow_html=True,
            )

        for row in rows:
            rid = _safe_key_part(row.get(row_key, row.get("ticker", "")))
            row_cols = st.columns(widths)
            for col, cell in zip(columns, row_cols):
                kind = col.get("kind", "text")
                value = row.get(col["key"])

                if kind == "ticker_badge":
                    ticker = row.get("ticker", "")
                    # nav_name (si présent) prime sur name : une colonne peut afficher
                    # un libellé enrichi (ex : "Tesla, Inc. · NMS") sans que cette
                    # bourse/suffixe finisse stocké comme nom de l'actif à la
                    # navigation (positions, historique des trades...).
                    name = row.get("nav_name", row.get("name", ticker))
                    label = "—" if value is None else str(value)
                    key = f"tslight_ticker_{table_key}_{rid}"
                    bg, fg = badge_color(ticker)
                    # Sélecteur à 3 classes (ts_light + la clé de ce badge + .stButton) pour
                    # dépasser la spécificité de la règle générique .st-key-ts_light .stButton
                    # > button (2 classes) : à égalité de !important, la spécificité la plus
                    # haute gagne quel que soit l'ordre d'apparition dans la feuille de style.
                    badge_rules.append(
                        f'.st-key-ts_light .st-key-{key}.stElementContainer .stButton > button '
                        f'{{ background:{bg} !important; color:{fg} !important; }}'
                    )
                    if cell.button(label, key=key):
                        go_to_trading(ticker, name)
                    continue

                if kind == "link":
                    ticker = row.get("ticker", "")
                    name = row.get("nav_name", row.get("name", ticker))
                    label = "—" if value is None else str(value)
                    if cell.button(label, key=f"tslight_name_{table_key}_{rid}"):
                        go_to_trading(ticker, name)
                    continue

                align = "right" if kind in numeric_kinds else "left"
                cell.markdown(
                    f'<div class="ts-light-cell" style="text-align:{align}">{_light_cell_content(col, value)}</div>',
                    unsafe_allow_html=True,
                )

    if badge_rules:
        st.markdown(f"<style>{''.join(badge_rules)}</style>", unsafe_allow_html=True)
