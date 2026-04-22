"""Backtest config dialog — period, basket, charts, leverage.

Extracted from launcher.App._config_backtest. render(app, name, script,
desc, parent_menu) builds the dialog, wires the basket/leverage
selectors, and on RUN assembles both the legacy stdin-auto-inputs and
the modern CLI args before handing control to app._exec.
"""
from __future__ import annotations

import tkinter as tk

from core.ui.ui_palette import (
    AMBER, AMBER_D,
    BG, BG3,
    DIM, DIM2, FONT,
    GREEN,
)


def render(app, name, script, desc, parent_menu):
    """Mount the backtest config dialog for ``name``.

    Uses launcher.py module-level constants PERIODS_UI and BASKETS_UI
    (pulled lazily to avoid a top-level cycle). Config state lives on
    the App instance (_cfg_period / _cfg_basket / _cfg_plots /
    _cfg_leverage) and on the widget-reference tuples (_per_btns /
    _bsk_btns / _bsk_assets / _bsk_preview_* / _plot_btn / _lev_btns)
    that downstream helpers like _select_basket already consume.
    """
    import launcher as _launcher_mod
    PERIODS_UI = _launcher_mod.PERIODS_UI
    BASKETS_UI = _launcher_mod.BASKETS_UI

    app._clr()
    app._clear_kb()
    app.h_path.configure(text=f"> {parent_menu.upper()} > {name} > CONFIG")
    app.h_stat.configure(text="CONFIGURAR", fg=AMBER_D)
    app.f_lbl.configure(text="Clique nas opções  |  ENTER rodar com seleções")

    # State
    app._cfg_period = "90"
    app._cfg_basket = ""  # empty = default
    app._cfg_plots = "s"
    app._cfg_leverage = ""

    _outer, f = app._ui_page_shell(
        f"{name} · BACKTEST CONFIG",
        "Configure run horizon, basket and execution options before launch",
        content_width=920,
    )

    # -- PERIOD --
    tk.Label(f, text="PERÍODO", font=(FONT, 8, "bold"), fg=AMBER, bg=BG, anchor="w").pack(anchor="w")
    tk.Frame(f, bg=DIM2, height=1).pack(fill="x", pady=(2, 6))
    per_f = tk.Frame(f, bg=BG)
    per_f.pack(fill="x", pady=(0, 14))

    app._per_btns = []
    for label, hint, val in PERIODS_UI:
        btn = tk.Label(per_f, text=f" {label} ", font=(FONT, 9, "bold"),
                       fg=BG if val == "90" else DIM, bg=AMBER if val == "90" else BG3,
                       cursor="hand2", padx=10, pady=4)
        btn.pack(side="left", padx=2)
        app._per_btns.append((btn, val))

        def select_period(event, v=val):
            app._cfg_period = v
            for b, bv in app._per_btns:
                b.configure(fg=BG if bv == v else DIM, bg=AMBER if bv == v else BG3)
            # Limpa o entry custom ao selecionar preset.
            try:
                app._cfg_period_entry.delete(0, tk.END)
            except Exception:
                pass
        btn.bind("<Button-1>", select_period)

    # Custom days entry — digite um numero livre, sobrescreve preset.
    tk.Label(per_f, text="  ou  ", font=(FONT, 8), fg=DIM2,
             bg=BG).pack(side="left", padx=(8, 2))
    app._cfg_period_entry = tk.Entry(per_f, width=6, font=(FONT, 9, "bold"),
                                     fg=AMBER, bg=BG3, insertbackground=AMBER,
                                     relief="flat", highlightthickness=1,
                                     highlightbackground=DIM2,
                                     highlightcolor=AMBER)
    app._cfg_period_entry.pack(side="left", padx=2, ipady=3)

    def _apply_custom_period(_event=None):
        raw = app._cfg_period_entry.get().strip()
        try:
            n = int(raw)
        except ValueError:
            return
        if n < 7:
            return
        app._cfg_period = str(n)
        # Limpa highlight dos presets (usuario foi pro custom).
        for b, _bv in app._per_btns:
            b.configure(fg=DIM, bg=BG3)
    app._cfg_period_entry.bind("<KeyRelease>", _apply_custom_period)
    app._cfg_period_entry.bind("<FocusOut>", _apply_custom_period)

    tk.Label(per_f, text="dias", font=(FONT, 8), fg=DIM2,
             bg=BG).pack(side="left", padx=(2, 0))

    # -- BASKET --
    tk.Label(f, text="CESTA DE ATIVOS", font=(FONT, 8, "bold"), fg=AMBER, bg=BG, anchor="w").pack(anchor="w")
    tk.Frame(f, bg=DIM2, height=1).pack(fill="x", pady=(2, 6))

    # Basket buttons — row 1
    bsk_f = tk.Frame(f, bg=BG)
    bsk_f.pack(fill="x")

    app._bsk_btns = []
    app._bsk_assets = {b[1]: b[2] for b in BASKETS_UI}  # val -> asset list

    for label, val, assets in BASKETS_UI[:5]:
        btn = tk.Label(bsk_f, text=f" {label} ", font=(FONT, 8, "bold"),
                       fg=BG if val == "" else DIM, bg=AMBER if val == "" else BG3,
                       cursor="hand2", padx=8, pady=3)
        btn.pack(side="left", padx=2)
        app._bsk_btns.append((btn, val))
        btn.bind("<Button-1>", lambda e, v=val: app._select_basket(v))

    # Row 2
    bsk_f2 = tk.Frame(f, bg=BG)
    bsk_f2.pack(fill="x", pady=(2, 0))
    for label, val, assets in BASKETS_UI[5:]:
        btn = tk.Label(bsk_f2, text=f" {label} ", font=(FONT, 8, "bold"),
                       fg=DIM, bg=BG3, cursor="hand2", padx=8, pady=3)
        btn.pack(side="left", padx=2)
        app._bsk_btns.append((btn, val))
        btn.bind("<Button-1>", lambda e, v=val: app._select_basket(v))

    # Preview bar — shows selected assets
    app._bsk_preview_f = tk.Frame(f, bg=BG)
    app._bsk_preview_f.pack(fill="x", pady=(6, 14))
    app._bsk_preview_count = tk.Label(app._bsk_preview_f, text="", font=(FONT, 7, "bold"),
                                      fg=AMBER_D, bg=BG, padx=6)
    app._bsk_preview_count.pack(side="left", pady=4)
    app._bsk_preview_lbl = tk.Label(app._bsk_preview_f, text="", font=(FONT, 7),
                                    fg=DIM, bg=BG, anchor="w", padx=4)
    app._bsk_preview_lbl.pack(side="left", fill="x", expand=True, pady=4)
    tk.Frame(app._bsk_preview_f, bg=DIM2, height=1).pack(fill="x", side="bottom")

    # Show default basket on load
    app._select_basket("")

    # -- OPTIONS --
    opt_f = tk.Frame(f, bg=BG)
    opt_f.pack(fill="x", pady=(0, 14))

    # Charts toggle
    app._plot_btn = tk.Label(opt_f, text=" GRÁFICOS ON ", font=(FONT, 8, "bold"),
                             fg=BG, bg=GREEN, cursor="hand2", padx=8, pady=3)
    app._plot_btn.pack(side="left", padx=2)

    def toggle_plots(event):
        app._cfg_plots = "s" if app._cfg_plots == "n" else "n"
        on = app._cfg_plots == "s"
        app._plot_btn.configure(text=" GRÁFICOS ON " if on else " GRÁFICOS OFF ",
                                fg=BG if on else DIM, bg=GREEN if on else BG3)
    app._plot_btn.bind("<Button-1>", toggle_plots)

    # Leverage
    tk.Label(opt_f, text="  LEVERAGE:", font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG).pack(side="left", padx=(12, 4))
    app._lev_btns = []
    for lev in ["1.0", "2.0", "3.0", "5.0"]:
        btn = tk.Label(opt_f, text=f" {lev}x ", font=(FONT, 8, "bold"),
                       fg=BG if lev == "1.0" else DIM, bg=AMBER if lev == "1.0" else BG3,
                       cursor="hand2", padx=6, pady=3)
        btn.pack(side="left", padx=1)
        app._lev_btns.append((btn, lev))

        def select_lev(event, v=lev):
            app._cfg_leverage = "" if v == "1.0" else v
            for b, bv in app._lev_btns:
                b.configure(fg=BG if bv == v else DIM, bg=AMBER if bv == v else BG3)
        btn.bind("<Button-1>", select_lev)

    tk.Frame(f, bg=BG, height=10).pack()

    # Summary
    tk.Frame(f, bg=DIM2, height=1).pack(fill="x", pady=(0, 10))

    # Run button
    btn_f = tk.Frame(f, bg=BG)
    btn_f.pack()

    def do_run():
        # Build BOTH stdin auto-inputs (legacy) AND CLI args (preferred).
        # Engines that parse argparse use CLI; engines with interactive
        # prompts read stdin. Modern engines respect --no-menu and CLI
        # args, falling back to stdin only when --no-menu is absent.
        inputs = [app._cfg_period, app._cfg_basket]
        if name == "CITADEL":
            inputs.append(app._cfg_plots)
        inputs.append(app._cfg_leverage)
        inputs.append("")  # enter to start

        # CLI args — works for CITADEL/BRIDGEWATER/JUMP/DE SHAW/RENAISSANCE
        cli = []
        try:
            _days = int(str(app._cfg_period).strip()) if str(app._cfg_period).strip() else 0
            if _days >= 7:
                cli += ["--days", str(_days)]
        except (ValueError, TypeError):
            pass
        _basket = str(app._cfg_basket or "").strip()
        # _cfg_basket may be a numeric index ("1","2"...) or basket name
        if _basket and not _basket.isdigit():
            cli += ["--basket", _basket]
        elif _basket.isdigit():
            # Resolve index → basket name
            from config.params import BASKETS
            _bnames = [k for k in BASKETS if k != "custom"]
            _idx = int(_basket) - 1
            if 0 <= _idx < len(_bnames):
                cli += ["--basket", _bnames[_idx]]
        try:
            _lev = float(str(app._cfg_leverage).replace("x", "").strip()) if str(app._cfg_leverage).strip() else 0
            if 0.1 <= _lev <= 125:
                cli += ["--leverage", str(_lev)]
        except (ValueError, TypeError):
            pass
        cli += app._engine_extra_cli_flags(name)
        cli += ["--no-menu"]
        app._exec(name, script, desc, parent_menu, inputs, cli_args=cli)

    run_btn = tk.Label(btn_f, text="  RODAR BACKTEST  ", font=(FONT, 11, "bold"),
                       fg=BG, bg=AMBER, cursor="hand2", padx=16, pady=5)
    run_btn.pack(side="left", padx=4)
    run_btn.bind("<Button-1>", lambda e: do_run())
    app._kb("<Return>", do_run)

    back_btn = tk.Label(btn_f, text="  VOLTAR  ", font=(FONT, 10), fg=DIM, bg=BG3,
                        cursor="hand2", padx=12, pady=5)
    back_btn.pack(side="left", padx=4)
    back_btn.bind("<Button-1>", lambda e: app._brief(name, script, desc, parent_menu))
    app._kb("<Escape>", lambda: app._brief(name, script, desc, parent_menu))
