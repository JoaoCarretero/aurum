"""Contract tests for core.signals.

Cobrem os 8 pontos de entrada: _liq_prices, decide_direction, score_omega,
score_chop, calc_levels, calc_levels_chop, label_trade, label_trade_chop.

Testes focam em invariantes (enum de direção, ordenação stop/entry/target,
identidades em label_trade) em vez de magic numbers — sobrevivem a tuning
de params.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from config.params import (
    CHOP_RSI_LONG,
    CHOP_RSI_SHORT,
    LEVERAGE,
    MAX_HOLD,
    MIN_STOP_PCT,
    REGIME_MIN_STRENGTH,
    RR_MIN,
    SLIPPAGE,
    SPREAD,
    TARGET_RR,
    TRAIL_ACTIVATE_MULT,
    TRAIL_BE_MULT,
    VOL_RISK_SCALE,
)
from core.signals import (
    _liq_prices,
    calc_levels,
    calc_levels_chop,
    decide_direction,
    label_trade,
    label_trade_chop,
    score_chop,
    score_omega,
)


# ────────────────────────────────────────────────────────────
# helpers
# ────────────────────────────────────────────────────────────

def _row(**overrides) -> pd.Series:
    """Base row com campos default aceitáveis para decide_direction/score_*."""
    base = {
        "trend_struct": "UP",
        "struct_strength": 0.80,
        "slope21": 0.05,
        "slope200": 0.05,
        "vol_regime": "NORMAL",
        "dist_ema21": 0.5,
        # omega components
        "casc_up": 1,
        "casc_down": 0,
        "omega_flow_bull": 0.7,
        "omega_flow_bear": 0.3,
        "omega_mom_bull": 0.8,
        "omega_mom_bear": 0.2,
        "omega_pullback": 0.6,
        "omega_struct_up": 0.9,
        "omega_struct_down": 0.0,
        # chop fields
        "close": 100.0,
        "bb_upper": 102.0,
        "bb_lower": 98.0,
        "bb_mid": 100.0,
        "bb_width": 0.04,
        "rsi": 50.0,
    }
    base.update(overrides)
    return pd.Series(base)


def _ohlc_df(n: int, entry_price: float = 100.0) -> pd.DataFrame:
    """OHLC skeleton with ATR column for calc_levels."""
    return pd.DataFrame({
        "open": np.full(n, entry_price),
        "high": np.full(n, entry_price * 1.001),
        "low": np.full(n, entry_price * 0.999),
        "close": np.full(n, entry_price),
        "atr": np.full(n, entry_price * 0.01),  # 1% ATR
        "swing_high": np.zeros(n),
        "swing_low": np.zeros(n),
    })


# ────────────────────────────────────────────────────────────
# _liq_prices
# ────────────────────────────────────────────────────────────

class TestLiqPrices:
    def test_leverage_1_returns_sentinels(self):
        # LEVERAGE=1 → liq inativa: long sentinel < 0, short sentinel > 2×
        if LEVERAGE > 1.0:
            pytest.skip("depende de LEVERAGE=1.0 (default atual)")
        long_liq, short_liq = _liq_prices(100.0, "BULLISH")
        assert long_liq < 0
        assert short_liq > 100.0


# ────────────────────────────────────────────────────────────
# decide_direction
# ────────────────────────────────────────────────────────────

class TestDecideDirection:
    def test_low_strength_rejects(self):
        row = _row(struct_strength=REGIME_MIN_STRENGTH - 0.01)
        direction, motivo, score = decide_direction(row, "BULL")
        assert direction is None
        assert "regime" in motivo
        assert score == 0.0

    def test_chop_slopes_reject(self):
        # Ambos slopes pequenos E strength ≤ 0.70 → chop
        row = _row(slope21=0.001, slope200=0.001, struct_strength=0.60)
        direction, motivo, _ = decide_direction(row, "BULL")
        assert direction is None
        assert "chop" in motivo

    def test_vol_extreme_rejects(self):
        # VOL_RISK_SCALE['EXTREME'] == 0.0 → reject
        assert VOL_RISK_SCALE["EXTREME"] == 0.0
        row = _row(vol_regime="EXTREME")
        direction, motivo, _ = decide_direction(row, "BULL")
        assert direction is None
        assert motivo == "vol_extreme"

    def test_macro_bear_vetoes_long(self):
        row = _row(trend_struct="UP", struct_strength=0.80)
        direction, motivo, _ = decide_direction(row, "BEAR")
        assert direction is None
        assert "macro_bear_veto_long" in motivo

    def test_macro_bull_vetoes_short(self):
        row = _row(trend_struct="DOWN", struct_strength=0.80,
                   casc_up=0, casc_down=1)
        direction, motivo, _ = decide_direction(row, "BULL")
        assert direction is None
        assert "macro_bull_veto_short" in motivo

    def test_bull_trend_aligned_returns_bullish(self):
        # Struct UP + macro BULL + pullback presente → BULLISH
        row = _row(trend_struct="UP", struct_strength=0.80, dist_ema21=0.5)
        direction, motivo, score = decide_direction(row, "BULL")
        assert direction == "BULLISH"
        assert motivo == "ok"
        assert score == 1.0

    def test_bull_no_pullback_rejects(self):
        # Struct UP + macro BULL mas dist_ema21 < BULL_LONG_MIN_PULLBACK_ATR
        row = _row(trend_struct="UP", struct_strength=0.80, dist_ema21=0.05)
        direction, motivo, _ = decide_direction(row, "BULL")
        assert direction is None
        assert motivo == "bull_no_pullback"

    def test_down_struct_chop_macro_returns_bearish(self):
        row = _row(trend_struct="DOWN", struct_strength=0.80)
        direction, motivo, _ = decide_direction(row, "CHOP")
        assert direction == "BEARISH"
        assert motivo == "ok"

    def test_neutral_struct_returns_none(self):
        row = _row(trend_struct="NEUTRAL", struct_strength=0.80,
                   slope21=0.05, slope200=0.05)
        direction, motivo, _ = decide_direction(row, "CHOP")
        assert direction is None
        assert "neutral" in motivo


# ────────────────────────────────────────────────────────────
# score_omega
# ────────────────────────────────────────────────────────────

class TestScoreOmega:
    def test_returns_tuple_of_float_and_comps(self):
        score, comps = score_omega(_row(), "BULLISH")
        assert isinstance(score, float)
        assert isinstance(comps, dict)
        assert set(comps.keys()) == {"struct", "flow", "cascade", "momentum", "pullback"}

    def test_cascade_zero_yields_zero_score(self):
        # casc_up abaixo de CASCADE_MIN → c_s=0 → score=0
        row = _row(casc_up=0)
        score, _ = score_omega(row, "BULLISH")
        assert score == 0.0

    def test_score_positive_with_active_cascade(self):
        score, _ = score_omega(_row(), "BULLISH")
        assert score > 0

    def test_bearish_uses_bear_components(self):
        # Com casc_down=1 e flow_bear=0.8, score BEARISH > score BULLISH
        row = _row(casc_up=0, casc_down=1,
                   omega_flow_bull=0.2, omega_flow_bear=0.8,
                   omega_mom_bull=0.2, omega_mom_bear=0.8,
                   omega_struct_up=0.0, omega_struct_down=0.9)
        s_bear, _ = score_omega(row, "BEARISH")
        s_bull, _ = score_omega(row, "BULLISH")
        assert s_bear > s_bull

    def test_score_bounded_by_weights(self):
        # Com tudo em 1.0 e casc ativo, score <= 1.0 (weights somam 1.0, penalty ≤ 1)
        row = _row(casc_up=1, omega_flow_bull=1.0, omega_mom_bull=1.0,
                   omega_pullback=1.0, omega_struct_up=1.0)
        score, _ = score_omega(row, "BULLISH")
        assert 0 <= score <= 1.0

    def test_penalty_reduces_score_when_min_component_low(self):
        # Um componente baixo aplica penalty 0.70 (min=0); tudo alto dá penalty 1.0
        high_all = _row(casc_up=1, omega_flow_bull=1.0, omega_mom_bull=1.0,
                        omega_pullback=1.0, omega_struct_up=1.0)
        one_low = _row(casc_up=1, omega_flow_bull=1.0, omega_mom_bull=1.0,
                       omega_pullback=0.0, omega_struct_up=1.0)
        s_high, _ = score_omega(high_all, "BULLISH")
        s_low, _ = score_omega(one_low, "BULLISH")
        assert s_high > s_low


# ────────────────────────────────────────────────────────────
# score_chop
# ────────────────────────────────────────────────────────────

class TestScoreChop:
    def test_missing_bands_returns_none(self):
        direction, score, info = score_chop(_row(bb_upper=0, bb_lower=0, bb_mid=0))
        assert direction is None
        assert score == 0.0
        assert info == {}

    def test_extreme_vol_rejects(self):
        direction, _, _ = score_chop(_row(vol_regime="EXTREME",
                                          close=95.0, rsi=20.0))
        assert direction is None

    def test_high_slope_rejects(self):
        # slope21 > CHOP_MAX_SLOPE_ABS (0.025)
        direction, _, _ = score_chop(_row(slope21=0.10, close=95.0, rsi=20.0))
        assert direction is None

    def test_tiny_bb_width_rejects(self):
        direction, _, _ = score_chop(_row(bb_width=0.001, close=95.0, rsi=20.0))
        assert direction is None

    def test_oversold_below_lower_band_returns_bullish(self):
        direction, score, info = score_chop(_row(
            close=97.0, bb_lower=98.0, bb_upper=102.0,
            rsi=CHOP_RSI_LONG - 5, slope21=0.01,
        ))
        assert direction == "BULLISH"
        assert score > 0
        assert "rsi_extreme" in info

    def test_overbought_above_upper_band_returns_bearish(self):
        direction, score, info = score_chop(_row(
            close=103.0, bb_lower=98.0, bb_upper=102.0,
            rsi=CHOP_RSI_SHORT + 5, slope21=0.01,
        ))
        assert direction == "BEARISH"
        assert score > 0

    def test_within_bands_returns_none(self):
        direction, _, _ = score_chop(_row(close=100.0, bb_lower=98.0, bb_upper=102.0,
                                           rsi=50.0, slope21=0.01))
        assert direction is None


# ────────────────────────────────────────────────────────────
# calc_levels
# ────────────────────────────────────────────────────────────

class TestCalcLevels:
    def test_last_idx_returns_none(self):
        df = _ohlc_df(10)
        assert calc_levels(df, 9, "BULLISH") is None

    def test_nan_atr_returns_none(self):
        df = _ohlc_df(10)
        df.loc[5, "atr"] = np.nan
        assert calc_levels(df, 5, "BULLISH") is None

    def test_zero_atr_returns_none(self):
        df = _ohlc_df(10)
        df.loc[5, "atr"] = 0.0
        assert calc_levels(df, 5, "BULLISH") is None

    def test_bullish_levels_ordered(self):
        df = _ohlc_df(10)
        out = calc_levels(df, 5, "BULLISH")
        assert out is not None
        entry, stop, target, rr = out
        assert stop < entry < target
        assert rr >= RR_MIN

    def test_bearish_levels_ordered(self):
        df = _ohlc_df(10)
        out = calc_levels(df, 5, "BEARISH")
        assert out is not None
        entry, stop, target, rr = out
        assert target < entry < stop
        assert rr >= RR_MIN

    def test_slippage_applied_bullish(self):
        df = _ohlc_df(10)
        raw = df["open"].iloc[6]  # entry bar = idx+1
        out = calc_levels(df, 5, "BULLISH")
        entry = out[0]
        # Entry should be raw * (1 + SLIPPAGE + SPREAD)
        expected = raw * (1 + SLIPPAGE + SPREAD)
        assert abs(entry - expected) < 1e-6

    def test_slippage_applied_bearish(self):
        df = _ohlc_df(10)
        raw = df["open"].iloc[6]
        out = calc_levels(df, 5, "BEARISH")
        entry = out[0]
        expected = raw * (1 - SLIPPAGE - SPREAD)
        assert abs(entry - expected) < 1e-6

    def test_min_stop_pct_respected_bullish(self):
        # Stop deve estar pelo menos MIN_STOP_PCT abaixo do entry
        df = _ohlc_df(10)
        out = calc_levels(df, 5, "BULLISH")
        entry, stop, _, _ = out
        assert entry - stop >= entry * MIN_STOP_PCT - 1e-6

    def test_target_rr_multiple(self):
        df = _ohlc_df(10)
        out = calc_levels(df, 5, "BULLISH")
        entry, stop, target, rr = out
        # Target = entry + (entry-stop) * TARGET_RR
        expected_target = entry + (entry - stop) * TARGET_RR
        assert abs(target - expected_target) < 1e-3
        assert abs(rr - TARGET_RR) < 0.01


# ────────────────────────────────────────────────────────────
# calc_levels_chop
# ────────────────────────────────────────────────────────────

class TestCalcLevelsChop:
    def test_bullish_target_is_bb_mid(self):
        df = _ohlc_df(10, entry_price=98.0)
        bb_mid = 100.0
        out = calc_levels_chop(df, 5, "BULLISH", bb_mid)
        assert out is not None
        entry, stop, target, rr = out
        assert target == round(bb_mid, 4)
        assert stop < entry < target

    def test_bearish_target_is_bb_mid(self):
        df = _ohlc_df(10, entry_price=102.0)
        bb_mid = 100.0
        out = calc_levels_chop(df, 5, "BEARISH", bb_mid)
        assert out is not None
        entry, stop, target, rr = out
        assert target == round(bb_mid, 4)
        assert target < entry < stop

    def test_rr_below_1_rejects(self):
        # bb_mid muito perto do entry → rr<1 → None
        df = _ohlc_df(10, entry_price=100.0)
        bb_mid = 100.01
        assert calc_levels_chop(df, 5, "BULLISH", bb_mid) is None


# ────────────────────────────────────────────────────────────
# label_trade
# ────────────────────────────────────────────────────────────

class TestLabelTrade:
    def _df_price_path(self, prices: list[float]) -> pd.DataFrame:
        """Build a minimal OHLC df where each bar's high = low = close = price[i]."""
        n = len(prices)
        p = np.array(prices, dtype=float)
        return pd.DataFrame({
            "open": p,
            "high": p,
            "low": p,
            "close": p,
        })

    def test_bullish_target_hit(self):
        # Entry 100, stop 99, target 103; prices rise to 103
        df = self._df_price_path([100, 101, 102, 103, 104])
        result, bars, exit_px, reason = label_trade(
            df, 0, "BULLISH", 100.0, 99.0, 103.0
        )
        assert result == "WIN"
        assert reason == "target"
        assert exit_px == 103.0

    def test_bullish_stop_initial_hit(self):
        # Prices fall immediately to 98 (below stop 99)
        df = self._df_price_path([100, 98, 97, 96])
        result, bars, exit_px, reason = label_trade(
            df, 0, "BULLISH", 100.0, 99.0, 103.0
        )
        assert result == "LOSS"
        assert reason == "stop_initial"

    def test_bullish_breakeven_protects(self):
        # Entry 100, stop 99 (risk=1), target 110. Price hits 101 (1R) then reverses to 99.5.
        # Breakeven should trigger at 100, then stop exit at 100.
        df = self._df_price_path([100, 101 + TRAIL_BE_MULT * 0.01, 99.5])
        # Need high = 100 + TRAIL_BE_MULT * 1 = 101 (if TRAIL_BE=1.0) to trigger BE
        prices = [100, 100 + TRAIL_BE_MULT * 1.0 + 0.01, 99.8]
        df = self._df_price_path(prices)
        result, bars, exit_px, reason = label_trade(
            df, 0, "BULLISH", 100.0, 99.0, 110.0
        )
        # BE triggered at bar 1 (price hit 101+), then bar 2 (price 99.8) crosses BE stop
        assert reason == "breakeven"
        # At breakeven, cur_stop == entry, so result is WIN (cur_stop >= entry)
        assert result == "WIN"

    def test_bearish_target_hit(self):
        df = self._df_price_path([100, 99, 98, 97, 96])
        result, bars, exit_px, reason = label_trade(
            df, 0, "BEARISH", 100.0, 101.0, 97.0
        )
        assert result == "WIN"
        assert reason == "target"

    def test_bearish_stop_initial_hit(self):
        df = self._df_price_path([100, 102, 103])
        result, bars, exit_px, reason = label_trade(
            df, 0, "BEARISH", 100.0, 101.0, 97.0
        )
        assert result == "LOSS"
        assert reason == "stop_initial"

    def test_open_returned_when_max_hold_reached(self):
        # Price stays flat → never hits stop or target
        prices = [100.0] * (MAX_HOLD + 10)
        df = self._df_price_path(prices)
        result, bars, exit_px, reason = label_trade(
            df, 0, "BULLISH", 100.0, 99.0, 110.0
        )
        assert result == "OPEN"
        assert reason == "max_hold"
        assert bars == MAX_HOLD

    def test_result_is_enum(self):
        df = self._df_price_path([100, 101, 102, 103])
        result, _, _, _ = label_trade(df, 0, "BULLISH", 100.0, 99.0, 103.0)
        assert result in {"WIN", "LOSS", "OPEN"}


# ────────────────────────────────────────────────────────────
# label_trade_chop
# ────────────────────────────────────────────────────────────

class TestLabelTradeChop:
    def _df(self, prices: list[float]) -> pd.DataFrame:
        n = len(prices)
        p = np.array(prices, dtype=float)
        return pd.DataFrame({"open": p, "high": p, "low": p, "close": p})

    def test_bullish_target_hit(self):
        df = self._df([98, 99, 100])
        result, bars, exit_px, reason = label_trade_chop(
            df, 0, "BULLISH", 98.0, 97.0, 100.0
        )
        assert result == "WIN"
        assert reason == "target"

    def test_bullish_stop_hit(self):
        df = self._df([98, 96])
        result, _, _, reason = label_trade_chop(
            df, 0, "BULLISH", 98.0, 97.0, 100.0
        )
        assert result == "LOSS"
        assert reason == "stop_initial"

    def test_bearish_target_hit(self):
        df = self._df([102, 101, 100])
        result, _, _, reason = label_trade_chop(
            df, 0, "BEARISH", 102.0, 103.0, 100.0
        )
        assert result == "WIN"
        assert reason == "target"

    def test_chop_max_hold_is_shorter_than_trend(self):
        # chop_max_hold = min(MAX_HOLD // 2, 24)
        expected_max = min(MAX_HOLD // 2, 24)
        prices = [100.0] * (expected_max + 10)
        df = self._df(prices)
        _, bars, _, reason = label_trade_chop(
            df, 0, "BULLISH", 100.0, 99.0, 110.0
        )
        assert reason == "max_hold"
        assert bars == expected_max
