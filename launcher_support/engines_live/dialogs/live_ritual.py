"""LIVE confirmation ritual dialog.

Requires the operator to type the engine name exactly (case-sensitive)
before the CONFIRM button is enabled. Intended as a final speed-bump
before real-money orders fly. Returns ``True`` on CONFIRM, ``False`` on
Cancel / Escape / window close.

Usage:
    from launcher_support.engines_live.dialogs.live_ritual import (
        open_live_ritual,
    )
    if open_live_ritual(parent, engine="citadel"):
        start_live_instance(...)

Helpers `_build_ritual_widgets`, `_refresh_confirm_state`,
`_on_confirm_ritual`, `_on_cancel_ritual` are exposed for testing
without a full modal event loop.
"""
from __future__ import annotations

import tkinter as tk
from typing import Any

from core.ui.ui_palette import BG, DIM, RED, WHITE


def _refresh_confirm_state(widgets: dict, engine: str) -> None:
    """Enable CONFIRM only on exact (case-sensitive) match of engine name."""
    typed = widgets["name_var"].get()
    if typed == engine:
        widgets["confirm"].configure(state="normal", fg=RED)
    else:
        widgets["confirm"].configure(state="disabled", fg=DIM)


def _build_ritual_widgets(
    parent: tk.Widget,
    engine: str,
) -> tuple[tk.Toplevel, dict]:
    """Build the Toplevel and its widgets. Returns (top, widgets_dict).

    Confirm/Cancel commands are attached by the caller
    (`open_live_ritual`) so they can close over the shared `result` cell.
    """
    top = tk.Toplevel(parent, bg=BG)
    top.title(f"! LIVE - {engine.upper()}")
    top.transient(parent)

    widgets: dict[str, Any] = {"engine": engine}

    widgets["warn"] = tk.Label(
        top,
        text="! Real money. Real orders.",
        bg=BG,
        fg=RED,
        font=("Consolas", 12, "bold"),
    )
    widgets["warn"].pack(padx=16, pady=(14, 4))

    tk.Label(
        top,
        text=f"Type the engine name ({engine}) to confirm:",
        bg=BG,
        fg=WHITE,
        font=("Consolas", 10),
    ).pack(padx=16, pady=(4, 2))

    widgets["name_var"] = tk.StringVar(top, value="")
    widgets["entry"] = tk.Entry(
        top,
        textvariable=widgets["name_var"],
        bg=BG,
        fg=WHITE,
        insertbackground=WHITE,
        font=("Consolas", 10),
        highlightthickness=1,
        highlightbackground=DIM,
    )
    widgets["entry"].pack(padx=16, fill="x")

    widgets["_button_row"] = tk.Frame(top, bg=BG)
    widgets["_button_row"].pack(fill="x", padx=16, pady=(12, 14))

    # Confirm starts disabled; caller wires `command` after construction.
    widgets["confirm"] = tk.Button(
        widgets["_button_row"],
        text="CONFIRM",
        bg=BG,
        fg=DIM,
        font=("Consolas", 10, "bold"),
        bd=0,
        cursor="hand2",
        state="disabled",
    )
    widgets["confirm"].pack(side="left", padx=(0, 8))

    widgets["cancel"] = tk.Button(
        widgets["_button_row"],
        text="Cancel",
        bg=BG,
        fg=DIM,
        font=("Consolas", 10),
        bd=0,
        cursor="hand2",
    )
    widgets["cancel"].pack(side="left")

    widgets["name_var"].trace_add(
        "write", lambda *_a: _refresh_confirm_state(widgets, engine)
    )

    return top, widgets


def _on_confirm_ritual(top: tk.Toplevel, result: dict) -> None:
    """Mark the ritual as confirmed and close the Toplevel."""
    result["value"] = True
    top.destroy()


def _on_cancel_ritual(top: tk.Toplevel, result: dict) -> None:
    """Mark the ritual as cancelled and close the Toplevel."""
    result["value"] = False
    top.destroy()


def open_live_ritual(parent: tk.Widget, engine: str) -> bool:
    """Modal dialog requiring the operator to type the engine name.

    Returns ``True`` on CONFIRM, ``False`` on Cancel / Escape / window close.
    """
    top, widgets = _build_ritual_widgets(parent, engine)
    result: dict[str, Any] = {"value": False}

    widgets["confirm"].configure(
        command=lambda: _on_confirm_ritual(top, result),
    )
    widgets["cancel"].configure(
        command=lambda: _on_cancel_ritual(top, result),
    )
    top.protocol("WM_DELETE_WINDOW", lambda: _on_cancel_ritual(top, result))
    top.bind("<Escape>", lambda _e: _on_cancel_ritual(top, result))

    top.grab_set()
    top.wait_window()
    return bool(result["value"])
