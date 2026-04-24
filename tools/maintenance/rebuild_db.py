"""AURUM - rebuild data/aurum.db from disk reports."""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.ops.db import DB_PATH, save_run  # noqa: E402

DATA = ROOT / "data"

ENGINE_PATTERNS = {
    "citadel": (Path("runs"), "citadel_*_v*.json"),
    "bridgewater": (Path("bridgewater"), "*.json"),
    "jump": (Path("jump"), "*.json"),
    "deshaw": (Path("deshaw"), "*.json"),
    "renaissance": (Path("renaissance"), "*.json"),
    "millennium": (Path("millennium"), "*.json"),
    "twosigma": (Path("twosigma"), "*.json"),
    "aqr": (Path("aqr"), "*.json"),
    "janestreet": (Path("janestreet"), "*.json"),
    "kepos": (Path("kepos"), "*.json"),
    "medallion": (Path("medallion"), "*.json"),
    "graham": (Path("graham"), "*.json"),
    "phi": (Path("phi"), "*.json"),
}

SKIP_NAMES = {
    "config.json", "equity.json", "index.json", "overfit.json",
    "price_data.json", "summary.json", "trades.json",
    "simulate_historical.json",
}


def find_reports(*, data_dir: Path = DATA) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for engine, (root_rel, pattern) in ENGINE_PATTERNS.items():
        root = data_dir / root_rel
        if not root.exists():
            continue
        for run_dir in root.iterdir():
            if not run_dir.is_dir():
                continue
            if engine == "citadel":
                candidates = list(run_dir.glob(pattern))
            else:
                reports_dir = run_dir / "reports"
                if not reports_dir.exists():
                    continue
                candidates = list(reports_dir.glob(pattern))
            for path in candidates:
                if path.name not in SKIP_NAMES:
                    found.append((engine, path))
    return found


def backup_db(*, db_path: Path = DB_PATH, dry_run: bool = False, stamp: str | None = None) -> Path | None:
    if not db_path.exists():
        return None
    stamp = stamp or time.strftime("%Y-%m-%d_%H%M%S")
    dst = db_path.with_suffix(f".bak_{stamp}.db")
    if dry_run:
        print(f"[dry-run] backup DB -> {dst.name}")
        return dst
    shutil.copy2(db_path, dst)
    print(f"  backup DB -> {dst}")
    return dst


def wipe_db(*, db_path: Path = DB_PATH, dry_run: bool = False) -> None:
    if not db_path.exists():
        return
    if dry_run:
        print("[dry-run] DELETE FROM runs, trades (wipe)")
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM trades")
        conn.execute("DELETE FROM runs")
        seq_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
        ).fetchone()
        if seq_exists:
            conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('trades')")
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()
    print(f"  wiped DB ({db_path})")


def current_counts(*, db_path: Path = DB_PATH) -> tuple[int, int]:
    if not db_path.exists():
        return (0, 0)
    conn = sqlite3.connect(db_path)
    try:
        runs_n = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        trades_n = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    finally:
        conn.close()
    return (runs_n, trades_n)


def report_counts(reports: list[tuple[str, Path]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for engine, _path in reports:
        counts[engine] = counts.get(engine, 0) + 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="execute the wipe + rebuild (default: dry-run)")
    parser.add_argument("--no-backup", action="store_true", help="skip DB backup (dangerous)")
    args = parser.parse_args()

    dry = not args.apply

    print("=== AURUM DB rebuild ===")
    runs_n, trades_n = current_counts()
    if DB_PATH.exists():
        print(f"  current DB: {runs_n} runs · {trades_n} trades · {DB_PATH.stat().st_size / 1024 / 1024:.1f} MB")
    else:
        print("  current DB: missing")

    reports = find_reports()
    print(f"  reports found on disk: {len(reports)}")
    for engine in sorted(report_counts(reports)):
        print(f"    {engine:14s} {report_counts(reports)[engine]:4d}")

    if dry:
        print()
        print("[dry-run] would:")
        print("  1. backup DB")
        print("  2. DELETE FROM runs, trades (wipe)")
        print("  3. save_run() for each report found")
        print("  4. VACUUM")
        print()
        print("  re-run with --apply to execute.")
        return 0

    if not args.no_backup:
        backup_db(dry_run=False)

    wipe_db(dry_run=False)

    ok = 0
    fail = 0
    skipped = 0
    for idx, (engine, path) in enumerate(reports, start=1):
        try:
            run_id = save_run(engine, str(path))
            if run_id:
                ok += 1
            else:
                skipped += 1
        except Exception as exc:  # noqa: BLE001
            fail += 1
            print(f"  FAIL {path.name}: {type(exc).__name__}: {exc}")
        if idx % 25 == 0:
            print(f"  progress: {idx}/{len(reports)} (ok={ok}, skipped={skipped}, fail={fail})")

    print()
    print(f"  saved:   {ok}")
    print(f"  skipped: {skipped}")
    print(f"  failed:  {fail}")

    runs_n, trades_n = current_counts()
    print(f"  final DB: {runs_n} runs · {trades_n} trades · {DB_PATH.stat().st_size / 1024 / 1024:.1f} MB")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("VACUUM")
    print(f"  VACUUM done · {DB_PATH.stat().st_size / 1024 / 1024:.1f} MB")

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
