"""Tests for persistent screen-metrics logging + snapshot dump."""
from __future__ import annotations

import json
import logging

import pytest

from core.ops.health import runtime_health
from launcher_support.screens._metrics import emit_switch_metric
from launcher_support.screens._persistence import (
    configure_screen_logging,
    dump_screen_metrics,
)

_LOGGER = "aurum.launcher.screens"
_TAG = "aurum.screen_file"


def _strip_tagged_handlers() -> None:
    logger = logging.getLogger(_LOGGER)
    for handler in list(logger.handlers):
        if getattr(handler, "_aurum_tag", None) == _TAG:
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass


@pytest.fixture(autouse=True)
def _isolation():
    runtime_health.counters.clear()
    _strip_tagged_handlers()
    yield
    runtime_health.counters.clear()
    _strip_tagged_handlers()


def test_configure_attaches_handler_once(tmp_path):
    first = configure_screen_logging(tmp_path)
    second = configure_screen_logging(tmp_path)
    assert first == second == tmp_path / "screens.log"
    tagged = [
        h for h in logging.getLogger(_LOGGER).handlers
        if getattr(h, "_aurum_tag", None) == _TAG
    ]
    assert len(tagged) == 1


def test_configured_handler_writes_log_line(tmp_path):
    path = configure_screen_logging(tmp_path)
    emit_switch_metric("splash", "first_visit", ms=12.3)
    for handler in logging.getLogger(_LOGGER).handlers:
        try:
            handler.flush()
        except Exception:
            pass
    content = path.read_text(encoding="utf-8")
    assert "splash" in content
    assert "first_visit" in content
    assert "12.3" in content


def test_dump_writes_filtered_snapshot(tmp_path):
    emit_switch_metric("splash", "first_visit", ms=1.0)
    emit_switch_metric("menu", "reentry", ms=2.0)
    runtime_health.record("unrelated.counter")
    path = dump_screen_metrics(tmp_path, reason="test")
    assert path is not None
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "screen_metrics.v1"
    assert data["reason"] == "test"
    counters = data["counters"]
    assert counters.get("screen.splash.first_visit") == 1
    assert counters.get("screen.menu.reentry") == 1
    assert "unrelated.counter" not in counters


def test_dump_returns_none_when_no_screen_counters(tmp_path):
    runtime_health.record("unrelated.counter")
    assert dump_screen_metrics(tmp_path) is None
