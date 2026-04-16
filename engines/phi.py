"""
PHI — AURUM Finance Fibonacci Fractal Engine
=============================================
Pure Fibonacci multi-timeframe confluence strategy. Detects when multiple
fractal layers (1D/4H/1H/15m/5m) agree on a 0.618 retracement within
0.5*ATR, and executes on a Golden Trigger in the 5m execution TF.

Hypothesis (spec 2026-04-16-aurum-phi-design.md)
------------------------------------------------
Fibonacci confluence across 5 timeframes plus strong rejection in the
micro TF produces a measurable edge over random pullback entries.

Discipline
----------
- Local feature computation (ATR/RSI/BB/ADX/EMA200). No core.indicators
  mutation (protected module).
- AURUM cost model (C1+C2) imported from config.params.
- Local sizing (Phi_Score² convex, 1% risk, 2% notional cap). No coupling
  to core.portfolio.
- Backtest-first. Registered in config/engines.py but NOT in
  FROZEN_ENGINES / ENGINE_INTERVALS until overfit_audit 6/6 passes.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from config.params import (
    ACCOUNT_SIZE,
    BASKETS,
    COMMISSION,
    FUNDING_PER_8H,
    LEVERAGE,
    SLIPPAGE,
    SPREAD,
    SYMBOLS,
    _TF_MINUTES,
)
from core.data import fetch_all, validate
from core.fs import atomic_write

log = logging.getLogger("PHI")
_tl = logging.getLogger("PHI.trades")


# ════════════════════════════════════════════════════════════════════
# Parameters — all thresholds from the Fibonacci series
# ════════════════════════════════════════════════════════════════════

@dataclass
class PhiParams:
    # Timeframes (Ω1..Ω5)
    tf_omega1: str = "1d"
    tf_omega2: str = "4h"
    tf_omega3: str = "1h"
    tf_omega4: str = "15m"
    tf_omega5: str = "5m"

    # Zigzag
    zigzag_atr_mult: float = 2.0
    pivot_confirm_bars: int = 2

    # Cluster
    cluster_atr_tolerance: float = 0.5   # |price-fib_0.618| < 0.5*ATR(14,5m)
    cluster_min_confluences: int = 3
    cluster_window_bars: int = 3         # trigger within 3 bars of cluster

    # Regime gates
    adx_min: float = 23.6
    bb_width_percentile: float = 38.2
    bb_width_lookback: int = 500
    ema200_distance_atr: float = 0.618

    # Golden Trigger
    wick_ratio_min: float = 0.618
    volume_mult: float = 1.272
    rsi_long_max: float = 38.2
    rsi_short_min: float = 61.8

    # Ω_PHI weights (sum = 1.000)
    w_phi_score: float = 0.382
    w_rejection: float = 0.236
    w_volume: float = 0.146
    w_trend: float = 0.146
    w_regime: float = 0.090
    omega_phi_entry: float = 0.618

    # Sizing (Golden Convex)
    risk_per_trade: float = 0.01
    notional_cap: float = 0.02
    range_size_scale: float = 0.618

    # Trade levels
    sl_atr_buffer: float = 0.3  # ±0.3*ATR(1h) past fib_0.786
    tp1_partial: float = 0.382
    tp2_partial: float = 0.382
    tp3_runner: float = 0.236

    # Kill-switch (% drawdown from equity high)
    kill_daily: float = 0.02618
    kill_weekly: float = 0.0618

    # Data window
    n_candles_5m: int = 210_000  # ~2 years at 5m
    max_bars_in_trade: int = 288  # 24h on 5m


# ════════════════════════════════════════════════════════════════════
# Local feature computation
# ════════════════════════════════════════════════════════════════════

def _rma(series: pd.Series, length: int) -> pd.Series:
    """Wilder's RMA (smoothed moving average)."""
    return series.ewm(alpha=1.0 / length, adjust=False).mean()


def _atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return _rma(tr, length)


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    avg_up = _rma(up, length)
    avg_down = _rma(down, length)
    rs = avg_up / avg_down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _bb_width(close: pd.Series, length: int = 20, k: float = 2.0) -> pd.Series:
    mid = close.rolling(length).mean()
    sd = close.rolling(length).std(ddof=0)
    return (2 * k * sd) / mid


def _adx(df: pd.DataFrame, length: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff()
    down = -l.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr_ = _rma(tr, length)
    plus_di = 100 * _rma(pd.Series(plus_dm, index=df.index), length) / atr_.replace(0, np.nan)
    minus_di = 100 * _rma(pd.Series(minus_dm, index=df.index), length) / atr_.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return _rma(dx, length)


def compute_features(df: pd.DataFrame, params: PhiParams) -> pd.DataFrame:
    """Add local indicators to df. No lookahead."""
    out = df.copy()
    out["atr"] = _atr(out, 14)
    out["rsi"] = _rsi(out["close"], 14)
    out["bb_width"] = _bb_width(out["close"], 20, 2.0)
    out["adx"] = _adx(out, 14)
    out["ema200"] = out["close"].ewm(span=200, adjust=False).mean()
    out["ema200_slope"] = out["ema200"].diff(20) / 20.0
    body = (out["close"] - out["open"]).abs()
    total_range = (out["high"] - out["low"]).replace(0, np.nan)
    upper_wick = out["high"] - out[["open", "close"]].max(axis=1)
    lower_wick = out[["open", "close"]].min(axis=1) - out["low"]
    wick = pd.concat([upper_wick, lower_wick], axis=1).max(axis=1)
    out["wick_ratio"] = (wick / total_range).clip(0, 1).fillna(0)
    out["body_ratio"] = (body / total_range).fillna(0)
    out["vol_ma20"] = out["volume"].rolling(20).mean()
    return out


def compute_zigzag(df: pd.DataFrame, params: PhiParams) -> pd.DataFrame:
    """Add last_pivot_* and prev_pivot_* columns using confirmed-pivot zigzag.

    Algorithm: walk forward tracking a running extreme. When price moves
    against the running extreme by >= zigzag_atr_mult * ATR, the extreme
    becomes a *candidate* pivot. After `pivot_confirm_bars` bars without
    being superseded, it's *confirmed* and exposed at indices
    >= (candidate_idx + pivot_confirm_bars). On confirmation, the prior
    confirmed pivot rotates into prev_pivot_*.

    No lookahead: the confirmed pivot visible at row t never depends on
    data from rows > t.
    """
    out = df.copy()
    n = len(out)
    high = out["high"].to_numpy()
    low = out["low"].to_numpy()
    atr = out["atr"].to_numpy()

    last_pivot_idx = np.full(n, -1, dtype=np.int64)
    last_pivot_price = np.full(n, np.nan)
    last_pivot_type = np.array([""] * n, dtype=object)
    prev_pivot_idx_arr = np.full(n, -1, dtype=np.int64)
    prev_pivot_price_arr = np.full(n, np.nan)
    prev_pivot_type_arr = np.array([""] * n, dtype=object)

    # Running extreme state
    run_ext_idx = 0
    run_ext_high = high[0]
    run_ext_low = low[0]
    run_dir = 0  # 0 = unknown; +1 = seeking new high (from low base); -1 = seeking new low (from high base)

    # Candidate pivot queue (one at a time)
    candidate_idx: Optional[int] = None
    candidate_price: Optional[float] = None
    candidate_type: Optional[str] = None

    # Confirmed + prev state
    confirmed_idx: int = -1
    confirmed_price: float = np.nan
    confirmed_type: str = ""
    prev_idx: int = -1
    prev_price: float = np.nan
    prev_type: str = ""

    for t in range(n):
        if np.isnan(atr[t]) or atr[t] <= 0:
            last_pivot_idx[t] = confirmed_idx
            last_pivot_price[t] = confirmed_price
            last_pivot_type[t] = confirmed_type
            prev_pivot_idx_arr[t] = prev_idx
            prev_pivot_price_arr[t] = prev_price
            prev_pivot_type_arr[t] = prev_type
            continue

        thresh_abs = params.zigzag_atr_mult * atr[t]

        # Promote candidate to confirmed after pivot_confirm_bars
        if candidate_idx is not None and (t - candidate_idx) >= params.pivot_confirm_bars:
            if confirmed_idx >= 0:
                prev_idx = confirmed_idx
                prev_price = confirmed_price
                prev_type = confirmed_type
            confirmed_idx = candidate_idx
            confirmed_price = candidate_price  # type: ignore[assignment]
            confirmed_type = candidate_type    # type: ignore[assignment]
            candidate_idx = None
            candidate_price = None
            candidate_type = None

        # Update running extremes
        if high[t] > run_ext_high:
            run_ext_high = high[t]
            if run_dir >= 0:
                run_ext_idx = t
        if low[t] < run_ext_low:
            run_ext_low = low[t]
            if run_dir <= 0:
                run_ext_idx = t

        # Detect reversal → enqueue candidate pivot
        if run_dir >= 0 and (run_ext_high - low[t]) >= thresh_abs and run_ext_high > 0:
            # Was tracking up-moves; a high pivot candidate forms
            candidate_idx = run_ext_idx
            candidate_price = run_ext_high
            candidate_type = "H"
            # Flip: now track for lower lows
            run_dir = -1
            run_ext_high = high[t]
            run_ext_low = low[t]
            run_ext_idx = t
        elif run_dir <= 0 and (high[t] - run_ext_low) >= thresh_abs and run_ext_low > 0:
            candidate_idx = run_ext_idx
            candidate_price = run_ext_low
            candidate_type = "L"
            run_dir = +1
            run_ext_high = high[t]
            run_ext_low = low[t]
            run_ext_idx = t

        last_pivot_idx[t] = confirmed_idx
        last_pivot_price[t] = confirmed_price
        last_pivot_type[t] = confirmed_type
        prev_pivot_idx_arr[t] = prev_idx
        prev_pivot_price_arr[t] = prev_price
        prev_pivot_type_arr[t] = prev_type

    out["last_pivot_idx"] = last_pivot_idx
    out["last_pivot_price"] = last_pivot_price
    out["last_pivot_type"] = last_pivot_type
    out["prev_pivot_idx"] = prev_pivot_idx_arr
    out["prev_pivot_price"] = prev_pivot_price_arr
    out["prev_pivot_type"] = prev_pivot_type_arr
    return out


def compute_fibs(df: pd.DataFrame, params: PhiParams) -> pd.DataFrame:
    """Compute Fibonacci retracements (0.382/0.500/0.618/0.786) and
    extensions (1.000/1.272/1.618/2.618) from the last two confirmed pivots.

    Direction:
      +1 = up-swing (prev=L, last=H). Retracements below H toward L.
                                       Extensions above H.
      -1 = down-swing (prev=H, last=L). Retracements above L toward H.
                                         Extensions below L.
       0 = insufficient or same-type pivots — all fib levels are NaN.
    """
    out = df.copy()
    last_p = out["last_pivot_price"].to_numpy()
    last_t = out["last_pivot_type"].to_numpy()
    prev_p = out["prev_pivot_price"].to_numpy()
    prev_t = out["prev_pivot_type"].to_numpy()
    n = len(out)

    retr = [0.382, 0.500, 0.618, 0.786]
    ext = [1.000, 1.272, 1.618, 2.618]
    direction = np.zeros(n, dtype=np.int8)
    fib_cols: dict[str, np.ndarray] = {}
    for r in retr:
        fib_cols[f"fib_{r:.3f}"] = np.full(n, np.nan)
    for e in ext:
        fib_cols[f"fib_{e:.3f}"] = np.full(n, np.nan)

    for t in range(n):
        lp, lt = last_p[t], last_t[t]
        pp, pt = prev_p[t], prev_t[t]
        if np.isnan(lp) or np.isnan(pp) or lt == "" or pt == "":
            continue
        if lt == "H" and pt == "L":
            direction[t] = +1
            rng = lp - pp
            base = lp
            for r in retr:
                fib_cols[f"fib_{r:.3f}"][t] = base - r * rng
            for e in ext:
                fib_cols[f"fib_{e:.3f}"][t] = base + (e - 1.0) * rng
        elif lt == "L" and pt == "H":
            direction[t] = -1
            rng = pp - lp
            base = lp
            for r in retr:
                fib_cols[f"fib_{r:.3f}"][t] = base + r * rng
            for e in ext:
                fib_cols[f"fib_{e:.3f}"][t] = base - (e - 1.0) * rng
        # else: same-type pivots → direction stays 0, fibs stay NaN

    for col, arr in fib_cols.items():
        out[col] = arr
    out["swing_direction"] = direction
    return out


# ════════════════════════════════════════════════════════════════════
# Multi-TF alignment
# ════════════════════════════════════════════════════════════════════

def _shift_htf_for_close(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Return HTF df with timestamps shifted forward by 1 period so that
    each row's 'time' represents the instant the bar CLOSED (rather than
    when it opened). This enables `merge_asof(direction='backward')` to
    pick the most-recently-CLOSED HTF bar for a given base timestamp."""
    period = pd.Timedelta(minutes=_TF_MINUTES.get(tf, 60))
    shifted = df.copy()
    shifted["time"] = shifted["time"] + period
    return shifted


def align_htfs_to_base(base: pd.DataFrame, htfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Merge HTF dataframes onto the base (5m) timeline using backward
    as-of join with a 1-period shift. No lookahead: only CLOSED HTF bars
    are visible.

    Each HTF value is suffixed with '_<tf>' in the output columns.
    `htfs` keys must be TF strings recognised by `_TF_MINUTES` in
    config.params (e.g. '1d', '4h', '1h', '15m')."""
    out = base.sort_values("time").reset_index(drop=True).copy()
    for tf, htf_df in htfs.items():
        if htf_df is None or len(htf_df) == 0:
            continue
        shifted = _shift_htf_for_close(htf_df, tf).sort_values("time").reset_index(drop=True)
        suffix = f"_{tf}"
        htf_cols = [c for c in shifted.columns if c != "time"]
        shifted_ren = shifted.rename(columns={c: c + suffix for c in htf_cols})
        out = pd.merge_asof(out, shifted_ren, on="time", direction="backward")
    return out


# ════════════════════════════════════════════════════════════════════
# Cluster detection (PHI_CLUSTER)
# ════════════════════════════════════════════════════════════════════

def detect_cluster(df: pd.DataFrame, params: PhiParams) -> pd.DataFrame:
    """Count TFs whose fib_0.618 is within cluster_atr_tolerance * ATR(5m)
    of close. If count >= cluster_min_confluences, set cluster_active.
    Direction is the sign of the sum of signed swing_direction values
    across contributing TFs (majority vote; ties = 0 = no-go).

    Assumes TF columns are suffixed: fib_0.618_{1d,4h,1h,15m}, with the
    5m (base) using unsuffixed fib_0.618 / swing_direction columns.
    """
    out = df.copy()
    n = len(out)
    tolerance = params.cluster_atr_tolerance * out["atr"]
    close = out["close"]

    tf_keys = ["1d", "4h", "1h", "15m"]
    fib_cols = [f"fib_0.618_{tf}" for tf in tf_keys] + ["fib_0.618"]
    dir_cols = [f"swing_direction_{tf}" for tf in tf_keys] + ["swing_direction"]

    confluences = np.zeros(n, dtype=np.int8)
    signed_sum = np.zeros(n, dtype=np.int32)

    for fc, dc in zip(fib_cols, dir_cols):
        if fc not in out.columns:
            continue
        fib_vals = out[fc]
        if dc in out.columns:
            dir_vals = out[dc].astype(np.int32).to_numpy()
        else:
            dir_vals = np.zeros(n, dtype=np.int32)
        within = (fib_vals.notna()) & ((close - fib_vals).abs() <= tolerance)
        within_arr = within.astype(np.int8).to_numpy()
        confluences = confluences + within_arr
        signed_sum = signed_sum + (within_arr.astype(np.int32) * dir_vals)

    out["cluster_confluences"] = confluences
    out["cluster_active"] = confluences >= params.cluster_min_confluences
    out["cluster_direction"] = np.sign(signed_sum).astype(np.int8)
    return out


# ════════════════════════════════════════════════════════════════════
# Regime gates + Golden Trigger
# ════════════════════════════════════════════════════════════════════

def check_regime_gates(df: pd.DataFrame, params: PhiParams) -> pd.DataFrame:
    """ADX > 23.6 AND BB_width > percentile_38.2(lookback 500) AND
    |close - EMA200|/ATR > 0.618. All three must pass for regime_ok=True."""
    out = df.copy()
    adx_ok = out["adx"] > params.adx_min
    bbw_p = out["bb_width"].rolling(params.bb_width_lookback, min_periods=50).quantile(
        params.bb_width_percentile / 100.0
    )
    bbw_ok = out["bb_width"] > bbw_p
    atr_safe = out["atr"].replace(0, np.nan)
    dist_ok = ((out["close"] - out["ema200"]).abs() / atr_safe) > params.ema200_distance_atr
    out["regime_ok"] = (adx_ok & bbw_ok & dist_ok).fillna(False)
    return out


def check_golden_trigger(df: pd.DataFrame, params: PhiParams) -> pd.DataFrame:
    """Wick >= 0.618 of range AND volume > MA20*1.272 AND
    (RSI<38.2 for long / RSI>61.8 for short)."""
    out = df.copy()
    wick_ok = out["wick_ratio"] >= params.wick_ratio_min
    vol_ok = out["volume"] > out["vol_ma20"] * params.volume_mult
    base = wick_ok & vol_ok
    out["trigger_long"] = (base & (out["rsi"] < params.rsi_long_max)).fillna(False)
    out["trigger_short"] = (base & (out["rsi"] > params.rsi_short_min)).fillna(False)
    return out


# ════════════════════════════════════════════════════════════════════
# CLI entry
# ════════════════════════════════════════════════════════════════════

def main() -> int:
    """Stub — implemented in Task 12."""
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
