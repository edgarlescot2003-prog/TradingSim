"""Journalisation temporaire des appels aux sources de marché.

Active uniquement avec TS_DIAG_LOG=1. Ce module ne fait aucun appel réseau et
ne modifie pas la logique métier.
"""

import inspect
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


def _session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return getattr(ctx, "session_id", "-") if ctx else "-"
    except Exception:
        return "-"


def _caller() -> str:
    for frame in inspect.stack()[2:]:
        if frame.filename != __file__:
            return f"{os.path.basename(frame.filename)}:{frame.function}"
    return "unknown"


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
