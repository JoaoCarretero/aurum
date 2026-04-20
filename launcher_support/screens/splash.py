"""SplashScreen — pilot migration of launcher._splash.

Original function: launcher.py:_splash (L2250-L2365).
This class encapsulates the same visual output but with:
  - widgets built once in build(); subsequent visits only refresh data
  - pulse timer + click/key bindings auto-cancelled in on_exit

SYSTEM_TAGLINE and the connection manager are module-level in launcher.py,
so they are passed through the factory lambda at register() time. The
screen receives the launcher Terminal `app` to reuse drawing helpers
(_draw_panel, _draw_kv_rows, etc.) and header labels (h_stat, h_path,
f_lbl).
"""
from __future__ import annotations

import tkinter as tk
from typing import Any

from core.ui.ui_palette import (
    AMBER, AMBER_B, AMBER_D, BG, BORDER, DIM, DIM2, FONT,
    GREEN, RED, WHITE,
)

from launcher_support.screens.base import Screen


class SplashScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any, conn: Any, tagline: str):
        super().__init__(parent)
        self.app = app
        self.conn = conn
        self.tagline = tagline
        self.canvas: tk.Canvas | None = None
        self._pulse_cursor_on = True
        self._design_w = app._SPLASH_DESIGN_W
        self._design_h = app._SPLASH_DESIGN_H

    def build(self) -> None:
        f = tk.Frame(self.container, bg=BG)
        f.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(
            f, bg=BG, highlightthickness=0,
            width=self._design_w, height=self._design_h,
        )
        self.canvas.pack(fill="both", expand=True)

        canvas = self.canvas
        canvas.create_line(48, 48, 872, 48, fill=AMBER_D, width=1)
        canvas.create_line(48, 596, 872, 596, fill=DIM2, width=1)

        LOGO_CX, LOGO_CY = 460, 108
        self.app._draw_aurum_logo(canvas, LOGO_CX, LOGO_CY, scale=40,
                                  tag="splash-logo")
        canvas.create_text(LOGO_CX, 180, anchor="center", text="A U R U M",
                           font=(FONT, 22, "bold"), fill=WHITE, tags="wordmark")
        canvas.create_text(LOGO_CX, 210, anchor="center", text="F I N A N C E",
                           font=(FONT, 12), fill=AMBER_D, tags="wordmark")
        canvas.create_line(LOGO_CX - 140, 230, LOGO_CX + 140, 230,
                           fill=AMBER_D, width=1, tags="wordmark")
        canvas.create_text(LOGO_CX, 246, anchor="center", text=self.tagline,
                           font=(FONT, 8, "bold"), fill=DIM, tags="subtitle")
        canvas.create_line(280, 268, 640, 268, fill=BORDER, width=1,
                           tags="subtitle")
        canvas.create_text(460, 500, anchor="center",
                           text="[ ENTER TO ACCESS DESK ]_",
                           font=(FONT, 11, "bold"), fill=AMBER_B,
                           tags="prompt2")

    def on_enter(self, **kwargs: Any) -> None:
        app = self.app
        app.h_path.configure(text="")
        app.h_stat.configure(text="READY", fg=AMBER_B)
        app.f_lbl.configure(text="ENTER proceed  |  CLICK proceed  |  Q quit")

        canvas = self.canvas
        try:
            st = self.conn.status_summary()
            market_val = st.get("market", "-")
        except Exception:
            market_val = "-"
        try:
            keys = app._load_json("keys.json")
            has_tg = bool(keys.get("telegram", {}).get("bot_token"))
            has_keys = bool(
                keys.get("demo", {}).get("api_key")
                or keys.get("testnet", {}).get("api_key")
            )
        except Exception:
            has_tg = False
            has_keys = False

        market_cell = "LIVE" if market_val and market_val != "-" else "OFFLINE"
        market_col = GREEN if market_cell == "LIVE" else DIM
        conn_cell = "BINANCE READY" if has_keys else "OFFLINE"
        conn_col = GREEN if has_keys else DIM
        tg_cell = "ONLINE" if has_tg else "OFFLINE"
        tg_col = GREEN if has_tg else DIM

        # Clear previous "splash" tagged content so re-entry refreshes values
        canvas.delete("splash")

        app._draw_panel(canvas, 140, 296, 780, 414,
                        title="SESSION OVERVIEW", accent=AMBER, tag="splash")
        app._draw_kv_rows(canvas, 168, 330, [
            ("ENGINE", "AURUM CORE", WHITE),
            ("MODE", "OPERATOR CONSOLE", AMBER_B),
            ("ACCOUNT", "PAPER · MULTI", WHITE),
            ("ENVIRONMENT", "LOCAL", WHITE),
        ], value_x=316, tag="splash")
        app._draw_kv_rows(canvas, 472, 330, [
            ("MARKET FEED", market_cell, market_col),
            ("CONNECTION", conn_cell, conn_col),
            ("TELEGRAM", tg_cell, tg_col),
            ("RISK", "KILL-SWITCH ARMED", RED),
        ], value_x=640, tag="splash")

        # Bindings + timer (auto-cleanup in on_exit)
        self._bind(canvas, "<Button-1>", lambda e: app._splash_on_click())
        app._bind_global_nav()
        self._after(500, self._pulse_tick)

        # Resize hook
        self._bind(canvas, "<Configure>", self._render_resize)
        self._render_resize()

    def _render_resize(self, _event=None) -> None:
        if self.canvas is None:
            return
        self.app._apply_canvas_scale(
            self.canvas, self._design_w, self._design_h, 1.0,
        )

    def _pulse_tick(self) -> None:
        canvas = self.canvas
        if canvas is None:
            return
        try:
            cur = canvas.itemcget("prompt2", "text")
        except tk.TclError:
            return
        if cur.endswith("_"):
            canvas.itemconfigure("prompt2", text=cur[:-1] + " ")
        else:
            canvas.itemconfigure("prompt2", text=cur[:-1] + "_")
        self._after(500, self._pulse_tick)
