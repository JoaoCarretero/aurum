"""Backfill aurum.db from disk run dirs."""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data"
DB_PATH = DATA / "aurum.db"

ENGINE_DIRS = {
    "bridgewater": "bridgewater",
    "citadel": "citadel",
    "deshaw": "deshaw",
    "jump": "jump",
    "renaissance": "renaissance",
    "millennium": "millennium",
    "twosigma": "twosigma",
    "janestreet": "janestreet",
    "aqr": "aqr",
    "runs": "citadel",
}


def find_report_json(run_dir: Path) -> Path | None:
    reports = run_dir / "reports"
    if reports.is_dir():
        for path in reports.glob("*.json"):
            if path.name.lower() not in {"config.json", "equity.json"}:
                return path
    for path in run_dir.glob("*.json"):
        if path.name.lower() not in {"config.json", "equity.json", "summary.json", "overfit.json"}:
            return path
    summary = run_dir / "summary.json"
    return summary if summary.is_file() else None


def db_run_ids(*, db_path: Path = DB_PATH) -> set[str]:
    if not db_path.exists():
        return set()
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT run_id FROM runs").fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def walk_disk(*, data_dir: Path = DATA) -> list[tuple[str, Path, Path]]:
    out: list[tuple[str, Path, Path]] = []
    for parent_name, engine in ENGINE_DIRS.items():
        parent = data_dir / parent_name
        if not parent.is_dir():
            continue
        for run_dir in parent.iterdir():
            if not run_dir.is_dir():
                continue
            report = find_report_json(run_dir)
            if report is not None:
                out.append((engine, run_dir, report))
    return out


def missing_runs(
    *,
    existing_ids: set[str],
    disk_runs: list[tuple[str, Path, Path]],
) -> list[tuple[str, Path, Path]]:
    covered = set(existing_ids)
    missing: list[tuple[str, Path, Path]] = []
    for engine, run_dir, report in disk_runs:
        run_id_bare = run_dir.name
        run_id_pref = run_id_bare if run_id_bare.startswith(engine + "_") else f"{engine}_{run_id_bare}"
        if run_id_bare in covered or run_id_pref in covered:
            continue
        missing.append((engine, run_dir, report))
    return missing


def group_missing(missing: list[tuple[str, Path, Path]]) -> dict[str, int]:
    grouped: dict[str, int] = {}
    for engine, _run_dir, _report in missing:
        grouped[engine] = grouped.get(engine, 0) + 1
    return grouped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually insert missing runs into the DB")
    args = parser.parse_args()

    existing = db_run_ids()
    disk = walk_disk()
    missing = missing_runs(existing_ids=existing, disk_runs=disk)

    print(f"DB has {len(existing)} run rows")
    print(f"Disk has {len(disk)} run dirs (with a report JSON)")
    print(f"Missing from DB: {len(missing)}")

    if not missing:
        return 0

    for engine, count in sorted(group_missing(missing).items()):
        print(f"  {engine}: {count}")

    if not args.apply:
        print("\nDry-run. Re-run with --apply to ingest.")
        return 1

    sys.path.insert(0, str(ROOT))
    from core.ops.db import save_run

    ok = 0
    fail = 0
    for engine, run_dir, report in missing:
        try:
            run_id = save_run(engine, str(report))
            if run_id:
                ok += 1
            else:
                fail += 1
                print(f"  ! {engine}/{run_dir.name}: save_run returned None")
        except Exception as exc:  # noqa: BLE001
            fail += 1
            print(f"  ! {engine}/{run_dir.name}: {type(exc).__name__}: {exc}")

    print(f"\nIngested: {ok}  Failed: {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
