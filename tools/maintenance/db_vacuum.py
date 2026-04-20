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
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = [r[0] for r in cur.fetchall()]
    sizes = []
    for name in names:
        cur.execute(f"SELECT COUNT(*) FROM '{name}'")
        sizes.append((name, cur.fetchone()[0]))
    con.close()
    return sorted(sizes, key=lambda x: -x[1])[:limit]


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

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_path = BACKUP_DIR / f"aurum.db.{stamp}.bak"
    shutil.copy2(DB_PATH, backup_path)
    print(f"\nbackup: {backup_path} ({human(backup_path.stat().st_size)})")

    con = sqlite3.connect(DB_PATH)
    con.execute("VACUUM")
    con.close()

    size_after = DB_PATH.stat().st_size
    print(f"\nsize after:  {human(size_after)}")
    print(f"delta:       {human(size_before - size_after)} freed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
