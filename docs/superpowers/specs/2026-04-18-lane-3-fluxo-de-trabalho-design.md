# Lane 3 — Fluxo de Trabalho — Design

**Data:** 2026-04-18
**Branch de origem:** `feat/phi-engine`
**Escopo:** reduzir fricção de ritual (session/daily log), formalizar
coordenação multiagente (Claude ↔ Codex), e organizar `config/params.py`
em camadas.
**Motivação:** ritual de log toma 3-5 min por sessão; coordenação multiagente
foi ad-hoc em 2026-04-17 mas sem formato reutilizável; `config/params.py`
tem 496 linhas e 131 constantes num único ficheiro, custo cognitivo alto
pra localizar e mudar uma camada sem tocar outra.

**Princípio-guia:** zero mudança em lógica de trading ou em valores
numéricos. Onde tocar core protegido (`config/params.py`), fazer via
shim — mesmo pattern da Lane 1.3.

---

## 3.1 — Session / Daily log helper

### Dor atual
Ritual manual documentado em `CLAUDE.md`:
- Gerar tabela de commits (`git log --since`)
- Listar arquivos modificados
- Capturar estado do smoke
- Redigir Resumo, Mudanças Críticas, Achados, Notas pro Joao

Os primeiros três são mecânicos; os quatro últimos exigem julgamento.

### Alvo
`tools/maintenance/new_session_log.py` que **scaffold** a parte mecânica.
Prosa continua sendo Claude/Codex.

### Comportamento
**Argumentos:**
- `--since "HH:MM"` ou `--last-commit` (HEAD^) ou `--range <commitA>..<commitB>`
- `--out docs/sessions/YYYY-MM-DD_HHMM.md` (default: gera timestamp atual)

**Saída `docs/sessions/YYYY-MM-DD_HHMM.md`:**
```markdown
# Session Log — <timestamp>

## Resumo
<!-- TODO: 1-3 frases do que foi feito -->

## Commits
| Hash | Mensagem | Arquivos |
|------|----------|----------|
<gerado automaticamente via git log>

## Mudanças Críticas
<!-- TODO: mudanças em lógica de sinais, custos, sizing ou risco.
    Se nenhuma: "Nenhuma mudança em lógica de trading." -->

## Achados
<!-- TODO: bugs, comportamentos inesperados, métricas suspeitas -->

## Estado do Sistema
- Smoke test: <lido de tests/reports/latest_smoke.json se existir, senão TBD>
- Backlog restante: TBD
- Próximo passo sugerido: TBD

## Arquivos Modificados
<gerado automaticamente via git diff --stat base..HEAD, com +/- linhas>

## Notas para o Joao
<!-- TODO: preencher pelo agente -->
```

**Daily log update:** atualiza `docs/days/YYYY-MM-DD.md`:
- Adiciona a nova sessão no topo da lista "Sessões do dia"
- Incrementa contagem de commits
- Se daily log não existir, cria do zero com scaffold

### O que o script NÃO faz
- Não escreve prosa.
- Não infere "Mudanças Críticas" — decisão humana explícita.
- Não commita o resultado — deixa pro ritual normal.
- Não edita session logs de sessões passadas.

### Ganho esperado
3-5 min por sessão → ~30s de scaffold + revisão humana.

---

## 3.2 — Claude ↔ Codex orchestration

### Dor atual
Merge conflicts sem aviso, perder contexto entre agentes, perguntas
repetidas de "Codex pode mexer aqui?". Padrão ad-hoc emergiu em
`docs/audits/2026-04-17_agent_orchestration.md` mas não foi reutilizado.

### Alvo
Dois artefatos: um vivo (estado), um estático (regras).

### `docs/orchestration/ACTIVE.md`
**Vivo, sobrescrito a cada sessão.** Foto das lanes ativas.

```markdown
# Agent Orchestration — ACTIVE — YYYY-MM-DD HH:MM

## Lanes ativas
| Agente | Branch/Worktree | Lane | Arquivos escopo | Status |
|--------|-----------------|------|-----------------|--------|
| Claude | feat/phi-engine | Lane 1 organização | launcher.py, core/ | em andamento |
| Codex  | feat/meanrev    | Engine tuning | engines/meanrev.py | waiting review |

## High-risk files agora (não tocar sem coordenar)
- `core/indicators.py` — locked (protected)
- `config/params.py` — Claude editando costs layer

## Próxima sincronização
- Joao revisa PRs pendentes
- Merge order: <se houver>
```

### `docs/orchestration/PROTOCOL.md`
**Estático, 1x escrito, referenciado sempre.** Regras fixas:
- Quem pode tocar CORE protegido (resposta: ninguém sem aprovação de Joao explícita na sessão)
- Como sinalizar edição em progresso (`ACTIVE.md` + commit/push frequente em branch)
- Protocolo de conflito (quem foi primeiro, quem resolve)
- Ordem de merge quando dois branches tocam arquivos partilhados

Referência adicionada em `CLAUDE.md` seção "Regras para Claude Code".

### Helper script
`tools/maintenance/orchestration_snapshot.py`:
- `--claim "Lane 1" --files "launcher.py,core/*" --agent Claude`
- Gera/atualiza `ACTIVE.md`.
- `--release "Lane 1"` remove a entrada.

### Critério de sucesso
Uma sessão conjunta Claude+Codex onde `ACTIVE.md` é atualizado por ambos
e nenhum merge conflict inesperado ocorre.

---

## 3.3 — config/params.py split em camadas

### Aprovação registrada
João aprovou em 2026-04-18 o toque em `config/params.py` **estritamente via shim**,
com critério duro de bit-identidade de backtest de referência.

### Estado atual
- 496 linhas, 131 constantes.
- Misturadas: custos, risco, universo, sinais, stops, params por engine.
- Qualquer edição exige scroll e cuidado cruzado.

### Alvo
```
config/
├── params.py            # shim (≤ 30 linhas)
└── _params/
    ├── __init__.py
    ├── costs.py         # SLIPPAGE, SPREAD, COMMISSION, FUNDING_PER_8H, C1+C2
    ├── risk.py          # Kelly, MAX_DD, CORR_*, MAX_OPEN_POSITIONS, SIZE_MULT
    ├── universe.py      # BASKETS, ACCOUNT_SIZE, symbols, TIMEFRAMES
    ├── signals.py       # OMEGA_WEIGHTS, SCORE_*, STOP_ATR_M, TARGET_RR, trailing
    └── engines/
        ├── __init__.py
        ├── phi.py       # PHI_*
        ├── citadel.py   # CITADEL_* (se existir)
        ├── millennium.py
        └── ...          # 1 por engine com constantes específicas
```

### Shim em `config/params.py`
```python
"""Compatibility shim. Layers live in config._params.*
Importing * continues to work for all legacy consumers.
"""
from config._params.costs import *       # noqa: F401,F403
from config._params.risk import *
from config._params.universe import *
from config._params.signals import *
from config._params.engines.phi import *
# ... 1 linha por engine com params
```

### Protocolo de migração (rígido)
1. Copiar um grupo de constantes (ex.: costs) de `params.py` para `_params/costs.py`.
2. Adicionar `from config._params.costs import *` no shim.
3. Rodar: `python -c "from config.params import SLIPPAGE, SPREAD, COMMISSION, FUNDING_PER_8H; print(SLIPPAGE, SPREAD, COMMISSION, FUNDING_PER_8H)"`.
4. Se valores idênticos → **remover** essas linhas do `params.py` original.
5. Rodar smoke: `python smoke_test.py --quiet` → 156/156.
6. Rodar backtest de referência curto (ex.: CITADEL 30d) → gerar digest SHA-256 do CSV → comparar com baseline pré-Lane 3.3.
7. Só avançar pra próximo grupo se digest bater.

**Regra de parada:** digest divergente em qualquer grupo → revert do grupo, investigar antes de continuar.

### Fora de escopo deste sub-lane
- Migrar imports em engines pra usar paths novos (shim cobre; migração futura).
- Renomear constantes.
- Mudar valores.

---

## Critérios de sucesso Lane 3 (consolidado)

- Script de session log gera scaffold em ≤ 5s; testado 1x por Claude, 1x por Codex.
- `docs/orchestration/ACTIVE.md` + `PROTOCOL.md` commitados; `CLAUDE.md` referencia ambos.
- `config/params.py` ≤ 30 linhas (só shims).
- Backtest de referência bit-identical pré/pós Lane 3.3.
- Smoke 156/156.

## Fora de escopo (explicitamente)

- LLM auto-gerando Resumo ou Notas pro Joao (nada automático onde julgamento importa).
- Migrar consumidores de `config.params` pra paths novos (shim protege; depois).
- Orchestration como daemon/bot (over-engineering).
- Dashboard de orchestration em tempo real.

---

## Integração com Lanes 1 e 2

Lane 3 não depende de Lanes 1 ou 2. Pode executar em qualquer ordem.

Recomendação: **Lane 3.1 antes de iniciar execução das outras** — o helper
de session log vai ser usado imediatamente ao encerrar cada sub-lane,
amortizando o investimento já no dia 1 de execução.
