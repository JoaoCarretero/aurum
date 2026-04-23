"""
AURUM Finance — SimpleArbEngine
================================
In-process paper arbitrage engine for the hub. Replaces the JANE STREET
subprocess for paper mode — runs inside the launcher Tk event loop via
periodic tick() calls from the scanner refresh callback.

Scope (MVP):
  - FUNDING cross-venue arbitrage only (from `FundingScanner.arb_pairs()`)
  - Paper-only (no real place_order)
  - Delta-neutral assumption: MTM ≈ 0, PnL = funding_accrued - fees
  - Exits on decay | flip | max_hold | kill_switch

Out of scope for MVP (left to JANE STREET subprocess if needed):
  - BASIS / SPOT_ARB opp types
  - Depth/latency/adversarial detection
  - Live execution / audit trail
  - Multi-leg hedge monitoring

Interaction with UI:
  - Launcher creates SimpleArbEngine on START, calls tick(opps) each
    scan cycle (15s default), reads snapshot() for gauges.
  - State persisted to data/arb_hub/state.json on each tick so the UI
    can survive launcher restart (load() to restore).
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_STATE_PATH = ROOT / "data" / "arb_hub" / "state.json"

# ── Defaults (can be overridden via __init__) ────────────────────────
ACCOUNT_DEFAULT = 5000.0
MAX_POS_DEFAULT = 3
SIZE_USD_DEFAULT = 1000.0
MIN_APR_DEFAULT = 20.0               # %
MIN_VOL_DEFAULT = 1_000_000.0        # USD 24h volume (min of both legs)
MAX_HOLD_H_DEFAULT = 72.0
EXIT_DECAY_RATIO_DEFAULT = 0.30      # exit if current_apr / entry_apr < this
KILL_DD_PCT_DEFAULT = 10.0
ENTRY_FEE_BPS_DEFAULT = 10.0         # 0.10% total round-trip (both legs)
SLIPPAGE_BPS_DEFAULT = 5.0           # 0.05% total round-trip


class SimpleArbEngine:
    """Paper arbitrage engine running inside the hub."""

    def __init__(
        self,
        *,
        account: float = ACCOUNT_DEFAULT,
        max_pos: int = MAX_POS_DEFAULT,
        size_usd: float = SIZE_USD_DEFAULT,
        min_apr: float = MIN_APR_DEFAULT,
        min_vol: float = MIN_VOL_DEFAULT,
        max_hold_h: float = MAX_HOLD_H_DEFAULT,
        exit_decay_ratio: float = EXIT_DECAY_RATIO_DEFAULT,
        kill_dd_pct: float = KILL_DD_PCT_DEFAULT,
        entry_fee_bps: float = ENTRY_FEE_BPS_DEFAULT,
        slippage_bps: float = SLIPPAGE_BPS_DEFAULT,
        state_path: Path | str | None = None,
    ):
        self.account_initial = float(account)
        self.account = float(account)
        self.peak = float(account)
        self.max_pos = int(max_pos)
        self.size_usd = float(size_usd)
        self.min_apr = float(min_apr)
        self.min_vol = float(min_vol)
        self.max_hold_h = float(max_hold_h)
        self.exit_decay_ratio = float(exit_decay_ratio)
        self.kill_dd_pct = float(kill_dd_pct)
        self.entry_fee_bps = float(entry_fee_bps)
        self.slippage_bps = float(slippage_bps)
        self.state_path = Path(state_path) if state_path else DEFAULT_STATE_PATH

        self.running: bool = False
        self.mode: str | None = None
        self.killed: bool = False
        self.positions: list[dict] = []
        self.closed: list[dict] = []
        self.losses_streak: int = 0
        self.last_tick_ts: float = 0.0
        self.started_ts: float = 0.0

    # ── Lifecycle ────────────────────────────────────────────────

    def start(self, mode: str = "paper") -> None:
        if self.running:
            return
        self.running = True
        self.mode = mode
        self.killed = False
        self.started_ts = time.time()
        self._persist()

    def stop(self) -> None:
        if not self.running:
            return
        # Force-close all open positions as "manual"
        now = time.time()
        for pos in list(self.positions):
            self._close(pos, reason="manual", now=now)
        self.running = False
        self._persist()

    # ── Main tick — called every scan cycle ──────────────────────

    def tick(self, opps: list[dict], now: float | None = None) -> None:
        """Process open positions + consider new opps.

        ``opps`` is a list of dicts from FundingScanner.arb_pairs()
        (shape: {symbol, short_venue, long_venue, net_apr, mark_price,
        volume_short, volume_long, ...}).
        """
        if not self.running:
            return
        now = float(now) if now is not None else time.time()
        self.last_tick_ts = now

        # Track symbols closed in THIS tick — prevents same-tick reentry
        # (avoids thrashing when a position just decayed out).
        just_closed: set[str] = set()

        # 1. Update open positions — accrue funding + check exits
        opps_by_symbol = {o["symbol"]: o for o in opps}
        for pos in list(self.positions):
            self._refresh_position(pos, opps_by_symbol.get(pos["symbol"]), now)
            reason = self._should_exit(pos, now)
            if reason:
                just_closed.add(pos["symbol"])
                self._close(pos, reason, now)

        # 2. Risk gate — drawdown kill switch
        dd_pct = (self.peak - self.account) / max(self.peak, 1.0) * 100.0
        if dd_pct >= self.kill_dd_pct:
            self.killed = True
            for pos in list(self.positions):
                just_closed.add(pos["symbol"])
                self._close(pos, "kill", now)

        # 3. If not killed and below max_pos, open new positions
        if not self.killed and len(self.positions) < self.max_pos:
            open_symbols = {p["symbol"] for p in self.positions} | just_closed
            ranked = sorted(opps, key=lambda o: abs(o.get("net_apr", 0)), reverse=True)
            for opp in ranked:
                if len(self.positions) >= self.max_pos:
                    break
                if opp["symbol"] in open_symbols:
                    continue
                if abs(opp.get("net_apr", 0)) < self.min_apr:
                    continue
                vol = min(opp.get("volume_short", 0), opp.get("volume_long", 0))
                if vol < self.min_vol:
                    continue
                self._open(opp, now)
                open_symbols.add(opp["symbol"])

        self._persist()

    # ── Internal: open/close/refresh ─────────────────────────────

    def _open(self, opp: dict, now: float) -> None:
        fee_usd = self.size_usd * (self.entry_fee_bps + self.slippage_bps) / 10_000.0
        pos = {
            "id": uuid.uuid4().hex[:12],
            "type": "FUNDING",
            "symbol": opp["symbol"],
            "venue_long": opp.get("long_venue", ""),
            "venue_short": opp.get("short_venue", ""),
            "entry_ts": now,
            "entry_apr": float(opp.get("net_apr", 0)),
            "current_apr": float(opp.get("net_apr", 0)),
            "size_usd": self.size_usd,
            "mark_price": float(opp.get("mark_price", 0)),
            "funding_accrued": 0.0,
            "fees_paid": round(fee_usd, 4),
            "hours_open": 0.0,
        }
        self.account -= fee_usd
        self.positions.append(pos)

    def _refresh_position(self, pos: dict, opp: dict | None, now: float) -> None:
        """Update funding accrual + current_apr + hours_open."""
        dt_h = (now - pos["entry_ts"] - (pos["hours_open"] * 3600.0)) / 3600.0
        if dt_h > 0:
            # Funding per hour = (apr/100 / (365*24)) * size_usd
            accrual = pos["entry_apr"] / 100.0 / (365.0 * 24.0) * pos["size_usd"] * dt_h
            pos["funding_accrued"] += accrual
        pos["hours_open"] = (now - pos["entry_ts"]) / 3600.0
        if opp is not None:
            pos["current_apr"] = float(opp.get("net_apr", pos["current_apr"]))

    def _should_exit(self, pos: dict, now: float) -> str | None:
        if pos["hours_open"] >= self.max_hold_h:
            return "max_hold"
        entry = pos["entry_apr"]
        current = pos["current_apr"]
        # Flip: spread changed sign — edge gone
        if entry > 0 and current < 0:
            return "flip"
        if entry < 0 and current > 0:
            return "flip"
        # Decay: spread collapsed below the threshold
        if abs(entry) > 0 and abs(current) / abs(entry) < self.exit_decay_ratio:
            return "decay"
        return None

    def _close(self, pos: dict, reason: str, now: float) -> None:
        exit_fee = pos["size_usd"] * (self.entry_fee_bps + self.slippage_bps) / 10_000.0
        pnl = pos["funding_accrued"] - pos["fees_paid"] - exit_fee
        self.account += pos["funding_accrued"] - exit_fee  # entry fee already deducted
        if self.account > self.peak:
            self.peak = self.account
        if pnl < 0:
            self.losses_streak += 1
        else:
            self.losses_streak = 0
        closed = dict(pos)
        closed.update({
            "exit_ts": now,
            "exit_reason": reason,
            "pnl": round(pnl, 4),
        })
        self.closed.append(closed)
        self.positions.remove(pos)

    # ── Snapshot / persistence ───────────────────────────────────

    def snapshot(self) -> dict:
        realized = round(sum(c["pnl"] for c in self.closed), 4)
        unrealized = round(sum(p["funding_accrued"] - p["fees_paid"]
                               for p in self.positions), 4)
        exposure = round(sum(p["size_usd"] for p in self.positions), 2)
        dd_pct = (self.peak - self.account) / max(self.peak, 1.0) * 100.0
        return {
            "mode": self.mode,
            "running": self.running,
            "killed": self.killed,
            "account": round(self.account, 4),
            "peak": round(self.peak, 4),
            "drawdown_pct": round(dd_pct, 3),
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "exposure_usd": exposure,
            "losses_streak": self.losses_streak,
            "trades_count": len(self.closed) + len(self.positions),
            "positions": list(self.positions),
            "closed_recent": self.closed[-10:],
            "ts": self.last_tick_ts or time.time(),
            "started_ts": self.started_ts,
        }

    def _persist(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "mode": self.mode,
            "running": self.running,
            "killed": self.killed,
            "account": self.account,
            "account_initial": self.account_initial,
            "peak": self.peak,
            "losses_streak": self.losses_streak,
            "last_tick_ts": self.last_tick_ts,
            "started_ts": self.started_ts,
            "positions": self.positions,
            "closed": self.closed,
            "config": {
                "max_pos": self.max_pos,
                "size_usd": self.size_usd,
                "min_apr": self.min_apr,
                "min_vol": self.min_vol,
                "max_hold_h": self.max_hold_h,
                "exit_decay_ratio": self.exit_decay_ratio,
                "kill_dd_pct": self.kill_dd_pct,
                "entry_fee_bps": self.entry_fee_bps,
                "slippage_bps": self.slippage_bps,
            },
        }
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        tmp.replace(self.state_path)

    @classmethod
    def load(cls, state_path: Path | str) -> SimpleArbEngine:
        path = Path(state_path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        cfg = raw.get("config", {})
        e = cls(
            account=raw.get("account_initial", ACCOUNT_DEFAULT),
            max_pos=cfg.get("max_pos", MAX_POS_DEFAULT),
            size_usd=cfg.get("size_usd", SIZE_USD_DEFAULT),
            min_apr=cfg.get("min_apr", MIN_APR_DEFAULT),
            min_vol=cfg.get("min_vol", MIN_VOL_DEFAULT),
            max_hold_h=cfg.get("max_hold_h", MAX_HOLD_H_DEFAULT),
            exit_decay_ratio=cfg.get("exit_decay_ratio", EXIT_DECAY_RATIO_DEFAULT),
            kill_dd_pct=cfg.get("kill_dd_pct", KILL_DD_PCT_DEFAULT),
            entry_fee_bps=cfg.get("entry_fee_bps", ENTRY_FEE_BPS_DEFAULT),
            slippage_bps=cfg.get("slippage_bps", SLIPPAGE_BPS_DEFAULT),
            state_path=state_path,
        )
        e.running = bool(raw.get("running", False))
        e.mode = raw.get("mode")
        e.killed = bool(raw.get("killed", False))
        e.account = float(raw.get("account", e.account))
        e.peak = float(raw.get("peak", e.peak))
        e.losses_streak = int(raw.get("losses_streak", 0))
        e.last_tick_ts = float(raw.get("last_tick_ts", 0.0))
        e.started_ts = float(raw.get("started_ts", 0.0))
        e.positions = list(raw.get("positions", []))
        e.closed = list(raw.get("closed", []))
        return e
