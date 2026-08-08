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

import streamlit as st

BG = "#0A0B0D"
PANEL = "#131417"
BORDER = "#23262B"
TEXT = "#E8E9ED"
MUTED = "#7C8187"
GREEN = "#3DDC97"
RED = "#F65B5B"

FONT_SANS = "'Inter', -apple-system, sans-serif"
FONT_MONO = "'JetBrains Mono', 'Courier New', monospace"

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
}}

html, body, .stApp {{
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

/* Densité : marges et espacements réduits */
.block-container {{
    padding-top: 4.5rem !important;
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

/* Barre de valeur fixe */
.ts-topbar {{
    position: fixed;
    top: 0; left: 0; right: 0;
    z-index: 999999;
    background: var(--ts-panel);
    border-bottom: 1px solid var(--ts-border);
    padding: 0.65rem 1.75rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    row-gap: 0.35rem;
}}
.ts-topbar-left {{ display: flex; align-items: center; gap: 0.6rem; }}
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
    border-color: var(--ts-green) !important;
    color: var(--ts-green) !important;
}}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {{
    background: var(--ts-green) !important;
    border-color: var(--ts-green) !important;
    color: #06110C !important;
}}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {{
    filter: brightness(1.08);
    color: #06110C !important;
}}

/* Champs de saisie */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea,
[data-baseweb="select"] * {{
    font-family: {FONT_SANS} !important;
    border-radius: 3px !important;
}}
[data-testid="stNumberInput"] input {{
    font-family: {FONT_MONO} !important;
    font-variant-numeric: tabular-nums;
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
    color: var(--ts-green) !important;
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
    color: var(--ts-green);
    padding: 0.55rem 0.05rem;
    border-bottom: 2px solid var(--ts-green);
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
    color: var(--ts-green) !important;
    border-color: var(--ts-green) !important;
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
    background: rgba(255,255,255,0.025);
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
    session — et l'authentification — n'est jamais perdue)."""
    st.session_state.selected_ticker = ticker
    st.session_state.selected_name = name or ticker
    st.session_state.selected_quote_type = ""
    st.session_state.search_query = ""
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
