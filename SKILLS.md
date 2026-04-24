# SKILLS.md — Quando invocar cada workflow

> **Propósito:** mapa dos skills (superpowers + built-in) que fazem
> sentido para AURUM, com gatilhos específicos e fluxos típicos.
> Skills override system prompt default behavior. Instruções explícitas
> do Joao (CLAUDE.md, mensagens diretas) override tudo.

---

## 1. Regra base (da skill `using-superpowers`)

**Se tem 1% de chance de um skill aplicar, INVOQUE.**

Não decidir "esse é só um question" ou "eu conheço isso". Skills evoluem — versão atual via `Skill` tool. Red flags mentais que significam PARE:

| Pensamento | Realidade |
|---|---|
| "é simples" | Question é task. Checa skill. |
| "preciso contexto primeiro" | Skill check vem ANTES de perguntar. |
| "deixa eu explorar código rápido" | Skills dizem COMO explorar. |
| "não precisa skill formal" | Se existe, use. |
| "eu lembro desse skill" | Leia versão atual. |

**Prioridade quando múltiplos se aplicam:**
1. **Process skills primeiro** (brainstorming, debugging) — definem COMO abordar
2. **Implementation skills depois** (feature-dev, frontend-design) — execução

---

## 2. Superpowers skills — gatilhos em AURUM

### Antes de começar qualquer coisa criativa

**`superpowers:brainstorming`** — **MUST USE** antes de:
- Novo engine (ex: antes de abrir código do PHI)
- Feature no launcher
- Refactor grande (ex: roadmap 3 fases de 2026-04-23)
- Mudar lógica de sinais/signals/portfolio

Fluxo: explorar intent → requirements → design → AÍ implementação.

### Planejamento estruturado

**`superpowers:writing-plans`** — quando tem spec/requirements para multi-step task, antes de tocar código. Output vai pra `docs/superpowers/plans/YYYY-MM-DD-<slug>.md`.

**`superpowers:executing-plans`** — quando tem plan escrito para executar em sessão separada com checkpoints.

**`superpowers:subagent-driven-development`** — quando plan tem tasks independentes (ex: "extrair 84 methods em 6 commits" na Fase 3 do roadmap). Dispatcha 1 implementer por task.

**`superpowers:dispatching-parallel-agents`** — quando 2+ tasks independentes sem shared state (ex: forense BRIDGEWATER com 4 agents em domínios diferentes). Ver `AGENTS.md` seção 3.

**`superpowers:using-git-worktrees`** — quando feature precisa isolamento do workspace atual ou antes de executar plan. Padrão AURUM: `.worktrees/<slug>` off main. Ex: `feat/arb-hub-v2` em 2026-04-23.

### Desenvolvimento disciplinado

**`superpowers:test-driven-development`** — **rigid skill**. Usado ao implementar feature ou bugfix, **antes** de escrever código de implementação.

**`superpowers:systematic-debugging`** — **rigid skill**. Usar ao encontrar bug, test failure, comportamento inesperado — **antes** de propor fix. Exemplo de uso correto: sessão 2026-04-23 15:32 BACKTEST em branco (lazy-load connections), não saiu chutando fix, mapeou root cause primeiro.

**`superpowers:verification-before-completion`** — **MUST USE** antes de claim de "funcionou", "pronto", "passing". Roda comandos, mostra output, **evidência antes de asserção**. Regra: nunca "funcionou" sem rodar.

### Revisão

**`superpowers:requesting-code-review`** — ao completar tasks, features majors, ou antes de merge. Verifica que trabalho bate com requisitos.

**`superpowers:receiving-code-review`** — quando recebe feedback, antes de implementar sugestões, especialmente se feedback parece unclear ou tecnicamente duvidoso. **Não implementa cegamente** — verifica. Exemplo: sessão 2026-04-15 Codex sugeriu trocar RSI pra fazer teste passar; aplicar este skill preveniu damage (ver `MEMORY.md` → Incidentes).

### Finalização

**`superpowers:finishing-a-development-branch`** — implementação completa, tests passam, decidir integração (merge, PR, cleanup).

### Meta

**`superpowers:writing-skills`** — criar novos skills ou editar existentes.

---

## 3. Built-in Claude Code skills

**`update-config`** — `settings.json` do Claude Code (hooks, permissões, env vars). Gatilhos: "allow X", "when claude stops do Y", "set DEBUG=true".

**`keybindings-help`** — rebind keys em `~/.claude/keybindings.json`.

**`simplify`** — revisar código changed para reuse, qualidade, eficiência. Aplicado antes de commits grandes.

**`fewer-permission-prompts`** — scan transcripts por Bash/MCP reads comuns, adiciona allowlist em `.claude/settings.json`.

**`loop`** — rodar prompt/comando em intervalo recorrente (ex: "/loop 5m /check-deploy"). Só pra recurring, não one-off.

**`schedule`** — agente remoto em cron (ex: "agent em 2 semanas pra remover flag X"). **Proativamente ofereça** quando trabalho tem natural follow-up (feature flag, soak window, cleanup TODO).

**`claude-api`** — build/debug Claude API apps com `anthropic` SDK. Trigger: código importa `anthropic`, pergunta sobre prompt caching. **Skip** se importa `openai` ou outro provider.

**`feature-dev:feature-dev`** — guided feature development com codebase understanding.

**`frontend-design:frontend-design`** — frontend polished, não-AI-genérico. Usar pro `server/website` ou UIs novas.

**`init`** — inicializar CLAUDE.md novo (não aplicável, já temos).

**`review`** — review PR.

**`security-review`** — security review de pending changes na branch atual.

---

## 4. Fluxos típicos em AURUM

### 4.1. Nova engine

```
1. brainstorming (intent, mecanismo, differentiation)
2. writing-plans → docs/superpowers/plans/<slug>.md
3. docs/engines/<engine>/hypothesis.md (mecanismo + falsificação + split hardcoded)
4. docs/engines/<engine>/grid.md (lista fechada de configs, commit antes de rodar)
5. test-driven-development pra módulos novos
6. Code em engines/<engine>.py usando core.* + config/params.py (engine-prefixed)
7. Grid run → analysis/dsr.py → docs/audits/YYYY-MM-DD_<engine>_*.md
8. verification-before-completion antes de reportar findings
9. Se falhou protocol → arquiva (com pushback checado, ver MEMORY feedback)
10. requesting-code-review antes de merge
11. Session/Daily log
```

### 4.2. Bug hunt

```
1. systematic-debugging (mapear, reproduzir, isolar antes de fix)
2. Se múltiplas hipóteses independentes: dispatching-parallel-agents
3. Write failing test primeiro (TDD)
4. Fix
5. verification-before-completion (teste passa + smoke)
6. Session log com **ATENÇÃO:** se tocou CORE (spoiler: não deveria)
```

### 4.3. Refactor grande (tipo roadmap 3 fases)

```
1. brainstorming (escopo, blast radius, CORE intocado?)
2. writing-plans → docs/superpowers/plans/<slug>.md
3. using-git-worktrees pra isolar
4. subagent-driven-development (tasks independentes em paralelo)
5. Code reviews em waves
6. verification-before-completion (smoke + suite paralela)
7. Merge limpo em base branch, depois PR pra main
8. Session + Daily logs
```

### 4.4. Engine validation (ex: "faz X funcionar hoje")

```
1. Reler AGENTS.md seção 3 (padrão de paralelismo)
2. Dispatch 3-5 general-purpose em paralelo:
   - veto forensics
   - walk-forward deslizante
   - attribution por símbolo/direção/regime
   - infra de dados (cache)
   - mechanical compare com engine validated
3. Consolidar em docs/audits/YYYY-MM-DD_<engine>_*.md
4. Atualizar docs/engines/<engine>/hypothesis.md (com aprovação Joao)
5. NÃO promover/arquivar state sem aprovação explícita
6. Session log destacando cascade-harvester ou não-edge
```

### 4.5. Deploy / Live

```
1. security-review (pending changes)
2. verify_keys_intact.py antes de qualquer coisa em config/
3. Paper → demo → testnet → live (gradual)
4. Kill-switch: config/risk_gates.json + core/risk_gates.py
5. VPS deploy via deploy/install_shadow_vps.sh + systemd
6. Telegram health check ativo (bot/telegram.py)
7. Session log com **ATENÇÃO:** modo alterado
```

### 4.6. Fim de sessão (sempre)

```
1. verification-before-completion (tudo passa?)
2. git status + diff review
3. Session log: docs/sessions/YYYY-MM-DD_HHMM.md (formato em CLAUDE.md)
4. Daily log: docs/days/YYYY-MM-DD.md (incrementa se existe)
5. Commit logs junto com último commit de trabalho
6. finishing-a-development-branch se branch de feature pronta
7. Oferecer /schedule se há follow-up natural (flag cleanup, soak)
```

---

## 5. Anti-patterns em skill usage

- **"Eu sei disso, skip skill"** — Sempre checa versão atual.
- **Dispatch parallel agents em tudo** — Se tasks são sequenciais ou trivial, não paraleliza.
- **brainstorming em bug fix trivial** — Overkill. Bug fix → systematic-debugging direto.
- **TDD pra UI polish** — Não. TDD pra logic.
- **Cascade de skills sem aplicar os resultados** — Cada skill invocado deve ter impacto no trabalho.
- **verification-before-completion pulado "porque sei que funciona"** — Nunca pule. Evidência antes de asserção.

---

## 6. Skills específicos do AURUM (não-superpowers, mas de facto)

### Protocolo Anti-Overfit
Ver `docs/methodology/anti_overfit_protocol.md` + `MEMORY.md` seção 5.
5 princípios rigid. Falhou? Arquiva (com pushback checado pra edges episódicos).

### Multi-agent validation
Ver `AGENTS.md` seção 3. Quando Joao diz "invoque tudo", 3-5 paralelos.

### CORE protection
Ver `MEMORY.md` seção 1. Qualquer tentativa de mudar RSI/swing/Kelly/params → pergunta Joao primeiro, sempre.

### Keys.json intocável
Ver `MEMORY.md` seção 2. `verify_keys_intact.py` antes de qualquer `config/` touch.

---

## 7. Referência rápida — "qual skill agora?"

| Situação | Skill primário |
|---|---|
| Joao disse "build X" | brainstorming → writing-plans |
| "Fix this bug" | systematic-debugging |
| "Plan is done, execute" | executing-plans ou subagent-driven-development |
| "Merge when ready" | requesting-code-review → finishing-a-development-branch |
| "Check security" | security-review |
| "Validate engine X" | Parallel agents (AGENTS.md §3) |
| "Faxina / refactor" | brainstorming → writing-plans → subagent-driven |
| "Rode novamente / verify" | verification-before-completion |
| "/schedule for later" | schedule |
| "Review my PR" | review |
| About to EnterPlanMode? | brainstorming antes |
| About to claim "done" | verification-before-completion |
