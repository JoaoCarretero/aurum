"""Engines Live header pane.

Layout (left -> right):
- "> ENGINES" title (AMBER bold 12pt)
- counts label ("N live . M stale") — placeholder until wired by view.py
- PillSegment for mode (PAPER/DEMO/TESTNET/LIVE)
- market label (DIM, e.g., "BTC $42k")

Below the inner row, a 1px RED Frame is packed only when state.mode == "live".
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from core.ui.ui_palette import AMBER, BG, DIM, RED
from launcher_support.engines_live.state import StateSnapshot
from launcher_support.engines_live.widgets.pill_segment import PillSegment

_MODES = ["PAPER", "SHADOW", "DEMO", "TESTNET", "LIVE"]


def build_header(
    parent: tk.Widget,
    state: StateSnapshot,
    on_mode_change: Callable[[str], None] | None = None,
) -> tk.Frame:
    """Build the header frame. Stashes child references on the frame.

    Attributes exposed on the returned frame:
    - _pills:         PillSegment for mode selection
    - _live_line:     1px red Frame, packed iff state.mode == "live"
    - _counts_label:  tk.Label for "N live . M stale" (empty at build time)
    - _market_label:  tk.Label for market ticker (empty at build time)
    """
    frame = tk.Frame(parent, bg=BG, highlightthickness=0)

    row = tk.Frame(frame, bg=BG)
    row.pack(fill="x", padx=8, pady=4)

    title = tk.Label(
        row,
        text="› ENGINES",
        bg=BG,
        fg=AMBER,
        font=("Consolas", 12, "bold"),
    )
    title.pack(side="left")

    counts = tk.Label(
        row,
        text="",
        bg=BG,
        fg=DIM,
        font=("Consolas", 9),
    )
    counts.pack(side="left", padx=(12, 0))

    market = tk.Label(
        row,
        text="",
        bg=BG,
        fg=DIM,
        font=("Consolas", 9),
    )
    market.pack(side="right")

    pills = PillSegment(
        row,
        options=_MODES,
        active=state.mode.upper(),
        on_change=on_mode_change,
    )
    pills.pack(side="right", padx=(0, 12))

    live_line = tk.Frame(frame, bg=RED, height=1)
    if state.mode == "live":
        live_line.pack(fill="x", side="bottom")

    frame._pills = pills
    frame._live_line = live_line
    frame._counts_label = counts
    frame._market_label = market
    return frame


def update_header(frame: tk.Frame, state: StateSnapshot) -> None:
    """Reflect new state in the header: mode pill and live bottom border."""
    pills: PillSegment = frame._pills
    target = state.mode.upper()
    if pills.active != target:
        pills.set_active(target)

    live_line: tk.Frame = frame._live_line
    # winfo_manager() reports the current geometry manager ("pack" or ""),
    # independent of whether the root is currently mapped/visible.
    is_packed = live_line.winfo_manager() == "pack"
    if state.mode == "live":
        if not is_packed:
            live_line.pack(fill="x", side="bottom")
    else:
        if is_packed:
            live_line.pack_forget()
