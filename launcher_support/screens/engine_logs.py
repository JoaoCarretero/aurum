"""Engine logs launcher screen."""
from __future__ import annotations

import tkinter as tk
from typing import Any

from launcher_support.engine_logs_view import cleanup, render_screen
from launcher_support.screens.base import Screen


class EngineLogsScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent)
        self.app = app
        self.host: tk.Frame | None = None

    def build(self) -> None:
        self.host = tk.Frame(self.container)
        self.host.pack(fill="both", expand=True)

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        host = self.host
        if host is None:
            return
        render_screen(self.app, host, on_escape=self.app._data_center)

    def on_exit(self) -> None:
        super().on_exit()
        cleanup(self.app)
