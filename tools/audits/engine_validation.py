"""Run baseline validation across observable engines and write REPORT.md.

This is intentionally read-mostly tooling: it runs existing engine entrypoints,
collects the artifacts they already emit, and summarizes the current baseline
without changing sacred logic.
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
TODAY = datetime.now().strftime("%Y-%m-%d")
VALIDATION_DIR = ROOT / "data" / "validation" / TODAY
REPORT_PATH = VALIDATION_DIR / "REPORT.md"
RAW_PATH = VALIDATION_DIR / "engine_validation.json"


@dataclass(frozen=True)
class EngineSpec:
    name: str
    display: str
    mode: str
    script: str | None = None
    data_dir: str | None = None
    report_glob: str | None = None
    cli_args: tuple[str, ...] = ()
    interactive_input: str = ""
    notes: str = ""


ENGINE_SPECS = [
    EngineSpec(
        name="citadel",
        display="CITADEL",
        mode="cli",
        script="engines/citadel.py",
        data_dir="data/runs",
        notes="Backtest CLI supports --days/--basket/--leverage/--no-menu.",
    ),
    EngineSpec(
        name="newton",
        display="DE SHAW",
        mode="cli",
        script="engines/deshaw.py",
        data_dir="data/newton",
        report_glob="reports/newton_*_v1.json",
        cli_args=("--no-menu",),
        notes="CLI supports --days/--basket/--no-menu for deterministic diagnostic runs.",
    ),
    EngineSpec(
        name="mercurio",
        display="JUMP",
        mode="interactive",
        script="engines/jump.py",
        data_dir="data/mercurio",
        report_glob="reports/mercurio_*_v1.json",
        interactive_input="\n\n\n\n",
        notes="Interactive prompts accepted with default values.",
    ),
    EngineSpec(
        name="thoth",
        display="BRIDGEWATER",
        mode="cli",
        script="engines/bridgewater.py",
        data_dir="data/thoth",
        report_glob="reports/thoth_*_v1.json",
        cli_args=("--no-menu",),
        notes="CLI supports --days/--basket/--no-menu for deterministic diagnostic runs.",
    ),
    EngineSpec(
        name="harmonics",
        display="RENAISSANCE",
        mode="cli",
        script="engines/renaissance.py",
        data_dir="data/renaissance",
        report_glob="reports/renaissance_*_v1.json",
        notes="Standalone backtest wrapper around scan_hermes().",
    ),
    EngineSpec(
        name="prometeu",
        display="TWO SIGMA",
        mode="blocked",
        notes="Blocked: requires trade history from 2+ validated engines; standalone script is advisory only.",
    ),
    EngineSpec(
        name="arbitrage",
        display="JANE STREET",
        mode="cli",
        script="engines/janestreet.py",
        data_dir="data/arbitrage",
        report_glob="reports/simulate_historical.json",
        cli_args=("--simulate-historical", "--sim-capital", "1000"),
        notes="Snapshot-based scanner report; not a trade backtest.",
    ),
]


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    return env


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _equity_from_trades(account_size: float, trades: list[dict[str, Any]]) -> list[float]:
    eq = [account_size]
    cur = account_size
    for trade in trades:
        pnl = float(trade.get("pnl", 0.0) or 0.0)
        cur += pnl
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
    return round(max_dd * 100, 2)


def _latest_new_dir(parent: Path, before: set[str]) -> Path | None:
    if not parent.exists():
        return None
    after = {p.name for p in parent.iterdir() if p.is_dir()}
    created = sorted(after - before)
    if created:
        return max((parent / name for name in created), key=lambda p: p.stat().st_mtime)
    dirs = [p for p in parent.iterdir() if p.is_dir()]
    return max(dirs, key=lambda p: p.stat().st_mtime) if dirs else None


def _run_subprocess(args: list[str], *, input_text: str = "", timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=input_text,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
        env=_env(),
        timeout=timeout,
    )


def _failure_summary(stdout_tail: str, stderr_tail: str) -> str | None:
    haystack = f"{stdout_tail}\n{stderr_tail}"
    checks = [
        ("apenas 0 pares cointegrados", "No valid cointegrated pairs found for the current 90d/default universe."),
        ("sem trades fechados", "Run completed but produced no closed trades."),
        ("HTTP 202", "External OI/sentiment endpoints returned HTTP 202 responses during data collection."),
        ("Read timed out", "External sentiment fetch hit network read timeouts."),
        ("statsmodels nao instalado", "statsmodels is missing, so the engine cannot run cointegration."),
    ]
    for needle, summary in checks:
        if needle in haystack:
            return summary
    return None


def _parse_citadel(run_dir: Path) -> dict[str, Any]:
    summary = _load_json(run_dir / "summary.json")
    return {
        "run_dir": str(run_dir.relative_to(ROOT)),
        "n_trades": int(summary.get("n_trades", 0)),
        "win_rate": float(summary.get("win_rate", 0.0)),
        "pnl": float(summary.get("total_pnl", summary.get("pnl", 0.0))),
        "sortino": summary.get("sortino"),
        "sharpe": summary.get("sharpe"),
        "max_dd_pct": float(summary.get("max_dd_pct", summary.get("max_dd", 0.0) or 0.0)),
        "final_equity": float(summary.get("final_equity", 0.0)),
        "html_report": (run_dir / "report.html").exists(),
    }


def _parse_generic_report(report_path: Path) -> dict[str, Any]:
    data = _load_json(report_path)
    account_size = float(data.get("account_size", 10000.0))
    trades = list(data.get("trades", []))
    equity = _equity_from_trades(account_size, trades)
    max_dd_pct = float(data.get("max_dd_pct", _max_dd_pct(equity)))
    final_equity = float(data.get("final_equity", equity[-1] if equity else account_size))
    return {
        "kind": "backtest",
        "report_path": str(report_path.relative_to(ROOT)),
        "n_trades": int(data.get("n_trades", len(trades))),
        "win_rate": float(data.get("win_rate", 0.0)),
        "pnl": round(final_equity - account_size, 2),
        "sortino": data.get("sortino"),
        "sharpe": data.get("sharpe"),
        "max_dd_pct": max_dd_pct,
        "final_equity": final_equity,
    }


def _parse_scanner_report(report_path: Path) -> dict[str, Any]:
    data = _load_json(report_path)
    return {
        "kind": "scanner",
        "report_path": str(report_path.relative_to(ROOT)),
        "total_opportunities": int(data.get("total_opportunities", 0)),
        "profitable_count": int(data.get("profitable_count", 0)),
        "avg_apr": float(data.get("avg_apr", 0.0)),
        "estimated_monthly_income": float(data.get("estimated_monthly_income", 0.0)),
        "best_venue": data.get("best_venue"),
        "worst_venue": data.get("worst_venue"),
    }


def run_engine(spec: EngineSpec, days: int, basket: str, leverage: float) -> dict[str, Any]:
    result: dict[str, Any] = {
        "engine": spec.display,
        "status": "skipped",
        "notes": spec.notes,
    }
    if spec.mode == "unsupported":
        result["status"] = "unsupported"
        return result
    if spec.mode == "blocked":
        result["status"] = "blocked"
        return result

    assert spec.script is not None
    assert spec.data_dir is not None
    parent = ROOT / spec.data_dir
    before = {p.name for p in parent.iterdir() if p.is_dir()} if parent.exists() else set()

    if spec.mode == "cli":
        cmd = [str(PYTHON), spec.script]
        if spec.name == "citadel":
            cmd.extend(["--days", str(days), "--basket", basket, "--leverage", str(leverage), "--no-menu"])
        elif spec.name == "harmonics":
            cmd.extend(["--days", str(days), "--basket", basket])
        elif spec.name in {"newton", "thoth"}:
            cmd.extend(["--days", str(days), "--basket", basket, *spec.cli_args])
        else:
            cmd.extend(spec.cli_args)
        proc = _run_subprocess(cmd, timeout=5400)
    else:
        proc = _run_subprocess(
            [str(PYTHON), spec.script],
            input_text=spec.interactive_input,
            timeout=5400,
        )

    result["returncode"] = proc.returncode
    result["stdout_tail"] = proc.stdout[-4000:]
    result["stderr_tail"] = proc.stderr[-2000:]
    if proc.returncode != 0:
        result["status"] = "failed"
        result["failure_summary"] = _failure_summary(result["stdout_tail"], result["stderr_tail"])
        return result

    run_dir = _latest_new_dir(parent, before)
    if run_dir is None:
        result["status"] = "failed"
        result["notes"] = f"{spec.notes} No run directory detected under {spec.data_dir}."
        return result

    if spec.name == "citadel":
        parsed = _parse_citadel(run_dir)
        parsed["kind"] = "backtest"
    else:
        assert spec.report_glob is not None
        reports = sorted(run_dir.glob(spec.report_glob))
        if not reports:
            result["status"] = "failed"
            result["notes"] = f"{spec.notes} No report matched {spec.report_glob} in {run_dir}."
            return result
        parsed = _parse_scanner_report(reports[-1]) if spec.name == "arbitrage" else _parse_generic_report(reports[-1])

    result.update(parsed)
    result["status"] = "ok"
    return result


def _fmt_float(value: Any, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{digits}f}"


def _fmt_pct(value: Any, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{digits}f}%"


def build_report(results: list[dict[str, Any]], days: int, basket: str, leverage: float) -> str:
    generated_at = datetime.now().isoformat(timespec="seconds")
    lines = [
        "# Engine Validation Report",
        "",
        f"- Generated at: `{generated_at}`",
        f"- Days: `{days}`",
        f"- Basket: `{basket}`",
        f"- Leverage: `{leverage}x`",
        f"- Python: `{PYTHON}`",
        "",
        "## Current Risk/Sizing Context",
        "",
        "- `_wr()` is continuous/linear in `core/portfolio.py`.",
        "- `position_size()` is the simplified 3-factor version in `core/portfolio.py`.",
        "",
        "## Results",
        "",
    ]

    for res in results:
        lines.append(f"### {res['engine']}")
        if res["status"] != "ok":
            lines.append(f"- Status: `{res['status']}`")
            if res.get("notes"):
                lines.append(f"- Notes: {res['notes']}")
            if res.get("failure_summary"):
                lines.append(f"- Failure summary: {res['failure_summary']}")
            if res.get("returncode") is not None:
                lines.append(f"- Return code: `{res['returncode']}`")
            lines.append("")
            continue

        lines.append("- Status: `ok`")
        if res.get("kind") == "scanner":
            lines.extend([
                f"- Total opportunities: `{res['total_opportunities']}`",
                f"- Profitable count: `{res['profitable_count']}`",
                f"- Average APR: `{_fmt_pct(res.get('avg_apr'), 2)}`",
                f"- Estimated monthly income on $1000: `${_fmt_float(res.get('estimated_monthly_income'))}`",
                f"- Best venue: `{res.get('best_venue')}`",
                f"- Worst venue: `{res.get('worst_venue')}`",
                f"- Artifact: `{res['report_path']}`",
            ])
        else:
            lines.extend([
                f"- Trades: `{res['n_trades']}`",
                f"- WR: `{_fmt_pct(res['win_rate'])}`",
                f"- PnL: `${_fmt_float(res['pnl'])}`",
                f"- Sharpe: `{_fmt_float(res.get('sharpe'), 3)}`",
                f"- Sortino: `{_fmt_float(res.get('sortino'), 3)}`",
                f"- MaxDD: `{_fmt_pct(res.get('max_dd_pct'))}`",
                f"- Final equity: `${_fmt_float(res.get('final_equity'))}`",
            ])
            if res["engine"] == "CITADEL":
                lines.append(f"- HTML report present: `{'yes' if res.get('html_report') else 'no'}`")
                lines.append(f"- Run dir: `{res['run_dir']}`")
            else:
                lines.append(f"- Artifact: `{res['report_path']}`")
        if res.get("notes"):
            lines.append(f"- Notes: {res['notes']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run baseline engine validation and write REPORT.md")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--basket", default="default")
    parser.add_argument("--leverage", type=float, default=1.0)
    args = parser.parse_args()

    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)

    results = [run_engine(spec, args.days, args.basket, args.leverage) for spec in ENGINE_SPECS]
    REPORT_PATH.write_text(build_report(results, args.days, args.basket, args.leverage), encoding="utf-8")
    RAW_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"REPORT -> {REPORT_PATH}")
    print(f"RAW -> {RAW_PATH}")
    for res in results:
        print(f"{res['engine']}: {res['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
