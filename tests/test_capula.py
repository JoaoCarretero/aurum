"""Tests for engines/capula.py — funding-rate carry engine.

CAPULA captures perpetual-futures funding-rate carry in a delta-neutral
structure (short perp + long spot, or long perp + short spot depending
on funding sign). Entries are driven by z-score extremes of funding,
exits by reversion or kill-switches.

Tests exercise the logic (sizing, z-score features, entry/exit decisions,
kill-switches, PnL accounting) on synthetic funding series — no network.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from config.params import ACCOUNT_SIZE
from engines.capula import (
    CapulaParams,
    _delta_neutral_cost,
    _period_funding_pnl,
    capula_size,
    compute_features,
    compute_summary,
    decide_direction,
    resolve_exit,
    run_backtest,
    scan_symbol,
)


# ════════════════════════════════════════════════════════════════════
# Synthetic data helpers
# ════════════════════════════════════════════════════════════════════

def _df_with_funding(
    funding_rates: np.ndarray,
    start: str = "2025-01-01",
    freq: str = "8h",
    price: float = 100.0,
) -> pd.DataFrame:
    """Minimal df with funding_rate column — funding cadence per row."""
    n = len(funding_rates)
    idx = pd.date_range(start, periods=n, freq=freq)
    return pd.DataFrame({
        "time": idx,
        "open": np.full(n, price),
        "high": np.full(n, price * 1.001),
        "low": np.full(n, price * 0.999),
        "close": np.full(n, price),
        "vol": np.full(n, 1000.0),
        "funding_rate": funding_rates.astype(float),
    })


def _oscillating_funding(n: int, amplitude: float = 0.0008,
                        period: int = 48, noise: float = 0.00005,
                        seed: int = 0) -> np.ndarray:
    """Sine-wave funding with small noise — produces periodic z-score extremes."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    signal = amplitude * np.sin(2 * np.pi * t / period)
    return signal + rng.standard_normal(n) * noise


# ════════════════════════════════════════════════════════════════════
# Sizing — quarter-Kelly notional
# ════════════════════════════════════════════════════════════════════

def test_capula_size_quarter_kelly_default():
    """size = equity * kelly_fraction * max_pct_equity with defaults."""
    size = capula_size(equity=10_000, kelly_fraction=0.25, max_pct_equity=0.10)
    # 10_000 * 0.25 * 0.10 = $250 notional
    assert size == pytest.approx(250.0, rel=1e-6)


def test_capula_size_zero_on_bad_inputs():
    assert capula_size(equity=0, kelly_fraction=0.25, max_pct_equity=0.1) == 0.0
    assert capula_size(equity=-10, kelly_fraction=0.25, max_pct_equity=0.1) == 0.0
    assert capula_size(equity=float("nan"), kelly_fraction=0.25,
                       max_pct_equity=0.1) == 0.0
    assert capula_size(equity=10_000, kelly_fraction=0.0,
                       max_pct_equity=0.1) == 0.0


def test_capula_size_caps_at_max_pct_equity():
    """Kelly > 1 (edge exceeds variance) still bounded by max_pct_equity."""
    # kelly_fraction=2.0 × 0.10 → product 0.20 but the multiplier semantics
    # is a *fraction of the max exposure*, so values ≤ 1 scale down, > 1
    # clamp at 1 (full max_pct_equity utilisation).
    big = capula_size(equity=10_000, kelly_fraction=5.0, max_pct_equity=0.10)
    cap = capula_size(equity=10_000, kelly_fraction=1.0, max_pct_equity=0.10)
    assert big == cap == pytest.approx(1000.0, rel=1e-6)


# ════════════════════════════════════════════════════════════════════
# PnL primitives
# ════════════════════════════════════════════════════════════════════

def test_period_funding_pnl_short_collects_positive_funding():
    """SHORT perp (direction=-1) collects positive funding rate."""
    pnl = _period_funding_pnl(direction=-1, notional=1000.0, rate=0.001)
    # SHORT receives +rate × notional when rate > 0
    assert pnl == pytest.approx(1.0, rel=1e-9)


def test_period_funding_pnl_long_collects_negative_funding():
    """LONG perp (direction=+1) collects when funding is negative (shorts pay longs)."""
    pnl = _period_funding_pnl(direction=+1, notional=1000.0, rate=-0.001)
    # LONG receives -rate × notional when rate < 0
    assert pnl == pytest.approx(1.0, rel=1e-9)


def test_period_funding_pnl_wrong_side_pays():
    """Wrong-side (LONG on positive funding) pays funding — negative PnL."""
    pnl = _period_funding_pnl(direction=+1, notional=1000.0, rate=0.001)
    assert pnl == pytest.approx(-1.0, rel=1e-9)


def test_delta_neutral_cost_positive_and_scales_with_notional():
    """Round-trip cost for delta-neutral (2 legs) must be > 0 and linear."""
    c1 = _delta_neutral_cost(notional=1_000.0)
    c2 = _delta_neutral_cost(notional=10_000.0)
    assert c1 > 0
    assert c2 == pytest.approx(c1 * 10, rel=1e-6)


# ════════════════════════════════════════════════════════════════════
# compute_features — z-score of funding
# ════════════════════════════════════════════════════════════════════

def test_compute_features_adds_funding_zscore_column():
    rates = _oscillating_funding(300)
    df = _df_with_funding(rates)
    params = CapulaParams(z_window=50)
    enriched = compute_features(df, params)
    assert "capula_funding_z" in enriched.columns
    # After warmup, should have finite values
    assert np.isfinite(enriched["capula_funding_z"].iloc[-1])


def test_compute_features_zscore_nan_during_warmup():
    """Z-score should be NaN (or zero-safe) at the very start before window fills."""
    rates = _oscillating_funding(200)
    df = _df_with_funding(rates)
    params = CapulaParams(z_window=50)
    enriched = compute_features(df, params)
    # First bar has no prior history — z must be NaN
    assert not np.isfinite(enriched["capula_funding_z"].iloc[0])


def test_compute_features_missing_funding_col_adds_nan_zscore():
    """If funding_rate column is absent, engine should not crash — z becomes all NaN."""
    df = pd.DataFrame({
        "time": pd.date_range("2025-01-01", periods=60, freq="8h"),
        "open": np.full(60, 100.0),
        "high": np.full(60, 101.0),
        "low": np.full(60, 99.0),
        "close": np.full(60, 100.0),
    })
    params = CapulaParams(z_window=20)
    enriched = compute_features(df, params)
    assert "capula_funding_z" in enriched.columns
    assert enriched["capula_funding_z"].isna().all()


# ════════════════════════════════════════════════════════════════════
# decide_direction — z-score thresholds
# ════════════════════════════════════════════════════════════════════

def _df_with_z(n: int, z_values: np.ndarray,
               funding_values: np.ndarray | None = None) -> pd.DataFrame:
    """Minimal df with the columns decide_direction reads."""
    if funding_values is None:
        funding_values = np.zeros(n)
    return pd.DataFrame({
        "time": pd.date_range("2025-01-01", periods=n, freq="8h"),
        "close": np.full(n, 100.0),
        "funding_rate": funding_values,
        "capula_funding_z": z_values,
    })


def test_decide_direction_short_on_high_positive_funding():
    """z > z_entry with rate > 0 → direction = -1 (short perp to collect)."""
    params = CapulaParams(z_entry=2.0, kill_switch_z=5.0)
    z = np.full(10, 2.5)
    rates = np.full(10, 0.001)  # positive rate
    df = _df_with_z(10, z, rates)
    assert decide_direction(df, 9, params) == -1


def test_decide_direction_long_on_extreme_negative_funding():
    """z < -z_entry with rate < 0 → direction = +1 (long perp to collect)."""
    params = CapulaParams(z_entry=2.0, kill_switch_z=5.0)
    z = np.full(10, -2.5)
    rates = np.full(10, -0.001)
    df = _df_with_z(10, z, rates)
    assert decide_direction(df, 9, params) == +1


def test_decide_direction_no_signal_below_threshold():
    params = CapulaParams(z_entry=2.0)
    z = np.full(10, 1.5)
    df = _df_with_z(10, z, np.full(10, 0.001))
    assert decide_direction(df, 9, params) == 0


def test_decide_direction_kill_switch_blocks_entry_on_extreme_z():
    """|z| > kill_switch_z → no new entry (crash-protection)."""
    params = CapulaParams(z_entry=2.0, kill_switch_z=5.0)
    z = np.full(10, 6.0)  # extreme — beyond kill-switch
    df = _df_with_z(10, z, np.full(10, 0.01))
    assert decide_direction(df, 9, params) == 0


def test_decide_direction_nan_funding_returns_zero():
    params = CapulaParams(z_entry=2.0)
    z = np.full(10, np.nan)
    df = _df_with_z(10, z, np.full(10, np.nan))
    assert decide_direction(df, 9, params) == 0


def test_decide_direction_sign_mismatch_returns_zero():
    """High positive z but negative funding rate → contradictory, no trade."""
    params = CapulaParams(z_entry=2.0)
    z = np.full(10, 2.5)
    rates = np.full(10, -0.001)  # rate sign does not match z sign
    df = _df_with_z(10, z, rates)
    assert decide_direction(df, 9, params) == 0


# ════════════════════════════════════════════════════════════════════
# resolve_exit — reversion / max-hold / kill-switch
# ════════════════════════════════════════════════════════════════════

def test_resolve_exit_on_reversion():
    """|z| below z_exit → reversion exit."""
    params = CapulaParams(z_entry=2.0, z_exit=0.5, max_hold_periods=50,
                          kill_switch_z=5.0)
    z = np.full(20, 0.3)
    df = _df_with_z(20, z, np.full(20, 0.0001))
    trade = {"entry_idx": 5, "direction": -1}
    result = resolve_exit(df, t=10, trade=trade, params=params)
    assert result is not None
    assert result[0] == "reversion"


def test_resolve_exit_on_max_hold():
    params = CapulaParams(z_entry=2.0, z_exit=0.5, max_hold_periods=5,
                          kill_switch_z=5.0)
    # Hold open, z still above exit threshold
    z = np.full(30, 2.2)
    df = _df_with_z(30, z, np.full(30, 0.001))
    trade = {"entry_idx": 5, "direction": -1}
    result = resolve_exit(df, t=5 + 5, trade=trade, params=params)
    assert result is not None
    assert result[0] == "max_hold"


def test_resolve_exit_on_kill_switch():
    """|z| > kill_switch_z while in trade → emergency exit."""
    params = CapulaParams(z_entry=2.0, z_exit=0.5, max_hold_periods=50,
                          kill_switch_z=5.0)
    z = np.full(30, 6.0)
    df = _df_with_z(30, z, np.full(30, 0.01))
    trade = {"entry_idx": 5, "direction": -1}
    result = resolve_exit(df, t=7, trade=trade, params=params)
    assert result is not None
    assert result[0] == "kill_switch"


def test_resolve_exit_none_when_still_carrying():
    """|z| between exit and kill thresholds, within max hold → no exit."""
    params = CapulaParams(z_entry=2.0, z_exit=0.5, max_hold_periods=50,
                          kill_switch_z=5.0)
    z = np.full(30, 1.8)
    df = _df_with_z(30, z, np.full(30, 0.001))
    trade = {"entry_idx": 5, "direction": -1}
    assert resolve_exit(df, t=8, trade=trade, params=params) is None


def test_resolve_exit_not_on_entry_bar():
    """Must never exit on the entry bar (duration 0)."""
    params = CapulaParams(z_entry=2.0, z_exit=0.5, max_hold_periods=50,
                          kill_switch_z=5.0)
    z = np.full(30, 0.0)  # would trigger reversion
    df = _df_with_z(30, z, np.full(30, 0.0))
    trade = {"entry_idx": 10, "direction": -1}
    assert resolve_exit(df, t=10, trade=trade, params=params) is None


# ════════════════════════════════════════════════════════════════════
# scan_symbol — integration
# ════════════════════════════════════════════════════════════════════

def test_scan_symbol_empty_df_returns_empty():
    params = CapulaParams()
    df = _df_with_funding(np.array([]))
    trades, vetos = scan_symbol(df, "BTCUSDT", params, ACCOUNT_SIZE)
    assert trades == []
    assert "too_few_bars" in vetos


def test_scan_symbol_all_flat_funding_no_trades():
    """Flat funding → z-score stays ~0 → no entries."""
    rates = np.full(500, 0.0001)  # constant funding
    df = _df_with_funding(rates)
    params = CapulaParams(z_window=60, z_entry=2.0)
    df_feat = compute_features(df, params)
    trades, vetos = scan_symbol(df_feat, "BTCUSDT", params, ACCOUNT_SIZE)
    assert trades == []
    assert vetos.get("no_signal", 0) > 0


def test_scan_symbol_oscillating_funding_produces_trades():
    """Sine-wave funding should produce multiple entries and clean exits."""
    rates = _oscillating_funding(1000, amplitude=0.002, period=80, noise=0.0001)
    df = _df_with_funding(rates)
    params = CapulaParams(
        z_window=50, z_entry=1.5, z_exit=0.3,
        max_hold_periods=40, kill_switch_z=8.0,
        kelly_fraction=0.25, max_pct_equity=0.10,
    )
    df_feat = compute_features(df, params)
    trades, _ = scan_symbol(df_feat, "BTCUSDT", params, ACCOUNT_SIZE)
    assert len(trades) >= 2
    # Trades must have required schema fields
    for t in trades:
        for key in ("symbol", "direction", "entry_idx", "exit_idx",
                    "notional", "pnl", "exit_reason", "result", "duration"):
            assert key in t, f"trade missing {key}"
        assert t["direction"] in (+1, -1)
        assert t["duration"] > 0


def test_scan_symbol_missing_funding_col_produces_no_trades():
    """If funding_rate column is absent, engine must abstain — no spurious trades."""
    df = pd.DataFrame({
        "time": pd.date_range("2025-01-01", periods=400, freq="8h"),
        "open": np.full(400, 100.0),
        "high": np.full(400, 101.0),
        "low": np.full(400, 99.0),
        "close": np.full(400, 100.0),
    })
    params = CapulaParams(z_window=50)
    df_feat = compute_features(df, params)
    trades, _ = scan_symbol(df_feat, "BTCUSDT", params, ACCOUNT_SIZE)
    assert trades == []


# ════════════════════════════════════════════════════════════════════
# run_backtest + summary
# ════════════════════════════════════════════════════════════════════

def test_run_backtest_aggregates_across_symbols():
    rates_a = _oscillating_funding(800, amplitude=0.002, period=80, seed=1)
    rates_b = _oscillating_funding(800, amplitude=0.002, period=60, seed=2)
    all_dfs = {
        "BTCUSDT": _df_with_funding(rates_a),
        "ETHUSDT": _df_with_funding(rates_b),
    }
    params = CapulaParams(z_window=50, z_entry=1.5, z_exit=0.3,
                          max_hold_periods=40)
    trades, vetos, per_sym = run_backtest(all_dfs, params, ACCOUNT_SIZE)
    assert isinstance(trades, list)
    assert set(per_sym.keys()) == {"BTCUSDT", "ETHUSDT"}


def test_compute_summary_empty_trades():
    summary = compute_summary([], initial_equity=10_000.0)
    assert summary["n_trades"] == 0
    assert summary["pnl"] == 0.0
    assert summary["final_equity"] == 10_000.0


def test_compute_summary_non_empty_preserves_pnl_sum():
    trades = [
        {"pnl": 10.0, "result": "WIN"},
        {"pnl": -3.0, "result": "LOSS"},
        {"pnl": 5.0, "result": "WIN"},
    ]
    summary = compute_summary(trades, initial_equity=1_000.0)
    assert summary["n_trades"] == 3
    assert summary["pnl"] == pytest.approx(12.0, rel=1e-6)
    # compute_summary rounds to 2 decimals (AURUM convention, see kepos.py)
    assert summary["win_rate"] == pytest.approx(2 / 3 * 100, abs=0.01)


# ════════════════════════════════════════════════════════════════════
# Regression — bar cadence vs funding cadence (MAJOR 1, AUR-10)
# ════════════════════════════════════════════════════════════════════

def test_scan_symbol_scales_funding_by_bar_cadence_15m_vs_8h():
    """Regression for AUR-10 MAJOR 1 — per-bar accrual must scale by
    (bar_minutes / funding_interval_minutes).

    Binance funding publishes every 8h (480min). When the engine runs on
    15m candles, ``merge_asof(backward)`` forward-fills each funding value
    onto 32 consecutive bars. Without scaling, ``scan_symbol`` would accrue
    the full funding on all 32 → PnL inflated by 32×. With the scaling
    each 15m bar only contributes 1/32 of a full funding period.

    The test builds a synthetic 15m dataset that mimics ffilled 8h funding
    and asserts per-trade gross funding PnL stays well below what the
    unscaled (broken) path would produce. Failure of this test means the
    cadence-mismatch inflation is back.
    """
    block = 32  # 32 × 15min = 8h
    # Structured funding cycle: strong positive period then reversion.
    funding_events = np.concatenate([
        np.full(6, 0.0),
        np.full(8, 0.002),
        np.full(6, 0.0),
        np.full(6, -0.002),
        np.full(4, 0.0),
    ]).astype(float)
    rates_15m = np.repeat(funding_events, block)  # 30 × 32 = 960 bars
    df_15m = _df_with_funding(rates_15m, freq="15min")

    params = CapulaParams(
        z_window=150, z_entry=1.5, z_exit=0.3,
        max_hold_periods=400, kill_switch_z=8.0,
        kelly_fraction=0.25, max_pct_equity=0.10,
        funding_interval_h=8.0, interval="15m",
    )
    df_feat = compute_features(df_15m, params)
    trades, _ = scan_symbol(df_feat, "BTCUSDT", params, ACCOUNT_SIZE)

    assert len(trades) >= 1, "expected at least one trade on the engineered cycle"

    max_rate = float(np.max(np.abs(rates_15m)))
    for tr in trades:
        # Unscaled worst case if engine accrued full funding every bar.
        unscaled_cap = max_rate * tr["notional"] * tr["duration"]
        # Scaled correctly, per-bar share is 15/480 = 1/32 → gross must be
        # well under 1/10 of the unscaled cap even with costs absorbed.
        assert abs(tr["gross_funding_pnl"]) < unscaled_cap / 10, (
            f"trade gross funding {tr['gross_funding_pnl']} exceeds 1/10 of "
            f"unscaled cap {unscaled_cap} — MAJOR 1 scaling regressed"
        )
