"""Focused mean-reversion variant search.

Keeps the thesis fixed:
- price stretched away from the mean
- RSI confirms exhaustion
- trade only the reversion back toward the anchor

What changes from variant to variant:
- how far the stretch must be
- how strict the reversal confirmation is
- whether to average into the stretch
- stop/time-stop geometry

Pre-registered grid:
- docs/engines/meanrev/2026-04-18_exhaustion_grid.md
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engines._archive.meanrev import MeanRevParams, run_backtest, save_run

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
DAYS = 180
GRID_DOC = "docs/engines/meanrev/2026-04-18_exhaustion_grid.md"
MIN_TRADES = 100
MIN_PF = 1.0
MIN_EXP_R = 0.0

VARIANTS: dict[str, dict] = {
    "MR00_baseline_reversal_bar": {},
    "MR01_touch_entry": {"entry_mode": "touch"},
    "MR02_close_back_inside": {"entry_mode": "close_back_inside"},
    "MR03_dev25": {"deviation_enter": 2.5},
    "MR04_dev30": {"deviation_enter": 3.0},
    "MR05_rsi_25_75": {"rsi_long_max": 25.0, "rsi_short_min": 75.0},
    "MR06_stop_25atr": {"atr_stop_mult": 2.5},
    "MR07_tstop_48": {"time_stop_bars": 48},
    "MR08_long_only": {"side_filter": "long_only"},
    "MR09_short_only": {"side_filter": "short_only"},
    "MR10_scale2_05atr": {"scale_in_levels": 2, "scale_in_step_atr": 0.5},
    "MR11_scale2_10atr": {"scale_in_levels": 2, "scale_in_step_atr": 1.0},
    "MR12_scale3_075atr": {"scale_in_levels": 3, "scale_in_step_atr": 0.75},
}


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run pre-registered MEANREV exhaustion grid.")
    ap.add_argument("--out", default=None, help="Output dir. Default: data/meanrev/variant_search_<timestamp>")
    ap.add_argument("--days", type=int, default=DAYS, help=f"Backtest horizon in days. Default: {DAYS}")
    ap.add_argument("--symbols", default=",".join(SYMBOLS),
                    help="Comma-separated symbols. Default: majors 5-pack used in pre-registration.")
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


def _write_markdown_report(path: Path, rows: list[dict], meta: dict) -> None:
    winners = [r for r in rows if r["passes_filters"]]
    lines = [
        "# MEANREV Exhaustion Grid Results",
        "",
        f"- Grid: `{meta['grid_doc']}`",
        f"- Run timestamp: `{meta['timestamp']}`",
        f"- Symbols: `{','.join(meta['symbols'])}`",
        f"- Days: `{meta['days']}`",
        f"- Budget: `{meta['budget']}` variants",
        "",
        "## Objective Filters",
        "",
        f"- `n_trades >= {MIN_TRADES}`",
        f"- `profit_factor > {MIN_PF:.2f}`",
        f"- `expectancy_r > {MIN_EXP_R:.0f}`",
        "",
        f"## Verdict",
        "",
        f"- Survivors: `{len(winners)}` / `{len(rows)}`",
    ]
    if winners:
        lines.extend([
            "",
            "## Winners",
            "",
            "| Rank | Variant | N | Sharpe | WR | PF | ExpR | PnL |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ])
        for row in winners:
            lines.append(
                f"| {row['rank']} | {row['variant']} | {row['n_trades']} | "
                f"{row['sharpe']:+.3f} | {row['win_rate'] * 100:.1f}% | {row['pf']:.3f} | "
                f"{row['expectancy_r']:+.3f} | ${row['pnl']:+,.2f} |"
            )
    lines.extend([
        "",
        "## Full Ranking",
        "",
        "| Rank | Status | Variant | N | Sharpe | WR | PF | ExpR | PnL | Filter Note |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
    ])
    for row in rows:
        status = "PASS" if row["passes_filters"] else "FAIL"
        lines.append(
            f"| {row['rank']} | {status} | {row['variant']} | {row['n_trades']} | "
            f"{row['sharpe']:+.3f} | {row['win_rate'] * 100:.1f}% | {row['pf']:.3f} | "
            f"{row['expectancy_r']:+.3f} | ${row['pnl']:+,.2f} | {row['filter_note']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    args = _parse_args()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_root = Path(args.out) if args.out else Path("data/meanrev") / f"variant_search_{ts}"
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
        run_id = f"{ts}_{name}"
        run_dir = variant_root / name
        try:
            trades, summary = run_backtest(symbols, params, days=args.days)
            save_run(
                run_dir,
                trades,
                summary,
                params,
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
            pass_filters, filter_note = False, f"error:{exc}"
            rows.append({
                "variant": name,
                "run_dir": str(run_dir),
                "n_trades": 0,
                "sharpe": 0.0,
                "win_rate": 0.0,
                "max_dd": 0.0,
                "expectancy_r": 0.0,
                "pf": 0.0,
                "pnl": 0.0,
                "passes_filters": pass_filters,
                "filter_note": filter_note,
                "error": str(exc),
                "overrides": json.dumps(overrides, sort_keys=True),
            })
            raw_rows.append(rows[-1].copy())
            continue

        row = {
            "variant": name,
            "run_dir": str(run_dir),
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
        latest = row
        print(
            f"  n={latest['n_trades']} sharpe={latest['sharpe']:+.3f} "
            f"wr={latest['win_rate'] * 100:.1f}% pf={latest['pf']:.3f} "
            f"exp_r={latest['expectancy_r']:+.3f} pnl=${latest['pnl']:+,.2f} "
            f"status={'PASS' if latest['passes_filters'] else 'FAIL'}[{latest['filter_note']}]"
        )

    rows = sorted(rows, key=_sort_key, reverse=True)
    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx

    csv_path = out_root / "results_ranked.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    raw_csv_path = out_root / "results_raw_order.csv"
    with open(raw_csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(raw_rows[0].keys()))
        writer.writeheader()
        writer.writerows(raw_rows)

    meta = {
        "timestamp": ts,
        "symbols": symbols,
        "days": args.days,
        "grid_doc": GRID_DOC,
        "budget": len(VARIANTS),
        "filters": {
            "min_trades": MIN_TRADES,
            "min_profit_factor_gt": MIN_PF,
            "min_expectancy_r_gt": MIN_EXP_R,
        },
    }
    manifest_path = out_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                **meta,
                "variants": {name: overrides for name, overrides in VARIANTS.items()},
                "winners": [row["variant"] for row in rows if row["passes_filters"]],
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    report_path = out_root / "summary.md"
    _write_markdown_report(report_path, rows, meta)

    print(f"\nRanked CSV: {csv_path}")
    print(f"Raw-order CSV: {raw_csv_path}")
    print(f"Manifest: {manifest_path}")
    print(f"Markdown summary: {report_path}")
    print("\n=== Ranking ===")
    print(f"{'Rank':>4} {'Status':>6} {'Variant':<28} {'N':>5} {'Sharpe':>8} {'WR%':>6} {'PF':>6} {'ExpR':>8} {'PnL':>12}")
    for row in rows:
        status = "PASS" if row["passes_filters"] else "FAIL"
        print(
            f"{row['rank']:>4} {status:>6} {row['variant']:<28} {row['n_trades']:>5} {row['sharpe']:>+8.3f} "
            f"{row['win_rate'] * 100:>5.1f}% {row['pf']:>6.3f} "
            f"{row['expectancy_r']:>+8.3f} ${row['pnl']:>+11,.2f}"
        )
    winners = [row for row in rows if row["passes_filters"]]
    print(f"\nSurvivors: {len(winners)}/{len(rows)}")
    if winners:
        print("Winner shortlist:")
        for row in winners:
            print(f"  #{row['rank']} {row['variant']}  exp_r={row['expectancy_r']:+.3f} pf={row['pf']:.3f} sharpe={row['sharpe']:+.3f}")
    else:
        print("No variant passed the minimum filters.")


if __name__ == "__main__":
    main()
