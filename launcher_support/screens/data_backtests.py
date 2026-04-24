"""Standalone backtest browser — split-pane run list + detail panel.

Extracted from launcher.App._data_backtests. render(app) mounts the
screen into the current content area. Registers the standalone widgets
under the same _dash_widgets keys (bt_list / bt_count / bt_detail /
bt_canvas) that the main dashboard uses, so the shared click handlers
(_dash_backtest_render / _dash_backtest_select / _dash_backtest_delete)
work without per-screen duplication.
"""
from __future__ import annotations

import json
import tkinter as tk

from core.ui.scroll import bind_mousewheel
from core.ui.ui_palette import (
    AMBER, AMBER_D,
    BG, BORDER,
    DIM, DIM2, FONT,
    PANEL,
)


def render(app):
    """Build the standalone backtest browser.

    Reached from DATA CENTER > BACKTESTS (or 'B' at the hub) and from
    the deploy-pipeline 'VALIDATED' tile.
    """
    # _BT_COLS is a launcher.py module-level const shared with the
    # dashboard renderers that haven't been extracted yet. Pulled lazily
    # to avoid bootstrapping the launcher module during unit tests.
    import launcher as _launcher_mod
    _BT_COLS = _launcher_mod._BT_COLS

    app._clr()
    app._clear_kb()
    app.h_path.configure(text="> DATA > BACKTESTS")
    app.h_stat.configure(text="BROWSE", fg=AMBER_D)
    app.f_lbl.configure(
        text="ESC voltar  |  click run for details  |  DELETE to remove")
    app._kb("<Escape>", lambda: app._data_center())

    # Ensure _dash_widgets exists — the standalone screen owns this
    # instance attr when it's used outside the dashboard build path.
    app._dash_widgets = getattr(app, "_dash_widgets", {})

    _outer, outer = app._ui_page_shell(
        "BACKTEST RUNS",
        "Indexed historical runs reconciled against data/index.json",
    )
    hdr = tk.Frame(outer, bg=BG)
    hdr.pack(fill="x")
    count_l = tk.Label(hdr, text="", font=(FONT, 8), fg=DIM, bg=BG)
    count_l.pack(side="right")
    app._dash_widgets[("bt_count",)] = count_l
    tk.Frame(outer, bg=DIM2, height=1).pack(fill="x", pady=(4, 10))

    split = tk.Frame(outer, bg=BG)
    split.pack(fill="both", expand=True)
    split.grid_columnconfigure(0, weight=3, uniform="bt_split")
    split.grid_columnconfigure(1, weight=2, uniform="bt_split")
    split.grid_rowconfigure(0, weight=1)

    # -- LEFT: run list --
    left = tk.Frame(split, bg=BG, highlightbackground=BORDER, highlightthickness=1)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

    hrow = tk.Frame(left, bg=BG)
    hrow.pack(fill="x")
    for label, width in _BT_COLS:
        tk.Label(hrow, text=label, font=(FONT, 8, "bold"),
                 fg=DIM, bg=BG, width=width, anchor="w").pack(side="left")
    tk.Frame(left, bg=DIM2, height=1).pack(fill="x", pady=(1, 2))

    # Scrollable inner frame for the row list
    canvas_wrap = tk.Frame(left, bg=BG)
    canvas_wrap.pack(fill="both", expand=True)
    canvas = tk.Canvas(canvas_wrap, bg=BG, bd=0, highlightthickness=0)
    scroll = tk.Scrollbar(canvas_wrap, orient="vertical",
                          command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)
    canvas.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    inner = tk.Frame(canvas, bg=BG)
    window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
    app._bind_canvas_window_width(canvas, window_id, pad_x=4)
    inner.bind("<Configure>",
               lambda e, c=canvas: c.configure(scrollregion=c.bbox("all")))

    bind_mousewheel(canvas)

    app._dash_widgets[("bt_list",)] = inner
    app._dash_widgets[("bt_canvas",)] = canvas

    # -- RIGHT: detail panel --
    right = tk.Frame(split, bg=PANEL, width=420,
                     highlightbackground=BORDER, highlightthickness=1)
    right.grid(row=0, column=1, sticky="nsew")
    right.grid_propagate(False)

    tk.Label(right, text="DETAILS", font=(FONT, 7, "bold"),
             fg=AMBER_D, bg=PANEL, anchor="w").pack(anchor="nw",
                                                    padx=10, pady=(10, 4))
    tk.Frame(right, bg=DIM2, height=1).pack(fill="x", padx=10, pady=(0, 6))

    # Scrollable inner area — metric blocks (PERFORMANCE/TRADES/CONFIG)
    # can overflow the panel height on smaller windows. Wrapping the
    # detail body in a Canvas + Scrollbar lets the content grow without
    # clipping, while the "[ DETAILS ]" badge above stays pinned.
    scroll_wrap = tk.Frame(right, bg=PANEL)
    scroll_wrap.pack(fill="both", expand=True, padx=6, pady=(2, 6))

    d_canvas = tk.Canvas(scroll_wrap, bg=PANEL, bd=0,
                         highlightthickness=0)
    d_scroll = tk.Scrollbar(scroll_wrap, orient="vertical",
                            command=d_canvas.yview)
    d_canvas.configure(yscrollcommand=d_scroll.set)
    d_canvas.pack(side="left", fill="both", expand=True)
    d_scroll.pack(side="right", fill="y")

    detail_body = tk.Frame(d_canvas, bg=PANEL)
    window_id = d_canvas.create_window((0, 0), window=detail_body, anchor="nw",
                                       width=300)
    app._bind_canvas_window_width(d_canvas, window_id, pad_x=18, min_width=300)
    detail_body.bind("<Configure>",
                     lambda e, c=d_canvas:
                     c.configure(scrollregion=c.bbox("all")))

    bind_mousewheel(d_canvas)

    app._dash_widgets[("bt_detail",)] = detail_body

    # Placeholder — overwritten by auto-select below when the index
    # has any runs. Kept as a fallback for the empty-index case.
    tk.Label(detail_body,
             text="\n  click any run on the left\n  to load metrics + actions",
             font=(FONT, 9, "bold"), fg=AMBER_D, bg=PANEL,
             justify="left").pack(anchor="w")

    # Bottom bar: back + jump to engine logs
    tk.Frame(outer, bg=BG, height=10).pack()
    bottom = tk.Frame(outer, bg=BG)
    bottom.pack(fill="x")

    back_btn = tk.Label(bottom, text="  VOLTAR  ",
                        font=(FONT, 9), fg=DIM, bg=BG,
                        cursor="hand2", padx=10, pady=3)
    back_btn.pack(side="left")
    back_btn.bind("<Button-1>", lambda e: app._data_center())
    back_btn.bind("<Enter>", lambda e: back_btn.configure(fg=AMBER))
    back_btn.bind("<Leave>", lambda e: back_btn.configure(fg=DIM))

    eng_btn = tk.Label(bottom, text="  ENGINE LOGS  ",
                       font=(FONT, 9, "bold"), fg=AMBER_D, bg=BG,
                       cursor="hand2", padx=10, pady=3)
    eng_btn.pack(side="left", padx=(6, 0))
    eng_btn.bind("<Button-1>", lambda e: app._data_engines())
    eng_btn.bind("<Enter>", lambda e: eng_btn.configure(fg=AMBER))
    eng_btn.bind("<Leave>", lambda e: eng_btn.configure(fg=AMBER_D))

    # Trigger the initial render — this reads data/index.json, sorts
    # by timestamp desc, renders up to 50 rows with click handlers.
    app._dash_backtest_render()

    # Auto-select the most recent run so the detail panel is never
    # empty on first open. The user was getting confused when the
    # only visible thing in the right pane was "[ DETAILS ]" plus a
    # dim placeholder — it looked like nothing clickable existed.
    # With auto-select the detail panel always shows real metrics,
    # OPEN HTML + DELETE buttons immediately. Clicking other rows
    # still swaps the selection as before.
    try:
        newest = getattr(app, "_bt_recent_run_id", None)
        if newest:
            app.after(0, lambda rid=newest:
                      app._dash_backtest_select(rid))
    except (OSError, json.JSONDecodeError, TypeError):
        pass
