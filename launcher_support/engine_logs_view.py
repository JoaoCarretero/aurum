from __future__ import annotations

import tkinter as tk

from core.ui.ui_palette import AMBER, AMBER_B, AMBER_D, BG, BG3, DIM, DIM2, FONT, GREEN, RED, WHITE


def refresh_list(app) -> None:
    if not hasattr(app, "_eng_list_wrap"):
        return
    try:
        if not app._eng_list_wrap.winfo_exists():
            return
    except Exception:
        return

    for child in app._eng_list_wrap.winfo_children():
        try:
            child.destroy()
        except Exception:
            pass

    try:
        from launcher_support.engines_live_view import _get_cockpit_client
        from core.ops import run_catalog

        client = _get_cockpit_client()
    except Exception:
        client = None
        run_catalog = None

    if run_catalog is None:
        running, stopped, error_text = [], [], "run catalog unavailable"
    else:
        running, stopped, error_text = run_catalog.list_engine_log_sections(
            client=client,
            mode_filter=app._eng_mode_filter,
            vps_limit=20,
            historical_limit=30,
            historical_hours=72,
        )

    if error_text:
        tk.Label(
            app._eng_list_wrap,
            text=f"  {error_text}",
            font=(FONT, 7),
            fg=RED,
            bg=BG,
            anchor="w",
        ).pack(fill="x")

    refresh_filter_tabs(app)
    filt_label = app._eng_mode_filter.upper() if app._eng_mode_filter != "all" else "ALL ENGINES"

    tk.Label(
        app._eng_list_wrap,
        text=f"  ●  RUNNING  ·  {filt_label}  ({len(running)})",
        font=(FONT, 7, "bold"),
        fg=GREEN,
        bg=BG,
        anchor="w",
    ).pack(fill="x", pady=(2, 2))
    if running:
        for row in running:
            render_row(app, row)
    else:
        tk.Label(
            app._eng_list_wrap,
            text="   — nenhum engine ativo no filtro selecionado —",
            font=(FONT, 7, "italic"),
            fg=DIM2,
            bg=BG,
            anchor="w",
        ).pack(fill="x", pady=2)

    tk.Frame(app._eng_list_wrap, bg=DIM2, height=1).pack(fill="x", pady=(6, 4), padx=8)
    tk.Label(
        app._eng_list_wrap,
        text=f"  ○  STOPPED (últimas 72h)  ·  {filt_label}  ({len(stopped)})",
        font=(FONT, 7, "bold"),
        fg=DIM,
        bg=BG,
        anchor="w",
    ).pack(fill="x", pady=(2, 2))
    if stopped:
        for row in stopped[:30]:
            render_row(app, row)
    else:
        tk.Label(
            app._eng_list_wrap,
            text="   — sem runs recentes no filtro selecionado —",
            font=(FONT, 7, "italic"),
            fg=DIM2,
            bg=BG,
            anchor="w",
        ).pack(fill="x", pady=2)

    try:
        if getattr(app, "_eng_after_id", None):
            app.after_cancel(app._eng_after_id)
    except Exception:
        pass
    try:
        app._eng_after_id = app.after(2000, app._eng_refresh)
    except Exception:
        pass


def refresh_filter_tabs(app) -> None:
    for filter_name, tab in getattr(app, "_eng_filter_tabs", {}).items():
        active = filter_name == getattr(app, "_eng_mode_filter", "all")
        try:
            tab.configure(
                fg=AMBER_D if active else DIM,
                bg=BG3 if active else BG,
            )
        except Exception:
            pass


def render_row(app, proc: dict) -> None:
    alive = bool(proc.get("alive"))
    row_key = app._eng_row_key(proc)
    engine_full = str(proc.get("engine", "?"))
    if "(" in engine_full and engine_full.endswith(")"):
        base, mode = engine_full.split("(", 1)
        engine = base.strip()[:9]
        mode = mode.rstrip(")").strip()[:6]
    else:
        engine = engine_full[:9]
        mode = str(proc.get("mode") or "live")[:6]
    started = str(proc.get("started", "") or "")[:16].replace("T", " ")
    src = "VPS" if proc.get("_remote") else "local"
    state = "●LIVE" if alive else "○done"
    state_color = GREEN if alive else DIM
    hb = proc.get("_heartbeat") or {}
    up_text = app._eng_uptime_of(proc, hb)
    sig_n = hb.get("novel_since_prime")
    if sig_n is None:
        sig_n = hb.get("novel_total")
    sig_text = "—" if sig_n is None else str(sig_n)

    row = tk.Frame(app._eng_list_wrap, bg=BG, cursor="hand2")
    row.pack(fill="x", pady=0)

    cells = [
        (state, 6, state_color, "bold"),
        (engine, 9, WHITE, "bold"),
        (mode, 6, AMBER, "normal"),
        (src, 5, (GREEN if src == "VPS" else DIM2), "normal"),
        (started, 12, DIM, "normal"),
        (up_text, 6, WHITE, "normal"),
        (sig_text, 4, AMBER_B if (sig_n or 0) > 0 else DIM2, "bold"),
    ]
    labels = []
    for text, width, color, weight in cells:
        lbl = tk.Label(
            row,
            text=text,
            font=(FONT, 7, weight),
            fg=color,
            bg=BG,
            width=width,
            anchor="w",
        )
        lbl.pack(side="left")
        labels.append(lbl)

    def _select(_e=None, p=proc):
        app._eng_select(p)

    def _hover_on(_e=None, refs=labels):
        for lbl in refs:
            try:
                lbl.configure(bg=BG3)
            except Exception:
                pass

    def _hover_off(_e=None, refs=labels, p=proc):
        bg = BG3 if app._eng_selected_key == app._eng_row_key(p) else BG
        for lbl in refs:
            try:
                lbl.configure(bg=bg)
            except Exception:
                pass

    for widget in (row, *labels):
        widget.bind("<Button-1>", _select)
        widget.bind("<Enter>", _hover_on)
        widget.bind("<Leave>", _hover_off)

    if app._eng_selected_key == row_key:
        for lbl in labels:
            try:
                lbl.configure(bg=BG3)
            except Exception:
                pass
