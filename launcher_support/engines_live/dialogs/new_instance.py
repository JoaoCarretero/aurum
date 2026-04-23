"""+ NEW INSTANCE modal dialog.

Collects ``{mode, label, target}`` for a new engine instance. Returns
``None`` on cancel or window close.

Usage:
    from launcher_support.engines_live.dialogs.new_instance import (
        open_new_instance_dialog,
    )
    result = open_new_instance_dialog(parent, engine="citadel", default_mode="paper")
    if result is not None:
        start_instance(**result)

Helpers `_build_dialog_widgets`, `_refresh_preview`, `_on_confirm`,
`_on_cancel` are exposed for testing without a full modal event loop.
"""
from __future__ import annotations

import tkinter as tk
from typing import Any

from core.ui.ui_palette import AMBER, BG, DIM, WHITE
from launcher_support.engines_live.widgets.hold_button import HoldButton
from launcher_support.engines_live.widgets.pill_segment import PillSegment
from tools.operations.run_id import sanitize_label

_MODES = ["PAPER", "DEMO", "TESTNET", "LIVE"]
_TARGETS = ["LOCAL", "VPS"]


def _preview_text(engine: str, mode: str, label: str, target: str) -> str:
    """Compose an approximate launch command for the preview label."""
    parts = [f"$ python -m engines.{engine}", f"--mode={mode}"]
    if label:
        parts.append(f"--label={label}")
    parts.append(f"--target={target}")
    return " ".join(parts)


def _refresh_preview(widgets: dict, engine: str) -> None:
    """Recompute preview text from current widget state."""
    mode = widgets["mode_pills"].active.lower()
    label = widgets["label_var"].get()
    target = widgets["target_pills"].active.lower()
    widgets["preview"].configure(text=_preview_text(engine, mode, label, target))


def _build_dialog_widgets(
    parent: tk.Widget,
    engine: str,
    default_mode: str,
) -> tuple[tk.Toplevel, dict]:
    """Build the Toplevel and its widgets. Returns (top, widgets_dict).

    Does NOT wire Confirm/Cancel buttons — those are attached by the
    caller (`open_new_instance_dialog`) so they can close over the
    `result` cell. An empty ``_buttons_row`` frame is provided ready to
    hold them.
    """
    top = tk.Toplevel(parent, bg=BG)
    top.title(f"+ New instance - {engine.upper()}")
    top.transient(parent)

    widgets: dict[str, Any] = {"engine": engine}

    tk.Label(
        top, text="MODE", bg=BG, fg=DIM, font=("Consolas", 9, "bold"),
    ).pack(anchor="w", padx=12, pady=(10, 2))
    widgets["mode_pills"] = PillSegment(
        top,
        options=_MODES,
        active=default_mode.upper(),
        on_change=lambda _m: _refresh_preview(widgets, engine),
    )
    widgets["mode_pills"].pack(anchor="w", padx=12)

    tk.Label(
        top, text="LABEL (optional)", bg=BG, fg=DIM, font=("Consolas", 9, "bold"),
    ).pack(anchor="w", padx=12, pady=(10, 2))
    widgets["label_var"] = tk.StringVar(top, value="")
    widgets["label_entry"] = tk.Entry(
        top,
        textvariable=widgets["label_var"],
        bg=BG,
        fg=WHITE,
        insertbackground=WHITE,
        font=("Consolas", 10),
        highlightthickness=1,
        highlightbackground=DIM,
    )
    widgets["label_entry"].pack(fill="x", padx=12)

    tk.Label(
        top, text="TARGET", bg=BG, fg=DIM, font=("Consolas", 9, "bold"),
    ).pack(anchor="w", padx=12, pady=(10, 2))
    widgets["target_pills"] = PillSegment(
        top,
        options=_TARGETS,
        active="LOCAL",
        on_change=lambda _t: _refresh_preview(widgets, engine),
    )
    widgets["target_pills"].pack(anchor="w", padx=12)

    tk.Label(
        top, text="PREVIEW", bg=BG, fg=DIM, font=("Consolas", 9, "bold"),
    ).pack(anchor="w", padx=12, pady=(14, 2))
    widgets["preview"] = tk.Label(
        top,
        text="",
        bg=BG,
        fg=AMBER,
        font=("Consolas", 9),
        anchor="w",
        justify="left",
        wraplength=420,
    )
    widgets["preview"].pack(fill="x", padx=12)

    widgets["label_var"].trace_add("write", lambda *_a: _refresh_preview(widgets, engine))

    _refresh_preview(widgets, engine)

    widgets["_buttons_row"] = tk.Frame(top, bg=BG)
    widgets["_buttons_row"].pack(fill="x", padx=12, pady=(14, 10))

    return top, widgets


def _on_confirm(top: tk.Toplevel, widgets: dict, result: dict) -> None:
    """Populate result cell with current selection and close the Toplevel."""
    raw_label = widgets["label_var"].get()
    sanitized = sanitize_label(raw_label) or ""
    result["value"] = {
        "mode": widgets["mode_pills"].active.lower(),
        "label": sanitized,
        "target": widgets["target_pills"].active.lower(),
    }
    top.destroy()


def _on_cancel(top: tk.Toplevel, result: dict) -> None:
    """Close the Toplevel leaving result cell untouched (stays None)."""
    # result["value"] remains None — caller seeds it as None.
    top.destroy()


def open_new_instance_dialog(
    parent: tk.Widget,
    engine: str,
    default_mode: str = "paper",
) -> dict | None:
    """Open a modal dialog. Returns ``{mode, label, target}`` on confirm,
    ``None`` on cancel / Escape / window close.
    """
    top, widgets = _build_dialog_widgets(parent, engine, default_mode)
    result: dict[str, Any] = {"value": None}

    btn_row = widgets["_buttons_row"]

    def _confirm() -> None:
        _on_confirm(top, widgets, result)

    if widgets["mode_pills"].active == "LIVE":
        confirm_btn: tk.Widget = HoldButton(
            btn_row, text="CONFIRM", hold_ms=1500, on_complete=_confirm,
        )
    else:
        confirm_btn = tk.Button(
            btn_row,
            text="CONFIRM",
            bg=BG,
            fg=AMBER,
            font=("Consolas", 10, "bold"),
            bd=0,
            cursor="hand2",
            command=_confirm,
        )
    confirm_btn.pack(side="left", padx=(0, 8))

    cancel_btn = tk.Button(
        btn_row,
        text="Cancel",
        bg=BG,
        fg=DIM,
        font=("Consolas", 10),
        bd=0,
        cursor="hand2",
        command=lambda: _on_cancel(top, result),
    )
    cancel_btn.pack(side="left")

    top.protocol("WM_DELETE_WINDOW", lambda: _on_cancel(top, result))
    top.bind("<Escape>", lambda _e: _on_cancel(top, result))

    top.grab_set()
    top.wait_window()
    return result["value"]
