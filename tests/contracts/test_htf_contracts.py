"""Contract tests for core.htf — prepare_htf + merge_all_htf_to_ltf.

Verifica:
- prepare_htf adiciona htf_score + htf_macro sem quebrar pipeline
- merge_all_htf_to_ltf NÃO introduz lookahead bias (HTF bar só aparece
  depois que fechou, via time-shift backward merge_asof)
- Todas as linhas LTF recebem HTF preenchido ou NEUTRAL/CHOP/0.0
- Params de _tf_params são restaurados após prepare_htf (finally)
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

# Usar sys.modules pois core/__init__.py re-exporta funções com o mesmo nome
# dos submódulos (core.indicators função vs core.indicators módulo).
# O próprio htf.py usa este mesmo padrão internamente.
import core.indicators  # noqa: F401 — força registro em sys.modules
import core.signals  # noqa: F401
_ind = sys.modules["core.indicators"]
_sig = sys.modules["core.signals"]

from core.htf import merge_all_htf_to_ltf, prepare_htf


N = 400  # > EMA200 + slope window


def _make_ohlcv(n: int = N, start_ts: str = "2026-01-01",
                freq: str = "4h", seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    times = pd.date_range(start=start_ts, periods=n, freq=freq)
    close = 100.0 + np.cumsum(rng.normal(0.2, 1.5, n))
    return pd.DataFrame({
        "time": times,
        "open": close,
        "high": close * 1.002,
        "low": close * 0.998,
        "close": close,
        "vol": np.full(n, 1_000.0),
        "tbb": np.full(n, 500.0),
    })


# ────────────────────────────────────────────────────────────
# prepare_htf
# ────────────────────────────────────────────────────────────

class TestPrepareHtf:
    def test_adds_htf_score_and_macro_columns(self):
        df = _make_ohlcv()
        out = prepare_htf(df, "4h")
        assert "htf_score" in out.columns
        assert "htf_macro" in out.columns

    def test_htf_macro_is_enum(self):
        df = _make_ohlcv()
        out = prepare_htf(df, "4h")
        assert set(out["htf_macro"].dropna().unique()).issubset({"BULL", "BEAR", "CHOP"})

    def test_htf_score_bounded_0_1(self):
        df = _make_ohlcv()
        out = prepare_htf(df, "4h")
        scores = out["htf_score"].dropna()
        assert (scores >= 0).all()
        assert (scores <= 1.0).all()

    def test_length_preserved(self):
        df = _make_ohlcv()
        out = prepare_htf(df, "4h")
        assert len(out) == len(df)

    def test_restores_patched_params_after_call(self):
        """finally: restaura SLOPE_N/PIVOT_N/CHOP_S21/CHOP_S200/MIN_STOP_PCT.

        Se prepare_htf fizer patching global e não restaurar, próximas chamadas
        de indicators()/signals() em LTF usariam params errados — bug silencioso.
        """
        saved = (_ind.SLOPE_N, _ind.PIVOT_N,
                 _sig.CHOP_S21, _sig.CHOP_S200, _sig.MIN_STOP_PCT)
        df = _make_ohlcv()
        prepare_htf(df, "4h")
        after = (_ind.SLOPE_N, _ind.PIVOT_N,
                 _sig.CHOP_S21, _sig.CHOP_S200, _sig.MIN_STOP_PCT)
        assert saved == after

    def test_restores_params_even_on_exception(self):
        # Passar df vazio pode crashear; params devem ser restaurados via finally
        saved = (_ind.SLOPE_N, _ind.PIVOT_N,
                 _sig.CHOP_S21, _sig.CHOP_S200, _sig.MIN_STOP_PCT)
        try:
            prepare_htf(pd.DataFrame(), "4h")
        except Exception:
            pass
        after = (_ind.SLOPE_N, _ind.PIVOT_N,
                 _sig.CHOP_S21, _sig.CHOP_S200, _sig.MIN_STOP_PCT)
        assert saved == after


# ────────────────────────────────────────────────────────────
# merge_all_htf_to_ltf
# ────────────────────────────────────────────────────────────

class TestMergeHtfToLtf:
    def _ltf_df(self, n: int = 300) -> pd.DataFrame:
        return _make_ohlcv(n=n, freq="15min")

    def _htf_df(self, n: int = 100, freq: str = "4h") -> pd.DataFrame:
        # Simplified HTF frame with just the columns merge_all_htf_to_ltf needs
        times = pd.date_range(start="2026-01-01", periods=n, freq=freq)
        return pd.DataFrame({
            "time": times,
            "trend_struct": np.random.default_rng(0).choice(
                ["UP", "DOWN", "NEUTRAL"], n
            ),
            "struct_strength": np.random.default_rng(1).uniform(0, 1, n),
            "htf_score": np.random.default_rng(2).uniform(0, 1, n),
            "htf_macro": np.random.default_rng(3).choice(
                ["BULL", "BEAR", "CHOP"], n
            ),
        })

    def test_adds_htf_columns_for_each_stack_entry(self):
        ltf = self._ltf_df()
        stack = {"4h": self._htf_df(), "1d": self._htf_df(freq="1D")}
        out = merge_all_htf_to_ltf(ltf, stack)
        for i in (1, 2):
            for col in (f"htf{i}_struct", f"htf{i}_strength",
                        f"htf{i}_score", f"htf{i}_macro"):
                assert col in out.columns

    def test_length_preserved(self):
        ltf = self._ltf_df()
        stack = {"4h": self._htf_df()}
        out = merge_all_htf_to_ltf(ltf, stack)
        assert len(out) == len(ltf)

    def test_fills_nan_with_neutral_defaults(self):
        """LTF bars antes do primeiro HTF bar fechar → default NEUTRAL/0.0/CHOP."""
        # LTF starts before HTF data → early bars have no HTF match
        ltf = self._ltf_df(n=100)
        # HTF starts 30 days later, so all LTF bars are before HTF
        future_htf = self._htf_df(n=20)
        future_htf["time"] = future_htf["time"] + pd.Timedelta(days=30)
        out = merge_all_htf_to_ltf(ltf, {"4h": future_htf})
        # All LTF bars should have default values
        assert (out["htf1_struct"] == "NEUTRAL").all()
        assert (out["htf1_strength"] == 0.0).all()
        assert (out["htf1_score"] == 0.0).all()
        assert (out["htf1_macro"] == "CHOP").all()

    def test_no_lookahead_time_shift_applied(self):
        """CRÍTICO: HTF bar só deve influenciar LTF DEPOIS que HTF fechou.

        merge_all_htf_to_ltf adiciona tf_minutes ao time HTF antes do
        merge_asof backward. Então um HTF 4h que fecha às 04:00 só aparece
        pros LTF bars >= 08:00 (o "time" shifted é 04:00 + 4h = 08:00).

        Sem isso, o backtest enxerga o futuro.
        """
        # LTF a cada 15min, HTF 4h
        ltf_times = pd.date_range("2026-01-01", periods=40, freq="15min")
        ltf = pd.DataFrame({
            "time": ltf_times,
            "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0,
        })
        # Um único HTF bar às 04:00 com sinal distintivo
        htf = pd.DataFrame({
            "time": pd.to_datetime(["2026-01-01 04:00"]),
            "trend_struct": ["UP"],
            "struct_strength": [0.99],
            "htf_score": [0.77],
            "htf_macro": ["BULL"],
        })
        out = merge_all_htf_to_ltf(ltf, {"4h": htf})
        # Bars antes de 08:00 (04:00 + 4h shift) devem ser NEUTRAL
        before_shift = out[out["time"] < pd.Timestamp("2026-01-01 08:00")]
        assert (before_shift["htf1_struct"] == "NEUTRAL").all()
        # Bars a partir de 08:00 devem ver UP
        after_shift = out[out["time"] >= pd.Timestamp("2026-01-01 08:00")]
        assert (after_shift["htf1_struct"] == "UP").all()
        assert (after_shift["htf1_score"] == 0.77).all()

    def test_stack_ordering_maps_to_indexed_columns(self):
        """Primeiro tf → htf1_*; segundo → htf2_*."""
        ltf = self._ltf_df()
        stack = {
            "4h": self._htf_df(n=100, freq="4h"),
            "1d": self._htf_df(n=20, freq="1D"),
        }
        out = merge_all_htf_to_ltf(ltf, stack)
        assert "htf1_macro" in out.columns
        assert "htf2_macro" in out.columns
        # htf3_ não deveria existir (apenas 2 tfs no stack)
        assert "htf3_macro" not in out.columns
