# Spec — Engines sem edge: protocolo disciplinado 2026-04-22

Data: 2026-04-22
Autor: Claude (brainstorming session com Joao)
Status: aprovado, pendente implementação do plano

## Contexto

OOS audit de 2026-04-16 classificou como "sem edge confirmado" os engines
DE SHAW, KEPOS, MEDALLION, BRIDGEWATER, RENAISSANCE inflado, ORNSTEIN e
PHI. Entre 17/04 e 21/04 cada um passou (ou começou a passar) por
recalibração disciplinada sob o protocolo anti-overfit
(`docs/methodology/anti_overfit_protocol.md`). Situação em 2026-04-22:

- BRIDGEWATER — `keep_quarantine` (funding+LS, BEAR,CHOP), OOS histórico
  bloqueado por coverage. Não-escopo hoje.
- RENAISSANCE — rodando com edge real (~2.4 deflacionado). Não-escopo hoje.
- ORNSTEIN — `archive confirmed` em 2026-04-21. Não-escopo hoje.
- KEPOS — hipótese registrada em `docs/engines/kepos/hypothesis.md`
  (2026-04-20). Engine + `tools/kepos_recalibration.py` em voo no working
  tree. Grid pré-registrado. Aguarda execução dos Passos 2-7.
- PHI — hipótese registrada em `docs/engines/phi/hypothesis.md` (reopen
  2026-04-21). `tools/batteries/phi_reopen_protocol.py` e
  `docs/engines/phi/grid.md` em voo. Aguarda execução dos Passos 2-7.
- DE SHAW — hipótese registrada em `docs/engines/deshaw/hypothesis.md`
  (2026-04-20) com `2026-04-20_recalibration_plan.md`. Draft de audit em
  TODO. Nada em voo no tree.
- MEDALLION — hipótese registrada em `docs/engines/medallion/hypothesis.md`
  (2026-04-20). Nada em voo no tree.

Hoje o objetivo é executar o protocolo nesses quatro (KEPOS, PHI, DE SHAW,
MEDALLION) em paralelo onde possível, sem iteração livre de parâmetros e
sem reformulação de universo durante o round.

## Objetivo

Produzir quatro verdicts honestos sob protocolo anti-overfit
(`keep_quarantine` | `archive` | `hypothesis_v2`), cada um registrado em
`docs/audits/2026-04-22_<engine>_recalibration.md`, em uma única sessão.

## Escopo

**In:** KEPOS, PHI, DE SHAW, MEDALLION — cada um com hipótese já
registrada, grid pré-registrado, split hardcoded no engine.

**Out:**
- RENAISSANCE (rodando com edge, não mexer).
- BRIDGEWATER (quarantined, bloqueado por coverage histórica).
- ORNSTEIN (arquivado ontem).
- CITADEL, JUMP (edge confirmado, protegidos).
- GRAHAM (arquivado anteriormente, não reopen hoje).
- MEANREV (design exploratório separado, fora do protocolo do dia).
- CORE de trading (`core/indicators.py`, `core/signals.py`,
  `core/portfolio.py`, `config/params.py`) — intocável.

## Princípios operacionais (não-negociáveis)

Herdados de `docs/methodology/anti_overfit_protocol.md`:

1. Mecanismo > iteração. Hipótese já está escrita para os quatro; não
   reescrevemos durante o round.
2. Split hardcoded no engine. Não muda.
3. Grid fechado. Lista pré-registrada em `docs/engines/<e>/grid.md`. Não
   muda durante o round. Sem `iterN` adicional.
4. DSR obrigatório. Sharpe cru sem haircut por `n_trials` não vale.
5. Regra de parada honra. Falhou a barreira → registra `archive` ou
   `hypothesis_v2`. Sem retry silencioso.
6. CORE protegido. Ninguém toca `core/indicators.py`, `core/signals.py`,
   `core/portfolio.py`, `config/params.py`. Se teste sintético quebrar,
   ajusta o teste.

## Arquitetura de execução

### Paralelismo híbrido

```
main branch (feat/phi-engine)
├── Lane main (Claude): KEPOS → PHI (sequencial)
│   ├── Modifica engines/kepos.py, engines/phi.py se necessário
│   ├── Usa tools/kepos_recalibration.py e tools/batteries/phi_reopen_protocol.py
│   └── Commita em feat/phi-engine
│
├── Lane worktree A (subagent): DE SHAW
│   ├── worktree .worktrees/deshaw-protocol
│   ├── branch feat/deshaw-protocol
│   └── merge back depois do verdict
│
└── Lane worktree B (subagent): MEDALLION
    ├── worktree .worktrees/medallion-protocol
    ├── branch feat/medallion-protocol
    └── merge back depois do verdict
```

As três lanes dispatcham em paralelo assim que o commit das mods em voo
no working tree estiver feito. Lanes não compartilham arquivos:

- Cada engine é um arquivo próprio em `engines/`.
- Cada hypothesis/grid é um dir próprio em `docs/engines/`.
- Cada verdict é um arquivo próprio em `docs/audits/`.
- `config/params.py` é intocável por todas.
- `config/engines.py` é tocado só pela lane main (única fonte de
  EXPERIMENTAL_SLUGS). Subagents entregam mudança proposta; main merge
  decide.

### Sequência de lane main

1. Commit das mods em voo no tree atual (KEPOS, PHI, ornstein audit,
   millennium tools, testes). Atômico.
2. Criar worktrees A e B a partir de `feat/phi-engine` HEAD.
3. Dispatch dos dois subagents (worktree A e B) via Agent tool, run in
   background.
4. Lane main executa KEPOS (Passos 2-7) e commita verdict.
5. Lane main executa PHI (Passos 2-7) e commita verdict.
6. Lane main aguarda subagents completarem, faz merge-back dos branches
   deshaw-protocol e medallion-protocol via `git merge --no-ff` (merge
   commit preservado pra histórico legível). Sem rebase, sem force-push,
   sem squash — preservar SHAs dos subagents pra auditoria.
7. Consolidação final: session log + daily log + análise de meta-trigger.

### Protocolo por engine (Passos 2-7)

Para cada engine:

1. **Confirmar split hardcoded** — ler topo de `engines/<e>.py`,
   garantir que `TRAIN_END`, `TEST_END` estão lá e coerentes com
   hypothesis.md. Não mudar.
2. **Grid fechado** — rodar todos os N configs de
   `docs/engines/<e>/grid.md` somente em janela train.
3. **DSR haircut** — usar `analysis/dsr.py` (criar se não existir,
   fórmula de López de Prado 2014 conforme protocolo). p-value > 0.95
   pra sobreviver.
4. **Top-3 em test** — top-3 por DSR-adjusted Sharpe. Reportar **pior
   dos 3**. Threshold: pior Sharpe >= 1.0.
5. **Holdout final** — único config escolhido (pior-de-top3 do test)
   rodado em holdout. Threshold: Sharpe >= 0.8.
6. **Verdict** — escrito em
   `docs/audits/2026-04-22_<engine>_recalibration.md` com o template do
   protocolo (summary, fixed hypothesis, grid, results train/test/OOS,
   interpretation, decision). Preenchido, sem TODO.
7. **Decisão**:
   - `keep_quarantine` — passou todas as barreiras.
   - `archive` — falhou em qualquer barreira sob protocolo disciplinado.
     Vai pra `EXPERIMENTAL_SLUGS` ou é removido do registry conforme
     convenção atual.
   - `hypothesis_v2` — Claude propõe hipótese mecânica nova, PARA e
     apresenta ao Joao. Só roda round 2 com aprovação explícita.

## Política de autonomia

### Autônomo (sem parar)
- Rodar grids pré-registrados.
- Computar DSR e classificar top-3.
- Escrever verdict honesto (qualquer valor de decisão).
- Arquivar sob protocolo se falhar.
- Commits atômicos por engine + session/daily log.
- Limpar scratch/runs intermediários.

### Pausa obrigatória
- Propor hipótese mecânica v2 (reopen de engine arquivado). Apresentar
  ao Joao antes de rodar round 2.
- Tentar tocar CORE protegido (não deve acontecer).
- Erro crítico em infra que arrisca quebrar outros engines.
- Meta-trigger disparar 2ª vez (≥3 archives no dia). Pausa, apresenta,
  espera decisão.

## Definition of Done

- [ ] Spec (este doc) commitado.
- [ ] Implementation plan (via writing-plans) commitado.
- [ ] Mods em voo commitadas.
- [ ] 4 verdicts escritos em `docs/audits/2026-04-22_<engine>_recalibration.md`.
- [ ] 4 commits atômicos (1 por engine) com verdict e mudanças.
- [ ] Merge-back das worktrees de DE SHAW e MEDALLION.
- [ ] `docs/sessions/2026-04-22_HHMM.md` escrito conforme template.
- [ ] `docs/days/2026-04-22.md` atualizado conforme template.
- [ ] Meta-trigger avaliado: se ≥3 archives, apresentado ao Joao.
- [ ] Smoke test passa: `python smoke_test.py --quiet`.
- [ ] Sem mods em `core/indicators.py`, `core/signals.py`,
  `core/portfolio.py`, `config/params.py`.
- [ ] Sem mods em engines fora do escopo (RENAISSANCE, BRIDGEWATER,
  CITADEL, JUMP, ORNSTEIN).

## Riscos e mitigações

### Risco 1 — Meta-trigger segunda vez
ORNSTEIN arquivou 21/04. Se KEPOS + DE SHAW + MEDALLION arquivarem
hoje, são 4 archives em 2 dias. Meta-trigger dispara segunda vez.

**Mitigação:** Não mascarar. Registrar no `meta-trigger log` do
protocolo. Apresentar ao Joao: ou hipóteses fracas consecutivas indicam
método de formação de hipótese problemático, ou espaço de estratégias
quant simples está saturado nas faixas escolhidas.

### Risco 2 — Conflito de commit em `config/engines.py`
Subagents em worktree podem querer tocar `EXPERIMENTAL_SLUGS` ou
registry.

**Mitigação:** Subagents entregam diff proposto no verdict, main
aplica depois. Subagents não escrevem em `config/engines.py`.

### Risco 3 — CORE contamination por subagent
Agent em worktree tem acesso total ao repo.

**Mitigação:** Prompt dos subagents explicita "não tocar core/*, não
tocar config/params.py, não tocar engines fora do próprio engine-alvo".
Main verifica `git diff` no merge-back e rejeita se tiver toque em CORE.

### Risco 4 — Custo computacional dos grids
Walk-forward com holdout pode ser longo.

**Mitigação:** Grid fechado limita N configs. Cada engine roda em OHLCV
cacheado. Se tempo total ultrapassar 2h, paro e apresento parcial.

### Risco 5 — DSR sem implementação
`analysis/dsr.py` pode não existir.

**Mitigação:** Primeira ação de cada lane: `ls analysis/` e verificar.
Se não existe, implementar conforme fórmula do protocolo antes de
rodar grid. Testar com caso conhecido antes de usar em verdict.

## Não-objetivos

- Descobrir edge novo em engines sem hipótese mecânica registrada.
- Rodar RENAISSANCE re-audit (escopo de outra sessão).
- Tocar launcher, cockpit, macro_brain, alchemy.
- Otimizar CITADEL ou JUMP (edge confirmado, não mexer).
- Criar engines novos.
- Refatorar infra que não bloqueia o protocolo.

## Próximos passos (após aprovação do spec)

1. Invocar `superpowers:writing-plans` pra produzir plano de execução
   detalhado com comandos concretos por lane.
2. Executar o plano.
