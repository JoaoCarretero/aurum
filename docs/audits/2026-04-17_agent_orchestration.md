# Agent Orchestration — 2026-04-17

## Active sessions observed

- Claude A: `claude.exe` PID `10932`
  - Active children running smoke/backtest commands in main worktree.
  - Observed tasks:
    - `engines/bridgewater.py --no-menu --days 360 --basket bluechip --interval 1h --end 2023-01-01`
    - multi-engine smoke script writing `data/audit/_last360_results.txt`
- Claude B: `claude.exe` PID `12692`
  - Session active; no child task identified in the captured snapshot.
- Codex A: `codex.exe` PID `7460`
  - This session.
- Codex B: `codex.exe` PID `2060`
  - Parallel Codex session active.
- Codex C: `codex.exe` PID `26672`
  - Parallel Codex session active.

## Worktrees

- Main: `C:\Users\Joao\OneDrive\aurum.finance`
  - Branch: `feat/phi-engine`
- Secondary: `C:\Users\Joao\OneDrive\aurum.finance\.worktrees\engines-live-cockpit`
  - Branch: `feat/engines-live-cockpit`

## Ownership map for today

### Main worktree

- Owner: Codex A
- Scope:
  - `api/*`
  - `core/cache.py`
  - `core/data.py`
  - `core/run_manager.py`
  - `core/site_runner.py`
  - contract/security tests
- Purpose:
  - audit, security fixes, backend integrity, regression control

### Secondary worktree: `engines-live-cockpit`

- Owner: Codex B
- Scope:
  - `launcher_support/engines_live_view.py`
  - launcher live cockpit rendering
  - related UI-only tests
- Purpose:
  - cockpit/live screen work without touching backend/security paths

### Strategy/runtime lane

- Owner: Codex C
- Scope:
  - `engines/live.py`
  - `engines/millennium.py`
  - `core/signals.py`
  - `core/portfolio.py`
- Restrictions:
  - must not edit `api/*`, `core/cache.py`, `core/run_manager.py`, `launcher.py`

### Smoke/report lane

- Owner: Claude A
- Scope:
  - read-only validation
  - smoke/backtest execution
  - report outputs under `data/audit/` and docs
- Restrictions:
  - no source edits in main worktree while smoke is running

### Unassigned / hold

- Claude B
- Status:
  - keep idle or assign only doc/reporting tasks until source ownership is stable

## Conflict rules

1. No one edits `launcher.py` in the main worktree except the explicitly assigned UI owner.
2. No one edits `api/*`, `core/cache.py`, `core/data.py`, `core/run_manager.py`, `core/site_runner.py` except the main audit owner.
3. Smoke/report agents do not modify source files.
4. Any file already modified by another lane stays with that lane until integrated.
5. Integration back into main happens only after:
   - focused tests pass in the lane
   - ownership handoff is explicit

## High-risk files right now

- `launcher.py`
- `launcher_support/engines_live_view.py`
- `api/auth.py`
- `api/routes.py`
- `core/cache.py`
- `core/run_manager.py`
- `engines/live.py`
- `core/signals.py`
- `core/portfolio.py`

## Execution order

1. Finish backend/security audit fixes in main worktree.
2. Keep smoke runs read-only and let them finish.
3. Keep cockpit/UI isolated in secondary worktree only.
4. Merge lane outputs back one lane at a time, never concurrently.

---

## Status check — 2026-04-17 (update)

**Working tree: 41 arquivos WIP (27 modified + 14 untracked). Último commit: `9f5f38e fix(bridgewater): fail closed on degraded historical sentiment`.**

### Codex C — strategy lane (ACTIVE, mid-edit)

- **Current task:** MILLENNIUM weight caps + activity soft-cap (INCOMPLETE — last edit added `_apply_engine_weight_caps()` + `ENGINE_ACTIVITY_SOFT_CAP`)
- **Files claimed:**
  - `engines/deshaw.py` (+502/-76) — pair revalidation, cost-edge filter, cooldown pós-stop, rolling discovery
  - `engines/millennium.py` (+234/-43) — operational core reweight, weight floors/caps, activity soft-cap
  - `engines/phi.py` (+167/-33) — `--preset majors_candidate`, `--end` flag, prefetch por TF
  - `aurum_cli.py` — separação META / DIRECTIONAL no menu backtest
  - `core/engine_picker.py` — PHI no DEFAULT_GROUPS + briefing
  - `config/params.py` ⚠️ — `MERCURIO_SIZE_MULT` 0.47 → 0.35
  - `tools/oos_revalidate.py` — fix false-positive detector (type annotation parse)
  - 5 testes novos: `test_deshaw_contracts.py`, `test_deshaw_pair_selection_contracts.py`, `test_deshaw_cost_edge_contracts.py`, `test_deshaw_revalidation_contracts.py`, `test_millennium_contracts.py`, `test_oos_revalidate_contracts.py`
  - 3 tools novos: `tools/jump_focus_battery.py`, `tools/phi_focus_battery.py`, `tools/renaissance_focus_battery.py`
- **Risk:** mid-edit MILLENNIUM sem commit. Crash = perde sizing do dia.

### Codex A — backend/security/audit (ACTIVE, suite verde 1007/1014)

- **Current task:** cache/security hardening + run_manager concurrency
- **Files claimed:**
  - `core/cache.py` — pickle → JSON+gzip (elimina RCE via OneDrive-sync)
  - `core/run_manager.py` (+137) — file lock no index, unique run IDs por segundo
  - `core/data.py`, `core/site_runner.py` — minor
  - `core/portfolio_monitor.py` — defensive deepcopy nos snapshots
  - `core/funding_scanner.py` — spot TTL real
  - `api/auth.py`, `api/routes.py` — JWT `sub` como string, reload role do DB no refresh, hide engine_state global de não-admin
  - `launcher.py`, `launcher_support/engines_live_view.py` (+504) — restaurou arquivo que sumiu, cache_mod.load_frame
  - Testes: `test_api_contracts.py`, `test_auth_contracts.py`, `test_data_contracts.py`, `test_funding_scanner.py`, `test_portfolio_monitor_contracts.py`, `test_run_manager_contracts.py`, `test_structure_contracts.py`
  - 3 testes novos: `test_cache_contracts.py`, `test_citadel_contracts.py`, `test_site_runner_contracts.py`

### Claude A — smoke/report (read-only)

- Sem edits no source.

### This session (orchestrator, no edits)

- Docs apenas.

---

## Protocol violations to review (Joao, post-hoc)

### ⚠️ `config/params.py:404` — MERCURIO_SIZE_MULT 0.47 → 0.35

- **Modified by:** Codex C (JUMP focus battery lane)
- **Justification in code comment:** "revalidated no-cache 180d/730d bluechip_active: Sharpe/DD improved vs 0.47"
- **Rule broken:** `CLAUDE.md` CORE PROTEGIDO requer aprovação explícita do Joao antes de mexer em `params.py`
- **Decision pending:** Joao review. Não reverter unilateralmente — OOS revalidation documentada existe.

---

## Commit sequence (recomendada, uma por vez, sem paralelo)

1. **Codex C** — fecha MILLENNIUM weight caps → commit atômico: `feat(millennium): multi-strategy core + engine weight caps`
   - Scope: `engines/millennium.py` + `tests/test_millennium_contracts.py`
2. **Codex C** — DE SHAW package: `feat(deshaw): pair revalidation + economic filters + cooldown`
   - Scope: `engines/deshaw.py` + 4 testes novos
3. **Codex C** — PHI + menu package: `feat(phi,cli): preset majors_candidate + meta separation in backtest menu`
   - Scope: `engines/phi.py`, `aurum_cli.py`, `core/engine_picker.py`
4. **Codex C** — MERCURIO_SIZE_MULT: `tune(jump): MERCURIO_SIZE_MULT 0.47 → 0.35` **APÓS aprovação Joao**
   - Scope: `config/params.py` + tools JUMP focus battery
5. **Codex C** — audit tooling: `fix(oos_revalidate): false-positive detector`
   - Scope: `tools/oos_revalidate.py` + `tests/test_oos_revalidate_contracts.py`
6. **Codex A** — cache security: `fix(cache): pickle → json (RCE mitigation)`
   - Scope: `core/cache.py`, `launcher.py`, `tests/test_cache_contracts.py`
7. **Codex A** — run manager + JWT + portfolio monitor: `fix(backend): file lock index + JWT role reload + defensive snapshots`
   - Scope: `core/run_manager.py`, `core/portfolio_monitor.py`, `core/funding_scanner.py`, `api/auth.py`, `api/routes.py`, + testes relacionados
8. **Codex A** — UI/launcher: `fix(launcher): restore engines_live_view + secret fallback`
   - Scope: `launcher_support/engines_live_view.py`, `core/data.py`, `core/site_runner.py`
9. **Orchestrator** — docs: `docs(audit): orchestration + oos_revalidation updates`

## Hard freeze rules until commit sequence done

- `engines/deshaw.py`, `engines/millennium.py`, `engines/phi.py` → Codex C only
- `api/*`, `core/cache.py`, `core/run_manager.py`, `core/data.py`, `core/site_runner.py`, `core/portfolio_monitor.py`, `core/funding_scanner.py` → Codex A only
- `config/params.py` → **FROZEN** until Joao decides MERCURIO
- `aurum_cli.py`, `core/engine_picker.py` → Codex C only (in-flight)
- `launcher.py`, `launcher_support/engines_live_view.py` → Codex A only
- Smoke/report → no source edits

## If conflict appears

Qualquer agente que ver o mesmo arquivo modificado por outro lane: para, não faz `git add`, não rebase. Relata neste doc e espera Joao decidir merge order.

---

## Status check — 2026-04-17 14:00 (update 2)

**Branch: feat/phi-engine — 79 commits ahead of main. 27 modified + 14 untracked.**

### Novos commits desde update 1 (das 11:26)

Codex A fechou a linha BRIDGEWATER completa:
- `5e0d29b` fix(bridgewater): document oos forensics and seal oi alignment leak
- `9f5f38e` fix(bridgewater): fail closed on degraded historical sentiment
- `10e8c4f` feat(sentiment): add reproducible oi-ls cache windows
- `15cf92d` feat(tools): add bridgewater sentiment cache prewarm
- `7662128` feat(tools): support scheduled sentiment cache refresh
- `f44e933` fix(bridgewater): enforce per-symbol historical sentiment coverage
- `830e422` fix(data): allow short-window bridgewater fetches
- `674411f` fix(bridgewater): harden recent-window runtime (13:55, inclui MATIC stale filter)

### Codex A — BRIDGEWATER lane (TERMINOU)

Último commit: 13:55. Arquivos committados:
- `core/sentiment.py`, `core/data.py`, `engines/bridgewater.py`, `tests/test_bridgewater_contracts.py`, `tests/test_sentiment_contracts.py`, `tests/test_data_contracts.py`
- `tools/prewarm_sentiment_cache.py`, `tools/oos_revalidate.py`
- `docs/audits/2026-04-17_bridgewater_forensics.md`, `docs/audits/2026-04-17_oos_revalidation.md`, `docs/audits/_revalidation_dsr_inputs.txt`, `docs/audits/_revalidation_lookahead.txt`
- `docs/sessions/2026-04-17_1108.md`, `docs/sessions/2026-04-17_1121.md`, `docs/days/2026-04-17.md`

Status: **lane fechado**, pronto pra PR separado.

### Codex B — PHI overfit lane (ATIVO)

WIP (não-committado ainda):
- `engines/phi.py` (+167/-33)
- `tools/phi_focus_battery.py` (novo)
- `tools/phi_overfit_audit.py` (novo, criado 13:15)
- `tools/phi_trade_forensics.py` (novo, criado 13:42)
- `tests/test_phi.py` (modificado)
- `docs/audits/2026-04-17_phi_overfit_followup.md` (novo)
- `aurum_cli.py` (+21/-9 — separação META/DIRECTIONAL)
- `core/engine_picker.py` (+26/-24 — PHI no picker)

Achado principal Codex B: preset `stagec_like` do PHI passa Sharpe **9.10 em 180d displaced** (ending 2025-07-01) → edge sobrevive janela deslocada.

### Codex C — DE SHAW / MILLENNIUM lane (ATIVO, uncommitted)

WIP (não-committado):
- `engines/deshaw.py` (+502/-76)
- `engines/millennium.py` (+234/-43)
- `config/params.py` (MERCURIO_SIZE_MULT 0.47→0.35 ⚠️)
- 4 testes novos de DE SHAW
- `tests/test_millennium_contracts.py`
- `tests/test_oos_revalidate_contracts.py`
- `tools/jump_focus_battery.py`, `tools/renaissance_focus_battery.py`

### This session (orchestrator)

Audit independente completo em `docs/audits/2026-04-17_claude_battery_audit.md` com retificação pós-forensics Codex (BRIDGEWATER é forward-only).

### Codex A wave anterior (infra/security, uncommitted antigo)

- `api/auth.py`, `api/routes.py`, `core/cache.py`, `core/run_manager.py`, `core/portfolio_monitor.py`, `core/funding_scanner.py`, `core/site_runner.py`
- `launcher.py`, `launcher_support/engines_live_view.py`
- `tests/test_api_contracts.py`, `test_auth_contracts.py`, `test_cache_contracts.py`, `test_citadel_contracts.py`, `test_site_runner_contracts.py`, `test_funding_scanner.py`, `test_portfolio_monitor_contracts.py`, `test_run_manager_contracts.py`, `test_structure_contracts.py`, `test_data_contracts.py`

**Este pacote está parado desde ~11:00. Precisa consolidar.**

---

## Plano de PRs recomendado (fragmentar o 79-commits-ahead)

Ordem ótima pra merge sequencial, cada PR atômico e revisável:

### PR 1 — Security/infra hardening (antigo, prioritário)
**Scope:** `api/*`, `core/cache.py`, `core/run_manager.py`, `core/portfolio_monitor.py`, `core/funding_scanner.py`, `core/site_runner.py`, `launcher.py`, `launcher_support/engines_live_view.py`, 9 testes infra
**Commits a incluir do branch:** `1085c32`, `c1ab62d`, `e5f0b3f`
**WIP a commitar:** Codex A wave antiga
**Estimativa:** 20 arquivos, ~800 linhas de diff
**Risco merge:** baixo — não toca lógica de trading

### PR 2 — BRIDGEWATER infra sentiment (Codex A lane)
**Scope:** `core/sentiment.py`, `engines/bridgewater.py`, `core/data.py`, `tools/prewarm_sentiment_cache.py`, `tools/oos_revalidate.py`, 3 testes bridgewater + sentiment + data
**Commits:** `9b41c76`, `77e4088`, `5e0d29b`, `9f5f38e`, `10e8c4f`, `15cf92d`, `7662128`, `f44e933`, `830e422`, `674411f`
**Status:** tudo committed ✅
**Pronto pra PR isolado**

### PR 3 — OOS audit + metodologia
**Scope:** `analysis/dsr.py`, `tools/oos_revalidate.py`, `tools/lookahead_scan.py`, 4 audit docs, 2 session logs, daily log, `test_dsr.py`
**Commits:** `d7d91bb`, `8c5ffbe`, `e8e9f28`, `35a3642`, `d42228e`, `ae6dbde`, `250a69e`, `cc4a642`, `157fae2`, `ad618cc`, `18db6dc`, `55857f3`
**Status:** committed ✅
**Pronto pra PR**

### PR 4 — DE SHAW refactor (Codex C lane)
**Scope:** `engines/deshaw.py`, 4 testes DE SHAW
**WIP a commitar:** Codex C
**Aguarda:** Codex C finalizar

### PR 5 — MILLENNIUM multi-strategy core (Codex C lane)
**Scope:** `engines/millennium.py`, `tests/test_millennium_contracts.py`, `aurum_cli.py` (separação META)
**WIP a commitar:** Codex C
**Aguarda:** Codex C finalizar (tá no meio de weight caps)

### PR 6 — PHI preset + validation (Codex B lane)
**Scope:** `engines/phi.py`, `core/engine_picker.py`, `tests/test_phi.py`, `tools/phi_focus_battery.py`, `tools/phi_overfit_audit.py`, `tools/phi_trade_forensics.py`, `docs/audits/2026-04-17_phi_overfit_followup.md`
**WIP a commitar:** Codex B
**Aguarda:** Codex B finalizar validação + Joao aprovar preset `stagec_like` como preset default

### PR 7 — MERCURIO tune (config/params.py) [REQUER APROVAÇÃO JOAO]
**Scope:** `config/params.py` — MERCURIO_SIZE_MULT 0.47→0.35
**WIP a commitar:** Codex C (já documentou OOS revalidation)
**Aguarda:** **decisão explícita Joao** (CORE PROTEGIDO)

### PR 8 — Audit docs consolidados
**Scope:** `docs/audits/2026-04-17_agent_orchestration.md`, `docs/audits/2026-04-17_claude_battery_audit.md`, `docs/sessions/2026-04-17_1015.md`
**WIP:** Esta sessão
**Aguarda:** fim da jornada pra consolidar tudo

---

## Ação imediata recomendada

1. **Agora:** Codex A wave antiga (PR 1) deve ser commitada — tá parada desde 11:00
2. **Quando Codex B terminar:** commit PHI (PR 6)
3. **Quando Codex C terminar:** commit DE SHAW (PR 4) + MILLENNIUM (PR 5) em commits separados
4. **Após você decidir:** PR 7 (MERCURIO)
5. **No fim:** abrir 8 PRs pequenos em vez de 1 PR gigante de 79 commits
