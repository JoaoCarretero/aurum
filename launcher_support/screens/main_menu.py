"""MainMenuScreen for the Bloomberg-style launcher desk router.

This migrates ``App._menu_main_bloomberg`` to the ScreenManager pattern:
widgets are built once, the canvas is reused across visits, and only the
menu state is repainted on re-entry.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Any

from core.data.connections import MARKETS
from core.ui.ui_palette import (
    AMBER,
    AMBER_B,
    AMBER_D,
    BG,
    BG2,
    BORDER,
    DIM,
    FONT,
    TILE_CONTROL,
    TILE_EXECUTE,
    TILE_MARKETS,
    TILE_RESEARCH,
    WHITE,
)
from launcher_support.menu_data import main_groups
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

        # Tiles maiores — layout spread-out pra preencher o espaco que abriu
        # com a remocao dos paineis DESK OVERVIEW / ACTIVE CONTEXT.
        app._active_tile_slots = [
            ("nw", 192, 170),
            ("ne", 728, 170),
            ("sw", 192, 370),
            ("se", 728, 370),
        ]
        app._active_cd_center = (460, 270)
        app._menu_render_scale = 1.0
        app.h_stat.configure(text="DESK SELECT", fg=AMBER_B)
        app.h_path.configure(text="> MAIN  |  DESK ROUTER")
        app.f_lbl.configure(
            text="1-4 open desk  |  arrows navigate  |  enter select  |  esc landing"
        )

        app._menu_canvas = canvas
        app._menu_expanded_tile = None
        # Expose the screen so launcher._menu_tile_expand_impl can redraw
        # chrome from a clean scale-1 state (see draw_chrome docstring).
        app._main_menu_screen = self
        canvas.delete("all")

        self._bind(canvas, "<Configure>", app._render_main_menu)
        self._bind(canvas, "<Button-1>", self._canvas_click)

        if not any(
            app._menu_live.get(key) for key in ("markets", "execute", "research", "control")
        ):
            app._menu_live_fetch_async()

        self.draw_chrome()

        app._draw_cd_center(canvas, r=52)
        self.redraw_tiles()

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

    def draw_chrome(self) -> None:
        """Draw the persistent frame chrome at design (scale-1) coords.

        Used by on_enter and by _menu_tile_expand_impl after the latter
        clears the canvas. Keeping one drawing path guarantees the chrome
        and any content drawn alongside share the same coordinate system,
        so _render_main_menu scales them together.
        """
        canvas = self.canvas
        if canvas is None:
            return
        try:
            market_label = MARKETS.get(self.conn.active_market, {}).get("label", "UNSET")
        except Exception:
            market_label = "UNSET"
        canvas.create_rectangle(24, 18, 896, 522, outline=AMBER_D, width=2, tags="frame")
        canvas.create_rectangle(28, 22, 892, 518, outline=BORDER, width=1, tags="frame")
        canvas.create_rectangle(32, 24, 888, 42, outline="", fill=BG2, tags="frame")
        canvas.create_line(32, 42, 888, 42, fill=AMBER, width=1, tags="frame")
        canvas.create_text(
            42, 33, anchor="w", text="AURUM FINANCE",
            font=(FONT, 8, "bold"), fill=WHITE, tags="frame",
        )
        canvas.create_text(
            460, 33, anchor="center", text="DESK ROUTER",
            font=(FONT, 8, "bold"), fill=AMBER, tags="frame",
        )
        canvas.create_text(
            876, 33, anchor="e",
            text=f"PAPER  ·  {market_label.upper()}  ·  15M  ·  KILL-SW ARMED",
            font=(FONT, 7, "bold"), fill=DIM, tags="frame",
        )
        canvas.create_line(32, 504, 888, 504, fill=AMBER_D, width=1, tags="frame")

    def redraw_tiles(self) -> None:
        app = self.app
        canvas = self.canvas
        if canvas is None or app._menu_canvas is not canvas:
            return
        if getattr(app, "_menu_expanded_tile", None) is not None:
            return
        canvas.delete("spokes")
        for idx in range(4):
            canvas.delete(f"tile{idx}")
        app._draw_spokes(canvas, app._menu_focused_tile)
        for idx in range(4):
            app._draw_isometric_tile(canvas, idx, idx == app._menu_focused_tile)

    def _canvas_click(self, event: tk.Event) -> str:
        app = self.app
        groups = self._main_groups()
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
            label = groups[hit][0]
            app.h_stat.configure(text=f"-> {label}", fg=AMBER_B)
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

    def _main_groups(self) -> list[tuple[str, str, str, list[tuple[str, str]]]]:
        return main_groups(
            MARKETS,
            TILE_MARKETS,
            TILE_EXECUTE,
            TILE_RESEARCH,
            TILE_CONTROL,
        )
