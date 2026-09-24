"""Journalisation temporaire des appels aux sources de marché.

Active uniquement avec TS_DIAG_LOG=1. Ce module ne fait aucun appel réseau et
ne modifie pas la logique métier.
"""

import os
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone

_PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat()
_REQUESTS_BY_SOURCE: dict[str, deque[float]] = {}
_LOCK = threading.Lock()


def enabled() -> bool:
    return os.environ.get("TS_DIAG_LOG", "").lower() in {"1", "true", "yes", "on"}


_get_ctx = None  # résolu une fois : Streamlit absent dans le cron (pas de nouvel essai d'import par ligne)


def _session_id() -> str:
    global _get_ctx
    try:
        if _get_ctx is None:
            try:
                from streamlit.runtime.scriptrunner import get_script_run_ctx
                _get_ctx = get_script_run_ctx
            except Exception:
                _get_ctx = False
        if not _get_ctx:
            return "-"
        ctx = _get_ctx(suppress_warning=True)
        return getattr(ctx, "session_id", "-") if ctx else "-"
    except Exception:
        return "-"


def _caller() -> str:
    # sys._getframe plutôt qu'inspect.stack() : ce dernier lit le code source
    # de TOUTE la pile d'appels (contexte de lignes) à chaque ligne de log.
    # Ici, simple remontée des cadres, sans aucune lecture de fichier. On
    # saute diag_log et market_data/kraken_data pour nommer le vrai appelant.
    frame = sys._getframe(2)
    skipped = (__file__, "market_data.py", "kraken_data.py")
    while frame is not None and frame.f_code.co_filename.endswith(skipped):
        frame = frame.f_back
    if frame is None:
        return "unknown"
    return f"{os.path.basename(frame.f_code.co_filename)}:{frame.f_code.co_name}"


def log_process_start() -> None:
    if enabled():
        log("process_start", "system", "bootstrap", "-", "startup", 0.0, "-")


def log(
    issue: str,
    source: str,
    operation: str,
    tickers: str,
    kind: str,
    duration_seconds: float,
    raw_error: str = "-",
    real_request: bool = False,
) -> None:
    if not enabled():
        return
    now = time.time()
    with _LOCK:
        requests = _REQUESTS_BY_SOURCE.setdefault(source, deque())
        while requests and now - requests[0] > 60:
            requests.popleft()
        if real_request:
            requests.append(now)
        per_minute = len(requests)
    raw_error = str(raw_error).replace("\n", " ")[:500]
    print(
        f"[DIAG] ts={datetime.now(timezone.utc).isoformat()} pid={os.getpid()} "
        f"process_start={_PROCESS_STARTED_AT} session={_session_id()} "
        f"source={source} caller={_caller()} operation={operation} "
        f"tickers={tickers} kind={kind} issue={issue} "
        f"duration_ms={duration_seconds * 1000:.1f} requests_last_minute={per_minute} "
        f"raw_error={raw_error}",
        file=sys.stdout,
        flush=True,
    )
