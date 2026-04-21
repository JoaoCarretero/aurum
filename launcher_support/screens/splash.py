"""SplashScreen - pilot migration of launcher._splash.

Original function: launcher.py:_splash.
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
    _CENTER_X = 460
    _TOP_RULE_Y = 48
    _BOTTOM_RULE_Y = 596
    _RULE_X1 = 48
    _RULE_X2 = 872
    _WORDMARK_DIVIDER_HALF = 140
    _SUBTITLE_DIVIDER_HALF = 180
    _SESSION_PANEL_W = 640
    _SESSION_PANEL_H = 118
    _SESSION_PANEL_Y1 = 296
    _SESSION_PANEL_Y2 = _SESSION_PANEL_Y1 + _SESSION_PANEL_H
    _SESSION_GUTTER = 28
    _SESSION_LABEL_VALUE_GAP = 132
    _SESSION_LINE_H = 18

    def __init__(self, parent: tk.Misc, app: Any, conn: Any, tagline: str):
        super().__init__(parent)
        self.app = app
        self.conn = conn
        self.tagline = tagline
        self.canvas: tk.Canvas | None = None
        self._design_w = app._SPLASH_DESIGN_W
        self._design_h = app._SPLASH_DESIGN_H

    def build(self) -> None:
        frame = tk.Frame(self.container, bg=BG)
        frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(
            frame,
            bg=BG,
            highlightthickness=0,
            width=self._design_w,
            height=self._design_h,
        )
        self.canvas.pack(fill="both", expand=True)

        canvas = self.canvas
        canvas.create_line(
            self._RULE_X1, self._TOP_RULE_Y, self._RULE_X2, self._TOP_RULE_Y,
            fill=AMBER_D, width=1,
        )
        canvas.create_line(
            self._RULE_X1, self._BOTTOM_RULE_Y, self._RULE_X2, self._BOTTOM_RULE_Y,
            fill=DIM2, width=1,
        )
        self._draw_wordmark(canvas)
        canvas.create_text(
            self._CENTER_X,
            500,
            anchor="center",
            text="[ ENTER TO ACCESS DESK ]_",
            font=(FONT, 11, "bold"),
            fill=AMBER_B,
            tags="prompt2",
        )

    def on_enter(self, **kwargs: Any) -> None:
        app = self.app
        app.h_path.configure(text="")
        app.h_stat.configure(text="READY", fg=AMBER_B)
        app.f_lbl.configure(text="ENTER proceed  |  CLICK proceed  |  Q quit")

        canvas = self.canvas
        if canvas is None:
            return
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

        canvas.delete("splash")
        self._draw_session_overview(
            canvas,
            left_rows=[
                ("ENGINE", "AURUM CORE", WHITE),
                ("MODE", "OPERATOR CONSOLE", AMBER_B),
                ("ACCOUNT", "PAPER · MULTI", WHITE),
                ("ENVIRONMENT", "LOCAL", WHITE),
            ],
            right_rows=[
                ("MARKET FEED", market_cell, market_col),
                ("CONNECTION", conn_cell, conn_col),
                ("TELEGRAM", tg_cell, tg_col),
                ("RISK", "KILL-SWITCH ARMED", RED),
            ],
        )

        self._bind(canvas, "<Button-1>", lambda e: app._splash_on_click())
        app._bind_global_nav()
        self._after(500, self._pulse_tick)
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
            current = canvas.itemcget("prompt2", "text")
        except tk.TclError:
            return
        if current.endswith("_"):
            canvas.itemconfigure("prompt2", text=current[:-1] + " ")
        else:
            canvas.itemconfigure("prompt2", text=current[:-1] + "_")
        self._after(500, self._pulse_tick)

    def _draw_wordmark(self, canvas: tk.Canvas) -> None:
        logo_cx, logo_cy = self._CENTER_X, 108
        self.app._draw_aurum_logo(canvas, logo_cx, logo_cy, scale=40, tag="splash-logo")
        canvas.create_text(
            logo_cx,
            180,
            anchor="center",
            text="A U R U M",
            font=(FONT, 22, "bold"),
            fill=WHITE,
            tags="wordmark",
        )
        canvas.create_text(
            logo_cx,
            210,
            anchor="center",
            text="F I N A N C E",
            font=(FONT, 12),
            fill=AMBER_D,
            tags="wordmark",
        )
        canvas.create_line(
            logo_cx - self._WORDMARK_DIVIDER_HALF,
            230,
            logo_cx + self._WORDMARK_DIVIDER_HALF,
            230,
            fill=AMBER_D,
            width=1,
            tags="wordmark",
        )
        canvas.create_text(
            logo_cx,
            246,
            anchor="center",
            text=self.tagline,
            font=(FONT, 8, "bold"),
            fill=DIM,
            tags="subtitle",
        )
        canvas.create_line(
            logo_cx - self._SUBTITLE_DIVIDER_HALF,
            268,
            logo_cx + self._SUBTITLE_DIVIDER_HALF,
            268,
            fill=BORDER,
            width=1,
            tags="subtitle",
        )

    def _draw_session_overview(
        self,
        canvas: tk.Canvas,
        *,
        left_rows: list[tuple[str, str, str]],
        right_rows: list[tuple[str, str, str]],
    ) -> None:
        panel_x1 = self._CENTER_X - (self._SESSION_PANEL_W // 2)
        panel_x2 = self._CENTER_X + (self._SESSION_PANEL_W // 2)
        panel_mid = self._CENTER_X
        left_x = panel_x1 + self._SESSION_GUTTER
        right_x = panel_mid + self._SESSION_GUTTER
        row_y = self._SESSION_PANEL_Y1 + 34

        self.app._draw_panel(
            canvas,
            panel_x1,
            self._SESSION_PANEL_Y1,
            panel_x2,
            self._SESSION_PANEL_Y2,
            title="SESSION OVERVIEW",
            accent=AMBER,
            tag="splash",
        )
        canvas.create_line(
            panel_mid,
            self._SESSION_PANEL_Y1 + 18,
            panel_mid,
            self._SESSION_PANEL_Y2 - 16,
            fill=BORDER,
            width=1,
            tags="splash",
        )
        canvas.create_text(
            left_x,
            self._SESSION_PANEL_Y1 + 18,
            anchor="w",
            text="DESK",
            font=(FONT, 7, "bold"),
            fill=AMBER_D,
            tags="splash",
        )
        canvas.create_text(
            right_x,
            self._SESSION_PANEL_Y1 + 18,
            anchor="w",
            text="LINKS",
            font=(FONT, 7, "bold"),
            fill=AMBER_D,
            tags="splash",
        )
        canvas.create_line(
            left_x,
            self._SESSION_PANEL_Y1 + 22,
            panel_mid - self._SESSION_GUTTER,
            self._SESSION_PANEL_Y1 + 22,
            fill=BORDER,
            width=1,
            tags="splash",
        )
        canvas.create_line(
            right_x,
            self._SESSION_PANEL_Y1 + 22,
            panel_x2 - self._SESSION_GUTTER,
            self._SESSION_PANEL_Y1 + 22,
            fill=BORDER,
            width=1,
            tags="splash",
        )
        self.app._draw_kv_rows(
            canvas,
            left_x,
            row_y,
            left_rows,
            value_x=left_x + self._SESSION_LABEL_VALUE_GAP,
            line_h=self._SESSION_LINE_H,
            tag="splash",
        )
        self.app._draw_kv_rows(
            canvas,
            right_x,
            row_y,
            right_rows,
            value_x=right_x + self._SESSION_LABEL_VALUE_GAP,
            line_h=self._SESSION_LINE_H,
            tag="splash",
        )
