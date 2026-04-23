"""PHI Stage C — universe validation of top Stage B combos.

Runs top 4 partial-Stage-B winners on the full SYMBOLS universe.
The goal is to detect overfitting: if Sharpe holds across symbols,
the signal is real; if it collapses, combo was overfit to BNBUSDT.
"""
from __future__ import annotations

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

log = logging.getLogger("phi_stage_c")
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


def main() -> int:
    combos = [
        ("C1", dict(cluster_min_confluences=1, cluster_atr_tolerance=0.5, adx_min=10.0, ema200_distance_atr=0.618, wick_ratio_min=0.382, omega_phi_entry=0.382)),
        ("C2", dict(cluster_min_confluences=1, cluster_atr_tolerance=0.5, adx_min=10.0, ema200_distance_atr=0.200, wick_ratio_min=0.382, omega_phi_entry=0.382)),
        ("C3", dict(cluster_min_confluences=1, cluster_atr_tolerance=0.5, adx_min=10.0, ema200_distance_atr=0.382, wick_ratio_min=0.382, omega_phi_entry=0.382)),
        ("C4", dict(cluster_min_confluences=1, cluster_atr_tolerance=0.5, adx_min=10.0, ema200_distance_atr=0.200, wick_ratio_min=0.618, omega_phi_entry=0.382)),
    ]

    symbols = list(SYMBOLS)
    log.info("Stage C universe: %d symbols, %d combos", len(symbols), len(combos))

    base_params = PhiParams()
    base_frames: dict[str, pd.DataFrame] = {}
    t0 = time.time()
    for sym in symbols:
        log.info("Prep %s...", sym)
        merged = prepare_symbol_frames(sym, base_params)
        if merged is None:
            log.warning("%s: no data", sym)
            continue
        base_frames[sym] = merged
    log.info("Frame prep done in %.1fs", time.time() - t0)

    if not base_frames:
        return 1

    all_results = []
    t1 = time.time()
    for combo_id, params_dict in combos:
        log.info("Running %s...", combo_id)
        params = replace(base_params, **params_dict)
        trades, summary, per_sym = run_combo(base_frames, params, ACCOUNT_SIZE)
        all_results.append({
            "combo_id": combo_id,
            "params": params_dict,
            "summary": summary,
            "per_symbol": per_sym,
            "n_trades": summary["total_trades"],
            "sharpe": summary["sharpe"],
            "pf": summary["profit_factor"] if summary["profit_factor"] != float("inf") else None,
            "wr": summary["win_rate"],
            "maxdd": summary["max_drawdown"],
            "pnl": summary["total_pnl"],
            "exp_r": summary["expectancy_r"],
        })
        log.info("%s: trades=%d sharpe=%.2f pf=%s pnl=%.2f",
                 combo_id, summary["total_trades"], summary["sharpe"],
                 f"{summary['profit_factor']:.2f}" if summary["profit_factor"] != float("inf") else "inf",
                 summary["total_pnl"])
    log.info("Stage C done in %.1fs", time.time() - t1)

    # Print universe summary
    print("\n" + "=" * 100)
    print("  PHI STAGE C — Universe Validation (11 symbols)")
    print("=" * 100)
    print(f"  {'combo':>6} {'trades':>7} {'wr%':>5} {'pf':>7} {'sharpe':>7} {'sortino':>7} {'mdd%':>5} {'exp_R':>7} {'pnl':>10}")
    print("  " + "-" * 98)
    for r in all_results:
        pf_str = f"{r['pf']:.2f}" if r['pf'] is not None else "  inf"
        print(f"  {r['combo_id']:>6} {r['n_trades']:>7} "
              f"{r['wr']*100:>4.1f} {pf_str:>7} {r['sharpe']:>7.2f} "
              f"{r['summary']['sortino']:>7.2f} "
              f"{r['maxdd']*100:>4.1f} {r['exp_r']:>7.3f} {r['pnl']:>+10.2f}")
    print("=" * 100)

    # Per-symbol breakdown for best combo
    best = max(all_results, key=lambda r: r["sharpe"] * (r["n_trades"] / 30) ** 0.5 if r["n_trades"] > 0 else 0)
    print(f"\n  BEST COMBO: {best['combo_id']} — per-symbol breakdown:")
    print(f"  {'symbol':>12} {'trades':>7} {'wr%':>5} {'sharpe':>7} {'pnl':>10}")
    print("  " + "-" * 50)
    for sym, s in sorted(best["per_symbol"].items(), key=lambda x: -x[1]["total_pnl"]):
        print(f"  {sym:>12} {s['total_trades']:>7} {s['win_rate']*100:>4.1f} "
              f"{s['sharpe']:>7.2f} {s['total_pnl']:>+10.2f}")

    # Overfit check: is BNBUSDT outperforming the rest dramatically?
    if "BNBUSDT" in best["per_symbol"]:
        bnb_pnl = best["per_symbol"]["BNBUSDT"]["total_pnl"]
        total = best["pnl"]
        bnb_share = bnb_pnl / total if total != 0 else 0
        print(f"\n  BNBUSDT share of total PnL: {bnb_share*100:.1f}%")
        if abs(bnb_share) > 0.6:
            print(f"  !!! OVERFIT WARNING: >60% of PnL concentrated in BNBUSDT !!!")

    # Save
    out_dir = Path("data/phi/_sweep")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = pd.Timestamp.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"stage_c_{ts}.json"
    with open(out_path, "w") as f:
        json.dump({
            "stage": "C",
            "symbols": symbols,
            "combos": [{"id": cid, "params": p} for cid, p in combos],
            "results": all_results,
        }, f, indent=2, default=str)
    print(f"\n  Saved: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
