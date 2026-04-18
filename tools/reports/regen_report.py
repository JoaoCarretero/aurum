"""Quick re-render of an existing run's report.html with the current
analysis.report_html module. Used to validate CSS/HTML polish changes
without rerunning the backtest.

Usage: python tools/regen_report.py data/jump/2026-04-17_133748
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

from analysis.report_html import generate_report


def _load(run_dir: Path, name: str, default=None):
    p = run_dir / name
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def main(run_dir_str: str) -> None:
    run_dir = Path(run_dir_str)
    if not run_dir.exists():
        raise SystemExit(f"run dir not found: {run_dir}")

    summary = _load(run_dir, "summary.json", {}) or {}
    trades = _load(run_dir, "trades.json", []) or []
    equity = _load(run_dir, "equity.json", []) or []
    config = _load(run_dir, "config.json", {}) or {}
    overfit = _load(run_dir, "overfit.json", {}) or {}

    # Reconstruct common derived structures
    by_sym: dict[str, list] = {}
    for t in trades:
        sym = t.get("symbol") or "UNKNOWN"
        by_sym.setdefault(sym, []).append(t)

    ratios = {
        "ret": summary.get("roi_pct") or summary.get("roi") or 0.0,
        "sharpe": summary.get("sharpe"),
        "sortino": summary.get("sortino"),
    }
    mdd_pct = summary.get("max_dd_pct") or summary.get("max_dd") or 0.0

    out = generate_report(
        all_trades=trades,
        eq=equity,
        mc={},
        cond={},
        ratios=ratios,
        mdd_pct=mdd_pct,
        wf=[],
        wf_regime={},
        by_sym=by_sym,
        all_vetos={},
        run_dir=run_dir,
        config_dict=config,
        price_data={},
        audit_results=overfit or None,
        engine_name=summary.get("engine"),
    )
    print(f"wrote: {out}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python tools/regen_report.py <run_dir>")
    main(sys.argv[1])
