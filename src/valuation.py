"""Calcul de la valeur d'un portefeuille et du P&L de ses positions à partir
des prix courants du marché. Centralisé ici pour être réutilisé à la fois par
l'affichage (onglet Portefeuille) et par l'enregistrement de la courbe de
valeur (record_value_snapshot).
"""

from datetime import datetime

from . import market_data as md

# Regroupement des quoteType Yahoo en 3 grandes catégories d'actif, utilisées
# pour la répartition affichée dans l'onglet Portefeuille. "Autres" couvre le
# cas où le quoteType n'a pas pu être déterminé (prix en repli, cache de prix
# partagé sans ce détail — voir leaderboard.py).
_CATEGORY_LABELS = {
    "EQUITY": "Actions",
    "ETF": "Indices/ETF",
    "INDEX": "Indices/ETF",
    "MUTUALFUND": "Indices/ETF",
    "CRYPTOCURRENCY": "Crypto",
}


def category_for(quote_type: str) -> str:
    return _CATEGORY_LABELS.get((quote_type or "").upper(), "Autres")


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
    if price_cache is not None and position.ticker in price_cache:
        current_price_eur = price_cache[position.ticker]
        error = None
    else:
        try:
            quote = md.get_quote(position.ticker)
            current_price_eur = md.convert_to_eur(quote["price"], quote["currency"])
            if quote.get("previous_close") is not None:
                previous_close_eur = md.convert_to_eur(quote["previous_close"], quote["currency"])
            quote_type = quote.get("quote_type") or ""
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
    leverage = (cost_basis / position.margin_eur) if position.margin_eur > 1e-9 else None

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
        "equity_contribution_eur": position.margin_eur + pnl_eur,
        "day_pnl_eur": day_pnl_eur,
        "day_pnl_pct": day_pnl_pct,
        "category": category_for(quote_type),
        "error": error,
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
