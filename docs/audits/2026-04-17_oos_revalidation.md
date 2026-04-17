# OOS Revalidation Gate — 2026-04-17

Generated: `2026-04-17T11:08:00`

Este documento fecha o Bloco 0 com separação explícita entre:

1. **Gate histórico reproduzido**: o estado validado contra o audit de `2026-04-16`.
2. **Matriz multi-window no HEAD atual**: BEAR/BULL/CHOP rodados após commits
   posteriores já terem entrado no branch.

Essa separação é obrigatória para honestidade metodológica. O branch foi
contaminado por fixes pós-gate (`9b41c76`, `18db6dc`, `77e4088` e outros), então
o BEAR re-rodado no HEAD atual **não substitui** a evidência histórica do gate.

## 1. Gate Histórico vs 2026-04-16

Fonte: `docs/audits/_revalidation_repro.txt` e runs persistidos de `2026-04-16`.

| Engine | Repro 2026-04-17 09:29 | Nota |
| --- | --- | --- |
| CITADEL | PASS | bateu exato no gate original |
| RENAISSANCE | PASS | bateu exato no gate original |
| JUMP | PASS | bateu exato no gate original |
| DE SHAW | PASS | bateu exato no gate original |
| BRIDGEWATER | FAIL | Sharpe parecido, `n_trades` divergente; depois bug de sentiment foi confirmado |
| KEPOS | PASS | 0 trades no gate original |
| MEDALLION | PASS | bateu exato no gate original |

**Leitura correta:** o gate original era reproduzível para 6/7 antes dos fixes
posteriores. O que mudou depois disso deve ser tratado como **drift de branch**,
não como "o audit de ontem estava errado" por default.

## 2. Multi-Window no HEAD Atual

Raw outputs:

- `data/audit/oos_revalidate_bear_2022.json`
- `data/audit/oos_revalidate_bull_2020.json`
- `data/audit/oos_revalidate_chop_2019.json`

Tabela: `Sharpe / n_trades / ROI%`

| Engine | BEAR 2022 | BULL 2020-07..2021-07 | CHOP 2019-06..2020-03 | Leitura |
| --- | --- | --- | --- | --- |
| CITADEL | 2.149 / 140 / 11.40 | 2.810 / 82 / 11.32 | 4.842 / 10 / 6.17 | positivo em 3/3, mas CHOP sem amostra |
| RENAISSANCE | 6.673 / 242 / 23.88 | 5.949 / 225 / 23.35 | -0.040 / 16 / -0.03 | positivo em trend, CHOP sem amostra |
| JUMP | 3.149 / 110 / 12.14 | 3.187 / 136 / 21.53 | 4.268 / 231 / 32.74 | positivo em 3/3 com amostra |
| DE SHAW | 1.324 / 80 / 3.19 | 0.899 / 15 / 1.11 | 1.400 / 10 / 1.50 | sinais positivos só com branch drift + baixa amostra fora BEAR |
| BRIDGEWATER | 4.934 / 4037 / 80.66 | 8.723 / 3390 / 145.67 | 4.981 / 1526 / 48.34 | continua implausível |
| KEPOS | 0.645 / 7 / 4.66 | -0.248 / 18 / -2.61 | 0.000 / 0 / 0.00 | amostra insuficiente |
| MEDALLION | -3.305 / 172 / -38.51 | -0.778 / 173 / -10.71 | -0.783 / 61 / -4.13 | negativo em todas |

**Regra de amostra:** qualquer janela com `< 50` trades fica
`INSUFFICIENT_SAMPLE`; não é base para chamar de "colapso" nem para promover
engine quebrada a edge real.

## 3. Cost / Look-Ahead / Bug Notes

### Cost symmetry

- Audit estático detalhado: `docs/audits/_revalidation_costs.txt`
- `KEPOS` e `MEDALLION` tinham assimetria real de custo no entry path.
- O diff cirúrgico já existe no histórico em `18db6dc`:
  - 2 arquivos alterados
  - 22 inserções / 8 deleções
  - mudança local em `_pnl_with_costs()` de cada engine
  - impacto esperado explicitado no commit: ~3 bps por trade a mais no entry,
    reduzindo Sharpe in-sample alguns décimos
- Como essa mudança já foi aterrissada fora do escopo do gate puro, o veredito
  final destes dois engines deve ser conservador: **não promover**, apenas
  registrar que o histórico anterior estava inflado.

### Look-ahead

- Scanner e classificação manual: `docs/audits/_revalidation_lookahead.txt`
- Veredito: **0 leaks confirmados**
- Padrão dominante `open[t+1]` continua classificado como execução na próxima
  barra, não look-ahead.

### BRIDGEWATER

- `9b41c76` corrigiu `end_time_ms` nas fetches de sentiment.
- `77e4088` ajustou limites/escala do sentiment para a janela OOS.
- Mesmo após esses fixes, BRIDGEWATER continua com Sharpe/ROI/trade count
  implausíveis para um engine desse tipo. O status correto permanece
  **invalidado por bug/artefato**, não "edge".

## 4. DSR — CITADEL e JUMP

Inputs documentados em `docs/audits/_revalidation_dsr_inputs.txt`.

| Engine | Window | Sharpe | n_trades | n_trials | DSR | Leitura |
| --- | --- | --- | --- | --- | --- | --- |
| CITADEL | BEAR histórico (gate) | 5.677 | 240 | 50 | 1.000 | forte no gate original |
| CITADEL | BEAR HEAD atual | 2.149 | 140 | 50 | 0.205 | robustez enfraquecida pelo drift |
| CITADEL | BULL | 2.810 | 82 | 50 | 0.985 | robusto |
| CITADEL | CHOP | 4.842 | 10 | 50 | 0.985 | ignorar para veredito; amostra insuficiente |
| JUMP | BEAR | 3.149 | 110 | 35 | 1.000 | robusto |
| JUMP | BULL | 3.187 | 136 | 35 | 1.000 | robusto |
| JUMP | CHOP | 4.268 | 231 | 35 | 1.000 | robusto |

**Leitura correta:**

- `JUMP` sobrevive ao haircut de multiple testing nas 3 janelas.
- `CITADEL` continua forte em BULL e no gate histórico BEAR, mas o BEAR no HEAD
  atual cai bastante; portanto a claim de "robustez limpa" enfraqueceu.

## 5. Veredito Final por Engine

| Engine | Classe | Há edge real? | Racional |
| --- | --- | --- | --- |
| CITADEL | EDGE_DE_REGIME | sim, mas enfraquecido | gate histórico forte em BEAR + BULL positivo; CHOP sem amostra; BEAR no HEAD atual caiu materialmente |
| RENAISSANCE | EDGE_DE_REGIME | sim, com cara de trend follower | positivo em BEAR+BULL; CHOP insuficiente e sem evidência de edge transversal |
| JUMP | EDGE_REAL | sim | positivo em BEAR+BULL+CHOP com `n_trades >= 50` e DSR ~1.0 |
| DE SHAW | NO_EDGE_OU_OVERFIT | não | único regime significativo no gate histórico era negativo; leituras positivas novas não bastam para reabilitar |
| BRIDGEWATER | INVALID_OOS_LIVE_SENTIMENT | não | original invalidado por bug de sentiment; pós-fix continua implausível demais para aceitar como edge |
| KEPOS | INSUFFICIENT_SAMPLE | não | 0 trades no gate histórico; 7/18/0 trades nas janelas atuais; cost bug já contaminou o histórico |
| MEDALLION | NO_EDGE_OU_OVERFIT | não | negativo em BEAR, BULL e CHOP; cost asymmetry só reforça suspeita de in-sample inflado |

## 6. Checkpoint para Blocos 1–3

Estado do gate:

- `JUMP` é o sobrevivente mais limpo.
- `CITADEL` e `RENAISSANCE` ficam como edge de regime, não como edge universal.
- `DE SHAW`, `KEPOS` e `MEDALLION` não devem receber nova calibração hoje.
- `BRIDGEWATER` continua invalidado por bug/artefato.

Consequência prática:

- **Não** há base metodologicamente limpa para avançar cegamente para Blocos 1–3
  como se o branch estivesse congelado.
- Há drift pós-gate suficiente para justificar **parada para aprovação do João**
  antes de qualquer bloco novo ou de qualquer nova reclassificação agressiva.
