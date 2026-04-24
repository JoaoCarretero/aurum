"""Trade history list panel — clickable rows for PAPER/SHADOW cockpit panes.

Pure formatters (format_trade_row, format_r_multiple, format_duration,
resolve_exit_marker, normalize_direction) are unit-tested. Render Tk (render)
is smoke-only.

Design spec: docs/superpowers/specs/2026-04-24-cockpit-trade-history-chart-design.md
"""
from __future__ import annotations

from typing import Any, Callable


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


# render() is defined in Task 3 below — not in this initial commit.
