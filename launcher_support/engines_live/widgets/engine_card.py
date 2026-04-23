"""Single engine card (V3 shape) render + update.

Card format:
    ╭ CITADEL ── 2●● ╮
    │ p+s · 15m      │
    │ 0/17 nvl/t     │
    │ eq $10k · 0dd% │
    ╰────────────────╯

State determines border color + dot symbols:
- healthy:     BORDER,  ● per instance (green)
- selected:    AMBER_B (2px border), + lines
- stale:       HAZARD,  ! per stale instance
- error:       RED,     ✕ per error instance
- not running: DIM,     ○ (used in research shelf, not main grid)
"""
from __future__ import annotations

import tkinter as tk

from core.ui.ui_palette import (
    AMBER, AMBER_B, BG, BG2, BG3,
    BORDER, DIM, DIM2, GREEN, HAZARD, RED, WHITE,
)
from launcher_support.engines_live.data.aggregate import EngineCard
from launcher_support.engines_live_helpers import format_uptime

_CARD_WIDTH_PX = 200
_CARD_HEIGHT_PX = 104


def _dot_chars(card: EngineCard) -> str:
    return "●" * card.live_count + "!" * card.stale_count + "✕" * card.error_count


def _dot_color(card: EngineCard) -> str:
    if card.error_count > 0:
        return RED
    if card.stale_count > 0:
        return HAZARD
    return GREEN


def _border_color(card: EngineCard, selected: bool) -> str:
    if selected:
        return AMBER_B
    if card.has_error:
        return RED
    if card.stale_count > 0:
        return HAZARD
    return BORDER


def _equity_short(eq: float) -> str:
    if eq >= 1000:
        return f"${eq/1000:.0f}k"
    return f"${eq:.0f}"


def build_card(parent: tk.Widget, card: EngineCard, selected: bool = False) -> tk.Frame:
    border = _border_color(card, selected)
    frame = tk.Frame(
        parent,
        bg=BG2 if selected else BG,
        highlightthickness=2 if selected else 1,
        highlightbackground=border,
        highlightcolor=border,
        width=_CARD_WIDTH_PX, height=_CARD_HEIGHT_PX,
    )
    frame.pack_propagate(False)

    # Header line: "CITADEL ── 2●● " — display label is a direct child of
    # frame so callers/tests can introspect it via frame.winfo_children().
    tk.Label(
        frame, text=card.display, bg=frame["bg"],
        fg=RED if card.has_error else AMBER,
        font=("Consolas", 10, "bold"), anchor="w",
    ).pack(side="top", fill="x", padx=8, pady=(6, 0))

    tk.Label(
        frame, text=f"{card.instance_count}{_dot_chars(card)}",
        bg=frame["bg"], fg=_dot_color(card),
        font=("Consolas", 10, "bold"), anchor="e",
    ).pack(side="top", fill="x", padx=8, pady=(0, 2))

    # Body lines
    def _line(text: str, fg: str = WHITE, bold: bool = False) -> None:
        tk.Label(
            frame, text=text, bg=frame["bg"], fg=fg,
            font=("Consolas", 9, "bold" if bold else "normal"),
            anchor="w",
        ).pack(fill="x", padx=8)

    _line(f"{card.mode_summary} · {format_uptime(seconds=card.max_uptime_s)}", fg=DIM)
    _line(f"{card.total_novel}/{card.total_ticks} nvl/t", fg=WHITE, bold=True)

    eq_color = GREEN if card.total_equity > 0 else DIM2
    _line(f"eq {_equity_short(card.total_equity)}", fg=eq_color)

    frame._card = card  # stash for update_card
    return frame


def update_card(frame: tk.Frame, card: EngineCard, selected: bool = False) -> None:
    """Re-render in place. For diff-based repaint, this destroys children and
    rebuilds. The caller avoids calling this when card == frame._card already.
    """
    prev = getattr(frame, "_card", None)
    if prev == card and selected == getattr(frame, "_selected", None):
        return
    for child in list(frame.winfo_children()):
        child.destroy()
    border = _border_color(card, selected)
    frame.configure(
        bg=BG2 if selected else BG,
        highlightthickness=2 if selected else 1,
        highlightbackground=border,
        highlightcolor=border,
    )

    tk.Label(
        frame, text=card.display, bg=frame["bg"],
        fg=RED if card.has_error else AMBER,
        font=("Consolas", 10, "bold"), anchor="w",
    ).pack(side="top", fill="x", padx=8, pady=(6, 0))
    tk.Label(
        frame, text=f"{card.instance_count}{_dot_chars(card)}",
        bg=frame["bg"], fg=_dot_color(card),
        font=("Consolas", 10, "bold"), anchor="e",
    ).pack(side="top", fill="x", padx=8, pady=(0, 2))

    def _line(text: str, fg: str = WHITE, bold: bool = False) -> None:
        tk.Label(
            frame, text=text, bg=frame["bg"], fg=fg,
            font=("Consolas", 9, "bold" if bold else "normal"),
            anchor="w",
        ).pack(fill="x", padx=8)

    _line(f"{card.mode_summary} · {format_uptime(seconds=card.max_uptime_s)}", fg=DIM)
    _line(f"{card.total_novel}/{card.total_ticks} nvl/t", fg=WHITE, bold=True)
    eq_color = GREEN if card.total_equity > 0 else DIM2
    _line(f"eq {_equity_short(card.total_equity)}", fg=eq_color)

    frame._card = card
    frame._selected = selected
