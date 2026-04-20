"""Unit tests for ScreenManager — cache miss path first."""
from __future__ import annotations

import pytest
import tkinter as tk

from launcher_support.screens.base import Screen
from launcher_support.screens.manager import ScreenManager


class _Recording(Screen):
    def __init__(self, parent):
        super().__init__(parent)
        self.events: list[tuple[str, dict]] = []

    def build(self) -> None:
        self.events.append(("build", {}))

    def on_enter(self, **kwargs) -> None:
        self.events.append(("enter", dict(kwargs)))

    def on_exit(self) -> None:
        super().on_exit()
        self.events.append(("exit", {}))


@pytest.fixture
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def test_register_screen_factory(tk_root):
    mgr = ScreenManager(parent=tk_root)
    mgr.register("foo", _Recording)
    assert "foo" in mgr.registered_names()


def test_first_show_instantiates_builds_enters_and_packs(tk_root):
    mgr = ScreenManager(parent=tk_root)
    mgr.register("foo", _Recording)

    screen = mgr.show("foo", x=1)

    assert isinstance(screen, _Recording)
    assert [e[0] for e in screen.events] == ["build", "enter"]
    assert screen.events[1][1] == {"x": 1}
    tk_root.update_idletasks()
    assert screen.container.winfo_manager() == "pack"
    assert mgr.current_name() == "foo"


def test_unknown_screen_raises(tk_root):
    mgr = ScreenManager(parent=tk_root)
    with pytest.raises(ValueError, match="unknown screen"):
        mgr.show("nonexistent")
