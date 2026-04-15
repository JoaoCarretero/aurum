"""Contract tests for core.htf_filter — HTF alignment veto layer.

Covers:
- htf_agrees: veto on BULLISH+DOWN / BEARISH+UP; NEUTRAL passes both;
  missing symbol → True (no veto)
- htf_contrarian: veto on BULLISH+UP / BEARISH+DOWN (opposite polarity
  to htf_agrees); NEUTRAL passes; missing symbol → True
- htf_macro: missing symbol → "CHOP"; reads df value when present;
  idx beyond df length → "CHOP"
- prepare_htf_context: missing HTF df → None; short HTF (<50 bars) →
  None; prepare_htf exception → None (graceful)
"""
from __future__ import annotations

import pandas as pd

from core.htf_filter import (
    htf_agrees,
    htf_contrarian,
    htf_macro,
    prepare_htf_context,
)


def _mk_ctx(symbol: str, struct_values: list[str],
            macro_values: list[str] | None = None) -> dict:
    macro = macro_values or ["CHOP"] * len(struct_values)
    return {
        symbol: pd.DataFrame({
            "htf_struct": struct_values,
            "htf_macro":  macro,
        })
    }


# ────────────────────────────────────────────────────────────
# htf_agrees
# ────────────────────────────────────────────────────────────

class TestHtfAgrees:
    def test_missing_symbol_does_not_veto(self):
        assert htf_agrees({}, "BTC", 0, "BULLISH") is True
        assert htf_agrees({}, "BTC", 0, "BEARISH") is True

    def test_idx_out_of_bounds_passes(self):
        ctx = _mk_ctx("BTC", ["UP"])
        assert htf_agrees(ctx, "BTC", 99, "BULLISH") is True

    def test_bullish_vetoed_by_down(self):
        ctx = _mk_ctx("BTC", ["DOWN"])
        assert htf_agrees(ctx, "BTC", 0, "BULLISH") is False

    def test_bearish_vetoed_by_up(self):
        ctx = _mk_ctx("BTC", ["UP"])
        assert htf_agrees(ctx, "BTC", 0, "BEARISH") is False

    def test_neutral_passes_both_directions(self):
        ctx = _mk_ctx("BTC", ["NEUTRAL"])
        assert htf_agrees(ctx, "BTC", 0, "BULLISH") is True
        assert htf_agrees(ctx, "BTC", 0, "BEARISH") is True

    def test_bullish_with_up_passes(self):
        ctx = _mk_ctx("BTC", ["UP"])
        assert htf_agrees(ctx, "BTC", 0, "BULLISH") is True

    def test_bearish_with_down_passes(self):
        ctx = _mk_ctx("BTC", ["DOWN"])
        assert htf_agrees(ctx, "BTC", 0, "BEARISH") is True


# ────────────────────────────────────────────────────────────
# htf_contrarian (opposite logic)
# ────────────────────────────────────────────────────────────

class TestHtfContrarian:
    def test_missing_symbol_passes(self):
        assert htf_contrarian({}, "BTC", 0, "BULLISH") is True

    def test_bullish_into_up_vetoed(self):
        # Contrarian: don't buy into existing strength
        ctx = _mk_ctx("BTC", ["UP"])
        assert htf_contrarian(ctx, "BTC", 0, "BULLISH") is False

    def test_bearish_into_down_vetoed(self):
        ctx = _mk_ctx("BTC", ["DOWN"])
        assert htf_contrarian(ctx, "BTC", 0, "BEARISH") is False

    def test_opposite_polarity_to_htf_agrees(self):
        # For any non-NEUTRAL struct, htf_agrees and htf_contrarian
        # should disagree — one vetoes, the other passes.
        for struct in ("UP", "DOWN"):
            for direction in ("BULLISH", "BEARISH"):
                ctx = _mk_ctx("BTC", [struct])
                assert (
                    htf_agrees(ctx, "BTC", 0, direction)
                    != htf_contrarian(ctx, "BTC", 0, direction)
                )

    def test_neutral_passes_contrarian(self):
        ctx = _mk_ctx("BTC", ["NEUTRAL"])
        assert htf_contrarian(ctx, "BTC", 0, "BULLISH") is True
        assert htf_contrarian(ctx, "BTC", 0, "BEARISH") is True


# ────────────────────────────────────────────────────────────
# htf_macro
# ────────────────────────────────────────────────────────────

class TestHtfMacro:
    def test_missing_symbol_returns_chop(self):
        assert htf_macro({}, "BTC", 0) == "CHOP"

    def test_idx_out_of_bounds_returns_chop(self):
        ctx = _mk_ctx("BTC", ["UP"], ["BULL"])
        assert htf_macro(ctx, "BTC", 99) == "CHOP"

    def test_reads_macro_value(self):
        ctx = _mk_ctx("BTC", ["UP", "DOWN"], ["BULL", "BEAR"])
        assert htf_macro(ctx, "BTC", 0) == "BULL"
        assert htf_macro(ctx, "BTC", 1) == "BEAR"


# ────────────────────────────────────────────────────────────
# prepare_htf_context — guarded paths
# ────────────────────────────────────────────────────────────

class TestPrepareHtfContextGuards:
    def test_missing_htf_df_becomes_none(self):
        ltf = {"BTC": pd.DataFrame({"time": pd.date_range("2025-01-01", periods=5)})}
        ctx = prepare_htf_context(ltf, htf_dfs={})
        assert ctx["BTC"] is None

    def test_short_htf_df_becomes_none(self):
        ltf = {"BTC": pd.DataFrame({"time": pd.date_range("2025-01-01", periods=5)})}
        htf = {"BTC": pd.DataFrame({"time": pd.date_range("2025-01-01", periods=10)})}
        ctx = prepare_htf_context(ltf, htf_dfs=htf)
        assert ctx["BTC"] is None  # <50 bars

    def test_prepare_exception_becomes_none(self, monkeypatch):
        # Force prepare_htf to raise — module should catch and set None
        def boom(*args, **kwargs):
            raise RuntimeError("sim failure")
        monkeypatch.setattr("core.htf.prepare_htf", boom)

        ltf = {"BTC": pd.DataFrame({"time": pd.date_range("2025-01-01", periods=5)})}
        # Provide enough bars (>=50) so we hit prepare_htf
        htf = {"BTC": pd.DataFrame({"time": pd.date_range("2025-01-01", periods=100)})}
        ctx = prepare_htf_context(ltf, htf_dfs=htf)
        assert ctx["BTC"] is None
