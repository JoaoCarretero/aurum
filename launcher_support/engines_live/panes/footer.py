"""Engines Live footer — context-sensitive keybind hints.

Single DIM label packed across the bottom of the view. Text depends on
``state.focus_pane``. Kept intentionally static-y: no click handling, just
a visual affordance telling the user which keybinds are active in the
current pane.
"""
from __future__ import annotations

import tkinter as tk

from core.ui.ui_palette import BG, DIM
from launcher_support.engines_live.state import StateSnapshot


_HINTS: dict[str, str] = {
    "strip":            "↑↓←→ nav   Enter detail   + new   m mode   / filter   ? help   Esc exit",
    "detail_instances": "↑↓ nav   s stop   r restart   a stop all   + new   c config   Esc back",
    "detail_log":       "f follow   o open full   t telegram test   Esc back",
    "shelf":            "↑↓←→ nav   Enter start   b backtest   Esc back",
}


def _hint_for(state: StateSnapshot) -> str:
    return _HINTS.get(state.focus_pane, "")


def build_footer(parent: tk.Widget, state: StateSnapshot) -> tk.Frame:
    frame = tk.Frame(parent, bg=BG, highlightthickness=0)
    label = tk.Label(
        frame,
        text=_hint_for(state),
        bg=BG,
        fg=DIM,
        font=("Consolas", 9),
        anchor="w",
    )
    label.pack(fill="x", padx=8, pady=4)
    frame._label = label  # type: ignore[attr-defined]
    return frame


def update_footer(frame: tk.Frame, state: StateSnapshot) -> None:
    frame._label.configure(text=_hint_for(state))  # type: ignore[attr-defined]
