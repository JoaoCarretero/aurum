# Grid pre-registrado - GRAHAM

Registrado em 2026-04-21.
Budget fechado: 8 configs.

## Baseline desta rodada

Baseline = ultima tentativa manual reaberta em `4h bluechip`, com o mesmo
trigger local e o mesmo gate Hawkes, incluindo a incoerencia conhecida entre
entrada e saida de regime.

## Grid fechado

| # | Variant | eta_lower | eta_upper | eta_exit_lower | eta_exit_sustained | slope_min_abs | structure_min_count |
|---|---|---:|---:|---:|---:|---:|---:|
| 1 | GR00_baseline_incoherent | 0.65 | 0.90 | 0.75 | 2 | 0.0008 | 2 |
| 2 | GR01_exit_floor_match | 0.65 | 0.90 | 0.65 | 2 | 0.0008 | 2 |
| 3 | GR02_exit_floor_buffer | 0.65 | 0.90 | 0.62 | 2 | 0.0008 | 2 |
| 4 | GR03_exit_floor_match_exit3 | 0.65 | 0.90 | 0.65 | 3 | 0.0008 | 2 |
| 5 | GR04_exit_floor_buffer_exit3 | 0.65 | 0.90 | 0.62 | 3 | 0.0008 | 2 |
| 6 | GR05_match_stronger_slope | 0.65 | 0.90 | 0.65 | 3 | 0.0012 | 2 |
| 7 | GR06_match_stronger_structure | 0.65 | 0.90 | 0.65 | 3 | 0.0008 | 3 |
| 8 | GR07_tighter_upper_match | 0.65 | 0.85 | 0.65 | 3 | 0.0012 | 2 |

## Regras desta rodada

- ordenacao principal por DSR em train;
- nenhuma variante fora da tabela entra depois da primeira execucao;
- se todas falharem em train, test e holdout nao serao rodados;
- se alguma passar em train, o top-3 segue para test sem reordenacao manual;
- se a baseline continuar liderando mesmo com o lifecycle incoerente, a tese
  de "edge escondido no lifecycle" esta rejeitada;
- se a melhora vier concentrada em um unico simbolo, a leitura e archive e
  nao promocao.
