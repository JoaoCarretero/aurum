# Hipotese - PHI reopen 2026-04-21

## Fenomeno de mercado
Em majors muito liquidos, impulsos direcionais fortes tendem a aceitar pullbacks rasos em vez de reversoes completas. Quando o preco revisita uma zona de retracao proxima do fib 0.618 recente com volatilidade ainda expansionista e liquidez suficiente para absorver a contra-parte, a continuacao do impulso pode dominar a reversao local.

## Por que funciona
O mecanismo nao e "fib magico". O fib funciona aqui apenas como aproximacao operacional de uma zona onde participantes de tendencia reentram apos um pullback curto. Em majors, books mais fundos reduzem micro-gap espurio e permitem que o mesmo padrao de continuation apareca em varios ativos. Se a tese existir, ela deve sobreviver com filtros simples: confluencia rasa, regime levemente tendencial e gatilho de rejeicao sem apertar dezenas de parametros.

## Precedente academico
Nao ha motivo academico forte para acreditar em edge por numeros de Fibonacci isoladamente. O suporte teorico vem de continuation apos pullback em mercados com tendencia e friccao limitada, nao da razao 0.618 em si. Portanto a calibracao precisa provar que o uso do nivel como aproximacao operacional melhora resultados OOS em majors liquidos; se isso nao ocorrer, a tese esta falsa.

## Falsificacao
Se o melhor candidato em train nao atingir confianca DSR > 0.95 e Sharpe deflacionado >= 1.5, PHI falha antes do test. Se os top-3 por Sharpe deflacionado nao sustentarem Sharpe >= 1.0 no pior caso do test, PHI falha. Se o unico candidato escolhido cair abaixo de Sharpe 0.8 no holdout, PHI continua arquivado.
