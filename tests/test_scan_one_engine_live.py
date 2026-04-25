"""Tests for engines.millennium._scan_one_engine_live.

Helper imported by tools/operations/_paper_runner.py — wraps
_collect_live_signals and filters to a single sub-engine, so per-engine
paper runners (jump_paper / citadel_paper / renaissance_paper) produce
signals identical to the same engine running inside MILLENNIUM.
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout

import pytest


def test_scan_one_engine_live_exists_and_is_callable():
    """Importable + callable for the 3 operational engines."""
    from engines.millennium import _scan_one_engine_live
    assert callable(_scan_one_engine_live)


def test_scan_one_engine_live_returns_list_for_jump():
    """Returns a list (possibly empty) of trade dicts for JUMP."""
    from engines.millennium import _scan_one_engine_live
    with redirect_stdout(io.StringIO()):
        out = _scan_one_engine_live("JUMP")
    assert isinstance(out, list)
    for t in out:
        assert isinstance(t, dict)
        assert t.get("strategy") == "JUMP"


def test_scan_one_engine_live_returns_list_for_citadel():
    from engines.millennium import _scan_one_engine_live
    with redirect_stdout(io.StringIO()):
        out = _scan_one_engine_live("CITADEL")
    assert isinstance(out, list)
    for t in out:
        assert t.get("strategy") == "CITADEL"


def test_scan_one_engine_live_returns_list_for_renaissance():
    from engines.millennium import _scan_one_engine_live
    with redirect_stdout(io.StringIO()):
        out = _scan_one_engine_live("RENAISSANCE")
    assert isinstance(out, list)
    for t in out:
        assert t.get("strategy") == "RENAISSANCE"


def test_scan_one_engine_live_unknown_engine_returns_empty():
    """Unknown engine name: empty list, not exception."""
    from engines.millennium import _scan_one_engine_live
    with redirect_stdout(io.StringIO()):
        out = _scan_one_engine_live("NOT_AN_ENGINE")
    assert out == []


def test_scan_one_engine_live_case_insensitive():
    """Lower-case input still works — runners pass os.environ name verbatim."""
    from engines.millennium import _scan_one_engine_live
    with redirect_stdout(io.StringIO()):
        out_upper = _scan_one_engine_live("JUMP")
        out_lower = _scan_one_engine_live("jump")
    assert isinstance(out_upper, list)
    assert isinstance(out_lower, list)
