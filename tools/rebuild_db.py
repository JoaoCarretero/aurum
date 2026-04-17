"""AURUM — rebuild data/aurum.db from disk reports (index.json + engine dirs).

Fonte de verdade: os JSON reports no disco (`data/<engine>/<run_id>/reports/*.json`
e `data/runs/<run_id>/citadel_*_v*.json`). Este script varre tudo, limpa
DB runs/trades e re-executa `core.db.save_run()` pra cada report válido.

Corrige o drift entre DB e index.json observado em 2026-04-17: 155 runs
no DB sem entry no index, 102 entries no index sem row no DB. O rebuild
a partir do disco garante consistência forte.

Uso:
    python tools/rebuild_db.py                 # dry-run
    python tools/rebuild_db.py --apply         # backup + wipe + rebuild
    python tools/rebuild_db.py --apply --no-backup
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.db import DB_PATH, save_run  # noqa: E402

DATA = ROOT / "data"
INDEX = DATA / "index.json"

# Mapa engine -> pasta root + padrão do JSON file dentro de reports/.
ENGINE_PATTERNS = {
    "citadel":     (DATA / "runs",          "citadel_*_v*.json"),
    "bridgewater": (DATA / "bridgewater",   "*.json"),
    "jump":        (DATA / "jump",          "*.json"),
    "deshaw":      (DATA / "deshaw",        "*.json"),
    "renaissance": (DATA / "renaissance",   "*.json"),
    "millennium":  (DATA / "millennium",    "*.json"),
    "twosigma":    (DATA / "twosigma",      "*.json"),
    "aqr":         (DATA / "aqr",           "*.json"),
    "janestreet":  (DATA / "janestreet",    "*.json"),
    "kepos":       (DATA / "kepos",         "*.json"),
    "medallion":   (DATA / "medallion",     "*.json"),
    "graham":      (DATA / "graham",        "*.json"),
    "phi":         (DATA / "phi",           "*.json"),
}

SKIP_NAMES = {
    "config.json", "equity.json", "index.json", "overfit.json",
    "price_data.json", "summary.json", "trades.json",
    "simulate_historical.json",
}


def _find_reports() -> list[tuple[str, Path]]:
    """Return list of (engine_slug, json_path) — report JSONs only."""
    found: list[tuple[str, Path]] = []
    for engine, (root, pattern) in ENGINE_PATTERNS.items():
        if not root.exists():
            continue
        for run_dir in root.iterdir():
            if not run_dir.is_dir():
                continue
            # CITADEL: reports no próprio run_dir
            # Outros engines: reports em run_dir/reports/
            if engine == "citadel":
                candidates = list(run_dir.glob(pattern))
            else:
                reports_dir = run_dir / "reports"
                if not reports_dir.exists():
                    continue
                candidates = list(reports_dir.glob(pattern))
            for p in candidates:
                if p.name in SKIP_NAMES:
                    continue
                # mais recente primeiro por mtime
                found.append((engine, p))
    return found


def _backup_db(dry_run: bool) -> Path | None:
    if not DB_PATH.exists():
        return None
    ts = time.strftime("%Y-%m-%d_%H%M%S")
    dst = DB_PATH.with_suffix(f".bak_{ts}.db")
    if dry_run:
        print(f"[dry-run] backup DB -> {dst.name}")
        return dst
    shutil.copy2(DB_PATH, dst)
    print(f"  backup DB -> {dst}")
    return dst


def _wipe_db(dry_run: bool) -> None:
    if not DB_PATH.exists():
        return
    if dry_run:
        print(f"[dry-run] DELETE FROM runs, trades (wipe)")
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("DELETE FROM trades")
        conn.execute("DELETE FROM runs")
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('trades')")
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()
    print(f"  wiped DB ({DB_PATH})")


def _current_counts() -> tuple[int, int]:
    if not DB_PATH.exists():
        return (0, 0)
    conn = sqlite3.connect(DB_PATH)
    try:
        rn = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        tn = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    finally:
        conn.close()
    return (rn, tn)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="execute the wipe + rebuild (default: dry-run)")
    ap.add_argument("--no-backup", action="store_true",
                    help="skip DB backup (dangerous)")
    args = ap.parse_args()

    dry = not args.apply

    print("=== AURUM DB rebuild ===")
    r0, t0 = _current_counts()
    print(f"  current DB: {r0} runs · {t0} trades · {DB_PATH.stat().st_size / 1024 / 1024:.1f} MB" if DB_PATH.exists() else "  current DB: missing")

    reports = _find_reports()
    print(f"  reports found on disk: {len(reports)}")
    per_engine: dict[str, int] = {}
    for eng, _ in reports:
        per_engine[eng] = per_engine.get(eng, 0) + 1
    for eng in sorted(per_engine):
        print(f"    {eng:14s} {per_engine[eng]:4d}")

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
        _backup_db(False)

    _wipe_db(False)

    ok = 0
    fail = 0
    skipped = 0
    for i, (engine, path) in enumerate(reports, start=1):
        try:
            rid = save_run(engine, str(path))
            if rid:
                ok += 1
            else:
                skipped += 1
        except Exception as exc:  # noqa: BLE001
            fail += 1
            print(f"  FAIL {path.name}: {type(exc).__name__}: {exc}")
        if i % 25 == 0:
            print(f"  progress: {i}/{len(reports)} (ok={ok}, skipped={skipped}, fail={fail})")

    print()
    print(f"  saved:   {ok}")
    print(f"  skipped: {skipped}")
    print(f"  failed:  {fail}")

    r1, t1 = _current_counts()
    print(f"  final DB: {r1} runs · {t1} trades · "
          f"{DB_PATH.stat().st_size / 1024 / 1024:.1f} MB")

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()
    print(f"  VACUUM done · {DB_PATH.stat().st_size / 1024 / 1024:.1f} MB")

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
