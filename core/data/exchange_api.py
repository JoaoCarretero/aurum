"""
☿ AURUM Finance — Exchange API (read-only)
============================================
Minimal HMAC-signed REST client for Binance Futures used by the dashboard
to read account state. Read-only — never places orders.

Reuses the signing pattern from engines/live.py LiveEngine._verify_api_connection.
Mirrors the three Binance environments (testnet / demo / live).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Optional

import requests


log = logging.getLogger(__name__)

_BASE_URLS = {
    "testnet": "https://testnet.binancefuture.com",
    "demo":    "https://demo-fapi.binance.com",
    "live":    "https://fapi.binance.com",
}

_DEFAULT_TIMEOUT = 5
_RECV_WINDOW = 5000


class BinanceFuturesAPI:
    """Read-only REST client for Binance USDⓂ-Futures (testnet/demo/live)."""

    def __init__(self, api_key: str, api_secret: str, mode: str = "testnet"):
        self.key = api_key or ""
        self.secret = api_secret or ""
        self.mode = mode if mode in _BASE_URLS else "testnet"
        self.base = _BASE_URLS[self.mode]

    # ── INTERNALS ─────────────────────────────────────────────
    def _signed_get(self, path: str, params: Optional[dict] = None):
        """Issue an authenticated GET. Returns parsed JSON or None on failure.

        Returns None uniformly across failure modes (network / auth / parsing)
        to keep callers simple, but logs them at distinct levels so operators
        can tell connectivity blips apart from credential rejections.
        """
        if not self.key or not self.secret:
            return None
        params = dict(params or {})
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = _RECV_WINDOW
        # Binance signs the URL-encoded query string in deterministic order.
        query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        sig = hmac.new(
            self.secret.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()
        url = f"{self.base}{path}?{query}&signature={sig}"
        try:
            r = requests.get(
                url,
                headers={"X-MBX-APIKEY": self.key},
                timeout=_DEFAULT_TIMEOUT,
            )
        except requests.exceptions.Timeout:
            log.debug("binance %s %s timeout", self.mode, path)
            return None
        except requests.exceptions.ConnectionError as e:
            log.debug("binance %s %s connection error: %s", self.mode, path, e)
            return None
        except requests.RequestException as e:
            log.warning("binance %s %s request error: %s", self.mode, path, e)
            return None

        if r.status_code in (401, 403):
            log.warning(
                "binance %s %s auth rejected (HTTP %s) — key invalid or permissions missing",
                self.mode, path, r.status_code,
            )
            return None
        if r.status_code == 429 or r.status_code == 418:
            log.warning("binance %s %s rate-limited (HTTP %s)", self.mode, path, r.status_code)
            return None
        if r.status_code != 200:
            log.debug("binance %s %s HTTP %s: %s", self.mode, path, r.status_code, r.text[:200])
            return None
        try:
            return r.json()
        except ValueError:
            log.warning("binance %s %s returned non-JSON body", self.mode, path)
            return None

    # ── PUBLIC ENDPOINTS ──────────────────────────────────────
    def ping(self) -> Optional[int]:
        """Returns server-time lag in ms (positive = local clock ahead)."""
        try:
            t0 = time.time()
            r = requests.get(f"{self.base}/fapi/v1/time", timeout=_DEFAULT_TIMEOUT)
            if r.status_code != 200:
                return None
            srv = int(r.json().get("serverTime", 0))
            return int(t0 * 1000) - srv
        except Exception:
            return None

    # ── ACCOUNT READS ─────────────────────────────────────────
    def balance(self) -> Optional[list[dict]]:
        """GET /fapi/v2/balance — list of per-asset balances."""
        return self._signed_get("/fapi/v2/balance")

    def account(self) -> Optional[dict]:
        """GET /fapi/v2/account — full account snapshot (equity/margin/positions)."""
        return self._signed_get("/fapi/v2/account")

    def positions(self) -> Optional[list[dict]]:
        """GET /fapi/v2/positionRisk — open positions (filtered to size != 0)."""
        data = self._signed_get("/fapi/v2/positionRisk")
        if not isinstance(data, list):
            return None
        out = []
        for p in data:
            try:
                amt = float(p.get("positionAmt", 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            if amt == 0:
                continue
            out.append(p)
        return out

    def recent_trades(self, symbol: Optional[str] = None,
                      limit: int = 50) -> Optional[list[dict]]:
        """GET /fapi/v1/userTrades — most recent fills.
        Binance requires a symbol; if none is provided, the call is skipped."""
        if not symbol:
            return None
        return self._signed_get(
            "/fapi/v1/userTrades",
            {"symbol": symbol, "limit": min(int(limit), 1000)},
        )

    def income_history(self, days: int = 7,
                       income_type: str = "REALIZED_PNL") -> Optional[list[dict]]:
        """GET /fapi/v1/income — realised PnL history for the last *days*."""
        end = int(time.time() * 1000)
        start = end - int(days) * 24 * 3600 * 1000
        return self._signed_get("/fapi/v1/income", {
            "incomeType": income_type,
            "startTime":  start,
            "endTime":    end,
            "limit":      1000,
        })


def make_client(mode: str, keys_file: str = "config/keys.json") -> Optional[BinanceFuturesAPI]:
    """Build a client from the runtime key store for a given mode."""
    from core.key_store import KeyStoreError, load_runtime_keys

    try:
        cfg = load_runtime_keys(plaintext_path=keys_file)
    except KeyStoreError:
        return None
    block = cfg.get(mode) or {}
    api_key = block.get("api_key", "")
    api_secret = block.get("api_secret", "")
    if not api_key or not api_secret or "COLE_AQUI" in api_key:
        return None
    return BinanceFuturesAPI(api_key, api_secret, mode=mode)
