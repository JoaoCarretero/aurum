"""Tests for screen metrics emission (logs + counters)."""
from __future__ import annotations

import logging

import pytest

from core.ops.health import runtime_health
from launcher_support.screens._metrics import clear_timings, emit_switch_metric, emit_timing_metric, snapshot_timings


@pytest.fixture(autouse=True)
def _reset_counters():
    runtime_health.counters.clear()
    clear_timings()
    yield
    runtime_health.counters.clear()
    clear_timings()


def test_emit_records_counter_first_visit():
    emit_switch_metric("splash", "first_visit", ms=42.0)
    assert runtime_health.snapshot().get("screen.splash.first_visit") == 1


def test_emit_records_counter_reentry():
    emit_switch_metric("splash", "reentry", ms=5.0)
    emit_switch_metric("splash", "reentry", ms=6.0)
    assert runtime_health.snapshot().get("screen.splash.reentry") == 2


def test_emit_logs_ms(caplog):
    caplog.set_level(logging.INFO, logger="aurum.launcher.screens")
    emit_switch_metric("menu", "first_visit", ms=123.4)
    records = [r for r in caplog.records if r.name == "aurum.launcher.screens"]
    assert len(records) == 1
    assert "menu" in records[0].getMessage()
    assert "first_visit" in records[0].getMessage()
    assert "123.4" in records[0].getMessage()


def test_emit_validates_phase():
    with pytest.raises(ValueError, match="phase"):
        emit_switch_metric("x", "bogus", ms=1.0)


def test_emit_timing_records_latest_value():
    emit_timing_metric("boot.chrome", ms=12.5)
    emit_timing_metric("boot.chrome", ms=8.0)
    assert runtime_health.snapshot().get("timing.boot.chrome.samples") == 2
    assert snapshot_timings()["boot.chrome"] == 8.0
