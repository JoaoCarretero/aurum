# Hipotese - KEPOS

Registrado em 2026-04-20 antes de qualquer bateria com os gates novos de
RSI/HMM/cooldown.

## Fenomeno de mercado

Eventos de agressao de fluxo podem produzir extensoes curtas demais para
continuar no mesmo sentido quando o regime agregado nao confirma tendencia
persistente. Nesses casos, parte do movimento volta rapido para o centro
local.

## Mecanismo

O edge candidato do KEPOS e mean reversion apos burst auto-excitante. Os
novos filtros tentam separar dois cenarios:
1. exaustao real de curto prazo em mercado lateral, onde o fade faz sentido;
2. ruptura com continuidade, onde o fade drena capital.
RSI, HMM e cooldown so sao defensaveis se reduzirem exatamente o segundo
caso sem matar todo o sample do primeiro.

## Precedente academico

Hawkes e processos auto-excitantes sao usados para modelar clusterizacao
de eventos e propagacao de fluxo. O salto da teoria para esta implementacao
so se sustenta se o burst vier acompanhado de sinais de exaustao local,
nao apenas de intensidade alta.

## Falsificacao

Arquivar se:
- O ganho dos filtros vier com colapso de sample (`n_trades < 100`).
- DSR train <= 0.95 no grid fechado.
- O top-3 em test nao sustentar Sharpe >= 1.0.
- Holdout 2025-01-01 -> 2026-04-20 cair abaixo de Sharpe 0.8.

## Split hardcoded desta rodada

```python
TRAIN_END = "2024-01-01"
TEST_END = "2025-01-01"
HOLDOUT_START = "2025-01-01"
HOLDOUT_END = "2026-04-20"
```

## Tese fixa

- Engine: `kepos`
- Familia: fade de burst auto-excitante
- Universo: `bluechip`
- Timeframe: `15m`
- Janela por run: `1095d`
- Direcao: `invert_direction=False` fixa nesta rodada

## O que pode variar nesta rodada

- `rsi_exhaustion_level`
- `min_reentry_cooldown_bars`
- `hmm_min_prob_chop`
- `hmm_max_trend_prob`
- `tp_atr_mult`

## O que nao pode variar nesta rodada

- Nada de ligar `invert_direction` nesta bateria principal.
- Nada de trocar universo, timeframe ou logica Hawkes.
- Nada de adicionar filtros macro extras fora dos parametros acima.
- Nada de desligar HMM depois de ver resultado; isso exigiria rodada nova.
