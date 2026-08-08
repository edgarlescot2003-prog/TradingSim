"""Classement multi-utilisateurs : qui a le meilleur P&L.

S'appuie sur la dernière valeur connue de chaque portefeuille
(value_history, déjà tenue à jour par app.py à chaque interaction — voir
record_value_snapshot) plutôt que de recalculer les prix en direct de tout
le monde à chaque consultation du classement : ça reste rapide et n'ajoute
aucune charge sur les APIs de marché. Repli sur cash + positions à leur prix
d'achat (P&L nul) si un portefeuille n'a encore aucun point d'historique.

Un utilisateur avec plusieurs portefeuilles est classé sur la somme de tous
(capital de départ total vs valeur totale actuelle) — plus juste qu'un seul
de ses portefeuilles, qui pourrait masquer des pertes ailleurs.
"""

from sqlalchemy import func, select

from . import db
from .db_models import PortfolioRow, PositionRow, User, ValueHistoryRow


def _latest_value(session, portfolio_id: str, cash: float) -> float:
    last_date = session.execute(
        select(ValueHistoryRow.value_eur, ValueHistoryRow.date)
        .where(ValueHistoryRow.portfolio_id == portfolio_id)
        .order_by(ValueHistoryRow.date.desc())
        .limit(1)
    ).first()
    if last_date is not None:
        return last_date[0]

    book_value = session.execute(
        select(func.coalesce(func.sum(PositionRow.quantity * PositionRow.avg_price_eur), 0.0))
        .where(PositionRow.portfolio_id == portfolio_id)
    ).scalar()
    return cash + book_value


def compute_rankings() -> list[dict]:
    """Un P&L par utilisateur (agrégé sur tous ses portefeuilles), trié du
    meilleur au moins bon. Chaque entrée : user_id, username, n_portfolios,
    initial_capital, current_value, pnl_eur, pnl_pct.
    """
    with db.get_session() as session:
        usernames = {u.id: u.username for u in session.execute(select(User)).scalars().all()}
        portfolios = session.execute(select(PortfolioRow)).scalars().all()

        totals: dict[str, dict] = {}
        for p in portfolios:
            current_value = _latest_value(session, p.id, p.cash)
            entry = totals.setdefault(p.user_id, {
                "username": usernames.get(p.user_id, "(compte supprimé)"),
                "initial_capital": 0.0,
                "current_value": 0.0,
                "n_portfolios": 0,
            })
            entry["initial_capital"] += p.initial_capital
            entry["current_value"] += current_value
            entry["n_portfolios"] += 1

    rankings = []
    for user_id, data in totals.items():
        pnl_eur = data["current_value"] - data["initial_capital"]
        pnl_pct = (pnl_eur / data["initial_capital"] * 100) if data["initial_capital"] else 0.0
        rankings.append({"user_id": user_id, **data, "pnl_eur": pnl_eur, "pnl_pct": pnl_pct})

    rankings.sort(key=lambda r: r["pnl_eur"], reverse=True)
    return rankings
