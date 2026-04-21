"""
AURUM Finance — Analysis Export
===============================
Collects every scrap of run state the system has into a single
JSON snapshot suitable for external review (Claude.ai, ChatGPT,
any tool that accepts one file per upload).

The contract is shaped by the ``export_analysis`` docstring and the
accompanying test suite in ``tests/test_analysis_export.py``. The
output is ALWAYS a dict; ``output_path`` is an optional side-effect.

Design decisions
----------------
- Everything is best-effort: a missing file, a bad JSON blob, or a
  missing directory yields ``None`` / empty list instead of an
  exception. The export must never fail loudly when the system is
  mid-crash — that is exactly when we need the snapshot.
- Trades per run are truncated to ``TRADES_PER_RUN_MAX`` to keep the
  final file under Claude.ai's 2 MB upload ceiling. The underlying
  summary still carries the full count.
- Logs are tailed to ``LOG_TAIL_LINES`` per file for the same reason.
- ``root`` parameter allows tests to point at a fake project tree;
  production callers omit it and fall back to the real project root.
"""
from __future__ import annotations

import json
import sys
import platform
import logging
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

from config.runtime import snapshot as config_snapshot
from core.health import runtime_health
from core.persistence import atomic_write_text
from core.versioned_state import with_schema_version

log = logging.getLogger("analysis_export")

ROOT = Path(__file__).resolve().parent.parent.parent

RUNS_MAX = 20
LIVE_SESSIONS_MAX = 10
ARB_SESSIONS_MAX = 5
TRADES_PER_RUN_MAX = 500          # latest run only
TRADES_PER_OLDER_RUN_MAX = 20     # older runs carry just a sample
LOG_TAIL_LINES = 100
AURUM_VERSION = "4.0"
ANALYSIS_EXPORT_SCHEMA_VERSION = "analysis_export.v1"


# ══════════════════════════════════════════════════════════════
#  Small file helpers — every one swallows its own errors
# ══════════════════════════════════════════════════════════════
def _safe_read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_tail(path: Path, n_lines: int = LOG_TAIL_LINES) -> str | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            lines = deque(f, maxlen=n_lines)
        return "".join(lines)
    except Exception:
        return None


def _engine_from_run_id(run_id: str) -> str:
    # e.g. "citadel_2026-04-11_1528" -> "citadel"
    first = run_id.split("_", 1)[0]
    return first or "unknown"


# ══════════════════════════════════════════════════════════════
#  META + CONFIG
# ══════════════════════════════════════════════════════════════
def _collect_meta(root: Path) -> dict:
    return {
        "schema_version": ANALYSIS_EXPORT_SCHEMA_VERSION,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "aurum_version": AURUM_VERSION,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "root": str(root),
    }


def _collect_config() -> dict:
    """Pull the live parameter values via ``config.params``. Everything
    is wrapped so a missing symbol does not sink the export."""
    out: dict = {}
    try:
        snap = config_snapshot().as_dict()
        out["account_size"] = snap["risk"]["account_size"]
        out["leverage"] = snap["risk"]["leverage"]
        out["base_risk"] = snap["risk"]["base_risk"]
        out["max_risk"] = snap["risk"]["max_risk"]
        out["kelly_frac"] = snap["risk"]["kelly_frac"]
        out["slippage"] = snap["market_costs"]["slippage"]
        out["spread"] = snap["market_costs"]["spread"]
        out["commission"] = snap["market_costs"]["commission"]
        out["funding_per_8h"] = snap["market_costs"]["funding_per_8h"]
        out["entry_tf"] = snap["entry"]["entry_tf"]
        out["max_open_positions"] = snap["risk"]["max_open_positions"]
        out["score_threshold"] = snap["entry"]["score_threshold"]
        out["corr_threshold"] = snap["risk"]["corr_threshold"]
        out["stop_atr_m"] = snap["entry"]["stop_atr_m"]
        out["target_rr"] = snap["entry"]["target_rr"]
        out["symbols"] = snap["symbols"]
        return out
    except Exception:
        runtime_health.record("analysis_export.config_snapshot_failure")
        return out


# ══════════════════════════════════════════════════════════════
#  RUNS
# ══════════════════════════════════════════════════════════════
def _collect_run(run_dir: Path, trades_cap: int = TRADES_PER_RUN_MAX) -> dict:
    run_id = run_dir.name
    entry: dict = {
        "run_id": run_id,
        "engine": _engine_from_run_id(run_id),
        "timestamp": None,
        "summary": _safe_read_json(run_dir / "summary.json"),
        "config_snapshot": _safe_read_json(run_dir / "config.json"),
        "overfit": _safe_read_json(run_dir / "overfit.json"),
        "equity_curve": _safe_read_json(run_dir / "equity.json"),
        "trades": [],
        "log_tail": _safe_tail(run_dir / "log.txt"),
        "pre_l6": None,
    }

    try:
        entry["timestamp"] = datetime.fromtimestamp(run_dir.stat().st_mtime).isoformat(timespec="seconds")
    except Exception:
        pass

    # Trades: accept either a raw list or ``{"trades": [...]}``.
    trades_raw = _safe_read_json(run_dir / "trades.json")
    trades_list: list = []
    if isinstance(trades_raw, list):
        trades_list = trades_raw
    elif isinstance(trades_raw, dict):
        tval = trades_raw.get("trades")
        if isinstance(tval, list):
            trades_list = tval
    if len(trades_list) > trades_cap:
        trades_list = trades_list[-trades_cap:]
    entry["trades"] = trades_list

    return entry


def _collect_runs(root: Path) -> list[dict]:
    """Collect up to RUNS_MAX runs, newest first.

    Size budget: Claude.ai caps uploads around 2 MB. Carrying 500
    trades in every run explodes that ceiling, so only the newest run
    keeps a full slice — older runs ship a small sample that preserves
    schema shape without ballooning the payload.
    """
    runs_dir = root / "data" / "runs"
    if not runs_dir.exists():
        return []
    try:
        dirs = [d for d in runs_dir.iterdir() if d.is_dir()]
    except Exception:
        return []
    dirs.sort(key=lambda d: d.name, reverse=True)
    out: list[dict] = []
    for i, d in enumerate(dirs[:RUNS_MAX]):
        cap = TRADES_PER_RUN_MAX if i == 0 else TRADES_PER_OLDER_RUN_MAX
        try:
            out.append(_collect_run(d, trades_cap=cap))
        except Exception as e:
            log.warning(f"collect_run failed for {d.name}: {e}")
    return out


# ══════════════════════════════════════════════════════════════
#  LIVE + ARBITRAGE SESSIONS
# ══════════════════════════════════════════════════════════════
def _collect_live_sessions(root: Path) -> list[dict]:
    base = root / "data" / "live"
    if not base.exists():
        return []
    try:
        dirs = sorted(
            [d for d in base.iterdir() if d.is_dir()],
            key=lambda d: d.name,
            reverse=True,
        )
    except Exception:
        return []
    out: list[dict] = []
    for d in dirs[:LIVE_SESSIONS_MAX]:
        log_path = d / "logs" / "live.log"
        tail = _safe_tail(log_path, n_lines=LOG_TAIL_LINES)
        crashed = bool(tail and "Traceback" in tail)
        trades_count = 0
        trades_log = d / "logs" / "trades.log"
        try:
            if trades_log.exists():
                trades_count = sum(1 for _ in trades_log.open("r", encoding="utf-8", errors="replace"))
        except Exception:
            pass
        out.append({
            "run_id": d.name,
            "log_tail": tail,
            "trades_count": trades_count,
            "crash": crashed,
        })
    return out


def _collect_arbitrage_sessions(root: Path) -> list[dict]:
    base = root / "data" / "arbitrage"
    if not base.exists():
        return []
    try:
        dirs = sorted(
            [d for d in base.iterdir() if d.is_dir()],
            key=lambda d: d.name,
            reverse=True,
        )
    except Exception:
        return []
    out: list[dict] = []
    for d in dirs[:ARB_SESSIONS_MAX]:
        log_path = d / "logs" / "arb.log"
        tail = _safe_tail(log_path, n_lines=LOG_TAIL_LINES)
        report = None
        rep_dir = d / "reports"
        if rep_dir.exists():
            try:
                json_files = [p for p in rep_dir.iterdir() if p.suffix == ".json"]
                if json_files:
                    report = _safe_read_json(sorted(json_files)[-1])
            except Exception:
                pass
        out.append({
            "run_id": d.name,
            "log_tail": tail,
            "report": report,
        })
    return out


# ══════════════════════════════════════════════════════════════
#  ANALYSIS — aggregate stats for the latest run
# ══════════════════════════════════════════════════════════════
def _empty_analysis() -> dict:
    return {
        "latest_run_id": None,
        "n_trades": 0,
        "win_rate": 0.0,
        "sortino": None,
        "profit_factor": None,
        "max_dd_pct": None,
        "avg_r_multiple": None,
        "avg_duration": None,
        "trades_by_symbol": {},
        "trades_by_direction": {},
        "trades_by_regime": {},
        "trades_by_month": {},
        "chop_trades": {"n": 0, "wr": 0.0, "pnl": 0.0},
        "omega_distribution": {},
        "hmm_regime": {"available": False, "distribution": {},
                       "trades_by_hmm_regime": {}},
        "cost_breakdown": {"total_slippage": None, "total_commission": None,
                           "total_funding": None, "total_costs": None,
                           "gross_pnl": 0.0, "net_pnl": 0.0,
                           "cost_pct_of_gross": None},
    }


def _grouped(trades: list, key: str) -> dict:
    groups: dict[str, list] = defaultdict(list)
    for t in trades:
        k = t.get(key)
        if k is None:
            continue
        groups[str(k)].append(t)
    out: dict[str, dict] = {}
    for k, ts in groups.items():
        n = len(ts)
        wins = sum(1 for t in ts if t.get("result") == "WIN")
        pnl = sum(float(t.get("pnl") or 0) for t in ts)
        rs = [float(t.get("r_multiple") or 0) for t in ts if t.get("r_multiple") is not None]
        out[k] = {
            "n": n,
            "wr": round(100.0 * wins / n, 2) if n else 0.0,
            "pnl": round(pnl, 2),
            "avg_r": round(sum(rs) / len(rs), 4) if rs else 0.0,
        }
    return out


def _build_analysis(latest_run: dict | None) -> dict:
    base = _empty_analysis()
    if not latest_run:
        return base
    base["latest_run_id"] = latest_run.get("run_id")
    trades = latest_run.get("trades") or []
    closed = [t for t in trades if t.get("result") in ("WIN", "LOSS")]
    base["n_trades"] = len(closed)
    if not closed:
        return base

    wins = sum(1 for t in closed if t.get("result") == "WIN")
    base["win_rate"] = round(100.0 * wins / len(closed), 2)

    rs = [float(t.get("r_multiple") or 0) for t in closed if t.get("r_multiple") is not None]
    if rs:
        base["avg_r_multiple"] = round(sum(rs) / len(rs), 4)
    durs = [float(t.get("duration") or 0) for t in closed if t.get("duration") is not None]
    if durs:
        base["avg_duration"] = round(sum(durs) / len(durs), 2)

    # Pull summary fields the backtest engines already compute.
    summary = latest_run.get("summary") or {}
    base["sortino"] = summary.get("sortino")
    base["max_dd_pct"] = summary.get("max_dd_pct") or summary.get("max_dd")

    # Profit factor
    gross_win = sum(float(t.get("pnl") or 0) for t in closed if t.get("result") == "WIN")
    gross_loss = abs(sum(float(t.get("pnl") or 0) for t in closed if t.get("result") == "LOSS"))
    base["profit_factor"] = round(gross_win / gross_loss, 3) if gross_loss > 0 else None

    base["trades_by_symbol"] = _grouped(closed, "symbol")
    base["trades_by_direction"] = _grouped(closed, "direction")
    base["trades_by_regime"] = _grouped(closed, "macro_bias")

    # Monthly buckets by YYYY-MM from timestamp.
    month_buckets: dict[str, list] = defaultdict(list)
    for t in closed:
        ts = t.get("timestamp") or t.get("time") or ""
        try:
            month = str(ts)[:7] if len(str(ts)) >= 7 else "unknown"
        except Exception:
            month = "unknown"
        month_buckets[month].append(t)
    month_out: dict[str, dict] = {}
    for m, ts in month_buckets.items():
        n = len(ts)
        w = sum(1 for t in ts if t.get("result") == "WIN")
        month_out[m] = {
            "n": n,
            "wr": round(100.0 * w / n, 2) if n else 0.0,
            "pnl": round(sum(float(t.get("pnl") or 0) for t in ts), 2),
        }
    base["trades_by_month"] = month_out

    # CHOP mean-reversion slice
    chop_ts = [t for t in closed if t.get("chop_trade")]
    if chop_ts:
        cw = sum(1 for t in chop_ts if t.get("result") == "WIN")
        base["chop_trades"] = {
            "n": len(chop_ts),
            "wr": round(100.0 * cw / len(chop_ts), 2),
            "pnl": round(sum(float(t.get("pnl") or 0) for t in chop_ts), 2),
        }

    # Omega component averages (skip if the columns are absent)
    omega_keys = ["omega_struct", "omega_flow", "omega_cascade",
                  "omega_momentum", "omega_pullback"]
    for k in omega_keys:
        vals = [float(t.get(k)) for t in closed if t.get(k) is not None]
        if vals:
            base["omega_distribution"][k.replace("omega_", "")] = round(sum(vals) / len(vals), 4)

    # HMM regime analysis — only if the column exists on the latest run
    has_hmm = any(t.get("hmm_regime") for t in closed)
    if has_hmm:
        by_hmm = _grouped(closed, "hmm_regime")
        dist: dict[str, float] = {}
        total_n = sum(v["n"] for v in by_hmm.values()) or 1
        for regime, v in by_hmm.items():
            dist[regime] = round(v["n"] / total_n, 3)
        base["hmm_regime"] = {
            "available": True,
            "distribution": dist,
            "trades_by_hmm_regime": by_hmm,
        }

    # Cost breakdown (best-effort — the backtest engines don't always
    # break PnL into cost components, so we estimate from config rates
    # applied to executed size×price).
    total_slippage = 0.0
    total_commission = 0.0
    total_funding = 0.0
    try:
        from config.params import SLIPPAGE, SPREAD, COMMISSION, FUNDING_PER_8H
        slip_rate = float(SLIPPAGE) + float(SPREAD)
        comm_rate = float(COMMISSION)
        fund_rate = float(FUNDING_PER_8H)
    except Exception:
        slip_rate = comm_rate = fund_rate = 0.0
    for t in closed:
        size = float(t.get("size") or 0)
        entry = float(t.get("entry") or 0)
        dur = float(t.get("duration") or 0)
        notional = size * entry
        total_slippage += notional * slip_rate
        total_commission += notional * comm_rate * 2  # entry + exit
        total_funding += abs(notional * fund_rate * dur / 32)
    net_pnl = sum(float(t.get("pnl") or 0) for t in closed)
    total_costs = total_slippage + total_commission + total_funding
    gross_pnl = net_pnl + total_costs
    base["cost_breakdown"] = {
        "total_slippage": round(total_slippage, 2),
        "total_commission": round(total_commission, 2),
        "total_funding": round(total_funding, 2),
        "total_costs": round(total_costs, 2),
        "gross_pnl": round(gross_pnl, 2),
        "net_pnl": round(net_pnl, 2),
        "cost_pct_of_gross": round(100.0 * total_costs / gross_pnl, 2)
                             if gross_pnl > 0 else None,
    }

    return base


# ══════════════════════════════════════════════════════════════
#  SYSTEM STATE + COMPARISON
# ══════════════════════════════════════════════════════════════
def _collect_system_state(root: Path) -> dict:
    state: dict = {
        "schema_version": "system_state.v1",
        "smoke_test": None,
        "kill_switch": None,
        "connections": None,
        "last_session_log": None,
        "pending_phases": [],
        "risk_gates_config": _safe_read_json(root / "config" / "risk_gates.json"),
        "runtime_health": runtime_health.diagnostic_payload(),
    }
    # Last session log file by name.
    sessions = root / "docs" / "sessions"
    if sessions.exists():
        try:
            files = sorted([p.name for p in sessions.iterdir() if p.suffix == ".md"])
            if files:
                state["last_session_log"] = files[-1]
        except Exception:
            pass
    # Connection manager summary — optional dependency, may not import.
    try:
        from core.connections import ConnectionManager
        cm = ConnectionManager()
        state["connections"] = cm.status_summary() if hasattr(cm, "status_summary") else None
    except Exception:
        state["connections"] = None
    return state


def _build_comparison(runs: list[dict]) -> dict:
    """If two or more runs share the same engine, compare the newest
    to the one before it and emit key-metric deltas."""
    out: dict = {}
    if len(runs) < 2:
        return out
    by_engine: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        by_engine[r.get("engine") or "unknown"].append(r)
    for engine, rs in by_engine.items():
        if len(rs) < 2:
            continue
        current, previous = rs[0], rs[1]
        cs, ps = current.get("summary") or {}, previous.get("summary") or {}
        def _d(a, b):
            try:
                return round(float(a) - float(b), 4)
            except Exception:
                return None
        out[engine] = {
            "current": current.get("run_id"),
            "previous": previous.get("run_id"),
            "delta_sortino": _d(cs.get("sortino"), ps.get("sortino")),
            "delta_wr": _d(cs.get("win_rate"), ps.get("win_rate")),
            "delta_pnl": _d(cs.get("total_pnl"), ps.get("total_pnl")),
            "delta_trades": _d(cs.get("n_trades"), ps.get("n_trades")),
            "delta_max_dd": _d(cs.get("max_dd_pct"), ps.get("max_dd_pct")),
        }
    return out


# ══════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════
def export_analysis(output_path: str | Path | None = None,
                    root: str | Path | None = None) -> dict:
    """Generate a full analysis snapshot.

    Parameters
    ----------
    output_path : optional str or Path
        If provided, the dict is also persisted as UTF-8 JSON at that
        location. Parent directories are created if missing.
    root : optional str or Path
        Override the project root. Defaults to the real AURUM tree,
        but test code passes a temporary directory to exercise the
        pipeline in isolation.

    Returns
    -------
    dict — the full snapshot, always populated (missing pieces become
    ``None`` or empty collections rather than raising).
    """
    root_path = Path(root) if root else ROOT

    runs = _collect_runs(root_path)
    latest = runs[0] if runs else None

    payload: dict = {
        "meta": _collect_meta(root_path),
        "config": _collect_config(),
        "runs": runs,
        "live_sessions": _collect_live_sessions(root_path),
        "arbitrage_sessions": _collect_arbitrage_sessions(root_path),
        "analysis": _build_analysis(latest),
        "system_state": _collect_system_state(root_path),
        "comparison": _build_comparison(runs),
    }
    payload = with_schema_version(payload, ANALYSIS_EXPORT_SCHEMA_VERSION)

    if output_path is not None:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            out_path,
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        )

    return payload
