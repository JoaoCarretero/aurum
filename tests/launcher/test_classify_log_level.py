"""Pin-down classifier behavior — ported from the shelved engines_live/ rebuild.

The classifier drives log tail coloring in `_render_log_panel`. Priority
order matters: ERROR > WARN > EXIT > FILL > ORDER > SIGNAL > INFO.
"""
from __future__ import annotations

import pytest

from launcher_support.engines_live_view import _classify_log_level


@pytest.mark.parametrize("line, expected", [
    # ERROR wins over everything
    ("ERROR: bad state", "ERROR"),
    ("FATAL thing", "ERROR"),
    ("CRITICAL boom", "ERROR"),
    ("Traceback (most recent call last):", "ERROR"),
    # WARN (case-insensitive on keywords)
    ("WARNING: stale", "WARN"),
    ("warn thing", "WARN"),
    ("STALE heartbeat", "WARN"),
    ("SKIP signal", "WARN"),
    # EXIT / FILL / ORDER / SIGNAL
    ("EXIT BNBUSDT +2.3R", "EXIT"),
    ("FILL BNBUSDT 0.05", "FILL"),
    ("ORDER submitted BNBUSDT", "ORDER"),
    ("SIGNAL BNBUSDT LONG", "SIGNAL"),
    ("novel=3 candidates", "SIGNAL"),
    # novel=0 is NOT signal
    ("novel=0 no candidates", "INFO"),
    # Default
    ("tick 42 ok", "INFO"),
    ("", "INFO"),
])
def test_classify(line: str, expected: str) -> None:
    assert _classify_log_level(line) == expected


def test_error_beats_warn() -> None:
    # ERROR keyword + WARN keyword on the same line → ERROR wins
    assert _classify_log_level("ERROR: STALE run") == "ERROR"


def test_warn_beats_signal() -> None:
    assert _classify_log_level("SKIP SIGNAL novel=2") == "WARN"
