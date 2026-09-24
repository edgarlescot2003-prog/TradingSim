"""Connexion à la base PostgreSQL (Supabase) pour l'app Streamlit.

La chaîne de connexion est lue depuis `st.secrets["DATABASE_URL"]` une fois
déployé (Streamlit Cloud), ou depuis la variable d'environnement
`DATABASE_URL` (fichier .env local via python-dotenv, voir db_core.py) en
développement. Jamais codée en dur dans le script.

Toute la logique indépendante de Streamlit (normalisation de l'URL, création
du moteur SQLAlchemy) vit dans `src/db_core.py` — ce module-ci n'ajoute que
le repli `st.secrets` et la mise en cache par processus serveur
(`st.cache_resource`), pour que les scripts exécutés HORS de l'app
(sauvegarde/restauration, voir scripts/backup_db.py) n'aient jamais besoin
d'installer Streamlit en important `src.db`.

`pool_pre_ping=True` évite de renvoyer une connexion morte du pool (le
pooler Supabase peut fermer les connexions inactives sans prévenir) ;
`pool_recycle=3600` recycle les connexions avant qu'elles ne soient coupées
côté serveur. `sslmode=require` est forcé si absent de l'URL fournie
(voir db_core.normalize_url).
"""

import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from . import db_core


def _get_database_url() -> str:
    try:
        url = st.secrets["DATABASE_URL"]
    except Exception:
        url = None
    return url or db_core.get_database_url_from_env()


@st.cache_resource(show_spinner=False)
def get_engine():
    """Moteur SQLAlchemy, mis en cache (un seul pool de connexions par
    processus serveur, réutilisé à travers tous les reruns Streamlit)."""
    url = db_core.normalize_url(_get_database_url())
    return create_engine(url, pool_pre_ping=True, pool_recycle=3600)


def get_session() -> Session:
    """Nouvelle session SQLAlchemy liée au moteur partagé. À fermer par
    l'appelant (idéalement via `with get_session() as session:`)."""
    factory = sessionmaker(bind=get_engine())
    return factory()


def init_db() -> None:
    """Crée les tables manquantes et applique les migrations (idempotent) —
    voir db_core.ensure_schema, source unique partagée avec les
    scripts/crons indépendants de l'app."""
    db_core.ensure_schema(get_engine())


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
    from . import diag_log

    diag_log.log_process_start()
    init_db()
