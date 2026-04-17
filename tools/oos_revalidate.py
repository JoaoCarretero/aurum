"""
OOS revalidation gate for the 2026-04-16 pre-calibration audit.

This tool automates the Bloco 0 checkpoint:
1. Re-run the 7 audited engines on fixed OOS windows.
2. Compare BEAR reruns with the persisted 2026-04-16 baseline.
3. Persist raw rerun payloads under data/audit/.
4. Record static checks for cost symmetry, look-ahead patterns, and method risks.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "docs" / "audits" / "2026-04-17_oos_revalidation.md"
DEFAULT_PYTHON = Path(r"C:\Users\Joao\AppData\Local\Python\bin\python.exe")
TOLERANCE_PCT = 0.1

SUMMARY_FIELDS = (
    "n_trades",
    "win_rate",
    "pnl",
    "roi",
    "roi_pct",
    "sharpe",
    "sortino",
    "max_dd",
    "max_dd_pct",
    "final_equity",
    "period_days",
    "n_symbols",
    "n_candles",
    "interval",
    "basket",
)

LOOKAHEAD_PATTERNS = (
    r"\.shift\(-\d+",
    r"iloc\[\s*i\s*\+",
    r"\bfuture_",
    r"\bahead_",
    r"\bpeek_",
)


@dataclass(frozen=True)
class Window:
    key: str
    label: str
    start: str
    end: str
    days: int
    regime: str


@dataclass(frozen=True)
class EngineSpec:
    key: str
    display: str
    script: str
    run_root: str
    basket: str
    baseline_runs: dict[str, str]
    cost_paths: tuple[str, ...] = ()


WINDOWS: dict[str, Window] = {
    "bear_2022": Window(
        key="bear_2022",
        label="2022-01-01 -> 2023-01-01",
        start="2022-01-01",
        end="2023-01-01",
        days=360,
        regime="BEAR",
    ),
    "bull_2020": Window(
        key="bull_2020",
        label="2020-07-01 -> 2021-07-01",
        start="2020-07-01",
        end="2021-07-01",
        days=360,
        regime="BULL",
    ),
    "chop_2019": Window(
        key="chop_2019",
        label="2019-06-01 -> 2020-03-01",
        start="2019-06-01",
        end="2020-03-01",
        days=360,
        regime="CHOP",
    ),
}


ENGINES: dict[str, EngineSpec] = {
    "citadel": EngineSpec(
        key="citadel",
        display="CITADEL",
        script="engines/citadel.py",
        run_root="data/runs",
        basket="default",
        baseline_runs={
            "bear_2022": "data/runs/citadel_2026-04-16_232542",
        },
        cost_paths=("engines/citadel.py",),
    ),
    "renaissance": EngineSpec(
        key="renaissance",
        display="RENAISSANCE",
        script="engines/renaissance.py",
        run_root="data/renaissance",
        basket="bluechip",
        baseline_runs={"bear_2022": "data/renaissance/2026-04-16_232914"},
        cost_paths=("core/harmonics.py", "engines/renaissance.py"),
    ),
    "jump": EngineSpec(
        key="jump",
        display="JUMP",
        script="engines/jump.py",
        run_root="data/jump",
        basket="bluechip",
        baseline_runs={"bear_2022": "data/jump/2026-04-16_232916"},
        cost_paths=("engines/jump.py",),
    ),
    "deshaw": EngineSpec(
        key="deshaw",
        display="DE SHAW",
        script="engines/deshaw.py",
        run_root="data/deshaw",
        basket="bluechip",
        baseline_runs={"bear_2022": "data/deshaw/2026-04-16_232917"},
        cost_paths=("engines/deshaw.py",),
    ),
    "bridgewater": EngineSpec(
        key="bridgewater",
        display="BRIDGEWATER",
        script="engines/bridgewater.py",
        run_root="data/bridgewater",
        basket="bluechip",
        baseline_runs={"bear_2022": "data/bridgewater/2026-04-16_232919"},
        cost_paths=("engines/bridgewater.py",),
    ),
    "kepos": EngineSpec(
        key="kepos",
        display="KEPOS",
        script="engines/kepos.py",
        run_root="data/kepos",
        basket="bluechip",
        baseline_runs={"bear_2022": "data/kepos/kepos_2026-04-16_2338"},
        cost_paths=("engines/kepos.py",),
    ),
    "medallion": EngineSpec(
        key="medallion",
        display="MEDALLION",
        script="engines/medallion.py",
        run_root="data/medallion",
        basket="bluechip",
        baseline_runs={"bear_2022": "data/medallion/medallion_2026-04-16_2338"},
        cost_paths=("engines/medallion.py",),
    ),
}


def _rel(path: str | Path) -> Path:
    return ROOT / Path(path)


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _normalize_summary(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"missing summary.json in {run_dir}")

    raw = _load_json(summary_path)
    nested = isinstance(raw, dict) and isinstance(raw.get("summary"), dict) and "engine" in raw
    summary = dict(raw.get("summary", {})) if nested else dict(raw)

    if nested:
        meta = raw.get("meta", {}) or {}
        params = raw.get("params", {}) or {}
        summary.setdefault("period_days", meta.get("scan_days"))
        summary.setdefault("interval", params.get("interval"))
        summary.setdefault("basket", meta.get("basket"))
        summary.setdefault("engine", raw.get("engine"))
        summary.setdefault("run_id", raw.get("run_id"))

    return {field: summary.get(field) for field in SUMMARY_FIELDS}


def _fmt_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _metric_match(expected: Any, actual: Any, tolerance_pct: float) -> tuple[bool, str]:
    if expected is None and actual is None:
        return True, "both null"
    if type(expected) is str or type(actual) is str:
        ok = expected == actual
        return ok, "exact" if ok else "changed"
    if expected is None or actual is None:
        return False, "null mismatch"
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if expected == actual:
            return True, "exact"
        if math.isclose(float(expected), 0.0, abs_tol=1e-12):
            ok = math.isclose(float(actual), 0.0, abs_tol=1e-9)
            return ok, "zero-baseline"
        rel = abs((float(actual) - float(expected)) / float(expected)) * 100.0
        return rel <= tolerance_pct, f"{rel:.3f}%"
    return expected == actual, "exact" if expected == actual else "changed"


def _compare_summaries(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    failures = 0
    for field in SUMMARY_FIELDS:
        exp = expected.get(field)
        got = actual.get(field)
        ok, detail = _metric_match(exp, got, TOLERANCE_PCT)
        if not ok:
            failures += 1
        fields.append(
            {
                "field": field,
                "baseline": exp,
                "fresh": got,
                "ok": ok,
                "detail": detail,
            }
        )
    return {"ok": failures == 0, "failures": failures, "fields": fields}


def _scan_cost_model(paths: list[Path]) -> dict[str, Any]:
    required = ("SLIPPAGE", "SPREAD", "COMMISSION", "FUNDING_PER_8H")
    found = {token: False for token in required}
    suspicious: list[str] = []
    scanned: list[str] = []
    for path in paths:
        scanned.append(str(path.relative_to(ROOT)))
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        for token in required:
            found[token] = found[token] or any(token in line for line in lines)
        for idx, line in enumerate(lines):
            if "backtest" in line.lower() and "skip" in line.lower():
                suspicious.append(f"{path.relative_to(ROOT)}:{idx + 1}")
    return {
        "all_present": all(found.values()),
        "found": found,
        "suspicious_lines": suspicious,
        "scanned": scanned,
    }


def _scan_lookahead(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    hits: list[dict[str, Any]] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        for pattern in LOOKAHEAD_PATTERNS:
            if re.search(pattern, line):
                hits.append({"line": idx, "pattern": pattern, "snippet": line.strip()[:160]})
    return hits


def _scan_method_risks(spec: EngineSpec) -> list[str]:
    notes: list[str] = []
    script_text = _rel(spec.script).read_text(encoding="utf-8", errors="replace")
    if "fetch_funding_rate" in script_text or "fetch_open_interest" in script_text or "fetch_long_short_ratio" in script_text:
        sentiment_text = _rel("core/sentiment.py").read_text(encoding="utf-8", errors="replace")
        # Post-2026-04-17: the sentiment helpers accept ``end_time_ms`` so live
        # calls can be bounded by a historical cutoff. Flag engines whose
        # sentiment source is still missing that parameter, not engines whose
        # call sites simply don't pass it.
        for fn in ("fetch_funding_rate", "fetch_open_interest", "fetch_long_short_ratio"):
            marker = f"def {fn}("
            if marker not in sentiment_text:
                continue
            signature = sentiment_text.split(marker, 1)[1].split(":", 1)[0]
            if "end_time_ms" not in signature:
                notes.append(
                    "LIVE_SENTIMENT_UNBOUNDED: "
                    f"{fn} has no historical end/start parameter."
                )
    return notes


def _list_dirs(root: Path) -> set[Path]:
    if not root.exists():
        return set()
    return {p.resolve() for p in root.iterdir() if p.is_dir()}


def _find_new_run(before: set[Path], after: set[Path]) -> Path | None:
    new_dirs = sorted(after - before, key=lambda p: p.stat().st_mtime, reverse=True)
    if new_dirs:
        return new_dirs[0]
    return None


def _run_engine(spec: EngineSpec, window: Window, python_bin: Path) -> dict[str, Any]:
    script_path = _rel(spec.script)
    run_root = _rel(spec.run_root)
    before = _list_dirs(run_root)
    cmd = [
        str(python_bin),
        str(script_path),
        "--days",
        str(window.days),
        "--end",
        window.end,
        "--basket",
        spec.basket,
        "--no-menu",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    after = _list_dirs(run_root)
    run_dir = _find_new_run(before, after)
    summary = _normalize_summary(run_dir) if proc.returncode == 0 and run_dir else None
    return {
        "engine": spec.key,
        "window": window.key,
        "window_label": window.label,
        "regime": window.regime,
        "command": cmd,
        "returncode": proc.returncode,
        "status": "OK" if proc.returncode == 0 and summary else "FAILED",
        "stdout_tail": "\n".join(proc.stdout.splitlines()[-20:]),
        "stderr_tail": "\n".join(proc.stderr.splitlines()[-20:]),
        "run_dir": str(run_dir.relative_to(ROOT)) if run_dir else None,
        "summary": summary,
    }


def _verdict_from_windows(rows: list[dict[str, Any]]) -> str:
    if rows:
        max_roi = max(abs(r.get("roi_pct") or 0.0) for r in rows)
        max_sharpe = max(abs(r.get("sharpe") or 0.0) for r in rows)
        max_trades = max(r.get("n_trades") or 0 for r in rows)
        if max_roi >= 200 or max_sharpe >= 8 or max_trades >= 5000:
            return "BUG_SUSPECT"
    significant = [r for r in rows if (r.get("n_trades") or 0) >= 50]
    positives = [r for r in significant if (r.get("sharpe") or 0) > 0]
    if len(positives) >= 2:
        return "EDGE_REAL"
    if len(positives) == 1:
        return "EDGE_DE_REGIME"
    if significant:
        return "NO_EDGE_OU_OVERFIT"
    return "INSUFFICIENT_SAMPLE"


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(out)


def _results_path(selected_windows: list[Window]) -> Path:
    audit_dir = ROOT / "data" / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    if len(selected_windows) == 1:
        return audit_dir / f"oos_revalidate_{selected_windows[0].key}.json"
    return audit_dir / "oos_revalidate.json"


def _persist_results(
    selected_windows: list[Window],
    selected_engines: list[EngineSpec],
    reruns: dict[str, dict[str, dict[str, Any]]],
) -> Path:
    payload = []
    for window in selected_windows:
        for spec in selected_engines:
            result = reruns.get(spec.key, {}).get(window.key)
            if result:
                payload.append(result)
    out_path = _results_path(selected_windows)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def build_markdown(
    run_at: datetime,
    engines: list[EngineSpec],
    windows: list[Window],
    baselines: dict[str, dict[str, dict[str, Any]]],
    reruns: dict[str, dict[str, dict[str, Any]]],
    cost_scans: dict[str, dict[str, Any]],
    lookahead: dict[str, list[dict[str, Any]]],
    method_risks: dict[str, list[str]],
) -> str:
    lines: list[str] = []
    lines.append("# OOS Revalidation Gate — 2026-04-17")
    lines.append("")
    lines.append(f"Generated: `{run_at.isoformat(timespec='seconds')}`")
    lines.append("")
    lines.append("Baseline source: persisted runs cited in `docs/audits/2026-04-16_oos_verdict.md`.")
    lines.append("")
    repro_rows: list[list[Any]] = []
    multi_rows: list[list[Any]] = []

    for spec in engines:
        engine_key = spec.key
        for window in windows:
            baseline = baselines.get(engine_key, {}).get(window.key)
            fresh = reruns.get(engine_key, {}).get(window.key)
            if not baseline:
                repro_rows.append([spec.display, window.regime, "no-baseline", "—", "—", "—"])
                continue
            if not fresh:
                repro_rows.append([spec.display, window.regime, "not-run", "—", "—", "—"])
                continue
            cmp = fresh.get("comparison")
            repro_rows.append(
                [
                    spec.display,
                    window.regime,
                    "PASS" if cmp and cmp["ok"] else "FAIL",
                    baseline.get("sharpe", "—"),
                    fresh["summary"].get("sharpe", "—") if fresh.get("summary") else "—",
                    cmp["failures"] if cmp else "—",
                ]
            )
        verdict_rows: list[dict[str, Any]] = []
        for window in windows:
            summary = reruns.get(engine_key, {}).get(window.key, {}).get("summary") or baselines.get(engine_key, {}).get(window.key)
            if not summary:
                continue
            verdict_rows.append({"window": window.key, "sharpe": summary.get("sharpe"), "n_trades": summary.get("n_trades"), "roi_pct": summary.get("roi_pct")})
            multi_rows.append(
                [
                    spec.display,
                    window.regime,
                    _fmt_value(summary.get("sharpe")),
                    _fmt_value(summary.get("sortino")),
                    _fmt_value(summary.get("roi_pct")),
                    _fmt_value(summary.get("n_trades")),
                ]
            )
        final_verdict = _verdict_from_windows(verdict_rows)
        if method_risks.get(engine_key):
            if any("LIVE_SENTIMENT_UNBOUNDED" in note for note in method_risks[engine_key]):
                final_verdict = "INVALID_OOS_LIVE_SENTIMENT"
        reruns.setdefault(engine_key, {})["_verdict"] = {"final": final_verdict}

    lines.append("## Reproducibility")
    lines.append("")
    lines.append(_markdown_table(["Engine", "Regime", "Match", "Sharpe baseline", "Sharpe fresh", "Field fails"], repro_rows))
    lines.append("")

    lines.append("## Cost Symmetry")
    lines.append("")
    cost_rows = []
    for spec in engines:
        scan = cost_scans[spec.key]
        cost_rows.append(
            [
                spec.display,
                "yes" if scan["all_present"] else "no",
                ", ".join(k for k, v in scan["found"].items() if v),
                ", ".join(scan["scanned"]),
                ", ".join(str(x) for x in scan["suspicious_lines"]) if scan["suspicious_lines"] else "—",
            ]
        )
    lines.append(_markdown_table(["Engine", "All cost tokens present", "Found", "Scanned files", "Suspicious lines"], cost_rows))
    lines.append("")

    lines.append("## Multi-Window Summary")
    lines.append("")
    lines.append(_markdown_table(["Engine", "Regime", "Sharpe", "Sortino", "ROI%", "Trades"], multi_rows))
    lines.append("")

    lines.append("## Look-Ahead Scan")
    lines.append("")
    for spec in engines:
        hits = lookahead[spec.key]
        lines.append(f"### {spec.display}")
        if not hits:
            lines.append("- No direct match for `.shift(-N)`, `iloc[i+...]`, `future_`, `ahead_`, or `peek_`.")
        else:
            for hit in hits[:20]:
                lines.append(f"- Line {hit['line']}: `{hit['pattern']}` -> `{hit['snippet']}`")
        lines.append("")

    lines.append("## Methodology Risks")
    lines.append("")
    for spec in engines:
        lines.append(f"### {spec.display}")
        notes = method_risks.get(spec.key, [])
        if not notes:
            lines.append("- No additional engine-specific methodology risk detected by static scan.")
        else:
            for note in notes:
                lines.append(f"- {note}")
        lines.append("")

    lines.append("## Final Revised Verdict")
    lines.append("")
    verdict_rows = []
    for spec in engines:
        verdict_rows.append([spec.display, reruns.get(spec.key, {}).get("_verdict", {}).get("final", "—")])
    lines.append(_markdown_table(["Engine", "Verdict"], verdict_rows))
    lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append("- Reproducibility tolerance: `±0.1%` on normalized summary fields.")
    lines.append("- `KEPOS` and `MEDALLION` use nested payloads in `summary.json`; the tool unwraps `summary` and enriches `period_days`, `interval`, and `basket` from `meta`/`params`.")
    lines.append("- Missing baseline windows stay available for future expansion.")
    lines.append("")

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Revalidate the 2026-04-16 OOS verdict against persisted runs.")
    ap.add_argument("--python-bin", default=str(DEFAULT_PYTHON), help="Python interpreter that has repo dependencies installed.")
    ap.add_argument("--engines", nargs="*", default=list(ENGINES.keys()), choices=list(ENGINES.keys()))
    ap.add_argument("--windows", nargs="*", default=["bear_2022", "bull_2020", "chop_2019"], choices=list(WINDOWS.keys()))
    ap.add_argument("--skip-runs", action="store_true", help="Do not rerun engines; only read baselines and static scans.")
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    python_bin = Path(args.python_bin)
    if not python_bin.exists():
        print(f"Python interpreter not found: {python_bin}", file=sys.stderr)
        return 2

    selected_engines = [ENGINES[key] for key in args.engines]
    selected_windows = [WINDOWS[key] for key in args.windows]

    baselines: dict[str, dict[str, dict[str, Any]]] = {}
    reruns: dict[str, dict[str, dict[str, Any]]] = {}
    cost_scans: dict[str, dict[str, Any]] = {}
    lookahead: dict[str, list[dict[str, Any]]] = {}
    method_risks: dict[str, list[str]] = {}

    for spec in selected_engines:
        baselines[spec.key] = {}
        reruns[spec.key] = {}
        script_path = _rel(spec.script)
        cost_scans[spec.key] = _scan_cost_model([_rel(path) for path in spec.cost_paths or (spec.script,)])
        lookahead[spec.key] = _scan_lookahead(script_path)
        method_risks[spec.key] = _scan_method_risks(spec)

        for window in selected_windows:
            baseline_run = spec.baseline_runs.get(window.key)
            if baseline_run:
                baselines[spec.key][window.key] = _normalize_summary(_rel(baseline_run))
            if args.skip_runs:
                continue
            print(f">>> {spec.key:12s} window={window.key:10s} end={window.end}", flush=True)
            fresh = _run_engine(spec, window, python_bin)
            if fresh.get("summary") and baselines[spec.key].get(window.key):
                fresh["comparison"] = _compare_summaries(baselines[spec.key][window.key], fresh["summary"])
            reruns[spec.key][window.key] = fresh
            print(
                f"    status={fresh['status']:6s} returncode={fresh['returncode']} run_dir={fresh.get('run_dir') or '—'}",
                flush=True,
            )

    results_path = _persist_results(selected_windows, selected_engines, reruns)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        build_markdown(datetime.now(), selected_engines, selected_windows, baselines, reruns, cost_scans, lookahead, method_risks),
        encoding="utf-8",
    )
    print(f"Wrote {output}")
    print(f"Wrote {results_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
