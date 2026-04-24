"""Strategy briefing screen — narrative + technical panel before execution.

Extracted from launcher.App._brief. Same signature surface: the screen
reads from launcher_support.briefings (BRIEFINGS + BRIEFINGS_V2), renders
the 4-section Bloomberg-style briefing (philosophy, best config, pipeline,
edge/risk), and wires up the three action buttons (run, view code, back).

The launcher App method is a 2-line delegate, preserving every existing
call site in launcher.py (seven call sites across the menu/strategy
screens) without renaming anything.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from code_viewer import CodeViewer
from core.ui.ui_palette import (
    AMBER, AMBER_D,
    BG, BG3,
    DIM, DIM2, FONT,
    GREEN, RED, WHITE,
)
from launcher_support.briefings import BRIEFINGS, BRIEFINGS_V2


def render(app, name, script, desc, parent_menu):
    """Build and mount the strategy briefing screen.

    Half-Life 2 / Bloomberg terminal aesthetic: dense, single-column,
    amber-on-black, monospace. Cuts cruft (technical V2 panel, model
    governance, meta operacional) in favor of the 4 things that matter:
    identity, best config, pipeline, edge/risk.
    """
    app._clr()
    app._clear_kb()
    app.h_path.configure(text=f"> {parent_menu.upper()} > {name}")
    app.h_stat.configure(text="BRIEFING", fg=AMBER_D)
    app.f_lbl.configure(text="ENTER executar  |  ESC voltar")

    brief = BRIEFINGS.get(name, {})

    _outer, f = app._ui_page_shell(name, desc, content_width=720)

    # Bloomberg-style section header — amber bar + label + thin rule
    def _section(parent, title):
        tk.Frame(parent, bg=BG, height=14).pack()
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x")
        tk.Frame(row, bg=AMBER, width=3).pack(side="left", fill="y")
        tk.Label(row, text=f" {title} ", font=(FONT, 8, "bold"),
                 fg=AMBER, bg=BG, anchor="w", padx=6).pack(side="left", fill="x", expand=True)
        tk.Frame(parent, bg=DIM2, height=1).pack(fill="x", pady=(2, 6))

    # -- HEADER bar: BRIEFING badge + 1-line desc + amber rule --
    hdr = tk.Frame(f, bg=BG)
    hdr.pack(fill="x", pady=(0, 4))
    tk.Label(hdr, text=" BRIEFING ", font=(FONT, 7, "bold"),
             fg=BG, bg=AMBER, padx=6, pady=2).pack(side="left")
    tk.Label(hdr, text=f"  {desc}", font=(FONT, 8), fg=DIM, bg=BG,
             anchor="w").pack(side="left", fill="x", expand=True)
    tk.Frame(f, bg=AMBER_D, height=1).pack(fill="x", pady=(4, 0))

    # Philosophy as a single italic block (no panel chrome)
    if brief.get("philosophy"):
        tk.Frame(f, bg=BG, height=10).pack()
        tk.Label(f, text=brief["philosophy"], font=(FONT, 8, "italic"),
                 fg=AMBER_D, bg=BG, wraplength=680, justify="left",
                 anchor="w").pack(fill="x")

    # -- BEST CONFIG (most actionable, render first) --
    bc = brief.get("best_config")
    if bc:
        _section(f, "BEST CONFIG · BATTERY VALIDATED")
        for k, v in bc.items():
            row = tk.Frame(f, bg=BG)
            row.pack(fill="x", pady=0)
            tk.Label(row, text=f"  {k.upper():<14}", font=(FONT, 8, "bold"),
                     fg=AMBER_D, bg=BG, anchor="w", width=16).pack(side="left")
            # Status row gets emoji-aware color
            v_str = str(v)
            _fg = (GREEN if "✓" in v_str else
                   RED if "✗" in v_str else
                   AMBER if "?" in v_str else WHITE)
            tk.Label(row, text=v_str, font=(FONT, 8),
                     fg=_fg, bg=BG, anchor="w",
                     wraplength=540, justify="left").pack(side="left", fill="x", expand=True)

    # -- PIPELINE (numbered, no panel chrome) --
    if brief.get("logic"):
        _section(f, "PIPELINE")
        for i, step in enumerate(brief["logic"], start=1):
            row = tk.Frame(f, bg=BG)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"  {i:02d}", font=(FONT, 7, "bold"),
                     fg=AMBER, bg=BG, width=4, anchor="w").pack(side="left")
            tk.Label(row, text=step, font=(FONT, 8), fg=WHITE, bg=BG,
                     wraplength=620, justify="left",
                     anchor="w").pack(side="left", fill="x", expand=True)

    # -- EDGE / RISK (color-tagged inline pills) --
    if brief.get("edge") or brief.get("risk"):
        _section(f, "EDGE / RISK")
        if brief.get("edge"):
            row = tk.Frame(f, bg=BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text="  EDGE  ", font=(FONT, 7, "bold"),
                     fg=BG, bg=GREEN, padx=4).pack(side="left")
            tk.Label(row, text="  " + brief["edge"], font=(FONT, 8),
                     fg=WHITE, bg=BG, anchor="w",
                     wraplength=580, justify="left").pack(side="left", fill="x", expand=True)
        if brief.get("risk"):
            row = tk.Frame(f, bg=BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text="  RISK  ", font=(FONT, 7, "bold"),
                     fg=BG, bg=RED, padx=4).pack(side="left")
            tk.Label(row, text="  " + brief["risk"], font=(FONT, 8),
                     fg=DIM, bg=BG, anchor="w",
                     wraplength=580, justify="left").pack(side="left", fill="x", expand=True)

    tk.Frame(f, bg=BG, height=20).pack()

    is_bt = parent_menu == "backtest"
    is_live = parent_menu == "live"

    btn_f = tk.Frame(f, bg=BG)
    btn_f.pack()

    if is_bt:
        next_fn = lambda: app._config_backtest(name, script, desc, parent_menu)
        btn_text = "  CONFIGURAR & RODAR  "
    elif is_live:
        next_fn = lambda: app._config_live(name, script, desc, parent_menu)
        btn_text = "  SELECIONAR MODO & RODAR  "
    else:
        next_fn = lambda: app._exec(name, script, desc, parent_menu, [])
        btn_text = "  EXECUTAR  "

    run_btn = tk.Label(btn_f, text=btn_text, font=(FONT, 10, "bold"),
                       fg=BG, bg=AMBER, cursor="hand2", padx=12, pady=4)
    run_btn.pack(side="left", padx=4)
    run_btn.bind("<Button-1>", lambda e: next_fn())
    app._kb("<Return>", next_fn)

    # VER CÓDIGO — opens engine source. Uses BRIEFINGS_V2 main_function
    # when available (richer entry point), falls back to script + scan_symbol.
    _v2 = BRIEFINGS_V2.get(name, None)
    _v2_files = _v2.get("source_files") if _v2 else None
    _v2_main = _v2.get("main_function") if _v2 else None

    def _open_code(_e=None, _script=script,
                   _files=_v2_files, _main=_v2_main):
        try:
            files = _files if _files else [_script]
            main = _main if _main else (_script, "scan_symbol")
            CodeViewer(app, source_files=files, main_function=main)
        except Exception as exc:
            messagebox.showerror("CodeViewer", f"{type(exc).__name__}: {exc}")

    code_btn = tk.Label(btn_f, text="  VER CÓDIGO  ", font=(FONT, 10, "bold"),
                        fg=AMBER, bg=BG3, cursor="hand2", padx=12, pady=4)
    code_btn.pack(side="left", padx=4)
    code_btn.bind("<Button-1>", _open_code)
    app._kb("<F2>", _open_code)

    back_btn = tk.Label(btn_f, text="  VOLTAR  ", font=(FONT, 10), fg=DIM, bg=BG3,
                        cursor="hand2", padx=12, pady=4)
    back_btn.pack(side="left", padx=4)
    back_btn.bind("<Button-1>", lambda e: app._menu(parent_menu))
    app._kb("<Escape>", lambda: app._menu(parent_menu))
