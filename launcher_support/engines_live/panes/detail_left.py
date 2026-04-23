"""Left column of the ENGINE detail view.

Stacks:
1. Header       — "Detail: {ENGINE}"
2. Instances    — per-row: mode.label ●status uptime ticks/novel eq
3. Separator
4. KPIs grid    — total_equity / total_ticks / total_novel / instance_count
5. Separator
6. Instance actions   — HoldButton [STOP] + [RESTART]
7. Engine actions     — HoldButton [STOP ALL] + Button [+ NEW] + [CONFIG]

Selected instance row has bg=BG2. Unselected rows have bg=BG.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from core.ui.ui_palette import AMBER, BG, BG2, DIM, GREEN, HAZARD, RED, WHITE
from launcher_support.engines_live.widgets.hold_button import HoldButton
from launcher_support.engines_live_helpers import format_uptime


_STATUS_GLYPH = {"live": "●", "stale": "!", "error": "✕", "dead": "○"}
_STATUS_COLOR = {"live": GREEN, "stale": HAZARD, "error": RED, "dead": DIM}


def _row_text(inst: dict) -> str:
    mode = str(inst.get("mode", "?"))[:1]
    label = str(inst.get("label", ""))[:10]
    uptime = format_uptime(seconds=inst.get("uptime_s", 0))
    ticks = inst.get("ticks", 0)
    novel = inst.get("novel", 0)
    equity = inst.get("equity", 0.0)
    return f"{mode}.{label:<10} {uptime:>6} {ticks}t/{novel}nv eq {equity:.0f}"


def _render_instances(
    container: tk.Frame,
    instances: list[dict],
    selected_instance: str | None,
    on_instance_select: Callable[[str], None] | None,
) -> dict[str, tk.Frame]:
    for child in list(container.winfo_children()):
        child.destroy()

    rows: dict[str, tk.Frame] = {}
    for inst in instances:
        rid = inst["run_id"]
        is_sel = rid == selected_instance
        bg = BG2 if is_sel else BG
        row = tk.Frame(container, bg=bg)
        row.pack(fill="x", padx=4, pady=1)

        status = str(inst.get("status", "dead"))
        glyph = _STATUS_GLYPH.get(status, "?")
        color = _STATUS_COLOR.get(status, DIM)

        glyph_lbl = tk.Label(
            row, text=glyph, bg=bg, fg=color,
            font=("Consolas", 9, "bold"), width=2,
        )
        glyph_lbl.pack(side="left")

        text_lbl = tk.Label(
            row, text=_row_text(inst), bg=bg, fg=WHITE,
            font=("Consolas", 9), anchor="w",
        )
        text_lbl.pack(side="left", fill="x", expand=True)

        if on_instance_select is not None:
            row.bind("<Button-1>", lambda e, r=rid: on_instance_select(r))
            glyph_lbl.bind("<Button-1>", lambda e, r=rid: on_instance_select(r))
            text_lbl.bind("<Button-1>", lambda e, r=rid: on_instance_select(r))

        rows[rid] = row

    return rows


def _render_kpis(container: tk.Frame, kpis: dict) -> None:
    for child in list(container.winfo_children()):
        child.destroy()

    pairs = [
        ("total equity", f"${kpis.get('total_equity', 0):.0f}"),
        ("instances", f"{kpis.get('instance_count', 0)}"),
        ("ticks", f"{kpis.get('total_ticks', 0)}"),
        ("novel", f"{kpis.get('total_novel', 0)}"),
    ]
    avg_wr = kpis.get("avg_win_rate")
    if avg_wr is not None:
        pairs.append(("avg WR", f"{avg_wr*100:.0f}%"))

    for i, (k, v) in enumerate(pairs):
        r, c = divmod(i, 2)
        kl = tk.Label(container, text=k, bg=BG, fg=DIM, font=("Consolas", 9), anchor="w")
        kl.grid(row=r, column=c*2, sticky="w", padx=(8, 2))
        vl = tk.Label(container, text=v, bg=BG, fg=WHITE, font=("Consolas", 9, "bold"), anchor="w")
        vl.grid(row=r, column=c*2+1, sticky="w", padx=(0, 16))


def _hsep(parent: tk.Widget) -> tk.Frame:
    sep = tk.Frame(parent, bg=DIM, height=1)
    sep.pack(fill="x", padx=4, pady=4)
    return sep


def build_detail_left(
    parent: tk.Widget,
    engine: str,
    engine_display: str,
    instances: list[dict],
    kpis: dict,
    selected_instance: str | None,
    on_instance_select: Callable[[str], None] | None = None,
    on_stop_instance: Callable[[str], None] | None = None,
    on_restart_instance: Callable[[str], None] | None = None,
    on_stop_all: Callable[[str], None] | None = None,
    on_new_instance: Callable[[str], None] | None = None,
    on_open_config: Callable[[str], None] | None = None,
) -> tk.Frame:
    frame = tk.Frame(parent, bg=BG)

    # 1) Header
    header = tk.Frame(frame, bg=BG)
    header.pack(fill="x", padx=8, pady=(6, 4))
    tk.Label(
        header, text=f"Detail: {engine_display}", bg=BG, fg=AMBER,
        font=("Consolas", 11, "bold"), anchor="w",
    ).pack(side="left")

    # 2) Instances
    instances_frame = tk.Frame(frame, bg=BG)
    instances_frame.pack(fill="x", padx=4)
    rows = _render_instances(instances_frame, instances, selected_instance, on_instance_select)

    _hsep(frame)

    # 4) KPIs
    kpis_frame = tk.Frame(frame, bg=BG)
    kpis_frame.pack(fill="x", padx=4)
    _render_kpis(kpis_frame, kpis)

    _hsep(frame)

    # 6) Instance actions
    inst_actions = tk.Frame(frame, bg=BG)
    inst_actions.pack(fill="x", padx=4, pady=2)

    def _wrap_selected(cb):
        def _handler():
            rid = frame._selected_instance
            if rid is not None and cb is not None:
                cb(rid)
        return _handler

    stop_btn = HoldButton(
        inst_actions, text="STOP", hold_ms=1500,
        on_complete=_wrap_selected(on_stop_instance),
    )
    stop_btn.pack(side="left", padx=(0, 4))

    restart_btn = HoldButton(
        inst_actions, text="RESTART", hold_ms=1500,
        on_complete=_wrap_selected(on_restart_instance),
    )
    restart_btn.pack(side="left", padx=(0, 4))

    # 7) Engine actions
    eng_actions = tk.Frame(frame, bg=BG)
    eng_actions.pack(fill="x", padx=4, pady=2)

    def _call_engine(cb):
        def _h():
            if cb is not None:
                cb(engine)
        return _h

    stop_all = HoldButton(
        eng_actions, text="STOP ALL", hold_ms=1500,
        on_complete=_call_engine(on_stop_all),
    )
    stop_all.pack(side="left", padx=(0, 4))

    new_btn = tk.Button(
        eng_actions, text="[+] NEW", bg=BG, fg=AMBER,
        font=("Consolas", 9, "bold"), bd=0, cursor="hand2",
        command=_call_engine(on_new_instance),
    )
    new_btn.pack(side="left", padx=(0, 4))

    cfg_btn = tk.Button(
        eng_actions, text="[C]ONFIG", bg=BG, fg=DIM,
        font=("Consolas", 9, "bold"), bd=0, cursor="hand2",
        command=_call_engine(on_open_config),
    )
    cfg_btn.pack(side="left")

    # Stash
    frame._engine = engine
    frame._engine_display = engine_display
    frame._selected_instance = selected_instance
    frame._instances_frame = instances_frame
    frame._kpis_frame = kpis_frame
    frame._instance_rows = rows
    frame._on_instance_select = on_instance_select
    return frame


def update_detail_left(
    frame: tk.Frame,
    instances: list[dict],
    kpis: dict,
    selected_instance: str | None,
) -> None:
    frame._selected_instance = selected_instance
    frame._instance_rows = _render_instances(
        frame._instances_frame, instances, selected_instance,
        getattr(frame, "_on_instance_select", None),
    )
    _render_kpis(frame._kpis_frame, kpis)
