"""DataCenterScreen for the DATA routing hub."""
from __future__ import annotations

import tkinter as tk
from typing import Any

from core.ui.ui_palette import AMBER, AMBER_D, BG, BG2, DIM, FONT
from launcher_support.screens.base import Screen


class DataCenterScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent)
        self.app = app
        self._subtitle_label: tk.Label | None = None
        self._content: tk.Frame | None = None

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
            text="DATA CENTER",
            font=(FONT, 14, "bold"),
            fg=AMBER,
            bg=BG,
            anchor="w",
        ).pack(anchor="w")
        self._subtitle_label = tk.Label(
            title_wrap,
            text="",
            font=(FONT, 8),
            fg=DIM,
            bg=BG,
            anchor="w",
        )
        self._subtitle_label.pack(anchor="w", pady=(3, 0))

        tk.Frame(outer, bg=BG2, height=6).pack(fill="x")
        tk.Frame(outer, bg=DIM, height=1).pack(fill="x", pady=(0, 12))

        self._content = tk.Frame(outer, bg=BG)
        self._content.pack(fill="both", expand=True)

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        app.h_path.configure(text="> DATA")
        app.h_stat.configure(text="CENTER", fg=AMBER_D)
        app.f_lbl.configure(
            text="ESC voltar  |  B backtests  |  E engines  |  R reports  |  P lake  |  X export"
        )
        app._kb("<Escape>", lambda: app._menu("main"))
        app._kb("<Key-0>", lambda: app._menu("main"))
        app._bind_global_nav()

        bt_count = app._data_count_backtests()
        eng_running, eng_total = app._data_count_procs()
        rep_count = app._data_count_reports()
        cache_tag = self._cache_tag()

        if self._subtitle_label is not None:
            self._subtitle_label.configure(
                text=f"{bt_count} runs | {eng_running}/{eng_total} engines | "
                f"{rep_count} files | cache {cache_tag}"
            )

        if self._content is None:
            return
        for child in self._content.winfo_children():
            child.destroy()

        panel = app._ui_panel_frame(self._content, "DATA ROUTING")
        sections = [
            (
                "PRIMARY ROUTES",
                [
                    (
                        "H",
                        "RUNS HISTORY",
                        "unified cockpit: local + VPS runs, results, trades, logs",
                        "banco de dados",
                        lambda: app._data_runs_history(),
                    ),
                    (
                        "B",
                        "BACKTESTS",
                        "validated runs, metrics and run-level inspection",
                        f"{bt_count} runs on disk",
                        lambda: app._data_backtests(),
                    ),
                    (
                        "E",
                        "ENGINE LOGS",
                        "running and recent engines with live tail",
                        f"{eng_running} running | {eng_total} total",
                        lambda: app._data_engines(),
                    ),
                ],
            ),
            (
                "HISTORICAL CACHE",
                [
                    (
                        "P",
                        "OHLCV LAKE",
                        "inspeciona cache local e baixa novos dados",
                        cache_tag,
                        lambda: app._data_lake(),
                    ),
                ],
            ),
            (
                "ARTIFACTS",
                [
                    (
                        "R",
                        "REPORT INDEX",
                        "raw JSON and persisted report artifact browser",
                        f"{rep_count} files indexed",
                        lambda: app._data(),
                    ),
                ],
            ),
            (
                "EXTERNAL REVIEW",
                [
                    (
                        "X",
                        "EXPORT ANALYSIS",
                        "single-file snapshot for external analysis workflows",
                        "< 2 MB JSON",
                        lambda: app._export_analysis(),
                    ),
                ],
            ),
        ]

        for section_name, items in sections:
            sec = app._ui_section(panel, section_name)
            for key_label, name, desc, stat, cmd in items:
                row, name_lbl, desc_lbl = app._ui_action_row(
                    sec,
                    key_label,
                    name,
                    desc,
                    command=cmd,
                    title_width=20,
                    tag=stat,
                    tag_fg=AMBER_D,
                    tag_bg=BG,
                )
                for widget in (row, name_lbl, desc_lbl):
                    widget.bind("<Enter>", lambda _e, n=name_lbl: n.configure(fg=AMBER))
                    widget.bind("<Leave>", lambda _e, n=name_lbl: n.configure(fg="white"))
                app._kb(f"<Key-{key_label.lower()}>", cmd)

        app._ui_back_row(panel, lambda: app._menu("main"))

    def _cache_tag(self) -> str:
        try:
            from core import cache as cache_mod

            info = cache_mod.info()
            if info["n_files"]:
                return f"{info['n_files']} files | {info['total_bytes']/1024/1024:.1f} MB"
            return "vazio"
        except Exception:
            return "indisponivel"
