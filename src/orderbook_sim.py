"""Carnet d'ordre PUREMENT DÉCORATIF pour la fiche Trading (prompt 20).

AUCUNE vraie donnée de marché ici : ce module ne fait que fabriquer des
niveaux bid/ask crédibles visuellement à partir d'un prix de référence déjà
connu (le dernier prix réel mis en cache par `ui_trading._render_price_and_chart`,
voir `ui_trading._render_order_book`). Il ne contient et ne doit JAMAIS
contenir d'appel réseau (`market_data.get_quote`, `kraken_data.*`,
`yfinance`...) — c'est un générateur de bruit local, rien d'autre. Un futur
développeur qui voudrait le connecter à un vrai order book se trompe de
module : il n'y a ici aucune notion d'ordres réels, juste de l'esthétique.

Principe (voir le prompt d'origine) : quand le prix de référence change
(nouveau tick réel), `generate_snapshot` régénère les niveaux autour du
nouveau prix, avec un léger biais directionnel reflétant le sens du
mouvement (juste pour l'effet — aucune signification). Entre deux vrais
ticks, `apply_noise` anime seulement les quantités (léger random walk) sans
toucher aux prix ni au `reference_price`, pour donner une impression de
mouvement continu sans jamais prétendre à un nouveau tick réel.
"""

import random

LEVELS_PER_SIDE = 8

# Écart symbolique entre le meilleur bid et le meilleur ask (moitié de
# chaque côté du prix de référence), en points de base (1 bps = 0.01%).
BASE_SPREAD_BPS = 4.0
# Écart de prix entre deux paliers consécutifs d'un même côté, en bps.
LEVEL_STEP_BPS = 7.0
# Amplitude du bruit relatif appliqué aux quantités entre deux vrais ticks
# (random walk léger, voir apply_noise).
NOISE_FRACTION = 0.12
# Biais directionnel maximal appliqué aux quantités lors d'un nouveau tick
# (voir generate_snapshot) : purement cosmétique, ne représente aucune
# vraie pression acheteuse/vendeuse.
TREND_BIAS_MAX = 0.25


def _level_quantity(rank: int, rng: random.Random, bias: float) -> float:
    """Quantité d'un palier à la distance `rank` du prix (0 = le plus
    proche). Loi log-normale décroissante avec l'éloignement, pour plus de
    volume près du prix — purement pour le rendu visuel, aucune
    signification de marché. `bias` (entre -TREND_BIAS_MAX et
    +TREND_BIAS_MAX) accentue ou atténue légèrement ce côté selon le sens
    du dernier mouvement de prix."""
    decay = 1.0 / (1.0 + rank * 0.35)
    base = rng.lognormvariate(0, 0.55) * decay
    return max(base * (1.0 + bias), 0.001)


def _levels_side(reference_price: float, side: str, rng: random.Random, bias: float) -> list[dict]:
    """Génère LEVELS_PER_SIDE paliers pour un côté (side="ask" ou "bid"),
    du plus proche du prix (index 0) au plus loin."""
    sign = 1.0 if side == "ask" else -1.0
    half_spread = reference_price * (BASE_SPREAD_BPS / 2 / 10_000)
    start_price = reference_price + sign * half_spread
    step = reference_price * (LEVEL_STEP_BPS / 10_000)
    levels = []
    for rank in range(LEVELS_PER_SIDE):
        price = start_price + sign * rank * step
        quantity = _level_quantity(rank, rng, bias)
        levels.append({"price": price, "quantity": quantity})
    return levels


def generate_snapshot(reference_price: float, previous_price: float | None = None,
                       seed: int | None = None) -> dict:
    """Nouveau snapshot complet (asks + bids), généré autour de
    `reference_price` — appelé quand le prix réel caché vient de changer
    (nouveau tick) ou au tout premier affichage. `previous_price` (le
    dernier `reference_price` connu avant ce tick) sert uniquement à
    calculer un léger biais directionnel cosmétique sur les quantités —
    aucune des deux valeurs n'est jamais récupérée par un appel réseau ici,
    seulement transmises par l'appelant (voir ui_trading._render_order_book).
    `seed` optionnel pour des snapshots reproductibles en test.
    """
    rng = random.Random(seed)
    if previous_price and previous_price > 0 and reference_price != previous_price:
        relative_move = (reference_price - previous_price) / previous_price
        # Clampé : un mouvement de prix, même important, ne doit jamais
        # rendre un côté du carnet vide ou disproportionné à l'œil.
        trend = max(-1.0, min(1.0, relative_move * 50)) * TREND_BIAS_MAX
    else:
        trend = 0.0
    # Prix en hausse -> légèrement plus de profondeur côté bids (la
    # "demande" qui a fait monter le prix), un peu moins côté asks, et
    # inversement — cosmétique uniquement, voir la docstring du module.
    asks = _levels_side(reference_price, "ask", rng, bias=-trend)
    bids = _levels_side(reference_price, "bid", rng, bias=trend)
    return {"reference_price": reference_price, "asks": asks, "bids": bids}


def apply_noise(snapshot: dict, seed: int | None = None) -> dict:
    """Anime les quantités d'un snapshot existant par un léger bruit
    aléatoire (random walk), SANS régénérer ni toucher aux prix ni au
    `reference_price` — utilisé entre deux vrais ticks pour donner une
    impression de mouvement continu. Jamais d'appel réseau (voir docstring
    du module)."""
    rng = random.Random(seed)
    new_snapshot = {"reference_price": snapshot["reference_price"], "asks": [], "bids": []}
    for side in ("asks", "bids"):
        for level in snapshot[side]:
            factor = 1.0 + rng.uniform(-NOISE_FRACTION, NOISE_FRACTION)
            new_snapshot[side].append({
                "price": level["price"],
                "quantity": max(level["quantity"] * factor, 0.001),
            })
    return new_snapshot


def with_cumulative(levels: list[dict]) -> list[dict]:
    """Ajoute le total cumulé (depuis le palier le plus proche du prix,
    index 0) à chaque palier — pour la colonne "total cumulé" et la barre
    de profondeur affichées par `ui_trading._render_order_book`."""
    cumulative = 0.0
    out = []
    for level in levels:
        cumulative += level["quantity"]
        out.append({**level, "cumulative": cumulative})
    return out
