"""Legacy BRIDGEWATER-focused sweep — THOTH_MIN_SCORE only, 180d window.

Hypothesis (pre-registered):
    Pre-R2-fix (2026-04-14), grid at THOTH_MIN_SCORE=0.30 showed Sharpe
    dropping from 2.71 → 0.87 — reading as "lower threshold better".
    Post-R2 fix (sentiment end_time_ms, 2026-04-17), that conclusion may
    not hold: with honest sentiment, higher threshold might filter noise
    instead of edge.

Mechanism tested:
    BRIDGEWATER historically emitted ~89% of MILLENNIUM trades at THOTH_MIN_SCORE
    = 0.20. Raising threshold should (a) reduce trade count, (b) raise
    average R-multiple per trade, (c) decide whether edge is in the volume
    or in selectivity.

Grid (closed):
    0.20 (baseline), 0.25, 0.30.
    No other parameters moved. Single window (180d).

Decision rule:
    Accept variant with highest Sharpe × (1 - MaxDD) balance. If all
    variants within 10% Sharpe, prefer higher MIN_SCORE (simpler, more
    selective).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tools.millennium_battery import (
    _reset_millennium_globals,
    _per_strategy,
    _portfolio_summary,
    _write_trades,
    _write_html_report,
)


VARIANTS = [
    {"name": "score_020_baseline", "THOTH_MIN_SCORE": 0.20},
    {"name": "score_025",          "THOTH_MIN_SCORE": 0.25},
    {"name": "score_030",          "THOTH_MIN_SCORE": 0.30},
]


def _run_variant(variant: dict, window_days: int, sweep_root: Path,
                  account_size: float, cached: dict | None) -> dict:
    import engines.millennium as ms
    import engines.bridgewater as bw
    import config.params as cp

    variant_dir = sweep_root / variant["name"]
    variant_dir.mkdir(parents=True, exist_ok=True)
    (variant_dir / "logs").mkdir(exist_ok=True)

    _win_log = variant_dir / "logs" / "multistrategy.log"
    fh = logging.FileHandler(_win_log, encoding="utf-8", mode="w")
    fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
    ms.log.addHandler(fh)
    try:
        print(f"\n{'='*72}")
        print(f"  VARIANT: {variant['name']}  ·  THOTH_MIN_SCORE={variant['THOTH_MIN_SCORE']}")
        print(f"{'='*72}")
        t0 = time.time()

        # Patch the global THRESHOLD in both config.params and the
        # BRIDGEWATER module (which snapshots it via `from config.params import *`).
        cp.THOTH_MIN_SCORE = variant["THOTH_MIN_SCORE"]
        bw.THOTH_MIN_SCORE = variant["THOTH_MIN_SCORE"]

        _reset_millennium_globals(window_days)
        ms.MS_RUN_DIR = variant_dir
        ms.RUN_ID = f"sweep_{variant['name']}"

        # Reuse cached data across variants — fetch once, scan N times.
        # Data is identical between variants (same window + symbols).
        if cached is None:
            all_dfs, htf_stack, macro, corr = ms._load_dados(generate_plots=False)
            cached = {"all_dfs": all_dfs, "htf_stack": htf_stack,
                       "macro": macro, "corr": corr}
        else:
            print("  [cache] reusing fetched data from previous variant")

        ms.log.info(
            f"SWEEP variant={variant['name']}  THOTH_MIN_SCORE={variant['THOTH_MIN_SCORE']}  "
            f"window={window_days}d  account=${account_size:,.0f}"
        )

        _, all_trades = ms._collect_operational_trades(
            cached["all_dfs"], cached["htf_stack"],
            cached["macro"], cached["corr"],
        )
        if not all_trades:
            print(f"  [{variant['name']}] sem trades"); return {"name": variant["name"], "n_trades": 0}

        portfolio_trades = ms.operational_core_reweight(all_trades)
        summary = _portfolio_summary(portfolio_trades, window_days, account_size)
        per_strat = _per_strategy(portfolio_trades)

        (variant_dir / "summary.json").write_text(
            json.dumps({**variant, **summary}, indent=2, default=str),
            encoding="utf-8",
        )
        (variant_dir / "per_strategy.json").write_text(
            json.dumps(per_strat, indent=2, default=str), encoding="utf-8",
        )
        _write_trades(portfolio_trades, ms.RUN_ID, window_days, variant_dir)

        try:
            _write_html_report(
                portfolio_trades, summary, per_strat, variant_dir,
                f"MILLENNIUM · {variant['name']}", account_size,
            )
        except Exception as e:
            print(f"  [{variant['name']}] report.html falhou: {e}")

        dt = time.time() - t0
        print(f"\n  [{variant['name']}] {summary.get('n_trades')} trades  "
              f"Sharpe={summary.get('sharpe')}  ROI={summary.get('roi_pct')}%  "
              f"DD={summary.get('max_dd_pct')}%  ({dt:.1f}s)")

        return {
            "name": variant["name"],
            "THOTH_MIN_SCORE": variant["THOTH_MIN_SCORE"],
            **summary,
            "per_strategy": per_strat,
            "cached_bundle": cached,
        }
    finally:
        ms.log.removeHandler(fh)
        fh.close()


def _write_sweep_summary(results: list[dict], sweep_root: Path,
                          window_days: int, account_size: float) -> None:
    # JSON (strip cache to keep file small)
    clean = [{k: v for k, v in r.items() if k != "cached_bundle"} for r in results]
    (sweep_root / "sweep_summary.json").write_text(
        json.dumps({
            "run_at": datetime.now().isoformat(),
            "window_days": window_days,
            "account_size": account_size,
            "variants": clean,
        }, indent=2, default=str),
        encoding="utf-8",
    )

    # Markdown
    lines = []
    lines.append(f"# MILLENNIUM — THOTH_MIN_SCORE sweep ({window_days}d)\n")
    lines.append(f"**Account:** ${account_size:,.0f} · **Engine:** op=1 CORE OPERATIONAL\n")

    lines.append("\n## Portfolio metrics per variant\n")
    lines.append("| Variant | MIN_SCORE | Trades | WR% | ROI% | Sharpe | Sortino | MaxDD% | PnL |")
    lines.append("|---------|----------:|-------:|----:|-----:|-------:|--------:|-------:|----:|")
    for r in results:
        if r.get("n_trades", 0) == 0:
            continue
        lines.append(
            f"| {r['name']} | {r.get('THOTH_MIN_SCORE')} | {r.get('n_trades')} | "
            f"{r.get('win_rate_pct', '—')} | {r.get('roi_pct', '—')} | "
            f"{r.get('sharpe', '—')} | {r.get('sortino', '—')} | "
            f"{r.get('max_dd_pct', '—')} | ${r.get('total_pnl', 0):,.0f} |"
        )

    lines.append("\n## BRIDGEWATER share per variant\n")
    lines.append("| Variant | BW trades | BW share | BW PnL | BW avg R |")
    lines.append("|---------|----------:|---------:|-------:|---------:|")
    for r in results:
        if r.get("n_trades", 0) == 0:
            continue
        bw = r["per_strategy"].get("BRIDGEWATER", {})
        share = (bw.get("n", 0) / r["n_trades"]) * 100 if r["n_trades"] else 0
        lines.append(
            f"| {r['name']} | {bw.get('n', 0)} | {share:.1f}% | "
            f"${bw.get('total_pnl', 0):,.0f} | {bw.get('avg_r_multiple', 0)} |"
        )

    lines.append("\n## Per-strategy breakdown per variant\n")
    for r in results:
        if r.get("n_trades", 0) == 0:
            continue
        lines.append(f"\n### {r['name']} (MIN_SCORE={r['THOTH_MIN_SCORE']})\n")
        lines.append("| Engine | n | WR% | L/S | PnL | Avg R | MaxStreak |")
        lines.append("|--------|--:|----:|:---:|----:|------:|----------:|")
        for eng in ("CITADEL", "RENAISSANCE", "JUMP", "BRIDGEWATER"):
            s = r["per_strategy"].get(eng)
            if not s:
                lines.append(f"| {eng} | 0 | — | — | — | — | — |"); continue
            lines.append(
                f"| {eng} | {s['n']} | {s['win_rate_pct']} | "
                f"{s['longs']}L/{s['shorts']}S | ${s['total_pnl']:,.0f} | "
                f"{s['avg_r_multiple']} | {s['max_consec_losses']} |"
            )

    (sweep_root / "sweep_summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main() -> int:
    import engines.millennium as ms

    if "BRIDGEWATER" not in ms.OPERATIONAL_ENGINES:
        print(
            "MILLENNIUM THOTH_MIN_SCORE sweep is disabled: "
            "BRIDGEWATER is not part of today's operational core."
        )
        print(
            "Use tools/millennium_battery.py for the current "
            "CITADEL + RENAISSANCE + JUMP battery."
        )
        return 2

    ap = argparse.ArgumentParser(description="MILLENNIUM THOTH_MIN_SCORE sweep")
    ap.add_argument("--window", type=int, default=180, help="Window in days (default 180)")
    ap.add_argument("--account", type=float, default=None)
    args = ap.parse_args()

    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    sweep_root = ROOT / "data" / "millennium" / f"sweep_minscore_{ts}"
    sweep_root.mkdir(parents=True, exist_ok=True)

    from config.params import ACCOUNT_SIZE
    account_size = args.account if args.account is not None else ACCOUNT_SIZE

    print(f"\n{'#'*72}")
    print(f"#  MILLENNIUM THOTH_MIN_SCORE SWEEP")
    print(f"#  window: {args.window}d  ·  account: ${account_size:,.0f}")
    print(f"#  output: {sweep_root}")
    print(f"#  variants: {[v['name'] for v in VARIANTS]}")
    print(f"{'#'*72}")

    results: list[dict] = []
    cached_bundle: dict | None = None
    for v in VARIANTS:
        try:
            r = _run_variant(v, args.window, sweep_root, account_size, cached_bundle)
            cached_bundle = r.pop("cached_bundle", None)
            results.append(r)
        except Exception as e:
            import traceback; traceback.print_exc()
            results.append({"name": v["name"], "status": "error", "error": str(e)})

    _write_sweep_summary(results, sweep_root, args.window, account_size)

    print(f"\n{'#'*72}")
    print(f"#  SWEEP COMPLETE")
    print(f"#  summary: {sweep_root / 'sweep_summary.md'}")
    print(f"{'#'*72}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
