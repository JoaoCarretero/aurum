"""Rolling BRIDGEWATER battery comparing robust ALL-regimes vs robust BEAR,CHOP.

This isolates whether the regime filter itself deserves promotion from an
operator flag to an explicit operational preset.
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


def _extract_metrics(payload: dict) -> dict:
    return {
        "n_trades": payload.get("n_trades"),
        "roi": payload.get("roi"),
        "sharpe": payload.get("sharpe"),
        "max_dd_pct": payload.get("max_dd_pct"),
        "allowed_macro_regimes": payload.get("allowed_macro_regimes"),
        "overfit": {
            "passed": payload.get("overfit_passed"),
            "warnings": payload.get("overfit_warnings"),
            "failed": payload.get("overfit_failed"),
        },
    }


def _run_one(end_value: str, days: int, basket: str, allowed_regimes: str | None, out_base: Path) -> dict:
    tag = end_value.replace(":", "").replace("T", "_")
    regime_tag = "all" if not allowed_regimes else allowed_regimes.replace(",", "_").lower()
    out_dir = out_base / "runs" / tag / regime_tag
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        PYTHON,
        "engines/bridgewater.py",
        "--days",
        str(days),
        "--basket",
        basket,
        "--no-menu",
        "--preset",
        "robust",
        "--end",
        end_value,
    ]
    if allowed_regimes:
        cmd.extend(["--allowed-regimes", allowed_regimes])

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
        return {"end": end_value, "status": f"EXIT {proc.returncode}", "allowed_regimes": allowed_regimes}

    report_dirs = sorted(
        (REPO / "data" / "bridgewater").glob("*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    payload = None
    report_dir = None
    for cand in report_dirs[:5]:
        path = cand / "reports" / "bridgewater_1h_v1.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            report_dir = cand
            break
    if payload is None:
        return {"end": end_value, "status": "NO_REPORT", "allowed_regimes": allowed_regimes}

    (out_dir / "report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {
        "end": end_value,
        "status": "OK",
        "allowed_regimes": allowed_regimes,
        "report_dir": str(report_dir.relative_to(REPO)) if report_dir else None,
        "metrics": _extract_metrics(payload),
    }


def _write_report(rows: list[dict], out_base: Path, args: argparse.Namespace) -> None:
    grouped: dict[str, dict] = {}
    for row in rows:
        grouped.setdefault(row["end"], {})["all" if not row.get("allowed_regimes") else "bearchop"] = row

    wins = {"all": 0, "bearchop": 0, "tie": 0}
    table_rows: list[dict] = []
    for end_value in args.ends:
        all_row = grouped.get(end_value, {}).get("all")
        bc_row = grouped.get(end_value, {}).get("bearchop")
        winner = "tie"
        if all_row and bc_row and all_row.get("status") == "OK" and bc_row.get("status") == "OK":
            all_sharpe = float((all_row.get("metrics") or {}).get("sharpe") or 0.0)
            bc_sharpe = float((bc_row.get("metrics") or {}).get("sharpe") or 0.0)
            if bc_sharpe > all_sharpe:
                winner = "bearchop"
            elif all_sharpe > bc_sharpe:
                winner = "all"
        wins[winner] = wins.get(winner, 0) + 1
        table_rows.append({"end": end_value, "winner": winner, "all": all_row, "bearchop": bc_row})

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "days": args.days,
        "basket": args.basket,
        "ends": args.ends,
        "wins": wins,
        "rows": table_rows,
    }
    (out_base / "report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# BRIDGEWATER regime filter battery",
        "",
        f"days: `{args.days}`  basket: `{args.basket}`",
        "",
        f"wins: `ALL={wins['all']}`  `BEAR,CHOP={wins['bearchop']}`  `tie={wins['tie']}`",
        "",
        "| End | Winner | ALL Sharpe | ALL ROI | ALL N | BEAR,CHOP Sharpe | BEAR,CHOP ROI | BEAR,CHOP N | Gap |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in table_rows:
        all_row = row.get("all")
        bc_row = row.get("bearchop")
        if not all_row or not bc_row or all_row.get("status") != "OK" or bc_row.get("status") != "OK":
            lines.append(f"| {row['end']} | {row['winner']} | - | - | - | - | - | - | - |")
            continue
        all_metrics = all_row["metrics"]
        bc_metrics = bc_row["metrics"]
        gap = float(bc_metrics.get("sharpe") or 0.0) - float(all_metrics.get("sharpe") or 0.0)
        lines.append(
            f"| {row['end']} | {row['winner']} | {float(all_metrics.get('sharpe') or 0.0):+.3f} | "
            f"{float(all_metrics.get('roi') or 0.0):+.2f}% | {all_metrics.get('n_trades')} | "
            f"{float(bc_metrics.get('sharpe') or 0.0):+.3f} | {float(bc_metrics.get('roi') or 0.0):+.2f}% | "
            f"{bc_metrics.get('n_trades')} | {gap:+.3f} |"
        )
    (out_base / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Rolling BRIDGEWATER battery comparing ALL-regimes vs BEAR,CHOP.")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--basket", default="bluechip")
    ap.add_argument("--ends", nargs="*", default=_default_ends())
    args = ap.parse_args()

    run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_base = REPO / "data" / "_bridgewater_regime_filter" / run_id
    out_base.mkdir(parents=True, exist_ok=True)

    print(f"BRIDGEWATER regime filter battery @ {run_id}")
    rows = []
    for end_value in args.ends:
        print(f"  running end={end_value} all-regimes")
        rows.append(_run_one(end_value, args.days, args.basket, None, out_base))
        print(f"  running end={end_value} bearchop")
        rows.append(_run_one(end_value, args.days, args.basket, "BEAR,CHOP", out_base))

    _write_report(rows, out_base, args)
    print((out_base / "report.md").read_text(encoding="utf-8"))
    print(f"\nreports: {out_base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
