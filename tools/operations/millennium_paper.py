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
import socket
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.fs import atomic_write  # noqa: E402
from core.ops import db_live_runs  # noqa: E402
from core.shadow_contract import compute_config_hash  # noqa: E402
from core.data.ws_price_feed import (  # noqa: E402
    WSPriceFeed, make_live_price_fn,
)
from tools.operations.millennium_signal_gate import (  # noqa: E402
    is_live_signal,
    signal_age_seconds,
    signal_timestamp,
    trade_key,
)
from tools.operations.paper_account import PaperAccount  # noqa: E402
from tools.operations.paper_executor import PaperExecutor, Position  # noqa: E402
from tools.operations.paper_position_manager import (  # noqa: E402
    PositionManager,
)
from tools.operations.paper_ks_gate import KSLiveGate, KSState  # noqa: E402
from tools.operations.paper_metrics import MetricsStreamer  # noqa: E402
from tools.operations.run_id import build_run_id, sanitize_label  # noqa: E402

RUN_TS = datetime.now(timezone.utc)
# Module-level LABEL reads from env at import (systemd path). CLI --label
# later overrides via _configure_run(). Tests monkeypatch RUN_ID/paths
# directly and never exercise _configure_run.
LABEL: str | None = sanitize_label(os.environ.get("AURUM_PAPER_LABEL"))
RUN_ID = build_run_id(RUN_TS, LABEL, mode="paper")
RUN_DIR = ROOT / "data" / "millennium_paper" / RUN_ID
LOGS_DIR = RUN_DIR / "logs"
REPORTS_DIR = RUN_DIR / "reports"
STATE_DIR = RUN_DIR / "state"

PAPER_LOG = LOGS_DIR / "paper.log"
TRADES_PATH = REPORTS_DIR / "trades.jsonl"
EQUITY_PATH = REPORTS_DIR / "equity.jsonl"
FILLS_PATH = REPORTS_DIR / "fills.jsonl"
SIGNALS_PATH = REPORTS_DIR / "signals.jsonl"
POSITIONS_PATH = STATE_DIR / "positions.json"
ACCOUNT_PATH = STATE_DIR / "account.json"
HEARTBEAT_PATH = STATE_DIR / "heartbeat.json"
MANIFEST_PATH = STATE_DIR / "manifest.json"

# Symbol cooldown after a stop-loss exit. Mirrors engines.millennium
# SYMBOL_COOLDOWN_BARS_AFTER_LOSS (24 bars). Hardcoded here to avoid
# importing the heavy engines/millennium module at startup just for a
# single int. Override via env for tests/operations:
#   AURUM_SYM_LOSS_COOLDOWN_BARS=0  → disable
#   AURUM_SYM_LOSS_COOLDOWN_BARS=N  → N bars × tick_sec
SYM_LOSS_COOLDOWN_BARS = int(os.environ.get("AURUM_SYM_LOSS_COOLDOWN_BARS", "24"))
# Exit reasons that classify as a real loss → arm the cooldown. "breakeven"
# is excluded (scratch outcome at entry price), "target" is a win, "ks_abort"
# / "manual_flatten" are forced exits unrelated to signal quality.
_LOSS_EXIT_REASONS = frozenset({"stop_initial", "trailing"})
KILL_FLAG = RUN_DIR / ".kill"


def _ensure_run_dirs() -> None:
    for _d in (LOGS_DIR, REPORTS_DIR, STATE_DIR):
        _d.mkdir(parents=True, exist_ok=True)


def _configure_run(label: str | None) -> None:
    """Re-point module-level paths at a new RUN_ID built from ``label``.

    Called from main() after argparse when --label differs from the
    env-derived LABEL. Rebuilds RUN_ID, RUN_DIR and every path global.
    Safe to call multiple times; disk materialization is deferred until
    run_paper() starts.
    """
    global LABEL, RUN_ID, RUN_DIR, LOGS_DIR, REPORTS_DIR, STATE_DIR
    global PAPER_LOG, TRADES_PATH, EQUITY_PATH, FILLS_PATH, SIGNALS_PATH
    global POSITIONS_PATH, ACCOUNT_PATH, HEARTBEAT_PATH, MANIFEST_PATH
    global KILL_FLAG
    LABEL = sanitize_label(label)
    RUN_ID = build_run_id(RUN_TS, LABEL, mode="paper")
    RUN_DIR = ROOT / "data" / "millennium_paper" / RUN_ID
    LOGS_DIR = RUN_DIR / "logs"
    REPORTS_DIR = RUN_DIR / "reports"
    STATE_DIR = RUN_DIR / "state"
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
    try:
        from core.risk.key_store import load_runtime_keys  # noqa: PLC0415
        data = load_runtime_keys()
        tg = data.get("telegram") or {}
        if tg.get("bot_token") and tg.get("chat_id"):
            _TELEGRAM_CFG = {"token": str(tg["bot_token"]),
                             "chat_id": str(tg["chat_id"])}
            return _TELEGRAM_CFG
    except Exception:  # noqa: BLE001
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


def _persist_signal_to_db(record: dict, *, observed_at: str) -> None:
    """Persist one paper LIVE signal (non-stale) to SQLite live_signals.

    Companion to _persist_trade_to_db: closed trades land in live_trades,
    fired (live, non-stale) signals land in live_signals — together they
    let the operator SQL-query "what was the JUMP score of the signal
    that opened pos_X?" without parsing JSONLs from the run_dir.

    Failures NEVER bubble — tick loop must never crash on DB issue.
    Connection is short-lived (per-call) to avoid long-lived locks.

    Aliasing: the runner's signal dict uses 'engine' (paper vocabulary);
    table column is 'strategy'. We map engine→strategy if the canonical
    is missing. observed_at is injected by the caller (= now_iso of the
    tick that observed the signal) and feeds the unique key together
    with (run_id, symbol).
    """
    try:
        import sqlite3
        from core.ops.db_live_trades import upsert_signal  # noqa: PLC0415
        db_path = ROOT / "data" / "aurum.db"
        if not db_path.exists():
            return  # DB not initialised on this host — silent skip
        payload = dict(record)
        # 'engine' (paper-runner term) → 'strategy' (DB column term)
        if "engine" in payload and "strategy" not in payload:
            payload["strategy"] = payload["engine"]
        # observed_at is required for the unique key — caller passes it
        payload["observed_at"] = observed_at
        with sqlite3.connect(str(db_path), timeout=5.0) as conn:
            upsert_signal(conn, RUN_ID, payload)
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        try:
            import logging as _log
            _log.getLogger("aurum.paper").warning(
                "live_signals upsert failed (non-fatal): %s", exc,
            )
        except Exception:
            pass


def _persist_trade_to_db(record: dict) -> None:
    """Persist a closed-trade record to SQLite live_trades table.

    Belt-and-suspenders companion to _append_jsonl(TRADES_PATH, ...):
    JSONL stays the source of truth; DB is convenience for cross-run
    SQL queries ("all citadel paper trades this week"). Failures here
    NEVER bubble — trade lifecycle must not depend on DB availability.

    Connection is opened per-call and closed immediately to keep zero
    long-lived locks and survive concurrent writers (multiple paper
    runners on same VPS, or operator running ad-hoc backfills).

    The runner's record uses 'engine'/'entry_price'/'pnl_after_fees' —
    `db_live_trades._norm_trade` knows the aliases (entry_price→entry,
    pnl→pnl_usd, etc), so we forward the raw record. We additionally
    map 'engine'→'strategy' (the table column for which sub-engine
    inside millennium emitted the signal) before forwarding.
    """
    try:
        import sqlite3
        from core.ops.db_live_trades import upsert_trade  # noqa: PLC0415
        db_path = ROOT / "data" / "aurum.db"
        if not db_path.exists():
            return  # DB not initialised on this host — silent skip
        payload = dict(record)
        # 'engine' (paper-runner term) → 'strategy' (DB column term)
        if "engine" in payload and "strategy" not in payload:
            payload["strategy"] = payload["engine"]
        # canonical 'ts' for UNIQUE key — paper writer uses entry_at
        if "ts" not in payload and payload.get("entry_at"):
            payload["ts"] = payload["entry_at"]
        # canonical pnl_usd — paper uses pnl_after_fees as the realised pnl
        if "pnl_usd" not in payload and payload.get("pnl_after_fees") is not None:
            payload["pnl_usd"] = payload["pnl_after_fees"]
        with sqlite3.connect(str(db_path), timeout=5.0) as conn:
            upsert_trade(conn, RUN_ID, payload)
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        # Never crash trading on DB issue — log via PAPER_LOG handler
        try:
            import logging as _log
            _log.getLogger("aurum.paper").warning(
                "live_trades upsert failed (non-fatal): %s", exc,
            )
        except Exception:
            pass


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
        "label": LABEL,
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
    # Live collector scans the *tail* bars that _collect_operational_trades
    # skips (needs forward bars for WIN/LOSS labeling). Without this,
    # the last ~50h of bars NEVER produce signals and paper never opens
    # — see engines/citadel.py live_mode docstring for the mechanism.
    from engines.millennium import _load_dados, _collect_live_signals
    with contextlib.redirect_stdout(io.StringIO()):
        all_dfs, htf_stack, macro_series, corr = _load_dados(False)
        _, all_trades = _collect_live_signals(all_dfs, htf_stack,
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
        from datetime import datetime as dt
        try:
            since_dt = dt.fromisoformat(since_iso.replace("Z", "+00:00"))
        except ValueError:
            log.warning("fetch_new_bars %s: malformed since_iso %r — skipping filter",
                        symbol, since_iso)
            since_dt = None
        if since_dt is not None:
            # df["time"] is naive UTC (pd.to_datetime of Binance klines ms).
            # An aware cursor used to TypeError the comparison; the old bare
            # except swallowed it, the filter was skipped, and _walk_bars got
            # ~5h of pre-open candles — ghost-exit bug (2026-04-23 ARBUSDT).
            if since_dt.tzinfo is not None:
                since_dt = since_dt.astimezone(timezone.utc).replace(tzinfo=None)
            df = df[df["time"] > since_dt]
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
    # symbol → ISO timestamp until which new opens on that symbol are blocked
    # after a stop-loss exit. Mirrors engines.millennium.SYMBOL_COOLDOWN_BARS_AFTER_LOSS
    # (24 bars × tick_sec = 6h default at 15m tf). Without this, a stop-out can
    # be re-entered the next tick on the very same setup (XRP 2026-04-25 13:30
    # incident: pos_000001 stopped 16:30, pos_000002 opened 16:47, same JUMP LONG).
    sym_loss_cooldown_until: dict[str, str] = field(default_factory=dict)
    ticks_ok: int = 0
    ticks_fail: int = 0
    novel_total: int = 0
    novel_since_prime: int = 0
    last_novel_at: str | None = None
    trades_closed: int = 0
    primed: bool = False
    ws_feed: WSPriceFeed | None = None

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
    return trade_key(trade)


def _signal_age_seconds(trade: dict) -> float | None:
    return signal_age_seconds(trade)


def _is_live_signal(trade: dict, tick_sec: int,
                    tolerance_mult: float = 2.0) -> bool:
    """True if signal is from the most recent bar(s).

    A signal is 'live' when its timestamp is within ``tolerance_mult×tick_sec``
    of now. Default tolerance is 2× — for a 15m tick, accepts signals whose
    bar opened in the last 30 minutes. Protects paper from treating 90d of
    backscan history as novel opens (bug 2026-04-19).
    """
    return is_live_signal(trade, tick_sec=tick_sec, tolerance_mult=tolerance_mult)


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
        trade_record = {
            "id": c.id, "engine": c.engine, "symbol": c.symbol,
            "direction": c.direction, "entry_price": c.entry_price,
            "exit_price": c.exit_price, "stop": c.stop, "target": c.target,
            "size": c.size, "notional": c.entry_price * c.size,
            "entry_at": c.opened_at,
            "exit_at": c.closed_at, "exit_reason": reason,
            "pnl": c.pnl, "pnl_after_fees": c.pnl_after_fees,
            "r_multiple": c.r_multiple, "bars_held": c.bars_held,
            "primed": False,
        }
        _append_jsonl(TRADES_PATH, trade_record)
        _persist_trade_to_db(trade_record)
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
            trade_record = {
                "id": c.id, "engine": c.engine, "symbol": c.symbol,
                "direction": c.direction, "entry_price": c.entry_price,
                "exit_price": c.exit_price, "stop": c.stop, "target": c.target,
                "size": c.size, "notional": c.entry_price * c.size,
                "entry_at": c.opened_at,
                "exit_at": c.closed_at, "exit_reason": c.exit_reason,
                "pnl": c.pnl, "pnl_after_fees": c.pnl_after_fees,
                "r_multiple": c.r_multiple, "bars_held": c.bars_held,
                "primed": False,
            }
            _append_jsonl(TRADES_PATH, trade_record)
            _persist_trade_to_db(trade_record)
            _append_jsonl(FILLS_PATH, {
                "event": "close", "pos_id": c.id, "ts": c.closed_at,
                "reason": c.exit_reason, "price": c.exit_price,
                "pnl": c.pnl, "pnl_after_fees": c.pnl_after_fees,
                "commission": c.exit_commission,
            })
            if c.exit_reason in _LOSS_EXIT_REASONS and SYM_LOSS_COOLDOWN_BARS > 0:
                cooldown_until = (
                    datetime.fromisoformat(
                        str(c.closed_at).replace("Z", "+00:00")
                    )
                    if isinstance(c.closed_at, str)
                    else c.closed_at
                )
                if cooldown_until.tzinfo is None:
                    cooldown_until = cooldown_until.replace(tzinfo=timezone.utc)
                from datetime import timedelta
                cooldown_until = cooldown_until + timedelta(
                    seconds=SYM_LOSS_COOLDOWN_BARS * state.tick_sec
                )
                state.sym_loss_cooldown_until[c.symbol] = cooldown_until.isoformat()
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

    # 3. Signal discovery (skip if KS halted). Init counters upfront so the
    # heartbeat/log below can read them even when KS fast-halt short-circuits
    # the scan branch.
    all_trades: list = []
    priming = not state.primed
    primed_count = 0
    dedup_skips = 0
    stale_skips = 0
    live_count = 0
    opened_count = 0
    if state.ks.state == KSState.NORMAL:
        try:
            all_trades = _scan_new_signals(notify=notify)
        except Exception as exc:  # noqa: BLE001
            log.warning("scan failed: %s", exc)
            all_trades = []
        # First tick still populates seen_keys for dedup, but no longer
        # blocks opens — is_live_signal() is the real stale gate against
        # the 90d backscan residue (bug 2026-04-19). Pre-2026-04-21 the
        # priming unconditionally skipped opens, forcing every run to wait
        # one full tick_sec (15m default) before ever trading; runs killed
        # before tick 2 produced zero trades (data/millennium_paper/*
        # empty).
        for t in all_trades:
            key = _trade_key(t)
            if key in state.seen_keys:
                dedup_skips += 1
                continue
            state.seen_keys.add(key)

            # Live-bar filter: only open on signals from the most recent
            # bar(s). Rejects 90d backscan residue and most "future-ts"
            # artifacts from incomplete tail candles.
            if not _is_live_signal(t, state.tick_sec):
                stale_skips += 1
                if priming:
                    primed_count += 1
                _append_jsonl(SIGNALS_PATH, {
                    "ts": now_iso, "engine": t.get("strategy"),
                    "symbol": t.get("symbol"),
                    "direction": t.get("direction"),
                    "decision": "skipped",
                    "reason": "stale_bar",
                    "signal_ts": str(signal_timestamp(t)),
                })
                continue
            state.novel_total += 1
            state.novel_since_prime += 1
            live_count += 1
            state.last_novel_at = now_iso

            # Persist live signal to live_signals — captures pre-gate
            # context (score/struct/entropy/hurst/primed) that JSONL has
            # but live_trades doesn't. Fires for every non-stale signal,
            # regardless of whether the gates below let it open. Pairs
            # with _persist_trade_to_db on close. Silent on DB failure.
            _persist_signal_to_db(t, observed_at=now_iso)

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

            # Portfolio gate V3: reject opening a position on a symbol whose
            # cooldown after a recent stop-loss has not expired yet. Without
            # this, JUMP/CITADEL signals can re-fire the same setup tick after
            # the stop fills and re-enter on the very same noise that just
            # stopped them out (XRP 2026-04-25 incident).
            t_sym_cd = str(t.get("symbol") or "").upper()
            cooldown_iso = state.sym_loss_cooldown_until.get(t_sym_cd)
            if cooldown_iso:
                try:
                    cooldown_dt = datetime.fromisoformat(
                        cooldown_iso.replace("Z", "+00:00")
                    )
                except ValueError:
                    cooldown_dt = None
                if cooldown_dt is not None:
                    now_dt = datetime.now(timezone.utc)
                    if cooldown_dt.tzinfo is None:
                        cooldown_dt = cooldown_dt.replace(tzinfo=timezone.utc)
                    if now_dt < cooldown_dt:
                        _append_jsonl(SIGNALS_PATH, {
                            "ts": now_iso, "engine": t.get("strategy"),
                            "symbol": t.get("symbol"),
                            "direction": t.get("direction"),
                            "decision": "skipped",
                            "reason": "sym_loss_cooldown",
                            "cooldown_until": cooldown_iso,
                        })
                        continue
                    # cooldown expired — clear stale entry
                    state.sym_loss_cooldown_until.pop(t_sym_cd, None)

            # Portfolio gate V2: reject opening a position on a symbol that
            # already has an open position in the OPPOSITE direction. Prevents
            # accidental cross-engine hedges (e.g. JUMP SHORT + RENAISSANCE
            # LONG on LINKUSDT simultaneously — zero net exposure, doubled
            # costs). Policy: first-come-first-served within the tick. Same
            # direction is allowed (confluence, not conflict).
            t_sym = str(t.get("symbol") or "").upper()
            t_dir = str(t.get("direction") or "").upper()
            has_opposing = any(
                str(p.symbol).upper() == t_sym
                and str(p.direction).upper() != t_dir
                for p in state.open_positions
            )
            if has_opposing:
                _append_jsonl(SIGNALS_PATH, {
                    "ts": now_iso, "engine": t.get("strategy"),
                    "symbol": t.get("symbol"),
                    "direction": t.get("direction"),
                    "decision": "skipped",
                    "reason": "direction_conflict",
                })
                continue

            live_fn = None
            if state.ws_feed is not None:
                live_fn = make_live_price_fn(state.ws_feed, max_age_sec=60.0)
            pos = state.executor.open(t, opened_at_idx=tick_idx,
                                      opened_at_iso=now_iso,
                                      live_price_fn=live_fn)
            state.open_positions.append(pos)
            opened_count += 1
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
    if state.ks.state == KSState.NORMAL and (priming or dedup_skips or stale_skips or opened_count):
        log.info(
            "SIGNAL scan tick=%d scanned=%d dedup=%d stale=%d opened=%d priming=%s",
            tick_idx, len(all_trades), dedup_skips, stale_skips, opened_count,
            "yes" if priming else "no",
        )
    if state.ks.state == KSState.NORMAL and not state.primed:
        # After a successful first scan, paper is primed — future ticks
        # open positions.
        state.primed = True
        log.info(
            "PAPER PRIMED tick=%d signals_seen=%d stale=%d dedup=%d",
            tick_idx, primed_count, stale_skips, dedup_skips,
        )
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
    # Always emit a per-tick INFO line so `journalctl -u millennium_paper`
    # doesn't look dead on silent ticks. Mirrors shadow's TICK log.
    log.info(
        "TICK ok=%d novel=%d open=%d equity=%.2f dd=%.2f%% ks=%s primed=%s",
        state.ticks_ok, state.novel_since_prime,
        len(state.open_positions), state.account.equity,
        state.account.drawdown_pct, state.ks.state.value,
        "yes" if state.primed else "no",
    )
    _write_heartbeat({
        "run_id": RUN_ID, "status": "running",
        "label": LABEL,
        "started_at": RUN_TS.isoformat(),
        "tick_sec": state.tick_sec, "ticks_ok": state.ticks_ok,
        "ticks_fail": state.ticks_fail,
        "novel_total": state.novel_total,
        "novel_since_prime": state.novel_since_prime,
        "last_scan_scanned": len(all_trades),
        "last_scan_dedup": dedup_skips,
        "last_scan_stale": stale_skips,
        "last_scan_live": live_count,
        "last_scan_opened": opened_count,
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
    # DB live_runs upsert — best-effort; never crashes the tick loop.
    # First call this process: row may or may not exist (fresh run or
    # restart on same RUN_ID).  Check first, split insert vs update —
    # upsert's immutable-on-update guard would raise on restart otherwise,
    # causing _live_runs_initialized to never be set and flooding the log.
    try:
        if not getattr(state, "_live_runs_initialized", False):
            # First call this process: row may or may not exist (fresh run
            # or restart on same RUN_ID). Check first, split insert vs update
            # — upsert's immutable-on-update guard would raise otherwise.
            existing = db_live_runs.get_live_run(RUN_ID)
            if existing is None:
                db_live_runs.upsert(
                    run_id=RUN_ID,
                    engine="millennium",
                    mode="paper",
                    started_at=RUN_TS.isoformat(),
                    run_dir=str(RUN_DIR.relative_to(ROOT)),
                    host=socket.gethostname(),
                    label=LABEL,
                    status="running",
                    tick_count=state.ticks_ok,
                    novel_count=state.novel_total,
                    open_count=len(state.open_positions),
                    equity=round(state.account.equity, 2),
                    last_tick_at=now_iso,
                )
            else:
                db_live_runs.upsert(
                    run_id=RUN_ID,
                    status="running",
                    tick_count=state.ticks_ok,
                    novel_count=state.novel_total,
                    open_count=len(state.open_positions),
                    equity=round(state.account.equity, 2),
                    last_tick_at=now_iso,
                )
            state._live_runs_initialized = True  # type: ignore[attr-defined]
        else:
            db_live_runs.upsert(
                run_id=RUN_ID,
                status="running",
                tick_count=state.ticks_ok,
                novel_count=state.novel_total,
                open_count=len(state.open_positions),
                equity=round(state.account.equity, 2),
                last_tick_at=now_iso,
            )
    except Exception:
        log.exception("db_live_runs upsert failed (tick continues)")


def _write_run_summary(state: RunnerState, stopped_reason: str) -> None:
    metrics = state.metrics.current_metrics()
    summary = {
        "run_id": RUN_ID,
        "mode": "paper",
        "label": LABEL,
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
    _ensure_run_dirs()
    handler = logging.FileHandler(PAPER_LOG, encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(fmt)
    log.addHandler(handler)
    stderr = logging.StreamHandler()
    stderr.setFormatter(fmt)
    log.addHandler(stderr)

    _write_manifest(account_size)

    state = RunnerState(account_size=account_size, tick_sec=tick_sec)

    # Start the Binance futures markPrice WS feed so opens use the live
    # market price at execution time instead of the bar-close open[idx+1]
    # the signal was computed against. Symbols come from config.params —
    # only the trading universe, macro is excluded.
    try:
        from config.params import SYMBOLS as _SYMBOLS
    except Exception:  # noqa: BLE001
        _SYMBOLS = []
    if _SYMBOLS:
        try:
            state.ws_feed = WSPriceFeed(symbols=list(_SYMBOLS))
            state.ws_feed.start()
            log.info("WS price feed started for %d symbols", len(_SYMBOLS))
        except Exception as exc:  # noqa: BLE001
            log.warning("WS price feed start failed: %s — using signal entry",
                        exc)
            state.ws_feed = None

    deadline = time.time() + run_hours * 3600.0 if run_hours > 0 else None
    stop = {"flag": False, "reason": ""}

    def _handle_signal(signum, _frame):
        if stop["flag"]:
            sys.exit(130)
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
            # Sleep in small slices so STOP buttons (drop_kill via cockpit) +
            # SIGINT/SIGTERM are responsive. Mirrors shadow's pattern. Without
            # this, user clicking STOP waits up to tick_sec (15min default)
            # for the runner to notice the .kill flag — feels like the button
            # is broken even though the flag is dropped immediately.
            sliced = 0.0
            while sliced < tick_sec:
                if KILL_FLAG.exists() or stop["flag"]:
                    break
                chunk = min(2.0, tick_sec - sliced)
                time.sleep(chunk)
                sliced += chunk
    finally:
        if state.ws_feed is not None:
            try:
                state.ws_feed.stop()
            except Exception:  # noqa: BLE001
                pass
        _write_run_summary(state, stop["reason"] or "clean_exit")
        # Final DB upsert: mark run as stopped. Pre-check that the row
        # exists — when paper crashes before tick 1 (e.g. SIGTERM at boot,
        # DB table missing and later migrated), the insert-path would fail
        # with "missing required fields" because this call only passes
        # ended_at+status. Skip gracefully instead.
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
        # Also flush heartbeat.json with status=stopped so the filesystem
        # path (/v1/runs in cockpit_api) reports the right status without
        # waiting for the 45min staleness threshold to expire. Without
        # this, /v1/runs consumers kept showing the run as "running" for
        # ~45min after systemctl stop (bug 2026-04-24: 2 citadel_paper
        # rows in launcher when only 1 was actually alive).
        try:
            _write_heartbeat({
                "run_id": RUN_ID, "status": "stopped",
                "label": LABEL, "engine": "millennium",
                "started_at": RUN_TS.isoformat(),
                "tick_sec": state.tick_sec, "ticks_ok": state.ticks_ok,
                "ticks_fail": state.ticks_fail,
                "novel_total": state.novel_total,
                "last_tick_at": state.last_novel_at or datetime.now(timezone.utc).isoformat(),
                "stopped_at": datetime.now(timezone.utc).isoformat(),
                "stopped_reason": stop["reason"] or "clean_exit",
                "mode": "paper",
                "primed": state.primed,
                "account_size": state.account_size,
                "equity": round(state.account.equity, 2),
                "drawdown_pct": round(state.account.drawdown_pct, 3),
                "ks_state": state.ks.state.value,
            })
        except Exception:
            log.exception("final heartbeat write failed")
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
    parser.add_argument("--label", type=str, default=None,
                        help="optional instance label (sanitized to [a-z0-9-], max 40). "
                             "overrides AURUM_PAPER_LABEL env.")
    args = parser.parse_args()
    # CLI --label overrides env-derived LABEL only when explicitly passed.
    # Rebuild paths so manifest/heartbeat/logs land in the labeled RUN_DIR.
    if args.label is not None and sanitize_label(args.label) != LABEL:
        _configure_run(args.label)
    return run_paper(args.tick_sec, args.run_hours, args.account_size)


if __name__ == "__main__":
    sys.exit(main())
