"""Normalize run_id to canonical `<engine>_<timestamp>` form."""
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
    for known in KNOWN_ENGINES:
        if run_id.startswith(known + "_"):
            return False
    return True


def _db_plan(*, db_path: Path = DB_PATH) -> list[tuple[str, str, str]]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT run_id, engine FROM runs").fetchall()
    finally:
        conn.close()
    plan: list[tuple[str, str, str]] = []
    for run_id, engine in rows:
        if _needs_prefix(run_id, engine):
            plan.append((run_id, engine, f"{engine}_{run_id}"))
    return plan


def _index_plan(*, index_path: Path = INDEX_PATH) -> list[tuple[int, str, str, str]]:
    if not index_path.exists():
        return []
    data = json.loads(index_path.read_text(encoding="utf-8"))
    plan: list[tuple[int, str, str, str]] = []
    for idx, entry in enumerate(data):
        if not isinstance(entry, dict):
            continue
        run_id = entry.get("run_id")
        engine = (entry.get("engine") or entry.get("strategy") or "").lower().strip()
        if engine == "backtest":
            engine = "citadel"
        if not run_id or engine not in KNOWN_ENGINES:
            continue
        if _needs_prefix(run_id, engine):
            plan.append((idx, run_id, engine, f"{engine}_{run_id}"))
    return plan


def _apply_db(plan: list[tuple[str, str, str]], *, db_path: Path = DB_PATH) -> int:
    if not plan:
        return 0
    conn = sqlite3.connect(db_path)
    changes = 0
    try:
        for old, _engine, new in plan:
            existing = conn.execute("SELECT 1 FROM runs WHERE run_id=?", (new,)).fetchone()
            if existing:
                print(f"  ! skip {old} -> {new}: collision")
                continue
            conn.execute("UPDATE runs SET run_id=? WHERE run_id=?", (new, old))
            conn.execute("UPDATE trades SET run_id=? WHERE run_id=?", (new, old))
            changes += 1
        conn.commit()
    finally:
        conn.close()
    return changes


def _apply_index(plan: list[tuple[int, str, str, str]], *, index_path: Path = INDEX_PATH) -> int:
    if not plan:
        return 0
    data = json.loads(index_path.read_text(encoding="utf-8"))
    for idx, old, _engine, new in plan:
        if idx < len(data) and isinstance(data[idx], dict) and data[idx].get("run_id") == old:
            data[idx]["run_id"] = new
    index_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(plan)


def _dedupe_index(*, index_path: Path = INDEX_PATH) -> int:
    if not index_path.exists():
        return 0
    data = json.loads(index_path.read_text(encoding="utf-8"))
    seen: dict[str, int] = {}
    for idx, entry in enumerate(data):
        if isinstance(entry, dict) and entry.get("run_id"):
            seen[entry["run_id"]] = idx
    keep = set(seen.values())
    new_data = [
        entry
        for idx, entry in enumerate(data)
        if idx in keep or not (isinstance(entry, dict) and entry.get("run_id"))
    ]
    dropped = len(data) - len(new_data)
    if dropped:
        index_path.write_text(json.dumps(new_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return dropped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    db_plan = _db_plan()
    idx_plan = _index_plan()

    print(f"DB rows to rename: {len(db_plan)}")
    for old, _engine, new in db_plan[:10]:
        print(f"  {old}  -> {new}")
    if len(db_plan) > 10:
        print(f"  ...and {len(db_plan) - 10} more")

    print(f"\nIndex rows to rename: {len(idx_plan)}")
    for _, old, _engine, new in idx_plan[:10]:
        print(f"  {old}  -> {new}")
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
