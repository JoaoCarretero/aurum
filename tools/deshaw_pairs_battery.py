"""Pre-registered DE SHAW macro/HMM/revalidation battery."""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data" / "deshaw"
PYTHON_EXE = Path(r"C:\Program Files\FreeCAD 1.1\bin\python.exe")
GRID_DOC = "docs/engines/deshaw/grid.md"

MIN_TRADES = 80
MIN_PROFIT_FACTOR = 1.0
MIN_EXPECTANCY_R = 0.0

VARIANTS: dict[str, dict[str, object]] = {
    "DSH00_baseline": {
        "allowed_macro_entry": "CHOP,BULL",
        "min_hmm_chop_prob": 0.35,
        "max_hmm_trend_prob": 0.55,
        "max_revalidation_misses": 1,
    },
    "DSH01_chop_only": {
        "allowed_macro_entry": "CHOP",
        "min_hmm_chop_prob": 0.35,
        "max_hmm_trend_prob": 0.55,
        "max_revalidation_misses": 1,
    },
    "DSH02_hmm_looser": {
        "allowed_macro_entry": "CHOP,BULL",
        "min_hmm_chop_prob": 0.30,
        "max_hmm_trend_prob": 0.60,
        "max_revalidation_misses": 1,
    },
    "DSH03_hmm_tighter": {
        "allowed_macro_entry": "CHOP,BULL",
        "min_hmm_chop_prob": 0.40,
        "max_hmm_trend_prob": 0.50,
        "max_revalidation_misses": 1,
    },
    "DSH04_no_grace": {
        "allowed_macro_entry": "CHOP,BULL",
        "min_hmm_chop_prob": 0.35,
        "max_hmm_trend_prob": 0.55,
        "max_revalidation_misses": 0,
    },
    "DSH05_chop_only_no_grace": {
        "allowed_macro_entry": "CHOP",
        "min_hmm_chop_prob": 0.35,
        "max_hmm_trend_prob": 0.55,
        "max_revalidation_misses": 0,
    },
    "DSH06_chop_only_tighter": {
        "allowed_macro_entry": "CHOP",
        "min_hmm_chop_prob": 0.40,
        "max_hmm_trend_prob": 0.50,
        "max_revalidation_misses": 1,
    },
    "DSH07_chop_only_looser": {
        "allowed_macro_entry": "CHOP",
        "min_hmm_chop_prob": 0.30,
        "max_hmm_trend_prob": 0.60,
        "max_revalidation_misses": 1,
    },
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the DE SHAW pre-registered battery.")
    parser.add_argument("--days", type=int, required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--basket", default="bluechip")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--out", default=None)
    return parser.parse_args()


def _newest_run_after(before: set[str]) -> Path | None:
    if not DATA_ROOT.exists():
        return None
    candidates = [path for path in DATA_ROOT.iterdir() if path.is_dir() and path.name not in before]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _read_summary(run_dir: Path) -> dict:
    summary = run_dir / "summary.json"
    if summary.exists():
        return json.loads(summary.read_text(encoding="utf-8"))
    legacy = run_dir / "reports" / "newton_backtest_report.json"
    if legacy.exists():
        return json.loads(legacy.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"Missing summary JSON in {run_dir}")


def _read_trades(run_dir: Path) -> list[dict]:
    trades = run_dir / "trades.json"
    if not trades.exists():
        return []
    return json.loads(trades.read_text(encoding="utf-8"))


def _summary_metric(summary: dict, *keys: str) -> float:
    for key in keys:
        value = summary.get(key)
        if value is not None:
            return float(value or 0.0)
    return 0.0


def _trade_metrics(trades: list[dict]) -> tuple[float, float]:
    if not trades:
        return 0.0, 0.0
    gross_win = sum(max(float(trade.get("pnl", 0.0) or 0.0), 0.0) for trade in trades)
    gross_loss = sum(-min(float(trade.get("pnl", 0.0) or 0.0), 0.0) for trade in trades)
    profit_factor = gross_win / gross_loss if gross_loss > 1e-9 else (999.0 if gross_win > 0 else 0.0)
    expectancy_r = sum(float(trade.get("r_multiple", 0.0) or 0.0) for trade in trades) / len(trades)
    return round(profit_factor, 4), round(expectancy_r, 4)


def _evaluate_filters(row: dict) -> tuple[bool, str]:
    reasons: list[str] = []
    if row["trades"] < MIN_TRADES:
        reasons.append(f"n<{MIN_TRADES}")
    if row["profit_factor"] <= MIN_PROFIT_FACTOR:
        reasons.append("pf<=1.0")
    if row["expectancy_r"] <= MIN_EXPECTANCY_R:
        reasons.append("exp<=0")
    return len(reasons) == 0, ",".join(reasons) if reasons else "pass"


def _sort_key(row: dict) -> tuple[float, ...]:
    return (
        1.0 if row["passes_filters"] else 0.0,
        row["sharpe"],
        row["roi"],
        row["profit_factor"],
        row["expectancy_r"],
        row["trades"],
    )


def _cmd_for_variant(args: argparse.Namespace, overrides: dict[str, object]) -> list[str]:
    cmd = [
        str(PYTHON_EXE),
        "engines/deshaw.py",
        "--no-menu",
        "--days",
        str(args.days),
        "--end",
        args.end,
        "--basket",
        args.basket,
        "--interval",
        args.interval,
    ]
    flag_map = {
        "allowed_macro_entry": "--allowed-macro-entry",
        "min_hmm_chop_prob": "--min-hmm-chop-prob",
        "max_hmm_trend_prob": "--max-hmm-trend-prob",
        "max_revalidation_misses": "--max-revalidation-misses",
    }
    for key, flag in flag_map.items():
        if key in overrides:
            cmd.extend([flag, str(overrides[key])])
    return cmd


def _row_from_summary(name: str, run_dir: str, overrides: dict[str, object], summary: dict) -> dict:
    trades = _read_trades(REPO_ROOT / run_dir)
    profit_factor, expectancy_r = _trade_metrics(trades)
    row = {
        "variant": name,
        "run_dir": run_dir,
        "trades": int(summary.get("n_trades", 0)),
        "roi": _summary_metric(summary, "roi", "roi_pct"),
        "sharpe": _summary_metric(summary, "sharpe"),
        "max_dd": _summary_metric(summary, "max_dd", "max_dd_pct"),
        "profit_factor": profit_factor,
        "expectancy_r": expectancy_r,
        "overrides": json.dumps(overrides, sort_keys=True),
    }
    row["passes_filters"], row["filter_note"] = _evaluate_filters(row)
    return row


def main() -> None:
    args = _parse_args()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_root = Path(args.out) if args.out else REPO_ROOT / "data" / "_deshaw_battery" / ts
    out_root.mkdir(parents=True, exist_ok=True)

    print(f"Using pre-registered grid: {GRID_DOC}")
    print(f"Budget locked: {len(VARIANTS)} variants")
    print(f"Window: days={args.days} end={args.end}")
    print(f"Output root: {out_root}")

    rows: list[dict] = []
    for name, overrides in VARIANTS.items():
        print(f"\n==== {name} overrides={overrides} ====")
        stdout_path = out_root / f"{name}.stdout.txt"
        stderr_path = out_root / f"{name}.stderr.txt"

        before = {path.name for path in DATA_ROOT.iterdir()} if DATA_ROOT.exists() else set()
        cmd = _cmd_for_variant(args, overrides)
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
        stdout_path.write_text(proc.stdout, encoding="utf-8")
        stderr_path.write_text(proc.stderr, encoding="utf-8")

        if proc.returncode != 0:
            row = {
                "variant": name,
                "run_dir": "",
                "trades": 0,
                "roi": 0.0,
                "sharpe": 0.0,
                "max_dd": 0.0,
                "profit_factor": 0.0,
                "expectancy_r": 0.0,
                "passes_filters": False,
                "filter_note": f"error:exit_{proc.returncode}",
                "overrides": json.dumps(overrides, sort_keys=True),
            }
            rows.append(row)
            print(f"  ERROR exit={proc.returncode}")
            continue

        run_dir = _newest_run_after(before)
        if run_dir is None:
            row = {
                "variant": name,
                "run_dir": "",
                "trades": 0,
                "roi": 0.0,
                "sharpe": 0.0,
                "max_dd": 0.0,
                "profit_factor": 0.0,
                "expectancy_r": 0.0,
                "passes_filters": False,
                "filter_note": "error:no_run_dir",
                "overrides": json.dumps(overrides, sort_keys=True),
            }
            rows.append(row)
            print("  ERROR no run dir detected")
            continue

        summary = _read_summary(run_dir)
        row = _row_from_summary(name, str(run_dir.relative_to(REPO_ROOT)), overrides, summary)
        rows.append(row)
        print(
            f"  trades={row['trades']} roi={row['roi']:+.2f}% sharpe={row['sharpe']:+.3f} "
            f"pf={row['profit_factor']:.2f} expR={row['expectancy_r']:+.3f} "
            f"maxdd={row['max_dd']:.1f}% status={'PASS' if row['passes_filters'] else 'FAIL'}"
            f"[{row['filter_note']}]"
        )

    rows.sort(key=_sort_key, reverse=True)
    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx

    ranked_csv = out_root / "results_ranked.csv"
    with ranked_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    manifest = out_root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "timestamp": ts,
                "grid_doc": GRID_DOC,
                "days": args.days,
                "end": args.end,
                "basket": args.basket,
                "interval": args.interval,
                "budget": len(VARIANTS),
                "variants": VARIANTS,
                "winners": [row["variant"] for row in rows if row["passes_filters"]],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"\nRanked CSV: {ranked_csv}")
    print(f"Manifest: {manifest}")
    print("\n=== Ranking ===")
    print(
        f"{'Rank':>4} {'Status':>6} {'Variant':<24} {'N':>5} {'ROI%':>8} "
        f"{'Sharpe':>8} {'PF':>6} {'ExpR':>7} {'MaxDD%':>8}"
    )
    for row in rows:
        status = "PASS" if row["passes_filters"] else "FAIL"
        print(
            f"{row['rank']:>4} {status:>6} {row['variant']:<24} {row['trades']:>5} "
            f"{row['roi']:>+8.2f} {row['sharpe']:>+8.3f} {row['profit_factor']:>6.2f} "
            f"{row['expectancy_r']:>+7.3f} {row['max_dd']:>8.1f}"
        )


if __name__ == "__main__":
    main()
