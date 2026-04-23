"""Research shelf: collapsible list of engines not currently running.

Header row (always visible): "RESEARCH · N engines not running" label on
the left, toggle arrow (▾ expanded / ▸ collapsed) on the right. The arrow
is clickable and fires ``on_toggle``.

Collapsed body: one line with comma-separated engine names in DIM.

Expanded body: grid of minimal cards (~160×60 px, 4 per row). Each card
shows the engine slug plus ``[START]`` and ``[BACKTEST]`` pseudo-buttons.
Clicking the card fires ``on_select(slug)``; the buttons fire
``on_start(slug)`` / ``on_backtest(slug)`` respectively.

The list of engines is supplied by the caller (``not_running_engines``).
Deriving that list from ``config/engines.py`` is a concern for the
view-level orchestrator (R3.16); this pane stays pure with respect to
its inputs.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from core.ui.ui_palette import AMBER, BG, BG3, BORDER, DIM


_CARD_WIDTH_PX = 160
_CARD_HEIGHT_PX = 60
_COLS = 4


def _title_text(engines: list[str]) -> str:
    """Header title — keeps the 'N engines' substring the tests assert on."""
    return f"RESEARCH · {len(engines)} engines not running"


def _arrow_text(expanded: bool) -> str:
    """Down-pointing triangle when expanded, right-pointing when collapsed."""
    return "▾" if expanded else "▸"


def _build_minimal_card(
    parent: tk.Widget,
    engine: str,
    on_select: Callable[[str], None] | None,
    on_start: Callable[[str], None] | None,
    on_backtest: Callable[[str], None] | None,
) -> tk.Frame:
    """Minimal engine tile for the expanded shelf.

    ~160×60 px. Name label on top, [START]/[BACKTEST] button row below.
    Clicking the card body (frame or name label) fires ``on_select``; the
    individual buttons fire their own callbacks and do not propagate.
    """
    card = tk.Frame(
        parent,
        bg=BG,
        highlightthickness=1,
        highlightbackground=BORDER,
        width=_CARD_WIDTH_PX,
        height=_CARD_HEIGHT_PX,
    )
    card.pack_propagate(False)

    name = tk.Label(
        card, text=engine, bg=BG, fg=DIM,
        font=("Consolas", 9, "bold"),
    )
    name.pack(anchor="w", padx=6, pady=(4, 0))

    btn_row = tk.Frame(card, bg=BG)
    btn_row.pack(anchor="w", padx=6, pady=(2, 4))

    start_btn = tk.Label(
        btn_row, text="[START]", bg=BG3, fg=AMBER,
        font=("Consolas", 8, "bold"), padx=4, cursor="hand2",
    )
    start_btn.pack(side="left")

    bt_btn = tk.Label(
        btn_row, text="[BACKTEST]", bg=BG3, fg=DIM,
        font=("Consolas", 8, "bold"), padx=4, cursor="hand2",
    )
    bt_btn.pack(side="left", padx=(4, 0))

    # Default-arg capture so every lambda binds its own engine slug, not a
    # reference to the loop variable of the caller.
    if on_select is not None:
        card.bind("<Button-1>", lambda _e, eng=engine: on_select(eng))
        name.bind("<Button-1>", lambda _e, eng=engine: on_select(eng))
    if on_start is not None:
        start_btn.bind("<Button-1>", lambda _e, eng=engine: on_start(eng))
    if on_backtest is not None:
        bt_btn.bind("<Button-1>", lambda _e, eng=engine: on_backtest(eng))

    return card


def _render_body(
    body: tk.Frame,
    engines: list[str],
    expanded: bool,
    on_select: Callable[[str], None] | None,
    on_start: Callable[[str], None] | None,
    on_backtest: Callable[[str], None] | None,
) -> None:
    """Destroy body children and redraw either the one-line list or the grid.

    Shelf contents are small (< 20 engines), so destroy-and-rebuild is
    cheap enough that the simplicity is worth more than in-place diffing.
    """
    for child in list(body.winfo_children()):
        child.destroy()
    if expanded:
        for i, eng in enumerate(engines):
            r, c = divmod(i, _COLS)
            card = _build_minimal_card(body, eng, on_select, on_start, on_backtest)
            card.grid(row=r, column=c, padx=4, pady=4, sticky="nw")
    else:
        joined = ", ".join(engines) if engines else "(none)"
        lbl = tk.Label(
            body, text=joined, bg=BG, fg=DIM,
            font=("Consolas", 9),
            anchor="w",
            justify="left",
        )
        lbl.pack(fill="x", padx=8, pady=(0, 4))


def build_shelf(
    parent: tk.Widget,
    not_running_engines: list[str],
    expanded: bool,
    on_toggle: Callable[[], None] | None = None,
    on_select: Callable[[str], None] | None = None,
    on_start: Callable[[str], None] | None = None,
    on_backtest: Callable[[str], None] | None = None,
) -> tk.Frame:
    """Build the collapsible research shelf.

    Attributes stashed on the returned frame (so ``update_shelf`` can
    re-render without the caller re-supplying callbacks):

    - ``_engines``:       list[str]
    - ``_expanded``:      bool
    - ``_on_toggle``:     Callable[[], None] | None
    - ``_on_select``:     Callable[[str], None] | None
    - ``_on_start``:      Callable[[str], None] | None
    - ``_on_backtest``:   Callable[[str], None] | None
    - ``_header_row``:    tk.Frame (the header row, kept across updates)
    - ``_title_label``:   tk.Label (the "RESEARCH · N engines..." label)
    - ``_toggle_label``:  tk.Label (the arrow ▾/▸, clickable)
    - ``_body``:          tk.Frame (recreated content on each update)
    """
    frame = tk.Frame(parent, bg=BG, highlightthickness=1, highlightbackground=BORDER)

    header = tk.Frame(frame, bg=BG)
    header.pack(fill="x", padx=8, pady=(4, 2))

    title = tk.Label(
        header, text=_title_text(not_running_engines), bg=BG, fg=DIM,
        font=("Consolas", 9, "bold"),
    )
    title.pack(side="left")

    arrow = tk.Label(
        header, text=_arrow_text(expanded), bg=BG, fg=DIM,
        font=("Consolas", 11, "bold"), cursor="hand2",
    )
    arrow.pack(side="right")
    if on_toggle is not None:
        arrow.bind("<Button-1>", lambda _e: on_toggle())

    body = tk.Frame(frame, bg=BG)
    body.pack(fill="x", padx=8, pady=(0, 4))
    _render_body(body, not_running_engines, expanded, on_select, on_start, on_backtest)

    frame._engines = list(not_running_engines)
    frame._expanded = expanded
    frame._on_toggle = on_toggle
    frame._on_select = on_select
    frame._on_start = on_start
    frame._on_backtest = on_backtest
    frame._header_row = header
    frame._title_label = title
    frame._toggle_label = arrow
    frame._body = body
    return frame


def update_shelf(
    frame: tk.Frame,
    not_running_engines: list[str],
    expanded: bool,
) -> None:
    """Update the shelf in place: refresh title/arrow, rebuild the body.

    The header row and its widgets are kept; only the body is destroyed
    and redrawn. Callbacks stashed on ``frame`` are reused.
    """
    frame._engines = list(not_running_engines)
    frame._expanded = expanded
    frame._title_label.configure(text=_title_text(not_running_engines))
    frame._toggle_label.configure(text=_arrow_text(expanded))
    _render_body(
        frame._body, not_running_engines, expanded,
        getattr(frame, "_on_select", None),
        getattr(frame, "_on_start", None),
        getattr(frame, "_on_backtest", None),
    )
