"""Smoke tests for panes/detail_left.py."""
from __future__ import annotations

import tkinter as tk

import pytest


def _inst(run_id: str, mode: str = "paper", status: str = "live") -> dict:
    return {
        "run_id": run_id,
        "mode": mode,
        "label": "default",
        "status": status,
        "uptime_s": 900,
        "ticks": 17,
        "novel": 0,
        "equity": 10123.45,
    }


def _kpis() -> dict:
    return {
        "total_equity": 20000.0,
        "total_ticks": 100,
        "total_novel": 3,
        "instance_count": 2,
    }


@pytest.fixture
def root():
    try:
        r = tk.Tk()
        r.withdraw()
    except tk.TclError:
        pytest.skip("no display")
    yield r
    r.destroy()


def test_header_shows_engine_display_name(root):
    from launcher_support.engines_live.panes.detail_left import build_detail_left

    frame = build_detail_left(
        root,
        engine="citadel",
        engine_display="CITADEL",
        instances=[_inst("rid-1")],
        kpis=_kpis(),
        selected_instance=None,
    )
    frame.pack()
    root.update()

    def _iter(w):
        yield w
        for c in w.winfo_children():
            yield from _iter(c)

    texts = " ".join(str(w.cget("text")) for w in _iter(frame) if isinstance(w, tk.Label))
    assert "CITADEL" in texts


def test_instance_row_has_mode_label_and_status(root):
    from launcher_support.engines_live.panes.detail_left import build_detail_left

    frame = build_detail_left(
        root,
        engine="citadel", engine_display="CITADEL",
        instances=[_inst("rid-1", mode="paper", status="live")],
        kpis=_kpis(),
        selected_instance=None,
    )
    frame.pack()
    root.update()

    def _iter(w):
        yield w
        for c in w.winfo_children():
            yield from _iter(c)

    texts = " ".join(str(w.cget("text")) for w in _iter(frame) if isinstance(w, tk.Label))
    assert "default" in texts  # label
    assert "●" in texts  # status glyph (live)


def test_selected_instance_row_has_highlight(root):
    from launcher_support.engines_live.panes.detail_left import build_detail_left
    from core.ui.ui_palette import BG2

    frame = build_detail_left(
        root,
        engine="citadel", engine_display="CITADEL",
        instances=[_inst("rid-1"), _inst("rid-2")],
        kpis=_kpis(),
        selected_instance="rid-2",
    )
    frame.pack()
    root.update()

    rid2_frame = frame._instance_rows.get("rid-2")
    assert rid2_frame is not None
    # Row background should be BG2 (highlighted)
    assert str(rid2_frame.cget("bg")).lower() == BG2.lower()


def test_kpis_show_total_equity(root):
    from launcher_support.engines_live.panes.detail_left import build_detail_left

    frame = build_detail_left(
        root,
        engine="citadel", engine_display="CITADEL",
        instances=[_inst("rid-1")],
        kpis={"total_equity": 50000.0, "total_ticks": 100, "total_novel": 5, "instance_count": 1},
        selected_instance=None,
    )
    frame.pack()
    root.update()

    def _iter(w):
        yield w
        for c in w.winfo_children():
            yield from _iter(c)

    texts = " ".join(str(w.cget("text")) for w in _iter(frame) if isinstance(w, tk.Label))
    assert "50" in texts  # total_equity value should appear somewhere


def test_update_reflects_new_selection(root):
    from launcher_support.engines_live.panes.detail_left import build_detail_left, update_detail_left
    from core.ui.ui_palette import BG, BG2

    frame = build_detail_left(
        root,
        engine="citadel", engine_display="CITADEL",
        instances=[_inst("rid-1"), _inst("rid-2")],
        kpis=_kpis(),
        selected_instance="rid-1",
    )
    frame.pack()
    root.update()
    assert str(frame._instance_rows["rid-1"].cget("bg")).lower() == BG2.lower()
    assert str(frame._instance_rows["rid-2"].cget("bg")).lower() == BG.lower()

    update_detail_left(
        frame,
        instances=[_inst("rid-1"), _inst("rid-2")],
        kpis=_kpis(),
        selected_instance="rid-2",
    )
    root.update()
    assert str(frame._instance_rows["rid-1"].cget("bg")).lower() == BG.lower()
    assert str(frame._instance_rows["rid-2"].cget("bg")).lower() == BG2.lower()
