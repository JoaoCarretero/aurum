"""
MEDALLION Grid Search — parameter sweep with shared feature computation
=======================================================================
Fetches OHLCV once, computes MEDALLION features once per symbol, then
sweeps gate/exit/sizing parameters that DON'T affect features — so a
144-point grid runs in minutes instead of hours.

Sweeps (default):
    ensemble_threshold  ∈ {0.35, 0.40, 0.45, 0.50}
    z_entry_min         ∈ {1.0, 1.3, 1.6}
    autocorr_max        ∈ {0.0, -0.03}
    tp_atr_mult         ∈ {0.6, 1.0, 1.4}
    stop_atr_mult       ∈ {1.0, 1.2}

Does NOT modify engines/medallion.py, config/params.py, or any other
file — zero interference with the rest of AURUM. The best config found
is re-run through engines.medallion.save_run(), which produces the
same artifacts any normal MEDALLION run emits (trades.json, summary.json,
index.json row). Downstream tools treat it identically.

Usage:
    python tools/medallion_grid.py                        # defaults
    python tools/medallion_grid.py --days 365 --interval 1h
    python tools/medallion_grid.py --basket bluechip_active --fast
"""
from __future__ import annotations

import argparse
import copy
import csv
import itertools
import logging
import sys
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config.params import (
    ACCOUNT_SIZE, BASKETS, INTERVAL, SYMBOLS, _TF_MINUTES,
)
from core.data import fetch_all, validate
from engines import medallion as med

log = logging.getLogger("MEDALLION_GRID")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
# Silence the engine's per-symbol INFO spam during grid
logging.getLogger("MEDALLION").setLevel(logging.WARNING)


# ════════════════════════════════════════════════════════════════════
# Grid definitions
# ════════════════════════════════════════════════════════════════════

PHASE1_GRID = {
    "ensemble_threshold": [0.35, 0.40, 0.45, 0.50],
    "z_entry_min":        [1.0, 1.3, 1.6],
    "autocorr_max":       [0.0, -0.03],
    "tp_atr_mult":        [0.6, 1.0, 1.4],
    "stop_atr_mult":      [1.0, 1.2],
}

PHASE1_GRID_FAST = {
    "ensemble_threshold": [0.35, 0.45],
    "z_entry_min":        [0.8, 1.2, 1.6],
    "autocorr_max":       [0.0, -0.03],
    "tp_atr_mult":        [0.8, 1.5, 2.5],
    "stop_atr_mult":      [1.0, 1.5],
}

PHASE2_REFINE = {
    "tp_atr_mult":         [0.8, 1.2, 1.8, 2.5],
    "stop_atr_mult":       [1.0, 1.5, 2.0],
    "max_bars_in_trade":   [6, 12, 24],
    "cooldown_bars":       [2, 6],
}


def _grid_combos(grid: dict) -> list[dict]:
    names = list(grid.keys())
    vals = [grid[n] for n in names]
    return [dict(zip(names, c)) for c in itertools.product(*vals)]


# ════════════════════════════════════════════════════════════════════
# Fast scan over precomputed features
# ════════════════════════════════════════════════════════════════════

def _scan_with_params(enriched: dict[str, pd.DataFrame],
                      params: med.MedallionParams) -> tuple[list, dict]:
    """Run medallion.scan_symbol on already-enriched dataframes."""
    all_trades = []
    all_vetos: dict[str, int] = {}
    for sym, df in enriched.items():
        trades, vetos = med.scan_symbol(df, sym, params, ACCOUNT_SIZE)
        all_trades.extend(trades)
        for k, v in vetos.items():
            all_vetos[k] = all_vetos.get(k, 0) + v
    return all_trades, all_vetos


def _row(metrics: dict, combo: dict) -> dict:
    """Flatten metrics + combo into a single CSV row."""
    row = dict(combo)
    row.update({
        "n_trades": metrics["n_trades"],
        "win_rate": metrics["win_rate"],
        "pnl": metrics["pnl"],
        "roi_pct": metrics["roi_pct"],
        "max_dd_pct": metrics["max_dd_pct"],
        "sharpe": metrics["sharpe"],
        "sortino": metrics["sortino"],
    })
    return row


def _score_config(m: dict) -> float:
    """Single score for ranking. Penalizes tiny trade counts so we don't
    pick lucky 3-trade configs."""
    if m["n_trades"] < 15:
        return -1e9
    if m["pnl"] <= 0:
        return m["sharpe"] - 1.0  # negative-PnL floor below any positive PnL
    return m["sharpe"] + 0.01 * m["roi_pct"]


# ════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(description="MEDALLION grid search")
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--basket", type=str, default="bluechip")
    ap.add_argument("--interval", type=str, default=INTERVAL)
    ap.add_argument("--fast", action="store_true",
                    help="Coarse grid for quick iteration")
    ap.add_argument("--no-phase2", action="store_true")
    ap.add_argument("--no-hmm", action="store_true",
                    help="Disable HMM gate in base params (larger signal pool)")
    ap.add_argument("--invert", action="store_true",
                    help="Flip direction (momentum continuation instead of fade)")
    args = ap.parse_args()

    tf_min = max(1, _TF_MINUTES.get(args.interval, 15))
    n_candles = int(args.days) * 24 * 60 // tf_min
    basket = args.basket
    symbols = BASKETS.get(basket, SYMBOLS)

    # Output dir
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    out_dir = ROOT / "data" / "medallion" / f"grid_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Banner
    print()
    print("  ╔════════════════════════════════════════════════════════════╗")
    print("  ║ MEDALLION grid search · Berlekamp calibration               ║")
    print("  ╠════════════════════════════════════════════════════════════╣")
    print(f"  ║ basket      {basket} ({len(symbols)} symbols)")
    print(f"  ║ days        {args.days}  ({n_candles:,} candles/sym)")
    print(f"  ║ interval    {args.interval}")
    print(f"  ║ mode        {'FAST' if args.fast else 'FULL'}")
    print(f"  ║ out         {out_dir}")
    print("  ╚════════════════════════════════════════════════════════════╝")
    print()

    # 1. Fetch
    print(f"  fetching {len(symbols)} symbols @ {args.interval} ...")
    t0 = time.time()
    all_dfs = fetch_all(symbols, interval=args.interval,
                        n_candles=n_candles, futures=True)
    if not all_dfs:
        print("  no data fetched.")
        return 1
    for s, df in all_dfs.items():
        validate(df, s)
    print(f"  fetched in {time.time()-t0:.1f}s")

    # 2. Compute features ONCE with default params
    print(f"  computing features (one pass per symbol) ...")
    base_params = med.MedallionParams()
    base_params.interval = args.interval
    if args.no_hmm:
        base_params.hmm_enabled = False
    if args.invert:
        base_params.invert_direction = True
    enriched: dict[str, pd.DataFrame] = {}
    t0 = time.time()
    for sym, df in all_dfs.items():
        enriched[sym] = med.compute_features(df, base_params)
    print(f"  features ready in {time.time()-t0:.1f}s")
    print()

    # ── PHASE 1: gate + exit sweep ──
    grid1 = _grid_combos(PHASE1_GRID_FAST if args.fast else PHASE1_GRID)
    print(f"  PHASE 1: sweeping {len(grid1)} combos ...")
    results1: list[dict] = []
    t0 = time.time()
    for i, combo in enumerate(grid1, 1):
        params = replace(base_params, **combo)
        trades, vetos = _scan_with_params(enriched, params)
        m = med.compute_summary(trades, ACCOUNT_SIZE)
        results1.append(_row(m, combo))
        if i % max(1, len(grid1) // 10) == 0 or i == len(grid1):
            print(f"    [{i:>3}/{len(grid1)}]  "
                  f"n={m['n_trades']:>4}  roi={m['roi_pct']:>+6.2f}%  "
                  f"sharpe={m['sharpe']:>+5.2f}  "
                  f"cfg={combo}")
    dt1 = time.time() - t0
    print(f"  phase 1 done in {dt1:.1f}s")

    # Save phase 1 CSV
    csv1 = out_dir / "phase1.csv"
    with csv1.open("w", newline="", encoding="utf-8") as f:
        if results1:
            w = csv.DictWriter(f, fieldnames=list(results1[0].keys()))
            w.writeheader()
            w.writerows(results1)
    print(f"  phase 1 csv → {csv1}")

    # Rank
    ranked1 = sorted(results1, key=lambda r: _score_config(r), reverse=True)
    print()
    print("  TOP 5 (phase 1):")
    print(f"  {'thr':>5} {'z':>4} {'ac':>6} {'tp':>4} {'st':>4}  "
          f"{'n':>4} {'wr':>5} {'roi':>7} {'sh':>6} {'sor':>6} {'dd':>6}")
    for r in ranked1[:5]:
        print(f"  {r['ensemble_threshold']:>5.2f} "
              f"{r['z_entry_min']:>4.1f} "
              f"{r['autocorr_max']:>+6.2f} "
              f"{r['tp_atr_mult']:>4.1f} "
              f"{r['stop_atr_mult']:>4.1f}  "
              f"{r['n_trades']:>4} "
              f"{r['win_rate']:>4.1f}% "
              f"{r['roi_pct']:>+6.2f}% "
              f"{r['sharpe']:>+6.2f} "
              f"{r['sortino']:>+6.2f} "
              f"{r['max_dd_pct']:>5.1f}%")

    best1 = ranked1[0]

    # ── PHASE 2: refine exits around best phase-1 config ──
    results2: list[dict] = []
    if not args.no_phase2:
        base_lock = {k: best1[k] for k in
                     ("ensemble_threshold", "z_entry_min", "autocorr_max")}
        grid2 = _grid_combos(PHASE2_REFINE)
        print()
        print(f"  PHASE 2: refining {len(grid2)} exit/cooldown combos "
              f"around best phase-1 gates ({base_lock}) ...")
        t0 = time.time()
        for i, combo in enumerate(grid2, 1):
            full = {**base_lock, **combo}
            params = replace(base_params, **full)
            trades, _ = _scan_with_params(enriched, params)
            m = med.compute_summary(trades, ACCOUNT_SIZE)
            results2.append(_row(m, full))
            if i % max(1, len(grid2) // 10) == 0 or i == len(grid2):
                print(f"    [{i:>3}/{len(grid2)}]  "
                      f"n={m['n_trades']:>4}  roi={m['roi_pct']:>+6.2f}%  "
                      f"sharpe={m['sharpe']:>+5.2f}  "
                      f"exit={combo}")
        dt2 = time.time() - t0
        print(f"  phase 2 done in {dt2:.1f}s")

        csv2 = out_dir / "phase2.csv"
        with csv2.open("w", newline="", encoding="utf-8") as f:
            if results2:
                w = csv.DictWriter(f, fieldnames=list(results2[0].keys()))
                w.writeheader()
                w.writerows(results2)
        print(f"  phase 2 csv → {csv2}")

        ranked2 = sorted(results2, key=lambda r: _score_config(r), reverse=True)
        print()
        print("  TOP 5 (phase 2):")
        print(f"  {'tp':>4} {'st':>4} {'bars':>5} {'cd':>3}  "
              f"{'n':>4} {'wr':>5} {'roi':>7} {'sh':>6} {'sor':>6} {'dd':>6}")
        for r in ranked2[:5]:
            print(f"  {r['tp_atr_mult']:>4.1f} "
                  f"{r['stop_atr_mult']:>4.1f} "
                  f"{r['max_bars_in_trade']:>5} "
                  f"{r['cooldown_bars']:>3}  "
                  f"{r['n_trades']:>4} "
                  f"{r['win_rate']:>4.1f}% "
                  f"{r['roi_pct']:>+6.2f}% "
                  f"{r['sharpe']:>+6.2f} "
                  f"{r['sortino']:>+6.2f} "
                  f"{r['max_dd_pct']:>5.1f}%")

        best_overall = ranked2[0]
    else:
        best_overall = best1

    # ── Final run: re-execute with best config using medallion.save_run ──
    print()
    print("  FINAL: re-running best config with native save_run() pipeline")
    final_params = replace(base_params, **{
        k: best_overall[k] for k in best_overall
        if k in {f.name for f in med.dataclasses.fields(med.MedallionParams)}
    }) if hasattr(med, "dataclasses") else base_params
    # Simpler: filter manually
    p_fields = set(asdict(base_params).keys())
    override = {k: v for k, v in best_overall.items() if k in p_fields}
    final_params = replace(base_params, **override)
    final_params.interval = args.interval

    all_trades, vetos, per_sym = med.run_backtest(
        {s: all_dfs[s] for s in all_dfs},
        final_params, ACCOUNT_SIZE,
    )
    summary = med.compute_summary(all_trades, ACCOUNT_SIZE)

    run_id = f"medallion_{stamp}_gridbest"
    run_dir = ROOT / "data" / "medallion" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    med.save_run(run_dir, all_trades, summary, final_params,
                 vetos, per_sym,
                 meta={"run_id": run_id, "basket": basket,
                       "scan_days": args.days, "symbols": list(all_dfs.keys()),
                       "grid_source": str(out_dir.name)})

    print()
    print(f"  ┌─ MEDALLION grid-best ({run_id}) ─────────────┐")
    print(f"  │ trades      {summary['n_trades']:>10d}")
    print(f"  │ win rate    {summary['win_rate']:>9.1f}%")
    print(f"  │ ROI         {summary['roi_pct']:>+9.2f}%")
    print(f"  │ PnL         ${summary['pnl']:>+12,.2f}")
    print(f"  │ max DD      {summary['max_dd_pct']:>9.2f}%")
    print(f"  │ Sharpe      {summary['sharpe']:>10.3f}")
    print(f"  │ Sortino     {summary['sortino']:>10.3f}")
    print("  └" + "─" * 48 + "┘")
    print(f"\n  final run → {run_dir}")

    # Final config for human consumption
    (out_dir / "best_config.txt").write_text(
        "\n".join(f"{k} = {v!r}" for k, v in sorted(override.items())),
        encoding="utf-8",
    )
    return 0 if summary["roi_pct"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
