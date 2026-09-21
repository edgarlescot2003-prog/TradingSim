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

# Palette globale de l'appli : dégradé sombre teal -> bleu-marine (inspiration
# Revolut), remplace le fond clair des prompts 1 à 7. Les noms de variables
# (BG/PANEL/...) restent génériques : ce sont "les couleurs du thème actuel",
# pas littéralement "claires" ou "sombres" — inutile de les renommer à chaque
# changement de direction esthétique.
#
# BG reste une couleur PLEINE (pas le dégradé lui-même, voir BG_GRADIENT
# ci-dessous) : sert de repli pour tout ce qui ne peut pas afficher un
# dégradé (.streamlit/config.toml, qui ne supporte que des couleurs unies).
BG = "#0F4C5C"
BG_GRADIENT_TOP = "#1B7A8C"
BG_GRADIENT_MID = "#0F4C5C"
BG_GRADIENT_BOTTOM = "#0A2A33"
BG_GRADIENT = f"linear-gradient(180deg, {BG_GRADIENT_TOP} 0%, {BG_GRADIENT_MID} 50%, {BG_GRADIENT_BOTTOM} 100%)"
# Fond de section légèrement rehaussée (boutons, champs de saisie, popovers,
# cartes News...) : plus clair que le dégradé mais reste dans la même famille
# sombre (jamais un fond clair qui trancherait). Couleur pleine (pas de
# dégradé ici, pour rester utilisable partout sans dépendre de la position
# verticale de l'élément sur la page).
PANEL = "#155A6B"
# Bordures/séparateurs : blanc translucide plutôt qu'une couleur pleine —
# reste discret quelle que soit la teinte du dégradé en dessous (clair en
# haut, presque noir en bas), sans avoir à varier selon la position.
BORDER = "rgba(255,255,255,0.16)"
TEXT = "#FFFFFF"
# Texte secondaire : blanc atténué (transparence), jamais un gris sombre —
# resterait illisible sur un fond lui-même sombre. La hiérarchie visuelle se
# fait par la taille/le poids de la police, pas par une variation de teinte
# de texte (voir la doc de conception d'origine de ce changement de fond).
MUTED = "rgba(255,255,255,0.65)"
# Vert/rouge éclaircis (variantes 400 plutôt que 600) : les teintes plus
# sombres utilisées sur fond clair perdaient en lisibilité sur ce nouveau
# fond sombre, sans changer leur fonction sémantique (vert = hausse,
# rouge = baisse).
GREEN = "#4ADE80"
RED = "#F87171"
# Action "Vendre" (clôture d'une position longue existante, prompt 13) :
# gris-bleu clair plutôt qu'une 3e teinte vive — se distingue nettement
# de Long (vert, "Acheter" jusqu'au prompt 18) et de Short (rouge), tout en
# restant neutre plutôt qu'alarmant (ce n'est ni un gain ni une perte en
# soi, juste une clôture).
SELL_NEUTRAL = "#94A3B8"
# Orange plutôt que bleu : sur un fond dégradé teal -> bleu-marine (donc
# lui-même dans la famille des bleus), un accent bleu se fond dans le fond au
# lieu de s'en détacher. L'orange, complémentaire du teal, reste visible sur
# TOUTE la hauteur du dégradé (clair en haut, presque noir en bas) — jamais
# le gain/perte (vert/rouge), ni une des couleurs de catégorie d'actif.
ACCENT = "#F97316"
# Texte sombre pour les badges à fond clair (voir badge_color) : réutilise le
# point le plus sombre du dégradé plutôt qu'un noir pur, pour rester dans la
# même famille de couleurs que le reste du thème.
BADGE_DARK_TEXT = BG_GRADIENT_BOTTOM

FONT_SANS = "'Inter', -apple-system, sans-serif"
FONT_MONO = "'JetBrains Mono', 'Courier New', monospace"

# -- Alias pour l'onglet Portefeuille (theme.inject_light() / render_table_light()) --
# Historiquement une palette séparée le temps que le reste de l'appli restait
# sombre ; désormais identique à la palette globale ci-dessus, gardée comme
# alias pour ne pas devoir toucher ui_portfolio.py. LIGHT_PAGE n'est PLUS
# utilisée comme fond réel (voir .st-key-ts_light, passé en transparent pour
# laisser transparaître le dégradé de la page sans à-plat rectangulaire) ;
# gardée pour compatibilité, au cas où un futur ajout en aurait besoin.
LIGHT_PAGE = BG
LIGHT_SURFACE = PANEL
LIGHT_BORDER = BORDER
LIGHT_GRIDLINE = BORDER
LIGHT_TEXT = TEXT
LIGHT_MUTED = MUTED
LIGHT_FAINT = MUTED
LIGHT_BLUE = ACCENT
LIGHT_GREEN = GREEN
LIGHT_RED = RED

# Palette par classe d'actif (badges/pills de tickers) : fixe et cohérente —
# deux tickers de la même classe d'actif ont toujours la même couleur, jamais
# une couleur aléatoire par ticker (voir badge_color ci-dessous). "Indices/ETF"
# reste le libellé de catégorie utilisé par valuation.category_for (regroupe
# ETF/indice/fonds classiques ; "Obligations" couvre spécifiquement les ETF
# obligataires, voir valuation.BOND_ETF_TICKERS). Teintes éclaircies par
# rapport à la palette claire d'origine (variantes 400 plutôt que 600/800) :
# calibrées pour rester identifiables sur l'ensemble du dégradé de fond, du
# teal clair en haut au bleu-marine presque noir en bas — la luminosité
# contraste autant que la teinte, pas seulement une question de choix de
# couleur (repère utile aussi pour une perception des couleurs réduite).
CATEGORY_COLORS = {
    "Actions": "#3B82F6",
    "Crypto": "#FBBF24",
    "Indices/ETF": "#A78BFA",
    "Obligations": "#2DD4BF",
    "Forex": "#38BDF8",
    "Matières premières": "#D97706",
}

# Contraste insuffisant en texte blanc sur ces fonds de badge (couleurs
# claires) : texte sombre à la place (voir BADGE_DARK_TEXT). Presque toutes
# les catégories sont concernées avec cette palette éclaircie — seule
# "Actions" reste assez soutenue pour garder du texte blanc.
_BADGE_DARK_TEXT_CATEGORIES = {"Crypto", "Indices/ETF", "Obligations", "Forex", "Matières premières"}


# Palette qualitative générique pour un camembert dont les catégories ne
# sont PAS connues à l'avance (secteur/géographie, prompt 21 point 2) —
# contrairement à CATEGORY_COLORS ci-dessus (classes d'actif, ensemble fixe
# de 6 valeurs). Couleurs vives choisies pour rester distinguables entre
# elles sur le dégradé de fond sombre de l'app, même logique de contraste.
QUALITATIVE_PALETTE = [
    "#3B82F6", "#FBBF24", "#A78BFA", "#2DD4BF", "#38BDF8", "#D97706",
    "#F472B6", "#4ADE80", "#F87171", "#818CF8", "#FB923C", "#34D399",
]
# Gris neutre dédié à "Non défini" (voir valuation.UNDEFINED_LABEL) : cette
# tranche ne doit JAMAIS se confondre avec une vraie catégorie, quelle que
# soit sa position dans la liste des labels — voir pie_colors ci-dessous.
UNDEFINED_SLICE_COLOR = "#64748B"


def pie_colors(labels: list[str]) -> list[str]:
    """Une couleur par label pour un camembert générique (secteur/
    géographie...) : cycle sur QUALITATIVE_PALETTE dans l'ordre des labels,
    sauf "Non défini" (valuation.UNDEFINED_LABEL — comparé en dur ici plutôt
    qu'importé pour ne pas faire dépendre ce module purement visuel de la
    logique métier de valuation.py) qui a toujours sa couleur neutre dédiée
    (voir UNDEFINED_SLICE_COLOR), peu importe sa position dans la liste."""
    colors = []
    i = 0
    for label in labels:
        if label == "Non défini":
            colors.append(UNDEFINED_SLICE_COLOR)
        else:
            colors.append(QUALITATIVE_PALETTE[i % len(QUALITATIVE_PALETTE)])
            i += 1
    return colors


def badge_color(category: str | None) -> tuple[str, str]:
    """Couleur de fond + couleur de texte lisible pour le badge d'un ticker,
    déterminée uniquement par sa classe d'actif (voir CATEGORY_COLORS) —
    deux tickers de la même catégorie partagent toujours la même couleur.
    Catégorie absente/inconnue (tables où elle n'est pas disponible sans
    appel réseau supplémentaire, ex. historique/ordres en attente) : couleur
    neutre par défaut, jamais une couleur aléatoire par ticker."""
    # PANEL (couleur pleine) plutôt que MUTED (blanc translucide, illisible
    # une fois utilisé comme fond de badge avec du texte blanc par-dessus).
    bg = CATEGORY_COLORS.get(category or "", PANEL)
    fg = BADGE_DARK_TEXT if category in _BADGE_DARK_TEXT_CATEGORIES else "#ffffff"
    return bg, fg


# Libellé affiché pour une valeur de Trade.action / PendingOrder.action
# (portfolio.py — "achat", "vente", "ouverture short", "rachat short", jamais
# modifiées : ce sont des clés internes réutilisées telles quelles par
# order_engine/valuation). Seul "achat" a un libellé dédié ("Long", prompt
# 18 — le bouton "Acheter" du formulaire d'ordre a été renommé "Long", ce
# libellé suit partout où l'action est réaffichée telle quelle : historique
# des trades, ordres en attente, page Historique) ; les 3 autres gardent
# leur capitalisation par défaut, inchangée.
ACTION_LABELS = {"achat": "Long"}


def action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action.capitalize())


_CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

:root {{
    --ts-bg: {BG_GRADIENT};
    --ts-panel: {PANEL};
    --ts-border: {BORDER};
    --ts-text: {TEXT};
    --ts-muted: {MUTED};
    --ts-green: {GREEN};
    --ts-red: {RED};
    --ts-accent: {ACCENT};
}}

html, body, .stApp {{
    /* color-scheme: dark (plutôt que le light forcé des prompts précédents) :
       le thème est maintenant réellement sombre, on veut que les widgets
       natifs du navigateur (scrollbars, cases à cocher...) suivent leur
       propre rendu sombre plutôt que d'entrer en conflit avec lui.
       background en propriété courte (pas background-color, qui n'accepte
       pas les dégradés) + background-attachment: fixed pour que le dégradé
       reste calé sur la hauteur de l'écran plutôt que de s'étirer/se répéter
       selon la hauteur de contenu de chaque page, qui varie beaucoup d'un
       onglet à l'autre. */
    color-scheme: dark !important;
    background: var(--ts-bg) !important;
    background-attachment: fixed !important;
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
    /* padding-left/right réduits (2rem, contre la marge par défaut de
       Streamlit ~6.5rem à cette largeur) : sur écran large, ça laissait un
       vide inutile de chaque côté de toute page (pas seulement Trading) —
       mesuré sur le site déployé (Playwright, 1920px) : ~104px de marge
       inutilisée par côté avant ce correctif, ramenée à ~32px. Vérifié à
       1366px (laptop courant) et sur Portefeuille/Classement : aucune
       régression, uniquement plus d'espace utile pour le contenu. */
    padding-left: 2rem !important;
    padding-right: 2rem !important;
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
    /* Transparent (pas --ts-panel) : ce bloc doit se fondre dans le dégradé
       général de la page, pas se détacher dessus avec un fond plus foncé —
       résidu du "fond de section légèrement rehaussée" pensé à l'origine
       pour le thème clair (prompts 1-7), jamais retiré au passage au fond
       dégradé sombre (prompt 8). background-attachment:fixed sur html/body
       (voir plus haut) assure que le dégradé reste continu même une fois la
       barre sticky au défilement. */
    background: transparent;
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
/* Décalage vertical de quelques pixels au clic/focus (repéré sur certains
   boutons) : BaseWeb ajoute par défaut un box-shadow/outline de focus et
   peut faire varier l'épaisseur de bordure entre états — border/box-shadow
   explicitement figés ici sur CHAQUE état (normal, survol, focus, actif)
   pour que la boîte du bouton ne change jamais de taille, quel que soit
   l'état. */
.stButton > button:active, .stFormSubmitButton > button:active,
.stButton > button:focus, .stFormSubmitButton > button:focus {{
    border: 1px solid var(--ts-accent) !important;
    box-shadow: none !important;
    outline: none !important;
    transform: none !important;
}}
.stButton > button[kind="primary"]:active, .stFormSubmitButton > button[kind="primary"]:active,
.stButton > button[kind="primary"]:focus, .stFormSubmitButton > button[kind="primary"]:focus {{
    border: 1px solid var(--ts-accent) !important;
    box-shadow: none !important;
    outline: none !important;
    transform: none !important;
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
/* Seule la couleur du texte distingue l'onglet actif des autres — même
   taille, même graisse, même position que [class*="st-key-navtab_"] button
   ci-dessous (bordure transparente incluse, pour ne pas décaler la ligne
   au clic) : aucun autre repère visuel (pas de soulignement plein, pas de
   letter-spacing différent). */
/* line-height/box-sizing/display explicites et IDENTIQUES entre .ts-tab
   (un <div>, l'onglet actif) et [class*="st-key-navtab_"] button (un vrai
   <button>, les onglets inactifs) : un <div> et un <button> n'ont pas le
   même line-height/vertical-align navigateur par défaut même à padding et
   taille de police identiques — l'onglet actif apparaissait décalé
   verticalement par rapport aux autres, alignés sur la même ligne dans
   .st-key-ts_tabbar (align-items: center, qui centre chacun sur SA propre
   hauteur, sans corriger une différence de hauteur entre eux). */
.ts-tab {{
    font-family: {FONT_SANS};
    font-weight: 600;
    font-size: 0.85rem;
    color: var(--ts-accent);
    padding: 0.55rem 0.05rem;
    border-bottom: 2px solid transparent;
    display: inline-flex;
    align-items: center;
    line-height: 1.2;
    box-sizing: border-box;
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
    display: inline-flex !important;
    align-items: center !important;
    line-height: 1.2 !important;
    box-sizing: border-box !important;
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
    /* min-height:0 (au lieu du min-height ~40px par défaut d'un st.button) :
       sans ça, cette cellule-bouton restait bien plus haute que les cellules
       texte voisines (de simples <div>, ~21px), ce qui gonflait toute la
       ligne du tableau à sa hauteur et laissait les autres cellules
       centrées dans un espace bien plus grand qu'elles (repéré sur
       Classement/Historique : lignes trop hautes, texte qui semblait
       "poussé" dans sa cellule). line-height aligné sur le reste du texte
       de tableau (.ts-row-cell) plutôt que la valeur par défaut d'un
       bouton, pour un rendu cohérent quelle que soit la cellule. */
    min-height: 0 !important;
    height: auto !important;
    line-height: 1.4 !important;
    justify-content: flex-start !important;
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
/* Panneau latéral natif : REPLIÉ PAR DÉFAUT sur desktop aussi désormais
   (voir app.py, initial_sidebar_state="collapsed") plutôt que masqué. Une
   première version masquait ici l'icône de repli interne au panneau
   (stSidebarCollapseButton) pour "nettoyer" l'UI sur desktop — mais cette
   icône est le SEUL moyen de refermer le panneau une fois ouvert : la
   masquer laissait le panneau coincé ouvert dès qu'il l'était (ce qui
   arrivait tout le temps, puisqu'il s'ouvrait encore en grand par défaut à
   l'époque), sans aucun moyen de le refermer — régression bloquante
   détectée après coup. Le panneau natif Streamlit (icône de repli/dépli
   comprise) n'est donc plus touché par du CSS ici : entièrement fonctionnel
   dans les deux sens, juste replié au chargement. */

/* Page Connexion/Inscription (voir ui_auth.py, st.container(key="ts_login_page")) :
   centrée au lieu de rester collée en haut à gauche par défaut. Centrage
   horizontal robuste (margin:auto + max-width) ; le centrage vertical reste
   approximatif (une marge haute fixe plutôt qu'un vrai centrage flex sur
   toute la hauteur d'écran, qui demanderait de transformer .block-container
   en conteneur flex pour TOUTE l'app, bien au-delà de cette seule page) —
   suffisant pour un rendu nettement plus soigné qu'un bloc aligné en haut à
   gauche, sans risquer de décaler autre chose. */
.st-key-ts_login_page {{
    max-width: 440px;
    margin: 10vh auto 0 auto !important;
}}
@media (max-width: 640px) {{
    .st-key-ts_login_page {{ margin-top: 4vh !important; }}
}}

/* Alertes : texte coloré, sans cadre ni fond de bloc (l'icône native
   Streamlit suffit à les distinguer du texte courant). */
[data-testid="stAlert"] {{
    background: transparent !important;
    border: none !important;
    font-family: {FONT_SANS} !important;
}}

/* Cartes de la grille News (voir ui_news.py, render_card) : fond légèrement
   rehaussé (PANEL) sans bordure — juste assez pour distinguer chaque carte
   dans une grille répétitive de plusieurs items similaires, contrairement
   aux sections Portefeuille/Trading (déjà séparées par l'espacement seul,
   voir prompt 1/5) qui n'ont pas ce besoin. */
[class*="st-key-ts_card_news_"] {{
    background: var(--ts-panel);
    border-radius: 10px;
    padding: 0.9rem 1.1rem;
    margin-bottom: 0.5rem;
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
    background: rgba(255,255,255,0.05);
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
    /* Les 3 indicateurs passent d'une rangée (label au-dessus de la valeur,
       serrés côte à côte) à une colonne de 3 lignes (label à gauche, valeur
       à droite, sur la même ligne) : avec 3 libellés dont un long
       ("LIQUIDITÉ DISPONIBLE"), les caser côte à côte à 375-414px forçait le
       libellé à passer à la ligne alors que sa valeur restait sur une
       seule, donnant l'impression que valeur et libellé n'étaient plus
       associés (repéré au test réel). Chaque paire reste sans ambiguïté
       quelle que soit la longueur du libellé. */
    .ts-topbar-right {{
        gap: 0.3rem;
        flex-direction: column;
        align-items: stretch;
        width: 100%;
    }}
    .ts-topbar-item {{
        flex-direction: row;
        justify-content: space-between;
        align-items: baseline;
        width: 100%;
    }}
    .ts-topbar-logo {{ font-size: 0.62rem !important; }}
    .ts-topbar-label {{ font-size: 0.6rem !important; }}
    .ts-topbar-value {{ font-size: 0.85rem !important; }}
    .ts-topbar-pnl-amount {{ display: inline; }}
    .ts-topbar-pnl-pct {{
        display: inline;
        margin-left: 0.3rem;
        font-size: 0.7rem !important;
        font-weight: 500;
    }}
    body:has([data-testid="stExpandSidebarButton"]) .ts-topbar-left {{ margin-left: 1.8rem; }}
    /* Titres de page hors barre de valeur (connexion, onboarding premier
       portefeuille, accueil Tutoriel) : mêmes st.title en tout début de
       page, qui se superposaient au bouton natif de réouverture du panneau
       latéral (stExpandSidebarButton, flottant en haut à gauche) quand
       celui-ci est replié — repéré au test réel à 390px. */
    body:has([data-testid="stExpandSidebarButton"]) h1 {{ margin-left: 1.8rem !important; }}

    /* Grille de cartes News (onglet News, hors du scope .st-key-ts_light) : 1
       colonne au lieu de 3, quel que soit le comportement natif exact de
       Streamlit sur les st.columns (non garanti pour un nombre fixe). */
    [class*="st-key-ts_news_grid"] [data-testid="stHorizontalBlock"] {{
        flex-direction: column !important;
    }}
    [class*="st-key-ts_news_grid"] [data-testid="stColumn"] {{
        width: 100% !important;
        flex: none !important;
    }}
    [class*="st-key-ts_card_news_"] {{
        padding: 0.7rem 0.85rem !important;
    }}
}}
"""


def inject() -> None:
    st.markdown(f"<style>{_CSS}</style>", unsafe_allow_html=True)


_LIGHT_CSS = f"""
.st-key-ts_light {{
    /* Transparent (pas LIGHT_PAGE) : laisse transparaître le dégradé de la
       page plutôt que de poser un à-plat rectangulaire dessus, ce qui
       casserait l'effet de dégradé continu sur les onglets Portefeuille et
       Trading (voir le prompt "Fond dégradé sombre"). */
    background: transparent !important;
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
/* Même correctif de décalage au clic/focus que dans _CSS (voir plus haut) :
   border/box-shadow figés sur tous les états pour que la boîte du bouton ne
   change jamais de taille. */
.st-key-ts_light .stButton > button:active, .st-key-ts_light .stFormSubmitButton > button:active,
.st-key-ts_light .stButton > button:focus, .st-key-ts_light .stFormSubmitButton > button:focus {{
    border: 1px solid {LIGHT_BLUE} !important;
    box-shadow: none !important;
    outline: none !important;
    transform: none !important;
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
   garde le style par défaut de Streamlit (base="dark" dans .streamlit/
   config.toml, voir CLAUDE.md), déjà cohérent avec le thème sombre. */
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
   du formulaire d'ordre, ET démarquée du reste de la page (elle s'y fondait
   auparavant, aucun fond/contour propre, seul l'input avait une bordure très
   proche de celle du fond). Fond légèrement rehaussé (PANEL, cohérent avec
   les autres "cartes" de l'app) + coin arrondis + une pointe de padding pour
   que la zone se lise comme un vrai bloc d'action, pas un simple champ posé
   sur la page. */
.st-key-ts_card_search {{
    background: {LIGHT_SURFACE};
    border: 1px solid {LIGHT_BORDER};
    border-radius: 12px;
    padding: 1rem 1.1rem !important;
}}
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

/* Récapitulatif d'ordre (Coût total / Marge requise / Liquidation estimée,
   voir _render_order_summary) : 3 st.metric côte à côte, désormais dans le
   panneau d'ordre étroit du layout Hyperliquid (colonne de droite, voir
   ts_trading_layout_row) — la taille par défaut des métriques (pensée pour
   toute la largeur de page) débordait et rendait les chiffres illisibles
   dans un tiers de colonne. Sélecteur plus spécifique que la règle générale
   ci-dessus (et que celle du media query mobile plus bas) pour l'emporter
   dans les deux cas : le panneau reste étroit sur mobile aussi (empilé en
   pleine largeur, mais avec 3 métriques toujours côte à côte). */
.st-key-ts_light [class*="st-key-ts_card_order_summary"] [data-testid="stMetricValue"] {{
    font-size: 0.95rem !important;
    white-space: normal !important;
    overflow-wrap: break-word !important;
}}
.st-key-ts_light [class*="st-key-ts_card_order_summary"] [data-testid="stMetricLabel"] {{
    font-size: 0.62rem !important;
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
    background: rgba(255,255,255,0.05);
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

/* Carnet d'ordre simulé (prompt 20, voir src/orderbook_sim.py et
   ui_trading._render_order_book) : PUREMENT DÉCORATIF, aucune vraie donnée
   de marché — colonne fine entre le graphique et le formulaire d'ordre.
   .ts-ob-row : une ligne de palier (prix/quantité/total cumulé), avec une
   barre de profondeur en arrière-plan (.ts-ob-depth, largeur posée en
   inline style par ligne, proportionnelle au cumulé) — position:relative/
   absolute + z-index pour que le texte reste lisible par-dessus. opacity
   (pas une couleur rgba dédiée) pour l'atténuer à ~50% : plus simple, la
   barre n'a de toute façon aucun contenu texte propre à en pâtir. */
.ts-ob-wrap {{
    display: flex;
    flex-direction: column;
    /* Repère demandé par Edgar (avec une position ouverte affichée, qui fait
       apparaître la section Take Profit/Stop Loss) : le carnet doit couvrir
       verticalement, dans la colonne du formulaire d'ordre, du début de
       "Mode d'exécution" jusqu'à la fin de la légende "Vend automatiquement
       une partie de cette position...". Mesuré au pixel près via Playwright
       sur le site déployé (1920px, position AAPL ouverte) : de y=635 à
       y=1180, soit 545px — le margin-top ci-dessous (.st-key-ts_card_orderbook)
       est calé sur ce même repère. Un compte sans position ouverte n'affiche
       pas cette section (elle disparaît entièrement, voir
       ui_trading._render_tp_sl_section) : la valeur reste fixe dans ce cas,
       purement esthétique comme le reste du carnet. */
    height: 545px;
}}
.ts-ob-side {{
    display: flex;
    flex-direction: column;
    flex: 1 1 0;
    min-height: 0;
}}
.ts-ob-asks {{ justify-content: space-between; }}
.ts-ob-bids {{ justify-content: space-between; }}
.ts-ob-center {{ flex: 0 0 auto; }}
.ts-ob-row {{
    position: relative;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.4rem;
    padding: 0.1rem 0.3rem;
    font-family: {FONT_MONO};
    font-size: 0.66rem;
    font-variant-numeric: tabular-nums;
    overflow: hidden;
    border-radius: 2px;
    white-space: nowrap;
}}
.ts-ob-depth {{
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    z-index: 0;
    opacity: 0.5;
}}
.ts-ob-ask .ts-ob-depth {{ background: {LIGHT_RED}; }}
.ts-ob-bid .ts-ob-depth {{ background: {LIGHT_GREEN}; }}
.ts-ob-price, .ts-ob-qty, .ts-ob-total {{
    position: relative;
    z-index: 1;
    flex: 1;
}}
.ts-ob-qty, .ts-ob-total {{ color: {LIGHT_MUTED}; text-align: right; }}
.ts-ob-price {{ text-align: left; font-weight: 600; }}
.ts-ob-ask .ts-ob-price {{ color: {LIGHT_RED}; }}
.ts-ob-bid .ts-ob-price {{ color: {LIGHT_GREEN}; }}
.ts-ob-center {{
    text-align: center;
    padding: 0.35rem 0;
    margin: 0.15rem 0;
    border-top: 1px solid {LIGHT_BORDER};
    border-bottom: 1px solid {LIGHT_BORDER};
}}
.ts-ob-center-price {{
    font-family: {FONT_MONO};
    font-variant-numeric: tabular-nums;
    font-weight: 700;
    font-size: 0.85rem;
    color: {LIGHT_TEXT};
}}
.ts-ob-center-spread {{
    font-family: {FONT_MONO};
    font-size: 0.65rem;
    color: {LIGHT_MUTED};
    margin-left: 0.4rem;
}}
/* Colonne étroite par construction (voir st.columns dans ui_trading.render)
   — largeur maximale posée ici en filet de sécurité, jamais un large
   tableau qui rivaliserait avec le graphique/formulaire d'ordre. */
/* Décale le carnet vers le bas pour aligner son sommet sur le début de
   "Mode d'exécution" dans le panneau d'ordre (repère demandé par Edgar,
   voir le commentaire de .ts-ob-wrap ci-dessus) plutôt que sur le début du
   graphique comme dans un essai précédent. Mesuré au pixel près sur le
   site déployé (Playwright, 1920px) : la colonne carnet démarre nativement
   à y≈507 (sans margin-top) et "Mode d'exécution" est à y≈635, d'où
   635-507=128px. À revalider si le contenu au-dessus de "Mode d'exécution"
   change un jour (nouvelle ligne dans "Passer un ordre", etc.). */
.st-key-ts_card_orderbook {{ max-width: 230px; margin-top: 128px; }}
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

    /* Cartes d'actifs "compactes" (encadrés d'accueil Trading, résultats de
       recherche, recherches récentes/suggestions — voir ui_trading.py, tout
       table_key préfixé "compact_") : version resserrée de la carte
       ci-dessus, jugée trop grande pour une simple liste de tickers (peu de
       colonnes, pas de raison d'occuper autant de hauteur qu'une ligne de
       Positions/Historique, plus riches en colonnes). */
    .st-key-ts_light [class*="st-key-tslight_table_compact_"] [data-testid="stHorizontalBlock"] {{
        padding: 0.35rem 0.6rem !important;
        margin-bottom: 0.3rem !important;
        border-radius: 6px !important;
        gap: 0.15rem !important;
    }}

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

    /* Graphique + récapitulatif des positions (courbe de performance,
       Portefeuille) : 1 colonne au lieu de 2 — le graphique garde toute la
       largeur sur mobile, la colonne recap (pensée desktop, pour ne plus que
       le graphique occupe 100% de la largeur) passe juste en dessous. */
    .st-key-ts_light [class*="st-key-ts_portfolio_chart_row"] [data-testid="stHorizontalBlock"] {{
        flex-direction: column !important;
    }}
    .st-key-ts_light [class*="st-key-ts_portfolio_chart_row"] [data-testid="stColumn"] {{
        width: 100% !important;
        flex: none !important;
    }}

    /* Fiche Trading (layout Hyperliquid, voir ui_trading.py) : la disposition
       2 colonnes (graphique | panneau d'ordre) ne concerne que le desktop —
       même principe que ts_portfolio_chart_row ci-dessus. Le graphique est
       rendu en premier dans le code (colonne de gauche), il reste donc
       naturellement en haut une fois empilé, panneau d'ordre en dessous. */
    .st-key-ts_light [class*="st-key-ts_trading_layout_row"] [data-testid="stHorizontalBlock"] {{
        flex-direction: column !important;
    }}
    .st-key-ts_light [class*="st-key-ts_trading_layout_row"] [data-testid="stColumn"] {{
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

    /* Sélecteur de période du graphique Portefeuille (1J/1S/.../Tout) : même
       traitement "une seule ligne défilable au doigt" que chart_period_radio
       ci-dessus (fiche Trading) — jusqu'ici seul ce dernier l'avait reçu,
       ts_period_pills passait à la ligne pastille par pastille, empilant
       9 lignes de boutons au-dessus du graphique (repéré au test réel). */
    /* Sélecteur au même "poids" que la règle .st-key-ts_portfolio_chart_row
       [data-testid="stHorizontalBlock"] ci-dessus (3 sélecteurs) : ts_period_pills
       EST lui-même un stHorizontalBlock (st.container(horizontal=True)) ET un
       descendant de ts_portfolio_chart_row (imbriqué dans sa colonne de
       gauche) — il se faisait donc lui aussi repasser en flex-direction:
       column par cette règle plus générale, malgré flex-wrap:nowrap posé
       ci-dessous (nowrap ne veut rien dire une fois l'axe principal devenu
       vertical, les pastilles continuaient de s'empiler une par ligne). */
    .st-key-ts_light [class*="st-key-ts_portfolio_chart_row"] .st-key-ts_period_pills {{
        flex-direction: row !important;
    }}
    .st-key-ts_light .st-key-ts_period_pills {{
        flex-wrap: nowrap !important;
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch;
    }}
    .st-key-ts_light .st-key-ts_period_pills > * {{ flex-shrink: 0 !important; }}

    /* Ancien blocage total des interactions Plotly sur mobile (pointer-events:
       none sur .nsewdrag, la couche transparente que Plotly pose au-dessus du
       tracé) retiré au prompt 18 : il neutralisait le zoom/pan par glisser ET
       le double-clic de réinitialisation d'un seul coup, alors que seul le
       premier devait rester désactivé (le double-clic était utile et a été
       redemandé). Le zoom/pan par glisser reste désactivé via dragmode=False
       (voir theme.plotly_layout, prompt 18) — réglage Python indépendant du
       double-clic côté Plotly.js, donc applicable sans ce contournement CSS
       ni effet de bord sur le double-clic. */
}}

/* Carnet d'ordre simulé (prompt 20) masqué en dessous de 1100px — PAS
   seulement sur mobile (max-width:640px ci-dessus, où le graphique et le
   formulaire d'ordre s'empilent déjà en 1 colonne) mais aussi sur les
   largeurs intermédiaires (tablette, petit laptop) où graphique + formulaire
   restent côte à côte mais où une 3e colonne les compresserait trop.
   Consigne du prompt : "si l'espace est insuffisant, le masquer plutôt que
   de compresser les deux autres éléments" — jamais l'inverse. `display:
   none` (jamais `display: contents`, qui a un lourd historique de bugs sur
   Safari/iOS — voir le prompt 19 et son annulation complète suite à un
   écran bleu en production) : propriété CSS parmi les plus anciennes et les
   mieux supportées, aucun risque de compatibilité connu. `:has()` cible la
   colonne (stColumn) qui contient la carte du carnet, sans avoir besoin
   d'une clé Streamlit dédiée sur la colonne elle-même (st.columns() n'en
   permet pas) — même technique déjà utilisée pour stExpandSidebarButton. */
@media (max-width: 1099px) {{
    [data-testid="stColumn"]:has(.st-key-ts_card_orderbook) {{
        display: none !important;
    }}
}}

/* Pop-up de confirmation d'ordre (prompt 21, point 1) : remplace l'ancien
   st.toast (petite notification en coin, jugée pas assez visible par les
   testeurs) par une bannière verte bien visible. VOLONTAIREMENT PAS
   `position: fixed` : premier essai testé au pixel près via Playwright sur
   le site déployé — l'app tourne dans un iframe Streamlit Cloud SANS son
   propre scroll interne (c'est la page EXTÉRIEURE qui défile, l'iframe fait
   toute la hauteur du contenu), donc `fixed` s'ancre au sommet de tout le
   contenu plutôt qu'au viewport réellement visible : dès que la page est
   scrollée, le pop-up sort du champ de vision, exactement l'inverse de
   l'objectif. Rendu à la place en flux normal, tout en haut de
   `_render_order_panel` (ui_trading.py) — c.-à-d. exactement la carte que
   l'utilisateur regarde déjà juste après avoir cliqué "Valider l'ordre"/
   "Créer le palier", donc visible sans avoir besoin de flotter par-dessus
   le reste. Fond vert + texte sombre (mêmes GREEN/BADGE_DARK_TEXT que les
   badges de catégorie clairs, cohérent avec la charte). Disparition
   automatique en pure CSS (@keyframes), sans JavaScript ; la durée totale
   (fade in -> maintien -> fade out) est pilotée par `animation-duration`
   posé en style inline par theme.render_order_confirmation_popup (secondes
   passées en Python, pas dupliquées ici). */
.ts-order-confirm-popup {{
    background: {GREEN};
    color: {BADGE_DARK_TEXT};
    padding: 0.75rem 1.4rem;
    border-radius: 10px;
    font-family: {FONT_SANS};
    font-weight: 600;
    font-size: 0.95rem;
    box-shadow: 0 6px 24px rgba(0,0,0,0.35);
    margin-bottom: 0.85rem;
    animation-name: ts-order-confirm-fade;
    animation-timing-function: ease;
    animation-fill-mode: forwards;
}}
@keyframes ts-order-confirm-fade {{
    0% {{ opacity: 0; transform: translateY(-8px); }}
    8% {{ opacity: 1; transform: translateY(0); }}
    88% {{ opacity: 1; }}
    100% {{ opacity: 0; transform: translateY(-8px); }}
}}
@media (max-width: 640px) {{
    .ts-order-confirm-popup {{ font-size: 0.85rem; padding: 0.6rem 1rem; }}
}}
"""


def inject_light() -> None:
    """Injecte le CSS scopé sous .st-key-ts_light (Portefeuille/Trading, voir
    le commentaire en tête de _LIGHT_CSS) — nom historique de l'époque où ce
    thème était clair pendant que le reste de l'appli restait sombre ; gardé
    tel quel plutôt que renommé à chaque changement de direction esthétique
    (même logique que les constantes BG/PANEL/..., voir plus haut). N'a
    aucun effet tant que le
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


def render_order_confirmation_popup(message: str, seconds: int = 5) -> None:
    """Confirmation d'ordre en pop-up visible (prompt 21, point 1 —
    régression : le message vert avait disparu, cassé par un
    `st.success()` immédiatement suivi d'un `st.rerun()`, voir
    `_render_tp_sl_section` dans ui_trading.py avant ce correctif).

    Remplace aussi l'ancien `st.toast` (petite notification en coin, jugée
    pas assez visible) utilisé pour les ordres marché/limite : un seul
    mécanisme désormais pour les 4 actions concernées (achat/vente/short,
    ordre à cours limité, création de palier TP/SL).

    Le message doit survivre au `st.rerun()` qui suit l'action (sinon il
    disparaît quasi instantanément, comme un `st.success()` classique) :
    l'appelant le dépose dans `st.session_state["_order_confirmation_message"]`
    AVANT son rerun, et c'est `_render_order_panel` (ui_trading.py) qui le
    récupère (`.pop(...)`, donc affiché une seule fois) tout en haut de son
    prochain rendu et appelle cette fonction — jamais appelée directement au
    moment de l'action elle-même.
    """
    st.markdown(
        f'<div class="ts-order-confirm-popup" style="animation-duration:{seconds}s">'
        f'✓ {html_lib.escape(message)}</div>',
        unsafe_allow_html=True,
    )


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
            Mouvement du jour sur tes positions : {" &nbsp;·&nbsp; ".join(parts)}
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
    donnée principale).

    dragmode=False (prompt 18) : désactive le zoom/pan par clic-glisser (et
    tap-glisser sur mobile) — le sélecteur de période reste le moyen normal
    de changer l'échelle affichée. Sans effet sur le double-clic (reset du
    zoom), qui reste actif indépendamment de dragmode côté Plotly.js — c'est
    justement ce qui permet de désactiver l'un sans l'autre, contrairement à
    l'ancien blocage CSS (pointer-events sur .nsewdrag) qui neutralisait les
    deux à la fois sur mobile."""
    layout = dict(
        height=380,
        margin=dict(l=10, r=10, t=10, b=10),
        dragmode=False,
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
# reset/téléchargement restent disponibles via la modebar (desktop) ou le
# double-clic (reset, desktop ET mobile — voir plotly_layout ci-dessous pour
# dragmode=False, qui désactive le zoom/pan par glisser sans toucher au
# double-clic, indépendant de dragmode côté Plotly.js).
# scrollZoom=False (molette/pinch) : repris ici depuis prompt 2/5 (Trading
# seul à l'origine) et étendu à tous les graphiques Plotly de l'app au
# prompt 18, pour que le graphique Portefeuille reste lui aussi sans zoom
# une fois le blocage CSS mobile (pointer-events sur .nsewdrag, qui cassait
# aussi le double-clic) retiré — voir _LIGHT_CSS.
PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "toggleSpikelines"],
    "scrollZoom": False,
}

# Affiché sous chaque graphique (voir ui_portfolio.py/ui_trading.py) :
# documente un comportement déjà en place (zoom par défaut resserré, double-
# clic pour le réinitialiser) mais jamais signalé à l'utilisateur.
PLOTLY_ZOOM_HINT = "Double-clique sur le graphique pour réinitialiser le zoom."

# Graphique de prix de l'onglet Trading (prompt 24) : zoom molette + glisser
# ACTIF en plein écran seulement. Le plein écran est celui, natif, de
# Streamlit : sa config Plotly ne peut pas différer entre normal et plein
# écran, et le CSS ne peut pas couper le zoom sans couper aussi le survol (les
# deux passent par la même couche .nsewdrag). Le graphique est donc
# configuré zoomable (scrollZoom + dragmode="zoom") et ce petit script,
# actif seulement sur le conteneur `TRADING_CHART_KEY`, bloque en phase de
# capture la molette et le début de glisser (souris ET tactile) tant que le
# cadre plein écran de Streamlit n'est pas ouvert (détecté via son bouton
# "Close fullscreen"). Survol et double-clic (reset) ne sont pas touchés.
# Vérifié Playwright/Chromium : desktop (normal/plein écran/retour) et
# balayage tactile émulé (le défilement de la page reste possible au doigt
# sur le graphique) ; pas testé sur un vrai téléphone.
TRADING_CHART_KEY = "ts_trading_chart"
PLOTLY_FULLSCREEN_ZOOM_HINT = (
    "Zoom (molette + sélection à la souris) disponible en plein écran "
    "— survole le graphique puis clique sur l'icône plein écran. "
    "Double-clique pour réinitialiser le zoom."
)
_FULLSCREEN_ZOOM_GATE_JS = '(function () {\n  if (window.__tsZoomGate) return;\n  window.__tsZoomGate = true;\n  var SEL = \'.st-key-ts_trading_chart\';\n  function gated(e) {\n    var t = e.target;\n    if (!t || !t.closest) return false;\n    var zone = t.closest(SEL);\n    if (!zone) return false;\n    var frame = zone.querySelector(\'[data-testid="stFullScreenFrame"]\');\n    return !(frame && frame.querySelector(\'button[aria-label="Close fullscreen"]\'));\n  }\n  var dragging = false;\n  window.addEventListener(\'wheel\', function (e) { if (gated(e)) e.stopImmediatePropagation(); }, true);\n  window.addEventListener(\'mousedown\', function (e) { dragging = gated(e); }, true);\n  window.addEventListener(\'touchstart\', function (e) { if (gated(e)) { dragging = true; e.stopImmediatePropagation(); } }, true);\n  window.addEventListener(\'mouseup\', function () { dragging = false; }, true);\n  window.addEventListener(\'touchend\', function () { dragging = false; }, true);\n  window.addEventListener(\'mousemove\', function (e) { if (dragging) e.stopImmediatePropagation(); }, true);\n  window.addEventListener(\'touchmove\', function (e) { if (dragging) e.stopImmediatePropagation(); }, true);\n})();\n'


def render_fullscreen_zoom_gate() -> None:
    """Installe (une seule fois par page, garde `window.__tsZoomGate`) le
    script décrit ci-dessus."""
    st.html(f"<script>{_FULLSCREEN_ZOOM_GATE_JS}</script>", unsafe_allow_javascript=True)


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
    """Équivalent de _cell_content pour le scope .st-key-ts_light (vert/rouge
    adaptés au contraste sur le fond de ce thème)."""
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
    """Équivalent de render_table pour le scope .st-key-ts_light (Portefeuille/Trading) :
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
    detail: "Callable[[dict], None] | None" = None, row_key: str = "ticker",
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
    `row_key` : clé de `row` utilisée pour générer la clé du widget expander
    de chaque ligne — "ticker" par défaut (une position par ticker, jamais de
    doublon), mais doit être une clé réellement unique par ligne pour une
    liste où le même ticker peut apparaître plusieurs fois (ex : historique
    des trades), sous peine de collision de clé de widget Streamlit.
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
            # Gabarit compacté sur une seule ligne (pas de retour à la ligne
            # entre une balise et son contenu) : avec le HTML indenté sur
            # plusieurs lignes utilisé auparavant, un champ "secondary" (ou
            # "primary") vide laissait une ligne ne contenant QUE de
            # l'indentation — que le moteur markdown de Streamlit interprète
            # alors comme un bloc de code indenté, coupant le rendu HTML en
            # plein milieu (fermetures de balises affichées en texte brut
            # dans un encart noir, repéré au test réel sur les listes qui
            # n'ont pas de valeur secondaire, ex. recherches récentes/
            # suggestions, sans prix à afficher).
            st.markdown(
                f'<div class="ts-compact-row">'
                f'<div class="ts-compact-left">'
                f'<span class="ts-compact-badge" style="background:{bg};color:{fg}">'
                f'{html_lib.escape(row["ticker"])}</span>'
                f'<div class="ts-compact-name-wrap">'
                f'<div class="ts-compact-name">{html_lib.escape(row["name"])}{side_html}</div>'
                f'</div></div>'
                f'<div class="ts-compact-right">'
                f'<div class="ts-compact-primary">{html_lib.escape(row.get("primary", ""))}</div>'
                f'<div class="ts-compact-secondary" style="color:{secondary_color}">'
                f'{html_lib.escape(str(row.get("secondary", "")))}</div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
            if detail is not None:
                with st.container(key=f"tslight_detail_{table_key}_{_safe_key_part(row[row_key])}"):
                    with st.expander("Détails"):
                        detail(row)
