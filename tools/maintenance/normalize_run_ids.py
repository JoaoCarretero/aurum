"""Normalize run_id to canonical `<engine>_<timestamp>` form.

The rename commit `5e055d3 fix(index+launcher): run_id prefixado` made the
prefixed form canonical, but legacy rows (DB + index.json) still carry bare
timestamps for runs written before that change. This tool migrates them.

Usage:
    python tools/maintenance/normalize_run_ids.py           # dry-run
    python tools/maintenance/normalize_run_ids.py --apply
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "aurum.db"
INDEX_PATH = ROOT / "data" / "index.json"

KNOWN_ENGINES = {
    "citadel", "bridgewater", "jump", "deshaw", "renaissance",
    "millennium", "twosigma", "janestreet", "aqr",
}


def _needs_prefix(run_id: str, engine: str) -> bool:
    if not run_id or not engine:
        return False
    if run_id.startswith(engine + "_"):
        return False
    # Already prefixed by a different known engine (weird but leave alone)
    for e in KNOWN_ENGINES:
        if run_id.startswith(e + "_"):
            return False
    return True


def _db_plan() -> list[tuple[str, str, str]]:
    """Return [(old_run_id, engine, new_run_id)] for DB rows that need rename."""
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute("SELECT run_id, engine FROM runs").fetchall()
    finally:
        conn.close()
    plan: list[tuple[str, str, str]] = []
    for rid, eng in rows:
        if _needs_prefix(rid, eng):
            plan.append((rid, eng, f"{eng}_{rid}"))
    return plan


def _index_plan() -> list[tuple[int, str, str, str]]:
    """Return [(row_idx, old_run_id, engine, new_run_id)] for index entries
    that need rename. Engine inferred from entry fields."""
    if not INDEX_PATH.exists():
        return []
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    plan: list[tuple[int, str, str, str]] = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            continue
        rid = entry.get("run_id")
        eng = (entry.get("engine") or entry.get("strategy") or "").lower().strip()
        if eng in {"backtest"}:
            eng = "citadel"
        if not rid or not eng or eng not in KNOWN_ENGINES:
            continue
        if _needs_prefix(rid, eng):
            plan.append((i, rid, eng, f"{eng}_{rid}"))
    return plan


def _apply_db(plan: list[tuple[str, str, str]]) -> int:
    if not plan:
        return 0
    conn = sqlite3.connect(DB_PATH)
    changes = 0
    try:
        for old, eng, new in plan:
            # Skip if new id already exists (collision)
            existing = conn.execute(
                "SELECT 1 FROM runs WHERE run_id=?", (new,)
            ).fetchone()
            if existing:
                print(f"  ! skip {old} → {new}: collision")
                continue
            conn.execute("UPDATE runs SET run_id=? WHERE run_id=?", (new, old))
            conn.execute("UPDATE trades SET run_id=? WHERE run_id=?", (new, old))
            changes += 1
        conn.commit()
    finally:
        conn.close()
    return changes


def _apply_index(plan: list[tuple[int, str, str, str]]) -> int:
    if not plan:
        return 0
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    for idx, old, _eng, new in plan:
        if idx < len(data) and isinstance(data[idx], dict) and data[idx].get("run_id") == old:
            data[idx]["run_id"] = new
    INDEX_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return len(plan)


def _dedupe_index() -> int:
    """Drop duplicate entries in index.json (same run_id). Keep the LAST
    one (assumed to be the most recent write)."""
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    seen: dict[str, int] = {}
    for i, entry in enumerate(data):
        if isinstance(entry, dict) and entry.get("run_id"):
            seen[entry["run_id"]] = i  # last wins
    keep = set(seen.values())
    new = [e for i, e in enumerate(data) if i in keep or not (isinstance(e, dict) and e.get("run_id"))]
    dropped = len(data) - len(new)
    if dropped:
        INDEX_PATH.write_text(
            json.dumps(new, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return dropped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db_plan = _db_plan()
    idx_plan = _index_plan()

    print(f"DB rows to rename: {len(db_plan)}")
    for old, eng, new in db_plan[:10]:
        print(f"  {old}  ->{new}")
    if len(db_plan) > 10:
        print(f"  ...and {len(db_plan) - 10} more")

    print(f"\nIndex rows to rename: {len(idx_plan)}")
    for _, old, _eng, new in idx_plan[:10]:
        print(f"  {old}  ->{new}")
    if len(idx_plan) > 10:
        print(f"  ...and {len(idx_plan) - 10} more")

    if not args.apply:
        print("\nDry-run only. Re-run with --apply.")
        return 0 if not (db_plan or idx_plan) else 1

    db_n = _apply_db(db_plan)
    idx_n = _apply_index(idx_plan)
    dedup_n = _dedupe_index()

    print(f"\nDB renames: {db_n}")
    print(f"Index renames: {idx_n}")
    print(f"Index dupes dropped: {dedup_n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
