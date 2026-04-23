"""Unit tests for Screen ABC lifecycle."""
from __future__ import annotations

import pytest
import tkinter as tk

from launcher_support.screens.base import Screen


class _FakeScreen(Screen):
    def __init__(self, parent):
        super().__init__(parent)
        self.build_count = 0
        self.enter_calls: list[dict] = []
        self.exit_count = 0

    def build(self) -> None:
        self.build_count += 1
        self._label = tk.Label(self.container, text="fake")
        self._label.pack()

    def on_enter(self, **kwargs) -> None:
        self.enter_calls.append(kwargs)

    def on_exit(self) -> None:
        self.exit_count += 1


@pytest.fixture(scope="module")
def tk_root():
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


def test_screen_creates_container_frame(tk_root):
    s = _FakeScreen(parent=tk_root)
    assert s.container is not None
    assert isinstance(s.container, tk.Frame)
    assert str(s.container.master) == str(tk_root)


def test_screen_build_is_invoked_once(tk_root):
    s = _FakeScreen(parent=tk_root)
    s.mount()
    assert s.build_count == 1
    # mount() a second time is a no-op (container already built)
    s.mount()
    assert s.build_count == 1


def test_screen_pack_and_unpack(tk_root):
    s = _FakeScreen(parent=tk_root)
    s.mount()
    s.pack()
    tk_root.update_idletasks()
    assert s.container.winfo_manager() == "pack"
    s.pack_forget()
    tk_root.update_idletasks()
    assert s.container.winfo_manager() == ""


def test_on_enter_receives_kwargs(tk_root):
    s = _FakeScreen(parent=tk_root)
    s.mount()
    s.on_enter(run_id="abc", mode="paper")
    assert s.enter_calls == [{"run_id": "abc", "mode": "paper"}]


def test_on_exit_invoked(tk_root):
    s = _FakeScreen(parent=tk_root)
    s.mount()
    s.on_enter()
    s.on_exit()
    assert s.exit_count == 1


def test_abstract_build_raises_if_not_overridden(tk_root):
    class _Incomplete(Screen):
        pass

    with pytest.raises(TypeError):
        _Incomplete(parent=tk_root)


class _TimerScreen(Screen):
    def __init__(self, parent):
        super().__init__(parent)
        self.tick_count = 0
        self.click_count = 0

    def build(self) -> None:
        self._btn = tk.Button(self.container, text="go")
        self._btn.pack()

    def on_enter(self, **kwargs) -> None:
        self._after(10, self._tick)
        self._bind(self._btn, "<Button-1>", self._click)

    def _tick(self) -> None:
        self.tick_count += 1

    def _click(self, _event) -> None:
        self.click_count += 1


def test_after_timer_cancelled_on_exit(tk_root):
    s = _TimerScreen(parent=tk_root)
    s.mount()
    s.on_enter()
    # Before on_exit, the timer is armed
    assert len(s._tracked_after_ids) == 1
    s.on_exit()
    # After on_exit, timer list cleared
    assert s._tracked_after_ids == []
    # Sleep past the scheduled firing — tick must NOT have fired
    tk_root.after(30, lambda: None)
    tk_root.update()
    tk_root.after(30, lambda: None)
    tk_root.update()
    assert s.tick_count == 0


def test_binding_cleared_on_exit(tk_root):
    s = _TimerScreen(parent=tk_root)
    s.mount()
    s.on_enter()
    # Before on_exit, binding tracked
    assert len(s._tracked_bindings) == 1
    s.on_exit()
    assert s._tracked_bindings == []


def test_auto_cleanup_is_idempotent(tk_root):
    s = _TimerScreen(parent=tk_root)
    s.mount()
    s.on_enter()
    s.on_exit()
    s.on_exit()  # second call is safe no-op
    assert s.tick_count == 0


def test_after_auto_prunes_fired_ids(tk_root):
    """_tracked_after_ids nao cresce alem do num de timers *ativos*."""
    import time as _time

    s = _TimerScreen(parent=tk_root)
    s.mount()
    # Agenda 5 timers curtos (todos vao firar logo)
    for _ in range(5):
        s._after(5, s._tick)
    assert len(s._tracked_after_ids) == 5
    # Espera todos firarem (pool de update() + sleep real — update()
    # sozinho nao processa eventos sem tempo wall-clock passar)
    deadline = _time.time() + 1.0
    while s.tick_count < 5 and _time.time() < deadline:
        tk_root.update()
        _time.sleep(0.01)
    assert s.tick_count == 5
    # Apos firar, lista foi podada — nao cresceu sem limite
    assert s._tracked_after_ids == []
