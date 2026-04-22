"""Per-engine paper runner — parametric core shared by citadel/jump/renaissance.

Structure mirrors ``tools/operations/millennium_paper.py`` one-to-one; the only
change is that this module is parametrized on ``ENGINE_NAME`` (read from env
at import time) and filters the shared MILLENNIUM signal collector to the
one engine, so each engine gets its own isolated paper account + data dir:

    data/{engine}_paper/<run_id>/{logs,reports,state}/

MILLENNIUM's own paper runner stays untouched. These engine-specific runners
are meant to run *alongside* it so we can cross-check that MILLENNIUM's
per-engine signals match what the solo runner produces for the same candles.

Entry scripts: ``tools/operations/{citadel,jump,renaissance}_paper.py``.
They set ``AURUM_ENGINE_NAME`` and delegate here.

Usage (typical — via entry script):
    python tools/operations/citadel_paper.py \\
        --account-size 10000 --tick-sec 900 --run-hours 0

Direct usage (debugging only):
    AURUM_ENGINE_NAME=citadel python tools/operations/_paper_runner.py \\
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
    ClosedTrade,
)
from tools.operations.paper_ks_gate import KSLiveGate, KSState  # noqa: E402
from tools.operations.paper_metrics import MetricsStreamer  # noqa: E402
from tools.operations.run_id import build_run_id, sanitize_label  # noqa: E402

# ─── Engine parametrization ──────────────────────────────────────
# ENGINE_NAME is read from env at import. Entry scripts set it before
# importing this module. Defaults to "citadel" for manual debugging.
ENGINE_NAME = os.environ.get("AURUM_ENGINE_NAME", "citadel").lower()
ENGINE_UPPER = ENGINE_NAME.upper()

RUN_TS = datetime.now(timezone.utc)
LABEL: str | None = sanitize_label(
    os.environ.get(f"AURUM_{ENGINE_UPPER}_PAPER_LABEL")
    or os.environ.get("AURUM_PAPER_LABEL")
)
RUN_ID = build_run_id(RUN_TS, LABEL, mode="paper")
RUN_DIR = ROOT / "data" / f"{ENGINE_NAME}_paper" / RUN_ID
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


def _ensure_run_dirs() -> None:
    for _d in (LOGS_DIR, REPORTS_DIR, STATE_DIR):
        _d.mkdir(parents=True, exist_ok=True)


def _configure_run(label: str | None) -> None:
    """Re-point module-level paths at a new RUN_ID built from ``label``.

    Called from main() after argparse when --label differs from the
    env-derived LABEL. Rebuilds RUN_ID, RUN_DIR and every path global.
    """
    global LABEL, RUN_ID, RUN_DIR, LOGS_DIR, REPORTS_DIR, STATE_DIR
    global PAPER_LOG, TRADES_PATH, EQUITY_PATH, FILLS_PATH, SIGNALS_PATH
    global POSITIONS_PATH, ACCOUNT_PATH, HEARTBEAT_PATH, MANIFEST_PATH
    global KILL_FLAG
    LABEL = sanitize_label(label)
    RUN_ID = build_run_id(RUN_TS, LABEL, mode="paper")
    RUN_DIR = ROOT / "data" / f"{ENGINE_NAME}_paper" / RUN_ID
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

log = logging.getLogger(f"{ENGINE_NAME}_paper")
log.setLevel(logging.INFO)


# Telegram (copy-adapted from millennium; silent fallback)
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
        "run_id": RUN_ID, "engine": ENGINE_NAME, "mode": "paper",
        "label": LABEL,
        "started_at": RUN_TS.isoformat(),
        "commit": commit, "branch": branch,
        "config_hash": compute_config_hash(),
        "host": socket.gethostname(),
        "python_version": sys.version.split()[0],
        "account_size": account_size,
    }
    atomic_write(MANIFEST_PATH, json.dumps(payload, indent=2))


# ── Engine-native scan config ────────────────────────────────────
# Pre 2026-04-22 22:00: delegava pra MILLENNIUM._collect_live_signals, que
# usa shared INTERVAL=15m + default SYMBOLS (all altcoins, no BTC/ETH).
# Isso significava que:
#   - CITADEL live MATCH backtest (15m + default)
#   - JUMP    live = 15m default, backtest = 1h bluechip → SIGNAL MISMATCH
#   - RENAIS  live = 15m default, backtest = 15m bluechip → BASKET MISMATCH
#
# Agora cada runner faz seu proprio fetch com TF + basket NATIVOS do
# ENGINE_INTERVALS/ENGINE_BASKETS, e chama a scan fn nativa diretamente.
# Assim os sinais ao vivo batem com a calibracao do backtest validado.
def _resolve_engine_scan_config():
    """Returns (engine_tf, engine_symbols, n_candles, scan_fn)."""
    from config.params import (
        ENGINE_INTERVALS, ENGINE_BASKETS, BASKETS, SYMBOLS as DEFAULT_SYMBOLS,
        SCAN_DAYS,
    )
    tf = ENGINE_INTERVALS.get(ENGINE_UPPER, "15m")
    basket_name = ENGINE_BASKETS.get(ENGINE_UPPER, "default")
    if basket_name == "default" or basket_name not in BASKETS:
        symbols = list(DEFAULT_SYMBOLS)
    else:
        symbols = list(BASKETS[basket_name])
    # Candles per day varies by TF: 15m=96, 1h=24, 4h=6, 1d=1
    bars_per_day = {
        "5m": 288, "15m": 96, "30m": 48, "1h": 24,
        "2h": 12, "4h": 6, "6h": 4, "12h": 2, "1d": 1,
    }.get(tf, 24)
    n_candles = SCAN_DAYS * bars_per_day
    # Dispatch to engine scan fn
    if ENGINE_NAME == "citadel":
        from engines.citadel import scan_symbol as scan_fn
    elif ENGINE_NAME == "jump":
        from engines.jump import scan_mercurio as scan_fn
    elif ENGINE_NAME == "renaissance":
        from core.harmonics import scan_hermes as scan_fn
    else:
        raise RuntimeError(f"no scan fn for engine {ENGINE_NAME!r}")
    return tf, symbols, n_candles, scan_fn


def _scan_new_signals(notify: bool = True) -> list[dict]:
    """Scan para ESTE engine, com TF + basket nativos do backtest validado.

    Fluxo:
      1. Fetch OHLCV no TF nativo do engine (via ENGINE_INTERVALS)
      2. Pro basket nativo (via ENGINE_BASKETS → BASKETS)
      3. Macro + corr computados no mesmo set
      4. Chama a scan fn nativa do engine (azoth_scan / scan_mercurio /
         scan_hermes) com live_mode=True
      5. Stamp strategy=ENGINE_UPPER, retorna lista de trades

    Garante que signals live batem com os signals do backtest OOS-validado.
    """
    from core.data import fetch_all, validate
    from core.portfolio import detect_macro, build_corr_matrix
    from config.params import MACRO_SYMBOL

    tf, engine_symbols, n_candles, scan_fn = _resolve_engine_scan_config()

    # Fetch: engine symbols + macro symbol (for regime detection)
    fetch_syms = list(engine_symbols)
    if MACRO_SYMBOL and MACRO_SYMBOL not in fetch_syms:
        fetch_syms.insert(0, MACRO_SYMBOL)

    with contextlib.redirect_stdout(io.StringIO()):
        all_dfs = fetch_all(fetch_syms, interval=tf, n_candles=n_candles)
        for sym, df in all_dfs.items():
            validate(df, sym)
        if not all_dfs:
            return []
        macro_series = detect_macro(all_dfs)
        corr = build_corr_matrix(all_dfs)

    trades: list = []
    with contextlib.redirect_stdout(io.StringIO()):
        for sym, df in all_dfs.items():
            if sym not in engine_symbols:
                continue
            t, _vetos = scan_fn(
                df if ENGINE_NAME != "jump" else df.copy(),
                sym, macro_series, corr, None,
                live_mode=True,
            )
            for tt in t:
                tt["strategy"] = ENGINE_UPPER
                if ENGINE_NAME == "citadel":
                    tt.setdefault("confirmed", False)
            trades.extend(t)
    return trades


def _fetch_new_bars(symbol: str, since_iso: str | None) -> list[dict]:
    """Fetch OHLCV bars newer than since_iso for symbol."""
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
    return is_live_signal(trade, tick_sec=tick_sec, tolerance_mult=tolerance_mult)


def _flatten_all(state: RunnerState, reason: str, notify: bool) -> None:
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
            f"<b>{ENGINE_UPPER} paper flatten</b> ({reason}) · "
            f"equity ${state.account.equity:,.2f}"
        )


def run_one_tick(state: RunnerState, tick_idx: int, notify: bool = True) -> None:
    """Execute one tick: check exits on open, fetch signals, open new."""
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
                    f"<b>{ENGINE_UPPER} paper · {c.symbol}</b> · {c.exit_reason.upper()}\n"
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
                f"<b>⚠ KS FAST HALT · {ENGINE_UPPER}</b> · paper run halted\n"
                f"equity ${state.account.equity:,.2f} · "
                f"dd ${state.account.drawdown:.2f}"
            )

    # 3. Signal discovery (skip if KS halted)
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
        for t in all_trades:
            key = _trade_key(t)
            if key in state.seen_keys:
                dedup_skips += 1
                continue
            state.seen_keys.add(key)

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

            # Portfolio gate V2: direction conflict check. Single-engine
            # runners rarely hit this (same engine seldom emits opposite
            # directions on the same symbol at the same tick), but the
            # rule is portfolio-level and still applies for consistency.
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
                    f"<b>{ENGINE_UPPER} paper · {pos.direction} {pos.symbol}</b>\n"
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
        state.primed = True
        log.info(
            "%s PAPER PRIMED tick=%d signals_seen=%d stale=%d dedup=%d",
            ENGINE_UPPER, tick_idx, primed_count, stale_skips, dedup_skips,
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
        "engine": ENGINE_NAME,
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
    try:
        if not getattr(state, "_live_runs_initialized", False):
            existing = db_live_runs.get_live_run(RUN_ID)
            if existing is None:
                db_live_runs.upsert(
                    run_id=RUN_ID,
                    engine=ENGINE_NAME,
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
        "engine": ENGINE_NAME,
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
        stop["flag"] = True
        stop["reason"] = f"signal {signum}"

    os_signal.signal(os_signal.SIGINT, _handle_signal)
    with contextlib.suppress(AttributeError, ValueError):
        os_signal.signal(os_signal.SIGTERM, _handle_signal)

    log.info("%s PAPER START run=%s account=%.2f tick=%ds hours=%.1f",
             ENGINE_UPPER, RUN_ID, account_size, tick_sec, run_hours)
    _tg_send(
        f"<b>{ENGINE_UPPER} paper START</b>\n"
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
        # exists — when paper crashes before tick 1, the insert-path would
        # fail because this call only passes ended_at+status.
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
        _tg_send(
            f"<b>{ENGINE_UPPER} paper STOP</b>\n"
            f"equity ${state.account.equity:,.2f} · "
            f"roi {state.metrics.current_metrics()['roi_pct']:+.2f}%"
        )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"{ENGINE_UPPER} paper runner (per-engine, parallel to MILLENNIUM)"
    )
    parser.add_argument("--account-size", type=float,
                        default=float(os.environ.get(
                            f"AURUM_{ENGINE_UPPER}_PAPER_ACCOUNT_SIZE",
                            os.environ.get("AURUM_PAPER_ACCOUNT_SIZE", 10_000.0),
                        )))
    parser.add_argument("--tick-sec", type=int, default=900)
    parser.add_argument("--run-hours", type=float, default=0.0)
    parser.add_argument("--label", type=str, default=None,
                        help="optional instance label (sanitized to [a-z0-9-], "
                             f"max 40). overrides AURUM_{ENGINE_UPPER}_PAPER_LABEL env.")
    args = parser.parse_args()
    if args.label is not None and sanitize_label(args.label) != LABEL:
        _configure_run(args.label)
    return run_paper(args.tick_sec, args.run_hours, args.account_size)


if __name__ == "__main__":
    raise SystemExit(main())
