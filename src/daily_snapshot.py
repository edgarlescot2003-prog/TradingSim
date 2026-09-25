"""Prix indicatifs quotidiens des pages de liste de l'onglet Trading, SANS
dépendance à Streamlit.

Table `asset_daily_snapshot` : une ligne par actif de l'univers
(asset_universe.py) avec sa clôture de la veille, sa devise réelle et sa
variation sur 30 jours. Les pages de liste LISENT cette table et ne
contactent jamais Yahoo/Kraken elles-mêmes : un rafraîchissement paresseux
(au plus une fois par jour et par catégorie) met la table à jour en arrière-
plan, à la première visite d'une liste.

Bail (`refresh_leases`) : garantit qu'un seul processus rafraîchit une
catégorie donnée à la fois, même si plusieurs participants ouvrent la même
liste en même temps. Acquis par une seule requête UPDATE conditionnelle
(atomique, portable SQLite/PostgreSQL), avec une durée de vie limitée pour
qu'un processus tué en plein travail ne bloque jamais les suivants.

Résilience : même principe que market_store (base injoignable, table absente
-> aucune exception ne remonte, l'appelant reçoit None et affiche un message
neutre). Tables créées automatiquement (CREATE TABLE IF NOT EXISTS), en plus
de db_core.ensure_schema.

Horodatages en texte ISO 8601 UTC à format FIXE (microsecondes toujours
présentes) : la comparaison de deux horodatages se fait alors directement
sur le texte, identique en SQLite et en PostgreSQL.
"""

import threading
import time
from datetime import datetime, timezone

from sqlalchemy import text

from . import asset_universe, market_store

LEASE_SECONDS = 10 * 60

_CREATE_TABLES_SQL = (
    """CREATE TABLE IF NOT EXISTS asset_daily_snapshot (
        ticker VARCHAR PRIMARY KEY,
        name VARCHAR NOT NULL,
        category VARCHAR NOT NULL,
        zone VARCHAR,
        country VARCHAR,
        close_price DOUBLE PRECISION,
        currency VARCHAR,
        change_30d_pct DOUBLE PRECISION,
        as_of_date VARCHAR,
        updated_at VARCHAR,
        last_attempt_at VARCHAR
    )""",
    "CREATE INDEX IF NOT EXISTS ix_asset_daily_snapshot_category ON asset_daily_snapshot (category)",
    """CREATE TABLE IF NOT EXISTS refresh_leases (
        name VARCHAR PRIMARY KEY,
        leased_until VARCHAR NOT NULL,
        holder VARCHAR
    )""",
)

_EPOCH_ISO = "1970-01-01T00:00:00.000000+00:00"


def iso(ts: float) -> str:
    """Horodatage ISO 8601 UTC à format fixe (voir la docstring du module)."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def from_iso(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


_ready_lock = threading.Lock()
_ready_engine = None


def _engine():
    """Moteur prêt (tables créées, univers amorcé une fois par processus),
    ou None si la base est indisponible."""
    global _ready_engine
    engine = market_store.engine_or_none()
    if engine is None:
        return None
    with _ready_lock:
        if _ready_engine is engine:
            return engine
        try:
            with engine.begin() as conn:
                for statement in _CREATE_TABLES_SQL:
                    conn.execute(text(statement))
                _seed(conn)
        except Exception as error:
            market_store.db_failed(error)
            return None
        _ready_engine = engine
    return engine


def _seed(conn) -> None:
    """Amorce la table avec l'univers actuel de l'app : insère les actifs
    absents, ne modifie JAMAIS une ligne existante (ON CONFLICT DO NOTHING)."""
    conn.execute(
        text("INSERT INTO asset_daily_snapshot (ticker, name, category) VALUES (:ticker, :name, :category) "
             "ON CONFLICT (ticker) DO NOTHING"),
        [{"ticker": t, "name": n, "category": c} for t, n, c in asset_universe.all_assets()],
    )


# -- Bail -------------------------------------------------------------------------

def acquire_lease(name: str, holder: str, duration: float = LEASE_SECONDS, now: float | None = None) -> bool:
    """Vrai si `holder` obtient le bail `name` (libre ou expiré). Une seule
    requête UPDATE conditionnelle : si deux processus tentent en même temps,
    la base n'en laisse passer qu'un (1 ligne modifiée pour lui, 0 pour
    l'autre). Faux si la base est indisponible (pas de rafraîchissement
    plutôt qu'un rafraîchissement non coordonné)."""
    engine = _engine()
    if engine is None:
        return False
    current = time.time() if now is None else now
    try:
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO refresh_leases (name, leased_until, holder) VALUES (:name, :epoch, NULL) "
                     "ON CONFLICT (name) DO NOTHING"),
                {"name": name, "epoch": _EPOCH_ISO},
            )
            result = conn.execute(
                text("UPDATE refresh_leases SET leased_until = :until, holder = :holder "
                     "WHERE name = :name AND leased_until < :now"),
                {"name": name, "holder": holder, "until": iso(current + duration), "now": iso(current)},
            )
            return result.rowcount == 1
    except Exception as error:
        market_store.db_failed(error)
        return False


def release_lease(name: str, holder: str) -> None:
    """Relâche le bail s'il appartient encore à `holder` (jamais celui d'un
    autre processus qui l'aurait repris après expiration)."""
    engine = _engine()
    if engine is None:
        return
    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE refresh_leases SET leased_until = :epoch, holder = NULL "
                     "WHERE name = :name AND holder = :holder"),
                {"name": name, "holder": holder, "epoch": _EPOCH_ISO},
            )
    except Exception as error:
        market_store.db_failed(error)


# -- Lecture ----------------------------------------------------------------------

_COLUMNS = ("ticker", "name", "category", "zone", "country", "close_price", "currency",
            "change_30d_pct", "as_of_date", "updated_at", "last_attempt_at")


def list_assets(category: str, zone: str | None = None, country: str | None = None) -> list[dict] | None:
    """Actifs d'une catégorie (lecture seule en base, jamais d'appel réseau),
    triés par nom. `zone`/`country` : filtres prévus pour une phase
    ultérieure (colonnes déjà présentes, nullables). None = base
    indisponible ou table absente."""
    engine = _engine()
    if engine is None:
        return None
    sql = f"SELECT {', '.join(_COLUMNS)} FROM asset_daily_snapshot WHERE category = :category"
    params = {"category": category}
    if zone is not None:
        sql += " AND zone = :zone"
        params["zone"] = zone
    if country is not None:
        sql += " AND country = :country"
        params["country"] = country
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(sql + " ORDER BY name"), params).fetchall()
    except Exception as error:
        market_store.db_failed(error)
        return None
    return [dict(zip(_COLUMNS, row)) for row in rows]
