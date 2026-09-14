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
BG = "#FAFAFA"
PANEL = "#F4F4F5"
BORDER = "#E4E4E7"
TEXT = "#18181B"
MUTED = "#71717A"
GREEN = "#16A34A"
RED = "#DC2626"
ACCENT = "#2563EB"  # bleu discret : boutons, liens, onglet actif — jamais le gain/perte (vert/rouge)

FONT_SANS = "'Inter', -apple-system, sans-serif"
FONT_MONO = "'JetBrains Mono', 'Courier New', monospace"

# -- Alias pour l'onglet Portefeuille (theme.inject_light() / render_table_light()) --
# Historiquement une palette séparée le temps que le reste de l'appli restait
# sombre ; désormais identique à la palette globale ci-dessus, gardée comme
# alias pour ne pas devoir toucher ui_portfolio.py.
LIGHT_PAGE = "#FAFAFA"
LIGHT_SURFACE = "#F4F4F5"
LIGHT_BORDER = "#E4E4E7"
LIGHT_GRIDLINE = "#E4E4E7"
LIGHT_TEXT = "#18181B"
LIGHT_MUTED = "#71717A"
LIGHT_FAINT = "#71717A"
LIGHT_BLUE = "#2563EB"
LIGHT_GREEN = "#16A34A"
LIGHT_RED = "#DC2626"

# Palette par classe d'actif (badges/pills de tickers) : fixe et cohérente —
# deux tickers de la même classe d'actif ont toujours la même couleur, jamais
# une couleur aléatoire par ticker (voir badge_color ci-dessous). "Indices/ETF"
# reste le libellé de catégorie utilisé par valuation.category_for (regroupe
# ETF/indice/fonds) ; "Obligations" n'est pas encore une classe d'actif
# disponible dans l'app, mais réservée dans la palette pour ce jour-là.
CATEGORY_COLORS = {
    "Actions": "#2563EB",
    "Crypto": "#F59E0B",
    "Indices/ETF": "#7C3AED",
    "Obligations": "#059669",
}

# Contraste insuffisant en texte blanc sur ces fonds de badge (couleurs
# claires) : texte sombre à la place.
_BADGE_DARK_TEXT_CATEGORIES = {"Crypto"}


def badge_color(category: str | None) -> tuple[str, str]:
    """Couleur de fond + couleur de texte lisible pour le badge d'un ticker,
    déterminée uniquement par sa classe d'actif (voir CATEGORY_COLORS) —
    deux tickers de la même catégorie partagent toujours la même couleur.
    Catégorie absente/inconnue (ex. forex, tables où elle n'est pas
    disponible sans appel réseau supplémentaire) : couleur neutre par défaut,
    jamais une couleur aléatoire par ticker."""
    bg = CATEGORY_COLORS.get(category or "", LIGHT_FAINT)
    fg = LIGHT_TEXT if category in _BADGE_DARK_TEXT_CATEGORIES else "#ffffff"
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
/* Le montant et le pourcentage du P&L sont deux <span> distincts (voir
   render_topbar) pour pouvoir les empiler sur mobile (voir le media query
   plus bas) ; en desktop ils restent affichés côte à côte comme avant. */
.ts-topbar-pnl-pct {{ margin-left: 0.35rem; }}
.ts-topbar-pnl-pct::before {{ content: "("; }}
.ts-topbar-pnl-pct::after {{ content: ")"; }}

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
[class*="st-key-navcell_"] button, [class*="st-key-navorder_"] button, [class*="st-key-navuser_"] button {{
    background: transparent !important;
    border: none !important;
    border-bottom: 1px dashed var(--ts-border) !important;
    border-radius: 0 !important;
    padding: 0.1rem 0 !important;
    color: var(--ts-text) !important;
    font-weight: 400 !important;
    width: auto !important;
}}
[class*="st-key-navcell_"] button:hover, [class*="st-key-navorder_"] button:hover,
[class*="st-key-navuser_"] button:hover {{
    color: var(--ts-accent) !important;
    border-color: var(--ts-accent) !important;
}}
[class*="st-key-navcell_ticker_"] button, [class*="st-key-navorder_"] button {{
    font-family: {FONT_MONO} !important;
    font-variant-numeric: tabular-nums;
}}

/* Expanders, séparateurs, sidebar : pas de cadre — juste de l'espacement, la
   hiérarchie vient de la typo (voir la direction "fintech épuré" du thème). */
[data-testid="stExpander"] {{
    background: transparent !important;
    border: none !important;
}}
hr {{ border-color: var(--ts-border) !important; }}
[data-testid="stSidebar"] {{
    background: var(--ts-panel) !important;
    border-right: 1px solid var(--ts-border) !important;
}}

/* Alertes : texte coloré, sans cadre ni fond de bloc (l'icône native
   Streamlit suffit à les distinguer du texte courant). */
[data-testid="stAlert"] {{
    background: transparent !important;
    border: none !important;
    font-family: {FONT_SANS} !important;
}}

/* Tableaux (positions, historique) : de vrais st.columns par ligne (pas du
   HTML brut), pour pouvoir y placer de vrais boutons de navigation. Pas de
   cadre autour du tableau — juste de la marge ; le repère visuel entre
   lignes reste la fine bordure du en-tête/des lignes ci-dessous. */
[class*="st-key-tstable_"] {{
    margin: 0.4rem 0 1rem 0;
}}
[class*="st-key-tstable_"] [data-testid="stHorizontalBlock"] {{
    border-bottom: 1px solid var(--ts-border);
    padding-bottom: 0.35rem;
    margin-bottom: 0.35rem;
    align-items: center;
}}
[class*="st-key-tstable_"] [data-testid="stHorizontalBlock"]:hover {{
    background: rgba(24,24,27,0.03);
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

/* Libellé de colonne réinjecté dans chaque cellule (voir render_table /
   render_table_light) : invisible en desktop (l'en-tête suffit), affiché
   uniquement une fois la ligne empilée en carte sur petit écran, où
   l'en-tête lui-même est masqué (voir le media query mobile plus bas). */
.ts-cell-mobile-label {{ display: none; }}

/* -- Mobile (écrans étroits) --------------------------------------------
   Principe : les tableaux (de vrais st.columns par ligne, un par tableau)
   passent de "1 ligne = 1 rangée horizontale" à "1 ligne = 1 carte
   empilée verticalement", en réutilisant les mêmes éléments déjà rendus
   (aucune donnée retirée, juste réorganisée) — voir la doc de
   render_table/render_table_light. La barre d'onglets devient défilable
   au doigt plutôt que de se tasser ou passer à la ligne. */
@media (max-width: 640px) {{
    /* -- Échelle globale mobile -------------------------------------------
       Les deux passes précédentes ne faisaient que réorganiser (lignes ->
       cartes, grilles -> 1 colonne) sans jamais réduire la taille des
       polices/paddings/boutons, qui restaient à leur taille desktop sur un
       écran de 375-414px -> débordements/superpositions (retour utilisateur
       après test réel : "tout est trop grand", pas un souci d'organisation).
       Réduire la police racine profite gratuitement à toute règle exprimée
       en rem dans ce fichier ET dans le HTML injecté ailleurs (inline
       style="font-size:0.95rem" compris, rem est toujours relatif à
       <html> peu importe où la règle est déclarée) — c'est le levier qui
       rend cette passe "globale et systématique" plutôt que zone par zone.
       Le reste (composants natifs Streamlit non couverts par du rem, seuil
       tactile des boutons) est ajusté explicitement ci-dessous. */
    html {{ font-size: 14px !important; }}

    .block-container {{
        padding-left: 0.75rem !important;
        padding-right: 0.75rem !important;
        padding-top: 0.6rem !important;
        padding-bottom: 1.25rem !important;
    }}
    [data-testid="stVerticalBlock"] {{ gap: 0.4rem !important; }}
    [data-testid="stHorizontalBlock"] {{ gap: 0.5rem !important; }}

    h1, [data-testid="stMarkdownContainer"] h1 {{ font-size: 1.3rem !important; }}
    h2, [data-testid="stMarkdownContainer"] h2 {{ font-size: 1.1rem !important; }}
    h3, [data-testid="stMarkdownContainer"] h3 {{ font-size: 1rem !important; }}
    h4, [data-testid="stMarkdownContainer"] h4,
    h5, [data-testid="stMarkdownContainer"] h5,
    h6, [data-testid="stMarkdownContainer"] h6 {{ font-size: 0.9rem !important; }}

    /* Boutons : hauteur tactile garantie (~40px) même après la réduction de
       police racine ci-dessus, qui ferait sinon passer la hauteur par
       défaut de Streamlit sous ce seuil. */
    .stButton > button, .stFormSubmitButton > button {{
        min-height: 40px !important;
        padding: 0.4rem 0.75rem !important;
        font-size: 0.82rem !important;
    }}

    [data-testid="stTextInput"] input,
    [data-testid="stNumberInput"] input,
    [data-testid="stTextArea"] textarea,
    [data-baseweb="select"] * {{
        font-size: 0.85rem !important;
    }}
    [data-testid="stRadio"] label p {{ font-size: 0.82rem !important; }}

    [data-testid="stMetricValue"] {{ font-size: 1.25rem !important; }}
    [data-testid="stMetricLabel"] {{ font-size: 0.6rem !important; }}
    [data-testid="stMetricDelta"] {{ font-size: 0.75rem !important; }}

    [data-testid="stExpander"] summary {{ font-size: 0.82rem !important; }}
    [data-testid="stAlert"] {{ font-size: 0.82rem !important; padding: 0.6rem 0.8rem !important; }}

    /* Tableau Admin (st.columns bruts, pas de composant tstable_/tslight_
       existant) : même passe d'échelle + passage en carte empilée comme les
       autres tableaux, voir les conteneurs ts_admin_* dans ui_admin.py. */
    .st-key-ts_admin_header {{ display: none; }}
    [class*="st-key-ts_admin_row_"] [data-testid="stHorizontalBlock"] {{
        flex-direction: column !important;
        align-items: stretch !important;
        border: 1px solid var(--ts-border);
        border-radius: 6px;
        padding: 0.6rem 0.75rem;
        margin-bottom: 0.5rem;
        gap: 0.35rem !important;
    }}
    [class*="st-key-ts_admin_row_"] [data-testid="stColumn"] {{
        width: 100% !important;
        flex: none !important;
        min-width: 0 !important;
    }}
    [class*="st-key-ts_admin_confirm_"] [data-testid="stHorizontalBlock"] {{
        flex-direction: column !important;
        gap: 0.4rem !important;
    }}
    [class*="st-key-ts_admin_confirm_"] [data-testid="stColumn"] {{
        width: 100% !important;
        flex: none !important;
    }}

    [class*="st-key-tstable_header_"] {{ display: none; }}
    [class*="st-key-tstable_"] [data-testid="stHorizontalBlock"] {{
        flex-direction: column !important;
        align-items: stretch !important;
        border: 1px solid var(--ts-border);
        border-radius: 6px;
        padding: 0.6rem 0.75rem;
        margin-bottom: 0.6rem;
    }}
    [class*="st-key-tstable_"] [data-testid="stHorizontalBlock"] [data-testid="stColumn"] {{
        width: 100% !important;
        flex: none !important;
        min-width: 0 !important;
    }}
    .ts-row-cell, .ts-row-cell .ts-num {{ text-align: left !important; white-space: normal; }}
    .ts-cell-mobile-label {{
        display: block;
        color: var(--ts-muted);
        font-size: 0.62rem;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        font-weight: 600;
        margin-top: 0.3rem;
    }}

    /* Barre d'onglets : défilement horizontal au doigt plutôt que des
       libellés tassés ou coupés. */
    .st-key-ts_tabbar {{
        overflow-x: auto;
        flex-wrap: nowrap !important;
        gap: 1rem !important;
        -webkit-overflow-scrolling: touch;
    }}
    .st-key-ts_tabbar > * {{ flex-shrink: 0; }}
    .ts-tab, [class*="st-key-navtab_"] button {{
        font-size: 0.78rem !important;
        padding: 0.4rem 0.05rem !important;
    }}

    /* Barre de valeur : la marge réservée à la barre d'outils Streamlit
       (7.5rem, voir plus haut) est disproportionnée sur un écran étroit.
       Nom du portefeuille masqué (superflu, déjà visible dans le panneau
       latéral) et P&L éclaté en deux lignes (montant, puis pourcentage
       dessous, voir render_topbar). Avec 3 indicateurs à droite (valeur
       totale, liquidité disponible, P&L) en plus du logo, tout ne tient
       plus sur une seule ligne à 375-414px : `flex-wrap` reste sur sa
       valeur par défaut (`wrap`, voir la règle desktop) plutôt que forcé en
       `nowrap` comme avant l'ajout de la liquidité — la barre est `sticky`
       (pas `fixed`, voir plus haut) donc passer sur 2 lignes ne recouvre
       rien, juste une barre un peu plus haute. */
    .ts-topbar {{
        padding: 0.5rem 3rem 0.5rem 0.9rem !important;
    }}
    .ts-topbar-sep, .ts-topbar-portfolio {{ display: none; }}
    .ts-topbar-right {{ gap: 0.75rem; }}
    .ts-topbar-logo {{ font-size: 0.62rem !important; }}
    .ts-topbar-label {{ font-size: 0.52rem !important; }}
    .ts-topbar-value {{ font-size: 0.78rem !important; }}
    .ts-topbar-pnl-amount {{ display: block; }}
    .ts-topbar-pnl-pct {{
        display: block;
        margin-left: 0;
        font-size: 0.62rem !important;
        font-weight: 500;
    }}
    .ts-topbar-pnl-pct::before, .ts-topbar-pnl-pct::after {{ content: ""; }}
    body:has([data-testid="stExpandSidebarButton"]) .ts-topbar-left {{ margin-left: 1.8rem; }}
    /* Titres de page hors barre de valeur (connexion, onboarding premier
       portefeuille, accueil Tutoriel) : mêmes st.title en tout début de
       page, qui se superposaient au bouton natif de réouverture du panneau
       latéral (stExpandSidebarButton, flottant en haut à gauche) quand
       celui-ci est replié — repéré au test réel à 390px. */
    body:has([data-testid="stExpandSidebarButton"]) h1 {{ margin-left: 1.8rem !important; }}

    /* Grille de cartes News (onglet News, hors thème clair scopé) : 1
       colonne au lieu de 3, quel que soit le comportement natif exact de
       Streamlit sur les st.columns (non garanti pour un nombre fixe). */
    [class*="st-key-ts_news_grid"] [data-testid="stHorizontalBlock"] {{
        flex-direction: column !important;
    }}
    [class*="st-key-ts_news_grid"] [data-testid="stColumn"] {{
        width: 100% !important;
        flex: none !important;
    }}
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
    padding: 0.4rem 0;
    margin-bottom: 1.25rem;
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

/* Liste compacte mobile façon Kraken/TradingView (voir render_compact_list) :
   1 ligne HTML par élément, badge+nom à gauche, valeur principale/secondaire
   empilées à droite. Masquée par défaut (desktop) — un rendu desktop
   équivalent (render_table_light, dans un conteneur "tslight_desktop_wrap_")
   coexiste dans le DOM, seule la CSS du media query plus bas décide laquelle
   est visible : aucune donnée n'est dupliquée en dur, les deux viennent des
   mêmes `rows`. */
.st-key-ts_light [class*="st-key-tslight_mobile_"] {{ display: none; }}
.ts-compact-row {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.6rem;
    padding: 0.55rem 0.1rem;
    border-bottom: 1px solid {LIGHT_GRIDLINE};
}}
.ts-compact-row:last-child {{ border-bottom: none; }}
.ts-compact-left {{
    display: flex;
    align-items: center;
    gap: 0.55rem;
    min-width: 0;
    flex: 1 1 auto;
}}
.ts-compact-badge {{
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 0.68rem;
    padding: 0.15rem 0.5rem;
    border-radius: 999px;
    white-space: nowrap;
    flex-shrink: 0;
}}
/* Enveloppe du nom : sans min-width/overflow EXPLICITES ici, un <div> flex
   enfant garde par défaut une largeur minimale basée sur son contenu (pas
   sur celle, contrainte, de .ts-compact-name plus bas) et refuse donc de
   rétrécir — le nom déborde alors de .ts-compact-left au lieu d'être
   tronqué par l'ellipsis, et pousse/chevauche les valeurs de droite quand
   le nom de l'actif est un peu long (repéré au test réel sur Positions). */
.ts-compact-name-wrap {{
    min-width: 0;
    overflow: hidden;
    flex: 1 1 auto;
}}
.ts-compact-name {{
    font-family: {FONT_SANS};
    font-size: 0.85rem;
    font-weight: 600;
    color: {LIGHT_TEXT};
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.ts-compact-sub {{
    font-family: {FONT_SANS};
    font-size: 0.72rem;
    color: {LIGHT_FAINT};
}}
.ts-compact-side {{
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 0.68rem;
    margin-left: 0.3rem;
}}
.ts-compact-right {{ text-align: right; flex-shrink: 0; }}
.ts-compact-primary {{
    font-family: {FONT_MONO};
    font-variant-numeric: tabular-nums;
    font-size: 0.85rem;
    font-weight: 600;
    color: {LIGHT_TEXT};
    white-space: nowrap;
}}
.ts-compact-secondary {{
    font-family: {FONT_MONO};
    font-variant-numeric: tabular-nums;
    font-size: 0.73rem;
    white-space: nowrap;
}}
/* Détail replié sous chaque ligne (Quantité, Gain total, Valeur...) : un
   expander natif Streamlit, allégé pour ne pas réintroduire un gros cadre.
   La bordure visible ne vient pas de [data-testid="stExpander"] (déjà à
   border:none ci-dessous) mais du <details> natif lui-même à l'intérieur,
   non ciblé jusqu'ici -> une fois ouvert, ce cadre touchait presque le
   texte de perf de la ligne juste au-dessus (repéré au test réel). */
.st-key-ts_light [class*="st-key-tslight_detail_"] [data-testid="stExpander"] {{
    border: none !important;
    background: transparent !important;
}}
.st-key-ts_light [class*="st-key-tslight_detail_"] details,
.st-key-ts_light [class*="st-key-tslight_detail_"] details > div {{
    border: none !important;
    background: transparent !important;
}}
.st-key-ts_light [class*="st-key-tslight_detail_"] [data-testid="stExpander"] summary {{
    padding: 0.1rem 0 !important;
    font-size: 0.75rem !important;
    color: {LIGHT_FAINT} !important;
}}
/* Marge propre entre la ligne compacte (dont la perf, en dessous du prix,
   est le dernier élément) et le "> Détails" qui suit, plutôt qu'un
   espacement dépendant du seul gap générique entre blocs Streamlit. */
.st-key-ts_light [class*="st-key-tslight_detail_"] {{
    margin-top: 0.3rem;
}}

/* Tableau (positions / historique) : mêmes principes que le tableau sombre
   (de vrais st.columns par ligne pour de vrais boutons de navigation). Pas de
   cadre autour du tableau — juste de la marge ; la séparation entre lignes
   reste la fine bordure ci-dessous (espacement, pas un cadre plein). */
.st-key-ts_light [class*="st-key-tslight_table_"] {{
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
/* Correctif à la règle :last-child ci-dessus : l'en-tête vit maintenant dans
   son propre conteneur isolé (tslight_header_, voir render_table_light) pour
   pouvoir être masqué sur mobile — son unique stHorizontalBlock y est donc
   TOUJOURS "dernier enfant" de son parent immédiat, peu importe le nombre de
   lignes de données qui suivent par ailleurs. Sans ce correctif, l'en-tête
   perdrait sa bordure du bas même quand des lignes le suivent. */
.st-key-ts_light [class*="st-key-tslight_header_"] [data-testid="stHorizontalBlock"]:last-child {{
    border-bottom: 1px solid {LIGHT_GRIDLINE} !important;
    margin-bottom: 0.4rem !important;
}}
.st-key-ts_light [class*="st-key-tslight_table_"] [data-testid="stHorizontalBlock"]:hover {{
    background: rgba(24,24,27,0.03);
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

/* Expanders (historique, réinitialisation) et alertes : pas de cadre ni de
   fond de bloc, juste du texte hiérarchisé par la typo (voir direction
   "fintech épuré" du thème). */
.st-key-ts_light [data-testid="stExpander"] {{
    background: transparent !important;
    border: none !important;
}}
.st-key-ts_light [data-testid="stAlert"] {{
    background: transparent !important;
    border: none !important;
    color: {LIGHT_TEXT} !important;
}}

/* Mobile (écrans étroits) : même principe que le tableau sombre (voir la
   fin de _CSS) — chaque ligne (Positions, Historique...) devient une
   carte empilée verticalement plutôt qu'une rangée horizontale tassée. */
@media (max-width: 640px) {{
    /* Positions (voir render_compact_list) : le rendu desktop cède la place
       à la liste compacte, toutes deux calculées à partir des mêmes rows. */
    .st-key-ts_light [class*="st-key-tslight_desktop_wrap_"] {{ display: none !important; }}
    .st-key-ts_light [class*="st-key-tslight_mobile_"] {{ display: block; }}

    .st-key-ts_light [class*="st-key-tslight_header_"] {{ display: none; }}
    .st-key-ts_light [class*="st-key-tslight_table_"] [data-testid="stHorizontalBlock"] {{
        flex-direction: column !important;
        align-items: stretch !important;
        border: 1px solid {LIGHT_BORDER};
        border-radius: 8px;
        padding: 0.7rem 0.9rem;
        margin-bottom: 0.6rem;
        background: {LIGHT_SURFACE};
    }}
    .st-key-ts_light [class*="st-key-tslight_table_"] [data-testid="stHorizontalBlock"] [data-testid="stColumn"] {{
        width: 100% !important;
        flex: none !important;
        min-width: 0 !important;
    }}
    .ts-light-cell, .ts-light-cell .ts-light-num {{ text-align: left !important; white-space: normal; }}

    /* Vitrine d'accueil Trading (Indices/Top cap/Crypto/Forex) : 1 colonne
       au lieu de 2, quel que soit le comportement natif exact de Streamlit
       sur les st.columns (non garanti pour un nombre fixe). */
    .st-key-ts_light [class*="st-key-ts_home_grid"] [data-testid="stHorizontalBlock"] {{
        flex-direction: column !important;
    }}
    .st-key-ts_light [class*="st-key-ts_home_grid"] [data-testid="stColumn"] {{
        width: 100% !important;
        flex: none !important;
    }}

    /* Échelle globale (voir le même principe, plus détaillé, dans le media
       query de _CSS) : la réduction de police racine posée là-bas profite
       déjà à tout ce qui est exprimé en rem ci-dessus (cartes, badges,
       lignes compactes...) ; ce qui suit couvre ce qui doit encore être
       resserré explicitement (paddings de carte, boutons pastille,
       métriques) pour ne plus déborder sur un écran de 375-414px. */
    .st-key-ts_light [class*="st-key-ts_card_"] {{
        padding: 0.3rem 0 !important;
        margin-bottom: 0.9rem !important;
    }}
    .st-key-ts_light .stButton > button,
    .st-key-ts_light .stFormSubmitButton > button {{
        font-size: 0.78rem !important;
        padding: 0.35rem 0.8rem !important;
        min-height: 40px !important;
    }}
    .st-key-ts_light [data-testid="stMetricValue"] {{ font-size: 1.2rem !important; }}
    .st-key-ts_light [data-testid="stMetricLabel"] {{ font-size: 0.6rem !important; }}

    .st-key-ts_portfolio_pills, .st-key-ts_period_pills {{ gap: 0.4rem !important; }}
    .ts-light-pill-active {{ padding: 0.32rem 0.8rem !important; font-size: 0.78rem !important; }}
    .st-key-ts_period_pills .stButton > button {{ font-size: 0.72rem !important; padding: 0.18rem 0.6rem !important; }}
    .ts-period-active {{ padding: 0.18rem 0.6rem !important; font-size: 0.72rem !important; }}

    /* Liste compacte (Positions sur mobile, voir render_compact_list) */
    .ts-compact-row {{ padding: 0.45rem 0.05rem !important; gap: 0.5rem !important; }}
    .ts-compact-badge {{ font-size: 0.62rem !important; padding: 0.12rem 0.4rem !important; }}
    .ts-compact-name {{ font-size: 0.8rem !important; }}
    .ts-compact-sub {{ font-size: 0.68rem !important; }}
    .ts-compact-primary {{ font-size: 0.8rem !important; }}
    .ts-compact-secondary {{ font-size: 0.68rem !important; }}

    /* Barre de recherche (onglet Trading) : reste bien visible mais sans
       déborder à côté du bouton "afficher/masquer" natif de l'input. */
    .st-key-ts_card_search [data-testid="stTextInput"] input {{
        font-size: 0.92rem !important;
        padding-top: 0.55rem !important;
        padding-bottom: 0.55rem !important;
    }}

    /* Graphique de prix (Plotly) : masquer la toolbar (loupe/zoom/pan/
       appareil photo — pensée desktop) qui grignotait une bonne partie de
       la hauteur disponible sur un écran étroit. Zoom/pan restent
       utilisables au doigt (pinch-to-zoom + glisser), gérés nativement par
       Plotly indépendamment de cette toolbar (CSS uniquement : la config
       Python st.plotly_chart reste la même sur desktop et mobile). */
    .st-key-ts_light .js-plotly-plot .modebar {{ display: none !important; }}

    /* Sélecteur de période (1J/1S/1M/3M/6M/YTD/1A/5A/Tout) : une seule
       ligne défilable au doigt façon Kraken, plutôt que les pastilles
       larges qui passaient sur plusieurs lignes et mangeaient une bonne
       partie de la hauteur restante pour le graphique lui-même. */
    .st-key-ts_light .st-key-chart_period_radio [role="radiogroup"] {{
        flex-wrap: nowrap !important;
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch;
        gap: 0.35rem !important;
    }}
    .st-key-ts_light .st-key-chart_period_radio [role="radiogroup"] label {{
        flex-shrink: 0 !important;
        min-height: 32px !important;
    }}
    .st-key-ts_light .st-key-chart_period_radio [role="radiogroup"] label p {{
        font-size: 0.72rem !important;
    }}
}}
"""


def inject_light() -> None:
    """Injecte le CSS du thème clair, entièrement scopé sous .st-key-ts_light
    (voir le commentaire en tête de _LIGHT_CSS). N'a aucun effet tant que le
    contenu n'est pas rendu à l'intérieur de `with st.container(key="ts_light")`.
    Sans effet sur le thème sombre global ni les autres onglets."""
    st.markdown(f"<style>{_LIGHT_CSS}</style>", unsafe_allow_html=True)


def render_topbar(portfolio_name: str, total_value: float, pnl_eur: float, pnl_pct: float, cash: float) -> None:
    """`cash` : liquidité disponible du portefeuille actif (portfolio.cash),
    la même valeur que le garde-fou déjà utilisé pour vérifier qu'un ordre ne
    dépasse pas le solde disponible (voir Portfolio.buy/open_short) — pas un
    nouveau calcul, juste rendue visible en permanence en haut de page."""
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
                    <span class="ts-topbar-label">LIQUIDITÉ DISPONIBLE</span>
                    <span class="ts-topbar-value">{cash:,.2f} €</span>
                </div>
                <div class="ts-topbar-item">
                    <span class="ts-topbar-label">P&amp;L JOUR</span>
                    <span class="ts-topbar-value" style="color:{color}">
                        <span class="ts-topbar-pnl-amount">{sign}{pnl_eur:,.2f} €</span>
                        <span class="ts-topbar-pnl-pct">{sign}{pnl_pct:.2f}%</span>
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


def render_movers_alert(movers: list[dict]) -> None:
    """Bannière en session (pas de push/email) signalant qu'une position
    détenue du portefeuille actif a bougé de plus du seuil configuré
    (voir valuation.MOVER_THRESHOLD_PCT) depuis la clôture précédente.
    Construite uniquement à partir de snapshots déjà calculés à chaque
    chargement de page (valuation.total_value) : aucun appel réseau
    supplémentaire vers les API de prix externes."""
    if not movers:
        return
    parts = []
    for m in movers:
        color = GREEN if m["day_pnl_pct"] >= 0 else RED
        sign = "+" if m["day_pnl_pct"] >= 0 else ""
        parts.append(
            f'<span style="color:{color};font-weight:600">{html_lib.escape(m["ticker"])} '
            f'{sign}{m["day_pnl_pct"]:.1f}%</span>'
        )
    st.markdown(
        f"""
        <div style="padding:0.5rem 1.1rem;border:1px solid var(--ts-border);border-radius:4px;
                     background:var(--ts-panel);margin-bottom:0.6rem;font-family:{FONT_SANS};
                     font-size:0.85rem;color:var(--ts-text);">
            ⚡ Mouvement du jour sur tes positions : {" &nbsp;·&nbsp; ".join(parts)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def go_to_history(user_id: str, username: str | None = None) -> None:
    """Bascule vers la page Historique (transparence des ordres + métriques
    de performance) du portefeuille officiel d'un utilisateur ARBITRAIRE,
    accessible en cliquant sur son nom depuis le Classement. Même mécanique
    que go_to_trading (session_state + st.rerun, jamais un lien <a href>,
    voir le commentaire en tête de fichier)."""
    st.session_state.history_user_id = user_id
    st.session_state.history_username = username or ""
    st.session_state.active_tab = "historique"
    st.rerun()


DEFAULT_TABS = [
    ("portefeuille", "Portefeuille"), ("trading", "Trading"),
    ("cours", "Tutoriel"), ("classement", "Classement"), ("news", "News"),
    ("reglement", "Règlement"),
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


# -- Graphiques Plotly (Portefeuille + Trading) -------------------------------
# Centralisé ici plutôt que dupliqué dans chaque ui_*.py : si la palette
# change un jour, les graphiques suivent automatiquement (voir prompt 2/5).

def plotly_layout(**overrides) -> dict:
    """Mise en page Plotly commune : fond transparent (se fond dans la page,
    plus de carte avec son propre fond derrière depuis la refonte des cadres),
    grille discrète (LIGHT_GRIDLINE, à peine plus marquée que le fond — jamais
    un gris franc), graduations en police mono (cohérent avec le reste des
    chiffres de l'app) et atténuées (LIGHT_MUTED, ce sont des repères, pas la
    donnée principale)."""
    layout = dict(
        height=380,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_SANS, color=LIGHT_MUTED),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(
            gridcolor=LIGHT_GRIDLINE, linecolor=LIGHT_GRIDLINE,
            tickfont=dict(family=FONT_MONO, color=LIGHT_MUTED),
        ),
        yaxis=dict(
            gridcolor=LIGHT_GRIDLINE, linecolor=LIGHT_GRIDLINE,
            tickfont=dict(family=FONT_MONO, color=LIGHT_MUTED),
        ),
    )
    layout.update(overrides)
    return layout


def plotly_area_range(*value_lists, pad_frac: float = 0.08) -> list[float]:
    """Plage [min, max] paddée à poser explicitement (`autorange=False`) sur
    l'axe Y d'un graphique utilisant `fill="tozeroy"` : sans ça, Plotly étend
    l'autorange jusqu'à 0 pour englober le polygone de remplissage, ce qui
    écrase visuellement toute variation qui reste loin de zéro (valeur de
    portefeuille en euros, indice en base 100...). Accepte directement des
    colonnes pandas (itérables), plusieurs si le graphique partage l'axe Y
    entre plusieurs courbes (ex : portefeuille + indice de comparaison)."""
    values = [v for values in value_lists for v in values if v is not None and v == v]
    lo, hi = min(values), max(values)
    span = hi - lo
    pad = span * pad_frac if span > 0 else max(abs(hi), 1.0) * pad_frac
    return [lo - pad, hi + pad]


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def plotly_area_fillgradient(color: str, opacity: float = 0.22) -> dict:
    """Dégradé vertical léger sous une courbe (`fill="tozeroy"`) : opaque près
    de la courbe, transparent vers la ligne de base — jamais un aplat uni."""
    return dict(
        type="vertical",
        colorscale=[[0, _hex_to_rgba(color, opacity)], [1, _hex_to_rgba(color, 0.0)]],
    )


# Modebar sans le logo Plotly (peu cohérent avec le style épuré) ni les
# boutons de sélection (select/lasso, toggle spikelines) : sans usage sur un
# graphique en ligne/aire/chandeliers, seulement du bruit visuel. Zoom/pan/
# reset/téléchargement restent disponibles. À fusionner avec {"scrollZoom":
# False} côté Trading (voir ui_trading.py), déjà en place et à ne pas
# changer (prompt 2/5).
PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "toggleSpikelines"],
}


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
        with st.container(key=f"tstable_header_{table_key}"):
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

                if kind == "user_link":
                    target_user_id = row.get("user_id", "")
                    nav_name = row.get("nav_username", row.get("username", ""))
                    label = "—" if value is None else str(value)
                    if cell.button(label, key=f"navuser_{col['key']}_{rid}"):
                        go_to_history(target_user_id, nav_name)
                    continue

                # Le libellé mobile (voir _CSS, masqué en desktop) permet à
                # chaque cellule de rester lisible une fois la ligne empilée
                # verticalement en carte sur petit écran, l'en-tête de colonne
                # étant alors masqué (voir tstable_header_ ci-dessus).
                align = "right" if kind in numeric_kinds else "left"
                cell.markdown(
                    f'<div class="ts-row-cell" style="text-align:{align}">'
                    f'<span class="ts-cell-mobile-label">{html_lib.escape(col["label"])}</span>'
                    f'{_cell_content(col, value)}</div>',
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
    if kind == "mono_text":
        # Valeur déjà formatée en chaîne (ex : prix avec suffixe "pts"/devise) mais
        # numérique par nature : police monospace comme les autres colonnes de chiffres.
        return f'<span class="ts-light-num">{html_lib.escape(str(value))}</span>'
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
    if kind == "signed_eur_pct":
        eur_value, pct_value = value
        color = LIGHT_GREEN if eur_value >= 0 else LIGHT_RED
        eur_sign = "+" if eur_value >= 0 else ""
        pct_sign = "+" if pct_value >= 0 else ""
        return (
            f'<span class="ts-light-num" style="color:{color}">'
            f'{eur_sign}{eur_value:,.{decimals}f} € ({pct_sign}{pct_value:,.1f}%)</span>'
        )
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
    ticker comme une pastille colorée cliquable (couleur fixe par classe
    d'actif, voir badge_color/CATEGORY_COLORS) plutôt qu'un simple lien texte.

    `show_header=False` masque la ligne d'en-têtes (listes compactes façon
    encadré d'actifs, où les libellés de colonne n'apportent rien).
    """
    numeric_kinds = {"num", "eur", "signed_eur", "pct", "signed_pct", "signed_eur_pct", "mono_text"}
    widths = [
        col["width"] if "width" in col else (1.3 if col.get("kind") in numeric_kinds else 1.0)
        for col in columns
    ]

    badge_rules = []
    with st.container(key=f"tslight_table_{table_key}"):
        if show_header:
            with st.container(key=f"tslight_header_{table_key}"):
                header_cols = st.columns(widths)
                for col, hcol in zip(columns, header_cols):
                    align = "right" if col.get("kind") in numeric_kinds else "left"
                    hcol.markdown(
                        f'<div class="ts-light-col-label" style="text-align:{align}">'
                        f'{html_lib.escape(col["label"])}</div>',
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
                    bg, fg = badge_color(row.get("category"))
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

                # Libellé mobile (voir _CSS, masqué en desktop) : garde chaque
                # cellule lisible une fois la ligne empilée en carte sur petit
                # écran, l'en-tête de colonne étant alors masqué (tslight_header_).
                align = "right" if kind in numeric_kinds else "left"
                cell.markdown(
                    f'<div class="ts-light-cell" style="text-align:{align}">'
                    f'<span class="ts-cell-mobile-label">{html_lib.escape(col["label"])}</span>'
                    f'{_light_cell_content(col, value)}</div>',
                    unsafe_allow_html=True,
                )

    if badge_rules:
        st.markdown(f"<style>{''.join(badge_rules)}</style>", unsafe_allow_html=True)


def render_compact_list(
    rows: list[dict], table_key: str,
    detail: "Callable[[dict], None] | None" = None,
) -> None:
    """Liste compacte façon Kraken/TradingView, pour l'affichage mobile
    (voir le media query dans _LIGHT_CSS — masquée en desktop, où
    render_table_light fait foi). Une ligne HTML par élément (badge coloré +
    nom + sens à gauche, valeur principale/secondaire empilées à droite),
    séparées par un simple trait plutôt qu'un cadre par ligne.

    `rows` : liste de dicts {"ticker", "name", "category" (optionnel),
    "side" (optionnel, "Long"/"Short"), "primary" (str déjà formaté, ex prix),
    "secondary" (str déjà formaté avec sa couleur, ex gain du jour),
    "secondary_color" (optionnel)}.
    `detail` : callable(row) optionnel, appelé à l'intérieur d'un expander
    replié sous chaque ligne — pour les champs secondaires (Quantité, Gain
    total, Valeur...) qui n'ont pas leur place dans la ligne compacte.
    """
    with st.container(key=f"tslight_mobile_{table_key}"):
        for row in rows:
            bg, fg = badge_color(row.get("category"))
            side = row.get("side")
            side_html = ""
            if side:
                side_color = LIGHT_GREEN if side == "Long" else LIGHT_RED
                side_html = f'<span class="ts-compact-side" style="color:{side_color}">{side[0]}</span>'
            secondary_color = row.get("secondary_color", LIGHT_TEXT)
            st.markdown(
                f"""
                <div class="ts-compact-row">
                    <div class="ts-compact-left">
                        <span class="ts-compact-badge" style="background:{bg};color:{fg}">
                            {html_lib.escape(row['ticker'])}
                        </span>
                        <div class="ts-compact-name-wrap">
                            <div class="ts-compact-name">{html_lib.escape(row['name'])}{side_html}</div>
                        </div>
                    </div>
                    <div class="ts-compact-right">
                        <div class="ts-compact-primary">{html_lib.escape(row.get('primary', ''))}</div>
                        <div class="ts-compact-secondary" style="color:{secondary_color}">
                            {html_lib.escape(str(row.get('secondary', '')))}
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if detail is not None:
                with st.container(key=f"tslight_detail_{table_key}_{_safe_key_part(row['ticker'])}"):
                    with st.expander("Détails"):
                        detail(row)
