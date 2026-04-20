"""Runs history launcher screen."""
from __future__ import annotations

import tkinter as tk
from typing import Any

from core.ui.ui_palette import GREEN
from launcher_support.screens.base import Screen


class RunsHistoryScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any, client_factory: Any):
        super().__init__(parent)
        self.app = app
        self.client_factory = client_factory
        self.host: tk.Frame | None = None
        self._render_root: tk.Frame | None = None

    def build(self) -> None:
        self.host = tk.Frame(self.container)
        self.host.pack(fill="both", expand=True)

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        host = self.host
        if host is None:
            return

        app.h_path.configure(text="> DATA > RUNS HISTORY")
        app.h_stat.configure(text="LIVE", fg=GREEN)
        app.f_lbl.configure(text="ESC voltar  |  click row to expand  |  auto-refresh 5s")
        app._kb("<Escape>", app._data_center)

        from launcher_support.runs_history import render_runs_history

        self._render_root = render_runs_history(host, app, client_factory=self.client_factory)

    def on_exit(self) -> None:
        super().on_exit()
        root = self._render_root
        self._render_root = None
        if root is None:
            return
        state = getattr(root, "_runs_history_state", None)
        aid = state.get("refresh_aid") if isinstance(state, dict) else None
        if aid is not None:
            try:
                self.app.after_cancel(aid)
            except Exception:
                pass
            state["refresh_aid"] = None
