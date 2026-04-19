"""Run a runnable audit across the current registry and write a report.

This complements tools/audits/engine_validation.py by covering the broader
registry in config/engines.py, including newer research engines and runtime
entrypoints that need honest classification (ok / failed / blocked /
not_applicable) instead of being silently omitted.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent.parent
PYTHON = Path(sys.executable)
STAMP = datetime.now().strftime("%Y-%m-%d_%H%M%S")
OUT_DIR = ROOT / "data" / "audit" / f"full_registry_{STAMP}"
RAW_PATH = OUT_DIR / "results.json"
REPORT_PATH = OUT_DIR / "REPORT.md"


@dataclass(frozen=True)
class AuditSpec:
    slug: str
    display: str
    category: str
    mode: str
    command: tuple[str, ...] = ()
    data_root: str | None = None
    input_text: str = ""
    report_glob: str | None = None
    notes: str = ""


SPECS: list[AuditSpec] = [
    AuditSpec(
        slug="citadel",
        display="CITADEL",
        category="directional",
        mode="run",
        command=("engines/citadel.py", "--days", "{days}", "--basket", "{basket}", "--leverage", "1.0", "--no-menu"),
        data_root="data/runs",
    ),
    AuditSpec(
        slug="renaissance",
        display="RENAISSANCE",
        category="directional",
        mode="run",
        command=("engines/renaissance.py", "--days", "{days}", "--basket", "{basket}", "--no-menu"),
        data_root="data/renaissance",
        report_glob="reports/renaissance_*_v1.json",
    ),
    AuditSpec(
        slug="jump",
        display="JUMP",
        category="directional",
        mode="run",
        command=("engines/jump.py", "--days", "{days}", "--basket", "{basket}", "--no-menu"),
        data_root="data/jump",
        report_glob="reports/jump_*_v1.json",
    ),
    AuditSpec(
        slug="bridgewater",
        display="BRIDGEWATER",
        category="directional",
        mode="run",
        command=("engines/bridgewater.py", "--days", "{days}", "--basket", "{basket}", "--no-menu"),
        data_root="data/bridgewater",
    ),
    AuditSpec(
        slug="deshaw",
        display="DE SHAW",
        category="directional",
        mode="run",
        command=("engines/deshaw.py", "--days", "{days}", "--basket", "{basket}", "--no-menu"),
        data_root="data/deshaw",
    ),
    AuditSpec(
        slug="kepos",
        display="KEPOS",
        category="directional",
        mode="run",
        command=("engines/kepos.py", "--days", "{days}", "--basket", "{basket}", "--no-menu"),
        data_root="data/kepos",
    ),
    AuditSpec(
        slug="graham",
        display="GRAHAM",
        category="directional",
        mode="run",
        command=("engines/graham.py", "--days", "{days}", "--basket", "{basket}", "--no-menu"),
        data_root="data/graham",
    ),
    AuditSpec(
        slug="medallion",
        display="MEDALLION",
        category="directional",
        mode="run",
        command=("engines/medallion.py", "--days", "{days}", "--basket", "{basket}", "--no-menu"),
        data_root="data/medallion",
    ),
    AuditSpec(
        slug="phi",
        display="PHI",
        category="directional",
        mode="run",
        command=("engines/phi.py", "--days", "{days}", "--basket", "{basket}"),
        data_root="data/phi",
    ),
    AuditSpec(
        slug="ornstein",
        display="ORNSTEIN",
        category="directional",
        mode="run",
        command=("engines/ornstein.py", "--days", "{days}", "--basket", "{basket}", "--no-menu"),
        data_root="data/ornstein",
    ),
    AuditSpec(
        slug="millennium",
        display="MILLENNIUM",
        category="meta",
        mode="run",
        command=("engines/millennium.py",),
        data_root="data/millennium",
        input_text="1\n{days}\n\n\n\n\n\nn\n\n",
        report_glob="reports/multistrategy_*_v1.json",
        notes="Interactive engine; audit feeds the default backtest menu path (option 1).",
    ),
    AuditSpec(
        slug="twosigma",
        display="TWO SIGMA",
        category="meta",
        mode="advisory",
        command=("engines/twosigma.py",),
        data_root="data/twosigma",
        notes="Advisory entrypoint; requires upstream trade history or orchestration via MILLENNIUM.",
    ),
    AuditSpec(
        slug="aqr",
        display="AQR",
        category="meta",
        mode="run",
        command=("engines/aqr.py",),
        data_root="data/aqr",
        notes="Consumes existing trade history from prior backtests.",
    ),
    AuditSpec(
        slug="janestreet",
        display="JANE STREET",
        category="arb",
        mode="run",
        command=("engines/janestreet.py", "--simulate-historical", "--sim-capital", "1000"),
        data_root="data/janestreet",
        report_glob="reports/simulate_historical.json",
    ),
    AuditSpec(
        slug="winton",
        display="WINTON",
        category="tool",
        mode="run",
        command=("core/chronos.py",),
        notes="Toolkit/demo entrypoint; validates dependency availability and feature enrichment path.",
    ),
    AuditSpec(
        slug="live",
        display="LIVE",
        category="runtime",
        mode="help_only",
        command=("engines/live.py", "--help"),
        notes="Infinite runtime loop; audit checks CLI/bootstrap only, not a live session start.",
    ),
]


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    return env


def _run(args: list[str], *, input_text: str = "", timeout: int = 5400) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PYTHON), *args],
        input=input_text,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
        env=_env(),
        timeout=timeout,
    )


def _list_dirs(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {p.name for p in path.iterdir() if p.is_dir()}


def _latest_dir(path: Path, before: set[str]) -> Path | None:
    if not path.exists():
        return None
    created = [p for p in path.iterdir() if p.is_dir() and p.name not in before]
    if created:
        return max(created, key=lambda p: p.stat().st_mtime)
    dirs = [p for p in path.iterdir() if p.is_dir()]
    return max(dirs, key=lambda p: p.stat().st_mtime) if dirs else None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _equity_from_trades(account_size: float, trades: list[dict[str, Any]]) -> list[float]:
    cur = account_size
    eq = [cur]
    for trade in trades:
        cur += float(trade.get("pnl", 0.0) or 0.0)
        eq.append(cur)
    return eq


def _max_dd_pct(equity: list[float]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak)
    return round(max_dd * 100.0, 2)


def _extract_summary(data: dict[str, Any]) -> dict[str, Any]:
    summary = dict(data.get("summary", {})) if isinstance(data.get("summary"), dict) else dict(data)
    total_trades = (
        summary.get("total_trades")
        or summary.get("n_trades")
        or summary.get("total")
        or 0
    )
    win_rate = summary.get("win_rate", 0.0)
    if isinstance(win_rate, (int, float)) and win_rate <= 1.0:
        win_rate = float(win_rate) * 100.0
    max_dd = summary.get("max_dd_pct", summary.get("max_drawdown", summary.get("max_dd", 0.0)))
    if isinstance(max_dd, (int, float)) and max_dd <= 1.0:
        max_dd = float(max_dd) * 100.0
    pnl = summary.get("total_pnl", summary.get("pnl", 0.0))
    final_equity = summary.get("final_equity")
    if final_equity is None and "account_size" in data and isinstance(pnl, (int, float)):
        final_equity = float(data["account_size"]) + float(pnl)
    metrics_note = summary.get("metrics_note")
    if not metrics_note and summary.get("metrics_reliable") is False:
        metrics_note = "insufficient_sample"
    return {
        "n_trades": int(total_trades or 0),
        "win_rate": float(win_rate or 0.0),
        "pnl": float(pnl or 0.0),
        "sharpe": summary.get("sharpe"),
        "sortino": summary.get("sortino"),
        "max_dd_pct": float(max_dd or 0.0),
        "final_equity": final_equity,
        "metrics_note": metrics_note,
    }


def _parse_run_artifact(run_dir: Path, spec: AuditSpec) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    if summary_path.exists():
        parsed = _extract_summary(_load_json(summary_path))
        parsed["artifact"] = str(summary_path.relative_to(ROOT))
        return parsed

    if spec.report_glob:
        reports = sorted(run_dir.glob(spec.report_glob))
        if reports:
            report_path = reports[-1]
            data = _load_json(report_path)
            if report_path.name == "simulate_historical.json":
                return {
                    "scanner": True,
                    "artifact": str(report_path.relative_to(ROOT)),
                    "total_opportunities": int(data.get("total_opportunities", 0)),
                    "profitable_count": int(data.get("profitable_count", 0)),
                    "avg_apr": float(data.get("avg_apr", 0.0)),
                    "estimated_monthly_income": float(data.get("estimated_monthly_income", 0.0)),
                }
            parsed = _extract_summary(data)
            if parsed["n_trades"] == 0 and isinstance(data.get("trades"), list):
                trades = list(data.get("trades", []))
                eq = _equity_from_trades(float(data.get("account_size", 10000.0)), trades)
                parsed["n_trades"] = len(trades)
                parsed["final_equity"] = eq[-1] if eq else float(data.get("account_size", 10000.0))
                parsed["pnl"] = round(parsed["final_equity"] - float(data.get("account_size", 10000.0)), 2)
                parsed["max_dd_pct"] = float(data.get("max_dd_pct", _max_dd_pct(eq)))
            parsed["artifact"] = str(report_path.relative_to(ROOT))
            return parsed

    json_candidates = sorted(
        [p for p in run_dir.rglob("*.json") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
    )
    if json_candidates:
        parsed = _extract_summary(_load_json(json_candidates[-1]))
        parsed["artifact"] = str(json_candidates[-1].relative_to(ROOT))
        return parsed
    raise FileNotFoundError(f"no summary/report artifact found in {run_dir}")


def _parse_advisory(spec: AuditSpec, proc: subprocess.CompletedProcess[str], before: set[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if spec.data_root:
        latest = _latest_dir(ROOT / spec.data_root, before)
        if latest is not None:
            result["run_dir"] = str(latest.relative_to(ROOT))
    stdout = proc.stdout.lower()
    if "requer trades de outros engines" in stdout or "requires" in stdout:
        result["status"] = "blocked"
        result["failure_summary"] = "Requires upstream trade history / orchestration instead of standalone execution."
    else:
        result["status"] = "ok"
    return result


def _failure_summary(proc: subprocess.CompletedProcess[str]) -> str | None:
    hay = f"{proc.stdout}\n{proc.stderr}".lower()
    checks = [
        ("read timed out", "Network read timeout during external data fetch."),
        ("http 202", "External API returned HTTP 202 during data fetch."),
        ("statsmodels", "statsmodels dependency missing for statistical routines."),
        ("lightgbm", "LightGBM dependency missing for ML meta-engine."),
        ("could not fetch data", "Could not fetch market data in the current environment."),
        ("no trades found", "Engine requires prior backtests / trade history before running."),
        ("no valid cointegrated pairs", "No valid cointegrated pairs found for the current window."),
    ]
    for needle, summary in checks:
        if needle in hay:
            return summary
    return None


def run_spec(spec: AuditSpec, days: int, basket: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "slug": spec.slug,
        "engine": spec.display,
        "category": spec.category,
        "mode": spec.mode,
        "notes": spec.notes,
    }
    if spec.mode == "not_applicable":
        result["status"] = "not_applicable"
        return result

    before = _list_dirs(ROOT / spec.data_root) if spec.data_root else set()
    cmd = [arg.format(days=days, basket=basket) for arg in spec.command]
    input_text = spec.input_text.format(days=days, basket=basket) if spec.input_text else ""
    timeout = 180 if spec.mode == "help_only" else 7200
    proc = _run(cmd, input_text=input_text, timeout=timeout)
    result["returncode"] = proc.returncode
    result["stdout_tail"] = proc.stdout[-4000:]
    result["stderr_tail"] = proc.stderr[-2000:]
    result["invocation"] = [str(PYTHON), *cmd]

    if spec.mode == "help_only":
        result["status"] = "ok" if proc.returncode == 0 else "failed"
        result["artifact"] = "cli_help_only"
        return result

    if proc.returncode != 0:
        result["status"] = "failed"
        result["failure_summary"] = _failure_summary(proc)
        return result

    if spec.mode == "advisory":
        result.update(_parse_advisory(spec, proc, before))
        return result

    if spec.data_root:
        run_dir = _latest_dir(ROOT / spec.data_root, before)
        if run_dir is not None and run_dir.is_dir():
            result["run_dir"] = str(run_dir.relative_to(ROOT))
            try:
                result.update(_parse_run_artifact(run_dir, spec))
            except Exception as exc:  # pragma: no cover - defensive audit output
                result["status"] = "failed"
                result["failure_summary"] = str(exc)
                return result

    if "status" not in result:
        result["status"] = "ok"
    return result


def _fmt_float(value: Any, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{digits}f}"


def _fmt_pct(value: Any, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{digits}f}%"


def build_report(results: list[dict[str, Any]], days: int, basket: str) -> str:
    now = datetime.now().isoformat(timespec="seconds")
    counts: dict[str, int] = {}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    lines = [
        "# Full Registry Audit",
        "",
        f"- Generated at: `{now}`",
        f"- Days: `{days}`",
        f"- Basket: `{basket}`",
        f"- Python: `{PYTHON}`",
        "",
        "## Status Summary",
        "",
        f"- ok: `{counts.get('ok', 0)}`",
        f"- failed: `{counts.get('failed', 0)}`",
        f"- blocked: `{counts.get('blocked', 0)}`",
        f"- not_applicable: `{counts.get('not_applicable', 0)}`",
        "",
        "## Results",
        "",
    ]

    for row in results:
        lines.append(f"### {row['engine']}")
        lines.append(f"- Status: `{row['status']}`")
        lines.append(f"- Category: `{row['category']}`")
        if row.get("notes"):
            lines.append(f"- Notes: {row['notes']}")
        if row.get("failure_summary"):
            lines.append(f"- Failure summary: {row['failure_summary']}")
        if row.get("scanner"):
            lines.extend(
                [
                    f"- Opportunities: `{row.get('total_opportunities', 0)}`",
                    f"- Profitable count: `{row.get('profitable_count', 0)}`",
                    f"- Avg APR: `{_fmt_pct(row.get('avg_apr'), 2)}`",
                    f"- Est. monthly income ($1000): `${_fmt_float(row.get('estimated_monthly_income'))}`",
                ]
            )
        elif row["status"] == "ok" and row.get("artifact") not in (None, "cli_help_only"):
            lines.extend(
                [
                    f"- Trades: `{row.get('n_trades', 0)}`",
                    f"- WR: `{_fmt_pct(row.get('win_rate'))}`",
                    f"- PnL: `${_fmt_float(row.get('pnl'))}`",
                    f"- Sharpe: `{_fmt_float(row.get('sharpe'), 3)}`",
                    f"- Sortino: `{_fmt_float(row.get('sortino'), 3)}`",
                    f"- MaxDD: `{_fmt_pct(row.get('max_dd_pct'))}`",
                    f"- Final equity: `${_fmt_float(row.get('final_equity'))}`",
                ]
            )
            if row.get("metrics_note"):
                lines.append(f"- Metrics note: `{row['metrics_note']}`")
        if row.get("run_dir"):
            lines.append(f"- Run dir: `{row['run_dir']}`")
        if row.get("artifact"):
            lines.append(f"- Artifact: `{row['artifact']}`")
        if row.get("returncode") is not None:
            lines.append(f"- Return code: `{row['returncode']}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Run a runnable audit across the full registry.")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--basket", default="bluechip")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = [run_spec(spec, args.days, args.basket) for spec in SPECS]
    RAW_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    REPORT_PATH.write_text(build_report(results, args.days, args.basket), encoding="utf-8")

    print(f"REPORT -> {REPORT_PATH}")
    print(f"RAW -> {RAW_PATH}")
    for row in results:
        print(f"{row['engine']}: {row['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
