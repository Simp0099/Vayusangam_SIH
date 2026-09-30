"""Shared helpers for VayuSangam data collectors: UTC handling, atomic writes,
key redaction, and structured collection logging."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# common/ -> data_collection -> scripts -> repo root
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs" / "data_collection"

# Everything the pipeline stores internally is UTC. Asia/Kolkata is a display
# concern only and is never used to interpret a source timestamp.
UTC = timezone.utc
DISPLAY_TZ = "Asia/Kolkata"

SECRET_PATTERNS = [
    # Credentials in query strings: ?api_key=…&limit=1
    re.compile(r"(?i)([?&](?:key|api_key|apikey|token|access_token|MAP_KEY)=)[^&\s]+"),
    # FIRMS embeds the key as the final path segment: /area/csv/<src>/<bbox>/<days>/<KEY>.
    # The trailing delimiter is optional: httpx error messages end with the bare key.
    re.compile(r"(?i)/[A-Za-z0-9_\-]{16,}(?=[/?#\s'\"]|$)"),
    # Bare long hex/alphanumeric tokens anywhere else.
    re.compile(r"(?<![A-Za-z0-9])[0-9a-fA-F]{32,}(?![A-Za-z0-9])"),
]


def redact(text: str) -> str:
    """Remove credential-shaped substrings before anything is logged or stored.

    Covers both query-string keys and path-embedded keys such as the NASA FIRMS
    MAP_KEY, which does not appear as a named parameter and would otherwise be
    written verbatim into logs and manifests.
    """
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(r"\1<REDACTED>" if pattern.groups else "<REDACTED>", text)
    return text


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write(path: Path, payload: str) -> None:
    """Write via a temp file + rename so an interrupted run never leaves a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def cache_path(folder: Path, name: str, query: dict[str, Any]) -> Path:
    """Deterministic cache filename: same query -> same file, so reruns resume."""
    digest = hashlib.sha256(json.dumps(query, sort_keys=True, default=str).encode()).hexdigest()[:12]
    return folder / f"{name}_{digest}.json"


def log_event(source: str, operation: str, status: str, records: int = 0,
              duration_s: float = 0.0, request: str = "", error: str = "") -> None:
    """Append one structured line. Keys and tokens never reach this file."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    row = {"timestamp": now_utc_iso(), "source": source, "operation": operation,
           "request": redact(request), "status": status, "records": records,
           "duration_s": round(duration_s, 3), "error": redact(error)[:500]}
    with (LOG_DIR / "data_collection.log").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def timed():
    """Context manager that logs an operation's status and duration."""
    from contextlib import contextmanager

    @contextmanager
    def _cm(source: str, operation: str, request: str = ""):
        started = time.time()
        try:
            yield
        except Exception as exc:
            log_event(source, operation, "ERROR", 0, time.time() - started, request, f"{type(exc).__name__}: {exc}")
            raise
        else:
            log_event(source, operation, "OK", 0, time.time() - started, request)

    return _cm
