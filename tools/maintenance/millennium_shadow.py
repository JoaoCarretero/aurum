"""MILLENNIUM shadow runner — rolling scan at fixed cadence, no order routing.

Runs the operational core (CITADEL + RENAISSANCE + JUMP) every TICK_SEC
seconds against fresh OHLCV pulled from the exchange. Emits novel signals
(trades whose (engine, symbol, open_ts) key has not been seen this run) to
an append-only JSONL so the session can be audited post-hoc.

It is NOT live execution — no orders are placed, no exchange credentials
are required, no keys are loaded. The output is paper evidence for OOS
validation of the ensemble under real-time candle arrival.

Usage:
    python tools/maintenance/millennium_shadow.py --tick-sec 900 --run-hours 24

Kill gracefully by creating `<run_dir>/.kill` or by sending SIGINT.
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

RUN_TS = datetime.now(timezone.utc)
LABEL: str | None = sanitize_label(os.environ.get("AURUM_SHADOW_LABEL"))
RUN_ID = build_run_id(RUN_TS, LABEL, mode="shadow")
RUN_DIR = ROOT / "data" / "millennium_shadow" / RUN_ID
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
    """Re-point module-level paths at a new RUN_ID built from ``label``.

    Called from main() after argparse when --label differs from the
    env-derived LABEL. Rebuilds RUN_ID, RUN_DIR and every path global.
    """
    global LABEL, RUN_ID, RUN_DIR, LOGS_DIR, REPORTS_DIR, STATE_DIR
    global SHADOW_LOG, TRADES_PATH, HEARTBEAT_PATH, KILL_FLAG
    LABEL = sanitize_label(label)
    RUN_ID = build_run_id(RUN_TS, LABEL, mode="shadow")
    RUN_DIR = ROOT / "data" / "millennium_shadow" / RUN_ID
    LOGS_DIR = RUN_DIR / "logs"
    REPORTS_DIR = RUN_DIR / "reports"
    STATE_DIR = RUN_DIR / "state"
    for _d in (LOGS_DIR, REPORTS_DIR, STATE_DIR):
        _d.mkdir(parents=True, exist_ok=True)
    SHADOW_LOG = LOGS_DIR / "shadow.log"
    TRADES_PATH = REPORTS_DIR / "shadow_trades.jsonl"
    HEARTBEAT_PATH = STATE_DIR / "heartbeat.json"
    KILL_FLAG = RUN_DIR / ".kill"

log = logging.getLogger("millennium_shadow")
log.setLevel(logging.INFO)


# ─── Telegram alerting (opt-in via config/keys.json) ──────────────
# Send simple text pings for start / tick_fail / stop. Uses the Telegram
# Bot HTTP API directly so the shadow runner stays synchronous. Silent
# fallback if keys.json is absent, misconfigured, or network fails.
_TELEGRAM_CFG: dict | None = None


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
        # Config ausente eh silencioso por design (não-op graceful), mas
        # agora tambem aparece no log pra diagnostico de "por que nao
        # notificou" — uma linha por processo, nao por send.
        global _TG_CFG_MISSING_LOGGED
        try:
            _TG_CFG_MISSING_LOGGED
        except NameError:
            _TG_CFG_MISSING_LOGGED = False
        if not _TG_CFG_MISSING_LOGGED:
            log.info("telegram: cfg ausente (keys.json sem telegram.bot_token/chat_id) — pings desativados")
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
        # Log cada send pra habilitar /telegram-diag a contar historico.
        log.info("telegram sent: %s", text.splitlines()[0][:120])
    except Exception as exc:  # noqa: BLE001
        # Alerting nunca derruba o runner. Erro vai pro log local.
        log.warning("telegram send failed: %s", exc)
_fmt = logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s")
_LOG_FILE_TARGET: str | None = None


def _ensure_log_handlers() -> None:
    """Bind stream/file handlers to the current RUN_DIR log file.

    When ``--label`` changes the RUN_DIR after import, SHADOW_LOG moves as
    well. The file handler must follow the new path, otherwise logs land in
    the bootstrap/orphan directory created before argparse finalized the run.
    """
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
    """Return (commit_short, branch). Empty strings on failure."""
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
    return _run(["git", "rev-parse", "--short", "HEAD"]), _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])


def _write_manifest(run_dir: Path, run_id: str, engine: str, mode: str,
                    label: str | None = None) -> None:
    """Write manifest.json once at runner start. Idempotent: overwrites if exists."""
    import platform
    import socket
    from core.shadow_contract import compute_config_hash

    commit, branch = _git_describe()
    payload = {
        "run_id": run_id,
        "engine": engine,
        "mode": mode,
        "label": label,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "commit": commit or "unknown",
        "branch": branch or "unknown",
        "config_hash": compute_config_hash(),
        "host": socket.gethostname(),
        "python_version": platform.python_version(),
    }
    atomic_write(run_dir / "state" / "manifest.json", json.dumps(payload, indent=2))


def _write_heartbeat(state: dict) -> None:
    payload = json.dumps(state, indent=2, ensure_ascii=True, default=str)
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
    """Best-effort upsert to aurum.db live_runs. Never raises.

    first_tick_state is a dict toggled by the caller to track whether the
    initial INSERT has been attempted this process. Pattern matches paper
    runner: check-then-split on first call (handles restart on same RUN_ID),
    then mutable-only on subsequent.
    """
    try:
        if not first_tick_state.get("initialized", False):
            existing = db_live_runs.get_live_run(run_id)
            if existing is None:
                db_live_runs.upsert(
                    run_id=run_id,
                    engine="millennium",
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
    """Append one trade to shadow_trades.jsonl (line-oriented, fsync on write)."""
    line = json.dumps(trade, ensure_ascii=True, default=str)
    with open(TRADES_PATH, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()


# Per-engine run dirs espelham o layout do backtest: data/<engine>_shadow/
# <RUN_ID>/{reports,state}. Cada engine ganha seu proprio trades.jsonl +
# manifest + summary — navegavel via launcher/runs e reports existentes.
_PER_ENGINE_INITIALIZED: set[str] = set()


def _engine_slug(trade: dict) -> str:
    return str(trade.get("strategy") or "unknown").lower()


def _engine_run_dir(slug: str) -> Path:
    d = ROOT / "data" / f"{slug}_shadow" / RUN_ID
    (d / "reports").mkdir(parents=True, exist_ok=True)
    (d / "state").mkdir(parents=True, exist_ok=True)
    return d


def _append_per_engine(trade: dict) -> None:
    slug = _engine_slug(trade)
    run_dir = _engine_run_dir(slug)
    if slug not in _PER_ENGINE_INITIALIZED:
        manifest = {
            "run_id": f"{slug}_shadow_{RUN_ID}",
            "engine": slug,
            "mode": "shadow",
            "label": LABEL,
            "parent_run_id": RUN_ID,
            "started_at": RUN_TS.isoformat(),
        }
        atomic_write(run_dir / "state" / "manifest.json",
                     json.dumps(manifest, indent=2))
        _PER_ENGINE_INITIALIZED.add(slug)
    line = json.dumps(trade, ensure_ascii=True, default=str)
    with open(run_dir / "reports" / "trades.jsonl", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()


def _compute_trade_metrics(records: list[dict]) -> dict:
    """Backward-compatible thin shim around core.metrics_helpers.compute_trade_metrics.

    Kept for test backward compat (tests/test_shadow_metrics.py imports
    this symbol). Behavior guaranteed identical — shared impl lives in
    core/metrics_helpers.py.
    """
    from core.metrics_helpers import compute_trade_metrics
    return compute_trade_metrics(records)


def _write_run_summary(ticks_ok: int, ticks_fail: int, novel_total: int,
                      novel_since_prime: int, stopped_reason: str,
                      stopped_at: str) -> None:
    """Compute + atomic-write reports/summary.json do run agregado.

    Le todos os trades em shadow_trades.jsonl (escrito tick-a-tick),
    filtra primed via metrics helper, calcula Sharpe/Sortino/WR/PF/
    MaxDD/ROI como backtest tradicional. Erro em metricas nao derruba
    o shutdown — summary minimo eh escrito mesmo assim.
    """
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
        "engine": "millennium",
        "mode": "shadow",
        "label": LABEL,
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


def _write_per_engine_summaries(ticks_ok: int, ticks_fail: int,
                                stopped_reason: str) -> None:
    stopped_at = datetime.now(timezone.utc).isoformat()
    for slug in _PER_ENGINE_INITIALIZED:
        run_dir = ROOT / "data" / f"{slug}_shadow" / RUN_ID
        trades_path = run_dir / "reports" / "trades.jsonl"
        n = 0
        if trades_path.exists():
            try:
                with open(trades_path, encoding="utf-8") as fh:
                    n = sum(1 for line in fh if line.strip())
            except OSError:
                n = 0
        summary = {
            "run_id": f"{slug}_shadow_{RUN_ID}",
            "engine": slug,
            "mode": "shadow",
            "label": LABEL,
            "parent_run_id": RUN_ID,
            "started_at": RUN_TS.isoformat(),
            "stopped_at": stopped_at,
            "stopped_reason": stopped_reason or "—",
            "ticks_ok": ticks_ok,
            "ticks_fail": ticks_fail,
            "n_trades": n,
        }
        atomic_write(run_dir / "summary.json",
                     json.dumps(summary, indent=2))


def _trade_key(trade: dict) -> tuple:
    """Stable dedup key: engine + symbol + entry timestamp."""
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
    # Um Telegram compacto por sinal novo. HTML mode ja tratado em _tg_send.
    sym = str(trade.get("symbol") or "?").upper()
    direction = str(trade.get("direction") or "?").upper()
    engine = str(trade.get("strategy") or "?").upper()
    entry = _fmt_num(trade.get("entry"))
    stop = _fmt_num(trade.get("stop"))
    target = _fmt_num(trade.get("target"))
    rr = _fmt_num(trade.get("rr"))
    size = _fmt_num(trade.get("size"))
    # Clamp cosmetic ts to "now" so incomplete tail candles don't surface a
    # future open_time (e.g. H1 candle 11:00 displayed at 10:45). Dedup is
    # unaffected — trade_key() uses the raw open_ts, not this display field.
    raw_ts = trade.get("timestamp")
    parsed = parse_utc_ts(raw_ts)
    now = datetime.now(timezone.utc)
    if parsed is not None and parsed > now:
        ts = now.isoformat().replace("T", " ")[:16]
    else:
        ts = str(raw_ts or "").replace("T", " ")[:16]
    dir_emoji = "LONG" if direction.startswith("L") else "SHORT" if direction.startswith("S") else direction
    tv_sym = sym.replace("/", "").replace("-", "")
    chart = (f"https://www.tradingview.com/chart/?symbol=BINANCE:{tv_sym}.P&interval=60"
             if tv_sym.endswith("USDT") and len(tv_sym) >= 6 else None)
    lines = [
        f"<b>SHADOW · {engine}</b>  {dir_emoji} {sym}",
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
) -> tuple[int, int, int, str | None]:
    """Run one shadow tick. Returns (novel_count, total_scanned, engines_ok,
    last_novel_observed_at).

    Fetches fresh OHLCV, runs operational scans inside a stdout-silenced block
    (the engine prints verbosely), appends any novel trades to the JSONL, and
    updates `seen_keys` in place. When `notify=False` (first tick priming the
    dedup set), skips Telegram pings and marks records with `primed=True` so
    the cockpit nao confunde "sinal detectado pelo shadow" com "trade no
    universo backtest 180d".
    """
    # Import inside the tick so config reloads pick up changes between ticks
    # if someone edits params.py while the loop runs.
    # Use the *live* collector: it scans the tail bars that the backtest
    # collector skips (needs forward bars for outcome labeling). Without
    # the live path, the last ~50h of bars never produce signals — shadow
    # would miss every brand-new setup. See engines/citadel.py live_mode.
    from engines.millennium import (  # noqa: E402
        _load_dados,
        _collect_live_signals,
    )

    # Silence verbose engine stdout — the shadow.log is the canonical channel.
    with contextlib.redirect_stdout(io.StringIO()):
        all_dfs, htf_stack, macro_series, corr = _load_dados(False)
        engine_trades, all_trades = _collect_live_signals(
            all_dfs, htf_stack, macro_series, corr,
        )

    engines_ok = sum(1 for trades in engine_trades.values() if trades)
    novel = 0
    last_novel_at: str | None = None
    # Primed records = populacao inicial do dedup set (notify=False). Novel
    # records = detectados AO VIVO (notify=True) — esses contam pra LAST SIG
    # e disparam Telegram.
    primed_flag = not notify
    for t in all_trades:
        key = _trade_key(t)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        record = dict(t)
        record["shadow_run_id"] = RUN_ID
        observed_at = datetime.now(timezone.utc).isoformat()
        record["shadow_observed_at"] = observed_at
        record["primed"] = primed_flag
        if notify and not is_live_signal(record, tick_sec=tick_sec, reference_ts=observed_at):
            log.info(
                "STALE signal skipped strategy=%s symbol=%s signal_ts=%s observed_at=%s",
                str(record.get("strategy") or "?").upper(),
                str(record.get("symbol") or "?").upper(),
                signal_timestamp(record),
                observed_at,
            )
            continue
        _append_trade(record)
        _append_per_engine(record)
        novel += 1
        if notify:
            last_novel_at = observed_at
            _tg_signal(record)
    return novel, len(all_trades), engines_ok, last_novel_at


def run_shadow(tick_sec: int, run_hours: float) -> int:
    """Main shadow loop. Returns exit code."""
    deadline = time.time() + run_hours * 3600.0 if run_hours > 0 else None
    seen_keys: set = set()
    ticks_ok = 0
    ticks_fail = 0
    novel_total = 0
    novel_since_prime = 0           # sinais detectados AO VIVO (pos-prime)
    last_novel_at: str | None = None  # timestamp do ultimo novel observado
    first_tick = True
    stop_requested = {"flag": False, "reason": ""}

    def _handle_signal(signum, _frame):  # noqa: ARG001
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

    _write_manifest(RUN_DIR, run_id=RUN_ID, engine="millennium", mode="shadow",
                    label=LABEL)

    log.info("SHADOW START run=%s tick=%ds hours=%.1f dir=%s",
             RUN_ID, tick_sec, run_hours, RUN_DIR)
    _tg_send(
        f"<b>MILLENNIUM shadow START</b>\n"
        f"run: <code>{RUN_ID}</code>\n"
        f"tick: {tick_sec}s · hours: {run_hours}"
    )
    _write_heartbeat({
        "run_id": RUN_ID,
        "status": "running",
        "label": LABEL,
        "started_at": RUN_TS.isoformat(),
        "tick_sec": tick_sec,
        "run_hours": run_hours,
        "ticks_ok": 0,
        "ticks_fail": 0,
        "novel_total": 0,
        "novel_since_prime": 0,
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
            novel, scanned, engines_ok, tick_last_novel = _run_tick(
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
                "started_at": RUN_TS.isoformat(),
                "tick_sec": tick_sec,
                "run_hours": run_hours,
                "ticks_ok": ticks_ok,
                "ticks_fail": ticks_fail,
                "novel_total": novel_total,
                "novel_since_prime": novel_since_prime,
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
                f"<b>MILLENNIUM shadow TICK FAIL</b>\n"
                f"run: <code>{RUN_ID}</code>\n"
                f"fails: {ticks_fail}\n"
                f"err: <code>{err[:200]}</code>"
            )
            now_iso_fail = datetime.now(timezone.utc).isoformat()
            _write_heartbeat({
                "run_id": RUN_ID,
                "status": "running",
                "label": LABEL,
                "started_at": RUN_TS.isoformat(),
                "tick_sec": tick_sec,
                "run_hours": run_hours,
                "ticks_ok": ticks_ok,
                "ticks_fail": ticks_fail,
                "novel_total": novel_total,
                "novel_since_prime": novel_since_prime,
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
        # Sleep in small slices so kill-flag / SIGINT are responsive.
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
        "stopped_reason": stop_requested["reason"] or "deadline",
        "started_at": RUN_TS.isoformat(),
        "stopped_at": stopped_at_str,
        "tick_sec": tick_sec,
        "run_hours": run_hours,
        "ticks_ok": ticks_ok,
        "ticks_fail": ticks_fail,
        "novel_total": novel_total,
        "novel_since_prime": novel_since_prime,
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
    # Backtest-style metrics: ler todos os records do JSONL, filtrar primed
    # (universo historico), computar Sharpe/Sortino/WR/PF/MaxDD/ROI sobre
    # os novel_since_prime e escrever em reports/summary.json.
    _write_run_summary(
        ticks_ok=ticks_ok,
        ticks_fail=ticks_fail,
        novel_total=novel_total,
        novel_since_prime=novel_since_prime,
        stopped_reason=stop_requested["reason"] or "deadline",
        stopped_at=stopped_at_str,
    )
    _write_per_engine_summaries(
        ticks_ok=ticks_ok,
        ticks_fail=ticks_fail,
        stopped_reason=stop_requested["reason"] or "deadline",
    )
    # Pre-check: skip graceful if tick 1 never created the row (e.g.
    # shadow crashed at boot, DB migrated later). Without this, upsert
    # raises "missing required fields" because we only pass ended_at+status.
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
        "SHADOW END ok=%d fail=%d novel=%d reason=%s",
        ticks_ok, ticks_fail, novel_total,
        stop_requested["reason"] or "deadline",
    )
    _tg_send(
        f"<b>MILLENNIUM shadow STOP</b>\n"
        f"run: <code>{RUN_ID}</code>\n"
        f"ticks_ok: {ticks_ok} · fails: {ticks_fail}\n"
        f"signals: {novel_total}\n"
        f"reason: {stop_requested['reason'] or 'deadline'}"
    )
    return 0 if ticks_ok > 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tick-sec", type=int, default=900,
                    help="seconds between ticks (default 900 = 15min)")
    ap.add_argument("--run-hours", type=float, default=24.0,
                    help="total run duration in hours; 0 = forever (default 24)")
    ap.add_argument("--label", type=str, default=None,
                    help="optional instance label (sanitized to [a-z0-9-], max 40). "
                         "overrides AURUM_SHADOW_LABEL env.")
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
