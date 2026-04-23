"""Smoke tests for panes/research_shelf.py."""
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


def test_collapsed_shows_comma_separated_names(root):
    from launcher_support.engines_live.panes.research_shelf import build_shelf

    frame = build_shelf(
        root, not_running_engines=["renaissance", "deshaw"], expanded=False,
    )
    frame.pack()
    root.update()

    def _iter(w):
        yield w
        for c in w.winfo_children():
            yield from _iter(c)

    texts = [str(w.cget("text")) for w in _iter(frame) if isinstance(w, tk.Label)]
    joined = " ".join(texts)
    assert "renaissance" in joined
    assert "deshaw" in joined


def test_toggle_label_changes_glyph(root):
    from launcher_support.engines_live.panes.research_shelf import build_shelf, update_shelf

    frame = build_shelf(root, not_running_engines=["a", "b"], expanded=False)
    frame.pack()
    root.update()
    assert "▸" in str(frame._toggle_label.cget("text"))

    update_shelf(frame, ["a", "b"], expanded=True)
    root.update()
    assert "▾" in str(frame._toggle_label.cget("text"))


def test_toggle_click_fires_callback(root):
    from launcher_support.engines_live.panes.research_shelf import build_shelf

    calls: list = []
    frame = build_shelf(
        root, not_running_engines=["a"], expanded=False, on_toggle=lambda: calls.append(1),
    )
    frame.pack()
    root.deiconify()
    root.update()
    frame._toggle_label.event_generate("<Button-1>", x=2, y=2)
    root.update()
    assert calls == [1]


def test_expanded_renders_minimal_cards(root):
    from launcher_support.engines_live.panes.research_shelf import build_shelf

    frame = build_shelf(
        root, not_running_engines=["renaissance", "deshaw"], expanded=True,
    )
    frame.pack()
    root.update()

    # Body should contain some Frame children (the minimal cards)
    body = frame._body
    assert body is not None
    children = list(body.winfo_children())
    assert len(children) >= 2


def test_title_label_updates_count(root):
    from launcher_support.engines_live.panes.research_shelf import build_shelf, update_shelf

    frame = build_shelf(root, not_running_engines=["a"], expanded=False)
    frame.pack()
    root.update()
    assert "1 engines" in str(frame._title_label.cget("text"))

    update_shelf(frame, ["a", "b", "c"], expanded=False)
    root.update()
    assert "3 engines" in str(frame._title_label.cget("text"))
