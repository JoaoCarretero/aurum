"""ENGINES LIVE launcher screen."""
from __future__ import annotations

import tkinter as tk
from typing import Any

from core.data.connections import MARKETS
from core.ui.ui_palette import AMBER_D
from launcher_support.screens.base import Screen


class EnginesLiveScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any, conn: Any):
        super().__init__(parent)
        self.app = app
        self.conn = conn
        self.host: tk.Frame | None = None

    def build(self) -> None:
        self.host = tk.Frame(self.container)
        self.host.pack(fill="both", expand=True)

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        host = self.host
        if host is None:
            return

        app.h_path.configure(text="> ENGINES")
        market_label = MARKETS.get(self.conn.active_market, {}).get("label", "UNKNOWN")
        app.h_stat.configure(text=market_label, fg=AMBER_D)
        app.f_lbl.configure(text="ESC main  |  ▲▼ select  |  ENTER run  |  M cycle mode")
        app._bind_global_nav()

        prior = getattr(app, "_engines_live_handle", None)
        if prior and callable(prior.get("cleanup")):
            try:
                prior["cleanup"]()
            except Exception:
                pass

        for child in host.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass

        from launcher_support import engines_live_view

        app._engines_live_handle = engines_live_view.render(
            app,
            host,
            on_escape=lambda: app._menu("main"),
        )

    def on_exit(self) -> None:
        super().on_exit()
        app = self.app
        prior = getattr(app, "_engines_live_handle", None)
        if prior and callable(prior.get("cleanup")):
            try:
                prior["cleanup"]()
            except Exception:
                pass
        app._engines_live_handle = None
