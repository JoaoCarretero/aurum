"""Smoke tests for panes/detail.py orchestrator."""
from __future__ import annotations

import tkinter as tk

import pytest

from launcher_support.engines_live.state import empty_state, select_engine


def _data_with_engine() -> dict:
    return {
        "engine_display": "CITADEL",
        "instances": [],
        "kpis": {"total_equity": 0.0, "total_ticks": 0, "total_novel": 0, "instance_count": 0},
        "log_lines": [],
        "global_stats": {"engines_live": 0, "total_ticks_24h": 0, "total_equity_paper": 0.0},
    }


@pytest.fixture
def root():
    try:
        r = tk.Tk()
        r.withdraw()
    except tk.TclError:
        pytest.skip("no display")
    yield r
    r.destroy()


def test_empty_state_shows_detail_empty(root):
    from launcher_support.engines_live.panes.detail import build_detail

    s = empty_state()
    frame = build_detail(root, s, _data_with_engine())
    frame.pack()
    root.update()

    assert frame._mode == "empty"


def test_selected_engine_shows_left_and_right(root):
    from launcher_support.engines_live.panes.detail import build_detail

    s = select_engine(empty_state(), "citadel")
    frame = build_detail(root, s, _data_with_engine())
    frame.pack()
    root.update()

    assert frame._mode == "detail"
    assert frame._left is not None
    assert frame._right is not None


def test_update_switches_from_empty_to_detail(root):
    from launcher_support.engines_live.panes.detail import build_detail, update_detail

    s_empty = empty_state()
    frame = build_detail(root, s_empty, _data_with_engine())
    frame.pack()
    root.update()
    assert frame._mode == "empty"

    s_sel = select_engine(s_empty, "citadel")
    update_detail(frame, s_sel, _data_with_engine())
    root.update()
    assert frame._mode == "detail"
    assert frame._left is not None
