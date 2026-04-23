"""Empty-state of the detail pane — shown when no engine is selected.

Renders a simple centered vertical stack:
- "{N} engines live"         AMBER bold 18pt
- "total ticks 24h: {N}"     WHITE 11pt
- "total equity paper: $X"   GREEN 11pt
- "← Select an engine above" DIM  10pt

Only Labels — no interactivity. The frame stashes refs so that
``update_detail_empty`` can mutate text without rebuilding widgets.
"""
from __future__ import annotations

import tkinter as tk

from core.ui.ui_palette import AMBER, BG, DIM, GREEN, WHITE


def _label(parent: tk.Widget, *, text: str, fg: str, font: tuple) -> tk.Label:
    lbl = tk.Label(parent, text=text, bg=BG, fg=fg, font=font)
    lbl.pack(pady=2)
    return lbl


def _big_text(global_stats: dict) -> str:
    return f"{global_stats.get('engines_live', 0)} engines live"


def _ticks_text(global_stats: dict) -> str:
    return f"total ticks 24h: {global_stats.get('total_ticks_24h', 0)}"


def _equity_text(global_stats: dict) -> str:
    return f"total equity paper: ${global_stats.get('total_equity_paper', 0):.0f}"


def build_detail_empty(parent: tk.Widget, global_stats: dict) -> tk.Frame:
    frame = tk.Frame(parent, bg=BG)

    inner = tk.Frame(frame, bg=BG)
    inner.pack(expand=True)

    big = _label(inner, text=_big_text(global_stats), fg=AMBER, font=("Consolas", 18, "bold"))
    ticks = _label(inner, text=_ticks_text(global_stats), fg=WHITE, font=("Consolas", 11))
    equity = _label(inner, text=_equity_text(global_stats), fg=GREEN, font=("Consolas", 11))
    hint = _label(inner, text="← Select an engine above", fg=DIM, font=("Consolas", 10))

    frame._big = big
    frame._ticks = ticks
    frame._equity = equity
    frame._hint = hint
    return frame


def update_detail_empty(frame: tk.Frame, global_stats: dict) -> None:
    frame._big.configure(text=_big_text(global_stats))
    frame._ticks.configure(text=_ticks_text(global_stats))
    frame._equity.configure(text=_equity_text(global_stats))
