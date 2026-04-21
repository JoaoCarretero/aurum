# Hipotese - ORNSTEIN salvage attempt

Registrado em 2026-04-21 antes da bateria desta sessao.

## Fenomeno de mercado

Em cripto 15m, reversao curta tende a aparecer quando o preco fica
estatisticamente deslocado da ancora local, mas a confirmacao por consenso
fractal de 5 timeframes pode ser muito rara. O proprio desvio assinado ja
carrega a direcao mean-reversion; o que precisa ser validado e o regime,
nao uma segunda camada combinatoria de direcao.

## Por que pode funcionar

Se a serie de desvio realmente estiver em regime mean-reverting, a bateria
OU/ADF/VR/Bollinger deve bastar para separar "mola esticada" de breakout.
Nesse caso, remover o gate de divergencia como fonte unica de direcao deve
liberar sample sem transformar o engine em trend-following, porque a
direcao continua sendo o fade do desvio e os filtros estatisticos seguem
ativos.

## Precedente interno

O historico de 2026-04-17/18 mostrou dois extremos ruins: com divergencia
fractal estrita o engine zerava sample; com thresholds soltos ainda
ancorados na divergencia, o sample aparecia mas o Sharpe ficava fortemente
negativo. Tambem ficou registrado que `disable_divergence` era no-op
conceitual, porque a direcao do trade vinha exclusivamente de
`div_direction`.

## Falsificacao

Esta hipotese falha se, mesmo apos tornar o modo sem divergencia funcional,
nenhum config do grid fechado produzir edge defensavel nas janelas
train/test/holdout abaixo. Criterio objetivo:

- DSR train <= 0.95 ou Sharpe train <= 1.5: falha.
- Pior Sharpe dos top-3 no test < 1.0: falha.
- Sharpe holdout do config escolhido < 0.8: falha.

Se qualquer condicao ocorrer, ORNSTEIN continua arquivado como lane de mean
reversion.
