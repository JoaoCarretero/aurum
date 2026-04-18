from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pandas as pd

from tools.capture import prewarm_sentiment_cache as tool


def test_resolve_symbols_uses_engine_basket_default():
    basket, symbols = tool._resolve_symbols("BRIDGEWATER", None, None)
    assert basket == "bluechip"
    assert "BTCUSDT" in symbols


def test_build_report_includes_generated_at_and_symbol_payload(monkeypatch):
    monkeypatch.setattr(
        tool,
        "fetch_funding_rate",
        lambda symbol, limit=0: pd.DataFrame({"time": pd.date_range("2026-01-01", periods=2, freq="8h")}),
    )
    monkeypatch.setattr(
        tool,
        "fetch_open_interest",
        lambda symbol, period="15m", limit=0: pd.DataFrame({"time": pd.date_range("2026-01-01", periods=3, freq="15min")}),
    )
    monkeypatch.setattr(
        tool,
        "fetch_long_short_ratio",
        lambda symbol, period="15m", limit=0: pd.DataFrame({"time": pd.date_range("2026-01-01", periods=4, freq="15min")}),
    )
    args = Namespace(
        engine="BRIDGEWATER",
        basket=None,
        symbols="BTC",
        period="15m",
        funding_limit=10,
        oi_limit=10,
        ls_limit=10,
        json=True,
        loop_minutes=0.0,
        iterations=0,
        heartbeat_file=None,
    )

    report = tool._build_report(args)

    assert report["basket"] == "custom"
    assert report["generated_at"]
    assert report["symbols"]["BTCUSDT"]["funding"]["rows"] == 2
    assert report["symbols"]["BTCUSDT"]["open_interest"]["rows"] == 3
    assert report["symbols"]["BTCUSDT"]["long_short_ratio"]["rows"] == 4


def test_main_loop_writes_heartbeat_and_stops_after_iterations(tmp_path, monkeypatch):
    monkeypatch.setattr(
        tool,
        "parse_args",
        lambda: Namespace(
            engine="BRIDGEWATER",
            basket=None,
            symbols="BTC",
            period="15m",
            funding_limit=10,
            oi_limit=10,
            ls_limit=10,
            json=False,
            loop_minutes=0.0001,
            iterations=2,
            heartbeat_file=str(tmp_path / "heartbeat.json"),
        ),
    )
    counter = {"n": 0}

    def _build_report(_args):
        counter["n"] += 1
        return {
            "engine": "BRIDGEWATER",
            "basket": "custom",
            "period": "15m",
            "generated_at": f"2026-04-17T13:00:0{counter['n']}Z",
            "symbols": {"BTCUSDT": {"funding": None, "open_interest": None, "long_short_ratio": None}},
        }

    monkeypatch.setattr(tool, "_build_report", _build_report)
    monkeypatch.setattr(tool, "_emit_report", lambda report, json_mode: None)
    monkeypatch.setattr(tool.time, "sleep", lambda seconds: None)

    rc = tool.main()

    assert rc == 0
    assert counter["n"] == 2
    heartbeat = json.loads(Path(tmp_path / "heartbeat.json").read_text(encoding="utf-8"))
    assert heartbeat["generated_at"] == "2026-04-17T13:00:02Z"
