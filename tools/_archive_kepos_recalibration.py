from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from analysis.dsr import deflated_sharpe_ratio
from config.params import ACCOUNT_SIZE, BASKETS, SYMBOLS, _TF_MINUTES
from core.data import fetch_all, validate
from engines.kepos import (
    KeposParams,
    compute_features,
    compute_summary,
    run_backtest_on_features,
)
from tools.anti_overfit_grid import (
    ENGINE_SPECS,
    build_windows,
    load_existing_results,
    select_variants,
    summarize_results,
    write_artifacts,
)


SPEC = ENGINE_SPECS["kepos"]
ROOT = Path(__file__).resolve().parents[1]


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run the closed KEPOS recalibration grid efficiently.")
    ap.add_argument("--phase", choices=["all", "train", "test", "holdout"], default="all")
    ap.add_argument("--out", required=True, help="Artifact directory for manifest/checklist/logs.")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--variant", action="append", default=None)
    ap.add_argument("--force", action="store_true", help="Re-run already recorded variant/window stages.")
    return ap.parse_args()


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
    return m3 / (m2 ** 1.5), m4 / (m2 ** 2)


def _stage_metrics(
    trades: list[dict[str, Any]],
    summary: dict[str, Any],
    per_sym: dict[str, dict[str, Any]],
    *,
    n_trials: int,
) -> dict[str, Any]:
    pnls = [float(t["pnl"]) for t in trades if t.get("pnl") is not None]
    skew, kurtosis = _sample_skew_kurtosis(pnls)
    sharpe = float(summary.get("sharpe", 0.0) or 0.0)
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
        "run_dir": "",
        "n_trades": int(summary.get("n_trades", 0)),
        "win_rate": float(summary.get("win_rate", 0.0) or 0.0),
        "pnl": float(summary.get("pnl", 0.0) or 0.0),
        "roi_pct": float(summary.get("roi_pct", 0.0) or 0.0),
        "sharpe": sharpe,
        "sortino": float(summary.get("sortino", 0.0) or 0.0),
        "max_dd_pct": float(summary.get("max_dd_pct", 0.0) or 0.0),
        "skew": skew,
        "kurtosis": kurtosis,
        "dsr": dsr,
        "per_symbol": per_sym,
    }


def _build_params(overrides: dict[str, Any]) -> KeposParams:
    params = KeposParams(interval=SPEC.interval)
    mapping = {
        "rsi_exhaustion": "rsi_exhaustion_level",
        "cooldown_bars": "min_reentry_cooldown_bars",
        "hmm_min_prob_chop": "hmm_min_prob_chop",
        "hmm_max_trend_prob": "hmm_max_trend_prob",
        "tp_atr": "tp_atr_mult",
    }
    updates = {mapping[key]: value for key, value in overrides.items()}
    return replace(params, **updates)


def _fetch_window(window) -> dict[str, Any]:
    symbols = BASKETS.get(SPEC.basket, SYMBOLS)
    tf_min = max(1, _TF_MINUTES.get(SPEC.interval, 15))
    n_candles = window.days * 24 * 60 // tf_min
    end_time_ms = int(__import__("pandas").Timestamp(window.end).timestamp() * 1000)
    all_dfs = fetch_all(
        symbols,
        interval=SPEC.interval,
        n_candles=n_candles,
        futures=True,
        end_time_ms=end_time_ms,
    )
    for sym, df in all_dfs.items():
        validate(df, sym)
    return all_dfs


def _precompute_features(all_dfs: dict[str, Any]) -> dict[str, Any]:
    base_params = KeposParams(interval=SPEC.interval)
    return {sym: compute_features(df, base_params) for sym, df in all_dfs.items()}


def main() -> int:
    args = _parse_args()
    out_root = Path(args.out)
    results = load_existing_results(out_root)
    variants = select_variants(
        SPEC,
        variant_names=args.variant,
        offset=max(0, args.offset),
        limit=args.limit,
    )
    windows = build_windows(SPEC, args.phase)
    n_trials = len(SPEC.variants)

    for window in windows:
        print(f"[KEPOS] precomputing window={window.name} days={window.days} end={window.end}")
        all_dfs = _fetch_window(window)
        all_features = _precompute_features(all_dfs)
        for variant_name, overrides in variants:
            existing = results.get(variant_name, {}).get(window.name)
            if existing and not args.force:
                print(f"[KEPOS] skip {variant_name}/{window.name} (already recorded)")
                continue
            params = _build_params(overrides)
            print(f"[KEPOS] run {variant_name}/{window.name}")
            trades, vetos, per_sym = run_backtest_on_features(
                all_features,
                params=params,
                initial_equity=ACCOUNT_SIZE,
            )
            summary = compute_summary(trades, ACCOUNT_SIZE)
            stage = _stage_metrics(trades, summary, per_sym, n_trials=n_trials)
            stage["vetos"] = vetos
            results.setdefault(variant_name, {})[window.name] = stage
            aggregate = summarize_results(SPEC, results)
            write_artifacts(SPEC, out_root, results, aggregate)

    aggregate = summarize_results(SPEC, results)
    write_artifacts(SPEC, out_root, results, aggregate)
    print(f"Artifacts -> {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
