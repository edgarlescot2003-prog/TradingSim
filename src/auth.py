"""Authentification, comptes et rôles.

Mots de passe hachés avec bcrypt (primitive standard, éprouvée — c'est
d'ailleurs ce qu'utilise streamlit-authenticator en interne). Un compte créé
par inscription publique est toujours "standard" ; le premier compte Admin
se crée via scripts/create_admin.py. Un Admin peut ensuite promouvoir
n'importe quel compte standard en Admin depuis la page d'administration
(promotion à sens unique — pas de rétrogradation depuis l'UI, pour éviter
de se retrouver sans plus aucun admin par erreur).

Rôles (2 seulement) :
- admin    : accès total. Gère les comptes (activer/désactiver/supprimer/
             promouvoir), peut écrire n'importe quel cours (y compris ceux
             d'un autre auteur), seul à pouvoir écrire dans le futur News.
- standard : rôle par défaut, y compris pour tout nouveau compte inscrit.
             Son propre portefeuille, isolé. Peut ajouter des cours et
             modifier ceux qu'il a écrits, mais ne peut en supprimer aucun
             (ni les siens ni ceux des autres — réservé à l'Admin). Lecture
             seule sur le futur onglet News.
"""

import bcrypt
from sqlalchemy import select

from . import db
from .db_models import CourseRow, PendingOrderRow, PortfolioRow, PositionRow, TradeRow, User, ValueHistoryRow

ROLE_ADMIN = "admin"
ROLE_STANDARD = "standard"

ROLE_LABELS = {
    ROLE_ADMIN: "Admin",
    ROLE_STANDARD: "Utilisateur standard",
}

STATUS_OK = "ok"
STATUS_INVALID = "invalid"
STATUS_DISABLED = "disabled"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False  # hash corrompu/vide, jamais un plantage


def authenticate(username: str, password: str):
    """Retourne (statut, User|None). Statut : STATUS_OK, STATUS_INVALID
    (identifiant ou mot de passe incorrect) ou STATUS_DISABLED (identifiants
    corrects mais compte désactivé)."""
    with db.get_session() as session:
        user = session.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if user is None or not verify_password(password, user.password_hash):
            return STATUS_INVALID, None
        if not user.is_active:
            return STATUS_DISABLED, None
        session.expunge(user)
        return STATUS_OK, user


def create_user(username: str, password: str, role: str = ROLE_STANDARD) -> User:
    username = username.strip()
    if not username:
        raise ValueError("L'identifiant est obligatoire.")
    if len(password) < 8:
        raise ValueError("Le mot de passe doit faire au moins 8 caractères.")

    with db.get_session() as session:
        existing = session.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if existing is not None:
            raise ValueError(f"L'identifiant « {username} » est déjà pris.")

        user = User(username=username, password_hash=hash_password(password), role=role, is_active=True)
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user


def list_users() -> list[User]:
    with db.get_session() as session:
        users = session.execute(select(User).order_by(User.created_at)).scalars().all()
        session.expunge_all()
        return users


def set_active(user_id: str, is_active: bool) -> None:
    with db.get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise ValueError("Compte introuvable.")
        user.is_active = is_active
        session.commit()


def promote_to_admin(user_id: str) -> None:
    """Promeut un compte standard en Admin. Pas de chemin inverse depuis
    l'UI (voir le commentaire de module)."""
    with db.get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise ValueError("Compte introuvable.")
        user.role = ROLE_ADMIN
        session.commit()


def delete_user(user_id: str) -> None:
    """Supprime le compte et toutes ses données (portefeuilles, positions,
    trades, ordres, courbe de valeur). Les cours qu'il a rédigés sont
    conservés (contenu partagé) mais détachés de son compte.

    Pas de contrainte ON DELETE CASCADE en base (les tables existaient déjà
    avant l'introduction des comptes) : la suppression en cascade est donc
    faite explicitement ici, dans l'ordre qui respecte les clés étrangères.
    """
    with db.get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            return

        user.active_portfolio_id = None
        session.flush()

        portfolio_ids = [
            row[0] for row in session.execute(
                select(PortfolioRow.id).where(PortfolioRow.user_id == user_id)
            ).all()
        ]
        for model in (PositionRow, TradeRow, PendingOrderRow, ValueHistoryRow):
            session.query(model).filter(model.portfolio_id.in_(portfolio_ids)).delete(
                synchronize_session=False
            )
        session.query(PortfolioRow).filter_by(user_id=user_id).delete(synchronize_session=False)
        session.query(CourseRow).filter_by(user_id=user_id).update(
            {"user_id": None}, synchronize_session=False
        )
        session.delete(user)
        session.commit()


def get_active_portfolio_id(user_id: str) -> str | None:
    with db.get_session() as session:
        user = session.get(User, user_id)
        return user.active_portfolio_id if user else None


def set_active_portfolio(user_id: str, portfolio_id: str) -> None:
    with db.get_session() as session:
        user = session.get(User, user_id)
        if user is not None:
            user.active_portfolio_id = portfolio_id
            session.commit()


# -- Permissions ---------------------------------------------------------
#
# Point d'entrée unique pour toute vérification de droit dans l'UI. Un futur
# onglet News réutilise can_write_news tel quel — aucune nouvelle logique de
# permission à écrire.

def is_admin(role: str) -> bool:
    return role == ROLE_ADMIN


def can_add_course(role: str) -> bool:
    """Tout compte connecté (donc actif) peut ajouter un cours."""
    return True


def can_edit_course(role: str, author_id: str | None, current_user_id: str) -> bool:
    """Admin : n'importe quel cours. Standard : uniquement ceux qu'il a écrits."""
    if role == ROLE_ADMIN:
        return True
    return author_id == current_user_id


def can_delete_course(role: str) -> bool:
    """Suppression réservée à l'Admin, y compris pour ses propres cours."""
    return role == ROLE_ADMIN


def can_write_news(role: str) -> bool:
    """Écriture du futur onglet News réservée à l'Admin."""
    return role == ROLE_ADMIN
