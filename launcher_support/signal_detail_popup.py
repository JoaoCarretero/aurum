"""Signal detail popup — drill-down modal pra trade completo.

Pure formatters (format_omega_bar, section_*) sao unit-tested.
Render Tk (show) eh smoke-only.

Design spec: docs/superpowers/specs/2026-04-18-shadow-gate-breakdown-sidebar-design.md
"""
from __future__ import annotations

_BAR_WIDTH = 10
_BAR_FILL = "█"
_BAR_EMPTY = "░"


def format_omega_bar(value) -> str:
    """Unicode block bar de largura 10 pra valor em [0, 1]."""
    if value is None:
        return " " * _BAR_WIDTH
    try:
        f = float(value)
    except (TypeError, ValueError):
        return " " * _BAR_WIDTH
    f = max(0.0, min(1.0, f))
    filled = round(f * _BAR_WIDTH)
    return _BAR_FILL * filled + _BAR_EMPTY * (_BAR_WIDTH - filled)


def _fmt_num(v, fmt: str = "g") -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if fmt == "d":
        return f"{int(f)}"
    if fmt == "pnl":
        sign = "+" if f >= 0 else "-"
        return f"{sign}${abs(f):.2f}"
    if fmt == "usd":
        return f"${f:.2f}"
    if fmt == "price":
        if abs(f) >= 1000:
            return f"{f:.2f}"
        return f"{f:.4g}"
    return f"{f:.4g}"


def _fmt_result_value(v) -> str:
    if v in ("WIN", "LOSS"):
        return v
    return "—"


def _result_color(v) -> str:
    if v == "WIN":
        return "GREEN"
    if v == "LOSS":
        return "RED"
    return "DIM"


def _fmt_str_or_dash(v) -> str:
    if v is None or v == "":
        return "—"
    return str(v)


def _fmt_bool(v) -> str:
    if v is True:
        return "true"
    if v is False:
        return "false"
    return "—"


def section_outcome(trade: dict) -> list[tuple[str, str, str]]:
    """Return list de (label, value_str, color_name) pra seção OUTCOME."""
    return [
        ("result", _fmt_result_value(trade.get("result")),
            _result_color(trade.get("result"))),
        ("exit_reason", _fmt_str_or_dash(trade.get("exit_reason")), "WHITE"),
        ("pnl", _fmt_num(trade.get("pnl"), "pnl"),
            "GREEN" if (trade.get("pnl") or 0) >= 0 else "RED"),
        ("exit_price", _fmt_num(trade.get("exit_p"), "price"), "WHITE"),
        ("r_multiple", _fmt_num(trade.get("r_multiple")), "WHITE"),
        ("duration", _fmt_num(trade.get("duration"), "d"), "WHITE"),
    ]


def section_entry(trade: dict) -> list[tuple[str, str, str]]:
    return [
        ("entry", _fmt_num(trade.get("entry"), "price"), "WHITE"),
        ("stop", _fmt_num(trade.get("stop"), "price"), "WHITE"),
        ("target", _fmt_num(trade.get("target"), "price"), "WHITE"),
        ("rr", _fmt_num(trade.get("rr")), "WHITE"),
        ("size", _fmt_num(trade.get("size"), "usd"), "WHITE"),
        ("score", _fmt_num(trade.get("score")), "WHITE"),
    ]


def section_regime(trade: dict) -> list[tuple[str, str, str]]:
    return [
        ("macro_bias", _fmt_str_or_dash(trade.get("macro_bias")), "WHITE"),
        ("vol_regime", _fmt_str_or_dash(trade.get("vol_regime")), "WHITE"),
        ("hmm_regime", _fmt_str_or_dash(trade.get("hmm_regime")), "WHITE"),
        ("chop_trade", _fmt_bool(trade.get("chop_trade")), "WHITE"),
        ("dd_scale", _fmt_num(trade.get("dd_scale")), "WHITE"),
        ("corr_mult", _fmt_num(trade.get("corr_mult")), "WHITE"),
    ]


def section_omega(trade: dict) -> list[tuple[str, str, str]]:
    """Return list de (dim_name, value_str, bar_str) para as 5 axes."""
    dims = [
        ("struct", trade.get("omega_struct")),
        ("flow", trade.get("omega_flow")),
        ("cascade", trade.get("omega_cascade")),
        ("momentum", trade.get("omega_momentum")),
        ("pullback", trade.get("omega_pullback")),
    ]
    return [(name, _fmt_num(value), format_omega_bar(value))
            for name, value in dims]


def section_structure(trade: dict) -> list[tuple[str, str, str]]:
    return [
        ("struct", _fmt_str_or_dash(trade.get("struct")), "WHITE"),
        ("struct_str", _fmt_num(trade.get("struct_str")), "WHITE"),
        ("rsi", _fmt_num(trade.get("rsi")), "WHITE"),
        ("dist_ema21", _fmt_num(trade.get("dist_ema21")), "WHITE"),
    ]


def show(parent, trade: dict) -> None:
    """Abre Toplevel modal com drill-down do trade. Tk-only; smoke-tested."""
    raise NotImplementedError("Tk render added in Task 5")
