from __future__ import annotations

import subprocess
import sys
import threading
import time

from config.engines import ENGINE_NAMES
from core.health import runtime_health
from core.transport import RequestSpec, TransportClient


LEGACY_ENGINE_ALIASES = {
    "backtest": "citadel",
    "citadel": "citadel",
    "thoth": "bridgewater",
    "bridgewater": "bridgewater",
    "mercurio": "jump",
    "jump": "jump",
    "newton": "deshaw",
    "deshaw": "deshaw",
    "de_shaw": "deshaw",
    "prometeu": "twosigma",
    "twosigma": "twosigma",
    "two_sigma": "twosigma",
    "darwin": "aqr",
    "aqr": "aqr",
    "multistrategy": "millennium",
    "millennium": "millennium",
    "harmonics": "renaissance",
    "harmonics_backtest": "renaissance",
    "renaissance": "renaissance",
    "arbitrage": "janestreet",
    "jane_street": "janestreet",
    "janestreet": "janestreet",
}

ENGINE_PREFIX_ALIASES = (
    "citadel_", "thoth_", "bridgewater_", "newton_", "deshaw_",
    "mercurio_", "jump_", "multistrategy_", "millennium_",
    "prometeu_", "twosigma_", "renaissance_", "harmonics_",
)

VPS_HOST = "root@37.60.254.151"
VPS_PROJECT = "~/aurum.finance"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_TICKER_DATA: dict[str, dict[str, float]] = {}
_TICKER_LOCK = threading.Lock()


def canonical_engine_key(name) -> str:
    raw = str(name or "").strip().lower().replace(" ", "_")
    return LEGACY_ENGINE_ALIASES.get(raw, raw)


def engine_display_name(name) -> str:
    key = canonical_engine_key(name)
    return ENGINE_NAMES.get(key, key.replace("_", " ").upper())


def run_vps_cmd(cmd: str, timeout: int = 10) -> str | None:
    """Run a command on the VPS over SSH from a worker thread."""
    try:
        r = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no",
             "-o", "ConnectTimeout=5",
             "-o", "BatchMode=yes",
             VPS_HOST, cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=NO_WINDOW,
        )
        if r.returncode == 0:
            return r.stdout
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def fetch_ticker_loop() -> None:
    client = TransportClient()
    while True:
        try:
            r = client.request(RequestSpec(
                method="GET",
                url="https://fapi.binance.com/fapi/v1/ticker/24hr",
                timeout=8,
            ))
            if r.status_code == 200:
                payload = {t["symbol"]: t for t in r.json()}
                with _TICKER_LOCK:
                    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]:
                        if sym in payload:
                            _TICKER_DATA[sym] = {
                                "p": float(payload[sym]["lastPrice"]),
                                "c": float(payload[sym]["priceChangePercent"]),
                            }
        except Exception:
            runtime_health.record("launcher.ticker_fetch_failure")
        time.sleep(12)


def ticker_str() -> str:
    with _TICKER_LOCK:
        if not _TICKER_DATA:
            return "connecting..."
        return "   ".join(
            f"{sym.replace('USDT', '')} {_TICKER_DATA[sym]['p']:,.2f} "
            f"{'+' if _TICKER_DATA[sym]['c'] >= 0 else ''}{_TICKER_DATA[sym]['c']:.1f}%"
            for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
            if sym in _TICKER_DATA
        )
