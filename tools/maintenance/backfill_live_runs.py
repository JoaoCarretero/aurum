"""Backfill the aurum.db live_runs table from existing run dirs and VPS.

Local-disk scan (default):
  Scans data/<engine>_{live,paper,shadow}/ for every known engine and
  inserts one row per dir into live_runs. Reads heartbeat.json if
  present for accurate status/metrics; otherwise marks as stopped.

VPS sync (--from-vps):
  Queries /v1/runs on the cockpit API and upserts every paper/shadow/
  live run the VPS reports. Fills the gap when local disk has no
  mirror of a VPS-only run (typical for the Windows dev box where
  services don't run locally).

Idempotent: first call inserts, later calls update mutable fields
only (respects the immutable-on-update guard in db_live_runs.upsert).
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from typing import Any

# Ensure the project root is on sys.path when this module is invoked
# directly as `python tools/maintenance/backfill_live_runs.py`. Without
# this, `from config.paths import DATA_DIR` fails on a fresh shell.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config.paths import DATA_DIR
from core.ops import db_live_runs

DATA_ROOT: Path = DATA_DIR

# Every engine × mode pairing we know about. Previous version only
# covered millennium_* — citadel/jump/renaissance/probe dirs were
# silently skipped, which is why the audit saw VPS runs with no DB
# counterpart even on machines where they had run locally.
_ENGINE_SLUGS = (
    "millennium", "citadel", "jump", "renaissance", "probe",
    "bridgewater", "deshaw", "janestreet", "twosigma", "aqr",
)
_MODES = ("live", "paper", "shadow")
_PARENT_TO_ENGINE_MODE: dict[str, tuple[str, str]] = {
    f"{engine}_{mode}": (engine, mode)
    for engine in _ENGINE_SLUGS
    for mode in _MODES
}
# Legacy catch-all dir from pre-per-engine days — keep so older runs
# still get catalogued.
_PARENT_TO_ENGINE_MODE["live"] = ("unknown", "live")


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
        _upsert_row(parsed)
    return n


def _upsert_row(parsed: dict[str, Any]) -> None:
    """Insert-or-update a single parsed row, respecting the immutable guard."""
    existing = db_live_runs.get_live_run(parsed["run_id"])
    if existing is None:
        db_live_runs.upsert(**parsed)
        return
    mutable_only = {"run_id": parsed["run_id"]}
    for key in ("ended_at", "status", "tick_count", "novel_count",
                "open_count", "equity", "last_tick_at", "notes"):
        if key in parsed and parsed[key] is not None:
            mutable_only[key] = parsed[key]
    if len(mutable_only) > 1:
        db_live_runs.upsert(**mutable_only)


def _parse_vps_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a /v1/runs payload into live_runs upsert fields.

    VPS runs don't have a local run_dir — we record a `vps://<run_id>`
    placeholder so the row has a non-null run_dir (required on insert)
    without pretending the files are on this disk.
    """
    run_id = row.get("run_id")
    if not run_id:
        return None
    engine = str(row.get("engine") or "").lower() or "unknown"
    mode = str(row.get("mode") or "").lower() or "unknown"
    status = str(row.get("status") or "unknown").lower()
    started_at = row.get("started_at")
    if not started_at:
        # Fall back to a synthetic stamp so the insert doesn't blow up;
        # marks the row clearly as VPS-sourced missing a real started_at.
        started_at = f"{run_id}T00:00:00+00:00"
    parsed: dict[str, Any] = {
        "run_id": str(run_id),
        "engine": engine,
        "mode": mode,
        "started_at": started_at,
        "status": status,
        "tick_count": int(row.get("ticks_ok") or 0),
        "novel_count": int(row.get("novel_total") or row.get("novel_count") or 0),
        "open_count": int(row.get("open_count") or 0),
        "equity": row.get("equity"),
        "last_tick_at": row.get("last_tick_at"),
        "host": row.get("host") or "vps",
        "label": row.get("label"),
        "run_dir": f"vps://{run_id}",
    }
    return parsed


def run_from_vps(*, dry_run: bool) -> tuple[int, int]:
    """Fetch /v1/runs and upsert each row. Returns (seen, written)."""
    from launcher_support.engines_live_view import _get_cockpit_client

    client = _get_cockpit_client()
    if client is None:
        print("!! cockpit client unavailable — check config/keys.json `cockpit_api`")
        return 0, 0
    try:
        rows = client._get("/v1/runs")
    except Exception as e:
        print(f"!! /v1/runs failed: {e}")
        return 0, 0
    if not isinstance(rows, list):
        print(f"!! unexpected /v1/runs payload: {type(rows).__name__}")
        return 0, 0

    seen = 0
    written = 0
    for row in rows:
        parsed = _parse_vps_row(row)
        if parsed is None:
            continue
        seen += 1
        if dry_run:
            continue
        _upsert_row(parsed)
        written += 1
    return seen, written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="Actually write to DB. Default is dry-run.")
    ap.add_argument("--from-vps", action="store_true",
                    help="Sync live_runs from VPS /v1/runs instead of local disk.")
    args = ap.parse_args(argv)
    if args.from_vps:
        seen, written = run_from_vps(dry_run=not args.apply)
        verb = "would upsert" if not args.apply else "upserted"
        print(f"{verb} {seen} VPS runs ({written} written)")
    else:
        n = run(dry_run=not args.apply)
        verb = "would backfill" if not args.apply else "backfilled"
        print(f"{verb} {n} run dirs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
