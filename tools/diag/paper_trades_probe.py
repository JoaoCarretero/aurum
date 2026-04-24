"""Probe VPS for paper trade history on all currently-running paper runs.

One-shot diagnostic so the operator can see exactly what the cockpit API
returns for each active paper run:

  python tools/diag/paper_trades_probe.py

No side effects — read-only GETs against the cockpit API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from launcher_support.engines_live_view import _get_cockpit_client


def main() -> int:
    client = _get_cockpit_client()
    if client is None:
        print("!! cockpit client unavailable — check config/keys.json `cockpit_api` block")
        return 1
    try:
        runs = client._get("/v1/runs")
    except Exception as e:
        print(f"!! /v1/runs failed: {e}")
        return 1
    if not isinstance(runs, list):
        print(f"!! unexpected /v1/runs payload: {type(runs).__name__}")
        return 1

    wanted_modes = {"paper", "shadow"}
    filtered = [
        r for r in runs
        if str(r.get("mode") or "").lower() in wanted_modes
    ]
    # Sort newest first so recent history surfaces at the top.
    filtered.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    print(f"== {len(filtered)} paper/shadow run(s) — running + stopped ==\n")
    if not filtered:
        print("(nada em paper nem shadow mode)")
        return 0

    for r in filtered:
        rid = r.get("run_id")
        engine = r.get("engine")
        mode = r.get("mode")
        label = r.get("label")
        status = r.get("status")
        started = r.get("started_at")
        print(f"-- {engine} [{mode}] / {rid} ({label}) [{status}] — started_at={started}")
        # heartbeat
        try:
            hb = client._get(f"/v1/runs/{rid}/heartbeat")
        except Exception as e:
            hb = {"__error__": str(e)}
        status = (hb or {}).get("status")
        ticks_ok = (hb or {}).get("ticks_ok")
        novel = (hb or {}).get("novel_total")
        print(f"   heartbeat: status={status} ticks_ok={ticks_ok} novel_total={novel}")
        # positions
        try:
            pos_payload = client._get(f"/v1/runs/{rid}/positions")
            positions = (pos_payload or {}).get("positions") or []
        except Exception as e:
            positions = []
            print(f"   positions ERROR: {e}")
        print(f"   positions: {len(positions)} open")
        for p in positions[:3]:
            print(f"      · {p.get('symbol')} {p.get('direction')} entry={p.get('entry_price')} u_pnl={p.get('unrealized_pnl')}")
        # trades
        try:
            trades_payload = client._get(f"/v1/runs/{rid}/trades?limit=50")
        except Exception as e:
            print(f"   trades ENDPOINT ERROR: {e}")
            continue
        if not isinstance(trades_payload, dict):
            print(f"   trades: unexpected payload {type(trades_payload).__name__}")
            continue
        trades = trades_payload.get("trades") or []
        total_count = trades_payload.get("count")
        print(f"   trades: count={total_count} · returned={len(trades)}")
        for t in trades[-5:]:
            print(f"      · {t.get('timestamp')}  {t.get('symbol')} {t.get('direction')} "
                  f"entry={t.get('entry_price')} exit={t.get('exit_price')} pnl={t.get('pnl')} "
                  f"primed={t.get('primed', False)}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
