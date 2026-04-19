"""Unit tests for MetricsStreamer and sparkline helper."""
from tools.operations.paper_metrics import MetricsStreamer, sparkline, SPARK_CHARS


def test_sparkline_empty_returns_empty_string():
    assert sparkline([]) == ""


def test_sparkline_flat_returns_middle_char():
    s = sparkline([100.0, 100.0, 100.0])
    assert len(s) == 3
    # All same char (middle band)
    assert s[0] == s[1] == s[2]


def test_sparkline_range_uses_full_scale():
    s = sparkline([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
    assert s[0] == SPARK_CHARS[0]   # lowest
    assert s[-1] == SPARK_CHARS[-1]  # highest


def test_metrics_streamer_tracks_equity_points():
    ms = MetricsStreamer(account_size=10_000.0)
    ms.record_equity_point(tick=1, ts="t1", equity=10_100.0, balance=10_050.0,
                           realized=50.0, unrealized=50.0, drawdown=0.0,
                           positions_open=1)
    ms.record_equity_point(tick=2, ts="t2", equity=10_200.0, balance=10_100.0,
                           realized=100.0, unrealized=100.0, drawdown=0.0,
                           positions_open=1)
    pts = ms.equity_points()
    assert len(pts) == 2
    assert pts[-1]["equity"] == 10_200.0


def test_metrics_streamer_computes_from_trades():
    ms = MetricsStreamer(account_size=10_000.0)
    ms.record_closed({"primed": False, "pnl": 50.0, "strategy": "CITADEL"})
    ms.record_closed({"primed": False, "pnl": -20.0, "strategy": "JUMP"})
    m = ms.current_metrics()
    assert m["n_trades"] == 2
    assert m["wins"] == 1
    assert m["net_pnl"] == 30.0


def test_metrics_uses_configured_account_size_for_roi():
    ms = MetricsStreamer(account_size=100_000.0)
    ms.record_closed({"primed": False, "pnl": 1000.0, "strategy": "X"})
    m = ms.current_metrics()
    # roi = 1000 / 100_000 * 100 = 1.0
    assert round(m["roi_pct"], 2) == 1.0
