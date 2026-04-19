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


def _tradingview_url(symbol) -> str | None:
    # Perp symbol na Binance USDT-M -> BINANCE:<SYM>.P. Aceita 'BTCUSDT'
    # ou 'BTC/USDT'. Retorna None se nao da pra formar URL confiavel.
    if not symbol:
        return None
    sym = str(symbol).replace("/", "").replace("-", "").upper().strip()
    if not sym.endswith("USDT") or len(sym) < 6:
        return None
    return f"https://www.tradingview.com/chart/?symbol=BINANCE:{sym}.P&interval=60"


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
    # notional = size (qty tokens) * entry (preço). risk = stop_dist * size.
    size = trade.get("size")
    entry = trade.get("entry")
    stop = trade.get("stop")
    try:
        notional = float(size) * float(entry)
        notional_str = f"${notional:,.0f}"
    except (TypeError, ValueError):
        notional_str = "—"
    try:
        risk = abs(float(entry) - float(stop)) * float(size)
        risk_str = f"${risk:,.2f}"
    except (TypeError, ValueError):
        risk_str = "—"
    return [
        ("entry", _fmt_num(trade.get("entry"), "price"), "WHITE"),
        ("stop", _fmt_num(trade.get("stop"), "price"), "WHITE"),
        ("target", _fmt_num(trade.get("target"), "price"), "WHITE"),
        ("rr", _fmt_num(trade.get("rr")), "WHITE"),
        ("size (qty)", _fmt_num(trade.get("size")), "DIM"),
        ("notional", notional_str, "WHITE"),
        ("risk @ stop", risk_str, "AMBER"),
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


def _build_body(container, trade: dict) -> None:
    """Pinta as 5 seções (OUTCOME/ENTRY/REGIME/OMEGA/STRUCTURE) dentro
    de `container`. Mesma formatação usada pelo popup antigo e pelo
    inline renderer — compartilha section_* helpers."""
    import tkinter as tk
    from core.ui_palette import (
        AMBER, BORDER, DIM, DIM2, FONT, GREEN, PANEL, RED, WHITE,
    )

    COLORS = {
        "GREEN": GREEN, "RED": RED, "DIM": DIM, "DIM2": DIM2,
        "WHITE": WHITE, "AMBER": AMBER,
    }

    def _section(title: str, rows: list[tuple[str, str, str]]) -> None:
        tk.Label(container, text=title, fg=AMBER, bg=PANEL,
                 font=(FONT, 7, "bold")).pack(anchor="w", padx=12, pady=(8, 2))
        tk.Frame(container, bg=BORDER, height=1).pack(
            fill="x", padx=12, pady=(0, 4))
        inner = tk.Frame(container, bg=PANEL)
        inner.pack(fill="x", padx=12, pady=(0, 2))
        for label, value, color_name in rows:
            row = tk.Frame(inner, bg=PANEL)
            row.pack(fill="x", pady=(0, 1))
            tk.Label(row, text=f"{label}:", fg=DIM2, bg=PANEL,
                     font=(FONT, 7), width=14, anchor="w").pack(side="left")
            tk.Label(row, text=str(value),
                     fg=COLORS.get(color_name, WHITE), bg=PANEL,
                     font=(FONT, 7, "bold"), anchor="w").pack(side="left")

    def _omega_section() -> None:
        tk.Label(container, text="OMEGA 5D", fg=AMBER, bg=PANEL,
                 font=(FONT, 7, "bold")).pack(anchor="w", padx=12, pady=(8, 2))
        tk.Frame(container, bg=BORDER, height=1).pack(
            fill="x", padx=12, pady=(0, 4))
        inner = tk.Frame(container, bg=PANEL)
        inner.pack(fill="x", padx=12, pady=(0, 2))
        for dim_name, value_str, bar in section_omega(trade):
            row = tk.Frame(inner, bg=PANEL)
            row.pack(fill="x", pady=(0, 1))
            tk.Label(row, text=f"{dim_name}:", fg=DIM2, bg=PANEL,
                     font=(FONT, 7), width=12, anchor="w").pack(side="left")
            tk.Label(row, text=value_str, fg=WHITE, bg=PANEL,
                     font=(FONT, 7, "bold"), width=6,
                     anchor="w").pack(side="left")
            tk.Label(row, text=bar, fg=AMBER, bg=PANEL,
                     font=(FONT, 7)).pack(side="left", padx=(4, 0))

    _section("OUTCOME", section_outcome(trade))
    _section("ENTRY", section_entry(trade))
    _section("REGIME", section_regime(trade))
    _omega_section()
    _section("STRUCTURE", section_structure(trade))


def render_inline(parent, trade: dict, on_close) -> "tk.Frame":  # noqa: F821
    """Render trade detail INLINE dentro do detail pane do cockpit —
    sem popup separado. Retorna o Frame host.

    Contém header compacto (sym · dir · time · X fechar · OPEN CHART se
    USDT), as 5 seções (OUTCOME/ENTRY/REGIME/OMEGA/STRUCTURE), e um botão
    CLOSE DETAIL no final. `on_close` eh chamado sem args quando o user
    pede pra fechar o detail — host decide o que fazer (limpar state e
    rerender)."""
    import tkinter as tk
    from core.ui_palette import (
        AMBER, AMBER_B, BG, BG2, BORDER, DIM2, FONT, PANEL, WHITE,
    )

    symbol = trade.get("symbol", "?")
    direction = str(trade.get("direction", "?"))
    time_str = str(trade.get("timestamp", "?")).replace("T", " ")[:16]

    # Card envolvente pra dar separação visual entre a signals table e
    # o drill-down — operador vê "isso é um zoom, não uma linha nova".
    frame = tk.Frame(parent, bg=PANEL,
                     highlightbackground=AMBER_B, highlightthickness=1)
    frame.pack(fill="x", padx=12, pady=(4, 8))

    # Header com title + X close à direita + OPEN CHART quando aplica
    hdr = tk.Frame(frame, bg=BG2)
    hdr.pack(fill="x")
    tk.Label(hdr, text="  TRADE DETAIL", fg=AMBER, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="left", padx=(8, 0), pady=4)
    tk.Label(hdr, text=f"  {symbol}  ·  {direction}  ·  {time_str}",
             fg=WHITE, bg=BG2, font=(FONT, 7, "bold")).pack(
                 side="left", pady=4)

    close_btn = tk.Label(hdr, text="  ✕  ", fg=BG, bg=DIM2,
                         font=(FONT, 7, "bold"), cursor="hand2",
                         padx=6, pady=2)
    close_btn.pack(side="right", padx=(0, 6), pady=3)
    close_btn.bind("<Button-1>", lambda _e: on_close())

    chart_url = _tradingview_url(symbol)
    if chart_url:
        def _open_chart(_e=None) -> None:
            import webbrowser
            webbrowser.open(chart_url)
        chart_btn = tk.Label(hdr, text="  OPEN CHART  ", fg=BG, bg=AMBER,
                             font=(FONT, 7, "bold"), cursor="hand2",
                             padx=6, pady=2)
        chart_btn.pack(side="right", padx=(0, 4), pady=3)
        chart_btn.bind("<Button-1>", _open_chart)

    _build_body(frame, trade)
    return frame


def show(parent, trade: dict) -> None:
    """(legacy) Abre Toplevel modal com detail completo do trade. Mantido
    pra compat; preferir `render_inline` pro cockpit shadow."""
    import tkinter as tk
    from core.ui_palette import AMBER, BG, DIM2, FONT, PANEL, WHITE

    symbol = trade.get("symbol", "?")
    direction = trade.get("direction", "?")
    time_str = str(trade.get("timestamp", "?")).replace("T", " ")[:16]

    top = tk.Toplevel(parent)
    top.title(f"Trade detail — {symbol}")
    top.configure(bg=PANEL)
    top.geometry("520x640")

    hdr = tk.Frame(top, bg=PANEL)
    hdr.pack(fill="x", padx=16, pady=(14, 6))
    tk.Label(hdr,
             text=f"{symbol}  ·  {direction}  ·  {time_str}",
             fg=WHITE, bg=PANEL, font=(FONT, 11, "bold")).pack(anchor="w")

    _build_body(top, trade)

    close_row = tk.Frame(top, bg=PANEL)
    close_row.pack(fill="x", padx=16, pady=(16, 12))
    close_btn = tk.Label(close_row, text="  ESC close  ", fg=BG, bg=DIM2,
                         font=(FONT, 7, "bold"), cursor="hand2",
                         padx=8, pady=4)
    close_btn.pack(side="right")
    close_btn.bind("<Button-1>", lambda _e: top.destroy())

    chart_url = _tradingview_url(symbol)
    if chart_url:
        def _open_chart(_e=None) -> None:
            import webbrowser
            webbrowser.open(chart_url)
        chart_btn = tk.Label(close_row, text="  OPEN CHART  ", fg=BG, bg=AMBER,
                             font=(FONT, 7, "bold"), cursor="hand2",
                             padx=8, pady=4)
        chart_btn.pack(side="right", padx=(0, 8))
        chart_btn.bind("<Button-1>", _open_chart)
    top.bind("<Escape>", lambda _e: top.destroy())
    top.transient(parent)
    top.grab_set()
    top.focus_set()
