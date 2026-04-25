# Fase C+D: New DEX Venues + Spot-Perp/Spot-Spot Arb Types

## Goal

1. **Fase C**: Add 5 new DEX venue fetchers to `core/funding_scanner.py`
2. **Fase D**: Add spot-perp basis trade scanning and spot-spot spread scanning

## Non-Goals

- No UI changes (scanner/hub already render whatever data the scanner returns)
- No execution logic changes
- No changes to scoring engine (it works on any dict with the right fields)

---

## Fase C: New DEX Venues

Add fetchers for: GMX v2, Vertex, Aevo, Drift, ApeX.

Each fetcher follows the existing pattern:
- `def fetch_<venue>() -> list[FundingOpp]`
- HTTP GET/POST to public API (no auth)
- Parse response, build FundingOpp via `_mk()`
- Add to `VENUE_FETCHERS` dict

### Venue Details

| Venue | Endpoint | Interval | Notes |
|-------|----------|----------|-------|
| GMX v2 | `GET https://arbitrum-api.gmxinfra.io/markets/info` | continuous (normalize to 1h) | Rates in wei, need /1e30 |
| Vertex | `POST https://archive.prod.vertexprotocol.com/v1/indexer` | 8h | Rate ×10^18 string |
| Aevo | `GET https://api.aevo.xyz/funding?instrument_name={SYM}-PERP` | 1h | Simple float string |
| Drift | `GET https://data.api.drift.trade/market/{SYM}-PERP/fundingRates?limit=1` | 1h | Latest rate |
| ApeX | `GET https://omni.apex.exchange/api/v3/history-funding?symbol={SYM}-USDT` | 1h | `rate` field |

All added as `"DEX"` venue type except ApeX which is `"DEX"` (StarkEx-based).

### Symbols

Use the existing `SCAN_SYMBOLS` list from `funding_scanner.py`. Each fetcher
queries the API and maps to normalized USDT symbols.

---

## Fase D: Spot-Perp Basis + Spot-Spot

### Spot Price Data

New `SpotPrice` dataclass:
```python
@dataclass
class SpotPrice:
    symbol: str
    venue: str
    price: float
    volume_24h: float
```

New `SPOT_FETCHERS` dict with spot price fetchers for Binance and Bybit
(the two largest spot venues with public APIs):
- `fetch_binance_spot()` → `GET https://api.binance.com/api/v3/ticker/24hr`
- `fetch_bybit_spot()` → `GET https://api.bybit.com/v5/market/tickers?category=spot`

### Basis Pairs

New method `basis_pairs(min_basis_bps=10)`:
- For each symbol, match perp mark_price (from existing scan) with spot price
- Basis = (perp_mark - spot_price) / spot_price * 10000 (in bps)
- Returns list of dicts: `{symbol, venue_perp, venue_spot, mark_price, spot_price, basis_bps, basis_apr}`
- `basis_apr = basis_bps / 10000 * 365 / funding_interval_days * 100`

### Spot-Spot Pairs

New method `spot_arb_pairs(min_spread_bps=5)`:
- Group spot prices by symbol
- For each pair of venues, compute spread = |price_a - price_b| / min(price_a, price_b) * 10000
- Returns list of dicts: `{symbol, venue_a, venue_b, price_a, price_b, spread_bps}`

---

## Files Changed

| File | Action | Lines est. |
|------|--------|-----------|
| `core/funding_scanner.py` | Add 5 fetchers + SpotPrice + SPOT_FETCHERS + basis_pairs + spot_arb_pairs | +250 |
| `tests/test_funding_scanner.py` | New test file for fetcher + pair logic | +80 |
| `smoke_test.py` | Verify new fetchers don't crash on import | +1 |
