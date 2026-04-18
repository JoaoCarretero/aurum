# MEANREV Partial-Revert Exit Grid

> Terceira hipotese mecanica separada.
> Registrado em 2026-04-18 apos falha das grades de exaustao simples e
> snapback/rejection com alvo na media.
> Budget fechado: 8 configs.

## Hipotese mecanica

Pode existir reversao curta sem full mean reversion. O trigger de exaustao
ou rejeicao pode acertar a direcao, mas exigir alvo na EMA50 talvez esteja
transformando trades que tinham edge curto em trades devolvidos ao mercado.
Esta rodada testa se o edge vive em `snapback parcial`, nao em volta total.

## Tese fixa

- Direcao: mean reversion apenas
- Universo: majors 5-pack
- Timeframe: 15m
- Entradas herdadas dos candidatos menos ruins anteriores
- Mudanca central: take-profit parcial do deslocamento

## Filtros minimos

- `n_trades >= 100`
- `profit_factor > 1.00`
- `expectancy_r > 0`

## Grid pre-registrado

| Variant | entry_mode | side_filter | scale_in_levels | scale_in_step_atr | atr_stop_mult | time_stop_bars | target_mode | target_reclaim_frac |
|---|---|---|---:|---:|---:|---:|---|---:|
| PR00_short_partial_25 | reversal_bar | short_only | 1 | 0.75 | 2.0 | 96 | partial_revert | 0.25 |
| PR01_short_partial_50 | reversal_bar | short_only | 1 | 0.75 | 2.0 | 96 | partial_revert | 0.50 |
| PR02_short_partial_75 | reversal_bar | short_only | 1 | 0.75 | 2.0 | 96 | partial_revert | 0.75 |
| PR03_wick_both_scale2_25 | wick_reclaim | both | 2 | 0.50 | 2.0 | 48 | partial_revert | 0.25 |
| PR04_wick_both_scale2_50 | wick_reclaim | both | 2 | 0.50 | 2.0 | 48 | partial_revert | 0.50 |
| PR05_wick_long_25 | wick_reclaim | long_only | 1 | 0.75 | 2.0 | 48 | partial_revert | 0.25 |
| PR06_wick_long_50 | wick_reclaim | long_only | 1 | 0.75 | 2.0 | 48 | partial_revert | 0.50 |
| PR07_wick_short_scale2_25 | wick_reclaim | short_only | 2 | 0.50 | 2.0 | 48 | partial_revert | 0.25 |

## Regra de parada

- Se zero variants sobreviverem, a lane mean reversion por single-asset
  stretch/rejection fica falsificada nesta familia de sinais.
- Nenhuma variant nova entra apos a primeira execucao.
