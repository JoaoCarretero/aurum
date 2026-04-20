"""Integration: Tk-real switching between 3 fake screens.

Marker `@pytest.mark.gui` — runs by default in local/normal CI.
Skip with `-m "not gui"` in a truly headless env that lacks tk.
"""
from __future__ import annotations

import tkinter as tk

import pytest

from core.ops.health import runtime_health
from launcher_support.screens.base import Screen
from launcher_support.screens.manager import ScreenManager


class _Counter(Screen):
    def __init__(self, parent):
        super().__init__(parent)
        self.enter_count = 0
        self.exit_count = 0
        self.tick_count = 0

    def build(self):
        self._lbl = tk.Label(self.container, text=f"counter {id(self) % 1000}")
        self._lbl.pack()

    def on_enter(self, **kwargs):
        self.enter_count += 1
        self._after(10, self._tick)

    def on_exit(self):
        super().on_exit()
        self.exit_count += 1

    def _tick(self):
        self.tick_count += 1


@pytest.fixture(scope="module")
def gui_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("tk unavailable")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.mark.gui
def test_3_screen_rotation_caches_and_cleans_up(gui_root):
    runtime_health.counters.clear()
    container = tk.Frame(gui_root)
    container.pack()
    mgr = ScreenManager(parent=container)
    mgr.register("a", _Counter)
    mgr.register("b", _Counter)
    mgr.register("c", _Counter)

    a = mgr.show("a")
    b = mgr.show("b")
    c = mgr.show("c")
    a_again = mgr.show("a")

    # Cache reused
    assert a is a_again
    # Counts: a entered 2x, exited 1x; b entered 1x, exited 1x; c entered 1x, exited 1x
    assert a.enter_count == 2
    assert a.exit_count == 1
    assert b.enter_count == 1
    assert b.exit_count == 1
    assert c.enter_count == 1
    assert c.exit_count == 1

    # Metrics
    snap = runtime_health.snapshot()
    assert snap.get("screen.a.first_visit") == 1
    assert snap.get("screen.a.reentry") == 1
    assert snap.get("screen.b.first_visit") == 1
    assert snap.get("screen.c.first_visit") == 1


@pytest.mark.gui
def test_after_timer_does_not_fire_on_hidden_screen(gui_root):
    container = tk.Frame(gui_root)
    container.pack()
    mgr = ScreenManager(parent=container)
    mgr.register("a", _Counter)
    mgr.register("b", _Counter)

    a = mgr.show("a")
    # Timer was armed; switch before it fires
    mgr.show("b")
    # Pump events a few times well past the 10ms threshold
    for _ in range(10):
        gui_root.after(5, lambda: None)
        gui_root.update()
    assert a.tick_count == 0, "a's _after timer leaked past on_exit"
