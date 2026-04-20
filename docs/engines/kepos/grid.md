# Grid pre-registrado - KEPOS

Registrado em 2026-04-20.
Budget fechado: 8 configs.

## Baseline desta rodada

- `rsi_exhaustion_level=8.0`
- `min_reentry_cooldown_bars=6`
- `hmm_min_prob_chop=0.35`
- `hmm_max_trend_prob=0.60`
- `tp_atr_mult=1.8`

## Grid fechado

| # | Variant | rsi_exhaustion | cooldown_bars | hmm_min_prob_chop | hmm_max_trend_prob | tp_atr |
|---|---|---:|---:|---:|---:|---:|
| 1 | KEP00_baseline | 8.0 | 6 | 0.35 | 0.60 | 1.8 |
| 2 | KEP01_rsi_looser | 6.0 | 6 | 0.35 | 0.60 | 1.8 |
| 3 | KEP02_rsi_tighter | 10.0 | 6 | 0.35 | 0.60 | 1.8 |
| 4 | KEP03_cooldown_short | 8.0 | 3 | 0.35 | 0.60 | 1.8 |
| 5 | KEP04_cooldown_long | 8.0 | 9 | 0.35 | 0.60 | 1.8 |
| 6 | KEP05_hmm_looser | 8.0 | 6 | 0.30 | 0.65 | 1.8 |
| 7 | KEP06_hmm_tighter | 8.0 | 6 | 0.40 | 0.55 | 1.8 |
| 8 | KEP07_takeprofit_longer | 8.0 | 6 | 0.35 | 0.60 | 2.4 |

## Regras desta rodada

- Ordenacao principal por DSR-adjusted Sharpe em train.
- Filtros minimos:
  - `n_trades >= 100`
  - `profit_factor > 1.0`
  - `expectancy_r > 0`
- Se `KEP07_takeprofit_longer` ganhar so no train e voltar a colapsar no
  multi-ano, repetir o veredito de 2026-04-16: pico local, nao edge robusto.
- Nenhuma config fora da tabela entra depois da primeira execucao.
