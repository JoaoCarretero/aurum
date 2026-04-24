"""Rolling BRIDGEWATER channel-ablation battery inside the valid sentiment window.

Runs `tools/bridgewater_compare_battery.py` on multiple end timestamps using the
same disciplined runtime gates, then aggregates which channel thesis wins more
often across the covered recent window.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
PYTHON = sys.executable


def _default_ends() -> list[str]:
    return [
        "2026-04-05T19:00:00",
        "2026-04-10T19:00:00",
        "2026-04-15T19:00:00",
        "2026-04-20T19:00:00",
    ]


def _extract_variant_metrics(row: dict | None) -> dict:
    row = row or {}
    summary = row.get("summary") or {}
    diagnostics = row.get("sentiment_diagnostics") or {}
    overfit = row.get("overfit") or {}
    return {
        "n_trades": summary.get("n_trades"),
        "roi_pct": summary.get("roi_pct"),
        "sharpe": summary.get("sharpe"),
        "max_dd_pct": summary.get("max_dd_pct"),
        "oi_zero_pct": diagnostics.get("oi_zero_pct"),
        "oi_nonzero_trades": diagnostics.get("oi_nonzero_trades"),
        "ls_zero_pct": diagnostics.get("ls_zero_pct"),
        "overfit": {
            "passed": overfit.get("passed"),
            "warnings": overfit.get("warnings"),
            "failed": overfit.get("failed"),
        } if overfit else None,
    }


def _run_one(end_value: str, days: int, basket: str, preset: str, allowed_regimes: str, out_base: Path) -> dict:
    tag = end_value.replace(":", "").replace("T", "_")
    out_dir = out_base / "runs" / tag
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        PYTHON,
        "tools/bridgewater_compare_battery.py",
        "--days",
        str(days),
        "--basket",
        basket,
        "--preset",
        preset,
        "--allowed-regimes",
        allowed_regimes,
        "--end",
        end_value,
    ]
    proc = subprocess.run(
        cmd,
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    (out_dir / "stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
    (out_dir / "stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
    if proc.returncode != 0:
        return {"end": end_value, "status": f"EXIT {proc.returncode}"}

    report_dirs = sorted(
        (REPO / "data" / "_bridgewater_compare").glob("*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    report_payload = None
    report_dir = None
    for cand in report_dirs[:5]:
        path = cand / "report.json"
        if path.exists():
            report_payload = json.loads(path.read_text(encoding="utf-8"))
            report_dir = cand
            break
    if report_payload is None:
        return {"end": end_value, "status": "NO_REPORT"}

    (out_dir / "report.json").write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
    variants = {row["variant"]: row for row in report_payload.get("variants", [])}
    oi = variants.get("funding+oi+ls", {}).get("summary", {})
    ls = variants.get("funding+ls", {}).get("summary", {})
    winner = "tie"
    if float(ls.get("sharpe") or 0.0) > float(oi.get("sharpe") or 0.0):
        winner = "funding+ls"
    elif float(oi.get("sharpe") or 0.0) > float(ls.get("sharpe") or 0.0):
        winner = "funding+oi+ls"
    return {
        "end": end_value,
        "status": "OK",
        "winner": winner,
        "report_dir": str(report_dir.relative_to(REPO)) if report_dir else None,
        "funding_oi_ls": _extract_variant_metrics(variants.get("funding+oi+ls")),
        "funding_ls": _extract_variant_metrics(variants.get("funding+ls")),
    }


def _write_report(rows: list[dict], out_base: Path, args: argparse.Namespace) -> None:
    wins = {"funding+ls": 0, "funding+oi+ls": 0, "tie": 0}
    for row in rows:
        if row.get("status") == "OK":
            wins[row["winner"]] = wins.get(row["winner"], 0) + 1

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "days": args.days,
        "basket": args.basket,
        "preset": args.preset,
        "allowed_regimes": args.allowed_regimes,
        "ends": args.ends,
        "wins": wins,
        "rows": rows,
    }
    (out_base / "report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# BRIDGEWATER rolling compare battery",
        "",
        f"days: `{args.days}`  basket: `{args.basket}`  preset: `{args.preset}`  regimes: `{args.allowed_regimes}`",
        "",
        f"wins: `funding+LS={wins['funding+ls']}`  `funding+OI+LS={wins['funding+oi+ls']}`  `tie={wins['tie']}`",
        "",
        "| End | Winner | OI+LS Sharpe | OI+LS ROI | OI zero | LS Sharpe | LS ROI | OI gap |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        if row.get("status") != "OK":
            lines.append(f"| {row['end']} | {row.get('status')} | - | - | - | - | - | - |")
            continue
        oi = row["funding_oi_ls"]
        ls = row["funding_ls"]
        oi_zero = float(oi.get("oi_zero_pct") or 0.0)
        sharpe_gap = float(ls.get("sharpe") or 0.0) - float(oi.get("sharpe") or 0.0)
        lines.append(
            f"| {row['end']} | {row['winner']} | {float(oi['sharpe'] or 0.0):+.3f} | "
            f"{float(oi['roi_pct'] or 0.0):+.2f}% | {oi_zero:.2f}% | {float(ls['sharpe'] or 0.0):+.3f} | "
            f"{float(ls['roi_pct'] or 0.0):+.2f}% | {sharpe_gap:+.3f} |"
        )
    (out_base / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Rolling BRIDGEWATER compare battery over covered recent windows.")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--basket", default="bluechip")
    ap.add_argument("--preset", default="robust")
    ap.add_argument("--allowed-regimes", default="BEAR,CHOP")
    ap.add_argument("--ends", nargs="*", default=_default_ends())
    args = ap.parse_args()

    run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_base = REPO / "data" / "_bridgewater_rolling_compare" / run_id
    out_base.mkdir(parents=True, exist_ok=True)

    print(f"BRIDGEWATER rolling compare battery @ {run_id}")
    rows = []
    for end_value in args.ends:
        print(f"  running end={end_value}")
        rows.append(_run_one(end_value, args.days, args.basket, args.preset, args.allowed_regimes, out_base))

    _write_report(rows, out_base, args)
    print((out_base / "report.md").read_text(encoding="utf-8"))
    print(f"\nreports: {out_base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
