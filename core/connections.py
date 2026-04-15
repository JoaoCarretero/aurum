"""
AURUM Finance — Connection Manager
====================================
Manages state for all exchange, broker, and data provider connections.
Persists to config/connections.json.
"""
import json
import time
from pathlib import Path
from datetime import datetime

STATE_FILE = Path("config/connections.json")

DEFAULT_STATE = {
    "active_market": "crypto_futures",
    "connections": {
        "binance_futures": {"mode": "testnet", "connected": False, "label": "Binance Futures"},
        "binance_spot":    {"connected": False, "label": "Binance Spot"},
        "bybit":           {"connected": False, "label": "Bybit"},
        "okx":             {"connected": False, "label": "OKX"},
        "hyperliquid":     {"connected": False, "label": "Hyperliquid"},
        "gate":            {"connected": False, "label": "Gate.io"},
        "mt5":             {"connected": False, "label": "MetaTrader 5", "server": "", "login": ""},
        "ib":              {"connected": False, "label": "Interactive Brokers"},
        "alpaca":          {"connected": False, "label": "Alpaca"},
        "coinglass":       {"connected": False, "label": "CoinGlass"},
        "glassnode":       {"connected": False, "label": "Glassnode"},
        "cftc":            {"connected": True,  "label": "CFTC COT", "public": True},
        "fred":            {"connected": True,  "label": "FRED", "public": True},
        "yahoo":           {"connected": True,  "label": "Yahoo Finance", "public": True},
        "telegram":        {"connected": False, "label": "Telegram Bot"},
        "discord":         {"connected": False, "label": "Discord Webhook"},
    },
}

MARKETS = {
    "crypto_futures": {"label": "CRYPTO FUTURES",  "desc": "Binance, Bybit, OKX, Hyperliquid",
                       "exchanges": ["binance_futures", "bybit", "okx", "hyperliquid", "gate"],
                       "available": True},
    "crypto_spot":    {"label": "CRYPTO SPOT",     "desc": "Binance, Coinbase, Kraken",
                       "exchanges": ["binance_spot"], "available": False},
    "forex":          {"label": "FOREX / CFD",     "desc": "via MetaTrader 5",
                       "exchanges": ["mt5"], "available": False},
    "equities":       {"label": "EQUITIES",        "desc": "via Interactive Brokers / Alpaca",
                       "exchanges": ["ib", "alpaca"], "available": False},
    "commodities":    {"label": "COMMODITIES",     "desc": "Gold, Oil, Nat Gas (via MT5/IB)",
                       "exchanges": ["mt5", "ib"], "available": False},
    "indices":        {"label": "INDICES",          "desc": "S&P500, NASDAQ, DXY (via MT5/IB)",
                       "exchanges": ["mt5", "ib"], "available": False},
    "onchain":        {"label": "ON-CHAIN",         "desc": "DeFi protocols, DEX data",
                       "exchanges": ["coinglass", "glassnode"], "available": False},
}


class ConnectionManager:
    """Manage state of all connections (exchanges, brokers, data providers)."""

    def __init__(self):
        self.state = self._load()

    def _load(self) -> dict:
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                # Merge with defaults to handle new fields
                merged = dict(DEFAULT_STATE)
                merged["active_market"] = saved.get("active_market", "crypto_futures")
                for k, v in saved.get("connections", {}).items():
                    if k in merged["connections"]:
                        merged["connections"][k].update(v)
                return merged
            except Exception:
                pass
        return dict(DEFAULT_STATE)

    def save(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, default=str)

    @property
    def active_market(self) -> str:
        return self.state.get("active_market", "crypto_futures")

    @active_market.setter
    def active_market(self, value: str):
        self.state["active_market"] = value
        self.save()

    def get(self, provider: str) -> dict:
        return self.state["connections"].get(provider, {})

    def is_connected(self, provider: str) -> bool:
        return self.state["connections"].get(provider, {}).get("connected", False)

    def set_connected(self, provider: str, connected: bool, **kwargs):
        if provider in self.state["connections"]:
            self.state["connections"][provider]["connected"] = connected
            self.state["connections"][provider].update(kwargs)
            if connected:
                self.state["connections"][provider]["last_ping"] = datetime.now().isoformat()
            self.save()

    _PING_CACHE_TTL_S = 8.0  # Avoid hammering the exchange — UI polls repeatedly

    def ping(self, provider: str, max_age: float | None = None) -> float | None:
        """Ping an exchange and return latency in ms, or None on failure.

        Cached for ``_PING_CACHE_TTL_S`` seconds per provider. The dashboard
        tabs + home tile + live engines can hit this from multiple threads
        within a second of each other — the cache collapses those into one
        actual network call per TTL window.

        Pass ``max_age=0`` to force a fresh call (e.g., explicit user refresh).
        """
        ttl = self._PING_CACHE_TTL_S if max_age is None else float(max_age)
        cache = getattr(self, "_ping_cache", None)
        if cache is None:
            cache = self._ping_cache = {}
        now = time.monotonic()
        entry = cache.get(provider)
        if ttl > 0 and entry is not None and (now - entry["t"]) < ttl:
            return entry["val"]

        val: float | None = None
        if provider == "binance_futures":
            try:
                import requests
                t0 = time.time()
                r = requests.get("https://fapi.binance.com/fapi/v1/ping", timeout=3)
                if r.status_code == 200:
                    ms = (time.time() - t0) * 1000
                    self.set_connected(provider, True, latency_ms=round(ms))
                    val = round(ms)
            except Exception:
                val = None
        cache[provider] = {"t": now, "val": val}
        return val

    def get_balance(self, provider: str) -> float | None:
        """Get account balance. Currently only works for Binance with keys."""
        return None  # Placeholder — requires API key integration

    def status_summary(self) -> dict:
        """Quick status for display: active_market, connected exchanges, etc."""
        market_info = MARKETS.get(self.active_market, {})
        connected = [k for k, v in self.state["connections"].items() if v.get("connected")]
        return {
            "market": market_info.get("label", "UNKNOWN"),
            "market_key": self.active_market,
            "connected": connected,
            "n_connected": len(connected),
        }
