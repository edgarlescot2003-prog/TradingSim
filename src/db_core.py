"""Connexion à la base PostgreSQL (Supabase), SANS dépendance à Streamlit.

Isolé de `src/db.py` pour que les scripts exécutés HORS de l'app (sauvegarde
via GitHub Actions, restauration en local, migration ponctuelle...) n'aient
jamais besoin d'installer Streamlit — un framework d'interface web qui n'a
rien à faire dans un script d'export/restauration de base de données lancé
par un cron (voir la panne "ModuleNotFoundError: streamlit" du workflow de
sauvegarde, causée par cette dépendance transitive avant cet isolement).

La chaîne de connexion est lue uniquement depuis la variable d'environnement
`DATABASE_URL` (fichier `.env` local via python-dotenv, secret GitHub
Actions, ou toute autre variable d'environnement d'exécution). `src/db.py`
(utilisé par l'app Streamlit) ajoute par-dessus un repli sur
`st.secrets["DATABASE_URL"]` et la mise en cache par processus serveur —
tout le reste (normalisation de l'URL, création du moteur SQLAlchemy) vit
ici pour n'être écrit qu'une seule fois.
"""

import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

load_dotenv()


def get_database_url_from_env() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL introuvable : définis-la dans .env (local), dans les secrets "
            "Streamlit Cloud (déploiement de l'app) ou dans les secrets du dépôt GitHub "
            "(workflows Actions, ex : sauvegarde quotidienne)."
        )
    return url


def normalize_url(url: str) -> str:
    """Force le driver psycopg (v3) et sslmode=require."""
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    elif url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]

    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.setdefault("sslmode", "require")
    return urlunsplit(parts._replace(query=urlencode(query)))


def create_engine_from_env() -> Engine:
    """Nouveau moteur SQLAlchemy à partir de DATABASE_URL (variable
    d'environnement uniquement, pas de cache ici) — pour les scripts
    indépendants de l'app (sauvegarde, restauration...). Voir
    `db.get_engine()` pour la version utilisée par l'app Streamlit
    (repli sur st.secrets + mise en cache par processus serveur)."""
    return create_engine(
        normalize_url(get_database_url_from_env()), pool_pre_ping=True, pool_recycle=3600,
    )
