"""SplashScreen - pilot migration of launcher._splash."""
from __future__ import annotations

import tkinter as tk
from typing import Any

from core.ui.ui_palette import (
    AMBER, AMBER_B, AMBER_D, BG, BORDER, DIM, DIM2, FONT,
    GREEN, RED, WHITE,
)

from launcher_support.screens.base import Screen


class SplashScreen(Screen):
    # Canvas dimensions come from app._SPLASH_DESIGN_W / _H (920×640).

    # Top band + wordmark
    _CENTER_X = 460
    _TOP_RULE_Y = 30
    _BOTTOM_RULE_Y = 596
    _RULE_X1 = 48
    _RULE_X2 = 872

    _WORDMARK_BAND_Y = 46
    _WORDMARK_BAND_GAP = 78
    _LOGO_Y = 96
    _TITLE_Y = 132
    _SUBTITLE_Y = 152
    _TAGLINE_Y = 174
    _TAGLINE_DIVIDER_HALF = 170

    # Tile grid 2×3 (row 2 has wide tile in slot 2-3)
    _CONTENT_X1 = 48          # = _RULE_X1
    _CONTENT_X2 = 872         # = _RULE_X2
    _TILE_GAP = 16
    _TILE_W_SIMPLE = 264      # (824 - 2*16) / 3
    _TILE_W_WIDE = 544        # 2 simples + 1 gap
    _TILE_H = 150
    _TILE_PAD = 14
    _TILE_LINE_H = 19

    _ROW1_Y1 = 190
    _ROW1_Y2 = _ROW1_Y1 + _TILE_H       # 340
    _ROW2_Y1 = _ROW1_Y2 + _TILE_GAP     # 356
    _ROW2_Y2 = _ROW2_Y1 + _TILE_H       # 506

    _PROMPT_DIVIDER_Y = 530
    _PROMPT_Y = 552

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
            486,
            anchor="center",
            text="[ ENTER TO ACCESS DESK ]_",
            font=(FONT, 11, "bold"),
            fill=AMBER_B,
            tags="prompt2",
        )

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
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
                ("ACCOUNT", "PAPER / MULTI", WHITE),
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
        logo_cx, logo_cy = self._CENTER_X, self._LOGO_Y
        band_gap = self._TOP_BAND_GAP
        canvas.create_line(
            self._RULE_X1,
            self._TOP_BAND_Y,
            self._CENTER_X - band_gap,
            self._TOP_BAND_Y,
            fill=AMBER_D,
            width=1,
            tags="wordmark",
        )
        canvas.create_line(
            self._CENTER_X + band_gap,
            self._TOP_BAND_Y,
            self._RULE_X2,
            self._TOP_BAND_Y,
            fill=AMBER_D,
            width=1,
            tags="wordmark",
        )
        canvas.create_text(
            self._CENTER_X,
            self._TOP_BAND_Y,
            anchor="center",
            text="AURUM FINANCE",
            font=(FONT, 7, "bold"),
            fill=AMBER,
            tags="wordmark",
        )
        self.app._draw_aurum_logo(canvas, logo_cx, logo_cy, scale=22, tag="splash-logo")
        canvas.create_text(
            logo_cx,
            self._TITLE_Y,
            anchor="center",
            text="OPERATOR DESK",
            font=(FONT, 22, "bold"),
            fill=WHITE,
            tags="wordmark",
        )
        canvas.create_text(
            logo_cx,
            self._BRAND_Y,
            anchor="center",
            text="Quant operations console",
            font=(FONT, 9),
            fill=DIM2,
            tags="wordmark",
        )
        canvas.create_line(
            logo_cx - self._WORDMARK_DIVIDER_HALF,
            self._BRAND_Y + 18,
            logo_cx + self._WORDMARK_DIVIDER_HALF,
            self._BRAND_Y + 18,
            fill=AMBER_D,
            width=1,
            tags="wordmark",
        )
        canvas.create_text(
            logo_cx,
            self._BRAND_Y + 34,
            anchor="center",
            text=self.tagline,
            font=(FONT, 8),
            fill=DIM,
            tags="subtitle",
        )
        canvas.create_line(
            logo_cx - self._SUBTITLE_DIVIDER_HALF,
            self._BRAND_Y + 50,
            logo_cx + self._SUBTITLE_DIVIDER_HALF,
            self._BRAND_Y + 50,
            fill=BORDER,
            width=1,
            tags="subtitle",
        )
        canvas.create_text(
            self._CENTER_X,
            self._INTRO_Y,
            anchor="center",
            text="Live supervision, routing, and risk control for coordinated multi-engine execution.",
            font=(FONT, 8),
            fill=WHITE,
            tags="subtitle",
        )
        canvas.create_line(
            logo_cx - self._SUBTITLE_DIVIDER_HALF,
            self._INTRO_Y + self._INTRO_BLOCK_GAP + 2,
            logo_cx + self._SUBTITLE_DIVIDER_HALF,
            self._INTRO_Y + self._INTRO_BLOCK_GAP + 2,
            fill=DIM2,
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
        inner_x1 = panel_x1 + self._SESSION_GUTTER
        inner_x2 = panel_x2 - self._SESSION_GUTTER
        usable_w = inner_x2 - inner_x1
        col_w = (usable_w - self._SESSION_COLUMN_GAP) // 2
        left_col_x = inner_x1 + 12
        right_col_x = inner_x1 + col_w + self._SESSION_COLUMN_GAP + 12
        divider_x = self._CENTER_X
        header_y = self._SESSION_PANEL_Y1 + 28
        row_y = self._SESSION_PANEL_Y1 + 44

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
            divider_x,
            self._SESSION_PANEL_Y1 + 24,
            divider_x,
            self._SESSION_PANEL_Y2 - 16,
            fill=BORDER,
            width=1,
            tags="splash",
        )
        self._draw_overview_column_header(canvas, x=left_col_x, y=header_y, title="DESK")
        self._draw_overview_column_header(canvas, x=right_col_x, y=header_y, title="STATUS")
        self.app._draw_kv_rows(
            canvas,
            left_col_x,
            row_y,
            left_rows,
            value_x=left_col_x + self._SESSION_LABEL_VALUE_GAP,
            line_h=self._SESSION_LINE_H,
            tag="splash",
        )
        self.app._draw_kv_rows(
            canvas,
            right_col_x,
            row_y,
            right_rows,
            value_x=right_col_x + self._SESSION_LABEL_VALUE_GAP,
            line_h=self._SESSION_LINE_H,
            tag="splash",
        )

    def _draw_overview_column_header(
        self,
        canvas: tk.Canvas,
        *,
        x: int,
        y: int,
        title: str,
    ) -> None:
        canvas.create_text(
            x,
            y,
            anchor="w",
            text=title,
            font=(FONT, 7, "bold"),
            fill=AMBER,
            tags="splash",
        )
        canvas.create_line(
            x,
            y + 8,
            x + 244,
            y + 8,
            fill=BORDER,
            width=1,
            tags="splash",
        )
