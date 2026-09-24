"""État partagé des sources de marché (Yahoo, Kraken), SANS dépendance à
Streamlit (réutilisé par les scripts du cron, comme db_core/valuation).

Coupe-circuit après un HTTP 429 ("Too Many Requests") : l'IP sortante de
Streamlit Cloud est partagée avec d'autres applications, et Yahoo l'a déjà
bloquée (24/09). Continuer d'appeler une source qui nous bloque entretient le
blocage : dès qu'un vrai rate limit est constaté, plus AUCUN appel vers cette
source pendant une pause de 5 min, doublée à chaque nouveau 429 consécutif,
plafonnée à 30 min, remise à zéro dès qu'un appel réussit.

L'état vit en base (table `api_circuit_state`) pour être partagé entre
processus et survivre aux redémarrages/redéploiements — un état purement en
mémoire repartait à zéro à chaque redémarrage et relançait une rafale sur une
IP déjà bloquée. Relu au plus toutes les _STATE_REFRESH_SECONDS secondes
(jamais à chaque appel individuel), pour ne pas ajouter de trafic base inutile.

Résilience (impératif) : si la base est injoignable, non configurée ou la
table absente, tout se dégrade en mémoire locale. Aucune exception de lecture/
écriture de cet état ne remonte jamais à l'appelant.
"""

import re
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import text

_engine_getter = None


def configure(engine_getter) -> None:
    """Branche la persistance en base. `engine_getter` : fonction sans
    argument qui retourne un Engine SQLAlchemy (db.get_engine dans l'app,
    un moteur de db_core dans les scripts). Sans appel à configure(), tout
    reste en mémoire (tests, usage hors app)."""
    global _engine_getter, _tables_ready
    _engine_getter = engine_getter
    _tables_ready = False


def log_event(event: str, **fields) -> None:
    """Ligne de log permanente (indépendante de TS_DIAG_LOG), volontairement
    rare : ouverture/fermeture du coupe-circuit, passage en prix daté, refus
    d'ordre pour prix trop ancien."""
    details = " ".join(f"{k}={str(v).replace(chr(10), ' ')[:200]}" for k, v in fields.items())
    print(f"[MARKET] ts={datetime.now(timezone.utc).isoformat()} event={event} {details}", flush=True)


def _to_iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else None


def _from_iso(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


# -- Accès base, toujours protégé ---------------------------------------------

_DB_RETRY_SECONDS = 60
_db_unavailable_until = 0.0
_tables_ready = False
_db_lock = threading.Lock()

_CREATE_TABLES_SQL = (
    """CREATE TABLE IF NOT EXISTS api_circuit_state (
        source VARCHAR PRIMARY KEY,
        blocked_until VARCHAR,
        consecutive_failures INTEGER NOT NULL DEFAULT 0,
        last_error VARCHAR,
        updated_at VARCHAR NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS last_known_prices (
        ticker VARCHAR PRIMARY KEY,
        price DOUBLE PRECISION NOT NULL,
        currency VARCHAR NOT NULL,
        previous_close DOUBLE PRECISION,
        quote_type VARCHAR,
        market_time VARCHAR,
        fetched_at VARCHAR NOT NULL,
        change_30d_pct DOUBLE PRECISION,
        change_30d_at VARCHAR
    )""",
)


def _engine():
    """Moteur prêt à l'emploi, ou None (non configuré, base en panne récente)."""
    global _tables_ready
    if _engine_getter is None or time.time() < _db_unavailable_until:
        return None
    try:
        engine = _engine_getter()
        if not _tables_ready:
            # CREATE TABLE IF NOT EXISTS explicite, en plus de create_all
            # (db_core.ensure_schema) : ne dépend pas du fait que l'app ait
            # redémarré depuis l'ajout de ces tables.
            with engine.begin() as conn:
                for statement in _CREATE_TABLES_SQL:
                    conn.execute(text(statement))
            _tables_ready = True
        return engine
    except Exception as error:
        _db_failed(error)
        return None


def _db_failed(error: Exception) -> None:
    """Met la base de côté 60 s (évite qu'une base en panne ralentisse chaque
    appel de prix par un timeout de connexion) et le journalise une fois."""
    global _db_unavailable_until
    with _db_lock:
        already_down = time.time() < _db_unavailable_until
        _db_unavailable_until = time.time() + _DB_RETRY_SECONDS
    if not already_down:
        log_event("store_unavailable", fallback="memory", error=repr(error))


# -- Coupe-circuit ------------------------------------------------------------

BASE_PAUSE_SECONDS = 5 * 60
MAX_PAUSE_SECONDS = 30 * 60
_STATE_REFRESH_SECONDS = 5

_state_lock = threading.Lock()
_state: dict[str, dict] = {}
_state_synced_at: dict[str, float] = {}

_RATE_LIMIT_RE = re.compile(r"too many requests|rate limit|\b429\b", re.IGNORECASE)


def is_rate_limit_error(error) -> bool:
    """Vrai uniquement pour un vrai rate limit (HTTP 429 / YFRateLimitError /
    "EAPI:Rate limit exceeded" de Kraken) — un ticker introuvable ou une
    erreur ponctuelle ne bloque jamais toute la source."""
    if type(error).__name__ == "YFRateLimitError":
        return True
    return bool(_RATE_LIMIT_RE.search(str(error)))


def pause_seconds(consecutive_failures: int) -> int:
    """5 min, 10, 20, puis plafonné à 30 min."""
    exponent = max(consecutive_failures, 1) - 1
    return min(BASE_PAUSE_SECONDS * 2 ** min(exponent, 10), MAX_PAUSE_SECONDS)


def _empty_state() -> dict:
    return {"blocked_until": None, "failures": 0, "last_error": None}


def _load_state(source: str, force: bool = False) -> dict:
    """État courant (mémoire), rafraîchi depuis la base au plus toutes les
    _STATE_REFRESH_SECONDS secondes. Appelé sous _state_lock."""
    now = time.time()
    state = _state.setdefault(source, _empty_state())
    if not force and now - _state_synced_at.get(source, 0.0) < _STATE_REFRESH_SECONDS:
        return state
    _state_synced_at[source] = now
    engine = _engine()
    if engine is None:
        return state
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT blocked_until, consecutive_failures, last_error "
                     "FROM api_circuit_state WHERE source = :source"),
                {"source": source},
            ).first()
    except Exception as error:
        _db_failed(error)
        return state
    if row is not None:
        state.update(blocked_until=_from_iso(row[0]), failures=int(row[1] or 0), last_error=row[2])
    else:
        state.update(_empty_state())
    return state


def _save_state(source: str, state: dict) -> None:
    engine = _engine()
    if engine is None:
        return
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO api_circuit_state "
                    "(source, blocked_until, consecutive_failures, last_error, updated_at) "
                    "VALUES (:source, :blocked_until, :failures, :last_error, :updated_at) "
                    "ON CONFLICT (source) DO UPDATE SET "
                    "blocked_until = excluded.blocked_until, "
                    "consecutive_failures = excluded.consecutive_failures, "
                    "last_error = excluded.last_error, updated_at = excluded.updated_at"
                ),
                {
                    "source": source, "blocked_until": _to_iso(state["blocked_until"]),
                    "failures": state["failures"], "last_error": (state["last_error"] or "")[:300] or None,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
    except Exception as error:
        _db_failed(error)


def blocked_remaining(source: str) -> float:
    """Secondes de pause restantes pour `source` (0 = appels autorisés)."""
    with _state_lock:
        state = _load_state(source)
        blocked_until = state["blocked_until"]
    return max(0.0, blocked_until - time.time()) if blocked_until else 0.0


def record_rate_limit(source: str, error) -> None:
    """À appeler sur un vrai 429 : ouvre (ou prolonge) la pause."""
    with _state_lock:
        state = _load_state(source, force=True)
        state["failures"] += 1
        pause = pause_seconds(state["failures"])
        state["blocked_until"] = time.time() + pause
        state["last_error"] = str(error)[:300]
        _save_state(source, dict(state))
    log_event("circuit_open", source=source, pause_s=pause, consecutive_429=state["failures"],
              error=repr(error))


def record_success(source: str) -> None:
    """À appeler après un appel réussi : remet la pause à zéro. N'écrit en
    base que si l'état change réellement (pas à chaque succès)."""
    with _state_lock:
        state = _state.get(source)
        if state is None or (state["failures"] == 0 and state["blocked_until"] is None):
            return
        state.update(_empty_state())
        _save_state(source, dict(state))
    log_event("circuit_closed", source=source)


# -- Dernier prix connu ---------------------------------------------------------
#
# Alimenté UNIQUEMENT à partir de prix déjà obtenus d'une source live (jamais
# de requête dédiée), par l'app comme par les scripts du cron : c'est ce qui
# rompt la dépendance circulaire de l'ancien repli (market_price_snapshots,
# rempli seulement par le cron, lui-même bloqué quand Yahoo l'est). Une ligne
# par ticker (upsert), plutôt que market_price_snapshots : celle-ci est un
# historique (une ligne par passage du cron) servant aux variations sur 8
# jours de la page Admin News, et ne garde ni la devise réelle ni le prix
# natif — deux informations indispensables pour convertir correctement un
# prix daté en euros.
#
# Entrée : {"ticker", "price", "currency", "previous_close", "quote_type",
#           "market_time" (float|None), "fetched_at" (float),
#           "change_30d_pct", "change_30d_at" (float|None)}.

LAST_KNOWN_WRITE_INTERVAL_SECONDS = 5 * 60
_LAST_KNOWN_READ_TTL_SECONDS = 30

_known_lock = threading.Lock()
_known_memory: dict[str, dict] = {}
_known_written_at: dict[str, float] = {}
_known_db_read: dict[str, tuple[dict | None, float]] = {}


def remember_prices(entries: list[dict]) -> None:
    """Mémorise des prix frais. En base : au plus une écriture par ticker
    toutes les LAST_KNOWN_WRITE_INTERVAL_SECONDS (sauf nouvelle variation
    30 j), et tout un lot dans une seule transaction."""
    now = time.time()
    to_write = []
    with _known_lock:
        for entry in entries:
            if not entry or entry.get("price") is None or not entry.get("currency"):
                continue  # jamais de ligne vide : un échec ne remplace pas un bon prix
            ticker = entry["ticker"]
            _known_memory[ticker] = dict(entry)
            has_new_change = entry.get("change_30d_pct") is not None
            if has_new_change or now - _known_written_at.get(ticker, 0.0) >= LAST_KNOWN_WRITE_INTERVAL_SECONDS:
                _known_written_at[ticker] = now
                to_write.append(entry)
    if not to_write:
        return
    engine = _engine()
    if engine is None:
        return
    params = [{
        "ticker": e["ticker"], "price": float(e["price"]), "currency": e["currency"],
        "previous_close": e.get("previous_close"), "quote_type": e.get("quote_type") or None,
        "market_time": _to_iso(e.get("market_time")), "fetched_at": _to_iso(e["fetched_at"]),
        "change_30d_pct": e.get("change_30d_pct"), "change_30d_at": _to_iso(e.get("change_30d_at")),
    } for e in to_write]
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO last_known_prices (ticker, price, currency, previous_close, quote_type, "
                    "market_time, fetched_at, change_30d_pct, change_30d_at) VALUES (:ticker, :price, "
                    ":currency, :previous_close, :quote_type, :market_time, :fetched_at, :change_30d_pct, "
                    ":change_30d_at) ON CONFLICT (ticker) DO UPDATE SET "
                    "price = excluded.price, currency = excluded.currency, "
                    "previous_close = COALESCE(excluded.previous_close, last_known_prices.previous_close), "
                    "quote_type = COALESCE(excluded.quote_type, last_known_prices.quote_type), "
                    "market_time = COALESCE(excluded.market_time, last_known_prices.market_time), "
                    "fetched_at = excluded.fetched_at, "
                    "change_30d_pct = COALESCE(excluded.change_30d_pct, last_known_prices.change_30d_pct), "
                    "change_30d_at = COALESCE(excluded.change_30d_at, last_known_prices.change_30d_at) "
                    "WHERE excluded.fetched_at >= last_known_prices.fetched_at"
                ),
                params,
            )
    except Exception as error:
        _db_failed(error)


def _row_to_entry(row) -> dict:
    return {
        "ticker": row[0], "price": row[1], "currency": row[2], "previous_close": row[3],
        "quote_type": row[4] or "", "market_time": _from_iso(row[5]), "fetched_at": _from_iso(row[6]),
        "change_30d_pct": row[7], "change_30d_at": _from_iso(row[8]),
    }


def get_last_known(tickers) -> dict[str, dict]:
    """Derniers prix connus (mémoire du processus, complétée par la base,
    relue au plus toutes les 30 s par ticker). Ne fait JAMAIS d'appel à une
    API de marché. Tickers inconnus absents du résultat."""
    tickers = list(dict.fromkeys(tickers))
    now = time.time()
    result: dict[str, dict] = {}
    to_read = []
    with _known_lock:
        for ticker in tickers:
            memory = _known_memory.get(ticker)
            cached = _known_db_read.get(ticker)
            if cached and now - cached[1] < _LAST_KNOWN_READ_TTL_SECONDS:
                candidates = [e for e in (memory, cached[0]) if e]
                if candidates:
                    result[ticker] = max(candidates, key=lambda e: e["fetched_at"] or 0)
            else:
                to_read.append(ticker)
                if memory:
                    result[ticker] = memory
    if not to_read:
        return result
    engine = _engine()
    if engine is None:
        return result
    try:
        with engine.connect() as conn:
            rows = []
            for chunk_start in range(0, len(to_read), 100):
                chunk = to_read[chunk_start:chunk_start + 100]
                placeholders = ", ".join(f":t{i}" for i in range(len(chunk)))
                rows += conn.execute(
                    text("SELECT ticker, price, currency, previous_close, quote_type, market_time, "
                         f"fetched_at, change_30d_pct, change_30d_at FROM last_known_prices "
                         f"WHERE ticker IN ({placeholders})"),
                    {f"t{i}": t for i, t in enumerate(chunk)},
                ).fetchall()
    except Exception as error:
        _db_failed(error)
        return result
    from_db = {row[0]: _row_to_entry(row) for row in rows}
    with _known_lock:
        for ticker in to_read:
            entry = from_db.get(ticker)
            _known_db_read[ticker] = (entry, now)
            current = result.get(ticker)
            if entry and (current is None or (entry["fetched_at"] or 0) > (current["fetched_at"] or 0)):
                result[ticker] = entry
    return result
