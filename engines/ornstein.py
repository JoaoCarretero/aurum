"""
ORNSTEIN — AURUM Finance Mean-Reversion Engine
===============================================
Leonard Ornstein tribute (Ornstein-Uhlenbeck process co-author).

Thesis
------
*"Quanto mais a mola estica, mais forte volta — mas só se ela ainda for mola."*

Trade mean-reversion setups **only** when the price deviation series passes
a statistical battery confirming it is in a mean-reverting regime:

  1. Rolling Ornstein-Uhlenbeck fit (AR(1) on deviation) with half-life
     inside a sane band (5–50 bars of the execution TF).
  2. Hurst exponent H < 0.5 on deviation (anti-persistent).
  3. ADF p-value < 0.05 on deviation (stationarity).
  4. Variance Ratio (Lo-MacKinlay) < 1 on majority of lags.
  5. Bollinger %B extreme on deviation (secondary confirmation).

Plus a **fractal divergence filter** across 5 timeframes (consensus on
direction vs SMA20/EMA50/EMA200/VWAP/HMA21) and an ATR regime guard
(block on extreme vol, boost on calm vol).

Discipline
----------
- All features computed locally. No `core.indicators` mutation (protected).
- AURUM cost model (C1+C2) from `config.params`.
- Local sizing (convex, phi-scaled, 1% risk, 2% notional cap).
- NOT in FROZEN_ENGINES / OPERATIONAL_ENGINES until overfit_audit 6/6 passes.
- Every trade logs each Ω subscore separately for auditability.
- Ablation suite: run-time flag masks components to isolate marginal value.
- Zero lookahead: HTF features are forward-filled only after bar close.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
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
from core.ops.fs import atomic_write
from analysis.stats import calc_ratios, equity_stats

log = logging.getLogger("ORNSTEIN")
_tl = logging.getLogger("ORNSTEIN.trades")

TRAIN_END = "2025-10-21"
TEST_END = "2026-01-19"
HOLDOUT_END = "2026-04-21"
VALIDATION_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")


# ════════════════════════════════════════════════════════════════════
# Parameters
# ════════════════════════════════════════════════════════════════════

@dataclass
class OrnsteinParams:
    # Timeframes — execution + 4 HTFs for divergence consensus
    tf_exec: str = "15m"
    tf_htfs: tuple = ("5m", "1h", "4h", "1d")

    # Moving averages (on price)
    sma_fast: int = 20
    ema_medium: int = 50
    ema_slow: int = 200
    hma_period: int = 21

    # RSI
    rsi_period: int = 14
    rsi_long_max: float = 30.0         # exec TF hard long threshold
    rsi_short_min: float = 70.0        # exec TF hard short threshold
    rsi_htf_long_max: float = 40.0     # soft HTF threshold
    rsi_htf_short_min: float = 60.0
    rsi_htf_min_confirm: int = 2       # HTFs required to confirm

    # ATR regime filter (on exec TF)
    atr_period: int = 14
    atr_percentile_window: int = 500
    atr_percentile_block: float = 90.0   # above -> block entry
    atr_percentile_boost: float = 30.0   # below -> boost omega
    atr_boost_factor: float = 0.05       # +5% on omega when calm

    # Statistical battery windows (rolling on deviation series)
    stat_window: int = 200
    halflife_min: float = 5.0
    halflife_max: float = 50.0
    hurst_threshold: float = 0.45
    adf_pvalue_max: float = 0.05
    vr_lags: tuple = (2, 4, 8)
    vr_min_below_one: int = 2  # majority of lags must be below 1

    # Bollinger on deviation series
    bb_window: int = 20
    bb_k: float = 2.0

    # Ω score weights (sum to 1.0 without ATR boost; ATR boost is additive)
    w_divergence: float = 0.30
    w_rsi: float = 0.15
    w_ou: float = 0.20
    w_hurst: float = 0.10
    w_adf: float = 0.10
    w_vr: float = 0.05
    w_bb: float = 0.05
    # Remaining 5% cushion absorbs floats/rounding; ATR boost is ±0.05 outside.

    omega_entry: float = 75.0   # score threshold for entry, 0-100

    # Sizing (convex scaling by Ω strength)
    risk_per_trade: float = 0.01
    notional_cap: float = 0.02
    size_mult_cap: float = 1.5

    # Exit controls
    partial_take_frac: float = 0.50
    stop_deviation_sigma: float = 4.0
    stop_extra_atr_expansion: float = 1.5
    time_stop_halflife_mult: float = 2.0
    time_stop_floor: int = 12
    time_stop_ceiling: int = 200

    # Kill-switch (% drawdown from equity high)
    kill_daily: float = 0.02618
    kill_weekly: float = 0.0618

    # Data budget
    n_candles_exec: int = 60_000
    max_bars_in_trade: int = 288

    # Multi-TF consensus requirements (per spec):
    # - Exec TF: 4/5 medias must agree (hard).
    # - Each HTF: 3/5 medias (soft) to count as "HTF in consensus".
    # - Then `htfs_min_consensus` of the 4 HTFs must agree directionally.
    exec_tf_min_medias: int = 4
    htf_tf_min_medias: int = 3   # softer bar for each individual HTF
    htfs_min_consensus: int = 3

    # Ablation: set one of these to True to disable that component
    disable_divergence: bool = False
    disable_rsi: bool = False
    disable_ou: bool = False
    disable_hurst: bool = False
    disable_adf: bool = False
    disable_vr: bool = False
    disable_bb: bool = False
    disable_atr_boost: bool = False
    disable_multi_tf: bool = False  # rolls up to disable_divergence + HTF rsi


ORNSTEIN_PRESETS: dict[str, dict] = {
    "default": {},
    "relaxed": {
        "omega_entry": 70.0,
        "hurst_threshold": 0.50,
        "adf_pvalue_max": 0.10,
    },
    "strict": {
        "omega_entry": 85.0,
        "hurst_threshold": 0.40,
        "adf_pvalue_max": 0.01,
        "halflife_max": 30.0,
    },
    # Exploratory: designed for the FIRST battery run when we do not yet
    # know which regimes this engine fires in. Thresholds are intentionally
    # loose — treat any trade count here as a search result, not a signal
    # of edge. Tighten back to default/strict once regime is located.
    #
    # Hurst is disabled here: crypto 15m shows H ~ 0.8-1.0 (short-horizon
    # trending micro-structure) regardless of whether macro is ranging.
    # The spec's "H<0.45 = anti-persistent MR" threshold comes from econ
    # research on daily/weekly data. Re-introduce only after validating
    # the H estimator against a regime where MR is ground-truth-known.
    "exploratory": {
        "omega_entry": 50.0,
        "hurst_threshold": 1.01,        # effectively OFF
        "disable_hurst": True,           # skip the gate entirely
        "adf_pvalue_max": 0.20,
        "halflife_max": 80.0,
        "rsi_long_max": 40.0,
        "rsi_short_min": 60.0,
        "rsi_htf_long_max": 50.0,
        "rsi_htf_short_min": 50.0,
        "rsi_htf_min_confirm": 1,
        "exec_tf_min_medias": 3,
        "htf_tf_min_medias": 2,
        "htfs_min_consensus": 2,
    },
    "tf_1h": {
        "tf_exec": "1h",
        "tf_htfs": ("15m", "4h", "1d", "1w"),
    },
    "tf_5m": {
        "tf_exec": "5m",
        "tf_htfs": ("15m", "1h", "4h", "1d"),
        "max_bars_in_trade": 576,
    },
}


# Ablation variants exposed via --ablation <name>.
ABLATION_VARIANTS: dict[str, dict] = {
    "none": {},
    "no_ou":         {"disable_ou": True},
    "no_hurst":      {"disable_hurst": True},
    "no_adf":        {"disable_adf": True},
    "no_vr":         {"disable_vr": True},
    "no_bb":         {"disable_bb": True},
    "no_rsi":        {"disable_rsi": True},
    "no_divergence": {"disable_divergence": True},
    "no_multi_tf":   {"disable_multi_tf": True},
    "no_atr_boost":  {"disable_atr_boost": True},
}


# ════════════════════════════════════════════════════════════════════
# Local feature computation (prices + MAs + BB + ATR + RSI)
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
    return (100 - (100 / (1 + rs))).fillna(50.0)


def _hma(close: pd.Series, length: int = 21) -> pd.Series:
    """Hull Moving Average — reduced lag weighted average."""
    half = max(1, length // 2)
    sqrt_len = max(1, int(round(math.sqrt(length))))
    w_half = close.rolling(half).apply(
        lambda s: np.dot(s, np.arange(1, len(s) + 1)) / np.arange(1, len(s) + 1).sum(),
        raw=True,
    )
    w_full = close.rolling(length).apply(
        lambda s: np.dot(s, np.arange(1, len(s) + 1)) / np.arange(1, len(s) + 1).sum(),
        raw=True,
    )
    return (2 * w_half - w_full).rolling(sqrt_len).apply(
        lambda s: np.dot(s, np.arange(1, len(s) + 1)) / np.arange(1, len(s) + 1).sum(),
        raw=True,
    )


def _vwap_session(df: pd.DataFrame) -> pd.Series:
    """Session VWAP reset daily (UTC). Uses typical price × volume."""
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    dayk = pd.to_datetime(df["time"]).dt.normalize()
    pv = typical * df["vol"]
    cum_pv = pv.groupby(dayk).cumsum()
    cum_v = df["vol"].groupby(dayk).cumsum().replace(0, np.nan)
    return (cum_pv / cum_v).ffill()


def _bollinger(series: pd.Series, length: int, k: float):
    mid = series.rolling(length).mean()
    sd = series.rolling(length).std(ddof=0)
    upper = mid + k * sd
    lower = mid - k * sd
    width = (upper - lower) / mid.replace(0, np.nan)
    # %B
    pct_b = (series - lower) / (upper - lower).replace(0, np.nan)
    return mid, upper, lower, width, pct_b


def compute_features(df: pd.DataFrame, params: OrnsteinParams) -> pd.DataFrame:
    """Add local indicators to df. No lookahead. Operates on price bars only."""
    out = df.copy()
    out["atr"] = _atr(out, params.atr_period)
    out["rsi"] = _rsi(out["close"], params.rsi_period)
    out["sma_fast"] = out["close"].rolling(params.sma_fast).mean()
    out["ema_medium"] = out["close"].ewm(span=params.ema_medium, adjust=False).mean()
    out["ema_slow"] = out["close"].ewm(span=params.ema_slow, adjust=False).mean()
    out["hma"] = _hma(out["close"], params.hma_period)
    out["vwap"] = _vwap_session(out)

    # Deviation series — central to all stat tests.
    atr_safe = out["atr"].replace(0, np.nan)
    out["deviation"] = (out["close"] - out["ema_medium"]) / atr_safe

    # Bollinger on deviation (Ornstein spec: test on residual, not price)
    bb_mid, bb_up, bb_lo, bb_w, bb_pct = _bollinger(
        out["deviation"], params.bb_window, params.bb_k
    )
    out["bb_mid"] = bb_mid
    out["bb_upper"] = bb_up
    out["bb_lower"] = bb_lo
    out["bb_width"] = bb_w
    out["bb_pct_b"] = bb_pct

    # ATR regime percentile (0-100) rolling
    out["atr_percentile"] = (
        out["atr"]
        .rolling(params.atr_percentile_window, min_periods=50)
        .rank(pct=True)
        * 100.0
    )

    return out


# ════════════════════════════════════════════════════════════════════
# Statistical battery — all on deviation series
# ════════════════════════════════════════════════════════════════════

def _rolling_ou_fit(series: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fit AR(1) on deviation series rolling. Returns (theta, mu, halflife) arrays.

    AR(1) form:   x_t - x_{t-1} = alpha + beta * x_{t-1} + eps
    O-U mapping:  theta = -beta,  mu = -alpha/beta,  halflife = ln(2)/theta
    Needs theta > 0 to be mean-reverting (otherwise trending — invalid fit).
    """
    n = len(series)
    theta = np.full(n, np.nan)
    mu = np.full(n, np.nan)
    halflife = np.full(n, np.nan)
    if n < window + 2:
        return theta, mu, halflife
    for t in range(window, n):
        x = series[t - window : t]
        if np.any(np.isnan(x)) or x.std() == 0:
            continue
        x_lag = x[:-1]
        x_diff = np.diff(x)
        # OLS: x_diff = alpha + beta * x_lag
        A = np.vstack([np.ones(len(x_lag)), x_lag]).T
        try:
            coef, *_ = np.linalg.lstsq(A, x_diff, rcond=None)
            alpha, beta = coef
            if beta < 0:
                th = -beta
                if th > 1e-6:
                    theta[t] = th
                    mu[t] = -alpha / beta
                    halflife[t] = math.log(2.0) / th
        except np.linalg.LinAlgError:
            continue
    return theta, mu, halflife


def _rolling_adf_pvalue(series: np.ndarray, window: int,
                        stride: int = 5) -> np.ndarray:
    """Rolling ADF p-value — stationarity test on deviation.

    `stride` controls re-fit cadence (ADF is expensive). Values between
    fits are forward-filled.
    """
    try:
        from statsmodels.tsa.stattools import adfuller
    except ImportError:
        return np.full(len(series), np.nan)

    n = len(series)
    pvals = np.full(n, np.nan)
    for t in range(window, n, stride):
        x = series[t - window : t]
        if np.any(np.isnan(x)) or x.std() == 0:
            continue
        try:
            res = adfuller(x, regression="c", autolag=None, maxlag=5)
            pvals[t] = res[1]
        except Exception:
            continue
    # Forward fill between stride points to keep a usable per-bar signal.
    pvals_ser = pd.Series(pvals)
    return pvals_ser.ffill().to_numpy()


def _rolling_variance_ratio(series: np.ndarray, window: int,
                            lags: tuple = (2, 4, 8),
                            stride: int = 5) -> np.ndarray:
    """Rolling Lo-MacKinlay Variance Ratio.

    Returns array[n, len(lags)] of VR per lag. VR < 1 -> anti-persistent.
    """
    n = len(series)
    out = np.full((n, len(lags)), np.nan)
    if n < window + 2:
        return out
    for t in range(window, n, stride):
        x = series[t - window : t]
        if np.any(np.isnan(x)):
            continue
        diffs = np.diff(x)
        if diffs.std() == 0:
            continue
        var1 = diffs.var(ddof=1)
        for j, q in enumerate(lags):
            if len(diffs) < q + 1:
                continue
            agg = np.array([x[q + i] - x[i] for i in range(len(x) - q)])
            varq = agg.var(ddof=1) / q
            if var1 > 0:
                out[t, j] = varq / var1
    # forward fill each column
    dfv = pd.DataFrame(out).ffill().to_numpy()
    return dfv


def _hurst_rs_multiscale(series: np.ndarray,
                         scales: tuple = (10, 20, 40, 80, 160)) -> float:
    """Multi-scale R/S Hurst estimator via log-log regression.

    Single-window R/S is known to be biased upward (~0.79 on crypto 15m
    windows regardless of true persistence). Multi-scale fits H from the
    slope of log(R/S) vs log(scale), which is the canonical approach.

    Returns H in [0, 1]; NaN if series too short.
    """
    if len(series) < max(scales) + 1:
        return float("nan")
    if np.any(np.isnan(series)) or np.std(series) == 0:
        return float("nan")
    rs_vals = []
    ns = []
    for n in scales:
        chunks = len(series) // n
        if chunks < 1:
            continue
        rs_chunk = []
        for i in range(chunks):
            s = series[i * n : (i + 1) * n]
            if np.std(s) == 0:
                continue
            dev = np.cumsum(s - s.mean())
            r = dev.max() - dev.min()
            sd = np.std(s, ddof=1)
            if sd > 0 and r > 0:
                rs_chunk.append(r / sd)
        if rs_chunk:
            rs_vals.append(np.mean(rs_chunk))
            ns.append(n)
    if len(rs_vals) < 2:
        return float("nan")
    log_n = np.log(ns)
    log_rs = np.log(rs_vals)
    slope, _ = np.polyfit(log_n, log_rs, 1)
    return float(np.clip(slope, 0.0, 1.0))


def _rolling_hurst_multiscale(series: np.ndarray, window: int,
                              stride: int = 10) -> np.ndarray:
    """Rolling multi-scale Hurst. Strided for performance; forward-filled."""
    n = len(series)
    out = np.full(n, np.nan)
    for t in range(window, n, stride):
        out[t] = _hurst_rs_multiscale(series[t - window : t])
    return pd.Series(out).ffill().to_numpy()


def compute_stats(df: pd.DataFrame, params: OrnsteinParams) -> pd.DataFrame:
    """Run the statistical battery on the deviation series."""
    out = df.copy()
    dev = out["deviation"].to_numpy()

    theta, mu, hl = _rolling_ou_fit(dev, params.stat_window)
    out["ou_theta"] = theta
    out["ou_mu"] = mu
    out["halflife"] = hl

    pvals = _rolling_adf_pvalue(dev, params.stat_window)
    out["adf_pvalue"] = pvals

    vr_arr = _rolling_variance_ratio(dev, params.stat_window, params.vr_lags)
    for j, q in enumerate(params.vr_lags):
        out[f"vr_lag{q}"] = vr_arr[:, j]

    # Multi-scale R/S Hurst on the deviation series. Single-window R/S
    # (used by core.chronos.hurst_rolling) is biased upward on crypto 15m
    # windows — it rarely drops below 0.7 even in ranging regimes. Using
    # the log-log slope across scales (10..160) recovers a usable H.
    out["hurst"] = _rolling_hurst_multiscale(dev, params.stat_window)

    return out


# ════════════════════════════════════════════════════════════════════
# Multi-TF divergence + RSI consensus
# ════════════════════════════════════════════════════════════════════

def _shift_htf_for_close(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Shift HTF timestamps forward by one period so merge_asof(backward)
    picks the *just-closed* HTF bar rather than the open one.
    No lookahead: value visible at exec bar `t` comes from HTF bar that
    closed at-or-before `t`.
    """
    period = pd.Timedelta(minutes=_TF_MINUTES.get(tf, 60))
    shifted = df.copy()
    shifted["time"] = shifted["time"] + period
    return shifted


def align_htfs_to_base(base: pd.DataFrame,
                       htfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    out = base.sort_values("time").reset_index(drop=True).copy()
    out["time"] = out["time"].astype("datetime64[ms]")
    for tf, htf_df in htfs.items():
        if htf_df is None or len(htf_df) == 0:
            continue
        shifted = _shift_htf_for_close(htf_df, tf).sort_values("time").reset_index(drop=True)
        shifted["time"] = shifted["time"].astype("datetime64[ms]")
        suffix = f"_{tf}"
        cols = [c for c in shifted.columns if c != "time"]
        shifted_ren = shifted.rename(columns={c: c + suffix for c in cols})
        out = pd.merge_asof(out, shifted_ren, on="time", direction="backward")
    return out


def _consensus_direction_on_row(row: pd.Series, tf_suffix: str,
                                params: OrnsteinParams,
                                min_medias: Optional[int] = None) -> tuple[int, int]:
    """Return (direction, n_medias_agree) for a single TF row.

    direction:
      +1  = price below enough medias -> long bias
      -1  = price above enough medias -> short bias
       0  = no consensus
    `min_medias` overrides the default (exec=4, HTF=3 per spec).
    """
    close_col = f"close{tf_suffix}" if tf_suffix else "close"
    close = row.get(close_col, np.nan)
    if isinstance(close, float) and np.isnan(close):
        return 0, 0
    media_cols = ("sma_fast", "ema_medium", "ema_slow", "vwap", "hma")
    below = 0
    above = 0
    total = 0
    for m in media_cols:
        col = f"{m}{tf_suffix}" if tf_suffix else m
        v = row.get(col, np.nan)
        if isinstance(v, float) and np.isnan(v):
            continue
        total += 1
        if close < v:
            below += 1
        elif close > v:
            above += 1
    if total == 0:
        return 0, 0
    threshold = min_medias if min_medias is not None else params.exec_tf_min_medias
    if below >= threshold:
        return +1, below
    if above >= threshold:
        return -1, above
    return 0, max(below, above)


def compute_fractal_divergence(df: pd.DataFrame,
                               params: OrnsteinParams) -> pd.DataFrame:
    """Per row, compute divergence direction and score from multi-TF consensus.

    Output columns:
      div_direction     : +1 / -1 / 0
      div_score_0_100   : strength 0-100
      htf_agree_count   : HTFs voting same side as exec TF
    """
    out = df.copy()

    n = len(out)
    directions = np.zeros(n, dtype=np.int8)
    scores = np.zeros(n, dtype=float)
    htf_agree = np.zeros(n, dtype=np.int8)

    htfs = params.tf_htfs

    for i in range(n):
        row = out.iloc[i]
        exec_dir, exec_strength = _consensus_direction_on_row(
            row, "", params, min_medias=params.exec_tf_min_medias
        )
        if exec_dir == 0:
            continue
        # Count HTFs agreeing (each HTF judged with its own softer threshold)
        agree = 0
        strengths = [exec_strength / 5.0]
        for tf in htfs:
            suf = f"_{tf}"
            htf_dir, htf_strength = _consensus_direction_on_row(
                row, suf, params, min_medias=params.htf_tf_min_medias
            )
            if htf_dir == exec_dir:
                agree += 1
                strengths.append(htf_strength / 5.0)
        htf_agree[i] = agree
        if agree >= params.htfs_min_consensus:
            directions[i] = exec_dir
            score = (2 * strengths[0] + (sum(strengths[1:]) / max(1, len(strengths) - 1))) / 3.0
            scores[i] = min(100.0, score * 100.0)
    out["div_direction"] = directions
    out["div_score"] = scores
    out["htf_agree_count"] = htf_agree
    return out


def compute_rsi_consensus(df: pd.DataFrame,
                          params: OrnsteinParams) -> pd.DataFrame:
    """RSI consensus: exec TF hard threshold + N HTFs soft threshold.

    Columns added:
      rsi_long_ok  : bool
      rsi_short_ok : bool
      rsi_score    : 0-100 magnitude
    """
    out = df.copy()

    exec_rsi = out["rsi"].to_numpy()
    long_ok = exec_rsi < params.rsi_long_max
    short_ok = exec_rsi > params.rsi_short_min

    htf_rsi_cols = [f"rsi_{tf}" for tf in params.tf_htfs if f"rsi_{tf}" in out.columns]
    if not htf_rsi_cols:
        out["rsi_long_ok"] = long_ok
        out["rsi_short_ok"] = short_ok
        out["rsi_score"] = 0.0
        return out

    n = len(out)
    rsi_long = np.zeros(n, dtype=bool)
    rsi_short = np.zeros(n, dtype=bool)
    scores = np.zeros(n, dtype=float)
    for i in range(n):
        if long_ok[i]:
            agree = sum(
                1 for c in htf_rsi_cols
                if not np.isnan(out[c].iloc[i]) and out[c].iloc[i] < params.rsi_htf_long_max
            )
            if agree >= params.rsi_htf_min_confirm:
                rsi_long[i] = True
                magnitude = (params.rsi_long_max - exec_rsi[i]) / params.rsi_long_max
                scores[i] = min(100.0, magnitude * 100.0 + agree * 5)
        elif short_ok[i]:
            agree = sum(
                1 for c in htf_rsi_cols
                if not np.isnan(out[c].iloc[i]) and out[c].iloc[i] > params.rsi_htf_short_min
            )
            if agree >= params.rsi_htf_min_confirm:
                rsi_short[i] = True
                magnitude = (exec_rsi[i] - params.rsi_short_min) / (100.0 - params.rsi_short_min)
                scores[i] = min(100.0, magnitude * 100.0 + agree * 5)
    out["rsi_long_ok"] = rsi_long
    out["rsi_short_ok"] = rsi_short
    out["rsi_score"] = scores
    return out


# ════════════════════════════════════════════════════════════════════
# Score Ω aggregation (with per-component logging)
# ════════════════════════════════════════════════════════════════════

def _subscore_ou(row, params: OrnsteinParams) -> float:
    hl = row.get("halflife", np.nan)
    theta = row.get("ou_theta", np.nan)
    if isinstance(hl, float) and np.isnan(hl):
        return 0.0
    if not (params.halflife_min <= hl <= params.halflife_max):
        return 0.0
    # Quality: tighter half-life = better. theta magnitude also = more certain MR.
    hl_mid = (params.halflife_min + params.halflife_max) / 2.0
    hl_quality = 1.0 - abs(hl - hl_mid) / hl_mid
    theta_q = min(1.0, max(0.0, float(theta) * 10))
    return float(0.6 * hl_quality + 0.4 * theta_q) * 100.0


def _subscore_hurst(row, params: OrnsteinParams) -> float:
    h = row.get("hurst", np.nan)
    if isinstance(h, float) and np.isnan(h):
        return 0.0
    if h >= params.hurst_threshold:
        return 0.0
    # Closer to 0 = stronger anti-persistence
    return float(max(0.0, min(1.0, (params.hurst_threshold - h) / 0.3)) * 100.0)


def _subscore_adf(row, params: OrnsteinParams) -> float:
    p = row.get("adf_pvalue", np.nan)
    if isinstance(p, float) and np.isnan(p):
        return 0.0
    if p > params.adf_pvalue_max:
        return 0.0
    # Map p in [0, adf_pvalue_max] -> [100, 0]
    return float((1.0 - p / params.adf_pvalue_max) * 100.0)


def _subscore_vr(row, params: OrnsteinParams) -> float:
    below = 0
    total = 0
    for q in params.vr_lags:
        v = row.get(f"vr_lag{q}", np.nan)
        if isinstance(v, float) and np.isnan(v):
            continue
        total += 1
        if v < 1.0:
            below += 1
    if total == 0:
        return 0.0
    if below < params.vr_min_below_one:
        return 0.0
    return float(below / total) * 100.0


def _subscore_bb(row, direction: int) -> float:
    pct_b = row.get("bb_pct_b", np.nan)
    if isinstance(pct_b, float) and np.isnan(pct_b):
        return 0.0
    if direction == +1 and pct_b < 0.0:
        return float(min(100.0, -pct_b * 100.0))
    if direction == -1 and pct_b > 1.0:
        return float(min(100.0, (pct_b - 1.0) * 100.0))
    return 0.0


def _atr_gate(row, params: OrnsteinParams) -> tuple[bool, float]:
    """Returns (allow_entry, omega_boost_pct).

    omega_boost_pct is a float in [-100, +100] to be added weighted by
    params.atr_boost_factor in compute_omega.
    """
    p = row.get("atr_percentile", np.nan)
    if isinstance(p, float) and np.isnan(p):
        return True, 0.0
    if p > params.atr_percentile_block:
        return False, 0.0
    if p < params.atr_percentile_boost:
        return True, 100.0  # full boost
    return True, 0.0


def derive_entry_direction(row, params: OrnsteinParams) -> int:
    """Resolve trade direction from consensus or signed deviation."""
    if params.disable_divergence or params.disable_multi_tf:
        dev = row.get("deviation", np.nan)
        if pd.isna(dev):
            return 0
        if dev < 0:
            return +1
        if dev > 0:
            return -1
        return 0
    return int(row.get("div_direction", 0))


def compute_omega(row, direction: int, params: OrnsteinParams) -> dict:
    """Aggregate Ω score with transparent per-component accounting.

    Returns dict:
      omega_final : 0-100
      allow       : bool (ATR-guard gate)
      subscores   : dict per component (div, rsi, ou, hurst, adf, vr, bb, atr_boost)
      weighted    : dict per component (what was actually added to omega)
    """
    # Components
    if params.disable_divergence or params.disable_multi_tf:
        div_raw = 0.0
    else:
        div_raw = float(row.get("div_score", 0.0))

    if params.disable_rsi:
        rsi_raw = 0.0
    else:
        rsi_raw = float(row.get("rsi_score", 0.0))

    ou_raw = 0.0 if params.disable_ou else _subscore_ou(row, params)
    hurst_raw = 0.0 if params.disable_hurst else _subscore_hurst(row, params)
    adf_raw = 0.0 if params.disable_adf else _subscore_adf(row, params)
    vr_raw = 0.0 if params.disable_vr else _subscore_vr(row, params)
    bb_raw = 0.0 if params.disable_bb else _subscore_bb(row, direction)

    allow, atr_boost_raw = _atr_gate(row, params)
    if params.disable_atr_boost:
        atr_boost_raw = 0.0

    weighted = {
        "div": params.w_divergence * div_raw,
        "rsi": params.w_rsi * rsi_raw,
        "ou": params.w_ou * ou_raw,
        "hurst": params.w_hurst * hurst_raw,
        "adf": params.w_adf * adf_raw,
        "vr": params.w_vr * vr_raw,
        "bb": params.w_bb * bb_raw,
        "atr_boost": params.atr_boost_factor * atr_boost_raw,
    }
    omega_final = float(sum(weighted.values()))
    omega_final = max(0.0, min(100.0, omega_final))

    return {
        "omega_final": omega_final,
        "allow": allow,
        "subscores": {
            "div": div_raw, "rsi": rsi_raw, "ou": ou_raw, "hurst": hurst_raw,
            "adf": adf_raw, "vr": vr_raw, "bb": bb_raw, "atr_boost": atr_boost_raw,
        },
        "weighted": weighted,
    }


# ════════════════════════════════════════════════════════════════════
# Sizing
# ════════════════════════════════════════════════════════════════════

def ornstein_size(equity: float, entry: float, sl: float,
                  omega: float, params: OrnsteinParams) -> dict:
    """Convex sizing scaled by Ω strength.

    size_mult = min(omega / omega_entry, size_mult_cap)
    risk_usd  = equity * risk_per_trade * size_mult**2
    size_units= risk_usd / |entry - sl|
    notional capped at equity * notional_cap.
    """
    size_mult = min(max(0.0, omega) / max(params.omega_entry, 1e-6),
                    params.size_mult_cap)
    risk_usd = equity * params.risk_per_trade * (size_mult ** 2)
    stop_dist = abs(entry - sl)
    if stop_dist <= 0 or entry <= 0:
        return {"size_units": 0.0, "notional": 0.0, "risk_usd": 0.0, "size_mult": size_mult}
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
        "size_mult": float(size_mult),
    }


# ════════════════════════════════════════════════════════════════════
# Trade lifecycle
# ════════════════════════════════════════════════════════════════════

def _resolve_ornstein_exit(df: pd.DataFrame, t: int, trade: dict,
                           params: OrnsteinParams) -> Optional[tuple[str, float]]:
    """Per bar, evaluate exits in priority order:
      1. Stop loss (initial or widening-ATR based)
      2. Partial at midpoint toward EMA50
      3. Full TP at EMA50 crossing
      4. Time stop at 2 x halflife
    """
    high = float(df["high"].iloc[t])
    low = float(df["low"].iloc[t])
    close = float(df["close"].iloc[t])
    atr_here = float(df["atr"].iloc[t]) if not np.isnan(df["atr"].iloc[t]) else trade["entry_atr"]
    d = trade["direction"]

    # Stop: initial level OR deviation expansion past stop_extra_atr_expansion.
    stop = trade["sl"]
    if d == +1 and low <= stop:
        return "sl", stop
    if d == -1 and high >= stop:
        return "sl", stop
    # Expansion-based stop
    entry_px = trade["entry"]
    adverse = (entry_px - low) if d == +1 else (high - entry_px)
    if adverse >= params.stop_extra_atr_expansion * trade["entry_atr"]:
        return "sl_expansion", entry_px - d * params.stop_extra_atr_expansion * trade["entry_atr"]

    # TP — reversion to EMA50 (mean)
    mean_now = float(df["ema_medium"].iloc[t])
    if not trade.get("partial_taken", False):
        midpoint = (entry_px + mean_now) / 2.0
        if d == +1 and high >= midpoint:
            return "partial", midpoint
        if d == -1 and low <= midpoint:
            return "partial", midpoint
    if d == +1 and high >= mean_now:
        return "tp_mean", mean_now
    if d == -1 and low <= mean_now:
        return "tp_mean", mean_now

    # Time stop: 2 * halflife at entry.
    if (t - trade["entry_idx"]) >= trade["time_stop_bars"]:
        return "time_stop", close
    return None


def _pnl_with_costs(direction: int, entry: float, exit_p: float,
                    size: float, duration: int,
                    funding_periods_per_8h: float) -> float:
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

class KillSwitch:
    def __init__(self, params: OrnsteinParams):
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
# Regime classification helper (for reporting)
# ════════════════════════════════════════════════════════════════════

def _regime_tag(row) -> str:
    """Classify bar regime by Hurst × ATR percentile.

    trend     : H >= 0.55
    range     : H <  0.45
    high_vol  : atr_percentile >= 80
    low_vol   : atr_percentile <= 20
    (combined)
    """
    h = row.get("hurst", np.nan)
    p = row.get("atr_percentile", np.nan)
    parts: list[str] = []
    if not (isinstance(h, float) and np.isnan(h)):
        if h >= 0.55:
            parts.append("trend")
        elif h < 0.45:
            parts.append("range")
        else:
            parts.append("neutral")
    if not (isinstance(p, float) and np.isnan(p)):
        if p >= 80:
            parts.append("high_vol")
        elif p <= 20:
            parts.append("low_vol")
        else:
            parts.append("mid_vol")
    return "/".join(parts) if parts else "unknown"


# ════════════════════════════════════════════════════════════════════
# scan_symbol — the decision loop
# ════════════════════════════════════════════════════════════════════

def scan_symbol(df: pd.DataFrame, symbol: str,
                params: Optional[OrnsteinParams] = None,
                initial_equity: float = ACCOUNT_SIZE) -> tuple[list, dict]:
    """Run ORNSTEIN on a fully-prepared merged df for one symbol.

    df must already have features, stats, htfs merged, divergence/rsi_consensus.
    """
    params = params or OrnsteinParams()
    trades: list[dict] = []
    vetos: dict[str, int] = defaultdict(int)

    if len(df) < max(300, params.stat_window + 50):
        return [], {"too_few_bars": 1}

    account = float(initial_equity)
    kill = KillSwitch(params)
    n = len(df)
    funding_periods_per_8h = 8 * 60 / _TF_MINUTES.get(params.tf_exec, 15)
    open_trade: Optional[dict] = None
    warmup_start = max(params.stat_window + 50, 250)

    for t in range(warmup_start, n - 1):
        row = df.iloc[t]
        ts = row["time"]
        kill.on_equity(ts, account)

        # ── Manage open trade ────────────────────────────────────
        if open_trade is not None:
            resolved = _resolve_ornstein_exit(df, t, open_trade, params)
            if resolved is not None:
                reason, exit_px = resolved
                if reason == "partial":
                    frac = params.partial_take_frac
                    sz = open_trade["size"] * frac
                    pnl = _pnl_with_costs(
                        open_trade["direction"], open_trade["entry"], exit_px,
                        sz, t - open_trade["entry_idx"], funding_periods_per_8h,
                    )
                    account = max(account + pnl, 0.0)
                    open_trade["size"] -= sz
                    open_trade["partial_taken"] = True
                    open_trade.setdefault("partials", []).append({
                        "reason": reason, "price": round(exit_px, 6),
                        "size": sz, "pnl": pnl, "idx": t,
                    })
                else:
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

        direction = derive_entry_direction(row, params)
        if direction == 0:
            veto_key = "no_direction" if (
                params.disable_divergence or params.disable_multi_tf
            ) else "no_divergence"
            vetos[veto_key] += 1
            continue

        # RSI confirmation at exec TF
        rsi_ok = bool(row.get("rsi_long_ok", False)) if direction == +1 \
            else bool(row.get("rsi_short_ok", False))
        if not params.disable_rsi and not rsi_ok:
            vetos["rsi_block"] += 1
            continue

        # Statistical gates (entry filters — not stops)
        if not params.disable_ou:
            hl = row.get("halflife", np.nan)
            if isinstance(hl, float) and np.isnan(hl):
                vetos["ou_nan"] += 1
                continue
            if not (params.halflife_min <= hl <= params.halflife_max):
                vetos["halflife_outside"] += 1
                continue

        if not params.disable_hurst:
            h = row.get("hurst", np.nan)
            if isinstance(h, float) and np.isnan(h) or h >= params.hurst_threshold:
                vetos["hurst_block"] += 1
                continue

        if not params.disable_adf:
            p = row.get("adf_pvalue", np.nan)
            if isinstance(p, float) and np.isnan(p) or p > params.adf_pvalue_max:
                vetos["adf_block"] += 1
                continue

        if not params.disable_vr:
            below = 0
            counted = 0
            for q in params.vr_lags:
                v = row.get(f"vr_lag{q}", np.nan)
                if isinstance(v, float) and np.isnan(v):
                    continue
                counted += 1
                if v < 1.0:
                    below += 1
            if counted == 0 or below < params.vr_min_below_one:
                vetos["vr_block"] += 1
                continue

        # Ω aggregation (full accounting)
        omega = compute_omega(row, direction, params)
        if not omega["allow"]:
            vetos["atr_extreme"] += 1
            continue
        if omega["omega_final"] < params.omega_entry:
            vetos["omega_low"] += 1
            continue

        # Levels
        entry = float(df["open"].iloc[t + 1])
        atr_here = float(row.get("atr", np.nan))
        if np.isnan(atr_here) or atr_here <= 0:
            vetos["atr_nan"] += 1
            continue
        dev = float(row.get("deviation", 0.0))

        # Stop at deviation_sigma * ATR past entry — mapped to price space.
        # If long (deviation negative), stop sits below: entry - |stop_sigma - |dev|| * ATR
        stop_extra = max(0.5, params.stop_deviation_sigma - abs(dev))
        if direction == +1:
            sl = entry - stop_extra * atr_here
        else:
            sl = entry + stop_extra * atr_here
        mean_now = float(row.get("ema_medium", entry))
        # Sanity: stop on the right side, target on the opposite.
        if direction == +1 and not (sl < entry < mean_now):
            vetos["invalid_geometry"] += 1
            continue
        if direction == -1 and not (sl > entry > mean_now):
            vetos["invalid_geometry"] += 1
            continue

        # Sizing
        sz = ornstein_size(account, entry, sl, omega["omega_final"], params)
        if sz["size_units"] <= 0:
            vetos["zero_size"] += 1
            continue

        # Time stop from half-life at entry (frozen)
        hl_entry = float(row.get("halflife", 20.0)) if not params.disable_ou else 20.0
        time_stop_bars = int(params.time_stop_halflife_mult * hl_entry)
        time_stop_bars = max(params.time_stop_floor,
                             min(params.time_stop_ceiling, time_stop_bars))

        open_trade = {
            "symbol": symbol,
            "direction": direction,
            "entry_idx": t + 1,
            "entry_time": df["time"].iloc[t + 1],
            "entry": round(entry, 6),
            "entry_atr": atr_here,
            "sl": round(sl, 6),
            "mean_target": round(mean_now, 6),
            "size": sz["size_units"],
            "notional": sz["notional"],
            "size_mult": sz["size_mult"],
            "omega_final": omega["omega_final"],
            "div_score": omega["subscores"]["div"],
            "rsi_score": omega["subscores"]["rsi"],
            "ou_score": omega["subscores"]["ou"],
            "hurst_score": omega["subscores"]["hurst"],
            "adf_score": omega["subscores"]["adf"],
            "vr_score": omega["subscores"]["vr"],
            "bb_score": omega["subscores"]["bb"],
            "atr_boost": omega["subscores"]["atr_boost"],
            "deviation_at_entry": dev,
            "halflife_at_entry": hl_entry,
            "time_stop_bars": time_stop_bars,
            "regime_tag": _regime_tag(row),
            "partials": [],
            "partial_taken": False,
        }

    return trades, dict(vetos)


# ════════════════════════════════════════════════════════════════════
# Multi-symbol orchestration
# ════════════════════════════════════════════════════════════════════

def _tf_bars_for_days(days: int, tf: str) -> int:
    mins = _TF_MINUTES.get(tf, 15)
    bars_per_day = max(1, int((24 * 60) / mins))
    warmup_days = {
        "1d": 90, "4h": 30, "1h": 14, "30m": 7, "15m": 5, "5m": 3,
    }.get(tf, 7)
    return max(300, (days + warmup_days) * bars_per_day)


def _n_candles_map(params: OrnsteinParams, days: Optional[int]) -> dict[str, int]:
    tfs = [params.tf_exec] + list(params.tf_htfs)
    if days is None:
        return {tf: max(1000, params.n_candles_exec // 2) for tf in tfs}
    return {tf: _tf_bars_for_days(days, tf) for tf in tfs}


def _end_to_ms(end: Optional[str]) -> Optional[int]:
    if not end:
        return None
    return int(pd.Timestamp(end).timestamp() * 1000)


def prepare_symbol(symbol: str, params: OrnsteinParams,
                   prefetched: Optional[dict] = None,
                   days: Optional[int] = None,
                   end: Optional[str] = None) -> Optional[pd.DataFrame]:
    """Fetch all TFs, compute features + stats, merge HTFs, score everything."""
    tfs = [params.tf_exec] + list(params.tf_htfs)
    n_candles_map = _n_candles_map(params, days)
    end_time_ms = _end_to_ms(end)
    frames: dict[str, pd.DataFrame] = {}
    for tf in tfs:
        if prefetched is not None:
            df = prefetched.get(tf, {}).get(symbol)
        else:
            got = fetch_all([symbol], interval=tf,
                            n_candles=n_candles_map[tf],
                            futures=True, end_time_ms=end_time_ms)
            df = got.get(symbol)
        if df is None or len(df) < 300:
            log.warning("%s: insufficient data on %s", symbol, tf)
            return None
        validate(df, symbol)
        df = compute_features(df, params)
        frames[tf] = df

    exec_df = frames[params.tf_exec]
    exec_df = compute_stats(exec_df, params)
    htfs = {tf: frames[tf] for tf in params.tf_htfs}
    merged = align_htfs_to_base(exec_df, htfs)
    merged = compute_fractal_divergence(merged, params)
    merged = compute_rsi_consensus(merged, params)
    return merged


def prefetch_universe(symbols: list[str], params: OrnsteinParams,
                      days: Optional[int] = None,
                      end: Optional[str] = None) -> tuple[dict, dict]:
    tfs = [params.tf_exec] + list(params.tf_htfs)
    n_candles_map = _n_candles_map(params, days)
    end_time_ms = _end_to_ms(end)
    universe: dict[str, dict[str, pd.DataFrame]] = {}
    for tf in tfs:
        t0 = time.time()
        universe[tf] = fetch_all(symbols, interval=tf,
                                 n_candles=n_candles_map[tf],
                                 futures=True, end_time_ms=end_time_ms)
        log.info("Prefetch %s: %s/%s in %.1fs", tf,
                 len(universe[tf]), len(symbols), time.time() - t0)
    return universe, n_candles_map


def run_backtest(symbols: list[str], params: Optional[OrnsteinParams] = None,
                 initial_equity: float = ACCOUNT_SIZE,
                 days: Optional[int] = None,
                 end: Optional[str] = None,
                 profile: bool = False) -> tuple[list, dict, dict]:
    params = params or OrnsteinParams()
    all_trades: list[dict] = []
    all_vetos: dict[str, int] = defaultdict(int)
    per_symbol: dict[str, dict] = {}
    prefetched, n_candles_map = prefetch_universe(symbols, params, days=days, end=end)
    for idx, sym in enumerate(symbols, 1):
        t0 = time.time()
        log.info("[%s/%s] Preparing %s", idx, len(symbols), sym)
        merged = prepare_symbol(sym, params, prefetched=prefetched, days=days, end=end)
        if merged is None:
            continue
        t1 = time.time()
        trades, vetos = scan_symbol(merged, sym, params, initial_equity)
        t2 = time.time()
        all_trades.extend(trades)
        for k, v in vetos.items():
            all_vetos[k] += v
        sym_sum = compute_summary(trades, initial_equity, n_days=days)
        sym_sum["vetos"] = vetos
        per_symbol[sym] = sym_sum
        log.info("[%s/%s] %s: %d trades | prep %.1fs scan %.1fs",
                 idx, len(symbols), sym, len(trades), t1 - t0, t2 - t1)
    summary = compute_summary(all_trades, initial_equity, n_days=days)
    summary["vetos"] = dict(all_vetos)
    if profile:
        summary["profile"] = {
            "n_symbols": len(symbols), "days": days, "end": end,
            "n_candles_map": n_candles_map,
        }
    # Regime breakdown
    regime_counts: dict[str, int] = defaultdict(int)
    regime_pnl: dict[str, float] = defaultdict(float)
    for tr in all_trades:
        tag = tr.get("regime_tag", "unknown")
        regime_counts[tag] += 1
        regime_pnl[tag] += float(tr.get("pnl", 0.0))
    summary["regime_breakdown"] = {
        tag: {"n": n, "pnl": round(regime_pnl[tag], 2)}
        for tag, n in regime_counts.items()
    }
    return all_trades, summary, per_symbol


def compute_summary(trades: list[dict], initial_equity: float = ACCOUNT_SIZE,
                    n_days: Optional[int] = None,
                    min_sample_for_ratios: int = 30) -> dict:
    if not trades:
        return {
            "total_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "sharpe": 0.0, "sortino": 0.0, "max_drawdown": 0.0,
            "expectancy_r": 0.0,
            "final_equity": float(initial_equity), "total_pnl": 0.0,
            "metrics_reliable": False, "metrics_note": "insufficient_sample",
        }
    pnls = np.array([t["pnl"] for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    equity, _mdd_abs, mdd_pct, _ = equity_stats(pnls.tolist(), initial_equity)
    ratios = calc_ratios(pnls.tolist(), initial_equity, n_days=n_days or 365)
    reliable = len(trades) >= min_sample_for_ratios
    sharpe = float(ratios.get("sharpe") or 0.0) if reliable else 0.0
    sortino = float(ratios.get("sortino") or 0.0) if reliable else 0.0
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
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": float(mdd_pct / 100.0),
        "expectancy_r": expectancy_r,
        "final_equity": float(equity[-1]),
        "total_pnl": float(pnls.sum()),
        "metrics_reliable": reliable,
        "metrics_note": "" if reliable else "insufficient_sample",
    }


# ════════════════════════════════════════════════════════════════════
# Ablation runner
# ════════════════════════════════════════════════════════════════════

def run_ablation_suite(symbols: list[str], base_params: OrnsteinParams,
                       initial_equity: float,
                       days: Optional[int] = None,
                       end: Optional[str] = None,
                       variants: Optional[list[str]] = None) -> dict:
    """Run full ORNSTEIN + each variant with one component disabled.

    Returns dict keyed by variant name with summary + delta vs full.
    """
    variants = variants or list(ABLATION_VARIANTS.keys())
    log.info("Ablation suite: %d variants on %d symbols", len(variants), len(symbols))
    results: dict[str, dict] = {}
    for name in variants:
        overrides = ABLATION_VARIANTS[name]
        p = OrnsteinParams(**{**asdict(base_params), **overrides})
        log.info("Ablation variant: %s", name)
        trades, summary, _ = run_backtest(
            symbols, p, initial_equity, days=days, end=end, profile=False
        )
        results[name] = {
            "n_trades": summary.get("total_trades"),
            "sharpe": summary.get("sharpe"),
            "sortino": summary.get("sortino"),
            "profit_factor": summary.get("profit_factor"),
            "win_rate": summary.get("win_rate"),
            "max_drawdown": summary.get("max_drawdown"),
            "total_pnl": summary.get("total_pnl"),
        }
    base = results.get("none", {})
    for k, v in results.items():
        if k == "none":
            v["delta_sharpe_vs_full"] = 0.0
            continue
        v["delta_sharpe_vs_full"] = float(
            (v.get("sharpe") or 0.0) - (base.get("sharpe") or 0.0)
        )
    return results


# ════════════════════════════════════════════════════════════════════
# Persistence (AURUM run envelope)
# ════════════════════════════════════════════════════════════════════

def _trades_to_serializable(trades: list[dict]) -> list[dict]:
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
             params: OrnsteinParams, vetos: dict, per_sym: dict,
             meta: dict, ablation: Optional[dict] = None) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(run_dir / "trades.json",
                 json.dumps(_trades_to_serializable(trades),
                            separators=(",", ":"), default=str))
    payload = {
        "engine": "ORNSTEIN",
        "version": "1.0.0",
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
    if ablation is not None:
        atomic_write(run_dir / "ablation.json",
                     json.dumps(ablation, indent=2, default=str))


def _setup_logging(run_dir: Path) -> None:
    fh = logging.FileHandler(run_dir / "log.txt", encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s - %(message)s"
    ))
    logging.getLogger().addHandler(fh)
    logging.getLogger().setLevel(logging.INFO)


# ════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════

def _print_summary(summary: dict) -> None:
    print(f"\n  ORNSTEIN — Mean-Reversion Engine")
    print(f"  {'=' * 60}")
    print(f"  Total trades       : {summary['total_trades']}")
    print(f"  Win rate           : {summary['win_rate'] * 100:.2f}%")
    pf = summary["profit_factor"]
    pf_str = "inf" if pf == float("inf") else f"{pf:.3f}"
    print(f"  Profit factor      : {pf_str}")
    print(f"  Sharpe             : {summary['sharpe']:.3f}")
    print(f"  Sortino            : {summary['sortino']:.3f}")
    if not summary.get("metrics_reliable", True):
        note = summary.get("metrics_note") or "insufficient_sample"
        print(f"  Ratio status       : n/a ({note})")
    print(f"  Max drawdown       : {summary['max_drawdown'] * 100:.2f}%")
    print(f"  Expectancy (R)     : {summary['expectancy_r']:.3f}")
    print(f"  Final equity       : ${summary['final_equity']:,.2f}")
    print(f"  Total PnL          : ${summary['total_pnl']:,.2f}")
    regime = summary.get("regime_breakdown", {})
    if regime:
        print(f"\n  Regime breakdown:")
        for tag, r in sorted(regime.items(), key=lambda x: -x[1]["n"]):
            print(f"    {tag:<22s} n={r['n']:>4d}  pnl=${r['pnl']:+10,.2f}")
    vetos = summary.get("vetos", {})
    if vetos:
        print(f"\n  Vetos:")
        for k, v in sorted(vetos.items(), key=lambda x: -x[1])[:15]:
            print(f"    {k:<22s} {v:>8d}")


def _print_ablation(ablation: dict) -> None:
    print(f"\n  ORNSTEIN Ablation Suite")
    print(f"  {'=' * 60}")
    print(f"  {'variant':<18s} {'N':>6} {'Sharpe':>8} {'Sortino':>9} {'PF':>7} {'WR%':>6} {'ΔSharpe':>9}")
    for k, v in ablation.items():
        pf_str = f"{v.get('profit_factor', 0):>6.3f}" if v.get('profit_factor') != float('inf') else "    inf"
        print(f"  {k:<18s} {v.get('n_trades', 0):>6d} "
              f"{v.get('sharpe', 0):>+8.3f} {v.get('sortino', 0):>+9.3f} "
              f"{pf_str} {(v.get('win_rate', 0) or 0) * 100:>5.1f}% "
              f"{v.get('delta_sharpe_vs_full', 0):>+9.3f}")


def main() -> int:
    ap = argparse.ArgumentParser(description="ORNSTEIN — AURUM Mean-Reversion Engine")
    ap.add_argument("--preset", choices=sorted(ORNSTEIN_PRESETS.keys()),
                    help="Apply a named research preset before CLI overrides")
    ap.add_argument("--symbols", default=None,
                    help="Comma-separated symbols (default: SYMBOLS from config.params)")
    ap.add_argument("--basket", default=None, help="Basket name from config.params BASKETS")
    ap.add_argument("--days", type=int, default=None, help="Lookback window in days")
    ap.add_argument("--end", type=str, default=None, help="End date YYYY-MM-DD for OOS")
    ap.add_argument("--out", default="data/ornstein", help="Output base dir")
    ap.add_argument("--tf", default=None, help="Execution timeframe override")
    ap.add_argument("--omega-entry", type=float, default=None, help="Ω entry threshold (0-100)")
    ap.add_argument("--hurst-threshold", type=float, default=None)
    ap.add_argument("--adf-pvalue", type=float, default=None)
    ap.add_argument("--halflife-min", type=float, default=None)
    ap.add_argument("--halflife-max", type=float, default=None)
    ap.add_argument("--rsi-long-max", type=float, default=None)
    ap.add_argument("--rsi-short-min", type=float, default=None)
    ap.add_argument("--htfs-min-consensus", type=int, default=None)
    ap.add_argument("--disable-divergence", action="store_true")
    ap.add_argument("--disable-hurst", action="store_true")
    ap.add_argument("--disable-multi-tf", action="store_true")
    ap.add_argument("--ablation", action="store_true",
                    help="Run full ablation suite after main backtest")
    ap.add_argument("--ablation-only", action="store_true",
                    help="Skip main output, run only the ablation suite")
    ap.add_argument("--no-kill-switch", action="store_true")
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--no-menu", action="store_true", help="(compat flag, no prompts)")
    args = ap.parse_args()

    # Symbols resolution
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    elif args.basket:
        symbols = list(BASKETS.get(args.basket, SYMBOLS))
    else:
        symbols = list(SYMBOLS)

    # Params resolution
    params = OrnsteinParams()
    if args.preset:
        for k, v in ORNSTEIN_PRESETS[args.preset].items():
            setattr(params, k, v)
    if args.tf:
        params.tf_exec = args.tf
    if args.omega_entry is not None:
        params.omega_entry = args.omega_entry
    if args.hurst_threshold is not None:
        params.hurst_threshold = args.hurst_threshold
    if args.adf_pvalue is not None:
        params.adf_pvalue_max = args.adf_pvalue
    if args.halflife_min is not None:
        params.halflife_min = args.halflife_min
    if args.halflife_max is not None:
        params.halflife_max = args.halflife_max
    if args.rsi_long_max is not None:
        params.rsi_long_max = args.rsi_long_max
    if args.rsi_short_min is not None:
        params.rsi_short_min = args.rsi_short_min
    if args.htfs_min_consensus is not None:
        params.htfs_min_consensus = args.htfs_min_consensus
    if args.disable_divergence:
        params.disable_divergence = True
    if args.disable_hurst:
        params.disable_hurst = True
    if args.disable_multi_tf:
        params.disable_multi_tf = True
    if args.no_kill_switch:
        params.kill_daily = 1.0
        params.kill_weekly = 1.0

    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    run_dir = Path(args.out) / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s - %(message)s")
    _setup_logging(run_dir)
    log.info("ORNSTEIN run starting: symbols=%s run_dir=%s", symbols, run_dir)

    meta = {
        "run_id": ts,
        "symbols": symbols,
        "initial_equity": float(ACCOUNT_SIZE),
        "preset": args.preset,
        "basket": args.basket,
        "days": args.days,
        "end": args.end,
        "cli_args": vars(args),
    }

    ablation = None

    if not args.ablation_only:
        trades, summary, per_sym = run_backtest(
            symbols, params, ACCOUNT_SIZE, days=args.days, end=args.end,
            profile=args.profile,
        )
        vetos = summary.pop("vetos", {})
        save_run(run_dir, trades, summary, params, vetos, per_sym, meta, ablation)
        _print_summary({**summary, "vetos": vetos})

    if args.ablation or args.ablation_only:
        ablation = run_ablation_suite(
            symbols, params, ACCOUNT_SIZE, days=args.days, end=args.end,
        )
        _print_ablation(ablation)
        if args.ablation_only:
            save_run(run_dir, [], {"total_trades": 0}, params, {}, {}, meta, ablation)
        else:
            atomic_write(run_dir / "ablation.json",
                         json.dumps(ablation, indent=2, default=str))

    print(f"\n  Run saved to: {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
