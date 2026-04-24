# RENAISSANCE Audit

- Date: `2026-04-13`
- Engine: `RENAISSANCE`
- Source artifact: `data/renaissance/2026-04-13_1540/reports/renaissance_15m_v1.json`
- Artifact headline metrics:
  - Trades: `88`
  - WR: `85.23%`
  - PnL: `$+346.14`
  - Sharpe: `4.705`
  - Sortino: `4.801`
  - MaxDD: `0.55%`

## Executive Verdict

- Verdict: `suspicious`
- Reason:
  - the saved trade list does **not** support the reported `85.23%` win rate
  - recomputing from the `trades` array yields `54` wins and `34` losses, or `61.36%`
  - drawdown does look internally consistent with the trade list
  - there is no obvious forced-close artifact, no duplicate rows, and no single huge PnL outlier dominating the run

Working interpretation:
- This looks less like a fake-equity bug and more like a reporting inconsistency between top-level summary fields and the underlying trade list.

## Recomputed Statistics From Trade List

- Total trades: `88`
- Wins: `54`
- Losses: `34`
- Zero-PnL trades: `0`
- Recomputed WR: `61.36%`
- Reported WR in artifact: `85.23%`
- Total PnL: `$346.14`
- Average PnL per trade: `$3.93`
- Median PnL per trade: `$4.97`
- Average win: `$12.56`
- Average loss: `$-9.77`
- Profit factor: `2.04`
- Recomputed max drawdown: `0.5492%`
- Reported max drawdown: `0.55%`
- Negative equity steps: `34`

## Audit Questions

### 1. Forced-close / mark-to-market exits

- Forced-close-like trades detected by text scan: `0`
- Fields scanned:
  - `exit_reason`
  - `reason`
  - `close_reason`
  - `result_reason`
  - `tag`
  - `notes`
  - `status`

Interpretation:
- No explicit `forced_close`, `mtm`, or `mark-to-market` style labels are present in the saved trade rows.
- That does not prove such exits never occur in code, but this artifact does not expose them.

### 2. Equity curve realism

- Equity curve is `not monotonic`
- Negative steps: `34`
- Recomputed drawdown matches the artifact closely

Interpretation:
- The curve is plausibly noisy.
- The low drawdown is unusually good, but it is not contradicted by the trade sequence itself.

### 3. Trade concentration

- Trades are not dominated by 1-2 symbols.
- Top 5 symbols by trade count:
  - `FETUSDT`: `13` trades (`14.77%`)
  - `ARBUSDT`: `13` trades (`14.77%`)
  - `SANDUSDT`: `8` trades (`9.09%`)
  - `NEARUSDT`: `8` trades (`9.09%`)
  - `RENDERUSDT`: `8` trades (`9.09%`)

Interpretation:
- Symbol distribution is broad enough that concentration is not the main explanation.

### 4. PnL and sizing sanity

- Largest winner: `$57.68`
- Largest loser: `$-41.40`
- No single trade dominates the total result.

- `size` distribution is highly heterogeneous:
  - min: `0.5775`
  - max: `44281.5756`
  - avg: `6440.8854`

Interpretation:
- PnL distribution is sane enough on its face.
- The `size` field is not directly comparable across symbols and may represent units rather than normalized USD exposure.
- This is a residual audit risk, but not the strongest red flag in the file.

### 5. Duplicate / overlapping / repeated trade patterns

- Duplicate full trade rows: `0`
- Duplicate `(symbol, timestamp)` rows: `0`
- Repeated exact PnL values appearing 3+ times: `0`
- Pattern mix:
  - `Gartley`: `61`
  - `Bat`: `27`

Interpretation:
- No obvious duplicate-row inflation was found.
- No repeated timestamp duplication suggests straightforward overcounting is unlikely from raw duplication.

### 6. Does max drawdown look believable?

- Yes, relative to the trade list.
- Recomputed `0.5492%` matches reported `0.55%`.

Interpretation:
- The drawdown number itself appears credible.
- The stronger concern is the mismatch in win-rate reporting, not the drawdown math.

### 7. Does win rate align with trade-level PnL distribution?

- Yes for the recomputed `61.36%` WR.
- No for the reported `85.23%` WR.

Interpretation:
- With average win `$12.56`, average loss `$-9.77`, and profit factor `2.04`, a `61.36%` WR is plausible.
- An `85.23%` WR would imply about `75` wins out of `88`, which the trade list does not support.

### 8. Any sign of overcounting wins or undercounting losses?

- There is no obvious duplication or missing-loss pattern in the raw `trades` array.
- The suspicious element is the top-level summary field, not the raw rows.

Interpretation:
- Current evidence points to `summary/reporting inconsistency` rather than `trade-list inflation`.

## Top 10 Symbols By Trade Count And PnL

| Symbol | Trades | WR | PnL |
|---|---:|---:|---:|
| FETUSDT | 13 | 61.54% | $171.02 |
| ARBUSDT | 13 | 30.77% | $-39.63 |
| SANDUSDT | 8 | 87.50% | $95.44 |
| NEARUSDT | 8 | 100.00% | $62.04 |
| RENDERUSDT | 8 | 25.00% | $-35.12 |
| OPUSDT | 7 | 100.00% | $92.05 |
| LINKUSDT | 7 | 71.43% | $27.57 |
| INJUSDT | 7 | 57.14% | $24.80 |
| BNBUSDT | 6 | 50.00% | $1.26 |
| SUIUSDT | 6 | 50.00% | $-43.45 |

## Largest Winners

| Symbol | Timestamp | Pattern | Dir | PnL | Size | Duration |
|---|---|---|---|---:|---:|---:|
| FETUSDT | 2026-03-29T00:15:00 | Bat | BULLISH | $57.68 | 7623.99 | 17 |
| FETUSDT | 2026-03-15T22:15:00 | Gartley | BULLISH | $47.15 | 10530.40 | 26 |
| OPUSDT | 2026-03-02T08:00:00 | Bat | BULLISH | $33.53 | 13778.24 | 11 |
| FETUSDT | 2026-01-16T04:45:00 | Gartley | BULLISH | $29.32 | 10969.12 | 3 |
| ARBUSDT | 2026-02-06T23:00:00 | Bat | BEARISH | $27.75 | 28672.18 | 4 |

## Largest Losers

| Symbol | Timestamp | Pattern | Dir | PnL | Size | Duration |
|---|---|---|---|---:|---:|---:|
| SUIUSDT | 2026-02-17T05:30:00 | Gartley | BULLISH | $-41.40 | 2440.50 | 36 |
| ARBUSDT | 2026-03-31T12:00:00 | Bat | BEARISH | $-35.57 | 28965.98 | 5 |
| FETUSDT | 2026-02-10T22:30:00 | Gartley | BEARISH | $-31.62 | 22313.74 | 8 |
| ARBUSDT | 2026-02-23T06:15:00 | Bat | BEARISH | $-30.88 | 17871.57 | 12 |
| LINKUSDT | 2026-03-08T07:15:00 | Gartley | BEARISH | $-25.97 | 334.45 | 11 |

## Suspicious Patterns

- Major red flag: top-level `win_rate` field does not match the trade list.
- Secondary red flag: `size` spans from `<1` to `44k+`, which makes cross-symbol exposure interpretation unclear.
- Not found:
  - monotonic equity
  - duplicate trade rows
  - duplicate symbol/timestamp rows
  - repeated exact PnL clusters suggesting templated rows
  - a single outlier trade dominating the run

## Final Classification

- Classification: `suspicious`
- Most likely issue class: `reporting / aggregation inconsistency`
- Not enough evidence to call it `likely bug-inflated` at the PnL level.
- Not clean enough to call it simply `plausible`.
