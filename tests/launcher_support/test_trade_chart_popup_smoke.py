"""Smoke tests — TradeChartPopup instantiates & destroys cleanly.

Skips on headless CI (no DISPLAY) following existing project pattern.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("CI") == "true" and not os.environ.get("DISPLAY"),
    reason="needs display",
)


@pytest.fixture
def tk_root():
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture
def stub_colors():
    return {
        "BG": "#0a0a0a", "PANEL": "#1a1a1a", "BG2": "#202020",
        "AMBER": "#FFB000", "AMBER_B": "#FFC940", "AMBER_D": "#C08000",
        "GREEN": "#44FF88", "RED": "#FF4444",
        "WHITE": "#FFFFFF", "DIM": "#888888", "DIM2": "#555555",
        "BORDER": "#333333",
    }


def _closed_trade():
    return {
        "symbol": "SANDUSDT", "strategy": "JUMP",
        "direction": "BEARISH",
        "timestamp": "2026-04-21T23:00:00+00:00",
        "entry": 0.0776, "stop": 0.0810, "target": 0.0742,
        "exit_p": 0.0742, "duration": 9,
        "result": "WIN", "exit_reason": "target",
        "r_multiple": 1.80, "pnl": 24.30, "size": 16784.609,
    }


def _live_trade():
    return {
        "symbol": "NEARUSDT", "strategy": "CITADEL",
        "direction": "BULLISH",
        "timestamp": "2026-04-21T23:30:00+00:00",
        "entry": 4.85, "stop": 4.70, "target": 5.20,
        "exit_p": 4.92, "duration": 0,
        "result": "LIVE", "exit_reason": "live",
        "r_multiple": 0.0, "pnl": 8.20, "size": 412.37,
    }


@patch("launcher_support.trade_chart_popup.fetch_binance_candles")
def test_closed_trade_popup_renders(mock_fetch, tk_root, stub_colors):
    """Popup builds, shows chart placeholder (empty DF), destroys cleanly."""
    import pandas as pd
    from launcher_support.trade_chart_popup import TradeChartPopup

    mock_fetch.return_value = pd.DataFrame(
        columns=["Open", "High", "Low", "Close", "Volume"])

    popup = TradeChartPopup(tk_root, _closed_trade(), run_id="test-run",
                            colors=stub_colors, font_name="Consolas")
    assert popup.top.winfo_exists()
    assert popup.engine == "JUMP"
    assert popup.tf == "1h"  # from ENGINE_INTERVALS
    assert popup.symbol == "SANDUSDT"
    popup.destroy()
    assert popup._destroyed is True


@patch("launcher_support.trade_chart_popup.fetch_binance_candles")
def test_live_trade_popup_schedules_refresh(mock_fetch, tk_root, stub_colors):
    """LIVE trade schedules an after() callback for refresh."""
    import pandas as pd
    from launcher_support.trade_chart_popup import TradeChartPopup

    mock_fetch.return_value = pd.DataFrame(
        columns=["Open", "High", "Low", "Close", "Volume"])

    popup = TradeChartPopup(tk_root, _live_trade(), run_id="test-run",
                            colors=stub_colors, font_name="Consolas")
    assert popup._after_id is not None
    assert popup.tf == "15m"  # CITADEL from ENGINE_INTERVALS
    popup.destroy()


@patch("launcher_support.trade_chart_popup.fetch_binance_candles")
def test_open_trade_chart_reuses_popup(mock_fetch, tk_root, stub_colors):
    """Clicking twice on same trade lifts existing popup instead of duplicating."""
    import pandas as pd
    from launcher_support.trade_chart_popup import open_trade_chart

    mock_fetch.return_value = pd.DataFrame(
        columns=["Open", "High", "Low", "Close", "Volume"])

    trade = _closed_trade()
    first = open_trade_chart(tk_root, trade, "test-run",
                             colors=stub_colors, font_name="Consolas")
    second = open_trade_chart(tk_root, trade, "test-run",
                              colors=stub_colors, font_name="Consolas")
    assert first is second
    first.destroy()
