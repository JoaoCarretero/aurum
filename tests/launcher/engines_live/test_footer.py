"""Smoke tests for panes/footer.py."""
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


def test_footer_strip_hints(root):
    from launcher_support.engines_live.panes.footer import build_footer

    s = StateSnapshot(focus_pane="strip")
    frame = build_footer(root, s)
    frame.pack()
    root.update()

    assert "Enter" in str(frame._label.cget("text"))
    assert "mode" in str(frame._label.cget("text"))


def test_footer_detail_log_hints(root):
    from launcher_support.engines_live.panes.footer import build_footer

    s = StateSnapshot(focus_pane="detail_log", selected_engine="citadel")
    frame = build_footer(root, s)
    frame.pack()
    root.update()
    assert "follow" in str(frame._label.cget("text")).lower()


def test_footer_update_switches_hints(root):
    from launcher_support.engines_live.panes.footer import build_footer, update_footer

    s_strip = StateSnapshot(focus_pane="strip")
    frame = build_footer(root, s_strip)
    frame.pack()
    root.update()
    first = str(frame._label.cget("text"))

    s_log = StateSnapshot(focus_pane="detail_log", selected_engine="citadel")
    update_footer(frame, s_log)
    root.update()
    second = str(frame._label.cget("text"))
    assert first != second
    assert "follow" in second.lower()
