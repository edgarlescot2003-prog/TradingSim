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
    absents, ne modifie JAMAIS une ligne existante (ON CONFLICT DO NOTHING),
    puis renseigne zone/pays (trading_nav_config.ASSET_PLACES) là où ils
    sont encore vides seulement — idempotent, aucune valeur écrasée."""
    from .trading_nav_config import ASSET_PLACES

    conn.execute(
        text("INSERT INTO asset_daily_snapshot (ticker, name, category) VALUES (:ticker, :name, :category) "
             "ON CONFLICT (ticker) DO NOTHING"),
        [{"ticker": t, "name": n, "category": c} for t, n, c in asset_universe.all_assets()],
    )
    conn.execute(
        text("UPDATE asset_daily_snapshot SET zone = COALESCE(zone, :zone), country = COALESCE(country, :country) "
             "WHERE ticker = :ticker AND (zone IS NULL OR country IS NULL)"),
        [{"ticker": t, "zone": z, "country": c} for t, (z, c) in ASSET_PLACES.items()],
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


PLACES_CACHE_SECONDS = 300
_places_cache: dict[str, tuple[set[tuple[str, str | None]], float]] = {}
_places_lock = threading.Lock()


def available_places(category: str) -> set[tuple[str, str | None]] | None:
    """Couples (zone, pays) ayant au moins un actif de `category` dans la
    table — c'est ce qui rend une carte de zone/pays cliquable (sinon
    « Bientôt »). Une seule requête légère, mise en cache 5 min par
    processus. None si la base est indisponible (l'appelant affiche alors
    tout en « Bientôt », sans erreur)."""
    now = time.time()
    with _places_lock:
        cached = _places_cache.get(category)
        if cached and now - cached[1] < PLACES_CACHE_SECONDS:
            return cached[0]
    engine = _engine()
    if engine is None:
        return None
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT DISTINCT zone, country FROM asset_daily_snapshot "
                     "WHERE category = :category AND zone IS NOT NULL"),
                {"category": category},
            ).fetchall()
    except Exception as error:
        market_store.db_failed(error)
        return None
    places = {(row[0], row[1]) for row in rows}
    with _places_lock:
        _places_cache[category] = (places, now)
    return places


# -- Rafraîchissement paresseux ------------------------------------------------------
#
# Deux déclencheurs, même code, même bail (jamais de double chargement) :
# - le cron GitHub Actions (scripts/refresh_daily_lists.py), qui pré-charge
#   toutes les listes au premier passage après minuit UTC ;
# - l'ouverture d'une page de liste (ui_trading), filet de sécurité si le
#   cron n'a pas tourné (bridage des crons GitHub).
# Une ligne est "due" si elle n'a pas encore été mise à jour AUJOURD'HUI
# (jour calendaire UTC) ; une ligne en échec n'est retentée qu'après
# RETRY_AFTER_SECONDS (pas de boucle de tentatives sur un ticker en panne).

RETRY_AFTER_SECONDS = 3 * 3600
REQUEST_SPACING_SECONDS = 1.0
REQUEST_JITTER_SECONDS = 0.5
CHANGE_WINDOW_DAYS = 30


def summarize(candles, today) -> dict | None:
    """Règle "veille" et variation 30 j, sur des bougies quotidiennes
    [(date, clôture)] :
    - clôture de la veille = dernière bougie STRICTEMENT antérieure à
      `today` (la bougie du jour, en cours, est ignorée) — `today` est la
      date UTC (voir market_data.get_daily_closes) ;
    - variation 30 j = clôture de la veille / clôture de la dernière bougie
      datée au plus tard 30 jours avant elle - 1.
    None si l'une des deux est introuvable ou invalide (donnée incomplète :
    jamais écrite en base)."""
    from datetime import timedelta
    from math import isfinite

    past = sorted((d, c) for d, c in candles if d < today and c is not None and isfinite(c) and c > 0)
    if not past:
        return None
    as_of, close = past[-1]
    limit = as_of - timedelta(days=CHANGE_WINDOW_DAYS)
    reference = [c for d, c in past if d <= limit]
    if not reference:
        return None
    change = (close / reference[-1] - 1) * 100
    if not isfinite(change):
        return None
    return {"close_price": close, "as_of_date": as_of.isoformat(), "change_30d_pct": change}


def _start_of_utc_day(ts: float) -> float:
    day = datetime.fromtimestamp(ts, tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return day.timestamp()


def is_due(row: dict, now: float) -> bool:
    """À recharger si pas encore mise à jour aujourd'hui (UTC), et pas de
    tentative ratée depuis moins de RETRY_AFTER_SECONDS. Au plus une mise à
    jour réussie par jour calendaire, quelle que soit l'heure de la veille."""
    updated = from_iso(row.get("updated_at"))
    if updated is not None and updated >= _start_of_utc_day(now):
        return False
    attempted = from_iso(row.get("last_attempt_at"))
    return attempted is None or now - attempted >= RETRY_AFTER_SECONDS


def _write_success(ticker: str, data: dict, now: float) -> bool:
    engine = _engine()
    if engine is None:
        return False
    try:
        with engine.begin() as conn:  # une transaction par ligne
            conn.execute(
                text("UPDATE asset_daily_snapshot SET close_price = :close_price, currency = :currency, "
                     "change_30d_pct = :change_30d_pct, as_of_date = :as_of_date, updated_at = :now, "
                     "last_attempt_at = :now WHERE ticker = :ticker"),
                {**data, "ticker": ticker, "now": iso(now)},
            )
        return True
    except Exception as error:
        market_store.db_failed(error)
        return False


def _write_attempt(ticker: str, now: float) -> None:
    """Échec : seule l'heure de tentative change, les dernières bonnes
    valeurs restent en place."""
    engine = _engine()
    if engine is None:
        return
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE asset_daily_snapshot SET last_attempt_at = :now WHERE ticker = :ticker"),
                         {"ticker": ticker, "now": iso(now)})
    except Exception as error:
        market_store.db_failed(error)


def _fetch(ticker: str, category: str, pace) -> dict | None:
    """Bougies quotidiennes : Kraken pour la crypto (Yahoo en secours si
    Kraken échoue), Yahoo sinon. Respecte les deux coupe-circuits : une
    source en pause n'est jamais appelée. `pace()` est appelé juste avant
    chaque vraie requête (espacement). None si aucune source n'a répondu."""
    from . import kraken_data, market_data as md

    sources = [(kraken_data.KRAKEN, kraken_data.get_daily_closes)] if category == asset_universe.CRYPTO else []
    sources.append((md.YAHOO, md.get_daily_closes))
    for source, fetch in sources:
        if market_store.blocked_remaining(source) > 0:
            market_store.log_event("daily_refresh_circuit_open", source=source, ticker=ticker)
            continue
        pace()
        try:
            return fetch(ticker)
        except md.MarketDataError:
            continue
    return None


def refresh_category(category: str, sleep=time.sleep, now_fn=time.time) -> tuple[int, int]:
    """Met à jour les lignes dues d'une catégorie, une requête à la fois,
    espacées d'environ 1 s (plus un léger aléa). Retourne (mises à jour,
    ignorées). À appeler seulement avec le bail en main (voir
    start_refresh_if_due)."""
    import random

    rows = list_assets(category)
    if rows is None:
        return 0, 0
    due = [r for r in rows if is_due(r, now_fn())]
    market_store.log_event("daily_refresh_start", category=category, due=len(due), total=len(rows))
    requests_made = [0]

    def pace():
        if requests_made[0]:
            sleep(REQUEST_SPACING_SECONDS + random.uniform(0, REQUEST_JITTER_SECONDS))
        requests_made[0] += 1

    updated = skipped = 0
    for index, row in enumerate(due):
        ticker = row["ticker"]
        requests_before = requests_made[0]
        fetched = _fetch(ticker, category, pace)
        if requests_made[0] == requests_before:
            # Toutes les sources en pause : aucune requête, la liste garde ses
            # valeurs actuelles, retentée à la prochaine visite après la pause.
            skipped += len(due) - index
            break
        summary = summarize(fetched["candles"], fetched["today"]) if fetched else None
        if summary is not None and fetched.get("currency") and \
                _write_success(ticker, {**summary, "currency": fetched["currency"]}, now_fn()):
            updated += 1
            continue
        _write_attempt(ticker, now_fn())  # échec : pas de nouvel essai avant RETRY_AFTER_SECONDS
        skipped += 1
    market_store.log_event("daily_refresh_end", category=category, updated=updated, skipped=skipped,
                           requests=requests_made[0])
    return updated, skipped


def lease_name(category: str) -> str:
    return f"asset_daily:{category}"


_running_lock = threading.Lock()
_running: set[str] = set()


def is_refreshing(category: str) -> bool:
    """Rafraîchissement en cours DANS CE PROCESSUS (information d'affichage)."""
    with _running_lock:
        return category in _running


def start_refresh_if_due(category: str, now: float | None = None, rows: list[dict] | None = None) -> str:
    """Appelé à l'ouverture d'une page de liste : "fresh" (rien à faire),
    "started" (bail obtenu, rafraîchissement lancé en arrière-plan), "busy"
    (déjà en cours ici ou bail détenu par un autre processus),
    "unavailable" (base indisponible). Ne bloque jamais l'affichage : au
    plus deux requêtes SQL courtes ici, le travail réseau se fait dans un
    thread séparé."""
    import os
    import uuid

    current = time.time() if now is None else now
    rows = list_assets(category) if rows is None else rows  # `rows` : déjà lues par l'appelant
    if rows is None:
        return "unavailable"
    if not any(is_due(r, current) for r in rows):
        return "fresh"
    with _running_lock:
        if category in _running:
            return "busy"
        _running.add(category)
    holder = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    if not acquire_lease(lease_name(category), holder, now=current):
        with _running_lock:
            _running.discard(category)
        return "busy"

    def worker():
        try:
            refresh_category(category)
        except Exception as error:  # un thread d'arrière-plan ne doit jamais mourir en silence
            market_store.log_event("daily_refresh_error", category=category, error=repr(error))
        finally:
            release_lease(lease_name(category), holder)
            with _running_lock:
                _running.discard(category)

    threading.Thread(target=worker, name=f"daily-refresh-{category}", daemon=True).start()
    return "started"


def refresh_all_due(categories=None, holder: str = "cron") -> dict[str, str]:
    """Pré-chargement SYNCHRONE de toutes les listes dues (utilisé par le
    cron GitHub Actions) : même bail que l'app, donc jamais de chargement en
    double si quelqu'un ouvre une liste au même moment. Retourne
    {catégorie: résultat lisible}."""
    import os

    results = {}
    for category in categories or asset_universe.CATEGORIES:
        rows = list_assets(category)
        if rows is None:
            results[category] = "base indisponible"
            continue
        if not any(is_due(r, time.time()) for r in rows):
            results[category] = "déjà à jour"
            continue
        owner = f"{holder}-{os.getpid()}"
        if not acquire_lease(lease_name(category), owner):
            results[category] = "déjà en cours ailleurs"
            continue
        try:
            updated, skipped = refresh_category(category)
            results[category] = f"{updated} mis à jour, {skipped} ignoré(s)"
        finally:
            release_lease(lease_name(category), owner)
    return results
