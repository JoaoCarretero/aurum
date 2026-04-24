# Auditoria Codex — 2026-04-21

**Data auditoria:** 2026-04-22
**Auditor:** Claude Opus 4.7 (1M)
**Escopo:** Todos os 35 commits do dia 2026-04-21 em `feat/phi-engine` + working tree pendente

---

## TL;DR

- **6 commits Claude** (manhã, 09:46-11:32): limpos, bem-documentados, com session logs completos.
- **29 commits Codex** (tarde/noite, 17:27-21:28): grande volume de UI/launcher, runtime fixes de paper/shadow, perf caching em core/launcher. Qualidade técnica média-alta.
- **CORE protegido (indicators/signals/portfolio/params) intocado.** Keys.json intacto.
- **1 BUG confirmado**: `6720c1a` mudou assinatura de função sem atualizar teste → suite crítica tem 1 fail (1160 passed / 1 failed).
- **2 commits com mensagem enganosa** (`8b52c48` diz "frontend" mas mexe em engines; `9213b04` diz "testing" mas mexe em bridgewater + api/server). Conteúdo válido, rotulagem ruim.
- **Working tree** com ~15 arquivos uncommitted: coerente com session log 20:27 + batterias em progresso (kepos recal, metrics last_scan, caching risk_gates/api).
- **Daily log 2026-04-21 desatualizado** — declara 5 commits, existem 35.

---

## Distribuição dos 29 commits do Codex

| Categoria | Qty | Verdict consolidado |
|-----------|-----|---------------------|
| UI/Splash/Main-menu | 11 | ✅ CLEAN — todos |
| Launcher refactor (screens, engine_logs) | 3 | ✅ CLEAN |
| Paper/Shadow runtime | 5 | ✅ CLEAN — exceto `6720c1a` (test broken) |
| Core perf (caching) | 1 (`bd048d1`) | 🟠 DISCUSS — 2 issues técnicos |
| Cockpit perf/fix | 4 | ✅ CLEAN |
| Deploy (multi-instance VPS) | 1 (`7d0f20e`) | ✅ CLEAN |
| Cockpit tunnel | 1 (`c7e1a91`) | 🟡 REVIEW — TOFU não mitigado |
| Data/chore | 1 (`ef9ff48`) | ✅ CLEAN |
| "Engines research" mal-rotulado | 2 (`8b52c48`, `5187cad`) | 🟡 REVIEW — msg ≠ conteúdo |
| "Testing" mal-rotulado | 1 (`9213b04`) | 🟡 REVIEW — msg ≠ conteúdo, defensivo |

---

## Itens FIXADOS em 2026-04-22

| # | Origem | Fix aplicado | Arquivo |
|---|--------|--------------|---------|
| 1 | `6720c1a` (Codex) | mock do `_active_paper_runs` agora aceita `state=None` | tests/integration/test_engines_live_view.py:346 |
| 2 | `bd048d1` (Codex) | removidas 2 definições duplicadas (dead code merge) | core/ops/run_manager.py |
| 3 | `bd048d1` (Codex) | `_JSON_CACHE` + `_RUN_DISCOVERY_CACHE` agora capam em 512 entries | core/shadow_contract.py |
| 4 | working tree (Codex) | `all_trades` + 5 counters agora iniciam antes do branch KS — fim do UnboundLocalError em KS fast_halt | tools/operations/millennium_paper.py:466-473 |
| 5 | `7d0f20e` (Codex) | teste de systemctl atualizado pra substring estável após generalização da msg multi-instance | tests/test_cockpit_paper_endpoints.py:190 |

**Resultado após fixes:**
- Suite crítica: **1580 passed / 0 failed / 72 skipped** (antes: 1160 passed / 1 failed com `-x`; na volta completa: 1578 passed / 2 failed)
- Smoke: 178/178 passed

## Itens que exigem ação

### 🔴 BUG — `6720c1a perf(engines): reduce paper shadow entry blocking`

Mudou assinatura de `_active_paper_runs(launcher)` → `_active_paper_runs(launcher, state)` em `launcher_support/engines_live_view.py` mas não atualizou mock em `tests/integration/test_engines_live_view.py::test_render_detail_reuses_shell_for_paper_refresh` (ainda tem `lambda x:` com 1 arg).

**Evidência:**
```
FAILED tests/integration/test_engines_live_view.py::test_render_detail_reuses_shell_for_paper_refresh
TypeError: ...lambda() takes 1 positional argument but 2 were given
```

**Implicação:** O Codex commitou sem rodar a suite. Regra AURUM: sempre rodar testes após mudança. Codex violou.

**Fix:** patch de 1 linha no teste (mudar lambda pra aceitar `state` como 2º arg).

**Severidade:** baixa (só teste quebrado, código correto) — mas o meta-signal é importante: Codex tá commitando sem verificar.

---

### 🟠 DISCUSS — `bd048d1 perf(core): cache runtime reads and harden bridgewater audits` (30 arquivos, +1185/-152)

Adiciona 5 camadas de cache com TTL curto (0.75s–30s) em `core/ops/*`, `core/arb/*`, `core/shadow_contract.py`, `core/risk/audit_trail.py`. Padrão geral é bom (TTL conservador, invalidação on-write). **NÃO toca core protegido.** "Harden bridgewater" = `run_audit()` agora passa `audit_results` pra `save_run_artifacts/append_to_index/generate_report` — puramente pipeline de reporting, não muda lógica de trading.

**Dois achados técnicos (não críticos):**

1. **Definições duplicadas em `core/ops/run_manager.py`** (confidence 95):
   - `create_run_dir` em linhas 91-104 **e** 392-405
   - `append_to_index` em linhas 222-300 **e** 408-474
   - Python usa só a segunda. Primeira é dead code de merge. Remover L91-104 e L222-300.

2. **`_JSON_CACHE` em `core/shadow_contract.py` é dict sem bound** (confidence 82):
   - Em launcher de longa duração, cresce sem prune. Baixo risco de crash no tier atual mas digno de cap (`if len(_JSON_CACHE) > 500: _JSON_CACHE.clear()`).

**Recomendação:** limpeza simples dos duplicados. Cap do `_JSON_CACHE` opcional.

---

### 🟡 REVIEW — Commits com mensagem enganosa

#### `8b52c48 refactor(frontend): polish landing and desk entry`
**Realidade**: muda `engines/graham.py` (docstring), `engines/ornstein.py` (nova função `derive_entry_direction` fixando ablation `disable_divergence`), `tools/anti_overfit_grid.py`, `tools/batteries/phi_reopen_protocol.py`, `tools/deshaw_pairs_battery.py`, tests de graham/ornstein, docs/engines/*/grid.md e hypothesis.md. Só uma fração pequena é frontend de fato.

**Conteúdo das mudanças de engines:** válido e seguindo anti-overfit protocol. `disable_divergence` agora cai em signed deviation (metodologicamente honesto) — verdict aceito no audit ORNSTEIN 2026-04-21.

**Problema:** mensagem polui git history. Em `git bisect` futuro, esse hash vai ser invisível pra qualquer busca por "engine" ou "ornstein".

**Ação sugerida:** se for merge to main, squash ou rename.

#### `9213b04 fix(testing): stabilize full-suite launcher audit`
**Realidade**: muda `engines/bridgewater.py` (nova função `_runtime_sentiment_view` — zera `oi_df` quando `disable_oi=True` por segurança defensiva) + `api/server.py` + 18 testes + docs.

**Conteúdo das mudanças em bridgewater:** defensivo, não afeta outcome de trading (só sanitiza input que já seria ignorado a jusante).

**Problema:** mesmo diagnóstico — mensagem "testing" mascara mudança em engine quarantined.

**Ação sugerida:** registrar mentalmente; sem reverter.

#### `5187cad docs(research): finalize validation notes and archive decisions`
Toca `engines/graham.py` só com docstring (bloco de revalidation status). Trivial — não é problema real, mensagem mais ou menos OK.

---

### 🟡 REVIEW — `c7e1a91 fix(cockpit): isolate tunnel known_hosts for vps sync`

Isola `known_hosts` em arquivo per-tunnel — **correto em intenção**. Mas mantém `StrictHostKeyChecking=accept-new` que deixa a janela TOFU aberta no primeiro conectar. Pra tunnel que carrega tráfego do cockpit (leitura de equity/positions do VPS), aceitar chave nova sem checar é risco operacional real.

**Fix opcional**: adicionar `ssh-keyscan $HOST >> $KNOWN_HOSTS_FILE` nos scripts `deploy/install_paper_multi_vps.sh` / `deploy/install_shadow_multi_vps.sh` — pré-seed o known_hosts antes do serviço subir. Zero custo usabilidade, remove janela TOFU.

---

## Core protegido — verificação final

| Arquivo | Status |
|---------|--------|
| `core/indicators.py` | ✅ intacto |
| `core/signals.py` | ✅ intacto |
| `core/portfolio.py` | ✅ intacto |
| `config/params.py` | ✅ intacto |
| `config/keys.json` | ✅ intacto (verify_keys_intact.py exit 0) |

Codex honrou o contrato. **Nenhuma tentativa como o incidente 2026-04-15** (quando tentou mudar RSI pra fazer teste passar).

---

## Working tree não commitado (snapshot 2026-04-22)

13 arquivos M + 3 untracked. Coerente com:
- **Session log 20:27** (ORNSTEIN archive confirmado): `config/engines.py`, `engines/ornstein.py`, `docs/audits/2026-04-21_ornstein_recalibration.md`, `docs/sessions/2026-04-21_2027.md`
- **Kepos recalibration em progresso**: `tools/kepos_recalibration.py` (novo), `engines/kepos.py` (extração `_summarize_symbol_trades` + `run_backtest_on_features`), `tests/engines/test_kepos.py`
- **Metrics enhancement em paper/shadow runner**: `tools/operations/millennium_paper.py`, `tools/maintenance/millennium_shadow.py`, `tests/integration/test_paper_runner_tick.py`, `tests/tools/test_millennium_shadow_helpers.py` — novas stats `last_scan_scanned/dedup/stale/live/opened` no heartbeat
- **Perf caching (coerente com padrão do Codex)**: `api/routes.py` (cache TTL 2s em `/trading/positions`), `core/risk/risk_gates.py` (cache mtime-invalidated em `load_gate_config`)
- **PHI battery**: `docs/engines/phi/grid.md`, `tools/batteries/phi_reopen_protocol.py`

**Verdict:** trabalho válido em progresso, não commitado. Nada suspeito.

**Atenção em `core/risk/risk_gates.py`:** não é core protegido mas é camada de circuit breaker. Cache é mtime-based (pega edições de `risk_gates.json`), então baixo risco. Porém, **se um processo reescrever `risk_gates.json` com `mtime=now` duas vezes no mesmo segundo**, o cache pode servir a versão antiga. Edge case improvável, digno de mencionar.

---

## Consistência de documentação

- **Daily log `docs/days/2026-04-21.md`:** desatualizado. Declara "5 commits" no dia, real são 35. Seção "Sessões do dia" lista só as sessões do Claude. Precisa append das sessões Codex.
- **Session logs**: 3 arquivos (1003, 1130 Claude; 2027 Codex). 2027 está presente no working tree como untracked — foi criado mas não commitado.

---

## Recomendações (priorizadas)

1. **Fixar teste quebrado** (`test_render_detail_reuses_shell_for_paper_refresh`) — patch 1 linha. 🔴 urgente.
2. **Limpar duplicates em `core/ops/run_manager.py`** (L91-104, L222-300). 🟠 baixo-médio urgência.
3. **Rodar suite completa após commits do Codex** como regra — Codex não fez antes de commitar 6720c1a.
4. **Commitar working tree** conforme escopo (ORNSTEIN archive + KEPOS recal + metrics heartbeat + caching api/risk_gates). Sugestão de split em 3-4 commits por tema.
5. **Atualizar daily log 2026-04-21** com as sessões do Codex. 🟡
6. **Cap no `_JSON_CACHE`** em `shadow_contract.py`. Opcional.
7. **Pre-seed known_hosts** nos install scripts VPS. Opcional.
8. **No próximo merge to main**, considerar squash de `8b52c48` e `9213b04` pra história limpa.

---

## Veredito final

**Codex teve um dia produtivo e disciplinado dentro do contrato.** Volume alto (29 commits), core protegido intacto, padrões de caching razoáveis, cobertura de teste decente. **Mas falhou em rigor processual**: 1 teste quebrado por não rodar a suite, 2 mensagens de commit enganosas, 1 session log não commitado.

Nenhum dos achados exige revert. Nenhum toca lógica de trading real (sinais, custos, sizing, risco). O bug confirmado é cosmético em termos de produção (código funciona, só teste está desatualizado), mas é um red flag meta: **Codex precisa rodar `python -m pytest tests/` antes de commitar**. O smoke test (178/178 passed) não pegou porque é subset, não suite integration.

Ponto positivo forte: **a correção metodológica em ORNSTEIN `disable_divergence`** é exatamente o tipo de mudança que o protocolo anti-overfit pede — fix de mecanismo honesto, não knob tuning. E a decisão de manter o archive foi protocolo em ação, não hesitação.

---

## Apêndice — Commits auditados (completo)

| Hash | Tipo | Mensagem | Verdict |
|------|------|----------|---------|
| 6cf3a7a | Claude | fix(paper+shadow): priming, ts futuro e crash-loop | ✅ |
| b6b64a7 | Claude | fix(paper): portfolio gate V2 | ✅ |
| 1447cc1 | Claude | docs(sessions): 2026-04-21_1003 | ✅ |
| 511246c | Claude | fix(runners): desambiguar run_id paper/shadow | ✅ |
| 0b6d502 | Claude | docs(daily): atualizar 2026-04-21 | ✅ |
| 67ed86f | Claude | fix(metrics): export completo | ✅ |
| 67ed86f~29 → 6720c1a | Codex | vários (ver tabela de distribuição) | ver itens acima |
| **6720c1a** | Codex | perf(engines): reduce paper shadow entry blocking | 🔴 test broken |
| **8b52c48** | Codex | refactor(frontend) — msg enganosa | 🟡 review |
| **9213b04** | Codex | fix(testing) — msg enganosa | 🟡 review |
| **bd048d1** | Codex | perf(core) — duplicates + unbounded cache | 🟠 discuss |
| **c7e1a91** | Codex | tunnel isolation — TOFU aberto | 🟡 review |
| demais 24 | Codex | UI/splash/deploy/cockpit | ✅ clean |
