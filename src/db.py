"""Connexion à la base PostgreSQL (Supabase).

La chaîne de connexion est lue depuis `st.secrets["DATABASE_URL"]` une fois
déployé (Streamlit Cloud), ou depuis la variable d'environnement
`DATABASE_URL` (fichier .env local via python-dotenv) en développement.
Jamais codée en dur dans le script.

`pool_pre_ping=True` évite de renvoyer une connexion morte du pool (le
pooler Supabase peut fermer les connexions inactives sans prévenir) ;
`pool_recycle=3600` recycle les connexions avant qu'elles ne soient coupées
côté serveur. `sslmode=require` est forcé si absent de l'URL fournie.
"""

import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()


def _get_database_url() -> str:
    try:
        url = st.secrets["DATABASE_URL"]
    except Exception:
        url = None
    if not url:
        url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL introuvable : définis-la dans .env (local) ou dans "
            "les secrets Streamlit Cloud (déploiement)."
        )
    return url


def _normalize_url(url: str) -> str:
    """Force le driver psycopg (v3) et sslmode=require."""
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    elif url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]

    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.setdefault("sslmode", "require")
    return urlunsplit(parts._replace(query=urlencode(query)))


@st.cache_resource(show_spinner=False)
def get_engine():
    """Moteur SQLAlchemy, mis en cache (un seul pool de connexions par
    processus serveur, réutilisé à travers tous les reruns Streamlit)."""
    url = _normalize_url(_get_database_url())
    return create_engine(url, pool_pre_ping=True, pool_recycle=3600)


def get_session() -> Session:
    """Nouvelle session SQLAlchemy liée au moteur partagé. À fermer par
    l'appelant (idéalement via `with get_session() as session:`)."""
    factory = sessionmaker(bind=get_engine())
    return factory()


def init_db() -> None:
    """Crée les tables manquantes (idempotent)."""
    from sqlalchemy import text

    from . import db_models
    db_models.Base.metadata.create_all(get_engine())

    # create_all ne modifie jamais une table déjà existante : une colonne
    # ajoutée après coup (ex : is_official) doit être migrée explicitement
    # ici. ADD COLUMN IF NOT EXISTS est idempotent (sans effet si la colonne
    # existe déjà), donc sans risque à rappeler à chaque démarrage.
    with get_engine().begin() as conn:
        conn.execute(text(
            "ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS is_official BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        conn.execute(text(
            "ALTER TABLE news ADD COLUMN IF NOT EXISTS is_system BOOLEAN NOT NULL DEFAULT FALSE"
        ))


DEFAULT_USERNAME = "default"


def ensure_default_user() -> str:
    """Crée (si besoin) un utilisateur unique servant de propriétaire des
    données tant que l'authentification (phase suivante) n'est pas branchée.
    Retourne son id. Idempotent : rappelable à chaque lancement de l'app.
    """
    from sqlalchemy import select
    from .db_models import User

    with get_session() as session:
        user = session.execute(select(User).where(User.username == DEFAULT_USERNAME)).scalar_one_or_none()
        if user is None:
            user = User(username=DEFAULT_USERNAME, password_hash="", role="admin", is_active=True)
            session.add(user)
            session.commit()
            session.refresh(user)
        return user.id


@st.cache_resource(show_spinner=False)
def bootstrap() -> None:
    """Crée les tables manquantes, une seule fois par processus serveur (pas
    à chaque rerun/session).

    Ne crée plus d'utilisateur par défaut depuis que l'authentification est
    branchée : le premier compte Admin se crée via scripts/create_admin.py
    (qui met à niveau l'ancien compte "default" en place s'il en reste un —
    voir ensure_default_user, encore utilisée par ce script et par la
    migration JSON ponctuelle). Appeler ensure_default_user() ici recréerait
    un compte "default" fantôme à chaque redémarrage dès qu'il a été
    renommé, ce qui s'est produit et a laissé un compte orphelin en base.
    """
    init_db()
