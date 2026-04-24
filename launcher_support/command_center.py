from __future__ import annotations

from pathlib import Path
import re


def get_site_runner(app):
    """Lazily instantiate the singleton SiteRunner."""
    sr = getattr(app, "_site_runner_inst", None)
    if sr is None:
        from core.ops.site_runner import SiteRunner
        sr = SiteRunner()
        app._site_runner_inst = sr
    return sr


def command_center(app, *, colors: dict[str, str], command_roadmaps) -> None:
    app._clr()
    app._clear_kb()
    if not app.history:
        app.history = ["main"]
    app.h_path.configure(text="> COMMAND CENTER")
    app.h_stat.configure(text="MANAGE", fg=colors["AMBER_D"])
    app.f_lbl.configure(text="ESC voltar  |  número para selecionar  |  H hub")
    app._kb("<Escape>", lambda: app._menu("main"))
    app._kb("<Key-0>", lambda: app._menu("main"))
    app._bind_global_nav()

    _outer, body = app._ui_page_shell(
        "COMMAND CENTER",
        "Administrative routing for local site, deploy and system control",
    )
    panel = app._ui_panel_frame(body, "CONTROL SURFACES", "Operational and infrastructure workflows")

    sr = app._get_site_runner()
    site_running = sr.is_running()
    running_tag = "● RUNNING" if site_running else None

    items = [
        ("SITE LOCAL", "Dev server (npm/vite/next)", True, app._site_local, running_tag),
        ("DEPLOY", "Push to production", False, lambda: app._command_coming_soon("DEPLOY"), None),
        ("SERVERS", "VPS status & SSH", False, lambda: app._command_coming_soon("SERVERS"), None),
        ("DATABASES", "Connections & backups", False, lambda: app._command_coming_soon("DATABASES"), None),
        ("SERVICES", "Background processes", False, lambda: app._command_coming_soon("SERVICES"), None),
        ("SYSTEM", "CPU, RAM, disk, network", False, lambda: app._command_coming_soon("SYSTEM"), None),
    ]

    app._ui_note(
        panel,
        "Local site control is active. Remaining surfaces stay documented until implementation is wired.",
        fg=colors["DIM"],
    )

    for i, (name, desc, available, cmd, tag) in enumerate(items, start=1):
        row, nl, dl = app._ui_action_row(
            panel, str(i), name, desc,
            available=available,
            tag=tag or ("COMING SOON" if not available else None),
            tag_fg=colors["BG"] if tag else colors["DIM"],
            tag_bg=colors["GREEN"] if tag else colors["BG2"],
            title_width=18,
        )
        for widget in [row, nl, dl]:
            widget.bind("<Button-1>", lambda e, c=cmd: c())
            if available:
                widget.bind("<Enter>", lambda e, n=nl: n.configure(fg=colors["AMBER"]))
                widget.bind("<Leave>", lambda e, n=nl: n.configure(fg=colors["WHITE"]))
        app._kb(f"<Key-{i}>", cmd)

    app._ui_back_row(panel, lambda: app._menu("main"))


def command_coming_soon(app, name: str, *, colors: dict[str, str], command_roadmaps) -> None:
    app._clr()
    app._clear_kb()
    app.h_path.configure(text=f"> COMMAND CENTER > {name}")
    app.h_stat.configure(text="ROADMAP", fg=colors["DIM"])
    app.f_lbl.configure(text="ESC voltar  |  H hub")
    app._kb("<Escape>", app._command_center)
    app._kb("<Key-0>", app._command_center)
    app._bind_global_nav()

    roadmap = command_roadmaps.get(name, ["Coming soon"])
    _outer, body = app._ui_page_shell(name, "Roadmap placeholder for command-center pipeline")
    box = app._ui_panel_frame(body, "ROADMAP", f"{name} implementation plan")
    for item in roadmap:
        app._ui_note(box, f"[ ] {item}", fg=colors["DIM"])
    app._ui_back_row(box, lambda: app._command_center())


def site_local(app) -> None:
    app._clr()
    app._clear_kb()
    app.history = ["main", "command"]
    app.h_path.configure(text="> COMMAND CENTER > SITE LOCAL")
    app.f_lbl.configure(text="ESC voltar  |  H hub")
    app._kb("<Escape>", app._command_center)
    app._bind_global_nav()

    sr = app._get_site_runner()
    if sr.is_running():
        app._site_running_screen(sr)
    else:
        app._site_config_screen(sr)


def site_config_screen(app, sr, *, tk_mod, colors: dict[str, str], font_name: str) -> None:
    app.h_stat.configure(text="● STOPPED", fg=colors["RED"])

    _outer, body = app._ui_page_shell(
        "SITE LOCAL",
        "Local site runner configuration and launch controls",
        content_width=860,
    )
    box = app._ui_panel_frame(body, "SITE RUNNER", "Resolved local app command and operator settings")

    framework_d, command_d = sr.resolved_command()
    info = [
        ("Project Dir", sr.config.get("project_dir") or "(not set)"),
        ("Framework", f"{sr.config.get('framework','auto')}  →  {framework_d}"),
        ("Port", str(sr.config.get("port", 3000))),
        ("Command", command_d),
        ("Auto-open", "yes" if sr.config.get("auto_open_browser") else "no"),
    ]
    for label, value in info:
        row = tk_mod.Frame(box, bg=colors["BG"])
        row.pack(fill="x", pady=2)
        tk_mod.Label(
            row, text=label, font=(font_name, 8, "bold"),
            fg=colors["DIM"], bg=colors["BG"], width=14, anchor="w"
        ).pack(side="left")
        tk_mod.Label(
            row, text=value, font=(font_name, 9),
            fg=colors["WHITE"], bg=colors["BG"], anchor="w"
        ).pack(side="left", padx=4)

    app._ui_note(box, "Status: stopped", fg=colors["RED"])

    bf = tk_mod.Frame(box, bg=colors["BG"])
    bf.pack(fill="x", pady=(8, 4))

    def mkbtn(text, color, fg, cmd):
        btn = tk_mod.Label(
            bf, text=text, font=(font_name, 10, "bold"),
            fg=fg, bg=color, cursor="hand2", padx=14, pady=5
        )
        btn.pack(side="left", padx=4)
        btn.bind("<Button-1>", lambda e: cmd())
        return btn

    mkbtn(" START ", colors["GREEN"], colors["BG"], app._site_start)
    mkbtn(" CONFIG ", colors["AMBER"], colors["BG"], app._site_config_edit)
    mkbtn(" OPEN BROWSER ", colors["BG3"], colors["AMBER"], app._site_open_browser)
    mkbtn(" VOLTAR ", colors["BG3"], colors["DIM"], app._command_center)

    if not sr.config.get("project_dir"):
        app._ui_note(box, "Warning: configure PROJECT_DIR before START.", fg=colors["AMBER_D"])


def site_running_screen(app, sr, *, tk_mod, colors: dict[str, str], font_name: str) -> None:
    app.h_stat.configure(text="● RUNNING", fg=colors["GREEN"])
    framework, _command = sr.resolved_command()
    port = sr.config.get("port", 3000)

    _outer, body = app._ui_page_shell(
        "SITE LOCAL",
        "Local runner status, console stream and browser routing",
    )
    top = app._ui_panel_frame(body, "SITE RUNNER", f"Running on {framework}  ·  port {port}")
    meta = tk_mod.Frame(top, bg=colors["BG"])
    meta.pack(fill="x", pady=(0, 8))
    tk_mod.Label(
        meta, text="Status: running", font=(font_name, 8, "bold"),
        fg=colors["GREEN"], bg=colors["BG"]
    ).pack(side="left")
    app._site_uptime_lbl = tk_mod.Label(
        meta,
        text=f"PID {sr.proc.pid if sr.proc else '?'}   uptime {sr.uptime()}",
        font=(font_name, 7), fg=colors["DIM"], bg=colors["BG"],
    )
    app._site_uptime_lbl.pack(side="left", padx=12)
    url_lbl = tk_mod.Label(
        meta, text=sr.url(), font=(font_name, 7),
        fg=colors["AMBER_D"], bg=colors["BG"], cursor="hand2",
    )
    url_lbl.pack(side="right", padx=8)
    url_lbl.bind("<Button-1>", lambda e: app._site_open_browser())

    cf = tk_mod.Frame(body, bg=colors["PANEL"])
    cf.pack(fill="both", expand=True)
    sb = tk_mod.Scrollbar(cf, bg=colors["BG"], troughcolor=colors["BG"], highlightthickness=0, bd=0)
    sb.pack(side="right", fill="y")
    app.site_con = tk_mod.Text(
        cf, bg=colors["PANEL"], fg=colors["WHITE"], font=(font_name, 9), wrap="word",
        borderwidth=0, highlightthickness=0, padx=10, pady=6, state="disabled",
        cursor="arrow", yscrollcommand=sb.set,
    )
    app.site_con.pack(fill="both", expand=True)
    sb.config(command=app.site_con.yview)
    app.site_con.tag_configure("a", foreground=colors["AMBER"])
    app.site_con.tag_configure("g", foreground=colors["GREEN"])
    app.site_con.tag_configure("r", foreground=colors["RED"])
    app.site_con.tag_configure("d", foreground=colors["DIM"])
    app.site_con.tag_configure("w", foreground=colors["WHITE"])

    bf = tk_mod.Frame(body, bg=colors["BG"])
    bf.pack(fill="x", pady=(8, 0))

    def mkbtn(text, fg, cmd):
        btn = tk_mod.Label(
            bf, text=text, font=(font_name, 9, "bold"),
            fg=fg, bg=colors["BG"], cursor="hand2", padx=10, pady=5
        )
        btn.pack(side="left", padx=2, pady=2)
        btn.bind("<Button-1>", lambda e: cmd())

    mkbtn(" STOP ", colors["RED"], app._site_stop)
    mkbtn(" OPEN BROWSER ", colors["AMBER"], app._site_open_browser)
    mkbtn(" CLEAR ", colors["DIM"], app._site_clear_console)
    mkbtn(" BACK ", colors["DIM"], app._command_center)

    app._site_seen_idx = 0
    app._site_screen_alive = True
    app._site_poll()


def site_print(app, line: str, default_tag: str = "w") -> None:
    if not hasattr(app, "site_con"):
        return
    try:
        if not app.site_con.winfo_exists():
            return
    except Exception:
        return
    clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", line)
    low = clean.lower()
    tag = default_tag
    if "✓" in clean or "ready in" in low or "compiled" in low:
        tag = "g"
    elif "✗" in clean or "error" in low or "failed" in low or "sigterm" in low:
        tag = "r"
    elif "warn" in low:
        tag = "a"
    try:
        app.site_con.configure(state="normal")
        app.site_con.insert("end", clean, tag)
        app.site_con.see("end")
        app.site_con.configure(state="disabled")
    except Exception:
        pass


def site_poll(app) -> None:
    if not getattr(app, "_site_screen_alive", False):
        return
    sr = getattr(app, "_site_runner_inst", None)
    if sr is None:
        return

    new_idx, lines = sr.lines_after(getattr(app, "_site_seen_idx", 0))
    for line in lines:
        app._site_print(line)
    app._site_seen_idx = new_idx

    try:
        if hasattr(app, "_site_uptime_lbl") and app._site_uptime_lbl.winfo_exists():
            pid = sr.proc.pid if sr.proc else "?"
            app._site_uptime_lbl.configure(text=f"PID {pid}   uptime {sr.uptime()}")
    except Exception:
        pass

    if not sr.is_running():
        app._site_print("\n  >> PROCESS EXITED\n", "r")
        app._site_screen_alive = False
        app.after(800, app._site_local)
        return

    app.after(150, app._site_poll)


def site_start(app, *, path_cls=Path, webbrowser_mod=None, colors: dict[str, str] | None = None) -> None:
    colors = colors or {}
    sr = app._get_site_runner()
    if sr.is_running():
        app.h_stat.configure(text="ALREADY RUNNING", fg=colors.get("AMBER_D")); return
    if not (sr.config.get("project_dir") or "").strip():
        app.h_stat.configure(text="DEFINE PROJECT_DIR FIRST", fg=colors.get("RED"))
        return
    if not path_cls(sr.config["project_dir"]).is_dir():
        app.h_stat.configure(text="DIR NOT FOUND", fg=colors.get("RED"))
        return
    ok, msg = sr.start()
    if not ok:
        app.h_stat.configure(text=f"FAIL: {msg[:32]}", fg=colors.get("RED"))
        return
    if sr.config.get("auto_open_browser"):
        try:
            if webbrowser_mod is None:
                import webbrowser as webbrowser_mod
            app.after(1500, lambda: webbrowser_mod.open(sr.url()))
        except Exception:
            pass
    app._site_local()


def site_stop(app) -> None:
    sr = getattr(app, "_site_runner_inst", None)
    if sr and sr.is_running():
        try:
            sr.stop()
        except Exception:
            pass
    app._site_screen_alive = False
    app.after(200, app._site_local)


def site_open_browser(app, *, webbrowser_mod=None, colors: dict[str, str] | None = None) -> None:
    colors = colors or {}
    sr = app._get_site_runner()
    if not sr.is_running():
        app.h_stat.configure(text="server not running", fg=colors.get("AMBER_D"))
        return
    try:
        if webbrowser_mod is None:
            import webbrowser as webbrowser_mod
        webbrowser_mod.open(sr.url())
        app.h_stat.configure(text="opened", fg=colors.get("GREEN"))
    except Exception as exc:
        app.h_stat.configure(text=f"browser fail: {str(exc)[:24]}", fg=colors.get("RED"))


def site_clear_console(app) -> None:
    try:
        if hasattr(app, "site_con") and app.site_con.winfo_exists():
            app.site_con.configure(state="normal")
            app.site_con.delete("1.0", "end")
            app.site_con.configure(state="disabled")
    except Exception:
        pass
    sr = getattr(app, "_site_runner_inst", None)
    if sr is not None:
        app._site_seen_idx = sr.total_emitted


def site_config_edit(app) -> None:
    sr = app._get_site_runner()

    def load():
        return {
            "project_dir": sr.config.get("project_dir", ""),
            "framework": sr.config.get("framework", "auto"),
            "port": str(sr.config.get("port", 3000)),
            "command": sr.config.get("command", ""),
            "auto_open": "yes" if sr.config.get("auto_open_browser", True) else "no",
        }

    def save(values):
        try:
            raw = (values.get("port") or "").strip()
            port = int(raw) if raw else 3000
        except ValueError:
            port = 3000
        sr.save_config(
            project_dir=(values.get("project_dir") or "").strip(),
            framework=((values.get("framework") or "auto").strip() or "auto"),
            port=port,
            command=(values.get("command") or "").strip(),
            auto_open_browser=((values.get("auto_open") or "").strip().lower() in ("yes", "y", "true", "1")),
        )
        app.after(1500, app._site_local)

    app._cfg_edit(
        "SITE LOCAL",
        [
            ("project_dir", "PROJECT DIR", "absolute path", False),
            ("framework", "FRAMEWORK", "auto/next/vite/nuxt/gatsby/django/static/custom", False),
            ("port", "PORT", "default 3000", False),
            ("command", "COMMAND", "override (optional)", False),
            ("auto_open", "AUTO BROWSER", "yes/no", False),
        ],
        load,
        save,
        back_fn=app._site_local,
    )
