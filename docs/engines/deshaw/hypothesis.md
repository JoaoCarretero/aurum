# Hipotese - DE SHAW

Registrado em 2026-04-20 antes de qualquer nova bateria da revisao com
macro/HMM/revalidation grace.

## Fenomeno de mercado

Pares grandes de crypto com beta parecido podem abrir desvios temporarios
de spread quando fluxo direcional ou liquidacao empurra uma perna mais do
que a outra. Se a relacao estrutural continua valida, parte desse desvio
reverte nas horas seguintes.

## Mecanismo

A tese nao e "qualquer cointegracao funciona". A tese e mais estreita:
mean reversion de spread so deve existir quando o ambiente agregado nao
esta em tendencia forte. Por isso a entrada nova tenta restringir a
operacao a estados mais proximos de CHOP e bloquear pares que falham
revalidacao repetida. Se o edge existir, o ganho vem de compressao do
spread, nao de carregar momentum de uma das pernas.

## Precedente academico

Pairs trading e stat-arb de spread tem precedente forte em equities e FX.
O ponto fragil em crypto e a menor estabilidade de relacoes entre ativos,
o que exige filtro de regime e revalidacao frequente do par em vez de
assumir cointegracao persistente.

## Falsificacao

Arquivar se qualquer uma destas condicoes aparecer:
- DSR train <= 0.95 apos haircut pelo tamanho real do grid.
- Pior Sharpe do top-3 em test < 1.0.
- Sharpe holdout < 0.8 na janela 2025-01-01 -> 2026-04-20.
- PnL continuar dependente de um subconjunto pequeno de pares ou de um
  unico regime mesmo apos os filtros novos.

## Split hardcoded desta rodada

```python
TRAIN_END = "2024-01-01"
TEST_END = "2025-01-01"
HOLDOUT_START = "2025-01-01"
HOLDOUT_END = "2026-04-20"
```

## Tese fixa

- Engine: `deshaw`
- Familia: spread mean reversion em pares grandes
- Universo: `bluechip`
- Timeframe: `1h`
- Janela por run: `1095d` para calibracao e comparacao disciplinada
- Custos: defaults atuais do engine, sem overrides fora do grid

## O que pode variar nesta rodada

- `NEWTON_ALLOWED_MACRO_ENTRY`
- `NEWTON_MIN_HMM_CHOP_PROB`
- `NEWTON_MAX_HMM_TREND_PROB`
- `NEWTON_MAX_REVALIDATION_MISSES`

## O que nao pode variar nesta rodada

- Nada de trocar universo ou timeframe.
- Nada de liberar entrada em BEAR sem abrir rodada nova.
- Nada de alterar logica de score, sizing ou custos no meio da bateria.
- Nada de adicionar pares customizados depois de ver resultado.
