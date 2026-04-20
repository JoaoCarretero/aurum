"""RUNS HISTORY — unified view of every shadow/paper/backtest run.

Single institutional table listing everything in `data/` plus what the
VPS cockpit reports, with the columns a trader actually looks at:

    ENGINE · MODE · STATUS · STARTED · DURATION · TICKS · SIGNALS ·
    FINAL EQ · ROI · TRADES

Click a row: the right pane replaces itself with that run's full
readout — manifest (commit/branch/host/config hash), heartbeat, equity
curve, metrics, tail of fills/trades, tail of the log.

Data sources
    * Local disk: `data/<engine>_{shadow,paper}/<run_id>/state/
      heartbeat.json` + `reports/*.jsonl`
    * VPS: cockpit API `/v1/runs` → `/v1/runs/<id>/{heartbeat,account,
      equity,trades,log}`
    * Dedup: when a run_id shows up both local and VPS, prefer the VPS
      row (live heartbeat) and attach the local reports directory for
      deeper reads (`fills`, log tail)

The pane is 100% read-only; no systemctl actions here (those live on
the engines live cockpit). This is the log, not the console.
"""
from __future__ import annotations

import json
import math
import threading
import tkinter as tk
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from core.ui.ui_palette import (
    AMBER, AMBER_B, AMBER_D, BG, BG2, BG3, BORDER, CYAN, DIM, DIM2,
    FONT, GREEN, PANEL, RED, WHITE,
)


ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = ROOT / "data"


# ─── Data model ───────────────────────────────────────────────────

@dataclass
class RunSummary:
    run_id: str
    engine: str              # UPPER
    mode: str                # shadow | paper | live | backtest
    status: str              # running | stopped | failed | unknown
    started_at: str | None
    stopped_at: str | None
    last_tick_at: str | None
    ticks_ok: int | None
    ticks_fail: int | None
    novel: int | None        # novel_since_prime preferred, else novel_total
    equity: float | None
    initial_balance: float | None
    roi_pct: float | None
    trades_closed: int | None
    source: str              # "vps" | "local"
    run_dir: Path | None
    heartbeat: dict | None
    _raw: dict = field(default_factory=dict)


# ─── Collectors ───────────────────────────────────────────────────

def collect_local_runs(data_root: Path | None = None) -> list[RunSummary]:
    """Scan data/<engine>_{shadow,paper}/*/ and build summaries.

    Layouts supported (same as `core.shadow_contract.find_runs`):
      - data/<engine>_shadow/<run_id>/state/heartbeat.json
      - data/<engine>_paper/<run_id>/state/heartbeat.json
      - data/shadow/<engine>/<run_id>/state/heartbeat.json (legacy)
    """
    root = data_root or DATA_ROOT
    rows: list[RunSummary] = []
    if not root.exists():
        return rows
    for engine_dir in root.iterdir():
        if not engine_dir.is_dir():
            continue
        name = engine_dir.name
        if name.endswith("_shadow"):
            engine = name.removesuffix("_shadow").upper()
            mode = "shadow"
            _scan_engine_dir(engine_dir, engine, mode, rows)
        elif name.endswith("_paper"):
            engine = name.removesuffix("_paper").upper()
            mode = "paper"
            _scan_engine_dir(engine_dir, engine, mode, rows)
        elif name == "shadow":
            for sub in engine_dir.iterdir():
                if sub.is_dir():
                    _scan_engine_dir(sub, sub.name.upper(), "shadow", rows)
    return rows


def _scan_engine_dir(engine_dir: Path, engine: str, mode: str,
                     rows: list[RunSummary]) -> None:
    try:
        children = list(engine_dir.iterdir())
    except OSError:
        return
    for run_dir in children:
        if not run_dir.is_dir():
            continue
        hb_path = run_dir / "state" / "heartbeat.json"
        if not hb_path.exists():
            continue
        try:
            hb = json.loads(hb_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            hb = {}
        rows.append(_summary_from_local(run_dir, engine, mode, hb))


def _summary_from_local(run_dir: Path, engine: str, mode: str,
                        hb: dict) -> RunSummary:
    # Derive ROI from account.json if available (paper only)
    account: dict | None = None
    acct_path = run_dir / "state" / "account.json"
    if acct_path.exists():
        try:
            account = json.loads(acct_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            account = None
    equity = None
    initial = None
    roi = None
    trades_closed = None
    if account is not None:
        try:
            equity = float(account.get("equity") or 0.0)
            initial = float(account.get("initial_balance") or 0.0)
            if initial:
                roi = (equity - initial) / initial * 100.0
            trades_closed = int(account.get("trades_closed") or 0)
        except Exception:  # noqa: BLE001
            pass
    novel = hb.get("novel_since_prime")
    if novel is None:
        novel = hb.get("novel_total")
    return RunSummary(
        run_id=str(hb.get("run_id") or run_dir.name),
        engine=engine,
        mode=mode,
        status=str(hb.get("status") or "unknown"),
        started_at=hb.get("started_at"),
        stopped_at=hb.get("stopped_at"),
        last_tick_at=hb.get("last_tick_at"),
        ticks_ok=_as_int(hb.get("ticks_ok")),
        ticks_fail=_as_int(hb.get("ticks_fail")),
        novel=_as_int(novel),
        equity=equity,
        initial_balance=initial,
        roi_pct=roi,
        trades_closed=trades_closed,
        source="local",
        run_dir=run_dir,
        heartbeat=hb,
    )


def collect_vps_runs(client) -> list[RunSummary]:
    """Fetch /v1/runs from cockpit and pull per-run heartbeat+account."""
    rows: list[RunSummary] = []
    if client is None:
        return rows
    try:
        runs = client._get("/v1/runs")
    except Exception:  # noqa: BLE001
        return rows
    if not isinstance(runs, list):
        return rows
    for r in runs:
        rid = r.get("run_id")
        if not rid:
            continue
        hb: dict = {}
        account: dict | None = None
        try:
            hb = client._get(f"/v1/runs/{rid}/heartbeat") or {}
        except Exception:  # noqa: BLE001
            hb = {}
        try:
            account = client._get(f"/v1/runs/{rid}/account")
            if isinstance(account, dict) and not account.get("available", True):
                account = None
        except Exception:  # noqa: BLE001
            account = None
        equity = None
        initial = None
        roi = None
        trades_closed = None
        if account:
            try:
                equity = float(account.get("equity") or 0.0)
                initial = float(account.get("initial_balance") or 0.0)
                if initial:
                    roi = (equity - initial) / initial * 100.0
                trades_closed = int(account.get("trades_closed") or 0)
            except Exception:  # noqa: BLE001
                pass
        novel = hb.get("novel_since_prime")
        if novel is None:
            novel = hb.get("novel_total", r.get("novel_total"))
        rows.append(RunSummary(
            run_id=rid,
            engine=str(r.get("engine") or hb.get("engine") or "?").upper(),
            mode=str(r.get("mode") or hb.get("mode") or "?"),
            status=str(r.get("status") or hb.get("status") or "unknown"),
            started_at=r.get("started_at") or hb.get("started_at"),
            stopped_at=hb.get("stopped_at"),
            last_tick_at=r.get("last_tick_at") or hb.get("last_tick_at"),
            ticks_ok=_as_int(hb.get("ticks_ok")),
            ticks_fail=_as_int(hb.get("ticks_fail")),
            novel=_as_int(novel),
            equity=equity,
            initial_balance=initial,
            roi_pct=roi,
            trades_closed=trades_closed,
            source="vps",
            run_dir=None,
            heartbeat=hb,
            _raw=r,
        ))
    return rows


def merge_runs(local: list[RunSummary],
               vps: list[RunSummary]) -> list[RunSummary]:
    """Prefer VPS row when the same run_id appears on both sides; attach
    the matching local run_dir to the VPS row so file-based readers still
    work (log tail, trades.jsonl)."""
    local_by_id = {r.run_id: r for r in local}
    out: list[RunSummary] = []
    seen: set[str] = set()
    for v in vps:
        if v.run_id in local_by_id:
            v.run_dir = local_by_id[v.run_id].run_dir
        out.append(v)
        seen.add(v.run_id)
    for l in local:
        if l.run_id not in seen:
            out.append(l)
    out.sort(key=_recency_key, reverse=True)
    return out


def _recency_key(r: RunSummary) -> float:
    for v in (r.last_tick_at, r.started_at):
        if not v:
            continue
        try:
            ts = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts.timestamp()
        except Exception:  # noqa: BLE001
            continue
    return 0.0


def _as_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ─── Formatters ───────────────────────────────────────────────────

def fmt_duration(started: str | None, stopped: str | None,
                 last_tick: str | None, running: bool) -> str:
    if not started:
        return "—"
    try:
        t0 = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        if t0.tzinfo is None:
            t0 = t0.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return "—"
    if running:
        t1 = datetime.now(timezone.utc)
    else:
        ref = stopped or last_tick
        if ref:
            try:
                t1 = datetime.fromisoformat(str(ref).replace("Z", "+00:00"))
                if t1.tzinfo is None:
                    t1 = t1.replace(tzinfo=timezone.utc)
            except Exception:  # noqa: BLE001
                t1 = datetime.now(timezone.utc)
        else:
            t1 = datetime.now(timezone.utc)
    secs = max(0, int((t1 - t0).total_seconds()))
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    h, m = divmod(secs // 60, 60)
    if h < 24:
        return f"{h}h{m:02d}m"
    d, rh = divmod(h, 24)
    return f"{d}d{rh}h"


def fmt_started(started: str | None) -> str:
    if not started:
        return "—"
    s = str(started)[:16].replace("T", " ")
    return s


def fmt_equity(eq: float | None) -> str:
    if eq is None:
        return "—"
    return f"${eq:,.0f}"


def fmt_roi(roi: float | None) -> str:
    if roi is None:
        return "—"
    sign = "+" if roi >= 0 else ""
    return f"{sign}{roi:.2f}%"


# ─── Tk rendering ─────────────────────────────────────────────────

def render_runs_history(parent: tk.Widget, launcher,
                        client_factory: Callable[[], object | None]
                        ) -> tk.Frame:
    """Full RUNS HISTORY screen. Two-column split: table left, detail right.

    `client_factory` mirrors the lazy cockpit pattern used elsewhere —
    must return a cockpit client or None.
    """
    root = tk.Frame(parent, bg=BG)
    root.pack(fill="both", expand=True)

    state: dict = {
        "selected_run_id": None,
        "rows": [],
        "refresh_aid": None,
        "filter_mode": "all",  # all | shadow | paper
    }

    split = tk.Frame(root, bg=BG)
    split.pack(fill="both", expand=True)

    # LEFT — table
    left = tk.Frame(split, bg=BG, width=640,
                    highlightbackground=BORDER, highlightthickness=1)
    left.pack(side="left", fill="y")
    left.pack_propagate(False)

    _render_left_header(left, state, launcher)
    table_wrap = tk.Frame(left, bg=BG)
    table_wrap.pack(fill="both", expand=True)
    state["table_wrap"] = table_wrap

    # RIGHT — detail
    right = tk.Frame(split, bg=PANEL,
                     highlightbackground=BORDER, highlightthickness=1)
    right.pack(side="right", fill="both", expand=True)
    state["detail_host"] = right

    def _refresh():
        _refresh_runs(state, launcher, client_factory)
    state["refresh_fn"] = _refresh

    _refresh()
    _schedule_refresh(launcher, state, _refresh)
    return root


def _render_left_header(parent: tk.Widget, state: dict, launcher) -> None:
    hdr = tk.Frame(parent, bg=BG)
    hdr.pack(fill="x", padx=10, pady=(8, 2))
    tk.Label(hdr, text="RUNS HISTORY", fg=AMBER, bg=BG,
             font=(FONT, 9, "bold")).pack(side="left")
    tk.Label(hdr, text="  ·  local + VPS, newest first",
             fg=DIM, bg=BG, font=(FONT, 7)).pack(side="left")
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=10, pady=(1, 4))

    # Filter chips
    f_row = tk.Frame(parent, bg=BG)
    f_row.pack(fill="x", padx=10, pady=(0, 4))
    tk.Label(f_row, text="MODE", fg=DIM2, bg=BG,
             font=(FONT, 6, "bold")).pack(side="left")
    for label in ("ALL", "SHADOW", "PAPER"):
        key = label.lower()

        def _pick(_e=None, _k=key):
            state["filter_mode"] = "all" if _k == "all" else _k
            fn = state.get("refresh_fn")
            if fn:
                fn()
        chip = tk.Label(f_row, text=f" {label} ", fg=WHITE, bg=BG3,
                        font=(FONT, 6, "bold"), cursor="hand2",
                        padx=5, pady=1)
        chip.pack(side="left", padx=(4, 0))
        chip.bind("<Button-1>", _pick)

    # Column header
    cols = _COLUMNS
    col_hdr = tk.Frame(parent, bg=BG)
    col_hdr.pack(fill="x", padx=10, pady=(4, 0))
    for label, w in cols:
        tk.Label(col_hdr, text=label, fg=DIM2, bg=BG,
                 font=(FONT, 6, "bold"), width=w,
                 anchor="w").pack(side="left", padx=(2, 0))
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=10)


_COLUMNS = [
    ("ST",      3),
    ("ENGINE",  8),
    ("MODE",    6),
    ("STARTED", 13),
    ("DUR",     7),
    ("TICKS",   6),
    ("SIG",     5),
    ("EQ",      9),
    ("ROI",     7),
    ("TR",      4),
    ("SRC",     4),
]


def _refresh_runs(state: dict, launcher,
                  client_factory: Callable[[], object | None]) -> None:
    wrap = state.get("table_wrap")
    if wrap is None:
        return
    try:
        if not wrap.winfo_exists():
            return
    except Exception:
        return

    # Clear
    for w in wrap.winfo_children():
        try:
            w.destroy()
        except Exception:
            pass

    # Local is cheap (sync). VPS is HTTP — kick a daemon thread for it.
    local = collect_local_runs()

    def _fetch_vps():
        try:
            client = client_factory()
        except Exception:
            client = None
        vps = collect_vps_runs(client)
        merged = merge_runs(local, vps)
        state["rows"] = merged
        try:
            launcher.after(0, lambda: _paint_rows(state))
        except Exception:
            pass

    t = threading.Thread(target=_fetch_vps, daemon=True)
    t.start()

    # Paint the local-only view immediately so user sees something while
    # the VPS call is in flight.
    state["rows"] = merge_runs(local, [])
    _paint_rows(state)


def _paint_rows(state: dict) -> None:
    wrap = state.get("table_wrap")
    if wrap is None:
        return
    try:
        if not wrap.winfo_exists():
            return
    except Exception:
        return
    for w in wrap.winfo_children():
        try:
            w.destroy()
        except Exception:
            pass

    rows = state.get("rows") or []
    flt = state.get("filter_mode", "all")
    if flt != "all":
        rows = [r for r in rows if r.mode == flt]

    if not rows:
        tk.Label(wrap,
                 text="   — nenhum run visível (local ou VPS) —",
                 fg=DIM2, bg=BG,
                 font=(FONT, 7, "italic")).pack(anchor="w", pady=8, padx=12)
        return

    for r in rows[:60]:
        _render_run_row(wrap, r, state)


def _render_run_row(parent: tk.Widget, r: RunSummary, state: dict) -> None:
    is_sel = state.get("selected_run_id") == r.run_id
    bg = BG2 if is_sel else BG
    row = tk.Frame(parent, bg=bg, cursor="hand2")
    row.pack(fill="x", padx=10, pady=0)

    running = str(r.status).lower() == "running"
    dot = "●" if running else "○"
    dot_color = GREEN if running else (RED if r.status == "failed" else DIM2)

    dur = fmt_duration(r.started_at, r.stopped_at, r.last_tick_at, running)
    ticks = "—" if r.ticks_ok is None else str(r.ticks_ok)
    sig = "—" if r.novel is None else str(r.novel)
    tr = "—" if r.trades_closed is None else str(r.trades_closed)
    roi_txt = fmt_roi(r.roi_pct)
    roi_color = (GREEN if (r.roi_pct or 0) > 0 else
                 (RED if (r.roi_pct or 0) < 0 else DIM))
    src_color = GREEN if r.source == "vps" else CYAN
    mode_color = AMBER if r.mode == "paper" else (
        CYAN if r.mode == "shadow" else DIM)

    cells = [
        (dot, dot_color, 3, "bold"),
        (r.engine[:8], WHITE, 8, "bold"),
        (r.mode[:6], mode_color, 6, "normal"),
        (fmt_started(r.started_at), DIM, 13, "normal"),
        (dur, WHITE, 7, "normal"),
        (ticks, WHITE if (r.ticks_ok or 0) > 0 else DIM2, 6, "normal"),
        (sig, AMBER_B if (r.novel or 0) > 0 else DIM2, 5, "bold"),
        (fmt_equity(r.equity), WHITE, 9, "normal"),
        (roi_txt, roi_color, 7, "bold"),
        (tr, WHITE, 4, "normal"),
        (r.source.upper(), src_color, 4, "bold"),
    ]
    labels = []
    for text, color, w, weight in cells:
        lbl = tk.Label(row, text=text, fg=color, bg=bg,
                       font=(FONT, 7, weight), width=w,
                       anchor="w")
        lbl.pack(side="left", padx=(2, 0))
        labels.append(lbl)

    def _click(_e=None, _r=r):
        state["selected_run_id"] = _r.run_id
        _load_detail(_r, state)
        # Re-paint rows to highlight
        _paint_rows(state)

    def _hover_on(_e=None, _labels=labels):
        for l in _labels:
            try:
                l.configure(bg=BG3)
            except Exception:
                pass

    def _hover_off(_e=None, _labels=labels, _rid=r.run_id):
        _bg = BG2 if state.get("selected_run_id") == _rid else BG
        for l in _labels:
            try:
                l.configure(bg=_bg)
            except Exception:
                pass

    for w in (row, *labels):
        w.bind("<Button-1>", _click)
        w.bind("<Enter>", _hover_on)
        w.bind("<Leave>", _hover_off)


# ─── Detail pane ───────────────────────────────────────────────────

def _load_detail(r: RunSummary, state: dict) -> None:
    host = state.get("detail_host")
    if host is None:
        return
    try:
        if not host.winfo_exists():
            return
    except Exception:
        return

    for w in host.winfo_children():
        try:
            w.destroy()
        except Exception:
            pass

    _render_detail_header(host, r)

    body = tk.Frame(host, bg=PANEL)
    body.pack(fill="both", expand=True, padx=10, pady=(4, 0))

    _render_detail_telemetry(body, r)
    _render_detail_equity_metrics(body, r)
    _render_detail_trades(body, r)
    _render_detail_log_tail(body, r)


def _render_detail_header(parent: tk.Widget, r: RunSummary) -> None:
    bar = tk.Frame(parent, bg=BG)
    bar.pack(fill="x")
    inner = tk.Frame(bar, bg=BG)
    inner.pack(fill="x", padx=10, pady=7)
    dot_color = GREEN if r.status == "running" else (
        RED if r.status == "failed" else DIM2)
    tk.Label(inner, text="●", fg=dot_color, bg=BG,
             font=(FONT, 12)).pack(side="left", padx=(0, 6))
    tk.Label(inner, text=r.engine, fg=WHITE, bg=BG,
             font=(FONT, 11, "bold")).pack(side="left")
    tk.Label(inner, text=f"  {r.mode.upper()}",
             fg=AMBER, bg=BG, font=(FONT, 8, "bold")).pack(side="left")
    tk.Label(inner, text=f"  ·  {r.status.upper()}",
             fg=dot_color, bg=BG, font=(FONT, 7, "bold")).pack(side="left")
    tk.Label(inner, text=f"  ·  run {r.run_id}", fg=DIM, bg=BG,
             font=(FONT, 7)).pack(side="left")
    tk.Label(inner, text=f"  ·  {r.source.upper()}",
             fg=(GREEN if r.source == "vps" else CYAN), bg=BG,
             font=(FONT, 7, "bold")).pack(side="left")
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")


def _render_detail_telemetry(parent: tk.Widget, r: RunSummary) -> None:
    strip = tk.Frame(parent, bg=PANEL)
    strip.pack(fill="x", pady=(6, 2))
    running = r.status == "running"
    dur = fmt_duration(r.started_at, r.stopped_at, r.last_tick_at, running)
    cells = [
        ("STARTED", fmt_started(r.started_at), WHITE),
        ("DURATION", dur, WHITE),
        ("TICKS OK", "—" if r.ticks_ok is None else str(r.ticks_ok),
         GREEN if (r.ticks_ok or 0) > 0 else DIM2),
        ("FAIL", "—" if r.ticks_fail is None else str(r.ticks_fail),
         RED if (r.ticks_fail or 0) > 0 else DIM2),
        ("SIGNALS", "—" if r.novel is None else str(r.novel),
         AMBER_B if (r.novel or 0) > 0 else DIM2),
        ("TRADES", "—" if r.trades_closed is None else str(r.trades_closed),
         WHITE),
    ]
    for label, value, color in cells:
        _cell(strip, label, str(value), color)


def _cell(parent: tk.Widget, label: str, value: str, color: str) -> None:
    cell = tk.Frame(parent, bg=BG, highlightbackground=BORDER,
                    highlightthickness=1)
    cell.pack(side="left", fill="both", expand=True, padx=(0, 3))
    tk.Label(cell, text=label.upper(), fg=DIM2, bg=BG,
             font=(FONT, 6, "bold")).pack(anchor="w", padx=6, pady=(4, 0))
    tk.Label(cell, text=value, fg=color, bg=BG,
             font=(FONT, 10, "bold")).pack(anchor="w", padx=6, pady=(0, 4))


def _render_detail_equity_metrics(parent: tk.Widget, r: RunSummary) -> None:
    if r.equity is None and r.initial_balance is None:
        return
    box = tk.Frame(parent, bg=PANEL)
    box.pack(fill="x", pady=(6, 2))
    _section(box, "ACCOUNT")
    row = tk.Frame(box, bg=PANEL)
    row.pack(fill="x", pady=(2, 2))
    initial = r.initial_balance or r.equity or 0.0
    eq_color = (GREEN if (r.equity or 0) >= initial else
                (RED if (r.equity or 0) < initial else WHITE))
    roi_color = (GREEN if (r.roi_pct or 0) > 0 else
                 (RED if (r.roi_pct or 0) < 0 else DIM))
    _cell(row, "INITIAL", fmt_equity(initial), WHITE)
    _cell(row, "EQUITY", fmt_equity(r.equity), eq_color)
    _cell(row, "ROI", fmt_roi(r.roi_pct), roi_color)


def _render_detail_trades(parent: tk.Widget, r: RunSummary) -> None:
    """Read reports/trades.jsonl if we have the run_dir; show last 10."""
    if r.run_dir is None:
        return
    trades_path = r.run_dir / "reports" / "trades.jsonl"
    if not trades_path.exists():
        return
    lines = []
    try:
        raw = trades_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for ln in raw.splitlines()[-10:]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            lines.append(json.loads(ln))
        except Exception:  # noqa: BLE001
            continue
    if not lines:
        return
    box = tk.Frame(parent, bg=PANEL)
    box.pack(fill="x", pady=(6, 2))
    _section(box, "TRADES", extra=f"last {len(lines)}")
    tbl = tk.Frame(box, bg=PANEL)
    tbl.pack(fill="x", pady=(1, 4))
    hdr = tk.Frame(tbl, bg=BG)
    hdr.pack(fill="x")
    for lbl, w in [("SYMBOL", 9), ("DIR", 5), ("ENTRY", 9), ("EXIT", 9),
                   ("PNL", 9), ("R", 5), ("REASON", 8)]:
        tk.Label(hdr, text=lbl, fg=DIM2, bg=BG,
                 font=(FONT, 6, "bold"), width=w,
                 anchor="w").pack(side="left", padx=(3, 0))
    tk.Frame(box, bg=BORDER, height=1).pack(fill="x")
    for t in lines:
        pnl = float(t.get("pnl_after_fees") or t.get("pnl") or 0.0)
        pnl_color = GREEN if pnl >= 0 else RED
        direction = str(t.get("direction", ""))[:5]
        reason = str(t.get("exit_reason") or "")[:8]
        ep = t.get("entry_price")
        xp = t.get("exit_price")
        r_mul = t.get("r_multiple")
        cells = [
            (str(t.get("symbol", "?"))[:9], WHITE, 9, "bold"),
            (direction, (GREEN if direction.startswith(("L", "B"))
                          else RED), 5, "bold"),
            (f"{float(ep):.5g}" if ep is not None else "—", WHITE, 9, "normal"),
            (f"{float(xp):.5g}" if xp is not None else "—", WHITE, 9, "normal"),
            (f"{pnl:+.2f}", pnl_color, 9, "bold"),
            (f"{float(r_mul):+.2f}" if r_mul is not None else "—",
             pnl_color, 5, "normal"),
            (reason, DIM, 8, "normal"),
        ]
        row = tk.Frame(tbl, bg=PANEL)
        row.pack(fill="x")
        for text, color, w, weight in cells:
            tk.Label(row, text=text, fg=color, bg=PANEL,
                     font=(FONT, 7, weight), width=w,
                     anchor="w").pack(side="left", padx=(3, 0))


def _render_detail_log_tail(parent: tk.Widget, r: RunSummary) -> None:
    if r.run_dir is None:
        return
    logs_dir = r.run_dir / "logs"
    if not logs_dir.exists():
        return
    candidates = [
        logs_dir / "shadow.log",
        logs_dir / "paper.log",
        logs_dir / "live.log",
        logs_dir / "engine.log",
    ]
    log_path = next((p for p in candidates if p.exists()), None)
    if log_path is None:
        globs = sorted(logs_dir.glob("*.log"))
        if globs:
            log_path = globs[0]
    if log_path is None:
        return
    try:
        lines = log_path.read_text(encoding="utf-8",
                                   errors="replace").splitlines()[-25:]
    except OSError:
        return
    box = tk.Frame(parent, bg=PANEL)
    box.pack(fill="both", expand=True, pady=(6, 6))
    _section(box, "LOG TAIL", extra=log_path.name)
    txt = tk.Text(box, wrap="word", bg=BG, fg=WHITE,
                  font=(FONT, 7), padx=6, pady=4,
                  borderwidth=0, highlightthickness=0, height=10)
    txt.pack(fill="both", expand=True, pady=(1, 0))
    txt.insert("end", "\n".join(lines) + "\n")
    txt.see("end")
    txt.config(state="disabled")


def _section(parent: tk.Widget, title: str, extra: str | None = None) -> None:
    row = tk.Frame(parent, bg=PANEL)
    row.pack(fill="x")
    tk.Label(row, text=title.upper(), fg=AMBER, bg=PANEL,
             font=(FONT, 7, "bold")).pack(side="left")
    if extra:
        tk.Label(row, text=f"  ·  {extra}", fg=DIM, bg=PANEL,
                 font=(FONT, 7)).pack(side="left")
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(1, 2))


def _schedule_refresh(launcher, state: dict,
                      refresh_fn: Callable[[], None]) -> None:
    prev = state.pop("refresh_aid", None)
    if prev is not None:
        try:
            launcher.after_cancel(prev)
        except Exception:
            pass
    try:
        aid = launcher.after(5000, lambda: (
            refresh_fn(), _schedule_refresh(launcher, state, refresh_fn)))
        state["refresh_aid"] = aid
    except Exception:
        pass
