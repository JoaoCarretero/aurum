"""Smoke tests for pill_segment widget."""
from __future__ import annotations

import tkinter as tk

import pytest


@pytest.fixture
def root():
    try:
        r = tk.Tk()
        r.withdraw()
    except tk.TclError:
        pytest.skip("no display")
    yield r
    r.destroy()


def test_pill_segment_builds(root):
    from launcher_support.engines_live.widgets.pill_segment import PillSegment

    ps = PillSegment(root, options=["PAPER", "DEMO", "TESTNET", "LIVE"], active="PAPER")
    ps.pack()
    assert ps.active == "PAPER"


def test_set_active_updates(root):
    from launcher_support.engines_live.widgets.pill_segment import PillSegment

    ps = PillSegment(root, options=["PAPER", "DEMO", "TESTNET", "LIVE"], active="PAPER")
    ps.pack()
    ps.set_active("LIVE")
    assert ps.active == "LIVE"


def test_click_fires_on_change(root):
    from launcher_support.engines_live.widgets.pill_segment import PillSegment

    changed: list = []
    ps = PillSegment(root, options=["A", "B"], active="A", on_change=changed.append)
    ps.pack()
    ps.set_active("B")  # simulate click via public API
    assert changed == ["B"]
