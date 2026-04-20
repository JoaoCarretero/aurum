# Grid pre-registrado - DE SHAW

Registrado em 2026-04-20.
Budget fechado: 8 configs.

## Baseline desta rodada

A baseline e o estado atual da tese com gates novos:
- `NEWTON_ALLOWED_MACRO_ENTRY=CHOP,BULL`
- `NEWTON_MIN_HMM_CHOP_PROB=0.35`
- `NEWTON_MAX_HMM_TREND_PROB=0.55`
- `NEWTON_MAX_REVALIDATION_MISSES=1`

## Grid fechado

| # | Variant | allowed_macro_entry | min_hmm_chop_prob | max_hmm_trend_prob | max_revalidation_misses |
|---|---|---|---:|---:|---:|
| 1 | DSH00_baseline | CHOP,BULL | 0.35 | 0.55 | 1 |
| 2 | DSH01_chop_only | CHOP | 0.35 | 0.55 | 1 |
| 3 | DSH02_hmm_looser | CHOP,BULL | 0.30 | 0.60 | 1 |
| 4 | DSH03_hmm_tighter | CHOP,BULL | 0.40 | 0.50 | 1 |
| 5 | DSH04_no_grace | CHOP,BULL | 0.35 | 0.55 | 0 |
| 6 | DSH05_chop_only_no_grace | CHOP | 0.35 | 0.55 | 0 |
| 7 | DSH06_chop_only_tighter | CHOP | 0.40 | 0.50 | 1 |
| 8 | DSH07_chop_only_looser | CHOP | 0.30 | 0.60 | 1 |

## Regras desta rodada

- Ordenacao principal por DSR-adjusted Sharpe em train.
- Filtros minimos antes de promover qualquer config:
  - `n_trades >= 80`
  - `profit_factor > 1.0`
  - `expectancy_r > 0`
- Nenhuma variante fora da tabela entra depois da primeira execucao.
- Se nenhuma variante sobreviver com DSR honesto, a revisao macro/HMM
  deve ser arquivada como gating cosmetico sem edge novo.
