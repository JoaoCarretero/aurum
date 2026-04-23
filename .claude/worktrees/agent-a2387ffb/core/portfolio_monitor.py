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
        """Return True if config/keys.json has a usable block for *mode*."""
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
        """Combine balance + account + positions into a unified dict."""
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

        acct = client.account()
        if isinstance(acct, dict):
            try:
                out["equity"] = float(acct.get("totalWalletBalance", 0) or 0)
                out["balance"] = float(acct.get("availableBalance", 0) or 0)
                out["margin_used"] = float(acct.get("totalInitialMargin", 0) or 0)
                out["margin_free"] = float(acct.get("availableBalance", 0) or 0)
                out["unrealized_pnl"] = float(acct.get("totalUnrealizedProfit", 0) or 0)
            except (TypeError, ValueError):
                pass
        elif isinstance(acct, dict) and acct.get("code"):
            out["error"] = f"Binance: {acct.get('msg', acct.get('code'))}"

        bals = client.balance()
        if isinstance(bals, list) and not out["equity"]:
            usdt = next((b for b in bals if isinstance(b, dict) and b.get("asset") == "USDT"), None)
            if usdt:
                try:
                    out["balance"] = float(usdt.get("balance", 0) or 0)
                    out["equity"]  = float(usdt.get("balance", 0) or 0) + float(usdt.get("crossUnPnl", 0) or 0)
                    out["unrealized_pnl"] = float(usdt.get("crossUnPnl", 0) or 0)
                except (TypeError, ValueError):
                    pass

        positions = client.positions()
        if isinstance(positions, list):
            out["positions"] = self._normalise_positions(positions)

        income = client.income_history(days=7)
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

        # Pull recent trades for the symbol of each open position.
        recent: list[dict] = []
        for pos in out["positions"][:5]:
            sym = pos.get("symbol")
            if not sym:
                continue
            trades = client.recent_trades(symbol=sym, limit=10)
            if isinstance(trades, list):
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

    # ── PAPER (last backtest) ─────────────────────────────────
    def _load_paper(self) -> dict:
        """Build a 'paper' account snapshot from the latest local backtest run."""
        out: dict = {
            "mode":     "paper",
            "status":   "paper",
            "ts":       datetime.now().isoformat(),
            "error":    None,
            "balance":  0.0,
            "equity":   0.0,
            "today_pnl": 0.0,
            "positions": [],
            "recent_trades": [],
            "trades":   [],
            "equity_curve": [],
            "summary":  {},
            "run_id":   None,
        }

        index_file = self.data_dir / "index.json"
        if not index_file.exists():
            out["error"] = "No backtest runs found."
            return out

        try:
            runs = json.loads(index_file.read_text(encoding="utf-8"))
        except Exception:
            out["error"] = "Could not parse data/index.json."
            return out

        if not isinstance(runs, list) or not runs:
            out["error"] = "No backtest runs registered."
            return out

        latest = runs[-1]
        run_id = latest.get("run_id") or latest.get("id")
        if not run_id:
            out["error"] = "Latest run missing run_id."
            return out

        run_dir = self.data_dir / "runs" / run_id
        if not run_dir.exists():
            # Old runs may be elsewhere — fall back to summary in index
            out["run_id"] = run_id
            out["summary"] = latest
            out["equity"]  = float(latest.get("final_equity", 0) or 0)
            return out

        out["run_id"] = run_id

        summary_path = run_dir / "summary.json"
        if summary_path.exists():
            try:
                out["summary"] = json.loads(summary_path.read_text(encoding="utf-8"))
            except Exception:
                out["summary"] = latest
        else:
            out["summary"] = latest

        # Equity curve
        for fname in ("equity.json", "equity_curve.json"):
            p = run_dir / fname
            if p.exists():
                try:
                    out["equity_curve"] = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    pass
                break

        # Trades
        for fname in ("trades.json", "all_trades.json"):
            p = run_dir / fname
            if p.exists():
                try:
                    raw = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        raw = raw.get("trades", [])
                    out["trades"] = raw if isinstance(raw, list) else []
                except Exception:
                    pass
                break

        eq = out["equity_curve"]
        if eq:
            try:
                out["equity"] = float(eq[-1])
            except (TypeError, ValueError):
                pass

        if not out["equity"]:
            out["equity"] = float(out["summary"].get("final_equity", 0) or 0)
        out["balance"] = out["equity"]

        # Recent trades = last 50
        trades = out["trades"] or []
        out["recent_trades"] = trades[-50:][::-1]
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
