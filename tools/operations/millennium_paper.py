"""MILLENNIUM paper runner — pod execution with configurable account.

Runs operational core (CITADEL + JUMP + RENAISSANCE) every TICK_SEC sec,
opens positions on novel signals, tracks them tick-a-tick over real OHLCV,
closes on stop/target intrabar or KS fast_halt. Writes positions/account/
trades/equity/fills/signals/summary to data/millennium_paper/<run_id>/.

Not live trading — this is a simulated account. No exchange credentials
required. Use launcher cockpit or systemctl to manage lifecycle.

Usage:
    python tools/operations/millennium_paper.py \\
        --account-size 10000 --tick-sec 900 --run-hours 0
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import os
import signal as os_signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.fs import atomic_write  # noqa: E402
from core.shadow_contract import compute_config_hash  # noqa: E402
from tools.operations.paper_account import PaperAccount  # noqa: E402
from tools.operations.paper_executor import PaperExecutor, Position  # noqa: E402
from tools.operations.paper_position_manager import (  # noqa: E402
    PositionManager,
    ClosedTrade,
)
from tools.operations.paper_ks_gate import KSLiveGate, KSState  # noqa: E402
from tools.operations.paper_metrics import MetricsStreamer  # noqa: E402

RUN_TS = datetime.now(timezone.utc)
RUN_ID = RUN_TS.strftime("%Y-%m-%d_%H%M")
RUN_DIR = ROOT / "data" / "millennium_paper" / RUN_ID
LOGS_DIR = RUN_DIR / "logs"
REPORTS_DIR = RUN_DIR / "reports"
STATE_DIR = RUN_DIR / "state"
for _d in (LOGS_DIR, REPORTS_DIR, STATE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

PAPER_LOG = LOGS_DIR / "paper.log"
TRADES_PATH = REPORTS_DIR / "trades.jsonl"
EQUITY_PATH = REPORTS_DIR / "equity.jsonl"
FILLS_PATH = REPORTS_DIR / "fills.jsonl"
SIGNALS_PATH = REPORTS_DIR / "signals.jsonl"
POSITIONS_PATH = STATE_DIR / "positions.json"
ACCOUNT_PATH = STATE_DIR / "account.json"
HEARTBEAT_PATH = STATE_DIR / "heartbeat.json"
MANIFEST_PATH = STATE_DIR / "manifest.json"
KILL_FLAG = RUN_DIR / ".kill"

log = logging.getLogger("millennium_paper")
log.setLevel(logging.INFO)


# Telegram (copy-adapted from shadow; silent fallback)
_TELEGRAM_CFG: dict | None = None
_TG_CFG_MISSING_LOGGED = False


def _telegram_cfg() -> dict | None:
    global _TELEGRAM_CFG
    if _TELEGRAM_CFG is not None:
        return _TELEGRAM_CFG or None
    keys_path = ROOT / "config" / "keys.json"
    if not keys_path.exists():
        _TELEGRAM_CFG = {}
        return None
    try:
        data = json.loads(keys_path.read_text(encoding="utf-8"))
        tg = data.get("telegram") or {}
        if tg.get("bot_token") and tg.get("chat_id"):
            _TELEGRAM_CFG = {"token": str(tg["bot_token"]),
                             "chat_id": str(tg["chat_id"])}
            return _TELEGRAM_CFG
    except (json.JSONDecodeError, OSError):
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
        import urllib.request
        url = f"https://api.telegram.org/bot{cfg['token']}/sendMessage"
        payload = json.dumps({
            "chat_id": cfg["chat_id"], "text": text, "parse_mode": "HTML",
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        first = text.splitlines()[0][:80]
        log.info("telegram sent: %s", first)
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram send failed: %s", exc)


# Atomic writers
def _append_jsonl(path: Path, record: dict) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _pos_snapshot(pos: Position) -> dict:
    return {
        "id": pos.id, "engine": pos.engine, "symbol": pos.symbol,
        "direction": pos.direction, "entry_price": round(pos.entry_price, 6),
        "stop": round(pos.stop, 6), "target": round(pos.target, 6),
        "size": round(pos.size, 6), "notional": round(pos.notional, 2),
        "opened_at": pos.opened_at, "opened_at_idx": pos.opened_at_idx,
        "unrealized_pnl": round(pos.unrealized_pnl, 2),
        "mtm_price": round(pos.mtm_price, 6) if pos.mtm_price is not None else None,
        "bars_held": pos.bars_held,
    }


def _write_positions(positions: list[Position]) -> None:
    payload = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "count": len(positions),
        "positions": [_pos_snapshot(p) for p in positions],
    }
    atomic_write(POSITIONS_PATH, json.dumps(payload, indent=2))


def _write_account(account: PaperAccount, ks: KSLiveGate, n_open: int,
                   n_closed: int, metrics: dict) -> None:
    snap = account.snapshot()
    snap.update(ks.snapshot())
    snap["positions_open"] = n_open
    snap["trades_closed"] = n_closed
    snap["metrics"] = metrics
    snap["as_of"] = datetime.now(timezone.utc).isoformat()
    atomic_write(ACCOUNT_PATH, json.dumps(snap, indent=2))


def _write_heartbeat(state_dict: dict) -> None:
    atomic_write(HEARTBEAT_PATH, json.dumps(state_dict, indent=2))


def _write_manifest(account_size: float) -> None:
    import socket
    import subprocess
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=ROOT).decode().strip()
    except Exception:  # noqa: BLE001
        commit = "unknown"
        branch = "unknown"
    payload = {
        "run_id": RUN_ID, "engine": "millennium", "mode": "paper",
        "started_at": RUN_TS.isoformat(),
        "commit": commit, "branch": branch,
        "config_hash": compute_config_hash(),
        "host": socket.gethostname(),
        "python_version": sys.version.split()[0],
        "account_size": account_size,
    }
    atomic_write(MANIFEST_PATH, json.dumps(payload, indent=2))


# Scan hook (wraps _collect_operational_trades)
def _scan_new_signals(notify: bool = True) -> list[dict]:
    """Call the MILLENNIUM scan and return the list of novel trade dicts.

    This is the paper equivalent of shadow's _run_tick signal extraction.
    De-dup keys use (engine, symbol, open_ts) — same as shadow.
    """
    from engines.millennium import _load_dados, _collect_operational_trades
    with contextlib.redirect_stdout(io.StringIO()):
        all_dfs, htf_stack, macro_series, corr = _load_dados(False)
        _, all_trades = _collect_operational_trades(all_dfs, htf_stack,
                                                    macro_series, corr)
    return list(all_trades)


def _fetch_new_bars(symbol: str, since_iso: str | None) -> list[dict]:
    """Fetch OHLCV bars newer than since_iso for symbol.

    Uses core.data fetch helpers; returns list of bar dicts with keys
    high/low/close/time. Returns empty list on failure (caller MTM safely
    ignores a position until bars arrive).
    """
    try:
        from core.data import fetch as core_fetch
        df = core_fetch(symbol, interval="15m", n_candles=20)
    except Exception as exc:  # noqa: BLE001
        log.warning("fetch_new_bars %s failed: %s", symbol, exc)
        return []
    if df is None or df.empty:
        return []
    df = df.copy()
    if since_iso:
        try:
            from datetime import datetime as dt
            since_dt = dt.fromisoformat(since_iso.replace("Z", "+00:00"))
            df = df[df["time"] > since_dt]
        except Exception:  # noqa: BLE001
            pass
    out: list[dict] = []
    for _, row in df.iterrows():
        out.append({
            "time": row["time"].isoformat() if hasattr(row["time"], "isoformat")
                    else str(row["time"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        })
    return out


# Runner state
@dataclass
class RunnerState:
    account_size: float
    account: PaperAccount = field(init=False)
    ks: KSLiveGate = field(init=False)
    executor: PaperExecutor = field(init=False)
    pos_mgr: PositionManager = field(init=False)
    metrics: MetricsStreamer = field(init=False)
    tick_sec: int = 900
    open_positions: list[Position] = field(default_factory=list)
    seen_keys: set = field(default_factory=set)
    last_bar_ts_by_symbol: dict[str, str] = field(default_factory=dict)
    ticks_ok: int = 0
    ticks_fail: int = 0
    novel_total: int = 0
    novel_since_prime: int = 0
    last_novel_at: str | None = None
    trades_closed: int = 0
    primed: bool = False

    def __post_init__(self):
        from config.params import (
            ACCOUNT_SIZE, BASE_RISK, SLIPPAGE, SPREAD, COMMISSION,
            FUNDING_PER_8H,
        )
        try:
            from engines.live import KS_FAST_DD_MULT as _KS_MULT
        except Exception:
            _KS_MULT = 2.0
        self.account = PaperAccount(initial_balance=self.account_size)
        self.ks = KSLiveGate(account_size=self.account_size,
                             base_risk=BASE_RISK, fast_mult=_KS_MULT)
        self.executor = PaperExecutor(
            account_size=self.account_size,
            base_account_size=float(ACCOUNT_SIZE),
            slippage=SLIPPAGE, spread=SPREAD, commission=COMMISSION,
        )
        self.pos_mgr = PositionManager(
            commission=COMMISSION, funding_per_8h=FUNDING_PER_8H,
            tick_sec=self.tick_sec,
        )
        self.metrics = MetricsStreamer(account_size=self.account_size)


def _trade_key(trade: dict) -> tuple:
    return (str(trade.get("strategy")), str(trade.get("symbol")),
            str(trade.get("open_ts") or trade.get("timestamp")))


def _signal_age_seconds(trade: dict) -> float | None:
    """Age of trade signal in seconds (UTC now - signal timestamp).

    Returns None if the timestamp is missing or unparseable. Accepts both
    ISO ('2026-04-20T11:15:00+00:00') and the legacy CITADEL format
    ('2026-04-20 11:15:00' naive = UTC).
    """
    raw = trade.get("open_ts") or trade.get("timestamp")
    if raw is None:
        return None
    try:
        if hasattr(raw, "to_pydatetime"):
            ts = raw.to_pydatetime()
        elif isinstance(raw, datetime):
            ts = raw
        else:
            s = str(raw).strip()
            if "T" not in s and " " in s:
                s = s.replace(" ", "T", 1)
            s = s.replace("Z", "+00:00")
            ts = datetime.fromisoformat(s)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None
    return (datetime.now(timezone.utc) - ts).total_seconds()


def _is_live_signal(trade: dict, tick_sec: int,
                    tolerance_mult: float = 2.0) -> bool:
    """True if signal is from the most recent bar(s).

    A signal is 'live' when its timestamp is within ``tolerance_mult×tick_sec``
    of now. Default tolerance is 2× — for a 15m tick, accepts signals whose
    bar opened in the last 30 minutes. Protects paper from treating 90d of
    backscan history as novel opens (bug 2026-04-19).
    """
    age = _signal_age_seconds(trade)
    if age is None:
        return False
    if age < -tick_sec:
        return False
    return age <= tolerance_mult * tick_sec


def _flatten_all(state: RunnerState, reason: str, notify: bool) -> None:
    """Close every open position at MTM or entry price. Records ClosedTrade
    per position, appends to trades.jsonl and fills.jsonl."""
    flatten_ts = datetime.now(timezone.utc).isoformat()
    for pos in state.open_positions:
        exit_px = pos.mtm_price if pos.mtm_price is not None else pos.entry_price
        c = state.pos_mgr._close(pos, exit_px, reason, flatten_ts)
        state.account.apply_realized(c.pnl_after_fees)
        state.metrics.record_closed({
            "primed": False, "pnl": c.pnl_after_fees,
            "strategy": c.engine, "symbol": c.symbol,
            "exit_reason": c.exit_reason,
        })
        _append_jsonl(TRADES_PATH, {
            "id": c.id, "engine": c.engine, "symbol": c.symbol,
            "direction": c.direction, "entry_price": c.entry_price,
            "exit_price": c.exit_price, "stop": c.stop, "target": c.target,
            "size": c.size, "entry_at": c.opened_at,
            "exit_at": c.closed_at, "exit_reason": reason,
            "pnl": c.pnl, "pnl_after_fees": c.pnl_after_fees,
            "r_multiple": c.r_multiple, "bars_held": c.bars_held,
            "primed": False,
        })
        _append_jsonl(FILLS_PATH, {
            "event": "close", "pos_id": c.id, "ts": c.closed_at,
            "reason": reason, "price": c.exit_price,
            "pnl_after_fees": c.pnl_after_fees,
        })
        state.trades_closed += 1
    state.open_positions = []
    state.account.set_unrealized(0.0)
    if notify:
        _tg_send(
            f"<b>PAPER flatten</b> ({reason}) · equity ${state.account.equity:,.2f}"
        )


def run_one_tick(state: RunnerState, tick_idx: int, notify: bool = True) -> None:
    """Execute one tick: check exits on open, fetch signals, open new.

    Tick order:
      1. Update MTM + check exits on existing open positions
      2. KS gate check (flatten if fast_halt triggered)
      3. Scan for new signals (dedup via seen_keys)
      4. Open new positions (subject to MAX_OPEN_POSITIONS)
      5. Update metrics + snapshot all state atomically
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Exits on open positions
    still_open: list[Position] = []
    for pos in list(state.open_positions):
        new_bars = _fetch_new_bars(pos.symbol,
                                   state.last_bar_ts_by_symbol.get(pos.symbol))
        if new_bars:
            state.last_bar_ts_by_symbol[pos.symbol] = new_bars[-1]["time"]
        closed = state.pos_mgr.check_exits([pos], new_bars)
        if closed:
            c = closed[0]
            state.account.apply_realized(c.pnl_after_fees)
            state.metrics.record_closed({
                "primed": False, "pnl": c.pnl_after_fees,
                "strategy": c.engine, "symbol": c.symbol,
                "exit_reason": c.exit_reason,
            })
            _append_jsonl(TRADES_PATH, {
                "id": c.id, "engine": c.engine, "symbol": c.symbol,
                "direction": c.direction, "entry_price": c.entry_price,
                "exit_price": c.exit_price, "stop": c.stop, "target": c.target,
                "size": c.size, "entry_at": c.opened_at,
                "exit_at": c.closed_at, "exit_reason": c.exit_reason,
                "pnl": c.pnl, "pnl_after_fees": c.pnl_after_fees,
                "r_multiple": c.r_multiple, "bars_held": c.bars_held,
                "primed": False,
            })
            _append_jsonl(FILLS_PATH, {
                "event": "close", "pos_id": c.id, "ts": c.closed_at,
                "reason": c.exit_reason, "price": c.exit_price,
                "pnl": c.pnl, "pnl_after_fees": c.pnl_after_fees,
                "commission": c.exit_commission,
            })
            if notify:
                _tg_send(
                    f"<b>PAPER · {c.engine} {c.symbol}</b> · {c.exit_reason.upper()}\n"
                    f"pnl: {c.pnl_after_fees:+.2f} · R={c.r_multiple:.2f} · "
                    f"equity ${state.account.equity:,.2f}"
                )
            state.trades_closed += 1
        else:
            still_open.append(pos)
    state.open_positions = still_open

    # Update unrealized total from remaining positions
    total_unreal = sum(p.unrealized_pnl for p in state.open_positions)
    state.account.set_unrealized(total_unreal)

    # 2. KS gate
    triggered = state.ks.check(peak_equity=state.account.peak_equity,
                               equity=state.account.equity)
    if triggered:
        log.warning("KS FAST HALT triggered — flattening %d positions",
                    len(state.open_positions))
        _flatten_all(state, "ks_abort", notify)
        if notify:
            _tg_send(
                f"<b>⚠ KS FAST HALT</b> · paper run halted\n"
                f"equity ${state.account.equity:,.2f} · "
                f"dd ${state.account.drawdown:.2f}"
            )

    # 3. Signal discovery (skip if KS halted)
    if state.ks.state == KSState.NORMAL:
        try:
            all_trades = _scan_new_signals(notify=notify)
        except Exception as exc:  # noqa: BLE001
            log.warning("scan failed: %s", exc)
            all_trades = []
        # First tick primes seen_keys without opening positions. The
        # MILLENNIUM scan returns *all* historical trades in the 90d
        # DataFrame; without priming, paper would treat 628 backscan
        # signals as novels and open the first 5 using prices from
        # months ago (bug 2026-04-19).
        priming = not state.primed
        primed_count = 0
        for t in all_trades:
            key = _trade_key(t)
            if key in state.seen_keys:
                continue
            state.seen_keys.add(key)
            state.novel_total += 1
            state.last_novel_at = now_iso
            if priming:
                primed_count += 1
                continue
            state.novel_since_prime += 1

            # Live-bar filter: only open on signals from the most recent
            # bar. Rejects residual history that slips past priming (e.g.
            # a deleted+readded bar between ticks).
            if not _is_live_signal(t, state.tick_sec):
                _append_jsonl(SIGNALS_PATH, {
                    "ts": now_iso, "engine": t.get("strategy"),
                    "symbol": t.get("symbol"),
                    "direction": t.get("direction"),
                    "decision": "skipped",
                    "reason": "stale_bar",
                    "signal_ts": str(t.get("timestamp") or t.get("open_ts")),
                })
                continue

            # 4. Portfolio gate V1: MAX_OPEN_POSITIONS only
            try:
                from config.params import MAX_OPEN_POSITIONS
            except Exception:
                MAX_OPEN_POSITIONS = 5
            if len(state.open_positions) >= MAX_OPEN_POSITIONS:
                _append_jsonl(SIGNALS_PATH, {
                    "ts": now_iso, "engine": t.get("strategy"),
                    "symbol": t.get("symbol"),
                    "direction": t.get("direction"),
                    "decision": "skipped",
                    "reason": "max_open_positions",
                })
                continue

            pos = state.executor.open(t, opened_at_idx=tick_idx,
                                      opened_at_iso=now_iso)
            state.open_positions.append(pos)
            state.last_bar_ts_by_symbol[pos.symbol] = now_iso
            _append_jsonl(FILLS_PATH, {
                "event": "open", "pos_id": pos.id, "ts": pos.opened_at,
                "engine": pos.engine, "symbol": pos.symbol,
                "direction": pos.direction, "price": pos.entry_price,
                "size": pos.size, "commission": pos.commission_paid,
            })
            _append_jsonl(SIGNALS_PATH, {
                "ts": now_iso, "engine": pos.engine,
                "symbol": pos.symbol, "direction": pos.direction,
                "entry": pos.entry_price, "stop": pos.stop,
                "target": pos.target, "decision": "opened",
                "pos_id": pos.id,
            })
            if notify:
                _tg_send(
                    f"<b>PAPER · {pos.engine} {pos.direction} {pos.symbol}</b>\n"
                    f"entry {pos.entry_price:.4f} · stop {pos.stop:.4f} · "
                    f"tgt {pos.target:.4f} · notional ${pos.notional:,.0f}"
                )

    # 5. Metrics + snapshots
    if state.ks.state == KSState.NORMAL and not state.primed:
        # After a successful first scan, paper is primed — future ticks
        # open positions.
        state.primed = True
        log.info("PAPER PRIMED tick=%d signals_seen=%d", tick_idx, primed_count)
    metrics = state.metrics.current_metrics()
    state.metrics.record_equity_point(
        tick=tick_idx, ts=now_iso,
        equity=state.account.equity, balance=state.account.balance,
        realized=state.account.realized_pnl,
        unrealized=state.account.unrealized_pnl,
        drawdown=state.account.drawdown,
        positions_open=len(state.open_positions),
    )
    _append_jsonl(EQUITY_PATH, state.metrics.equity_points()[-1])
    _write_positions(state.open_positions)
    _write_account(state.account, state.ks, len(state.open_positions),
                   state.trades_closed, metrics)
    state.ticks_ok += 1
    _write_heartbeat({
        "run_id": RUN_ID, "status": "running",
        "started_at": RUN_TS.isoformat(),
        "tick_sec": state.tick_sec, "ticks_ok": state.ticks_ok,
        "ticks_fail": state.ticks_fail,
        "novel_total": state.novel_total,
        "novel_since_prime": state.novel_since_prime,
        "last_novel_at": state.last_novel_at,
        "last_tick_at": now_iso,
        "last_error": None,
        "mode": "paper",
        "primed": state.primed,
        "account_size": state.account_size,
        "equity": round(state.account.equity, 2),
        "drawdown_pct": round(state.account.drawdown_pct, 3),
        "ks_state": state.ks.state.value,
    })


def _write_run_summary(state: RunnerState, stopped_reason: str) -> None:
    metrics = state.metrics.current_metrics()
    summary = {
        "run_id": RUN_ID,
        "mode": "paper",
        "account_size": state.account_size,
        "started_at": RUN_TS.isoformat(),
        "stopped_at": datetime.now(timezone.utc).isoformat(),
        "stopped_reason": stopped_reason,
        "ticks_ok": state.ticks_ok, "ticks_fail": state.ticks_fail,
        "novel_total": state.novel_total,
        "final_equity": round(state.account.equity, 2),
        "final_balance": round(state.account.balance, 2),
        "peak_equity": round(state.account.peak_equity, 2),
        "realized_pnl": round(state.account.realized_pnl, 2),
        "ks_state": state.ks.state.value,
        "metrics": metrics,
    }
    atomic_write(REPORTS_DIR / "summary.json",
                 json.dumps(summary, indent=2))


def run_paper(tick_sec: int, run_hours: float, account_size: float) -> int:
    """Main paper loop. Returns exit code."""
    handler = logging.FileHandler(PAPER_LOG, encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(fmt)
    log.addHandler(handler)
    stderr = logging.StreamHandler()
    stderr.setFormatter(fmt)
    log.addHandler(stderr)

    _write_manifest(account_size)

    state = RunnerState(account_size=account_size, tick_sec=tick_sec)
    deadline = time.time() + run_hours * 3600.0 if run_hours > 0 else None
    stop = {"flag": False, "reason": ""}

    def _handle_signal(signum, _frame):
        stop["flag"] = True
        stop["reason"] = f"signal {signum}"

    os_signal.signal(os_signal.SIGINT, _handle_signal)
    with contextlib.suppress(AttributeError, ValueError):
        os_signal.signal(os_signal.SIGTERM, _handle_signal)

    log.info("PAPER START run=%s account=%.2f tick=%ds hours=%.1f",
             RUN_ID, account_size, tick_sec, run_hours)
    _tg_send(
        f"<b>MILLENNIUM paper START</b>\n"
        f"run: <code>{RUN_ID}</code>\n"
        f"account: ${account_size:,.0f} · tick {tick_sec}s · hours {run_hours}"
    )

    tick_idx = 0
    first_tick = True
    try:
        while True:
            if KILL_FLAG.exists():
                stop["flag"] = True
                stop["reason"] = "kill file"
                break
            if deadline is not None and time.time() >= deadline:
                stop["reason"] = f"deadline {run_hours}h"
                break
            if stop["flag"]:
                break
            if state.ks.state != KSState.NORMAL:
                stop["flag"] = True
                stop["reason"] = f"ks_{state.ks.state.value}"
                break
            tick_idx += 1
            try:
                run_one_tick(state, tick_idx=tick_idx, notify=not first_tick)
                first_tick = False
            except Exception as exc:  # noqa: BLE001
                state.ticks_fail += 1
                log.exception("tick %d failed: %s", tick_idx, exc)
            time.sleep(tick_sec)
    finally:
        _write_run_summary(state, stop["reason"] or "clean_exit")
        _tg_send(
            f"<b>MILLENNIUM paper STOP</b>\n"
            f"equity ${state.account.equity:,.2f} · "
            f"roi {state.metrics.current_metrics()['roi_pct']:+.2f}%"
        )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-size", type=float,
                        default=float(os.environ.get("AURUM_PAPER_ACCOUNT_SIZE",
                                                     10_000.0)))
    parser.add_argument("--tick-sec", type=int, default=900)
    parser.add_argument("--run-hours", type=float, default=0.0)
    args = parser.parse_args()
    return run_paper(args.tick_sec, args.run_hours, args.account_size)


if __name__ == "__main__":
    sys.exit(main())
