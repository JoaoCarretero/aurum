"""TabStrip — barra de tabs customizada no estilo do top nav do launcher.

Labels clicaveis com hover AMBER_B, tab ativa fica AMBER + underline.
Nao usa ttk pra preservar paleta Bloomberg.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from core.ui.ui_palette import AMBER, AMBER_B, BG, BG2, DIM, FONT, WHITE


class ClickableLabel(tk.Label):
    """A Label that triggers bound <Button-1> handlers when event_generate is called."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._button1_handler = None

    def bind(self, sequence=None, func=None, add=None):
        """Override bind to capture the <Button-1> handler."""
        if sequence == "<Button-1>" and func is not None:
            self._button1_handler = func
        return super().bind(sequence, func, add)

    def event_generate(self, sequence, **kw):
        """Override event_generate to trigger <Button-1> handlers."""
        super().event_generate(sequence, **kw)
        if sequence == "<Button-1>" and self._button1_handler is not None:
            # Create a fake event object
            event = tk.Event()
            event.widget = self
            self._button1_handler(event)


class TabStrip(tk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        tabs: list[tuple[str, str]],   # [(key, label), ...]
        on_select: Callable[[str], None],
        initial_key: str,
    ):
        super().__init__(parent, bg=BG)
        self._on_select = on_select
        self._tabs = tabs
        self._active = initial_key
        self._labels: dict[str, tk.Label] = {}
        self._build()

    def _build(self) -> None:
        for key, label_text in self._tabs:
            lbl = ClickableLabel(
                self, text=f"  {label_text}  ",
                font=(FONT, 9, "bold"),
                fg=WHITE, bg=BG2, cursor="hand2",
                padx=4, pady=6,
            )
            lbl.pack(side="left", padx=(0, 2))
            lbl.bind("<Button-1>", lambda _e, k=key: self._on_click(k))
            lbl.bind("<Enter>", lambda _e, k=key: self._on_hover(k, True))
            lbl.bind("<Leave>", lambda _e, k=key: self._on_hover(k, False))
            self._labels[key] = lbl
        self._repaint()
        tk.Frame(self, bg=DIM, height=1).pack(side="bottom", fill="x")

    def _on_click(self, key: str) -> None:
        if key == self._active:
            return
        self._active = key
        self._repaint()
        self._on_select(key)

    def _on_hover(self, key: str, entered: bool) -> None:
        if key == self._active:
            return
        lbl = self._labels[key]
        lbl.configure(fg=AMBER_B if entered else WHITE)

    def _repaint(self) -> None:
        for key, lbl in self._labels.items():
            if key == self._active:
                lbl.configure(fg=AMBER, bg=BG, font=(FONT, 9, "bold"))
            else:
                lbl.configure(fg=WHITE, bg=BG2, font=(FONT, 9, "bold"))

    def set_active(self, key: str) -> None:
        """Muda tab ativa SEM disparar on_select (evita loop na
        integracao com screen parent)."""
        if key not in self._labels:
            return
        self._active = key
        self._repaint()
