"""Backfill live_trades + live_signals from VPS or local disk.

Sister of `backfill_live_runs.py`: that one syncs RUN METADATA from
the cockpit to `live_runs`. This one syncs the actual TRADE/SIGNAL
records to `live_trades` and `live_signals` so SQL queries like
"all paper trades on AVAXUSDT this week" become possible.

Sources (in priority order, per run):
  1. Cockpit endpoint /v1/runs/{id}/trades  (paper trades, full lifecycle)
  2. Local disk <run_dir>/reports/trades.jsonl  (same shape, fallback)
  3. Local disk <run_dir>/reports/shadow_trades.jsonl  (shadow signals)

Idempotent — UNIQUE(run_id, ts, symbol) means rerunning is safe.

Usage:
    python -m tools.maintenance.backfill_live_trades --from-vps
    python -m tools.maintenance.backfill_live_trades --from-vps --apply
    python -m tools.maintenance.backfill_live_trades --runs RID1,RID2 --apply
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from core.ops.db_live_trades import (
    upsert_trades_bulk,
    upsert_signals_bulk,
)

DB_PATH = Path("data/aurum.db")
_COCKPIT_UNAVAILABLE = False


def _load_trades_from_disk(run_dir: Path) -> list[dict]:
    """Read reports/trades.jsonl OR reports/shadow_trades.jsonl. Empty if absent."""
    out: list[dict] = []
    for fname in ("trades.jsonl", "shadow_trades.jsonl"):
        path = run_dir / "reports" / fname
        if not path.exists():
            continue
        try:
            for ln in path.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    out.append(json.loads(ln))
            return out  # first hit wins (trades.jsonl preferred)
        except (OSError, ValueError):
            continue
    return out


def _is_signal_payload(payload: dict) -> bool:
    """Distinguish shadow signal records from paper trade records.

    Shadow records carry 'shadow_run_id' and 'shadow_observed_at' as
    runner-injected fields. Paper trade records don't.
    """
    return ("shadow_observed_at" in payload
            or "shadow_run_id" in payload)


def _fetch_from_cockpit(run_id: str) -> list[dict]:
    """GET /v1/runs/{id}/trades from the local cockpit. Empty list on error."""
    global _COCKPIT_UNAVAILABLE
    if _COCKPIT_UNAVAILABLE:
        return []
    try:
        from core.risk.key_store import load_runtime_keys
        import urllib.request
        tok = load_runtime_keys().get("cockpit_api", {}).get("read_token")
        if not tok:
            return []
        req = urllib.request.Request(
            f"http://127.0.0.1:8787/v1/runs/{run_id}/trades",
            headers={"Authorization": f"Bearer {tok}"},
        )
        with urllib.request.urlopen(req, timeout=2) as r:
            data = json.loads(r.read())
        if isinstance(data, dict):
            return data.get("trades") or []
        return []
    except Exception:
        _COCKPIT_UNAVAILABLE = True
        return []


def _backfill_one_run(conn: sqlite3.Connection, run_row: tuple,
                       *, prefer_vps: bool, apply: bool) -> tuple[int, int]:
    """Backfill a single run. Returns (trades_inserted, signals_inserted)."""
    run_id, run_dir = run_row
    payloads: list[dict] = []
    if prefer_vps:
        payloads = _fetch_from_cockpit(run_id)
    if not payloads and run_dir:
        payloads = _load_trades_from_disk(Path(run_dir))

    trades = [p for p in payloads if not _is_signal_payload(p)]
    signals = [p for p in payloads if _is_signal_payload(p)]

    if not apply:
        return len(trades), len(signals)

    n_t = upsert_trades_bulk(conn, run_id, trades)
    n_s = upsert_signals_bulk(conn, run_id, signals)
    return n_t, n_s


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-vps", action="store_true",
                    help="prefer cockpit endpoint over local disk")
    ap.add_argument("--apply", action="store_true",
                    help="actually write (default is dry-run)")
    ap.add_argument("--runs", type=str,
                    help="comma-separated run_ids (default: all live_runs)")
    ap.add_argument("--db", type=str, default=str(DB_PATH))
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)

    if args.runs:
        run_ids = [r.strip() for r in args.runs.split(",") if r.strip()]
        rows = [
            (r[0], r[1])
            for r in conn.execute(
                f"SELECT run_id, run_dir FROM live_runs "
                f"WHERE run_id IN ({','.join('?' * len(run_ids))})",
                run_ids,
            ).fetchall()
        ]
    else:
        rows = conn.execute(
            "SELECT run_id, run_dir FROM live_runs ORDER BY started_at DESC"
        ).fetchall()

    src = "vps-then-disk" if args.from_vps else "disk-only"
    mode = "APPLY" if args.apply else "dry-run"
    print(f"backfilling {len(rows)} run(s) (source={src}, {mode})")

    total_t = 0
    total_s = 0
    runs_with_data = 0
    for run_row in rows:
        n_t, n_s = _backfill_one_run(
            conn, run_row, prefer_vps=args.from_vps, apply=args.apply,
        )
        if n_t or n_s:
            runs_with_data += 1
            print(f"  {run_row[0]:<50} trades={n_t:>3} signals={n_s:>3}")
        total_t += n_t
        total_s += n_s

    if args.apply:
        conn.commit()

    print()
    print(f"runs with data: {runs_with_data}/{len(rows)}")
    print(f"total trades:   {total_t}")
    print(f"total signals:  {total_s}")
    if not args.apply:
        print("(dry-run — re-run with --apply to persist)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
