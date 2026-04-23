"""Smoke tests for widgets/hold_button.py.

These tests require a Tk root. Skip if DISPLAY unavailable.
"""
from __future__ import annotations

import os
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


def test_hold_button_creates_frame(root):
    from launcher_support.engines_live.widgets.hold_button import HoldButton

    calls: list = []
    btn = HoldButton(root, text="STOP", hold_ms=1500, on_complete=lambda: calls.append(1))
    btn.pack()
    assert isinstance(btn, tk.Frame)


def test_hold_button_does_not_fire_before_hold_completes(root):
    from launcher_support.engines_live.widgets.hold_button import HoldButton

    calls: list = []
    btn = HoldButton(root, text="STOP", hold_ms=1500, on_complete=lambda: calls.append(1))
    btn.pack()

    btn.press()
    root.update()
    btn.release()  # released too early
    root.update()

    assert calls == []


def test_hold_button_fires_after_hold_completes(root):
    from launcher_support.engines_live.widgets.hold_button import HoldButton

    calls: list = []
    btn = HoldButton(root, text="STOP", hold_ms=50, on_complete=lambda: calls.append(1))
    btn.pack()

    btn.press()
    # Let hold timer fire
    root.update()
    root.after(100, lambda: None)
    import time
    time.sleep(0.15)
    root.update()

    assert calls == [1]


def test_hold_button_progress_fill_updates_during_hold(root):
    from launcher_support.engines_live.widgets.hold_button import HoldButton

    btn = HoldButton(root, text="STOP", hold_ms=200, on_complete=lambda: None)
    btn.pack()

    assert btn._progress == 0.0

    btn.press()
    import time
    time.sleep(0.1)
    root.update()

    assert 0.0 < btn._progress < 1.0
