"""
GRAHAM — Endogenous Momentum Engine (AURUM Finance)
===================================================
Trend-following gated by Hawkes branching ratio η in the endogenous regime
(typically 0.80 ≤ η < 0.95 in tick-level literature; η_lower..upper on
candle-level must be calibrated to local distribution — see discipline note).

Named after Graham Capital, classic CTA trend-follower — GRAHAM conditions
trend entries on moderate self-excitation regime, not just EMA crossover.

Hypothesis H2
-------------
In moderate endogenous regime (sustained η in ENDO band), self-reinforcement
amplifies trend continuation. Entries require:
  - η sustained in ENDO band
  - EMA fast > EMA slow (LONG) or opposite (SHORT)
  - Significant EMA slope (not flat)
  - Confirmed structure (≥ N higher-highs for LONG, lower-lows for SHORT)

Falsification test
------------------
`run_backtest(..., bypass_eta_gate=True)` disables the η filter and lets the
trend-follower fire on EMA+slope+structure alone. If η gate does NOT add
measurable edge (Sharpe, hit rate, Sortino) vs the baseline, H2 is rejected
even if GRAHAM is profitable — because the profit is from trend, not η.

Discipline
----------
- Local fixed-risk-% sizing (same pattern as KEPOS).
- AURUM cost model imported from config.params.
- Backtest-first; no ENGINE_INTERVALS / FROZEN registration until edge
  validated against the bypass baseline.
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
    INTERVAL,
    LEVERAGE,
    SCAN_DAYS,
    SLIPPAGE,
    SPREAD,
    SYMBOLS,
    _TF_MINUTES,
)
from core.data import fetch_all, validate
from core.fs import atomic_write
from core.hawkes import rolling_branching_ratio
from core.indicators import indicators

log = logging.getLogger("GRAHAM")
_tl = logging.getLogger("GRAHAM.trades")


# ════════════════════════════════════════════════════════════════════
# Parameters
# ════════════════════════════════════════════════════════════════════

@dataclass
class GrahamParams:
    """Defaults follow literature thresholds. For candle-level work,
    override via CLI with empirically-calibrated values."""

    # Hawkes
    hawkes_window_bars: int = 2000
    hawkes_refit_every: int = 100
    hawkes_k_sigma: float = 2.0
    hawkes_vol_lookback: int = 100
    hawkes_smooth_span: int = 5
    hawkes_min_events: int = 30

    # η gate (ENDO regime band)
    eta_lower: float = 0.80
    eta_upper: float = 0.95
    eta_sustained_bars: int = 10
    eta_exit_lower: float = 0.75   # below → regime_low exit
    eta_exit_upper: float = 0.97   # above → regime_crit exit
    eta_exit_sustained: int = 2
    bypass_eta_gate: bool = False  # set True for falsification baseline

    # Trend / EMA
    ema_fast: int = 21
    ema_slow: int = 55

    # Slope
    slope_lookback: int = 10
    slope_min_abs: float = 0.0008  # fraction per bar

    # Market structure
    structure_lookback: int = 20
    structure_min_count: int = 2

    # Stops / trailing
    atr_period: int = 14
    stop_atr_mult: float = 2.0
    trail_atr_mult: float = 2.0
    max_bars_in_trade: int = 200

    # Sizing
    max_pct_equity: float = 0.03

    # Backtest metadata
    interval: str = field(default_factory=lambda: INTERVAL)


# ════════════════════════════════════════════════════════════════════
# Sizing (local fixed-risk-%)
# ════════════════════════════════════════════════════════════════════

def graham_size(equity: float, entry: float, stop: float,
                target_pct: float = 0.03) -> float:
    """Fixed-risk-% sizing. Same pattern as KEPOS but with GRAHAM's
    higher target (3% vs 2%) reflecting more frequent entries."""
    if equity <= 0 or not np.isfinite(equity):
        return 0.0
    dist = abs(entry - stop)
    if dist <= 0 or not np.isfinite(dist):
        return 0.0
    return round(equity * target_pct / dist, 4)


# ════════════════════════════════════════════════════════════════════
# Structure: higher-highs / lower-lows counts
# ════════════════════════════════════════════════════════════════════

def _precompute_pivots(highs: np.ndarray, lows: np.ndarray
                       ) -> tuple[np.ndarray, np.ndarray]:
    """Strict 3-bar fractal pivots. Pivot at index i requires i+1 to be
    seen, so the pivot at bar t is only confirmed one bar later — callers
    must use pivots at indices ≤ t-1 when deciding at bar t."""
    n = len(highs)
    is_hi = np.zeros(n, dtype=bool)
    is_lo = np.zeros(n, dtype=bool)
    if n >= 3:
        is_hi[1:-1] = (highs[1:-1] > highs[:-2]) & (highs[1:-1] > highs[2:])
        is_lo[1:-1] = (lows[1:-1] < lows[:-2]) & (lows[1:-1] < lows[2:])
    return is_hi, is_lo


def count_higher_highs(highs: np.ndarray, lookback: int) -> int:
    """Count pivots in last `lookback` bars strictly higher than the prior
    pivot. Uses strict 3-bar fractal. Returns 0 if < 2 pivots in window."""
    if len(highs) < 3:
        return 0
    is_hi, _ = _precompute_pivots(highs, highs)  # lows unused
    end = len(highs)
    start = max(1, end - lookback)
    # Only confirmed pivots (i+1 must exist)
    window_mask = is_hi[start:end - 1]
    window_vals = highs[start:end - 1][window_mask]
    if len(window_vals) < 2:
        return 0
    return int(np.sum(np.diff(window_vals) > 0))


def count_lower_lows(lows: np.ndarray, lookback: int) -> int:
    """Symmetric to count_higher_highs: pivots strictly lower than prior."""
    if len(lows) < 3:
        return 0
    _, is_lo = _precompute_pivots(lows, lows)  # highs unused
    end = len(lows)
    start = max(1, end - lookback)
    window_mask = is_lo[start:end - 1]
    window_vals = lows[start:end - 1][window_mask]
    if len(window_vals) < 2:
        return 0
    return int(np.sum(np.diff(window_vals) < 0))


def _compute_structure_arrays(highs: np.ndarray, lows: np.ndarray,
                              lookback: int) -> tuple[np.ndarray, np.ndarray]:
    """Per-bar HH/LL counts over rolling `lookback` window. Vectorised with
    precomputed pivots and an O(N × lookback) loop (acceptable for our sizes)."""
    n = len(highs)
    is_hi, is_lo = _precompute_pivots(highs, lows)
    hh = np.zeros(n, dtype=int)
    ll = np.zeros(n, dtype=int)
    for t in range(lookback, n):
        lo = t - lookback
        # Use only confirmed pivots: indices i where i+1 <= t, i.e. i in [lo, t-1]
        hi_mask = is_hi[lo:t]
        if hi_mask.sum() >= 2:
            vals = highs[lo:t][hi_mask]
            hh[t] = int(np.sum(np.diff(vals) > 0))
        lo_mask = is_lo[lo:t]
        if lo_mask.sum() >= 2:
            vals = lows[lo:t][lo_mask]
            ll[t] = int(np.sum(np.diff(vals) < 0))
    return hh, ll


# ════════════════════════════════════════════════════════════════════
# Feature computation
# ════════════════════════════════════════════════════════════════════

def compute_features(df: pd.DataFrame, params: GrahamParams) -> pd.DataFrame:
    """Enrich OHLCV with GRAHAM's feature set."""
    df = indicators(df.copy())

    # EMA fast/slow — fast is 21 (already in indicators as ema21), slow 55 local
    df["graham_ema_fast"] = df[f"ema{params.ema_fast}"] if f"ema{params.ema_fast}" in df.columns \
        else df["close"].ewm(span=params.ema_fast, adjust=False).mean()
    df["graham_ema_slow"] = df["close"].ewm(span=params.ema_slow, adjust=False).mean()

    # Slope of ema_fast over lookback bars (fraction per bar)
    ef = df["graham_ema_fast"].values.astype(float)
    slope = np.full(len(df), np.nan)
    lb = params.slope_lookback
    for i in range(lb, len(df)):
        ref = ef[i - lb]
        if ref > 0 and np.isfinite(ref):
            slope[i] = (ef[i] - ref) / ref / lb
    df["graham_slope"] = slope

    # η rolling
    eta = rolling_branching_ratio(
        df,
        window_bars=params.hawkes_window_bars,
        refit_every=params.hawkes_refit_every,
        k_sigma=params.hawkes_k_sigma,
        vol_lookback=params.hawkes_vol_lookback,
        smoothing_span=params.hawkes_smooth_span,
        min_events=params.hawkes_min_events,
    )
    df = df.join(eta[["eta_raw", "eta_smooth", "n_events", "fit_bar"]])

    # Market structure counts
    hh, ll = _compute_structure_arrays(
        df["high"].values.astype(float),
        df["low"].values.astype(float),
        params.structure_lookback,
    )
    df["graham_hh_count"] = hh
    df["graham_ll_count"] = ll

    return df


# ════════════════════════════════════════════════════════════════════
# Entry logic
# ════════════════════════════════════════════════════════════════════

def _eta_sustained_endo(df: pd.DataFrame, t: int,
                        params: GrahamParams) -> bool:
    """η_smooth ∈ [eta_lower, eta_upper) for last N bars ending at t."""
    if params.bypass_eta_gate:
        return True
    need = params.eta_sustained_bars
    if t + 1 < need:
        return False
    window = df["eta_smooth"].iloc[t + 1 - need : t + 1].values
    if np.any(np.isnan(window)):
        return False
    return bool(np.all((window >= params.eta_lower) & (window < params.eta_upper)))


def decide_direction(df: pd.DataFrame, t: int, params: GrahamParams) -> int:
    """+1 LONG, -1 SHORT, 0 no signal.

    Five conditions (all required, bypass_eta_gate skips #1):
      1. η sustained in ENDO band
      2. EMA_fast vs EMA_slow alignment AND close aligned with EMA_fast
      3. |slope| >= slope_min_abs with correct sign
      4. HH count ≥ min (LONG) or LL count ≥ min (SHORT)
      5. No NaNs in core columns
    """
    if t < 1:
        return 0

    close = float(df["close"].iloc[t])
    ef = float(df["graham_ema_fast"].iloc[t])
    es = float(df["graham_ema_slow"].iloc[t])
    slope = float(df["graham_slope"].iloc[t]) if not pd.isna(df["graham_slope"].iloc[t]) else np.nan
    hh = int(df["graham_hh_count"].iloc[t])
    ll = int(df["graham_ll_count"].iloc[t])
    if not np.isfinite(close) or not np.isfinite(ef) or not np.isfinite(es) or not np.isfinite(slope):
        return 0

    if not _eta_sustained_endo(df, t, params):
        return 0

    # LONG
    if ef > es and close > ef and slope > params.slope_min_abs \
            and hh >= params.structure_min_count:
        return +1
    # SHORT
    if ef < es and close < ef and slope < -params.slope_min_abs \
            and ll >= params.structure_min_count:
        return -1
    return 0


def calc_levels(df: pd.DataFrame, t: int, direction: int,
                params: GrahamParams) -> Optional[tuple[float, float]]:
    """Return (entry, stop). No fixed TP — GRAHAM uses trailing + regime exit."""
    if direction == 0 or t + 1 >= len(df):
        return None
    entry = float(df["open"].iloc[t + 1])
    atr = float(df["atr"].iloc[t])
    if not np.isfinite(entry) or not np.isfinite(atr) or atr <= 0:
        return None
    if direction == +1:
        stop = entry - params.stop_atr_mult * atr
    else:
        stop = entry + params.stop_atr_mult * atr
    return entry, stop


# ════════════════════════════════════════════════════════════════════
# Exit logic
# ════════════════════════════════════════════════════════════════════

def update_trailing_stop(trade: dict, high: float, low: float,
                         atr_now: float, params: GrahamParams) -> None:
    """Mutates `trade` in place. Trailing stop activates after ≥ 1 ATR
    of unrealized profit (measured from entry using atr_at_entry); after
    activation, stop trails at TRAIL_ATR_MULT × current ATR from the
    favorable extreme."""
    direction = trade["direction"]
    entry = trade["entry"]
    atr_entry = trade["atr_at_entry"]

    if direction == +1:
        trade["extreme_price"] = max(trade["extreme_price"], high)
        if not trade["trail_active"] and (trade["extreme_price"] - entry) >= atr_entry:
            trade["trail_active"] = True
        if trade["trail_active"] and np.isfinite(atr_now) and atr_now > 0:
            candidate = trade["extreme_price"] - params.trail_atr_mult * atr_now
            if candidate > trade["stop"]:
                trade["stop"] = candidate
    else:
        trade["extreme_price"] = min(trade["extreme_price"], low)
        if not trade["trail_active"] and (entry - trade["extreme_price"]) >= atr_entry:
            trade["trail_active"] = True
        if trade["trail_active"] and np.isfinite(atr_now) and atr_now > 0:
            candidate = trade["extreme_price"] + params.trail_atr_mult * atr_now
            if candidate < trade["stop"]:
                trade["stop"] = candidate


def _regime_exit_check(df: pd.DataFrame, t: int, params: GrahamParams
                       ) -> Optional[str]:
    """Returns 'regime_low', 'regime_crit', or None. Bypass_eta_gate
    disables regime exits too (baseline is pure trend-follower)."""
    if params.bypass_eta_gate:
        return None
    need = params.eta_exit_sustained
    if t + 1 < need:
        return None
    window = df["eta_smooth"].iloc[t + 1 - need : t + 1].values
    if np.any(np.isnan(window)):
        return None
    if bool(np.all(window < params.eta_exit_lower)):
        return "regime_low"
    if bool(np.all(window > params.eta_exit_upper)):
        return "regime_crit"
    return None


def _resolve_exit(df: pd.DataFrame, t: int, trade: dict,
                  params: GrahamParams) -> Optional[tuple[str, float]]:
    """Exit precedence:
      1. Stop hit (trailing or fixed)
      2. Regime-low exit (η dropped out of ENDO band, sustained)
      3. Regime-crit exit (η went above upper — cede to KEPOS-style fade)
      4. Trend break (EMA_fast cross EMA_slow against position)
      5. Time stop
    """
    direction = trade["direction"]
    stop = trade["stop"]
    high = float(df["high"].iloc[t])
    low = float(df["low"].iloc[t])
    close = float(df["close"].iloc[t])

    if direction == +1 and low <= stop:
        return "stop", stop
    if direction == -1 and high >= stop:
        return "stop", stop

    rr = _regime_exit_check(df, t, params)
    if rr == "regime_low":
        return "regime_low", close
    if rr == "regime_crit":
        return "regime_crit", close

    ef = float(df["graham_ema_fast"].iloc[t])
    es = float(df["graham_ema_slow"].iloc[t])
    if direction == +1 and ef < es:
        return "trend_break", close
    if direction == -1 and ef > es:
        return "trend_break", close

    if (t - trade["entry_idx"]) >= params.max_bars_in_trade:
        return "time_stop", close
    return None


# ════════════════════════════════════════════════════════════════════
# Cost model (mirror of KEPOS)
# ════════════════════════════════════════════════════════════════════

def _pnl_with_costs(direction: int, entry: float, exit_p: float, size: float,
                    duration: int, funding_periods_per_8h: float) -> float:
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
# Scan
# ════════════════════════════════════════════════════════════════════

def scan_symbol(df: pd.DataFrame, symbol: str,
                params: Optional[GrahamParams] = None,
                initial_equity: float = ACCOUNT_SIZE) -> tuple[list, dict]:
    """Scan one symbol. df must already have compute_features applied."""
    params = params or GrahamParams()
    trades: list[dict] = []
    vetos: dict[str, int] = defaultdict(int)

    if len(df) < params.hawkes_window_bars + params.structure_lookback + 10:
        log.warning("%s: too few bars (%d); skipping", symbol, len(df))
        return [], {"too_few_bars": 1}

    account = float(initial_equity)
    n = len(df)
    min_idx = max(
        params.hawkes_window_bars,
        params.ema_slow * 5,
        params.structure_lookback,
        200,
    )
    funding_periods_per_8h = 8 * 60 / _TF_MINUTES.get(params.interval, 15)
    open_trade: Optional[dict] = None

    for t in range(min_idx, n - 1):
        if open_trade is not None:
            atr_now = float(df["atr"].iloc[t])
            update_trailing_stop(
                open_trade,
                high=float(df["high"].iloc[t]),
                low=float(df["low"].iloc[t]),
                atr_now=atr_now,
                params=params,
            )
            resolved = _resolve_exit(df, t, open_trade, params)
            if resolved is not None:
                reason, exit_price = resolved
                duration = t - open_trade["entry_idx"]
                pnl = _pnl_with_costs(
                    direction=open_trade["direction"],
                    entry=open_trade["entry"],
                    exit_p=exit_price,
                    size=open_trade["size"],
                    duration=duration,
                    funding_periods_per_8h=funding_periods_per_8h,
                )
                account = max(account + pnl, 0.0)
                open_trade.update({
                    "exit_idx": t,
                    "exit_time": df["time"].iloc[t] if "time" in df.columns else None,
                    "exit_price": round(exit_price, 6),
                    "exit_reason": reason,
                    "duration": duration,
                    "pnl": round(pnl, 4),
                    "result": "WIN" if pnl > 0 else "LOSS",
                    "account_after": round(account, 2),
                })
                trades.append(open_trade)
                open_trade = None
            else:
                continue

        if open_trade is not None:
            continue

        direction = decide_direction(df, t, params)
        if direction == 0:
            vetos["no_signal"] += 1
            continue

        levels = calc_levels(df, t, direction, params)
        if levels is None:
            vetos["levels_unavailable"] += 1
            continue
        entry, stop = levels

        size = graham_size(account, entry, stop, target_pct=params.max_pct_equity)
        if size <= 0:
            vetos["size_zero"] += 1
            continue

        max_notional = account * LEVERAGE
        if size * entry > max_notional and entry > 0:
            size = round(max_notional / entry, 4)
            if size <= 0:
                vetos["size_zero_after_cap"] += 1
                continue

        atr_at_entry = float(df["atr"].iloc[t])
        open_trade = {
            "symbol": symbol,
            "direction": direction,
            "entry_idx": t + 1,
            "entry_time": df["time"].iloc[t + 1] if "time" in df.columns else None,
            "entry": round(entry, 6),
            "stop": round(stop, 6),
            "size": round(size, 4),
            "atr_at_entry": atr_at_entry,
            "eta_at_entry": float(df["eta_smooth"].iloc[t])
                            if not pd.isna(df["eta_smooth"].iloc[t]) else None,
            "slope_at_entry": float(df["graham_slope"].iloc[t]),
            "hh_count": int(df["graham_hh_count"].iloc[t]),
            "ll_count": int(df["graham_ll_count"].iloc[t]),
            "account_at_entry": round(account, 2),
            "extreme_price": entry,
            "trail_active": False,
        }

    # Mark-to-market any still-open trade
    if open_trade is not None:
        exit_idx = len(df) - 1
        exit_price = float(df["close"].iloc[exit_idx])
        duration = exit_idx - open_trade["entry_idx"]
        pnl = _pnl_with_costs(
            direction=open_trade["direction"],
            entry=open_trade["entry"],
            exit_p=exit_price,
            size=open_trade["size"],
            duration=duration,
            funding_periods_per_8h=funding_periods_per_8h,
        )
        account = max(account + pnl, 0.0)
        open_trade.update({
            "exit_idx": exit_idx,
            "exit_time": df["time"].iloc[exit_idx] if "time" in df.columns else None,
            "exit_price": round(exit_price, 6),
            "exit_reason": "forced_mtm",
            "duration": duration,
            "pnl": round(pnl, 4),
            "result": "WIN" if pnl > 0 else "LOSS",
            "account_after": round(account, 2),
            "forced_mtm": True,
        })
        trades.append(open_trade)

    return trades, dict(vetos)


# ════════════════════════════════════════════════════════════════════
# Backtest orchestrator
# ════════════════════════════════════════════════════════════════════

def run_backtest(all_dfs: dict[str, pd.DataFrame],
                 params: Optional[GrahamParams] = None,
                 initial_equity: float = ACCOUNT_SIZE,
                 ) -> tuple[list, dict, dict]:
    params = params or GrahamParams()
    all_trades: list[dict] = []
    all_vetos: dict[str, int] = defaultdict(int)
    per_sym: dict[str, dict] = {}

    for sym, df in all_dfs.items():
        log.info("scanning %s (%d bars)%s", sym, len(df),
                 " [BYPASS η]" if params.bypass_eta_gate else "")
        df_feat = compute_features(df, params)
        trades, vetos = scan_symbol(df_feat, sym, params, initial_equity)
        all_trades.extend(trades)
        for k, v in vetos.items():
            all_vetos[k] += v
        wins = sum(1 for t in trades if t["result"] == "WIN")
        per_sym[sym] = {
            "n_trades": len(trades),
            "wins": wins,
            "losses": len(trades) - wins,
            "pnl": round(sum(t["pnl"] for t in trades), 2),
        }
    return all_trades, dict(all_vetos), per_sym


def compute_summary(trades: list[dict], initial_equity: float = ACCOUNT_SIZE
                    ) -> dict:
    n = len(trades)
    if n == 0:
        return {
            "n_trades": 0, "win_rate": 0.0, "pnl": 0.0, "roi_pct": 0.0,
            "final_equity": initial_equity, "max_dd_pct": 0.0,
            "sharpe": 0.0, "sortino": 0.0,
        }
    pnls = np.asarray([t["pnl"] for t in trades], dtype=float)
    wins = int(np.sum(pnls > 0))
    wr = wins / n * 100.0
    total_pnl = float(pnls.sum())
    final_eq = initial_equity + total_pnl
    roi = total_pnl / initial_equity * 100.0
    equity_curve = initial_equity + np.cumsum(pnls)
    peak = np.maximum.accumulate(equity_curve)
    dd = (peak - equity_curve) / peak
    max_dd_pct = float(dd.max()) * 100.0
    mean_pnl = float(pnls.mean())
    std_pnl = float(pnls.std(ddof=1)) if n > 1 else 0.0
    sharpe = mean_pnl / std_pnl * np.sqrt(n) if std_pnl > 0 else 0.0
    neg = pnls[pnls < 0]
    downside = float(neg.std(ddof=1)) if len(neg) > 1 else 0.0
    sortino = mean_pnl / downside * np.sqrt(n) if downside > 0 else 0.0
    return {
        "n_trades": n,
        "win_rate": round(wr, 2),
        "pnl": round(total_pnl, 2),
        "roi_pct": round(roi, 2),
        "final_equity": round(float(final_eq), 2),
        "max_dd_pct": round(max_dd_pct, 2),
        "sharpe": round(float(sharpe), 3),
        "sortino": round(float(sortino), 3),
    }


# ════════════════════════════════════════════════════════════════════
# Persistence
# ════════════════════════════════════════════════════════════════════

def _trades_to_serializable(trades: list[dict]) -> list[dict]:
    out = []
    for t in trades:
        tt = dict(t)
        for key in ("entry_time", "exit_time"):
            v = tt.get(key)
            if v is None:
                continue
            try:
                tt[key] = pd.Timestamp(v).isoformat()
            except Exception:
                tt[key] = str(v)
        out.append(tt)
    return out


def save_run(run_dir: Path, trades: list[dict], summary: dict,
             params: GrahamParams, vetos: dict, per_sym: dict,
             meta: dict,
             baseline_summary: Optional[dict] = None) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(run_dir / "trades.json",
                 json.dumps(_trades_to_serializable(trades),
                            separators=(",", ":"), default=str))
    payload = {
        "engine": "GRAHAM",
        "version": "0.1.0",
        "run_id": meta.get("run_id"),
        "timestamp": datetime.now().isoformat(),
        "params": asdict(params),
        "summary": summary,
        "per_symbol": per_sym,
        "vetos": vetos,
        "baseline_summary": baseline_summary,
        "meta": meta,
    }
    atomic_write(run_dir / "summary.json",
                 json.dumps(payload, indent=2, default=str))


# ════════════════════════════════════════════════════════════════════
# CLI helpers
# ════════════════════════════════════════════════════════════════════

def _setup_logging(run_dir: Path) -> None:
    fmt = logging.Formatter("%(asctime)s  %(levelname)s  %(message)s")
    fh = logging.FileHandler(run_dir / "log.txt", encoding="utf-8")
    fh.setFormatter(fmt); fh.setLevel(logging.DEBUG)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt); sh.setLevel(logging.INFO)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(fh); root.addHandler(sh)


def _print_summary(label: str, summary: dict) -> None:
    print(f"\n  ┌─ {label} " + "─" * max(0, 50 - len(label)) + "┐")
    print(f"  │ trades      {summary['n_trades']:>10d}")
    print(f"  │ win rate    {summary['win_rate']:>9.1f}%")
    print(f"  │ ROI         {summary['roi_pct']:>+9.2f}%")
    print(f"  │ PnL         ${summary['pnl']:>+12,.2f}")
    print(f"  │ final eq    ${summary['final_equity']:>12,.2f}")
    print(f"  │ max DD      {summary['max_dd_pct']:>9.2f}%")
    print(f"  │ Sharpe      {summary['sharpe']:>10.3f}")
    print(f"  │ Sortino     {summary['sortino']:>10.3f}")
    print("  └" + "─" * 54 + "┘")


def _print_comparison(graham: dict, baseline: dict) -> None:
    print("\n  ┌─ GRAHAM vs BASELINE (η-gate bypassed) " + "─" * 15 + "┐")
    rows = [
        ("n_trades",    "{:>10d}",   "{:>10d}",   ""),
        ("win_rate",    "{:>9.1f}%", "{:>9.1f}%", "%"),
        ("roi_pct",     "{:>+9.2f}%","{:>+9.2f}%","%"),
        ("sharpe",      "{:>10.3f}", "{:>10.3f}", ""),
        ("sortino",     "{:>10.3f}", "{:>10.3f}", ""),
        ("max_dd_pct",  "{:>9.2f}%", "{:>9.2f}%", ""),
    ]
    print(f"  │ {'metric':<12s}  {'GRAHAM':>14s}  {'BASELINE':>14s}  "
          f"{'Δ':>10s}")
    for key, gfmt, bfmt, unit in rows:
        g = graham[key]; b = baseline[key]
        if isinstance(g, (int, float)) and isinstance(b, (int, float)):
            diff = g - b
            print(f"  │ {key:<12s}  {gfmt.format(g):>14s}  "
                  f"{bfmt.format(b):>14s}  {diff:>+10.3f}{unit}")
    # Verdict
    h2_passes = (graham["sharpe"] > baseline["sharpe"]
                 and graham["sortino"] > baseline["sortino"]
                 and graham["win_rate"] >= baseline["win_rate"])
    print(f"  │")
    print(f"  │ H2 edge (GRAHAM strictly better on 3 metrics): "
          f"{'PASS' if h2_passes else 'FAIL'}")
    print("  └" + "─" * 62 + "┘")


def main() -> int:
    ap = argparse.ArgumentParser(description="GRAHAM — Endogenous Momentum")
    ap.add_argument("--days", type=int, default=SCAN_DAYS)
    ap.add_argument("--basket", type=str, default="bluechip")
    ap.add_argument("--interval", type=str, default=None,
                    help="Timeframe override (e.g. 1h, 15m). Default from config.params.INTERVAL")
    ap.add_argument("--no-menu", action="store_true")
    ap.add_argument("--k-sigma", type=float, default=None)
    ap.add_argument("--eta-lower", type=float, default=None)
    ap.add_argument("--eta-upper", type=float, default=None)
    ap.add_argument("--eta-exit-lower", type=float, default=None)
    ap.add_argument("--eta-exit-upper", type=float, default=None)
    ap.add_argument("--eta-sustained", type=int, default=None)
    ap.add_argument("--slope-min", type=float, default=None,
                    help="Override slope_min_abs threshold")
    ap.add_argument("--compare-baseline", action="store_true",
                    help="Also run GRAHAM with η gate bypassed and print comparison")
    args = ap.parse_known_args()[0]

    basket_name = args.basket or "default"
    symbols = BASKETS.get(basket_name, SYMBOLS)
    scan_days = int(args.days)
    interval = args.interval or INTERVAL
    tf_min = max(1, _TF_MINUTES.get(interval, 15))
    n_candles = scan_days * 24 * 60 // tf_min

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    run_id = f"graham_{stamp}"
    from config.paths import DATA_DIR
    run_dir = DATA_DIR / "graham" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _setup_logging(run_dir)

    params = GrahamParams()
    params.interval = interval
    if args.k_sigma is not None:
        params.hawkes_k_sigma = float(args.k_sigma)
    if args.eta_lower is not None:
        params.eta_lower = float(args.eta_lower)
    if args.eta_upper is not None:
        params.eta_upper = float(args.eta_upper)
    if args.eta_exit_lower is not None:
        params.eta_exit_lower = float(args.eta_exit_lower)
    if args.eta_exit_upper is not None:
        params.eta_exit_upper = float(args.eta_exit_upper)
    if args.eta_sustained is not None:
        params.eta_sustained_bars = int(args.eta_sustained)
    if args.slope_min is not None:
        params.slope_min_abs = float(args.slope_min)
    if params.eta_upper <= params.eta_lower:
        raise SystemExit("eta-upper must be > eta-lower")

    print()
    print("  ╔════════════════════════════════════════════════════════════╗")
    print("  ║ GRAHAM · Endogenous Momentum · AURUM Finance               ║")
    print("  ╠════════════════════════════════════════════════════════════╣")
    print(f"  ║ UNIVERSE   {len(symbols)} assets (basket: {basket_name})")
    print(f"  ║ PERIOD     {scan_days}d · {n_candles:,} candles/asset · {params.interval}")
    print(f"  ║ GATE η     [{params.eta_lower}, {params.eta_upper}) sustained {params.eta_sustained_bars}b")
    print(f"  ║            k_sigma={params.hawkes_k_sigma}")
    print(f"  ║ TREND      ema{params.ema_fast}/ema{params.ema_slow} + slope≥{params.slope_min_abs}")
    print(f"  ║ STRUCT     ≥{params.structure_min_count} HH/LL in last {params.structure_lookback}b")
    print(f"  ║ SIZING     fixed {params.max_pct_equity*100:.1f}% equity risk (local)")
    print(f"  ║ EXITS      trail {params.trail_atr_mult}xATR · stop {params.stop_atr_mult}xATR")
    print(f"  ║            regime_low η<{params.eta_exit_lower} · regime_crit η>{params.eta_exit_upper}")
    print("  ╚════════════════════════════════════════════════════════════╝")

    print(f"\n  fetching {len(symbols)} symbols @ {interval} ...")
    all_dfs = fetch_all(symbols, interval=interval,
                        n_candles=n_candles, futures=True)
    if not all_dfs:
        print("  no data fetched.")
        return 1
    for s, df in all_dfs.items():
        validate(df, s)

    print(f"  running GRAHAM scan on {len(all_dfs)} symbols ...")
    trades, vetos, per_sym = run_backtest(all_dfs, params, ACCOUNT_SIZE)
    summary = compute_summary(trades, ACCOUNT_SIZE)
    _print_summary(f"GRAHAM summary ({run_id})", summary)

    baseline_summary = None
    if args.compare_baseline:
        print(f"\n  running BASELINE scan (η gate bypassed) ...")
        params_baseline = GrahamParams(**asdict(params))
        params_baseline.bypass_eta_gate = True
        b_trades, b_vetos, b_per_sym = run_backtest(
            all_dfs, params_baseline, ACCOUNT_SIZE,
        )
        baseline_summary = compute_summary(b_trades, ACCOUNT_SIZE)
        _print_summary("BASELINE (trend without η gate)", baseline_summary)
        _print_comparison(summary, baseline_summary)

    if per_sym:
        print("\n  GRAHAM per symbol:")
        for s, st in sorted(per_sym.items()):
            print(f"    {s:<12s}  n={st['n_trades']:>3d}  "
                  f"W={st['wins']:>2d}  L={st['losses']:>2d}  "
                  f"pnl=${st['pnl']:>+10,.2f}")
    if vetos:
        print("\n  vetoes:")
        for k, v in sorted(vetos.items(), key=lambda kv: -kv[1])[:5]:
            print(f"    {k:<22s}  {v:>6d}")

    save_run(run_dir, trades, summary, params, vetos, per_sym,
             meta={"run_id": run_id, "basket": basket_name,
                   "scan_days": scan_days, "symbols": list(all_dfs.keys()),
                   "compared_to_baseline": args.compare_baseline},
             baseline_summary=baseline_summary)
    print(f"\n  run → {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
