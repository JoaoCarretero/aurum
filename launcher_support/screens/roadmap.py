"""RoadmapScreen — capabilities the cockpit aspires to deliver.

Operator-facing roadmap. Surfaces gap analysis (institutional crypto
funds + TradFi quant cockpits vs current AURUM state) so the team
knows what is shipped, scaffolded, in flight, or still planned.

Bloomberg-terminal aesthetic — three tier tabs (institutional /
differentiator / cutting-edge), counter strip in the header, dense
table rows with sigil + name + status chip + area + summary, and a
right-side detail panel that updates on row click.
"""
from __future__ import annotations

import tkinter as tk
from typing import Any

from core.ui.ui_palette import (
    AMBER, AMBER_B, AMBER_D, BG, BG2, BG3, BORDER, CYAN, DIM, DIM2,
    FONT, GREEN, WHITE,
)
from launcher_support.roadmap_data import (
    ROADMAP, by_tier, counters, status_color_key,
)
from launcher_support.screens.base import Screen


_STATUS_COLORS: dict[str, str] = {
    "amber":   AMBER,
    "amber_b": AMBER_B,
    "cyan":    CYAN,
    "green":   GREEN,
    "dim":     DIM,
}


class RoadmapScreen(Screen):
    """Roadmap of planned + scaffolded + in-progress capabilities."""

    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent)
        self.app = app
        self._active_tier: int = 1
        self._tier_btns: dict[int, tk.Label] = {}
        self._list_frame: tk.Frame | None = None
        self._detail_frame: tk.Frame | None = None
        self._row_frames: list[tk.Frame] = []
        self._selected_id: str | None = None

    # ------------------------------------------------------------------
    # Build (called once)
    # ------------------------------------------------------------------
    def build(self) -> None:
        outer = tk.Frame(self.container, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=14)

        # HEADER --------------------------------------------------------
        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x")
        strip = tk.Frame(head, bg=BG)
        strip.pack(fill="x")
        tk.Frame(strip, bg=AMBER, width=4, height=22).pack(side="left", padx=(0, 8))
        title_wrap = tk.Frame(strip, bg=BG)
        title_wrap.pack(side="left", fill="x", expand=True)
        tk.Label(title_wrap, text="ROADMAP · COMING SOON",
                 font=(FONT, 11, "bold"), fg=AMBER, bg=BG, anchor="w"
                 ).pack(anchor="w")
        tk.Label(title_wrap,
                 text="Capabilities derived from gap analysis vs institutional "
                      "crypto funds (Talos · FalconX · Bloomberg · Two Sigma)",
                 font=(FONT, 7), fg=DIM, bg=BG, anchor="w"
                 ).pack(anchor="w", pady=(3, 0))

        # COUNTER STRIP -------------------------------------------------
        cs = counters()
        ctr = tk.Frame(head, bg=BG)
        ctr.pack(side="right")
        self._counter_chip(ctr, "TOTAL",       cs["total"],       AMBER_D)
        self._counter_chip(ctr, "PLANNED",     cs["planned"],     AMBER)
        self._counter_chip(ctr, "SCAFFOLDED",  cs["scaffolded"],  CYAN)
        self._counter_chip(ctr, "IN PROGRESS", cs["in_progress"], AMBER_B)
        if cs["done"]:
            self._counter_chip(ctr, "DONE", cs["done"], GREEN)

        tk.Frame(outer, bg=DIM2, height=1).pack(fill="x", pady=(8, 8))

        # TIER TABS -----------------------------------------------------
        tabs = tk.Frame(outer, bg=BG)
        tabs.pack(fill="x", pady=(0, 8))
        tk.Label(tabs, text="TIER", font=(FONT, 8, "bold"),
                 fg=DIM, bg=BG).pack(side="left", padx=(0, 8))
        for tier, label in (
            (1, f"1 · INSTITUTIONAL  ({cs['tier1']})"),
            (2, f"2 · DIFFERENTIATOR ({cs['tier2']})"),
            (3, f"3 · CUTTING-EDGE   ({cs['tier3']})"),
        ):
            self._tier_btns[tier] = self._tab_btn(tabs, tier, label)

        tk.Frame(outer, bg=BORDER, height=1).pack(fill="x", pady=(0, 10))

        # MAIN BODY: list (left) + detail (right) -----------------------
        body = tk.Frame(outer, bg=BG)
        body.pack(fill="both", expand=True)

        list_shell = tk.Frame(body, bg=BG2,
                              highlightbackground=BORDER,
                              highlightthickness=1)
        list_shell.pack(side="left", fill="both", expand=True,
                        padx=(0, 6))
        self._list_frame = tk.Frame(list_shell, bg=BG)
        self._list_frame.pack(fill="both", expand=True)

        detail_shell = tk.Frame(body, bg=BG2,
                                highlightbackground=BORDER,
                                highlightthickness=1, width=360)
        detail_shell.pack(side="left", fill="both", padx=(6, 0))
        detail_shell.pack_propagate(False)
        self._detail_frame = tk.Frame(detail_shell, bg=BG)
        self._detail_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self._render_detail_empty()

        # FOOTER --------------------------------------------------------
        tk.Frame(outer, bg=BORDER, height=1).pack(fill="x", pady=(10, 6))
        foot = tk.Frame(outer, bg=BG)
        foot.pack(fill="x")
        tk.Label(foot,
                 text="ESC voltar  |  1·2·3 trocar tier  |  click row para detalhes",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(side="left")
        tk.Label(foot,
                 text="single source of truth: launcher_support/roadmap_data.py",
                 font=(FONT, 7), fg=DIM2, bg=BG).pack(side="right")

        self._render_tier(1)

    # ------------------------------------------------------------------
    # Header helpers
    # ------------------------------------------------------------------
    def _counter_chip(self, parent: tk.Misc, label: str,
                      value: int, color: str) -> None:
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(side="left", padx=(8, 0))
        tk.Label(wrap, text=str(value), font=(FONT, 11, "bold"),
                 fg=color, bg=BG).pack(side="left")
        tk.Label(wrap, text=f" {label}", font=(FONT, 7),
                 fg=DIM, bg=BG).pack(side="left", padx=(2, 0))

    def _tab_btn(self, parent: tk.Misc, tier: int, label: str) -> tk.Label:
        active = (tier == self._active_tier)
        btn = tk.Label(
            parent, text=f" {label} ", font=(FONT, 8, "bold"),
            fg=BG if active else WHITE,
            bg=AMBER if active else BG2,
            cursor="hand2", padx=8, pady=2,
        )
        btn.pack(side="left", padx=(0, 4))
        btn.bind("<Button-1>", lambda e, t=tier: self._render_tier(t))
        return btn

    # ------------------------------------------------------------------
    # Tier rendering
    # ------------------------------------------------------------------
    def _render_tier(self, tier: int) -> None:
        self._active_tier = tier
        # Repaint tab styles.
        for t, btn in self._tier_btns.items():
            active = (t == tier)
            btn.configure(
                fg=BG if active else WHITE,
                bg=AMBER if active else BG2,
            )

        if self._list_frame is None:
            return
        for child in self._list_frame.winfo_children():
            child.destroy()
        self._row_frames = []

        items = by_tier(tier)
        if not items:
            tk.Label(self._list_frame,
                     text=f"No items in tier {tier}",
                     font=(FONT, 9), fg=DIM, bg=BG, anchor="w"
                     ).pack(fill="x", padx=10, pady=10)
            return

        # Column header.
        hdr = tk.Frame(self._list_frame, bg=BG)
        hdr.pack(fill="x", padx=8, pady=(6, 4))
        tk.Label(hdr, text=" ", font=(FONT, 7), bg=BG, width=3
                 ).pack(side="left")
        tk.Label(hdr, text="CAPABILITY", font=(FONT, 7, "bold"),
                 fg=DIM, bg=BG, width=24, anchor="w").pack(side="left")
        tk.Label(hdr, text="STATUS", font=(FONT, 7, "bold"),
                 fg=DIM, bg=BG, width=14, anchor="w").pack(side="left")
        tk.Label(hdr, text="AREA", font=(FONT, 7, "bold"),
                 fg=DIM, bg=BG, width=12, anchor="w").pack(side="left")
        tk.Label(hdr, text="SUMMARY", font=(FONT, 7, "bold"),
                 fg=DIM, bg=BG, anchor="w").pack(side="left", fill="x", expand=True)
        tk.Frame(self._list_frame, bg=DIM2, height=1).pack(fill="x", padx=8)

        for item in items:
            self._render_row(item)

    def _render_row(self, item: dict[str, Any]) -> None:
        if self._list_frame is None:
            return
        is_selected = (item["id"] == self._selected_id)
        row_bg = BG3 if is_selected else BG
        row = tk.Frame(self._list_frame, bg=row_bg, cursor="hand2")
        row.pack(fill="x", padx=8, pady=1)
        self._row_frames.append(row)

        status_color = _STATUS_COLORS.get(
            status_color_key(item["status"]), AMBER)

        # Sigil column.
        tk.Label(row, text=item["sigil"], font=(FONT, 11, "bold"),
                 fg=status_color, bg=row_bg, width=3
                 ).pack(side="left")
        # Name.
        tk.Label(row, text=item["name"], font=(FONT, 9, "bold"),
                 fg=WHITE, bg=row_bg, width=24, anchor="w"
                 ).pack(side="left")
        # Status chip.
        chip = tk.Label(row, text=f" {item['status']} ",
                        font=(FONT, 7, "bold"),
                        fg=BG, bg=status_color, padx=4)
        chip.pack(side="left", padx=(0, 6), pady=2)
        # Area.
        tk.Label(row, text=item["area"], font=(FONT, 8),
                 fg=DIM2, bg=row_bg, width=12, anchor="w"
                 ).pack(side="left")
        # Summary.
        tk.Label(row, text=item["summary"], font=(FONT, 8),
                 fg=DIM, bg=row_bg, anchor="w"
                 ).pack(side="left", fill="x", expand=True)

        # Bind click on the whole row tree.
        for w in (row, *row.winfo_children()):
            w.bind("<Button-1>", lambda _e, it=item: self._select(it))

    def _select(self, item: dict[str, Any]) -> None:
        self._selected_id = item["id"]
        self._render_tier(self._active_tier)
        self._render_detail(item)

    # ------------------------------------------------------------------
    # Detail panel
    # ------------------------------------------------------------------
    def _render_detail_empty(self) -> None:
        if self._detail_frame is None:
            return
        for child in self._detail_frame.winfo_children():
            child.destroy()
        tk.Label(self._detail_frame, text="DETAIL",
                 font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, anchor="w"
                 ).pack(fill="x")
        tk.Frame(self._detail_frame, bg=DIM2, height=1).pack(fill="x", pady=(4, 8))
        tk.Label(self._detail_frame,
                 text="Click a capability on the left to read the full plan, "
                      "the reference platform, and current implementation status.",
                 font=(FONT, 8), fg=DIM, bg=BG, anchor="w",
                 justify="left", wraplength=320
                 ).pack(fill="x")

    def _render_detail(self, item: dict[str, Any]) -> None:
        if self._detail_frame is None:
            return
        for child in self._detail_frame.winfo_children():
            child.destroy()

        status_color = _STATUS_COLORS.get(
            status_color_key(item["status"]), AMBER)

        # Title row with sigil.
        title_row = tk.Frame(self._detail_frame, bg=BG)
        title_row.pack(fill="x")
        tk.Label(title_row, text=item["sigil"], font=(FONT, 16, "bold"),
                 fg=status_color, bg=BG).pack(side="left", padx=(0, 8))
        title_wrap = tk.Frame(title_row, bg=BG)
        title_wrap.pack(side="left", fill="x", expand=True)
        tk.Label(title_wrap, text=item["name"], font=(FONT, 11, "bold"),
                 fg=WHITE, bg=BG, anchor="w").pack(anchor="w")
        tk.Label(title_wrap,
                 text=f"TIER {item['tier']} · {item['area']}",
                 font=(FONT, 7), fg=DIM, bg=BG, anchor="w"
                 ).pack(anchor="w", pady=(2, 0))

        # Status chip below title.
        st_row = tk.Frame(self._detail_frame, bg=BG)
        st_row.pack(fill="x", pady=(8, 8))
        tk.Label(st_row, text=f" {item['status']} ",
                 font=(FONT, 8, "bold"),
                 fg=BG, bg=status_color, padx=6, pady=2
                 ).pack(side="left")

        tk.Frame(self._detail_frame, bg=DIM2, height=1
                 ).pack(fill="x", pady=(0, 8))

        # Summary.
        tk.Label(self._detail_frame, text="SUMMARY",
                 font=(FONT, 7, "bold"), fg=AMBER_D, bg=BG, anchor="w"
                 ).pack(fill="x")
        tk.Label(self._detail_frame, text=item["summary"],
                 font=(FONT, 8), fg=WHITE, bg=BG, anchor="w",
                 justify="left", wraplength=320
                 ).pack(fill="x", pady=(2, 8))

        # Detail.
        tk.Label(self._detail_frame, text="PLAN",
                 font=(FONT, 7, "bold"), fg=AMBER_D, bg=BG, anchor="w"
                 ).pack(fill="x")
        tk.Label(self._detail_frame, text=item["detail"],
                 font=(FONT, 8), fg=DIM2, bg=BG, anchor="w",
                 justify="left", wraplength=320
                 ).pack(fill="x", pady=(2, 8))

        # Reference.
        tk.Label(self._detail_frame, text="REFERENCE",
                 font=(FONT, 7, "bold"), fg=AMBER_D, bg=BG, anchor="w"
                 ).pack(fill="x")
        tk.Label(self._detail_frame, text=item["reference"],
                 font=(FONT, 8), fg=CYAN, bg=BG, anchor="w",
                 justify="left", wraplength=320
                 ).pack(fill="x", pady=(2, 0))

    # ------------------------------------------------------------------
    # Deep-link helper
    # ------------------------------------------------------------------
    def _focus_item(self, item_id: str) -> None:
        """Switch to the item's tier and render its detail panel.

        Callable from on_enter(item_id=...) so screens like RISK can
        deep-link directly to a roadmap entry instead of dumping the
        operator on tier 1.
        """
        match = next((it for it in ROADMAP if it["id"] == item_id), None)
        if not match:
            return
        target_tier = int(match.get("tier", 1))
        self._selected_id = item_id
        self._render_tier(target_tier)
        self._render_detail(match)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def on_enter(self, **kwargs: Any) -> None:
        app = self.app
        app.h_path.configure(text="> ROADMAP")
        app.h_stat.configure(text="COMING SOON", fg=AMBER_D)
        app.f_lbl.configure(
            text="ESC voltar  |  1 tier1  |  2 tier2  |  3 tier3  |  H hub")
        app._kb("<Escape>", lambda: app._menu("main"))
        app._kb("<Key-0>", lambda: app._menu("main"))
        app._kb("<Key-1>", lambda: self._render_tier(1))
        app._kb("<Key-2>", lambda: self._render_tier(2))
        app._kb("<Key-3>", lambda: self._render_tier(3))
        app._bind_global_nav()

        item_id = kwargs.get("item_id")
        if item_id:
            self._focus_item(str(item_id))

    def on_exit(self) -> None:
        # Detail selection is screen-local; clear so the next entry
        # starts fresh.
        self._selected_id = None
