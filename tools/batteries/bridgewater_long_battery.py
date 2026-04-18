"""BRIDGEWATER post-fix long-window battery — 2026-04-17.

Tests the post-4-bug-fix engine on progressively longer windows and
alternate timeframes. BTCUSDT is the only symbol with deep cache
(2023-11-14 onwards), so isolated-BTC runs probe how far the edge
extends when sentiment data is actually present.

Grid (closed, pre-registered):
  - BTCUSDT solo, 1h: 90d, 180d, 365d, 720d
  - BTCUSDT solo, 4h: 90d, 180d, 365d, 720d
  - bluechip basket, 1h, 90d (reproducibility baseline)

Outputs per run: summary.json copied into this dir + aggregated report.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
PYTHON = sys.executable

GRID: list[dict] = [
    {"tag": "btc_1h_90d",   "args": ["--symbols", "BTCUSDT", "--interval", "1h", "--days", "90"]},
    {"tag": "btc_1h_180d",  "args": ["--symbols", "BTCUSDT", "--interval", "1h", "--days", "180"]},
    {"tag": "btc_1h_365d",  "args": ["--symbols", "BTCUSDT", "--interval", "1h", "--days", "365"]},
    {"tag": "btc_1h_720d",  "args": ["--symbols", "BTCUSDT", "--interval", "1h", "--days", "720"]},
    {"tag": "btc_4h_90d",   "args": ["--symbols", "BTCUSDT", "--interval", "4h", "--days", "90"]},
    {"tag": "btc_4h_180d",  "args": ["--symbols", "BTCUSDT", "--interval", "4h", "--days", "180"]},
    {"tag": "btc_4h_365d",  "args": ["--symbols", "BTCUSDT", "--interval", "4h", "--days", "365"]},
    {"tag": "btc_4h_720d",  "args": ["--symbols", "BTCUSDT", "--interval", "4h", "--days", "720"]},
    {"tag": "bluechip_1h_90d", "args": ["--interval", "1h", "--days", "90"]},
]


def _run(cfg: dict, out_base: Path) -> dict:
    tag = cfg["tag"]
    out_dir = out_base / "runs" / tag
    out_dir.mkdir(parents=True, exist_ok=True)

    engine_dir = REPO / "data" / "bridgewater"
    engine_dir.mkdir(parents=True, exist_ok=True)
    existing = {p for p in engine_dir.iterdir() if p.is_dir()}

    cmd = [PYTHON, "engines/bridgewater.py"] + cfg["args"] + ["--no-menu"]
    print(f"  [{tag}] {' '.join(cmd)}")
    start = datetime.now()
    try:
        res = subprocess.run(
            cmd, cwd=REPO, capture_output=True, text=True, timeout=1200,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {"tag": tag, "status": "TIMEOUT"}
    if res.returncode != 0:
        (out_dir / "stderr.txt").write_text(res.stderr or "", encoding="utf-8")
        (out_dir / "stdout.txt").write_text(res.stdout or "", encoding="utf-8")
        return {"tag": tag, "status": f"EXIT {res.returncode}"}

    new_dirs = [p for p in engine_dir.iterdir()
                if p.is_dir() and (p not in existing or p.stat().st_mtime >= start.timestamp() - 5)]
    new_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    summary = None
    overfit = None
    for cand in new_dirs[:5]:
        sfile = cand / "summary.json"
        ofile = cand / "overfit.json"
        if sfile.exists():
            summary = json.loads(sfile.read_text(encoding="utf-8"))
            (out_dir / "summary.json").write_text(sfile.read_text(encoding="utf-8"), encoding="utf-8")
            if ofile.exists():
                overfit = json.loads(ofile.read_text(encoding="utf-8"))
                (out_dir / "overfit.json").write_text(ofile.read_text(encoding="utf-8"), encoding="utf-8")
            break
    if summary is None:
        return {"tag": tag, "status": "NO_SUMMARY"}
    elapsed = (datetime.now() - start).total_seconds()
    row = {
        "tag": tag, "status": "OK", "elapsed_s": round(elapsed, 1),
        "n_trades": summary.get("n_trades"),
        "win_rate": summary.get("win_rate"),
        "sharpe": summary.get("sharpe"),
        "sortino": summary.get("sortino"),
        "calmar": summary.get("calmar"),
        "max_dd_pct": summary.get("max_dd_pct"),
        "pnl": summary.get("pnl"),
        "roi_pct": summary.get("roi_pct"),
    }
    if overfit is not None:
        row["overfit_passed"] = overfit.get("passed")
        row["overfit_warn"] = overfit.get("warnings")
        row["overfit_fail"] = overfit.get("failed")
        row["overfit_detail"] = {k: v.get("status") for k, v in overfit.get("tests", {}).items()}
    return row


def main() -> int:
    run_id = datetime.now().strftime("%Y-%m-%d_%H%M")
    out_base = REPO / "data" / "_bridgewater_battery" / run_id
    out_base.mkdir(parents=True, exist_ok=True)
    print(f"BRIDGEWATER long battery @ {run_id}")
    print(f"Output: {out_base}")
    print(f"Total runs: {len(GRID)}")
    rows = []
    for cfg in GRID:
        r = _run(cfg, out_base)
        rows.append(r)
        print(f"    -> {r.get('status')} n={r.get('n_trades','-')} sharpe={r.get('sharpe','-')} "
              f"overfit={r.get('overfit_passed','-')}/{6}")

    (out_base / "report.json").write_text(
        json.dumps(rows, indent=2, default=str), encoding="utf-8"
    )

    # Pretty table
    lines = ["# BRIDGEWATER long battery", "",
             f"run_id: `{run_id}`", "",
             "| Tag | N | WR% | Sharpe | Sortino | Calmar | DD% | PnL | Overfit |",
             "|-----|---|-----|--------|---------|--------|-----|-----|---------|"]
    for r in rows:
        if r.get("status") != "OK":
            lines.append(f"| {r['tag']} | {r.get('status')} | | | | | | | |")
            continue
        n = r.get("n_trades") or 0
        wr = r.get("win_rate") or 0
        sh = r.get("sharpe") or 0
        so = r.get("sortino") or 0
        cal = r.get("calmar") or 0
        dd = r.get("max_dd_pct") or 0
        pnl = r.get("pnl") or 0
        ov = r.get("overfit_passed", "-")
        ow = r.get("overfit_warn", "-")
        of = r.get("overfit_fail", "-")
        lines.append(f"| {r['tag']} | {n} | {wr:.1f} | {sh:+.3f} | {so:+.3f} | {cal:+.2f} | {dd:.2f} | {pnl:+.2f} | {ov}P/{ow}W/{of}F |")
    (out_base / "report.md").write_text("\n".join(lines), encoding="utf-8")

    print()
    print("\n".join(lines[2:]))
    print()
    print(f"Reports: {out_base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
