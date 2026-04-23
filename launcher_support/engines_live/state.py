"""Immutable StateSnapshot + pure reducers.

All UI state lives here. No tkinter. No mutation — reducers return new
snapshots. view.py holds the current snapshot and swaps it atomically.

Focus panes:
- strip              focus on strip grid (arrow keys navigate engines)
- detail_instances   focus on detail left column (arrow keys navigate instances)
- detail_log         focus on detail right column (F toggles follow)
- shelf              focus on research shelf (arrow keys navigate items)
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

Mode = Literal["paper", "shadow", "demo", "testnet", "live"]
FocusPane = Literal["strip", "detail_instances", "detail_log", "shelf"]

_MODE_CYCLE: tuple[Mode, ...] = ("paper", "shadow", "demo", "testnet", "live")
_TAB_CYCLE: dict[FocusPane, FocusPane] = {
    "strip": "detail_instances",
    "detail_instances": "detail_log",
    "detail_log": "strip",
    "shelf": "strip",  # shelf is entered via toggle_shelf(); tab escapes back to strip
}


@dataclass(frozen=True)
class StateSnapshot:
    selected_engine: str | None = None
    selected_instance: str | None = None
    focus_pane: FocusPane = "strip"
    mode: Mode = "paper"
    follow_tail: bool = False
    shelf_expanded: bool = False


def empty_state() -> StateSnapshot:
    return StateSnapshot()


def select_engine(state: StateSnapshot, engine: str) -> StateSnapshot:
    return replace(
        state,
        selected_engine=engine,
        selected_instance=None,
        focus_pane="detail_instances",
    )


def select_instance(state: StateSnapshot, instance_id: str) -> StateSnapshot:
    return replace(state, selected_instance=instance_id)


def cycle_mode_state(state: StateSnapshot) -> StateSnapshot:
    idx = _MODE_CYCLE.index(state.mode)
    return replace(state, mode=_MODE_CYCLE[(idx + 1) % len(_MODE_CYCLE)])


def toggle_shelf(state: StateSnapshot) -> StateSnapshot:
    return replace(state, shelf_expanded=not state.shelf_expanded)


def toggle_follow(state: StateSnapshot) -> StateSnapshot:
    return replace(state, follow_tail=not state.follow_tail)


def tab_focus(state: StateSnapshot) -> StateSnapshot:
    return replace(state, focus_pane=_TAB_CYCLE[state.focus_pane])


def reset_selection(state: StateSnapshot) -> StateSnapshot:
    return replace(
        state,
        selected_engine=None,
        selected_instance=None,
        focus_pane="strip",
        follow_tail=False,
    )
