"""Persistance des cours dans PostgreSQL — contenu partagé entre tous les
comptes (pas de filtrage par utilisateur à la lecture). `user_id` marque
l'auteur d'origine, utilisé pour les permissions (auth.can_edit_course) :
il n'est jamais réassigné, même si un Admin modifie le cours ensuite.

Contrairement à storage.py (portefeuilles, remplacés en bloc à chaque
sauvegarde), ici chaque opération (ajout/modification/suppression) touche
une seule ligne : plusieurs comptes peuvent modifier le contenu partagé
sans qu'une sauvegarde écrase le travail d'un autre.
"""

from datetime import datetime, timezone

from sqlalchemy import select

from . import db
from .course import Course
from .db_models import CourseRow


def load_courses() -> list[Course]:
    with db.get_session() as session:
        rows = session.execute(select(CourseRow).order_by(CourseRow.created_at)).scalars().all()
        return [Course(
            id=r.id, title=r.title, theme=r.theme, content=r.content,
            created_at=r.created_at, updated_at=r.updated_at, author_id=r.user_id,
        ) for r in rows]


def add_course(course: Course, author_user_id: str) -> None:
    with db.get_session() as session:
        session.add(CourseRow(
            id=course.id, user_id=author_user_id, title=course.title, theme=course.theme,
            content=course.content, created_at=course.created_at, updated_at=course.updated_at,
        ))
        session.commit()


def update_course(course: Course) -> None:
    """Modifie le contenu ; l'auteur d'origine (user_id) n'est jamais
    changé, y compris quand c'est l'Admin qui édite le cours d'un autre."""
    with db.get_session() as session:
        row = session.get(CourseRow, course.id)
        if row is None:
            raise ValueError("Cours introuvable.")
        row.title = course.title
        row.theme = course.theme
        row.content = course.content
        row.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()


def delete_course(course_id: str) -> None:
    with db.get_session() as session:
        session.query(CourseRow).filter_by(id=course_id).delete()
        session.commit()
