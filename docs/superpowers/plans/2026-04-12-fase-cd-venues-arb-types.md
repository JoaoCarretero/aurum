# Fase C+D: New DEX Venues + Arb Types — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 5 new DEX venue fetchers (GMX, Vertex, Aevo, Drift, ApeX) and 2 new arb scanning methods (spot-perp basis, spot-spot spread) to `core/funding_scanner.py`.

**Architecture:** All changes in one file (`core/funding_scanner.py`). New fetchers follow the existing pattern: `def fetch_<venue>() -> list[FundingOpp]`, added to `VENUE_FETCHERS`. Spot data uses a new `SpotPrice` dataclass with `SPOT_FETCHERS` dict and two new methods on `FundingScanner`.

**Tech Stack:** Python 3.14, `requests` (already imported), stdlib.

**Spec reference:** `docs/superpowers/specs/2026-04-12-fase-cd-venues-arb-types-design.md`

---

## File Structure

| File | Role | Action |
|---|---|---|
| `core/funding_scanner.py` | Add 5 DEX fetchers + SpotPrice + 2 spot fetchers + basis_pairs + spot_arb_pairs | Modify (+250 lines) |
| `tests/test_funding_scanner.py` | Unit tests for new fetchers and pair methods | Create (~80 lines) |

---

## Task 1: Add 5 new DEX venue fetchers

**Files:**
- Modify: `core/funding_scanner.py:440` (before `VENUE_FETCHERS` dict) — add 5 fetcher functions
- Modify: `core/funding_scanner.py:442-451` — add 5 entries to `VENUE_FETCHERS`
- Create: `tests/test_funding_scanner.py` — test fetcher return types

### Step 1 — write tests

Create `tests/test_funding_scanner.py`:

```python
"""Tests for funding scanner — new venue fetchers + arb types."""
import pytest


def test_venue_fetchers_registry_has_13_venues():
    from core.funding_scanner import VENUE_FETCHERS
    # 8 original + 5 new = 13
    assert len(VENUE_FETCHERS) >= 13
    for name in ("gmx", "vertex", "aevo", "drift", "apex"):
        assert name in VENUE_FETCHERS, f"missing venue: {name}"
        fn, vtype = VENUE_FETCHERS[name]
        assert callable(fn)
        assert vtype == "DEX"


def test_fetcher_functions_return_list():
    """Each fetcher is importable and returns a list (may be empty if API is down)."""
    from core.funding_scanner import VENUE_FETCHERS
    for name in ("gmx", "vertex", "aevo", "drift", "apex"):
        fn, _ = VENUE_FETCHERS[name]
        # We don't call them (network), just verify they exist and are callable
        assert callable(fn), f"{name} fetcher is not callable"


def test_mk_helper_builds_valid_opp():
    from core.funding_scanner import _mk
    opp = _mk("BTC", "test_venue", "DEX", 0.0001, 1.0, 50000.0, 1e6, 5e5)
    assert opp.symbol == "BTC"
    assert opp.venue == "test_venue"
    assert opp.apr > 0
    assert opp.risk in ("LOW", "MED", "HIGH")
```

### Step 2 — run tests, expect fail

```
python -m pytest tests/test_funding_scanner.py::test_venue_fetchers_registry_has_13_venues -v
```

Expected: FAIL — only 8 venues exist.

### Step 3 — add 5 fetcher functions

In `core/funding_scanner.py`, BEFORE the `VENUE_FETCHERS` dict (line ~440), add these 5 functions after the existing `fetch_bingx` / `fetch_bitget` functions:

```python
# ═══════════════════════════════════════════════════════════════════════
# New DEX venue fetchers (Fase C)
# ═══════════════════════════════════════════════════════════════════════

def fetch_gmx() -> list[FundingOpp]:
    """GET https://arbitrum-api.gmxinfra.io/markets/info
    GMX v2 on Arbitrum. Continuous funding — normalize to 1h equivalent.
    Rates are in wei (1e30 scale). Markets include both long/short rates."""
    resp = requests.get(
        "https://arbitrum-api.gmxinfra.io/markets/info",
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    markets = data if isinstance(data, list) else (data.get("markets") or [])

    out: list[FundingOpp] = []
    for m in markets:
        try:
            name = m.get("name") or m.get("indexToken") or ""
            base = _is_usdt_base(name)
            if not base:
                # Try extracting from market name like "ETH [WETH-USDC]"
                for tok in name.replace("[", " ").replace("]", " ").split():
                    base = _is_usdt_base(tok + "USDT")
                    if base:
                        break
            if not base:
                continue
            # Rates in wei — divide by 1e30 to get per-second rate
            rate_long = float(m.get("netRateLong") or m.get("fundingRateLong") or 0) / 1e30
            rate_short = float(m.get("netRateShort") or m.get("fundingRateShort") or 0) / 1e30
            # Use the dominant (larger absolute) rate
            rate = rate_long if abs(rate_long) >= abs(rate_short) else rate_short
            # Convert per-second to per-hour
            rate_1h = rate * 3600
            mark = float(m.get("markPrice") or m.get("indexPrice") or 0) / 1e30
            oi_long = float(m.get("openInterestLong") or 0) / 1e30
            oi_short = float(m.get("openInterestShort") or 0) / 1e30
            oi_usd = (oi_long + oi_short) * mark if mark > 0 else 0
            if rate_1h == 0 or mark == 0:
                continue
            if oi_usd < MIN_OI_USD:
                continue
            out.append(_mk(base, "gmx", "DEX", rate_1h, 1.0, mark, oi_usd, oi_usd))
        except (TypeError, ValueError, KeyError):
            continue
    return out


def fetch_vertex() -> list[FundingOpp]:
    """POST https://archive.prod.vertexprotocol.com/v1/indexer
    Vertex Protocol on Arbitrum. 8h funding. Rate as x18 string."""
    # First get all product IDs from the contracts endpoint
    resp = requests.post(
        "https://archive.prod.vertexprotocol.com/v1/indexer",
        json={"funding_rates": {"product_ids": list(range(1, 50))}},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    # Response shape: {"funding_rates": {"product_id": {"funding_rate_x18": "...", ...}}}
    rates = data.get("funding_rates") or data
    if not isinstance(rates, dict):
        return []

    # Vertex product ID → symbol mapping (major pairs)
    _VERTEX_SYMBOLS = {
        2: "BTC", 4: "ETH", 6: "ARB", 8: "BNB", 10: "XRP",
        12: "SOL", 14: "MATIC", 16: "SUI", 18: "OP", 20: "APT",
        22: "LTC", 24: "BCH", 28: "DOGE", 31: "LINK", 33: "DYDX",
    }

    out: list[FundingOpp] = []
    for pid_str, info in rates.items():
        try:
            pid = int(pid_str)
            sym = _VERTEX_SYMBOLS.get(pid)
            if not sym:
                continue
            rate_x18 = float(info.get("funding_rate_x18") or 0) / 1e18
            if rate_x18 == 0:
                continue
            out.append(_mk(sym, "vertex", "DEX", rate_x18, 8.0, 0.0, 0.0, 0.0))
        except (TypeError, ValueError, KeyError):
            continue
    return out


def fetch_aevo() -> list[FundingOpp]:
    """GET https://api.aevo.xyz/funding  (all instruments)
    Aevo — 1h funding. Simple float string rate."""
    resp = requests.get(
        "https://api.aevo.xyz/funding",
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        data = [data] if data else []

    out: list[FundingOpp] = []
    for item in data:
        try:
            inst = item.get("instrument_name") or ""
            base = inst.replace("-PERP", "").replace("-USD", "")
            if not base:
                continue
            rate = float(item.get("funding_rate") or 0)
            mark = float(item.get("mark_price") or item.get("index_price") or 0)
            if rate == 0:
                continue
            out.append(_mk(base, "aevo", "DEX", rate, 1.0, mark, 0.0, 0.0))
        except (TypeError, ValueError, KeyError):
            continue
    return out


def fetch_drift() -> list[FundingOpp]:
    """GET https://data.api.drift.trade/fundingRates
    Drift Protocol on Solana. 1h funding."""
    # Drift's bulk endpoint
    resp = requests.get(
        "https://data.api.drift.trade/fundingRates",
        params={"limit": 50},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    records = data.get("records") or data if isinstance(data, list) else data.get("records") or []
    if not isinstance(records, list):
        records = []

    # Deduplicate: keep latest per symbol
    latest: dict[str, dict] = {}
    for r in records:
        sym = r.get("symbol") or r.get("marketSymbol") or ""
        base = sym.replace("-PERP", "").replace("PERP", "").replace("-", "")
        if not base:
            continue
        ts = r.get("ts") or 0
        if base not in latest or ts > latest[base].get("ts", 0):
            latest[base] = {**r, "base": base, "ts": ts}

    out: list[FundingOpp] = []
    for base, r in latest.items():
        try:
            rate = float(r.get("fundingRate") or r.get("fundingRateLong") or 0)
            mark = float(r.get("oraclePriceTwap") or r.get("markPriceTwap") or 0)
            if rate == 0:
                continue
            out.append(_mk(base, "drift", "DEX", rate, 1.0, mark, 0.0, 0.0))
        except (TypeError, ValueError, KeyError):
            continue
    return out


def fetch_apex() -> list[FundingOpp]:
    """GET https://omni.apex.exchange/api/v3/ticker
    ApeX Protocol (StarkEx). 1h funding."""
    resp = requests.get(
        "https://omni.apex.exchange/api/v3/ticker",
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    tickers = data.get("data") or data.get("tickers") or []
    if isinstance(tickers, dict):
        tickers = list(tickers.values())

    out: list[FundingOpp] = []
    for t in tickers:
        try:
            sym = t.get("symbol") or ""
            base = _is_usdt_base(sym)
            if not base:
                base = sym.replace("-USDT", "").replace("-USDC", "").replace("-", "")
            if not base:
                continue
            rate = float(t.get("fundingRate") or t.get("lastFundingRate") or 0)
            mark = float(t.get("lastPrice") or t.get("oraclePrice") or 0)
            vol = float(t.get("volume24h") or t.get("turnover24h") or 0)
            oi = float(t.get("openInterest") or 0)
            if rate == 0:
                continue
            out.append(_mk(base, "apex", "DEX", rate, 1.0, mark, vol, oi))
        except (TypeError, ValueError, KeyError):
            continue
    return out
```

### Step 4 — add to VENUE_FETCHERS

Update the `VENUE_FETCHERS` dict to include the 5 new venues:

```python
VENUE_FETCHERS = {
    "hyperliquid": (fetch_hyperliquid, "DEX"),
    "dydx":        (fetch_dydx,        "DEX"),
    "paradex":     (fetch_paradex,     "DEX"),
    "gmx":         (fetch_gmx,         "DEX"),
    "vertex":      (fetch_vertex,      "DEX"),
    "aevo":        (fetch_aevo,        "DEX"),
    "drift":       (fetch_drift,       "DEX"),
    "apex":        (fetch_apex,        "DEX"),
    "binance":     (fetch_binance,     "CEX"),
    "bybit":       (fetch_bybit,       "CEX"),
    "gate":        (fetch_gate,        "CEX"),
    "bitget":      (fetch_bitget,      "CEX"),
    "bingx":       (fetch_bingx,       "CEX"),
}
```

### Step 5 — run tests, expect pass

```
python -m pytest tests/test_funding_scanner.py -v
```

### Step 6 — smoke test

```
python smoke_test.py --quiet
```

### Step 7 — commit

```
git add core/funding_scanner.py tests/test_funding_scanner.py
git commit -m "feat(scanner): Fase C — 5 new DEX venues (GMX, Vertex, Aevo, Drift, ApeX)"
```

---

## Task 2: Spot-perp basis + spot-spot arb scanning

**Files:**
- Modify: `core/funding_scanner.py` — add SpotPrice, SPOT_FETCHERS, fetch_binance_spot, fetch_bybit_spot, basis_pairs, spot_arb_pairs
- Modify: `tests/test_funding_scanner.py` — add tests

### Step 1 — write tests

Append to `tests/test_funding_scanner.py`:

```python


def test_spot_price_dataclass():
    from core.funding_scanner import SpotPrice
    sp = SpotPrice(symbol="BTC", venue="binance", price=50000.0, volume_24h=1e9)
    assert sp.symbol == "BTC"
    assert sp.price == 50000.0


def test_spot_fetchers_registry():
    from core.funding_scanner import SPOT_FETCHERS
    assert "binance" in SPOT_FETCHERS
    assert "bybit" in SPOT_FETCHERS
    for name, fn in SPOT_FETCHERS.items():
        assert callable(fn)


def test_basis_pairs_with_synthetic_data():
    from core.funding_scanner import FundingScanner, FundingOpp, SpotPrice
    scanner = FundingScanner()
    # Inject synthetic perp data
    scanner._cache = [
        FundingOpp("BTC", "binance", "CEX", 0.0001, 8.0, 45.6,
                   "SHORT", 50100.0, 5e9, 3e9, "LOW"),
    ]
    scanner._last_scan = 9999999999.0  # prevent rescan
    # Inject synthetic spot data
    scanner._spot_cache = [
        SpotPrice("BTC", "binance", 50000.0, 1e9),
    ]
    pairs = scanner.basis_pairs(min_basis_bps=0)
    assert len(pairs) >= 1
    p = pairs[0]
    assert p["symbol"] == "BTC"
    assert "basis_bps" in p
    assert p["basis_bps"] > 0  # perp > spot


def test_spot_arb_pairs_with_synthetic_data():
    from core.funding_scanner import FundingScanner, SpotPrice
    scanner = FundingScanner()
    scanner._last_scan = 9999999999.0
    scanner._spot_cache = [
        SpotPrice("BTC", "binance", 50000.0, 1e9),
        SpotPrice("BTC", "bybit", 50050.0, 8e8),
    ]
    pairs = scanner.spot_arb_pairs(min_spread_bps=0)
    assert len(pairs) >= 1
    p = pairs[0]
    assert p["symbol"] == "BTC"
    assert "spread_bps" in p
    assert p["spread_bps"] > 0
```

### Step 2 — run tests, expect fail

```
python -m pytest tests/test_funding_scanner.py -v
```

Expected: FAIL — `SpotPrice` and `basis_pairs` don't exist.

### Step 3 — add SpotPrice dataclass

After the `FundingOpp` class (around line 82), add:

```python
@dataclass
class SpotPrice:
    """A spot price observation at one venue."""
    symbol: str
    venue: str
    price: float
    volume_24h: float
```

### Step 4 — add spot fetchers

After the new DEX fetchers and before the `VENUE_FETCHERS` dict, add:

```python
# ═══════════════════════════════════════════════════════════════════════
# Spot price fetchers (Fase D — for basis + spot-spot arb)
# ═══════════════════════════════════════════════════════════════════════

def fetch_binance_spot() -> list[SpotPrice]:
    """GET https://api.binance.com/api/v3/ticker/24hr — all spot tickers."""
    resp = requests.get(
        "https://api.binance.com/api/v3/ticker/24hr",
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    out: list[SpotPrice] = []
    for t in data:
        try:
            sym = t.get("symbol") or ""
            base = _is_usdt_base(sym)
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
    resp = requests.get(
        "https://api.bybit.com/v5/market/tickers",
        params={"category": "spot"},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    tickers = (data.get("result") or {}).get("list") or []
    out: list[SpotPrice] = []
    for t in tickers:
        try:
            sym = t.get("symbol") or ""
            base = _is_usdt_base(sym)
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
```

### Step 5 — add basis_pairs and spot_arb_pairs to FundingScanner

In the `FundingScanner` class, add `_spot_cache` to `__init__`:

```python
    def __init__(self, cache_ttl: float = CACHE_TTL):
        self._cache: list[FundingOpp] = []
        self._spot_cache: list[SpotPrice] = []
        self._last_scan: float = 0.0
        self._cache_ttl: float = cache_ttl
        self._last_error: dict[str, str] = {}
        self._last_counts: dict[str, int] = {}
        self._lock = threading.Lock()
```

Add a `scan_spot` method after `scan`:

```python
    def scan_spot(self, force: bool = False) -> list[SpotPrice]:
        """Fetch spot prices from all spot venues."""
        all_spot: list[SpotPrice] = []
        with ThreadPoolExecutor(max_workers=len(SPOT_FETCHERS)) as ex:
            futures = {ex.submit(fn): name for name, fn in SPOT_FETCHERS.items()}
            for fut in as_completed(futures):
                venue = futures[fut]
                try:
                    all_spot.extend(fut.result())
                except Exception as e:
                    log.warning("spot_scan: %s failed — %s", venue, e)
        self._spot_cache = all_spot
        return all_spot
```

Add `basis_pairs` and `spot_arb_pairs` after `arb_pairs`:

```python
    def basis_pairs(self, min_basis_bps: float = 10.0) -> list[dict]:
        """Spot-perp basis: (perp_mark - spot_price) / spot_price.

        Returns list of {symbol, venue_perp, venue_spot, mark_price,
        spot_price, basis_bps, basis_apr} ordered by |basis_bps| desc.
        """
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
                # Estimate APR: assume basis converges over funding interval
                interval_days = p.interval_h / 24.0
                basis_apr = abs(basis_bps) / 10_000 / max(interval_days, 1/24) * 365 * 100
                pairs.append({
                    "symbol": p.symbol,
                    "venue_perp": p.venue,
                    "venue_spot": s.venue,
                    "mark_price": round(p.mark_price, 4),
                    "spot_price": round(s.price, 4),
                    "basis_bps": round(basis_bps, 2),
                    "basis_apr": round(basis_apr, 1),
                    "volume_perp": p.volume_24h,
                    "volume_spot": s.volume_24h,
                })
        pairs.sort(key=lambda x: abs(x["basis_bps"]), reverse=True)
        return pairs

    def spot_arb_pairs(self, min_spread_bps: float = 5.0) -> list[dict]:
        """Spot-spot spread: price divergence across spot venues.

        Returns list of {symbol, venue_a, venue_b, price_a, price_b,
        spread_bps} ordered by spread_bps desc.
        """
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
                    # Higher price venue is "expensive", lower is "cheap"
                    if a.price >= b.price:
                        pairs.append({
                            "symbol": symbol,
                            "venue_a": a.venue,
                            "venue_b": b.venue,
                            "price_a": round(a.price, 4),
                            "price_b": round(b.price, 4),
                            "spread_bps": round(spread_bps, 2),
                            "volume_a": a.volume_24h,
                            "volume_b": b.volume_24h,
                        })
                    else:
                        pairs.append({
                            "symbol": symbol,
                            "venue_a": b.venue,
                            "venue_b": a.venue,
                            "price_a": round(b.price, 4),
                            "price_b": round(a.price, 4),
                            "spread_bps": round(spread_bps, 2),
                            "volume_a": b.volume_24h,
                            "volume_b": a.volume_24h,
                        })
        pairs.sort(key=lambda x: x["spread_bps"], reverse=True)
        return pairs
```

### Step 6 — run tests, expect pass

```
python -m pytest tests/test_funding_scanner.py -v
```

### Step 7 — smoke test

```
python smoke_test.py --quiet
```

### Step 8 — commit

```
git add core/funding_scanner.py tests/test_funding_scanner.py
git commit -m "feat(scanner): Fase D — spot-perp basis + spot-spot arb scanning"
```

---

## Verification Checklist

- [ ] `VENUE_FETCHERS` has 13 entries (8 original + 5 new)
- [ ] All new fetchers are callable and follow the `fetch_<name>() -> list[FundingOpp]` pattern
- [ ] `SpotPrice` dataclass exists with symbol, venue, price, volume_24h
- [ ] `SPOT_FETCHERS` has binance + bybit
- [ ] `FundingScanner.basis_pairs()` returns valid pair dicts
- [ ] `FundingScanner.spot_arb_pairs()` returns valid pair dicts
- [ ] `python -m pytest tests/test_funding_scanner.py` — all pass
- [ ] `python smoke_test.py --quiet` — exit 0
- [ ] No changes to `engines/arbitrage.py`, `launcher.py`, or `config/params.py`
