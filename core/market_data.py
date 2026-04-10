"""
☿ AURUM Finance — Market Data Fetcher
======================================
Thread-safe market data fetcher para o dashboard de Crypto Futures.

Todos os endpoints são públicos da Binance Futures (fapi.binance.com) e
alternative.me — não requerem API key. Cada chamada usa timeout=5 e
degrada graciosamente quando a rede está bloqueada ou o endpoint falha.

Uso:
    fetcher = MarketDataFetcher(["BTCUSDT", "ETHUSDT", ...])
    # numa thread de background:
    fetcher.fetch_all()
    # na thread da UI:
    snap = fetcher.snapshot()
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Optional

import requests


_BINANCE_FAPI = "https://fapi.binance.com"
_FNG_URL      = "https://api.alternative.me/fng/"
_HTTP_TIMEOUT = 5


class MarketDataFetcher:
    """Thread-safe fetcher: writes happen in worker thread, reads via snapshot()."""

    def __init__(self, symbols: list[str]):
        self.symbols     = list(symbols)
        self.tickers:    dict[str, dict]   = {}
        self.funding:    dict[str, float]  = {}
        self.fear_greed: Optional[dict]    = None
        self.ls_ratio:   Optional[float]   = None
        self.last_update: Optional[datetime] = None
        self.errors:     dict[str, str]    = {}
        self._lock = threading.Lock()

    # ── PUBLIC API ────────────────────────────────────────────
    def fetch_all(self) -> None:
        """Run every fetch in sequence. Call from a background thread."""
        self._fetch_tickers()
        self._fetch_funding()
        self._fetch_fear_greed()
        self._fetch_ls_ratio()
        with self._lock:
            self.last_update = datetime.now()

    def snapshot(self) -> dict:
        """Atomic copy of current state — safe to call from the UI thread."""
        with self._lock:
            return {
                "tickers":     dict(self.tickers),
                "funding":     dict(self.funding),
                "fear_greed":  dict(self.fear_greed) if self.fear_greed else None,
                "ls_ratio":    self.ls_ratio,
                "last_update": self.last_update,
                "errors":      dict(self.errors),
            }

    def funding_avg(self) -> Optional[float]:
        """Average funding rate across the tracked symbols (decimal, e.g. 0.0001)."""
        with self._lock:
            if not self.funding:
                return None
            return sum(self.funding.values()) / len(self.funding)

    # ── INTERNAL FETCHERS ─────────────────────────────────────
    def _fetch_tickers(self) -> None:
        """One bulk call for every 24h ticker, then filter for tracked symbols."""
        try:
            r = requests.get(f"{_BINANCE_FAPI}/fapi/v1/ticker/24hr",
                             timeout=_HTTP_TIMEOUT)
            if r.status_code != 200:
                with self._lock:
                    self.errors["tickers"] = f"HTTP {r.status_code}"
                return
            data = r.json()
            wanted = set(self.symbols)
            out: dict[str, dict] = {}
            for d in data:
                sym = d.get("symbol")
                if sym not in wanted:
                    continue
                try:
                    out[sym] = {
                        "price": float(d["lastPrice"]),
                        "pct":   float(d["priceChangePercent"]),
                        "vol":   float(d["quoteVolume"]),
                        "high":  float(d["highPrice"]),
                        "low":   float(d["lowPrice"]),
                    }
                except (KeyError, ValueError, TypeError):
                    continue
            with self._lock:
                self.tickers = out
                self.errors.pop("tickers", None)
        except Exception as e:
            with self._lock:
                self.errors["tickers"] = str(e)[:80]

    def _fetch_funding(self) -> None:
        """Bulk premium index (lastFundingRate) for every symbol — filter locally."""
        try:
            r = requests.get(f"{_BINANCE_FAPI}/fapi/v1/premiumIndex",
                             timeout=_HTTP_TIMEOUT)
            if r.status_code != 200:
                with self._lock:
                    self.errors["funding"] = f"HTTP {r.status_code}"
                return
            data = r.json()
            wanted = set(self.symbols)
            out: dict[str, float] = {}
            for d in data:
                sym = d.get("symbol")
                if sym not in wanted:
                    continue
                try:
                    out[sym] = float(d.get("lastFundingRate", 0))
                except (ValueError, TypeError):
                    continue
            with self._lock:
                self.funding = out
                self.errors.pop("funding", None)
        except Exception as e:
            with self._lock:
                self.errors["funding"] = str(e)[:80]

    def _fetch_fear_greed(self) -> None:
        """alternative.me Fear & Greed Index (latest value)."""
        try:
            r = requests.get(_FNG_URL, params={"limit": 1}, timeout=_HTTP_TIMEOUT)
            if r.status_code != 200:
                with self._lock:
                    self.errors["fear_greed"] = f"HTTP {r.status_code}"
                return
            j = r.json()
            row = (j.get("data") or [{}])[0]
            try:
                val = int(row.get("value", 0))
            except (ValueError, TypeError):
                val = 0
            cls = str(row.get("value_classification", ""))
            with self._lock:
                self.fear_greed = {"value": val, "classification": cls}
                self.errors.pop("fear_greed", None)
        except Exception as e:
            with self._lock:
                self.errors["fear_greed"] = str(e)[:80]

    def _fetch_ls_ratio(self) -> None:
        """BTCUSDT global long/short account ratio (5 minute window)."""
        try:
            r = requests.get(
                f"{_BINANCE_FAPI}/futures/data/globalLongShortAccountRatio",
                params={"symbol": "BTCUSDT", "period": "5m", "limit": 1},
                timeout=_HTTP_TIMEOUT,
            )
            if r.status_code != 200:
                with self._lock:
                    self.errors["ls_ratio"] = f"HTTP {r.status_code}"
                return
            j = r.json()
            if not j:
                return
            try:
                ratio = float(j[0].get("longShortRatio", 0))
            except (ValueError, TypeError):
                return
            with self._lock:
                self.ls_ratio = ratio
                self.errors.pop("ls_ratio", None)
        except Exception as e:
            with self._lock:
                self.errors["ls_ratio"] = str(e)[:80]
