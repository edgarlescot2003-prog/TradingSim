"""Écrans de navigation de l'onglet Trading : accueil (cartes de
catégories), zones et pays (Actions), fil d'Ariane. AUCUNE requête
Yahoo/Kraken : uniquement la configuration statique (trading_nav_config) et
une lecture légère en base pour la disponibilité (daily_snapshot).

État de navigation : st.session_state[NAV_KEY] = {"category", "view",
"zone", "country"} avec view parmi "zones" | "countries" | "list" (absent =
accueil). Chaque changement d'écran passe par un vrai st.button puis
st.rerun() : jamais de lien, la session (et la connexion) est conservée.
"""

import html

import streamlit as st

from . import asset_universe, daily_snapshot, trading_nav_config as cfg, ui_cards, valuation

NAV_KEY = "trading_category"

CATEGORY_DESCRIPTIONS = {
    asset_universe.ACTIONS: "Entreprises cotées, par zone puis par pays.",
    asset_universe.CRYPTO: "Bitcoin, Ethereum et autres cryptomonnaies.",
    asset_universe.BONDS: "ETF d'obligations d'État américaines.",
    asset_universe.FOREX: "Paires de devises majeures.",
    asset_universe.COMMODITIES: "Or, argent, pétrole et gaz naturel.",
}

# Catégories qui passent par un écran intermédiaire avant la liste.
_FIRST_VIEW = {asset_universe.ACTIONS: "zones"}


def current() -> dict | None:
    return st.session_state.get(NAV_KEY)


def go(category: str | None = None, view: str = "list", zone: str | None = None,
       country: str | None = None) -> None:
    """Change d'écran (category=None : accueil) et relance la page."""
    st.session_state.selected_ticker = None
    if category is None:
        st.session_state.pop(NAV_KEY, None)
    else:
        st.session_state[NAV_KEY] = {"category": category, "view": view, "zone": zone, "country": country}
    st.rerun()


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
    if category == asset_universe.ACTIONS and nav.get("zone"):
        zone = nav["zone"]
        parts.append((cfg.ZONES[zone]["nom"], {"category": category, "view": "countries", "zone": zone}))
        if nav.get("view") == "list":
            if nav.get("country"):
                parts.append((cfg.PAYS[nav["country"]]["nom"],
                              {"category": category, "view": "list", "zone": zone, "country": nav["country"]}))
            else:
                parts.append((cfg.WIDE_ZONE_LABELS[zone], {"category": category, "view": "list", "zone": zone}))
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
        go(target["category"], target["view"], target.get("zone"), target.get("country"))


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
    if not nav or nav.get("category") != category or nav.get("view") != "list":
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


# -- Actions : zones puis pays ----------------------------------------------------

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
                         "Les zones sans actif disponible pour l'instant sont marquées « Bientôt ».")
    places = daily_snapshot.available_places(asset_universe.ACTIONS)
    cols = st.columns(len(cfg.ZONES))
    for col, (zone_key, zone) in zip(cols, cfg.ZONES.items()):
        available = _zone_available(places, zone_key)
        countries = " · ".join(cfg.PAYS[c]["nom"] for c in zone["pays"])
        body = (f'<div class="tsnav-name">{html.escape(zone["nom"])}</div>'
                f'<div class="tsnav-desc">{html.escape(zone["description"])}</div>'
                f'<div class="tsnav-countries">{html.escape(countries)}</div>'
                f'{_indices_html(zone["indices"])}{_cta(available)}')
        with col:
            if ui_cards.nav_card(f"zone_{zone_key}", body, size="large", available=available,
                                 aria_label=f"Explorer la zone {zone['nom']}", outline=_outline(zone["contour"])):
                go(asset_universe.ACTIONS, "countries", zone_key)
    ui_cards.footnote(cfg.PERF_FOOTNOTE)


def render_countries(zone_key: str) -> None:
    zone = cfg.ZONES[zone_key]
    render_breadcrumb(current())
    ui_cards.page_header(f"Actions · {zone['nom']}", "Choisir un pays",
                         "Ou parcours toute la zone d'un coup. Les pays sans actif pour l'instant sont marqués « Bientôt ».")
    places = daily_snapshot.available_places(asset_universe.ACTIONS)
    zone_ok = _zone_available(places, zone_key)
    wide_label = cfg.WIDE_ZONE_LABELS[zone_key]
    wide_body = (f'<div class="tsnav-name">{html.escape(wide_label)}</div>'
                 f'<div class="tsnav-desc">{html.escape(zone["description"])}</div>'
                 f'{_indices_html(zone["indices"])}{_cta(zone_ok, "Voir toute la liste →")}')
    if ui_cards.nav_card(f"wide_{zone_key}", wide_body, size="wide", available=zone_ok,
                         aria_label=f"Voir toute la liste : {wide_label}", outline=_outline(zone["contour"])):
        go(asset_universe.ACTIONS, "list", zone_key)

    countries = zone["pays"]
    per_row = 5
    for start in range(0, len(countries), per_row):
        cols = st.columns(per_row)
        for col, country_key in zip(cols, countries[start:start + per_row]):
            country = cfg.PAYS[country_key]
            available = bool(places) and (zone_key, country_key) in places
            body = (f'<div class="tsnav-name">{html.escape(country["nom"])}</div>'
                    f'{_indices_html([country["indice"]])}{_cta(available)}')
            with col:
                if ui_cards.nav_card(f"country_{country_key}", body, size="country", available=available,
                                     aria_label=f"Explorer {country['nom']}", outline=_outline(country["contour"])):
                    go(asset_universe.ACTIONS, "list", zone_key, country_key)
    ui_cards.footnote(cfg.PERF_FOOTNOTE)
