"""AURUM probe runner — pure diagnostic scan, zero side effects.

Roda em cadencia fixa (15min por default) e para cada symbol do UNIVERSE
computa a cadeia COMPLETA de indicators + swing_structure + omega, com
os mesmos params que citadel/jump/renaissance usam. Depois chama
`decide_direction` e `score_omega` em READ-ONLY — sem posicionar ordem,
sem registrar trade, sem escrever no portfolio.

Emite por tick:
  * `reports/probe_tick.jsonl` — 1 linha com array de symbols ranked
    por score (top-5 visivel no cockpit). Cada entry traz:
      symbol · score · direction_hint · reason · chop_state · chop_score
      · fired (bool) · macro · close
  * `state/heartbeat.json` — top_score, mean_score, threshold atual,
    n_above_{threshold,80pct,60pct}, top_symbol, top_direction

Objetivo: quando todas as engines estao com `novel=0`, a probe prova
que o pipeline (fetch → indicators → omega → regime) esta rodando e
vendo o mercado. Se top_score fica em ~0.15 em tudo, mercado morto.
Se top_score ~0.68 mas todos abaixo do threshold 0.75, mercado ativo
mas filtros corretos.

Uso:
    python tools/maintenance/probe_runner.py --tick-sec 900 --run-hours 0

Kill: SIGINT, SIGTERM ou criar ``<run_dir>/.kill``.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import signal
import socket
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.ops import db_live_runs  # noqa: E402
from core.ops.fs import atomic_write  # noqa: E402
from tools.operations.run_id import build_run_id, sanitize_label  # noqa: E402

RUN_TS = datetime.now(timezone.utc)
LABEL: str | None = sanitize_label(os.environ.get("AURUM_PROBE_LABEL"))
RUN_ID = build_run_id(RUN_TS, LABEL, mode="shadow")
RUN_DIR = ROOT / "data" / "probe_shadow" / RUN_ID
LOGS_DIR = RUN_DIR / "logs"
REPORTS_DIR = RUN_DIR / "reports"
STATE_DIR = RUN_DIR / "state"
for _d in (LOGS_DIR, REPORTS_DIR, STATE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

PROBE_LOG = LOGS_DIR / "shadow.log"
PROBE_TICK_PATH = REPORTS_DIR / "probe_tick.jsonl"
HEARTBEAT_PATH = STATE_DIR / "heartbeat.json"
KILL_FLAG = RUN_DIR / ".kill"


def _configure_run(label: str | None) -> None:
    global LABEL, RUN_ID, RUN_DIR, LOGS_DIR, REPORTS_DIR, STATE_DIR
    global PROBE_LOG, PROBE_TICK_PATH, HEARTBEAT_PATH, KILL_FLAG
    LABEL = sanitize_label(label)
    RUN_ID = build_run_id(RUN_TS, LABEL, mode="shadow")
    RUN_DIR = ROOT / "data" / "probe_shadow" / RUN_ID
    LOGS_DIR = RUN_DIR / "logs"
    REPORTS_DIR = RUN_DIR / "reports"
    STATE_DIR = RUN_DIR / "state"
    for _d in (LOGS_DIR, REPORTS_DIR, STATE_DIR):
        _d.mkdir(parents=True, exist_ok=True)
    PROBE_LOG = LOGS_DIR / "shadow.log"
    PROBE_TICK_PATH = REPORTS_DIR / "probe_tick.jsonl"
    HEARTBEAT_PATH = STATE_DIR / "heartbeat.json"
    KILL_FLAG = RUN_DIR / ".kill"


log = logging.getLogger("probe")
log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s")
_LOG_FILE_TARGET: str | None = None


def _ensure_log_handlers() -> None:
    global _LOG_FILE_TARGET
    if not any(
        isinstance(h, logging.StreamHandler)
        and getattr(h, "stream", None) is sys.stdout
        for h in log.handlers
    ):
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(_fmt)
        log.addHandler(sh)
    target = str(PROBE_LOG.resolve())
    if _LOG_FILE_TARGET == target:
        return
    for h in list(log.handlers):
        if isinstance(h, logging.FileHandler):
            log.removeHandler(h)
            with contextlib.suppress(Exception):
                h.close()
    fh = logging.FileHandler(PROBE_LOG, encoding="utf-8")
    fh.setFormatter(_fmt)
    log.addHandler(fh)
    _LOG_FILE_TARGET = target


def _git_describe() -> tuple[str, str]:
    import subprocess
    def _run(args):
        try:
            return subprocess.check_output(
                args, cwd=str(ROOT), text=True, timeout=2,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (subprocess.SubprocessError, OSError):
            return ""
    return _run(["git", "rev-parse", "--short", "HEAD"]), _run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"])


def _write_manifest() -> None:
    import platform
    from core.shadow_contract import compute_config_hash
    commit, branch = _git_describe()
    payload = {
        "run_id": RUN_ID,
        "engine": "probe",
        "mode": "shadow",
        "label": LABEL,
        "started_at": RUN_TS.isoformat(),
        "commit": commit or "unknown",
        "branch": branch or "unknown",
        "config_hash": compute_config_hash(),
        "host": socket.gethostname(),
        "python_version": platform.python_version(),
    }
    atomic_write(STATE_DIR / "manifest.json", json.dumps(payload, indent=2))


def _write_heartbeat(state: dict) -> None:
    atomic_write(HEARTBEAT_PATH,
                 json.dumps(state, indent=2, ensure_ascii=True, default=str))


def _append_probe_tick(record: dict) -> None:
    line = json.dumps(record, ensure_ascii=True, default=str)
    with open(PROBE_TICK_PATH, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()


def _upsert_live_run(ctx: dict[str, Any], tick_count: int, last_tick_at: str,
                     status: str = "running") -> None:
    try:
        if not ctx.get("initialized", False):
            existing = db_live_runs.get_live_run(RUN_ID)
            if existing is None:
                db_live_runs.upsert(
                    run_id=RUN_ID,
                    engine="probe",
                    mode="shadow",
                    started_at=ctx["started_at"],
                    run_dir=ctx["run_dir"],
                    host=socket.gethostname(),
                    label=ctx.get("label"),
                    status=status,
                    tick_count=tick_count,
                    novel_count=0,
                    last_tick_at=last_tick_at,
                )
            else:
                db_live_runs.upsert(
                    run_id=RUN_ID, status=status,
                    tick_count=tick_count, novel_count=0,
                    last_tick_at=last_tick_at,
                )
            ctx["initialized"] = True
        else:
            db_live_runs.upsert(
                run_id=RUN_ID, status=status,
                tick_count=tick_count, novel_count=0,
                last_tick_at=last_tick_at,
            )
    except Exception:
        log.exception("db_live_runs upsert failed (probe continues)")


def _probe_tick() -> dict:
    """Run one probe scan. Returns aggregate tick record."""
    from config.params import (
        ENTRY_TF, SYMBOLS, MACRO_SYMBOL, N_CANDLES,
        SCORE_THRESHOLD, SCORE_BY_REGIME,
    )
    from core.data import fetch_all, validate
    from core.indicators import indicators, swing_structure, omega
    from core.portfolio import detect_macro
    from core.signals import decide_direction, score_omega, score_chop

    syms = list(SYMBOLS)
    if MACRO_SYMBOL not in syms:
        syms = [MACRO_SYMBOL] + syms

    all_dfs = fetch_all(syms, interval=ENTRY_TF, n_candles=N_CANDLES)
    for s, df in all_dfs.items():
        validate(df, s)

    macro_series = detect_macro(all_dfs)
    macro_now = "BULL"
    if macro_series is not None and len(macro_series) > 0:
        macro_now = str(macro_series.iloc[-1])

    per_symbol = []
    for sym in SYMBOLS:
        df = all_dfs.get(sym)
        if df is None or len(df) < 300:
            continue
        try:
            df_i = indicators(df)
            df_s = swing_structure(df_i)
            df_o = omega(df_s)
            last = df_o.iloc[-1]

            direction, reason, conf = decide_direction(last, macro_now)
            if direction:
                score, _breakdown = score_omega(last, direction)
                dir_hint = direction
                fired = True
            else:
                sl, _ = score_omega(last, "LONG")
                ss, _ = score_omega(last, "SHORT")
                score = float(max(sl, ss))
                dir_hint = "LONG" if sl >= ss else "SHORT"
                fired = False
            chop_state, chop_score, _cb = score_chop(last)

            per_symbol.append({
                "symbol": sym,
                "score": float(score),
                "direction_hint": dir_hint,
                "reason": reason,
                "confidence": float(conf) if conf is not None else None,
                "fired": fired,
                "macro": macro_now,
                "chop_state": chop_state,
                "chop_score": float(chop_score) if chop_score is not None else None,
                "close": float(last.get("close", 0) or 0),
            })
        except Exception as exc:  # noqa: BLE001
            log.warning("probe %s failed: %s", sym, exc)

    per_symbol.sort(key=lambda r: r["score"], reverse=True)
    threshold = float(SCORE_BY_REGIME.get(macro_now, SCORE_THRESHOLD))
    scores = [r["score"] for r in per_symbol]
    if scores:
        agg = {
            "top_score": max(scores),
            "mean_score": sum(scores) / len(scores),
            "n_above_threshold": sum(1 for s in scores if s >= threshold),
            "n_above_80pct": sum(1 for s in scores if s >= threshold * 0.8),
            "n_above_60pct": sum(1 for s in scores if s >= threshold * 0.6),
            "top_symbol": per_symbol[0]["symbol"],
            "top_direction": per_symbol[0]["direction_hint"],
        }
    else:
        agg = {"top_score": 0.0, "mean_score": 0.0, "n_above_threshold": 0,
               "n_above_80pct": 0, "n_above_60pct": 0,
               "top_symbol": None, "top_direction": None}

    return {
        "tick_at": datetime.now(timezone.utc).isoformat(),
        "macro": macro_now,
        "threshold": threshold,
        "n_symbols": len(per_symbol),
        "per_symbol": per_symbol,
        **agg,
    }


def run_probe(tick_sec: int, run_hours: float) -> int:
    deadline = time.time() + run_hours * 3600.0 if run_hours > 0 else None
    ticks_ok = 0
    ticks_fail = 0
    last_top_score = 0.0
    last_macro = ""
    stop_requested = {"flag": False, "reason": ""}

    def _handle_signal(signum, _frame):  # noqa: ARG001
        if stop_requested["flag"]:
            sys.exit(130)
        stop_requested["flag"] = True
        stop_requested["reason"] = f"signal {signum}"
        log.info("SIGNAL %s received — shutting down after current tick", signum)

    signal.signal(signal.SIGINT, _handle_signal)
    with contextlib.suppress(AttributeError, ValueError):
        signal.signal(signal.SIGTERM, _handle_signal)

    ctx: dict[str, Any] = {
        "started_at": RUN_TS.isoformat(),
        "run_dir": str(RUN_DIR.relative_to(ROOT)),
        "label": LABEL,
        "initialized": False,
    }

    _write_manifest()
    log.info("PROBE START run=%s tick=%ds hours=%.1f dir=%s",
             RUN_ID, tick_sec, run_hours, RUN_DIR)

    _write_heartbeat({
        "run_id": RUN_ID, "status": "running",
        "engine": "probe", "mode": "shadow",
        "label": LABEL, "started_at": RUN_TS.isoformat(),
        "tick_sec": tick_sec, "run_hours": run_hours,
        "ticks_ok": 0, "ticks_fail": 0,
        "novel_total": 0, "novel_since_prime": 0,
        "top_score": 0.0, "mean_score": 0.0,
        "n_above_threshold": 0, "n_above_80pct": 0, "n_above_60pct": 0,
        "top_symbol": None, "top_direction": None,
        "macro": None, "threshold": None,
        "last_tick_at": None, "last_error": None,
    })
    _upsert_live_run(ctx, tick_count=0, last_tick_at=RUN_TS.isoformat())

    while True:
        tick_start = time.time()
        if KILL_FLAG.exists():
            stop_requested["flag"] = True
            stop_requested["reason"] = "kill file"
            break
        if deadline is not None and time.time() >= deadline:
            break
        if stop_requested["flag"]:
            break

        try:
            record = _probe_tick()
            _append_probe_tick(record)
            ticks_ok += 1
            last_top_score = float(record.get("top_score", 0.0))
            last_macro = str(record.get("macro", ""))
            log.info(
                "TICK ok=%d top=%.3f top_sym=%s mean=%.3f macro=%s above_thr=%d above_80=%d above_60=%d",
                ticks_ok, last_top_score,
                record.get("top_symbol") or "-",
                record.get("mean_score", 0.0), last_macro,
                record.get("n_above_threshold", 0),
                record.get("n_above_80pct", 0),
                record.get("n_above_60pct", 0),
            )
            now_iso = datetime.now(timezone.utc).isoformat()
            _write_heartbeat({
                "run_id": RUN_ID, "status": "running",
                "engine": "probe", "mode": "shadow",
                "label": LABEL, "started_at": RUN_TS.isoformat(),
                "tick_sec": tick_sec, "run_hours": run_hours,
                "ticks_ok": ticks_ok, "ticks_fail": ticks_fail,
                "novel_total": 0, "novel_since_prime": 0,
                "top_score": last_top_score,
                "mean_score": record.get("mean_score", 0.0),
                "n_above_threshold": record.get("n_above_threshold", 0),
                "n_above_80pct": record.get("n_above_80pct", 0),
                "n_above_60pct": record.get("n_above_60pct", 0),
                "top_symbol": record.get("top_symbol"),
                "top_direction": record.get("top_direction"),
                "macro": last_macro,
                "threshold": record.get("threshold"),
                "last_tick_at": now_iso,
                "last_error": None,
            })
            _upsert_live_run(ctx, tick_count=ticks_ok, last_tick_at=now_iso)
        except Exception as exc:  # noqa: BLE001
            ticks_fail += 1
            err = f"{type(exc).__name__}: {exc}"
            log.error("TICK fail=%d err=%s", ticks_fail, err)
            log.error("%s", traceback.format_exc())
            now_iso_fail = datetime.now(timezone.utc).isoformat()
            _write_heartbeat({
                "run_id": RUN_ID, "status": "running",
                "engine": "probe", "mode": "shadow",
                "label": LABEL, "started_at": RUN_TS.isoformat(),
                "tick_sec": tick_sec, "run_hours": run_hours,
                "ticks_ok": ticks_ok, "ticks_fail": ticks_fail,
                "novel_total": 0, "novel_since_prime": 0,
                "top_score": last_top_score, "mean_score": 0.0,
                "n_above_threshold": 0, "n_above_80pct": 0,
                "n_above_60pct": 0,
                "top_symbol": None, "top_direction": None,
                "macro": last_macro, "threshold": None,
                "last_tick_at": now_iso_fail, "last_error": err,
            })
            _upsert_live_run(ctx, tick_count=ticks_ok,
                             last_tick_at=now_iso_fail)

        elapsed = time.time() - tick_start
        sleep_for = max(0.0, tick_sec - elapsed)
        sliced = 0.0
        while sliced < sleep_for:
            if KILL_FLAG.exists() or stop_requested["flag"]:
                break
            chunk = min(2.0, sleep_for - sliced)
            time.sleep(chunk)
            sliced += chunk

    stopped_at_str = datetime.now(timezone.utc).isoformat()
    _write_heartbeat({
        "run_id": RUN_ID, "status": "stopped",
        "engine": "probe", "mode": "shadow",
        "label": LABEL,
        "stopped_reason": stop_requested["reason"] or "deadline",
        "started_at": RUN_TS.isoformat(),
        "stopped_at": stopped_at_str,
        "tick_sec": tick_sec, "run_hours": run_hours,
        "ticks_ok": ticks_ok, "ticks_fail": ticks_fail,
        "novel_total": 0, "novel_since_prime": 0,
        "top_score": last_top_score,
        "macro": last_macro,
    })
    try:
        if db_live_runs.get_live_run(RUN_ID) is not None:
            db_live_runs.upsert(
                run_id=RUN_ID,
                ended_at=stopped_at_str,
                status="stopped",
            )
    except Exception:
        log.exception("db_live_runs final upsert failed")
    log.info("PROBE END ok=%d fail=%d reason=%s",
             ticks_ok, ticks_fail,
             stop_requested["reason"] or "deadline")
    return 0 if ticks_ok > 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tick-sec", type=int, default=900,
                    help="segundos entre ticks (default 900 = 15min)")
    ap.add_argument("--run-hours", type=float, default=0.0,
                    help="duracao total em horas; 0 = forever (default 0)")
    ap.add_argument("--label", type=str, default=None,
                    help="instance label opcional (sanitized [a-z0-9-], max 40)")
    args = ap.parse_args()

    if args.tick_sec < 60:
        print("tick-sec must be >= 60", file=sys.stderr)
        return 2
    if args.run_hours < 0:
        print("run-hours must be >= 0", file=sys.stderr)
        return 2

    if args.label is not None and sanitize_label(args.label) != LABEL:
        _configure_run(args.label)
    _ensure_log_handlers()
    return run_probe(args.tick_sec, args.run_hours)


if __name__ == "__main__":
    raise SystemExit(main())
