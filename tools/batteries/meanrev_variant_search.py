"""Systematic variant search for meanrev edge — 2026-04-18 night session.

Tests hypotheses about what might salvage mean-rev:
- Regime gate (low_vol only)
- VWAP anchor vs EMA50
- Long-only vs short-only (directional asymmetry)
- Deeper extremes (dev=3, dev=4)
- Reverse direction (trend-cont) variants

Not anti-overfit sweep — each variant is a distinct hypothesis.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from engines.meanrev import MeanRevParams, run_backtest

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
DAYS = 180

# Second pass — push V10 (long_only_reverse) into positive territory.
# V10 baseline: Sharpe -0.60, WR 53.4%, PF 0.97, PnL -$93.
VARIANTS: dict[str, dict] = {
    "V10_baseline": {"side_filter": "long_only", "reverse_direction": True},
    "V12_V10_high_vol": {"side_filter": "long_only", "reverse_direction": True, "regime_filter": "high_vol"},
    "V13_V10_low_vol": {"side_filter": "long_only", "reverse_direction": True, "regime_filter": "low_vol"},
    "V14_V10_dev3": {"side_filter": "long_only", "reverse_direction": True, "deviation_enter": 3.0},
    "V15_V10_dev4": {"side_filter": "long_only", "reverse_direction": True, "deviation_enter": 4.0},
    "V16_V10_tstop24": {"side_filter": "long_only", "reverse_direction": True, "time_stop_bars": 24},
    "V17_V10_tstop8": {"side_filter": "long_only", "reverse_direction": True, "time_stop_bars": 8},
    "V18_V10_atr3": {"side_filter": "long_only", "reverse_direction": True, "atr_stop_mult": 3.0},
    "V19_V10_rsi80": {"side_filter": "long_only", "reverse_direction": True, "rsi_short_min": 80.0},
    "V20_V10_vwap": {"side_filter": "long_only", "reverse_direction": True, "anchor_type": "vwap_daily"},
    "V21_V10_composite": {"side_filter": "long_only", "reverse_direction": True,
                          "deviation_enter": 3.0, "time_stop_bars": 24, "rsi_short_min": 75.0},
    "V22_short_only_reverse_high_vol": {"side_filter": "short_only", "reverse_direction": True,
                                         "regime_filter": "high_vol"},
}


def main():
    out_root = Path("data/meanrev") / f"variant_search_{datetime.now():%Y-%m-%d}"
    out_root.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, overrides in VARIANTS.items():
        print(f"\n==== {name}  overrides={overrides} ====", flush=True)
        params = MeanRevParams()
        for k, v in overrides.items():
            setattr(params, k, v)
        try:
            trades, summary = run_backtest(SYMBOLS, params, days=DAYS)
        except Exception as e:
            print(f"  ERROR: {e}")
            rows.append({
                "variant": name, "n_trades": 0, "sharpe": 0.0, "win_rate": 0.0,
                "max_dd": 0.0, "expectancy_r": 0.0, "pf": 0.0, "pnl": 0.0,
                "error": str(e), "overrides": json.dumps(overrides),
            })
            continue
        rows.append({
            "variant": name,
            "n_trades": int(summary.get("total_trades", 0)),
            "sharpe": float(summary.get("sharpe", 0.0)),
            "win_rate": float(summary.get("win_rate", 0.0)),
            "max_dd": float(summary.get("max_drawdown", 0.0)),
            "expectancy_r": float(summary.get("expectancy_r", 0.0)),
            "pf": float(summary.get("profit_factor", 0.0)),
            "pnl": float(summary.get("total_pnl", 0.0)),
            "error": "",
            "overrides": json.dumps(overrides),
        })
        print(f"  n={rows[-1]['n_trades']} sharpe={rows[-1]['sharpe']:+.3f} "
              f"wr={rows[-1]['win_rate']*100:.1f}% pf={rows[-1]['pf']:.3f} "
              f"exp_r={rows[-1]['expectancy_r']:+.3f} pnl=${rows[-1]['pnl']:+,.2f}")

    csv_path = out_root / "results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n\nCSV: {csv_path}")

    print("\n=== Summary ===")
    print(f"{'Variant':<28} {'N':>5} {'Sharpe':>8} {'WR%':>6} {'PF':>6} {'ExpR':>8} {'PnL':>12}")
    for r in rows:
        print(f"{r['variant']:<28} {r['n_trades']:>5} {r['sharpe']:>+8.3f} "
              f"{r['win_rate']*100:>5.1f}% {r['pf']:>6.3f} {r['expectancy_r']:>+8.3f} "
              f"${r['pnl']:>+11,.2f}")


if __name__ == "__main__":
    main()
