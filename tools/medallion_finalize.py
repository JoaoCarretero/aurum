"""
MEDALLION Finalizer — standardize run artifacts across the AURUM pipeline
=========================================================================
Takes a MEDALLION backtest run directory and appends every artifact that
the CITADEL-level pipeline produces, so downstream tools (index.json,
launcher Backtest panel, compare_runs) see MEDALLION runs with the same
shape as any other engine.

What it adds:

  trades_audit_normalized.json   direction/exit_p/score aliases for the
                                 overfit audit + downstream consumers
  overfit.json                   6-test overfit audit (walk-forward,
                                 sensitivity, concentration, regime,
                                 temporal, slippage)
  equity.json                    per-trade equity curve (list of floats)
  config.json                    full SSOT config snapshot via
                                 core.run_manager.snapshot_config
  summary.json                   updated in place — adds monte_carlo
                                 and walk_forward blocks
  index.json row                 overfit_pass + overfit_warn updated

What it does NOT do:
  - Re-run the backtest (trades.json is source of truth)
  - Touch engine code, config/params.py, or any protected module
  - Generate an HTML report (report_html expects CITADEL-specific feeds
    like Ω scores and macro_bias; MEDALLION can gain one later if needed)

Usage:
  python tools/medallion_finalize.py                       # latest run
  python tools/medallion_finalize.py <run_dir>             # specific
  python tools/medallion_finalize.py <run_id>              # by id
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from analysis.montecarlo import monte_carlo
from analysis.overfit_audit import run_audit
from analysis.walkforward import walk_forward
from config.params import ACCOUNT_SIZE
from core.persistence import atomic_write_json
from core.run_manager import snapshot_config


MEDALLION_ROOT = ROOT / "data" / "medallion"
INDEX_PATH = ROOT / "data" / "index.json"


# ════════════════════════════════════════════════════════════════════
# Trade normalization
# ════════════════════════════════════════════════════════════════════

def _normalize_trades(trades: list[dict]) -> list[dict]:
    """Add the aliases downstream analysis modules need.

    MEDALLION trades are stored in integer-direction / exit_price form.
    The overfit audit, walk-forward, and diagnostics helpers all assume
    CITADEL-style fields (direction as 'BULLISH'/'BEARISH', exit_p,
    timestamp, score). This function writes those aliases without
    mutating semantics.
    """
    out = []
    for t in trades:
        tt = dict(t)
        d = t.get("direction")
        if isinstance(d, (int, float)):
            tt["direction"] = "BULLISH" if d >= 0 else "BEARISH"
        if "exit_price" in tt and "exit_p" not in tt:
            tt["exit_p"] = tt["exit_price"]
        if "ensemble_score" in tt and "score" not in tt:
            tt["score"] = abs(float(tt["ensemble_score"]))
        # timestamp: walk_forward sorts by this field
        if "timestamp" not in tt:
            tt["timestamp"] = tt.get("entry_time") or ""
        out.append(tt)
    return out


# ════════════════════════════════════════════════════════════════════
# Locate run
# ════════════════════════════════════════════════════════════════════

def _resolve_run_dir(arg: str | None) -> Path:
    if arg:
        p = Path(arg)
        if p.exists() and p.is_dir():
            return p
        candidate = MEDALLION_ROOT / arg
        if candidate.exists():
            return candidate
        raise SystemExit(f"run not found: {arg}")
    # Latest medallion run (any dir containing trades.json)
    runs = sorted(
        [d for d in MEDALLION_ROOT.iterdir()
         if d.is_dir() and (d / "trades.json").exists()],
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if not runs:
        raise SystemExit("no MEDALLION runs found")
    return runs[0]


# ════════════════════════════════════════════════════════════════════
# Equity curve
# ════════════════════════════════════════════════════════════════════

def _equity_curve(trades: list[dict]) -> list[float]:
    """Cumulative equity from ACCOUNT_SIZE across closed trades, sorted
    by entry time. Matches the shape CITADEL's equity.json uses.
    """
    closed = [t for t in trades if t.get("result") in ("WIN", "LOSS")]
    closed.sort(key=lambda t: t.get("timestamp") or t.get("entry_time") or "")
    eq: list[float] = [float(ACCOUNT_SIZE)]
    for t in closed:
        eq.append(round(eq[-1] + float(t.get("pnl", 0.0)), 4))
    return eq


# ════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════

def finalize(run_dir: Path) -> dict:
    """Run the full finalization pipeline on ``run_dir``.

    Idempotent — overwrites any prior artifacts. Returns a dict of
    summary counters for the caller to print.
    """
    print(f"  finalizing {run_dir.relative_to(ROOT)}")

    trades_path = run_dir / "trades.json"
    if not trades_path.exists():
        raise SystemExit(f"missing trades.json in {run_dir}")
    trades_raw = json.loads(trades_path.read_text(encoding="utf-8"))
    print(f"    trades: {len(trades_raw)} raw")

    # 1. Normalize trades for downstream tools
    trades = _normalize_trades(trades_raw)
    norm_path = run_dir / "trades_audit_normalized.json"
    atomic_write_json(norm_path, trades)
    print(f"    wrote  {norm_path.name}")

    # 2. Equity curve
    eq = _equity_curve(trades)
    atomic_write_json(run_dir / "equity.json", eq)
    print(f"    wrote  equity.json  ({len(eq)} points)")

    # 3. Monte Carlo on PnL stream
    pnls = [float(t.get("pnl", 0.0))
            for t in trades if t.get("result") in ("WIN", "LOSS")]
    mc_res = monte_carlo(pnls, seed=42)  # deterministic for reproducibility
    if mc_res is not None:
        # Strip the large `paths` / `finals` / `dds` for the summary block;
        # keep them for a separate mc.json if you want deep inspection.
        mc_summary = {k: v for k, v in mc_res.items()
                      if k not in ("paths", "finals", "dds")}
        atomic_write_json(run_dir / "montecarlo.json", mc_summary)
        print(f"    wrote  montecarlo.json  "
              f"(pct_pos={mc_summary['pct_pos']}% median=${mc_summary['median']})")
    else:
        mc_summary = None
        print(f"    MC skipped (need >= 2*MC_BLOCK trades)")

    # 4. Walk-forward formal (analysis.walkforward)
    wf = walk_forward(trades)
    if wf:
        atomic_write_json(run_dir / "walkforward.json", wf)
        stable = sum(1 for w in wf if w["test"]["pnl"] > 0)
        print(f"    wrote  walkforward.json  ({len(wf)} windows, "
              f"{stable}/{len(wf)} positive test windows)")
    else:
        print(f"    WF skipped (insufficient trades for WF_TRAIN+WF_TEST)")

    # 5. Overfit audit (6 tests)
    audit = run_audit(trades)
    atomic_write_json(run_dir / "overfit.json", audit)
    print(f"    wrote  overfit.json  "
          f"({audit['passed']}/{audit['total']} PASS, "
          f"{audit.get('skipped',0)} SKIP, {audit.get('failed',0)} FAIL)")

    # 6. Config snapshot
    cfg = snapshot_config()
    cfg["ENGINE"] = "MEDALLION"
    cfg["RUN_ID"] = run_dir.name
    atomic_write_json(run_dir / "config.json", cfg)
    print(f"    wrote  config.json  ({len(cfg)} keys)")

    # 7. Enrich summary.json in place with MC + WF blocks
    summary_path = run_dir / "summary.json"
    if summary_path.exists():
        s = json.loads(summary_path.read_text(encoding="utf-8"))
        if mc_summary:
            s["monte_carlo"] = mc_summary
        if wf:
            positive = sum(1 for w in wf if w["test"]["pnl"] > 0)
            s["walk_forward"] = {
                "n_windows": len(wf),
                "positive_test": positive,
                "stable_pct": round(positive / len(wf) * 100, 1)
                              if wf else None,
                "windows": wf,
            }
        s["overfit_audit"] = {
            "passed": audit["passed"],
            "total": audit["total"],
            "failed": audit.get("failed", 0),
            "skipped": audit.get("skipped", 0),
            "warnings": audit.get("warnings", 0),
            "details": {k: {"status": v["status"], "detail": v.get("detail")}
                        for k, v in audit["tests"].items()},
        }
        atomic_write_json(summary_path, s)
        print(f"    updated summary.json with MC/WF/audit blocks")

    # 8. Patch index.json row
    if INDEX_PATH.exists():
        rows = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        run_id_tag = run_dir.name
        patched = 0
        for r in rows:
            rid = r.get("run_id", "")
            if rid.endswith(run_id_tag):
                r["overfit_pass"] = audit.get("failed", 0) == 0
                r["overfit_warn"] = audit.get("warnings", 0) + audit.get("skipped", 0)
                patched += 1
        if patched:
            atomic_write_json(INDEX_PATH, rows)
            print(f"    patched index.json  ({patched} row(s))")
        else:
            print(f"    no index row matched {run_id_tag}")

    return {
        "run_dir": str(run_dir),
        "n_trades": len(trades),
        "audit_passed": audit["passed"],
        "audit_failed": audit.get("failed", 0),
        "mc_pct_pos": mc_summary["pct_pos"] if mc_summary else None,
        "wf_windows": len(wf),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Finalize a MEDALLION backtest run to CITADEL standard.")
    ap.add_argument("target", nargs="?", default=None,
                    help="Run directory or id (default: latest)")
    args = ap.parse_args()

    run_dir = _resolve_run_dir(args.target)
    result = finalize(run_dir)
    print()
    print("  DONE.  summary:")
    for k, v in result.items():
        print(f"    {k:<16s} {v}")
    print(f"  artifacts in: {run_dir}")
    return 0 if result["audit_failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
