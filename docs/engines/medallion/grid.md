# Grid pre-registrado - MEDALLION

Registrado em 2026-04-20.
Budget fechado: 8 configs.

## Baseline desta rodada

- `z_entry_min=1.2`
- `ensemble_threshold=0.45`
- `min_active_components=4`
- `kelly_fraction=0.25`
- `hmm_exit_trend_prob=0.75`

## Grid fechado

| # | Variant | z_entry_min | ensemble_threshold | min_active_components | kelly_fraction | hmm_exit_trend_prob |
|---|---|---:|---:|---:|---:|---:|
| 1 | MED00_baseline | 1.2 | 0.45 | 4 | 0.25 | 0.75 |
| 2 | MED01_entry_tighter | 1.4 | 0.45 | 4 | 0.25 | 0.75 |
| 3 | MED02_entry_looser | 1.0 | 0.45 | 4 | 0.25 | 0.75 |
| 4 | MED03_threshold_tighter | 1.2 | 0.55 | 4 | 0.25 | 0.75 |
| 5 | MED04_threshold_looser | 1.2 | 0.35 | 4 | 0.25 | 0.75 |
| 6 | MED05_components_tighter | 1.2 | 0.45 | 5 | 0.25 | 0.75 |
| 7 | MED06_kelly_lower | 1.2 | 0.45 | 4 | 0.15 | 0.75 |
| 8 | MED07_hmm_exit_earlier | 1.2 | 0.45 | 4 | 0.25 | 0.65 |

## Regras desta rodada

- Ordenacao principal por DSR-adjusted Sharpe em train.
- Filtros minimos:
  - `n_trades >= 120`
  - `profit_factor > 1.0`
  - `expectancy_r > 0`
- Se as configs mais apertadas vencerem so reduzindo sample, considerar
  isso falha de mecanismo e nao sucesso.
- Nenhuma variante fora da tabela entra depois da primeira execucao.
