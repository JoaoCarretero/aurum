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


def test_second_show_same_name_reuses_cached_instance(tk_root):
    mgr = ScreenManager(parent=tk_root)
    mgr.register("foo", _Recording)
    a = mgr.show("foo")
    b = mgr.show("foo", y=2)
    assert a is b
    # build called once; enter called twice (one per show)
    assert [e[0] for e in a.events] == ["build", "enter", "exit", "enter"]
    assert a.events[-1][1] == {"y": 2}


def test_switch_exits_previous_before_enter_next(tk_root):
    mgr = ScreenManager(parent=tk_root)
    mgr.register("foo", _Recording)
    mgr.register("bar", _Recording)

    foo = mgr.show("foo")
    bar = mgr.show("bar", mode="live")

    foo_events = [e[0] for e in foo.events]
    bar_events = [e[0] for e in bar.events]
    assert foo_events == ["build", "enter", "exit"]
    assert bar_events == ["build", "enter"]
    assert mgr.current_name() == "bar"


def test_current_screen_pack_forget_on_switch(tk_root):
    mgr = ScreenManager(parent=tk_root)
    mgr.register("foo", _Recording)
    mgr.register("bar", _Recording)

    foo = mgr.show("foo")
    tk_root.update_idletasks()
    assert foo.container.winfo_manager() == "pack"

    bar = mgr.show("bar")
    tk_root.update_idletasks()
    assert foo.container.winfo_manager() == ""
    assert bar.container.winfo_manager() == "pack"


# ─── Error paths ──────────────────────────────────────────────

from launcher_support.screens.exceptions import (
    ScreenBuildError,
    ScreenContextError,
)


class _BuildFails(Screen):
    def build(self) -> None:
        raise RuntimeError("nope")

    def on_enter(self, **kwargs) -> None:
        pass


class _EnterFails(Screen):
    def build(self) -> None:
        pass

    def on_enter(self, **kwargs) -> None:
        if "run_id" not in kwargs:
            raise ScreenContextError("pic", missing=["run_id"])


def test_build_failure_raises_screen_build_error(tk_root):
    mgr = ScreenManager(parent=tk_root)
    mgr.register("bad", _BuildFails)
    with pytest.raises(ScreenBuildError) as excinfo:
        mgr.show("bad")
    assert excinfo.value.screen_name == "bad"
    assert isinstance(excinfo.value.original, RuntimeError)


def test_build_failure_keeps_previous_current(tk_root):
    mgr = ScreenManager(parent=tk_root)
    mgr.register("foo", _Recording)
    mgr.register("bad", _BuildFails)
    mgr.show("foo")
    with pytest.raises(ScreenBuildError):
        mgr.show("bad")
    # Previous screen is still logically current
    assert mgr.current_name() == "foo"


def test_on_enter_context_error_propagates_and_keeps_current(tk_root):
    mgr = ScreenManager(parent=tk_root)
    mgr.register("foo", _Recording)
    mgr.register("pic", _EnterFails)
    mgr.show("foo")
    with pytest.raises(ScreenContextError):
        mgr.show("pic")  # missing run_id
    assert mgr.current_name() == "foo"


def test_on_enter_arbitrary_error_propagates_and_keeps_current(tk_root):
    class _Boom(Screen):
        def build(self):
            pass

        def on_enter(self, **kwargs):
            raise RuntimeError("boom")

    mgr = ScreenManager(parent=tk_root)
    mgr.register("foo", _Recording)
    mgr.register("boom", _Boom)
    mgr.show("foo")
    with pytest.raises(RuntimeError):
        mgr.show("boom")
    assert mgr.current_name() == "foo"
