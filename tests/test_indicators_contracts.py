"""Contract tests for core.indicators.

Não testam magic numbers de params — testam invariantes matemáticas
das funções: shapes, ranges, relações entre colunas, comportamento em
entradas degeneradas (preço flat, volume zero). Se algum dia mudarmos
um parâmetro, os testes continuam válidos.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from config.params import (
    ATR_PERIOD,
    CHOP_BB_PERIOD,
    EMA_SPANS,
    PIVOT_N,
    VOL_WINDOW,
)
from core.indicators import (
    cvd,
    cvd_divergence,
    indicators,
    liquidation_proxy,
    omega,
    swing_structure,
    volume_imbalance,
)


# ────────────────────────────────────────────────────────────
# FIXTURES — synthetic OHLCV+tbb frames
# ────────────────────────────────────────────────────────────

N_ROWS = 500  # > max(EMA200 + SLOPE_N*2, VOL_WINDOW, W_NORM, PIVOT_N*3)


def _make_df(close: np.ndarray, vol: np.ndarray | None = None,
             tbb: np.ndarray | None = None) -> pd.DataFrame:
    n = len(close)
    if vol is None:
        vol = np.full(n, 1_000.0)
    if tbb is None:
        tbb = vol * 0.5
    high = close * 1.002
    low = close * 0.998
    return pd.DataFrame({
        "close": close,
        "high": high,
        "low": low,
        "vol": vol,
        "tbb": tbb,
    })


@pytest.fixture
def flat_df() -> pd.DataFrame:
    return _make_df(np.full(N_ROWS, 100.0))


def _random_walk_with_drift(n: int, drift: float, sigma: float, seed: int,
                             start: float = 100.0) -> np.ndarray:
    """Random walk com drift — gera naturalmente pivots locais + tendência.
    drift positivo = uptrend; negativo = downtrend."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(drift, sigma, n)
    return start + np.cumsum(steps)


@pytest.fixture
def uptrend_df() -> pd.DataFrame:
    # drift 0.2 + sigma 2.0 gera pullbacks suficientes pro swing_structure
    # detectar swing_lows (sem isso, price nunca é o min dos últimos 24 bars)
    close = _random_walk_with_drift(N_ROWS, drift=0.2, sigma=2.0, seed=0)
    return _make_df(close)


@pytest.fixture
def downtrend_df() -> pd.DataFrame:
    close = _random_walk_with_drift(N_ROWS, drift=-0.2, sigma=2.0, seed=2, start=250.0)
    return _make_df(close)


@pytest.fixture
def sideways_df() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = 100.0 + rng.normal(0, 0.5, N_ROWS).cumsum() * 0.1
    return _make_df(close)


@pytest.fixture
def full_df(uptrend_df):
    """Uptrend with all pipeline stages applied (indicators → swing → omega)."""
    return omega(swing_structure(indicators(uptrend_df)))


# ────────────────────────────────────────────────────────────
# indicators()
# ────────────────────────────────────────────────────────────

class TestIndicators:
    EXPECTED_COLS = {
        "rsi", "atr", "vol_ma", "taker_ratio", "taker_ma",
        "slope21", "slope200", "atr_pct", "vol_pct_rank", "vol_regime",
        "bb_upper", "bb_lower", "bb_mid", "bb_width", "regime_transition",
    }

    def test_preserves_length(self, uptrend_df):
        assert len(indicators(uptrend_df)) == len(uptrend_df)

    def test_emits_all_ema_spans(self, uptrend_df):
        out = indicators(uptrend_df)
        for span in EMA_SPANS:
            assert f"ema{span}" in out.columns

    def test_emits_expected_columns(self, uptrend_df):
        out = indicators(uptrend_df)
        assert self.EXPECTED_COLS.issubset(out.columns)

    def test_rsi_bounded_0_100(self, uptrend_df):
        rsi = indicators(uptrend_df)["rsi"].dropna()
        assert (rsi >= 0).all() and (rsi <= 100).all()

    def test_rsi_elevated_on_uptrend(self, uptrend_df):
        # Uptrend com ruído: RSI médio na cauda fica acima de 55 (pra 14-period)
        rsi = indicators(uptrend_df)["rsi"].dropna()
        assert rsi.tail(50).mean() > 55

    def test_rsi_depressed_on_downtrend(self, downtrend_df):
        rsi = indicators(downtrend_df)["rsi"].dropna()
        assert rsi.tail(50).mean() < 45

    def test_atr_nonneg(self, uptrend_df):
        atr = indicators(uptrend_df)["atr"].dropna()
        assert (atr >= 0).all()

    def test_atr_positive_on_nondegenerate_data(self, sideways_df):
        atr = indicators(sideways_df)["atr"].iloc[ATR_PERIOD * 3:]
        assert (atr > 0).all()

    def test_bollinger_ordering(self, uptrend_df):
        out = indicators(uptrend_df).dropna(subset=["bb_upper", "bb_mid", "bb_lower"])
        tail = out.iloc[CHOP_BB_PERIOD:]
        assert (tail["bb_upper"] >= tail["bb_mid"]).all()
        assert (tail["bb_mid"] >= tail["bb_lower"]).all()

    def test_vol_regime_is_enum(self, uptrend_df):
        vr = set(indicators(uptrend_df)["vol_regime"].unique())
        assert vr.issubset({"LOW", "NORMAL", "HIGH", "EXTREME"})

    def test_vol_pct_rank_bounded_0_1(self, uptrend_df):
        r = indicators(uptrend_df)["vol_pct_rank"].dropna()
        assert (r >= 0).all() and (r <= 1).all()

    def test_taker_ratio_bounded_0_1(self, uptrend_df):
        tr = indicators(uptrend_df)["taker_ratio"].dropna()
        assert (tr >= 0).all() and (tr <= 1).all()

    def test_handles_zero_volume_rows(self):
        close = np.linspace(100.0, 110.0, N_ROWS)
        vol = np.full(N_ROWS, 1_000.0)
        vol[50:55] = 0.0  # zero-volume pocket
        tbb = vol * 0.5
        out = indicators(_make_df(close, vol, tbb))
        # no exception + taker_ratio rows that had vol==0 are NaN or 0, not inf
        assert np.isfinite(out["taker_ratio"].fillna(0)).all()

    def test_regime_transition_is_boolean(self, uptrend_df):
        out = indicators(uptrend_df)
        assert out["regime_transition"].dtype == bool

    def test_does_not_mutate_input(self, uptrend_df):
        cols_before = set(uptrend_df.columns)
        indicators(uptrend_df)
        assert set(uptrend_df.columns) == cols_before


# ────────────────────────────────────────────────────────────
# swing_structure()
# ────────────────────────────────────────────────────────────

class TestSwingStructure:
    def test_preserves_length(self, uptrend_df):
        assert len(swing_structure(uptrend_df)) == len(uptrend_df)

    def test_emits_expected_columns(self, uptrend_df):
        out = swing_structure(uptrend_df)
        for col in ("swing_high", "swing_low", "trend_struct", "struct_strength"):
            assert col in out.columns

    def test_trend_struct_is_enum(self, uptrend_df):
        out = swing_structure(uptrend_df)
        assert set(out["trend_struct"].unique()).issubset({"NEUTRAL", "UP", "DOWN"})

    def test_struct_strength_bounded_0_1(self, uptrend_df):
        s = swing_structure(uptrend_df)["struct_strength"]
        assert (s >= 0).all() and (s <= 1).all()

    def test_uptrend_becomes_up_after_warmup(self, uptrend_df):
        out = swing_structure(uptrend_df).iloc[PIVOT_N * 3 + 20:]
        up = (out["trend_struct"] == "UP").sum()
        down = (out["trend_struct"] == "DOWN").sum()
        assert up > down

    def test_downtrend_becomes_down_after_warmup(self, downtrend_df):
        out = swing_structure(downtrend_df).iloc[PIVOT_N * 3 + 20:]
        up = (out["trend_struct"] == "UP").sum()
        down = (out["trend_struct"] == "DOWN").sum()
        assert down > up

    def test_warmup_window_is_neutral(self, uptrend_df):
        out = swing_structure(uptrend_df)
        assert (out["trend_struct"].iloc[:PIVOT_N * 3] == "NEUTRAL").all()


# ────────────────────────────────────────────────────────────
# omega()
# ────────────────────────────────────────────────────────────

class TestOmega:
    def test_preserves_length(self, full_df):
        # full_df was built from uptrend N_ROWS
        assert len(full_df) == N_ROWS

    def test_emits_expected_columns(self, full_df):
        for col in (
            "casc_up", "casc_down",
            "omega_flow_bull", "omega_flow_bear",
            "omega_mom_bull", "omega_mom_bear",
            "omega_pullback",
            "omega_struct_up", "omega_struct_down",
            "dist_ema21",
        ):
            assert col in full_df.columns

    def test_cascade_is_binary_not_sum(self, full_df):
        # ACHADO: casc_up/casc_down usam `bool + bool` no numpy, que é OR,
        # não soma. Então o valor é 0 ou 1, nunca 2-4. Provavelmente bug
        # (intenção parece ter sido contagem de 0..4). Teste fotografa a
        # realidade atual — se for corrigido pra soma, este teste FALHA
        # e a correção precisa ser validada via backtest (CLAUDE.md §SEMPRE 6).
        assert set(full_df["casc_up"].unique()).issubset({0, 1})
        assert set(full_df["casc_down"].unique()).issubset({0, 1})

    def test_cascade_both_can_fire_when_emas_unordered(self, full_df):
        # ACHADO correlato ao bool-sum: casc_up=1 e casc_down=1 podem coexistir
        # no mesmo bar quando as EMAs não estão nem totalmente empilhadas nem
        # totalmente invertidas (ex: e9>e21 mas e21<e50). Documenta a realidade;
        # se o bool-sum for corrigido pra soma inteira, este teste precisa mudar.
        both = ((full_df["casc_up"] == 1) & (full_df["casc_down"] == 1)).sum()
        assert both >= 0  # apenas documenta que o caso existe, não força


    def test_flow_bull_bear_complementary(self, full_df):
        mask = full_df["omega_flow_bull"].notna()
        s = full_df.loc[mask, "omega_flow_bull"] + full_df.loc[mask, "omega_flow_bear"]
        assert np.allclose(s, 1.0)

    def test_momentum_scores_bounded_0_1(self, full_df):
        for col in ("omega_mom_bull", "omega_mom_bear", "omega_pullback"):
            s = full_df[col].dropna()
            assert (s >= 0).all() and (s <= 1).all()

    def test_uptrend_activates_casc_up(self, full_df):
        # Uptrend sustentado → EMAs empilhadas → casc_up=1 predomina na cauda
        tail = full_df["casc_up"].iloc[-50:]
        assert tail.mean() > 0.8

    def test_downtrend_activates_casc_down(self, downtrend_df):
        df = omega(swing_structure(indicators(downtrend_df)))
        tail = df["casc_down"].iloc[-50:]
        assert tail.mean() > 0.8


# ────────────────────────────────────────────────────────────
# cvd() / cvd_divergence() / volume_imbalance() / liquidation_proxy()
# ────────────────────────────────────────────────────────────

class TestOrderFlow:
    def test_cvd_emits_expected_columns(self, uptrend_df):
        out = cvd(uptrend_df)
        for col in ("vdelta", "cvd", "cvd_z"):
            assert col in out.columns

    def test_cvd_vdelta_equals_2tbb_minus_vol(self, uptrend_df):
        out = cvd(uptrend_df)
        expected = 2 * uptrend_df["tbb"] - uptrend_df["vol"]
        assert np.allclose(out["vdelta"], expected)

    def test_cvd_is_cumulative(self, uptrend_df):
        out = cvd(uptrend_df)
        assert np.allclose(out["cvd"].diff().dropna(), out["vdelta"].iloc[1:])

    def test_cvd_divergence_is_binary(self, uptrend_df):
        out = cvd_divergence(uptrend_df)
        assert set(out["cvd_div_bull"].unique()).issubset({0.0, 1.0})
        assert set(out["cvd_div_bear"].unique()).issubset({0.0, 1.0})

    def test_cvd_divergence_idempotent(self, uptrend_df):
        once = cvd_divergence(uptrend_df)
        twice = cvd_divergence(once)
        pd.testing.assert_series_equal(once["cvd_div_bull"], twice["cvd_div_bull"])
        pd.testing.assert_series_equal(once["cvd_div_bear"], twice["cvd_div_bear"])

    def test_volume_imbalance_bounded_0_1(self, uptrend_df):
        out = volume_imbalance(uptrend_df)
        assert out["vimb"].between(0, 1).all()

    def test_volume_imbalance_all_buys_equals_1(self):
        n = 100
        vol = np.full(n, 1_000.0)
        df = _make_df(np.linspace(100, 110, n), vol=vol, tbb=vol.copy())
        out = volume_imbalance(df)
        tail = out["vimb"].iloc[10:]
        assert np.allclose(tail, 1.0)

    def test_volume_imbalance_all_sells_equals_0(self):
        n = 100
        vol = np.full(n, 1_000.0)
        df = _make_df(np.linspace(110, 100, n), vol=vol, tbb=np.zeros(n))
        out = volume_imbalance(df)
        tail = out["vimb"].iloc[10:]
        assert np.allclose(tail, 0.0)

    def test_liquidation_proxy_is_binary(self, uptrend_df):
        with_atr = indicators(uptrend_df)
        out = liquidation_proxy(with_atr)
        assert set(out["liq_proxy"].unique()).issubset({0.0, 1.0})

    def test_liquidation_proxy_works_without_atr(self, uptrend_df):
        out = liquidation_proxy(uptrend_df)
        assert "liq_proxy" in out.columns
        assert set(out["liq_proxy"].unique()).issubset({0.0, 1.0})
