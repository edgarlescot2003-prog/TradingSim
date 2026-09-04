"""Historique des actifs récemment consultés dans l'onglet Trading, par
utilisateur : propose un raccourci quand la barre de recherche est vide,
plutôt que de retaper le ticker à chaque fois.
"""

from datetime import datetime, timezone

from sqlalchemy import select

from . import db
from .db_models import SearchHistoryRow

MAX_RECENT = 8


def record(user_id: str, ticker: str, name: str, quote_type: str = "") -> None:
    """Enregistre (ou renouvelle la date de) la consultation de `ticker`."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with db.get_session() as session:
        row = session.execute(
            select(SearchHistoryRow).where(
                SearchHistoryRow.user_id == user_id, SearchHistoryRow.ticker == ticker,
            )
        ).scalar_one_or_none()
        if row is None:
            session.add(SearchHistoryRow(
                user_id=user_id, ticker=ticker, name=name, quote_type=quote_type, searched_at=now_iso,
            ))
        else:
            row.name = name
            row.quote_type = quote_type
            row.searched_at = now_iso
        session.commit()


def get_recent(user_id: str, limit: int = MAX_RECENT) -> list[dict]:
    """Les derniers actifs consultés, du plus récent au plus ancien."""
    with db.get_session() as session:
        rows = session.execute(
            select(SearchHistoryRow)
            .where(SearchHistoryRow.user_id == user_id)
            .order_by(SearchHistoryRow.searched_at.desc())
            .limit(limit)
        ).scalars().all()
        return [{"ticker": r.ticker, "name": r.name, "quote_type": r.quote_type} for r in rows]
