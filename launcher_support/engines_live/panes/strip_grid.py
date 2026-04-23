"""Responsive engine card grid.

Cards auto-arrange into 3/4/5 columns based on parent width. A sentinel
"+ NEW ENGINE" card sits at the end of the grid. Each card is clickable:
engine cards fire on_select(engine_slug); the + card fires on_new_engine().

Column breakpoints (parent winfo_width):
  width < 900         -> 3 cols
  900  <= width < 1200 -> 4 cols
  width >= 1200        -> 5 cols

update_strip_grid uses destroy-and-rebuild for simplicity. Card counts
are small (10-15 engines), so the cost is negligible. TODO: switch to
in-place diff via widgets.engine_card.update_card if profiling shows it.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from core.ui.ui_palette import AMBER, BG, DIM
from launcher_support.engines_live.data.aggregate import EngineCard
from launcher_support.engines_live.widgets.engine_card import build_card

_CARD_WIDTH_PX = 200
_CARD_HEIGHT_PX = 104
_CARD_PAD = 6


def _calc_cols(width: int) -> int:
    """Pick column count based on parent viewport width."""
    if width >= 1200:
        return 5
    if width >= 900:
        return 4
    return 3


def _build_new_engine_card(
    parent: tk.Widget, on_new_engine: Callable[[], None] | None
) -> tk.Frame:
    """Build the sentinel '+ NEW ENGINE' card. Same footprint as EngineCard."""
    frame = tk.Frame(
        parent,
        bg=BG,
        highlightthickness=1,
        highlightbackground=DIM,
        highlightcolor=DIM,
        width=_CARD_WIDTH_PX,
        height=_CARD_HEIGHT_PX,
    )
    frame.pack_propagate(False)
    label = tk.Label(
        frame,
        text="+ NEW ENGINE",
        bg=BG,
        fg=AMBER,
        font=("Consolas", 10, "bold"),
    )
    label.pack(expand=True)
    if on_new_engine is not None:
        frame.bind("<Button-1>", lambda _e: on_new_engine())
        label.bind("<Button-1>", lambda _e: on_new_engine())
    return frame


def _render(
    frame: tk.Frame,
    cards: list[EngineCard],
    selected_engine: str | None,
    on_select: Callable[[str], None] | None,
    on_new_engine: Callable[[], None] | None,
) -> dict[str, tk.Frame]:
    """Destroy all children and rebuild the grid in place.

    Returns the new engine -> card Frame mapping (plus '__new__' for the
    sentinel + card).
    """
    for child in list(frame.winfo_children()):
        child.destroy()

    # Parent width may be 1 before first layout. Fall back to a sane default
    # so early renders don't collapse to a 1-column ribbon.
    raw_width = frame.winfo_width()
    width = raw_width if raw_width > 1 else 1000
    cols = _calc_cols(width)

    # Responsive columns: let tk distribute extra horizontal space evenly.
    for c in range(cols):
        frame.grid_columnconfigure(c, weight=1)

    card_frames: dict[str, tk.Frame] = {}
    for i, card in enumerate(cards):
        r, c = divmod(i, cols)
        is_selected = card.engine == selected_engine
        cf = build_card(frame, card, selected=is_selected)
        cf._selected = is_selected  # mirror engine_card.update_card's convention
        cf.grid(row=r, column=c, padx=_CARD_PAD, pady=_CARD_PAD, sticky="nw")
        if on_select is not None:
            engine_slug = card.engine
            cf.bind("<Button-1>", lambda _e, eng=engine_slug: on_select(eng))
            # Also bind on direct children so clicks on labels propagate.
            for child in cf.winfo_children():
                child.bind("<Button-1>", lambda _e, eng=engine_slug: on_select(eng))
        card_frames[card.engine] = cf

    # Sentinel '+ NEW ENGINE' card at the end.
    ne_index = len(cards)
    r, c = divmod(ne_index, cols)
    ne = _build_new_engine_card(frame, on_new_engine)
    ne.grid(row=r, column=c, padx=_CARD_PAD, pady=_CARD_PAD, sticky="nw")
    card_frames["__new__"] = ne

    return card_frames


def build_strip_grid(
    parent: tk.Widget,
    cards: list[EngineCard],
    selected_engine: str | None,
    on_select: Callable[[str], None] | None = None,
    on_new_engine: Callable[[], None] | None = None,
) -> tk.Frame:
    """Build the responsive engine card grid.

    Stashes cards/callbacks/card_frames on the returned frame so
    update_strip_grid can re-render without the caller re-supplying them.

    Attributes stashed on the returned frame:
    - _cards:          list[EngineCard]
    - _selected_engine: str | None
    - _on_select:      Callable[[str], None] | None
    - _on_new_engine:  Callable[[], None] | None
    - _card_frames:    dict[str, tk.Frame] (engine slug -> frame;
                       '__new__' key holds the sentinel + card)
    """
    frame = tk.Frame(parent, bg=BG)
    # Let tk settle any geometry from the pack/grid of the caller before we
    # compute winfo_width(). Caller can still re-render later if the parent
    # resizes (e.g. via <Configure> binding) by invoking update_strip_grid.
    frame.update_idletasks()

    card_frames = _render(frame, cards, selected_engine, on_select, on_new_engine)

    frame._cards = list(cards)
    frame._selected_engine = selected_engine
    frame._on_select = on_select
    frame._on_new_engine = on_new_engine
    frame._card_frames = card_frames
    return frame


def update_strip_grid(
    frame: tk.Frame,
    cards: list[EngineCard],
    selected_engine: str | None,
) -> None:
    """Re-render the grid with new cards / selection. Keeps stashed callbacks."""
    frame._cards = list(cards)
    frame._selected_engine = selected_engine
    card_frames = _render(
        frame,
        cards,
        selected_engine,
        getattr(frame, "_on_select", None),
        getattr(frame, "_on_new_engine", None),
    )
    frame._card_frames = card_frames
