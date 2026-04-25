"""Compact agent badge drawn in tk.Canvas.

Kept as a small compatibility widget for tests and older callers. The current
Research Desk surface uses text chips directly; this canvas version follows
the same restrained terminal language: frame, two-letter code, no glyph lore.
"""
from __future__ import annotations

import tkinter as tk

from core.ui.ui_palette import DIM, FONT, PANEL
from launcher_support.research_desk.palette import AGENT_COLORS


_DEFAULT_SIZE = 96


class SigilCanvas:
    """Compatibility wrapper: a compact canvas badge for one agent."""

    def __init__(
        self,
        parent: tk.Misc,
        agent_key: str,
        *,
        size: int = _DEFAULT_SIZE,
        bg: str = PANEL,
    ):
        self.agent_key = agent_key
        self.size = size
        self.bg = bg
        self.canvas = tk.Canvas(
            parent,
            width=size,
            height=size,
            bg=bg,
            highlightthickness=0,
            borderwidth=0,
        )
        self.draw()

    def pack(self, **opts: object) -> None:
        self.canvas.pack(**opts)

    def grid(self, **opts: object) -> None:
        self.canvas.grid(**opts)

    def place(self, **opts: object) -> None:
        self.canvas.place(**opts)

    def draw(self) -> None:
        palette = AGENT_COLORS.get(self.agent_key)
        primary = palette.primary if palette is not None else DIM
        dim = palette.dim if palette is not None else DIM
        pad = max(3, int(self.size * 0.08))
        self.canvas.create_rectangle(
            pad,
            pad,
            self.size - pad,
            self.size - pad,
            outline=dim,
            width=1,
        )
        self.canvas.create_rectangle(
            pad,
            pad,
            self.size - pad,
            pad + max(2, int(self.size * 0.08)),
            fill=primary,
            outline=primary,
        )
        self.canvas.create_line(
            pad + 3,
            self.size - pad - 3,
            self.size - pad - 3,
            self.size - pad - 3,
            fill=dim,
            width=1,
        )
        code = (self.agent_key or "?")[:2].upper()
        font_size = max(7, int(self.size * 0.26))
        self.canvas.create_text(
            self.size / 2,
            self.size / 2 + max(1, int(self.size * 0.03)),
            text=code,
            fill=primary,
            font=(FONT, font_size, "bold"),
        )
