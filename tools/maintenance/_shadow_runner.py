"""Per-engine shadow runner — parametric core shared by citadel/jump/renaissance.

Mirrors ``tools/maintenance/millennium_shadow.py`` one-to-one; this module is
parametrized on ``ENGINE_NAME`` (read from env at import time) and filters
MILLENNIUM's signal collector so only this engine's signals land in the
shadow trades JSONL.

Data layout: ``data/{engine}_shadow/<run_id>/{reports,state,logs}/``.

MILLENNIUM shadow already writes per-engine rollups via ``_append_per_engine``
into the same ``data/{engine}_shadow/<mill_run>/`` parent — those records
carry ``parent_run_id`` in their manifest. Solo shadow runs (this module)
write their OWN RUN_ID without parent_run_id, so cockpit UI can distinguish:
  - ``manifest.json.parent_run_id == null`` → solo engine shadow
  - ``manifest.json.parent_run_id == "<mill_run>"`` → derived from MILLENNIUM

Entry scripts: ``tools/maintenance/{citadel,jump,renaissance}_shadow.py``.
They set AURUM_ENGINE_NAME and delegate here.

Usage (via entry script):
    python tools/maintenance/citadel_shadow.py --tick-sec 900 --run-hours 24

Direct (debug):
    AURUM_ENGINE_NAME=citadel python tools/maintenance/_shadow_runner.py \\
        --tick-sec 900 --run-hours 24
"""
from __future__ import annotations

import argparse
import contextlib
import io
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
from core.risk.key_store import KeyStoreError, load_runtime_keys  # noqa: E402
from tools.operations.millennium_signal_gate import (  # noqa: E402
    is_live_signal,
    parse_utc_ts,
    signal_timestamp,
    trade_key,
)
from tools.operations.run_id import build_run_id, sanitize_label  # noqa: E402

# ─── Engine parametrization ──────────────────────────────────────
ENGINE_NAME = os.environ.get("AURUM_ENGINE_NAME", "citadel").lower()
ENGINE_UPPER = ENGINE_NAME.upper()

RUN_TS = datetime.now(timezone.utc)
LABEL: str | None = sanitize_label(
    os.environ.get(f"AURUM_{ENGINE_UPPER}_SHADOW_LABEL")
    or os.environ.get("AURUM_SHADOW_LABEL")
)
RUN_ID = build_run_id(RUN_TS, LABEL, mode="shadow")
RUN_DIR = ROOT / "data" / f"{ENGINE_NAME}_shadow" / RUN_ID
LOGS_DIR = RUN_DIR / "logs"
REPORTS_DIR = RUN_DIR / "reports"
STATE_DIR = RUN_DIR / "state"
for _d in (LOGS_DIR, REPORTS_DIR, STATE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

SHADOW_LOG = LOGS_DIR / "shadow.log"
TRADES_PATH = REPORTS_DIR / "shadow_trades.jsonl"
HEARTBEAT_PATH = STATE_DIR / "heartbeat.json"
KILL_FLAG = RUN_DIR / ".kill"


def _configure_run(label: str | None) -> None:
    """Re-point module-level paths at a new RUN_ID built from ``label``."""
    global LABEL, RUN_ID, RUN_DIR, LOGS_DIR, REPORTS_DIR, STATE_DIR
    global SHADOW_LOG, TRADES_PATH, HEARTBEAT_PATH, KILL_FLAG
    LABEL = sanitize_label(label)
    RUN_ID = build_run_id(RUN_TS, LABEL, mode="shadow")
    RUN_DIR = ROOT / "data" / f"{ENGINE_NAME}_shadow" / RUN_ID
    LOGS_DIR = RUN_DIR / "logs"
    REPORTS_DIR = RUN_DIR / "reports"
    STATE_DIR = RUN_DIR / "state"
    for _d in (LOGS_DIR, REPORTS_DIR, STATE_DIR):
        _d.mkdir(parents=True, exist_ok=True)
    SHADOW_LOG = LOGS_DIR / "shadow.log"
    TRADES_PATH = REPORTS_DIR / "shadow_trades.jsonl"
    HEARTBEAT_PATH = STATE_DIR / "heartbeat.json"
    KILL_FLAG = RUN_DIR / ".kill"

log = logging.getLogger(f"{ENGINE_NAME}_shadow")
log.setLevel(logging.INFO)


# ─── Telegram ────────────────────────────────────────────────────
_TELEGRAM_CFG: dict | None = None
_TG_CFG_MISSING_LOGGED = False


def _telegram_cfg() -> dict | None:
    global _TELEGRAM_CFG
    if _TELEGRAM_CFG is not None:
        return _TELEGRAM_CFG
    try:
        data = load_runtime_keys()
        tg = data.get("telegram") or {}
        if tg.get("bot_token") and tg.get("chat_id"):
            _TELEGRAM_CFG = {
                "token": str(tg["bot_token"]),
                "chat_id": str(tg["chat_id"]),
            }
            return _TELEGRAM_CFG
    except KeyStoreError:
        pass
    _TELEGRAM_CFG = {}
    return None


def _tg_send(text: str) -> None:
    cfg = _telegram_cfg()
    if not cfg:
        global _TG_CFG_MISSING_LOGGED
        if not _TG_CFG_MISSING_LOGGED:
            log.info("telegram: cfg ausente — pings desativados")
            _TG_CFG_MISSING_LOGGED = True
        return
    try:
        import urllib.parse
        import urllib.request
        url = f"https://api.telegram.org/bot{cfg['token']}/sendMessage"
        payload = urllib.parse.urlencode({
            "chat_id": cfg["chat_id"],
            "text": text,
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            resp.read()
        log.info("telegram sent: %s", text.splitlines()[0][:120])
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram send failed: %s", exc)

_fmt = logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s")
_LOG_FILE_TARGET: str | None = None


def _ensure_log_handlers() -> None:
    """Bind stream/file handlers to the current RUN_DIR log file."""
    global _LOG_FILE_TARGET

    if not any(
        isinstance(handler, logging.StreamHandler)
        and getattr(handler, "stream", None) is sys.stdout
        for handler in log.handlers
    ):
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(_fmt)
        log.addHandler(stream_handler)

    target = str(SHADOW_LOG.resolve())
    if _LOG_FILE_TARGET == target:
        return

    for handler in list(log.handlers):
        if isinstance(handler, logging.FileHandler):
            log.removeHandler(handler)
            with contextlib.suppress(Exception):
                handler.close()

    file_handler = logging.FileHandler(SHADOW_LOG, encoding="utf-8")
    file_handler.setFormatter(_fmt)
    log.addHandler(file_handler)
    _LOG_FILE_TARGET = target


def _git_describe() -> tuple[str, str]:
    import subprocess
    def _run(args: list[str]) -> str:
        try:
            out = subprocess.check_output(
                args, cwd=str(ROOT), text=True, timeout=2,
                stderr=subprocess.DEVNULL,
            )
            return out.strip()
        except (subprocess.SubprocessError, OSError):
            return ""
    return (
        _run(["git", "rev-parse", "--short", "HEAD"]),
        _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
    )


def _write_manifest() -> None:
    """Write manifest.json once at runner start. parent_run_id is null —
    this marks the manifest as a SOLO engine shadow (not derived from a
    MILLENNIUM run, which would stamp parent_run_id with the mill run_id)."""
    import platform
    from core.shadow_contract import compute_config_hash

    commit, branch = _git_describe()
    payload = {
        "run_id": RUN_ID,
        "engine": ENGINE_NAME,
        "mode": "shadow",
        "label": LABEL,
        "parent_run_id": None,
        "started_at": RUN_TS.isoformat(),
        "commit": commit or "unknown",
        "branch": branch or "unknown",
        "config_hash": compute_config_hash(),
        "host": socket.gethostname(),
        "python_version": platform.python_version(),
    }
    atomic_write(RUN_DIR / "state" / "manifest.json",
                 json.dumps(payload, indent=2))


def _write_heartbeat(state_dict: dict) -> None:
    payload = json.dumps(state_dict, indent=2, ensure_ascii=True, default=str)
    atomic_write(HEARTBEAT_PATH, payload)


def _upsert_live_run(
    *,
    first_tick_state: dict[str, Any],
    run_id: str,
    tick_count: int,
    novel_count: int,
    last_tick_at: str,
    status: str = "running",
) -> None:
    """Best-effort upsert to aurum.db live_runs. Never raises."""
    try:
        if not first_tick_state.get("initialized", False):
            existing = db_live_runs.get_live_run(run_id)
            if existing is None:
                db_live_runs.upsert(
                    run_id=run_id,
                    engine=ENGINE_NAME,
                    mode="shadow",
                    started_at=first_tick_state["started_at"],
                    run_dir=first_tick_state["run_dir"],
                    host=socket.gethostname(),
                    label=first_tick_state.get("label"),
                    status=status,
                    tick_count=tick_count,
                    novel_count=novel_count,
                    last_tick_at=last_tick_at,
                )
            else:
                db_live_runs.upsert(
                    run_id=run_id,
                    status=status,
                    tick_count=tick_count,
                    novel_count=novel_count,
                    last_tick_at=last_tick_at,
                )
            first_tick_state["initialized"] = True
        else:
            db_live_runs.upsert(
                run_id=run_id,
                status=status,
                tick_count=tick_count,
                novel_count=novel_count,
                last_tick_at=last_tick_at,
            )
    except Exception:
        log.exception("db_live_runs upsert failed (shadow continues)")


def _append_trade(trade: dict) -> None:
    """Append one trade to shadow_trades.jsonl."""
    line = json.dumps(trade, ensure_ascii=True, default=str)
    with open(TRADES_PATH, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()


def _compute_trade_metrics(records: list[dict]) -> dict:
    from core.metrics_helpers import compute_trade_metrics
    return compute_trade_metrics(records)


def _write_run_summary(ticks_ok: int, ticks_fail: int, novel_total: int,
                      novel_since_prime: int, stopped_reason: str,
                      stopped_at: str) -> None:
    """Compute + atomic-write reports/summary.json."""
    reports_dir = RUN_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    summary_path = reports_dir / "summary.json"
    records: list[dict] = []
    if TRADES_PATH.exists():
        try:
            with open(TRADES_PATH, encoding="utf-8") as fh:
                for ln in fh:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        records.append(json.loads(ln))
                    except ValueError:
                        continue
        except OSError as exc:
            log.warning("summary: falha lendo trades.jsonl: %s", exc)
    try:
        metrics = _compute_trade_metrics(records)
    except Exception as exc:  # noqa: BLE001
        log.warning("summary: falha computando metricas: %s", exc)
        metrics = {"error": f"{type(exc).__name__}: {exc}"}
    payload = {
        "run_id": RUN_ID,
        "engine": ENGINE_NAME,
        "mode": "shadow",
        "label": LABEL,
        "parent_run_id": None,
        "started_at": RUN_TS.isoformat(),
        "stopped_at": stopped_at,
        "stopped_reason": stopped_reason,
        "ticks_ok": ticks_ok,
        "ticks_fail": ticks_fail,
        "novel_total": novel_total,
        "novel_since_prime": novel_since_prime,
        "metrics": metrics,
    }
    try:
        atomic_write(summary_path, json.dumps(payload, indent=2))
        log.info("summary: wrote %s (%d trades, pnl=%.2f, sharpe=%.2f)",
                 summary_path, metrics.get("n_trades", 0),
                 metrics.get("net_pnl", 0.0), metrics.get("sharpe", 0.0))
    except Exception as exc:  # noqa: BLE001
        log.warning("summary: falha escrevendo %s: %s", summary_path, exc)


def _trade_key(trade: dict) -> tuple:
    return trade_key(trade)


def _fmt_num(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if abs(f) >= 1000:
        return f"{f:,.2f}"
    return f"{f:.4g}"


def _tg_signal(trade: dict) -> None:
    sym = str(trade.get("symbol") or "?").upper()
    direction = str(trade.get("direction") or "?").upper()
    entry = _fmt_num(trade.get("entry"))
    stop = _fmt_num(trade.get("stop"))
    target = _fmt_num(trade.get("target"))
    rr = _fmt_num(trade.get("rr"))
    size = _fmt_num(trade.get("size"))
    raw_ts = trade.get("timestamp")
    parsed = parse_utc_ts(raw_ts)
    now = datetime.now(timezone.utc)
    if parsed is not None and parsed > now:
        ts = now.isoformat().replace("T", " ")[:16]
    else:
        ts = str(raw_ts or "").replace("T", " ")[:16]
    dir_label = (
        "LONG" if direction.startswith("L")
        else "SHORT" if direction.startswith("S")
        else direction
    )
    tv_sym = sym.replace("/", "").replace("-", "")
    chart = (f"https://www.tradingview.com/chart/?symbol=BINANCE:{tv_sym}.P&interval=60"
             if tv_sym.endswith("USDT") and len(tv_sym) >= 6 else None)
    lines = [
        f"<b>{ENGINE_UPPER} shadow</b>  {dir_label} {sym}",
        f"entry <code>{entry}</code> · stop <code>{stop}</code> · tgt <code>{target}</code>",
        f"RR <code>{rr}</code> · size <code>{size}</code> · ts <code>{ts}</code>",
    ]
    if chart:
        lines.append(f'<a href="{chart}">chart</a>')
    _tg_send("\n".join(lines))


def _run_tick(
    seen_keys: set,
    tick_sec: int,
    notify: bool = True,
) -> tuple[int, int, int, str | None, dict[str, int]]:
    """Run one shadow tick. Returns (novel_count, total_scanned, engines_ok,
    last_novel_observed_at, scan_stats).

    Delega ao helper nativo do MILLENNIUM (``_scan_one_engine_live``) pro
    fetch dedicado com TF+basket nativos — garante que shadow reproduz o
    backtest OOS do engine exato e bate com CITADEL/JUMP/RENAISSANCE
    dentro do pod MILLENNIUM (mesma source-of-truth).
    """
    from engines.millennium import _scan_one_engine_live
    filtered = _scan_one_engine_live(ENGINE_NAME)

    engines_ok = 1 if filtered else 0
    novel = 0
    dedup_skips = 0
    stale_skips = 0
    last_novel_at: str | None = None
    primed_flag = not notify
    for t in filtered:
        key = _trade_key(t)
        if key in seen_keys:
            dedup_skips += 1
            continue
        seen_keys.add(key)
        record = dict(t)
        record["shadow_run_id"] = RUN_ID
        observed_at = datetime.now(timezone.utc).isoformat()
        record["shadow_observed_at"] = observed_at
        record["primed"] = primed_flag
        if not is_live_signal(record, tick_sec=tick_sec, reference_ts=observed_at):
            stale_skips += 1
            if notify:
                log.info(
                    "STALE signal skipped strategy=%s symbol=%s signal_ts=%s observed_at=%s",
                    str(record.get("strategy") or "?").upper(),
                    str(record.get("symbol") or "?").upper(),
                    signal_timestamp(record),
                    observed_at,
                )
            continue
        _append_trade(record)
        novel += 1
        if notify:
            last_novel_at = observed_at
            _tg_signal(record)
    if primed_flag:
        log.info(
            "PRIME scan scanned=%d dedup=%d stale=%d live=%d seen=%d",
            len(filtered), dedup_skips, stale_skips, novel, len(seen_keys),
        )
    elif dedup_skips or stale_skips:
        log.info(
            "LIVE scan scanned=%d dedup=%d stale=%d live=%d seen=%d",
            len(filtered), dedup_skips, stale_skips, novel, len(seen_keys),
        )
    return novel, len(filtered), engines_ok, last_novel_at, {
        "scanned": len(filtered),
        "dedup": dedup_skips,
        "stale": stale_skips,
        "live": novel,
    }


def run_shadow(tick_sec: int, run_hours: float) -> int:
    """Main shadow loop. Returns exit code."""
    deadline = time.time() + run_hours * 3600.0 if run_hours > 0 else None
    seen_keys: set = set()
    ticks_ok = 0
    ticks_fail = 0
    novel_total = 0
    novel_since_prime = 0
    last_novel_at: str | None = None
    first_tick = True
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

    _live_runs_ctx: dict[str, Any] = {
        "started_at": RUN_TS.isoformat(),
        "run_dir": str(RUN_DIR.relative_to(ROOT)),
        "label": LABEL,
        "initialized": False,
    }

    _write_manifest()

    log.info("%s SHADOW START run=%s tick=%ds hours=%.1f dir=%s",
             ENGINE_UPPER, RUN_ID, tick_sec, run_hours, RUN_DIR)
    _tg_send(
        f"<b>{ENGINE_UPPER} shadow START</b>\n"
        f"run: <code>{RUN_ID}</code>\n"
        f"tick: {tick_sec}s · hours: {run_hours}"
    )
    _write_heartbeat({
        "run_id": RUN_ID,
        "status": "running",
        "label": LABEL,
        "engine": ENGINE_NAME,
        "started_at": RUN_TS.isoformat(),
        "tick_sec": tick_sec,
        "run_hours": run_hours,
        "ticks_ok": 0,
        "ticks_fail": 0,
        "novel_total": 0,
        "novel_since_prime": 0,
        "last_scan_scanned": 0,
        "last_scan_dedup": 0,
        "last_scan_stale": 0,
        "last_scan_live": 0,
        "last_novel_at": None,
        "last_tick_at": None,
        "last_error": None,
    })
    _upsert_live_run(
        first_tick_state=_live_runs_ctx,
        run_id=RUN_ID,
        tick_count=0,
        novel_count=0,
        last_tick_at=RUN_TS.isoformat(),
    )

    while True:
        tick_start = time.time()

        if KILL_FLAG.exists():
            stop_requested["flag"] = True
            stop_requested["reason"] = "kill file"
            log.info("KILL FLAG detected at %s — exiting", KILL_FLAG)
            break
        if deadline is not None and time.time() >= deadline:
            log.info("DEADLINE reached after %.1fh — exiting", run_hours)
            break
        if stop_requested["flag"]:
            break

        try:
            novel, scanned, engines_ok, tick_last_novel, scan_stats = _run_tick(
                seen_keys, tick_sec=tick_sec, notify=not first_tick)
            was_first = first_tick
            first_tick = False
            ticks_ok += 1
            novel_total += novel
            if not was_first:
                novel_since_prime += novel
            if tick_last_novel is not None:
                last_novel_at = tick_last_novel
            log.info(
                "TICK ok=%d novel=%d scanned=%d engines_ok=%d seen=%d primed=%s",
                ticks_ok, novel, scanned, engines_ok, len(seen_keys),
                "yes" if was_first else "no",
            )
            now_iso_ok = datetime.now(timezone.utc).isoformat()
            _write_heartbeat({
                "run_id": RUN_ID,
                "status": "running",
                "label": LABEL,
                "engine": ENGINE_NAME,
                "started_at": RUN_TS.isoformat(),
                "tick_sec": tick_sec,
                "run_hours": run_hours,
                "ticks_ok": ticks_ok,
                "ticks_fail": ticks_fail,
                "novel_total": novel_total,
                "novel_since_prime": novel_since_prime,
                "last_scan_scanned": scan_stats["scanned"],
                "last_scan_dedup": scan_stats["dedup"],
                "last_scan_stale": scan_stats["stale"],
                "last_scan_live": scan_stats["live"],
                "last_novel_at": last_novel_at,
                "last_tick_at": now_iso_ok,
                "last_error": None,
            })
            _upsert_live_run(
                first_tick_state=_live_runs_ctx,
                run_id=RUN_ID,
                tick_count=ticks_ok,
                novel_count=novel_total,
                last_tick_at=now_iso_ok,
            )
        except Exception as exc:  # noqa: BLE001
            ticks_fail += 1
            err = f"{type(exc).__name__}: {exc}"
            log.error("TICK fail=%d err=%s", ticks_fail, err)
            log.error("%s", traceback.format_exc())
            _tg_send(
                f"<b>{ENGINE_UPPER} shadow TICK FAIL</b>\n"
                f"run: <code>{RUN_ID}</code>\n"
                f"fails: {ticks_fail}\n"
                f"err: <code>{err[:200]}</code>"
            )
            now_iso_fail = datetime.now(timezone.utc).isoformat()
            _write_heartbeat({
                "run_id": RUN_ID,
                "status": "running",
                "label": LABEL,
                "engine": ENGINE_NAME,
                "started_at": RUN_TS.isoformat(),
                "tick_sec": tick_sec,
                "run_hours": run_hours,
                "ticks_ok": ticks_ok,
                "ticks_fail": ticks_fail,
                "novel_total": novel_total,
                "novel_since_prime": novel_since_prime,
                "last_scan_scanned": 0,
                "last_scan_dedup": 0,
                "last_scan_stale": 0,
                "last_scan_live": 0,
                "last_novel_at": last_novel_at,
                "last_tick_at": now_iso_fail,
                "last_error": err,
            })
            _upsert_live_run(
                first_tick_state=_live_runs_ctx,
                run_id=RUN_ID,
                tick_count=ticks_ok,
                novel_count=novel_total,
                last_tick_at=now_iso_fail,
            )

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
        "run_id": RUN_ID,
        "status": "stopped",
        "label": LABEL,
        "engine": ENGINE_NAME,
        "stopped_reason": stop_requested["reason"] or "deadline",
        "started_at": RUN_TS.isoformat(),
        "stopped_at": stopped_at_str,
        "tick_sec": tick_sec,
        "run_hours": run_hours,
        "ticks_ok": ticks_ok,
        "ticks_fail": ticks_fail,
        "novel_total": novel_total,
        "novel_since_prime": novel_since_prime,
        "last_scan_scanned": 0,
        "last_scan_dedup": 0,
        "last_scan_stale": 0,
        "last_scan_live": 0,
        "last_novel_at": last_novel_at,
    })
    _upsert_live_run(
        first_tick_state=_live_runs_ctx,
        run_id=RUN_ID,
        tick_count=ticks_ok,
        novel_count=novel_total,
        last_tick_at=stopped_at_str,
        status="stopped",
    )
    _write_run_summary(
        ticks_ok=ticks_ok,
        ticks_fail=ticks_fail,
        novel_total=novel_total,
        novel_since_prime=novel_since_prime,
        stopped_reason=stop_requested["reason"] or "deadline",
        stopped_at=stopped_at_str,
    )
    try:
        if db_live_runs.get_live_run(RUN_ID) is not None:
            db_live_runs.upsert(
                run_id=RUN_ID,
                ended_at=datetime.now(timezone.utc).isoformat(),
                status="stopped",
            )
        else:
            log.warning(
                "db_live_runs: no row for %s to finalize "
                "(never created — tick 1 did not complete)",
                RUN_ID,
            )
    except Exception:
        log.exception("db_live_runs final upsert failed")
    log.info(
        "%s SHADOW END ok=%d fail=%d novel=%d reason=%s",
        ENGINE_UPPER, ticks_ok, ticks_fail, novel_total,
        stop_requested["reason"] or "deadline",
    )
    _tg_send(
        f"<b>{ENGINE_UPPER} shadow STOP</b>\n"
        f"run: <code>{RUN_ID}</code>\n"
        f"ticks_ok: {ticks_ok} · fails: {ticks_fail}\n"
        f"signals: {novel_total}\n"
        f"reason: {stop_requested['reason'] or 'deadline'}"
    )
    return 0 if ticks_ok > 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description=f"{ENGINE_UPPER} shadow runner (per-engine, parallel to MILLENNIUM)"
    )
    ap.add_argument("--tick-sec", type=int, default=900)
    ap.add_argument("--run-hours", type=float, default=24.0)
    ap.add_argument("--label", type=str, default=None,
                    help="optional instance label (sanitized to [a-z0-9-], "
                         f"max 40). overrides AURUM_{ENGINE_UPPER}_SHADOW_LABEL env.")
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

    return run_shadow(args.tick_sec, args.run_hours)


if __name__ == "__main__":
    raise SystemExit(main())
