"""Backfill aurum.db from disk run dirs.

Walks every engine dir under data/ and calls core.db.save_run() for any run
whose run_id is not already in the DB. Also ingests the legacy data/runs/
citadel layout.

Usage:
    python tools/maintenance/backfill_db_from_disk.py           # dry-run (report only)
    python tools/maintenance/backfill_db_from_disk.py --apply   # actually insert

Exit codes:
    0 — clean or applied
    1 — drift detected in dry-run
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data"
DB_PATH = DATA / "aurum.db"

# Engine dir → canonical engine name for save_run().
ENGINE_DIRS = {
    "bridgewater": "bridgewater",
    "citadel":     "citadel",
    "deshaw":      "deshaw",
    "jump":        "jump",
    "renaissance": "renaissance",
    "millennium":  "millennium",
    "twosigma":    "twosigma",
    "janestreet":  "janestreet",
    "aqr":         "aqr",
    "runs":        "citadel",  # legacy layout
}


def _find_report_json(run_dir: Path) -> Path | None:
    """Locate the primary run report JSON inside a run dir.

    Priority:
      1. reports/<engine>_*.json  (new layout)
      2. <engine>_*.json          (legacy flat layout, e.g. data/runs/)
      3. summary.json              (fallback)
    """
    reports = run_dir / "reports"
    if reports.is_dir():
        for p in reports.glob("*.json"):
            name = p.name.lower()
            if name == "config.json" or name == "equity.json":
                continue
            return p
    # legacy flat layout
    for p in run_dir.glob("*.json"):
        name = p.name.lower()
        if name in ("config.json", "equity.json", "summary.json", "overfit.json"):
            continue
        return p
    summary = run_dir / "summary.json"
    if summary.is_file():
        return summary
    return None


def _db_run_ids() -> set[str]:
    if not DB_PATH.exists():
        return set()
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute("SELECT run_id FROM runs").fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def _walk_disk() -> list[tuple[str, Path, Path]]:
    """Yield (engine, run_dir, report_json) for every run dir on disk."""
    out: list[tuple[str, Path, Path]] = []
    for parent_name, engine in ENGINE_DIRS.items():
        parent = DATA / parent_name
        if not parent.is_dir():
            continue
        for d in parent.iterdir():
            if not d.is_dir():
                continue
            report = _find_report_json(d)
            if report is None:
                continue
            out.append((engine, d, report))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="actually insert missing runs into the DB")
    args = ap.parse_args()

    existing = _db_run_ids()
    disk = _walk_disk()

    # A run_id on disk may already be in DB under either its bare or
    # engine-prefixed form. We treat both as "covered".
    covered = set(existing)
    missing: list[tuple[str, Path, Path]] = []
    for engine, run_dir, report in disk:
        rid_bare = run_dir.name
        rid_pref = f"{engine}_{rid_bare}" if not rid_bare.startswith(engine + "_") else rid_bare
        if rid_bare in covered or rid_pref in covered:
            continue
        missing.append((engine, run_dir, report))

    print(f"DB has {len(existing)} run rows")
    print(f"Disk has {len(disk)} run dirs (with a report JSON)")
    print(f"Missing from DB: {len(missing)}")

    if not missing:
        return 0

    # Group by engine for readability
    by_engine: dict[str, int] = {}
    for engine, _, _ in missing:
        by_engine[engine] = by_engine.get(engine, 0) + 1
    for engine, n in sorted(by_engine.items()):
        print(f"  {engine}: {n}")

    if not args.apply:
        print("\nDry-run. Re-run with --apply to ingest.")
        return 1

    # Import lazily so --help works even if core.db can't import.
    sys.path.insert(0, str(ROOT))
    from core.db import save_run

    ok = 0
    fail = 0
    for engine, run_dir, report in missing:
        try:
            rid = save_run(engine, str(report))
            if rid:
                ok += 1
            else:
                fail += 1
                print(f"  ! {engine}/{run_dir.name}: save_run returned None")
        except Exception as e:
            fail += 1
            print(f"  ! {engine}/{run_dir.name}: {type(e).__name__}: {e}")

    print(f"\nIngested: {ok}  Failed: {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
