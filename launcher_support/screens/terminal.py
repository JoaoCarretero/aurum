"""TerminalScreen for the TERMINAL routing hub."""
from __future__ import annotations

import tkinter as tk
from typing import Any

from core.ui.ui_palette import AMBER, AMBER_D, BG, BG2, DIM, FONT
from launcher_support.screens.base import Screen


class TerminalScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent)
        self.app = app

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
            text="TERMINAL",
            font=(FONT, 14, "bold"),
            fg=AMBER,
            bg=BG,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            title_wrap,
            text="Data, charts and research routing",
            font=(FONT, 8),
            fg=DIM,
            bg=BG,
            anchor="w",
        ).pack(anchor="w", pady=(3, 0))

        tk.Frame(outer, bg=BG2, height=6).pack(fill="x")
        tk.Frame(outer, bg=DIM, height=1).pack(fill="x", pady=(0, 12))

        content = tk.Frame(outer, bg=BG)
        content.pack(fill="both", expand=True)

        app = self.app
        panel = app._ui_panel_frame(
            content,
            "RESEARCH ROUTER",
            "Available and planned market intelligence modules",
        )

        pipeline = app._ui_section(panel, "EXECUTION PIPELINE")
        app._ui_action_row(
            pipeline,
            "Y",
            "Deploy Pipeline",
            "backtest -> validated DB -> paper candidate -> cockpit",
            command=app._deploy_pipeline,
            available=True,
            tag="recommended",
            tag_fg=AMBER_D,
            tag_bg=BG2,
            title_width=22,
        )

        sections = [
            ("MARKET DATA", [
                ("1", "Price Monitor", "Watchlist ao vivo com multiplos TFs", False),
                ("2", "Orderbook Depth", "L2 data, bid/ask heatmap", False),
                ("3", "Funding Rates", "Cross-exchange funding comparison", False),
                ("4", "Liquidation Map", "Estimated liquidation levels", False),
            ]),
            ("MACRO & FUNDAMENTAL", [
                ("5", "COT Report", "CFTC Commitment of Traders", False),
                ("6", "Economic Calendar", "Fed, CPI, PMI, NFP, FOMC", False),
                ("7", "Macro Dashboard", "DXY, yields, M2, fear & greed", False),
                ("8", "Token Fundamentals", "TVL, supply, unlocks, revenue", False),
            ]),
            ("RESEARCH", [
                ("9", "Correlation Matrix", "Cross-asset correlation radar", False),
                ("A", "Regime Detector", "Current market regime (HMM/GARCH)", False),
                ("B", "Seasonality", "Hour/day/month patterns", False),
            ]),
            ("LOCAL DATA", [
                ("D", "Reports & Logs", "Browse backtest reports", True),
                ("X", "Processes", "Manage running engines", True),
            ]),
        ]

        for section_name, items in sections:
            sec = app._ui_section(panel, section_name)
            for key_label, name, desc, available in items:
                tag = None if available else "COMING SOON"
                if name == "Reports & Logs":
                    cmd = app._data
                elif name == "Processes":
                    cmd = app._procs
                elif available:
                    cmd = lambda n=name: app.h_stat.configure(text=n, fg=AMBER_D)
                else:
                    cmd = lambda n=name: app.h_stat.configure(text=f"{n} - COMING SOON", fg=DIM)
                app._ui_action_row(
                    sec,
                    key_label,
                    name,
                    desc,
                    command=cmd,
                    available=available,
                    tag=tag,
                    tag_fg=DIM,
                    tag_bg=BG2,
                    title_width=22,
                )

        app._ui_back_row(panel, lambda: app._menu("main"))

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        app.h_path.configure(text="> TERMINAL")
        app.h_stat.configure(text="DATA", fg=AMBER_D)
        app.f_lbl.configure(text="ESC voltar  |  Y deploy  |  D data  |  X procs")
        app._kb("<Escape>", lambda: app._menu("main"))
        app._kb("<Key-0>", lambda: app._menu("main"))
        app._bind_global_nav()

        for key_label, cmd in {
            "y": app._deploy_pipeline,
            "d": app._data,
            "x": app._procs,
        }.items():
            app._kb(f"<Key-{key_label}>", cmd)
