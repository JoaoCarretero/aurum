# Grid pre-registrado - BRIDGEWATER

Registrado em 2026-04-21.
Budget fechado: 8 configs.

## Baseline desta rodada

Baseline = melhor path recente documentado em
`docs/audits/2026-04-20_bridgewater_recalibration.md`:
- `preset=robust`
- `allowed_regimes=BEAR,CHOP`
- `min_components=2`
- `min_dir_thresh=0.30`
- `strict_direction=true`
- sem `symbol_health`
- sem cooldown extra

## Grid fechado

| # | Variant | preset | allowed_regimes | min_components | min_dir_thresh | strict_direction | symbol_health | cooldown |
|---|---|---|---|---:|---:|---|---|---:|
| 1 | BW00_baseline | robust | BEAR,CHOP | 2 | 0.30 | on | off | 0 |
| 2 | BW01_thresh_035 | robust | BEAR,CHOP | 2 | 0.35 | on | off | 0 |
| 3 | BW02_thresh_040 | robust | BEAR,CHOP | 2 | 0.40 | on | off | 0 |
| 4 | BW03_components_3 | robust | BEAR,CHOP | 3 | 0.30 | on | off | 0 |
| 5 | BW04_health_on | robust | BEAR,CHOP | 2 | 0.30 | on | on | 0 |
| 6 | BW05_cooldown_4 | robust | BEAR,CHOP | 2 | 0.30 | on | off | 4 |
| 7 | BW06_thresh_035_components_3 | robust | BEAR,CHOP | 3 | 0.35 | on | off | 0 |
| 8 | BW07_thresh_035_health_on | robust | BEAR,CHOP | 2 | 0.35 | on | on | 0 |

## Regras desta rodada

- Ordenacao principal por DSR-adjusted Sharpe em train.
- Nenhuma variante com OI entra neste grid; isso segue em branch de pesquisa
  separado (`oi_research`).
- Nenhuma variante fora da tabela entra depois da primeira execucao.
- Se a baseline continuar vencendo, a leitura correta e simplificar, nao
  inventar mais knobs.
- Se todas falharem no split recente, o veredito continua `keep_quarantine`
  e a proxima prioridade vira ampliar cache historico antes de qualquer novo
  tuning.
