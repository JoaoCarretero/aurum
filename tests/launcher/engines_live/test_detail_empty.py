"""Smoke tests for panes/detail_empty.py."""
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


def test_renders_engine_live_count(root):
    from launcher_support.engines_live.panes.detail_empty import build_detail_empty

    frame = build_detail_empty(root, {"engines_live": 4, "total_ticks_24h": 100, "total_equity_paper": 50000.0})
    frame.pack()
    root.update()

    def _iter(w):
        yield w
        for c in w.winfo_children():
            yield from _iter(c)

    texts = " ".join(str(w.cget("text")) for w in _iter(frame) if isinstance(w, tk.Label))
    assert "4 engines live" in texts


def test_shows_select_hint(root):
    from launcher_support.engines_live.panes.detail_empty import build_detail_empty

    frame = build_detail_empty(root, {})
    frame.pack()
    root.update()

    def _iter(w):
        yield w
        for c in w.winfo_children():
            yield from _iter(c)

    texts = " ".join(str(w.cget("text")) for w in _iter(frame) if isinstance(w, tk.Label))
    assert "Select an engine" in texts


def test_update_reflects_new_stats(root):
    from launcher_support.engines_live.panes.detail_empty import build_detail_empty, update_detail_empty

    frame = build_detail_empty(root, {"engines_live": 1})
    frame.pack()
    root.update()

    update_detail_empty(frame, {"engines_live": 9, "total_ticks_24h": 555, "total_equity_paper": 123456.0})
    root.update()

    def _iter(w):
        yield w
        for c in w.winfo_children():
            yield from _iter(c)

    texts = " ".join(str(w.cget("text")) for w in _iter(frame) if isinstance(w, tk.Label))
    assert "9 engines live" in texts
    assert "555" in texts
