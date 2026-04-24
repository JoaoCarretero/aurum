"""Comparative battery — ORNSTEIN vs CITADEL vs RENAISSANCE (standalone).

Runs each engine on the same universe × window via CLI subprocess, then
emits a single table comparing Sortino / Calmar / PF / WR / DD / trades /
trades-per-regime.

ORNSTEIN is the new arrival (mean-reversion). CITADEL (ex-AZOTH) is the
trend/momentum baseline. RENAISSANCE (ex-HERMES) is the harmonic-pattern
counterparty.

This tool does NOT gate MILLENNIUM integration — that requires 6/6 on
ornstein_overfit_audit first (protocolo anti-overfit).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
PYTHON = sys.executable


def _latest_summary(engine_dir: Path, since_ts: float) -> dict | None:
    for cand in sorted(engine_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not cand.is_dir():
            continue
        if cand.stat().st_mtime < since_ts - 5:
            break
        sfile = cand / "summary.json"
        if sfile.exists():
            d = json.loads(sfile.read_text(encoding="utf-8"))
            return d.get("summary", d)
    return None


def _run_engine(engine: str, symbols: str, days: int, out_base: Path) -> dict:
    script = f"engines/{engine}.py"
    cmd = [PYTHON, script, "--symbols", symbols, "--days", str(days), "--no-menu"]
    print(f"  [{engine}] running: {' '.join(cmd)}")
    started = datetime.now()
    try:
        res = subprocess.run(
            cmd, cwd=REPO, capture_output=True, text=True, timeout=1800,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {"engine": engine, "status": "TIMEOUT"}
    if res.returncode != 0:
        stderr_path = out_base / f"{engine}_stderr.txt"
        stderr_path.write_text(res.stderr or "", encoding="utf-8")
        return {"engine": engine, "status": f"EXIT {res.returncode}"}

    engine_dir = REPO / "data" / engine
    summary = _latest_summary(engine_dir, started.timestamp())
    if summary is None:
        return {"engine": engine, "status": "NO_SUMMARY"}

    # Normalize key names — engines vary (n_trades vs total_trades, pct vs fraction).
    n = summary.get("total_trades")
    if n is None:
        n = summary.get("n_trades", 0)
    wr = summary.get("win_rate", 0) or 0
    if wr > 1.5:  # percent vs fraction
        wr = wr / 100.0
    pf = summary.get("profit_factor")
    if pf is None:
        pf = summary.get("pf") or 0.0
    pnl = summary.get("total_pnl")
    if pnl is None:
        pnl = summary.get("pnl", 0.0)
    mdd = summary.get("max_drawdown")
    if mdd is None:
        mdd = summary.get("max_dd_pct", 0)
        if mdd is not None and mdd > 1.0:
            mdd = mdd / 100.0
    return {
        "engine": engine.upper(),
        "status": "OK",
        "n_trades": n,
        "sharpe": summary.get("sharpe"),
        "sortino": summary.get("sortino"),
        "profit_factor": pf,
        "win_rate": wr,
        "max_drawdown": mdd,
        "total_pnl": pnl,
        "regime_breakdown": summary.get("regime_breakdown", {}),
    }


def _fmt_row(r: dict) -> str:
    if r.get("status") != "OK":
        return f"| {r['engine']:<12} | {r.get('status'):<10} | | | | | | |"
    pf = r.get("profit_factor") or 0
    pf_str = "inf" if pf == float("inf") else f"{pf:.3f}"
    return (f"| {r['engine']:<12} | "
            f"{r['n_trades']:>5} | "
            f"{r.get('sharpe', 0):+7.3f} | "
            f"{r.get('sortino', 0):+8.3f} | "
            f"{pf_str:>8} | "
            f"{(r.get('win_rate') or 0) * 100:>5.1f}% | "
            f"{(r.get('max_drawdown') or 0) * 100:>5.2f}% | "
            f"{r.get('total_pnl', 0):+10,.2f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT")
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--engines", default="ornstein,citadel,renaissance",
                    help="Comma-separated engine list to compare.")
    args = ap.parse_args()

    run_id = datetime.now().strftime("%Y-%m-%d_%H%M")
    out_base = REPO / "data" / "_ornstein_compare" / run_id
    out_base.mkdir(parents=True, exist_ok=True)

    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    print(f"Comparative battery @ {run_id}")
    print(f"Engines: {engines} | symbols={args.symbols} | days={args.days}")

    rows = [_run_engine(e, args.symbols, args.days, out_base) for e in engines]
    (out_base / "report.json").write_text(
        json.dumps(rows, indent=2, default=str), encoding="utf-8"
    )

    lines = [
        "# ORNSTEIN Comparative Battery",
        "",
        f"run_id: `{run_id}` | symbols: `{args.symbols}` | days: {args.days}",
        "",
        "| Engine | N | Sharpe | Sortino | PF | WR | DD | PnL |",
        "|--------|---|--------|---------|----|----|----|-----|",
    ]
    for r in rows:
        lines.append(_fmt_row(r))

    # Regime breakdown (ORNSTEIN only exposes this field for now)
    for r in rows:
        rb = r.get("regime_breakdown") or {}
        if rb and r.get("status") == "OK":
            lines += ["", f"### {r['engine']} · trades by regime", ""]
            lines.append("| Regime | N | PnL |")
            lines.append("|---|---|---|")
            for tag, rec in sorted(rb.items(), key=lambda kv: -kv[1]["n"]):
                lines.append(f"| {tag} | {rec['n']} | {rec['pnl']:+,.2f} |")

    (out_base / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print()
    print("\n".join(lines[2:]))
    print(f"\nReports: {out_base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
