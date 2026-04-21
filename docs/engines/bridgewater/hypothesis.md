# Hipotese - BRIDGEWATER

Registrado em 2026-04-21 antes de qualquer nova rodada de tuning no path
disciplinado `robust`.

## Fenomeno de mercado

Extremos de sentiment derivado de funding e long/short ratio tendem a
anteceder reversoes de curto prazo quando o mercado ja esta esticado e o
fluxo marginal perde capacidade de empurrar preco. O engine tenta capturar
essa exaustao de crowd em cesta cross-sectional, nao uma previsao macro
discricionaria.

## Mecanismo

A tese valida do momento e mais estreita do que a versao historica do
engine: funding + LS funcionam como sensores de crowding, enquanto open
interest so entra como pesquisa separada porque a cobertura recente mostrou
drift de qualidade. O edge esperado aparece quando:
- a leitura e contrarian e direcionalmente clara;
- o ambiente macro nao esta em tendencia limpa de alta;
- o filtro tecnico confirma que a estrutura ja aceita a reversao.

## Precedente academico

Funding e posicionamento agregado ja sao usados como proxies de crowding em
perpetual futures. A parte menos trivial aqui e o uso cross-sectional em
crypto, onde a persistencia do edge depende mais de qualidade de serie e de
regime do que de um sinal universal. Por isso a rodada atual congela a tese
em `funding + LS`, com OI fora do caminho principal.

## Falsificacao

Arquivar ou manter em quarentena se qualquer uma destas condicoes aparecer:
- DSR train <= 0.95 no grid fechado.
- Pior Sharpe do top-3 em test < 1.0.
- Sharpe holdout recente < 0.8.
- Variantes com `symbol_health` ou `cooldown` continuarem piorando a base.
- O path simples (`robust`, `BEAR,CHOP`, sem OI) perder para variantes mais
  complexas apenas em uma janela isolada, sem repeticao no corte seguinte.

## Split hardcoded desta rodada

```python
TRAIN_END = "2026-03-31"
TEST_END = "2026-04-10"
HOLDOUT_START = "2026-04-10"
HOLDOUT_END = "2026-04-20"
```

Observacao:
- este split e curto por restricao honesta de cobertura OI/LS;
- qualquer extensao para janelas antigas exige primeiro ampliar cache
  continuo e reabrir a rodada do zero.

## Tese fixa

- Engine: `bridgewater`
- Familia: sentiment contrarian cross-sectional
- Universo: `bluechip`
- Timeframe: `1h`
- Preset base: `robust`
- Canais promotaveis nesta rodada: `funding + LS`

## O que pode variar nesta rodada

- `min_components`
- `min_dir_thresh`
- `enable_symbol_health`
- `post_trade_cooldown_bars`

## O que nao pode variar nesta rodada

- Nada de reabilitar OI no path principal.
- Nada de trocar basket ou timeframe.
- Nada de mexer em score, lifecycle ou custos.
- Nada de abrir variantes fora da tabela apos ver os primeiros resultados.
