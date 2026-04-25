"""Render helpers para os 9 blocos da EngineDetailScreen.

Cada `render_*_block(parent, run)` recebe um Tk widget pai e a
RunSummary, pinta a seção, e retorna None. Skipa graceful (sem
levantar) se faltarem campos.

Blocos:
  ❶ render_triage_block       — last_error + freshness + integrity
  ❷ render_cadence_block      — tick drift + uptime + primed/ks_state
  ❸ render_scan_funnel_block  — scanned→dedup→stale→live→opened (Task 5)
  ❹ render_decisions_block    — last 30 signals com REASON (Task 5)
  ❺ render_positions_block    — open positions (Task 6)
  ❺ render_equity_block       — equity now/peak/dd (Task 6)
  ❻ render_trades_block       — closed trades full audit + footer (Task 7)
  ❼ render_freshness_block    — bar age per symbol (Task 8)
  ❽ render_log_tail_block     — last 200 lines + filter (Task 8)
  ❾ render_aderencia_block    — match% vs backtest (Task 9)
"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime, timezone

from core.ui.ui_palette import (
    AMBER, AMBER_D, BG, BORDER, DIM, DIM2, FONT, GREEN, RED, WHITE,
)
from launcher_support.runs_history import RunSummary


# ─── Layout helpers ─────────────────────────────────────────────────


def _block_header(parent: tk.Widget, label: str) -> None:
    """H2 8pt bold + horizontal rule. Pattern from runs_history._render_block_header."""
    bar = tk.Frame(parent, bg=BG)
    bar.pack(fill="x", pady=(14, 4))
    tk.Label(bar, text=label, font=(FONT, 8, "bold"),
             fg=DIM, bg=BG, anchor="w").pack(side="left", padx=(0, 8))
    tk.Frame(bar, bg=BORDER, height=1).pack(side="left", fill="x", expand=True)


def _kv_row(parent: tk.Widget, k: str, v: str, vfg: str = WHITE) -> None:
    """key:value row; key DIM, value white-or-color. 7pt body."""
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", padx=12, pady=1)
    tk.Label(row, text=f"  {k}", font=(FONT, 7), fg=DIM, bg=BG,
             width=24, anchor="w").pack(side="left")
    tk.Label(row, text=v, font=(FONT, 7, "bold"), fg=vfg, bg=BG,
             anchor="w").pack(side="left")


def _format_age(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        secs = int((datetime.now(timezone.utc) - t).total_seconds())
        if secs < 60:
            return f"{secs}s ago"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            h, m = divmod(secs // 60, 60)
            return f"{h}h{m:02d}m ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return str(iso)[:16]


# ─── Block ❶ TRIAGE ─────────────────────────────────────────────────


def render_triage_block(parent: tk.Widget, run: RunSummary) -> None:
    """❶ TRIAGE — algo quebrou agora?

    Renderiza last_error banner em vermelho (se houver), freshness do
    heartbeat, status do serviço, e integridade do run_dir.
    """
    _block_header(parent, "❶ TRIAGE")
    hb = run.heartbeat or {}
    last_err = hb.get("last_error")

    if last_err:
        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill="x", padx=12, pady=(2, 6))
        tk.Label(bar, text="LAST ERROR", font=(FONT, 8, "bold"),
                 fg=RED, bg=BG, anchor="w").pack(anchor="w")
        tk.Label(bar, text=str(last_err)[:600], font=(FONT, 7),
                 fg=RED, bg=BG, anchor="w", justify="left",
                 wraplength=900).pack(anchor="w", pady=(2, 0))
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12)

    age = _format_age(run.last_tick_at)
    tick_sec = hb.get("tick_sec") or 900
    fresh_color = WHITE
    try:
        if run.last_tick_at:
            t = datetime.fromisoformat(str(run.last_tick_at).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - t).total_seconds()
            if elapsed > 4 * tick_sec:
                fresh_color = RED
            elif elapsed > 2 * tick_sec:
                fresh_color = AMBER
    except Exception:
        pass

    _kv_row(parent, "heartbeat freshness", age, fresh_color)
    _kv_row(parent, "service status", run.status,
            GREEN if run.status == "running" else (
                AMBER if run.status == "stale" else DIM))


# ─── Block ❷ CADENCE ────────────────────────────────────────────────


def render_cadence_block(parent: tk.Widget, run: RunSummary) -> None:
    """❷ TICK CADENCE — engine alive?

    Mostra tick_sec esperado vs real, uptime, primed/ks_state.
    """
    _block_header(parent, "❷ TICK CADENCE")
    hb = run.heartbeat or {}

    tick_sec = hb.get("tick_sec") or 900
    _kv_row(parent, "expected tick_sec", str(tick_sec))

    _kv_row(parent, "ticks_ok", str(run.ticks_ok or 0))
    _kv_row(parent, "ticks_fail", str(run.ticks_fail or 0),
            RED if (run.ticks_fail or 0) > 0 else DIM)

    primed = hb.get("primed")
    _kv_row(parent, "primed", str(primed) if primed is not None else "—",
            GREEN if primed else AMBER)

    ks_state = hb.get("ks_state")
    _kv_row(parent, "ks_state", str(ks_state) if ks_state else "—",
            GREEN if ks_state == "armed" else AMBER)

    started_age = _format_age(run.started_at)
    _kv_row(parent, "uptime", started_age)
