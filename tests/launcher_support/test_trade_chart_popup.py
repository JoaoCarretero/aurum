"""Unit tests for trade_chart_popup pure helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from launcher_support.trade_chart_popup import (
    build_marker_specs,
    derive_candle_window,
    fetch_binance_candles,
    parse_klines_to_df,
    resolve_tf,
    tf_to_seconds,
)


# ─── resolve_tf (reads params.ENGINE_INTERVALS) ─────────────────────
class TestResolveTf:
    def test_citadel(self):
        assert resolve_tf("CITADEL") == "15m"

    def test_renaissance(self):
        assert resolve_tf("RENAISSANCE") == "15m"

    def test_jump(self):
        assert resolve_tf("JUMP") == "1h"

    def test_de_shaw_alias(self):
        # Logger name DE_SHAW maps to params key DESHAW
        assert resolve_tf("DE_SHAW") == "1h"

    def test_deshaw_direct(self):
        assert resolve_tf("DESHAW") == "1h"

    def test_bridgewater(self):
        assert resolve_tf("BRIDGEWATER") == "1h"

    def test_case_insensitive(self):
        assert resolve_tf("citadel") == "15m"
        assert resolve_tf("Jump") == "1h"

    def test_unknown_engine_fallback(self):
        # KEPOS/MEDALLION/PHI not in ENGINE_INTERVALS — fallback to INTERVAL
        from config.params import INTERVAL
        assert resolve_tf("KEPOS") == INTERVAL
        assert resolve_tf("MEDALLION") == INTERVAL

    def test_none_fallback(self):
        from config.params import INTERVAL
        assert resolve_tf(None) == INTERVAL

    def test_empty_fallback(self):
        from config.params import INTERVAL
        assert resolve_tf("") == INTERVAL


# ─── tf_to_seconds ──────────────────────────────────────────────────
class TestTfToSeconds:
    @pytest.mark.parametrize("tf,sec", [
        ("1m", 60),
        ("5m", 300),
        ("15m", 900),
        ("30m", 1800),
        ("1h", 3600),
        ("4h", 14400),
        ("1d", 86400),
    ])
    def test_known_tfs(self, tf, sec):
        assert tf_to_seconds(tf) == sec

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            tf_to_seconds("7h")


# ─── derive_candle_window ───────────────────────────────────────────
class TestDeriveCandleWindow:
    def test_closed_trade_basic(self):
        # Entry at 1000, exit at 1900 (1h tf, 15 candles)
        entry_ts = 1_000_000
        exit_ts = entry_ts + 15 * 3600
        start, end = derive_candle_window(entry_ts, exit_ts, tf_sec=3600)
        duration = 15
        window = max(20, int(duration * 1.6))  # 24 candles total
        pad = (window - duration) // 2  # 4 on each side
        assert start == entry_ts - pad * 3600
        assert end == exit_ts + pad * 3600

    def test_short_trade_min_window(self):
        # Trade of 2 candles → window floors at 20
        entry_ts = 1_000_000
        exit_ts = entry_ts + 2 * 3600
        start, end = derive_candle_window(entry_ts, exit_ts, tf_sec=3600)
        assert end - start >= 20 * 3600

    def test_live_trade(self):
        entry_ts = 1_000_000
        start, end = derive_candle_window(entry_ts, None, tf_sec=3600,
                                          now_ts=entry_ts + 10 * 3600)
        # LIVE: duration_candles=20 minimum, pad split both sides
        assert end - start >= 20 * 3600

    def test_window_caps_at_500(self):
        # 1000-candle trade should cap at 500
        entry_ts = 1_000_000
        exit_ts = entry_ts + 1000 * 3600
        start, end = derive_candle_window(entry_ts, exit_ts, tf_sec=3600)
        assert (end - start) // 3600 <= 500


# ─── build_marker_specs ─────────────────────────────────────────────
class TestBuildMarkerSpecs:
    def _trade(self, **overrides):
        base = {
            "entry": 0.0776, "stop": 0.0810, "target": 0.0742,
            "exit_p": 0.0742, "result": "WIN", "direction": "BEARISH",
            "timestamp": "2026-04-21T23:00:00",
            "duration": 9,
        }
        base.update(overrides)
        return base

    def test_closed_trade_all_levels(self):
        specs = build_marker_specs(self._trade(), tf_sec=900)
        levels = {s["kind"]: s for s in specs if s.get("kind")}
        assert "entry" in levels
        assert "stop" in levels
        assert "target" in levels
        assert "exit" in levels
        assert levels["entry"]["price"] == 0.0776

    def test_live_trade_no_exit_marker(self):
        specs = build_marker_specs(
            self._trade(result="LIVE", exit_p=None, duration=0),
            tf_sec=900,
        )
        kinds = {s.get("kind") for s in specs}
        assert "current" in kinds  # pulsing current price instead
        assert "exit" not in kinds

    def test_missing_stop_omitted(self):
        specs = build_marker_specs(
            self._trade(stop=0), tf_sec=900)
        kinds = {s.get("kind") for s in specs}
        assert "stop" not in kinds
        assert "entry" in kinds

    def test_missing_target_omitted(self):
        specs = build_marker_specs(
            self._trade(target=None), tf_sec=900)
        kinds = {s.get("kind") for s in specs}
        assert "target" not in kinds


# ─── parse_klines_to_df ─────────────────────────────────────────────
class TestParseKlinesToDf:
    def test_basic(self):
        # Binance kline format: [open_ts_ms, O, H, L, C, V, close_ts, ...]
        klines = [
            [1700000000000, "0.10", "0.12", "0.09", "0.11", "1000.0",
             1700003599999, "0", 0, "0", "0", "0"],
            [1700003600000, "0.11", "0.13", "0.10", "0.12", "1500.0",
             1700007199999, "0", 0, "0", "0", "0"],
        ]
        df = parse_klines_to_df(klines)
        assert len(df) == 2
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert df.iloc[0]["Open"] == 0.10
        assert df.iloc[0]["Close"] == 0.11
        # Index is datetime
        assert df.index.inferred_type in ("datetime64", "datetime")

    def test_empty(self):
        df = parse_klines_to_df([])
        assert len(df) == 0
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]


# ─── fetch_binance_candles (mocked urllib) ──────────────────────────
class TestFetchBinanceCandles:
    @patch("launcher_support.trade_chart_popup.urllib.request.urlopen")
    def test_successful_fetch(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'[[1700000000000,"0.1","0.12","0.09","0.11","1000.0",1700003599999,"0",0,"0","0","0"]]'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda *a: None
        mock_urlopen.return_value = mock_resp

        df = fetch_binance_candles("SANDUSDT", "1h",
                                   start_ts=1700000000,
                                   end_ts=1700003600)
        assert len(df) == 1
        assert df.iloc[0]["Close"] == 0.11

    @patch("launcher_support.trade_chart_popup.urllib.request.urlopen")
    def test_http_error_returns_empty(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://test", 429, "Too Many Requests", {}, None)
        df = fetch_binance_candles("SANDUSDT", "1h",
                                   start_ts=1700000000,
                                   end_ts=1700003600)
        assert len(df) == 0

    @patch("launcher_support.trade_chart_popup.urllib.request.urlopen")
    def test_timeout_returns_empty(self, mock_urlopen):
        mock_urlopen.side_effect = TimeoutError()
        df = fetch_binance_candles("SANDUSDT", "1h",
                                   start_ts=1700000000,
                                   end_ts=1700003600)
        assert len(df) == 0
