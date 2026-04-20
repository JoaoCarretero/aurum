"""SettingsScreen for the SETTINGS routing hub."""
from __future__ import annotations

import tkinter as tk
from typing import Any

from core.ui.ui_palette import AMBER, AMBER_D, BG, BG2, DIM, FONT
from launcher_support.screens.base import Screen


class SettingsScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent)
        self.app = app
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
            text="SETTINGS",
            font=(FONT, 14, "bold"),
            fg=AMBER,
            bg=BG,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            title_wrap,
            text="Configuration surfaces for credentials, deploy and operator defaults",
            font=(FONT, 8),
            fg=DIM,
            bg=BG,
            anchor="w",
        ).pack(anchor="w", pady=(3, 0))

        tk.Frame(outer, bg=BG2, height=6).pack(fill="x")
        tk.Frame(outer, bg=DIM, height=1).pack(fill="x", pady=(0, 12))

        self._content = tk.Frame(outer, bg=BG)
        self._content.pack(fill="both", expand=True)

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        app.h_path.configure(text="> SETTINGS")
        app.h_stat.configure(text="CONFIG", fg=AMBER_D)
        app.f_lbl.configure(text="ESC voltar  |  H hub")
        app._kb("<Escape>", lambda: app._menu("main"))
        app._kb("<Key-0>", lambda: app._menu("main"))
        app._bind_global_nav()

        if self._content is None:
            return
        for child in self._content.winfo_children():
            child.destroy()

        panel = app._ui_panel_frame(
            self._content,
            "CONFIGURATION ROUTER",
            "Editable and planned configuration modules",
        )
        cfgs = [
            ("API KEYS", "Exchange & broker credentials", app._cfg_keys, True),
            ("MACRO BRAIN APIS", "FRED, NewsAPI (data sources)", app._cfg_macro_keys, True),
            ("TELEGRAM", "Bot token & chat ID", app._cfg_tg, True),
            ("RISK PARAMETERS", "Account size, max risk, leverage", None, False),
            ("STRATEGY DEFAULTS", "Timeframes, symbols, baskets", None, False),
            ("DISPLAY", "Theme, font size, ticker symbols", None, False),
            ("DATA DIRECTORY", "Where reports & logs are stored", None, False),
            ("VPS / DEPLOY", "Remote server SSH connection", app._cfg_vps, True),
            ("BACKUP / RESTORE", "Export/import all settings", None, False),
        ]

        for idx, (name, desc, cmd, available) in enumerate(cfgs):
            app._ui_action_row(
                panel,
                str(idx + 1),
                name,
                desc,
                command=cmd if available else None,
                available=available,
                tag=None if available else "COMING SOON",
                tag_fg=DIM,
                tag_bg=BG2,
                title_width=20,
            )
            if cmd and available:
                app._kb(f"<Key-{idx + 1}>", cmd)

        app._ui_back_row(panel, lambda: app._menu("main"))
