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
    out["vol_ma20"] = out["vol"].rolling(20).mean()
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
    # Normalise to ms resolution to avoid dtype mismatch between cached (ms) and
    # freshly computed (us) timestamps when pandas merge_asof enforces dtype equality.
    out["time"] = out["time"].astype("datetime64[ms]")
    for tf, htf_df in htfs.items():
        if htf_df is None or len(htf_df) == 0:
            continue
        shifted = _shift_htf_for_close(htf_df, tf).sort_values("time").reset_index(drop=True)
        shifted["time"] = shifted["time"].astype("datetime64[ms]")
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
            # fillna(0) before astype to handle NaN rows from merge_asof (no matching HTF bar)
            dir_vals = out[dc].fillna(0).astype(np.int32).to_numpy()
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
    vol_ok = out["vol"] > out["vol_ma20"] * params.volume_mult
    base = wick_ok & vol_ok
    out["trigger_long"] = (base & (out["rsi"] < params.rsi_long_max)).fillna(False)
    out["trigger_short"] = (base & (out["rsi"] > params.rsi_short_min)).fillna(False)
    return out


# ════════════════════════════════════════════════════════════════════
# Scoring (Phi_Score + Ω_PHI) and sizing (Golden Convex)
# ════════════════════════════════════════════════════════════════════

def compute_scoring(df: pd.DataFrame, params: PhiParams) -> pd.DataFrame:
    """Compute Phi_Score and Ω_PHI per spec.

    Requires input columns:
      cluster_confluences, wick_ratio,
      ema200_slope_1d, ema200_slope_4h,
      volume, vol_ma20, regime_ok
    """
    out = df.copy()
    confluences = out["cluster_confluences"].astype(float)
    rejection = out["wick_ratio"].astype(float).clip(0, 1)

    s1 = out["ema200_slope_1d"].fillna(0)
    s2 = out["ema200_slope_4h"].fillna(0)
    tol = 1e-6
    same_sign = ((s1 > tol) & (s2 > tol)) | ((s1 < -tol) & (s2 < -tol))
    opposite = ((s1 > tol) & (s2 < -tol)) | ((s1 < -tol) & (s2 > tol))
    trend_align = pd.Series(0.5, index=out.index)
    trend_align.loc[same_sign] = 1.0
    trend_align.loc[opposite] = 0.0

    out["trend_alignment"] = trend_align
    out["phi_score"] = (confluences / 5.0) * rejection * trend_align

    volume_ok = (out["vol"] > out["vol_ma20"] * params.volume_mult).astype(float)
    regime_ok = out["regime_ok"].astype(float)

    out["omega_phi"] = (
        params.w_phi_score * out["phi_score"]
        + params.w_rejection * rejection
        + params.w_volume * volume_ok
        + params.w_trend * trend_align
        + params.w_regime * regime_ok
    )
    return out


def phi_size(equity: float, entry: float, sl: float,
             phi_score: float, params: PhiParams) -> dict:
    """Golden Convex sizing.

    risk_usd = equity * risk_per_trade * phi_score²
    size_units = risk_usd / |entry - sl|
    notional capped at equity * notional_cap (recompute size if breached).
    """
    phi_score = max(0.0, min(1.0, float(phi_score)))
    risk_usd = equity * params.risk_per_trade * (phi_score ** 2)
    stop_dist = abs(entry - sl)
    if stop_dist <= 0 or entry <= 0:
        return {"size_units": 0.0, "notional": 0.0, "risk_usd": 0.0}
    size_units = risk_usd / stop_dist
    notional = size_units * entry
    cap_notional = equity * params.notional_cap
    if notional > cap_notional:
        size_units = cap_notional / entry
        notional = cap_notional
    return {
        "size_units": float(size_units),
        "notional": float(notional),
        "risk_usd": float(risk_usd),
    }


# ════════════════════════════════════════════════════════════════════
# Trade lifecycle — levels, trailing, exit, PnL
# ════════════════════════════════════════════════════════════════════

def calc_phi_levels(row, direction: int, params: PhiParams) -> dict:
    """Compute SL/TP1/TP2/TP3 from Ω3 (1h) Fib levels + ATR buffer.

    SL = fib_0.786_1h ± sl_atr_buffer * atr_1h (below for long, above for short)
    TP1 = fib_1.272_1h (partial exit 38.2%)
    TP2 = fib_1.618_1h (partial exit 38.2%)
    TP3 = fib_2.618_1h (runner 23.6% + trailing)

    `row` can be a dict-like or a pandas Series. Must contain:
      fib_0.786_1h, fib_1.272_1h, fib_1.618_1h, fib_2.618_1h, atr_1h
    """
    sl_base = float(row["fib_0.786_1h"])
    atr_1h = float(row["atr_1h"])
    if direction == +1:
        sl = sl_base - params.sl_atr_buffer * atr_1h
    else:
        sl = sl_base + params.sl_atr_buffer * atr_1h
    return {
        "sl": float(sl),
        "tp1": float(row["fib_1.272_1h"]),
        "tp2": float(row["fib_1.618_1h"]),
        "tp3": float(row["fib_2.618_1h"]),
    }


def update_phi_trailing(trade: dict, new_trail_price: float) -> None:
    """Update trailing SL monotonically in favor of the trade.
    Never loosens (never retreats against position)."""
    cur = trade.get("trailing_sl", trade["sl"])
    if trade["direction"] == +1:
        trade["trailing_sl"] = max(cur, float(new_trail_price))
    else:
        trade["trailing_sl"] = min(cur, float(new_trail_price))


def _resolve_phi_exit(df: pd.DataFrame, t: int, trade: dict,
                      params: PhiParams) -> Optional[tuple[str, float]]:
    """Return (reason, exit_price) if any exit triggers at bar t, else None.

    Priority (per bar):
      1. SL / trailing stop (worst case first)
      2. Staged TP1, TP2 (partials)
      3. TP3 (closes runner)
      4. Time stop
    """
    high = float(df["high"].iloc[t])
    low = float(df["low"].iloc[t])
    close = float(df["close"].iloc[t])
    d = trade["direction"]

    stop = trade.get("trailing_sl", trade["sl"])
    if d == +1 and low <= stop:
        return "sl", stop
    if d == -1 and high >= stop:
        return "sl", stop

    stage = trade.get("stage", 0)
    if stage < 1:
        tp = trade["tp1"]
        if (d == +1 and high >= tp) or (d == -1 and low <= tp):
            return "tp1_partial", tp
    if stage < 2:
        tp = trade["tp2"]
        if (d == +1 and high >= tp) or (d == -1 and low <= tp):
            return "tp2_partial", tp
    tp = trade["tp3"]
    if (d == +1 and high >= tp) or (d == -1 and low <= tp):
        return "tp3", tp

    if (t - trade["entry_idx"]) >= params.max_bars_in_trade:
        return "time_stop", close
    return None


def _pnl_with_costs(direction: int, entry: float, exit_p: float, size: float,
                    duration: int, funding_periods_per_8h: float) -> float:
    """Cost model mirroring GRAHAM/KEPOS: slippage+spread on exit,
    commission on both legs, funding over duration. Returns PnL in USD."""
    slip_exit = SLIPPAGE + SPREAD
    if direction == +1:
        entry_cost = entry * (1 + COMMISSION)
        exit_net = exit_p * (1 - COMMISSION - slip_exit)
        funding = -(size * entry * FUNDING_PER_8H * duration / funding_periods_per_8h)
        pnl = size * (exit_net - entry_cost) + funding
    else:
        entry_cost = entry * (1 - COMMISSION)
        exit_net = exit_p * (1 + COMMISSION + slip_exit)
        funding = +(size * entry * FUNDING_PER_8H * duration / funding_periods_per_8h)
        pnl = size * (entry_cost - exit_net) + funding
    return float(pnl * LEVERAGE)


# ════════════════════════════════════════════════════════════════════
# Kill-switch
# ════════════════════════════════════════════════════════════════════

class KillSwitchState:
    """Track daily/weekly equity highs and block new entries when drawdown
    from the respective high exceeds kill_daily / kill_weekly. Does NOT
    force-close open positions — spec §11 explicitly states open trades
    follow natural management."""

    def __init__(self, params: PhiParams):
        self.params = params
        self.day_high: float = 0.0
        self.week_high: float = 0.0
        self.day_key: Optional[pd.Timestamp] = None
        self.week_key: Optional[pd.Timestamp] = None
        self.daily_blocked: bool = False
        self.weekly_blocked: bool = False

    def on_equity(self, ts: pd.Timestamp, equity: float) -> None:
        day = ts.normalize()
        week = (ts - pd.Timedelta(days=ts.weekday())).normalize()
        if self.day_key != day:
            self.day_key = day
            self.day_high = equity
            self.daily_blocked = False
        if self.week_key != week:
            self.week_key = week
            self.week_high = equity
            self.weekly_blocked = False
        self.day_high = max(self.day_high, equity)
        self.week_high = max(self.week_high, equity)
        day_dd = (self.day_high - equity) / self.day_high if self.day_high > 0 else 0.0
        week_dd = (self.week_high - equity) / self.week_high if self.week_high > 0 else 0.0
        if day_dd >= self.params.kill_daily:
            self.daily_blocked = True
        if week_dd >= self.params.kill_weekly:
            self.weekly_blocked = True

    @property
    def blocked(self) -> bool:
        return self.daily_blocked or self.weekly_blocked


# ════════════════════════════════════════════════════════════════════
# Symbol scan loop
# ════════════════════════════════════════════════════════════════════

def scan_symbol(df: pd.DataFrame, symbol: str,
                params: Optional[PhiParams] = None,
                initial_equity: float = ACCOUNT_SIZE) -> tuple[list, dict]:
    """Run the PHI scan on a fully-prepared merged dataframe for one symbol.

    The df must already have features, zigzag, fibs (per-TF merged with
    _1d/_4h/_1h/_15m suffixes), cluster, regime, trigger, and scoring
    columns applied. See `prepare_symbol_frames` (Task 11) for the full
    assembly pipeline.

    Returns (trades list, vetos counter dict).
    """
    params = params or PhiParams()
    trades: list[dict] = []
    vetos: dict[str, int] = defaultdict(int)

    if len(df) < 300:
        return [], {"too_few_bars": 1}

    account = float(initial_equity)
    kill = KillSwitchState(params)
    n = len(df)
    funding_periods_per_8h = 8 * 60 / _TF_MINUTES.get(params.tf_omega5, 5)
    open_trade: Optional[dict] = None
    cluster_armed_until: int = -1

    for t in range(200, n - 1):
        row = df.iloc[t]
        ts = row["time"]
        kill.on_equity(ts, account)

        # ── Manage open trade ────────────────────────────────────
        if open_trade is not None:
            # After TP2, update trailing using new fib_0.618 of base TF
            if open_trade.get("stage", 0) >= 2:
                trail_px = row.get("fib_0.618", np.nan)
                if trail_px is not None and not (isinstance(trail_px, float) and np.isnan(trail_px)):
                    update_phi_trailing(open_trade, float(trail_px))

            resolved = _resolve_phi_exit(df, t, open_trade, params)
            if resolved is not None:
                reason, exit_px = resolved
                if reason in ("tp1_partial", "tp2_partial"):
                    frac = params.tp1_partial if reason == "tp1_partial" else params.tp2_partial
                    sz = open_trade["size"] * frac
                    pnl = _pnl_with_costs(
                        open_trade["direction"], open_trade["entry"], exit_px,
                        sz, t - open_trade["entry_idx"], funding_periods_per_8h,
                    )
                    account = max(account + pnl, 0.0)
                    open_trade["size"] -= sz
                    open_trade["stage"] = open_trade.get("stage", 0) + 1
                    open_trade.setdefault("partials", []).append({
                        "reason": reason, "price": round(exit_px, 6),
                        "size": sz, "pnl": pnl, "idx": t,
                    })
                else:  # sl / tp3 / time_stop → close remainder
                    duration = t - open_trade["entry_idx"]
                    pnl = _pnl_with_costs(
                        open_trade["direction"], open_trade["entry"], exit_px,
                        open_trade["size"], duration, funding_periods_per_8h,
                    )
                    account = max(account + pnl, 0.0)
                    open_trade.update({
                        "exit_idx": t,
                        "exit_time": ts,
                        "exit_price": round(exit_px, 6),
                        "exit_reason": reason,
                        "pnl": float(pnl),
                        "duration_bars": duration,
                        "account_after": float(account),
                    })
                    trades.append(open_trade)
                    open_trade = None
            continue

        # ── Look for new entry ───────────────────────────────────
        if kill.blocked:
            vetos["kill_switch"] += 1
            continue

        if bool(row.get("cluster_active", False)):
            cluster_armed_until = t + params.cluster_window_bars

        if t > cluster_armed_until:
            continue

        direction = int(row.get("cluster_direction", 0))
        if direction == 0:
            vetos["no_direction"] += 1
            continue

        if not bool(row.get("regime_ok", False)):
            vetos["regime_block"] += 1
            continue

        # Macro filter: 1d slope sign
        macro_slope = row.get("ema200_slope_1d", 0)
        if isinstance(macro_slope, float) and np.isnan(macro_slope):
            macro_slope = 0
        macro = int(np.sign(macro_slope or 0))
        if macro == +1 and direction == -1:
            vetos["macro_mismatch"] += 1
            continue
        if macro == -1 and direction == +1:
            vetos["macro_mismatch"] += 1
            continue

        omega = float(row.get("omega_phi", 0.0))
        if omega < params.omega_phi_entry:
            vetos["omega_low"] += 1
            continue

        trig_long = bool(row.get("trigger_long", False))
        trig_short = bool(row.get("trigger_short", False))
        if direction == +1 and not trig_long:
            vetos["no_trigger"] += 1
            continue
        if direction == -1 and not trig_short:
            vetos["no_trigger"] += 1
            continue

        size_scale = 1.0 if macro != 0 else params.range_size_scale

        entry = float(df["open"].iloc[t + 1])
        fib_786 = row.get("fib_0.786_1h", np.nan)
        fib_1272 = row.get("fib_1.272_1h", np.nan)
        fib_1618 = row.get("fib_1.618_1h", np.nan)
        fib_2618 = row.get("fib_2.618_1h", np.nan)
        atr_1h = row.get("atr_1h", row.get("atr", np.nan))
        any_nan = any(
            isinstance(v, float) and np.isnan(v)
            for v in (fib_786, fib_1272, fib_1618, fib_2618, atr_1h)
        )
        if any_nan:
            vetos["nan_levels"] += 1
            continue

        levels = calc_phi_levels({
            "close": float(row["close"]),
            "fib_0.786_1h": float(fib_786),
            "fib_1.272_1h": float(fib_1272),
            "fib_1.618_1h": float(fib_1618),
            "fib_2.618_1h": float(fib_2618),
            "atr_1h": float(atr_1h),
        }, direction, params)

        phi_score = float(row.get("phi_score", 0.0))
        sz = phi_size(account, entry, levels["sl"], phi_score, params)
        if sz["size_units"] <= 0:
            vetos["zero_size"] += 1
            continue

        open_trade = {
            "symbol": symbol,
            "direction": direction,
            "entry_idx": t + 1,
            "entry_time": df["time"].iloc[t + 1],
            "entry": round(entry, 6),
            "sl": round(levels["sl"], 6),
            "trailing_sl": round(levels["sl"], 6),
            "tp1": round(levels["tp1"], 6),
            "tp2": round(levels["tp2"], 6),
            "tp3": round(levels["tp3"], 6),
            "size": sz["size_units"] * size_scale,
            "notional": sz["notional"] * size_scale,
            "phi_score": phi_score,
            "omega_phi": omega,
            "stage": 0,
            "partials": [],
        }

    return trades, dict(vetos)


# ════════════════════════════════════════════════════════════════════
# Multi-symbol orchestration + summary + persistence
# ════════════════════════════════════════════════════════════════════

def prepare_symbol_frames(symbol: str, params: PhiParams) -> Optional[pd.DataFrame]:
    """Fetch all 5 TFs, compute features+zigzag+fibs per TF, merge HTFs
    onto the 5m base, and run cluster/regime/trigger/scoring.
    Returns the fully-prepared base df, or None on data failure."""
    tfs = [params.tf_omega5, params.tf_omega4, params.tf_omega3,
           params.tf_omega2, params.tf_omega1]
    n_candles_map = {
        params.tf_omega1: 800,
        params.tf_omega2: 4_000,
        params.tf_omega3: 16_000,
        params.tf_omega4: 70_000,
        params.tf_omega5: params.n_candles_5m,
    }
    frames: dict[str, pd.DataFrame] = {}
    for tf in tfs:
        got = fetch_all([symbol], interval=tf, n_candles=n_candles_map[tf], futures=True)
        df = got.get(symbol)
        if df is None or len(df) < 300:
            log.warning("%s: insufficient data on %s (have=%s)",
                        symbol, tf, 0 if df is None else len(df))
            return None
        df = compute_features(df, params)
        df = compute_zigzag(df, params)
        df = compute_fibs(df, params)
        frames[tf] = df
    base = frames[params.tf_omega5]
    htfs = {
        params.tf_omega1: frames[params.tf_omega1],
        params.tf_omega2: frames[params.tf_omega2],
        params.tf_omega3: frames[params.tf_omega3],
        params.tf_omega4: frames[params.tf_omega4],
    }
    merged = align_htfs_to_base(base, htfs)
    merged = detect_cluster(merged, params)
    merged = check_regime_gates(merged, params)
    merged = check_golden_trigger(merged, params)
    merged = compute_scoring(merged, params)
    return merged


def run_backtest(symbols: list[str], params: Optional[PhiParams] = None,
                 initial_equity: float = ACCOUNT_SIZE) -> tuple[list[dict], dict, dict]:
    """Run PHI across symbols. Returns (trades, summary, per_symbol)."""
    params = params or PhiParams()
    all_trades: list[dict] = []
    all_vetos: dict[str, int] = defaultdict(int)
    per_symbol: dict[str, dict] = {}
    sym_trades_map: dict[str, list[dict]] = {}
    sym_vetos_map: dict[str, dict] = {}
    for sym in symbols:
        log.info("Preparing %s ...", sym)
        merged = prepare_symbol_frames(sym, params)
        if merged is None:
            continue
        trades, vetos = scan_symbol(merged, sym, params, initial_equity)
        all_trades.extend(trades)
        sym_trades_map[sym] = trades
        sym_vetos_map[sym] = vetos
        for k, v in vetos.items():
            all_vetos[k] += v
        log.info("%s: %d trades", sym, len(trades))
    summary = compute_summary(all_trades, initial_equity)
    all_vetos_dict = dict(all_vetos)
    summary["vetos"] = all_vetos_dict
    # Build per-symbol breakdown
    for sym in sym_trades_map:
        sym_sum = compute_summary(sym_trades_map[sym], initial_equity)
        sym_sum["vetos"] = sym_vetos_map[sym]
        per_symbol[sym] = sym_sum
    return all_trades, summary, per_symbol


def compute_summary(trades: list[dict], initial_equity: float = ACCOUNT_SIZE) -> dict:
    """Sharpe, Sortino, Profit Factor, Win Rate, Max Drawdown, Expectancy (R)."""
    if not trades:
        return {
            "total_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "sharpe": 0.0, "sortino": 0.0, "max_drawdown": 0.0,
            "expectancy_r": 0.0,
            "final_equity": float(initial_equity), "total_pnl": 0.0,
        }
    pnls = np.array([t["pnl"] for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    equity = initial_equity + np.cumsum(pnls)
    peaks = np.maximum.accumulate(equity)
    dd = (peaks - equity) / np.where(peaks > 0, peaks, 1.0)

    ret_series = pnls / initial_equity
    std_r = float(np.std(ret_series))
    sharpe = (float(np.mean(ret_series)) / std_r * np.sqrt(len(ret_series))) if std_r > 0 else 0.0
    downside = ret_series[ret_series < 0]
    std_d = float(np.std(downside)) if len(downside) > 0 else 0.0
    sortino = (float(np.mean(ret_series)) / std_d * np.sqrt(len(ret_series))) if std_d > 0 else 0.0

    if len(losses) > 0 and losses.sum() < 0:
        pf = float(wins.sum() / -losses.sum())
    elif len(wins) > 0:
        pf = float("inf")
    else:
        pf = 0.0

    r_values = []
    for t in trades:
        risk = abs(t.get("entry", 0) - t.get("sl", 0)) * t.get("size", 0)
        if risk > 0:
            r_values.append(t["pnl"] / risk)
    expectancy_r = float(np.mean(r_values)) if r_values else 0.0

    return {
        "total_trades": len(trades),
        "win_rate": float(len(wins) / len(trades)),
        "profit_factor": pf,
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "max_drawdown": float(dd.max()),
        "expectancy_r": expectancy_r,
        "final_equity": float(equity[-1]),
        "total_pnl": float(pnls.sum()),
    }


def _trades_to_serializable(trades: list[dict]) -> list[dict]:
    """Convert pd.Timestamp / numpy scalars to JSON-safe primitives.
    Preserves schema compatibility with overfit_audit (fix 1ff8b18)."""
    out = []
    for t in trades:
        o = dict(t)
        for k, v in list(o.items()):
            if isinstance(v, pd.Timestamp):
                o[k] = v.isoformat()
            elif isinstance(v, np.integer):
                o[k] = int(v)
            elif isinstance(v, np.floating):
                o[k] = float(v)
            elif isinstance(v, list):
                # Serialize list of dicts (e.g. partials)
                new_list = []
                for item in v:
                    if isinstance(item, dict):
                        new_item = dict(item)
                        for ik, iv in list(new_item.items()):
                            if isinstance(iv, pd.Timestamp):
                                new_item[ik] = iv.isoformat()
                            elif isinstance(iv, np.integer):
                                new_item[ik] = int(iv)
                            elif isinstance(iv, np.floating):
                                new_item[ik] = float(iv)
                        new_list.append(new_item)
                    else:
                        new_list.append(item)
                o[k] = new_list
        out.append(o)
    return out


def save_run(run_dir: Path, trades: list[dict], summary: dict,
             params: PhiParams, vetos: dict, per_sym: dict,
             meta: dict) -> None:
    """Write trades.json, summary.json (GRAHAM-envelope), config.json atomically."""
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(run_dir / "trades.json",
                 json.dumps(_trades_to_serializable(trades),
                            separators=(",", ":"), default=str))
    payload = {
        "engine": "PHI",
        "version": "0.1.0",
        "run_id": meta.get("run_id"),
        "timestamp": datetime.now().isoformat(),
        "params": asdict(params),
        "summary": summary,
        "per_symbol": per_sym,
        "vetos": vetos,
        "meta": meta,
    }
    atomic_write(run_dir / "summary.json",
                 json.dumps(payload, indent=2, default=str))
    atomic_write(run_dir / "config.json",
                 json.dumps(asdict(params), indent=2))


def _setup_logging(run_dir: Path) -> None:
    fh = logging.FileHandler(run_dir / "log.txt", encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s - %(message)s"
    ))
    logging.getLogger().addHandler(fh)
    logging.getLogger().setLevel(logging.INFO)


# ════════════════════════════════════════════════════════════════════
# CLI entry
# ════════════════════════════════════════════════════════════════════

def _print_summary(summary: dict) -> None:
    print(f"\n  PHI — AURUM Finance Fibonacci Fractal Engine")
    print(f"  {'='*60}")
    print(f"  Total trades       : {summary['total_trades']}")
    print(f"  Win rate           : {summary['win_rate']*100:.2f}%")
    pf = summary['profit_factor']
    pf_str = "inf" if pf == float("inf") else f"{pf:.3f}"
    print(f"  Profit factor      : {pf_str}")
    print(f"  Sharpe             : {summary['sharpe']:.3f}")
    print(f"  Sortino            : {summary['sortino']:.3f}")
    print(f"  Max drawdown       : {summary['max_drawdown']*100:.2f}%")
    print(f"  Expectancy (R)     : {summary['expectancy_r']:.3f}")
    print(f"  Final equity       : ${summary['final_equity']:,.2f}")
    print(f"  Total PnL          : ${summary['total_pnl']:,.2f}")
    vetos = summary.get("vetos", {})
    if vetos:
        print(f"\n  Vetos:")
        for k, v in sorted(vetos.items(), key=lambda x: -x[1]):
            print(f"    {k:20s} {v:>8d}")


def main() -> int:
    ap = argparse.ArgumentParser(description="PHI — AURUM Fibonacci Fractal Engine")
    ap.add_argument("--symbols", default=None,
                    help="Comma-separated list (default: SYMBOLS from config.params)")
    ap.add_argument("--out", default="data/phi",
                    help="Output base dir (default: data/phi)")
    ap.add_argument("--threshold-cluster", type=int, default=None,
                    help="Minimum TF confluences (default: 3)")
    ap.add_argument("--omega-entry", type=float, default=None,
                    help="Ω_PHI entry threshold (default: 0.618)")
    ap.add_argument("--no-kill-switch", action="store_true")
    args = ap.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else list(SYMBOLS)
    params = PhiParams()
    if args.threshold_cluster is not None:
        params.cluster_min_confluences = args.threshold_cluster
    if args.omega_entry is not None:
        params.omega_phi_entry = args.omega_entry
    if args.no_kill_switch:
        params.kill_daily = 1.0
        params.kill_weekly = 1.0

    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    run_dir = Path(args.out) / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s - %(message)s"
    )
    _setup_logging(run_dir)
    log.info("PHI run starting: symbols=%s run_dir=%s", symbols, run_dir)

    meta = {
        "run_id": ts,
        "symbols": symbols,
        "initial_equity": float(ACCOUNT_SIZE),
        "cli_args": vars(args),
    }
    trades, summary, per_sym = run_backtest(symbols, params, ACCOUNT_SIZE)
    vetos = summary.pop("vetos", {})
    save_run(run_dir, trades, summary, params, vetos, per_sym, meta)
    _print_summary({**summary, "vetos": vetos})
    print(f"\n  Run saved to: {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
