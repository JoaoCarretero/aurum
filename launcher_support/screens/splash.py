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
    _WORDMARK_DIVIDER_HALF = 124
    _SUBTITLE_DIVIDER_HALF = 196
    _SESSION_PANEL_W = 640
    _SESSION_PANEL_H = 138
    _SESSION_PANEL_Y1 = 296
    _SESSION_PANEL_Y2 = _SESSION_PANEL_Y1 + _SESSION_PANEL_H
    _SESSION_GUTTER = 24
    _SESSION_COLUMN_GAP = 20
    _SESSION_LABEL_VALUE_GAP = 114
    _SESSION_LINE_H = 19

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
        logo_cx, logo_cy = self._CENTER_X, 114
        intro_y = 286
        canvas.create_rectangle(
            352,
            70,
            568,
            90,
            outline=AMBER_D,
            fill=BG,
            width=1,
            tags="wordmark",
        )
        canvas.create_text(
            self._CENTER_X,
            80,
            anchor="center",
            text="AURUM FINANCE  ·  OPERATOR DESK",
            font=(FONT, 7, "bold"),
            fill=AMBER,
            tags="wordmark",
        )
        self.app._draw_aurum_logo(canvas, logo_cx, logo_cy, scale=34, tag="splash-logo")
        canvas.create_text(
            logo_cx,
            172,
            anchor="center",
            text="A U R U M",
            font=(FONT, 24, "bold"),
            fill=WHITE,
            tags="wordmark",
        )
        canvas.create_text(
            logo_cx,
            202,
            anchor="center",
            text="F I N A N C E",
            font=(FONT, 11, "bold"),
            fill=AMBER_D,
            tags="wordmark",
        )
        canvas.create_line(
            logo_cx - self._WORDMARK_DIVIDER_HALF,
            224,
            logo_cx + self._WORDMARK_DIVIDER_HALF,
            224,
            fill=AMBER_D,
            width=1,
            tags="wordmark",
        )
        canvas.create_text(
            logo_cx,
            242,
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
        canvas.create_text(
            self._CENTER_X,
            intro_y,
            anchor="center",
            text="Institutional operating shell for live monitoring, execution routing,",
            font=(FONT, 8),
            fill=WHITE,
            tags="subtitle",
        )
        canvas.create_text(
            self._CENTER_X,
            intro_y + 16,
            anchor="center",
            text="risk control and multi-engine supervision.",
            font=(FONT, 8),
            fill=DIM,
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
        inner_x1 = panel_x1 + self._SESSION_GUTTER
        inner_x2 = panel_x2 - self._SESSION_GUTTER
        usable_w = inner_x2 - inner_x1
        col_w = (usable_w - self._SESSION_COLUMN_GAP) // 2
        left_card_x1 = inner_x1
        left_card_x2 = left_card_x1 + col_w
        right_card_x1 = left_card_x2 + self._SESSION_COLUMN_GAP
        right_card_x2 = inner_x2
        card_y1 = self._SESSION_PANEL_Y1 + 24
        card_y2 = self._SESSION_PANEL_Y2 - 16
        row_y = card_y1 + 26

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
        self._draw_overview_column(
            canvas,
            x1=left_card_x1,
            x2=left_card_x2,
            y1=card_y1,
            y2=card_y2,
            title="DESK",
            rows=left_rows,
        )
        self._draw_overview_column(
            canvas,
            x1=right_card_x1,
            x2=right_card_x2,
            y1=card_y1,
            y2=card_y2,
            title="LINKS",
            rows=right_rows,
        )
        self.app._draw_kv_rows(
            canvas,
            left_card_x1 + 14,
            row_y,
            left_rows,
            value_x=left_card_x1 + 14 + self._SESSION_LABEL_VALUE_GAP,
            line_h=self._SESSION_LINE_H,
            tag="splash",
        )
        self.app._draw_kv_rows(
            canvas,
            right_card_x1 + 14,
            row_y,
            right_rows,
            value_x=right_card_x1 + 14 + self._SESSION_LABEL_VALUE_GAP,
            line_h=self._SESSION_LINE_H,
            tag="splash",
        )

    def _draw_overview_column(
        self,
        canvas: tk.Canvas,
        *,
        x1: int,
        x2: int,
        y1: int,
        y2: int,
        title: str,
        rows: list[tuple[str, str, str]],
    ) -> None:
        canvas.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            outline=BORDER,
            fill=BG,
            width=1,
            tags="splash",
        )
        canvas.create_line(
            x1,
            y1,
            x2,
            y1,
            fill=AMBER_D,
            width=1,
            tags="splash",
        )
        canvas.create_text(
            x1 + 14,
            y1 + 12,
            anchor="w",
            text=title,
            font=(FONT, 7, "bold"),
            fill=AMBER,
            tags="splash",
        )
        canvas.create_line(
            x1 + 14,
            y1 + 18,
            x2 - 14,
            y1 + 18,
            fill=BORDER,
            width=1,
            tags="splash",
        )
        for idx in range(1, len(rows)):
            yy = y1 + 26 + (idx * self._SESSION_LINE_H) - 8
            canvas.create_line(
                x1 + 14,
                yy,
                x2 - 14,
                yy,
                fill=DIM2,
                width=1,
                tags="splash",
            )
