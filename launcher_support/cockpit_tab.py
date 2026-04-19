from __future__ import annotations

import json
import subprocess
import threading
from datetime import datetime

import tkinter as tk


def build_tab(
    app,
    parent,
    *,
    tk_mod,
    colors: dict[str, str],
    font_name: str,
    vps_host,
    vps_project,
) -> None:
    """Render the VPS cockpit tab into the given parent container."""
    wrap = tk_mod.Frame(parent, bg=colors["BG"])
    wrap.pack(fill="both", expand=True, padx=14, pady=10)

    hdr = tk_mod.Frame(wrap, bg=colors["BG"])
    hdr.pack(fill="x", pady=(0, 6))
    tk_mod.Label(
        hdr,
        text="VPS REMOTE COCKPIT",
        font=(font_name, 9, "bold"),
        fg=colors["AMBER"],
        bg=colors["BG"],
    ).pack(side="left")
    reach_l = tk_mod.Label(
        hdr,
        text="○ checking VPS...",
        font=(font_name, 8),
        fg=colors["DIM"],
        bg=colors["BG"],
    )
    reach_l.pack(side="right")
    app._dash_widgets[("cp_reach",)] = reach_l
    tk_mod.Frame(wrap, bg=colors["DIM2"], height=1).pack(fill="x", pady=(0, 8))

    row1 = tk_mod.Frame(wrap, bg=colors["BG"])
    row1.pack(fill="x", pady=(0, 8))

    vps_box = tk_mod.Frame(
        row1,
        bg=colors["PANEL"],
        highlightbackground=colors["BORDER"],
        highlightthickness=1,
    )
    vps_box.pack(side="left", fill="both", expand=True, padx=(0, 6))
    tk_mod.Label(
        vps_box,
        text=" VPS ",
        font=(font_name, 7, "bold"),
        fg=colors["BG"],
        bg=colors["AMBER"],
    ).pack(side="top", anchor="nw", padx=8, pady=4)
    vps_inner = tk_mod.Frame(vps_box, bg=colors["PANEL"])
    vps_inner.pack(fill="x", padx=12, pady=(0, 10))
    tk_mod.Label(
        vps_inner,
        text=f"host:     {vps_host()}",
        font=(font_name, 8),
        fg=colors["WHITE"],
        bg=colors["PANEL"],
        anchor="w",
    ).pack(fill="x")
    tk_mod.Label(
        vps_inner,
        text=f"project:  {vps_project()}",
        font=(font_name, 8),
        fg=colors["WHITE"],
        bg=colors["PANEL"],
        anchor="w",
    ).pack(fill="x")
    vps_check_l = tk_mod.Label(
        vps_inner,
        text="last check: —",
        font=(font_name, 7),
        fg=colors["DIM2"],
        bg=colors["PANEL"],
        anchor="w",
    )
    vps_check_l.pack(fill="x", pady=(4, 0))
    app._dash_widgets[("cp_check",)] = vps_check_l

    eng_box = tk_mod.Frame(
        row1,
        bg=colors["PANEL"],
        highlightbackground=colors["BORDER"],
        highlightthickness=1,
    )
    eng_box.pack(side="left", fill="both", expand=True, padx=(6, 0))
    tk_mod.Label(
        eng_box,
        text=" ENGINE ",
        font=(font_name, 7, "bold"),
        fg=colors["BG"],
        bg=colors["AMBER"],
    ).pack(side="top", anchor="nw", padx=8, pady=4)
    eng_inner = tk_mod.Frame(eng_box, bg=colors["PANEL"])
    eng_inner.pack(fill="x", padx=12, pady=(0, 10))
    eng_state_l = tk_mod.Label(
        eng_inner,
        text="○ checking...",
        font=(font_name, 13, "bold"),
        fg=colors["DIM"],
        bg=colors["PANEL"],
        anchor="w",
    )
    eng_state_l.pack(anchor="w")
    eng_sub_l = tk_mod.Label(
        eng_inner,
        text="screen session: —",
        font=(font_name, 7),
        fg=colors["DIM"],
        bg=colors["PANEL"],
        anchor="w",
    )
    eng_sub_l.pack(anchor="w", pady=(2, 0))
    app._dash_widgets[("cp_engine_state",)] = eng_state_l
    app._dash_widgets[("cp_engine_sub",)] = eng_sub_l

    pos_box = tk_mod.Frame(
        wrap,
        bg=colors["PANEL"],
        highlightbackground=colors["BORDER"],
        highlightthickness=1,
    )
    pos_box.pack(fill="x", pady=(0, 8))
    pos_head = tk_mod.Label(
        pos_box,
        text=" OPEN POSITIONS (0) ",
        font=(font_name, 7, "bold"),
        fg=colors["BG"],
        bg=colors["AMBER"],
    )
    pos_head.pack(side="top", anchor="nw", padx=8, pady=4)
    pos_inner = tk_mod.Frame(pos_box, bg=colors["PANEL"])
    pos_inner.pack(fill="x", padx=12, pady=(0, 8))
    app._dash_widgets[("cp_pos_head",)] = pos_head
    app._dash_widgets[("cp_pos_inner",)] = pos_inner

    ctrl_box = tk_mod.Frame(
        wrap,
        bg=colors["PANEL"],
        highlightbackground=colors["BORDER"],
        highlightthickness=1,
    )
    ctrl_box.pack(fill="x", pady=(0, 8))
    tk_mod.Label(
        ctrl_box,
        text=" CONTROLS ",
        font=(font_name, 7, "bold"),
        fg=colors["BG"],
        bg=colors["AMBER"],
    ).pack(side="top", anchor="nw", padx=8, pady=4)
    ctrl_inner = tk_mod.Frame(ctrl_box, bg=colors["PANEL"])
    ctrl_inner.pack(fill="x", padx=12, pady=(0, 10))

    buttons = [
        ("START DEMO", colors["GREEN"], app._dash_cockpit_start_demo),
        ("START MLN", colors["AMBER_B"], app._dash_cockpit_start_millennium_bootstrap),
        ("STOP", colors["RED"], app._dash_cockpit_stop),
        ("DEPLOY", colors["AMBER"], app._dash_cockpit_deploy),
        ("STREAM LOGS", colors["AMBER_B"], app._dash_cockpit_toggle_stream),
    ]
    for label, color, cmd in buttons:
        btn = tk_mod.Label(
            ctrl_inner,
            text=f"  {label}  ",
            font=(font_name, 8, "bold"),
            fg=colors["BG"],
            bg=color,
            cursor="hand2",
            padx=8,
            pady=4,
        )
        btn.pack(side="left", padx=(0, 8))
        btn.bind("<Button-1>", lambda e, c=cmd: c())
        btn.bind(
            "<Enter>",
            lambda e, b=btn, c=color: b.configure(
                bg=colors["AMBER_B"] if c != colors["AMBER_B"] else "#FFFFFF"
            ),
        )
        btn.bind("<Leave>", lambda e, b=btn, c=color: b.configure(bg=c))
        if label == "STREAM LOGS":
            app._dash_widgets[("cp_stream_btn",)] = btn

    result_l = tk_mod.Label(
        ctrl_inner,
        text="",
        font=(font_name, 7),
        fg=colors["DIM"],
        bg=colors["PANEL"],
        anchor="w",
    )
    result_l.pack(side="left", padx=(10, 0))
    app._dash_widgets[("cp_action",)] = result_l

    log_box = tk_mod.Frame(
        wrap,
        bg=colors["PANEL"],
        highlightbackground=colors["BORDER"],
        highlightthickness=1,
    )
    log_box.pack(fill="both", expand=True, pady=(0, 0))
    log_head = tk_mod.Label(
        log_box,
        text=" LIVE LOG (polled every 5s) ",
        font=(font_name, 7, "bold"),
        fg=colors["BG"],
        bg=colors["AMBER"],
    )
    log_head.pack(side="top", anchor="nw", padx=8, pady=4)
    app._dash_widgets[("cp_log_head",)] = log_head

    log_frame = tk_mod.Frame(log_box, bg=colors["PANEL"])
    log_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))
    scroll = tk_mod.Scrollbar(log_frame, bg=colors["PANEL"])
    scroll.pack(side="right", fill="y")
    log_text = tk_mod.Text(
        log_frame,
        bg=colors["BG"],
        fg=colors["WHITE"],
        font=(font_name, 8),
        bd=0,
        highlightthickness=0,
        insertbackground=colors["AMBER"],
        wrap="none",
        yscrollcommand=scroll.set,
    )
    log_text.pack(side="left", fill="both", expand=True)
    scroll.configure(command=log_text.yview)
    log_text.insert("1.0", "— waiting for first log fetch —\n")
    log_text.configure(state="disabled")
    app._dash_widgets[("cp_log_text",)] = log_text

    app.f_lbl.configure(
        text=(
            "COCKPIT · VPS remote · "
            "1=Home 2=Market 3=Portfolio 4=Trades 5=Backtest 6=Cockpit"
        )
    )
    app.h_path.configure(text="> MARKETS > CRYPTO FUTURES > COCKPIT")


def fetch_async(
    app,
    *,
    vps_cmd,
    vps_project,
    vps_live_screen: str,
    vps_millennium_screen: str,
) -> None:
    """Single SSH round-trip for full status: screen, logs, positions."""
    if not getattr(app, "_dash_alive", False):
        return
    if getattr(app, "_dash_tab", "") != "cockpit":
        return

    project = vps_project()
    combined = (
        "echo '---SCREEN---'; screen -ls 2>&1 || true; "
        f"echo '---LOG---'; tail -5 {project}/data/live/*/logs/live.log "
        f"{project}/data/millennium_live/bootstrap.latest.log 2>/dev/null || true; "
        f"echo '---POS---'; cat {project}/data/live/*/state/positions.json 2>/dev/null || true; "
        "echo '---END---'"
    )

    def worker():
        import time as _time

        t0 = _time.time()
        out = vps_cmd(combined, timeout=8)
        lat_ms = int((_time.time() - t0) * 1000)

        snap = {
            "reachable": out is not None,
            "latency_ms": lat_ms,
            "screen_running": False,
            "screen_raw": "",
            "log_lines": [],
            "positions": [],
            "positions_raw": "",
            "ts": datetime.now().strftime("%H:%M:%S"),
        }

        if out:
            parts = {"SCREEN": "", "LOG": "", "POS": ""}
            current = None
            for line in out.splitlines():
                marker = line.strip()
                if marker == "---SCREEN---":
                    current = "SCREEN"
                    continue
                if marker == "---LOG---":
                    current = "LOG"
                    continue
                if marker == "---POS---":
                    current = "POS"
                    continue
                if marker == "---END---":
                    current = None
                    continue
                if current:
                    parts[current] += line + "\n"

            snap["screen_raw"] = parts["SCREEN"].strip()
            screen_raw = parts["SCREEN"]
            snap["screen_running"] = vps_live_screen in screen_raw
            snap["millennium_bootstrap_running"] = vps_millennium_screen in screen_raw
            snap["log_lines"] = [line for line in parts["LOG"].splitlines() if line.strip()]
            snap["positions_raw"] = parts["POS"].strip()
            try:
                if parts["POS"].strip():
                    pos_data = json.loads(parts["POS"])
                    if isinstance(pos_data, list):
                        snap["positions"] = pos_data
                    elif isinstance(pos_data, dict):
                        snap["positions"] = [
                            {"symbol": key, **(value if isinstance(value, dict) else {"value": value})}
                            for key, value in pos_data.items()
                        ]
            except (json.JSONDecodeError, TypeError):
                pass

        app._dash_cockpit_snap = snap
        if getattr(app, "_dash_alive", False):
            try:
                app.after(0, app._dash_cockpit_render)
            except Exception:
                pass

    threading.Thread(target=worker, daemon=True).start()


def render(
    app,
    *,
    tk_mod,
    colors: dict[str, str],
    font_name: str,
    vps_live_screen: str,
    vps_millennium_screen: str,
) -> None:
    if not getattr(app, "_dash_alive", False):
        return
    if getattr(app, "_dash_tab", "") != "cockpit":
        return

    snap = getattr(app, "_dash_cockpit_snap", {}) or {}

    reach_l = app._dash_widgets.get(("cp_reach",))
    if reach_l:
        if snap.get("reachable"):
            reach_l.configure(
                text=f"● reachable  ·  {snap.get('latency_ms', '?')}ms",
                fg=colors["GREEN"],
            )
            app.h_stat.configure(text="VPS OK", fg=colors["GREEN"])
        else:
            reach_l.configure(text="○ unreachable", fg=colors["RED"])
            app.h_stat.configure(text="VPS DOWN", fg=colors["RED"])

    check_l = app._dash_widgets.get(("cp_check",))
    if check_l:
        check_l.configure(text=f"last check: {snap.get('ts', '—')}")

    state_l = app._dash_widgets.get(("cp_engine_state",))
    sub_l = app._dash_widgets.get(("cp_engine_sub",))
    if state_l and sub_l:
        if not snap.get("reachable"):
            state_l.configure(text="○ UNKNOWN", fg=colors["DIM"])
            sub_l.configure(text="VPS not reachable", fg=colors["DIM2"])
        elif snap.get("millennium_bootstrap_running"):
            state_l.configure(text="● MLN BOOTSTRAP", fg=colors["AMBER_B"])
            first_line = next(
                (
                    line
                    for line in snap.get("screen_raw", "").splitlines()
                    if vps_millennium_screen in line
                ),
                "",
            )
            sub_l.configure(
                text=f"screen: {first_line.strip() or vps_millennium_screen}",
                fg=colors["DIM"],
            )
        elif snap.get("screen_running"):
            state_l.configure(text="● RUNNING", fg=colors["GREEN"])
            first_line = next(
                (
                    line
                    for line in snap.get("screen_raw", "").splitlines()
                    if vps_live_screen in line
                ),
                "",
            )
            sub_l.configure(
                text=f"screen: {first_line.strip() or vps_live_screen}",
                fg=colors["DIM"],
            )
        else:
            state_l.configure(text="○ STOPPED", fg=colors["AMBER_D"])
            sub_l.configure(text="no live/bootstrap screen session", fg=colors["DIM"])

    pos_head = app._dash_widgets.get(("cp_pos_head",))
    pos_inner = app._dash_widgets.get(("cp_pos_inner",))
    if pos_inner:
        for widget in pos_inner.winfo_children():
            try:
                widget.destroy()
            except Exception:
                pass
        positions = snap.get("positions") or []
        if pos_head:
            pos_head.configure(text=f" OPEN POSITIONS ({len(positions)}) ")

        if not positions:
            if snap.get("positions_raw") and snap.get("reachable"):
                tk_mod.Label(
                    pos_inner,
                    text="  — state/positions.json parse failed —",
                    font=(font_name, 8),
                    fg=colors["DIM"],
                    bg=colors["PANEL"],
                    anchor="w",
                ).pack(fill="x", pady=2)
            else:
                tk_mod.Label(
                    pos_inner,
                    text="  — no open positions —",
                    font=(font_name, 8),
                    fg=colors["DIM"],
                    bg=colors["PANEL"],
                    anchor="w",
                ).pack(fill="x", pady=2)
        else:
            for position in positions[:10]:
                sym = str(position.get("symbol", "?"))
                side = str(position.get("side", position.get("direction", "")))
                try:
                    size = float(position.get("size", position.get("qty", 0)) or 0)
                    entry = float(position.get("entry", position.get("entry_price", 0)) or 0)
                    pnl = float(position.get("pnl", position.get("unrealized_pnl", 0)) or 0)
                except (TypeError, ValueError):
                    size = entry = pnl = 0
                pnl_col = colors["GREEN"] if pnl >= 0 else colors["RED"]

                row = tk_mod.Frame(pos_inner, bg=colors["PANEL"])
                row.pack(fill="x", pady=1)
                tk_mod.Label(
                    row,
                    text=sym,
                    font=(font_name, 9, "bold"),
                    fg=colors["AMBER"],
                    bg=colors["PANEL"],
                    width=12,
                    anchor="w",
                ).pack(side="left")
                tk_mod.Label(
                    row,
                    text=side.upper()[:5],
                    font=(font_name, 8),
                    fg=colors["WHITE"],
                    bg=colors["PANEL"],
                    width=6,
                    anchor="w",
                ).pack(side="left")
                tk_mod.Label(
                    row,
                    text=f"{size:g}",
                    font=(font_name, 8),
                    fg=colors["DIM"],
                    bg=colors["PANEL"],
                    width=10,
                    anchor="w",
                ).pack(side="left")
                tk_mod.Label(
                    row,
                    text=f"@ {entry:,.4f}".rstrip("0").rstrip("."),
                    font=(font_name, 8),
                    fg=colors["DIM"],
                    bg=colors["PANEL"],
                    width=14,
                    anchor="w",
                ).pack(side="left")
                tk_mod.Label(
                    row,
                    text=f"PnL {'+' if pnl >= 0 else ''}${pnl:,.2f}",
                    font=(font_name, 9, "bold"),
                    fg=pnl_col,
                    bg=colors["PANEL"],
                    anchor="w",
                ).pack(side="left")

    if not app._dash_cockpit_streaming:
        log_text = app._dash_widgets.get(("cp_log_text",))
        if log_text:
            lines = snap.get("log_lines") or []
            log_text.configure(state="normal")
            log_text.delete("1.0", "end")
            if lines:
                log_text.insert("1.0", "\n".join(lines) + "\n")
            elif snap.get("reachable"):
                log_text.insert("1.0", "— log file not found or empty —\n")
            else:
                log_text.insert("1.0", "— VPS unreachable —\n")
            log_text.configure(state="disabled")

    if getattr(app, "_dash_alive", False) and app._dash_tab == "cockpit":
        aid = getattr(app, "_dash_after_id", None)
        if aid:
            try:
                app.after_cancel(aid)
            except Exception:
                pass
        app._dash_after_id = app.after(5000, app._dash_tick_refresh)


def action(
    app,
    label: str,
    cmd: str,
    *,
    vps_cmd,
    colors: dict[str, str],
    success_msg: str = "ok",
    timeout: int = 15,
) -> None:
    """Run an SSH command in a worker thread, flash a status message."""
    action_l = app._dash_widgets.get(("cp_action",))
    if action_l:
        action_l.configure(text=f"→ {label}...", fg=colors["AMBER_D"])

    def worker():
        out = vps_cmd(cmd, timeout=timeout)

        def apply():
            if not getattr(app, "_dash_alive", False):
                return
            if action_l:
                if out is not None:
                    action_l.configure(text=f"✓ {label}: {success_msg}", fg=colors["GREEN"])
                else:
                    action_l.configure(text=f"✗ {label}: failed", fg=colors["RED"])
            app._dash_cockpit_fetch_async()

        try:
            app.after(0, apply)
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()


def toggle_stream(
    app,
    *,
    subprocess_mod,
    threading_mod,
    no_window,
    build_vps_ssh_command,
    build_vps_log_tail_command,
    vps_project,
    colors: dict[str, str],
) -> None:
    """Toggle live streaming of the log file via `ssh ... tail -f`."""
    if app._dash_cockpit_streaming:
        app._dash_cockpit_kill_stream()
        btn = app._dash_widgets.get(("cp_stream_btn",))
        if btn:
            btn.configure(text="  STREAM LOGS  ", bg=colors["AMBER_B"])
        head = app._dash_widgets.get(("cp_log_head",))
        if head:
            head.configure(text=" LIVE LOG (polled every 5s) ")
        return
    if getattr(app, "_dash_cockpit_stream_pending", False):
        return

    log_text = app._dash_widgets.get(("cp_log_text",))
    if log_text:
        log_text.configure(state="normal")
        log_text.delete("1.0", "end")
        log_text.insert("1.0", "— starting live stream... —\n")
        log_text.configure(state="disabled")
    btn = app._dash_widgets.get(("cp_stream_btn",))
    if btn:
        btn.configure(text="  STARTING...  ", bg=colors["AMBER"])
    head = app._dash_widgets.get(("cp_log_head",))
    if head:
        head.configure(text=" LIVE LOG (connecting stream) ")
    app._dash_cockpit_stream_pending = True

    def _spawn_worker():
        try:
            proc = subprocess_mod.Popen(
                build_vps_ssh_command(build_vps_log_tail_command(vps_project())),
                stdout=subprocess_mod.PIPE,
                stderr=subprocess_mod.STDOUT,
                text=True,
                bufsize=1,
                creationflags=no_window,
            )
        except (FileNotFoundError, OSError) as err:
            def _fail():
                app._dash_cockpit_stream_pending = False
                btn = app._dash_widgets.get(("cp_stream_btn",))
                if btn:
                    btn.configure(text="  STREAM LOGS  ", bg=colors["AMBER_B"])
                head = app._dash_widgets.get(("cp_log_head",))
                if head:
                    head.configure(text=" LIVE LOG (polled every 5s) ")
                lt = app._dash_widgets.get(("cp_log_text",))
                if lt:
                    lt.configure(state="normal")
                    lt.insert("end", f"— stream failed: {err} —\n")
                    lt.configure(state="disabled")

            try:
                app.after(0, _fail)
            except Exception:
                pass
            return

        try:
            app.after(0, lambda p=proc: app._dash_cockpit_attach_stream(p))
        except Exception:
            try:
                if proc.stdout is not None:
                    proc.stdout.close()
            except (OSError, ValueError):
                pass
            try:
                proc.terminate()
            except (OSError, ValueError):
                pass

    threading_mod.Thread(target=_spawn_worker, daemon=True).start()


def attach_stream(app, proc, *, colors: dict[str, str], threading_mod) -> None:
    if proc is None:
        app._dash_cockpit_stream_pending = False
        return
    if app._dash_cockpit_streaming:
        try:
            if proc.stdout is not None:
                proc.stdout.close()
        except (OSError, ValueError):
            pass
        try:
            proc.terminate()
        except (OSError, ValueError):
            pass
        return
    app._dash_cockpit_stream = proc
    app._dash_cockpit_stream_pending = False
    app._dash_cockpit_streaming = True
    btn = app._dash_widgets.get(("cp_stream_btn",))
    if btn:
        btn.configure(text="  STOP STREAM  ", bg=colors["RED"])
    head = app._dash_widgets.get(("cp_log_head",))
    if head:
        head.configure(text=" LIVE LOG (streaming) ")
    threading_mod.Thread(
        target=app._dash_cockpit_stream_reader,
        args=(proc,),
        daemon=True,
    ).start()


def stream_reader(app, proc, *, tk_mod) -> None:
    if proc is None or proc.stdout is None:
        return
    try:
        while app._dash_cockpit_streaming:
            try:
                line = proc.stdout.readline()
            except (ValueError, OSError):
                break
            if not line:
                break
            if not app._dash_cockpit_streaming:
                break

            def append(chunk=line):
                if not getattr(app, "_dash_alive", False):
                    return
                lt = app._dash_widgets.get(("cp_log_text",))
                if lt is None:
                    return
                try:
                    if not lt.winfo_exists():
                        return
                    lt.configure(state="normal")
                    lt.insert("end", chunk)
                    total = int(lt.index("end-1c").split(".")[0])
                    if total > 500:
                        lt.delete("1.0", f"{total - 500}.0")
                    lt.see("end")
                    lt.configure(state="disabled")
                except tk_mod.TclError:
                    pass

            try:
                app.after(0, append)
            except Exception:
                return
    except Exception:
        pass


def kill_stream(app, *, subprocess_mod) -> None:
    """Idempotent kill; safe even when no stream exists."""
    app._dash_cockpit_stream_pending = False
    app._dash_cockpit_streaming = False
    proc = app._dash_cockpit_stream
    app._dash_cockpit_stream = None
    if proc is None:
        return
    if proc.stdout is not None:
        try:
            proc.stdout.close()
        except (OSError, ValueError):
            pass
    try:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess_mod.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=1)
            except subprocess_mod.TimeoutExpired:
                pass
    except (OSError, ValueError):
        pass
