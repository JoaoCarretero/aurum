"""Sidebar institucional + detail renderer reusavel pro ENGINES LIVE cockpit.

Pure helpers (build_engine_rows, format_signal_row, format_omega_bar,
result_color_name) sao testaveis sem Tk. Render functions (render_sidebar,
render_detail) criam widgets — smoke-tested manualmente.

Design spec: docs/superpowers/specs/2026-04-18-shadow-gate-breakdown-sidebar-design.md
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EngineRow:
    """Linha da sidebar de engines. Active=True quando tem run vivo."""
    slug: str
    display: str
    active: bool
    ticks: int | None
    signals: int | None


def build_engine_rows(
    registry: list[dict],
    heartbeats: dict[str, dict],
) -> list[EngineRow]:
    """Compoe EngineRow a partir do registry de engines + heartbeats ativos.

    Args:
        registry: lista de {slug, display} — ordem preservada na UI.
        heartbeats: {slug: heartbeat_dict} apenas engines com run.

    Returns:
        list[EngineRow] na ordem do registry. Engines sem heartbeat
        retornam active=False + ticks/signals=None. Engines com heartbeat
        mas sem contadores (non-shadow) retornam active=True com
        ticks/signals=None — sidebar renderiza so ✓ sem numeros.
    """
    rows: list[EngineRow] = []
    for item in registry:
        slug = item["slug"]
        hb = heartbeats.get(slug)
        if hb:
            ticks_raw = hb.get("ticks_ok")
            signals_raw = hb.get("novel_total")
            rows.append(EngineRow(
                slug=slug,
                display=item["display"],
                active=True,
                ticks=int(ticks_raw) if ticks_raw is not None else None,
                signals=int(signals_raw) if signals_raw is not None else None,
            ))
        else:
            rows.append(EngineRow(
                slug=slug,
                display=item["display"],
                active=False,
                ticks=None,
                signals=None,
            ))
    return rows


def _format_time(ts: str) -> str:
    """Extrai HH:MM de um timestamp ISO ou string arbitrária.

    Formato full ISO ("2026-04-18T19:02:15" ou "2026-04-18 19:02:15"):
    retorna "19:02". Strings já curtas ("12:00"): retornam como estão.
    Strings date-only ("2026-04-18") não produzem hora — retornam "—"
    pra evitar output enganoso tipo "2026-".
    """
    s = str(ts).replace("T", " ")
    if len(s) >= 16 and s[13] == ":":
        return s[11:16]
    # Short-form HH:MM already — preservar se primeiro char é dígito
    # e :a quarta posição indica formato de hora.
    if len(s) >= 5 and s[2] == ":" and s[:2].isdigit():
        return s[:5]
    return "—"


def _short_symbol(sym: str) -> str:
    """BTCUSDT → BTC (strip USDT/USD suffix); preserva curtos."""
    s = str(sym or "").upper()
    for suffix in ("USDT", "USD", "BUSD"):
        if s.endswith(suffix) and len(s) > len(suffix):
            return s[: -len(suffix)]
    return s


def _short_dir(direction: str) -> str:
    d = str(direction or "").upper()
    if d in ("LONG", "BULLISH", "BULL"):
        return "L"
    if d in ("SHORT", "BEARISH", "BEAR"):
        return "S"
    return "?"


def _fmt_price(v) -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if abs(f) >= 1000:
        return f"{f:.0f}"
    if abs(f) >= 10:
        return f"{f:.2f}"
    return f"{f:.4g}"


def _fmt_rr(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.1f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_size(v) -> str:
    if v is None:
        return "—"
    try:
        return f"${float(v):.0f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_result(v) -> str:
    if v in ("WIN", "LOSS"):
        return v
    return "—"


def format_signal_row(trade: dict) -> dict[str, str]:
    """Dict → dict de strings formatados pra tabela LAST SIGNALS.

    Chaves: time, sym, dir, entry, stop, rr, size, res.
    Campos ausentes renderizam '—'.
    """
    return {
        "time": _format_time(trade.get("timestamp", "")),
        "sym": _short_symbol(trade.get("symbol", "")),
        "dir": _short_dir(trade.get("direction", "")),
        "entry": _fmt_price(trade.get("entry")),
        "stop": _fmt_price(trade.get("stop")),
        "rr": _fmt_rr(trade.get("rr")),
        "size": _fmt_size(trade.get("size")),
        "res": _fmt_result(trade.get("result")),
    }


def result_color_name(result) -> str:
    """Mapeia result → nome de cor ('GREEN' | 'RED' | 'DIM')."""
    if result == "WIN":
        return "GREEN"
    if result == "LOSS":
        return "RED"
    return "DIM"


# ─── Tk rendering ─────────────────────────────────────────────────
# Render functions criam widgets — smoke-tested manualmente via launcher.
# Pure helpers acima sao unit-tested em tests/test_engines_sidebar.py.

import tkinter as tk
from typing import Callable

from core.ui_palette import (
    AMBER, AMBER_B, BG, BG2, BORDER, DIM, DIM2, FONT, GREEN,
    PANEL, RED, WHITE,
)


_COLORS = {
    "GREEN": GREEN, "RED": RED, "DIM": DIM, "DIM2": DIM2,
    "WHITE": WHITE, "AMBER": AMBER, "AMBER_B": AMBER_B,
}


def render_sidebar(
    parent: tk.Widget,
    engines: list[EngineRow],
    selected_slug: str | None,
    on_select: Callable[[str], None],
) -> tk.Frame:
    """Sidebar lateral fixa — lista engines do registry.

    Engine active: linha clicavel com ticks/signals. Inactive: DIM2
    com '—'. Selected: highlight AMBER_B bg.
    """
    frame = tk.Frame(parent, bg=PANEL, width=180)
    frame.pack(side="left", fill="y")
    frame.pack_propagate(False)

    tk.Label(frame, text="ENGINES", fg=AMBER, bg=PANEL,
             font=(FONT, 7, "bold")).pack(anchor="w", padx=10, pady=(10, 4))
    tk.Frame(frame, bg=BORDER, height=1).pack(fill="x", padx=8)

    for row in engines:
        is_sel = row.slug == selected_slug
        bg = AMBER_B if is_sel else PANEL
        fg_marker = WHITE if is_sel else (WHITE if row.active else DIM2)
        fg_text = BG if is_sel else (WHITE if row.active else DIM2)
        marker = "▸" if is_sel else ("✓" if row.active else "○")

        item = tk.Frame(frame, bg=bg, cursor="hand2")
        item.pack(fill="x", padx=6, pady=1)

        top = tk.Frame(item, bg=bg)
        top.pack(fill="x", padx=6, pady=(4, 0))
        tk.Label(top, text=marker, fg=fg_marker, bg=bg,
                 font=(FONT, 7, "bold")).pack(side="left")
        tk.Label(top, text=f" {row.display}", fg=fg_text, bg=bg,
                 font=(FONT, 7, "bold")).pack(side="left")

        sub = tk.Frame(item, bg=bg)
        sub.pack(fill="x", padx=6, pady=(0, 4))
        if row.active:
            if row.ticks is not None and row.signals is not None:
                sub_text = f"  ✓ {row.ticks}t · {row.signals}s"
            else:
                sub_text = "  ✓"
            sub_color = DIM if not is_sel else BG
        else:
            sub_text = "  —"
            sub_color = DIM2
        tk.Label(sub, text=sub_text, fg=sub_color, bg=bg,
                 font=(FONT, 6)).pack(anchor="w")

        def _handler(_e, _slug=row.slug):
            on_select(_slug)
        item.bind("<Button-1>", _handler)
        for child in item.winfo_children():
            child.bind("<Button-1>", _handler)
            for grand in child.winfo_children():
                grand.bind("<Button-1>", _handler)

    return frame


def render_detail(
    parent: tk.Widget,
    engine_display: str,
    mode: str,
    heartbeat: dict | None,
    manifest: dict | None,
    trades: list[dict],
    on_row_click: Callable[[dict], None],
    status_badge_text: str = "",
    status_badge_color: str = DIM2,
) -> tk.Frame:
    """Detail pane flex — HEALTH / RUN INFO / LAST SIGNALS / ACTIONS.

    Usa dados crus (heartbeat dict, trade dict) — sem dependencia de
    pydantic (client side tolera shapes extendidos).
    """
    frame = tk.Frame(parent, bg=PANEL)
    frame.pack(side="left", fill="both", expand=True)

    # HEADER
    hdr = tk.Frame(frame, bg=PANEL)
    hdr.pack(fill="x", padx=12, pady=(10, 8))
    tk.Label(hdr, text=f"{engine_display} · {mode}",
             font=(FONT, 10, "bold"), fg=WHITE, bg=PANEL).pack(side="left")
    if status_badge_text:
        tk.Label(hdr, text=f"  {status_badge_text}", fg=status_badge_color,
                 bg=PANEL, font=(FONT, 7, "bold")).pack(side="left")

    if heartbeat is None:
        empty = tk.Label(frame,
                         text="(engine sem run ativo — selecione outra ou inicie)",
                         fg=DIM, bg=PANEL, font=(FONT, 8, "italic"))
        empty.pack(padx=12, pady=20, anchor="w")
        return frame

    # HEALTH
    _section_header(frame, "HEALTH")
    health = tk.Frame(frame, bg=PANEL)
    health.pack(fill="x", padx=12, pady=(0, 8))
    _pair_row(health, "ticks_ok", str(heartbeat.get("ticks_ok", "—")),
              "uptime", _uptime_from_heartbeat(heartbeat))
    _pair_row(health, "ticks_fail", str(heartbeat.get("ticks_fail", "—")),
              "novel", str(heartbeat.get("novel_total", "—")))

    # RUN INFO
    _section_header(frame, "RUN INFO")
    info = tk.Frame(frame, bg=PANEL)
    info.pack(fill="x", padx=12, pady=(0, 8))
    run_id = heartbeat.get("run_id", "—")
    commit = (manifest or {}).get("commit", "—")
    branch = (manifest or {}).get("branch", "—")
    started = heartbeat.get("started_at", "—")
    _pair_row(info, "run_id", str(run_id), "commit", str(commit))
    _pair_row(info, "started", str(started)[:19], "branch", str(branch))

    # LAST SIGNALS
    _section_header(frame, f"LAST SIGNALS  ·  click row for detail")
    signals = tk.Frame(frame, bg=PANEL)
    signals.pack(fill="both", expand=True, padx=12, pady=(0, 8))
    _render_signals_table_rich(signals, trades[-10:][::-1] if trades else [],
                               on_row_click=on_row_click)

    return frame


def _section_header(parent, title: str) -> None:
    tk.Label(parent, text=title, fg=AMBER, bg=PANEL,
             font=(FONT, 7, "bold")).pack(anchor="w", padx=12, pady=(4, 2))
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12, pady=(0, 4))


def _pair_row(parent, k1, v1, k2, v2) -> None:
    row = tk.Frame(parent, bg=PANEL)
    row.pack(fill="x", pady=(0, 2))
    tk.Label(row, text=f"{k1}:", fg=DIM2, bg=PANEL,
             font=(FONT, 7)).pack(side="left", padx=(0, 4))
    tk.Label(row, text=str(v1), fg=WHITE, bg=PANEL,
             font=(FONT, 7, "bold"), width=18, anchor="w").pack(side="left")
    tk.Label(row, text=f"{k2}:", fg=DIM2, bg=PANEL,
             font=(FONT, 7)).pack(side="left", padx=(12, 4))
    tk.Label(row, text=str(v2), fg=WHITE, bg=PANEL,
             font=(FONT, 7, "bold"), anchor="w").pack(side="left")


def _uptime_from_heartbeat(hb: dict) -> str:
    # `run_hours` no heartbeat eh o max-hours CLI arg (estatico), nao
    # elapsed. Uptime real = (stopped_at | last_tick_at | now) - started_at.
    from datetime import datetime, timezone
    started = hb.get("started_at")
    if not started:
        return "—"
    try:
        t0 = datetime.fromisoformat(str(started))
    except (TypeError, ValueError):
        return "—"
    ref = hb.get("stopped_at") or hb.get("last_tick_at")
    t1 = None
    if ref:
        try:
            t1 = datetime.fromisoformat(str(ref))
        except (TypeError, ValueError):
            t1 = None
    if t1 is None:
        t1 = datetime.now(t0.tzinfo or timezone.utc)
    secs = max(0.0, (t1 - t0).total_seconds())
    from launcher_support.engines_live_view import format_uptime
    return format_uptime(seconds=secs)


def _render_signals_table_rich(parent, trades: list[dict], on_row_click):
    """Tabela com colunas time/sym/dir/entry/stop/rr/size/res. Rows clicaveis."""
    if not trades:
        tk.Label(parent,
                 text="(sem sinais ainda — aguardando primeiros ticks)",
                 fg=DIM, bg=PANEL, font=(FONT, 7, "italic")).pack(
                     anchor="w", pady=(4, 4))
        return

    cols = [("TIME", 6), ("SYM", 5), ("DIR", 4),
            ("ENTRY", 9), ("STOP", 9), ("RR", 4),
            ("SIZE", 7), ("RES", 5)]
    hdr = tk.Frame(parent, bg=BG2)
    hdr.pack(fill="x", pady=(2, 0))
    for name, w in cols:
        tk.Label(hdr, text=name, fg=DIM2, bg=BG2,
                 font=(FONT, 6, "bold"),
                 width=w, anchor="w").pack(side="left", padx=(4, 0))

    for trade in trades:
        cells = format_signal_row(trade)
        dir_color = GREEN if cells["dir"] == "L" else RED if cells["dir"] == "S" else DIM
        res_color_name = result_color_name(trade.get("result"))
        res_color = _COLORS.get(res_color_name, DIM)

        row = tk.Frame(parent, bg=PANEL, cursor="hand2")
        row.pack(fill="x", pady=(1, 0))

        _cell(row, cells["time"], DIM, 6)
        _cell(row, cells["sym"], WHITE, 5, bold=True)
        _cell(row, cells["dir"], dir_color, 4, bold=True)
        _cell(row, cells["entry"], WHITE, 9)
        _cell(row, cells["stop"], DIM, 9)
        _cell(row, cells["rr"], WHITE, 4)
        _cell(row, cells["size"], WHITE, 7)
        _cell(row, cells["res"], res_color, 5, bold=True)

        def _click(_e, _t=trade):
            on_row_click(_t)
        row.bind("<Button-1>", _click)
        for child in row.winfo_children():
            child.bind("<Button-1>", _click)


def _cell(parent, text, fg, width, bold=False):
    font = (FONT, 6, "bold") if bold else (FONT, 6)
    tk.Label(parent, text=str(text), fg=fg, bg=PANEL, font=font,
             width=width, anchor="w").pack(side="left", padx=(4, 0))
