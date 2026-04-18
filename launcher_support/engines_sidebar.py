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
        retornam active=False + ticks/signals=None.
    """
    rows: list[EngineRow] = []
    for item in registry:
        slug = item["slug"]
        hb = heartbeats.get(slug)
        if hb:
            rows.append(EngineRow(
                slug=slug,
                display=item["display"],
                active=True,
                ticks=int(hb.get("ticks_ok", 0) or 0),
                signals=int(hb.get("novel_total", 0) or 0),
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
    """Extrai HH:MM de um timestamp ISO ou string arbitrária."""
    s = str(ts).replace("T", " ")
    if len(s) >= 16 and s[13] == ":":
        return s[11:16]
    return s[:5]


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
