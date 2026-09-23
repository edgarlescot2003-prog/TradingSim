"""Requêtes sans réseau pour la page Admin News."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from . import db
from .db_models import (
    MarketPriceSnapshotRow, PortfolioValueSnapshotRow, TradeRow, User,
)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)


def _variation_rows(rows, window: timedelta) -> list[dict]:
    now = datetime.now(timezone.utc)
    cutoff = now - window
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(row.ticker, []).append(row)

    result = []
    for ticker, ticker_rows in grouped.items():
        current = max(ticker_rows, key=lambda row: _parse(row.recorded_at))
        previous_candidates = [row for row in ticker_rows if _parse(row.recorded_at) <= cutoff]
        if not previous_candidates:
            continue
        previous = max(previous_candidates, key=lambda row: _parse(row.recorded_at))
        if previous.price_eur == 0:
            continue
        result.append({
            "ticker": ticker, "name": current.name, "category": current.category,
            "price_eur": current.price_eur,
            "change_pct": (current.price_eur / previous.price_eur - 1) * 100,
        })
    return result


def _portfolio_variations(rows, usernames: dict[str, str], window: timedelta) -> list[dict]:
    now = datetime.now(timezone.utc)
    cutoff = now - window
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(row.portfolio_id, []).append(row)

    result = []
    for portfolio_id, portfolio_rows in grouped.items():
        current = max(portfolio_rows, key=lambda row: _parse(row.recorded_at))
        previous_candidates = [row for row in portfolio_rows if _parse(row.recorded_at) <= cutoff]
        if not previous_candidates:
            continue
        previous = max(previous_candidates, key=lambda row: _parse(row.recorded_at))
        if previous.value_eur == 0:
            continue
        result.append({
            "portfolio_id": portfolio_id, "user_id": current.user_id,
            "username": usernames.get(current.user_id, "(compte supprimé)"),
            "current_value": current.value_eur,
            "change_pct": (current.value_eur / previous.value_eur - 1) * 100,
        })
    return result


def load_dashboard() -> dict:
    now = datetime.now(timezone.utc)
    price_start = now - timedelta(days=8)
    trade_start = now - timedelta(hours=24)
    with db.get_session() as session:
        price_rows = session.execute(
            select(MarketPriceSnapshotRow).where(
                MarketPriceSnapshotRow.recorded_at >= price_start.isoformat()
            )
        ).scalars().all()
        portfolio_rows = session.execute(
            select(PortfolioValueSnapshotRow).where(
                PortfolioValueSnapshotRow.recorded_at >= price_start.isoformat()
            )
        ).scalars().all()
        trades = session.execute(
            select(TradeRow).where(TradeRow.date >= trade_start.isoformat()).order_by(TradeRow.date.desc())
        ).scalars().all()
        users = {user.id: user.username for user in session.execute(select(User)).scalars().all()}

    return {
        "assets_24h": _variation_rows(price_rows, timedelta(hours=24)),
        "assets_7d": _variation_rows(price_rows, timedelta(days=7)),
        "participants_24h": _portfolio_variations(portfolio_rows, users, timedelta(hours=24)),
        "participants_7d": _portfolio_variations(portfolio_rows, users, timedelta(days=7)),
        "trades": [
            {
                "id": str(trade.id), "date": trade.date,
                "username": users.get(trade.user_id, "(compte supprimé)"),
                "ticker": trade.ticker, "name": trade.name, "action": trade.action,
                "quantity": trade.quantity, "price_eur": trade.price_eur,
                "volume_eur": trade.quantity * trade.price_eur,
            }
            for trade in trades
        ],
    }