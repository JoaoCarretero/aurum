# BRIDGEWATER Diagnostic

- Date: `2026-04-13`
- Engine: `BRIDGEWATER` / `engines/thoth.py`
- Validation run: `python tools/engine_validation.py --days 90 --basket default --leverage 1.0`
- Outcome: `failed`

## Observed Run Result

- Universe: `default`
- Assets attempted: `11`
- Closed trades produced: `0`
- Failure summary: `Run completed but produced no closed trades.`

## External Data Symptoms Seen In Run

- `OI INJUSDT: HTTP 202`
- `OI RENDERUSDT: HTTP 202`
- `OI SUIUSDT: HTTP 202`
- `OI NEARUSDT: HTTP 202`
- `OI BNBUSDT: HTTP 202`
- `OI ARBUSDT: HTTP 202`
- `OI FETUSDT: HTTP 202`
- `OI SANDUSDT: HTTP 202`
- `OI OPUSDT: HTTP 202`
- `OI LINKUSDT`: read timeout at `10s`
- `OI XRPUSDT`: remote disconnected without response

## Code-Level Findings

- Funding source:
  - `https://fapi.binance.com/fapi/v1/fundingRate`
- Open interest source:
  - `https://fapi.binance.com/futures/data/openInterestHist`
- Long/short ratio source:
  - `https://fapi.binance.com/futures/data/globalLongShortAccountRatio`
- Request timeout on all three fetches: `10` seconds
- Internal rate-limit gap: `_REQ_GAP = 0.15` seconds between requests

## Relevant Code References

- [engines/thoth.py](/C:/Users/Joao/OneDrive/aurum.finance/engines/thoth.py:68): sentiment collection per symbol
- [engines/thoth.py](/C:/Users/Joao/OneDrive/aurum.finance/engines/thoth.py:129): uses `funding_z`, `oi_df`, `ls_signal`
- [core/sentiment.py](/C:/Users/Joao/OneDrive/aurum.finance/core/sentiment.py:27): funding fetch
- [core/sentiment.py](/C:/Users/Joao/OneDrive/aurum.finance/core/sentiment.py:52): OI history fetch
- [core/sentiment.py](/C:/Users/Joao/OneDrive/aurum.finance/core/sentiment.py:79): long/short ratio fetch
- [core/sentiment.py](/C:/Users/Joao/OneDrive/aurum.finance/core/sentiment.py:17): `_REQ_GAP = 0.15`

## Interpretation

- The engine is operational enough to fetch price data, build the sentiment pipeline, and complete a full run over the basket.
- The main blocker is degraded external OI availability, not an internal exception.
- The absence of closed trades can be explained by one or both of these conditions:
  - OI-dependent sentiment inputs are missing for most symbols because the upstream endpoint returns `HTTP 202` or times out.
  - The remaining sentiment stack is insufficient to produce entries that later close within the run.

## Classification Today

- Status: `⚠ diagnostic`
- Plain-language status: `engine runs, but the current external OI feed is unstable and the run ends with 0 closed trades`
- Not attempted here:
  - no endpoint swap
  - no timeout tuning
  - no symbol filtering
  - no threshold or weighting changes
