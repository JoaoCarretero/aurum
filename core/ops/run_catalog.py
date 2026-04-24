from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass, field
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from core import db_live_runs


ROOT = Path(__file__).resolve().parent.parent.parent
DATA_ROOT = ROOT / "data"
_LOCAL_RUNS_CACHE: dict[str, tuple[float, list["RunSummary"]]] = {}
_VPS_RUNS_CACHE: dict[int, tuple[float, list["RunSummary"]]] = {}
_DB_RUNS_CACHE: dict[str, tuple[float, list["RunSummary"]]] = {}
_RUNS_CACHE_TTL_S = 2.0

# Runs that claim status="running" but haven't emitted a heartbeat in
# this many seconds are considered dead. Paper/shadow runners tick every
# 15 minutes — 30 minutes = two missed ticks, unambiguously stale. The
# VPS cockpit never downgrades stopped runs' status on disk, so without
# this client-side check every dead-but-never-stopped run keeps showing
# up as LIVE in /data and inflates the cockpit RUNNING counter.
_RUN_STALE_THRESHOLD_S = 30 * 60


def _parse_iso_timestamp(value) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def is_run_stale(
    run: "RunSummary | dict",
    *,
    now: datetime | None = None,
    threshold_s: float = _RUN_STALE_THRESHOLD_S,
) -> bool:
    """True when a run claims status='running' but last_tick_at is older
    than ``threshold_s`` seconds. Accepts either a RunSummary or a raw
    cockpit-API dict so callers on both sides of the collection pipeline
    can share the check."""
    if isinstance(run, dict):
        status = str(run.get("status") or "").lower()
        last_tick = run.get("last_tick_at")
    else:
        status = str(run.status or "").lower()
        last_tick = run.last_tick_at
    if status != "running":
        return False
    ts = _parse_iso_timestamp(last_tick)
    if ts is None:
        # No last_tick_at yet — treat as still-priming, not stale. The
        # runner writes it on the first successful tick.
        return False
    reference = now or datetime.now(timezone.utc)
    return (reference - ts).total_seconds() > threshold_s


def resolve_status(raw_status, last_tick_at) -> str:
    """Normalize the status string, downgrading stale 'running' to 'stale'.

    Applied at collection time on local + VPS sources so every downstream
    consumer (cockpit RUNNING counters, /data engines LIVE/FINISHED split,
    anything filtering by status) sees a status that reflects reality."""
    status = str(raw_status or "unknown")
    if status.lower() != "running":
        return status
    ts = _parse_iso_timestamp(last_tick_at)
    if ts is None:
        return status
    if (datetime.now(timezone.utc) - ts).total_seconds() > _RUN_STALE_THRESHOLD_S:
        return "stale"
    return status


@dataclass
class RunSummary:
    run_id: str
    engine: str
    mode: str
    status: str
    started_at: str | None
    stopped_at: str | None
    last_tick_at: str | None
    ticks_ok: int | None
    ticks_fail: int | None
    novel: int | None
    equity: float | None
    initial_balance: float | None
    roi_pct: float | None
    trades_closed: int | None
    source: str
    run_dir: Path | None
    heartbeat: dict | None
    host: str | None = None
    label: str | None = None
    open_count: int | None = None
    notes: str | None = None
    _raw: dict = field(default_factory=dict)


def collect_local_runs(data_root: Path | None = None) -> list[RunSummary]:
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
            _scan_engine_dir(engine_dir, name.removesuffix("_shadow").upper(), "shadow", rows)
        elif name.endswith("_paper"):
            _scan_engine_dir(engine_dir, name.removesuffix("_paper").upper(), "paper", rows)
        elif name.endswith("_live"):
            _scan_engine_dir(engine_dir, name.removesuffix("_live").upper(), "live", rows)
        elif name == "shadow":
            for sub in engine_dir.iterdir():
                if sub.is_dir():
                    _scan_engine_dir(sub, sub.name.upper(), "shadow", rows)
    _store_cached_rows(_LOCAL_RUNS_CACHE, cache_key, rows)
    return rows


def collect_vps_runs(client) -> list[RunSummary]:
    """Fast list of VPS runs from ``GET /v1/runs`` only.

    Previous implementation fanned out to
    ``/v1/runs/{id}/heartbeat`` + ``/v1/runs/{id}/account`` for every
    row — 2*N extra HTTP calls through the SSH tunnel. With 24 live
    runs that was ~48 serialised round-trips, wall time ~6s, stalling
    the Live Cockpit every time the cache expired. The heartbeat/
    account data is only needed when the operator drills into a
    specific run; fetch it on demand there (see
    ``_collect_single_vps_run`` for the deep-fetch helper, still
    available for callers that genuinely need per-run detail).
    """
    rows: list[RunSummary] = []
    if client is None:
        return rows
    cache_key = id(client)
    cached = _cached_rows(_VPS_RUNS_CACHE, cache_key)
    if cached is not None:
        return cached
    try:
        runs = client._get("/v1/runs")
    except Exception:
        return rows
    if not isinstance(runs, list):
        return rows
    for payload in runs:
        rid = payload.get("run_id")
        if not rid:
            continue
        equity_val = payload.get("equity")
        try:
            equity_f = float(equity_val) if equity_val is not None else None
        except (TypeError, ValueError):
            equity_f = None
        rows.append(RunSummary(
            run_id=rid,
            engine=str(payload.get("engine") or "?").upper(),
            mode=str(payload.get("mode") or "?"),
            status=str(payload.get("status") or "unknown"),
            started_at=payload.get("started_at"),
            stopped_at=None,
            last_tick_at=payload.get("last_tick_at"),
            ticks_ok=_as_int(payload.get("ticks_ok")),
            ticks_fail=_as_int(payload.get("ticks_fail")),
            novel=_as_int(payload.get("novel_total") or payload.get("novel_count")),
            equity=equity_f,
            initial_balance=None,
            roi_pct=None,
            trades_closed=None,
            source="vps",
            run_dir=None,
            heartbeat=None,
            host=str(payload.get("host") or "") or None,
            label=str(payload.get("label") or "") or None,
            open_count=None,
            _raw=payload,
        ))
    _store_cached_rows(_VPS_RUNS_CACHE, cache_key, rows)
    return rows


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
        out.append(
            RunSummary(
                run_id=str(row.get("run_id") or ""),
                engine=str(row.get("engine") or "?").upper(),
                mode=str(row.get("mode") or "?"),
                status=str(row.get("status") or "unknown"),
                started_at=row.get("started_at"),
                stopped_at=row.get("ended_at"),
                last_tick_at=row.get("last_tick_at"),
                ticks_ok=_as_int(row.get("tick_count")),
                ticks_fail=None,
                novel=_as_int(row.get("novel_count")),
                equity=_as_float(row.get("equity")),
                initial_balance=None,
                roi_pct=None,
                trades_closed=None,
                source="db",
                run_dir=run_dir,
                heartbeat=None,
                host=str(row.get("host") or "") or None,
                label=str(row.get("label") or "") or None,
                open_count=_as_int(row.get("open_count")),
                notes=str(row.get("notes") or "") or None,
                _raw=dict(row),
            )
        )
    _store_cached_rows(_DB_RUNS_CACHE, cache_key, out)
    return out


def merge_runs(
    local: list[RunSummary],
    vps: list[RunSummary],
    db_rows: list[RunSummary] | None = None,
) -> list[RunSummary]:
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
    out.sort(key=recency_key, reverse=True)
    return out


def list_runs_catalog(*, mode: str | None = None, client=None, limit_db: int = 500) -> list[RunSummary]:
    local = collect_local_runs()
    db_rows = collect_db_runs(mode=mode, limit=limit_db)
    vps = collect_vps_runs(client)
    rows = merge_runs(local, vps, db_rows)
    if mode is not None:
        rows = [row for row in rows if row.mode == mode]
    return rows


def latest_active_run(
    *,
    engine: str | None = None,
    mode: str | None = None,
    client=None,
    limit_db: int = 500,
) -> RunSummary | None:
    rows = list_runs_catalog(mode=mode, client=client, limit_db=limit_db)
    if engine is not None:
        want = str(engine).strip().upper()
        rows = [row for row in rows if row.engine == want]
    rows = [row for row in rows if str(row.status or "").lower() == "running"]
    return rows[0] if rows else None


def get_run_summary(run_id: str, *, client=None, limit_db: int = 500) -> RunSummary | None:
    for row in list_runs_catalog(client=client, limit_db=limit_db):
        if row.run_id == run_id:
            return row
    return None


def infer_log_path(run_dir: Path | None) -> Path | None:
    if run_dir is None:
        return None
    logs_dir = run_dir / "logs"
    candidates = (
        logs_dir / "shadow.log",
        logs_dir / "paper.log",
        logs_dir / "live.log",
        logs_dir / "engine.log",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if logs_dir.exists():
        try:
            globs = sorted(logs_dir.glob("*.log"))
        except OSError:
            globs = []
        if globs:
            return globs[0]
    return None


def summary_to_engine_log_row(summary: RunSummary, *, remote: bool = False) -> dict:
    log_path = None if remote else infer_log_path(summary.run_dir)
    started = str(summary.started_at or summary.last_tick_at or "")[:16].replace("T", " ")
    engine_label = summary.engine
    if summary.mode in {"shadow", "paper"}:
        engine_label = f"{summary.engine} ({summary.mode})"
    hb = summary.heartbeat or {}
    if summary.started_at and "started_at" not in hb:
        hb["started_at"] = summary.started_at
    if summary.last_tick_at and "last_tick_at" not in hb:
        hb["last_tick_at"] = summary.last_tick_at
    if summary.novel is not None and "novel_total" not in hb:
        hb["novel_total"] = summary.novel
    if summary.status and "status" not in hb:
        hb["status"] = summary.status
    return {
        "engine": engine_label,
        "mode": summary.mode,
        "pid": "VPS" if remote and summary.status == "running" else "-",
        "started": started,
        "started_at": summary.started_at,
        "alive": str(summary.status or "").lower() == "running",
        "log": f"remote:{summary.run_id}" if remote else (str(log_path) if log_path else ""),
        "run_dir": f"remote://{summary.run_id}" if remote else (str(summary.run_dir) if summary.run_dir else ""),
        "_remote": remote,
        "_run_id": summary.run_id,
        "_heartbeat": hb,
        "_summary": summary,
    }


def engine_log_run_id_of(row: dict) -> str | None:
    rid = row.get("_run_id")
    if rid:
        return str(rid)
    rd = row.get("run_dir")
    if not rd:
        return None
    text = str(rd).rstrip("/\\")
    if not text:
        return None
    return text.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]


def engine_log_row_key(row: dict) -> str:
    rid = engine_log_run_id_of(row)
    if rid:
        return f"run:{rid}"
    pid = row.get("pid")
    log_file = row.get("log_file") or row.get("log") or ""
    return f"pid:{pid}|log:{log_file}"


def engine_log_recency_key(row: dict) -> float:
    for key in ("last_tick_at", "started_at", "started"):
        v = row.get(key) or row.get("_heartbeat", {}).get(key)
        if not v:
            continue
        try:
            ts = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts.timestamp()
        except Exception:
            continue
    return 0.0


def _legacy_engine_log_header_unused(row: dict) -> str:
    engine = row.get("engine", "?")
    pid = row.get("pid")
    log_file = row.get("log_file") or row.get("log") or ""
    return f"  {engine} · pid {pid} · {log_file}"


def normalize_engine_log_local_proc(proc: dict) -> dict:
    out = dict(proc)
    out.setdefault("alive", bool(proc.get("alive")))
    out["_remote"] = False
    out["src"] = "local"
    out.setdefault("mode", str(proc.get("mode") or "live"))
    return out


def engine_known_slugs(proc_engines: dict | None = None) -> set[str]:
    known = {str(name).lower() for name in (proc_engines or {}).keys()}
    known.update({
        "aqr", "arbitrage", "backtest", "bridgewater", "citadel",
        "darwin", "deshaw", "graham", "harmonics", "janestreet",
        "jump", "kepos", "live", "mercurio", "millennium",
        "multistrategy", "newton", "prometeu", "renaissance",
        "thoth", "twosigma", "winton",
    })
    return known


def engine_base_slug(row: dict) -> str:
    raw = str(row.get("engine") or "").strip().lower()
    if "(" in raw:
        raw = raw.split("(", 1)[0].strip()
    return raw


def is_engine_log_row(row: dict, *, known_slugs: set[str] | None = None) -> bool:
    if row.get("_remote"):
        return True
    base = engine_base_slug(row)
    if base in {"prefetch"}:
        return False
    return base in (known_slugs or engine_known_slugs())


def matches_engine_mode_filter(row: dict, mode_filter: str = "all") -> bool:
    current = str(mode_filter or "all").strip().lower()
    if current == "all":
        return True
    return str(row.get("mode") or "").strip().lower() == current


def list_engine_log_sections(
    *,
    client=None,
    mode_filter: str = "all",
    vps_limit: int = 20,
    historical_limit: int = 30,
    historical_hours: int = 72,
) -> tuple[list[dict], list[dict], str | None]:
    try:
        from core.ops.proc import ENGINES as proc_engines
        from core.ops.proc import list_procs
        local_procs = [normalize_engine_log_local_proc(p) for p in (list_procs() or [])]
    except Exception as exc:
        proc_engines = {}
        local_procs = []
        error = f"list_procs failed: {exc}"
    else:
        error = None

    known_slugs = engine_known_slugs(proc_engines)
    local_procs = [p for p in local_procs if is_engine_log_row(p, known_slugs=known_slugs)]
    vps_rows = collect_engine_log_vps_rows(client, limit=vps_limit)
    historical = collect_engine_log_local_rows(limit=historical_limit, hours=historical_hours)
    vps_ids = {engine_log_run_id_of(r) for r in vps_rows if engine_log_run_id_of(r)}
    historical = [
        row for row in historical
        if engine_log_run_id_of(row) not in vps_ids and is_engine_log_row(row, known_slugs=known_slugs)
    ]

    running: list[dict] = []
    stopped: list[dict] = []
    for row in local_procs + vps_rows + historical:
        if not matches_engine_mode_filter(row, mode_filter):
            continue
        if row.get("alive"):
            running.append(row)
        else:
            stopped.append(row)

    running_keys = {
        (
            str(row.get("engine") or "").strip().lower(),
            str(row.get("mode") or "").strip().lower(),
        )
        for row in running
    }
    stopped = [
        row for row in stopped
        if (
            str(row.get("engine") or "").strip().lower(),
            str(row.get("mode") or "").strip().lower(),
        ) not in running_keys
    ]
    running.sort(key=engine_log_recency_key, reverse=True)
    stopped.sort(key=engine_log_recency_key, reverse=True)
    return running, stopped, error


def engine_log_header(row: dict) -> str:
    engine = row.get("engine", "?")
    pid = row.get("pid")
    log_file = row.get("log_file") or row.get("log") or ""
    return f"  {engine} | pid {pid} | {log_file}"


def collect_engine_log_vps_rows(client, *, limit: int = 20) -> list[dict]:
    if client is None:
        return []
    try:
        payload = client._get("/v1/runs")
    except Exception:
        return []
    if not isinstance(payload, list):
        return []

    rows: list[dict] = []
    for raw in payload:
        status = str(raw.get("status") or "unknown")
        mode = str(raw.get("mode") or "?")
        if status.lower() != "running" or mode.lower() not in {"shadow", "paper"}:
            continue
        hb = {
            "status": status,
            "started_at": raw.get("started_at"),
            "last_tick_at": raw.get("last_tick_at"),
        }
        if raw.get("novel_since_prime") is not None:
            hb["novel_since_prime"] = raw.get("novel_since_prime")
        if raw.get("novel_total") is not None:
            hb["novel_total"] = raw.get("novel_total")
        summary = RunSummary(
            run_id=str(raw.get("run_id") or ""),
            engine=str(raw.get("engine") or "?").upper(),
            mode=mode,
            status=status,
            started_at=raw.get("started_at"),
            stopped_at=raw.get("ended_at") or raw.get("stopped_at"),
            last_tick_at=raw.get("last_tick_at"),
            ticks_ok=_as_int(raw.get("tick_count")),
            ticks_fail=None,
            novel=_as_int(raw.get("novel_since_prime") if raw.get("novel_since_prime") is not None else raw.get("novel_total")),
            equity=_as_float(raw.get("equity")),
            initial_balance=None,
            roi_pct=None,
            trades_closed=None,
            source="vps",
            run_dir=None,
            heartbeat=hb,
            host=str(raw.get("host") or "") or None,
            label=str(raw.get("label") or "") or None,
            open_count=_as_int(raw.get("open_count")),
            notes=str(raw.get("notes") or "") or None,
            _raw=dict(raw),
        )
        rows.append(summary_to_engine_log_row(summary, remote=True))
    rows.sort(key=engine_log_recency_key, reverse=True)
    return rows[:limit]


def collect_engine_log_local_rows(*, limit: int = 30, hours: int = 72) -> list[dict]:
    cutoff = time.time() - (hours * 3600)
    rows: list[dict] = []
    for summary in collect_local_runs():
        run_dir = summary.run_dir
        if run_dir is None:
            continue
        try:
            mtime = run_dir.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            continue
        row = summary_to_engine_log_row(summary, remote=False)
        row["alive"] = False
        rows.append(row)
    rows.sort(key=engine_log_recency_key, reverse=True)
    return rows[:limit]


def fetch_remote_entries(client, run_id: str, *, mode: str | None = None, limit: int = 50) -> tuple[list[str], str]:
    if client is None:
        return [], "cockpit not configured"
    if not run_id:
        return [], "no run_id"
    try:
        payload = client._get(f"/v1/runs/{run_id}/trades?limit={int(limit)}") or {}
    except Exception as exc:
        return [], f"fetch failed: {type(exc).__name__}"
    records = payload.get("trades") or []
    if not records:
        return [], "sem entries"
    return [format_entry_line(rec) for rec in records], f"{len(records)} entries"


def read_local_entries(run_dir: Path | str | None, *, limit: int = 50) -> tuple[list[str], str]:
    if not run_dir:
        return [], "sem run_dir"
    base = Path(run_dir)
    for candidate in ("reports/shadow_trades.jsonl",
                      "reports/trades.jsonl",
                      "reports/signals.jsonl"):
        path = base / candidate
        if not path.exists():
            continue
        records = _tail_jsonl_records(path, limit=limit)
        if not records:
            continue
        return [format_entry_line(rec) for rec in records], f"{len(records)} from {candidate}"
    return [], "sem entries no run_dir"


def format_entry_line(rec: dict) -> str:
    ts = (rec.get("ts") or rec.get("timestamp") or rec.get("shadow_observed_at") or "")
    ts_s = str(ts)[:19].replace("T", " ")
    strat = str(rec.get("strategy") or rec.get("engine") or "?")[:11]
    sym = str(rec.get("symbol") or "?")[:9]
    direction = str(rec.get("direction") or rec.get("trade_type") or "")[:4]
    entry = rec.get("entry") or rec.get("entry_price")
    decision = rec.get("decision") or rec.get("exit_reason") or ""
    pnl = rec.get("pnl") or rec.get("pnl_after_fees")
    tail = ""
    if pnl is not None:
        tail = f"  pnl={pnl:+.2f}"
    elif decision:
        tail = f"  [{decision}]"
    entry_s = f"  entry={entry:.5g}" if isinstance(entry, (int, float)) else ""
    return f"{ts_s}  {strat:<11} {sym:<9} {direction:<4}{entry_s}{tail}"


def fetch_remote_log_tail(client, run_id: str, *, tail: int = 500) -> tuple[list[str], str | None]:
    if client is None:
        return [], "(cockpit_api not configured — VPS logs unavailable)"
    try:
        payload = client._get(f"/v1/runs/{run_id}/log?tail={int(tail)}")
    except Exception as exc:
        return [], f"(cockpit log fetch failed: {type(exc).__name__})"
    lines = payload.get("lines") if isinstance(payload, dict) else None
    return list(lines or []), None


def read_log_seed_lines(log_path: Path | str, *, limit: int = 500) -> tuple[list[str], str | None]:
    path = Path(log_path)
    if not path.exists():
        return [], f"(log file not found: {path})"
    try:
        return _tail_text_lines(path, limit=limit), None
    except OSError as exc:
        return [], f"(log read error: {exc})"


def clear_collect_caches() -> None:
    _LOCAL_RUNS_CACHE.clear()
    _VPS_RUNS_CACHE.clear()
    _DB_RUNS_CACHE.clear()


def recency_key(r: RunSummary) -> float:
    for v in (r.last_tick_at, r.started_at):
        if not v:
            continue
        try:
            ts = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts.timestamp()
        except Exception:
            continue
    return 0.0


def _scan_engine_dir(engine_dir: Path, engine: str, mode: str, rows: list[RunSummary]) -> None:
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
        except Exception:
            hb = {}
        rows.append(_summary_from_local(run_dir, engine, mode, hb))


def _summary_from_local(run_dir: Path, engine: str, mode: str, hb: dict) -> RunSummary:
    account: dict | None = None
    acct_path = run_dir / "state" / "account.json"
    if acct_path.exists():
        try:
            account = json.loads(acct_path.read_text(encoding="utf-8"))
        except Exception:
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
        except Exception:
            pass
    novel = hb.get("novel_since_prime")
    if novel is None:
        novel = hb.get("novel_total")
    return RunSummary(
        run_id=str(hb.get("run_id") or run_dir.name),
        engine=engine,
        mode=mode,
        status=resolve_status(hb.get("status"), hb.get("last_tick_at")),
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


def _collect_single_vps_run(client, payload: dict) -> RunSummary | None:
    rid = payload.get("run_id")
    if not rid:
        return None
    hb: dict = {}
    account: dict | None = None
    try:
        hb = client._get(f"/v1/runs/{rid}/heartbeat") or {}
    except Exception:
        hb = {}
    try:
        account = client._get(f"/v1/runs/{rid}/account")
        if isinstance(account, dict) and not account.get("available", True):
            account = None
    except Exception:
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
        except Exception:
            pass
    novel = hb.get("novel_since_prime")
    if novel is None:
        novel = hb.get("novel_total", payload.get("novel_total"))
    last_tick_at = payload.get("last_tick_at") or hb.get("last_tick_at")
    return RunSummary(
        run_id=rid,
        engine=str(payload.get("engine") or hb.get("engine") or "?").upper(),
        mode=str(payload.get("mode") or hb.get("mode") or "?"),
        status=resolve_status(
            payload.get("status") or hb.get("status"), last_tick_at,
        ),
        started_at=payload.get("started_at") or hb.get("started_at"),
        stopped_at=hb.get("stopped_at"),
        last_tick_at=last_tick_at,
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


def _tail_text_lines(path: Path, *, limit: int) -> list[str]:
    buf: deque[str] = deque(maxlen=max(1, int(limit)))
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            buf.append(line.rstrip("\n"))
    return list(buf)


def _tail_jsonl_records(path: Path, *, limit: int) -> list[dict]:
    out: list[dict] = []
    for ln in _tail_text_lines(path, limit=limit):
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out
