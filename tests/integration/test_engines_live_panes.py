"""Smoke test that view.render produces a working screen."""
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


def test_render_builds_panes(root, monkeypatch):
    from launcher_support.engines_live import view
    from launcher_support.engines_live.data import procs, cockpit

    monkeypatch.setattr(procs, "list_procs", lambda force=False: [])
    monkeypatch.setattr(cockpit, "runs_cached", lambda: [])

    class FakeLauncher:
        def after(self, ms, fn): pass
        def bind(self, *a, **kw): pass
        def unbind(self, *a, **kw): pass

    frame = tk.Frame(root)
    frame.pack()
    launcher = FakeLauncher()

    handle = view.render(launcher, frame, on_escape=lambda: None)

    assert "frame" in handle
    assert "state" in handle
    assert "destroy" in handle
    root.update()

    handle["destroy"]()
