# ORNSTEIN Recalibration - 2026-04-21

## Executive summary

Decision: `archive confirmed`.

The 2026-04-21 salvage round reopened ORNSTEIN under the anti-overfit
protocol with a fixed split and a closed 5-config grid. The only material
code correction was methodological: when `disable_divergence=True`, trade
direction now comes from signed deviation instead of silently depending on
`div_direction`.

That fix did not reveal edge. In train, strict variants still produced
`0 trades`; the only variant that opened sample (`O01 exploratory`) traded
heavily but collapsed with `Sharpe -31.979`, `PF 0.307`, `Exp(R) -0.468`,
`MaxDD 8.92%`.

By protocol, `test` and `holdout` were not run.

## Registered split

- `train`: 180d ending `2025-10-21`
- `test`: 90d ending `2026-01-19`
- `holdout`: ending `2026-04-21`
- universe: `BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT`

## Closed grid result

| ID | Reading |
|---|---|
| `O00 default` | `0 trades` |
| `O01 exploratory` | `2115 trades`, `Sharpe -31.979` |
| `O02 exploratory + disable_divergence` | `0 trades` |
| `O03 O02 + RSI 35/65 + omega 55` | `0 trades` |
| `O04 O02 + ADF 0.10 + halflife 50 + omega 60` | `0 trades` |

## Interpretation

The family remains trapped in the same binary observed earlier:

1. Tight filters choke sample to zero.
2. Loose filters admit a large amount of anti-edge flow.
3. Making divergence ablation honest did not uncover a hidden mean-reverting
   pocket robust enough to promote.

## Objective verdict

- `archive confirmed`
- reopening again only makes sense with a new mechanism, not more threshold
  iteration on the same lane
