"""
MEDALLION — Berlekamp-Laufer Short-Term Mean-Reversion Engine (AURUM Finance)
=============================================================================
Faithful to the 1988-1990 Medallion Fund redesign under Elwyn Berlekamp and
Henry Laufer, documented in Zuckerman's "The Man Who Solved the Market".

The four Simons/Medallion pillars — implemented verbatim:

  1. SHORT HORIZON
     Intraday to a few bars. Time stop is tight; if the reversal doesn't
     come fast, the premise is broken.

  2. NEGATIVE SHORT-TERM AUTOCORRELATION
     Prices overreact on short scales and revert. The engine verifies this
     property is currently TRUE for the asset (rolling ρ(r_t, r_{t-1}) ≤
     threshold) before fading — not assumed.

  3. MANY SMALL EDGES AGGREGATED
     No single indicator drives a trade. A composite "ensemble_score"
     combines seven independent micro-signals (return z, volume z, EMA
     deviation, autocorrelation, RSI extreme, intraday seasonality,
     HMM chop probability). Each is tiny; the sum is statistically strong.

  4. KELLY SIZING
     Position size is fractional-Kelly over rolling empirical win-rate and
     payoff ratio per symbol. Falls back to conservative priors when the
     sample is too small. Hard-capped by max_pct_equity.

The result: short-term fade of overextended moves in chop regimes, sized
by Kelly, gated by empirical verification that the asset is CURRENTLY
mean-reverting. No single-indicator heroics — the aggregate does the work.

Discipline
----------
- Local Kelly-based sizing. No coupling to CITADEL's `position_size` / Ω.
- AURUM cost model (C1+C2: slippage + spread + commission + funding with
  LEVERAGE) — imported from config.params, never re-implemented.
- Backtest-first. Not in ENGINE_INTERVALS/ENGINE_BASKETS/FROZEN_ENGINES
  until 6/6 overfit audit passes.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict, deque
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
from core.ops.fs import atomic_write
from core.indicators import indicators

log = logging.getLogger("MEDALLION")
_tl = logging.getLogger("MEDALLION.trades")


# ════════════════════════════════════════════════════════════════════
# Parameters — every knob Berlekamp/Laufer would have tuned
# ════════════════════════════════════════════════════════════════════

@dataclass
class MedallionParams:
    """MEDALLION tunable parameters. Defaults are conservative priors; a
    post-calibration walk-forward would refine them per-symbol or per-regime.
    """

    # ── Return overshoot (pillar #1 + #2 detection) ──
    z_lookback: int = 10           # bars used for cum return (short horizon)
    z_sigma_window: int = 200      # σ baseline
    z_entry_min: float = 1.2       # min |z| to consider overshoot

    # ── Autocorrelation regime gate (pillar #2 verification) ──
    autocorr_window: int = 200     # bars for rolling ρ(r_t, r_{t-1})
    autocorr_max: float = 0.0      # require ρ ≤ this (non-positive) to confirm
                                   # mean-revert regime currently holds

    # ── Volume confirmation ──
    vol_window: int = 100
    vol_z_min: float = 1.0         # volume must be ≥ this z to count

    # ── EMA micro-overextension ──
    ema_fast: int = 20
    ema_dev_sigma_window: int = 100

    # ── RSI extreme ──
    rsi_period: int = 14           # passes through core.indicators
    rsi_extreme_min: float = 15.0  # |rsi - 50| must be ≥ this

    # ── Intraday seasonality ──
    seasonality_lookback: int = 500
    seasonality_min_samples: int = 20

    # ── HMM regime gate (pillar #3: ensemble dimension) ──
    hmm_enabled: bool = True
    hmm_min_prob_chop: float = 0.30     # prob(CHOP) required when enabled
    hmm_max_prob_trend: float = 0.75    # veto if BULL or BEAR too confident

    # ── Trend filter (avoid trending regimes entirely) ──
    trend_ema: int = 200
    trend_slope_max: float = 0.15  # |slope200 / close| × 1000 ≤ this (flat)

    # ── Ensemble composition (pillar #3 core) ──
    w_z_return: float = 0.30
    w_z_vol: float = 0.15
    w_ema_dev: float = 0.15
    w_autocorr: float = 0.10
    w_rsi: float = 0.10
    w_seasonality: float = 0.10
    w_hmm_chop: float = 0.10
    ensemble_threshold: float = 0.45  # tuned so ~2-4 trades/sym/month @ 15m
    min_active_components: int = 4

    # ── Exit ──
    stop_atr_mult: float = 1.0
    tp_atr_mult: float = 0.8       # shorter than stop: capture partial revert
    max_bars_in_trade: int = 8     # pillar #1 — short horizon
    exit_on_signal_flip: bool = True
    exit_on_hmm_trend: bool = True
    hmm_exit_trend_prob: float = 0.75

    # ── Kelly sizing (pillar #4) ──
    kelly_fraction: float = 0.25           # quarter-Kelly (safety)
    kelly_rolling_trades: int = 30         # recent N trades for p, b estimate
    kelly_min_trades: int = 10             # min before leaving prior
    kelly_prior_p: float = 0.56            # pre-data win rate estimate
    kelly_prior_b: float = 1.0             # pre-data avg_win / avg_loss
                                           # NOTE: priors must satisfy
                                           # p > 1/(1+b) else Kelly ≤ 0 and
                                           # engine vetoes every entry.
    max_pct_equity: float = 0.02           # hard cap on fraction per trade

    # ── Cooldown (avoid overtrading same setup) ──
    cooldown_bars: int = 4

    # ── Direction inversion (diagnostic — flips fade into momentum) ──
    # NOT a production knob. Only used during calibration to test whether
    # the asset/timeframe mean-reverts at all. If invert=True outperforms
    # invert=False on this instrument, MEDALLION's thesis does NOT hold
    # for that instrument and it should not be run there.
    invert_direction: bool = False

    # ── Metadata ──
    interval: str = field(default_factory=lambda: INTERVAL)


# ════════════════════════════════════════════════════════════════════
# Kelly sizing — rolling empirical with conservative prior fallback
# ════════════════════════════════════════════════════════════════════

def medallion_kelly_fraction(recent_pnls: list[float],
                             params: MedallionParams) -> float:
    """Fractional-Kelly fraction of equity to risk on next trade.

    Uses rolling empirical (p, b) from last ``kelly_rolling_trades`` PnLs
    when the sample is ≥ kelly_min_trades; otherwise falls back to
    conservative priors. Applied fraction is multiplied by ``kelly_fraction``
    (quarter-Kelly default) and clamped to [0, max_pct_equity].

    Pure function — no dataframe, no state. Easy to unit-test.
    """
    f_cap = params.max_pct_equity

    if len(recent_pnls) >= params.kelly_min_trades:
        tail = recent_pnls[-params.kelly_rolling_trades:]
        wins = [p for p in tail if p > 0]
        losses = [p for p in tail if p < 0]
        if not wins or not losses:
            p = params.kelly_prior_p
            b = params.kelly_prior_b
        else:
            p = len(wins) / len(tail)
            avg_w = float(np.mean(wins))
            avg_l = float(abs(np.mean(losses)))
            b = avg_w / avg_l if avg_l > 0 else params.kelly_prior_b
    else:
        p = params.kelly_prior_p
        b = params.kelly_prior_b

    q = 1.0 - p
    f_star = p - q / b if b > 0 else 0.0  # classic Kelly for binary bets
    f = max(0.0, f_star) * params.kelly_fraction
    if len(recent_pnls) >= params.kelly_min_trades:
        tail = recent_pnls[-params.kelly_rolling_trades:]
        expectancy = float(np.mean(tail)) if tail else 0.0
        loss_rate = sum(1 for pnl in tail if pnl < 0) / len(tail) if tail else 0.0
        if expectancy <= 0:
            f *= 0.5
        if loss_rate >= 0.55:
            f *= 0.75
    return float(min(f, f_cap))


def medallion_size(equity: float, entry: float, stop: float,
                   kelly_f: float) -> float:
    """Units to trade given Kelly fraction and stop distance."""
    if equity <= 0 or kelly_f <= 0 or not np.isfinite(equity):
        return 0.0
    dist = abs(entry - stop)
    if dist <= 0 or not np.isfinite(dist):
        return 0.0
    return round(equity * kelly_f / dist, 4)


# ════════════════════════════════════════════════════════════════════
# Feature computation — the seven micro-signals
# ════════════════════════════════════════════════════════════════════

def compute_features(df: pd.DataFrame, params: MedallionParams) -> pd.DataFrame:
    """Enrich OHLCV with every micro-signal the ensemble consumes.

    Adds:
      atr, ema*, rsi, vol_regime           (from core.indicators)
      med_z_return                         short-horizon overshoot z-score
      med_z_vol                            volume surge z-score
      med_ema_dev_z                        close vs EMA_fast in σ units
      med_autocorr                         rolling ρ(r_t, r_{t-1})
      med_rsi_ext                          |rsi - 50| normalized
      med_seasonality_z                    hour-of-day return anomaly
      med_prob_chop                        HMM P(CHOP)  (or NaN if disabled)
      med_trend_flat                       bool: 1 if |slope200| flat enough
      med_ensemble_score                   signed aggregate

    All denominators use shift(1) to prevent look-ahead on the current bar.
    """
    df = indicators(df.copy())
    close = df["close"].astype(float)
    n = len(df)

    # ── (1) short-horizon return z-score ──
    cum_n = np.log(close / close.shift(params.z_lookback))
    sigma_cum = cum_n.rolling(
        params.z_sigma_window, min_periods=params.z_sigma_window // 2
    ).std().shift(1)
    df["med_z_return"] = cum_n / sigma_cum.replace(0, np.nan)

    # ── (2) volume surge z-score ──
    vol = df["vol"].astype(float) if "vol" in df.columns else pd.Series(
        np.ones(n), index=df.index)
    vol_mean = vol.rolling(params.vol_window,
                           min_periods=params.vol_window // 2).mean().shift(1)
    vol_std = vol.rolling(params.vol_window,
                          min_periods=params.vol_window // 2).std().shift(1)
    df["med_z_vol"] = (vol - vol_mean) / vol_std.replace(0, np.nan)

    # ── (3) EMA deviation in σ units ──
    ema_col = f"ema{params.ema_fast}"
    if ema_col not in df.columns:
        df[ema_col] = close.ewm(span=params.ema_fast, adjust=False).mean()
    dev = close - df[ema_col].astype(float)
    dev_sigma = dev.rolling(params.ema_dev_sigma_window,
                            min_periods=params.ema_dev_sigma_window // 2
                            ).std().shift(1)
    df["med_ema_dev_z"] = dev / dev_sigma.replace(0, np.nan)

    # ── (4) rolling lag-1 autocorrelation of returns ──
    rets = np.log(close / close.shift(1))
    df["med_autocorr"] = rets.rolling(
        params.autocorr_window,
        min_periods=params.autocorr_window // 2,
    ).apply(
        lambda x: float(np.corrcoef(x[:-1], x[1:])[0, 1])
                  if np.std(x[:-1]) > 0 and np.std(x[1:]) > 0 else np.nan,
        raw=True,
    ).shift(1)

    # ── (5) RSI extreme ──
    rsi = df["rsi"].astype(float) if "rsi" in df.columns else pd.Series(
        np.full(n, 50.0), index=df.index)
    df["med_rsi_ext"] = (rsi - 50.0).abs() / 50.0  # ∈ [0, 1]

    # ── (6) intraday seasonality (hour-of-day return z-score) ──
    if "time" in df.columns:
        times = pd.to_datetime(df["time"])
        hours = times.dt.hour
        # Rolling hour-of-day mean/std from the LAST N bars, computed once
        # up to each index. This is approximate — a truly rigorous version
        # groups by hour and rolls per-group. For an ensemble weighted at
        # ~10% this is enough signal.
        rets_filled = rets.fillna(0.0)
        grp = rets_filled.groupby(hours)
        h_mean = grp.transform(lambda s: s.expanding(
            min_periods=params.seasonality_min_samples).mean().shift(1))
        h_std = grp.transform(lambda s: s.expanding(
            min_periods=params.seasonality_min_samples).std().shift(1))
        df["med_seasonality_z"] = (rets_filled - h_mean) / h_std.replace(0, np.nan)
    else:
        df["med_seasonality_z"] = np.nan

    # ── (7) HMM chop probability ──
    if params.hmm_enabled:
        try:
            from core.chronos import enrich_with_regime
            df = enrich_with_regime(df)
            df["med_prob_chop"] = df.get("hmm_prob_chop", pd.Series(np.nan, index=df.index))
        except Exception as e:
            log.warning("HMM unavailable (%s) — disabling chop feature.", e)
            df["med_prob_chop"] = np.nan
    else:
        df["med_prob_chop"] = np.nan

    # ── Trend filter (hard veto if trending) ──
    if f"ema{params.trend_ema}" in df.columns:
        ema_trend = df[f"ema{params.trend_ema}"].astype(float)
    else:
        ema_trend = close.ewm(span=params.trend_ema, adjust=False).mean()
    slope = ema_trend.diff(10) / 10.0
    slope_norm = (slope.abs() / close).replace([np.inf, -np.inf], np.nan) * 1000
    df["med_trend_flat"] = (slope_norm <= params.trend_slope_max).astype(float)

    # ── Ensemble aggregation (SIGNED by direction of overshoot) ──
    # Each sub-signal is normalized to ~[0, 1] scale via clip(|.|/cap, 0, 1)
    # so a single blown-out feature can't dominate.
    def _clip01(s: pd.Series, cap: float) -> pd.Series:
        return (s.abs() / cap).clip(lower=0.0, upper=1.0).fillna(0.0)

    z_ret_sc = _clip01(df["med_z_return"], 3.0)
    z_vol_sc = _clip01(df["med_z_vol"], 3.0)
    ema_sc = _clip01(df["med_ema_dev_z"], 3.0)
    # autocorr: we WANT negative. reward = max(0, -autocorr / 0.10)
    ac_raw = -df["med_autocorr"].clip(upper=0).fillna(0.0)
    ac_sc = (ac_raw / 0.10).clip(lower=0.0, upper=1.0)
    rsi_sc = df["med_rsi_ext"].clip(lower=0.0, upper=1.0).fillna(0.0)
    seas_sc = _clip01(df["med_seasonality_z"], 3.0)
    chop_sc = df["med_prob_chop"].fillna(0.5).clip(lower=0.0, upper=1.0)

    magnitude = (
        params.w_z_return * z_ret_sc
        + params.w_z_vol * z_vol_sc
        + params.w_ema_dev * ema_sc
        + params.w_autocorr * ac_sc
        + params.w_rsi * rsi_sc
        + params.w_seasonality * seas_sc
        + params.w_hmm_chop * chop_sc
    )

    # Sign: fade direction of z_return (positive overshoot → short signal,
    # negative overshoot → long signal). Signal = -sign(z_return) × magnitude.
    sign = -np.sign(df["med_z_return"].fillna(0.0))
    df["med_ensemble_score"] = sign * magnitude
    df["med_ensemble_mag"] = magnitude

    return df


# ════════════════════════════════════════════════════════════════════
# Entry logic
# ════════════════════════════════════════════════════════════════════

def decide_direction(df: pd.DataFrame, t: int,
                     params: MedallionParams) -> int:
    """Return +1 (LONG), -1 (SHORT) or 0 (no signal) at bar t.

    All gates must pass:
      (A) trend filter: not in trending regime (slope200 flat)
      (B) autocorr regime: rolling ρ ≤ autocorr_max (mean-revert currently active)
      (C) overshoot magnitude: |z_return| ≥ z_entry_min
      (D) volume confirmation: z_vol ≥ vol_z_min
      (E) RSI extreme: |rsi - 50| ≥ rsi_extreme_min
      (F) HMM regime (if enabled): prob_chop ≥ hmm_min_prob_chop
          AND max(prob_bull, prob_bear) ≤ hmm_max_prob_trend
      (G) ensemble: |score| ≥ ensemble_threshold

    Direction is the signed ensemble score — already a FADE of the overshoot.
    """
    if t < 1:
        return 0

    row = df.iloc[t]

    # (A) trend flat
    if float(row.get("med_trend_flat", 0.0)) < 1.0:
        return 0

    # (B) autocorr currently negative
    ac = float(row.get("med_autocorr", np.nan))
    if not np.isfinite(ac) or ac > params.autocorr_max:
        return 0

    # (C) overshoot magnitude
    z_ret = float(row.get("med_z_return", np.nan))
    if not np.isfinite(z_ret) or abs(z_ret) < params.z_entry_min:
        return 0

    # (D) volume climax
    z_vol = float(row.get("med_z_vol", np.nan))
    if not np.isfinite(z_vol) or z_vol < params.vol_z_min:
        return 0

    # (E) RSI extreme
    if "rsi" in df.columns:
        rsi = float(df["rsi"].iloc[t])
        if np.isfinite(rsi) and abs(rsi - 50.0) < params.rsi_extreme_min:
            return 0

    # (F) HMM regime gate
    if params.hmm_enabled:
        pc = float(row.get("hmm_prob_chop", np.nan))
        pb = float(row.get("hmm_prob_bull", np.nan))
        pbr = float(row.get("hmm_prob_bear", np.nan))
        if np.isfinite(pc) and pc < params.hmm_min_prob_chop:
            return 0
        if np.isfinite(pb) and pb > params.hmm_max_prob_trend:
            return 0
        if np.isfinite(pbr) and pbr > params.hmm_max_prob_trend:
            return 0

    # (G) ensemble threshold
    score = float(row.get("med_ensemble_score", 0.0))
    if abs(score) < params.ensemble_threshold:
        return 0

    ema_dev = float(row.get("med_ema_dev_z", np.nan))
    seas = float(row.get("med_seasonality_z", np.nan))
    active_components = 0
    active_components += int(abs(z_ret) >= params.z_entry_min)
    active_components += int(np.isfinite(z_vol) and z_vol >= params.vol_z_min)
    active_components += int(np.isfinite(ema_dev) and abs(ema_dev) >= 1.0)
    active_components += int(np.isfinite(ac) and ac <= params.autocorr_max)
    if "rsi" in df.columns:
        active_components += int(np.isfinite(rsi) and abs(rsi - 50.0) >= params.rsi_extreme_min)
    active_components += int(np.isfinite(seas) and abs(seas) >= 0.75)
    if params.hmm_enabled:
        active_components += int(np.isfinite(pc) and pc >= params.hmm_min_prob_chop)
    if active_components < params.min_active_components:
        return 0

    direction = +1 if score > 0 else -1
    return -direction if params.invert_direction else direction


def calc_levels(df: pd.DataFrame, t: int, direction: int,
                params: MedallionParams
                ) -> Optional[tuple[float, float, float]]:
    """Return (entry, stop, tp). Entry is next-bar open; stop/tp ATR-based."""
    if direction == 0 or t + 1 >= len(df):
        return None
    entry = float(df["open"].iloc[t + 1])
    atr = float(df["atr"].iloc[t])
    if not np.isfinite(entry) or not np.isfinite(atr) or atr <= 0:
        return None

    if direction == +1:
        stop = entry - params.stop_atr_mult * atr
        tp_floor = entry + params.tp_atr_mult * atr
        ema_target = float(df.get(f"ema{params.ema_fast}", pd.Series(np.nan, index=df.index)).iloc[t])
        tp = max(tp_floor, ema_target) if np.isfinite(ema_target) and ema_target > entry else tp_floor
    else:
        stop = entry + params.stop_atr_mult * atr
        tp_floor = entry - params.tp_atr_mult * atr
        ema_target = float(df.get(f"ema{params.ema_fast}", pd.Series(np.nan, index=df.index)).iloc[t])
        tp = min(tp_floor, ema_target) if np.isfinite(ema_target) and ema_target < entry else tp_floor
    return entry, stop, tp


# ════════════════════════════════════════════════════════════════════
# Exit logic
# ════════════════════════════════════════════════════════════════════

def _resolve_exit(df: pd.DataFrame, bar_idx: int,
                  entry_idx: int, direction: int,
                  entry: float, stop: float, tp: float,
                  params: MedallionParams) -> Optional[tuple[str, float]]:
    """Exit precedence within a bar:
         1. stop hit (conservative: stop wins if both stop & tp in same bar)
         2. take-profit hit
         3. signal flip (composite score reverses sign strongly)
         4. time stop (bars_in_trade ≥ max_bars_in_trade)

    Never exits on the entry bar itself.
    """
    if bar_idx <= entry_idx:
        return None

    high = float(df["high"].iloc[bar_idx])
    low = float(df["low"].iloc[bar_idx])
    close = float(df["close"].iloc[bar_idx])

    stop_hit = (low <= stop) if direction == +1 else (high >= stop)
    tp_hit = (high >= tp) if direction == +1 else (low <= tp)

    if stop_hit:
        return "stop", stop
    if tp_hit:
        return "tp", tp

    if params.exit_on_signal_flip:
        score = float(df["med_ensemble_score"].iloc[bar_idx])
        # Flip = score has opposite sign of the position, and magnitude ≥ half threshold
        flipped = (direction == +1 and score < -0.5 * params.ensemble_threshold) \
               or (direction == -1 and score > 0.5 * params.ensemble_threshold)
        if flipped:
            return "signal_flip", close

    if params.exit_on_hmm_trend and params.hmm_enabled:
        pb = float(df.get("hmm_prob_bull", pd.Series(np.nan, index=df.index)).iloc[bar_idx])
        pbr = float(df.get("hmm_prob_bear", pd.Series(np.nan, index=df.index)).iloc[bar_idx])
        if direction == +1 and np.isfinite(pbr) and pbr >= params.hmm_exit_trend_prob:
            return "hmm_trend_exit", close
        if direction == -1 and np.isfinite(pb) and pb >= params.hmm_exit_trend_prob:
            return "hmm_trend_exit", close

    if (bar_idx - entry_idx) >= params.max_bars_in_trade:
        return "time_stop", close

    return None


# ════════════════════════════════════════════════════════════════════
# Scan a single symbol
# ════════════════════════════════════════════════════════════════════

def scan_symbol(df: pd.DataFrame, symbol: str,
                params: Optional[MedallionParams] = None,
                initial_equity: float = ACCOUNT_SIZE) -> tuple[list, dict]:
    """Scan one symbol, return (trades, veto_counts)."""
    params = params or MedallionParams()
    trades: list[dict] = []
    vetos: dict[str, int] = defaultdict(int)

    min_bars = max(params.z_sigma_window, params.autocorr_window,
                   params.trend_ema, params.vol_window) + 50
    if len(df) < min_bars:
        log.warning("%s: too few bars (%d < %d); skipping", symbol, len(df), min_bars)
        return [], {"too_few_bars": 1}

    account = float(initial_equity)
    n = len(df)
    min_idx = min_bars

    funding_periods_per_8h = 8 * 60 / _TF_MINUTES.get(params.interval, 15)

    open_trade: Optional[dict] = None
    last_exit_idx = -10 ** 9
    recent_pnls: deque = deque(maxlen=params.kelly_rolling_trades)

    for t in range(min_idx, n - 1):
        # ── Manage open position first ──
        if open_trade is not None:
            resolved = _resolve_exit(
                df, t,
                entry_idx=open_trade["entry_idx"],
                direction=open_trade["direction"],
                entry=open_trade["entry"],
                stop=open_trade["stop"],
                tp=open_trade["tp"],
                params=params,
            )
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
                recent_pnls.append(pnl)
                last_exit_idx = t
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
                if _tl.handlers:
                    _tl.info(
                        "  %s %s %+d  exit=%s  pnl=%+.2f  dur=%dbars",
                        symbol,
                        open_trade.get("entry_time", ""),
                        open_trade["direction"], reason, pnl, duration,
                    )
                open_trade = None
            else:
                continue  # still holding, no new signal check

        if open_trade is not None:
            continue

        # ── Cooldown ──
        if (t - last_exit_idx) < params.cooldown_bars:
            vetos["cooldown"] += 1
            continue

        # ── Entry ──
        direction = decide_direction(df, t, params)
        if direction == 0:
            vetos["no_signal"] += 1
            continue

        levels = calc_levels(df, t, direction, params)
        if levels is None:
            vetos["levels_unavailable"] += 1
            continue
        entry, stop, tp = levels

        # ── Kelly sizing from rolling recent PnLs ──
        kelly_f = medallion_kelly_fraction(list(recent_pnls), params)
        if kelly_f <= 0.0:
            vetos["kelly_zero"] += 1
            continue
        size = medallion_size(account, entry, stop, kelly_f)
        if size <= 0:
            vetos["size_zero"] += 1
            continue

        # Notional cap: never exceed account × LEVERAGE even when Kelly wants more
        max_notional = account * LEVERAGE
        if size * entry > max_notional and entry > 0:
            size = round(max_notional / entry, 4)
            if size <= 0:
                vetos["size_zero_after_cap"] += 1
                continue

        open_trade = {
            "symbol": symbol,
            "direction": direction,
            "entry_idx": t + 1,
            "entry_time": df["time"].iloc[t + 1] if "time" in df.columns else None,
            "entry": round(entry, 6),
            "stop": round(stop, 6),
            "tp": round(tp, 6),
            "size": round(size, 4),
            "kelly_f": round(kelly_f, 5),
            "ensemble_score": float(df["med_ensemble_score"].iloc[t]),
            "z_return": float(df["med_z_return"].iloc[t]),
            "autocorr": float(df["med_autocorr"].iloc[t]),
            "prob_chop": float(df.get("hmm_prob_chop", pd.Series(np.nan, index=df.index)).iloc[t])
                         if params.hmm_enabled else None,
            "atr": float(df["atr"].iloc[t]),
            "account_at_entry": round(account, 2),
        }

    # Mark-to-market any trade still open at the end
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


def _pnl_with_costs(direction: int, entry: float, exit_p: float, size: float,
                    duration: int, funding_periods_per_8h: float) -> float:
    """AURUM C1+C2 cost model — simétrico entry/exit.

    Nota 2026-04-17: versão anterior aplicava slip só no exit. MEDALLION
    entra em market order (open[t+1]) — precisa pagar slip+spread nos dois
    lados. Fix reduz Sharpe in-sample em alguns pontos decimais mas é
    honesto. Ver docs/audits/2026-04-17_oos_revalidation.md seção cost
    symmetry.
    """
    slip_entry = SLIPPAGE + SPREAD
    slip_exit = SLIPPAGE + SPREAD
    if direction == +1:
        entry_cost = entry * (1 + COMMISSION + slip_entry)
        exit_net = exit_p * (1 - COMMISSION - slip_exit)
        funding = -(size * entry * FUNDING_PER_8H * duration / funding_periods_per_8h)
        pnl = size * (exit_net - entry_cost) + funding
    else:
        entry_cost = entry * (1 - COMMISSION - slip_entry)
        exit_net = exit_p * (1 + COMMISSION + slip_exit)
        funding = +(size * entry * FUNDING_PER_8H * duration / funding_periods_per_8h)
        pnl = size * (entry_cost - exit_net) + funding
    return float(pnl * LEVERAGE)


# ════════════════════════════════════════════════════════════════════
# Backtest orchestrator
# ════════════════════════════════════════════════════════════════════

def run_backtest(
    all_dfs: dict[str, pd.DataFrame],
    params: Optional[MedallionParams] = None,
    initial_equity: float = ACCOUNT_SIZE,
) -> tuple[list, dict, dict]:
    """Run MEDALLION across all symbols. Returns (trades, vetos, per_sym)."""
    params = params or MedallionParams()
    all_trades: list[dict] = []
    all_vetos: dict[str, int] = defaultdict(int)
    per_sym: dict[str, dict] = {}

    for sym, df in all_dfs.items():
        log.info("scanning %s (%d bars)", sym, len(df))
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


# ════════════════════════════════════════════════════════════════════
# Summary metrics (same shape as KEPOS)
# ════════════════════════════════════════════════════════════════════

def compute_summary(trades: list[dict],
                    initial_equity: float = ACCOUNT_SIZE) -> dict:
    n = len(trades)
    if n == 0:
        return {"n_trades": 0, "win_rate": 0.0, "pnl": 0.0, "roi_pct": 0.0,
                "final_equity": initial_equity, "max_dd_pct": 0.0,
                "sharpe": 0.0, "sortino": 0.0}

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
             params: MedallionParams, vetos: dict, per_sym: dict,
             meta: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    serializable = _trades_to_serializable(trades)
    atomic_write(run_dir / "trades.json",
                 json.dumps(serializable, separators=(",", ":"), default=str))

    payload = {
        "engine": "MEDALLION",
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

    try:
        from core.ops.run_manager import append_to_index, snapshot_config
        config_snapshot = snapshot_config()
        config_snapshot["MEDALLION_PARAMS"] = asdict(params)
        append_to_index(run_dir, {
            **summary,
            "engine": "MEDALLION",
            "basket": meta.get("basket"),
            "interval": params.interval,
            "period_days": meta.get("scan_days"),
            "n_symbols": len(per_sym),
            "account_size": ACCOUNT_SIZE,
            "leverage": LEVERAGE,
        }, config_snapshot, overfit_results=None)
    except Exception as e:  # pragma: no cover
        log.warning("append_to_index failed: %s", e)


# ════════════════════════════════════════════════════════════════════
# CLI
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
    th = logging.FileHandler(run_dir / "trades.log", encoding="utf-8")
    th.setFormatter(logging.Formatter("%(message)s"))
    _tl.handlers = [th]; _tl.setLevel(logging.DEBUG); _tl.propagate = False


def _print_banner(basket: str, symbols: list[str], days: int,
                  n_candles: int, params: MedallionParams) -> None:
    print()
    print("  ╔════════════════════════════════════════════════════════════╗")
    print("  ║ MEDALLION · Berlekamp-Laufer Mean-Reversion · AURUM         ║")
    print("  ║ honoring Renaissance 1988-1990 redesign · Simons era        ║")
    print("  ╠════════════════════════════════════════════════════════════╣")
    print(f"  ║ UNIVERSE   {len(symbols)} assets (basket: {basket})")
    print(f"  ║ PERIOD     {days} days · {n_candles:,} candles/asset")
    print(f"  ║ TIMEFRAME  {params.interval}")
    print(f"  ║ CAPITAL    ${ACCOUNT_SIZE:,.0f} · {LEVERAGE}x leverage")
    print(f"  ║ SIZING     Kelly × {params.kelly_fraction} (cap {params.max_pct_equity*100:.1f}%)")
    print(f"  ║ ENSEMBLE   {params.ensemble_threshold:.2f} threshold across 7 signals")
    print(f"  ║ GATES      autocorr≤{params.autocorr_max}  |z|≥{params.z_entry_min}  z_vol≥{params.vol_z_min}")
    print(f"  ║ EXIT       stop {params.stop_atr_mult}xATR · tp {params.tp_atr_mult}xATR · time {params.max_bars_in_trade}b")
    print("  ╚════════════════════════════════════════════════════════════╝")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="MEDALLION — Berlekamp-Laufer short-term mean-reversion")
    ap.add_argument("--days", type=int, default=SCAN_DAYS)
    ap.add_argument("--basket", type=str, default="bluechip")
    ap.add_argument("--interval", type=str, default=None)
    ap.add_argument("--no-menu", action="store_true")
    ap.add_argument("--z-entry", type=float, default=None,
                    help="Min |z_return| to consider overshoot")
    ap.add_argument("--ensemble-threshold", type=float, default=None,
                    help="Composite score required to fire entry")
    ap.add_argument("--min-components", type=int, default=None,
                    help="Minimum number of active ensemble components required to enter")
    ap.add_argument("--kelly-fraction", type=float, default=None,
                    help="Fractional Kelly multiplier (quarter=0.25)")
    ap.add_argument("--hmm-exit-trend-prob", type=float, default=None,
                    help="Exit when opposite HMM trend probability reaches this threshold")
    ap.add_argument("--no-hmm", action="store_true",
                    help="Disable HMM regime gate")
    ap.add_argument("--end", type=str, default=None,
                    help="End date YYYY-MM-DD for backtest window (pre-calibration OOS).")
    args = ap.parse_known_args()[0]
    END_TIME_MS = None
    if args.end:
        import pandas as _pd_tmp
        END_TIME_MS = int(_pd_tmp.Timestamp(args.end).timestamp() * 1000)

    basket_name = args.basket or "default"
    symbols = BASKETS.get(basket_name, SYMBOLS)
    scan_days = int(args.days)
    interval = args.interval or INTERVAL
    tf_min = max(1, _TF_MINUTES.get(interval, 15))
    n_candles = scan_days * 24 * 60 // tf_min

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    run_id = f"medallion_{stamp}"
    from config.paths import DATA_DIR
    run_dir = DATA_DIR / "medallion" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _setup_logging(run_dir)

    params = MedallionParams()
    params.interval = interval
    if args.z_entry is not None:
        params.z_entry_min = float(args.z_entry)
    if args.ensemble_threshold is not None:
        params.ensemble_threshold = float(args.ensemble_threshold)
    if args.min_components is not None:
        params.min_active_components = int(args.min_components)
    if args.kelly_fraction is not None:
        params.kelly_fraction = float(args.kelly_fraction)
    if args.hmm_exit_trend_prob is not None:
        params.hmm_exit_trend_prob = float(args.hmm_exit_trend_prob)
    if args.no_hmm:
        params.hmm_enabled = False

    _print_banner(basket_name, symbols, scan_days, n_candles, params)

    print(f"  fetching {len(symbols)} symbols @ {interval} ...")
    all_dfs = fetch_all(symbols, interval=interval,
                        n_candles=n_candles, futures=True, end_time_ms=END_TIME_MS)
    if not all_dfs:
        print("  no data fetched.")
        return 1
    for s, df in all_dfs.items():
        validate(df, s)

    print(f"  running scan on {len(all_dfs)} symbols ...")
    all_trades, vetos, per_sym = run_backtest(all_dfs, params, ACCOUNT_SIZE)
    summary = compute_summary(all_trades, ACCOUNT_SIZE)

    print()
    print(f"  ┌─ MEDALLION summary ({run_id}) " + "─" * 26 + "┐")
    print(f"  │ trades      {summary['n_trades']:>10d}")
    print(f"  │ win rate    {summary['win_rate']:>9.1f}%")
    print(f"  │ ROI         {summary['roi_pct']:>+9.2f}%")
    print(f"  │ PnL         ${summary['pnl']:>+12,.2f}")
    print(f"  │ final eq    ${summary['final_equity']:>12,.2f}")
    print(f"  │ max DD      {summary['max_dd_pct']:>9.2f}%")
    print(f"  │ Sharpe      {summary['sharpe']:>10.3f}")
    print(f"  │ Sortino     {summary['sortino']:>10.3f}")
    print("  └" + "─" * 54 + "┘")
    if per_sym:
        print("\n  per symbol:")
        for s, st in sorted(per_sym.items()):
            print(f"    {s:<12s}  n={st['n_trades']:>3d}  "
                  f"W={st['wins']:>2d}  L={st['losses']:>2d}  "
                  f"pnl=${st['pnl']:>+10,.2f}")
    if vetos:
        print("\n  top vetoes:")
        for k, v in sorted(vetos.items(), key=lambda kv: -kv[1])[:6]:
            print(f"    {k:<22s}  {v:>6d}")

    save_run(run_dir, all_trades, summary, params, vetos, per_sym,
             meta={"run_id": run_id, "basket": basket_name,
                   "scan_days": scan_days, "symbols": list(all_dfs.keys())})
    print(f"\n  run → {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
