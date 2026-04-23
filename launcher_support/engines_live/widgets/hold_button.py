"""Hold-to-confirm button widget.

Usage:
    btn = HoldButton(parent, text="STOP", hold_ms=1500, on_complete=lambda: foo())
    btn.pack()

Behavior:
- Press (mouse button 1 or keyboard): starts progress fill (amber, left->right).
- Release before hold_ms elapses: cancels, resets fill, no on_complete call.
- Holds full hold_ms: calls on_complete(), flashes green for 300ms, resets.

Rendered as a Frame containing a Canvas with the fill rectangle and a Label.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from core.ui.ui_palette import AMBER, AMBER_B, BG3, GREEN, RED, WHITE


class HoldButton(tk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        text: str,
        hold_ms: int = 1500,
        on_complete: Callable[[], None] | None = None,
        width: int = 140,
        height: int = 28,
        base_color: str = RED,
        fill_color: str = AMBER,
        text_color: str = WHITE,
    ) -> None:
        super().__init__(parent, bg=BG3, highlightthickness=0)
        self._hold_ms = hold_ms
        self._on_complete = on_complete or (lambda: None)
        self._progress = 0.0
        self._job = None
        self._start_t = None
        self._text = text
        self._width = width
        self._height = height
        self._base_color = base_color
        self._fill_color = fill_color
        self._text_color = text_color

        self._canvas = tk.Canvas(
            self, width=width, height=height, bg=base_color,
            highlightthickness=0, bd=0,
        )
        self._canvas.pack()

        self._fill_id = self._canvas.create_rectangle(
            0, 0, 0, height, fill=fill_color, outline="",
        )
        self._text_id = self._canvas.create_text(
            width // 2, height // 2, text=text, fill=text_color,
            font=("Consolas", 9, "bold"),
        )

        self._canvas.bind("<ButtonPress-1>", lambda e: self.press())
        self._canvas.bind("<ButtonRelease-1>", lambda e: self.release())

    def press(self) -> None:
        """Start or restart the hold timer."""
        self._cancel_job()
        self._start_t = self._canvas.tk.call("clock", "milliseconds")
        self._progress = 0.0
        self._tick()

    def release(self) -> None:
        """Release -- cancels unless progress >= 1.0."""
        self._cancel_job()
        if self._progress < 1.0:
            self._progress = 0.0
            self._redraw()

    def _tick(self) -> None:
        if self._start_t is None:
            return
        now = self._canvas.tk.call("clock", "milliseconds")
        elapsed = now - self._start_t
        self._progress = min(1.0, elapsed / self._hold_ms)
        self._redraw()
        if self._progress >= 1.0:
            self._start_t = None
            self._job = None
            self._flash_complete()
            self._on_complete()
            return
        self._job = self.after(16, self._tick)

    def _flash_complete(self) -> None:
        self._canvas.itemconfig(self._fill_id, fill=GREEN)
        self.after(300, self._reset)

    def _reset(self) -> None:
        self._progress = 0.0
        self._canvas.itemconfig(self._fill_id, fill=self._fill_color)
        self._redraw()

    def _redraw(self) -> None:
        fill_w = int(self._width * self._progress)
        self._canvas.coords(self._fill_id, 0, 0, fill_w, self._height)
        label = self._text
        if 0 < self._progress < 1.0:
            label = f"HOLD TO {self._text}..."
        self._canvas.itemconfig(self._text_id, text=label)

    def _cancel_job(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
