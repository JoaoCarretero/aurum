"""PHI parameter sweep — find param combos with edge.

Caches `prepare_symbol_frames` output once per symbol (expensive: fetch
+ features + zigzag + fibs per TF + HTF merge) and replays only the
cheap downstream layers (cluster/regime/trigger/scoring/scan) for each
param combo. This cuts a 30s/run full backtest down to <1s per combo
once frames are cached.

Usage:
    python tools/batteries/phi_sweep.py                        # BNBUSDT, 24 combos
    python tools/batteries/phi_sweep.py --symbols BNBUSDT,INJUSDT
    python tools/batteries/phi_sweep.py --universe             # 11 symbols (slow)
"""
from __future__ import annotations

import argparse
import itertools
import json
import logging
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

# Ensure repo root on path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
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

log = logging.getLogger("phi_sweep")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")


def _strip_downstream_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Remove any columns added by downstream layers so we can re-add with
    new params. Preserves all feature/zigzag/fib/HTF-merge columns."""
    drop_prefixes = ("cluster_", "regime_ok", "trigger_", "phi_score",
                     "omega_phi", "trend_alignment")
    keep = [c for c in df.columns
            if not any(c == p or c.startswith(p) for p in drop_prefixes)]
    return df[keep].copy()


def run_combo(base_frames: dict[str, pd.DataFrame], params: PhiParams,
              initial_equity: float) -> tuple[list, dict, dict]:
    """Run scan with fresh downstream layers on already-prepared frames."""
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
    """Combined score: sharpe × sqrt(trades/min) × (1 - maxdd).
    Trades below min are penalized with sqrt ratio < 1."""
    n = summary.get("total_trades", 0)
    if n == 0:
        return -999.0
    sharpe = float(summary.get("sharpe", 0.0))
    dd = float(summary.get("max_drawdown", 0.0))
    return sharpe * (n / min_trades) ** 0.5 * max(0.0, 1.0 - dd)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BNBUSDT",
                    help="Comma-separated symbols (default: BNBUSDT)")
    ap.add_argument("--universe", action="store_true",
                    help="Use full SYMBOLS universe (overrides --symbols)")
    ap.add_argument("--min-trades", type=int, default=30)
    ap.add_argument("--out", default="data/phi/_sweep",
                    help="Directory to write sweep_results.json")
    args = ap.parse_args()

    symbols = list(SYMBOLS) if args.universe else [s.strip() for s in args.symbols.split(",")]
    log.info("Sweep symbols: %s", symbols)

    # Grid
    grid_cluster = [2, 3]
    grid_omega = [0.382, 0.500, 0.618]
    grid_adx = [15.0, 20.0, 23.6, 27.0]
    combos = list(itertools.product(grid_cluster, grid_omega, grid_adx))
    log.info("Grid size: %d combos", len(combos))

    # Prepare frames ONCE per symbol (expensive)
    base_params = PhiParams()
    base_frames: dict[str, pd.DataFrame] = {}
    t0 = time.time()
    for sym in symbols:
        log.info("Preparing frames for %s...", sym)
        merged = prepare_symbol_frames(sym, base_params)
        if merged is None:
            log.warning("%s: no data, skipping", sym)
            continue
        base_frames[sym] = merged
    log.info("Frame prep done in %.1fs (%d symbols cached)",
             time.time() - t0, len(base_frames))

    if not base_frames:
        log.error("No symbols prepared; aborting.")
        return 1

    # Sweep
    results = []
    t1 = time.time()
    for i, (cluster, omega, adx) in enumerate(combos, 1):
        params = replace(base_params,
                         cluster_min_confluences=cluster,
                         omega_phi_entry=omega,
                         adx_min=adx)
        trades, summary, per_sym = run_combo(base_frames, params, ACCOUNT_SIZE)
        score = edge_score(summary, args.min_trades)
        results.append({
            "cluster": cluster,
            "omega": omega,
            "adx": adx,
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
        log.info("[%2d/%d] cluster=%d omega=%.3f adx=%.1f -> trades=%d sharpe=%.2f score=%.2f",
                 i, len(combos), cluster, omega, adx,
                 summary["total_trades"], summary["sharpe"], score)
    log.info("Sweep done in %.1fs", time.time() - t1)

    # Rank
    results.sort(key=lambda r: r["score"], reverse=True)

    # Print table
    print("\n" + "=" * 110)
    print(f"  PHI PARAMETER SWEEP — {len(combos)} combos × {len(base_frames)} symbols")
    print("=" * 110)
    print(f"  {'rank':>4} {'cluster':>8} {'omega':>7} {'adx':>6} {'trades':>7} "
          f"{'wr%':>6} {'pf':>6} {'sharpe':>7} {'maxdd%':>7} {'exp_R':>7} {'pnl':>10} {'score':>7}")
    print("  " + "-" * 108)
    for r, row in enumerate(results[:15], 1):
        pf_str = f"{row['pf']:.2f}" if row['pf'] is not None else "  inf"
        print(f"  {r:>4} {row['cluster']:>8} {row['omega']:>7.3f} {row['adx']:>6.1f} "
              f"{row['trades']:>7} {row['wr']*100:>5.1f} {pf_str:>6} "
              f"{row['sharpe']:>7.2f} {row['maxdd']*100:>6.1f} {row['exp_r']:>7.3f} "
              f"{row['pnl']:>+10.2f} {row['score']:>7.2f}")
    print("=" * 110)

    # Save
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = pd.Timestamp.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"sweep_{ts}.json"
    with open(out_path, "w") as f:
        json.dump({
            "symbols": symbols,
            "grid": {"cluster": grid_cluster, "omega": grid_omega, "adx": grid_adx},
            "min_trades": args.min_trades,
            "results": results,
        }, f, indent=2, default=str)
    print(f"\n  Sweep results saved to: {out_path}")

    # Recommend best
    promising = [r for r in results if r["trades"] >= args.min_trades and r["sharpe"] > 0]
    if promising:
        best = promising[0]
        print(f"\n  BEST COMBO: cluster={best['cluster']} omega={best['omega']} "
              f"adx={best['adx']} | {best['trades']} trades, sharpe={best['sharpe']:.2f}, "
              f"pnl=${best['pnl']:.2f}")
        print(f"  Run full engine: python -m engines.phi --threshold-cluster {best['cluster']} "
              f"--omega-entry {best['omega']}")
    else:
        print(f"\n  NO COMBO passes min_trades={args.min_trades} with positive Sharpe.")
        print(f"  Top combo by trade count: {results[0]['trades']} trades "
              f"(cluster={results[0]['cluster']} omega={results[0]['omega']} "
              f"adx={results[0]['adx']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
