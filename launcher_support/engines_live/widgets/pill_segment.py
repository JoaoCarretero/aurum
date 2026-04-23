"""Segmented pill control. Used for mode selection (PAPER/DEMO/TESTNET/LIVE).

Usage:
    ps = PillSegment(
        parent,
        options=["PAPER", "DEMO", "TESTNET", "LIVE"],
        active="PAPER",
        colors={"PAPER": CYAN, "DEMO": GREEN, "TESTNET": AMBER, "LIVE": RED},
        on_change=lambda new: print(new),
    )
    ps.pack()
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from core.ui.ui_palette import (
    AMBER, BG, BG3, CYAN, DIM, GREEN, RED, WHITE,
)

DEFAULT_COLORS = {
    "PAPER": CYAN,
    "DEMO": GREEN,
    "TESTNET": AMBER,
    "LIVE": RED,
}


class PillSegment(tk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        options: list[str],
        active: str,
        colors: dict[str, str] | None = None,
        on_change: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent, bg=BG, highlightthickness=0)
        self._pill_options = list(options)
        self._colors = {**DEFAULT_COLORS, **(colors or {})}
        self._on_change = on_change or (lambda new: None)
        self._active = active if active in options else options[0]
        self._labels: dict[str, tk.Label] = {}

        for i, opt in enumerate(options):
            lbl = tk.Label(
                self, text=opt, font=("Consolas", 9, "bold"),
                padx=10, pady=2, cursor="hand2",
            )
            lbl.pack(side="left", padx=(0 if i == 0 else 2, 0))
            lbl.bind("<Button-1>", lambda e, o=opt: self._on_click(o))
            self._labels[opt] = lbl

        self._restyle()

    @property
    def active(self) -> str:
        return self._active

    def set_active(self, opt: str) -> None:
        if opt not in self._pill_options or opt == self._active:
            return
        self._active = opt
        self._restyle()
        self._on_change(opt)

    def _on_click(self, opt: str) -> None:
        self.set_active(opt)

    def _restyle(self) -> None:
        for opt, lbl in self._labels.items():
            col = self._colors.get(opt, DIM)
            if opt == self._active:
                lbl.configure(bg=col, fg=BG)
            else:
                lbl.configure(bg=BG3, fg=col)
