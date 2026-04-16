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
    """Stub — implemented in Task 3."""
    raise NotImplementedError


def compute_fibs(df: pd.DataFrame, params: PhiParams) -> pd.DataFrame:
    """Stub — implemented in Task 4."""
    raise NotImplementedError


# ════════════════════════════════════════════════════════════════════
# CLI entry
# ════════════════════════════════════════════════════════════════════

def main() -> int:
    """Stub — implemented in Task 12."""
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
