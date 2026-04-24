"""Audit live engines — VPS vs DB vs local disk.

For every engine running (or recently stopped) in paper/shadow mode:
  - What the VPS cockpit reports (runs + trades + positions)
  - What the local DB (data/aurum.db :: live_runs, trades) has
  - What's on local disk (data/<engine>_<mode>/<run_id>/)
  - Mismatches: VPS running but missing from DB, DB stopped but disk has
    newer heartbeat, orphaned trades, etc.

Read-only. Run: `python tools/diag/live_engines_audit.py`
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Windows default stdout is cp1252 — we print non-ASCII chars (·, ⚠, ✔, …)
# so force UTF-8 to avoid UnicodeEncodeError halfway through the audit.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from launcher_support.engines_live_view import _get_cockpit_client


DB_PATH = ROOT / "data" / "aurum.db"
DATA_DIR = ROOT / "data"


def _vps_runs(client) -> list[dict]:
    try:
        rows = client._get("/v1/runs")
    except Exception as e:
        print(f"!! /v1/runs failed: {e}")
        return []
    return list(rows) if isinstance(rows, list) else []


def _vps_trades_count(client, run_id: str) -> tuple[int | None, list[dict], str | None]:
    """Returns (count, trades, error). count=None means VPS fetch failed
    — distinct from count=0 meaning the run really has no trades."""
    try:
        payload = client._get(f"/v1/runs/{run_id}/trades?limit=50")
    except Exception as e:
        return None, [], str(e)[:80]
    if not isinstance(payload, dict):
        return None, [], f"unexpected payload {type(payload).__name__}"
    trades = [t for t in (payload.get("trades") or [])
              if isinstance(t, dict) and not t.get("primed", False)]
    count = payload.get("count")
    return (int(count) if isinstance(count, int) else len(trades)), trades, None


def _vps_positions_count(client, run_id: str) -> tuple[int | None, str | None]:
    try:
        payload = client._get(f"/v1/runs/{run_id}/positions")
    except Exception as e:
        return None, str(e)[:80]
    if not isinstance(payload, dict):
        return None, f"unexpected payload {type(payload).__name__}"
    return len(payload.get("positions") or []), None


def _db_live_runs() -> list[dict]:
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT run_id, engine, mode, status, started_at, last_tick_at, "
            "tick_count, novel_count, open_count FROM live_runs"
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _db_trades_by_run() -> dict[str, int]:
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT run_id, COUNT(*) n FROM trades GROUP BY run_id"
        )
        return {str(r["run_id"]): int(r["n"]) for r in cur.fetchall()}
    finally:
        conn.close()


def _local_dirs_by_engine_mode() -> dict[tuple[str, str], list[str]]:
    """Map (engine, mode) -> list of run_id dirs on disk."""
    out: dict[tuple[str, str], list[str]] = defaultdict(list)
    if not DATA_DIR.exists():
        return dict(out)
    for sub in DATA_DIR.iterdir():
        if not sub.is_dir():
            continue
        name = sub.name
        # Pattern: <engine>_<mode>  (e.g. millennium_paper, citadel_shadow)
        for mode in ("paper", "shadow"):
            suffix = f"_{mode}"
            if name.endswith(suffix):
                engine = name[: -len(suffix)]
                try:
                    run_dirs = [p.name for p in sub.iterdir() if p.is_dir()]
                except OSError:
                    run_dirs = []
                out[(engine, mode)].extend(run_dirs)
                break
    return dict(out)


def main() -> int:
    client = _get_cockpit_client()
    if client is None:
        print("!! cockpit client unavailable — check config/keys.json")
        return 1

    print("== LIVE ENGINES AUDIT ==\n")

    # 1. VPS side
    vps_runs = _vps_runs(client)
    vps_paper_shadow = [
        r for r in vps_runs
        if str(r.get("mode") or "").lower() in ("paper", "shadow")
    ]
    print(f"VPS runs (paper+shadow): {len(vps_paper_shadow)}")
    # group by engine+mode
    by_engine_mode: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in vps_paper_shadow:
        key = (
            str(r.get("engine") or "?").lower(),
            str(r.get("mode") or "?").lower(),
        )
        by_engine_mode[key].append(r)

    # 2. Local DB
    db_rows = _db_live_runs()
    db_by_run_id = {str(r["run_id"]): r for r in db_rows}
    db_trades_by_run = _db_trades_by_run()

    # 3. Local disk
    disk_dirs = _local_dirs_by_engine_mode()

    engines_all = sorted({e for (e, _m) in by_engine_mode} | {e for (e, _m) in disk_dirs})
    modes = ("paper", "shadow")

    mismatches: list[str] = []

    for engine in engines_all:
        print("\n" + "=" * 64)
        print(f"engine: {engine}")
        for mode in modes:
            runs = by_engine_mode.get((engine, mode), [])
            dirs = disk_dirs.get((engine, mode), [])
            print(f"  {mode}:")
            print(f"    vps runs: {len(runs)}")
            running = [r for r in runs if str(r.get("status") or "").lower() == "running"]
            stopped = [r for r in runs if str(r.get("status") or "").lower() == "stopped"]
            print(f"       running={len(running)} · stopped={len(stopped)}")

            total_trades = 0
            total_positions = 0
            vps_errors = 0
            trades_per_run: list[tuple[str, int, int]] = []  # (rid, trades, positions)
            for r in runs:
                rid = str(r.get("run_id") or "")
                if not rid:
                    continue
                n_trades, _, terr = _vps_trades_count(client, rid)
                n_pos, perr = _vps_positions_count(client, rid)
                if terr is not None or perr is not None:
                    vps_errors += 1
                    continue
                total_trades += (n_trades or 0)
                total_positions += (n_pos or 0)
                if (n_trades or 0) or (n_pos or 0):
                    trades_per_run.append((rid, n_trades or 0, n_pos or 0))

            print(f"    total trades (vps): {total_trades}" + (f"   [{vps_errors} runs errored]" if vps_errors else ""))
            print(f"    total open positions (vps): {total_positions}")
            if vps_errors:
                mismatches.append(
                    f"!! {engine} {mode}: {vps_errors}/{len(runs)} runs errored on VPS "
                    f"(tunnel dropped? retry when SSH/cockpit is reachable)"
                )
            if trades_per_run:
                print("    runs with activity:")
                for rid, nt, npos in trades_per_run:
                    status = db_by_run_id.get(rid, {}).get("status", "?")
                    in_db = "db✔" if rid in db_by_run_id else "db✗"
                    print(f"       · {rid} trades={nt} pos={npos} [{in_db} {status}]")

            # Disk vs VPS
            disk_count = len(dirs)
            print(f"    local disk dirs: {disk_count}")
            disk_orphans = [d for d in dirs
                            if d not in db_by_run_id
                            and not any(r.get("run_id") == d for r in runs)]
            if disk_orphans:
                print(f"       !! orphan dirs (not in DB, not on VPS): {len(disk_orphans)}")

            # DB vs VPS
            db_for_engine_mode = [r for r in db_rows
                                  if str(r.get("engine", "")).lower() == engine
                                  and str(r.get("mode", "")).lower() == mode]
            print(f"    db live_runs rows: {len(db_for_engine_mode)}")
            running_not_in_db = [r for r in running if r.get("run_id") not in db_by_run_id]
            if running_not_in_db:
                msg = (f"!! {engine} {mode}: {len(running_not_in_db)} VPS-running "
                       f"runs NOT mirrored in DB live_runs (rid={', '.join(str(r.get('run_id')) for r in running_not_in_db[:3])})")
                mismatches.append(msg)

    # DB trades table — only backtest data lives here
    print("\n" + "=" * 64)
    print("db.trades table (backtest data — NOT live paper/shadow):")
    top = sorted(db_trades_by_run.items(), key=lambda kv: kv[1], reverse=True)[:10]
    for rid, n in top:
        print(f"   {n:>6}  {rid}")
    # Flag if any live run_id leaked in
    live_ids_in_db_trades = [rid for rid in db_trades_by_run
                              if rid in db_by_run_id or any(r.get("run_id") == rid for r in vps_paper_shadow)]
    if live_ids_in_db_trades:
        mismatches.append(f"!! {len(live_ids_in_db_trades)} live run_ids leaked into db.trades (backtest-only table)")

    print("\n" + "=" * 64)
    print("SUMMARY")
    print(f"  VPS paper+shadow runs:       {len(vps_paper_shadow)}")
    print(f"  DB live_runs rows:           {len(db_rows)}")
    print(f"  DB trades rows (backtests):  {sum(db_trades_by_run.values())}")
    print(f"  Engines seen:                {len(engines_all)}")
    print(f"  Mismatches flagged:          {len(mismatches)}")
    if mismatches:
        print("\nISSUES:")
        for m in mismatches:
            print(f"  {m}")
    else:
        print("\nAll aligned — no drift detected.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
