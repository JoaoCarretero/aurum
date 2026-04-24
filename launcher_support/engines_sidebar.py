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


def _fmt_notional(size, entry) -> str:
    """Size (qty de tokens) * entry (preço) = $ notional. Mostra $XXX ou
    $X.Xk pra compactar. Faltando qualquer ponta → '—'."""
    if size is None or entry is None:
        return "—"
    try:
        n = float(size) * float(entry)
    except (TypeError, ValueError):
        return "—"
    if abs(n) >= 10000:
        return f"${n/1000:.1f}k"
    if abs(n) >= 1000:
        return f"${n:,.0f}"
    return f"${n:.0f}"


def _fmt_result(v) -> str:
    if v in ("WIN", "LOSS"):
        return v
    return "—"


def format_signal_row(trade: dict) -> dict[str, str]:
    """Dict → dict de strings formatados pra tabela LAST SIGNALS.

    Chaves: time, sym, dir, entry, stop, rr, notional, res.
    `notional` = size (qty de tokens) * entry (preço) em $ — a leitura
    que importa pra um operador. Campos ausentes renderizam '—'.
    """
    return {
        "time": _format_time(trade.get("timestamp", "")),
        "sym": _short_symbol(trade.get("symbol", "")),
        "dir": _short_dir(trade.get("direction", "")),
        "entry": _fmt_price(trade.get("entry")),
        "stop": _fmt_price(trade.get("stop")),
        "rr": _fmt_rr(trade.get("rr")),
        "notional": _fmt_notional(trade.get("size"), trade.get("entry")),
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

from core.ui.ui_palette import (
    AMBER, AMBER_B, BG, BG2, BORDER, DIM, DIM2, FONT, GREEN,
    PANEL, RED, WHITE,
)


_COLORS = {
    "GREEN": GREEN, "RED": RED, "DIM": DIM, "DIM2": DIM2,
    "WHITE": WHITE, "AMBER": AMBER, "AMBER_B": AMBER_B,
}


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
    selected_trade: dict | None = None,
    on_close_detail: Callable[[], None] | None = None,
    account_snapshot: dict | None = None,
    open_positions: list[dict] | None = None,
    equity_series: list[float] | None = None,
    on_stop_paper: Callable[[], None] | None = None,
    on_flatten_paper: Callable[[], None] | None = None,
) -> tk.Frame:
    """HL2/CS 1.6 institutional cockpit detail pane.

    Layout (top → bottom):

        ┌───────────────────────────────────────────────────┐
        │ ● MILLENNIUM  SHADOW · RUNNING · TUNNEL UP · run… │
        ├───────────────────────────────────────────────────┤
        │ TICKS · FAIL · SIGNALS · UP · LAST · [+3 paper]   │
        ├───────────────────────────────────────────────────┤
        │ mode-specific blocks (account + positions + eq +  │
        │ metrics for paper; signal feed for shadow)        │
        ├───────────────────────────────────────────────────┤
        │ [■ STOP] [↻ RESTART] [⟳ REFRESH]                 │
        └───────────────────────────────────────────────────┘

    Contract preserved so existing callers keep working; body rebuilt
    for density. Every section defensively handles missing/partial data
    so a slow tunnel never crashes the pane.
    """
    frame = tk.Frame(parent, bg=PANEL)
    frame.pack(side="left", fill="both", expand=True)

    _hl2_header(frame, engine_display, mode, status_badge_text,
                status_badge_color, heartbeat)

    if heartbeat is None:
        _hl2_empty(frame, status_badge_text)
        return frame

    _hl2_telemetry_strip(frame, heartbeat, trades, mode, account_snapshot)

    # Secoes enriquecidas — mostram a saude OPERACIONAL do pipeline
    # que a strip de telemetria basica nao captura. Error banner em
    # vermelho se last_error != null; SCAN funnel (scanned/dedup/stale/
    # live/opened) mostra onde o pipeline de sinais perde candidatos;
    # PROBE DIAGNOSTIC so aparece quando engine == PROBE.
    _hl2_error_banner(frame, heartbeat)
    _hl2_scan_section(frame, heartbeat)
    _hl2_probe_section(frame, heartbeat, engine_display)

    if mode == "paper":
        _hl2_paper_body(frame, heartbeat, account_snapshot,
                        open_positions or [], equity_series or [],
                        trades, on_row_click, selected_trade,
                        on_close_detail)
        # Paper mode's body packs every sub-section with fill="x" only —
        # without this trailing spacer, empty PANEL below the last
        # metric/signal card reads as a dead cut-off zone. The spacer
        # absorbs that leftover vertical space so the pane fills cleanly.
        tk.Frame(frame, bg=PANEL).pack(fill="both", expand=True)
    else:
        _hl2_shadow_body(frame, trades, on_row_click, selected_trade,
                         on_close_detail)

    _hl2_actions_bar(frame, mode, on_stop_paper, on_flatten_paper)
    return frame


# ── HL2 building blocks ────────────────────────────────────────────

def _hl2_header(parent: tk.Widget, engine_display: str, mode: str,
                status_text: str, status_color: str,
                heartbeat: dict | None) -> None:
    """Black bar: pulse dot · engine · mode chip · status · run_id."""
    bar = tk.Frame(parent, bg=BG, highlightbackground=BORDER,
                   highlightthickness=0)
    bar.pack(fill="x")
    inner = tk.Frame(bar, bg=BG)
    inner.pack(fill="x", padx=10, pady=7)

    is_running = "RUNNING" in (status_text or "").upper()
    dot_color = GREEN if is_running else DIM2
    tk.Label(inner, text="●", fg=dot_color, bg=BG,
             font=(FONT, 12)).pack(side="left", padx=(0, 6))
    tk.Label(inner, text=engine_display.upper(),
             fg=WHITE, bg=BG, font=(FONT, 11, "bold")).pack(side="left")
    tk.Label(inner, text=f"  {mode.upper()}",
             fg=AMBER, bg=BG, font=(FONT, 8, "bold")).pack(side="left")

    if status_text:
        tk.Label(inner, text="  ·  ", fg=DIM2, bg=BG,
                 font=(FONT, 7)).pack(side="left")
        tk.Label(inner, text=status_text, fg=status_color, bg=BG,
                 font=(FONT, 7, "bold")).pack(side="left")

    if heartbeat is not None:
        rid = str(heartbeat.get("run_id") or "")
        if rid:
            tk.Label(inner, text=f"  ·  run {rid}", fg=DIM, bg=BG,
                     font=(FONT, 7)).pack(side="left")

    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")


def _hl2_empty(parent: tk.Widget, status_text: str) -> None:
    box = tk.Frame(parent, bg=PANEL)
    box.pack(fill="both", expand=True, padx=16, pady=20)
    tk.Label(box, text="— NO RUN VISIBLE —",
             fg=DIM, bg=PANEL, font=(FONT, 10, "bold")).pack(anchor="w")
    tk.Label(box,
             text=("Engine sem run ativo. Pode ser tunnel offline,\n"
                   "runner parado, ou primeira execução. Abra ACTIONS\n"
                   "abaixo pra START ou REFRESH."),
             fg=DIM2, bg=PANEL, font=(FONT, 7),
             justify="left", anchor="w").pack(anchor="w", pady=(6, 0))
    if status_text:
        tk.Label(box, text=f"status: {status_text}",
                 fg=DIM2, bg=PANEL, font=(FONT, 7, "italic")).pack(
                     anchor="w", pady=(6, 0))


def _hl2_telemetry_strip(parent: tk.Widget, hb: dict, trades: list[dict],
                         mode: str, account: dict | None) -> None:
    """One horizontal strip, 5–8 cells — all key numbers at a glance."""
    strip = tk.Frame(parent, bg=PANEL)
    strip.pack(fill="x", padx=10, pady=(8, 4))

    ticks_ok = hb.get("ticks_ok")
    ticks_fail = int(hb.get("ticks_fail") or 0)
    novel_raw = hb.get("novel_since_prime")
    if novel_raw is None:
        novel_raw = hb.get("novel_total")
    novel_n = int(novel_raw or 0)

    _hl2_cell(strip, "TICKS",
              "—" if ticks_ok is None else str(ticks_ok),
              GREEN if (ticks_ok or 0) > 0 else DIM2)
    _hl2_cell(strip, "FAIL", str(ticks_fail),
              RED if ticks_fail > 0 else DIM2)
    _hl2_cell(strip, "SIGNALS",
              "—" if novel_raw is None else str(novel_raw),
              AMBER_B if novel_n > 0 else DIM2)
    _hl2_cell(strip, "UPTIME", _uptime_from_heartbeat(hb), WHITE)
    last_text, last_color = _last_sig_age(trades, hb)
    _hl2_cell(strip, "LAST SIG", last_text, last_color)

    if mode == "paper" and account is not None:
        eq = float(account.get("equity") or 0.0)
        dd_pct = float(account.get("drawdown_pct") or 0.0)
        realized = float(account.get("realized_pnl") or 0.0)
        unrealized = float(account.get("unrealized_pnl") or 0.0)
        net = realized + unrealized
        initial = float(account.get("initial_balance") or eq or 1.0)
        eq_color = GREEN if eq >= initial else RED
        dd_color = DIM2 if dd_pct < 2.0 else (AMBER if dd_pct < 5.0 else RED)
        net_color = GREEN if net >= 0 else RED
        sign = "+" if net >= 0 else "-"
        _hl2_cell(strip, "EQUITY", f"${eq:,.0f}", eq_color)
        _hl2_cell(strip, "DD", f"-{dd_pct:.1f}%", dd_color)
        _hl2_cell(strip, "NET", f"{sign}${abs(net):,.0f}", net_color)


def _hl2_error_banner(parent: tk.Widget, hb: dict) -> None:
    """Banner vermelho compacto quando heartbeat.last_error != null.

    Fica entre a strip de telemetria e as secoes de conteudo — operador
    ve falha de tick imediatamente, sem precisar abrir log tail.
    """
    err = hb.get("last_error")
    if not err:
        return
    bar = tk.Frame(parent, bg=BG, highlightbackground=RED,
                   highlightthickness=1)
    bar.pack(fill="x", padx=10, pady=(4, 2))
    tk.Label(bar, text="LAST ERROR", fg=RED, bg=BG,
             font=(FONT, 6, "bold")).pack(anchor="w", padx=6, pady=(3, 0))
    tk.Label(bar, text=str(err)[:280], fg=RED, bg=BG,
             font=(FONT, 7), anchor="w", justify="left",
             wraplength=560).pack(anchor="w", padx=6, pady=(0, 3))


def _hl2_scan_section(parent: tk.Widget, hb: dict) -> None:
    """SCAN funnel — scanned -> dedup -> stale -> live -> opened.

    Mostra onde o pipeline perde candidatos na ultima tick. Quando
    operador ve novel=0 por horas, essa secao responde "o pipeline
    ta escaneando?" — se scanned=0, nenhum sinal ta chegando aos
    filtros; se scanned=N e live=0, filtros vetaram tudo.
    """
    keys = ("last_scan_scanned", "last_scan_dedup",
            "last_scan_stale", "last_scan_live")
    if all(hb.get(k) is None for k in keys) and not hb.get("last_novel_at"):
        return

    _hl2_section(parent, "SCAN", extra="last tick funnel")
    strip = tk.Frame(parent, bg=PANEL)
    strip.pack(fill="x", padx=10, pady=(0, 4))

    scanned = int(hb.get("last_scan_scanned") or 0)
    dedup = int(hb.get("last_scan_dedup") or 0)
    stale = int(hb.get("last_scan_stale") or 0)
    live = int(hb.get("last_scan_live") or 0)
    opened = hb.get("last_scan_opened")

    _hl2_cell(strip, "SCANNED", str(scanned),
              WHITE if scanned > 0 else DIM2)
    _hl2_cell(strip, "DEDUP", str(dedup),
              DIM2 if dedup == 0 else WHITE)
    _hl2_cell(strip, "STALE", str(stale),
              DIM2 if stale == 0 else AMBER)
    _hl2_cell(strip, "LIVE", str(live),
              GREEN if live > 0 else DIM2)
    if opened is not None:
        _hl2_cell(strip, "OPENED", str(int(opened or 0)),
                  GREEN if (opened or 0) > 0 else DIM2)


def _hl2_probe_section(parent: tk.Widget, hb: dict,
                       engine_display: str) -> None:
    """PROBE DIAGNOSTIC — so quando engine == PROBE.

    top_score vs threshold colorido (GREEN >= thr, AMBER_B >= 80%,
    AMBER >= 60%, DIM2 abaixo) + top_symbol + direction + macro + n_above_*.
    Quando engines reais estao com novel=0, probe responde "pipeline
    vendo mercado?" — top_score ~0.15 = mercado morto, ~0.55 =
    mercado ativo mas filtrado, >= threshold = sinal iminente.
    """
    if str(engine_display).upper() != "PROBE":
        return
    top = hb.get("top_score")
    if top is None:
        return

    try:
        top_f = float(top)
        thr = float(hb.get("threshold") or 0.62)
        mean = float(hb.get("mean_score") or 0.0)
    except (TypeError, ValueError):
        return
    n_thr = int(hb.get("n_above_threshold") or 0)
    n_80 = int(hb.get("n_above_80pct") or 0)
    n_60 = int(hb.get("n_above_60pct") or 0)

    top_color = (GREEN if top_f >= thr else
                 AMBER_B if top_f >= thr * 0.8 else
                 AMBER if top_f >= thr * 0.6 else DIM2)

    top_sym = str(hb.get("top_symbol") or "—")
    top_dir = str(hb.get("top_direction") or "—")
    macro = str(hb.get("macro") or "—")
    _hl2_section(parent, "PROBE DIAGNOSTIC",
                 extra=f"macro {macro} · thr {thr:.3f}")
    strip = tk.Frame(parent, bg=PANEL)
    strip.pack(fill="x", padx=10, pady=(0, 4))

    _hl2_cell(strip, "TOP", f"{top_f:.3f}", top_color)
    _hl2_cell(strip, "TOP SYM", top_sym[:10], WHITE)
    _hl2_cell(strip, "DIR", top_dir[:6], AMBER)
    _hl2_cell(strip, "MEAN", f"{mean:.3f}", WHITE)
    _hl2_cell(strip, ">THR", str(n_thr),
              GREEN if n_thr > 0 else DIM2)
    _hl2_cell(strip, ">80%", str(n_80),
              AMBER_B if n_80 > 0 else DIM2)
    _hl2_cell(strip, ">60%", str(n_60),
              AMBER if n_60 > 0 else DIM2)


def _hl2_cell(parent: tk.Widget, label: str, value: str, color: str) -> None:
    """HL2 telemetry cell — 2 lines, sharp border, equal-width flex.

    Label font 6 -> 7 (usuario reportou "letras minusculas" no cockpit).
    Value mantido em 10 bold — ja visivel e consome espaco vertical.
    """
    cell = tk.Frame(parent, bg=BG, highlightbackground=BORDER,
                    highlightthickness=1)
    cell.pack(side="left", fill="both", expand=True, padx=(0, 3))
    tk.Label(cell, text=label.upper(), fg=DIM2, bg=BG,
             font=(FONT, 7, "bold")).pack(anchor="w", padx=6, pady=(4, 0))
    tk.Label(cell, text=str(value), fg=color, bg=BG,
             font=(FONT, 10, "bold")).pack(anchor="w", padx=6, pady=(0, 4))


def _hl2_section(parent: tk.Widget, title: str,
                 extra: str | None = None) -> None:
    """Tight section header: caps title + thin amber underline."""
    row = tk.Frame(parent, bg=PANEL)
    row.pack(fill="x", padx=10, pady=(8, 1))
    tk.Label(row, text=title.upper(), fg=AMBER, bg=PANEL,
             font=(FONT, 7, "bold")).pack(side="left")
    if extra:
        tk.Label(row, text=f"  ·  {extra}", fg=DIM, bg=PANEL,
                 font=(FONT, 7)).pack(side="left")
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=10, pady=(0, 2))


def _hl2_paper_body(parent: tk.Widget, hb: dict, account: dict | None,
                    positions: list[dict], equity_series: list[float],
                    trades: list[dict],
                    on_row_click: Callable[[dict], None],
                    selected_trade: dict | None,
                    on_close_detail: Callable[[], None] | None) -> None:
    """POSITIONS · EQUITY CURVE + METRICS · SIGNALS (opt)."""
    # POSITIONS table
    _hl2_section(parent, "POSITIONS",
                 extra=f"{len(positions)} open · KS {hb.get('ks_state','NORMAL')}")
    if positions:
        _hl2_positions_table(parent, positions)
    else:
        tk.Label(parent, text="   — nenhuma posição aberta —",
                 fg=DIM2, bg=PANEL, font=(FONT, 7, "italic")).pack(
                     anchor="w", padx=12, pady=(2, 4))

    # EQUITY + METRICS (one compact block)
    if account is not None:
        _hl2_section(parent, "EQUITY + METRICS")
        _hl2_equity_metrics(parent, account, equity_series)

    # TRADE HISTORY — closed-trade feed (newest first) so the operator
    # sees what happened to positions that cycled through. Always renders
    # the section so an empty state is explicit instead of silent.
    if selected_trade is not None:
        from launcher_support.signal_detail_popup import render_inline
        _hl2_section(parent, "TRADE DETAIL  ·  click ✕ to close")
        render_inline(parent, selected_trade,
                      on_close_detail or (lambda: None))
    else:
        extra = (f"{len(trades)} closed · click row for detail"
                 if trades else "aguardando primeiro trade fechado")
        _hl2_section(parent, "TRADE HISTORY", extra=extra)
        if trades:
            sig_box = tk.Frame(parent, bg=PANEL)
            sig_box.pack(fill="x", padx=10, pady=(0, 6))
            _render_signals_table_rich(sig_box, trades[-6:][::-1], on_row_click)
        else:
            tk.Label(parent, text="   — nenhum trade fechado ainda —",
                     fg=DIM2, bg=PANEL, font=(FONT, 7, "italic")).pack(
                         anchor="w", padx=12, pady=(2, 6))


def _hl2_shadow_body(parent: tk.Widget, trades: list[dict],
                     on_row_click: Callable[[dict], None],
                     selected_trade: dict | None,
                     on_close_detail: Callable[[], None] | None) -> None:
    """Shadow = signal feed is the whole story."""
    if selected_trade is not None:
        from launcher_support.signal_detail_popup import render_inline
        _hl2_section(parent, "TRADE DETAIL  ·  click ✕ to close")
        render_inline(parent, selected_trade,
                      on_close_detail or (lambda: None))
        return

    extra = f"{len(trades)} recent" if trades else "aguardando primeiros novels"
    _hl2_section(parent, "SIGNAL FEED", extra=extra)
    sig_box = tk.Frame(parent, bg=PANEL)
    sig_box.pack(fill="both", expand=True, padx=10, pady=(0, 6))
    _render_signals_table_rich(sig_box,
                               trades[-12:][::-1] if trades else [],
                               on_row_click)


def _hl2_positions_table(parent: tk.Widget, positions: list[dict]) -> None:
    """Dense positions table: SYM · DIR · ENTRY · NOTIONAL · PNL · BARS."""
    box = tk.Frame(parent, bg=PANEL)
    box.pack(fill="x", padx=10, pady=(1, 4))
    cols = [("SYM", 9), ("DIR", 5), ("ENTRY", 10), ("STOP", 10),
            ("TGT", 10), ("NOT$", 10), ("PNL", 9), ("B", 3)]
    hdr = tk.Frame(box, bg=BG)
    hdr.pack(fill="x")
    for label, w in cols:
        tk.Label(hdr, text=label, fg=DIM2, bg=BG,
                 font=(FONT, 6, "bold"), width=w,
                 anchor="w").pack(side="left", padx=(3, 0))
    tk.Frame(box, bg=BORDER, height=1).pack(fill="x")
    for p in positions[:8]:
        row = tk.Frame(box, bg=PANEL)
        row.pack(fill="x")
        dir_raw = str(p.get("direction", ""))
        if dir_raw.upper().startswith(("BULL", "LONG")):
            dir_s, dir_color = "LONG", GREEN
        elif dir_raw.upper().startswith(("BEAR", "SHORT")):
            dir_s, dir_color = "SHORT", RED
        else:
            dir_s, dir_color = dir_raw[:5], DIM
        u = float(p.get("unrealized_pnl") or 0.0)
        u_color = GREEN if u >= 0 else RED
        entry = float(p.get("entry_price") or 0.0)
        stop = float(p.get("stop") or 0.0)
        tgt = float(p.get("target") or 0.0)
        notional = float(p.get("notional") or 0.0)
        cells = [
            (str(p.get("symbol", "?"))[:9], WHITE, 9, "bold"),
            (dir_s, dir_color, 5, "bold"),
            (f"{entry:.5g}", WHITE, 10, "normal"),
            (f"{stop:.5g}", DIM, 10, "normal"),
            (f"{tgt:.5g}", DIM, 10, "normal"),
            (f"${notional:,.0f}", WHITE, 10, "normal"),
            (f"{u:+.1f}", u_color, 9, "bold"),
            (str(p.get("bars_held", 0)), DIM, 3, "normal"),
        ]
        for text, color, w, weight in cells:
            tk.Label(row, text=text, fg=color, bg=PANEL,
                     font=(FONT, 7, weight), width=w,
                     anchor="w").pack(side="left", padx=(3, 0))


def _hl2_equity_metrics(parent: tk.Widget, account: dict,
                        equity_series: list[float]) -> None:
    """Sparkline + metrics in a single tight block."""
    box = tk.Frame(parent, bg=PANEL)
    box.pack(fill="x", padx=10, pady=(1, 6))
    if equity_series:
        try:
            from tools.operations.paper_metrics import sparkline
            spark = sparkline(equity_series[-120:])
        except Exception:
            spark = ""
        lo_v = min(equity_series) if equity_series else 0.0
        hi_v = max(equity_series) if equity_series else 0.0
        line = tk.Frame(box, bg=PANEL)
        line.pack(fill="x", pady=(1, 0))
        tk.Label(line, text="EQUITY", fg=DIM2, bg=PANEL,
                 font=(FONT, 6, "bold")).pack(side="left")
        tk.Label(line, text=f"  {spark}  ", fg=GREEN, bg=PANEL,
                 font=(FONT, 9)).pack(side="left")
        tk.Label(line, text=f"lo ${lo_v:,.0f}  ·  hi ${hi_v:,.0f}",
                 fg=DIM, bg=PANEL,
                 font=(FONT, 6)).pack(side="left", padx=(6, 0))
    m = account.get("metrics") or {}
    wr = float(m.get("win_rate") or 0.0) * 100
    pf = float(m.get("profit_factor") or 0.0)
    sharpe = float(m.get("sharpe") or 0.0)
    maxdd = float(m.get("maxdd") or 0.0)
    roi = float(m.get("roi_pct") or 0.0)
    n_trades = int(m.get("n_trades") or 0)
    mrow = tk.Frame(box, bg=PANEL)
    mrow.pack(fill="x", pady=(3, 0))
    _metric_card_compact(mrow, "TRADES", str(n_trades), WHITE)
    _metric_card_compact(mrow, "WR", f"{wr:.0f}%",
                         GREEN if wr >= 50 else (RED if wr > 0 else DIM2))
    _metric_card_compact(mrow, "PF", f"{pf:.2f}",
                         GREEN if pf >= 1.5 else (RED if pf > 0 else DIM2))
    _metric_card_compact(mrow, "SHARPE", f"{sharpe:.2f}", WHITE)
    _metric_card_compact(mrow, "MAXDD", f"${maxdd:,.0f}",
                         RED if maxdd > 0 else DIM2)
    _metric_card_compact(mrow, "ROI", f"{roi:+.2f}%",
                         GREEN if roi >= 0 else RED)


def _hl2_actions_bar(parent: tk.Widget, mode: str,
                     on_stop: Callable[[], None] | None,
                     on_flatten: Callable[[], None] | None) -> None:
    """Bottom bar com chips. STOP PAPER foi removido pra não ocupar
    espaço — controle heavy (parar runner) vive via systemctl no VPS.
    FLATTEN ALL fica porque é outra ação (zerar posições sem parar
    o runner). ``on_stop`` é ignorado; mantido na signature pra
    compatibilidade com callers antigos."""
    del on_stop  # deprecado — chip STOP PAPER removido do cockpit
    if not (mode == "paper" and on_flatten):
        return
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(4, 0))
    bar = tk.Frame(parent, bg=BG)
    bar.pack(fill="x")
    inner = tk.Frame(bar, bg=BG)
    inner.pack(fill="x", padx=10, pady=6)
    chip = tk.Label(inner, text="  ↻ FLATTEN ALL  ", fg=BG, bg=AMBER,
                    font=(FONT, 7, "bold"), cursor="hand2",
                    padx=8, pady=3)
    chip.pack(side="left")
    chip.bind("<Button-1>", lambda _e: on_flatten())


def _section_header(parent, title: str) -> None:
    tk.Label(parent, text=title, fg=AMBER, bg=PANEL,
             font=(FONT, 7, "bold")).pack(anchor="w", padx=12, pady=(4, 2))
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12, pady=(0, 4))


def _metric_card(parent, label: str, value: str, color: str) -> None:
    # Card institucional: label dim pequeno em cima, valor grande colorido
    # embaixo. Cresce pra preencher a linha (expand=True).
    box = tk.Frame(parent, bg=BG2, highlightbackground=BORDER,
                   highlightthickness=1)
    box.pack(side="left", fill="x", expand=True, padx=(0, 4))
    tk.Label(box, text=label, fg=DIM2, bg=BG2,
             font=(FONT, 6, "bold")).pack(anchor="w", padx=8, pady=(5, 1))
    tk.Label(box, text=str(value), fg=color, bg=BG2,
             font=(FONT, 11, "bold")).pack(anchor="w", padx=8, pady=(0, 6))


def _metric_card_compact(parent, label: str, value: str, color: str) -> None:
    """Compact variant: smaller padding, smaller value font. Designed for
    paper mode where screen real estate is tight and 5+ metrics share a row."""
    box = tk.Frame(parent, bg=BG2, highlightbackground=BORDER,
                   highlightthickness=1)
    box.pack(side="left", fill="x", expand=True, padx=(0, 3))
    tk.Label(box, text=label, fg=DIM2, bg=BG2,
             font=(FONT, 6, "bold")).pack(anchor="w", padx=4, pady=(2, 0))
    tk.Label(box, text=str(value), fg=color, bg=BG2,
             font=(FONT, 9, "bold")).pack(anchor="w", padx=4, pady=(0, 2))


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


def _last_sig_age(trades: list[dict],
                  heartbeat: dict | None = None) -> tuple[str, str]:
    """Idade do ultimo sinal detectado AO VIVO pelo shadow. Retorna
    (texto, cor).

    Fonte primaria: `heartbeat.last_novel_at` (setado pelo runner APENAS
    quando notify=True, i.e. apos first_tick prime). Se ausente (runner
    antigo pre-primed-flag), filtra `trades` excluindo `primed=True` e
    pega o ultimo. Com tudo vazio → '—' + 'primed only' como cor DIM2.

    Verde < 1h, amber < 6h, dim >= 6h.
    """
    from datetime import datetime, timezone

    raw: str | None = None
    if heartbeat is not None:
        hv = heartbeat.get("last_novel_at")
        if hv:
            raw = str(hv)

    if raw is None and trades:
        # Fallback: filtra primed records (se o runner marcou a flag) e
        # pega o ultimo nao-primed. Runner antigo nao marcava → todos
        # records contam (retorna timestamp cru do universo).
        non_primed = [t for t in trades if not t.get("primed", False)]
        pool = non_primed if non_primed else trades
        last = pool[-1]
        hv = last.get("shadow_observed_at") or last.get("timestamp")
        if hv:
            raw = str(hv)

    if raw is None:
        return "—", DIM2
    try:
        t = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "—", DIM2
    now = datetime.now(t.tzinfo or timezone.utc)
    delta = (now - t).total_seconds()
    if delta < 0:
        return "now", GREEN
    if delta < 60:
        return f"{int(delta)}s", GREEN
    if delta < 3600:
        return f"{int(delta/60)}m", GREEN
    hours = delta / 3600.0
    color = GREEN if hours < 1 else (AMBER_B if hours < 6 else DIM2)
    if hours < 24:
        return f"{hours:.1f}h", color
    return f"{int(hours/24)}d", DIM2


def _uptime_from_heartbeat(hb: dict) -> str:
    # Uptime = (stopped_at if parado) - started_at | now - started_at se
    # running. `last_tick_at` NÃO é o fim do uptime — tick acontece a cada
    # 15min, e o serviço fica vivo entre ticks. Usar last_tick_at congela o
    # display em "10s" imediatamente após o primeiro tick.
    from datetime import datetime, timezone
    started = hb.get("started_at")
    if not started:
        return "—"
    try:
        t0 = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "—"
    status = str(hb.get("status") or "").lower()
    stopped = hb.get("stopped_at")
    t1 = None
    if status != "running" and stopped:
        try:
            t1 = datetime.fromisoformat(str(stopped).replace("Z", "+00:00"))
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
        # Centered in the available vertical space. Without expand=True
        # the empty-state label glues itself to the top of sig_box and
        # the rest of the pane reads as a dead zone.
        tk.Label(parent,
                 text="(sem sinais ainda — aguardando primeiros ticks)",
                 fg=DIM, bg=PANEL, font=(FONT, 7, "italic")).pack(
                     expand=True)
        return

    cols = [("TIME", 6), ("SYM", 5), ("DIR", 4),
            ("ENTRY", 9), ("STOP", 9), ("RR", 4),
            ("NOTIONAL", 8), ("RES", 5)]
    hdr = tk.Frame(parent, bg=BG2)
    hdr.pack(fill="x", pady=(2, 0))
    # Barra vazia pra alinhar com o accent bar das rows abaixo
    tk.Frame(hdr, bg=BG2, width=3).pack(side="left")
    for name, w in cols:
        tk.Label(hdr, text=name, fg=DIM2, bg=BG2,
                 font=(FONT, 7, "bold"),
                 width=w, anchor="w").pack(side="left", padx=(4, 0))

    # Trade mais recente = primeiro da lista (chamador ja reversed).
    for i, trade in enumerate(trades):
        cells = format_signal_row(trade)
        dir_color = GREEN if cells["dir"] == "L" else RED if cells["dir"] == "S" else DIM
        res_color_name = result_color_name(trade.get("result"))
        res_color = _COLORS.get(res_color_name, DIM)
        is_latest = i == 0

        row = tk.Frame(parent, bg=PANEL, cursor="hand2")
        row.pack(fill="x", pady=(1, 0))
        # Accent bar amber no sinal mais recente — marca "fresh"
        accent = AMBER_B if is_latest else PANEL
        tk.Frame(row, bg=accent, width=3).pack(side="left", fill="y")

        _cell(row, cells["time"], DIM, 6)
        _cell(row, cells["sym"], WHITE, 5, bold=True)
        _cell(row, cells["dir"], dir_color, 4, bold=True)
        _cell(row, cells["entry"], WHITE, 9)
        _cell(row, cells["stop"], DIM, 9)
        _cell(row, cells["rr"], WHITE, 4)
        _cell(row, cells["notional"], WHITE, 8)
        _cell(row, cells["res"], res_color, 5, bold=True)

        def _click(_e, _t=trade):
            on_row_click(_t)
        row.bind("<Button-1>", _click)
        for child in row.winfo_children():
            child.bind("<Button-1>", _click)


def _cell(parent, text, fg, width, bold=False):
    font = (FONT, 7, "bold") if bold else (FONT, 7)
    tk.Label(parent, text=str(text), fg=fg, bg=PANEL, font=font,
             width=width, anchor="w").pack(side="left", padx=(4, 0))
