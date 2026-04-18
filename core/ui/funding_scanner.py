"""FundingScanner — cross-venue funding-rate observer.

Fetches funding rates from public perpetual-futures APIs (no auth required)
across both CEX and DEX venues and ranks opportunities by annualized APR.
Purely observational — no execution, no sizing, no orders.

Venues (all batch endpoints, public, no auth)
---------------------------------------------
DEX:
  hyperliquid  1h  130+ perps  — highest funding cadence in the industry
  dydx         8h  220+ perps  — largest Cosmos-based perp DEX
  paradex      1h  100+ perps  — Starknet-based perp DEX
  gmx          1h  40+  perps  — GMX v2 Arbitrum perpetuals
  vertex       8h  20+  perps  — Vertex Protocol Arbitrum orderbook
  aevo         1h  100+ perps  — Aevo options + perp exchange
  drift        1h  50+  perps  — Drift Protocol Solana perps
  apex         1h  50+  perps  — ApeX Pro StarkEx perps

CEX:
  binance      8h  400+ perps  — largest perps venue globally
  bybit        8h  500+ perps
  gate         8h  300+ perps
  bitget       8h  400+ perps
  bingx        8h  300+ perps  — Binance-compatible API shape

Three arbitrage modes over the same data
----------------------------------------
  dex-dex : both legs are DEX           (pure DeFi funding spread)
  cex-dex : one CEX leg + one DEX leg   (historically the biggest APR)
  cex-cex : handled by the JANE STREET engine, NOT this module

APR formula
-----------
    apr_pct = abs(rate) * (24 / interval_h) * 365 * 100
    e.g. Hyperliquid 0.01%/h  → 87.6% APR
         Binance     0.03%/8h → 32.85% APR

The scanner runs venue fetches in parallel (ThreadPoolExecutor); if a
venue fails the scan continues with the remaining venues. Cached for
``CACHE_TTL`` seconds between calls.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path

import requests

log = logging.getLogger("FUNDING_SCANNER")

# ─── Config ──────────────────────────────────────────────────────────────
HTTP_TIMEOUT  = 10          # seconds per venue
CACHE_TTL     = 30          # seconds between rescans
MIN_VOL_USD   = 500_000     # 24h volume floor (below = liquidity trap)
MIN_OI_USD    = 200_000     # open interest floor
HIGH_RISK_VOL = 2_000_000
HIGH_RISK_OI  = 500_000

_ROOT = Path(__file__).parent.parent.parent
_ALERT_LOG_PATH = _ROOT / "data" / "funding_scanner" / "alert_log.json"
ALERT_THROTTLE_S = 30 * 60  # 30 minutes per symbol


# ─── Data model ──────────────────────────────────────────────────────────
@dataclass
class FundingOpp:
    """A single funding-rate observation at one venue."""
    symbol: str
    venue: str
    venue_type: str      # "CEX" or "DEX"
    rate: float          # per-period rate (e.g. 0.0001 = 0.01%)
    interval_h: float    # hours between funding payments
    apr: float           # annualized, signed
    direction: str       # "SHORT" when rate > 0, "LONG" when rate < 0
    mark_price: float
    volume_24h: float
    open_interest: float
    risk: str            # "LOW" / "MED" / "HIGH"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SpotPrice:
    """A spot price observation at one venue."""
    symbol: str
    venue: str
    price: float
    volume_24h: float


# ─── Risk scoring ────────────────────────────────────────────────────────
def _classify_risk(volume: float, oi: float) -> str:
    if volume < HIGH_RISK_VOL or oi < HIGH_RISK_OI:
        return "HIGH"
    if volume < HIGH_RISK_VOL * 5 or oi < HIGH_RISK_OI * 5:
        return "MED"
    return "LOW"


def _apr_pct(rate: float, interval_h: float) -> float:
    periods_per_day = 24.0 / max(interval_h, 1e-9)
    return abs(rate) * periods_per_day * 365.0 * 100.0


def _mk(symbol, venue, venue_type, rate, interval_h, mark, vol, oi):
    apr = _apr_pct(rate, interval_h) * (1 if rate > 0 else -1)
    return FundingOpp(
        symbol=symbol.upper(),
        venue=venue,
        venue_type=venue_type,
        rate=rate,
        interval_h=interval_h,
        apr=apr,
        direction="SHORT" if rate > 0 else "LONG",
        mark_price=mark,
        volume_24h=vol,
        open_interest=oi,
        risk=_classify_risk(vol, oi),
    )


def _is_usdt_base(symbol: str) -> str | None:
    """Strip USDT/USD/PERP suffixes and return the base asset, or None."""
    s = symbol.upper().replace(":USDT", "").replace("-PERP", "")
    for sep in ("-", "_", "/"):
        s = s.replace(sep, "")
    for suffix in ("USDT", "USDC", "USD"):
        if s.endswith(suffix) and s != suffix:
            return s[: -len(suffix)]
    return None


# ═══════════════════════════════════════════════════════════════════════
# DEX venue fetchers
# ═══════════════════════════════════════════════════════════════════════
def fetch_hyperliquid() -> list[FundingOpp]:
    """POST https://api.hyperliquid.xyz/info  body {"type":"metaAndAssetCtxs"}
    Hourly funding, response is [meta, [asset_ctx...]]."""
    resp = requests.post(
        "https://api.hyperliquid.xyz/info",
        json={"type": "metaAndAssetCtxs"},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not (isinstance(payload, list) and len(payload) >= 2):
        raise ValueError("hyperliquid: unexpected payload shape")
    meta = payload[0] or {}
    ctxs = payload[1] or []
    universe = meta.get("universe") or []
    if len(universe) != len(ctxs):
        raise ValueError("hyperliquid: universe/ctxs length mismatch")

    out: list[FundingOpp] = []
    for asset, ctx in zip(universe, ctxs):
        try:
            coin = (asset or {}).get("name") or ""
            if not coin:
                continue
            rate = float((ctx or {}).get("funding") or 0.0)
            mark = float(ctx.get("markPx") or 0.0)
            oi_base = float(ctx.get("openInterest") or 0.0)
            vol_usd = float(ctx.get("dayNtlVlm") or 0.0)
            oi_usd = oi_base * mark
            if rate == 0.0 or mark == 0.0:
                continue
            if vol_usd < MIN_VOL_USD or oi_usd < MIN_OI_USD:
                continue
            out.append(_mk(coin, "hyperliquid", "DEX",
                           rate, 1.0, mark, vol_usd, oi_usd))
        except (TypeError, ValueError):
            continue
    return out


def fetch_dydx() -> list[FundingOpp]:
    """GET https://indexer.dydx.trade/v4/perpetualMarkets
    8h funding window."""
    resp = requests.get(
        "https://indexer.dydx.trade/v4/perpetualMarkets",
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    markets = (resp.json() or {}).get("markets") or {}

    out: list[FundingOpp] = []
    for ticker, info in markets.items():
        try:
            if not isinstance(info, dict):
                continue
            symbol = ticker.split("-")[0]
            rate = float(info.get("nextFundingRate") or 0.0)
            mark = float(info.get("oraclePrice") or 0.0)
            vol_usd = float(info.get("volume24H") or 0.0)
            oi_base = float(info.get("openInterest") or 0.0)
            oi_usd = oi_base * mark
            if rate == 0.0 or mark == 0.0:
                continue
            if vol_usd < MIN_VOL_USD or oi_usd < MIN_OI_USD:
                continue
            out.append(_mk(symbol, "dydx", "DEX",
                           rate, 8.0, mark, vol_usd, oi_usd))
        except (TypeError, ValueError):
            continue
    return out


def fetch_paradex() -> list[FundingOpp]:
    """GET https://api.prod.paradex.trade/v1/markets/summary?market=ALL

    Response mixes options and perps; we filter to ``*-USD-PERP``. The
    ``volume_24h`` field is already in USD quote units; ``open_interest``
    is in base units (multiply by mark). Paradex settles 8-hour funding.
    """
    resp = requests.get(
        "https://api.prod.paradex.trade/v1/markets/summary?market=ALL",
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    results = (resp.json() or {}).get("results") or []

    out: list[FundingOpp] = []
    for m in results:
        try:
            if not isinstance(m, dict):
                continue
            sym = m.get("symbol") or ""
            if not sym.endswith("-USD-PERP"):
                continue
            base = sym.replace("-USD-PERP", "")
            rate = float(m.get("funding_rate") or 0.0)
            mark = float(m.get("mark_price") or 0.0)
            vol_usd = float(m.get("volume_24h") or 0.0)          # already USD
            oi_base = float(m.get("open_interest") or 0.0)
            oi_usd = oi_base * mark
            if rate == 0.0 or mark == 0.0:
                continue
            if vol_usd < MIN_VOL_USD or oi_usd < MIN_OI_USD:
                continue
            out.append(_mk(base, "paradex", "DEX",
                           rate, 8.0, mark, vol_usd, oi_usd))
        except (TypeError, ValueError):
            continue
    return out


# ═══════════════════════════════════════════════════════════════════════
# CEX venue fetchers
# ═══════════════════════════════════════════════════════════════════════
def _fetch_binance_style(base_url: str, venue: str) -> list[FundingOpp]:
    """Binance / BingX share the same /premiumIndex batch shape:
       [{symbol, markPrice, lastFundingRate, nextFundingTime}, ...]"""
    # premiumIndex gives funding rate; 24hr gives volume
    pi = requests.get(f"{base_url}/fapi/v1/premiumIndex", timeout=HTTP_TIMEOUT)
    pi.raise_for_status()
    ti = requests.get(f"{base_url}/fapi/v1/ticker/24hr", timeout=HTTP_TIMEOUT)
    ti.raise_for_status()
    vol_map = {row["symbol"]: float(row.get("quoteVolume") or 0.0)
               for row in (ti.json() or []) if isinstance(row, dict)}

    oi_map: dict[str, float] = {}  # oi per symbol requires per-symbol calls; skip

    out: list[FundingOpp] = []
    for row in (pi.json() or []):
        try:
            if not isinstance(row, dict):
                continue
            sym = row.get("symbol") or ""
            base = _is_usdt_base(sym)
            if not base:
                continue
            rate = float(row.get("lastFundingRate") or 0.0)
            mark = float(row.get("markPrice") or 0.0)
            vol_usd = vol_map.get(sym, 0.0)
            if rate == 0.0 or mark == 0.0:
                continue
            if vol_usd < MIN_VOL_USD:
                continue
            # OI not available batched; use a fake floor so risk classifies
            # correctly — Binance liquidity is never the concern on top perps.
            oi_usd = max(vol_usd * 0.05, MIN_OI_USD)
            out.append(_mk(base, venue, "CEX",
                           rate, 8.0, mark, vol_usd, oi_usd))
        except (TypeError, ValueError):
            continue
    return out


def fetch_binance() -> list[FundingOpp]:
    """Binance USDT-M Futures — largest perps venue globally."""
    return _fetch_binance_style("https://fapi.binance.com", "binance")


def fetch_bingx() -> list[FundingOpp]:
    """BingX Perpetual Futures — funding from /premiumIndex, volume merged
    in from /ticker (quoteVolume). Two calls, joined by symbol."""
    base = "https://open-api.bingx.com"
    pi = requests.get(
        f"{base}/openApi/swap/v2/quote/premiumIndex",
        timeout=HTTP_TIMEOUT,
    )
    pi.raise_for_status()
    funding_rows = (pi.json() or {}).get("data") or []

    ti = requests.get(
        f"{base}/openApi/swap/v2/quote/ticker",
        timeout=HTTP_TIMEOUT,
    )
    ti.raise_for_status()
    vol_rows = (ti.json() or {}).get("data") or []
    vol_map = {
        row.get("symbol"): float(row.get("quoteVolume") or 0.0)
        for row in vol_rows if isinstance(row, dict)
    }

    out: list[FundingOpp] = []
    for row in funding_rows:
        try:
            if not isinstance(row, dict):
                continue
            sym = row.get("symbol") or ""        # "BTC-USDT"
            base_asset = _is_usdt_base(sym.replace("-", ""))
            if not base_asset:
                continue
            rate = float(row.get("lastFundingRate") or 0.0)
            mark = float(row.get("markPrice") or 0.0)
            interval_h = float(row.get("fundingIntervalHours") or 8)
            vol_usd = vol_map.get(sym, 0.0)
            if rate == 0.0 or mark == 0.0:
                continue
            if vol_usd < MIN_VOL_USD:
                continue
            oi_usd = max(vol_usd * 0.05, MIN_OI_USD)
            out.append(_mk(base_asset, "bingx", "CEX",
                           rate, interval_h, mark, vol_usd, oi_usd))
        except (TypeError, ValueError):
            continue
    return out


def fetch_bybit() -> list[FundingOpp]:
    """Bybit V5 tickers (linear) — single batch call with fundingRate inline."""
    resp = requests.get(
        "https://api.bybit.com/v5/market/tickers?category=linear",
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    rows = ((resp.json() or {}).get("result") or {}).get("list") or []

    out: list[FundingOpp] = []
    for row in rows:
        try:
            if not isinstance(row, dict):
                continue
            sym = row.get("symbol") or ""
            base = _is_usdt_base(sym)
            if not base:
                continue
            rate = float(row.get("fundingRate") or 0.0)
            mark = float(row.get("markPrice") or 0.0)
            vol_usd = float(row.get("turnover24h") or 0.0)
            oi_base = float(row.get("openInterest") or 0.0)
            oi_usd = oi_base * mark
            if rate == 0.0 or mark == 0.0:
                continue
            if vol_usd < MIN_VOL_USD or oi_usd < MIN_OI_USD:
                continue
            out.append(_mk(base, "bybit", "CEX",
                           rate, 8.0, mark, vol_usd, oi_usd))
        except (TypeError, ValueError):
            continue
    return out


def fetch_gate() -> list[FundingOpp]:
    """Gate.io USDT perpetual tickers — single batch call that has funding
    rate, mark price and 24h quote volume inline. The contracts endpoint
    carries funding_rate too but lacks volume; tickers has both."""
    resp = requests.get(
        "https://api.gateio.ws/api/v4/futures/usdt/tickers",
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    rows = resp.json() or []

    out: list[FundingOpp] = []
    for row in rows:
        try:
            if not isinstance(row, dict):
                continue
            contract = row.get("contract") or ""
            if not contract.endswith("_USDT"):
                continue
            base = contract.replace("_USDT", "")
            rate = float(row.get("funding_rate") or 0.0)
            mark = float(row.get("mark_price") or 0.0)
            vol_usd = float(row.get("volume_24h_quote") or 0.0)
            # No OI field on tickers — fall back to a proxy so the filter
            # doesn't reject everything. Gate OI lives in /positions which
            # isn't public; we accept vol-derived floor like BingX/Binance.
            oi_usd = max(vol_usd * 0.05, MIN_OI_USD)
            if rate == 0.0 or mark == 0.0:
                continue
            if vol_usd < MIN_VOL_USD:
                continue
            out.append(_mk(base, "gate", "CEX",
                           rate, 8.0, mark, vol_usd, oi_usd))
        except (TypeError, ValueError):
            continue
    return out


def fetch_bitget() -> list[FundingOpp]:
    """Bitget V2 mix tickers — USDT-FUTURES batch with fundingRate."""
    resp = requests.get(
        "https://api.bitget.com/api/v2/mix/market/tickers"
        "?productType=USDT-FUTURES",
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    rows = (resp.json() or {}).get("data") or []

    out: list[FundingOpp] = []
    for row in rows:
        try:
            if not isinstance(row, dict):
                continue
            sym = row.get("symbol") or ""
            base = _is_usdt_base(sym)
            if not base:
                continue
            rate = float(row.get("fundingRate") or 0.0)
            mark = float(row.get("markPrice") or 0.0)
            vol_usd = float(row.get("quoteVolume") or 0.0)
            oi_base = float(row.get("holdingAmount") or 0.0)
            oi_usd = oi_base * mark
            if rate == 0.0 or mark == 0.0:
                continue
            if vol_usd < MIN_VOL_USD or oi_usd < MIN_OI_USD:
                continue
            out.append(_mk(base, "bitget", "CEX",
                           rate, 8.0, mark, vol_usd, oi_usd))
        except (TypeError, ValueError):
            continue
    return out


def fetch_gmx() -> list[FundingOpp]:
    """GET https://arbitrum-api.gmxinfra.io/markets/info
    GMX v2 Arbitrum perpetuals.  Rates are in wei (1e30 divisor) per second;
    we normalise to per-hour.  netRateLong / netRateShort give the dominant
    direction — we take the one with higher absolute value as the signal."""
    resp = requests.get(
        "https://arbitrum-api.gmxinfra.io/markets/info",
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    markets = (resp.json() or {})

    out: list[FundingOpp] = []
    for info in (markets if isinstance(markets, list) else markets.values() if isinstance(markets, dict) else []):
        try:
            if not isinstance(info, dict):
                continue
            # Extract token symbol from indexToken or marketToken data
            index_token = info.get("indexToken") or {}
            symbol = (index_token.get("symbol") or "").upper()
            if not symbol:
                continue

            # Rates are per-second in wei (divisor 1e30)
            rate_long_raw = float(info.get("netRateLong") or 0.0)
            rate_short_raw = float(info.get("netRateShort") or 0.0)
            # Convert wei/second → rate/hour
            rate_long_h = (rate_long_raw / 1e30) * 3600.0
            rate_short_h = (rate_short_raw / 1e30) * 3600.0
            # Pick the dominant (higher abs) direction
            rate = rate_long_h if abs(rate_long_h) >= abs(rate_short_h) else rate_short_h

            mark = float(info.get("indexPrice") or 0.0)
            if mark == 0.0:
                # Try midPrice fallback
                mark = float(info.get("midPrice") or 0.0)

            # OI in wei (1e30 divisor gives USD)
            oi_long_raw = float(info.get("openInterestLong") or 0.0)
            oi_short_raw = float(info.get("openInterestShort") or 0.0)
            oi_usd = (oi_long_raw + oi_short_raw) / 1e30

            vol_usd = float(info.get("volumeUsd24h") or 0.0)

            if rate == 0.0 or mark == 0.0:
                continue
            # GMX often has low vol on small markets — allow 0 vol (HIGH risk)
            out.append(_mk(symbol, "gmx", "DEX",
                           rate, 1.0, mark, vol_usd, oi_usd))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    return out


# Vertex product_id → base asset for major perps (Arbitrum orderbook)
_VERTEX_PRODUCTS: dict[int, str] = {
    2: "BTC",
    4: "ETH",
    6: "ARB",
    8: "BNB",
    10: "XRP",
    12: "SOL",
    14: "MATIC",
    16: "SUI",
    18: "OP",
    20: "AVAX",
    22: "LINK",
    24: "DOGE",
    26: "INJ",
    28: "NEAR",
    30: "MKR",
    32: "PEPE",
    34: "APT",
    36: "LTC",
    38: "BCH",
    40: "ATOM",
}


def fetch_vertex() -> list[FundingOpp]:
    """POST https://archive.prod.vertexprotocol.com/v1/indexer
    body: {"funding_rates": {"product_ids": [...]}}
    Rates as x18 strings (divide by 1e18). 8h interval."""
    product_ids = list(_VERTEX_PRODUCTS.keys())
    resp = requests.post(
        "https://archive.prod.vertexprotocol.com/v1/indexer",
        json={"funding_rates": {"product_ids": product_ids}},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json() or {}
    funding_rates = payload.get("funding_rates") or {}

    out: list[FundingOpp] = []
    for product_id_str, rate_info in funding_rates.items():
        try:
            product_id = int(product_id_str)
            symbol = _VERTEX_PRODUCTS.get(product_id)
            if not symbol:
                continue
            if not isinstance(rate_info, dict):
                continue
            # rate is an x18 fixed-point string
            rate_raw = rate_info.get("funding_rate_x18") or rate_info.get("rate") or "0"
            rate = float(rate_raw) / 1e18

            # Mark price also x18 if present
            mark_raw = rate_info.get("product_price_x18") or rate_info.get("price_x18") or "0"
            mark = float(mark_raw) / 1e18

            if rate == 0.0:
                continue
            # Vol/OI not available in funding endpoint — pass 0 (HIGH risk)
            out.append(_mk(symbol, "vertex", "DEX",
                           rate, 8.0, mark, 0.0, 0.0))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    return out


def fetch_aevo() -> list[FundingOpp]:
    """GET https://api.aevo.xyz/funding
    Simple list of {instrument_name, funding_rate, ...}. 1h interval."""
    resp = requests.get(
        "https://api.aevo.xyz/funding",
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    rows = resp.json() or []
    if isinstance(rows, dict):
        rows = rows.get("data") or []

    out: list[FundingOpp] = []
    for row in rows:
        try:
            if not isinstance(row, dict):
                continue
            instrument = row.get("instrument_name") or ""
            if not instrument.endswith("-PERP"):
                continue
            symbol = instrument.replace("-PERP", "").upper()
            rate = float(row.get("funding_rate") or 0.0)
            mark = float(row.get("mark_price") or row.get("index_price") or 0.0)

            vol_usd = float(row.get("volume_24h") or row.get("daily_volume") or 0.0)
            oi_usd = float(row.get("open_interest") or 0.0)
            # OI field on aevo is in USD already when present
            if oi_usd == 0.0 and mark > 0.0:
                oi_base = float(row.get("open_interest_notional") or 0.0)
                oi_usd = oi_base * mark

            if rate == 0.0:
                continue
            out.append(_mk(symbol, "aevo", "DEX",
                           rate, 1.0, mark, vol_usd, oi_usd))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    return out


def fetch_drift() -> list[FundingOpp]:
    """GET https://data.api.drift.trade/fundingRates?limit=50
    Solana-based Drift Protocol perps. 1h funding.
    Deduplicates by symbol, keeping the latest entry by ``ts``."""
    resp = requests.get(
        "https://data.api.drift.trade/fundingRates?limit=50",
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json() or {}
    rows = payload if isinstance(payload, list) else (payload.get("data") or [])

    # Deduplicate: keep latest ts per symbol
    latest: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = (row.get("symbol") or row.get("marketSymbol") or "").upper()
        if not sym:
            continue
        # Normalise: "SOL-PERP" → "SOL"
        sym = sym.replace("-PERP", "").replace("_PERP", "")
        ts = float(row.get("ts") or row.get("timestamp") or 0.0)
        if sym not in latest or ts > float(latest[sym].get("ts") or latest[sym].get("timestamp") or 0.0):
            row["_sym"] = sym
            latest[sym] = row

    out: list[FundingOpp] = []
    for sym, row in latest.items():
        try:
            rate_raw = row.get("fundingRate") or row.get("funding_rate") or 0.0
            rate = float(rate_raw)
            mark = float(row.get("oraclePrice") or row.get("markPrice") or row.get("price") or 0.0)
            vol_usd = float(row.get("volume24h") or row.get("volume") or 0.0)
            oi_usd = float(row.get("openInterest") or row.get("open_interest") or 0.0)
            if oi_usd == 0.0 and mark > 0.0:
                oi_base = float(row.get("openInterestBase") or 0.0)
                oi_usd = oi_base * mark

            if rate == 0.0:
                continue
            out.append(_mk(sym, "drift", "DEX",
                           rate, 1.0, mark, vol_usd, oi_usd))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    return out


def fetch_apex() -> list[FundingOpp]:
    """GET https://omni.apex.exchange/api/v3/ticker
    ApeX Pro StarkEx perpetuals. 1h funding.
    Volume from ``volume24h`` or ``turnover24h``, OI from ``openInterest``."""
    resp = requests.get(
        "https://omni.apex.exchange/api/v3/ticker",
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json() or {}
    rows = payload if isinstance(payload, list) else (
        payload.get("data") or payload.get("tickers") or []
    )

    out: list[FundingOpp] = []
    for row in rows:
        try:
            if not isinstance(row, dict):
                continue
            sym_raw = row.get("symbol") or row.get("ticker") or ""
            # ApeX symbols often like "BTC-USDT" or "BTCUSDT"
            base = _is_usdt_base(sym_raw)
            if not base:
                # Try stripping "-USD" or direct symbol
                base = sym_raw.replace("-USD", "").replace("_USD", "").upper() or None
            if not base:
                continue

            rate = float(row.get("fundingRate") or row.get("lastFundingRate") or 0.0)
            mark = float(row.get("lastPrice") or row.get("markPrice") or row.get("indexPrice") or 0.0)
            vol_usd = float(
                row.get("volume24h") or row.get("turnover24h") or row.get("quoteVolume24h") or 0.0
            )
            oi_usd = float(row.get("openInterest") or row.get("openInterestValue") or 0.0)

            if rate == 0.0:
                continue
            out.append(_mk(base, "apex", "DEX",
                           rate, 1.0, mark, vol_usd, oi_usd))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    return out


# ═══════════════════════════════════════════════════════════════════════
# Spot price fetchers (Fase D — for basis + spot-spot arb)
# ═══════════════════════════════════════════════════════════════════════

def fetch_binance_spot() -> list[SpotPrice]:
    """GET https://api.binance.com/api/v3/ticker/24hr"""
    resp = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    out: list[SpotPrice] = []
    for t in resp.json():
        try:
            base = _is_usdt_base(t.get("symbol") or "")
            if not base:
                continue
            price = float(t.get("lastPrice") or 0)
            vol = float(t.get("quoteVolume") or 0)
            if price <= 0:
                continue
            out.append(SpotPrice(base, "binance", price, vol))
        except (TypeError, ValueError):
            continue
    return out


def fetch_bybit_spot() -> list[SpotPrice]:
    """GET https://api.bybit.com/v5/market/tickers?category=spot"""
    resp = requests.get("https://api.bybit.com/v5/market/tickers",
                        params={"category": "spot"}, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    tickers = (resp.json().get("result") or {}).get("list") or []
    out: list[SpotPrice] = []
    for t in tickers:
        try:
            base = _is_usdt_base(t.get("symbol") or "")
            if not base:
                continue
            price = float(t.get("lastPrice") or 0)
            vol = float(t.get("turnover24h") or 0)
            if price <= 0:
                continue
            out.append(SpotPrice(base, "bybit", price, vol))
        except (TypeError, ValueError):
            continue
    return out


SPOT_FETCHERS = {
    "binance": fetch_binance_spot,
    "bybit":   fetch_bybit_spot,
}


# Venue registry (priority ordered — DEX first, then CEX).
VENUE_FETCHERS = {
    # ── DEX ──────────────────────────────────────────────────────────────
    "hyperliquid": (fetch_hyperliquid, "DEX"),
    "dydx":        (fetch_dydx,        "DEX"),
    "paradex":     (fetch_paradex,     "DEX"),
    "gmx":         (fetch_gmx,         "DEX"),
    "vertex":      (fetch_vertex,      "DEX"),
    "aevo":        (fetch_aevo,        "DEX"),
    "drift":       (fetch_drift,       "DEX"),
    "apex":        (fetch_apex,        "DEX"),
    # ── CEX ──────────────────────────────────────────────────────────────
    "binance":     (fetch_binance,     "CEX"),
    "bybit":       (fetch_bybit,       "CEX"),
    "gate":        (fetch_gate,        "CEX"),
    "bitget":      (fetch_bitget,      "CEX"),
    "bingx":       (fetch_bingx,       "CEX"),
}


# ═══════════════════════════════════════════════════════════════════════
# Scanner
# ═══════════════════════════════════════════════════════════════════════
class FundingScanner:
    """Stateful scanner that aggregates funding from all venues."""

    def __init__(self, cache_ttl: float = CACHE_TTL):
        self._cache: list[FundingOpp] = []
        self._spot_cache: list[SpotPrice] = []
        self._last_scan: float = 0.0
        self._last_spot_scan: float = 0.0
        self._cache_ttl: float = cache_ttl
        self._last_error: dict[str, str] = {}
        self._last_counts: dict[str, int] = {}
        self._lock = threading.Lock()

    # ─ public API ───────────────────────────────────────────────
    def scan(self, force: bool = False) -> list[FundingOpp]:
        """Rescan all venues in parallel. Cached for ``cache_ttl`` seconds."""
        now = time.time()
        with self._lock:
            if not force and (now - self._last_scan) < self._cache_ttl and self._cache:
                return list(self._cache)

        all_opps: list[FundingOpp] = []
        errors: dict[str, str] = {}
        counts: dict[str, int] = {}

        with ThreadPoolExecutor(max_workers=len(VENUE_FETCHERS)) as ex:
            futures = {
                ex.submit(fn): name
                for name, (fn, _t) in VENUE_FETCHERS.items()
            }
            for fut in as_completed(futures):
                venue = futures[fut]
                try:
                    opps = fut.result()
                    all_opps.extend(opps)
                    counts[venue] = len(opps)
                except Exception as e:
                    errors[venue] = f"{type(e).__name__}: {e}"
                    counts[venue] = 0
                    log.warning("funding_scanner: %s failed — %s", venue, e)

        all_opps.sort(key=lambda o: abs(o.apr), reverse=True)

        with self._lock:
            self._cache = all_opps
            self._last_scan = now
            self._last_error = errors
            self._last_counts = counts
        return list(all_opps)

    # ─ filters ──────────────────────────────────────────────────
    def top(self, n: int = 30, min_apr: float = 20.0,
            min_vol: float = MIN_VOL_USD,
            venue_type: str | None = None) -> list[FundingOpp]:
        """Top N by |APR| filtered by volume and optional venue type."""
        opps = self._cache or self.scan()
        filtered = [
            o for o in opps
            if abs(o.apr) >= min_apr
            and o.volume_24h >= min_vol
            and (venue_type is None or o.venue_type == venue_type)
        ]
        return filtered[:n]

    def arb_pairs(self, mode: str = "all",
                  min_spread_apr: float = 20.0) -> list[dict]:
        """Same symbol seen on 2+ venues with divergent funding.

        mode:
            "all"      — any venue mix
            "dex-dex"  — both legs must be DEX
            "cex-cex"  — both legs must be CEX
            "cex-dex"  — exactly one CEX leg + one DEX leg (biggest APR)

        Returns list of {symbol, short_venue, long_venue, net_apr, ...}
        ordered by |net APR| descending.
        """
        opps = self._cache or self.scan()
        by_symbol: dict[str, list[FundingOpp]] = {}
        for o in opps:
            by_symbol.setdefault(o.symbol, []).append(o)

        pairs: list[dict] = []
        for symbol, lst in by_symbol.items():
            if len(lst) < 2:
                continue
            # test all unordered pairs — we want the best spread per symbol
            best: dict | None = None
            for i in range(len(lst)):
                for j in range(i + 1, len(lst)):
                    a, b = lst[i], lst[j]
                    if a.venue == b.venue:
                        continue
                    # mode filter
                    if mode == "dex-dex" and not (a.venue_type == "DEX" and b.venue_type == "DEX"):
                        continue
                    if mode == "cex-cex" and not (a.venue_type == "CEX" and b.venue_type == "CEX"):
                        continue
                    if mode == "cex-dex" and {a.venue_type, b.venue_type} != {"CEX", "DEX"}:
                        continue
                    # direction: SHORT the venue with higher APR (positive funding)
                    high, low = (a, b) if a.apr > b.apr else (b, a)
                    net = high.apr - low.apr
                    if abs(net) < min_spread_apr:
                        continue
                    if best is None or abs(net) > abs(best["net_apr"]):
                        best = {
                            "symbol": symbol,
                            "short_venue": high.venue,
                            "short_venue_type": high.venue_type,
                            "short_rate": high.rate,
                            "short_interval_h": high.interval_h,
                            "short_apr": high.apr,
                            "long_venue": low.venue,
                            "long_venue_type": low.venue_type,
                            "long_rate": low.rate,
                            "long_interval_h": low.interval_h,
                            "long_apr": low.apr,
                            "net_apr": net,
                            "mark_price": high.mark_price,
                        }
            if best is not None:
                pairs.append(best)

        pairs.sort(key=lambda p: abs(p["net_apr"]), reverse=True)
        return pairs

    def scan_spot(self, force: bool = False) -> list[SpotPrice]:
        """Fetch spot prices from all spot venues."""
        now = time.time()
        with self._lock:
            if not force and (now - self._last_spot_scan) < self._cache_ttl and self._spot_cache:
                return list(self._spot_cache)
        all_spot: list[SpotPrice] = []
        with ThreadPoolExecutor(max_workers=len(SPOT_FETCHERS)) as ex:
            futures = {ex.submit(fn): name for name, fn in SPOT_FETCHERS.items()}
            for fut in as_completed(futures):
                try:
                    all_spot.extend(fut.result())
                except Exception as e:
                    log.warning("spot_scan: %s failed — %s", futures[fut], e)
        with self._lock:
            self._spot_cache = all_spot
            self._last_spot_scan = now
        return list(all_spot)

    def basis_pairs(self, min_basis_bps: float = 10.0) -> list[dict]:
        """Spot-perp basis: (perp_mark - spot_price) / spot_price in bps."""
        perps = self._cache or self.scan()
        spots = self._spot_cache or self.scan_spot()
        spot_by_sym: dict[str, list[SpotPrice]] = {}
        for s in spots:
            spot_by_sym.setdefault(s.symbol, []).append(s)
        pairs: list[dict] = []
        for p in perps:
            for s in spot_by_sym.get(p.symbol, []):
                if s.price <= 0:
                    continue
                basis_bps = (p.mark_price - s.price) / s.price * 10_000
                if abs(basis_bps) < min_basis_bps:
                    continue
                interval_days = p.interval_h / 24.0
                basis_apr = abs(basis_bps) / 10_000 / max(interval_days, 1/24) * 365 * 100
                pairs.append({
                    "symbol": p.symbol,
                    "venue_perp": p.venue, "venue_spot": s.venue,
                    "mark_price": round(p.mark_price, 4),
                    "spot_price": round(s.price, 4),
                    "basis_bps": round(basis_bps, 2),
                    "basis_apr": round(basis_apr, 1),
                    "volume_perp": p.volume_24h, "volume_spot": s.volume_24h,
                })
        pairs.sort(key=lambda x: abs(x["basis_bps"]), reverse=True)
        return pairs

    def spot_arb_pairs(self, min_spread_bps: float = 5.0) -> list[dict]:
        """Spot-spot spread: price divergence across spot venues in bps."""
        spots = self._spot_cache or self.scan_spot()
        by_sym: dict[str, list[SpotPrice]] = {}
        for s in spots:
            by_sym.setdefault(s.symbol, []).append(s)
        pairs: list[dict] = []
        for symbol, lst in by_sym.items():
            if len(lst) < 2:
                continue
            for i in range(len(lst)):
                for j in range(i + 1, len(lst)):
                    a, b = lst[i], lst[j]
                    if a.venue == b.venue:
                        continue
                    mid = min(a.price, b.price)
                    if mid <= 0:
                        continue
                    spread_bps = abs(a.price - b.price) / mid * 10_000
                    if spread_bps < min_spread_bps:
                        continue
                    hi, lo = (a, b) if a.price >= b.price else (b, a)
                    pairs.append({
                        "symbol": symbol,
                        "venue_a": hi.venue, "venue_b": lo.venue,
                        "price_a": round(hi.price, 4), "price_b": round(lo.price, 4),
                        "spread_bps": round(spread_bps, 2),
                        "volume_a": hi.volume_24h, "volume_b": lo.volume_24h,
                    })
        pairs.sort(key=lambda x: x["spread_bps"], reverse=True)
        return pairs

    # ─ telemetry ────────────────────────────────────────────────
    def stats(self) -> dict:
        with self._lock:
            return {
                "last_scan": self._last_scan,
                "age_s": time.time() - self._last_scan if self._last_scan else None,
                "counts": dict(self._last_counts),
                "errors": dict(self._last_error),
                "total": sum(self._last_counts.values()),
                "venues_online": sum(1 for v in self._last_counts.values() if v > 0),
                "venues_total": len(VENUE_FETCHERS),
                "dex_online": sum(
                    1 for name, c in self._last_counts.items()
                    if c > 0 and VENUE_FETCHERS[name][1] == "DEX"
                ),
                "cex_online": sum(
                    1 for name, c in self._last_counts.items()
                    if c > 0 and VENUE_FETCHERS[name][1] == "CEX"
                ),
            }


# ═══════════════════════════════════════════════════════════════════════
# Optional Telegram alert (throttled)
# ═══════════════════════════════════════════════════════════════════════
def _load_alert_log() -> dict:
    try:
        if _ALERT_LOG_PATH.exists():
            return json.loads(_ALERT_LOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_alert_log(log_data: dict) -> None:
    try:
        _ALERT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _ALERT_LOG_PATH.write_text(
            json.dumps(log_data, indent=2), encoding="utf-8")
    except OSError:
        pass


def maybe_alert_telegram(opps: list[FundingOpp],
                         apr_threshold: float = 100.0) -> int:
    """Fire Telegram alerts for opps above ``apr_threshold``.
    Throttled to at most one alert per symbol:venue every ALERT_THROTTLE_S.
    Uses the bot configured in config/keys.json. Silent no-op otherwise."""
    try:
        keys_path = _ROOT / "config" / "keys.json"
        if not keys_path.exists():
            return 0
        cfg = json.loads(keys_path.read_text(encoding="utf-8"))
        tg = cfg.get("telegram", {}) or {}
        token = tg.get("bot_token") or ""
        chat_id = str(tg.get("chat_id") or "")
        if not (token and chat_id):
            return 0
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return 0

    alert_log = _load_alert_log()
    now = time.time()
    sent = 0

    for opp in opps:
        if abs(opp.apr) < apr_threshold:
            continue
        key = f"{opp.symbol}:{opp.venue}"
        if now - alert_log.get(key, 0) < ALERT_THROTTLE_S:
            continue

        msg = (
            f"🔥 FUNDING {opp.direction}\n"
            f"{opp.symbol} @ {opp.venue} ({opp.venue_type})\n"
            f"Rate: {opp.rate*100:+.4f}%/{opp.interval_h:.0f}h\n"
            f"APR:  {opp.apr:+.0f}%\n"
            f"Vol:  ${opp.volume_24h/1e6:.1f}M  OI: ${opp.open_interest/1e6:.1f}M\n"
            f"Risk: {opp.risk}"
        )
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": msg,
                      "disable_web_page_preview": True},
                timeout=HTTP_TIMEOUT,
            )
            if r.status_code == 200:
                alert_log[key] = now
                sent += 1
        except requests.RequestException as e:
            log.warning("funding_scanner: telegram alert failed — %s", e)

    if sent:
        _save_alert_log(alert_log)
    return sent


# ─── CLI test harness ────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(message)s")
    scanner = FundingScanner()
    print("scanning...")
    t0 = time.time()
    opps = scanner.scan()
    dt = time.time() - t0
    stats = scanner.stats()
    print(f"  {len(opps)} opportunities in {dt:.2f}s")
    print(f"  venues online: {stats['venues_online']}/{stats['venues_total']}"
          f"  (DEX {stats['dex_online']}, CEX {stats['cex_online']})")
    for venue, count in stats["counts"].items():
        err = stats["errors"].get(venue, "")
        tag = f"ERR {err[:60]}" if err else f"{count} opps"
        print(f"    {venue:12s}  {tag}")

    print("\ntop 15 by |APR|:")
    for i, o in enumerate(scanner.top(n=15, min_apr=20.0), 1):
        print(f"  {i:2d}  {o.symbol:10s} {o.venue:12s} ({o.venue_type}) "
              f"{o.rate*100:+.4f}%/{o.interval_h:.0f}h  "
              f"APR={o.apr:+7.1f}%  vol=${o.volume_24h/1e6:6.1f}M  "
              f"{o.risk}")

    for mode in ("dex-dex", "cex-cex", "cex-dex"):
        pairs = scanner.arb_pairs(mode=mode, min_spread_apr=10.0)
        print(f"\n{len(pairs)} arb pairs ({mode}, |net| > 10%):")
        for a in pairs[:8]:
            print(f"  {a['symbol']:10s} "
                  f"SHORT {a['short_venue']:11s} ({a['short_apr']:+6.1f}%)  "
                  f"LONG {a['long_venue']:11s} ({a['long_apr']:+6.1f}%)  "
                  f"net={a['net_apr']:+7.1f}%")
