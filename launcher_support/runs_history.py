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
    * SQLite ops index: `aurum.db.live_runs` for live/demo/testnet and
      DB-tracked paper/shadow metadata
    * VPS: cockpit API `/v1/runs` → `/v1/runs/<id>/{heartbeat,account,
      equity,trades,log}`
    * Dedup: when a run_id shows up across sources, prefer VPS telemetry,
      then DB metadata, then local disk; attach local run_dir whenever
      available for deeper reads (`fills`, log tail)

The pane is 100% read-only; no systemctl actions here (those live on
the engines live cockpit). This is the log, not the console.
"""
from __future__ import annotations

import copy
import json
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from core.ui.ui_palette import (
    AMBER, AMBER_B, AMBER_D, BG, BG2, BG3, BORDER, CYAN, DIM, DIM2,
    FONT, GREEN, PANEL, RED, WHITE,
)
from core import db_live_runs


ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = ROOT / "data"
_LOCAL_RUNS_CACHE: dict[str, tuple[float, list[RunSummary]]] = {}
_VPS_RUNS_CACHE: dict[int, tuple[float, list[RunSummary]]] = {}
_DB_RUNS_CACHE: dict[str, tuple[float, list[RunSummary]]] = {}
_RUNS_CACHE_TTL_S = 2.0


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
    host: str | None = None
    label: str | None = None
    open_count: int | None = None
    notes: str | None = None
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
    cache_key = str(root.resolve()) if root.exists() else str(root)
    cached = _cached_rows(_LOCAL_RUNS_CACHE, cache_key)
    if cached is not None:
        return cached
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
    _store_cached_rows(_LOCAL_RUNS_CACHE, cache_key, rows)
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
        open_count=None,
    )


def collect_vps_runs(client) -> list[RunSummary]:
    """Fetch /v1/runs from cockpit and pull per-run heartbeat+account."""
    rows: list[RunSummary] = []
    if client is None:
        return rows
    cache_key = id(client)
    cached = _cached_rows(_VPS_RUNS_CACHE, cache_key)
    if cached is not None:
        return cached
    try:
        runs = client._get("/v1/runs")
    except Exception:  # noqa: BLE001
        return rows
    if not isinstance(runs, list):
        return rows
    indexed_runs = [(idx, r) for idx, r in enumerate(runs) if r.get("run_id")]
    built_rows: dict[int, RunSummary] = {}
    max_workers = min(8, max(1, len(indexed_runs)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_collect_single_vps_run, client, r): idx
            for idx, r in indexed_runs
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                row = future.result()
            except Exception:
                row = None
            if row is not None:
                built_rows[idx] = row
    for idx, _ in indexed_runs:
        row = built_rows.get(idx)
        if row is not None:
            rows.append(row)
    _store_cached_rows(_VPS_RUNS_CACHE, cache_key, rows)
    return rows


def _collect_single_vps_run(client, payload: dict) -> RunSummary | None:
    rid = payload.get("run_id")
    if not rid:
        return None
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
        novel = hb.get("novel_total", payload.get("novel_total"))
    return RunSummary(
        run_id=rid,
        engine=str(payload.get("engine") or hb.get("engine") or "?").upper(),
        mode=str(payload.get("mode") or hb.get("mode") or "?"),
        status=str(payload.get("status") or hb.get("status") or "unknown"),
        started_at=payload.get("started_at") or hb.get("started_at"),
        stopped_at=hb.get("stopped_at"),
        last_tick_at=payload.get("last_tick_at") or hb.get("last_tick_at"),
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
        host=str(payload.get("host") or hb.get("host") or "") or None,
        label=str(payload.get("label") or hb.get("label") or "") or None,
        open_count=_as_int(account.get("open_count") if isinstance(account, dict) else None),
        _raw=payload,
    )


def collect_db_runs(*, mode: str | None = None, limit: int = 500) -> list[RunSummary]:
    cache_key = f"{mode or 'all'}:{int(limit)}"
    cached = _cached_rows(_DB_RUNS_CACHE, cache_key)
    if cached is not None:
        return cached
    try:
        rows = db_live_runs.list_live_runs(mode=mode, limit=limit)
    except Exception:
        rows = []
    out: list[RunSummary] = []
    for row in rows:
        run_dir_raw = row.get("run_dir")
        run_dir = Path(run_dir_raw) if run_dir_raw else None
        if run_dir is not None and not run_dir.is_absolute():
            run_dir = ROOT / run_dir
        started_at = row.get("started_at")
        stopped_at = row.get("ended_at")
        last_tick_at = row.get("last_tick_at")
        equity = _as_float(row.get("equity"))
        open_count = _as_int(row.get("open_count"))
        out.append(
            RunSummary(
                run_id=str(row.get("run_id") or ""),
                engine=str(row.get("engine") or "?").upper(),
                mode=str(row.get("mode") or "?"),
                status=str(row.get("status") or "unknown"),
                started_at=started_at,
                stopped_at=stopped_at,
                last_tick_at=last_tick_at,
                ticks_ok=_as_int(row.get("tick_count")),
                ticks_fail=None,
                novel=_as_int(row.get("novel_count")),
                equity=equity,
                initial_balance=None,
                roi_pct=None,
                trades_closed=None,
                source="db",
                run_dir=run_dir,
                heartbeat=None,
                host=str(row.get("host") or "") or None,
                label=str(row.get("label") or "") or None,
                open_count=open_count,
                notes=str(row.get("notes") or "") or None,
                _raw=dict(row),
            )
        )
    _store_cached_rows(_DB_RUNS_CACHE, cache_key, out)
    return out


def _clone_rows(rows: list[RunSummary]) -> list[RunSummary]:
    return [copy.deepcopy(row) for row in rows]


def _cached_rows(cache: dict, key) -> list[RunSummary] | None:
    now = time.monotonic()
    entry = cache.get(key)
    if entry is None:
        return None
    stamp, rows = entry
    if (now - stamp) > _RUNS_CACHE_TTL_S:
        return None
    return _clone_rows(rows)


def _store_cached_rows(cache: dict, key, rows: list[RunSummary]) -> None:
    cache[key] = (time.monotonic(), _clone_rows(rows))


def clear_collect_caches() -> None:
    _LOCAL_RUNS_CACHE.clear()
    _VPS_RUNS_CACHE.clear()
    _DB_RUNS_CACHE.clear()


def merge_runs(local: list[RunSummary],
               vps: list[RunSummary],
               db_rows: list[RunSummary] | None = None) -> list[RunSummary]:
    """Merge runs across local disk, live_runs DB, and VPS.

    Priority:
      1. VPS heartbeat/account when present
      2. DB live_runs index for operational metadata
      3. Local disk fallback
    """
    db_rows = db_rows or []
    local_by_id = {r.run_id: r for r in local}
    db_by_id = {r.run_id: r for r in db_rows}
    out: list[RunSummary] = []
    seen: set[str] = set()

    for v in vps:
        local_match = local_by_id.get(v.run_id)
        db_match = db_by_id.get(v.run_id)
        if local_match is not None and v.run_dir is None:
            v.run_dir = local_match.run_dir
        if db_match is not None:
            if v.run_dir is None:
                v.run_dir = db_match.run_dir
            if not v.host:
                v.host = db_match.host
            if not v.label:
                v.label = db_match.label
            if v.open_count is None:
                v.open_count = db_match.open_count
            if not v.notes:
                v.notes = db_match.notes
        out.append(v)
        seen.add(v.run_id)

    for d in db_rows:
        if d.run_id in seen:
            continue
        local_match = local_by_id.get(d.run_id)
        if local_match is not None:
            if d.run_dir is None:
                d.run_dir = local_match.run_dir
            if d.heartbeat is None:
                d.heartbeat = local_match.heartbeat
            if d.initial_balance is None:
                d.initial_balance = local_match.initial_balance
            if d.roi_pct is None:
                d.roi_pct = local_match.roi_pct
            if d.trades_closed is None:
                d.trades_closed = local_match.trades_closed
        out.append(d)
        seen.add(d.run_id)

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


def _as_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


from core.ops.run_catalog import (  # noqa: E402
    RunSummary,
    collect_db_runs,
    collect_local_runs,
    collect_vps_runs,
    merge_runs,
)


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
        # client_factory stash — _load_detail usa pra lazy-fetch do
        # heartbeat VPS quando o operador clica numa run. Sem isso,
        # as secoes SCAN/HEALTH/PROBE skipam silently porque
        # collect_vps_runs nao popula r.heartbeat (perf optimization).
        "client_factory": client_factory,
        # launcher stash — _load_detail precisa pra marshal de volta
        # do async heartbeat fetch pra Tk main thread (launcher.after).
        "launcher": launcher,
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
    root._runs_history_state = state

    _refresh()
    _schedule_refresh(launcher, state, _refresh)
    return root


def resume_runs_history(root: tk.Widget, launcher) -> None:
    """Re-arm auto-refresh and repaint an existing mounted runs-history tree."""
    state = getattr(root, "_runs_history_state", None)
    if not isinstance(state, dict):
        return
    refresh_fn = state.get("refresh_fn")
    if callable(refresh_fn):
        refresh_fn()
        _schedule_refresh(launcher, state, refresh_fn)


def pause_runs_history(root: tk.Widget, launcher) -> None:
    """Cancel the auto-refresh timer for an existing mounted runs-history tree."""
    state = getattr(root, "_runs_history_state", None)
    if not isinstance(state, dict):
        return
    aid = state.get("refresh_aid")
    if aid is not None:
        try:
            launcher.after_cancel(aid)
        except Exception:
            pass
        state["refresh_aid"] = None


def _render_left_header(parent: tk.Widget, state: dict, launcher) -> None:
    """Filter chips + column header for the runs table.

    Chips are 1px BORDER boxes when active (H2 8pt bold). Column headers
    are COL tier (7pt bold) to preserve pixel-accurate width alignment
    with 7pt rows. Numeric columns right-aligned to match rows.
    Divider rule: BORDER between blocks, DIM2 for sub-divisions.
    """
    current = state.get("filter_mode", "all")
    f_row = tk.Frame(parent, bg=BG)
    f_row.pack(fill="x", padx=10, pady=(10, 8))
    for idx, label in enumerate(("ALL", "SHADOW", "PAPER"), start=1):
        key = label.lower()
        is_active = (current == "all" and key == "all") or (current == key)

        def _pick(_e=None, _k=key):
            state["filter_mode"] = "all" if _k == "all" else _k
            fn = state.get("refresh_fn")
            if fn:
                fn()
        chip = tk.Label(
            f_row, text=f" {idx}:{label} ",
            font=(FONT, 8, "bold"),
            fg=AMBER_D if is_active else DIM,
            bg=BG3 if is_active else BG,
            cursor="hand2", padx=8, pady=4,
            highlightbackground=BORDER if is_active else BG,
            highlightthickness=1,
        )
        chip.pack(side="left", padx=(0, 6))
        chip.bind("<Button-1>", _pick)

    # Divider between filter block and table block — BORDER (structural).
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=10)

    # Column header — 7pt bold (COL tier, preserves alignment with rows).
    # Numeric columns right-aligned.
    numeric = {"TICKS", "SIG", "EQUITY", "ROI", "TRADES"}
    col_hdr = tk.Frame(parent, bg=BG)
    col_hdr.pack(fill="x", padx=10, pady=(6, 2))
    for label, w in _COLUMNS:
        anchor = "e" if label in numeric else "w"
        tk.Label(col_hdr, text=label, fg=DIM, bg=BG,
                 font=(FONT, 7, "bold"), width=w,
                 anchor=anchor).pack(side="left", padx=(2, 0))
    # Divider below column header — DIM2 (sub-division within table block).
    tk.Frame(parent, bg=DIM2, height=1).pack(fill="x", padx=10)


_COLUMNS = [
    ("ST",      2),
    ("ENGINE",  11),
    ("MODE",    6),
    ("STARTED", 13),
    ("DUR",     7),
    ("TICKS",   6),
    ("SIG",     5),
    ("EQUITY",  9),
    ("ROI",     8),
    ("TRADES",  6),
    ("SRC",     5),
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

    # Flicker fix definitivo: state["last_sig"] rastreia a assinatura
    # do que foi pintado por ultimo (nao state["rows"] que tem formas
    # diferentes em local+db vs merged). Antes: cada tick pintava 2x
    # — local+db sync (sig_local != sig_merged anterior -> paint) +
    # VPS async (sig_merged != sig_local -> paint). Agora: local+db
    # pinta so no bootstrap (last_sig None), refreshes subsequentes
    # dependem do retorno do VPS (que tb e invocado com vps=[] em
    # caso de falha, preservando o fluxo sem tunel).
    local = collect_local_runs()
    db_rows = collect_db_runs(limit=500)

    def _sig(rows):
        return tuple(
            (r.run_id, r.status,
             None if r.roi_pct is None else round(r.roi_pct, 2))
            for r in rows
        )

    def _fetch_vps():
        try:
            client = client_factory()
        except Exception:
            client = None
        try:
            vps = collect_vps_runs(client)
        except RuntimeError:
            return
        except Exception:
            vps = []
        merged = merge_runs(local, vps, db_rows)
        def _apply_vps_rows():
            new_sig = _sig(merged)
            if state.get("last_sig") == new_sig:
                return
            state["last_sig"] = new_sig
            state["rows"] = merged
            _paint_rows(state)
        try:
            if hasattr(launcher, "_ui_call_soon"):
                launcher._ui_call_soon(_apply_vps_rows)
            else:
                launcher.after(0, _apply_vps_rows)
        except Exception:
            pass

    # Bootstrap paint: so na PRIMEIRA refresh, antes do VPS responder
    # pela primeira vez. Refreshes subsequentes so repaintam via
    # _apply_vps_rows (que tambem dispara mesmo com vps=[] em falha).
    if state.get("last_sig") is None:
        new_local = merge_runs(local, [], db_rows)
        state["last_sig"] = _sig(new_local)
        state["rows"] = new_local
        _paint_rows(state)

    if hasattr(launcher, "_ui_call_soon"):
        t = threading.Thread(target=_fetch_vps, daemon=True)
        t.start()
    else:
        _fetch_vps()


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
                 text="— nenhum run visível (local ou VPS) —",
                 fg=DIM2, bg=BG,
                 font=(FONT, 7, "italic")).pack(pady=16)
        return

    # Split: LIVE (status='running' com tick recente), STALE (status claims
    # running mas last_tick > 30min — VPS/local nao atualiza o status em
    # shutdown imperfeito), FINISHED (stopped/failed/unknown).
    # Stale usa ``is_run_stale`` de core.ops.run_catalog — mesma regra que
    # o cockpit usa pra filtrar contadores. Sem isso, /data mostrava 21
    # live enquanto o VPS tinha 11 rodando de verdade.
    from core.ops.run_catalog import is_run_stale as _is_stale
    running_rows: list[RunSummary] = []
    stale_rows: list[RunSummary] = []
    finished_rows: list[RunSummary] = []
    for r in rows:
        status = str(r.status).lower()
        if status == "running":
            if _is_stale(r):
                stale_rows.append(r)
            else:
                running_rows.append(r)
        elif status == "stale":
            stale_rows.append(r)
        else:
            finished_rows.append(r)

    if running_rows:
        _render_list_section_header(
            wrap, "● LIVE", len(running_rows), color=GREEN,
        )
        for r in running_rows[:20]:
            _render_run_row(wrap, r, state)

    if stale_rows:
        if running_rows:
            tk.Frame(wrap, bg=BG, height=6).pack(fill="x")
        _render_list_section_header(
            wrap, "◌ STALE", len(stale_rows), color=AMBER,
        )
        for r in stale_rows[:20]:
            _render_run_row(wrap, r, state)

    if finished_rows:
        if running_rows or stale_rows:
            tk.Frame(wrap, bg=BG, height=6).pack(fill="x")
        _render_list_section_header(
            wrap, "○ FINISHED", len(finished_rows), color=DIM,
        )
        for r in finished_rows[:60]:
            _render_run_row(wrap, r, state)


def _render_list_section_header(parent: tk.Widget, title: str,
                                 count: int, color: str) -> None:
    """Section header separating LIVE / STALE / FINISHED in the list pane.

    Title is H2 (8pt bold, semantic color). Count is BODY (7pt normal
    DIM2). Divider below is BORDER (structural — marks new block).
    """
    hdr = tk.Frame(parent, bg=BG)
    hdr.pack(fill="x", padx=10, pady=(10, 3))
    tk.Label(hdr, text=title, font=(FONT, 8, "bold"),
             fg=color, bg=BG).pack(side="left")
    tk.Label(hdr, text=f"  ·  {count}", font=(FONT, 7),
             fg=DIM2, bg=BG).pack(side="left")
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=10, pady=(1, 2))


def _render_run_row(parent: tk.Widget, r: RunSummary, state: dict) -> None:
    is_sel = state.get("selected_run_id") == r.run_id
    bg = BG2 if is_sel else BG
    row = tk.Frame(parent, bg=bg, cursor="hand2")
    row.pack(fill="x", padx=10, pady=(1, 1))

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
    src_color = GREEN if r.source == "vps" else (AMBER_D if r.source == "db" else CYAN)
    mode_color = AMBER if r.mode == "paper" else (
        CYAN if r.mode == "shadow" else DIM)

    # Cells: (text, color, width, weight, anchor).
    # Weight rule: bold only on identity + outcome — ENGINE, ROI, SRC,
    # and SIG when > 0. Anchor rule: right-align numerics for decimal
    # alignment, left-align text for readability.
    cells = [
        (dot, dot_color, 2, "bold", "w"),
        (r.engine[:11], WHITE, 11, "bold", "w"),
        (r.mode[:6], mode_color, 6, "normal", "w"),
        (fmt_started(r.started_at), DIM, 13, "normal", "w"),
        (dur, WHITE, 7, "normal", "w"),
        (ticks, WHITE if (r.ticks_ok or 0) > 0 else DIM2, 6, "normal", "e"),
        (sig, AMBER_B if (r.novel or 0) > 0 else DIM2, 5,
         "bold" if (r.novel or 0) > 0 else "normal", "e"),
        (fmt_equity(r.equity), WHITE, 9, "normal", "e"),
        (roi_txt, roi_color, 8, "bold", "e"),
        (tr, WHITE, 6, "normal", "e"),
        (r.source.upper(), src_color, 5, "bold", "w"),
    ]
    labels = []
    for text, color, w, weight, anchor in cells:
        lbl = tk.Label(row, text=text, fg=color, bg=bg,
                       font=(FONT, 7, weight), width=w,
                       anchor=anchor)
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

def lazy_fetch_heartbeat(r: RunSummary, client_factory,
                         on_complete=None) -> bool:
    """Lazy-fetch heartbeat do VPS quando operador clica numa run.

    `collect_vps_runs` nao popula r.heartbeat por performance (antes
    fazia 2*N round-trips). O detail pane precisa dos campos ricos
    (last_scan_*, drawdown_pct, ks_state, top_score, etc), entao aqui
    buscamos sob demanda via cockpit `/v1/runs/{id}/heartbeat`.

    Se `on_complete` for None, fetch e SYNCRONO — caller aceita o
    bloqueio (ate 5s em tunnel lento).

    Se `on_complete` for callable, fetch roda em daemon thread;
    retorna True se o fetch foi disparado (caller deve mostrar
    placeholder + aguardar callback); on_complete e invocado APOS
    r.heartbeat ser populado. CALLBACK RODA NA THREAD — caller
    precisa marshal pra Tk main thread via `launcher.after(0, ...)`
    dentro do callback.

    Audit 2026-04-22 pegou 5s freeze no main thread quando tunnel
    responde lento; esta versao async fecha esse gap.
    """
    if r.heartbeat is not None:
        if on_complete is not None:
            on_complete()
        return False
    if r.source != "vps" or client_factory is None:
        if on_complete is not None:
            on_complete()
        return False

    def _fetch():
        client = None
        try:
            client = client_factory()
        except Exception:
            pass
        hb = None
        if client is not None:
            try:
                hb = client._get(f"/v1/runs/{r.run_id}/heartbeat")
            except Exception:
                hb = None
        if isinstance(hb, dict) and hb:
            r.heartbeat = hb
        if on_complete is not None:
            try:
                on_complete()
            except Exception:
                pass

    if on_complete is None:
        _fetch()  # sync path — preserva comportamento pre-audit
        return True

    import threading
    threading.Thread(
        target=_fetch, daemon=True, name=f"hb-fetch-{r.run_id[:16]}",
    ).start()
    return True


def _reload_if_still_selected(r: RunSummary, state: dict) -> None:
    """Re-render detail pane APENAS se a mesma run continua selecionada.

    Protege contra race quando operador clicou em outra run durante o
    fetch async do heartbeat — repaint errado sobrescreveria o detail
    da run nova. Checa state["selected_run_id"] antes de agir.
    """
    if state.get("selected_run_id") != r.run_id:
        return
    _load_detail(r, state)


def _load_detail(r: RunSummary, state: dict) -> None:
    host = state.get("detail_host")
    if host is None:
        return
    try:
        if not host.winfo_exists():
            return
    except Exception:
        return

    # Async lazy-fetch do heartbeat VPS. Antes era sync — congelava UI
    # por ate 5s se tunnel respondesse lento (audit 2026-04-22).
    # Agora: pinta detail pane imediatamente com r.heartbeat=None
    # (secoes SCAN/HEALTH/PROBE skipam graceful), dispara fetch em
    # daemon thread, e ao completar re-entra em _load_detail pra
    # repintar com heartbeat populado.
    client_factory = state.get("client_factory")
    launcher = state.get("launcher")
    attempted = state.setdefault("_hb_fetch_attempted", set())
    if (r.heartbeat is None and r.source == "vps"
            and launcher is not None and r.run_id not in attempted):
        # One-shot fetch per run — marcar ANTES de disparar pra nao
        # entrar em loop quando fetch falhar (heartbeat fica None mas
        # ja tentamos, nao re-dispara).
        attempted.add(r.run_id)

        def _after_fetch(_r=r, _state=state, _launcher=launcher):
            # Marshal de volta pra Tk main thread.
            try:
                _launcher.after(
                    0, lambda: _reload_if_still_selected(_r, _state),
                )
            except Exception:
                pass
        lazy_fetch_heartbeat(r, client_factory, on_complete=_after_fetch)

    for w in host.winfo_children():
        try:
            w.destroy()
        except Exception:
            pass

    _render_detail_header(host, r)

    # Banner de erro — se ultima tick falhou, mostra em destaque vermelho
    # antes de qualquer outra secao. Operador ve o problema imediatamente.
    hb = r.heartbeat or {}
    last_err = hb.get("last_error")
    if last_err:
        _render_error_banner(host, str(last_err))

    body = tk.Frame(host, bg=PANEL)
    body.pack(fill="both", expand=True, padx=10, pady=(4, 0))

    # RUNTIME — what the engine is doing right now.
    _render_block_header(body, "RUNTIME")
    _render_detail_telemetry(body, r)
    _render_detail_scan(body, r)
    _render_detail_health(body, r)
    _render_detail_probe(body, r)

    # PERFORMANCE — how it's doing.
    _render_block_header(body, "PERFORMANCE")
    _render_detail_equity_metrics(body, r)
    _render_detail_trades(body, r)

    # LOG — raw engine output.
    _render_block_header(body, "LOG")
    _render_detail_log_tail(body, r)


def _render_error_banner(parent: tk.Widget, err: str) -> None:
    """Red banner shown when the last heartbeat carries `last_error`.
    Label is H2 (8pt bold RED) so the operator registers the alert at
    first glance; text stays BODY (7pt RED) with wraplength tuned for
    the wider panes used by the cockpit-class displays."""
    bar = tk.Frame(parent, bg=BG)
    bar.pack(fill="x")
    inner = tk.Frame(bar, bg=BG)
    inner.pack(fill="x", padx=10, pady=(4, 6))
    tk.Label(inner, text="LAST ERROR", font=(FONT, 8, "bold"),
             fg=RED, bg=BG, anchor="w").pack(anchor="w")
    tk.Label(inner, text=err[:300], font=(FONT, 7),
             fg=RED, bg=BG, anchor="w", justify="left",
             wraplength=380).pack(anchor="w", pady=(1, 0))
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")


def _format_age_since(iso_str: str | None) -> str:
    """Format 'N seconds ago' relative to now. Returns 'never' if null."""
    if not iso_str:
        return "never"
    try:
        t = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        secs = int((datetime.now(timezone.utc) - t).total_seconds())
        if secs < 0:
            return "just now"
        if secs < 60:
            return f"{secs}s ago"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            h, m = divmod(secs // 60, 60)
            return f"{h}h{m:02d}m ago"
        return f"{secs // 86400}d ago"
    except Exception:  # noqa: BLE001
        return str(iso_str)[:16]


def _render_detail_scan(parent: tk.Widget, r: RunSummary) -> None:
    """SCAN funnel: scanned -> dedup -> stale -> live -> opened.

    Mostra onde o pipeline de sinais perde candidatos na ultima tick.
    Se todos os last_scan_* forem None ou 0 e nunca houve novel, nao
    renderiza a secao (run muito nova ou engine sem scan stats).
    """
    hb = r.heartbeat or {}
    scan_keys = ("last_scan_scanned", "last_scan_dedup",
                 "last_scan_stale", "last_scan_live")
    if all(hb.get(k) is None for k in scan_keys) and not hb.get("last_novel_at"):
        return

    scanned = hb.get("last_scan_scanned") or 0
    dedup = hb.get("last_scan_dedup") or 0
    stale = hb.get("last_scan_stale") or 0
    live = hb.get("last_scan_live") or 0
    opened = hb.get("last_scan_opened")
    last_novel_at = hb.get("last_novel_at")
    novel_age = _format_age_since(last_novel_at)

    rows = [
        ("scanned", str(scanned), WHITE if scanned > 0 else DIM2),
        ("dedup", str(dedup), DIM if dedup == 0 else WHITE),
        ("stale", str(stale), DIM if stale == 0 else AMBER_D),
        ("live", str(live), GREEN if live > 0 else DIM2),
    ]
    if opened is not None:
        rows.append(("opened", str(opened),
                     GREEN if opened > 0 else DIM2))
    rows.append((
        "last novel", novel_age,
        AMBER_B if last_novel_at else DIM2,
    ))
    _detail_section(parent, "SCAN (last tick)", rows)


def _render_detail_health(parent: tk.Widget, r: RunSummary) -> None:
    """HEALTH — drawdown, kill switch, primed flag, tick cadence.

    Campos paper-specific (drawdown_pct, ks_state, primed, account_size)
    aparecem so se o heartbeat reportar. Shadow que nao tem esses campos
    ainda renderiza tick_sec + cadencia real.
    """
    hb = r.heartbeat or {}
    if not hb:
        return

    rows = []
    # _as_float trata strings nao-numericas ("N/A", "") como None em vez
    # de raise. Sem isso, um cockpit mal-comportado derruba o detail pane
    # inteiro (audit 2026-04-22).
    dd_f = _as_float(hb.get("drawdown_pct"))
    if dd_f is not None:
        dd_color = (RED if dd_f >= 5 else
                    AMBER_D if dd_f >= 2 else WHITE)
        rows.append(("drawdown", f"{dd_f:.2f}%", dd_color))

    ks = hb.get("ks_state")
    if ks is not None:
        ks_str = str(ks).upper()
        ks_color = (GREEN if ks_str == "NORMAL" else
                    AMBER_D if ks_str == "WARNING" else RED)
        rows.append(("kill switch", ks_str, ks_color))

    primed = hb.get("primed")
    if primed is not None:
        rows.append((
            "primed",
            "yes" if primed else "no",
            GREEN if primed else AMBER_D,
        ))

    tick_sec = hb.get("tick_sec")
    if tick_sec is not None:
        rows.append(("tick sec", f"{int(tick_sec)}s", DIM))

    # Cadencia real: last tick age vs tick_sec esperado. Se > 2x tick_sec,
    # processo pode estar congelado mesmo com status=running.
    last_tick = hb.get("last_tick_at")
    if last_tick and tick_sec:
        age_s = None
        try:
            t = datetime.fromisoformat(str(last_tick).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            age_s = int((datetime.now(timezone.utc) - t).total_seconds())
        except Exception:  # noqa: BLE001
            pass
        if age_s is not None:
            threshold = int(tick_sec) * 2
            age_color = (RED if age_s > threshold else
                         AMBER_D if age_s > int(tick_sec) * 1.3 else WHITE)
            rows.append((
                "last tick",
                _format_age_since(last_tick),
                age_color,
            ))

    if not rows:
        return
    _detail_section(parent, "HEALTH", rows)


def _render_detail_probe(parent: tk.Widget, r: RunSummary) -> None:
    """PROBE DIAGNOSTIC — renderiza apenas quando engine == PROBE.

    Traz os campos diagnosticos do heartbeat da probe: top_score contra
    o threshold ativo, distribuicao de score (above_threshold / 80pct /
    60pct), top symbol + direction + macro regime detectado.
    """
    if str(r.engine).upper() != "PROBE":
        return
    hb = r.heartbeat or {}
    # _as_float trata strings nao-numericas como None — se o cockpit
    # mandar lixo em top_score, a secao simplesmente nao renderiza em
    # vez de crashar o detail pane (audit 2026-04-22).
    top_f = _as_float(hb.get("top_score"))
    if top_f is None:
        return

    thr = _as_float(hb.get("threshold")) or 0.62
    top_color = (GREEN if top_f >= thr else
                 AMBER_B if top_f >= thr * 0.8 else
                 AMBER_D if top_f >= thr * 0.6 else DIM)

    mean = _as_float(hb.get("mean_score")) or 0.0
    n_thr = _as_int(hb.get("n_above_threshold")) or 0
    n_80 = _as_int(hb.get("n_above_80pct")) or 0
    n_60 = _as_int(hb.get("n_above_60pct")) or 0

    rows = [
        ("top score", f"{top_f:.3f}", top_color),
        ("top symbol", str(hb.get("top_symbol") or "—"), WHITE),
        ("direction", str(hb.get("top_direction") or "—"), AMBER),
        ("macro", str(hb.get("macro") or "—"), AMBER),
        ("threshold", f"{thr:.3f}", DIM),
        ("mean score", f"{mean:.3f}", WHITE),
        ("above thr", str(n_thr),
         GREEN if n_thr > 0 else DIM2),
        ("above 80%", str(n_80),
         AMBER_B if n_80 > 0 else DIM2),
        ("above 60%", str(n_60),
         AMBER_D if n_60 > 0 else DIM2),
    ]
    _detail_section(parent, "PROBE DIAGNOSTIC", rows)


def _render_block_header(parent: tk.Widget, label: str) -> None:
    """Block header separating RUNTIME / PERFORMANCE / LOG in the right pane.

    H2 (8pt bold DIM) label followed by a 1px BORDER line that fills
    the remaining width. Same size as section titles inside the block,
    but DIM (not AMBER_D) to distinguish structural container from
    content title.
    """
    row = tk.Frame(parent, bg=PANEL)
    row.pack(fill="x", pady=(14, 2))
    tk.Label(row, text=label, font=(FONT, 8, "bold"),
             fg=DIM, bg=PANEL, anchor="w").pack(side="left", padx=(0, 6))
    tk.Frame(row, bg=BORDER, height=1).pack(
        side="left", fill="x", expand=True, pady=(6, 0))


def _render_detail_header(parent: tk.Widget, r: RunSummary) -> None:
    """Detail pane header — dot + ENGINE (H1) + MODE/STATUS/SRC (H2) +
    run_id (BODY).

    MODE color uses the semantic palette (paper=CYAN, demo=GREEN,
    testnet=AMBER, live=RED); shadow/unknown fall back to DIM. Status
    and SRC keep their existing semantic mappings. Divider below is
    BORDER (structural).
    """
    from core.ui.ui_palette import MODE_PAPER, MODE_DEMO, MODE_TESTNET, MODE_LIVE
    bar = tk.Frame(parent, bg=BG)
    bar.pack(fill="x")
    inner = tk.Frame(bar, bg=BG)
    inner.pack(fill="x", padx=10, pady=7)
    dot_color = GREEN if r.status == "running" else (
        RED if r.status == "failed" else DIM2)
    mode_map = {
        "paper": MODE_PAPER, "demo": MODE_DEMO,
        "testnet": MODE_TESTNET, "live": MODE_LIVE,
    }
    mode_color = mode_map.get(r.mode, DIM)
    src_color = GREEN if r.source == "vps" else (
        AMBER_D if r.source == "db" else CYAN)
    tk.Label(inner, text="●", fg=dot_color, bg=BG,
             font=(FONT, 10)).pack(side="left", padx=(0, 6))
    tk.Label(inner, text=r.engine, fg=WHITE, bg=BG,
             font=(FONT, 10, "bold")).pack(side="left")
    tk.Label(inner, text=f"  {r.mode.upper()}",
             fg=mode_color, bg=BG,
             font=(FONT, 8, "bold")).pack(side="left")
    tk.Label(inner, text=f"  ·  {r.status.upper()}",
             fg=dot_color, bg=BG,
             font=(FONT, 8, "bold")).pack(side="left")
    tk.Label(inner, text=f"  ·  run {r.run_id}", fg=DIM, bg=BG,
             font=(FONT, 7)).pack(side="left")
    tk.Label(inner, text=f"  ·  {r.source.upper()}",
             fg=src_color, bg=BG,
             font=(FONT, 8, "bold")).pack(side="left")
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")


def _render_detail_telemetry(parent: tk.Widget, r: RunSummary) -> None:
    # Formato alinhado com live_runs._detail_section: header AMBER_D 7
    # bold + divider + linhas label width=10 / value. Antes usava _cell
    # com grid de 6 boxes bordados que ocupava largura excessiva e
    # destoava dos outros detail panels.
    running = r.status == "running"
    dur = fmt_duration(r.started_at, r.stopped_at, r.last_tick_at, running)
    rows = [
        ("started", fmt_started(r.started_at), WHITE),
        ("duration", dur, WHITE),
        ("ticks ok", "—" if r.ticks_ok is None else str(r.ticks_ok),
         GREEN if (r.ticks_ok or 0) > 0 else DIM2),
        ("ticks fail", "—" if r.ticks_fail is None else str(r.ticks_fail),
         RED if (r.ticks_fail or 0) > 0 else DIM2),
        ("signals", "—" if r.novel is None else str(r.novel),
         AMBER_B if (r.novel or 0) > 0 else DIM2),
        ("trades", "—" if r.trades_closed is None else str(r.trades_closed),
         WHITE),
    ]
    _detail_section(parent, "TELEMETRY", rows)


def _detail_section(parent: tk.Widget, title: str,
                    rows: list[tuple[str, str, str]] | None = None,
                    extra: str | None = None) -> None:
    """Section header + optional label/value rows.

    Title is H2 (8pt bold AMBER_D). `extra` is a discreet annotation
    (e.g. 'last 10') shown in BODY (7pt normal DIM) next to the title.
    If `rows` is None, the caller builds a custom body below — useful
    for tables (TRADES) and streamed text (LOG TAIL).
    """
    hdr_row = tk.Frame(parent, bg=PANEL)
    hdr_row.pack(fill="x", pady=(10, 2))
    tk.Label(hdr_row, text=title,
             font=(FONT, 8, "bold"), fg=AMBER_D, bg=PANEL,
             anchor="w").pack(side="left")
    if extra:
        tk.Label(hdr_row, text=f"  ·  {extra}",
                 font=(FONT, 7), fg=DIM, bg=PANEL,
                 anchor="w").pack(side="left")
    tk.Frame(parent, bg=DIM2, height=1).pack(fill="x")
    if rows is None:
        return
    for k, v, color in rows:
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=0)
        tk.Label(row, text=k, font=(FONT, 7),
                 fg=DIM, bg=PANEL, anchor="w", width=10).pack(side="left")
        tk.Label(row, text=str(v), font=(FONT, 7),
                 fg=color, bg=PANEL, anchor="w").pack(side="left")


def _render_detail_equity_metrics(parent: tk.Widget, r: RunSummary) -> None:
    if r.equity is None and r.initial_balance is None:
        return
    initial = r.initial_balance or r.equity or 0.0
    eq_color = (GREEN if (r.equity or 0) >= initial else
                (RED if (r.equity or 0) < initial else WHITE))
    roi_color = (GREEN if (r.roi_pct or 0) > 0 else
                 (RED if (r.roi_pct or 0) < 0 else DIM))
    rows = [
        ("initial", fmt_equity(initial), WHITE),
        ("equity", fmt_equity(r.equity), eq_color),
        ("roi", fmt_roi(r.roi_pct), roi_color),
    ]
    _detail_section(parent, "ACCOUNT", rows)


def _render_detail_trades(parent: tk.Widget, r: RunSummary) -> None:
    """Read last 10 trades. Shadow runs write shadow_trades.jsonl; paper/live
    write trades.jsonl. Each run_dir only has one of the two — try shadow
    first (back-compat with cockpit_api), fall back to paper."""
    if r.run_dir is None:
        return
    trades_path = r.run_dir / "reports" / "shadow_trades.jsonl"
    if not trades_path.exists():
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
    _detail_section(box, "TRADES", extra=f"last {len(lines)}")
    tbl = tk.Frame(box, bg=PANEL)
    tbl.pack(fill="x", pady=(1, 4))
    hdr = tk.Frame(tbl, bg=BG)
    hdr.pack(fill="x")
    numeric_trade = {"ENTRY", "EXIT", "PNL", "R"}
    for lbl, w in [("SYMBOL", 9), ("DIR", 5), ("ENTRY", 9), ("EXIT", 9),
                   ("PNL", 9), ("R", 5), ("REASON", 8)]:
        anchor = "e" if lbl in numeric_trade else "w"
        tk.Label(hdr, text=lbl, fg=DIM, bg=BG,
                 font=(FONT, 7, "bold"), width=w,
                 anchor=anchor).pack(side="left", padx=(3, 0))
    tk.Frame(box, bg=BORDER, height=1).pack(fill="x")
    for t in lines:
        pnl = float(t.get("pnl_after_fees") or t.get("pnl") or 0.0)
        pnl_color = GREEN if pnl >= 0 else RED
        direction = str(t.get("direction", ""))[:5]
        reason = str(t.get("exit_reason") or "")[:8]
        ep = t.get("entry_price") if t.get("entry_price") is not None else t.get("entry")
        xp = t.get("exit_price") if t.get("exit_price") is not None else t.get("exit_p")
        r_mul = t.get("r_multiple")
        cells = [
            (str(t.get("symbol", "?"))[:9], WHITE, 9, "bold", "w"),
            (direction, (GREEN if direction.startswith(("L", "B"))
                          else RED), 5, "bold", "w"),
            (f"{float(ep):.5g}" if ep is not None else "—", WHITE, 9, "normal", "e"),
            (f"{float(xp):.5g}" if xp is not None else "—", WHITE, 9, "normal", "e"),
            (f"{pnl:+.2f}", pnl_color, 9, "bold", "e"),
            (f"{float(r_mul):+.2f}" if r_mul is not None else "—",
             pnl_color, 5, "normal", "e"),
            (reason, DIM, 8, "normal", "w"),
        ]
        row = tk.Frame(tbl, bg=PANEL)
        row.pack(fill="x")
        for text, color, w, weight, anchor in cells:
            tk.Label(row, text=text, fg=color, bg=PANEL,
                     font=(FONT, 7, weight), width=w,
                     anchor=anchor).pack(side="left", padx=(3, 0))


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
    _detail_section(box, "LOG TAIL", extra=log_path.name)
    txt = tk.Text(box, wrap="word", bg=BG, fg=WHITE,
                  font=(FONT, 7), padx=6, pady=4,
                  borderwidth=0, highlightthickness=0, height=10)
    txt.pack(fill="both", expand=True, pady=(1, 0))
    txt.insert("end", "\n".join(lines) + "\n")
    txt.see("end")
    txt.config(state="disabled")


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
