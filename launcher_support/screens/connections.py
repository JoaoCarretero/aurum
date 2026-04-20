"""ConnectionsScreen for the CONNECTIONS routing hub."""
from __future__ import annotations

import tkinter as tk
from typing import Any

from core.ui.ui_palette import AMBER, AMBER_D, BG, BG2, DIM, FONT, GREEN
from launcher_support.screens.base import Screen


class ConnectionsScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any, conn: Any):
        super().__init__(parent)
        self.app = app
        self.conn = conn
        self._content: tk.Frame | None = None
        self._wheel_canvas: tk.Canvas | None = None

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
            text="CONNECTIONS",
            font=(FONT, 14, "bold"),
            fg=AMBER,
            bg=BG,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            title_wrap,
            text="Exchange, broker, data-provider and notification endpoints",
            font=(FONT, 8),
            fg=DIM,
            bg=BG,
            anchor="w",
        ).pack(anchor="w", pady=(3, 0))

        tk.Frame(outer, bg=BG2, height=6).pack(fill="x")
        tk.Frame(outer, bg=DIM, height=1).pack(fill="x", pady=(0, 12))

        self._content = tk.Frame(outer, bg=BG)
        self._content.pack(fill="both", expand=True)

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        app.h_path.configure(text="> CONNECTIONS")
        app.h_stat.configure(text="ROUTING", fg=GREEN)
        app.f_lbl.configure(text="ESC return  |  number select  |  H hub")
        app._kb("<Escape>", lambda: app._menu("main"))
        app._kb("<Key-0>", lambda: app._menu("main"))
        app._bind_global_nav()

        if self._content is None:
            return
        for child in self._content.winfo_children():
            child.destroy()

        panel = app._ui_panel_frame(
            self._content,
            "ACCESS MATRIX",
            "Configured services and setup entry points",
        )

        canvas = tk.Canvas(panel, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(panel, orient="vertical", command=canvas.yview)
        sf = tk.Frame(canvas, bg=BG)
        sf.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        window_id = canvas.create_window((0, 0), window=sf, anchor="nw")
        app._bind_canvas_window_width(canvas, window_id, pad_x=6)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(14, 0), pady=(0, 14))
        sb.pack(side="right", fill="y", padx=(0, 14), pady=(0, 14))
        self._wheel_canvas = canvas

        def _wheel(event: tk.Event) -> None:
            try:
                canvas.yview_scroll(-1 * (event.delta // 120), "units")
            except Exception:
                pass

        self._bind(canvas, "<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _wheel))
        self._bind(canvas, "<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        sections = [
            ("CRYPTO EXCHANGES", [
                ("1", "binance_futures", "Binance Futures"),
                ("2", "binance_spot", "Binance Spot"),
                ("3", "bybit", "Bybit"),
                ("4", "okx", "OKX"),
                ("5", "hyperliquid", "Hyperliquid"),
                ("6", "gate", "Gate.io"),
            ]),
            ("BROKERS", [
                ("7", "mt5", "MetaTrader 5 - Forex, CFDs, Indices"),
                ("8", "ib", "Interactive Brokers - Equities, Options"),
                ("9", "alpaca", "Alpaca - Commission-free US equities"),
            ]),
            ("DATA PROVIDERS", [
                ("A", "coinglass", "CoinGlass - OI, liquidations"),
                ("B", "glassnode", "Glassnode - on-chain"),
                ("C", "cftc", "CFTC COT - public API (no key)"),
                ("D", "fred", "FRED - macro data (no key)"),
                ("E", "yahoo", "Yahoo Finance - equities (no key)"),
            ]),
            ("NOTIFICATIONS", [
                ("T", "telegram", "Telegram Bot"),
                ("W", "discord", "Discord Webhook"),
            ]),
        ]

        for section_name, items in sections:
            sec = app._ui_section(sf, section_name)
            for key_label, provider, desc in items:
                conn = self.conn.get(provider)
                is_conn = conn.get("connected", False)
                is_public = conn.get("public", False)

                if is_conn:
                    tag = "PUBLIC API" if is_public else "CONNECTED"
                    tag_fg = BG
                    tag_bg = GREEN
                else:
                    tag = "OFFLINE"
                    tag_fg = DIM
                    tag_bg = BG2

                if provider == "binance_futures":
                    cmd = app._cfg_keys
                elif provider == "telegram":
                    cmd = app._cfg_tg
                else:
                    cmd = lambda d=desc: app.h_stat.configure(text=f"{d} - setup coming soon", fg=AMBER_D)

                app._ui_action_row(
                    sec,
                    key_label,
                    provider.upper(),
                    desc,
                    command=cmd,
                    tag=tag,
                    tag_fg=tag_fg,
                    tag_bg=tag_bg,
                    title_width=20,
                )

        app._ui_back_row(sf, lambda: app._menu("main"))

    def on_exit(self) -> None:
        canvas = self._wheel_canvas
        if canvas is not None:
            try:
                canvas.unbind_all("<MouseWheel>")
            except Exception:
                pass
        self._wheel_canvas = None
        super().on_exit()
