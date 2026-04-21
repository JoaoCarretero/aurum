# Hipotese - GRAHAM

Registrado em 2026-04-21 antes de qualquer nova rodada de tuning.

## Fenomeno de mercado

Tendencias em cripto podem continuar por algumas barras quando o fluxo entra
em regime endogeno moderado: o proprio fluxo recente alimenta novas ordens na
mesma direcao, mas ainda sem a exaustao extrema que costuma preceder fades.
GRAHAM tenta capturar essa continuidade apenas quando o regime Hawkes e
compativel com propagacao de tendencia, e nao em qualquer cruzamento de EMA.

## Mecanismo

A tese reaberta desta rodada e mais estreita que a versao arquivada:
- `eta` nao e o sinal primario; ele e um gate de persistencia de fluxo;
- o trigger continua sendo tendencia local (EMA + slope + estrutura);
- a investigacao foca no lifecycle, porque a ultima rodada relaxou
  `eta_lower` para 0.65 mas manteve `eta_exit_lower` em 0.75, criando um
  stop estrutural de regime que cortava trades logo apos a entrada.

Se essa incoerencia de ciclo estava escondendo edge real, variantes com banda
de saida coerente devem melhorar Sharpe e reduzir a concentracao de trades de
1 barra sem precisar inventar novos sinais.

## Precedente academico

Processos Hawkes sao usados para modelar auto-excitacao e endogeneidade em
microestrutura. A parte defensavel aqui nao e "Hawkes prediz retorno" e sim
"quando o mercado esta moderadamente endogeno, choques de tendencia tendem a
se propagar por algumas barras". Em candle-level crypto isso so sobrevive se o
gate de regime e o lifecycle forem coerentes; caso contrario o modelo vira um
detector caro de entradas que ele mesmo cancela.

## Falsificacao

Arquivar novamente se qualquer uma destas condicoes aparecer:
- melhor config do grid fechado tiver DSR train <= 0.95;
- melhor config do grid fechado tiver Sharpe train < 1.5;
- top-3 nao mostrar robustez consistente entre si no train;
- se passar train, pior Sharpe dos top-3 em test < 1.0;
- se passar test, Sharpe holdout < 0.8.

Se a melhora vier so de um simbolo isolado ou de uma variante claramente mais
complexa sem repeticao OOS, a leitura correta continua sendo archive.

## Split hardcoded desta rodada

```python
TRAIN_END = "2024-06-01T00:00:00"
TEST_END = "2025-04-01T00:00:00"
HOLDOUT_END = "2026-04-20T20:00:00"
```

## Universo e tese fixa

- Engine: `graham`
- Familia: endogenous momentum com gate Hawkes
- Basket nominal: `bluechip`
- Universo efetivo desta rodada: subset `bluechip_4h_stable`
- Simbolos: `BTC, ETH, BNB, SOL, XRP, ADA, AVAX, LINK, DOT, ATOM, NEAR, INJ, ARB, OP, SUI, FET, SAND, AAVE`
- Timeframe: `4h`

## O que pode variar nesta rodada

- coerencia entre `eta_lower` e `eta_exit_lower`
- `eta_exit_sustained`
- severidade de confirmacao de tendencia (`slope_min_abs`, `structure_min_count`)
- largura superior do gate `eta_upper`

## O que nao pode variar nesta rodada

- nada de trocar basket ou timeframe;
- nada de trocar o signal base por outro paradigma;
- nada de mexer em custo, sizing global ou portfolio core;
- nada de adicionar variantes fora da tabela apos a primeira execucao.
