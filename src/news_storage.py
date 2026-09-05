"""Persistance des articles News dans PostgreSQL — contenu partagé entre
tous les comptes (pas de filtrage par utilisateur à la lecture), sur le
même principe que course_storage.py. Pas de modification en place : un
article publié se supprime, il ne s'édite pas (voir la roadmap V1).
"""

from sqlalchemy import select

from . import db
from .db_models import NewsRow
from .news import NewsItem


def load_news() -> list[NewsItem]:
    """Tous les articles, du plus récent au plus ancien."""
    with db.get_session() as session:
        rows = session.execute(select(NewsRow).order_by(NewsRow.created_at.desc())).scalars().all()
        return [NewsItem(
            id=r.id, title=r.title, content=r.content, link=r.link,
            image_couverture=r.image_couverture, created_at=r.created_at, author_id=r.user_id,
        ) for r in rows]


def add_news(item: NewsItem, author_user_id: str) -> None:
    with db.get_session() as session:
        session.add(NewsRow(
            id=item.id, user_id=author_user_id, title=item.title, content=item.content,
            link=item.link, image_couverture=item.image_couverture, created_at=item.created_at,
        ))
        session.commit()


def delete_news(news_id: str) -> None:
    with db.get_session() as session:
        session.query(NewsRow).filter_by(id=news_id).delete()
        session.commit()
