"""Tests for shared shadow-runner contract: pydantic models + discovery."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.shadow_contract import (
    Manifest,
    Heartbeat,
    RunSummary,
    find_runs,
    load_manifest,
    compute_config_hash,
)


def test_manifest_parses_valid_payload():
    payload = {
        "run_id": "2026-04-18_0229",
        "engine": "millennium",
        "mode": "shadow",
        "started_at": "2026-04-18T02:29:38.754671+00:00",
        "commit": "3fa328b",
        "branch": "feat/phi-engine",
        "config_hash": "sha256:deadbeef",
        "host": "vmi3200601",
    }
    m = Manifest(**payload)
    assert m.run_id == "2026-04-18_0229"
    assert m.engine == "millennium"
    assert m.mode == "shadow"


def test_manifest_rejects_unknown_mode():
    with pytest.raises(ValueError):
        Manifest(
            run_id="x", engine="millennium", mode="bogus",
            started_at=datetime.now(timezone.utc),
            commit="a", branch="b", config_hash="c", host="d",
        )


def test_heartbeat_accepts_null_last_error():
    hb = Heartbeat(
        run_id="x", status="running",
        ticks_ok=5, ticks_fail=0, novel_total=100,
        last_tick_at=datetime.now(timezone.utc),
        last_error=None, tick_sec=900,
    )
    assert hb.last_error is None


def test_heartbeat_rejects_unknown_status():
    with pytest.raises(ValueError):
        Heartbeat(
            run_id="x", status="bogus",
            ticks_ok=0, ticks_fail=0, novel_total=0,
            last_tick_at=None, last_error=None, tick_sec=900,
        )


def _make_run(root: Path, engine_subdir: str, run_id: str, hb_payload: dict) -> Path:
    run_dir = root / engine_subdir / run_id
    (run_dir / "state").mkdir(parents=True)
    (run_dir / "state" / "heartbeat.json").write_text(json.dumps(hb_payload))
    return run_dir


def test_find_runs_layout_a_millennium_shadow(tmp_path):
    hb = {
        "run_id": "2026-04-18_0229",
        "status": "running",
        "ticks_ok": 1, "ticks_fail": 0, "novel_total": 625,
        "last_tick_at": "2026-04-18T02:30:05+00:00",
        "last_error": None, "tick_sec": 900,
    }
    _make_run(tmp_path, "millennium_shadow", "2026-04-18_0229", hb)
    runs = find_runs(tmp_path)
    assert len(runs) == 1
    assert runs[0].name == "2026-04-18_0229"


def test_find_runs_layout_b_shadow_citadel(tmp_path):
    hb = {
        "run_id": "2026-04-18_0300",
        "status": "running",
        "ticks_ok": 0, "ticks_fail": 0, "novel_total": 0,
        "last_tick_at": None, "last_error": None, "tick_sec": 900,
    }
    _make_run(tmp_path, "shadow/citadel", "2026-04-18_0300", hb)
    runs = find_runs(tmp_path)
    assert len(runs) == 1


def test_find_runs_empty_when_no_data_root(tmp_path):
    assert find_runs(tmp_path / "nonexistent") == []


def test_find_runs_filter_by_engine(tmp_path):
    hb = {
        "run_id": "r", "status": "running",
        "ticks_ok": 0, "ticks_fail": 0, "novel_total": 0,
        "last_tick_at": None, "last_error": None, "tick_sec": 900,
    }
    _make_run(tmp_path, "millennium_shadow", "r1", hb)
    _make_run(tmp_path, "citadel_shadow", "r2", hb)
    only_mm = find_runs(tmp_path, engines=["millennium"])
    assert len(only_mm) == 1
    assert only_mm[0].parent.name == "millennium_shadow"


def test_load_manifest_returns_none_when_missing(tmp_path):
    hb = {
        "run_id": "x", "status": "running",
        "ticks_ok": 0, "ticks_fail": 0, "novel_total": 0,
        "last_tick_at": None, "last_error": None, "tick_sec": 900,
    }
    run_dir = _make_run(tmp_path, "millennium_shadow", "x", hb)
    assert load_manifest(run_dir) is None


def test_compute_config_hash_stable_format():
    h = compute_config_hash()
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 16


def test_trade_record_accepts_enriched_fields():
    """TradeRecord should type-check all enriched fields from shadow_trades.jsonl."""
    from core.shadow_contract import TradeRecord
    record = TradeRecord(
        timestamp="2026-04-18T12:00:00Z",
        symbol="BTCUSDT",
        strategy="CITADEL",
        direction="BULLISH",
        entry=65432.0,
        stop=65120.0,
        target=66950.0,
        exit_p=66210.0,
        rr=3.0,
        duration=5,
        result="WIN",
        exit_reason="trailing",
        size=285.4,
        score=0.5363,
        r_multiple=1.445,
        macro_bias="BULL",
        vol_regime="NORMAL",
        omega_struct=0.75,
        omega_flow=0.858,
        omega_cascade=0.25,
        omega_momentum=0.667,
        omega_pullback=0.933,
        struct="DOWN",
        struct_str=0.75,
        rsi=49.33,
        dist_ema21=0.101,
        chop_trade=False,
        dd_scale=1.0,
        corr_mult=1.0,
        hmm_regime=None,
        hmm_confidence=None,
        shadow_run_id="2026-04-18_0229",
    )
    assert record.stop == 65120.0
    assert record.result == "WIN"
    assert record.omega_struct == 0.75
    assert record.macro_bias == "BULL"


def test_trade_record_legacy_record_deserializes():
    """Legacy record without enriched fields should deserialize with defaults None."""
    from core.shadow_contract import TradeRecord
    record = TradeRecord(
        timestamp="2026-04-17T12:00:00Z",
        symbol="ETHUSDT",
        strategy="JUMP",
        direction="BEARISH",
        entry=3210.5,
    )
    assert record.stop is None
    assert record.result is None
    assert record.omega_struct is None
    assert record.macro_bias is None


def test_trade_record_extra_fields_still_allowed():
    """extra='allow' preserved — runner can evolve shape without breaking client."""
    from core.shadow_contract import TradeRecord
    record = TradeRecord(
        timestamp="2026-04-18T12:00:00Z",
        symbol="LINKUSDT",
        strategy="CITADEL",
        direction="BULLISH",
        entry=14.23,
        future_unknown_field="new_stuff",
    )
    dumped = record.model_dump()
    assert dumped["future_unknown_field"] == "new_stuff"


def test_trade_record_result_literal_validates():
    """result accepts only 'WIN' | 'LOSS' | None."""
    import pytest
    from pydantic import ValidationError
    from core.shadow_contract import TradeRecord
    with pytest.raises(ValidationError):
        TradeRecord(
            timestamp="2026-04-18T12:00:00Z",
            symbol="BTC", strategy="X", direction="L",
            result="PARTIAL",
        )
