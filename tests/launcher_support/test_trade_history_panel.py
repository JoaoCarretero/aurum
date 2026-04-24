"""Unit tests for trade_history_panel formatters."""
from __future__ import annotations

import pytest

from launcher_support.trade_history_panel import (
    format_duration,
    format_r_multiple,
    format_trade_row,
    normalize_direction,
    resolve_exit_marker,
)


# ─── normalize_direction ────────────────────────────────────────────
class TestNormalizeDirection:
    def test_bullish_to_long(self):
        assert normalize_direction("BULLISH") == "LONG"

    def test_bearish_to_short(self):
        assert normalize_direction("BEARISH") == "SHORT"

    def test_long_unchanged(self):
        assert normalize_direction("LONG") == "LONG"

    def test_short_unchanged(self):
        assert normalize_direction("SHORT") == "SHORT"

    def test_case_insensitive(self):
        assert normalize_direction("bullish") == "LONG"
        assert normalize_direction("Short") == "SHORT"

    def test_none(self):
        assert normalize_direction(None) == "—"

    def test_empty(self):
        assert normalize_direction("") == "—"

    def test_unknown(self):
        assert normalize_direction("NEUTRAL") == "NEUTRAL"


# ─── format_r_multiple ──────────────────────────────────────────────
class TestFormatRMultiple:
    def test_positive(self):
        assert format_r_multiple(1.80, result="WIN") == "+1.80R"

    def test_negative(self):
        assert format_r_multiple(-1.00, result="LOSS") == "-1.00R"

    def test_zero_live(self):
        assert format_r_multiple(0.0, result="LIVE") == "LIVE"

    def test_none(self):
        assert format_r_multiple(None, result="WIN") == "—"

    def test_small_positive(self):
        assert format_r_multiple(0.05, result="WIN") == "+0.05R"


# ─── format_duration ────────────────────────────────────────────────
class TestFormatDuration:
    def test_under_one_minute(self):
        # duration in candles; tf=900 → 1 candle = 15min
        # 0 candles → "<1m"
        assert format_duration(0, tf_sec=900) == "<1m"

    def test_minutes_only(self):
        # 3 candles × 15min = 45min
        assert format_duration(3, tf_sec=900) == "45m"

    def test_hours_and_minutes(self):
        # 9 candles × 15min = 2h15m
        assert format_duration(9, tf_sec=900) == "2h15m"

    def test_exact_hours(self):
        # 4 candles × 1h = 4h00m → "4h"
        assert format_duration(4, tf_sec=3600) == "4h"

    def test_days(self):
        # 48 candles × 1h = 48h → "2d"
        assert format_duration(48, tf_sec=3600) == "2d"

    def test_days_and_hours(self):
        # 50 candles × 1h = 50h → "2d2h"
        assert format_duration(50, tf_sec=3600) == "2d2h"

    def test_none(self):
        assert format_duration(None, tf_sec=900) == "—"


# ─── resolve_exit_marker ────────────────────────────────────────────
class TestResolveExitMarker:
    def test_target(self):
        assert resolve_exit_marker({"exit_reason": "target",
                                    "result": "WIN"}) == "TP_HIT"

    def test_stop(self):
        assert resolve_exit_marker({"exit_reason": "stop",
                                    "result": "LOSS"}) == "STOP"

    def test_trail(self):
        assert resolve_exit_marker({"exit_reason": "trail",
                                    "result": "WIN"}) == "TRAIL"

    def test_time(self):
        assert resolve_exit_marker({"exit_reason": "time",
                                    "result": "WIN"}) == "TIME"

    def test_live(self):
        assert resolve_exit_marker({"exit_reason": "live",
                                    "result": "LIVE"}) == "—"

    def test_missing(self):
        assert resolve_exit_marker({}) == "—"


# ─── format_trade_row (integration of formatters) ───────────────────
class TestFormatTradeRow:
    def _base(self, **overrides):
        base = {
            "symbol": "SANDUSDT",
            "strategy": "JUMP",
            "direction": "BEARISH",
            "entry": 0.0776,
            "exit_p": 0.0742,
            "r_multiple": 1.80,
            "pnl": 24.30,
            "duration": 9,  # candles
            "result": "WIN",
            "exit_reason": "target",
        }
        base.update(overrides)
        return base

    def test_closed_short_win(self):
        row = format_trade_row(self._base(), tf_sec=900)
        assert row["symbol"] == "SANDUSDT"
        assert row["engine"] == "JUMP"
        assert row["direction"] == "SHORT"
        assert row["dir_arrow"] == "▼"  # SHORT = down arrow
        assert row["levels"] == "0.0776→0.0742"
        assert row["r_mult"] == "+1.80R"
        assert row["pnl"] == "+$24.30"
        assert row["duration"] == "2h15m"
        assert row["exit_marker"] == "TP_HIT"

    def test_closed_long_loss(self):
        row = format_trade_row(
            self._base(direction="BULLISH", result="LOSS",
                       exit_reason="stop", r_multiple=-1.0, pnl=-15.0),
            tf_sec=900,
        )
        assert row["direction"] == "LONG"
        assert row["dir_arrow"] == "▲"  # LONG = up arrow
        assert row["r_mult"] == "-1.00R"
        assert row["pnl"] == "-$15.00"
        assert row["exit_marker"] == "STOP"

    def test_live_trade(self):
        row = format_trade_row(
            self._base(result="LIVE", exit_reason="live",
                       r_multiple=0.0, pnl=8.20, duration=0),
            tf_sec=900,
        )
        assert row["r_mult"] == "LIVE"
        assert row["pnl"] == "+$8.20"
        assert row["duration"] == "<1m"
        assert row["exit_marker"] == "—"

    def test_truncates_long_engine(self):
        row = format_trade_row(
            self._base(strategy="RENAISSANCE"), tf_sec=900)
        assert len(row["engine"]) <= 10  # column width
