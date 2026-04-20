"""RiskScreen for the RISK routing console."""
from __future__ import annotations

import tkinter as tk
from typing import Any

from core.ui.ui_palette import AMBER, AMBER_D, BG, BG2, DIM, FONT
from launcher_support.screens.base import Screen


class RiskScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent)
        self.app = app
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
            text="RISK CONSOLE",
            font=(FONT, 14, "bold"),
            fg=AMBER,
            bg=BG,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            title_wrap,
            text="Portfolio and risk management surfaces",
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
        app.h_path.configure(text="> RISK")
        app.h_stat.configure(text="CONSOLE", fg=AMBER_D)
        app.f_lbl.configure(text="ESC voltar  |  H hub")
        app._kb("<Escape>", lambda: app._menu("main"))
        app._kb("<Key-0>", lambda: app._menu("main"))
        app._bind_global_nav()

        if self._content is None:
            return
        for child in self._content.winfo_children():
            child.destroy()

        panel = app._ui_panel_frame(
            self._content,
            "RISK ROUTER",
            "Current and planned monitoring modules",
        )
        sections = [
            (
                "PORTFOLIO",
                [
                    ("1", "Open Positions", "All active positions across venues"),
                    ("2", "P&L Today", "Real-time daily P&L"),
                    ("3", "P&L History", "Historical equity curve"),
                    ("4", "Exposure Map", "Sector/asset heatmap"),
                ],
            ),
            (
                "RISK METRICS",
                [
                    ("5", "VaR Calculator", "Value at Risk (1d, 5d, 30d)"),
                    ("6", "Drawdown Monitor", "Current DD + historical worst"),
                    ("7", "Correlation Risk", "Portfolio correlation exposure"),
                    ("8", "Kill Switch Status", "3-layer kill switch state"),
                ],
            ),
            (
                "STRESS TEST",
                [
                    ("9", "Market Crash", "-20% BTC in 1h scenario"),
                    ("A", "Liquidity Crisis", "Spread blowout + slippage spike"),
                    ("B", "Black Swan", "Custom shock parameters"),
                ],
            ),
        ]

        for section_name, items in sections:
            sec = app._ui_section(panel, section_name)
            for key_label, name, desc in items:
                app._ui_action_row(
                    sec,
                    key_label,
                    name,
                    desc,
                    available=False,
                    tag="COMING SOON",
                    tag_fg=DIM,
                    tag_bg=BG2,
                    title_width=22,
                )

        app._ui_note(panel, "Risk console modules are in development.", fg=DIM)
        app._ui_note(
            panel,
            "Backtest stress tests remain available in STRATEGIES > MILLENNIUM.",
            fg=AMBER_D,
        )
        app._ui_back_row(panel, lambda: app._menu("main"))
