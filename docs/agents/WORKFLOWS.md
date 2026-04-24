# WORKFLOWS.md — RESEARCH DESK pipeline

> **Propósito:** workflows operacionais da mesa de 5 agents do RESEARCH DESK
> (RESEARCH, REVIEW, BUILD, CURATE, AUDIT) sobre a Paperclip API local
> (`127.0.0.1:3100`). Referenciado por cada `docs/agents/<key>.md` e pelos
> instruction files Paperclip (`~/.paperclip/instances/.../AGENTS.md`).
>
> Para filosofia/CORE ver `MEMORY.md`. Para arquitetura ver `CONTEXT.md`.
> Para subagents / paralelismo ver `AGENTS.md §3`.

---

## 1. Tipos de workflow

### TIPO 1 — Spec Review (RESEARCH → REVIEW gate)
1. RESEARCH pesquisa e escreve spec em `docs/superpowers/specs/YYYY-MM-DD-<slug>-design.md`
2. RESEARCH fecha ticket (ver §3 closure)
3. Ticket novo atribuído ao REVIEW: "Review spec X"
4. REVIEW aplica critérios §4.1, escreve review em `docs/reviews/YYYY-MM-DD_spec_{NAME}_review.md`
5. Veredito: SHIP (→ BUILD) / ITERATE (→ RESEARCH volta) / KILL (arquiva)
6. REVIEW fecha ticket

### TIPO 2 — Code Review (BUILD → REVIEW gate, com loop ITERATE)
1. BUILD implementa em branch `experiment/<engine>` + testes TDD
2. BUILD commit + push + fecha ticket com branch, commits, N/M testes
3. Ticket novo para REVIEW: "Review code X em experiment/X"
4. REVIEW aplica critérios §4.2, escreve review em `docs/reviews/YYYY-MM-DD_code_{NAME}_review.md`
5. Veredito SHIP / ITERATE (issues classificados BLOCKER/MAJOR/MINOR) / KILL
6. Se ITERATE → novo ticket para BUILD "Fix X"; após fix, re-review (TIPO 2 post-iterate)
7. REVIEW fecha ticket a cada ciclo

### AUDIT — integrity gate (pós REVIEW SHIP)
1. Após REVIEW SHIP, ticket para AUDIT: "Audit integridade de <engine> em <branch>"
2. AUDIT executa protocolo 6-block no worktree (§4.3)
3. Escreve relatório em `docs/audits/engines/YYYY-MM-DD_audit_{engine}.md`
4. Veredito VALIDATED (→ merge + flag `live_ready: True` em `config/engines.py`)
   / REJECTED (→ volta `stage=research`, blockers listados)
   / CONDITIONAL (→ VALIDATED com restrições: bluechip only, notional cap, paper-only 30d)
5. AUDIT fecha ticket

### CURATION — CURATE sob demanda
1. Joao abre ticket: "Audit {scope}" (dead code, stale branches, dependency bloat, alignment drift, etc.)
2. CURATE gera relatório em `docs/audits/repo/YYYY-MM-DD_{scope}_audit.md`
3. Propostas classificadas SAFE_TO_DELETE / NEEDS_REVIEW / KEEP
4. **NÃO executa limpeza — só propõe.** Execução exige aprovação explícita do Joao:
   → branch `chore/cleanup-<scope>` → REVIEW review → Joao merge
5. CURATE fecha ticket

---

## 2. Spec template (RESEARCH — 9 secções obrigatórias)

Formato exato de `docs/superpowers/specs/YYYY-MM-DD-<slug>-design.md`:

```markdown
# {STRATEGY_NAME} — Spec

## 1. Edge thesis
[1 parágrafo: edge estrutural (mecanismo causal), não só estatístico]

## 2. Literature
[3-5 referências com links verificáveis + takeaway de cada]

## 3. Mathematical framework
[Equações centrais, parâmetros críticos]

## 4. Data requirements
[Venues, timeframes, look-back, symbols]

## 5. Signal generation logic
[Pseudocódigo high-level — não implementação]

## 6. Risk & sizing
[Como dimensionar posição, kill-switches esperados]

## 7. Integration with AURUM
[Engine standalone? Feature em engine existente? Signal pra meta-orchestrator?]

## 8. Estimated development cost
[Dias de dev, complexity tier LOW/MEDIUM/HIGH]

## 9. Falsifiability criteria
[Qual resultado empírico mataria esta estratégia?]
```

**Fontes obrigatórias por candidato**: link verificável da fonte original,
evidência de uso em produção (se existir), edge documentado nos últimos 5 anos
(preferencial). Rejeita ideias com lastro em único blog post — exige
convergência de **2+ fontes independentes**.

---

## 3. Closure workflow (todos os agents)

Ao concluir qualquer ticket, nesta ordem:

1. **Comment final no ticket** com: sumário (1-2 frases) + paths dos artefatos criados + próxima ação sugerida.

2. **PATCH status:done**:
   ```bash
   curl -s -X PATCH http://127.0.0.1:3100/api/issues/{ISSUE_ID} \
     -H "Content-Type: application/json" \
     -d '{"status":"done"}'
   ```
   Se não souber o ISSUE_ID, buscar:
   ```bash
   curl -s http://127.0.0.1:3100/api/companies/c2ccbb97-bda1-45db-ab53-5b2bb63962ee/issues
   ```
   e filtra por `assigneeAgentId` teu + `status: "in_progress"`.

3. **Session log** em `docs/sessions/YYYY-MM-DD_HHMM.md` (formato exato no CLAUDE.md do repo).

4. **Daily log** em `docs/days/YYYY-MM-DD.md` — incrementa se existe, cria se não.

5. Só termina o run DEPOIS do PATCH confirmado (status:done).

**Reabertura silenciosa** (padrão conhecido do Paperclip): se ticket voltar a `in_progress` sem comment novo, re-PATCH silencioso. Evita loop, não poste novo comment.

---

## 4. Critérios de review e audit

### 4.1 REVIEW TIPO 1 — spec review
1. **Edge plausibility** — estrutural (mecanismo causal) ou só estatístico? Rejeita "funciona em backtest" sem POR QUÊ.
2. **Literature quality** — refs existem? Tenta verificar 3+ via WebFetch.
3. **Falsifiability** — critério específico e mensurável? "Sharpe <0.5 em 2 anos → matar" é válido; "se não performar bem" não é.
4. **Integration feasibility** — encaixa no padrão AURUM sem tocar CORE/launcher/config protegidos (ver `MEMORY.md §1-2`)?
5. **Standalone viability** — depende de engines não-confirmadas? Dependência em stub = RISCO, não bloqueio (sinaliza).

Scores 1-5 por critério. Veredito SHIP / ITERATE / KILL.

**Novidade não é critério.** Duas implementações funcionais > uma stub. Foco: essa spec, sozinha, é sólida?

### 4.2 REVIEW TIPO 2 — code review
1. **Padrão AURUM** — engine nova é indistinguível de engines validated (citadel.py, jump.py, janestreet.py, renaissance.py)? Estrutura, nomenclatura, interface, docstrings.
2. **Protected files tocados → KILL IMEDIATO** (ver `MEMORY.md §1-2`): core/indicators.py, core/signals.py, core/portfolio.py, config/params.py, config/keys.json, launcher.py, engines/*.py existentes.
3. **Core reuse** — usa `core/indicators`, `core/signals`, `core/portfolio` em vez de reimplementar?
4. **Codex anti-patterns** — testes ajustados pra match código (incidente 2026-04-15)? lookahead em pivot (`.shift(-N)` com N>0, `center=True` em rolling)?
5. **Integração automática** — registro em `config/engines.py` é suficiente (launcher/backtest/multistrategy são automáticos via registry, NÃO tocam)?
6. **Test coverage** — edge cases (NaN, outliers, dados vazios, mercado fechado) ou só happy path?

Issues classificados BLOCKER / MAJOR / MINOR. Veredito SHIP / ITERATE / KILL.

### 4.3 AUDIT — 6-block protocol (gates numéricos)

| Bloco | Gate |
|---|---|
| 1. Spec-Code conformance | Tabela regra→linha→OK/DIVERGE/AUSENTE |
| 2. Null baseline (shuffled signal, 10 seeds) | \|z\| ≥ 2 |
| 3. Walk-forward (3 janelas sequenciais) | OOS/IS ≥ 0.7 em todas |
| 4. Parameter sensitivity (±20% em 2-3 params) | Spread relativo Sharpe < 30% |
| 5. Cost stress (fees 2× + slippage 2×) | Ratio stress/normal ≥ 0.5 |
| 6. Lookahead bias scan | Zero bugs não-justificados |

Template completo de output: mantido no `AGENTS.md` do AUDIT (`~/.paperclip/.../AGENTS.md`) por ser extenso e AUDIT-específico.

---

## 5. Referências cruzadas

- **`AGENTS.md §4`** (repo root) — roster e sigils dos 5 operativos
- **`AGENTS.md §5`** — checklist antes de dispatchar qualquer agente
- **`MEMORY.md §1`** — CORE protegido (core/indicators, core/signals, core/portfolio, config/params)
- **`MEMORY.md §2`** — `config/keys.json` INTOCÁVEL
- **`MEMORY.md §3`** — incidentes fundadores (2026-04-15 Codex, 2026-04-19 keys wipe)
- **`MEMORY.md §4`** — status atual das engines
- **`MEMORY.md §5`** — Anti-Overfit Protocol (5 princípios)
- **`MEMORY.md §6`** — artifact locations canônicos
- **`CONTEXT.md §2`** — árvore de diretórios completa
- **`CONTEXT.md §3`** — pipeline canônico de sinais (CITADEL)
- **`CONTEXT.md §4`** — parâmetros chave em `config/params.py`
- **`SKILLS.md §4`** — fluxos genéricos (nova engine, bug hunt, refactor, engine validation, deploy, fim de sessão)
- **`config/engines.py`** — registry canônico de engines (fonte única)
