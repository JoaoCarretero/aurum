"""Pre-registered MEANREV partial-revert exit battery."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engines.meanrev import MeanRevParams, run_backtest, save_run

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
DAYS = 180
GRID_DOC = "docs/engines/meanrev/2026-04-18_partial_revert_grid.md"
MIN_TRADES = 100
MIN_PF = 1.0
MIN_EXP_R = 0.0

VARIANTS: dict[str, dict] = {
    "PR00_short_partial_25": {"side_filter": "short_only", "target_mode": "partial_revert", "target_reclaim_frac": 0.25},
    "PR01_short_partial_50": {"side_filter": "short_only", "target_mode": "partial_revert", "target_reclaim_frac": 0.50},
    "PR02_short_partial_75": {"side_filter": "short_only", "target_mode": "partial_revert", "target_reclaim_frac": 0.75},
    "PR03_wick_both_scale2_25": {
        "entry_mode": "wick_reclaim", "time_stop_bars": 48, "scale_in_levels": 2,
        "scale_in_step_atr": 0.5, "target_mode": "partial_revert", "target_reclaim_frac": 0.25,
    },
    "PR04_wick_both_scale2_50": {
        "entry_mode": "wick_reclaim", "time_stop_bars": 48, "scale_in_levels": 2,
        "scale_in_step_atr": 0.5, "target_mode": "partial_revert", "target_reclaim_frac": 0.50,
    },
    "PR05_wick_long_25": {
        "entry_mode": "wick_reclaim", "time_stop_bars": 48, "side_filter": "long_only",
        "target_mode": "partial_revert", "target_reclaim_frac": 0.25,
    },
    "PR06_wick_long_50": {
        "entry_mode": "wick_reclaim", "time_stop_bars": 48, "side_filter": "long_only",
        "target_mode": "partial_revert", "target_reclaim_frac": 0.50,
    },
    "PR07_wick_short_scale2_25": {
        "entry_mode": "wick_reclaim", "time_stop_bars": 48, "side_filter": "short_only",
        "scale_in_levels": 2, "scale_in_step_atr": 0.5,
        "target_mode": "partial_revert", "target_reclaim_frac": 0.25,
    },
}


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run pre-registered MEANREV partial-revert grid.")
    ap.add_argument("--out", default=None)
    ap.add_argument("--days", type=int, default=DAYS)
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    return ap.parse_args()


def _evaluate_filters(row: dict) -> tuple[bool, str]:
    reasons = []
    if row["n_trades"] < MIN_TRADES:
        reasons.append(f"n<{MIN_TRADES}")
    if row["pf"] <= MIN_PF:
        reasons.append("pf<=1.0")
    if row["expectancy_r"] <= MIN_EXP_R:
        reasons.append("exp<=0")
    return len(reasons) == 0, ",".join(reasons) if reasons else "pass"


def _sort_key(row: dict) -> tuple:
    return (
        1 if row["passes_filters"] else 0,
        row["expectancy_r"],
        row["pf"],
        row["sharpe"],
        row["pnl"],
        row["n_trades"],
    )


def main() -> None:
    args = _parse_args()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_root = Path(args.out) if args.out else Path("data/meanrev") / f"partial_revert_search_{ts}"
    out_root.mkdir(parents=True, exist_ok=True)
    variant_root = out_root / "variants"
    variant_root.mkdir(parents=True, exist_ok=True)
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    print(f"Using pre-registered grid: {GRID_DOC}")
    print(f"Budget locked: {len(VARIANTS)} variants")
    print(f"Output root: {out_root}")
    rows = []
    raw_rows = []
    for name, overrides in VARIANTS.items():
        print(f"\n==== {name} overrides={overrides} ====", flush=True)
        params = MeanRevParams()
        for key, value in overrides.items():
            setattr(params, key, value)
        run_dir = variant_root / name
        run_id = f"{ts}_{name}"
        try:
            trades, summary = run_backtest(symbols, params, days=args.days)
            save_run(
                run_dir, trades, summary, params,
                {
                    "run_id": run_id,
                    "variant": name,
                    "symbols": symbols,
                    "days": args.days,
                    "grid_doc": GRID_DOC,
                    "variant_overrides": overrides,
                    "search_root": str(out_root),
                },
            )
        except Exception as exc:
            print(f"  ERROR: {exc}")
            row = {
                "variant": name, "run_dir": str(run_dir), "n_trades": 0, "sharpe": 0.0,
                "win_rate": 0.0, "max_dd": 0.0, "expectancy_r": 0.0, "pf": 0.0,
                "pnl": 0.0, "passes_filters": False, "filter_note": f"error:{exc}",
                "error": str(exc), "overrides": json.dumps(overrides, sort_keys=True),
            }
            rows.append(row)
            raw_rows.append(row.copy())
            continue

        row = {
            "variant": name, "run_dir": str(run_dir),
            "n_trades": int(summary.get("total_trades", 0)),
            "sharpe": float(summary.get("sharpe", 0.0)),
            "win_rate": float(summary.get("win_rate", 0.0)),
            "max_dd": float(summary.get("max_drawdown", 0.0)),
            "expectancy_r": float(summary.get("expectancy_r", 0.0)),
            "pf": float(summary.get("profit_factor", 0.0)),
            "pnl": float(summary.get("total_pnl", 0.0)),
            "overrides": json.dumps(overrides, sort_keys=True),
            "error": "",
        }
        row["passes_filters"], row["filter_note"] = _evaluate_filters(row)
        rows.append(row)
        raw_rows.append(row.copy())
        print(
            f"  n={row['n_trades']} sharpe={row['sharpe']:+.3f} "
            f"wr={row['win_rate'] * 100:.1f}% pf={row['pf']:.3f} "
            f"exp_r={row['expectancy_r']:+.3f} pnl=${row['pnl']:+,.2f} "
            f"status={'PASS' if row['passes_filters'] else 'FAIL'}[{row['filter_note']}]"
        )

    rows = sorted(rows, key=_sort_key, reverse=True)
    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx

    ranked = out_root / "results_ranked.csv"
    with ranked.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    raw = out_root / "results_raw_order.csv"
    with raw.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(raw_rows[0].keys()))
        writer.writeheader()
        writer.writerows(raw_rows)
    manifest = out_root / "manifest.json"
    manifest.write_text(json.dumps({
        "timestamp": ts, "symbols": symbols, "days": args.days,
        "grid_doc": GRID_DOC, "budget": len(VARIANTS), "variants": VARIANTS,
        "winners": [row["variant"] for row in rows if row["passes_filters"]],
    }, indent=2) + "\n", encoding="utf-8")

    print(f"\nRanked CSV: {ranked}")
    print(f"Raw-order CSV: {raw}")
    print(f"Manifest: {manifest}")
    print("\n=== Ranking ===")
    print(f"{'Rank':>4} {'Status':>6} {'Variant':<24} {'N':>5} {'Sharpe':>8} {'WR%':>6} {'PF':>6} {'ExpR':>8} {'PnL':>12}")
    for row in rows:
        status = "PASS" if row["passes_filters"] else "FAIL"
        print(
            f"{row['rank']:>4} {status:>6} {row['variant']:<24} {row['n_trades']:>5} "
            f"{row['sharpe']:>+8.3f} {row['win_rate'] * 100:>5.1f}% {row['pf']:>6.3f} "
            f"{row['expectancy_r']:>+8.3f} ${row['pnl']:>+11,.2f}"
        )


if __name__ == "__main__":
    main()
