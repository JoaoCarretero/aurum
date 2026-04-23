"""Local procs snapshot + heartbeat file reader.

Pure module: no tkinter. Delegates to core.ops.proc.list_procs for the
actual procs ledger (which reads .aurum_procs.json and runs PID liveness
checks). Adds a module-level TTL cache (0.75s) matching the original
_list_procs_cached behaviour in engines_live_view.py.

Also exposes read_heartbeat() — a pure helper that reads
run_dir/state/heartbeat.json written by each runner on every tick.

Contract:
- list_procs(force=False) -> list[dict]
    Returns list of proc rows from core.ops.proc.list_procs.
    Each row has: engine, pid, started, log_file, status, alive, ...
    Uses TTL cache (0.75s) unless force=True. Returns [] on any error.

- read_heartbeat(run_dir: Path) -> dict | None
    Reads run_dir/state/heartbeat.json. Returns None if missing/malformed.

- reset_cache_for_tests() -> None
    Test-only: clear cache state. Never call from production code.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

CACHE_TTL_S: float = 0.75

_CACHE_STATE: dict = {"ts": 0.0, "rows": None}
_CACHE_LOCK = threading.Lock()


def reset_cache_for_tests() -> None:
    """Test-only: clear cache state. Never call from production code."""
    with _CACHE_LOCK:
        _CACHE_STATE["ts"] = 0.0
        _CACHE_STATE["rows"] = None


def list_procs(force: bool = False) -> list[dict]:
    """Return proc rows from core.ops.proc.list_procs with a TTL cache.

    Delegates liveness checking and JSON parsing to core.ops.proc which
    reads data/.aurum_procs.json and verifies PID identity (Fase 1 / D5).
    This module adds a 0.75s cache on top, matching the original
    _list_procs_cached in engines_live_view.py.

    Returns [] on any error (silent — not the caller's job to handle
    proc-manager failures).
    """
    now = time.monotonic()
    if not force:
        with _CACHE_LOCK:
            rows = _CACHE_STATE["rows"]
            age = now - _CACHE_STATE["ts"]
            if rows is not None and age < CACHE_TTL_S:
                return list(rows)

    try:
        from core.ops.proc import list_procs as _core_list_procs
        rows = _core_list_procs()
    except Exception:
        rows = []

    with _CACHE_LOCK:
        _CACHE_STATE["ts"] = time.monotonic()
        _CACHE_STATE["rows"] = list(rows)
    return list(rows)


def read_heartbeat(run_dir: Path) -> dict | None:
    """Read <run_dir>/state/heartbeat.json. Returns None if missing/malformed.

    heartbeat.json is written by each runner on every tick and contains
    fields like: status, ticks_ok, novel_total, run_id, ts, equity, ...
    """
    hb_path = Path(run_dir) / "state" / "heartbeat.json"
    if not hb_path.exists():
        return None
    try:
        return json.loads(hb_path.read_text(encoding="utf-8"))
    except Exception:
        return None
