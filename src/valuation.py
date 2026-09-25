"""Calcul de la valeur d'un portefeuille et du P&L de ses positions à partir
des prix courants du marché. Centralisé ici pour être réutilisé à la fois par
l'affichage (onglet Portefeuille) et par l'enregistrement de la courbe de
valeur (record_value_snapshot).
"""

import re
from datetime import datetime

from . import market_data as md

# Regroupement des quoteType Yahoo en grandes catégories d'actif, utilisées
# pour la répartition affichée dans l'onglet Portefeuille et pour la couleur
# des badges de ticker (voir theme.CATEGORY_COLORS). "Autres" couvre le cas
# où le quoteType n'a pas pu être déterminé (prix en repli, cache de prix
# partagé sans ce détail — voir leaderboard.py).
_CATEGORY_LABELS = {
    "EQUITY": "Actions",
    "ETF": "Indices/ETF",
    "INDEX": "Indices/ETF",
    "MUTUALFUND": "Indices/ETF",
    "CRYPTOCURRENCY": "Crypto",
    "CURRENCY": "Forex",
    "FUTURE": "Matières premières",
}

# ETF obligataires (voir asset_universe.ASSETS_BY_CATEGORY) : yfinance les classe en quoteType
# "ETF", indistinguable d'un ETF actions/indices classique par ce seul
# champ — d'où cette liste explicite plutôt qu'une détection automatique.
# Les tickers de rendement d'État bruts (^TNX, ^TYX, ^FVX, ^IRX...) sont
# volontairement absents : ce sont des % de rendement, pas des prix
# négociables, incompatibles avec le système de marge/P&L/liquidation.
BOND_ETF_TICKERS = {
    "TLT", "IEF", "BND", "AGG", "SHY",  # univers d'origine
    # élargissement de l'univers (25/09/2026)
    "SGOV", "IEI", "TLH", "GOVT", "TIP", "LQD", "HYG", "JNK", "BNDX", "EMB", "MUB",
}

# Repli par syntaxe de ticker, utilisé UNIQUEMENT quand quote_type est
# indisponible (ex. st.session_state.selected_quote_type après une
# navigation via theme.go_to_trading, jamais renseigné avec la vraie valeur
# — voir sa docstring) : les suffixes yfinance "=X" (paire de devises) et
# "=F" (contrat future) sont des conventions fiables, tout comme le format
# "XXX-YYY" pour une paire crypto (ex. BTC-USD).
_CRYPTO_TICKER_RE = re.compile(r"^[A-Z0-9]{2,10}-[A-Z]{3,4}$")
_FOREX_TICKER_RE = re.compile(r"^[A-Z]{6}=X$")
_FUTURE_TICKER_RE = re.compile(r"^[A-Z]{1,4}=F$")


UNDEFINED_LABEL = "Non défini"

# Catégories dont le ticker sous-jacent est une VRAIE action/ETF côté
# yfinance (donc un appel à market_data.get_company_profile a du sens) —
# Obligations inclus : ce sont des ETF obligataires (voir BOND_ETF_TICKERS),
# juste reclassés sous ce libellé pour le formulaire d'ordre, mais toujours
# de vrais tickers ETF pour yfinance. Crypto/Forex/Matières premières en
# sont volontairement exclus : leurs tickers (BTC-USD, EURUSD=X, GC=F...)
# n'ont structurellement pas de champ secteur/pays exploitable côté
# yfinance, appeler get_company_profile dessus serait un appel réseau pour
# rien (toujours vide) — Crypto a son propre mapping fixe (FinTech) plus
# bas, le reste tombe directement en "Non défini" sans appel.
_PROFILE_LOOKUP_CATEGORIES = {"Actions", "Indices/ETF", "Obligations"}

# Mapping fixe ticker -> secteur pour les matières premières (voir
# asset_universe.ASSETS_BY_CATEGORY pour la liste complète des tickers proposés) :
# yfinance n'a structurellement aucun champ "sector" exploitable sur un
# contrat future (GC=F, CL=F...), une liste posée à la main est donc la
# seule option, comme pour Crypto -> FinTech ci-dessous. Deux sous-secteurs
# (pas un seul "Matières premières" global) à la demande d'Edgar, pour
# distinguer énergie et métaux précieux dans le camembert. Un futur ticker
# ajouté à COMMODITIES sans entrée ici retombe sur UNDEFINED_LABEL (voir
# sector_for) plutôt que de planter — à compléter ici quand ça arrive.
_COMMODITY_SECTORS = {
    "GC=F": "Métaux précieux", "SI=F": "Métaux précieux", "PL=F": "Métaux précieux", "PA=F": "Métaux précieux",
    "HG=F": "Métaux industriels",
    "CL=F": "Énergie", "BZ=F": "Énergie", "NG=F": "Énergie", "RB=F": "Énergie", "HO=F": "Énergie",
    "ZC=F": "Agriculture", "ZW=F": "Agriculture", "ZS=F": "Agriculture", "KC=F": "Agriculture",
    "SB=F": "Agriculture", "CC=F": "Agriculture",
}


def sector_for(category: str, ticker: str) -> str:
    """Secteur pour le camembert de diversification (prompt 21, point 2).
    Mapping fixe pour Crypto (yfinance n'a pas de notion de secteur pour une
    cryptomonnaie) et pour Matières premières (voir _COMMODITY_SECTORS,
    ajouté après coup : yfinance n'a pas plus de notion de secteur pour un
    contrat future) ; pour Actions/ETF/Obligations, secteur réel via
    market_data.get_company_profile. Double filet de sécurité (demandé
    explicitement) : get_company_profile ne lève déjà jamais de lui-même
    (ticker introuvable, API en panne -> champs None), et le `try/except`
    ici couvre même une défaillance inattendue DANS ce filet — un ticker en
    erreur ou sans champ "sector" exploitable retombe toujours sur
    UNDEFINED_LABEL, jamais une exception qui ferait planter tout le calcul
    du camembert pour une seule position."""
    if category == "Crypto":
        return "FinTech"
    if category == "Matières premières":
        return _COMMODITY_SECTORS.get(ticker.upper(), UNDEFINED_LABEL)
    if category not in _PROFILE_LOOKUP_CATEGORIES:
        return UNDEFINED_LABEL
    try:
        sector = md.get_company_profile(ticker).get("sector")
    except Exception:
        return UNDEFINED_LABEL
    return sector or UNDEFINED_LABEL


def country_for(category: str, ticker: str) -> str:
    """Géographie pour le camembert de diversification (prompt 21, point 2) :
    pays réel (via market_data.get_company_profile) pour Actions/ETF/
    Obligations, "Non défini" pour tout le reste (Crypto, Forex, Matières
    premières n'ont pas de géographie claire). Même double filet de sécurité
    que sector_for ci-dessus."""
    if category not in _PROFILE_LOOKUP_CATEGORIES:
        return UNDEFINED_LABEL
    try:
        country = md.get_company_profile(ticker).get("country")
    except Exception:
        return UNDEFINED_LABEL
    return country or UNDEFINED_LABEL


def category_for(quote_type: str, ticker: str | None = None) -> str:
    ticker = (ticker or "").upper()
    if ticker in BOND_ETF_TICKERS:
        return "Obligations"
    if quote_type:
        return _CATEGORY_LABELS.get(quote_type.upper(), "Autres")
    if ticker:
        if _FOREX_TICKER_RE.match(ticker):
            return "Forex"
        if _FUTURE_TICKER_RE.match(ticker):
            return "Matières premières"
        if _CRYPTO_TICKER_RE.match(ticker):
            return "Crypto"
    return "Autres"


# Perte latente (en fraction de la marge engagée) qui déclenche la liquidation
# automatique d'une position à levier — marge de maintenance à 20%, plus
# prudent que la formule à 100% qui n'était auparavant qu'indicative dans le
# formulaire d'ordre (voir scripts/check_liquidation.py, qui applique ce même
# seuil). Ne s'applique qu'aux positions À LEVIER (leverage > 1, voir
# is_liquidatable ci-dessous) : une position sans levier (marge = notionnel,
# perte plafonnée à 100% de la marge par construction) n'est jamais liquidée
# automatiquement.
MAINTENANCE_LOSS_RATIO = 0.80


# Âge maximal du prix sur lequel un ORDRE MANUEL (au marché, clôture, pose
# d'ordre limite) peut s'appuyer — règle décidée par Edgar : quand la source
# de cotation est en pause (coupe-circuit, voir market_store.py), le site
# reste utilisable sur le dernier prix connu, jusqu'à cet âge. Au-delà,
# l'ordre est refusé avec un message clair. Crypto plus stricte : cote 24/7
# et bouge vite. Ne concerne JAMAIS TP/SL ni liquidation (prix frais
# uniquement, voir market_data.is_fresh_for_automation).
MAX_ORDER_PRICE_AGE_SECONDS = 60 * 60
MAX_ORDER_PRICE_AGE_CRYPTO_SECONDS = 15 * 60


def max_order_price_age_seconds(ticker: str, quote_type: str = "") -> int:
    if category_for(quote_type, ticker) == "Crypto":
        return MAX_ORDER_PRICE_AGE_CRYPTO_SECONDS
    return MAX_ORDER_PRICE_AGE_SECONDS


def order_price_age_error(age_seconds: float | None, ticker: str, quote_type: str = "") -> str | None:
    """Message de refus si le prix est trop ancien pour un ordre manuel,
    sinon None. `age_seconds` = maintenant - heure d'obtention du prix
    auprès de la source live (quote["fetched_at"]), pas l'heure de session."""
    limit = max_order_price_age_seconds(ticker, quote_type)
    if age_seconds is None:
        return "Prix indisponible : impossible d'exécuter cet ordre pour l'instant."
    if age_seconds > limit:
        return (
            f"Prix daté de {age_seconds / 60:.0f} min : au-delà de {limit // 60} min, les ordres sur "
            f"{ticker} sont bloqués. Réessaie quand la cotation sera revenue."
        )
    return None


def unrealized_pnl_eur(position, current_price_eur: float) -> float:
    """P&L latent (€) d'une position au prix courant, formule identique à
    celle utilisée dans position_snapshot ci-dessous (centralisée ici pour
    être réutilisable sans price_cache/appel API, voir scripts/check_liquidation.py)."""
    cost_basis = position.quantity * position.avg_price_eur
    current_exposure_eur = position.quantity * current_price_eur
    if position.side == "long":
        return current_exposure_eur - cost_basis
    return cost_basis - current_exposure_eur


def position_leverage(position) -> float | None:
    """Levier effectif d'une position (notionnel / marge engagée). None si
    aucune marge n'est enregistrée (positions héritées de la Phase 2, short
    sans levier — voir Portfolio.from_dict)."""
    if position.margin_eur <= 1e-9:
        return None
    cost_basis = position.quantity * position.avg_price_eur
    return cost_basis / position.margin_eur


def liquidation_price_eur(entry_price_eur: float, leverage: float | None, side: str) -> float | None:
    """Prix auquel une position ouverte à `entry_price_eur` avec `leverage`
    serait liquidée automatiquement (perte latente = MAINTENANCE_LOSS_RATIO
    de la marge engagée). None si `leverage` est absent ou <= 1 (pas de
    risque de liquidation sans effet de levier)."""
    if not leverage or leverage <= 1 + 1e-9:
        return None
    if side == "long":
        return entry_price_eur * (1 - MAINTENANCE_LOSS_RATIO / leverage)
    return entry_price_eur * (1 + MAINTENANCE_LOSS_RATIO / leverage)


def maintenance_margin_pct(position, current_price_eur: float) -> float | None:
    """% de la marge engagée déjà perdu au prix courant (0 si la position est
    en gain), pour l'indicateur de proximité de liquidation (voir
    ui_trading.py) — la liquidation se déclenche à MAINTENANCE_LOSS_RATIO*100
    (80%). None si la position n'est pas à levier (leverage <= 1)."""
    leverage = position_leverage(position)
    if leverage is None or leverage <= 1 + 1e-9:
        return None
    pnl_eur = unrealized_pnl_eur(position, current_price_eur)
    return max(0.0, -pnl_eur / position.margin_eur * 100)


def is_liquidatable(position, current_price_eur: float) -> bool:
    """Vrai si la perte latente de `position` au prix courant atteint le
    seuil de marge de maintenance (MAINTENANCE_LOSS_RATIO de sa marge
    engagée) — voir scripts/check_liquidation.py, qui clôture alors la
    position automatiquement. Ne s'applique qu'aux positions à levier
    (leverage > 1), jamais à une position sans levier."""
    pct = maintenance_margin_pct(position, current_price_eur)
    return pct is not None and pct >= MAINTENANCE_LOSS_RATIO * 100 - 1e-6


def position_snapshot(position, price_cache: dict[str, float] | None = None) -> dict:
    """Calcule les indicateurs courants d'une position : prix actuel, P&L en
    €/%, levier effectif, contribution à l'équity du portefeuille.

    La contribution à l'équity est `marge engagée + P&L latent` (et non le
    notionnel complet) : avec du levier, seule la marge a réellement été
    prélevée sur le cash (voir le modèle détaillé dans portfolio.py).

    En cas d'échec de récupération du prix (API indisponible, ticker
    retiré...), retombe sur le prix d'achat et le signale via "error".

    `price_cache` (optionnel) : dict partagé entre plusieurs appels, pour
    éviter de refaire le même appel API si le même ticker apparaît dans
    plusieurs portefeuilles (voir leaderboard.py, qui revalue tout le monde
    en direct à chaque consultation du classement).
    """
    cost_basis = position.quantity * position.avg_price_eur

    previous_close_eur = None
    quote_type = ""
    stale_since = None
    if price_cache is not None and position.ticker in price_cache:
        current_price_eur = price_cache[position.ticker]
        error = None
    else:
        try:
            # allow_stale : affichage uniquement (valeur, P&L, topbar) — si la
            # source est en pause, dernier prix connu plutôt que prix d'achat.
            # Jamais utilisé pour une liquidation (voir scripts/check_liquidation.py,
            # qui appelle get_quote sans allow_stale).
            quote = md.get_quote(position.ticker, allow_stale=True)
            current_price_eur = md.convert_to_eur(quote["price"], quote["currency"], allow_stale=True)
            if quote.get("previous_close") is not None:
                previous_close_eur = md.convert_to_eur(quote["previous_close"], quote["currency"], allow_stale=True)
            quote_type = quote.get("quote_type") or ""
            if quote.get("stale"):
                stale_since = quote["fetched_at"]
            error = None
        except md.MarketDataError as e:
            current_price_eur = position.avg_price_eur
            error = str(e)
        if price_cache is not None and error is None:
            price_cache[position.ticker] = current_price_eur

    current_exposure_eur = position.quantity * current_price_eur
    if position.side == "long":
        pnl_eur = current_exposure_eur - cost_basis
    else:
        pnl_eur = cost_basis - current_exposure_eur

    # Retour sur la marge réellement engagée (c'est elle que le levier
    # amplifie) ; repli sur le notionnel pour les positions héritées de la
    # Phase 2 dont la marge enregistrée est nulle (short sans levier).
    pnl_base = position.margin_eur if position.margin_eur > 1e-9 else cost_basis
    pnl_pct = (pnl_eur / pnl_base * 100) if pnl_base else 0.0
    leverage = position_leverage(position)
    liq_price_eur = liquidation_price_eur(position.avg_price_eur, leverage, position.side)
    maint_pct = maintenance_margin_pct(position, current_price_eur)

    # Gain du jour : variation depuis la clôture précédente (pas depuis le
    # prix d'achat). Indisponible (0) si previous_close n'a pas pu être
    # récupéré — prix en repli, ou prix pioché dans price_cache (voir
    # leaderboard.py, qui ne garde que le prix pour revaloriser vite).
    if previous_close_eur:
        previous_exposure_eur = position.quantity * previous_close_eur
        if position.side == "long":
            day_pnl_eur = current_exposure_eur - previous_exposure_eur
        else:
            day_pnl_eur = previous_exposure_eur - current_exposure_eur
        day_pnl_pct = (day_pnl_eur / previous_exposure_eur * 100) if previous_exposure_eur else 0.0
    else:
        day_pnl_eur = 0.0
        day_pnl_pct = 0.0

    return {
        "position": position,
        "current_price_eur": current_price_eur,
        "current_exposure_eur": current_exposure_eur,
        "pnl_eur": pnl_eur,
        "pnl_pct": pnl_pct,
        "pnl_base_eur": pnl_base,  # dénominateur utilisé pour pnl_pct, réutilisable pour un % agrégé
        "leverage": leverage,
        "liquidation_price_eur": liq_price_eur,
        "maintenance_margin_pct": maint_pct,  # None si pas à levier ; 0-100+ sinon (liquidation à 80%)
        "equity_contribution_eur": position.margin_eur + pnl_eur,
        "day_pnl_eur": day_pnl_eur,
        "day_pnl_pct": day_pnl_pct,
        "category": category_for(quote_type, position.ticker),
        "error": error,
        "stale_since": stale_since,  # epoch du dernier prix connu si prix daté, sinon None
    }


def total_value(portfolio, price_cache: dict[str, float] | None = None) -> tuple[float, list[dict]]:
    """Retourne (valeur totale du portefeuille, snapshots enrichis de chaque
    position). La valeur totale est cash + somme des contributions à l'équity.
    """
    snapshots = [position_snapshot(pos, price_cache) for pos in portfolio.positions.values()]
    total = portfolio.cash + sum(s["equity_contribution_eur"] for s in snapshots)
    return total, snapshots


# Seuil de variation (depuis la clôture précédente) au-delà duquel une
# position détenue déclenche la bannière d'alerte (voir large_movers).
MOVER_THRESHOLD_PCT = 5.0


def large_movers(snapshots: list[dict], threshold_pct: float = MOVER_THRESHOLD_PCT) -> list[dict]:
    """Positions DÉTENUES dont le prix a bougé de plus de `threshold_pct`
    depuis la clôture précédente (day_pnl_pct, déjà calculé par
    position_snapshot ci-dessus à partir du même appel API que le prix
    courant — voir get_quote). Ne déclenche donc AUCUN appel réseau
    supplémentaire : c'est un sous-produit de la revalorisation du
    portefeuille actif déjà effectuée à chaque chargement de page (voir
    app.py), qu'un mouvement de prix soit surveillé ou non.

    Volontairement limité aux positions détenues (pas aux actifs seulement
    "suivis"/recherchés sans être possédés, voir la doc de conception
    d'origine) : les revaloriser en continu demanderait des appels API
    dédiés, ce que cette fonctionnalité s'interdit explicitement.
    """
    movers = [
        {"ticker": s["position"].ticker, "name": s["position"].name, "day_pnl_pct": s["day_pnl_pct"]}
        for s in snapshots
        if not s["error"] and abs(s["day_pnl_pct"]) >= threshold_pct
    ]
    movers.sort(key=lambda m: abs(m["day_pnl_pct"]), reverse=True)
    return movers


def daily_pnl(portfolio, total_value_eur: float) -> tuple[float, float]:
    """P&L depuis le dernier point de value_history antérieur à aujourd'hui.

    À défaut (portefeuille créé aujourd'hui, sans historique antérieur), se
    rabat sur le capital de départ comme référence.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    baseline = portfolio.initial_capital
    for point in reversed(portfolio.value_history):
        if point["date"][:10] != today:
            baseline = point["value_eur"]
            break

    pnl_eur = total_value_eur - baseline
    pnl_pct = (pnl_eur / baseline * 100) if baseline else 0.0
    return pnl_eur, pnl_pct
