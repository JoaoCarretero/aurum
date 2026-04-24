"""ProcessesScreen for local process inspection and stop actions."""
from __future__ import annotations

import tkinter as tk
from typing import Any

from core.ui.ui_palette import AMBER, BG, BG2, DIM, FONT, GREEN, RED, WHITE
from launcher_support.screens.base import Screen


class ProcessesScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent)
        self.app = app
        self._list_host: tk.Frame | None = None
        self._empty_note: tk.Label | None = None

    def build(self) -> None:
        outer = tk.Frame(self.container, bg=BG)
        outer.pack(fill="both", expand=True, padx=28, pady=18)

        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x", pady=(0, 12))
        strip = tk.Frame(head, bg=BG)
        strip.pack(fill="x")
        tk.Frame(strip, bg=AMBER, width=4, height=28).pack(side="left", padx=(0, 8))

        title_wrap = tk.Frame(strip, bg=BG)
        title_wrap.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_wrap,
            text="PROCESSES",
            font=(FONT, 14, "bold"),
            fg=AMBER,
            bg=BG,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            title_wrap,
            text="Running engine processes and control actions",
            font=(FONT, 8),
            fg=DIM,
            bg=BG,
            anchor="w",
        ).pack(anchor="w", pady=(3, 0))

        tk.Frame(outer, bg=BG2, height=6).pack(fill="x")
        tk.Frame(outer, bg=DIM, height=1).pack(fill="x", pady=(0, 12))

        app = self.app
        panel = app._ui_panel_frame(
            outer,
            "PROCESS CONTROL",
            "Live engines currently registered in the local process index",
        )
        self._empty_note = tk.Label(
            panel,
            text="No engines running.",
            font=(FONT, 8),
            fg=DIM,
            bg=BG,
            anchor="w",
        )
        self._list_host = tk.Frame(panel, bg=BG)
        self._list_host.pack(fill="both", expand=True)

        app._ui_back_row(panel, lambda: app._menu("main"))

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        app.h_path.configure(text="> PROCS")
        app.h_stat.configure(text="MANAGE", fg=GREEN)
        app.f_lbl.configure(text="ESC back  |  R refresh")
        app._kb("<Escape>", lambda: app._menu("main"))
        app._kb("<Key-r>", app._procs)

        if self._list_host is None:
            return
        for child in self._list_host.winfo_children():
            child.destroy()

        try:
            from core.ops.proc import list_procs, stop_proc

            procs = [proc for proc in list_procs() if proc.get("alive")]
        except Exception:
            procs = []
            stop_proc = None  # type: ignore[assignment]

        if not procs:
            if self._empty_note is not None:
                self._empty_note.pack(fill="x", padx=14, pady=(4, 8))
        elif self._empty_note is not None:
            self._empty_note.pack_forget()

        def _safe_stop(pid: Any) -> None:
            if pid is None or stop_proc is None:
                return
            try:
                stop_proc(int(pid))
            except Exception as exc:
                app.h_stat.configure(text=f"STOP FAILED: {str(exc)[:30]}", fg=RED)
            app.after(200, app._procs)

        for proc in procs:
            row = tk.Frame(self._list_host, bg=BG2)
            row.pack(fill="x", padx=14, pady=2)
            tk.Label(
                row,
                text=f" {proc.get('engine', '?').upper()} ",
                font=(FONT, 8, "bold"),
                fg=BG,
                bg=GREEN,
            ).pack(side="left")
            tk.Label(
                row,
                text=f"  PID {proc.get('pid', '?')}",
                font=(FONT, 9),
                fg=WHITE,
                bg=BG2,
                padx=6,
                pady=4,
            ).pack(side="left")
            tk.Button(
                row,
                text="STOP",
                font=(FONT, 7, "bold"),
                fg=RED,
                bg=BG2,
                border=0,
                cursor="hand2",
                command=lambda pid=proc.get("pid"): _safe_stop(pid),
            ).pack(side="right", padx=4, pady=2)
