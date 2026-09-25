"""Écrans de navigation de l'onglet Trading : accueil (cartes de
catégories), zones (Actions), devises (Forex), maturités (Obligations),
familles (Matières premières), fil d'Ariane. AUCUNE requête Yahoo/Kraken :
uniquement la configuration statique (asset_universe, trading_nav_config) et
une lecture légère en base pour la disponibilité (daily_snapshot).

État de navigation : st.session_state[NAV_KEY] = {"category", "view",
"zone", "group"} avec view parmi "zones" | "currencies" | "maturities" |
"families" | "list" (absent = accueil). Chaque changement d'écran passe par un vrai st.button puis
st.rerun() : jamais de lien, la session (et la connexion) est conservée.
"""

import html

import streamlit as st

from . import asset_universe, daily_snapshot, trading_nav_config as cfg, ui_cards, valuation

NAV_KEY = "trading_category"

CATEGORY_DESCRIPTIONS = {
    asset_universe.ACTIONS: "Grandes entreprises d'Europe, d'Amérique et d'Asie.",
    asset_universe.CRYPTO: "Bitcoin, Ethereum et les principales cryptomonnaies.",
    asset_universe.BONDS: "ETF obligataires : Trésor américain, entreprises, inflation.",
    asset_universe.FOREX: "Paires de devises majeures et croisées, par devise.",
    asset_universe.COMMODITIES: "Métaux, énergie et produits agricoles.",
}

# Catégories qui passent par un écran intermédiaire avant la liste.
_FIRST_VIEW = {asset_universe.ACTIONS: "zones", asset_universe.FOREX: "currencies",
               asset_universe.BONDS: "maturities", asset_universe.COMMODITIES: "families"}


def current() -> dict | None:
    return st.session_state.get(NAV_KEY)


def go(category: str | None = None, view: str = "list", zone: str | None = None,
       country: str | None = None, group: str | None = None) -> None:
    """Change d'écran (category=None : accueil) et relance la page.
    `group` : regroupement propre à la catégorie (devise pour le Forex,
    maturité pour les Obligations)."""
    st.session_state.selected_ticker = None
    if category is None:
        st.session_state.pop(NAV_KEY, None)
    else:
        st.session_state[NAV_KEY] = {"category": category, "view": view, "zone": zone, "country": country,
                                     "group": group}
    st.rerun()


def group_label(category: str, group: str | None) -> str | None:
    if not group:
        return None
    if category == asset_universe.FOREX and group in cfg.FOREX_CURRENCIES:
        return f"{cfg.FOREX_CURRENCIES[group]['nom']} ({group})"
    if category == asset_universe.BONDS and group in cfg.BOND_GROUPS:
        return cfg.BOND_GROUPS[group]["nom"]
    if category == asset_universe.COMMODITIES and group in asset_universe.COMMODITY_FAMILIES:
        return asset_universe.COMMODITY_FAMILIES[group]["nom"]
    return None


def group_contains(category: str, group: str | None, ticker: str) -> bool:
    """Vrai si `ticker` fait partie du regroupement `group` (ou s'il n'y en a pas)."""
    if not group:
        return True
    if category == asset_universe.FOREX:
        return group in (cfg.pair_currencies(ticker) or ())
    if category == asset_universe.BONDS:
        return ticker in cfg.BOND_GROUPS.get(group, {}).get("tickers", [])
    if category == asset_universe.COMMODITIES:
        return ticker in asset_universe.COMMODITY_FAMILIES.get(group, {}).get("tickers", [])
    return True


def open_category(category: str) -> None:
    go(category, _FIRST_VIEW.get(category, "list"))


# -- Fil d'Ariane --------------------------------------------------------------

def _parts_for(nav: dict | None) -> list[tuple[str, dict | str]]:
    """Étapes cliquables menant à l'écran `nav` (lui compris, en dernier)."""
    parts: list[tuple[str, dict | str]] = [("Trading", "home")]
    if not nav:
        return parts
    category = nav["category"]
    label = asset_universe.CATEGORY_LABELS.get(category, category)
    first_view = _FIRST_VIEW.get(category, "list")
    parts.append((label, {"category": category, "view": first_view}))
    if category == asset_universe.ACTIONS and nav.get("zone") in cfg.ZONES and nav.get("view") == "list":
        zone = nav["zone"]
        parts.append((cfg.ZONES[zone]["nom"], {"category": category, "view": "list", "zone": zone}))
    label = group_label(category, nav.get("group"))
    if label and nav.get("view") == "list":
        parts.append((label, {"category": category, "view": "list", "group": nav["group"]}))
    return parts


def render_breadcrumb(nav: dict | None, current_label: str | None = None) -> None:
    """Fil d'Ariane de l'écran `nav` ; `current_label` ajoute un dernier
    niveau non cliquable (ex. nom de l'actif sur sa fiche)."""
    parts = _parts_for(nav)
    targets = {}
    crumbs = []
    for i, (label, target) in enumerate(parts):
        is_last = current_label is None and i == len(parts) - 1
        target_id = None if is_last else f"crumb{i}"
        targets[target_id] = target
        crumbs.append((label, target_id))
    if current_label is not None:
        crumbs.append((current_label, None))
    clicked = ui_cards.breadcrumb(crumbs)
    if clicked:
        target = targets[clicked]
        if target == "home":
            go(None)
        go(target["category"], target["view"], target.get("zone"), group=target.get("group"))


def asset_category(ticker: str, quote_type: str = "") -> str:
    """Classe d'actif affichée sur la fiche, sans aucune requête : univers de
    l'app d'abord, puis le type renvoyé par la cotation déjà obtenue (en
    session), puis la syntaxe du ticker. Le type n'est jamais connu après
    une navigation (theme.go_to_trading le remet à vide) : sans les deux
    premières étapes, une action classique s'affichait « Autres »."""
    known = asset_universe.category_of(ticker)
    if known:
        return known
    if not quote_type and st.session_state.get("trading_price_ticker") == ticker:
        quote_type = st.session_state.get("trading_quote_type") or ""
    return valuation.category_for(quote_type, ticker)


def render_asset_breadcrumb(ticker: str, name: str | None, quote_type: str = "") -> None:
    """Fil d'Ariane de la fiche actif : chemin de navigation mémorisé s'il
    correspond à la catégorie de l'actif, sinon la catégorie de l'actif."""
    nav = current()
    category = asset_category(ticker, quote_type)
    zone = asset_universe.ASSET_PLACES.get(ticker, (None, None))[0]
    if (not nav or nav.get("category") != category or nav.get("view") != "list"
            or not group_contains(category, nav.get("group"), ticker)
            or (category == asset_universe.ACTIONS and nav.get("zone") != zone)):
        nav = ({"category": category, "view": _FIRST_VIEW.get(category, "list")}
               if category in asset_universe.CATEGORY_LABELS else None)
    render_breadcrumb(nav, current_label=name or ticker)


# -- Accueil -------------------------------------------------------------------

def render_home_header() -> None:
    ui_cards.page_header("Trading", "Explorer les marchés",
                         "Choisis une catégorie pour parcourir les actifs, ou recherche directement un nom ou un ticker.")


def render_home_categories() -> None:
    with st.container(key="ts_card_home_categories"):
        cols = st.columns(len(asset_universe.CATEGORIES))
        for col, category in zip(cols, asset_universe.CATEGORIES):
            label = asset_universe.CATEGORY_LABELS[category]
            body = ui_cards.category_body(category, label, CATEGORY_DESCRIPTIONS[category],
                                          len(asset_universe.ASSETS_BY_CATEGORY[category]))
            with col:
                if ui_cards.nav_card(f"cat_{category}", body, size="category", aria_label=f"Explorer {label}"):
                    open_category(category)


# -- Actions : zones ----------------------------------------------------

def _indices_html(indices: list[dict]) -> str:
    label = "Indice de référence" if len(indices) == 1 else "Indices de référence"
    rows = "".join(
        f'<div class="tsnav-index-row"><span>{html.escape(i["nom"])}</span>'
        f'{ui_cards.perf_pill(i.get("perf"), i.get("decimales", 1), i.get("approx", False), cfg.ANNEE_PERF)}'
        + (f'<span class="tsnav-index-note">{html.escape(i["note"])}</span>' if i.get("note") else "")
        + "</div>"
        for i in indices
    )
    return f'<div class="tsnav-index-label">{label}</div>{rows}'


def _cta(available: bool, text: str = "Explorer →") -> str:
    return f'<div class="tsnav-cta">{html.escape(text)}</div>' if available else ui_cards.soon_pill()


def _zone_available(places, zone: str) -> bool:
    return bool(places) and any(z == zone for z, _ in places)


def _outline(key: str | None) -> dict | None:
    from .geo_outlines import GEO_OUTLINES
    return GEO_OUTLINES.get(key) if key else None


def render_zones() -> None:
    render_breadcrumb(current())
    ui_cards.page_header("Actions", "Choisir une zone",
                         "Chaque zone regroupe ses 30 plus grandes capitalisations, tous pays confondus.")
    places = daily_snapshot.available_places(asset_universe.ACTIONS)
    cols = st.columns(len(cfg.ZONES))
    for col, (zone_key, zone) in zip(cols, cfg.ZONES.items()):
        available = _zone_available(places, zone_key)
        countries = " · ".join(asset_universe.COUNTRY_NAMES[c] for c in asset_universe.countries_of_zone(zone_key))
        body = (f'<div class="tsnav-name">{html.escape(zone["nom"])}</div>'
                f'<div class="tsnav-desc">{html.escape(zone["description"])}</div>'
                f'<div class="tsnav-countries">{html.escape(countries)}</div>'
                f'{_indices_html(zone["indices"])}{_cta(available)}')
        with col:
            if ui_cards.nav_card(f"zone_{zone_key}", body, size="large", available=available,
                                 aria_label=f"Explorer la zone {zone['nom']}", outline=_outline(zone["contour"])):
                go(asset_universe.ACTIONS, "list", zone_key)
    ui_cards.footnote(cfg.PERF_FOOTNOTE)


# -- Forex : devises ------------------------------------------------------------------

def _available_tickers(category: str) -> set[str] | None:
    """Tickers présents dans la table des prix indicatifs (disponibilité :
    même règle que les zones et pays). None si la base est indisponible."""
    rows = daily_snapshot.list_assets(category)
    return None if rows is None else {r["ticker"] for r in rows}


def render_currencies() -> None:
    render_breadcrumb(current())
    ui_cards.page_header("Forex / Monnaies", "Choisir une devise",
                         "Chaque carte regroupe les paires qui contiennent cette devise.")
    pairs = [t for t, _ in asset_universe.ASSETS_BY_CATEGORY[asset_universe.FOREX]]
    names = dict(asset_universe.ASSETS_BY_CATEGORY[asset_universe.FOREX])
    available = _available_tickers(asset_universe.FOREX)
    cards = []
    for code, currency in cfg.FOREX_CURRENCIES.items():
        with_code = [t for t in pairs if code in (cfg.pair_currencies(t) or ())]
        if with_code:  # une carte n'apparaît que si elle a au moins une paire
            cards.append((code, currency, with_code))
    per_row = 4
    for start in range(0, len(cards), per_row):
        cols = st.columns(per_row)
        for col, (code, currency, with_code) in zip(cols, cards[start:start + per_row]):
            ok = bool(available) and any(t in available for t in with_code)
            pair_names = " · ".join(names.get(t, t) for t in with_code)
            body = (f'<div class="tsnav-name">{html.escape(currency["nom"])} '
                    f'<span class="tsnav-code">{code}</span></div>'
                    f'<div class="tsnav-desc">{html.escape(currency["banque_centrale"])}</div>'
                    f'<div class="tsnav-index-label">Paires</div>'
                    f'<div class="tsnav-countries">{html.escape(pair_names)}</div>{_cta(ok)}')
            with col:
                if ui_cards.nav_card(f"ccy_{code}", body, size="country", available=ok,
                                     aria_label=f"Explorer les paires en {currency['nom']}",
                                     outline=_outline(currency["contour"])):
                    go(asset_universe.FOREX, "list", group=code)


# -- Obligations : maturités --------------------------------------------------------

# Courbe des taux STYLISÉE (tracé générique, aucune donnée réelle) posée en
# fond des cartes de maturité, avec un point à l'abscisse de la maturité de
# la carte (aucun point pour « Diversifiés », qui couvre toute la courbe).
_CURVE_PATH = "M0 262 C 60 170, 140 125, 230 104 S 360 84, 400 80"
_CURVE_POINTS = {"court-terme": (40, 208), "moyen-terme": (150, 122), "long-terme": (330, 88)}


def yield_curve_outline(group: str) -> dict:
    d = _CURVE_PATH
    point = _CURVE_POINTS.get(group)
    if point:
        x, y = point
        d += f" M{x - 7} {y} a7 7 0 1 0 14 0 a7 7 0 1 0 -14 0"
    return {"w": 400, "h": 280, "d": d}


def render_maturities() -> None:
    render_breadcrumb(current())
    ui_cards.page_header("Obligations", "Choisir une maturité",
                         "Trésor américain par maturité, puis fonds diversifiés, entreprises, inflation et international.")
    names = dict(asset_universe.ASSETS_BY_CATEGORY[asset_universe.BONDS])
    available = _available_tickers(asset_universe.BONDS)
    groups = list(cfg.BOND_GROUPS.items())
    cols = st.columns(len(groups))
    for col, (key, group) in zip(cols, groups):
        ok = bool(available) and any(t in available for t in group["tickers"])
        funds = " · ".join(f"{t} ({names.get(t, t)})" for t in group["tickers"])
        body = (f'<div class="tsnav-name">{html.escape(group["nom"])}</div>'
                f'<div class="tsnav-desc">{html.escape(group["description"])}</div>'
                f'<div class="tsnav-index-label">Fonds</div>'
                f'<div class="tsnav-countries">{html.escape(funds)}</div>{_cta(ok)}')
        with col:
            if ui_cards.nav_card(f"bond_{key}", body, size="country", available=ok,
                                 aria_label=f"Explorer les obligations {group['nom'].lower()}",
                                 outline=yield_curve_outline(key)):
                go(asset_universe.BONDS, "list", group=key)
    ui_cards.footnote("Fond de carte : courbe des taux stylisée, à titre d'illustration (aucune donnée réelle).")


# -- Matières premières : familles -------------------------------------------------

def render_families() -> None:
    render_breadcrumb(current())
    ui_cards.page_header("Matières premières", "Choisir une famille",
                         "Contrats à terme les plus échangés, regroupés par famille.")
    names = dict(asset_universe.ASSETS_BY_CATEGORY[asset_universe.COMMODITIES])
    available = _available_tickers(asset_universe.COMMODITIES)
    families = list(asset_universe.COMMODITY_FAMILIES.items())
    cols = st.columns(len(families))
    for col, (key, family) in zip(cols, families):
        ok = bool(available) and any(t in available for t in family["tickers"])
        body = (f'<div class="tsnav-name">{html.escape(family["nom"])}</div>'
                f'<div class="tsnav-desc">{html.escape(family["description"])}</div>'
                f'<div class="tsnav-index-label">Contrats</div>'
                f'<div class="tsnav-countries">{html.escape(" · ".join(names[t] for t in family["tickers"]))}</div>'
                f'{_cta(ok)}')
        with col:
            if ui_cards.nav_card(f"family_{key}", body, size="country", available=ok,
                                 aria_label=f"Explorer la famille {family['nom']}"):
                go(asset_universe.COMMODITIES, "list", group=key)
