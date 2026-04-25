# DATA > ENGINES — inline detail page (debug-first)

**Status:** spec
**Date:** 2026-04-25
**Author:** Claude (Opus 4.7 1M, feat/research-desk)
**Branch:** `feat/engines-detail-page` (isolated worktree em `.worktrees/engines-detail`, off `feat/research-desk`)
**Successor to:** `docs/superpowers/plans/2026-04-24-engines-screen-polish.md` (typography polish, shipped 04-24)

---

## 1. Problema

A tela `DATA > ENGINES` hoje é split horizontal:

- **Esquerda 640px fixos**: filter chips ALL/SHADOW/PAPER + 11 colunas + linhas de runs (local + VPS + DB merged).
- **Direita expande**: detail pane com 3 blocos (RUNTIME / PERFORMANCE / LOG). **Vazio até clicar.**

Pain points reportados pelo Joao:
1. **Lista mal enquadrada.** 11 colunas em 640px no font 7pt ficam apertadas. Polish de 04-24 melhorou tipografia mas não framing.
2. **Pane direito desperdiçado.** Fica em branco até clicar — pesa visualmente sem entregar valor.
3. **Detalhe insuficiente para debug.** Quando algo dá errado num engine (live ou run antigo), o pane direito não tem dados suficientes pra diagnosticar — falta last_error completo, decisões skipped, cadence drift, cost decomposition, freshness de dados, log scrollable.
4. **Drift entre telas.** Cockpit, runs_history, /data engines, telegram — números nem sempre batem.

## 2. Objetivo

Substituir o split horizontal por um **drill-down**: a lista ocupa a tela inteira; clicar numa run abre uma **página nova full-screen** dedicada àquela run, organizada por **pergunta de debug**, com **máximo de dados possíveis** e **dados consistentes com as outras telas**.

**É upgrade, não rewrite.** Reaproveita helpers existentes (`_render_detail_*`, `lazy_fetch_heartbeat`, `RunSummary`, collectors). Adiciona blocos novos e move/expande os existentes.

## 3. Não-objetivos

- **Não** mudar lógica de trading. Zero toque em `core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py`.
- **Não** mexer em LiveRunsScreen / EngineLogsScreen / RunsHistoryScreen como pontos de entrada paralelos — eles continuam registrados pra splash quick-links e tecla R.
- **Não** mudar o pipeline de dados (collectors `collect_local_runs` / `collect_vps_runs` / `collect_db_runs` ficam intactos).
- **Não** redesenhar a sidebar / cockpit.
- **Não** quebrar testes existentes (`test_runs_history.py` 48/48 deve continuar verde).

## 4. Arquitetura

### 4.1 Novos arquivos

```
launcher_support/screens/engine_detail.py     ← novo screen full-page
launcher_support/engine_detail_view.py        ← render helpers (blocos ❶-❾)
tests/test_engine_detail.py                    ← contracts + smoke
```

### 4.2 Arquivos modificados

```
launcher_support/screens/registry.py          ← register("engine_detail", ...)
launcher_support/runs_history.py              ← list takes full width;
                                                row click navega pra
                                                engine_detail (não mais
                                                _load_detail no pane direito)
launcher_support/screens/engines.py           ← header reflete drill-down
                                                ("ESC voltar ao list" some,
                                                vira "click row pra detail")
```

### 4.3 Pattern de navegação

ScreenManager (`launcher_support/screens/manager.py:ScreenManager`) expõe `mgr.show(name, **kwargs)` — kwargs vão pro `on_enter`. O wrapper no app é tipicamente `app._screen_manager.show("engine_detail", run=r)` ou similar; o callsite exato depende do app field name (`app._screen_mgr` vs `app.screen_manager`) — confirmar lendo `engines_live.py` durante Step 3 e seguir o mesmo padrão.

Click numa row em `runs_history._render_run_row` (modo list) chama o helper de nav. `EngineDetailScreen.on_enter(run=r)` recebe a run e pinta. `on_exit()` cancela auto-refresh timer via `_after` cleanup automático da Screen base class.

## 5. Layout da página nova (scroll vertical único, debug-first)

```
┌─────────────────────────────────────────────────────────────┐
│ > DATA > ENGINES > MILLENNIUM PAPER · 2026-04-24_174017p   │ ← breadcrumb
│                                                              │
│ HEADER ─────────────────────────────────────────────────────│
│ MILLENNIUM PAPER · running · vps01    [⎘ run_id]  [R]reload │
│ started 14h32m ago · last tick 47s ago (esperado 15min)     │
└─────────────────────────────────────────────────────────────┘

❶ TRIAGE (something broken right now?)
   • LAST ERROR banner (red, full stack se houver)
   • Heartbeat freshness: now - last_tick_at vs expected cadence
   • Service status: running / zombie / stale (filter de stale_threshold 30min)
   • Run integrity: heartbeat.json / trades.jsonl / signals.jsonl present?

❷ TICK CADENCE (engine alive?)
   • tick_sec esperado · real · drift
   • uptime · primed flag · ks_state · warmup status
   • last 20 ticks: timestamp + duration sparkline ASCII

❸ SCAN FUNNEL (last tick — por que trade X não abriu?)
   • scanned → dedup → stale → live → opened
   • PROBE: top_score · threshold · n_above_threshold · n_above_strict
   • last_novel_at + age

❹ DECISIONS (last 30 signals — por que cada um?)
   • TS · SYMBOL · DECISION · score · REASON
   • REASON ∈ {opened, stale, max_open, dir_conflict, corr_block, portfolio_gate}
   • filter chip: ALL / OPENED / SKIPPED / STALE

❺ POSITIONS & EQUITY (state agora)
   • Open positions tabela: SYMBOL · DIR · ENTRY · MARK · PnL$/% · STOP · TARGET · age
   • Equity: now · peak · drawdown_now% · drawdown_max%
   • Exposure_pct · # symbols touched · gross / net leverage

❻ TRADES (closed) — full audit
   • Tabela completa scrollable
   • Cols: TS · SYM · DIR · ENTRY · EXIT · PNL$ · R · EXIT_REASON · slippage$ · commission$ · funding$
   • Filter por símbolo/direção · sort por TS / PnL / R
   • Footer: total trades · win_rate · avg_R · sharpe (rolling) · sortino

❼ DATA FRESHNESS (cache ok?)
   • Last bar per symbol: TS · age · gap detect
   • Source (cache / live) · prewarm hits · cache hit %

❽ LOG TAIL (raw output)
   • Last 200 lines (vs 25 hoje)
   • Filter level: ALL / DEBUG / INFO / WARN / ERROR
   • Substring search box
   • "tail -f" mode (auto-scroll on new lines se status==running)

❾ ADERÊNCIA vs BACKTEST (paper / shadow only)
   • Match % · last audit run timestamp
   • Divergências: lista de (símbolo, trade_id, diff)
   • Skipped pra live se não houver audit artifact
```

**Tipografia**: reusa o tier system de 04-24 — H1 10pt bold (titles), H2 8pt bold (block headers + filter chips), COL 7pt bold (column headers), BODY 7pt (data), BODY-emph 7pt bold (PNL/SYMBOL/key fields). Numéricos right-aligned.

**Cores semânticas**: GREEN positive, RED negative, AMBER warning, DIM stale, MODE_* no header (paper=CYAN, demo=GREEN, testnet=AMBER, live=RED).

## 6. Lista (esquerda, agora full width)

Com o pane direito morto:

- **Largura**: lista expande pra largura total da janela (vs 640px fixos hoje).
- **Colunas (14, era 11)**: adiciona `SHARPE` · `DD%` · `#POS` no meio. Ordem nova:
  ```
  ST · ENGINE · MODE · STARTED · DUR · TICKS · SIG · EQUITY · ROI · DD% · SHARPE · #POS · TRADES · SRC
  ```
- **Larguras (chars)**: ENGINE 11→14 (RENAISSANCE/BRIDGEWATER inteiros, espaço pra futuras), STARTED 13 (mantém), demais ajustam pra encaixar full width sem horizontal scroll em janelas ≥1280px.
- **Hover state**: row fica `BG3` no hover (já funciona).
- **Click**: dispara `app.show_screen("engine_detail", run=r)` em vez de `_load_detail(r, state)`.

## 7. Refresh & navegação

### 7.1 Auto-refresh
- `EngineDetailScreen.on_enter(run=r)` checa `r.status`:
  - `running` → arma `_after(5000, _refresh)` que repete (auto-tick 5s, igual cockpit). Re-fetch heartbeat (lazy se VPS) + trades.jsonl tail + signals.jsonl tail + log.txt tail.
  - `stopped` ou `done` → snapshot estático, sem timer. `[R] reload` botão manual no header.
- `on_exit()` cancela timer via `_after` cleanup automático (Screen base class).

### 7.2 Navegação
- **ESC** → `app.show_screen("engines")` (volta pra lista).
- **Breadcrumb top**: `> DATA > ENGINES > MILLENNIUM PAPER · 2026-04-24_174017p`. Click em `ENGINES` volta pra lista; `DATA` volta pro DATA CENTER.
- Lista preserva selected_run_id (state["selected_run_id"]) e scroll position pra UX continuous.

## 8. Data alignment (consistência cross-screen)

Garantir que cockpit, runs_history, /data engines, telegram **mostram o mesmo número**. Source of truth por bloco:

| Bloco | Helper canônico | Cache TTL |
|---|---|---|
| HEADER (status, started, mode) | `RunSummary` (já compartilhado) | n/a |
| ❶ TRIAGE | `r.heartbeat.last_error`, `core.ops.run_catalog.is_run_stale`, `resolve_status` | inline |
| ❷ TICK CADENCE | `r.heartbeat.last_tick_at`, `last_scan_*` | inline |
| ❸ SCAN FUNNEL | `r.heartbeat.last_scan_*`, `last_novel_at` | inline |
| ❹ DECISIONS | local `signals.jsonl` tail; **cockpit endpoint `/v1/runs/{id}/signals` NÃO EXISTE hoje** — VPS path requer endpoint novo (Step 5) ou fallback "VPS signals indisponível" | 5s |
| ❺ POSITIONS | cockpit `/v1/runs/{id}/positions` ✓ | 5s |
| ❺ ACCOUNT | cockpit `/v1/runs/{id}/account` ✓ | 5s |
| ❺ EQUITY | cockpit `/v1/runs/{id}/equity` ✓ + `r.equity_now/peak` | 5s |
| ❻ TRADES | cockpit `/v1/runs/{id}/trades` ✓ ou local `trades.jsonl` | 5s |
| ❻ FOOTER (sharpe rolling, win_rate, sortino, avg_R) | helper novo `core/analytics/run_metrics.py` — derived em-memória do trades; cockpit pode adotar depois pra ground truth comum | inline |
| ❼ DATA FRESHNESS | derivado de heartbeat `last_*_at` fields hoje; **endpoint dedicado `/v1/runs/{id}/data_freshness` NÃO EXISTE** — Step 8 cria ou skipa graceful | 5s |
| ❽ LOG TAIL | local `log.txt` ou cockpit `/v1/runs/{id}/log` ✓ (singular, não `/logs`) | 5s |
| ❾ ADERÊNCIA | daily audit artifact `data/audit/<YYYY-MM-DD>.json` — payload tem `engines.{engine}` com summary (match_pct, missed, extra). Lookup: latest JSON file by mtime; encontra row do engine; skipa graceful se ausente | inline |

**Anti-drift**: footer pequeno DIM no rodapé da página com timestamp do último refresh + source (`local | vps:cockpit | db`). Se source vier de cache, mostra age.

**Não duplicar lógica**: se cockpit já calcula sharpe rolling em algum helper, reusar. Se não, criar `core/analytics/run_metrics.py` e refatorar cockpit pra também usar — assim ambos saem do mesmo helper.

## 9. Implementação — sequência incremental

Cada step é commitável e roda smoke verde.

1. **Step 1 — extract list-only mode em `runs_history.py`** (fix lista cols + remoção do pane direito)
   - Adiciona `mode="list"` flag em `render_runs_history()` que skipa criação do `right` frame.
   - Atualiza `_COLUMNS` pra incluir SHARPE/DD%/#POS, ajusta widths.
   - Mantém o split atual como modo `mode="split"` pra compat com runs_history padrão (`/data > runs history` quick-link).
   - `engines.py` chama com `mode="list"`.

2. **Step 2 — `EngineDetailScreen` skeleton + registro**
   - Cria `launcher_support/screens/engine_detail.py` com `EngineDetailScreen(Screen)`.
   - `build()` cria container + breadcrumb + scroll frame.
   - `on_enter(run=r)` recebe run e pinta header + ESC binding.
   - Registra em `registry.py` como `engine_detail`.
   - Sem auto-refresh ainda; sem blocos ❶-❾ ainda — só esqueleto + ESC voltando.

3. **Step 3 — wire row click → drill-down**
   - `runs_history._render_run_row` em modo `list`: click chama `app.show_screen("engine_detail", run=r)`.
   - State preserva `selected_run_id` pra UX.
   - Adiciona breadcrumb voltar funcionando.

4. **Step 4 — bloco ❶ TRIAGE + ❷ CADENCE** (debug essentials primeiro)
   - Move/expande `_render_detail_health` + adiciona Triage banner + cadence drift card.
   - Helpers vão pra `engine_detail_view.py`.

5. **Step 5 — bloco ❸ SCAN FUNNEL + ❹ DECISIONS**
   - Reusa `_render_detail_scan` + `_render_detail_probe` (mover de runs_history.py pra engine_detail_view.py).
   - Cria seção DECISIONS lendo `signals.jsonl` tail (last 30) com filter chips.

6. **Step 6 — bloco ❺ POSITIONS & EQUITY**
   - Tabela de open positions com mark price live (cockpit endpoint).
   - Equity sumarizada (já existe parcial em `_render_detail_equity_metrics`).

7. **Step 7 — bloco ❻ TRADES full**
   - Expande `_render_detail_trades` (last 10) pra tabela completa scrollable.
   - Adiciona footer com win_rate, avg_R, sharpe (helper novo `core/analytics/run_metrics.py`).
   - Filter por símbolo/dir.

8. **Step 8 — bloco ❼ DATA FRESHNESS + ❽ LOG TAIL**
   - DATA FRESHNESS: parse de heartbeat fields (criar endpoint cockpit se necessário).
   - LOG TAIL: 200 lines, level filter, search box, tail-f auto-scroll.

9. **Step 9 — bloco ❾ ADERÊNCIA**
   - Lê `data/audit/{engine}_{run_id}_match.json` se existir; renderiza match% + divergences. Skip se não existir.

10. **Step 10 — auto-refresh wiring**
    - Status `running` → 5s timer via `Screen._after`.
    - Status `stopped/done` → snapshot estático + botão `[R]`.

11. **Step 11 — testes + manual checklist**
    - `tests/test_engine_detail.py`: contracts (block presence per status), smoke (mock RunSummary, mount/unmount sem crash).
    - Manual visual checklist (10 items).

12. **Step 12 — drift footer + cleanup**
    - Footer DIM com source/timestamp do refresh.
    - Remove código morto em `runs_history.py` (helpers movidos pra engine_detail_view.py).

## 10. Testing

- **Existing**: `tests/test_runs_history.py` 48/48 deve continuar verde (split mode preservado).
- **New**:
  - `test_engine_detail_render_per_status` — RUNNING / STOPPED / DONE / STALE renderiza blocks certos.
  - `test_engine_detail_navigation` — ESC volta pra `engines`; breadcrumb click idem.
  - `test_engine_detail_auto_refresh_only_when_running` — timer armado se running, none se stopped.
  - `test_engines_list_full_width_columns` — `mode="list"` skipa right pane; `_COLUMNS` tem 14.
  - `test_engine_detail_smoke` — mount com fake RunSummary, on_exit limpa timers.

Suite alvo: 167+ smoke + 48 runs_history + ~12 engine_detail = ~227 testes.

## 11. Riscos

| Risco | Mitigação |
|---|---|
| Drift entre cockpit/detail page | helpers compartilhados em `core/analytics/run_metrics.py`; footer com source visível |
| Auto-refresh leak (timer não cancela) | `Screen._after` cleanup automático em `on_exit` (já testado em outros screens) |
| Endpoint cockpit `/data_freshness` ainda não existe | bloco ❼ skipa graceful se 404; backlog adiciona endpoint |
| Audit artifact pode não existir pra runs antigas | bloco ❾ skipa graceful + label "no audit data" |
| `runs_history.py` fica fragmentado entre split/list modes | refactor commit-by-commit; teste de cada modo |
| Performance degrada com 14 cols + 50+ rows | virtualização não necessária no escopo (limite pragmático: 200 rows merged) |
| Conflito com lane de outro Claude (ex: cockpit-trade-chart, engines-rebuild) | isola em branch nova `feat/engines-detail-page` (worktree dedicada); rebase final |

## 12. Dependências

- **Cockpit endpoints existentes** (verificados em `tools/cockpit_api.py`):
  - `/v1/runs/{id}/heartbeat` ✓
  - `/v1/runs/{id}/trades` ✓
  - `/v1/runs/{id}/positions` ✓
  - `/v1/runs/{id}/account` ✓
  - `/v1/runs/{id}/equity` ✓
  - `/v1/runs/{id}/log` ✓
- **Endpoints que precisam ser criados** (sub-tasks dentro dos respectivos Steps):
  - `/v1/runs/{id}/signals` (Step 5, bloco ❹) — tail of `signals.jsonl` no run_dir do VPS
  - `/v1/runs/{id}/data_freshness` (Step 8, bloco ❼) — extrai `last_bar_at` per symbol do heartbeat ou cache state; **opcional** se bloco ❼ derivar do heartbeat hoje
- **`core/ops/run_catalog`**: já tem `is_run_stale`, `resolve_status` (usado em /data engines hoje).
- **`launcher_support/runs_history.py`**: refator de modo dual (split vs list).
- **Screen pattern**: `Screen` base class + `ScreenManager.show(name, **kwargs)` (`launcher_support/screens/manager.py:44`) — kwargs vão pro `on_enter`.
- **Daily audit artifact**: `data/audit/<YYYY-MM-DD>.json` (script `tools/debug/audit_live_vs_backtest_daily.py` na branch `fix/shadow-tick-cadence`); fallback graceful se ausente.

## 13. Resultado esperado

- DATA > ENGINES vira tela limpa de browse com 14 colunas alinhadas (lista full-width, sem pane direito vazio).
- Click numa run abre página drill-down com 9 blocos debug-first (~scrollable, auto-refresh 5s se RUNNING).
- ESC ou breadcrumb volta pra list preservando seleção.
- Suite verde, CORE intocado, dados consistentes com cockpit/telegram/runs_history.
- Cobertura debug ampla: por que trade X não abriu, engine alive?, custos certos?, dados frescos?, crash?, aderência vs backtest? — todas respondíveis na própria página.

---

## Apêndice A — perguntas de debug ↔ blocos da página

| Pergunta | Bloco que responde |
|---|---|
| Algo quebrou agora? | ❶ TRIAGE |
| Engine ainda tickando? | ❷ CADENCE |
| Por que trade X não abriu? | ❸ SCAN FUNNEL + ❹ DECISIONS |
| Quais sinais foram skipped por qual razão? | ❹ DECISIONS |
| Estado da carteira agora? | ❺ POSITIONS & EQUITY |
| Trade Y perdeu por quê? | ❻ TRADES (entry/exit/decomposição cost) |
| Custos batem? (slippage/commission/funding) | ❻ TRADES (footer + per-trade decomp) |
| Performance até agora (sharpe/win_rate)? | ❻ TRADES (footer agregado) |
| Dados frescos? Cache estourou? | ❼ DATA FRESHNESS |
| Engine crashou? Stack trace? | ❶ TRIAGE banner + ❽ LOG TAIL (filter ERROR) |
| Live bate com backtest? | ❾ ADERÊNCIA |

## Apêndice B — referências cruzadas

- `docs/superpowers/plans/2026-04-24-engines-screen-polish.md` — typography polish (predecessor)
- `docs/sessions/2026-04-24_2035.md` — polish session log
- `launcher_support/runs_history.py` — código atual da tela
- `launcher_support/engines_live_view.py` — cockpit (data alignment reference)
- `launcher_support/screens/base.py` — Screen ABC + lifecycle
- `launcher_support/screens/registry.py` — registration pattern
- `core/ops/run_catalog.py` — collectors + status resolvers compartilhados
- `MEMORY.md` — CORE protegido (não tocar)
- `CLAUDE.md` — sessão regras (session log obrigatório)
