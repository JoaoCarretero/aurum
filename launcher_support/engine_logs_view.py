from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from core.ui.ui_palette import AMBER, AMBER_B, AMBER_D, BG, BG3, DIM, DIM2, FONT, GREEN, RED, WHITE

ROOT = Path(__file__).resolve().parents[1]


def render_screen(app, host: tk.Misc, *, on_escape) -> None:
    for child in host.winfo_children():
        try:
            child.destroy()
        except Exception:
            pass

    app.h_path.configure(text="> DATA > ENGINES")
    app.h_stat.configure(text="LIVE", fg=GREEN)
    app.f_lbl.configure(text="ESC voltar  |  click proc to tail  |  STOP / PURGE")
    app._kb("<Escape>", lambda: on_escape())

    app._eng_selected_pid = None
    app._eng_tail_stop = threading.Event()
    app._eng_tail_thread = None
    app._eng_log_queue = queue.Queue()
    app._eng_after_id = None
    app._eng_log_poll_after_id = None
    app._eng_selected_key = None
    app._eng_mode_filter = getattr(app, "_eng_mode_filter", "all")
    app._eng_filter_tabs = {}
    app._eng_historical_cache = None
    app._eng_historical_cache_ts = 0.0

    outer = tk.Frame(host, bg=BG)
    outer.pack(fill="both", expand=True, padx=28, pady=18)

    head = tk.Frame(outer, bg=BG)
    head.pack(fill="x", pady=(0, 12))
    strip = tk.Frame(head, bg=BG)
    strip.pack(fill="x")
    tk.Frame(strip, bg=AMBER, width=4, height=28).pack(side="left", padx=(0, 8))
    title_wrap = tk.Frame(strip, bg=BG)
    title_wrap.pack(side="left", fill="x", expand=True)
    tk.Label(title_wrap, text="ENGINE LOGS", font=(FONT, 14, "bold"), fg=AMBER, bg=BG, anchor="w").pack(anchor="w")
    tk.Label(
        title_wrap,
        text="Running and recent engines with live log tail and verified stop control",
        font=(FONT, 8),
        fg=DIM,
        bg=BG,
        anchor="w",
    ).pack(anchor="w", pady=(3, 0))
    tk.Frame(outer, bg=DIM2, height=1).pack(fill="x", pady=(0, 12))

    split = tk.Frame(outer, bg=BG)
    split.pack(fill="both", expand=True)

    left = tk.Frame(split, bg=BG, width=420, highlightbackground=DIM2, highlightthickness=1)
    left.pack(side="left", fill="y", padx=(0, 8))
    left.pack_propagate(False)

    tk.Label(left, text="PROCS", font=(FONT, 7, "bold"), fg=AMBER_D, bg=BG, anchor="w").pack(anchor="w", pady=(0, 4))
    hrow = tk.Frame(left, bg=BG)
    hrow.pack(fill="x")
    for label, width in [("STATE", 6), ("ENGINE", 9), ("MODE", 6), ("SRC", 5), ("STARTED", 12), ("UP", 6), ("SIG", 4)]:
        tk.Label(hrow, text=label, font=(FONT, 7, "bold"), fg=DIM, bg=BG, width=width, anchor="w").pack(side="left")
    tk.Frame(left, bg=DIM2, height=1).pack(fill="x", pady=(1, 2))

    filter_row = tk.Frame(left, bg=BG)
    filter_row.pack(fill="x", pady=(2, 6))
    tk.Label(filter_row, text="FILTER", font=(FONT, 6, "bold"), fg=DIM2, bg=BG).pack(side="left", padx=(0, 8))
    for idx, (tab_label, filter_name) in enumerate(
        [("ALL", "all"), ("SHADOW", "shadow"), ("PAPER", "paper"), ("DEMO", "demo"), ("TESTNET", "testnet"), ("LIVE", "live")],
        start=1,
    ):
        tab = tk.Label(
            filter_row,
            text=f" {idx}:{tab_label} ",
            font=(FONT, 6, "bold"),
            fg=AMBER_D if app._eng_mode_filter == filter_name else DIM,
            bg=BG3 if app._eng_mode_filter == filter_name else BG,
            cursor="hand2",
            padx=5,
            pady=2,
        )
        tab.pack(side="left", padx=(0, 3))
        tab.bind("<Button-1>", lambda _e, f=filter_name: app._eng_set_mode_filter(f))
        app._eng_filter_tabs[filter_name] = tab
        app._kb(f"<Key-{idx}>", lambda f=filter_name: app._eng_set_mode_filter(f))

    list_wrap = tk.Frame(left, bg=BG)
    list_wrap.pack(fill="both", expand=True)
    app._eng_list_wrap = list_wrap

    actions_l = tk.Frame(left, bg=BG)
    actions_l.pack(fill="x", pady=(6, 0))

    def _do_stop():
        pid = app._eng_selected_pid
        if pid is None:
            app.h_stat.configure(text="NO PROC SELECTED", fg=RED)
            app.after(1200, lambda: app.h_stat.configure(text="LIVE", fg=GREEN))
            return
        try:
            from core.ops.proc import PidRecycledError, stop_proc

            ok = stop_proc(pid)
            msg = f"STOPPED {pid}" if ok else f"{pid} NOT RUNNING"
            app.h_stat.configure(text=msg, fg=GREEN if ok else AMBER_D)
        except PidRecycledError as exc:
            app.h_stat.configure(text="REFUSED: PID REUSE", fg=RED)
            messagebox.showerror("PID recycling detected", f"stop_proc refused:\n\n{exc}")
        app.after(1500, lambda: app.h_stat.configure(text="LIVE", fg=GREEN))
        app._eng_refresh()

    def _do_purge():
        try:
            from core.ops.proc import purge_finished

            n = purge_finished()
            app.h_stat.configure(text=f"PURGED {n}", fg=AMBER)
        except Exception as exc:
            app.h_stat.configure(text=f"PURGE FAILED: {str(exc)[:30]}", fg=RED)
        app.after(1500, lambda: app.h_stat.configure(text="LIVE", fg=GREEN))
        app._eng_refresh()

    def _do_spawn(engine_name: str):
        try:
            from core.ops.proc import spawn

            info = spawn(engine_name)
        except Exception as exc:
            app.h_stat.configure(text=f"SPAWN ERR: {str(exc)[:30]}", fg=RED)
            info = None
        if info:
            app.h_stat.configure(text=f"SPAWNED {engine_name} pid={info['pid']}", fg=GREEN)
            app.after(300, lambda p=info: app._eng_select(p))
        else:
            app.h_stat.configure(text=f"SPAWN FAILED: {engine_name}", fg=RED)
        app.after(2000, lambda: app.h_stat.configure(text="LIVE", fg=GREEN))
        app._eng_refresh()

    try:
        from core.ops.proc import ENGINES as _ENGINES
    except Exception:
        _ENGINES = {}
    try:
        from config.params import FROZEN_ENGINES as _FROZEN
    except Exception:
        _FROZEN = []

    spawn_menu = tk.Menu(actions_l, tearoff=0, bg=BG3, fg=AMBER, activebackground=AMBER, activeforeground=BG, font=(FONT, 8))
    for eng_name in sorted(_ENGINES.keys()):
        frozen = eng_name.upper() in [f.upper() for f in _FROZEN]
        label = f"{eng_name.upper()} [FROZEN]" if frozen else eng_name.upper()
        fg = DIM if frozen else AMBER
        spawn_menu.add_command(label=label, foreground=fg, command=lambda n=eng_name: _do_spawn(n))

    def _popup_spawn(event, menu=spawn_menu):
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    spawn_btn = tk.Label(actions_l, text="  SPAWN >  ", font=(FONT, 7, "bold"), fg=GREEN, bg=BG3, cursor="hand2", padx=6, pady=3)
    spawn_btn.pack(side="left", padx=(0, 6))
    spawn_btn.bind("<Button-1>", _popup_spawn)
    spawn_btn.bind("<Enter>", lambda _e: spawn_btn.configure(bg=GREEN, fg=BG))
    spawn_btn.bind("<Leave>", lambda _e: spawn_btn.configure(bg=BG3, fg=GREEN))

    for label, cmd, color in [("STOP", _do_stop, RED), ("PURGE", _do_purge, AMBER_D), ("REFRESH", lambda: app._eng_refresh(), AMBER)]:
        btn = tk.Label(actions_l, text=f"  {label}  ", font=(FONT, 7, "bold"), fg=color, bg=BG3, cursor="hand2", padx=6, pady=3)
        btn.pack(side="left", padx=2)
        btn.bind("<Button-1>", lambda _e, c=cmd: c())

    right = tk.Frame(split, bg=BG3, highlightbackground=DIM2, highlightthickness=1)
    right.pack(side="right", fill="both", expand=True)

    log_section = tk.Frame(right, bg=BG3)
    log_section.pack(fill="both", expand=True, padx=8, pady=(8, 0))
    tk.Label(log_section, text="LOG TAIL", font=(FONT, 7, "bold"), fg=AMBER_D, bg=BG3, anchor="w").pack(anchor="nw")
    tk.Frame(log_section, bg=DIM2, height=1).pack(fill="x", pady=(1, 4))
    app._eng_log_header = tk.Label(log_section, text=" -- select a proc to stream its log -- ", font=(FONT, 7), fg=DIM, bg=BG3, anchor="w")
    app._eng_log_header.pack(fill="x")
    app._eng_log_text = tk.Text(log_section, wrap="word", bg=BG, fg=WHITE, font=(FONT, 8), insertbackground=WHITE, padx=6, pady=6, borderwidth=0, highlightthickness=0, height=14)
    app._eng_log_text.pack(fill="both", expand=True, pady=(2, 4))
    app._eng_log_text.config(state="disabled")

    tk.Frame(right, bg=DIM2, height=1).pack(fill="x", padx=8, pady=(2, 0))
    entries_section = tk.Frame(right, bg=BG3)
    entries_section.pack(fill="both", expand=False, padx=8, pady=(4, 8))
    header_row = tk.Frame(entries_section, bg=BG3)
    header_row.pack(fill="x")
    app._eng_entries_header = tk.Label(header_row, text="ENTRIES", font=(FONT, 7, "bold"), fg=AMBER_D, bg=BG3, anchor="w")
    app._eng_entries_header.pack(side="left")
    app._eng_entries_status = tk.Label(header_row, text="", font=(FONT, 7), fg=DIM, bg=BG3, anchor="e")
    app._eng_entries_status.pack(side="right")
    tk.Frame(entries_section, bg=DIM2, height=1).pack(fill="x", pady=(1, 4))
    app._eng_entries_text = tk.Text(entries_section, wrap="none", bg=BG, fg=WHITE, font=(FONT, 7), padx=6, pady=4, borderwidth=0, highlightthickness=0, height=10)
    app._eng_entries_text.pack(fill="both", expand=True)
    app._eng_entries_text.config(state="disabled")

    app._eng_entries_stop = threading.Event()
    app._eng_entries_thread = None

    app._eng_refresh()
    app._eng_poll_logs()


def cleanup(app) -> None:
    try:
        if getattr(app, "_eng_after_id", None):
            app.after_cancel(app._eng_after_id)
    except Exception:
        pass
    app._eng_after_id = None
    try:
        if getattr(app, "_eng_log_poll_after_id", None):
            app.after_cancel(app._eng_log_poll_after_id)
    except Exception:
        pass
    app._eng_log_poll_after_id = None
    try:
        if getattr(app, "_eng_tail_thread", None) is not None:
            app._eng_tail_stop.set()
            app._eng_tail_thread = None
    except Exception:
        pass
    try:
        if getattr(app, "_eng_entries_thread", None) is not None:
            app._eng_entries_stop.set()
            app._eng_entries_thread = None
    except Exception:
        pass


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
        tk.Label(app._eng_list_wrap, text=f"  {error_text}", font=(FONT, 7), fg=RED, bg=BG, anchor="w").pack(fill="x")

    refresh_filter_tabs(app)
    filt_label = app._eng_mode_filter.upper() if app._eng_mode_filter != "all" else "ALL ENGINES"

    tk.Label(
        app._eng_list_wrap,
        text=f"  *  RUNNING  |  {filt_label}  ({len(running)})",
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
            text="   -- nenhum engine ativo no filtro selecionado --",
            font=(FONT, 7, "italic"),
            fg=DIM2,
            bg=BG,
            anchor="w",
        ).pack(fill="x", pady=2)

    tk.Frame(app._eng_list_wrap, bg=DIM2, height=1).pack(fill="x", pady=(6, 4), padx=8)
    tk.Label(
        app._eng_list_wrap,
        text=f"  o  STOPPED (ultimas 72h)  |  {filt_label}  ({len(stopped)})",
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
            text="   -- sem runs recentes no filtro selecionado --",
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
            tab.configure(fg=AMBER_D if active else DIM, bg=BG3 if active else BG)
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
    state = "*LIVE" if alive else "odone"
    state_color = GREEN if alive else DIM
    hb = proc.get("_heartbeat") or {}
    up_text = app._eng_uptime_of(proc, hb)
    sig_n = hb.get("novel_since_prime")
    if sig_n is None:
        sig_n = hb.get("novel_total")
    sig_text = "--" if sig_n is None else str(sig_n)

    row = tk.Frame(app._eng_list_wrap, bg=BG, cursor="hand2")
    row.pack(fill="x", pady=0)

    cells = [
        (state, 6, state_color, "bold"),
        (engine, 9, WHITE, "bold"),
        (mode, 6, AMBER, "normal"),
        (src, 5, GREEN if src == "VPS" else DIM2, "normal"),
        (started, 12, DIM, "normal"),
        (up_text, 6, WHITE, "normal"),
        (sig_text, 4, AMBER_B if (sig_n or 0) > 0 else DIM2, "bold"),
    ]
    labels = []
    for text, width, color, weight in cells:
        lbl = tk.Label(row, text=text, font=(FONT, 7, weight), fg=color, bg=BG, width=width, anchor="w")
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


def select_proc(app, proc: dict) -> None:
    from core.ops import run_catalog

    app._eng_selected_pid = proc.get("pid")
    app._eng_selected_key = app._eng_row_key(proc)

    if app._eng_tail_thread is not None:
        app._eng_tail_stop.set()
        app._eng_tail_thread = None
    app._eng_tail_stop = threading.Event()

    if getattr(app, "_eng_entries_thread", None) is not None:
        app._eng_entries_stop.set()
        app._eng_entries_thread = None
    app._eng_entries_stop = threading.Event()
    load_entries(app, proc)

    try:
        app._eng_log_text.config(state="normal")
        app._eng_log_text.delete("1.0", "end")
        app._eng_log_text.config(state="disabled")
    except tk.TclError:
        return

    log_file = proc.get("log_file") or proc.get("log") or ""
    app._eng_log_header.configure(text=run_catalog.engine_log_header(proc), fg=AMBER_D)

    if not log_file:
        try:
            app._eng_log_text.config(state="normal")
            app._eng_log_text.insert("end", "(no log file available for this run)\n")
            app._eng_log_text.config(state="disabled")
        except tk.TclError:
            pass
        return

    if proc.get("_remote") or str(log_file).startswith("remote:"):
        run_id = proc.get("_run_id") or str(log_file).split(":", 1)[-1]
        t = threading.Thread(target=tail_remote_worker, args=(app, run_id, app._eng_tail_stop), daemon=True)
    else:
        log_path = ROOT / log_file if not Path(log_file).is_absolute() else Path(log_file)
        t = threading.Thread(target=tail_worker, args=(app, log_path, app._eng_tail_stop), daemon=True)
    t.start()
    app._eng_tail_thread = t
    app._eng_refresh()


def load_entries(app, proc: dict) -> None:
    try:
        app._eng_entries_text.config(state="normal")
        app._eng_entries_text.delete("1.0", "end")
        app._eng_entries_text.config(state="disabled")
    except tk.TclError:
        return

    engine = proc.get("engine", "?")
    rid = app._eng_run_id_of(proc) or "?"
    try:
        app._eng_entries_header.configure(text=f"ENTRIES  |  {engine}  |  {rid}")
        app._eng_entries_status.configure(text="loading...", fg=DIM)
    except tk.TclError:
        pass

    def worker(p=proc, stop=app._eng_entries_stop):
        lines, summary = app._eng_fetch_entries(p, stop)
        if stop.is_set():
            return
        app.after(0, lambda: apply_entries(app, lines, summary))

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    app._eng_entries_thread = t


def apply_entries(app, lines: list[str], summary: str) -> None:
    try:
        app._eng_entries_text.config(state="normal")
        app._eng_entries_text.delete("1.0", "end")
        if lines:
            app._eng_entries_text.insert("end", "\n".join(lines) + "\n")
        else:
            app._eng_entries_text.insert("end", f"   -- {summary} --\n")
        app._eng_entries_text.config(state="disabled")
        app._eng_entries_status.configure(text=summary, fg=AMBER_D if lines else DIM2)
    except tk.TclError:
        pass


def tail_remote_worker(app, run_id: str, stop_event: threading.Event) -> None:
    try:
        from launcher_support.engines_live_view import _get_cockpit_client
        from core.ops import run_catalog

        client = _get_cockpit_client()
    except Exception as exc:
        app._eng_log_queue.put(("SYSTEM", f"(cockpit client unavailable: {exc})"))
        return

    seen_last: str | None = None
    while not stop_event.is_set():
        lines, error = run_catalog.fetch_remote_log_tail(client, run_id, tail=500)
        if error:
            app._eng_log_queue.put(("SYSTEM", error))
            if stop_event.wait(5.0):
                return
            continue
        if lines:
            if seen_last is not None and seen_last in lines:
                idx = len(lines) - 1 - lines[::-1].index(seen_last)
                lines = lines[idx + 1 :]
            for ln in lines:
                app._eng_log_queue.put(("LINE", ln))
            if lines:
                seen_last = lines[-1]
        if stop_event.wait(2.0):
            return


def tail_worker(app, log_path: Path, stop_event: threading.Event) -> None:
    from core.ops import run_catalog

    seed_lines, error = run_catalog.read_log_seed_lines(log_path, limit=500)
    if error:
        app._eng_log_queue.put(("SYSTEM", error))
        return
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in seed_lines:
                app._eng_log_queue.put(("LINE", line))
            fh.seek(0, 2)
            while not stop_event.is_set():
                line = fh.readline()
                if not line:
                    if stop_event.wait(0.25):
                        break
                    continue
                app._eng_log_queue.put(("LINE", line.rstrip("\n")))
    except OSError as exc:
        app._eng_log_queue.put(("SYSTEM", f"(log read error: {exc})"))


def poll_logs(app) -> None:
    try:
        if not hasattr(app, "_eng_log_text"):
            return
        if not app._eng_log_text.winfo_exists():
            return
    except Exception:
        return

    drained = 0
    max_drain = 200
    new_lines: list[str] = []
    try:
        while drained < max_drain:
            _kind, line = app._eng_log_queue.get_nowait()
            new_lines.append(line)
            drained += 1
    except queue.Empty:
        pass

    if new_lines:
        try:
            app._eng_log_text.config(state="normal")
            app._eng_log_text.insert("end", "\n".join(new_lines) + "\n")
            total_lines = int(app._eng_log_text.index("end-1c").split(".")[0])
            if total_lines > 1000:
                app._eng_log_text.delete("1.0", f"{total_lines - 1000}.0")
            app._eng_log_text.see("end")
            app._eng_log_text.config(state="disabled")
        except tk.TclError:
            return

    try:
        app._eng_log_poll_after_id = app.after(200, app._eng_poll_logs)
    except Exception:
        pass
