"""Pre-registered DE SHAW pairs mean-reversion battery."""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data" / "deshaw"
PYTHON_EXE = Path(r"C:\Program Files\FreeCAD 1.1\bin\python.exe")
GRID_DOC = "docs/engines/deshaw/2026-04-18_pairs_mr_grid.md"

MIN_TRADES = 200
MIN_SHARPE = 0.0
MIN_ROI = 0.0

VARIANTS: dict[str, dict] = {
    "DS00_baseline_recommended": {"z_entry": 3.0, "z_exit": 0.0, "z_stop": 3.5, "pvalue": 0.15, "hl_max": 300},
    "DS01_p010": {"z_entry": 3.0, "z_exit": 0.0, "z_stop": 3.5, "pvalue": 0.10, "hl_max": 300},
    "DS02_p005": {"z_entry": 3.0, "z_exit": 0.0, "z_stop": 3.5, "pvalue": 0.05, "hl_max": 300},
    "DS03_hl200": {"z_entry": 3.0, "z_exit": 0.0, "z_stop": 3.5, "pvalue": 0.15, "hl_max": 200},
    "DS04_hold_shorter": {"z_entry": 3.0, "z_exit": 0.0, "z_stop": 3.5, "pvalue": 0.15, "hl_max": 300, "max_hold": 72},
    "DS05_z35": {"z_entry": 3.5, "z_exit": 0.0, "z_stop": 4.0, "pvalue": 0.15, "hl_max": 300},
}


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run pre-registered DE SHAW pairs battery.")
    ap.add_argument("--days", type=int, default=1095)
    ap.add_argument("--basket", default="bluechip")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--out", default=None)
    return ap.parse_args()


def _newest_run_after(before: set[str]) -> Path | None:
    if not DATA_ROOT.exists():
        return None
    candidates = [p for p in DATA_ROOT.iterdir() if p.is_dir() and p.name not in before]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _read_summary(run_dir: Path) -> dict:
    summary = run_dir / "summary.json"
    if summary.exists():
        return json.loads(summary.read_text(encoding="utf-8"))
    legacy = run_dir / "reports" / "newton_backtest_report.json"
    if legacy.exists():
        return json.loads(legacy.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"Missing summary JSON in {run_dir}")


def _evaluate_filters(row: dict) -> tuple[bool, str]:
    reasons = []
    if row["trades"] < MIN_TRADES:
        reasons.append(f"n<{MIN_TRADES}")
    if row["sharpe"] <= MIN_SHARPE:
        reasons.append("sharpe<=0")
    if row["roi"] <= MIN_ROI:
        reasons.append("roi<=0")
    return len(reasons) == 0, ",".join(reasons) if reasons else "pass"


def _sort_key(row: dict) -> tuple:
    return (
        1 if row["passes_filters"] else 0,
        row["sharpe"],
        row["roi"],
        row["trades"],
    )


def _cmd_for_variant(args: argparse.Namespace, overrides: dict) -> list[str]:
    cmd = [
        str(PYTHON_EXE),
        "engines/deshaw.py",
        "--no-menu",
        "--days", str(args.days),
        "--basket", args.basket,
        "--interval", args.interval,
    ]
    flag_map = {
        "z_entry": "--z-entry",
        "z_exit": "--z-exit",
        "z_stop": "--z-stop",
        "pvalue": "--pvalue",
        "hl_max": "--hl-max",
        "max_hold": "--max-hold",
        "size_mult": "--size-mult",
    }
    for key, flag in flag_map.items():
        if key in overrides:
            cmd.extend([flag, str(overrides[key])])
    return cmd


def main() -> None:
    args = _parse_args()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_root = Path(args.out) if args.out else REPO_ROOT / "data" / "_deshaw_battery" / ts
    out_root.mkdir(parents=True, exist_ok=True)

    print(f"Using pre-registered grid: {GRID_DOC}")
    print(f"Budget locked: {len(VARIANTS)} variants")
    print(f"Output root: {out_root}")

    rows = []
    for name, overrides in VARIANTS.items():
        print(f"\n==== {name} overrides={overrides} ====")
        stdout_path = out_root / f"{name}.stdout.txt"
        stderr_path = out_root / f"{name}.stderr.txt"
        cached_run_dir = None
        if stdout_path.exists():
            for line in stdout_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if "data\\deshaw\\" in line:
                    start = line.find("data\\deshaw\\")
                    rel = line[start:].strip().rstrip("/\\")
                    candidate = REPO_ROOT / Path(rel)
                    if candidate.exists():
                        cached_run_dir = candidate
        if cached_run_dir is not None:
            summary = _read_summary(cached_run_dir)
            row = {
                "variant": name,
                "run_dir": str(cached_run_dir.relative_to(REPO_ROOT)),
                "trades": int(summary.get("n_trades", 0)),
                "roi": float(summary.get("roi", summary.get("roi_pct", 0.0)) or 0.0),
                "sharpe": float(summary.get("sharpe", 0.0) or 0.0),
                "max_dd": float(summary.get("max_dd", summary.get("max_dd_pct", 0.0)) or 0.0),
                "overrides": json.dumps(overrides, sort_keys=True),
            }
            row["passes_filters"], row["filter_note"] = _evaluate_filters(row)
            rows.append(row)
            print(
                f"  cached trades={row['trades']} roi={row['roi']:+.2f}% "
                f"sharpe={row['sharpe']:+.3f} maxdd={row['max_dd']:.1f}% "
                f"status={'PASS' if row['passes_filters'] else 'FAIL'}[{row['filter_note']}]"
            )
            continue

        before = {p.name for p in DATA_ROOT.iterdir()} if DATA_ROOT.exists() else set()
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
                "passes_filters": False,
                "filter_note": "error:no_run_dir",
                "overrides": json.dumps(overrides, sort_keys=True),
            }
            rows.append(row)
            print("  ERROR no run dir detected")
            continue

        summary = _read_summary(run_dir)
        row = {
            "variant": name,
            "run_dir": str(run_dir.relative_to(REPO_ROOT)),
            "trades": int(summary.get("n_trades", 0)),
            "roi": float(summary.get("roi", summary.get("roi_pct", 0.0)) or 0.0),
            "sharpe": float(summary.get("sharpe", 0.0) or 0.0),
            "max_dd": float(summary.get("max_dd", summary.get("max_dd_pct", 0.0)) or 0.0),
            "overrides": json.dumps(overrides, sort_keys=True),
        }
        row["passes_filters"], row["filter_note"] = _evaluate_filters(row)
        rows.append(row)
        print(
            f"  trades={row['trades']} roi={row['roi']:+.2f}% "
            f"sharpe={row['sharpe']:+.3f} maxdd={row['max_dd']:.1f}% "
            f"status={'PASS' if row['passes_filters'] else 'FAIL'}[{row['filter_note']}]"
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
    manifest.write_text(json.dumps({
        "timestamp": ts,
        "grid_doc": GRID_DOC,
        "days": args.days,
        "basket": args.basket,
        "interval": args.interval,
        "budget": len(VARIANTS),
        "variants": VARIANTS,
        "winners": [row["variant"] for row in rows if row["passes_filters"]],
    }, indent=2) + "\n", encoding="utf-8")

    print(f"\nRanked CSV: {ranked_csv}")
    print(f"Manifest: {manifest}")
    print("\n=== Ranking ===")
    print(f"{'Rank':>4} {'Status':>6} {'Variant':<24} {'N':>5} {'ROI%':>8} {'Sharpe':>8} {'MaxDD%':>8}")
    for row in rows:
        status = "PASS" if row["passes_filters"] else "FAIL"
        print(
            f"{row['rank']:>4} {status:>6} {row['variant']:<24} {row['trades']:>5} "
            f"{row['roi']:>+8.2f} {row['sharpe']:>+8.3f} {row['max_dd']:>8.1f}"
        )


if __name__ == "__main__":
    main()
