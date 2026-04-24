# MEANREV Snapback/Rejection Grid

> Segunda hipotese mecanica separada da rodada anterior.
> Registrado em 2026-04-18 apos falha da grade de exaustao simples.
> Budget fechado: 10 configs.

## Hipotese mecanica

Mean reversion nao ocorre so porque o preco ficou longe da media no
fechamento. O que pode gerar edge e o "blowoff + rejeicao": o candle estica
forte para longe da media intrabar, encontra exaustao e fecha recuperando
parte relevante do movimento. Isso tenta capturar capitulacao e fade de
spike, nao apenas distancia estatica para EMA50.

## Tese fixa

- Ancora: `EMA50`
- Confirmacao: `RSI extremo`
- Direcao: sempre mean reversion
- Trigger estrutural: overshoot intrabar + reclaim
- Saida: alvo na ancora, stop em ATR, time stop

## O que muda nesta rodada

- Modo de confirmacao: `wick_reclaim` vs `extreme_reclaim`
- Distancia do blowoff
- Intensidade minima do reclaim
- Assimetria long/short
- Escala de entrada

## O que NAO muda

- Nada de `reverse_direction`
- Nada de trocar universo
- Nada de gates macro/vol extras
- Nada de multi-TF

## Universo e janela

- Universo: `BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT`
- Horizonte: `180d`
- Timeframe: `15m`

## Filtros minimos

- `n_trades >= 100`
- `profit_factor > 1.00`
- `expectancy_r > 0`

## Grid pre-registrado

| Variant | entry_mode | deviation_enter | reclaim_atr_min | reclaim_deviation_exit | rsi_long_max | rsi_short_min | atr_stop_mult | time_stop_bars | side_filter | scale_in_levels | scale_in_step_atr |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|
| SB00_wick_both | wick_reclaim | 2.0 | 0.75 | 1.0 | 30 | 70 | 2.0 | 48 | both | 1 | 0.75 |
| SB01_wick_both_strict | wick_reclaim | 2.5 | 1.00 | 1.0 | 30 | 70 | 2.0 | 48 | both | 1 | 0.75 |
| SB02_wick_short_only | wick_reclaim | 2.0 | 0.75 | 1.0 | 30 | 70 | 2.0 | 48 | short_only | 1 | 0.75 |
| SB03_wick_short_strict | wick_reclaim | 2.5 | 1.00 | 1.0 | 30 | 75 | 2.0 | 48 | short_only | 1 | 0.75 |
| SB04_wick_short_stop25 | wick_reclaim | 2.0 | 0.75 | 1.0 | 30 | 70 | 2.5 | 48 | short_only | 1 | 0.75 |
| SB05_extreme_reclaim_both | extreme_reclaim | 2.0 | 0.75 | 1.0 | 30 | 70 | 2.0 | 48 | both | 1 | 0.75 |
| SB06_extreme_reclaim_short | extreme_reclaim | 2.0 | 0.75 | 0.5 | 30 | 70 | 2.0 | 48 | short_only | 1 | 0.75 |
| SB07_wick_both_scale2 | wick_reclaim | 2.0 | 0.75 | 1.0 | 30 | 70 | 2.0 | 48 | both | 2 | 0.50 |
| SB08_wick_short_scale2 | wick_reclaim | 2.0 | 0.75 | 1.0 | 30 | 70 | 2.0 | 48 | short_only | 2 | 0.50 |
| SB09_wick_long_only | wick_reclaim | 2.0 | 0.75 | 1.0 | 30 | 70 | 2.0 | 48 | long_only | 1 | 0.75 |

## Regra de parada

- Se zero variants sobreviverem, esta segunda hipotese falha e a lane mean
  reversion deve ser arquivada nesta familia de sinais.
- Nenhuma variant nova entra nesta rodada apos a primeira execucao.
