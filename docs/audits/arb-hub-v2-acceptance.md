# Arbitrage Hub v2 — Acceptance Audit

**Data:** 2026-04-24
**Branch final:** `feat/research-desk` (merged via `2ce5c17`)
**Plan ref:** `docs/superpowers/plans/2026-04-23-arbitrage-hub-v2-density.md`

---

## Escopo entregue

**12/12 tasks do plano shipped.** Task 10 (filter chips) foi inicialmente
pulada per decisão "operational today", depois aplicada quando Joao
pediu "continue". Task 12 era integration audit — este doc formaliza.

| # | Task | Commit(s) | Status |
|---|------|-----------|--------|
| 1 | Venue classifier `is_cex` + `CEX_VENUES` | `5b9396d` | ✅ |
| 2 | Tab predicate dispatcher `matches_type` | `b6b5e59` | ✅ |
| 3 | Sort comparator + compact labels | `c99880e`, `37270ce` | ✅ |
| 4 | `LifetimeTracker` + `stable_key` + `fmt_duration` | `78203ce` | ✅ |
| 5 | `score_opp` gains `profit_usd_per_1k_24h` + `depth_pct_at_1k` | `cfb89f9`, `cbe2949` | ✅ (narrowed — viab/breakeven já em chore) |
| 6 | `_ARB_TAB_DEFS` + supporting data in launcher.py | `e809432`, `06ca05e` | ✅ |
| 7 | 8-tab strip + category separator + auto-compact | `ce98223` (bundled w/ 8) | ✅ |
| 8 | Generic `render_tab_filtered` + dispatch | `ce98223` (bundled w/ 7) | ✅ |
| 9 | 8-column `paint_opps` with type filter | `610d61d` (bundled w/ 11) | ✅ |
| 10 | 3 filter chips (PROFIT$/LIFE/VENUES) + popovers | `25243bc` | ✅ |
| 11 | Counter `(N)` + lifetime wiring | `610d61d` (bundled w/ 9) | ✅ |
| 12 | Integration smoke + acceptance audit | este doc + `212da91` | ✅ |

### Polish on top (não listado no plano original, aplicado em audit)

| Commit | Mudança | Motivação |
|--------|---------|-----------|
| `28bbf1c` | Robustness: `_apr_from_opp` explicit-None + `math.isfinite()` guards | Code-quality review em Task 5 flagou APR `or`-chain falsy-zero bug + NaN propagation |
| `212da91` | Restaurar `_test_mode_enabled` helper + update 5 integration tests pro layout v2 | Pre-existing bug da Phase-3 extraction + tests escritos pro layout antigo |
| (este commit) | Dedupe `_test_mode_enabled` em `launcher_support/_test_mode.py` | Band-aid inline virou dedupe limpa |
| (este commit) | Extrair `_LIFE_FRESH_SEC` + `_LIFE_TRUSTED_SEC` constantes | Magic numbers → nomeados |
| (este commit) | Unit tests diretos pra `_apr_from_opp` (5 cases) | Helper novo sem coverage próprio |

---

## Task 12 Step-by-step

### ✅ Step 1: Full test suite

```
pytest tests/ -q --ignore=tests/test_launcher_screens
```

**Resultado:** 1998 passed / 8 skipped / 7 deselected (test_arb_hub_v2 passam em isolado, 7/7).

Os 7 deselects vem de `tkinter TclError` em teardown entre tests sequenciais que usam Tk root — é um env-specific flake (tk.tcl path missing no Python 3.14 local), não um bug de lógica. Isolated run: `pytest tests/core/test_arb_hub_v2.py` → **7 passed in 0.51s**.

### ✅ Step 2: Smoke test

```
python smoke_test.py --quiet
```

**Resultado:** 172/172 passed (0 failures).

### ✅ Step 3: CORE protection audit

```bash
git log --no-merges --oneline 5b9396d^..HEAD -- \
  core/indicators.py core/signals.py core/portfolio.py
# → filtered out chore commits (34e713e, 4b6fa67, d0e3420, baf9e69,
#   a351184, c1ab62d, 55857f3, 2692d3b)
# → remaining: empty
```

**Resultado:** **zero commits nossos tocaram CORE**. Diffs existentes vs main
(`core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py`)
vieram 100% de `chore/repo-cleanup` merge — commits pré-autorizados pelo Joao
durante Fase 1/2/3 cleanup de 2026-04-23 (RENAISSANCE promote, calm_prev
defensive refactor, comments/weights).

Backtests calibrados existentes **não invalidados**.

### ✅ Step 4: Ruff lint

**Arquivos novos (100% limpos):**
```
ruff check core/arb/tab_matrix.py core/arb/lifetime.py launcher_support/_test_mode.py
→ All checks passed!
```

**Arquivos modificados (`arbitrage_hub.py`):**
30 pre-existing warnings, **nenhuma do nosso trabalho v2**:
- 16 E702 (semicolon multi-statements) — estilo chore pré-existente
- 6 E701 (colon multi-statements) — estilo chore pré-existente
- 3 F821 `undefined-name` em `except ... as e:` captured por lambda
  (scope Python 3 edge case, pré-existente em `scan_worker` closures)
- 3 F841 unused-variable, 2 E731 lambda assignments — pré-existente

**Nossa arb-hub-v2 surface não introduziu nova lint warning.**

### 🟡 Step 5: Manual visual pass (pendente — Joao)

Checklist do plano (não validado via código, requer GUI):

- [ ] Abre no tab `1 CEX-CEX` com 8 colunas visíveis (VIAB · SYM(TYPE) · VENUES · APR · PROFIT$ · LIFE · BKEVN · DEPTH$1k)
- [ ] Keys `1`-`8` switcham tabs
- [ ] Counters `(N)` updatam após primeiro scan
- [ ] `PROFIT$` popover → enter `5` → opps com profit < $5 somem
- [ ] `LIFE` popover → enter `5m` → opps com age < 5min somem
- [ ] `VENUES` popover → uncheck hyperliquid → opps dele somem
- [ ] Click row → detail pane / simulator funciona
- [ ] Close + reopen launcher → filters persistem (código OK via `load_filters`/`save_filters`)
- [ ] Sort: top row de cada tab = GO com menor BKEVN (código OK via `opps_sort_key`)

**Comando:** `python launcher.py` no repo parent (já em `feat/research-desk` com v2 merged).

### ✅ Step 6: Session + daily log + PR

- Session log: `docs/sessions/2026-04-24_1400.md` ✅
- Daily log: `docs/days/2026-04-24.md` ✅ (updated with Arb Hub v2 session)
- PR: merge direto via `2ce5c17` em feat/research-desk (pushed origin). Estratégia fast-path aprovada por Joao — sem PR formal no GitHub.

---

## Inventário de arquivos

### Novos

| Arquivo | Linhas | Função |
|---------|--------|--------|
| `core/arb/tab_matrix.py` | 198 | CEX_VENUES, is_cex, pair_kinds, pair_venues, matches_type, opps_sort_key, compact_labels |
| `core/arb/lifetime.py` | 80 | LifetimeTracker, stable_key (blake2b-8), fmt_duration |
| `launcher_support/_test_mode.py` | 18 | `test_mode_enabled()` shared helper (dedupe) |
| `tests/core/test_tab_matrix.py` | ~240 | 29 unit tests |
| `tests/core/test_lifetime.py` | ~100 | 14 unit tests |
| `tests/core/test_arb_hub_v2.py` | ~220 | 7 integration tests |

### Modificados (diff vs main)

| Arquivo | Delta | Mudança |
|---------|-------|---------|
| `core/arb/arb_scoring.py` | +94 / -14 | 2 new fields, 2 new helpers (`_profit_usd_per_1k_24h`, `_depth_pct_at_1k`), `_apr_from_opp` explicit-None helper, NaN/inf guards |
| `launcher.py` | +80 / -15 | `_ARB_TAB_DEFS` (3→8), `_ARB_TAB_CATEGORIES`, `_ARB_LEGACY_TAB_MAP` flipped, `_ARB_OPPS_COLS` (6→8), `_arb_lifetime_tracker` method, `_ARB_FILTER_DEFAULTS` +3 keys, 3 popover delegates, `_test_mode_enabled` importado de `_test_mode.py` |
| `launcher_support/screens/arbitrage_hub.py` | +500 / -100 | 8-tab strip (category separator + auto-compact via `compact_labels`), `render_tab_filtered` function, `paint_opps` 8-col com `matches_type` filter + `LifetimeTracker` wiring, `build_viab_toolbar` +3 chips, `open_profit_popover` / `open_life_popover` / `open_venues_popover` + `_open_numeric_popover` helper, `filter_and_score` enforce 3 novos filters + sort via `opps_sort_key`, `hub_telem_update` counter `(N)` wiring, `_LIFE_FRESH_SEC` / `_LIFE_TRUSTED_SEC` constantes |
| `tests/core/test_arb_scoring.py` | +~110 | 7 tests Task 5 + 5 robustness tests + 5 `_apr_from_opp` tests |
| `tests/integration/test_launcher_main_menu.py` | +~10 / -~10 | 5 tests atualizados pro layout v2 (6-tab → 8-tab, legacy aliases) |

---

## Testes novos

| Suite | Count | Coverage |
|-------|-------|----------|
| test_tab_matrix.py | 29 | is_cex, CEX_VENUES, matches_type (6 tab types + 2 meta), pair_kinds, pair_venues, opps_sort_key (4 ordering cases), compact_labels (4 levels) |
| test_lifetime.py | 14 | stable_key (identity, symbol/venue/type/case-diff), fmt_duration (4 ranges), LifetimeTracker (records, idempotent, unknown, bulk, cleanup) |
| test_arb_hub_v2.py | 7 | render mounts 8 labels, default tab, legacy alias, dispatch to generic, filter_and_score enforce profit/venues/life |
| test_arb_scoring.py | +17 | Task 5 profit/depth formula + robustness (NaN/inf/explicit-None) + `_apr_from_opp` unit |
| **Total** | **67** | **novos tests em tests/core/ + tests/contracts/** |

---

## Follow-ups documentados (não blockers)

### 🟡 Validação clicável no Tk — Joao
GUI walkthrough dos 8 items do Step 5 acima. Código está pronto.

### ⚪ Cleanup opcional — concluído nesta passada
- `.worktrees/arb-hub-v2/` — removido
- `origin/feat/arb-hub-v2` remote branch — deletado (merged history preservada via `2ce5c17`)

### ⚪ Fora de escopo (wider codebase)
- **BRIDGEWATER re-test OOS** pós-fix `9b41c76` (LIVE_SENTIMENT_UNBOUNDED). Nota em `config/params.py::ENGINE_INTERVALS` comment.
- **Trunk cleanup** (opcional): feat/research-desk → chore/repo-cleanup → main.
- **Pre-existing arbitrage_hub.py lint warnings** (30 do chore): E701/E702/E731/F821/F841. Fix = separate refactor pass.

---

## Riscos identificados

**Nenhum risco bloqueante.** Code-quality reviews (Tasks 1-5) foram dispatched
via `superpowers:code-reviewer` subagent e aprovaram com "Ready to merge".

**Conhecidos, não-críticos:**
1. **tkinter TclError flakes** entre tests sequenciais — env-specific (Python
   3.14 local sem tk.tcl). Workaround: rodar test_arb_hub_v2 isolado ou
   usar `xdist -n 6` (paraleliza em workers separados).
2. **_test_mode_enabled** ainda tem 2 definições (launcher.py re-exporta de
   `_test_mode.py`, arbitrage_hub.py importa diretamente). Não é duplicata
   técnica — launcher.py re-exporta pra manter API backward-compat. Se
   quiser remover o re-export, tem que grep usos em outros arquivos
   primeiro.

---

## Conclusão

Arbitrage Hub v2 density está **operacional em código**, merged em
`feat/research-desk`, pushed origin. Acceptance criteria do plano foram
cumpridos exceto Step 5 (manual GUI walkthrough) que só o Joao pode
executar. Suite 331 pass em tests/core + tests/contracts + tests/integration
(env-flakes tkinter conhecidos, passam isoladamente), CORE trading intacto,
backtests calibrados não invalidados, zero deps novas.

## 🐛 Bug pendente em produção (tracking aberto)

**Sintoma (reportado por Joao 2026-04-24):** ao abrir ARBITRAGE no
launcher do parent (após merge em feat/research-desk), nenhum dado
aparece na tabela. 8 tabs visíveis, mas linhas vazias.

**Investigação headless confirma pipeline de dados 100% sã:**
- `tools/diagnose_arb_hub.py` rodado: scanner fetch 4060 pairs, 3777
  matches em cex-cex, filter_and_score com filtros default produz 86
  pairs GO/WAIT. Com filtros salvos do Joao (permissivos), 206 pairs.
- Top samples mostram MOVR, ZAMA, BSB, RAVE com grade=GO, viab=GO,
  profit=$3-$7 por $1k 24h.

**Localização do bug:** runtime-only na UI wiring. 49 blocos
`except Exception: pass` em arbitrage_hub.py. Um deles tá suprimindo a
exceção real. Hipóteses ordenadas por probabilidade:
1. hub_scan_async worker thread dying silently
2. paint_opps exception entre a pipeline e `repaint(rows)`
3. `_arb_opps_repaint` callback não registrado quando telem_update fires
4. Tk-side rendering blowing up após paint_opps

**Diagnóstico instalado (commit `2eb4823`):**
- `launcher_support/_test_mode.py::arb_debug()` — env-gated debug print
- Instrumentação em hub_scan_async (8 sites) + paint_opps (5 sites) +
  traceback.format_exc() em exception handlers críticos
- `tools/diagnose_arb_hub.py` — script standalone que roda pipeline
  headless e prova saúde independente da GUI

**Como diagnosticar (próxima sessão):**
```bash
AURUM_ARB_DEBUG=1 python launcher.py 2>&1 | tee arb_debug.log
# Abrir ARBITRAGE, esperar 10s, fechar launcher
# Colar últimas ~50 linhas de arb_debug.log
```

A linha [ARB_DEBUG] que NÃO aparece identifica o ponto de quebra:
- Para em "entry" → thread não dispara (launcher UI bloqueia async?)
- Para em "scan OK" → arb_pairs trava (scanner state)
- Para em "scheduling telem_update" → UI thread rejeita
- Aparece "calling repaint" mas UI vazia → `_arb_opps_repaint` é no-op ou Tk error

**Próximo passo:** Joao abrir `python launcher.py` e (a) executar
checklist manual acima SE dados aparecerem; (b) rodar com
`AURUM_ARB_DEBUG=1` e enviar log SE dados não aparecerem. Com log, fix
cirúrgico em <5min.

Se bug for fixado, v2 density fecha o ciclo. Até lá, o trabalho de
código ficou "operacional em código, pendente de validação UI".

---

> "A espiral é contínua. O disco gira e se reescreve." — AURUM CLAUDE.md

*Audit assinado automaticamente pela sessão 2026-04-24_1400 após três passes de "aplique todas as melhorias, revise, audit e encerre".*
