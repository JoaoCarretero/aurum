"""Detail pane orchestrator.

If ``state.selected_engine`` is None, renders ``detail_empty`` over the whole
frame. Otherwise renders a horizontal split (40/60) of ``detail_left`` +
``detail_right``.

``update_detail`` diffs the "mode" (empty vs detail):
- On mode flip, destroy all children and rebuild from scratch.
- Same mode — delegate to the child's update function.

The ``data`` dict is the single input bundle. Expected keys:
- ``engine_display`` (str)             — for detail_left header
- ``instances`` (list[dict])           — for detail_left
- ``kpis`` (dict)                      — for detail_left
- ``log_lines`` (list[str])            — for detail_right
- ``global_stats`` (dict)              — for detail_empty
- optional callback keys: ``on_instance_select``, ``on_stop_instance``,
  ``on_restart_instance``, ``on_stop_all``, ``on_new_instance``,
  ``on_open_config``, ``on_toggle_follow``, ``on_open_full``,
  ``on_telegram_test``.
"""
from __future__ import annotations

import tkinter as tk

from core.ui.ui_palette import BG
from launcher_support.engines_live.panes.detail_empty import (
    build_detail_empty,
    update_detail_empty,
)
from launcher_support.engines_live.panes.detail_left import (
    build_detail_left,
    update_detail_left,
)
from launcher_support.engines_live.panes.detail_right import (
    build_detail_right,
    update_detail_right,
)
from launcher_support.engines_live.state import StateSnapshot


def _build_detail_split(
    parent: tk.Widget,
    state: StateSnapshot,
    data: dict,
) -> tuple[tk.PanedWindow, tk.Frame, tk.Frame]:
    container = tk.PanedWindow(
        parent, orient="horizontal", bg=BG, sashwidth=2, sashrelief="flat",
    )
    container.pack(fill="both", expand=True)

    left = build_detail_left(
        container,
        engine=state.selected_engine or "",
        engine_display=data.get("engine_display", ""),
        instances=data.get("instances", []),
        kpis=data.get("kpis", {}),
        selected_instance=state.selected_instance,
        on_instance_select=data.get("on_instance_select"),
        on_stop_instance=data.get("on_stop_instance"),
        on_restart_instance=data.get("on_restart_instance"),
        on_stop_all=data.get("on_stop_all"),
        on_new_instance=data.get("on_new_instance"),
        on_open_config=data.get("on_open_config"),
    )
    right = build_detail_right(
        container,
        run_id=state.selected_instance,
        log_lines=data.get("log_lines", []),
        follow_mode=state.follow_tail,
        on_toggle_follow=data.get("on_toggle_follow"),
        on_open_full=data.get("on_open_full"),
        on_telegram_test=data.get("on_telegram_test"),
    )
    container.add(left, minsize=260, stretch="always")
    container.add(right, minsize=320, stretch="always")
    return container, left, right


def _mark_empty(frame: tk.Frame, empty_child: tk.Frame) -> None:
    frame._mode = "empty"  # type: ignore[attr-defined]
    frame._empty = empty_child  # type: ignore[attr-defined]
    frame._split = None  # type: ignore[attr-defined]
    frame._left = None  # type: ignore[attr-defined]
    frame._right = None  # type: ignore[attr-defined]


def _mark_detail(
    frame: tk.Frame,
    container: tk.PanedWindow,
    left: tk.Frame,
    right: tk.Frame,
) -> None:
    frame._mode = "detail"  # type: ignore[attr-defined]
    frame._empty = None  # type: ignore[attr-defined]
    frame._split = container  # type: ignore[attr-defined]
    frame._left = left  # type: ignore[attr-defined]
    frame._right = right  # type: ignore[attr-defined]


def build_detail(parent: tk.Widget, state: StateSnapshot, data: dict) -> tk.Frame:
    frame = tk.Frame(parent, bg=BG)
    if state.selected_engine is None:
        empty = build_detail_empty(frame, data.get("global_stats", {}))
        empty.pack(fill="both", expand=True)
        _mark_empty(frame, empty)
    else:
        container, left, right = _build_detail_split(frame, state, data)
        _mark_detail(frame, container, left, right)
    return frame


def update_detail(frame: tk.Frame, state: StateSnapshot, data: dict) -> None:
    new_mode = "empty" if state.selected_engine is None else "detail"
    if frame._mode != new_mode:  # type: ignore[attr-defined]
        # Mode flip — rebuild from scratch
        for child in list(frame.winfo_children()):
            child.destroy()
        if new_mode == "empty":
            empty = build_detail_empty(frame, data.get("global_stats", {}))
            empty.pack(fill="both", expand=True)
            _mark_empty(frame, empty)
        else:
            container, left, right = _build_detail_split(frame, state, data)
            _mark_detail(frame, container, left, right)
        return

    # Same mode — delegate to child updates
    if new_mode == "empty":
        update_detail_empty(frame._empty, data.get("global_stats", {}))  # type: ignore[attr-defined]
    else:
        update_detail_left(
            frame._left,  # type: ignore[attr-defined]
            instances=data.get("instances", []),
            kpis=data.get("kpis", {}),
            selected_instance=state.selected_instance,
        )
        update_detail_right(
            frame._right,  # type: ignore[attr-defined]
            run_id=state.selected_instance,
            log_lines=data.get("log_lines", []),
            follow_mode=state.follow_tail,
        )
