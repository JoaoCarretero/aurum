from __future__ import annotations

import pandas as pd

from tools.audits import bridgewater_sentiment_window_audit as audit


def test_joint_contiguous_start_uses_latest_channel_start(monkeypatch):
    def fake_earliest(kind, symbol, period):
        assert symbol == "BTCUSDT"
        return {
            "open_interest": pd.Timestamp("2026-03-17 23:30:00"),
            "long_short_ratio": pd.Timestamp("2026-03-18 14:30:00"),
        }[kind]

    monkeypatch.setattr(audit, "earliest_contiguous_ts", fake_earliest)

    joint, channels = audit.joint_contiguous_start("BTCUSDT", "15m")

    assert joint == pd.Timestamp("2026-03-18 14:30:00")
    assert channels["open_interest"] == "2026-03-17T23:30:00"
    assert channels["long_short_ratio"] == "2026-03-18T14:30:00"


def test_joint_contiguous_start_ignores_oi_when_disabled(monkeypatch):
    monkeypatch.setattr(
        audit,
        "earliest_contiguous_ts",
        lambda kind, symbol, period: {
            "open_interest": pd.Timestamp("2026-04-09 12:15:00"),
            "long_short_ratio": pd.Timestamp("2026-03-21 21:30:00"),
        }[kind],
    )

    joint, channels = audit.joint_contiguous_start("BTCUSDT", "15m", disable_oi=True)

    assert joint == pd.Timestamp("2026-03-21 21:30:00")
    assert channels["open_interest"] == "2026-04-09T12:15:00"
    assert channels["long_short_ratio"] == "2026-03-21T21:30:00"


def test_available_scan_candles_returns_zero_without_joint_start():
    assert audit.available_scan_candles(None, pd.Timestamp("2026-04-20"), "1h") == 0


def test_max_eligible_days_respects_fraction_and_max_hold():
    days = audit.max_eligible_days(available_candles=800, interval="1h", min_fraction=0.70, max_hold=48)

    assert days == 47.58


def test_build_report_uses_basket_blocker(monkeypatch):
    monkeypatch.setattr(
        audit,
        "_resolve_symbols",
        lambda engine, basket, symbols: ("bluechip", ["BTCUSDT", "ETHUSDT"]),
    )
    monkeypatch.setattr(
        audit,
        "audit_symbol",
        lambda symbol, **kwargs: {
            "symbol": symbol,
            "joint_start": "2026-03-18T14:30:00",
            "channel_starts": {"open_interest": None, "long_short_ratio": None},
            "available_scan_candles": 900 if symbol == "BTCUSDT" else 700,
            "max_eligible_days": 53.57 if symbol == "BTCUSDT" else 41.67,
        },
    )

    report = audit.build_report(
        audit.argparse.Namespace(
            engine="BRIDGEWATER",
            basket=None,
            symbols=None,
            interval="1h",
            period="15m",
            end="2026-04-20",
            disable_oi=False,
            min_fraction=0.70,
            max_hold=48,
        )
    )

    assert report["basket"] == "bluechip"
    assert report["basket_max_eligible_days"] == 41.67
    assert report["basket_blocker"] == "ETHUSDT"
    assert report["stable_symbols_30d"] == ["BTCUSDT", "ETHUSDT"]
    assert report["stable_symbols_30d_count"] == 2
