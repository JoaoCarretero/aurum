"""Smoke tests for panes/strip_grid.py."""
from __future__ import annotations

import tkinter as tk

import pytest

from launcher_support.engines_live.data.aggregate import EngineCard


def _make_card(engine: str, display: str | None = None) -> EngineCard:
    return EngineCard(
        engine=engine,
        display=(display or engine.upper()),
        instance_count=1,
        live_count=1,
        stale_count=0,
        error_count=0,
        mode_summary="p",
        max_uptime_s=900,
        total_equity=10000.0,
        total_novel=0,
        total_ticks=10,
        sort_weight=10,
        has_error=False,
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


def test_build_strip_grid_places_cards(root):
    from launcher_support.engines_live.panes.strip_grid import build_strip_grid

    cards = [_make_card("citadel"), _make_card("jump"), _make_card("renaissance")]
    frame = build_strip_grid(root, cards, selected_engine=None)
    frame.pack()
    root.update()

    # At least 3 cards + 1 "+ NEW ENGINE" card = 4 Frames
    frames = [c for c in frame.winfo_children() if isinstance(c, tk.Frame)]
    assert len(frames) >= 4


def test_build_strip_grid_with_selection(root):
    from launcher_support.engines_live.panes.strip_grid import build_strip_grid

    cards = [_make_card("citadel"), _make_card("jump")]
    frame = build_strip_grid(root, cards, selected_engine="citadel")
    frame.pack()
    root.update()

    # The stored reference for 'citadel' should have _selected=True on its card frame
    citadel_frame = frame._card_frames.get("citadel")
    assert citadel_frame is not None
    assert getattr(citadel_frame, "_selected", None) is True


def test_click_card_fires_on_select(root):
    from launcher_support.engines_live.panes.strip_grid import build_strip_grid

    clicks: list[str] = []
    cards = [_make_card("citadel")]
    frame = build_strip_grid(
        root, cards, selected_engine=None, on_select=clicks.append
    )
    frame.pack()
    # event_generate('<Button-1>') only dispatches when the widget is viewable,
    # so the root must be deiconified for this test (the fixture withdraws it
    # by default so other tests don't flash a window).
    root.deiconify()
    root.update()

    citadel_frame = frame._card_frames["citadel"]
    citadel_frame.event_generate("<Button-1>", x=5, y=5)
    root.update()
    assert clicks == ["citadel"]


def test_update_strip_grid_adds_new_card(root):
    from launcher_support.engines_live.panes.strip_grid import (
        build_strip_grid,
        update_strip_grid,
    )

    cards_v1 = [_make_card("citadel")]
    frame = build_strip_grid(root, cards_v1, selected_engine=None)
    frame.pack()
    root.update()
    assert "citadel" in frame._card_frames
    assert "jump" not in frame._card_frames

    cards_v2 = [_make_card("citadel"), _make_card("jump")]
    update_strip_grid(frame, cards_v2, selected_engine="jump")
    root.update()
    assert "citadel" in frame._card_frames
    assert "jump" in frame._card_frames
    assert getattr(frame._card_frames["jump"], "_selected", None) is True


def test_calc_cols_returns_3_for_narrow(root):
    from launcher_support.engines_live.panes.strip_grid import _calc_cols
    assert _calc_cols(600) == 3
    assert _calc_cols(900) == 4
    assert _calc_cols(1200) == 5
    assert _calc_cols(1500) == 5
