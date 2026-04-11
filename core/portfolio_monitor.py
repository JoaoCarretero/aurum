"""
☿ AURUM Finance — Portfolio Monitor
=====================================
Unified data layer for the dashboard's PORTFOLIO / TRADES / ENGINES tabs.

For TESTNET / DEMO / LIVE accounts: wraps BinanceFuturesAPI to fetch
balance / equity / positions / recent trades / income history.

For the PAPER account: reads the most recent backtest run from data/runs/
via data/index.json — gives the dashboard a "last simulated portfolio"
view that always works without API keys.

Thread-safe: refresh() can be called from worker threads, get_cached() and
status() return atomic snapshots for the UI thread.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.exchange_api import BinanceFuturesAPI, make_client


# Account modes that map to Binance environments.
LIVE_MODES = ("testnet", "demo", "live")


class PortfolioMonitor:
    """Caches per-account snapshots and exposes simple read APIs."""

    def __init__(self,
                 keys_path: str | Path = "config/keys.json",
                 data_dir: str | Path = "data"):
        self.keys_path = Path(keys_path)
        self.data_dir = Path(data_dir)
        self._cache: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ── KEY DETECTION ─────────────────────────────────────────
    def has_keys(self, mode: str) -> bool:
        """Return True if the account is usable:
        - Paper mode is always usable (local file, no API keys needed).
        - Live/demo/testnet need a valid config/keys.json entry."""
        if mode == "paper":
            return True
        if not self.keys_path.exists():
            return False
        try:
            cfg = json.loads(self.keys_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        block = cfg.get(mode) or {}
        k = block.get("api_key", "")
        s = block.get("api_secret", "")
        return bool(k and s and "COLE_AQUI" not in k)

    def status(self, mode: str) -> str:
        """Return one of: 'live', 'no_keys', 'paper'."""
        if mode == "paper":
            return "paper"
        if self.has_keys(mode):
            return "live"
        return "no_keys"

    # ── REFRESH (live accounts) ───────────────────────────────
    def refresh(self, mode: str) -> dict:
        """
        Pull a fresh snapshot for *mode*. Safe to call from a worker thread.
        Stores the result in the cache and returns it.
        """
        if mode == "paper":
            data = self._load_paper()
            with self._lock:
                self._cache[mode] = data
            return data

        if not self.has_keys(mode):
            data = {
                "mode":     mode,
                "status":   "no_keys",
                "ts":       datetime.now().isoformat(),
                "error":    "No API keys configured.",
                "balance":  0.0,
                "equity":   0.0,
                "positions": [],
                "recent_trades": [],
            }
            with self._lock:
                self._cache[mode] = data
            return data

        client = make_client(mode, str(self.keys_path))
        if client is None:
            data = {
                "mode":     mode,
                "status":   "no_keys",
                "ts":       datetime.now().isoformat(),
                "error":    "Could not build client.",
                "balance":  0.0,
                "equity":   0.0,
                "positions": [],
                "recent_trades": [],
            }
            with self._lock:
                self._cache[mode] = data
            return data

        snapshot = self._fetch_account_snapshot(client, mode)
        with self._lock:
            self._cache[mode] = snapshot
        return snapshot

    def _fetch_account_snapshot(self, client: BinanceFuturesAPI, mode: str) -> dict:
        """Combine balance + account + positions into a unified dict.
        The 4 independent calls (account/balance/positions/income) run in
        parallel threads — reduces latency from ~5× call-time to ~1× call-time."""
        out: dict = {
            "mode":     mode,
            "status":   "live",
            "ts":       datetime.now().isoformat(),
            "error":    None,
            "balance":  0.0,
            "equity":   0.0,
            "margin_used": 0.0,
            "margin_free": 0.0,
            "unrealized_pnl": 0.0,
            "today_pnl": 0.0,
            "positions": [],
            "recent_trades": [],
            "income_7d": [],
        }
        results: dict = {}

        def fetch_account():
            try: results["acct"] = client.account()
            except Exception: results["acct"] = None
        def fetch_balance():
            try: results["bal"] = client.balance()
            except Exception: results["bal"] = None
        def fetch_positions():
            try: results["pos"] = client.positions()
            except Exception: results["pos"] = None
        def fetch_income():
            try: results["inc"] = client.income_history(days=7)
            except Exception: results["inc"] = None

        workers = [
            threading.Thread(target=fetch_account,   daemon=True),
            threading.Thread(target=fetch_balance,   daemon=True),
            threading.Thread(target=fetch_positions, daemon=True),
            threading.Thread(target=fetch_income,    daemon=True),
        ]
        for w in workers: w.start()
        for w in workers: w.join(timeout=12)

        acct = results.get("acct")
        if isinstance(acct, dict):
            try:
                out["equity"] = float(acct.get("totalWalletBalance", 0) or 0)
                out["balance"] = float(acct.get("availableBalance", 0) or 0)
                out["margin_used"] = float(acct.get("totalInitialMargin", 0) or 0)
                out["margin_free"] = float(acct.get("availableBalance", 0) or 0)
                out["unrealized_pnl"] = float(acct.get("totalUnrealizedProfit", 0) or 0)
            except (TypeError, ValueError):
                pass
            if acct.get("code"):
                out["error"] = f"Binance: {acct.get('msg', acct.get('code'))}"

        bals = results.get("bal")
        if isinstance(bals, list) and not out["equity"]:
            usdt = next((b for b in bals if isinstance(b, dict) and b.get("asset") == "USDT"), None)
            if usdt:
                try:
                    out["balance"] = float(usdt.get("balance", 0) or 0)
                    out["equity"]  = float(usdt.get("balance", 0) or 0) + float(usdt.get("crossUnPnl", 0) or 0)
                    out["unrealized_pnl"] = float(usdt.get("crossUnPnl", 0) or 0)
                except (TypeError, ValueError):
                    pass

        positions = results.get("pos")
        if isinstance(positions, list):
            out["positions"] = self._normalise_positions(positions)

        income = results.get("inc")
        if isinstance(income, list):
            out["income_7d"] = income
            today_iso = datetime.now().date().isoformat()
            today_sum = 0.0
            for row in income:
                try:
                    ts_ms = int(row.get("time", 0))
                    if datetime.fromtimestamp(ts_ms / 1000).date().isoformat() == today_iso:
                        today_sum += float(row.get("income", 0) or 0)
                except (TypeError, ValueError):
                    continue
            out["today_pnl"] = round(today_sum, 2)

        # Recent trades: depends on positions, so run after join.
        # Parallelize across open-position symbols.
        open_syms = [p.get("symbol") for p in out["positions"][:5] if p.get("symbol")]
        trades_per_sym: dict[str, list] = {}

        def fetch_trades(sym):
            try:
                t = client.recent_trades(symbol=sym, limit=10)
                if isinstance(t, list):
                    trades_per_sym[sym] = t
            except Exception:
                trades_per_sym[sym] = []

        if open_syms:
            trade_workers = [threading.Thread(target=fetch_trades, args=(s,), daemon=True)
                             for s in open_syms]
            for w in trade_workers: w.start()
            for w in trade_workers: w.join(timeout=8)

            recent: list[dict] = []
            for sym, trades in trades_per_sym.items():
                for t in trades:
                    t["symbol"] = sym
                    recent.append(t)
            recent.sort(key=lambda r: int(r.get("time", 0) or 0), reverse=True)
            out["recent_trades"] = recent[:50]

        return out

    @staticmethod
    def _normalise_positions(raw: list[dict]) -> list[dict]:
        """Project Binance positionRisk rows into a UI-friendly shape."""
        out = []
        for p in raw:
            try:
                amt = float(p.get("positionAmt", 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            if amt == 0:
                continue
            try:
                entry = float(p.get("entryPrice", 0) or 0)
                mark  = float(p.get("markPrice", 0) or 0)
                pnl   = float(p.get("unRealizedProfit", 0) or 0)
                lev   = float(p.get("leverage", 0) or 0)
            except (TypeError, ValueError):
                entry = mark = pnl = lev = 0.0
            out.append({
                "symbol":   p.get("symbol", "?"),
                "side":     "LONG" if amt > 0 else "SHORT",
                "size":     abs(amt),
                "entry":    entry,
                "mark":     mark,
                "pnl":      pnl,
                "leverage": lev,
            })
        return out

    # ── PAPER STATE (editable persistent file) ────────────────
    PAPER_STATE_FILE = Path("config/paper_state.json")
    PAPER_DEFAULT_BALANCE = 10000.0
    # Class-level lock: every read/modify/write of paper_state.json goes
    # through this, protecting the file from concurrent mutations.
    _PAPER_LOCK = threading.Lock()

    @classmethod
    def _paper_default_state(cls) -> dict:
        now = datetime.now().isoformat()
        return {
            "initial_balance":  cls.PAPER_DEFAULT_BALANCE,
            "current_balance":  cls.PAPER_DEFAULT_BALANCE,
            "equity":           cls.PAPER_DEFAULT_BALANCE,
            "realized_pnl":     0.0,
            "unrealized_pnl":   0.0,
            "total_deposits":   cls.PAPER_DEFAULT_BALANCE,
            "total_withdraws":  0.0,
            "positions":        [],
            "trades":           [],
            "equity_curve":     [cls.PAPER_DEFAULT_BALANCE],
            "history": [
                {"ts": now, "type": "init",
                 "amount": cls.PAPER_DEFAULT_BALANCE,
                 "note": "paper account created"}
            ],
            "created":          now,
            "last_modified":    now,
        }

    @classmethod
    def _paper_read_unlocked(cls) -> dict | None:
        """Read the file without acquiring the lock. Caller must hold it."""
        f = cls.PAPER_STATE_FILE
        if not f.exists():
            return None
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return None

    @classmethod
    def _paper_write_unlocked(cls, state: dict) -> None:
        """Atomic write: tmp file + rename. Caller must hold the lock."""
        f = cls.PAPER_STATE_FILE
        f.parent.mkdir(parents=True, exist_ok=True)
        state["last_modified"] = datetime.now().isoformat()
        tmp = f.with_suffix(f.suffix + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        tmp.replace(f)  # atomic rename on both POSIX and Windows

    @classmethod
    def paper_state_load(cls) -> dict:
        """Read config/paper_state.json, create with defaults if missing.
        Thread-safe — the entire load-or-init is atomic."""
        with cls._PAPER_LOCK:
            state = cls._paper_read_unlocked()
            if state is None:
                state = cls._paper_default_state()
                cls._paper_write_unlocked(state)
            return state

    @classmethod
    def paper_state_save(cls, state: dict) -> None:
        """Thread-safe atomic write."""
        with cls._PAPER_LOCK:
            cls._paper_write_unlocked(state)

    @classmethod
    def paper_set_balance(cls, amount: float, note: str = "manual adjust") -> dict:
        """Thread-safe read-modify-write. Holds the lock for the entire op."""
        with cls._PAPER_LOCK:
            state = cls._paper_read_unlocked() or cls._paper_default_state()
            delta = float(amount) - float(state.get("current_balance", 0) or 0)
            state["current_balance"] = float(amount)
            state["equity"]          = float(amount) + float(state.get("unrealized_pnl", 0) or 0)
            if delta > 0:
                state["total_deposits"]  = float(state.get("total_deposits", 0) or 0) + delta
                event_type = "deposit"
            elif delta < 0:
                state["total_withdraws"] = float(state.get("total_withdraws", 0) or 0) + abs(delta)
                event_type = "withdraw"
            else:
                event_type = "adjust"
            state.setdefault("history", []).append({
                "ts": datetime.now().isoformat(),
                "type": event_type,
                "amount": delta,
                "new_balance": float(amount),
                "note": note,
            })
            state.setdefault("equity_curve", []).append(float(amount))
            cls._paper_write_unlocked(state)
            return state

    @classmethod
    def paper_reset(cls) -> dict:
        """Thread-safe reset to default state."""
        with cls._PAPER_LOCK:
            state = cls._paper_default_state()
            cls._paper_write_unlocked(state)
            return state

    def _load_paper(self) -> dict:
        """Build a 'paper' account snapshot from the persistent paper_state.json
        file. The file is the source of truth — editable via the dashboard."""
        state = self.paper_state_load()

        out: dict = {
            "mode":           "paper",
            "status":         "paper",
            "ts":             datetime.now().isoformat(),
            "error":          None,
            "balance":        float(state.get("current_balance", 0) or 0),
            "equity":         float(state.get("equity", state.get("current_balance", 0)) or 0),
            "margin_used":    0.0,
            "margin_free":    float(state.get("current_balance", 0) or 0),
            "unrealized_pnl": float(state.get("unrealized_pnl", 0) or 0),
            "today_pnl":      0.0,
            "positions":      state.get("positions") or [],
            "recent_trades":  list(reversed((state.get("trades") or [])[-50:])),
            "trades":         state.get("trades") or [],
            "equity_curve":   state.get("equity_curve") or [],
            "history":        state.get("history") or [],
            "initial_balance":  float(state.get("initial_balance", 0) or 0),
            "total_deposits":   float(state.get("total_deposits", 0) or 0),
            "total_withdraws":  float(state.get("total_withdraws", 0) or 0),
            "realized_pnl":     float(state.get("realized_pnl", 0) or 0),
            "summary": {
                "n_trades":   len(state.get("trades") or []),
                "pnl":        float(state.get("realized_pnl", 0) or 0),
                "final_equity": float(state.get("equity", 0) or 0),
            },
            "created":        state.get("created"),
            "last_modified":  state.get("last_modified"),
        }

        # today_pnl from history entries of today
        today = datetime.now().date().isoformat()
        for h in out["history"]:
            ts = str(h.get("ts", ""))
            if ts.startswith(today) and h.get("type") in ("trade", "realized_pnl"):
                try:
                    out["today_pnl"] += float(h.get("amount", 0) or 0)
                except (TypeError, ValueError):
                    pass

        return out

    # ── CACHE ACCESS ──────────────────────────────────────────
    def get_cached(self, mode: str) -> Optional[dict]:
        with self._lock:
            return self._cache.get(mode)

    def all_cached(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._cache)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
