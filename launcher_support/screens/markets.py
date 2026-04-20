"""MarketsScreen for market routing selection."""
from __future__ import annotations

import tkinter as tk
from typing import Any

from core.data.connections import MARKETS
from core.ui.ui_palette import AMBER, AMBER_D, BG, BG2, DIM, DIM2, FONT, GREEN, WHITE
from launcher_support.screens.base import Screen


class MarketsScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any, conn: Any):
        super().__init__(parent)
        self.app = app
        self.conn = conn
        self._content: tk.Frame | None = None

    def build(self) -> None:
        outer = tk.Frame(self.container, bg=BG)
        outer.pack(fill="both", expand=True, padx=28, pady=18)

        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x", pady=(0, 12))
        strip = tk.Frame(head, bg=BG)
        strip.pack(fill="x")
        tk.Frame(strip, bg=AMBER, width=4, height=28).pack(side="left", padx=(0, 8))

        title_wrap = tk.Frame(strip, bg=BG)
        title_wrap.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_wrap,
            text="MARKETS",
            font=(FONT, 14, "bold"),
            fg=AMBER,
            bg=BG,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            title_wrap,
            text="Select active market routing and environment context",
            font=(FONT, 8),
            fg=DIM,
            bg=BG,
            anchor="w",
        ).pack(anchor="w", pady=(3, 0))

        tk.Frame(outer, bg=BG2, height=6).pack(fill="x")
        tk.Frame(outer, bg=DIM2, height=1).pack(fill="x", pady=(0, 12))

        self._content = tk.Frame(outer, bg=BG)
        self._content.pack(fill="both", expand=True)

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        app.h_path.configure(text="> MARKETS")
        app.h_stat.configure(text="SELECT", fg=AMBER_D)
        app.f_lbl.configure(text="ESC return  |  ENTER keep current  |  H hub")
        app._kb("<Escape>", lambda: app._menu("main"))
        app._kb("<Key-0>", lambda: app._menu("main"))
        app._kb("<Return>", lambda: app._menu("main"))
        app._bind_global_nav()

        if self._content is None:
            return
        for child in self._content.winfo_children():
            child.destroy()

        panel = app._ui_panel_frame(
            self._content,
            "MARKET ROUTER",
            "Routing contexts, venue clusters and dashboard entry points",
        )

        summary = tk.Frame(panel, bg=BG)
        summary.pack(fill="x", padx=10, pady=(0, 8))
        current_label = MARKETS.get(self.conn.active_market, {}).get("label", "?")
        tk.Label(
            summary,
            text=f"ACTIVE  {current_label}",
            font=(FONT, 8, "bold"),
            fg=AMBER_D,
            bg=BG,
        ).pack(side="left")
        tk.Label(
            summary,
            text=f"  ROUTES  {len(MARKETS)}",
            font=(FONT, 8),
            fg=DIM,
            bg=BG,
        ).pack(side="left", padx=(12, 0))
        tk.Frame(panel, bg=DIM2, height=1).pack(fill="x", padx=10, pady=(0, 8))

        for idx, (market_key, info) in enumerate(MARKETS.items(), start=1):
            is_active = market_key == self.conn.active_market
            available = info["available"]
            row, name_lbl, desc_lbl = app._ui_action_row(
                panel,
                str(idx),
                info["label"],
                info["desc"],
                available=available,
                tag=("ACTIVE" if is_active else ("COMING SOON" if not available else "OPEN")),
                tag_fg=(BG if is_active else (DIM if not available else BG)),
                tag_bg=(GREEN if is_active else (BG2 if not available else AMBER_D)),
                title_width=18,
            )

            if available:
                def sel_market(_event=None, key=market_key, was_active=is_active, name=name_lbl) -> None:
                    self.conn.active_market = key
                    if key == "crypto_futures":
                        app._crypto_dashboard()
                    else:
                        app._markets()

                for widget in (row, name_lbl, desc_lbl):
                    widget.bind("<Button-1>", sel_market)
                    widget.bind("<Enter>", lambda _e, n=name_lbl: n.configure(fg=AMBER))
                    widget.bind(
                        "<Leave>",
                        lambda _e, n=name_lbl, a=is_active: n.configure(fg=AMBER if a else WHITE),
                    )
                app._kb(f"<Key-{idx}>", sel_market)
            else:
                def show_coming(_event=None, label=info["label"]) -> None:
                    app.h_stat.configure(text=f"{label} | COMING SOON", fg=AMBER_D)

                for widget in (row, name_lbl, desc_lbl):
                    widget.bind("<Button-1>", show_coming)
                app._kb(f"<Key-{idx}>", show_coming)

        app._ui_note(panel, "[enter] keep current    [0] return", fg=DIM)
        app._ui_back_row(panel, lambda: app._menu("main"))
