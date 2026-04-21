"""Disciplined PHI reopen battery with fixed splits and a closed grid.

Implements the PHI-specific anti-overfit workflow:
1. Tune a pre-registered 16-config grid on train only.
2. Deflate train Sharpe by number of trials.
3. Validate the top-3 configs on test and report the worst of the 3.
4. Run the selected config on holdout.

The script does not mutate the engine. It only replays downstream PHI
layers on cached base frames for each window.
"""
from __future__ import annotations

import json
import logging
import math
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from statistics import NormalDist

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from config.params import ACCOUNT_SIZE
from engines.phi import (
    PhiParams,
    check_golden_trigger,
    check_regime_gates,
    compute_scoring,
    compute_summary,
    detect_cluster,
    prefetch_symbol_universe,
    prepare_symbol_frames,
    scan_symbol,
)

log = logging.getLogger("phi_reopen")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

TRAIN_START = "2023-01-01"
TRAIN_END = "2024-01-01"
TEST_END = "2025-01-01"
HOLDOUT_END = "2026-04-21"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]

WINDOWS = {
    "train": {"start": TRAIN_START, "end": TRAIN_END},
    "test": {"start": TRAIN_END, "end": TEST_END},
    "holdout": {"start": TEST_END, "end": HOLDOUT_END},
}

GRID = [
    {"cluster_min_confluences": 1, "cluster_atr_tolerance": 0.5, "omega_phi_entry": 0.382, "ema200_distance_atr": 0.200},
    {"cluster_min_confluences": 1, "cluster_atr_tolerance": 0.5, "omega_phi_entry": 0.382, "ema200_distance_atr": 0.382},
    {"cluster_min_confluences": 1, "cluster_atr_tolerance": 0.5, "omega_phi_entry": 0.500, "ema200_distance_atr": 0.200},
    {"cluster_min_confluences": 1, "cluster_atr_tolerance": 0.5, "omega_phi_entry": 0.500, "ema200_distance_atr": 0.382},
    {"cluster_min_confluences": 1, "cluster_atr_tolerance": 1.0, "omega_phi_entry": 0.382, "ema200_distance_atr": 0.200},
    {"cluster_min_confluences": 1, "cluster_atr_tolerance": 1.0, "omega_phi_entry": 0.382, "ema200_distance_atr": 0.382},
    {"cluster_min_confluences": 1, "cluster_atr_tolerance": 1.0, "omega_phi_entry": 0.500, "ema200_distance_atr": 0.200},
    {"cluster_min_confluences": 1, "cluster_atr_tolerance": 1.0, "omega_phi_entry": 0.500, "ema200_distance_atr": 0.382},
    {"cluster_min_confluences": 2, "cluster_atr_tolerance": 0.5, "omega_phi_entry": 0.382, "ema200_distance_atr": 0.200},
    {"cluster_min_confluences": 2, "cluster_atr_tolerance": 0.5, "omega_phi_entry": 0.382, "ema200_distance_atr": 0.382},
    {"cluster_min_confluences": 2, "cluster_atr_tolerance": 0.5, "omega_phi_entry": 0.500, "ema200_distance_atr": 0.200},
    {"cluster_min_confluences": 2, "cluster_atr_tolerance": 0.5, "omega_phi_entry": 0.500, "ema200_distance_atr": 0.382},
    {"cluster_min_confluences": 2, "cluster_atr_tolerance": 1.0, "omega_phi_entry": 0.382, "ema200_distance_atr": 0.200},
    {"cluster_min_confluences": 2, "cluster_atr_tolerance": 1.0, "omega_phi_entry": 0.382, "ema200_distance_atr": 0.382},
    {"cluster_min_confluences": 2, "cluster_atr_tolerance": 1.0, "omega_phi_entry": 0.500, "ema200_distance_atr": 0.200},
    {"cluster_min_confluences": 2, "cluster_atr_tolerance": 1.0, "omega_phi_entry": 0.500, "ema200_distance_atr": 0.382},
]

BASE_PARAMS = PhiParams(
    adx_min=10.0,
    wick_ratio_min=0.382,
    volume_mult=1.272,
    entry_mode="continuation",
)


def _strip_downstream_cols(df: pd.DataFrame) -> pd.DataFrame:
    drop_prefixes = ("cluster_", "regime_ok", "trigger_", "phi_score", "omega_phi", "trend_alignment")
    keep = [c for c in df.columns if not any(c == prefix or c.startswith(prefix) for prefix in drop_prefixes)]
    return df[keep].copy()


def _days_between(start: str, end: str) -> int:
    return int((pd.Timestamp(end) - pd.Timestamp(start)).days)


def _window_meta(name: str) -> dict[str, str | int]:
    start = WINDOWS[name]["start"]
    end = WINDOWS[name]["end"]
    return {"start": start, "end": end, "days": _days_between(start, end)}


def _run_combo(base_frames: dict[str, pd.DataFrame], params: PhiParams, days: int) -> tuple[dict, dict]:
    all_trades: list[dict] = []
    per_symbol: dict[str, dict] = {}
    for sym, base in base_frames.items():
        df = _strip_downstream_cols(base)
        df = detect_cluster(df, params)
        df = check_regime_gates(df, params)
        df = check_golden_trigger(df, params)
        df = compute_scoring(df, params)
        trades, vetos = scan_symbol(df, sym, params, ACCOUNT_SIZE)
        sym_summary = compute_summary(trades, ACCOUNT_SIZE, n_days=days)
        sym_summary["vetos"] = vetos
        per_symbol[sym] = sym_summary
        all_trades.extend(trades)
    summary = compute_summary(all_trades, ACCOUNT_SIZE, n_days=days)
    return summary, per_symbol


def _expected_max_sharpe(sharpe_std: float, n_trials: int) -> float:
    if sharpe_std <= 0 or n_trials <= 1:
        return 0.0
    norm = NormalDist()
    return sharpe_std * (
        (1.0 - 0.5772) * norm.inv_cdf(1.0 - 1.0 / n_trials)
        + 0.5772 * norm.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    )


def _dsr_pvalue(sharpe_best: float, n_trials: int, sharpe_std: float, T: int) -> float:
    if T <= 1:
        return 0.0
    e_max = _expected_max_sharpe(sharpe_std, n_trials)
    numerator = (sharpe_best - e_max) * math.sqrt(T - 1.0)
    denominator = math.sqrt(max(1e-12, 1.0 + 0.5 * sharpe_best * sharpe_best))
    return NormalDist().cdf(numerator / denominator)


def _prepare_window_frames(window_name: str) -> dict[str, pd.DataFrame]:
    meta = _window_meta(window_name)
    days = int(meta["days"])
    end = str(meta["end"])
    log.info("Preparing %s window: %s -> %s (%sd)", window_name, meta["start"], end, days)
    prefetched, _ = prefetch_symbol_universe(SYMBOLS, BASE_PARAMS, days=days, end=end)
    base_frames: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        merged = prepare_symbol_frames(sym, BASE_PARAMS, prefetched=prefetched, days=days, end=end)
        if merged is not None:
            base_frames[sym] = merged
    if not base_frames:
        raise RuntimeError(f"no frames prepared for {window_name}")
    return base_frames


def main() -> int:
    started = time.time()
    train_meta = _window_meta("train")
    train_frames = _prepare_window_frames("train")
    train_rows: list[dict] = []
    for idx, overrides in enumerate(GRID, 1):
        params = replace(BASE_PARAMS, **overrides)
        summary, per_symbol = _run_combo(train_frames, params, int(train_meta["days"]))
        train_rows.append(
            {
                "rank_key": idx,
                "config_id": f"phi_{idx:02d}",
                "params": asdict(params),
                "overrides": overrides,
                "train_summary": summary,
                "train_per_symbol": per_symbol,
            }
        )
        log.info(
            "[train %02d/%02d] %s trades=%d sharpe=%.3f pnl=%+.2f",
            idx,
            len(GRID),
            train_rows[-1]["config_id"],
            summary["total_trades"],
            summary["sharpe"],
            summary["total_pnl"],
        )

    train_sharpes = [float(row["train_summary"].get("sharpe", 0.0) or 0.0) for row in train_rows]
    sharpe_std = pd.Series(train_sharpes).std(ddof=0)
    expected_max = _expected_max_sharpe(float(sharpe_std or 0.0), len(train_rows))
    for row in train_rows:
        sharpe = float(row["train_summary"].get("sharpe", 0.0) or 0.0)
        row["train_dsr_expected_max"] = expected_max
        row["train_deflated_sharpe"] = sharpe - expected_max
        row["train_dsr_pvalue"] = _dsr_pvalue(sharpe, len(train_rows), float(sharpe_std or 0.0), int(train_meta["days"]))

    train_rows.sort(
        key=lambda row: (
            float(row["train_deflated_sharpe"]),
            float(row["train_dsr_pvalue"]),
            float(row["train_summary"].get("sharpe", 0.0) or 0.0),
            float(row["train_summary"].get("total_pnl", 0.0) or 0.0),
        ),
        reverse=True,
    )
    top3 = train_rows[:3]

    test_meta = _window_meta("test")
    test_frames = _prepare_window_frames("test")
    for row in top3:
        params = replace(BASE_PARAMS, **row["overrides"])
        summary, per_symbol = _run_combo(test_frames, params, int(test_meta["days"]))
        row["test_summary"] = summary
        row["test_per_symbol"] = per_symbol

    top3.sort(
        key=lambda row: (
            float(row["test_summary"].get("sharpe", -999.0) or -999.0),
            float(row["test_summary"].get("total_pnl", -999999.0) or -999999.0),
        )
    )
    chosen = top3[0]

    holdout_meta = _window_meta("holdout")
    holdout_frames = _prepare_window_frames("holdout")
    chosen_params = replace(BASE_PARAMS, **chosen["overrides"])
    holdout_summary, holdout_per_symbol = _run_combo(holdout_frames, chosen_params, int(holdout_meta["days"]))
    chosen["holdout_summary"] = holdout_summary
    chosen["holdout_per_symbol"] = holdout_per_symbol

    best_train = train_rows[0]
    decision = {
        "train_gate_pass": (
            float(best_train["train_deflated_sharpe"]) >= 1.5
            and float(best_train["train_dsr_pvalue"]) >= 0.95
        ),
        "test_gate_pass": min(float(row["test_summary"].get("sharpe", 0.0) or 0.0) for row in top3) >= 1.0,
        "holdout_gate_pass": float(chosen["holdout_summary"].get("sharpe", 0.0) or 0.0) >= 0.8,
    }
    decision["survives_protocol"] = all(decision.values())
    decision["final_status"] = "survive_candidate" if decision["survives_protocol"] else "archive"

    payload = {
        "engine": "PHI",
        "registered_on": "2026-04-21",
        "symbols": SYMBOLS,
        "windows": WINDOWS,
        "grid_size": len(GRID),
        "base_params": asdict(BASE_PARAMS),
        "train_sharpe_std": float(sharpe_std or 0.0),
        "train_rows": train_rows,
        "top3_tested": top3,
        "chosen": chosen,
        "decision": decision,
        "elapsed_s": round(time.time() - started, 2),
    }

    out_dir = Path("data/phi/reopen_protocol")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = pd.Timestamp.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"phi_reopen_{ts}.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 118)
    print("  PHI REOPEN PROTOCOL")
    print("=" * 118)
    print(f"  Train window   : {TRAIN_START} -> {TRAIN_END}")
    print(f"  Test window    : {TRAIN_END} -> {TEST_END}")
    print(f"  Holdout window : {TEST_END} -> {HOLDOUT_END}")
    print(f"  Universe       : {', '.join(SYMBOLS)}")
    print(f"  Grid size      : {len(GRID)}")
    print(f"  Train sigma    : {float(sharpe_std or 0.0):.3f}")
    print("-" * 118)
    print(f"  {'cfg':<8} {'trades':>7} {'sharpe':>8} {'defl_sh':>8} {'dsr_p':>8} {'pnl':>11}")
    for row in train_rows[:8]:
        summary = row["train_summary"]
        print(
            f"  {row['config_id']:<8} {summary['total_trades']:>7} {summary['sharpe']:>8.3f} "
            f"{row['train_deflated_sharpe']:>8.3f} {row['train_dsr_pvalue']:>8.3f} {summary['total_pnl']:>+11.2f}"
        )
    print("-" * 118)
    print("  Top-3 test results:")
    for row in top3:
        test_summary = row["test_summary"]
        print(
            f"    {row['config_id']}: trades={test_summary['total_trades']} "
            f"sharpe={test_summary['sharpe']:.3f} pnl={test_summary['total_pnl']:+.2f}"
        )
    print(
        f"  Chosen for holdout: {chosen['config_id']} | "
        f"holdout trades={holdout_summary['total_trades']} "
        f"sharpe={holdout_summary['sharpe']:.3f} pnl={holdout_summary['total_pnl']:+.2f}"
    )
    print(f"  Final decision: {decision['final_status']}")
    print(f"  Saved: {out_path}")
    print("=" * 118)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
