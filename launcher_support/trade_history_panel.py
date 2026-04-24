"""Trade history list panel — clickable rows for PAPER/SHADOW cockpit panes.

Pure formatters (format_trade_row, format_r_multiple, format_duration,
resolve_exit_marker, normalize_direction) are unit-tested. Render Tk (render)
is smoke-only.

Design spec: docs/superpowers/specs/2026-04-24-cockpit-trade-history-chart-design.md
"""
from __future__ import annotations

import logging
from typing import Any, Callable

_log = logging.getLogger(__name__)


def normalize_direction(direction: str | None) -> str:
    """Normalize engine direction output to LONG/SHORT.

    BULLISH/LONG → LONG, BEARISH/SHORT → SHORT. Other non-empty values
    returned upper-case unchanged. None/empty → em-dash.
    """
    if direction is None or direction == "":
        return "—"
    d = str(direction).upper()
    if d == "BULLISH":
        return "LONG"
    if d == "BEARISH":
        return "SHORT"
    return d


def format_r_multiple(r: float | None, *, result: str) -> str:
    """Render R-multiple, or LIVE tag for open trades, or em-dash."""
    if result == "LIVE":
        return "LIVE"
    if r is None:
        return "—"
    sign = "+" if r >= 0 else "-"
    return f"{sign}{abs(r):.2f}R"


def format_duration(candles: int | None, *, tf_sec: int) -> str:
    """Render duration (candles × tf_sec) as compact string.

    Examples: 45m, 2h15m, 2d, 2d2h, <1m.
    """
    if candles is None:
        return "—"
    total_sec = int(candles) * int(tf_sec)
    if total_sec < 60:
        return "<1m"
    days, rem = divmod(total_sec, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days >= 1:
        if hours == 0:
            return f"{days}d"
        return f"{days}d{hours}h"
    if hours >= 1:
        if minutes == 0:
            return f"{hours}h"
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


_EXIT_REASON_MAP = {
    "target": "TP_HIT",
    "stop": "STOP",
    "trail": "TRAIL",
    "time": "TIME",
    "manual": "MANUAL",
}


def resolve_exit_marker(trade: dict) -> str:
    """Short label for exit reason column (TP_HIT/STOP/TRAIL/TIME/—)."""
    if trade.get("result") == "LIVE":
        return "—"
    reason = str(trade.get("exit_reason", "")).lower()
    return _EXIT_REASON_MAP.get(reason, "—")


def _format_price(p: Any) -> str:
    """Compact price string. Preserves significant digits for alt pairs."""
    if p is None:
        return "—"
    try:
        f = float(p)
    except (TypeError, ValueError):
        return str(p)[:10]
    if abs(f) >= 1000:
        return f"{f:,.2f}"
    if abs(f) >= 1:
        return f"{f:.4f}".rstrip("0").rstrip(".")
    return f"{f:.6g}"


def _format_pnl(pnl: float | None) -> str:
    if pnl is None:
        return "—"
    sign = "+" if pnl >= 0 else "-"
    return f"{sign}${abs(pnl):.2f}"


def format_trade_row(trade: dict, *, tf_sec: int) -> dict[str, str]:
    """Build a dict of display-ready fields for a single trade row.

    Keys: symbol, engine, direction, dir_arrow, levels, r_mult, pnl,
    duration, exit_marker.
    """
    direction = normalize_direction(trade.get("direction"))
    dir_arrow = "▲" if direction == "LONG" else ("▼" if direction == "SHORT" else "·")
    engine = str(trade.get("strategy") or "—")[:10]
    entry = _format_price(trade.get("entry"))
    exit_px = _format_price(trade.get("exit_p"))
    return {
        "symbol": str(trade.get("symbol") or "—")[:12],
        "engine": engine,
        "direction": direction,
        "dir_arrow": dir_arrow,
        "levels": f"{entry}→{exit_px}",
        "r_mult": format_r_multiple(trade.get("r_multiple"),
                                    result=str(trade.get("result", ""))),
        "pnl": _format_pnl(trade.get("pnl")),
        "duration": format_duration(trade.get("duration"), tf_sec=tf_sec),
        "exit_marker": resolve_exit_marker(trade),
    }


# ─── Tk render ───────────────────────────────────────────────────

def render(
    parent,
    trades: list[dict],
    *,
    on_click: Callable[[dict], None],
    colors: dict[str, str],
    font_name: str,
    tf_sec: int,
    title: str = "TRADE HISTORY",
    max_rows: int = 20,
) -> None:
    """Render a clickable trade history list into `parent`.

    `trades` newest-first. Click fires `on_click(trade_dict)`. Colors
    follows the engines_live_view palette convention (BG, PANEL, AMBER,
    GREEN, RED, WHITE, DIM, DIM2, BORDER, BG2).
    """
    import tkinter as tk

    AMBER = colors["AMBER"]
    PANEL = colors["PANEL"]
    BG = colors["BG"]
    BG2 = colors["BG2"]
    GREEN = colors["GREEN"]
    RED = colors["RED"]
    WHITE = colors["WHITE"]
    DIM = colors["DIM"]
    DIM2 = colors["DIM2"]
    BORDER = colors["BORDER"]
    AMBER_D = colors.get("AMBER_D", AMBER)

    # Header bar (matches other blocks in engines_live_view)
    box = tk.Frame(
        parent, bg=PANEL,
        highlightbackground=BORDER, highlightthickness=1,
    )
    box.pack(fill="x", pady=(0, 6))
    count = len(trades) if trades else 0
    tk.Label(
        box, text=f" {title} ({count}) ",
        font=(font_name, 7, "bold"),
        fg=BG, bg=AMBER,
    ).pack(side="top", anchor="nw", padx=8, pady=4)

    inner = tk.Frame(box, bg=PANEL)
    inner.pack(fill="x", padx=8, pady=(0, 8))

    if not trades:
        tk.Label(
            inner, text="  — no trades yet —",
            font=(font_name, 8),
            fg=DIM, bg=PANEL, anchor="w",
        ).pack(fill="x", pady=4)
        return

    shown = trades[:max_rows]
    for trade in shown:
        row_fields = format_trade_row(trade, tf_sec=tf_sec)
        row = tk.Frame(inner, bg=PANEL, cursor="hand2")
        row.pack(fill="x", pady=1)

        direction = row_fields["direction"]
        # DIM fallback: normalize_direction guarantees LONG/SHORT/em-dash
        # or uppercase-other (e.g. NEUTRAL) — non-trade directions fall
        # through to dim intentionally, no green/red signal.
        arrow_color = GREEN if direction == "LONG" else (
            RED if direction == "SHORT" else DIM)
        r_text, r_color = _color_for_r(
            row_fields["r_mult"], GREEN, RED, AMBER_D, DIM)

        # Column specs: (text, color, width, font_size, bold?)
        cols = [
            (row_fields["dir_arrow"], arrow_color, 2, 9, True),
            (row_fields["symbol"], WHITE, 12, 8, True),
            (row_fields["engine"], DIM, 10, 8, False),
            (direction, arrow_color, 7, 8, True),
            (row_fields["levels"], WHITE, 18, 8, False),
            (r_text, r_color, 8, 8, True),
        ]
        for text, color, width, fsize, bold in cols:
            weight = "bold" if bold else "normal"
            tk.Label(
                row, text=str(text), fg=color, bg=PANEL,
                font=(font_name, fsize, weight),
                width=width, anchor="w",
            ).pack(side="left", padx=(2, 0))

        pnl_text = row_fields["pnl"]
        pnl_color = GREEN if pnl_text.startswith("+$") else (
            RED if pnl_text.startswith("-$") else DIM)
        tk.Label(
            row, text=pnl_text, fg=pnl_color, bg=PANEL,
            font=(font_name, 8, "bold"), width=10, anchor="w",
        ).pack(side="left", padx=(2, 0))
        tk.Label(
            row, text=row_fields["duration"], fg=DIM, bg=PANEL,
            font=(font_name, 8), width=8, anchor="w",
        ).pack(side="left", padx=(2, 0))
        tk.Label(
            row, text=row_fields["exit_marker"], fg=DIM2, bg=PANEL,
            font=(font_name, 7), width=8, anchor="w",
        ).pack(side="left", padx=(2, 0))

        def _hover_in(_e, r=row):
            r.configure(bg=BG2)
            for child in r.winfo_children():
                try:
                    child.configure(bg=BG2)
                except tk.TclError:
                    pass  # ttk widgets or labels w/o bg option

        def _hover_out(_e, r=row):
            r.configure(bg=PANEL)
            for child in r.winfo_children():
                try:
                    child.configure(bg=PANEL)
                except tk.TclError:
                    pass

        def _click(_e, t=trade):
            try:
                on_click(t)
            except Exception:
                # Swallow so a buggy consumer can't kill the Tk mainloop,
                # but log the traceback so the operator can diagnose.
                _log.exception("trade_history_panel click handler failed")

        for widget in (row,) + tuple(row.winfo_children()):
            widget.bind("<Enter>", _hover_in)
            widget.bind("<Leave>", _hover_out)
            widget.bind("<Button-1>", _click)

    if count > max_rows:
        tk.Label(
            inner,
            text=f"  … +{count - max_rows} more (truncated)",
            font=(font_name, 7, "italic"),
            fg=DIM2, bg=PANEL, anchor="w",
        ).pack(fill="x", pady=(2, 0))


def _color_for_r(r_text: str, green: str, red: str, amber: str, dim: str) -> tuple[str, str]:
    """Return (text, color) for r_multiple column based on sign/state."""
    if r_text == "LIVE":
        return (r_text, amber)
    if r_text.startswith("+"):
        return (r_text, green)
    if r_text.startswith("-"):
        return (r_text, red)
    return (r_text, dim)
