# Ablation Test Results

**Date:** 2026-04-12 11:49
**Period:** 180 days
**Holdout:** 0% (full IS for ablation comparison)

| Component OFF | Trades | WR | PnL | Sharpe | MaxDD | ΔPnL vs Base |
|---|---|---|---|---|---|---|
| BASELINE | 257 | 53.7% | $+453 | 0.640 | 6.6% | +0.0% noise |
| -struct | 0 | 0.0% | $+0 | 0.000 | 0.0% | -100.0% **CORE** |
| -flow | 3 | 66.7% | $+506 | 2.144 | 0.5% | +11.7% noise/negative |
| -cascade | 1828 | 54.2% | $-3,189 | -1.955 | 44.5% | -804.0% **CORE** |
| -momentum | 44 | 61.4% | $+204 | 0.788 | 4.9% | -55.0% **CORE** |
| -pullback | 88 | 62.5% | $+858 | 2.103 | 3.5% | +89.4% noise/negative |

## Interpretation
- **ΔPnL < -20%**: Component is CORE — removing it kills the edge
- **ΔPnL -5% to -20%**: Component contributes but is not essential
- **ΔPnL ±5%**: Component is noise — candidate for removal
- **ΔPnL > +5%**: Component hurts performance — should be removed