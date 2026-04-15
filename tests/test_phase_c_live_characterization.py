import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import datetime as dt

import pytest

from engines import live as live_mod
from engines.live import LiveEngine, SignalEngine


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "phase_c" / "live"
RECORDED_STATE = ROOT / "data" / "live" / "2026-04-09_1503" / "state" / "positions.json"

pytestmark = pytest.mark.skipif(
    not RECORDED_STATE.exists(),
    reason="recorded live state dir cleaned up — replay fixture not yet wired",
)


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class _FixedDateTime:
    @classmethod
    def now(cls, tz=None):
        return dt.datetime(2026, 4, 13, 12, 0, 0, tzinfo=tz)


class _FakeBrokerClient:
    def __init__(self, payload):
        self._payload = payload

    def futures_position_information(self):
        return self._payload


def test_build_signal_dict_matches_base_snapshot(monkeypatch):
    monkeypatch.setattr(live_mod, "datetime", _FixedDateTime)
    engine = SignalEngine(buffer=None)

    signal = engine.build_signal_dict(
        symbol="BTCUSDT",
        size=1234.5678,
        score=0.6123,
        direction="BULLISH",
        entry_price=43210.12345678,
        stop=42890.0,
        target=43850.5,
        rr=2.1,
        macro_b="BULL",
        vol_r="NORMAL",
        corr_mult=0.85,
        struct="UP",
        symbol_pnl={},
        drift_summary={},
        is_chop_trade=False,
    )

    expected = _load_json(FIXTURES / "build_signal_dict_base.json")
    assert signal == expected


def test_build_signal_dict_applies_drift_penalty_without_changing_fields(monkeypatch):
    monkeypatch.setattr(live_mod, "datetime", _FixedDateTime)
    engine = SignalEngine(buffer=None)

    signal = engine.build_signal_dict(
        symbol="BTCUSDT",
        size=1234.5678,
        score=0.6123,
        direction="BULLISH",
        entry_price=43210.12345678,
        stop=42890.0,
        target=43850.5,
        rr=2.1,
        macro_b="BULL",
        vol_r="NORMAL",
        corr_mult=0.85,
        struct="UP",
        symbol_pnl={},
        drift_summary={"n": 10, "drift_mean": -0.2},
        is_chop_trade=False,
    )

    expected = _load_json(FIXTURES / "build_signal_dict_drift_penalty.json")
    assert signal == expected


def test_build_signal_dict_blocks_symbol_rank_and_records_veto(monkeypatch):
    monkeypatch.setattr(live_mod, "datetime", _FixedDateTime)
    engine = SignalEngine(buffer=None)

    signal = engine.build_signal_dict(
        symbol="BTCUSDT",
        size=1234.5678,
        score=0.6123,
        direction="BULLISH",
        entry_price=43210.12345678,
        stop=42890.0,
        target=43850.5,
        rr=2.1,
        macro_b="BULL",
        vol_r="NORMAL",
        corr_mult=0.85,
        struct="UP",
        symbol_pnl={"BTCUSDT": [-200.0] * 10},
        drift_summary={},
        is_chop_trade=False,
    )

    assert signal is None
    assert engine.last_veto["BTCUSDT"]["reason"] == "symbol_rank_block"
    assert engine.last_veto["BTCUSDT"]["extra"] == "pnl_10t=-2000.0"


def test_startup_reconcile_matches_recorded_empty_local_state():
    recorded = _load_json(RECORDED_STATE)
    assert recorded["positions"] == []

    engine = LiveEngine.__new__(LiveEngine)
    engine.orders = SimpleNamespace(
        paper=False,
        client=_FakeBrokerClient(_load_json(FIXTURES / "broker_positions_empty.json")),
    )
    engine.positions = []
    engine.killed = False

    asyncio.run(engine._startup_reconcile())

    assert engine.killed is False


def test_startup_reconcile_kills_on_broker_mismatch_against_recorded_empty_local_state():
    recorded = _load_json(RECORDED_STATE)
    assert recorded["positions"] == []

    engine = LiveEngine.__new__(LiveEngine)
    engine.orders = SimpleNamespace(
        paper=False,
        client=_FakeBrokerClient(_load_json(FIXTURES / "broker_positions_btc_only.json")),
    )
    engine.positions = []
    engine.killed = False

    asyncio.run(engine._startup_reconcile())

    assert engine.killed is True
