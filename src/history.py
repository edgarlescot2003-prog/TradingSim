"""Historique et métriques de performance du portefeuille OFFICIEL d'un
utilisateur donné — page Historique, accessible depuis le Classement.

Contrairement à storage.py (scopé à l'utilisateur de la session en cours),
ce module lit les données d'un utilisateur ARBITRAIRE désigné par son id : la
page est volontairement publique (transparence du concours) — n'importe quel
compte connecté peut consulter l'historique des ordres et les métriques de
risque du portefeuille officiel de n'importe quel autre participant.
"""

from datetime import datetime
from statistics import StatisticsError, stdev

from sqlalchemy import select

from . import db
from .db_models import PortfolioRow, TradeRow, User, ValueHistoryRow

# Taux sans risque utilisé pour le ratio de Sharpe : Euribor 3 mois (≈2,64 %
# au moment de l'implémentation), valeur fixe pour toute la durée du concours
# (pas de récupération temps réel, voir la doc de conception d'origine). À
# ajuster ici si Edgar communique une valeur plus à jour.
RISK_FREE_RATE = 0.0264  # 2.64 %/an

# En dessous de ce nombre de jours de données, l'annualisation n'est pas
# jugée représentative : les métriques restent calculées et affichées, mais
# accompagnées d'une mention explicite du nombre de jours disponibles
# (voir ui_history._render_metrics) plutôt que présentées sans nuance.
MIN_RELIABLE_DAYS = 30

TRADING_DAYS_PER_YEAR = 252


def _value_series(portfolio_row: PortfolioRow, value_history_rows: list) -> list[tuple[str, float]]:
    """Série (date, valeur) triée chronologiquement, avec le capital de
    départ ajouté au tout début si le premier point enregistré n'est pas déjà
    au jour de création du portefeuille (aucune position -> valeur = capital
    de départ ce jour-là)."""
    points = {v.date[:10]: v.value_eur for v in value_history_rows}
    created_date = portfolio_row.created_at[:10]
    points.setdefault(created_date, portfolio_row.initial_capital)
    return sorted(points.items(), key=lambda p: p[0])


def compute_metrics(portfolio_row: PortfolioRow, value_history_rows: list) -> dict:
    """Rendement annualisé, volatilité annualisée, Sharpe et max drawdown à
    partir de la courbe de valeur du portefeuille officiel.

    `n_days` est le nombre de jours couverts par les données disponibles ;
    `reliable` indique si ce nombre est jugé suffisant pour une annualisation
    représentative (voir MIN_RELIABLE_DAYS) — les métriques sont calculées et
    retournées dans tous les cas, seule l'interprétation affichée en dépend.
    """
    series = _value_series(portfolio_row, value_history_rows)
    if len(series) < 2:
        return {"available": False, "n_days": 0}

    dates = [datetime.strptime(d, "%Y-%m-%d") for d, _ in series]
    values = [v for _, v in series]
    n_days = (dates[-1] - dates[0]).days
    if n_days <= 0 or not values[0]:
        return {"available": False, "n_days": n_days}

    total_return = (values[-1] / values[0]) - 1
    annualized_return = (1 + total_return) ** (365 / n_days) - 1

    daily_returns = [
        (values[i] / values[i - 1]) - 1 for i in range(1, len(values)) if values[i - 1]
    ]
    try:
        daily_vol = stdev(daily_returns) if len(daily_returns) >= 2 else 0.0
    except StatisticsError:
        daily_vol = 0.0
    annualized_vol = daily_vol * (TRADING_DAYS_PER_YEAR ** 0.5)

    sharpe = (annualized_return - RISK_FREE_RATE) / annualized_vol if annualized_vol > 1e-9 else None

    peak = values[0]
    max_drawdown = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - v) / peak)

    return {
        "available": True,
        "n_days": n_days,
        "reliable": n_days >= MIN_RELIABLE_DAYS,
        "annualized_return": annualized_return,
        "annualized_volatility": annualized_vol,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "risk_free_rate": RISK_FREE_RATE,
    }


def get_user_history(user_id: str) -> dict | None:
    """Détail du portefeuille OFFICIEL de `user_id` : ordres chronologiques
    (plus récent en premier) et métriques de performance calculées sur sa
    seule courbe de valeur. None si l'utilisateur n'existe plus ou n'a pas de
    portefeuille officiel désigné — jamais un repli sur un autre portefeuille
    fun/test de ce même utilisateur.
    """
    with db.get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            return None

        prow = session.execute(
            select(PortfolioRow).where(
                PortfolioRow.user_id == user_id, PortfolioRow.is_official.is_(True)
            )
        ).scalar_one_or_none()
        if prow is None:
            return None

        trades = session.execute(
            select(TradeRow).where(TradeRow.portfolio_id == prow.id).order_by(TradeRow.date.desc())
        ).scalars().all()
        value_history = session.execute(
            select(ValueHistoryRow).where(ValueHistoryRow.portfolio_id == prow.id)
        ).scalars().all()

        metrics = compute_metrics(prow, value_history)

        return {
            "username": user.username,
            "portfolio_name": prow.name,
            "initial_capital": prow.initial_capital,
            "trades": [{
                "date": t.date, "ticker": t.ticker, "name": t.name, "action": t.action,
                "quantity": t.quantity, "price_eur": t.price_eur,
            } for t in trades],
            "metrics": metrics,
        }
