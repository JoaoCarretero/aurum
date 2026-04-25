# Auditoria Geral AURUM — 2026-04-25

> **Modo:** read-only, 5 lanes em paralelo (tech-debt / engines / ops / testes / security).
> **Tempo de relógio:** ~25 min de dispatch + síntese.
> **Origem:** pedido `Joao: tudo` em resposta ao menu de escopo da sessão 2026-04-25 manhã.
> **Estado git no início:** branch `feat/research-desk` clean, em sync com origin.

---

## Sumário executivo

5 subagents read-only varreram o repo (~310 .py / ~26k LOC). Resultado:

- **4 CRIT** — bloqueiam live trading ou indicam regressão imediata.
- **4 HIGH** — débito estrutural com risco real (testes, governance de engine, código god-class).
- **2 MED** — convergem em violação de protocolo MEMORY §2 + drift de docs vs realidade.
- **~12 LOW/MED** operacionais — backlog limpo mas conhecido.

**Veredicto global:** o sistema está em estado *funcionalmente saudável* (smoke 172/172, keys intact, hub drift 0, git clean) **mas tem 4 itens CRIT que devem ser endereçados antes da próxima sessão de live trading.** Os dois mais urgentes são (a) regressão de testes desde ontem e (b) duas das três camadas de risk gate mandadas pelo CLAUDE.md ainda não existem em código.

**O que NÃO está sob risco:** CORE (intocado), keys.json (intacto), kill-switch operacional, hub orientation, smoke suite. O trabalho da semana passada (~675 commits integrados) sobreviveu à auditoria.

---

## TOP-10 cross-lane (sequência de prioridade)

| # | Severidade | Issue | Lane | Evidência | Ação imediata |
|---|---|---|---|---|---|
| 1 | 🔴 CRIT | **Regressão de 16 testes** em `tests/core/test_arb_hub_v2.py` desde 2026-04-24 | 4 | `module 'launcher' has no attribute 'App'` em todos | Restaurar export de `App` ou atualizar import path |
| 2 | 🔴 CRIT | **`drawdown velocity` gate ausente** (CLAUDE.md mandata 3 camadas) | 5 | `core/risk/risk_gates.py:163-171` só implementa peak-to-current DD | Implementar `gate_dd_velocity` antes da próxima live |
| 3 | 🔴 CRIT | **`anomaly detection` gate ausente** (CLAUDE.md mandata 3 camadas) | 5 | nenhum gate de spread/latência/OOD em `_ALL_GATES` (linha 263) | Implementar `gate_anomaly` antes da próxima live |
| 4 | 🔴 CRIT | **`api/risk_check.py` fail-open** quando snapshot falha | 5 | `api/risk_check.py:47-65` retorna `equity=0` → todos balance gates `allow` | Retornar `soft_block` em modo real-money quando snapshot falhar |
| 5 | 🟠 HIGH | **BRIDGEWATER 8/8 anti-overfit fail não-actioned** | 2 | `data/anti_overfit/bridgewater/2026-04-21_191254/results.csv` DSR p=0.000 | **Decisão Joao:** falha no mérito ou cache OI/LS insuficiente? |
| 6 | 🟠 HIGH | **CITADEL com 1 contract test** (apenas logging) | 4 | `tests/contracts/test_citadel_contracts.py` — 1 função | Backfill: contract tests pra `decide_direction`, `calc_levels`, `label_trade` |
| 7 | 🟠 HIGH | **RENAISSANCE / TWO SIGMA / AQR / WINTON com zero tests** | 4 | `tests/**/test_*<engine>*.py` retorna nada | Mínimo: contract de import + assinatura de `run_backtest` |
| 8 | 🟠 HIGH | **`engines/live.py` é god class de 2485 linhas** | 1 + 5 | 7 concerns (`CandleBuffer`, `SignalEngine`, `OrderManager`, `PositionState`, `RiskEngine`, `ExecutionDrift`, `LiveEngine`); 23/59 funções tipadas | Extrair pra `engines/live/` (uma classe por módulo) |
| 9 | 🟠 HIGH | **PHI veredicto nunca finalizado** | 2 | `docs/audits/2026-04-22_deshaw_phi_ornstein_archive_verdict.md:121` ainda `[PENDENTE]` | Re-run grid OU escrever entry final de archive |
| 10 | 🟡 MED | **`bot/telegram.py` viola MEMORY §2** | 5 | `bot/telegram.py:57-58` raw `json.load(open(keys.json))` | Trocar por `load_runtime_keys()` de `core.risk.key_store` |

**Convergências cross-lane** (issue tocado por >1 agent independente):

- **`engines/live.py`** apareceu em Lane 1 (god class) + Lane 5 (gates faltando) + Lane 4 (cobertura fraca). Triangulação: arquivo de maior risco do repo.
- **Drift de docs vs realidade trading**: Lane 2 + Lane 3 ambos flagaram divergência entre `docs/days/2026-04-24.md` (BW awaiting cache) e estado real (battery already failed 2026-04-21).
- **Contract tests inexistentes pra engines vivas**: Lane 2 + Lane 4 ambos identificaram CITADEL/RENAISSANCE/orquestradores sem cobertura, contradizendo a regra fundadora 2026-04-15.

---

## Lane 1 — Tech Debt

### Stats
- Total .py: ~310 (excluindo `.venv`)
- Total LOC: ~26k
- Files >2000 LOC: 4
- Test functions: 2,101 em 163 test files
- Test/code ratio: ~0.7:1

| File | Lines |
|------|-------|
| `engines/live.py` | 2,485 |
| `macro_brain/dashboard_view.py` | 2,181 |
| `launcher.py` | 7,497 |
| `engines/millennium.py` | ~1,600 |

### TOP-10 findings

1. **[HIGH | L]** `launcher.py` é god object de 7,497 linhas — single `App` class com ~291 métodos. Apesar do refactor Fase 3 (-43%), métodos como `_site_*` em 7384-7416 já são thin delegators. Backlog claro: continuar extraindo pra `launcher_support/`.

2. **[HIGH | M]** **26 compat shims em `core/`** (`db.py`, `portfolio.py`, `engine_base.py`, `fs.py`, `proc.py`, `run_manager.py`, `persistence.py` e mais 19) são stubs de 6 linhas redirecionando pra `core/ops/`, `core/risk/`, `core/data/`, `core/ui/`. Suprimem IDE go-to-definition e mascaram hierarquia que nunca estabilizou. Após auditoria de callers, deletar.

3. **[HIGH | S]** **`engines/citadel.py:66-109` duplica `EngineRuntime`** de `core/ops/engine_base.py:15-53`. CITADEL nunca usa o canonical — tem versão própria com setup divergente (UTC stamps, 3 handlers vs 2). Migrar pra `EngineRuntime`.

4. **[HIGH | M]** **`engines/live.py`: 2485 linhas, 7 concerns, 23/59 funções tipadas.** Maior arquivo de risco do repo (real money asyncio). Extrair `CandleBuffer`, `SignalEngine`, `OrderManager`, `PositionState`, `RiskEngine`, `ExecutionDrift`, `LiveEngine` cada um pro próprio módulo.

5. **[MED | S]** **`export_json` duplicado** em citadel:569, jump:472, bridgewater:985, renaissance:59, millennium:1496. Bugs de serialização (ex: trades.jsonl sessão 2026-04-24 21:15) precisam ser propagados manualmente. Criar `analysis/report_export.py`.

6. **[MED | S]** **`core/hawkes.py` órfão** — único caller fora de testes é `engines/graham.py:101`, e GRAHAM está informalmente arquivada. KEPOS (caller original) foi deletada 2026-04-23. Mover pra `engines/_archive/`.

7. **[MED | M]** **`macro_brain/dashboard_view.py` é monolito de 2181 linhas sem sub-package paralelo.** Aplicar mesmo pattern do `launcher_support/`: criar `macro_brain/views/` e split por tab.

8. **[MED | S]** **`engines/millennium.py:31` import de citadel** é exceção documentada, mas `engines/millennium_live.py:32` cria cadeia transitiva: `live → millennium → citadel`. Side effects de citadel (RUN_DIR global, log mutation 35-43) vazam pra millennium_live. Mover `OPERATIONAL_ENGINES` pra `config/engines.py`.

9. **[MED | S]** **`core/htf.py` e `core/data/htf.py` coexistem.** Um deles é canonical, outro é shim ou drift. Verificar qual e deletar/shimnar o outro.

10. **[LOW | M]** **`analysis/` fragmentada em 16 files** — `walkforward.py` (60 linhas), `montecarlo.py` (tiny), etc. Sem facade `run_full_suite(trades, ...)`. Cada engine repete a chain de 6 chamadas. Adicionar `analysis.run_suite(trades, config) -> RunReport`.

---

## Lane 2 — Engines / Trading

### Status matrix
| Engine | Declared (MEMORY §4) | Última validação | Drift | Docs H/G/C | Próxima ação |
|---|---|---|---|---|---|
| CITADEL | ✅ EDGE_DE_REGIME (decay flag) | OOS 2026-04-16 + reval 2026-04-17 | Run 15d recente Sharpe -3.28 (decay confirmado anedotalmente) | ❌ / ❌ / ❌ | Re-run formal protocol em janela 180d |
| JUMP | ✅ EDGE_REAL DSR ~1.0 | Multi-window 2026-04-17 (BEAR/BULL/CHOP) | Sem audit pós-2026-04-17 | ❌ / ❌ / ❌ | OK; backfill docs |
| RENAISSANCE | ⚠️ inflado 2× real ~2.4 | 2026-04-22 audit_verdict | Run 360d in-sample Sharpe 5.10 (= claim inflado) | só audit_verdict | **Promoção bypassou protocolo 8-passos** |
| BRIDGEWATER | ⚠️ quarentena, ETA 2026-06-19 | Anti-overfit 2026-04-21 | **Battery 8/8 fail: train ≤ -1.03, test -25.96, holdout 0 trades, DSR p=0.000** | ✅ / ✅ / ✅ | **Decisão Joao** (ver Issue #5 cross-lane) |
| PHI | 🆕 overfit_audit | Run 2026-04-22 | 8 trades, "insufficient_sample" — verdict ainda `[PENDENTE]` | ✅ / ✅ / ❌ | Re-run grid OU archive final |
| JANE STREET | ⚪ arb live | n/a (scanner) | — | ❌ | OK |
| GRAHAM | 🗄️ experimental | — | docstring archivado, registry stage="experimental" | ✅ / ✅ / ❌ | Alinhar stage |
| MILLENNIUM/2σ/AQR/WINTON | orquestradores | — | — | ❌ | aceitável |

### Specific findings

- **CITADEL decay**: nenhum audit formal 180d-recent em `docs/audits/`. `data/runs/citadel_2026-04-24_092853/summary.json` 15d mostra Sharpe -3.28, ROI -1.16% — anedótico mas consistente com flag MEMORY. Sem artifact pinning o número 180d quotado em §4.

- **BRIDGEWATER post-fix `9b41c76`**: revalidação 2026-04-17 reduziu Sharpe BEAR 11.04→4.93 mas marcou `INVALID_OOS_LIVE_SENTIMENT`. Battery 2026-04-21 (8 configs × 3 windows) rodou pós-fix em janelas 10/9/10d → **uniformly negative Sharpe + DSR p=0.000 em todas as variantes**. Per protocolo Rule 5 → archive. Mas MEMORY §5 nuance + memory `feedback_pushback_on_quick_archive.md` dizem: investigar split antes de arquivar pra edges episódicos. **Pendência em `docs/days/2026-04-24.md` está stale** — a re-test JÁ aconteceu, falhou; ou doc ou MEMORY §4 desatualizado.

- **PHI overfit_audit**: grid registrado (`docs/engines/phi/grid.md` splits 2026-04-21). Run mais recente `data/phi/2026-04-22_1602/` produziu 8 trades + `metrics_note: "insufficient_sample"`. Archive verdict doc tem `[PENDENTE]` placeholder pra resultado PHI. `checklist.md` missing.

- **RENAISSANCE drift**: última validação formal = 2026-04-22 audit_verdict (promoted research → validated com base em single OOS BEAR 2022). Run 2026-04-22 reporta Sharpe 5.10 in-sample (claim inflado, não corrigido ~2.4). Promotion explicitamente "pragmática, não protocol-compliant".

- **JUMP post-DSR**: nenhum decay audit desde 2026-04-17. Runs recentes `data/jump/` são tick-level live shadow com `reports/` vazio e sem `summary.json`.

### Registry / protocol drift

- **`config/params.py`** — linhas 247, 313, 314 carregam comentários legacy `iter5/iter6` (não literais `WINNER` mas anti-pattern per MEMORY §5). Trocar por `tuned_on/oos_sharpe`.
- **`config/engines.py` vs MEMORY §4** — 12 engines listadas (consistente). Drift de stage:
  - PHI: registry `stage=research`, MEMORY diz `overfit_audit`
  - RENAISSANCE: registry `stage=research`, audit_verdict diz `validated`
  - GRAHAM: stage `experimental`, mas docstring diz arquivado
- **Stale orphan dirs**: `data/aqr/`, `data/meanrev/`, `data/runs/`, `data/ornstein/`, `data/_deshaw_battery/`, `data/kepos/`, `data/medallion/` — não em `data/index.json`, engines deletadas. Candidatos a cleanup.

---

## Lane 3 — Operational / Runtime

### Health dashboard
| Área | Status | Evidência |
|---|---|---|
| keys intact | 🟢 | exit 0 |
| hub drift | 🟢 | 0 warnings (7/7 OK) |
| smoke test | 🟢 | 172/172 |
| git clean | 🟢 | working tree clean, `feat/research-desk`, em sync |
| stashes | 🟡 | 4: `{0}` cockpit-controls em research-desk; `{1-3}` órfãs ref deleted `feat/cleanup-phase-3` |
| DB rows | 🟢 | 157 (== ontem) |
| DB size | 🟢 | 500 KB (cresceu 64 KB; VACUUM holding) |
| index.json | 🟡 | mtime 2026-04-24 09:29 — **stale 26h** |
| disk total | 🟢 | data/ = 794 MB |
| audit cronjob | 🔴 | `data/audit/daily/` não existe localmente (cronjob VPS desde 2026-04-24, artifacts não puxados) |

### Issues
1. **[MED]** Daily audit cronjob artifacts não landing local. VPS roda `aurum_audit_daily.timer` 23:00 UTC (commit `60f68d0`). Adicionar rsync/scp ou aceitar VPS-only retention.
2. **[MED]** `index.json` 26h stale. 21 novas runs bridgewater 2026-04-24 09:03-16:25 não reconciliadas. **Comando: `python -m tools.reports.reconcile_runs`**.
3. **[MED]** `feat/per-engine-runners` — 22 commits behind origin (non-FF rejected ontem). Decisão pendente: rebase ou force-with-lease.
4. **[MED]** Orphan LINKUSDT SHORT — millennium paper run `2026-04-21_012204` não existe local mas VPS heartbeat ainda diz running. SSH flatten.
5. **[LOW]** Stashes `{1-3}` órfãs (ref deleted branch). Triar e drop.
6. **[LOW]** 4-6 feature branches stale 5-7d (`feat/lane-2b-hmm`, `feat/millennium-paper`, `feat/safety-tests-live-janestreet`, `feat/website-refinement`, `feat/foundation-hardening`, `feat/claude-protocol-4engines`). Trending mas <14d.
7. **[LOW]** 20+ janestreet smoke leftover state dirs em `data/janestreet/2026-04-21_18*`. Sweep com `cleanup_orphan_run_dirs.py`.

---

## Lane 4 — Tests / Coverage

### Suite summary
- **pytest sequential: 2114 passed / 8 skipped / 16 FAILED em 42.44s** (vs 2034/0 ontem — **regressão**).
- smoke: 172/172 (0.0s) — ↑ vs 167 ontem.
- `pytest -n 6` falha: `pytest-xdist` listado em `[dev]` mas **não instalado** no env.
- Slowest 5: alchemy_state_contracts (2.20s), hmm_cache_integration (1.96s), chronos_hmm (1.59s/0.94s), paperclip_client (1.01s) — nada alarmante.

### Coverage map (CORE + engines)
| Source | Test | Ratio | Verdict |
|---|---|---|---|
| `core/indicators.py` | `tests/contracts/test_indicators_contracts.py` | 41/8 | ✅ OK |
| `core/signals.py` | `tests/contracts/test_signals_contracts.py` | 46/7 | ✅ OK |
| `core/portfolio.py` (shim) | `tests/contracts/test_portfolio_contracts.py` | 31/5 | ✅ OK |
| `config/params.py` | **none** | 0 | ❌ MISSING |
| CITADEL | `tests/contracts/test_citadel_contracts.py` | **1** (logging plumbing only) | ❌ WEAK |
| JUMP | `tests/contracts/test_jump_contracts.py` | 7 | ✅ OK |
| RENAISSANCE | **none** | 0 | ❌ MISSING |
| BRIDGEWATER | `test_bridgewater_contracts.py` + 4 tools | 30 | ✅ OK |
| PHI | `tests/engines/test_phi.py` | 33 | ✅ OK |
| JANE STREET | `test_janestreet_contracts.py` | 4 | 🟡 WEAK |
| GRAHAM | `tests/engines/test_graham.py` | 29 | ✅ OK |
| MILLENNIUM | 11+3 | 14 | ✅ OK |
| TWO SIGMA | **none** | 0 | ❌ MISSING |
| AQR | **none** | 0 | ❌ MISSING |
| WINTON | **none** | 0 | ❌ MISSING |

### Skip triage
- Stale (>30d, re-enableable): **0** — todos `pytest.skip` são runtime guards.
- Env-gated (aceitável): ~3 — `test_phase_c_*`, `test_research_desk_tabs.py`, `test_signals_contracts.py::skip("LEVERAGE=1.0")`.
- Platform/runtime guards: ~16 — Tk-unavail, supertrend-data-thin, Windows-only proc, `risk_gates.json` missing.

### TOP issues

1. **[CRIT]** **16 falhando em `tests/core/test_arb_hub_v2.py`** — `module 'launcher' has no attribute 'App'`. Daily log claim 2034/0 ontem. Engines-polish merge dropou `App` ou tests foram desmascarados. Triagar hoje, NÃO skipar.
2. **[HIGH]** CITADEL com 1 contract test (logging only) pra flagship live engine. Adicionar contracts pra `decide_direction`, `calc_levels`, `label_trade`.
3. **[HIGH]** RENAISSANCE / TWO SIGMA / AQR / WINTON com zero tests. Mínimo: import contract + signature de `run_backtest`.
4. **[MED]** `config/params.py` sem invariant tests — CORE protected mas nada trava `LEVERAGE`/`SLIPPAGE`/`MAX_OPEN_POSITIONS` contra edits silenciosos.
5. **[MED]** `pytest-xdist` no `[dev]` mas não instalado — workflow `pytest -n 6` silenciosamente quebrado.
6. **[MED]** `tests/conftest.py:27-34` monkeypatch de pytest internal sem restore — leaks entre invocações.
7. **[LOW]** `tests/contracts/test_htf_contracts.py:94-96` — `try/except Exception: pass` swallowing em vez de `pytest.raises`.
8. **[LOW]** JANE STREET com 4 contract tests pra arb engine real-money no cockpit.

---

## Lane 5 — Security / Risk Gates

### Risk gate matrix

| Gate | Implementado | Wired live.py | Tested | Notas |
|---|---|---|---|---|
| Drawdown (peak-to-current) | ✅ | ✅ | ✅ | `gate_daily_dd` + `gate_daily_loss` |
| Exposure (gross + net notional) | ✅ | ✅ | ✅ | soft-block only |
| Consecutive-loss circuit breaker | ✅ | ✅ | ✅ | soft N=3, hard N=6 |
| Single-position cap | ✅ | ✅ | ✅ | re-checa pré-`_open_position` |
| Kill-switch manual | ✅ | ✅ | ✅ | flatten idempotente |
| **Drawdown velocity** | ❌ | ❌ | ❌ | **CLAUDE.md mandata, ausente** |
| **Anomaly detection** | ❌ | ❌ | ❌ | **CLAUDE.md mandata, ausente** |
| Freeze window | ✅ | ✅ | ✅ | 21-02 UTC |

### Secrets exposure scan
- Hardcoded creds: **none**.
- Logger leaks: **none**.
- `json.load(keys.json)` violations: **1** — `bot/telegram.py:57-58` (raw `open()` + `json.load`). `engines/live.py:268` faz mesmo dentro de `_load_keys()` — wrappers próprio com encrypted-first, marginal mas notável.
- `.gitignore`: `config/keys.json` + `config/keys.json.enc` listados (linhas 38-39). ✅
- `verify_keys_intact`: não executado (forbidden no scope read-only).

### Findings

1. **[HIGH]** **Anomaly detection gate ausente** — CLAUDE.md spec é "Drawdown velocity, exposure limits, anomaly". `_ALL_GATES` em risk_gates.py:263 não tem anomaly. KillSwitch em live.py é outcome-based (PnL streak), não a "anomaly" gate. Definir `gate_anomaly` antes da próxima live.
2. **[HIGH]** **Drawdown velocity gate ausente** — `core/risk/risk_gates.py:163-171`. `gate_daily_dd` é peak-to-current static, não rate-of-change. Cliff de 3% em 10 min passa todos os gates até static breach. Adicionar `gate_dd_velocity(state, cfg)` com `dd_velocity_pct_per_hour`.
3. **[MED]** `bot/telegram.py:57-58` raw `json.load(open(keys.json))` — bypassa encrypted store. Trocar por `load_runtime_keys()`.
4. **[MED]** `api/risk_check.py:47-65` fail-open — se `PortfolioMonitor.refresh()` raise, `_fetch_snapshot` retorna `None` → `equity=0` → todos balance gates `<= 0` early-return `allow`. Network blip em real-money desativa silenciosamente todo balance circuit breaker. Retornar `soft_block` sentinel.
5. **[LOW]** `config/risk_gates.json` versionado com thresholds live (`max_daily_loss_pct: 3.0`, `max_daily_dd_pct: 5.0`). Visível com repo read access; edit emergencial requer commit. Mover live + arbitrage_live pra `config/risk_gates.local.json` gitignored.
6. **[LOW]** `deploy/install_shadow_vps.sh` sem `chmod` em config/. Adicionar `chmod 700 config && chmod 600 config/*.json`.

---

## Backlog operacional (não-bloqueante)

Cleanups e drifts conhecidos que NÃO bloqueiam trabalho mas são dívida observável:

- Reconciliar `data/index.json` (`python -m tools.reports.reconcile_runs`)
- Triar `git stash list` `{1-3}` (ref deleted branch — drop ou archive)
- Decidir `feat/per-engine-runners` non-FF (rebase vs force-with-lease)
- Flatten posição órfã LINKUSDT SHORT no VPS
- Pull rsync de `data/audit/daily/*.json` do VPS
- Sweep `data/janestreet/2026-04-21_18*` smoke leftovers
- Trim 26 compat shims em `core/` (após auditar callers)
- Arquivar `core/hawkes.py` se GRAHAM for arquivada formalmente
- Trocar `params.py:247,313,314` legacy iter comments
- Alinhar registry stage de RENAISSANCE/PHI/GRAHAM com MEMORY §4
- 4-6 feature branches stale 5-7d (triagar)
- Cleanup dirs `data/{ornstein,kepos,medallion,_deshaw_battery,meanrev}` (engines deletadas)
- Mover `OPERATIONAL_ENGINES` pra `config/engines.py` (quebrar transitive import)

---

## Sequência sugerida de ação

**Hoje (CRIT — antes de qualquer outra coisa):**
1. Triar 16 falhas em `tests/core/test_arb_hub_v2.py` — entender se foi merge regression ou desmascaramento
2. Decidir BRIDGEWATER (Issue #5): falha no mérito ou cache OI/LS insuficiente? Atualizar MEMORY §4 + daily 2026-04-24 com a verdade

**Esta semana (HIGH — antes da próxima sessão de live trading):**
3. Implementar `gate_dd_velocity` em `core/risk/risk_gates.py`
4. Implementar `gate_anomaly` em `core/risk/risk_gates.py`
5. Fixar `api/risk_check.py` fail-open
6. Backfill contract tests pra CITADEL (decide_direction / calc_levels / label_trade)
7. Backfill contract tests mínimos pra RENAISSANCE / TWO SIGMA / AQR / WINTON

**Esta sprint (MED — débito estrutural):**
8. Resolver PHI verdict ([PENDENTE] → final)
9. Trocar `bot/telegram.py:57-58` pra `load_runtime_keys()`
10. Adicionar `tests/contracts/test_params_invariants.py`
11. Instalar `pytest-xdist` (ou dropar `-n 6` do CLAUDE.md)

**Backlog (LOW — quando sobrar tempo):**
- Extrair `engines/live.py` (god class) — 7 módulos
- Trim 26 compat shims em `core/`
- Migrar `engines/citadel.py:66-109` pra `EngineRuntime`
- Continuação extraction de `launcher.py`
- Demais itens do backlog operacional acima

---

## Anexo — Lanes que não convergiram
Nenhuma. Todas as 5 retornaram com findings actionáveis. Triangulação cross-lane confirmou 3 issues (live.py, BW drift, contract test gaps) — alta confiança nesses três.

---

**Auditor principal:** Claude Code (Opus 4.7 1M)
**Lanes paralelas:**
- L1 tech-debt: `feature-dev:code-explorer` (agent `a38205f7e3623e95f`)
- L2 engines: `general-purpose` (agent `a10295501a41f9837`)
- L3 ops: `general-purpose` (agent `a19b3fdd458b21cb8`)
- L4 testes: `general-purpose` (agent `aff0068d02e3b2b01`)
- L5 security: `feature-dev:code-reviewer` (agent `a73450eaed0909646`)

---

## Apêndice — Fase 1 execução (2026-04-25 manhã)

### ✅ Concluído

| # | Issue | Commit | Tests |
|---|---|---|---|
| 1 | Test regression `test_arb_hub_v2.py` (16 falhas) | `c951f44` | 2114→2129 passed |
| 4 | `api/risk_check.py` fail-open em live mode | `b8c0fdb` | +5 contract tests |
| 10 | `bot/telegram.py` raw `json.load` | `02a5830` | +5 contract tests |

**Root cause #1 (não era regressão recente):** `tests/launcher/__init__.py` vazio fazia `tests/launcher/` virar pacote chamado `launcher` que sombrava `launcher.py` em `sys.modules`. Daily log de ontem chamava de "env-flake excluded" mas era esse bug latente. Fix: deletar 2 `__init__.py`. Suite full: 2129 passed / 8 skipped / 0 failed / 1 error (Tcl env, pré-existente).

### ⏸️ Pulado em Fase 1 (precisa decisão Joao)

| # | Issue | Razão |
|---|---|---|
| Op | Reconcile `data/index.json` | 17 missing dirs (referenciados no índice mas movidos pra `_archive/` ontem ou deletados na Fase 1 de cleanup). Decidir o que purgar do índice vs preservar requer julgamento histórico. |
| Op | Triagem stashes órfãs | `stash@{0}` cockpit-controls v2 (current branch, KEEP). `stash@{1}` adiciona engine CAPULA ao registry (engine não existe no repo). `stash@{2}` adiciona +153 linhas a `docs/engines/bridgewater/hypothesis.md` ("Revisão 2026-04-23"), modifica `engines/bridgewater.py` + tools — trabalho não-integrado. `stash@{3}` duplicata literal de `{2}`. **Dropar qualquer um requer decisão tua.** |

### ⏭️ Próxima fase

Fase 2 (HIGH risk gates + tests, ~6-8h) bloqueada nas tuas decisões:
- BW (#5): archive / quarentena / investigar?
- PHI (#9): re-run / archive?
- Anomaly gate (#3) signal: spread / latency / OOD / múltiplo?
- live.py extraction: skip esta sprint?
