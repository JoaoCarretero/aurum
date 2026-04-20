"""MainMenuScreen - ScreenManager migration for launcher._menu_main_bloomberg.

This keeps the Bloomberg desk router mounted in a cached screen container.
The canvas is created once; subsequent visits repaint the menu state without
destroying the entire legacy widget tree.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Any

from core.data.connections import MARKETS
from core.ui.ui_palette import AMBER, AMBER_B, AMBER_D, BG, BG2, BORDER, DIM, FONT, GREEN, TILE_EXECUTE, TILE_MARKETS, TILE_RESEARCH, WHITE, RED
from launcher_support.menu_data import MAIN_MENU
from launcher_support.screens.base import Screen


class MainMenuScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any, conn: Any):
        super().__init__(parent)
        self.app = app
        self.conn = conn
        self.canvas: tk.Canvas | None = None

    def build(self) -> None:
        frame = tk.Frame(self.container, bg=BG)
        frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(
            frame,
            bg=BG,
            highlightthickness=0,
            width=self.app._MENU_DESIGN_W,
            height=self.app._MENU_DESIGN_H,
        )
        self.canvas.pack(fill="both", expand=True)

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        canvas = self.canvas
        if canvas is None:
            return

        app._active_tile_slots = [
            ("nw", 192, 182),
            ("ne", 728, 182),
            ("sw", 192, 340),
            ("se", 728, 340),
        ]
        app._active_cd_center = (460, 261)
        app.h_stat.configure(text="DESK SELECT", fg=AMBER_B)
        app.h_path.configure(text="> MAIN  |  DESK ROUTER")
        app.f_lbl.configure(
            text="1-4 open desk  |  arrows navigate  |  enter select  |  esc landing"
        )

        app._menu_canvas = canvas
        app._menu_expanded_tile = None
        canvas.delete("all")

        self._bind(canvas, "<Configure>", app._render_main_menu)
        self._bind(canvas, "<Button-1>", self._canvas_click)

        if not any(app._menu_live.get(k) for k in ("markets", "execute", "research", "control")):
            app._menu_live_fetch_async()

        canvas.create_rectangle(24, 18, 896, 522, outline=AMBER_D, width=2, tags="frame")
        canvas.create_rectangle(28, 22, 892, 518, outline=BORDER, width=1, tags="frame")
        canvas.create_rectangle(32, 24, 888, 40, outline="", fill=BG2, tags="frame")
        canvas.create_line(32, 40, 888, 40, fill=AMBER, width=1, tags="frame")
        canvas.create_text(42, 32, anchor="w", text="AURUM FINANCE", font=(FONT, 8, "bold"), fill=WHITE, tags="frame")
        canvas.create_rectangle(170, 26, 260, 38, outline=AMBER, fill=BG, width=1, tags="frame")
        canvas.create_text(215, 32, anchor="center", text="MAIN MENU", font=(FONT, 8, "bold"), fill=AMBER, tags="frame")
        canvas.create_text(876, 32, anchor="e", text="DESK ROUTER / BLOOMBERG MODE", font=(FONT, 7), fill=DIM, tags="frame")
        canvas.create_line(32, 510, 888, 510, fill=AMBER_D, width=1, tags="frame")

        app._draw_panel(canvas, 52, 58, 868, 108, title="  ROUTING HEADER  ", accent=AMBER, tag="menu")

        def _col(x_lbl: int, label: str, x_val: int, value: str, value_fg: str = WHITE) -> None:
            canvas.create_text(x_lbl, 78, anchor="w", text=label, font=(FONT, 7, "bold"), fill=DIM, tags="menu")
            canvas.create_text(x_val, 78, anchor="w", text=value, font=(FONT, 9, "bold"), fill=value_fg, tags="menu")

        _col(66, "DESK", 110, "AURUM ROUTER", AMBER)
        canvas.create_text(66, 96, anchor="w", text="markets · execute · research · control", font=(FONT, 7), fill=DIM, tags="menu")
        canvas.create_line(296, 68, 296, 100, fill=app._dim_color(AMBER, 0.4), width=1, tags="menu")
        _col(310, "PROFILE", 364, "PAPER · LOCAL", GREEN)
        canvas.create_text(310, 96, anchor="w", text="operator mode · kill-switch armed", font=(FONT, 7), fill=DIM, tags="menu")
        canvas.create_line(556, 68, 556, 100, fill=app._dim_color(AMBER, 0.4), width=1, tags="menu")
        _col(570, "NAV", 604, "1-4 · ENTER · ESC", WHITE)
        canvas.create_text(570, 96, anchor="w", text="click tile · number key · esc to landing", font=(FONT, 7), fill=DIM, tags="menu")

        app._draw_cd_center(canvas, r=52)
        canvas.create_line(60, 118, 860, 118, fill=app._dim_color(AMBER, 0.3), width=1, tags="menu")
        app._draw_spokes(canvas, app._menu_focused_tile)
        for idx in range(4):
            app._draw_isometric_tile(canvas, idx, idx == app._menu_focused_tile)

        app._draw_panel(canvas, 52, 412, 868, 504, title="  SYSTEM CONTEXT  ", accent=AMBER, tag="menu")
        try:
            market_label = MARKETS.get(self.conn.active_market, {}).get("label", "UNSET")
        except Exception:
            market_label = "UNSET"
        app._draw_kv_rows(canvas, 78, 434, [
            ("ENGINE", "DESK ROUTER", TILE_MARKETS),
            ("MODE", "OPERATOR", WHITE),
            ("ACCOUNT", "PAPER", GREEN),
            ("MARKET", market_label.upper(), AMBER_B),
        ], value_x=218, line_h=16, tag="menu")
        app._draw_kv_rows(canvas, 468, 434, [
            ("BASKET", "DEFAULT", WHITE),
            ("TIMEFRAME", "15M", TILE_EXECUTE),
            ("ENVIRONMENT", "LOCAL", TILE_RESEARCH),
            ("RISK", "KILL-SWITCH ARMED", RED),
        ], value_x=630, line_h=16, tag="menu")

        for n in (1, 2, 3, 4):
            app._kb(
                f"<Key-{n}>",
                lambda _n=n - 1: (app._menu_tile_focus(_n), app._menu_tile_expand(_n)),
            )
        app._kb("<Right>", lambda: app._menu_tile_focus_delta(+1))
        app._kb("<Left>", lambda: app._menu_tile_focus_delta(-1))
        app._kb("<Down>", lambda: app._menu_tile_focus_delta(+2))
        app._kb("<Up>", lambda: app._menu_tile_focus_delta(-2))
        app._kb("<Tab>", lambda: app._menu_tile_focus_delta(+1))
        app._kb("<Return>", lambda: app._menu_tile_expand(app._menu_focused_tile))
        app._kb("<Escape>", app._splash)
        app._bind_global_nav()
        app._render_main_menu()
        self._schedule_live_refresh()
        try:
            app.focus_set()
        except Exception:
            pass

    def on_exit(self) -> None:
        super().on_exit()
        app = self.app
        aid = getattr(app, "_menu_live_after_id", None)
        if aid is not None:
            try:
                app.after_cancel(aid)
            except Exception:
                pass
        app._menu_live_after_id = None
        app._menu_canvas = None
        app._menu_expanded_tile = None

    def _canvas_click(self, event: tk.Event) -> str:
        app = self.app
        try:
            ex, ey = event.x, event.y
            hit = None
            for idx in range(4):
                x1, y1, x2, y2 = app._tile_rect(idx)
                if x1 <= ex <= x2 and y1 <= ey <= y2:
                    hit = idx
                    break
            if hit is None:
                app.h_stat.configure(text=f"NO TILE @ ({ex},{ey})", fg=AMBER_D)
                return "break"
            label = MAIN_MENU[hit][0]
            app.h_stat.configure(text=f"→ {label}", fg=AMBER_B)
            app._menu_tile_focus(hit)
            app._menu_tile_expand(hit)
            return "break"
        except Exception as exc:
            try:
                messagebox.showerror("Menu click", f"{type(exc).__name__}: {exc}")
            except Exception:
                pass
            return "break"

    def _schedule_live_refresh(self) -> None:
        app = self.app
        if self.canvas is None or app._menu_canvas is not self.canvas:
            app._menu_live_after_id = None
            return
        if getattr(app, "_menu_expanded_tile", None) is not None:
            app._menu_live_after_id = self._after(1000, self._schedule_live_refresh)
            return
        app._menu_live_fetch_async()
        app._menu_live_after_id = self._after(5000, self._schedule_live_refresh)
