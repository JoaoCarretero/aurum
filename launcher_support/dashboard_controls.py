from __future__ import annotations


def dash_paper_edit_dialog(app, *, tk_mod, colors: dict[str, str], font_name: str, root_path) -> None:
    """Modal-ish dialog to edit the persistent paper account state."""
    from core.ui.portfolio_monitor import PortfolioMonitor

    state = PortfolioMonitor.paper_state_load()
    current = float(state.get("current_balance", 0) or 0)
    initial = float(state.get("initial_balance", 0) or 0)

    dlg = tk_mod.Toplevel(app)
    dlg.title("Edit Paper Account")
    dlg.configure(bg=colors["BG"])
    dlg.transient(app)
    dlg.grab_set()
    dlg.resizable(False, False)

    try:
        app.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() // 2) - 220
        y = app.winfo_rooty() + (app.winfo_height() // 2) - 180
        dlg.geometry(f"440x360+{max(x, 0)}+{max(y, 0)}")
    except Exception:
        dlg.geometry("440x360")

    try:
        ico = root_path / "server" / "logo" / "aurum.ico"
        if ico.exists():
            dlg.iconbitmap(str(ico))
    except Exception:
        pass

    tk_mod.Label(
        dlg, text=" EDIT PAPER ACCOUNT ",
        font=(font_name, 9, "bold"), fg=colors["BG"], bg=colors["AMBER"],
        padx=10, pady=6,
    ).pack(fill="x", padx=16, pady=(16, 0))
    tk_mod.Frame(dlg, bg=colors["AMBER_D"], height=1).pack(fill="x", padx=16)

    info = tk_mod.Frame(dlg, bg=colors["BG"])
    info.pack(fill="x", padx=16, pady=(10, 6))
    tk_mod.Label(
        info, text=f"Current balance:  ${current:,.2f}",
        font=(font_name, 9), fg=colors["WHITE"], bg=colors["BG"], anchor="w",
    ).pack(fill="x")
    tk_mod.Label(
        info, text=f"Initial balance:  ${initial:,.2f}",
        font=(font_name, 8), fg=colors["DIM"], bg=colors["BG"], anchor="w",
    ).pack(fill="x")
    tk_mod.Label(
        info,
        text=f"Deposits: ${state.get('total_deposits', 0):,.2f}  ·  Withdraws: ${state.get('total_withdraws', 0):,.2f}",
        font=(font_name, 8), fg=colors["DIM"], bg=colors["BG"], anchor="w",
    ).pack(fill="x")
    tk_mod.Label(
        info,
        text=f"Realized PnL: ${state.get('realized_pnl', 0):,.2f}  ·  Trades: {len(state.get('trades') or [])}",
        font=(font_name, 8), fg=colors["DIM"], bg=colors["BG"], anchor="w",
    ).pack(fill="x")

    tk_mod.Frame(dlg, bg=colors["DIM2"], height=1).pack(fill="x", padx=16, pady=(8, 6))

    form = tk_mod.Frame(dlg, bg=colors["BG"])
    form.pack(fill="x", padx=16, pady=(2, 4))
    tk_mod.Label(
        form, text="New balance  $", font=(font_name, 9),
        fg=colors["AMBER"], bg=colors["BG"],
    ).pack(side="left")
    entry = tk_mod.Entry(
        form, font=(font_name, 10, "bold"), fg=colors["WHITE"],
        bg=colors["BG3"], insertbackground=colors["AMBER"],
        bd=0, relief="flat", width=14,
    )
    entry.pack(side="left", padx=(4, 0), ipady=4)
    entry.insert(0, f"{current:.2f}")
    entry.select_range(0, "end")
    entry.focus_set()

    note_f = tk_mod.Frame(dlg, bg=colors["BG"])
    note_f.pack(fill="x", padx=16, pady=(2, 8))
    tk_mod.Label(
        note_f, text="Note         ", font=(font_name, 8),
        fg=colors["DIM"], bg=colors["BG"],
    ).pack(side="left")
    note_entry = tk_mod.Entry(
        note_f, font=(font_name, 8), fg=colors["WHITE"],
        bg=colors["BG3"], insertbackground=colors["AMBER"],
        bd=0, relief="flat",
    )
    note_entry.pack(side="left", fill="x", expand=True, ipady=3)
    note_entry.insert(0, "manual adjust")

    status_l = tk_mod.Label(
        dlg, text="", font=(font_name, 7),
        fg=colors["DIM"], bg=colors["BG"], anchor="w",
    )
    status_l.pack(fill="x", padx=16, pady=(0, 6))

    def _invalidate_paper_cache():
        pm = app._get_portfolio_monitor()
        try:
            with pm._lock:
                pm._cache.pop("paper", None)
        except Exception:
            pass

    def _apply():
        raw = entry.get().strip().replace(",", "").replace("$", "")
        try:
            val = float(raw)
        except ValueError:
            status_l.configure(text="✗ invalid amount", fg=colors["RED"])
            return
        if val < 0:
            status_l.configure(text="✗ balance cannot be negative", fg=colors["RED"])
            return
        note = note_entry.get().strip() or "manual adjust"
        PortfolioMonitor.paper_set_balance(val, note=note)
        _invalidate_paper_cache()
        delta = val - current
        status_l.configure(
            text=f"✓ saved  ·  {'+' if delta >= 0 else ''}${delta:,.2f}  →  ${val:,.2f}",
            fg=colors["GREEN"],
        )
        app.after(500, dlg.destroy)
        app.after(550, app._dash_force_refresh)

    def _reset():
        PortfolioMonitor.paper_reset()
        _invalidate_paper_cache()
        status_l.configure(text="✓ reset to default $10,000", fg=colors["GREEN"])
        app.after(500, dlg.destroy)
        app.after(550, app._dash_force_refresh)

    btns = tk_mod.Frame(dlg, bg=colors["BG"])
    btns.pack(fill="x", padx=16, pady=(6, 14))

    def _mkbtn(parent, label, color, cmd):
        btn = tk_mod.Label(
            parent, text=f"  {label}  ", font=(font_name, 8, "bold"),
            fg=colors["BG"], bg=color, cursor="hand2", padx=8, pady=5,
        )
        btn.bind("<Button-1>", lambda e: cmd())
        btn.bind("<Enter>", lambda e: btn.configure(bg=colors["AMBER_B"]))
        btn.bind("<Leave>", lambda e: btn.configure(bg=color))
        return btn

    _mkbtn(btns, "APPLY", colors["GREEN"], _apply).pack(side="left", padx=(0, 6))
    _mkbtn(btns, "RESET", colors["RED"], _reset).pack(side="left", padx=6)
    _mkbtn(btns, "CANCEL", colors["DIM2"], dlg.destroy).pack(side="right")

    quick = tk_mod.Frame(dlg, bg=colors["BG"])
    quick.pack(fill="x", padx=16, pady=(0, 10))
    tk_mod.Label(
        quick, text="Quick:", font=(font_name, 7),
        fg=colors["DIM"], bg=colors["BG"],
    ).pack(side="left", padx=(0, 6))
    for label, amt in [("+$1K", 1000), ("+$5K", 5000), ("-$1K", -1000), ("-$5K", -5000)]:
        def _q(_e=None, a=amt):
            new = max(0, current + a)
            entry.delete(0, "end")
            entry.insert(0, f"{new:.2f}")
            note_entry.delete(0, "end")
            note_entry.insert(0, f"quick {'+' if a >= 0 else ''}${a}")

        qb = tk_mod.Label(
            quick, text=f" {label} ", font=(font_name, 7, "bold"),
            fg=colors["AMBER"], bg=colors["BG3"], cursor="hand2", padx=5, pady=2,
        )
        qb.pack(side="left", padx=2)
        qb.bind("<Button-1>", _q)

    dlg.bind("<Return>", lambda e: _apply())
    dlg.bind("<Escape>", lambda e: dlg.destroy())


def dash_exit_to_markets(app) -> None:
    app._dash_alive = False
    app._dash_cockpit_kill_stream()
    aid = getattr(app, "_dash_after_id", None)
    if aid:
        try:
            app.after_cancel(aid)
        except Exception:
            pass
    app._dash_after_id = None
    app._markets()
