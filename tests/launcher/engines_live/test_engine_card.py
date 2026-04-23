"""Smoke tests for engine_card widget."""
from __future__ import annotations

import tkinter as tk

import pytest

from launcher_support.engines_live.data.aggregate import EngineCard


def _healthy_card():
    return EngineCard(
        engine="citadel", display="CITADEL", instance_count=2,
        live_count=2, stale_count=0, error_count=0,
        mode_summary="p+s", max_uptime_s=900, total_equity=10000.0,
        total_novel=0, total_ticks=34, sort_weight=10, has_error=False,
    )


@pytest.fixture
def root():
    try:
        r = tk.Tk()
        r.withdraw()
    except tk.TclError:
        pytest.skip("no display")
    yield r
    r.destroy()


def test_build_card_has_display_name(root):
    from launcher_support.engines_live.widgets.engine_card import build_card

    card = _healthy_card()
    frame = build_card(root, card, selected=False)
    frame.pack()
    root.update()

    # Find any Label with text containing "CITADEL"
    found = any(
        isinstance(w, tk.Label) and "CITADEL" in str(w.cget("text"))
        for w in frame.winfo_children()
    )
    assert found


def test_selected_card_has_amber_border(root):
    from launcher_support.engines_live.widgets.engine_card import build_card
    from core.ui.ui_palette import AMBER_B

    card = _healthy_card()
    frame = build_card(root, card, selected=True)
    frame.pack()
    root.update()

    assert str(frame.cget("highlightbackground")).lower() in (AMBER_B.lower(), "#" + AMBER_B.lstrip("#").lower())


def test_error_card_has_red_border(root):
    from launcher_support.engines_live.widgets.engine_card import build_card
    from core.ui.ui_palette import RED

    card = EngineCard(
        engine="citadel", display="CITADEL", instance_count=1,
        live_count=0, stale_count=0, error_count=1,
        mode_summary="p", max_uptime_s=900, total_equity=10000.0,
        total_novel=0, total_ticks=17, sort_weight=10, has_error=True,
    )
    frame = build_card(root, card, selected=False)
    frame.pack()
    root.update()

    assert str(frame.cget("highlightbackground")).lower() in (RED.lower(), "#" + RED.lstrip("#").lower())


def test_update_card_replaces_contents(root):
    from launcher_support.engines_live.widgets.engine_card import build_card, update_card

    card1 = _healthy_card()
    frame = build_card(root, card1, selected=False)
    frame.pack()

    card2 = EngineCard(
        engine="citadel", display="CITADEL", instance_count=3,
        live_count=3, stale_count=0, error_count=0,
        mode_summary="p+s+l", max_uptime_s=7200, total_equity=20000.0,
        total_novel=2, total_ticks=100, sort_weight=10, has_error=False,
    )
    update_card(frame, card2, selected=True)
    root.update()
    # No assertion on visual — this test ensures update_card doesn't crash
    # and the frame is still usable.
    assert frame.winfo_exists()
