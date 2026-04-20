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
    root = tk.Tk()
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
