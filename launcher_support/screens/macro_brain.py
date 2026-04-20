"""Macro Brain launcher screen.

This wraps the legacy ``App._macro_brain_menu`` flow in ScreenManager so
the page lifecycle and timer cleanup live with the screen object.
"""
from __future__ import annotations

import threading
import tkinter as tk
from typing import Any

from core.ui.ui_palette import AMBER, BG, FONT, RED
from launcher_support.screens.base import Screen


class MacroBrainScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent)
        self.app = app
        self.host: tk.Frame | None = None
        self._rendered = False

    def build(self) -> None:
        self.host = tk.Frame(self.container, bg=BG)
        self.host.pack(fill="both", expand=True)

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        host = self.host
        if host is None:
            return

        app.h_path.configure(text="")
        app.h_stat.configure(text="COCKPIT", fg=AMBER)
        app.f_lbl.configure(text="ESC main menu  |  R refresh  |  C run cycle  |  bg cycle 5m")
        app._bind_global_nav()

        if not self._rendered:
            try:
                from macro_brain.dashboard_view import render as render_dashboard

                render_dashboard(host, app=app)
                self._rendered = True
            except Exception as exc:
                tk.Label(
                    host,
                    text=f"Macro Brain failed to render:\n{exc}\n\nPress ESC -> main menu",
                    font=(FONT, 10),
                    fg=RED,
                    bg=BG,
                ).pack(pady=40)
                return
        else:
            try:
                from macro_brain.dashboard_view import tick_update

                tick_update()
            except Exception:
                pass

        app._macro_page_token = object()
        token = app._macro_page_token

        def still_here() -> bool:
            return getattr(app, "_macro_page_token", None) is token

        def auto_tick() -> None:
            if not still_here():
                return
            try:
                from macro_brain.dashboard_view import tick_update

                tick_update()
            except Exception:
                pass
            app._macro_render_after = self._after(10_000, auto_tick)

        def auto_cycle() -> None:
            if not still_here():
                return

            def work() -> None:
                try:
                    from macro_brain.brain import run_once

                    run_once(force=False)
                except Exception:
                    pass

            threading.Thread(target=work, daemon=True).start()
            app._macro_cycle_after = self._after(300_000, auto_cycle)

        def kickoff() -> None:
            try:
                from macro_brain.brain import run_once

                run_once(force=False)
            except Exception:
                pass

        threading.Thread(target=kickoff, daemon=True).start()
        app._macro_render_after = self._after(10_000, auto_tick)
        app._macro_cycle_after = self._after(300_000, auto_cycle)
        try:
            app.focus_set()
        except Exception:
            pass

    def on_exit(self) -> None:
        super().on_exit()
        app = self.app
        app._macro_render_after = None
        app._macro_cycle_after = None
        app._macro_page_token = None
