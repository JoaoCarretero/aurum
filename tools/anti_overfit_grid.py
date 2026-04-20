from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np

from analysis.dsr import deflated_sharpe_ratio


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class WindowSpec:
    name: str
    days: int
    end: str


@dataclass(frozen=True)
class EngineSpec:
    key: str
    display: str
    script: str
    data_dir: str
    checklist_path: str
    basket: str
    interval: str
    train_days: int
    train_end: str
    test_end: str
    holdout_end: str
    variants: dict[str, dict[str, Any]]


ENGINE_SPECS: dict[str, EngineSpec] = {
    "deshaw": EngineSpec(
        key="deshaw",
        display="DE SHAW",
        script="engines/deshaw.py",
        data_dir="data/deshaw",
        checklist_path="docs/engines/deshaw/checklist.md",
        basket="bluechip",
        interval="1h",
        train_days=1095,
        train_end="2024-01-01",
        test_end="2025-01-01",
        holdout_end="2026-04-20",
        variants={
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
        },
    ),
    "kepos": EngineSpec(
        key="kepos",
        display="KEPOS",
        script="engines/kepos.py",
        data_dir="data/kepos",
        checklist_path="docs/engines/kepos/checklist.md",
        basket="bluechip",
        interval="15m",
        train_days=1095,
        train_end="2024-01-01",
        test_end="2025-01-01",
        holdout_end="2026-04-20",
        variants={
            "KEP00_baseline": {
                "rsi_exhaustion": 8.0,
                "cooldown_bars": 6,
                "hmm_min_prob_chop": 0.35,
                "hmm_max_trend_prob": 0.60,
                "tp_atr": 1.8,
            },
            "KEP01_rsi_looser": {
                "rsi_exhaustion": 6.0,
                "cooldown_bars": 6,
                "hmm_min_prob_chop": 0.35,
                "hmm_max_trend_prob": 0.60,
                "tp_atr": 1.8,
            },
            "KEP02_rsi_tighter": {
                "rsi_exhaustion": 10.0,
                "cooldown_bars": 6,
                "hmm_min_prob_chop": 0.35,
                "hmm_max_trend_prob": 0.60,
                "tp_atr": 1.8,
            },
            "KEP03_cooldown_short": {
                "rsi_exhaustion": 8.0,
                "cooldown_bars": 3,
                "hmm_min_prob_chop": 0.35,
                "hmm_max_trend_prob": 0.60,
                "tp_atr": 1.8,
            },
            "KEP04_cooldown_long": {
                "rsi_exhaustion": 8.0,
                "cooldown_bars": 9,
                "hmm_min_prob_chop": 0.35,
                "hmm_max_trend_prob": 0.60,
                "tp_atr": 1.8,
            },
            "KEP05_hmm_looser": {
                "rsi_exhaustion": 8.0,
                "cooldown_bars": 6,
                "hmm_min_prob_chop": 0.30,
                "hmm_max_trend_prob": 0.65,
                "tp_atr": 1.8,
            },
            "KEP06_hmm_tighter": {
                "rsi_exhaustion": 8.0,
                "cooldown_bars": 6,
                "hmm_min_prob_chop": 0.40,
                "hmm_max_trend_prob": 0.55,
                "tp_atr": 1.8,
            },
            "KEP07_takeprofit_longer": {
                "rsi_exhaustion": 8.0,
                "cooldown_bars": 6,
                "hmm_min_prob_chop": 0.35,
                "hmm_max_trend_prob": 0.60,
                "tp_atr": 2.4,
            },
        },
    ),
    "medallion": EngineSpec(
        key="medallion",
        display="MEDALLION",
        script="engines/medallion.py",
        data_dir="data/medallion",
        checklist_path="docs/engines/medallion/checklist.md",
        basket="bluechip",
        interval="15m",
        train_days=1095,
        train_end="2024-01-01",
        test_end="2025-01-01",
        holdout_end="2026-04-20",
        variants={
            "MED00_baseline": {
                "z_entry": 1.2,
                "ensemble_threshold": 0.45,
                "min_components": 4,
                "kelly_fraction": 0.25,
                "hmm_exit_trend_prob": 0.75,
            },
            "MED01_entry_tighter": {
                "z_entry": 1.4,
                "ensemble_threshold": 0.45,
                "min_components": 4,
                "kelly_fraction": 0.25,
                "hmm_exit_trend_prob": 0.75,
            },
            "MED02_entry_looser": {
                "z_entry": 1.0,
                "ensemble_threshold": 0.45,
                "min_components": 4,
                "kelly_fraction": 0.25,
                "hmm_exit_trend_prob": 0.75,
            },
            "MED03_threshold_tighter": {
                "z_entry": 1.2,
                "ensemble_threshold": 0.55,
                "min_components": 4,
                "kelly_fraction": 0.25,
                "hmm_exit_trend_prob": 0.75,
            },
            "MED04_threshold_looser": {
                "z_entry": 1.2,
                "ensemble_threshold": 0.35,
                "min_components": 4,
                "kelly_fraction": 0.25,
                "hmm_exit_trend_prob": 0.75,
            },
            "MED05_components_tighter": {
                "z_entry": 1.2,
                "ensemble_threshold": 0.45,
                "min_components": 5,
                "kelly_fraction": 0.25,
                "hmm_exit_trend_prob": 0.75,
            },
            "MED06_kelly_lower": {
                "z_entry": 1.2,
                "ensemble_threshold": 0.45,
                "min_components": 4,
                "kelly_fraction": 0.15,
                "hmm_exit_trend_prob": 0.75,
            },
            "MED07_hmm_exit_earlier": {
                "z_entry": 1.2,
                "ensemble_threshold": 0.45,
                "min_components": 4,
                "kelly_fraction": 0.25,
                "hmm_exit_trend_prob": 0.65,
            },
        },
    ),
}


FLAG_MAP = {
    "deshaw": {
        "allowed_macro_entry": "--allowed-macro-entry",
        "min_hmm_chop_prob": "--min-hmm-chop-prob",
        "max_hmm_trend_prob": "--max-hmm-trend-prob",
        "max_revalidation_misses": "--max-revalidation-misses",
    },
    "kepos": {
        "rsi_exhaustion": "--rsi-exhaustion",
        "cooldown_bars": "--cooldown-bars",
        "hmm_min_prob_chop": "--hmm-min-prob-chop",
        "hmm_max_trend_prob": "--hmm-max-trend-prob",
        "tp_atr": "--tp-atr",
    },
    "medallion": {
        "z_entry": "--z-entry",
        "ensemble_threshold": "--ensemble-threshold",
        "min_components": "--min-components",
        "kelly_fraction": "--kelly-fraction",
        "hmm_exit_trend_prob": "--hmm-exit-trend-prob",
    },
}


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run pre-registered anti-overfit grids.")
    ap.add_argument("engine", choices=sorted(ENGINE_SPECS))
    ap.add_argument("--phase", choices=["all", "train", "test", "holdout"], default="all")
    ap.add_argument("--python", default=sys.executable, help="Python interpreter used to run the engine CLIs")
    ap.add_argument("--out", default=None, help="Optional output root")
    ap.add_argument("--limit", type=int, default=None, help="Run only the first N variants from the locked grid")
    return ap.parse_args()


def build_windows(spec: EngineSpec, phase: str = "all") -> list[WindowSpec]:
    train_end = date.fromisoformat(spec.train_end)
    test_end = date.fromisoformat(spec.test_end)
    holdout_end = date.fromisoformat(spec.holdout_end)
    windows = {
        "train": WindowSpec("train", spec.train_days, spec.train_end),
        "test": WindowSpec("test", (test_end - train_end).days, spec.test_end),
        "holdout": WindowSpec("holdout", (holdout_end - test_end).days, spec.holdout_end),
    }
    if phase == "all":
        return [windows["train"], windows["test"], windows["holdout"]]
    return [windows[phase]]


def build_command(spec: EngineSpec, python_exe: str, window: WindowSpec, overrides: dict[str, Any]) -> list[str]:
    cmd = [
        python_exe,
        str(ROOT / spec.script),
        "--no-menu",
        "--days",
        str(window.days),
        "--basket",
        spec.basket,
        "--interval",
        spec.interval,
        "--end",
        window.end,
    ]
    for key, value in overrides.items():
        flag = FLAG_MAP[spec.key][key]
        if isinstance(value, bool):
            if value:
                cmd.append(flag)
            continue
        cmd.extend([flag, str(value)])
    return cmd


def _snapshot_dirs(parent: Path) -> set[Path]:
    if not parent.exists():
        return set()
    return {p for p in parent.iterdir() if p.is_dir()}


def _find_new_run_dir(parent: Path, before: set[Path], started_at: float) -> Path | None:
    if not parent.exists():
        return None
    candidates = [
        p for p in parent.iterdir()
        if p.is_dir() and (p not in before or p.stat().st_mtime >= started_at - 5)
    ]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for cand in candidates:
        if (cand / "summary.json").exists():
            return cand
    return None


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _extract_summary(path: Path) -> dict[str, Any]:
    data = _load_json(path, {}) or {}
    return data.get("summary", data)


def _pnl_series(trades: list[dict[str, Any]]) -> list[float]:
    vals: list[float] = []
    for trade in trades:
        pnl = trade.get("pnl")
        if pnl is None:
            continue
        try:
            vals.append(float(pnl))
        except (TypeError, ValueError):
            continue
    return vals


def _sample_skew_kurtosis(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    if arr.size < 2:
        return 0.0, 3.0
    mean = float(arr.mean())
    centered = arr - mean
    m2 = float(np.mean(centered ** 2))
    if m2 <= 0:
        return 0.0, 3.0
    m3 = float(np.mean(centered ** 3))
    m4 = float(np.mean(centered ** 4))
    skew = m3 / (m2 ** 1.5)
    kurtosis = m4 / (m2 ** 2)
    return skew, kurtosis


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _stage_metrics(run_dir: Path, n_trials: int) -> dict[str, Any]:
    summary = _extract_summary(run_dir / "summary.json")
    trades = _load_json(run_dir / "trades.json", []) or []
    pnls = _pnl_series(trades)
    skew, kurtosis = _sample_skew_kurtosis(pnls)
    sharpe = _safe_float(summary.get("sharpe"))
    dsr = None
    if len(pnls) >= 2:
        dsr = deflated_sharpe_ratio(
            sharpe=sharpe,
            n_trials=max(1, n_trials),
            skew=skew,
            kurtosis=kurtosis,
            n_obs=len(pnls),
        )
    return {
        "run_dir": str(run_dir.relative_to(ROOT)),
        "n_trades": int(_safe_float(summary.get("n_trades", summary.get("total_trades", 0)))),
        "win_rate": _safe_float(summary.get("win_rate")),
        "pnl": _safe_float(summary.get("pnl", summary.get("total_pnl", 0.0))),
        "roi_pct": _safe_float(summary.get("roi_pct", summary.get("roi", 0.0))),
        "sharpe": sharpe,
        "sortino": _safe_float(summary.get("sortino")),
        "max_dd_pct": _safe_float(summary.get("max_dd_pct", summary.get("max_dd", 0.0))),
        "skew": skew,
        "kurtosis": kurtosis,
        "dsr": dsr,
    }


def execute_run(spec: EngineSpec, variant: str, overrides: dict[str, Any], window: WindowSpec, python_exe: str, out_root: Path) -> dict[str, Any]:
    engine_dir = ROOT / spec.data_dir
    engine_dir.mkdir(parents=True, exist_ok=True)
    before = _snapshot_dirs(engine_dir)
    cmd = build_command(spec, python_exe, window, overrides)
    started_at = datetime.now().timestamp()
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    logs_dir = out_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{variant}_{window.name}"
    (logs_dir / f"{tag}.stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
    (logs_dir / f"{tag}.stderr.txt").write_text(proc.stderr or "", encoding="utf-8")

    if proc.returncode != 0:
        raise RuntimeError(f"{variant}/{window.name} exited with {proc.returncode}")

    run_dir = _find_new_run_dir(engine_dir, before, started_at)
    if run_dir is None:
        raise RuntimeError(f"{variant}/{window.name} did not produce a summary.json run dir")

    return _stage_metrics(run_dir, n_trials=len(spec.variants))


def summarize_results(spec: EngineSpec, results: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    train_rows: list[dict[str, Any]] = []
    for variant, stages in results.items():
        train = stages.get("train")
        if not train:
            continue
        train_rows.append({
            "variant": variant,
            "sharpe": train["sharpe"],
            "sortino": train["sortino"],
            "max_dd_pct": train["max_dd_pct"],
            "n_trades": train["n_trades"],
            "dsr": train["dsr"],
        })
    train_rows.sort(key=lambda row: (_safe_float(row["dsr"], -1.0), _safe_float(row["sharpe"], -1e9)), reverse=True)

    sharpe_values = [row["sharpe"] for row in train_rows]
    sharpe_std = float(np.std(sharpe_values, ddof=1)) if len(sharpe_values) > 1 else 0.0
    best_train = train_rows[0] if train_rows else None
    best_train_stage = results.get(best_train["variant"], {}).get("train") if best_train else None

    top3_variants = [row["variant"] for row in train_rows[:3]]
    top3_test_rows = []
    for rank, variant in enumerate(top3_variants, start=1):
        test = results.get(variant, {}).get("test", {})
        top3_test_rows.append({
            "rank": rank,
            "variant": variant,
            "sharpe_train": results[variant]["train"]["sharpe"],
            "sharpe_test": test.get("sharpe"),
            "sortino_test": test.get("sortino"),
        })

    has_complete_test = bool(top3_test_rows) and all(row["sharpe_test"] is not None for row in top3_test_rows)
    worst_top3_test_sharpe = None
    if has_complete_test:
        worst_top3_test_sharpe = min(_safe_float(r["sharpe_test"], 0.0) for r in top3_test_rows)

    conservative_variant = None
    if has_complete_test:
        conservative_variant = min(top3_test_rows, key=lambda row: _safe_float(row["sharpe_test"], 0.0))["variant"]
    holdout_stage = results.get(conservative_variant, {}).get("holdout") if conservative_variant else None

    return {
        "train_rows": train_rows,
        "best_train_variant": best_train["variant"] if best_train else None,
        "best_train_sharpe": best_train_stage["sharpe"] if best_train_stage else None,
        "best_train_dsr": best_train_stage["dsr"] if best_train_stage else None,
        "sharpe_std": sharpe_std,
        "dsr_passed": bool(best_train_stage and best_train_stage["dsr"] is not None and best_train_stage["dsr"] > 0.95),
        "top3_test_rows": top3_test_rows,
        "worst_top3_test_sharpe": worst_top3_test_sharpe,
        "test_passed": bool(has_complete_test and worst_top3_test_sharpe is not None and worst_top3_test_sharpe > 1.0),
        "test_pending": not has_complete_test,
        "conservative_variant": conservative_variant,
        "holdout_sharpe": holdout_stage["sharpe"] if holdout_stage else None,
        "holdout_passed": bool(holdout_stage) and _safe_float(holdout_stage["sharpe"], 0.0) > 0.8,
        "holdout_pending": holdout_stage is None,
    }


def render_checklist(spec: EngineSpec, aggregate: dict[str, Any]) -> str:
    train_lines = "\n".join(
        f"| {row['variant']} | {row['sharpe']:.3f} | {row['sortino']:.3f} | {row['max_dd_pct']:.2f} | {row['n_trades']} |"
        for row in aggregate["train_rows"]
    ) or "|  |  |  |  |  |"
    top3_lines = "\n".join(
        f"| {row['rank']} | {row['variant']} | {row['sharpe_train']:.3f} | {_fmt_metric(row['sharpe_test'])} | {_fmt_metric(row['sortino_test'])} |"
        for row in aggregate["top3_test_rows"]
    ) or "|  |  |  |  |  |"
    return (
        f"# Engine Validation Checklist - {spec.display}\n\n"
        f"Atualizado automaticamente em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.\n\n"
        "## Passo 1 - Hipotese mecanica\n\n"
        f"- [x] Hipotese registrada em `docs/engines/{spec.key}/hypothesis.md`\n"
        "- [x] Falsificacao escrita antes do grid\n\n"
        "## Passo 2 - Split hardcoded\n\n"
        "```python\n"
        f"TRAIN_END = \"{spec.train_end}\"\n"
        f"TEST_END = \"{spec.test_end}\"\n"
        f"HOLDOUT = \"{spec.test_end}\" ate \"{spec.holdout_end}\"\n"
        "```\n\n"
        "- [ ] Datas commitadas no runner da rodada\n"
        "- [x] Datas absolutas definidas antes da bateria\n\n"
        "## Passo 3 - Grid pre-registrado\n\n"
        f"- [x] Budget fechado em `docs/engines/{spec.key}/grid.md`\n"
        "- [ ] Commit feito antes da config #1\n\n"
        "## Passo 4 - Resultados train\n\n"
        "| # | Sharpe | Sortino | MDD | Trades |\n"
        "|---|---|---|---|---|\n"
        f"{train_lines}\n\n"
        "## Passo 5 - DSR\n\n"
        f"- n_trials: {len(spec.variants)}\n"
        f"- sharpe_best: {_fmt_metric(aggregate['best_train_sharpe'])}\n"
        f"- sharpe_std: {_fmt_metric(aggregate['sharpe_std'])}\n"
        f"- DSR p-value: {_fmt_metric(aggregate['best_train_dsr'])}\n"
        f"- Passou (> 0.95)? {'SIM' if aggregate['dsr_passed'] else 'NAO'}\n\n"
        "## Passo 6 - Top-3 em test\n\n"
        "| rank | config | sharpe_train | sharpe_test | sortino_test |\n"
        "|---|---|---|---|---|\n"
        f"{top3_lines}\n\n"
        f"- Pior Sharpe do top-3: {_fmt_metric(aggregate['worst_top3_test_sharpe'])}\n"
        f"- Passou (> 1.0)? {_status_label(aggregate['test_passed'], aggregate.get('test_pending', False))}\n\n"
        "## Passo 7 - Holdout\n\n"
        f"- Config escolhido: {aggregate['conservative_variant'] or ''}\n"
        f"- Sharpe holdout: {_fmt_metric(aggregate['holdout_sharpe'])}\n"
        f"- Passou (> 0.8)? {_status_label(aggregate['holdout_passed'], aggregate.get('holdout_pending', False))}\n\n"
        "## Passo 8 - Paper forward\n\n"
        "- Start:\n"
        "- End:\n"
        "- Sharpe paper:\n"
        "- Passou (> 50% do holdout)? SIM / NAO\n\n"
        "## Decisao final\n\n"
        "- [ ] FROZEN\n"
        "- [ ] ARQUIVADO\n"
        "- [ ] Motivo preenchido\n"
    )


def _fmt_metric(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)


def _status_label(passed: bool, pending: bool) -> str:
    if pending:
        return "PENDENTE"
    return "SIM" if passed else "NAO"


def write_artifacts(spec: EngineSpec, out_root: Path, results: dict[str, dict[str, dict[str, Any]]], aggregate: dict[str, Any]) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "engine": spec.key,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "windows": [window.__dict__ for window in build_windows(spec)],
        "variants": spec.variants,
        "results": results,
        "aggregate": aggregate,
    }
    (out_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    csv_rows = []
    for variant, stages in results.items():
        for stage_name, metrics in stages.items():
            csv_rows.append({
                "variant": variant,
                "stage": stage_name,
                **metrics,
            })
    if csv_rows:
        with (out_root / "results.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(csv_rows[0].keys()))
            writer.writeheader()
            writer.writerows(csv_rows)

    checklist = render_checklist(spec, aggregate)
    (ROOT / spec.checklist_path).write_text(checklist, encoding="utf-8")


def main() -> int:
    args = _parse_args()
    spec = ENGINE_SPECS[args.engine]
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_root = Path(args.out) if args.out else ROOT / "data" / "anti_overfit" / spec.key / ts
    variants = list(spec.variants.items())
    if args.limit is not None:
        variants = variants[:max(0, args.limit)]

    results: dict[str, dict[str, dict[str, Any]]] = {name: {} for name, _ in variants}
    for variant, overrides in variants:
        for window in build_windows(spec, args.phase):
            print(f"[{spec.display}] {variant} / {window.name} ...")
            results[variant][window.name] = execute_run(spec, variant, overrides, window, args.python, out_root)

    aggregate = summarize_results(spec, results)
    write_artifacts(spec, out_root, results, aggregate)
    print(f"Artifacts -> {out_root}")
    print(f"Checklist -> {ROOT / spec.checklist_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
