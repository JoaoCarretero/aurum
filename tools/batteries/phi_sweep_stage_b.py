"""PHI Stage B parameter sweep — expanded 5-dim grid on bottleneck dials.

Based on Stage A findings (cluster=3 dead; cluster=2 top combo Sharpe 1.59
with 7 trades), this stage explores cluster_atr_tolerance, adx_min,
ema200_distance_atr, and wick_ratio_min to find a combo with ≥30 trades.
"""
from __future__ import annotations

import argparse
import itertools
import json
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from config.params import SYMBOLS, ACCOUNT_SIZE
from engines.phi import (
    PhiParams,
    prepare_symbol_frames,
    detect_cluster,
    check_regime_gates,
    check_golden_trigger,
    compute_scoring,
    scan_symbol,
    compute_summary,
)

log = logging.getLogger("phi_sweep_b")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")


def _strip_downstream_cols(df: pd.DataFrame) -> pd.DataFrame:
    drop_prefixes = ("cluster_", "regime_ok", "trigger_", "phi_score",
                     "omega_phi", "trend_alignment")
    keep = [c for c in df.columns
            if not any(c == p or c.startswith(p) for p in drop_prefixes)]
    return df[keep].copy()


def run_combo(base_frames: dict[str, pd.DataFrame], params: PhiParams,
              initial_equity: float) -> tuple[list, dict, dict]:
    all_trades: list = []
    all_vetos: dict = {}
    per_sym: dict = {}
    for sym, base in base_frames.items():
        df = _strip_downstream_cols(base)
        df = detect_cluster(df, params)
        df = check_regime_gates(df, params)
        df = check_golden_trigger(df, params)
        df = compute_scoring(df, params)
        trades, vetos = scan_symbol(df, sym, params, initial_equity)
        sym_summary = compute_summary(trades, initial_equity)
        sym_summary["vetos"] = vetos
        per_sym[sym] = sym_summary
        all_trades.extend(trades)
        for k, v in vetos.items():
            all_vetos[k] = all_vetos.get(k, 0) + v
    summary = compute_summary(all_trades, initial_equity)
    summary["vetos"] = all_vetos
    return all_trades, summary, per_sym


def edge_score(summary: dict, min_trades: int = 30) -> float:
    n = summary.get("total_trades", 0)
    if n == 0:
        return -999.0
    sharpe = float(summary.get("sharpe", 0.0))
    dd = float(summary.get("max_drawdown", 0.0))
    # Penalize low trade count with sqrt ratio
    return sharpe * (n / min_trades) ** 0.5 * max(0.0, 1.0 - dd)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BNBUSDT")
    ap.add_argument("--universe", action="store_true")
    ap.add_argument("--min-trades", type=int, default=30)
    ap.add_argument("--out", default="data/phi/_sweep")
    args = ap.parse_args()

    symbols = list(SYMBOLS) if args.universe else [s.strip() for s in args.symbols.split(",")]
    log.info("Stage B sweep symbols: %s", symbols)

    # Expanded grid
    grid_cluster = [1, 2]
    grid_tol = [0.5, 1.0, 1.5]
    grid_adx = [10.0, 15.0, 20.0]
    grid_dist = [0.2, 0.382, 0.618]
    grid_wick = [0.382, 0.618]
    combos = list(itertools.product(grid_cluster, grid_tol, grid_adx, grid_dist, grid_wick))
    log.info("Grid size: %d combos", len(combos))

    base_params = PhiParams(omega_phi_entry=0.382)  # cheapest Ω threshold
    base_frames: dict[str, pd.DataFrame] = {}
    t0 = time.time()
    for sym in symbols:
        log.info("Preparing frames for %s...", sym)
        merged = prepare_symbol_frames(sym, base_params)
        if merged is None:
            log.warning("%s: no data", sym)
            continue
        base_frames[sym] = merged
    log.info("Frame prep done in %.1fs", time.time() - t0)
    if not base_frames:
        log.error("No symbols prepared")
        return 1

    results = []
    t1 = time.time()
    for i, (cluster, tol, adx, dist, wick) in enumerate(combos, 1):
        params = replace(base_params,
                         cluster_min_confluences=cluster,
                         cluster_atr_tolerance=tol,
                         adx_min=adx,
                         ema200_distance_atr=dist,
                         wick_ratio_min=wick)
        trades, summary, per_sym = run_combo(base_frames, params, ACCOUNT_SIZE)
        score = edge_score(summary, args.min_trades)
        results.append({
            "cluster": cluster, "tol": tol, "adx": adx,
            "dist": dist, "wick": wick,
            "trades": summary["total_trades"],
            "wr": summary["win_rate"],
            "pf": summary["profit_factor"] if summary["profit_factor"] != float("inf") else None,
            "sharpe": summary["sharpe"],
            "sortino": summary["sortino"],
            "maxdd": summary["max_drawdown"],
            "exp_r": summary["expectancy_r"],
            "pnl": summary["total_pnl"],
            "score": score,
            "per_symbol_trades": {s: v["total_trades"] for s, v in per_sym.items()},
        })
        log.info("[%3d/%d] cl=%d tol=%.1f adx=%.0f dist=%.2f wick=%.2f -> n=%d sh=%.2f sc=%.2f",
                 i, len(combos), cluster, tol, adx, dist, wick,
                 summary["total_trades"], summary["sharpe"], score)
    log.info("Sweep done in %.1fs", time.time() - t1)

    results.sort(key=lambda r: r["score"], reverse=True)

    print("\n" + "=" * 120)
    print(f"  PHI STAGE B SWEEP — {len(combos)} combos × {len(base_frames)} symbols")
    print("=" * 120)
    print(f"  {'rk':>3} {'cl':>3} {'tol':>4} {'adx':>5} {'dist':>5} {'wick':>5} "
          f"{'trades':>6} {'wr%':>5} {'pf':>6} {'sharpe':>6} {'mdd%':>5} {'exp_R':>6} {'pnl':>9} {'score':>6}")
    print("  " + "-" * 118)
    for r, row in enumerate(results[:20], 1):
        pf_str = f"{row['pf']:.2f}" if row['pf'] is not None else "  inf"
        print(f"  {r:>3} {row['cluster']:>3} {row['tol']:>4.1f} {row['adx']:>5.1f} "
              f"{row['dist']:>5.2f} {row['wick']:>5.2f} {row['trades']:>6} "
              f"{row['wr']*100:>4.1f} {pf_str:>6} {row['sharpe']:>6.2f} "
              f"{row['maxdd']*100:>4.1f} {row['exp_r']:>6.3f} {row['pnl']:>+9.2f} {row['score']:>6.2f}")
    print("=" * 120)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = pd.Timestamp.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"sweep_stage_b_{ts}.json"
    with open(out_path, "w") as f:
        json.dump({
            "stage": "B",
            "symbols": symbols,
            "grid": {
                "cluster": grid_cluster, "tol": grid_tol, "adx": grid_adx,
                "dist": grid_dist, "wick": grid_wick,
            },
            "min_trades": args.min_trades,
            "results": results,
        }, f, indent=2, default=str)
    print(f"\n  Results: {out_path}")

    promising = [r for r in results if r["trades"] >= args.min_trades and r["sharpe"] > 0]
    if promising:
        print(f"\n  TOP 5 (>={args.min_trades} trades, Sharpe>0):")
        for r in promising[:5]:
            pf_disp = f"{r['pf']:.2f}" if r['pf'] is not None else "inf"
            print(f"    cluster={r['cluster']} tol={r['tol']} adx={r['adx']} "
                  f"dist={r['dist']} wick={r['wick']} -> {r['trades']} trades, "
                  f"Sharpe={r['sharpe']:.2f}, PF={pf_disp}")
    else:
        print(f"\n  NO COMBO passes >={args.min_trades} trades with positive Sharpe.")
        best = max(results, key=lambda r: r["trades"])
        print(f"  Max trades: {best['trades']} "
              f"(cluster={best['cluster']} tol={best['tol']} adx={best['adx']} "
              f"dist={best['dist']} wick={best['wick']}) Sharpe={best['sharpe']:.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
