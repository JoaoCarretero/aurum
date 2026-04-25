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


# ─── Block ❸ SCAN FUNNEL ───────────────────────────────────────────


def render_scan_funnel_block(parent: tk.Widget, run: RunSummary) -> None:
    """❸ SCAN FUNNEL — last tick scanned→dedup→stale→live→opened."""
    _block_header(parent, "❸ SCAN FUNNEL (last tick)")
    hb = run.heartbeat or {}

    scanned = hb.get("last_scan_scanned") or 0
    dedup = hb.get("last_scan_dedup") or 0
    stale = hb.get("last_scan_stale") or 0
    live = hb.get("last_scan_live") or 0
    opened = hb.get("last_scan_opened") or 0

    _kv_row(parent, "scanned", str(scanned), WHITE if scanned else DIM)
    _kv_row(parent, "dedup", str(dedup), WHITE if dedup else DIM)
    _kv_row(parent, "stale", str(stale), AMBER_D if stale else DIM)
    _kv_row(parent, "live", str(live), GREEN if live else DIM)
    _kv_row(parent, "opened", str(opened), GREEN if opened else DIM)

    last_novel_at = hb.get("last_novel_at")
    _kv_row(parent, "last novel", _format_age(last_novel_at),
            AMBER if last_novel_at else DIM)


# ─── Block ❹ DECISIONS ─────────────────────────────────────────────


def render_decisions_block(parent: tk.Widget, run: RunSummary,
                           limit: int = 30) -> None:
    """❹ DECISIONS — last N signal decisions com REASON.

    Source: local signals.jsonl tail (se source==local) ou cockpit
    /v1/runs/{id}/signals (se source==vps). Skipa graceful se nenhum
    disponível.
    """
    _block_header(parent, f"❹ DECISIONS (last {limit})")

    rows = _fetch_signals(run, limit=limit)
    if not rows:
        tk.Label(parent, text="  (no signal records found)",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="w", padx=12)
        return

    hdr = tk.Frame(parent, bg=BG)
    hdr.pack(fill="x", padx=12, pady=(2, 1))
    for label, w, anchor in (("TS", 16, "w"), ("SYMBOL", 10, "w"),
                              ("DECISION", 14, "w"), ("SCORE", 7, "e"),
                              ("REASON", 30, "w")):
        tk.Label(hdr, text=label, font=(FONT, 7, "bold"), fg=DIM,
                 bg=BG, width=w, anchor=anchor).pack(side="left", padx=(2, 0))

    for r in rows:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=12, pady=0)
        decision = str(r.get("decision", "?"))
        decision_color = {"opened": GREEN, "stale": AMBER_D,
                          "max_open": DIM, "dir_conflict": AMBER,
                          "corr_block": AMBER}.get(decision, WHITE)
        try:
            score_val = float(r.get("score", 0) or 0)
        except (TypeError, ValueError):
            score_val = 0.0
        for val, w, anchor, color in (
            (str(r.get("ts", ""))[:16], 16, "w", DIM),
            (str(r.get("symbol", ""))[:10], 10, "w", WHITE),
            (decision, 14, "w", decision_color),
            (f"{score_val:.2f}", 7, "e", WHITE),
            (str(r.get("reason", ""))[:30], 30, "w", DIM),
        ):
            tk.Label(row, text=val, font=(FONT, 7), fg=color,
                     bg=BG, width=w, anchor=anchor).pack(side="left",
                                                          padx=(2, 0))


def _fetch_signals(run: RunSummary, limit: int) -> list[dict]:
    """Tail de signals.jsonl. Local: read file; VPS: cockpit endpoint."""
    import json
    from pathlib import Path

    rows: list[dict] = []
    if run.source == "local" and run.run_dir:
        candidates = [
            Path(run.run_dir) / "signals.jsonl",
            Path(run.run_dir) / "reports" / "signals.jsonl",
            Path(run.run_dir).parent / "reports" / "signals.jsonl",
        ]
        sig_path = next((p for p in candidates if p.exists()), None)
        if sig_path is not None:
            try:
                lines = sig_path.read_text(
                    encoding="utf-8").splitlines()[-limit:]
                for ln in lines:
                    if ln.strip():
                        rows.append(json.loads(ln))
            except (OSError, ValueError):
                pass
    elif run.source == "vps":
        try:
            from launcher_support.engines_live_view import _get_cockpit_client
            client = _get_cockpit_client()
            if client is not None:
                resp = client._get(
                    f"/v1/runs/{run.run_id}/signals?limit={limit}")
                if isinstance(resp, dict):
                    rows = resp.get("signals", []) or []
        except Exception:
            pass
    return rows


# ─── Block ❺ POSITIONS ─────────────────────────────────────────────


def render_positions_block(parent: tk.Widget, run: RunSummary) -> None:
    """❺ POSITIONS — open positions agora."""
    _block_header(parent, "❺ OPEN POSITIONS")
    hb = run.heartbeat or {}
    positions = hb.get("positions") or []

    if not positions:
        tk.Label(parent, text="  (no open positions)",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="w", padx=12)
        return

    hdr = tk.Frame(parent, bg=BG)
    hdr.pack(fill="x", padx=12, pady=(2, 1))
    cols = (("SYMBOL", 10, "w"), ("DIR", 5, "w"),
            ("ENTRY", 11, "e"), ("MARK", 11, "e"),
            ("PNL$", 9, "e"), ("PNL%", 7, "e"),
            ("STOP", 11, "e"), ("TARGET", 11, "e"),
            ("AGE", 8, "w"))
    for label, w, anchor in cols:
        tk.Label(hdr, text=label, font=(FONT, 7, "bold"), fg=DIM,
                 bg=BG, width=w, anchor=anchor).pack(side="left", padx=(2, 0))

    for p in positions:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=12, pady=0)
        pnl_pct = p.get("pnl_pct") or 0.0
        pnl_color = GREEN if pnl_pct > 0 else (RED if pnl_pct < 0 else DIM)
        for val, w, anchor, color in (
            (str(p.get("symbol", ""))[:10], 10, "w", WHITE),
            (str(p.get("direction", ""))[:5], 5, "w",
             GREEN if str(p.get("direction")) == "long" else RED),
            (f"{p.get('entry_price', 0):.4f}", 11, "e", WHITE),
            (f"{p.get('mark_price', 0):.4f}", 11, "e", WHITE),
            (f"{p.get('pnl_usd', 0):+.2f}", 9, "e", pnl_color),
            (f"{pnl_pct:+.2f}%", 7, "e", pnl_color),
            (f"{p.get('stop', 0):.4f}", 11, "e", DIM),
            (f"{p.get('target', 0):.4f}", 11, "e", DIM),
            (_format_age(p.get("opened_at")), 8, "w", DIM),
        ):
            tk.Label(row, text=val, font=(FONT, 7), fg=color,
                     bg=BG, width=w, anchor=anchor).pack(side="left", padx=(2, 0))


# ─── Block ❺ EQUITY ────────────────────────────────────────────────


def render_equity_block(parent: tk.Widget, run: RunSummary) -> None:
    """❺ EQUITY — agora vs peak vs drawdown."""
    _block_header(parent, "❺ EQUITY")
    hb = run.heartbeat or {}

    eq_now = hb.get("equity_now") or run.equity
    eq_peak = hb.get("equity_peak")
    dd_now = hb.get("drawdown_pct")
    dd_max = hb.get("drawdown_max_pct")
    exposure = hb.get("exposure_pct")

    _kv_row(parent, "equity now", f"{eq_now:.2f}" if eq_now else "—")
    _kv_row(parent, "equity peak", f"{eq_peak:.2f}" if eq_peak else "—")
    _kv_row(parent, "drawdown now",
            f"{dd_now:+.2f}%" if dd_now is not None else "—",
            RED if dd_now and dd_now < -2 else DIM)
    _kv_row(parent, "drawdown max",
            f"{dd_max:+.2f}%" if dd_max is not None else "—",
            RED if dd_max and dd_max < -5 else DIM)
    _kv_row(parent, "exposure",
            f"{exposure:.1f}%" if exposure is not None else "—")
    _kv_row(parent, "ROI", f"{run.roi_pct:+.3f}%" if run.roi_pct is not None else "—",
            GREEN if (run.roi_pct or 0) > 0 else (RED if (run.roi_pct or 0) < 0 else DIM))
