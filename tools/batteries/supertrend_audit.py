"""Disciplined SUPERTREND FUT overfit audit with fixed splits and closed grid.

Implements the SUPERTREND_FUT-specific anti-overfit workflow:
1. Tune a pre-registered 9-config grid on train only.
2. Deflate train Sharpe by number of trials (DSR).
3. Validate top-3 configs on test, report worst-of-3.
4. Run the chosen config on holdout.

The script does not mutate the engine module permanently — overrides
STOPLOSS_PCT and INITIAL_ROI_PCT via module attribute patching for each
config, restoring defaults at the end.

Specs: docs/engines/supertrend_futures/{hypothesis,grid}.md
"""
from __future__ import annotations

import json
import logging
import math
import sys
import time
from pathlib import Path
from statistics import NormalDist

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from config.params import ACCOUNT_SIZE
from analysis.stats import calc_ratios, equity_stats
from core import fetch_all, validate
from engines import supertrend_futures as stfu
from engines.supertrend_futures import (
    HOLDOUT_END, INTERVAL, LEVERAGE, TEST_END, TRAIN_END, TRAIN_START,
    scan_supertrend,
)

log = logging.getLogger("supertrend_audit")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]

WINDOWS = {
    "train":   {"start": TRAIN_START, "end": TRAIN_END},
    "test":    {"start": TRAIN_END,   "end": TEST_END},
    "holdout": {"start": TEST_END,    "end": HOLDOUT_END},
}

# Grid pré-registrado — docs/engines/supertrend_futures/grid.md
GRID = [
    {"id": "sf_01", "STOPLOSS_PCT": 0.20,  "INITIAL_ROI_PCT": 0.08},
    {"id": "sf_02", "STOPLOSS_PCT": 0.20,  "INITIAL_ROI_PCT": 0.10},
    {"id": "sf_03", "STOPLOSS_PCT": 0.20,  "INITIAL_ROI_PCT": 0.15},
    {"id": "sf_04", "STOPLOSS_PCT": 0.265, "INITIAL_ROI_PCT": 0.08},
    {"id": "sf_05", "STOPLOSS_PCT": 0.265, "INITIAL_ROI_PCT": 0.10},  # default freqtrade
    {"id": "sf_06", "STOPLOSS_PCT": 0.265, "INITIAL_ROI_PCT": 0.15},
    {"id": "sf_07", "STOPLOSS_PCT": 0.35,  "INITIAL_ROI_PCT": 0.08},
    {"id": "sf_08", "STOPLOSS_PCT": 0.35,  "INITIAL_ROI_PCT": 0.10},
    {"id": "sf_09", "STOPLOSS_PCT": 0.35,  "INITIAL_ROI_PCT": 0.15},
]


def _days_between(start: str, end: str) -> int:
    return int((pd.Timestamp(end) - pd.Timestamp(start)).days)


def _window_meta(name: str) -> dict:
    w = WINDOWS[name]
    return {"start": w["start"], "end": w["end"], "days": _days_between(w["start"], w["end"])}


def _fetch_window(window_name: str, warmup_days: int = 30) -> dict[str, pd.DataFrame]:
    """Fetch 1h klines for each symbol covering [start - warmup, end]. Returns
    symbol → dataframe dict with rows filtered to window_start..window_end.
    Warmup buffer feeds supertrend warmup (max period ~18 bars) plus margin.
    """
    meta = _window_meta(window_name)
    start_ts = pd.Timestamp(meta["start"])
    end_ts = pd.Timestamp(meta["end"])
    fetch_start = start_ts - pd.Timedelta(days=warmup_days)
    end_ms = int(end_ts.timestamp() * 1000)
    # 1h → 24 bars/day; +warmup; +300 safety
    n_candles = int((end_ts - fetch_start).total_seconds() / 3600) + 300
    log.info("fetch %s: %s → %s (n=%d)", window_name, meta["start"], meta["end"], n_candles)
    raw = fetch_all(SYMBOLS, interval=INTERVAL, n_candles=n_candles,
                    futures=True, end_time_ms=end_ms, min_rows=300)
    frames: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        df = raw.get(sym)
        if df is None:
            log.warning("missing data for %s in %s", sym, window_name)
            continue
        validate(df, sym)
        # Keep warmup buffer so supertrend has warmup; scan_supertrend
        # internally handles warmup. But downstream stats use only the
        # in-window portion — we slice by trade timestamp below.
        frames[sym] = df.reset_index(drop=True)
    return frames


def _run_config(frames: dict[str, pd.DataFrame], window_name: str, cfg: dict) -> dict:
    """Run a single config on all symbols in a window. Returns summary.

    Filters trades to those *entered* within the window, so warmup bars
    outside the window don't leak into performance stats.
    """
    # Patch module-level constants
    prev_stop = stfu.STOPLOSS_PCT
    prev_roi = stfu.INITIAL_ROI_PCT
    stfu.STOPLOSS_PCT = float(cfg["STOPLOSS_PCT"])
    stfu.INITIAL_ROI_PCT = float(cfg["INITIAL_ROI_PCT"])
    try:
        meta = _window_meta(window_name)
        window_start = pd.Timestamp(meta["start"])
        window_end = pd.Timestamp(meta["end"])
        all_trades: list[dict] = []
        per_sym: dict[str, dict] = {}
        for sym, df in frames.items():
            trades, vetos = scan_supertrend(df.copy(), sym)
            # Filter: entries within window only
            window_trades = []
            for t in trades:
                ts = pd.Timestamp(t.get("timestamp"))
                if pd.isna(ts):
                    continue
                if window_start <= ts < window_end:
                    window_trades.append(t)
            closed = [t for t in window_trades if t.get("result") in ("WIN", "LOSS")]
            pnl_list = [float(t.get("pnl", 0.0)) for t in closed]
            sym_summary = _summary(pnl_list, closed, meta["days"])
            sym_summary["vetos"] = dict(vetos)
            per_sym[sym] = sym_summary
            all_trades.extend(window_trades)
        closed_all = [t for t in all_trades if t.get("result") in ("WIN", "LOSS")]
        pnl_all = [float(t.get("pnl", 0.0)) for t in closed_all]
        summary = _summary(pnl_all, closed_all, meta["days"])
        summary["per_symbol_sharpe"] = {k: v.get("sharpe") for k, v in per_sym.items()}
        return {"summary": summary, "per_symbol": per_sym}
    finally:
        stfu.STOPLOSS_PCT = prev_stop
        stfu.INITIAL_ROI_PCT = prev_roi


def _summary(pnl_list: list[float], closed_trades: list[dict], n_days: int) -> dict:
    if not pnl_list:
        return {
            "total_trades": 0, "win_rate": 0.0, "total_pnl": 0.0,
            "sharpe": None, "sortino": None, "max_dd_pct": 0.0, "roi": 0.0,
        }
    ratios = calc_ratios(pnl_list, ACCOUNT_SIZE, n_days=n_days)
    equity, _, max_dd_pct, _ = equity_stats(pnl_list, ACCOUNT_SIZE)
    wins = sum(1 for t in closed_trades if t.get("result") == "WIN")
    return {
        "total_trades": len(closed_trades),
        "win_rate": round(wins / len(closed_trades) * 100.0, 2) if closed_trades else 0.0,
        "total_pnl": round(sum(pnl_list), 2),
        "sharpe": ratios.get("sharpe"),
        "sortino": ratios.get("sortino"),
        "max_dd_pct": round(max_dd_pct, 2),
        "roi": round(ratios.get("ret", 0.0), 2),
    }


def _expected_max_sharpe(sharpe_std: float, n_trials: int) -> float:
    if sharpe_std <= 0 or n_trials <= 1:
        return 0.0
    norm = NormalDist()
    return sharpe_std * (
        (1.0 - 0.5772) * norm.inv_cdf(1.0 - 1.0 / n_trials)
        + 0.5772 * norm.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    )


def _dsr_pvalue(sharpe_best: float, n_trials: int, sharpe_std: float, T: int) -> float:
    if T <= 1 or sharpe_best is None:
        return 0.0
    e_max = _expected_max_sharpe(sharpe_std, n_trials)
    num = (sharpe_best - e_max) * math.sqrt(T - 1.0)
    den = math.sqrt(max(1e-12, 1.0 + 0.5 * sharpe_best * sharpe_best))
    return NormalDist().cdf(num / den)


def main() -> int:
    started = time.time()

    # ── TRAIN ──────────────────────────────────────────────────────────
    train_meta = _window_meta("train")
    train_frames = _fetch_window("train")
    train_rows: list[dict] = []
    for idx, cfg in enumerate(GRID, 1):
        result = _run_config(train_frames, "train", cfg)
        summary = result["summary"]
        train_rows.append({
            "config_id": cfg["id"],
            "params": {k: v for k, v in cfg.items() if k != "id"},
            "train_summary": summary,
            "train_per_symbol": result["per_symbol"],
        })
        log.info(
            "[train %d/%d] %s trades=%d sharpe=%s pnl=%+.2f",
            idx, len(GRID), cfg["id"], summary["total_trades"],
            f"{summary['sharpe']:.3f}" if summary['sharpe'] else "None",
            summary["total_pnl"],
        )

    train_sharpes = [float(r["train_summary"].get("sharpe") or 0.0) for r in train_rows]
    sharpe_std = float(pd.Series(train_sharpes).std(ddof=0) or 0.0)
    expected_max = _expected_max_sharpe(sharpe_std, len(train_rows))
    for row in train_rows:
        sh = float(row["train_summary"].get("sharpe") or 0.0)
        row["train_deflated_sharpe"] = sh - expected_max
        row["train_dsr_pvalue"] = _dsr_pvalue(sh, len(train_rows), sharpe_std, train_meta["days"])
    row0 = train_rows[0] if train_rows else None

    train_rows.sort(key=lambda r: (
        float(r["train_deflated_sharpe"]),
        float(r["train_dsr_pvalue"]),
        float(r["train_summary"].get("sharpe") or 0.0),
    ), reverse=True)
    best_train = train_rows[0]
    top3 = train_rows[:3]

    # ── TRAIN GATE ─────────────────────────────────────────────────────
    train_gate_pass = (
        best_train["train_deflated_sharpe"] >= 1.5
        and best_train["train_dsr_pvalue"] >= 0.95
    )

    # ── TEST (só se train gate passar) ─────────────────────────────────
    test_frames = None
    if train_gate_pass:
        test_frames = _fetch_window("test")
        for row in top3:
            cfg = {"id": row["config_id"], **row["params"]}
            result = _run_config(test_frames, "test", cfg)
            row["test_summary"] = result["summary"]
            row["test_per_symbol"] = result["per_symbol"]
        # Choose worst-of-top-3 by test Sharpe (anti-overfit)
        top3.sort(key=lambda r: float(r["test_summary"].get("sharpe") or -999.0))
        chosen = top3[0]
        test_gate_pass = float(chosen["test_summary"].get("sharpe") or -999.0) >= 1.0
    else:
        chosen = best_train
        test_gate_pass = False

    # ── HOLDOUT (só se test gate passar) ───────────────────────────────
    if train_gate_pass and test_gate_pass:
        holdout_frames = _fetch_window("holdout")
        cfg = {"id": chosen["config_id"], **chosen["params"]}
        result = _run_config(holdout_frames, "holdout", cfg)
        chosen["holdout_summary"] = result["summary"]
        chosen["holdout_per_symbol"] = result["per_symbol"]
        holdout_gate_pass = float(chosen["holdout_summary"].get("sharpe") or 0.0) >= 0.8
    else:
        holdout_gate_pass = False

    survives = train_gate_pass and test_gate_pass and holdout_gate_pass
    decision = {
        "train_gate_pass": train_gate_pass,
        "test_gate_pass": test_gate_pass,
        "holdout_gate_pass": holdout_gate_pass,
        "survives_protocol": survives,
        "final_status": "survive_candidate" if survives else "archive",
    }

    payload = {
        "engine": "SUPERTREND_FUT",
        "registered_on": "2026-04-22",
        "symbols": SYMBOLS,
        "windows": WINDOWS,
        "grid_size": len(GRID),
        "leverage": LEVERAGE,
        "interval": INTERVAL,
        "train_sharpe_std": sharpe_std,
        "train_expected_max_sharpe": expected_max,
        "train_rows": train_rows,
        "top3_tested": top3 if train_gate_pass else [],
        "chosen": chosen,
        "decision": decision,
        "elapsed_s": round(time.time() - started, 2),
    }

    out_dir = Path("data/supertrend_futures/audit")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = pd.Timestamp.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"supertrend_audit_{ts}.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    # ── REPORT ─────────────────────────────────────────────────────────
    print("\n" + "=" * 118)
    print("  SUPERTREND FUT OVERFIT AUDIT")
    print("=" * 118)
    print(f"  Train window   : {TRAIN_START} → {TRAIN_END}  ({train_meta['days']}d)")
    print(f"  Test window    : {TRAIN_END} → {TEST_END}")
    print(f"  Holdout window : {TEST_END} → {HOLDOUT_END}")
    print(f"  Universe       : {', '.join(SYMBOLS)}")
    print(f"  Grid size      : {len(GRID)}")
    print(f"  Train σ(sharpe): {sharpe_std:.3f}")
    print(f"  E[max sharpe]  : {expected_max:.3f}")
    print("-" * 118)
    print(f"  {'cfg':<8} {'stop':>6} {'roi':>6} {'trades':>7} {'sharpe':>8} {'defl_sh':>8} {'dsr_p':>8} {'pnl':>11}")
    for row in train_rows:
        s = row["train_summary"]
        p = row["params"]
        sh = s["sharpe"] if s["sharpe"] is not None else 0.0
        print(
            f"  {row['config_id']:<8} {p['STOPLOSS_PCT']:>6.3f} {p['INITIAL_ROI_PCT']:>6.3f} "
            f"{s['total_trades']:>7} {sh:>8.3f} {row['train_deflated_sharpe']:>8.3f} "
            f"{row['train_dsr_pvalue']:>8.3f} {s['total_pnl']:>+11.2f}"
        )
    print("-" * 118)
    print(f"  Best train cfg : {best_train['config_id']} "
          f"(deflated sharpe {best_train['train_deflated_sharpe']:.3f}, "
          f"DSR p {best_train['train_dsr_pvalue']:.3f})")
    print(f"  Train gate     : {'PASS' if train_gate_pass else 'FAIL'}")

    if train_gate_pass:
        print("  Top-3 on test  :")
        for row in top3:
            ts_summary = row.get("test_summary", {})
            sh = ts_summary.get("sharpe")
            sh_str = f"{sh:.3f}" if sh else "None"
            print(
                f"    {row['config_id']}: trades={ts_summary.get('total_trades', 0)} "
                f"sharpe={sh_str} pnl={ts_summary.get('total_pnl', 0):+.2f}"
            )
        print(f"  Test gate      : {'PASS' if test_gate_pass else 'FAIL'} "
              f"(worst-of-3 chosen = {chosen['config_id']})")
        if test_gate_pass:
            h = chosen.get("holdout_summary", {})
            sh = h.get("sharpe")
            sh_str = f"{sh:.3f}" if sh else "None"
            print(
                f"  Holdout        : trades={h.get('total_trades', 0)} "
                f"sharpe={sh_str} pnl={h.get('total_pnl', 0):+.2f}"
            )
            print(f"  Holdout gate   : {'PASS' if holdout_gate_pass else 'FAIL'}")
    print("-" * 118)
    print(f"  FINAL DECISION : {decision['final_status'].upper()}")
    print(f"  Elapsed        : {payload['elapsed_s']:.1f}s")
    print(f"  Report         : {out_path}")
    print("=" * 118 + "\n")
    return 0 if survives else 0  # always exit 0 — archive is valid outcome


if __name__ == "__main__":
    sys.exit(main())
