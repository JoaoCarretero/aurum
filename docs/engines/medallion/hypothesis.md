# Hipotese - MEDALLION

Registrado em 2026-04-20 antes de qualquer nova bateria com
`min_active_components`, HMM exit e haircut adaptativo de Kelly.

## Fenomeno de mercado

Retornos muito estendidos no curtissimo prazo tendem a devolver parte do
movimento quando a extensao acontece sem regime de tendencia persistente e
com confirmacoes locais de exaustao. O alvo e reversao parcial, nao retorno
completo ao valor justo.

## Mecanismo

MEDALLION tenta combinar varias pistas fracas de exaustao para evitar
operar um unico indicador isolado. Os knobs novos so sao defensaveis se
melhorarem seletividade sem transformar o ensemble em um filtro
super-especifico de amostra. `min_active_components` e `exit_on_hmm_trend`
precisam provar que cortam cenarios ruins recorrentes, nao que apenas
reduzem trades ate sobrar um subgrupo historicamente favoravel.

## Precedente academico

Curto prazo mean reversion em overextension tem precedente amplo em market
microstructure e liquidity provision. O risco classico e virar um ensemble
de confirmation bias com muitos gates levemente correlacionados.

## Falsificacao

Arquivar se:
- DSR train <= 0.95 com o grid real.
- O top-3 em test falhar Sharpe >= 1.0.
- Holdout 2025-01-01 -> 2026-04-20 ficar abaixo de Sharpe 0.8.
- A melhora vier quase toda de queda de sample ou de um unico simbolo.

## Split hardcoded desta rodada

```python
TRAIN_END = "2024-01-01"
TEST_END = "2025-01-01"
HOLDOUT_START = "2025-01-01"
HOLDOUT_END = "2026-04-20"
```

## Tese fixa

- Engine: `medallion`
- Familia: partial mean reversion de curto prazo
- Universo: `bluechip`
- Timeframe: `15m`
- Janela por run: `1095d`
- Direcao: `invert_direction=False` fixa nesta rodada

## O que pode variar nesta rodada

- `z_entry_min`
- `ensemble_threshold`
- `min_active_components`
- `kelly_fraction`
- `hmm_exit_trend_prob`

## O que nao pode variar nesta rodada

- Nada de desligar HMM para resgatar sample.
- Nada de trocar universo, timeframe ou pesos do ensemble.
- Nada de ativar `invert_direction`.
- Nada de mexer em stops/cooldown/TP nesta rodada; isso exigiria bateria nova.
