"""Backfill the aurum.db live_runs table from existing run dirs.

Scans data/millennium_{live,paper,shadow}/ and data/live/ and inserts
one row per dir into live_runs. Reads heartbeat.json if present for
accurate status/metrics; otherwise marks as stopped with zero counters.

Idempotent: first run inserts, subsequent runs update mutable fields
only (respects the immutable-on-update guard in db_live_runs.upsert).
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from typing import Any

from config.paths import DATA_DIR
from core.ops import db_live_runs

DATA_ROOT: Path = DATA_DIR

_PARENT_TO_ENGINE_MODE: dict[str, tuple[str, str]] = {
    "millennium_live":   ("millennium", "live"),
    "millennium_paper":  ("millennium", "paper"),
    "millennium_shadow": ("millennium", "shadow"),
    "live":              ("unknown",    "live"),
}


def _parse_dir(run_dir: Path) -> dict[str, Any] | None:
    parent = run_dir.parent.name
    entry = _PARENT_TO_ENGINE_MODE.get(parent)
    if entry is None:
        return None
    engine, mode = entry
    heartbeat_path = run_dir / "state" / "heartbeat.json"
    hb: dict[str, Any] = {}
    if heartbeat_path.exists():
        try:
            hb = json.loads(heartbeat_path.read_text())
        except (json.JSONDecodeError, OSError):
            hb = {}
    # status: prefer heartbeat's value; fall back to "stopped" if no
    # heartbeat, or "unknown" if heartbeat exists but lacks status key.
    # Final override: if we have a heartbeat but no last_tick_at, force
    # "stopped" — a runner with status='running' but no last tick is dead.
    run_id = hb.get("run_id") or f"{parent}_{run_dir.name}"
    started_at = hb.get("started_at") or f"{run_dir.name}T00:00:00+00:00"
    last_tick_at = hb.get("last_tick_at")
    status = hb.get("status") or ("stopped" if not hb else "unknown")
    if hb and not last_tick_at:
        status = "stopped"
    return {
        "run_id": run_id,
        "engine": engine,
        "mode": mode,
        "started_at": started_at,
        "status": status,
        "tick_count": int(hb.get("ticks_ok") or 0),
        "novel_count": int(hb.get("novel_total") or 0),
        "open_count": int(hb.get("open_count") or 0),
        "equity": hb.get("equity"),
        "last_tick_at": last_tick_at,
        "host": hb.get("host") or socket.gethostname(),
        "label": hb.get("label"),
        "run_dir": str(run_dir.relative_to(DATA_ROOT.parent)),
    }


def _iter_run_dirs() -> list[Path]:
    dirs: list[Path] = []
    for parent_name in _PARENT_TO_ENGINE_MODE:
        parent = DATA_ROOT / parent_name
        if not parent.exists():
            continue
        dirs.extend(d for d in parent.iterdir() if d.is_dir())
    return dirs


def run(*, dry_run: bool) -> int:
    """Scan run dirs and populate live_runs. Returns number of dirs processed."""
    n = 0
    for run_dir in _iter_run_dirs():
        parsed = _parse_dir(run_dir)
        if parsed is None:
            continue
        n += 1
        if dry_run:
            continue
        existing = db_live_runs.get_live_run(parsed["run_id"])
        if existing is None:
            db_live_runs.upsert(**parsed)
        else:
            # Row already exists — only pass mutable fields to avoid
            # ValueError from the immutable-on-update guard in upsert().
            mutable_only = {
                "run_id": parsed["run_id"],
                "status": parsed["status"],
                "tick_count": parsed["tick_count"],
                "novel_count": parsed["novel_count"],
                "open_count": parsed["open_count"],
                "equity": parsed["equity"],
                "last_tick_at": parsed["last_tick_at"],
            }
            db_live_runs.upsert(**mutable_only)
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="Actually write to DB. Default is dry-run.")
    args = ap.parse_args(argv)
    n = run(dry_run=not args.apply)
    verb = "would backfill" if not args.apply else "backfilled"
    print(f"{verb} {n} run dirs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
