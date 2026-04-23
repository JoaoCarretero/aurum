"""Smoke tests for panes/detail_right.py."""
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


def _iter(w):
    yield w
    for c in w.winfo_children():
        yield from _iter(c)


def test_build_renders_log_lines(root):
    from launcher_support.engines_live.panes.detail_right import build_detail_right

    frame = build_detail_right(
        root, run_id="rid-1",
        log_lines=["INFO first line", "SIGNAL trigger", "ERROR oh no"],
        follow_mode=False,
    )
    frame.pack()
    root.update()

    texts = [w for w in _iter(frame) if isinstance(w, tk.Text)]
    assert len(texts) == 1
    t = texts[0]
    content = t.get("1.0", "end-1c")
    assert "first line" in content
    assert "trigger" in content


def test_level_tags_are_configured(root):
    from launcher_support.engines_live.panes.detail_right import build_detail_right
    from core.ui.ui_palette import RED, AMBER

    frame = build_detail_right(
        root, run_id="rid-1",
        log_lines=["SIGNAL test", "ERROR boom"],
        follow_mode=False,
    )
    frame.pack()
    root.update()

    t = next(w for w in _iter(frame) if isinstance(w, tk.Text))
    # Tags registered
    assert "SIGNAL" in t.tag_names()
    assert "ERROR" in t.tag_names()
    # ERROR tag has red fg
    assert str(t.tag_cget("ERROR", "foreground")).lower() in (RED.lower(), "#" + RED.lstrip("#").lower())


def test_follow_mode_status_label(root):
    from launcher_support.engines_live.panes.detail_right import build_detail_right

    frame = build_detail_right(
        root, run_id="rid-1",
        log_lines=[],
        follow_mode=True,
    )
    frame.pack()
    root.update()

    assert hasattr(frame, "_status_label")
    assert "FOLLOWING" in str(frame._status_label.cget("text"))


def test_update_switches_follow_mode(root):
    from launcher_support.engines_live.panes.detail_right import (
        build_detail_right,
        update_detail_right,
    )

    frame = build_detail_right(
        root, run_id="rid-1",
        log_lines=[],
        follow_mode=False,
    )
    frame.pack()
    root.update()
    assert "paused" in str(frame._status_label.cget("text"))

    update_detail_right(frame, run_id="rid-1", log_lines=[], follow_mode=True)
    root.update()
    assert "FOLLOWING" in str(frame._status_label.cget("text"))


def test_no_run_id_shows_placeholder(root):
    from launcher_support.engines_live.panes.detail_right import build_detail_right

    frame = build_detail_right(
        root, run_id=None,
        log_lines=[],
        follow_mode=False,
    )
    frame.pack()
    root.update()

    t = next(w for w in _iter(frame) if isinstance(w, tk.Text))
    content = t.get("1.0", "end-1c")
    assert (
        "no instance" in content.lower()
        or "no run" in content.lower()
        or "select" in content.lower()
    )
