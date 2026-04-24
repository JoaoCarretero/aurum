# OOS Revalidation Gate — 2026-04-17

Generated: `2026-04-17T11:19:38`

Baseline source: persisted runs cited in `docs/audits/2026-04-16_oos_verdict.md`.

## Reproducibility

| Engine | Regime | Match | Sharpe baseline | Sharpe fresh | Field fails |
| --- | --- | --- | --- | --- | --- |
| CITADEL | BEAR | FAIL | 5.677 | 2.149 | 10 |
| CITADEL | BULL | no-baseline | — | — | — |
| CITADEL | CHOP | no-baseline | — | — | — |
| RENAISSANCE | BEAR | FAIL | 2.421 | 6.673 | 10 |
| RENAISSANCE | BULL | no-baseline | — | — | — |
| RENAISSANCE | CHOP | no-baseline | — | — | — |
| JUMP | BEAR | FAIL | 3.15 | 3.149 | 6 |
| JUMP | BULL | no-baseline | — | — | — |
| JUMP | CHOP | no-baseline | — | — | — |
| BRIDGEWATER | BEAR | FAIL | 11.04 | 4.934 | 10 |
| BRIDGEWATER | BULL | no-baseline | — | — | — |
| BRIDGEWATER | CHOP | no-baseline | — | — | — |

## Cost Symmetry

| Engine | All cost tokens present | Found | Scanned files | Suspicious lines |
| --- | --- | --- | --- | --- |
| CITADEL | yes | SLIPPAGE, SPREAD, COMMISSION, FUNDING_PER_8H | engines\citadel.py | — |
| RENAISSANCE | yes | SLIPPAGE, SPREAD, COMMISSION, FUNDING_PER_8H | core\harmonics.py, engines\renaissance.py | — |
| JUMP | yes | SLIPPAGE, SPREAD, COMMISSION, FUNDING_PER_8H | engines\jump.py | — |
| BRIDGEWATER | yes | SLIPPAGE, SPREAD, COMMISSION, FUNDING_PER_8H | engines\bridgewater.py | — |

## Multi-Window Summary

| Engine | Regime | Sharpe | Sortino | ROI% | Trades |
| --- | --- | --- | --- | --- | --- |
| CITADEL | BEAR | 2.149 | 2.831 | 11.400 | 140 |
| CITADEL | BULL | 2.810 | 3.750 | 11.320 | 82 |
| CITADEL | CHOP | 4.842 | 7.333 | 6.170 | 10 |
| RENAISSANCE | BEAR | 6.673 | 7.191 | 23.880 | 242 |
| RENAISSANCE | BULL | 5.949 | 6.970 | 23.350 | 225 |
| RENAISSANCE | CHOP | -0.040 | -0.027 | -0.030 | 16 |
| JUMP | BEAR | 3.149 | 6.150 | 12.140 | 110 |
| JUMP | BULL | 3.187 | 14.797 | 21.530 | 136 |
| JUMP | CHOP | 4.268 | 9.629 | 32.740 | 231 |
| BRIDGEWATER | BEAR | 4.934 | 9.219 | 80.660 | 4037 |
| BRIDGEWATER | BULL | 8.723 | 20.803 | 145.670 | 3390 |
| BRIDGEWATER | CHOP | 4.981 | 10.118 | 48.340 | 1526 |

## Look-Ahead Scan

### CITADEL
- No direct match for `.shift(-N)`, `iloc[i+...]`, `future_`, `ahead_`, or `peek_`.

### RENAISSANCE
- No direct match for `.shift(-N)`, `iloc[i+...]`, `future_`, `ahead_`, or `peek_`.

### JUMP
- No direct match for `.shift(-N)`, `iloc[i+...]`, `future_`, `ahead_`, or `peek_`.

### BRIDGEWATER
- No direct match for `.shift(-N)`, `iloc[i+...]`, `future_`, `ahead_`, or `peek_`.

## Methodology Risks

### CITADEL
- No additional engine-specific methodology risk detected by static scan.

### RENAISSANCE
- No additional engine-specific methodology risk detected by static scan.

### JUMP
- No additional engine-specific methodology risk detected by static scan.

### BRIDGEWATER
- LIVE_SENTIMENT_UNBOUNDED: fetch_funding_rate has no historical end/start parameter.
- LIVE_SENTIMENT_UNBOUNDED: fetch_open_interest has no historical end/start parameter.
- LIVE_SENTIMENT_UNBOUNDED: fetch_long_short_ratio has no historical end/start parameter.

## Final Revised Verdict

| Engine | Verdict |
| --- | --- |
| CITADEL | EDGE_REAL |
| RENAISSANCE | EDGE_REAL |
| JUMP | EDGE_REAL |
| BRIDGEWATER | INVALID_OOS_LIVE_SENTIMENT |

## Notes

- Reproducibility tolerance: `±0.1%` on normalized summary fields.
- `KEPOS` and `MEDALLION` use nested payloads in `summary.json`; the tool unwraps `summary` and enriches `period_days`, `interval`, and `basket` from `meta`/`params`.
- Missing baseline windows stay available for future expansion.
- BRIDGEWATER follow-up forensics were documented separately in
  `docs/audits/2026-04-17_bridgewater_forensics.md`; the dedicated session kept
  the Block 0 verdict unchanged and concluded `CORRIGIR E REVALIDAR EM OUTRA SESSÃO`.
