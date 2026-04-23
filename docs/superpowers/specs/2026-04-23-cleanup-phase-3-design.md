# Cleanup Phase 3 — "Architecture / launcher.py decomposition"

**Data:** 2026-04-23
**Branch alvo:** `feat/cleanup-phase-3` (de `chore/repo-cleanup`)
**Fase:** 3 de 3 no roadmap de otimização

## Contexto

Fases 1 e 2 concluídas:
- **Fase 1** (merge `0c8ae97`): deletou 4 engines arquivados + ruff F401 → −8,748 LOC net.
- **Fase 2** (merge `6a3c1d2`): pytest-xdist + lazy core.data.connections + defer iconbitmap → launcher import 829ms→149ms (5.5x), boot ~2074ms→868-1300ms (2x).

Resta a dívida arquitetural: **`launcher.py` com 9,574 LOC e 296 methods** na classe App, impedindo navegação/manutenção rápida. Já existe padrão estabelecido de extração em `launcher_support/screens/` (37 modules, 18,503 LOC total) via `render(app, ...)` pattern, mas **a migração foi ~60-70% feita** — screens estão extraídos, mas muitos App methods ainda não delegam (especialmente `_arb*`, `_dash*`, `_eng*`).

## Objetivo

Reduzir launcher.py de **9,574 LOC → ≤6,500 LOC** (-32% mínimo; target ideal -37% = 6,000 LOC) extraindo os 3 maiores clusters de methods (`_arb*`, `_dash*`, `_eng*` = 112 methods) para os modules existentes em `launcher_support/screens/`, via pattern de thin delegate.

Zero regressões funcionais — mesmo pass count de tests, mesmo behavior visual no launcher, VPS services intactos.

## Escopo

### A) Cluster `_arb*` — 48 methods
**Target module:** `launcher_support/screens/arbitrage_hub.py` (já existe, 1 função `render`).

Mover para funções em arbitrage_hub.py:
- `_arb_render_opps`, `_arb_render_pairs`, `_arb_render_rates`, `_arb_render_execute`
- `_arb_scan_*`, `_arb_refresh_*`, `_arb_filter_*`
- Helpers: `_arb_format_*`, `_arb_compute_*`

Dividir em 2 batches (24 methods cada) pra rollback granular.

### B) Cluster `_dash*` — 42 methods
**Target modules:** `launcher_support/screens/dash_home.py`, `dash_portfolio.py`, `dash_trades.py` (existem, 1 função `render` cada).

Dividir por sub-cluster:
- `_dash_home_*` → dash_home.py (batch 1)
- `_dash_portfolio_*` → dash_portfolio.py (batch 2)
- `_dash_trades_*` → dash_trades.py (batch 3)

### C) Cluster `_eng*` — 22 methods
**Target modules:** `launcher_support/screens/engines.py`, `engines_live.py` (existem).

Batch único (22 é pequeno).

### Pattern de extração (estabelecido)

**Antes** (em launcher.py, App class):
```python
def _arb_render_opps(self, ...):
    # 30-50 lines of body
    self._some_helper()
    return ...
```

**Depois** (em screens/arbitrage_hub.py):
```python
def render_opps(app, ...):
    # same body; self → app
    app._some_helper()
    return ...
```

**Delegate em launcher.py (App class, ~3 linhas):**
```python
def _arb_render_opps(self, ...):
    from launcher_support.screens.arbitrage_hub import render_opps
    return render_opps(self, ...)
```

Net reduction: ~30-50 LOC per method (body moved + delegate kept).

## Fora de escopo (explícito)

- **Outros clusters** (`_menu*` 15, `_results*` 13, `_data*` 10, `_site*` 10, `_exec*` 10, `_ui*` 10, restante) — fora desta fase; podem ir em Fase 3.1 futura
- **Signature changes** de App public methods — preservadas 100%
- **CORE trading files** (`config/params.py`, `core/signals.py`, `core/indicators.py`, `core/portfolio.py`) — CLAUDE.md protege
- **Refactor de `launcher_support/` boundaries** (ex: `cockpit_tab` vs `command_center` vs `dashboard_controls`) — fora; só puxa methods de launcher.py pra screens/
- **Testes novos** — só não-regressão

## Riscos e mitigações

| # | Risco | Mitigação |
|---|-------|-----------|
| 1 | Method chamado via `self.after(0, self._foo)` quebra | Delegate preserva nome e assinatura — chamadas `self._foo` continuam resolvendo |
| 2 | Method acessa `self.<state>` (attributes) | Refactor para `app.<state>`; App instance passada tem mesmo state |
| 3 | Method é referenciado em dict callback maps (ex: `_MENU_MAP = {"arb": self._arbitrage_hub}`) | Delegates preservam — dict keys continuam apontando pra método em self |
| 4 | Tests chamam `app._method()` diretamente | Delegate faz o mesmo trabalho — tests pass intocados |
| 5 | Cross-cluster calls (`_arb_X` chama `_dash_Y`) | `app._dash_Y` continua funcionando (delegate vira method em outro module, mas App instance vê via thin delegate) |
| 6 | Method tem closure sobre locals de `__init__` | Identificar via grep antes de extrair; se houver, refatorar pra usar state em `app` |

## Estratégia de execução

### Branch e commits

Criar `feat/cleanup-phase-3` a partir de `chore/repo-cleanup` (merge da Fase 2 incluído). Push no origin após cada commit. Merge-commit final em `chore/repo-cleanup`.

### Commits atômicos (7 total)

| # | Commit subject |
|---|----------------|
| 1 | `refactor(launcher): extract _arb_* methods (batch 1)` (24 methods) |
| 2 | `refactor(launcher): extract _arb_* methods (batch 2)` (remaining 24) |
| 3 | `refactor(launcher): extract _dash_home_* methods` |
| 4 | `refactor(launcher): extract _dash_portfolio_* methods` |
| 5 | `refactor(launcher): extract _dash_trades_* methods` |
| 6 | `refactor(launcher): extract _eng* methods` |
| Merge | Merge feat/cleanup-phase-3 into chore/repo-cleanup |

Batching protege contra rollback grande.

### Gates cumulativos (por commit)

Após cada commit:

1. `.venv/Scripts/python.exe -c "import launcher; app = launcher.App(); app.destroy()"` — boots sem exception
2. `.venv/Scripts/python.exe -m pytest tests/launcher/ tests/integration/test_launcher_main_menu.py --tb=no -q 2>&1 | tail -3` — mesmo pass count que baseline de Fase 2
3. `grep -c "def _arb_\|def _dash_\|def _eng" launcher.py` — diminui conforme commits avançam (296 → ~200)
4. `wc -l launcher.py` — diminui conforme commits avançam (9,574 → ≤6,500)

### Gate final (antes de merge)

- `launcher.py` ≤ 6,500 LOC
- App methods total ≤ 200 (via grep)
- Full pytest suite: mesmo pass count que Fase 2 (1666)
- Smoke manual do launcher: user abre + clica em 3 screens afetados (arb, dash, engines) — todos renderizam OK
- VPS services 12/12 active

### Rollback

Cada commit pushed individualmente ao origin = checkpoint. `git reset --hard <sha>` + `git push --force-with-lease` volta ao estado anterior granular.

## Critérios de sucesso (mensuráveis)

| Métrica | Baseline | Target | Como medir |
|---------|----------|--------|------------|
| launcher.py LOC | 9,574 | **≤6,500** (ideal ≤6,000) | `wc -l launcher.py` |
| App methods (total) | 296 | **≤200** | `grep -c "^    def " launcher.py` |
| Tests pass | 1666 | **=1666** | `pytest -q` |
| Launcher boot behavior | open/render OK | **same** | manual smoke |
| Launcher import time | 149ms | **≤200ms** (marginal regression acceptable) | `python -c "import launcher"` timing |
| VPS services | 12/12 active | **12/12** | SSH check |

**Go/No-Go pra merge:** TODAS as métricas atendidas, smoke manual user-verified pra 3 screens.

**Go/No-Go pra encerrar roadmap:** Fase 3 mergeada + user validated launcher em uso real.

## Dependências

- Pré-requisito: Fase 1 + Fase 2 mergeadas (already done, commits `0c8ae97` + `6a3c1d2`)
- Pré-requisito: `launcher_support/screens/` modules existentes (já existem, 37 modules)
- Pré-requisito: ruff F401 clean config (já em pyproject.toml)

## Não-decisões deferidas pra Fase 3.1 (se quisermos, futuro)

- Extrair clusters menores (`_menu*`, `_results*`, `_data*`, etc.)
- Repensar boundaries entre `launcher_support/*.py` (cockpit_tab, command_center, dashboard_controls)
- Abstrações para engines (consolidar paper/shadow runners)
- Move App class fora de launcher.py (ex: `launcher_app.py`)

## Referências

- `docs/superpowers/specs/2026-04-23-cleanup-phase-1-design.md` — Fase 1 precedente
- `docs/superpowers/specs/2026-04-23-cleanup-phase-2-design.md` — Fase 2 precedente
- `launcher_support/screens/arbitrage_hub.py` — pattern example (render function + delegate)
- `launcher_support/screens/dash_home.py` — pattern example
- CLAUDE.md — CORE protection + session log rules
