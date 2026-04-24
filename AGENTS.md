# AGENTS.md — Quem trabalha no AURUM

> **Propósito:** mapa de quem opera neste repo — humanos, agentes
> persistentes, subagents dispatcháveis, e os operativos do RESEARCH DESK.
> Lido antes de qualquer orquestração pra não pisar em lane alheio.
>
> ⚠️ **NÃO é persona file.** Este arquivo é o hub de orientação do repo.
> As personas editáveis dos operativos SCRYER/ARBITER/ARTIFEX/CURATOR vivem
> em `docs/agents/<key>.md`. O `markdown_editor` do research_desk usa este
> AGENTS.md só como fallback se a persona específica não existir — então
> mantenha `docs/agents/` populado pra evitar edit acidental.

---

## 1. Humanos

| Quem | Papel | Idioma |
|---|---|---|
| **Joao Carretero** | Owner, trader, arquiteto. Aprova mudanças em CORE, config/keys.json, promoções/arquivamentos de engines, merges em `main`. | PT-BR |

**Autoridade exclusiva do Joao:**
- Modificações em `core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py` (ver `MEMORY.md` → CORE protegido)
- Sobrescrever `config/keys.json` (nunca autorizado por default)
- Promoção/arquivamento de engine (`stage` field, `EXPERIMENTAL_SLUGS`)
- Força-push em `main`, rebase de commits publicados

---

## 2. Agentes persistentes (rodam em sessões independentes)

| Agente | Modelo | Contexto | Responsabilidades típicas |
|---|---|---|---|
| **Claude Code** | Opus 4.7 (1M) | este repo | feature dev, refactor, audits consolidados, session/daily logs, orquestração de subagents |
| **Codex A / B / C** | GPT-5+ via terminal Codex | mesmo repo | paralelo em branches próprias — runtime fixes, perf caching, UI launcher, deploy. Codex pode commit direto mas **não** toca CORE nem keys.json |
| **macro_brain bots** | ML/DL local | `macro_brain/` | thesis generation, sentiment scoring, regime classification — autônomos, rodam via launcher |

**Conflito de lane:** quando dois agentes tocam na mesma área (ex: launcher.py), quem chega depois faz rebase/merge; CORE é inalienável de ambos. Histórico: ver `docs/audits/2026-04-17_agent_orchestration.md` e `docs/audits/2026-04-22_codex_day_audit.md` pra exemplos de coordenação.

**Regra 2026-04-15** (fundada após incidente): nenhum agente (Claude, Codex, outros) pode modificar código real pra fazer teste passar. O teste caracteriza o código, não o contrário. Ver `MEMORY.md` → Incidentes.

---

## 3. Subagents dispatcháveis (dentro de uma sessão Claude Code)

Invocados via tool `Agent` com `subagent_type`. Não persistem entre sessões.

| Tipo | Quando usar |
|---|---|
| `Explore` | Busca de padrão/keyword em repo grande (>3 queries previstas). Read-only. |
| `Plan` | Designar implementação multi-step antes de tocar código. |
| `feature-dev:code-explorer` | Tracing profundo de fluxo de execução / arquitetura existente. |
| `feature-dev:code-architect` | Blueprint pra feature nova com mapping de arquivos a criar/mudar. |
| `feature-dev:code-reviewer` | Revisão high-confidence antes de merge. |
| `general-purpose` | Qualquer tarefa multi-step quando os específicos não couberem. |
| `superpowers:code-reviewer` | Revisão contra plano + standards após major step. |
| `claude-code-guide` | Perguntas sobre Claude Code/SDK/API (não sobre o AURUM em si). |
| `statusline-setup` | Configurar statusline do Claude Code. |

### Padrão de paralelismo (ver `docs/audits/2026-04-17_agent_orchestration.md` + memory `feedback_multiagent_for_validation.md`)

**Regra fundada 2026-04-23 (BRIDGEWATER cascade case):** pra tarefas tipo "faz engine X funcionar hoje" ou "invoque tudo que tiver", dispatchar 3-5 general-purpose em paralelo por domínio independente:

1. **Veto forensics** — por que X produz 0/poucos trades no período-alvo?
2. **Walk-forward deslizante** — distribuição temporal do edge (janelas 7d-30d sobrepostas)
3. **Attribution forense** — concentração do melhor run por símbolo/direção/regime
4. **Infra de dados** — cobertura de cache, prewarm, agendamento
5. **Mechanical compare** — diff do engine novo contra um conhecido funcionar (CITADEL, JUMP)

Cada agente recebe prompt self-contained: contexto, caminhos, output format <500 palavras, constraint read-only. Consolidação fica no main agent.

**Quando NÃO paralelizar:** refactors lineares, bug fixes triviais, rename, docs.

---

## 4. RESEARCH DESK — Operativos AI (feat/research-desk)

Quatro personas configuráveis via Paperclip API (porta 3100), gerenciadas pelo `launcher_support/research_desk/`:

| Sigil | Operativo | Foco |
|---|---|---|
| 👁️ | **SCRYER** | Detecção / observação — scanning de mercado, anomaly flags, regime shifts |
| ⚖️ | **ARBITER** | Julgamento — validação de hipóteses, scoring de edges, ship/iterate/kill calls |
| 🔨 | **ARTIFEX** | Construção — geração de código/engine novos, implementação de features |
| 📚 | **CURATOR** | Curadoria — docs, audits, consolidação de findings, session logs |

Cada operativo tem:
- **Persona editável**: `docs/agents/{key}.md` (markdown inline editor no launcher)
- **Stats históricos**: `data/aurum.db` → tabela `research_desk_stats` (ship/iterate/kill ratio 30d)
- **Cost tracking**: sparklines + alert row quando >80% budget
- **Pause/Resume**: POST `/api/agents/:id/pause|/resume`

**Acesso humano:** tecla `n` cria ticket, click no card abre detail modal 720x720, tecla `c` abre cost dashboard. Branch `feat/research-desk` — ver daily 2026-04-23.

---

## 5. Checklist antes de dispatchar qualquer agente

- [ ] Tarefa é realmente independente (não precisa de state compartilhado)?
- [ ] Prompt é self-contained? (agent não vê esta conversa)
- [ ] Scope read-only ou write? Se write, CORE está fora do alcance?
- [ ] Lane está livre (nenhum Codex ativo no mesmo arquivo)?
- [ ] Output format e length definidos?
- [ ] Para paralelo: single message com múltiplas chamadas em um bloco

**Referências:**
- `docs/audits/2026-04-17_agent_orchestration.md` — exemplo canônico de coordenação multi-agente
- `docs/audits/2026-04-22_codex_day_audit.md` — auditoria de 35 commits do Codex em 1 dia
- Memory: `feedback_multiagent_for_validation.md`
