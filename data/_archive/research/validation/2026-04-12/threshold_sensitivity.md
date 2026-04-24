# Threshold Sensitivity Results

**Date:** 2026-04-12 12:00
**Period:** 180 days

| Param | -20% | BASE | +20% | Sharpe Low | Sharpe Base | Sharpe High | Fragility | Verdict |
|---|---|---|---|---|---|---|---|---|
| SCORE_THRESHOLD | 0.42 | 0.53 | 0.64 | -1.164 | — | 0.665 | None | UNKNOWN |
| STOP_ATR_M | 1.44 | 1.8 | 2.16 | -1.444 | — | 1.882 | None | UNKNOWN |
| TARGET_RR | 1.6 | 2.0 | 2.4 | 0.355 | — | 0.64 | None | UNKNOWN |
| REGIME_MIN_STRENGTH | 0.2 | 0.25 | 0.3 | 0.64 | — | 0.64 | None | UNKNOWN |

## Interpretation
- **ROBUST** (< 15%): Threshold is stable, edge likely real
- **MODERATE** (15-30%): Some sensitivity, monitor in live
- **FRAGILE** (> 30%): Edge may be curve-fitted to this value