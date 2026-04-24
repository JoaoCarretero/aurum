# MEANREV Exhaustion/Reversal Grid

> Registro disciplinado da tese de mean reversion por exaustao.
> Data de registro: 2026-04-18.
> Budget fechado antes da bateria: 13 configs.

## Hipotese mecanica

Quando o preco estica demais para longe da media local e o RSI confirma
extremo, a continuidade marginal fica pior e a chance de retorno parcial
para a ancora melhora. A entrada nao deve ser no meio do caminho; deve ser
na exaustao ou no primeiro sinal de reversao apos a exaustao.

## Tese fixa

- Ancora: `EMA50`
- Trigger base: `deviation = (close - ema50) / atr`
- Confirmacao: `RSI extremo`
- Direcao: sempre mean reversion, nunca continuation
- Saida base: alvo na ancora, stop em ATR, time stop

## O que PODE variar

- Distancia minima da exaustao
- Forma de confirmar a reversao
- Geometria de stop/time stop
- Escala de entrada e preco medio
- Assimetria long-only / short-only

## O que NAO pode variar nesta rodada

- Nada de `reverse_direction`
- Nada de trocar a tese para breakout/momentum
- Nada de multi-TF
- Nada de gates macro adicionais
- Nada de trocar universo no meio da bateria

## Universo e janela desta rodada

- Universo: `BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT`
- Horizonte por run: `180d`
- Timeframe: `15m`

## Criterio de score

Ordenacao principal:
1. `expectancy_r`
2. `profit_factor`
3. `sharpe`

Filtros minimos para sobreviver:
- `n_trades >= 100`
- `profit_factor > 1.00`
- `expectancy_r > 0`

## Grid pre-registrado

| Variant | entry_mode | deviation_enter | rsi_long_max | rsi_short_min | atr_stop_mult | time_stop_bars | side_filter | scale_in_levels | scale_in_step_atr |
|---|---|---:|---:|---:|---:|---:|---|---:|---:|
| MR00_baseline_reversal_bar | reversal_bar | 2.0 | 30 | 70 | 2.0 | 96 | both | 1 | 0.75 |
| MR01_touch_entry | touch | 2.0 | 30 | 70 | 2.0 | 96 | both | 1 | 0.75 |
| MR02_close_back_inside | close_back_inside | 2.0 | 30 | 70 | 2.0 | 96 | both | 1 | 0.75 |
| MR03_dev25 | reversal_bar | 2.5 | 30 | 70 | 2.0 | 96 | both | 1 | 0.75 |
| MR04_dev30 | reversal_bar | 3.0 | 30 | 70 | 2.0 | 96 | both | 1 | 0.75 |
| MR05_rsi_25_75 | reversal_bar | 2.0 | 25 | 75 | 2.0 | 96 | both | 1 | 0.75 |
| MR06_stop_25atr | reversal_bar | 2.0 | 30 | 70 | 2.5 | 96 | both | 1 | 0.75 |
| MR07_tstop_48 | reversal_bar | 2.0 | 30 | 70 | 2.0 | 48 | both | 1 | 0.75 |
| MR08_long_only | reversal_bar | 2.0 | 30 | 70 | 2.0 | 96 | long_only | 1 | 0.75 |
| MR09_short_only | reversal_bar | 2.0 | 30 | 70 | 2.0 | 96 | short_only | 1 | 0.75 |
| MR10_scale2_05atr | reversal_bar | 2.0 | 30 | 70 | 2.0 | 96 | both | 2 | 0.50 |
| MR11_scale2_10atr | reversal_bar | 2.0 | 30 | 70 | 2.0 | 96 | both | 2 | 1.00 |
| MR12_scale3_075atr | reversal_bar | 2.0 | 30 | 70 | 2.0 | 96 | both | 3 | 0.75 |

## Regra de parada desta rodada

- Se zero variants passarem os filtros minimos, a tese baseline falha nesta
  forma e a lane deve ser arquivada ou reformulada em nova sessao.
- Se 1-3 variants passarem, elas viram candidatas para etapa seguinte
  (DSR + validacao fora da amostra).
- Nenhuma variant nova entra nesta rodada depois da primeira execucao.
