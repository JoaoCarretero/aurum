"""Smoke tests for panes/header.py."""
from __future__ import annotations

import tkinter as tk

import pytest

from launcher_support.engines_live.state import StateSnapshot


@pytest.fixture
def root():
    try:
        r = tk.Tk()
        r.withdraw()
    except tk.TclError:
        pytest.skip("no display")
    yield r
    r.destroy()


def _iter_widgets(w):
    yield w
    for c in w.winfo_children():
        yield from _iter_widgets(c)


def test_header_has_title_label(root):
    from launcher_support.engines_live.panes.header import build_header

    state = StateSnapshot()
    frame = build_header(root, state)
    frame.pack()
    root.update()

    found = any(
        isinstance(w, tk.Label) and "ENGINES" in str(w.cget("text"))
        for w in _iter_widgets(frame)
    )
    assert found, "expected a title label containing 'ENGINES'"


def test_header_has_mode_pills(root):
    from launcher_support.engines_live.panes.header import build_header
    from launcher_support.engines_live.widgets.pill_segment import PillSegment

    state = StateSnapshot(mode="paper")
    frame = build_header(root, state)
    frame.pack()
    root.update()

    assert hasattr(frame, "_pills"), "header must expose _pills attribute"
    assert isinstance(frame._pills, PillSegment)
    assert frame._pills.active == "PAPER"


def test_header_live_mode_shows_red_border(root):
    from launcher_support.engines_live.panes.header import build_header

    state = StateSnapshot(mode="live")
    frame = build_header(root, state)
    frame.pack()
    root.update()

    assert hasattr(frame, "_live_line"), "header must expose _live_line attribute"
    # winfo_manager() returns "pack" when the widget has been pack()ed,
    # "" after pack_forget(). This is robust whether or not the root is mapped.
    assert frame._live_line.winfo_manager() == "pack", "live mode must pack the red border"


def test_update_header_switches_mode_pill(root):
    from launcher_support.engines_live.panes.header import build_header, update_header

    state_paper = StateSnapshot(mode="paper")
    frame = build_header(root, state_paper)
    frame.pack()
    root.update()
    assert frame._pills.active == "PAPER"
    assert frame._live_line.winfo_manager() == ""

    state_live = StateSnapshot(mode="live")
    update_header(frame, state_live)
    root.update()
    assert frame._pills.active == "LIVE"
    assert frame._live_line.winfo_manager() == "pack"

    state_back = StateSnapshot(mode="paper")
    update_header(frame, state_back)
    root.update()
    assert frame._pills.active == "PAPER"
    assert frame._live_line.winfo_manager() == ""
