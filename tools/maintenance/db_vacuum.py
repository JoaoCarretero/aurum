"""VACUUM data/aurum.db safely: backup first, close connections, report sizes.

Usage:
    python tools/maintenance/db_vacuum.py           # dry-run
    python tools/maintenance/db_vacuum.py --apply   # backup + VACUUM
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "aurum.db"
BACKUP_DIR = Path.home() / "aurum-backups"


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def top_tables(db: Path, limit: int = 5) -> list[tuple[str, int]]:
    with sqlite3.connect(db) as con:
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        names = [r[0] for r in cur.fetchall()]
        sizes = []
        for name in names:
            quoted_name = '"' + str(name).replace('"', '""') + '"'
            cur.execute(f"SELECT COUNT(*) FROM {quoted_name}")
            sizes.append((name, cur.fetchone()[0]))
    return sorted(sizes, key=lambda x: -x[1])[:limit]


def backup_db(db_path: Path, backup_dir: Path, *, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{db_path.name}.{stamp}.bak"
    shutil.copy2(db_path, backup_path)
    return backup_path


def run_vacuum(db_path: Path, *, backup_dir: Path = BACKUP_DIR, now: datetime | None = None) -> tuple[Path, int, int]:
    size_before = db_path.stat().st_size
    backup_path = backup_db(db_path, backup_dir, now=now)
    with sqlite3.connect(db_path, timeout=5.0) as con:
        con.execute("VACUUM")
    size_after = db_path.stat().st_size
    return backup_path, size_before, size_after


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Actually run VACUUM")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}", file=sys.stderr)
        return 1

    size_before = DB_PATH.stat().st_size
    print(f"DB: {DB_PATH}")
    print(f"size before: {human(size_before)}")
    print(f"top tables (by row count):")
    for name, rows in top_tables(DB_PATH):
        print(f"  {name}: {rows:,} rows")

    if not args.apply:
        print("\ndry-run — pass --apply to VACUUM")
        return 0

    try:
        backup_path, _size_before, size_after = run_vacuum(DB_PATH)
    except sqlite3.OperationalError as e:
        print(f"\nVACUUM failed: {e}", file=sys.stderr)
        print(f"Backup preserved at {BACKUP_DIR}", file=sys.stderr)
        print("Hint: stop launcher/cockpit/live engines holding the DB, then retry.", file=sys.stderr)
        return 2

    print(f"\nbackup: {backup_path} ({human(backup_path.stat().st_size)})")
    print(f"\nsize after:  {human(size_after)}")
    print(f"delta:       {human(size_before - size_after)} freed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
