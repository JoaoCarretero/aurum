# Cleanup Phase 2 — "Performance & Dev Loop"

**Data:** 2026-04-23
**Branch alvo:** `feat/cleanup-phase-2` (de `chore/repo-cleanup`)
**Fase:** 2 de 3 no roadmap de otimização

## Contexto

Phase 1 "Clear The Decks" foi mergeada em `chore/repo-cleanup` (merge commit 0c8ae97). Removeu 8,748 LOC net (4 engines arquivados, imports unused via ruff F401, 138 fixes).

Phase 2 ataca **performance dos loops de dev** (rodar tests + abrir launcher). Observou-se:

| Métrica | Valor atual | Fonte |
|---------|-------------|-------|
| Test suite (1677 tests) | **62s** | `pytest tests/ --ignore=tests/test_cockpit_paper_endpoints.py` |
| Launcher import | **829ms** | `python -c "import launcher"` |
| Launcher boot total | **~2074ms** | `data/.launcher_logs/screens.log` (09:25 baseline) |
| Top import offender | `core.data.connections` 641ms | `python -X importtime` |

Tempo acumulado por ciclo de iteração: ~65s (rodar tests) + ~2s (abrir launcher) = 67s de latência em cada mudança. Meta: **≤25s** total.

Phase 3 (arquitetura — decomp launcher.py 13k LOC) fica pra sessão dedicada. Nesta fase, só instrumentação + lazy + fixes targeted.

## Objetivo

Reduzir latência dos dois loops principais do dev:
- Test suite: **62s → ≤25s** (parallelism via pytest-xdist)
- Launcher import: **829ms → ≤400ms** (lazy imports de pandas/requests/hmmlearn/arch)
- Launcher boot total: **~2074ms → ≤1000ms** (profiling + hot-path fixes)

Zero regressões funcionais — mesma pass count de tests (1666), launcher abre normal, VPS services intactos.

## Escopo

### A) pytest parallelism (Fase 2a)

- Add `pytest-xdist>=3.5,<4` em `pyproject.toml [dev]`
- Reinstall venv: `pip install -e ".[all,dev]"`
- Run `pytest -n auto` — medir speed + detectar flakies
- Se algum teste flaky sob parallel: marcar com `@pytest.mark.serial` + configurar xdist pra respeitar
- Opcional (se gains forem sólidos e estáveis): adicionar `-n auto` em `[tool.pytest.ini_options] addopts` default. Se preferir ad-hoc, deixar pra usuário invocar manualmente.

### B) Launcher boot instrumentation (Fase 2a)

Adicionar ~8-12 `emit_timing_metric("boot.XXX", ms=elapsed)` em `launcher.py` `App.__init__` cobrindo:
- `super().__init__()` (Tk root creation)
- `tk_setPalette`
- `_configure_windows_dpi`
- `iconbitmap` loading
- Queue/state init
- `_chrome()` (já instrumentado — confirmar)
- `_splash()` (já instrumentado — confirmar)
- Shadow poller / tunnel setup

Após inserir metrics, rodar launcher 1x. Ler `data/.launcher_logs/screens.log` e identificar top 3 bottlenecks no gap não-instrumentado (~1200ms).

**Enabler pra Fase 2b** — sem profile, lazy imports e hot-path fixes são chute.

### C) Lazy imports no launcher (Fase 2b)

Mover os imports top-level pesados identificados no importtime profile (principalmente `core.data.connections`) pra dentro das funções que consomem:

- `from core.data import fetch, fetch_all, validate` (carrega pandas 350ms transitive) → dentro de backtest/scan callbacks
- `from core.chronos import enrich_with_regime, *` (carrega hmmlearn + arch) → dentro de HMM-using paths
- `from analysis import equity_stats, walk_forward, *` → dentro de results screen rendering

**Preservar re-exports** se algum test mockear via `@patch("launcher.fetch_all")`. Grep antes pra saber quais nomes precisam ficar top-level via `# noqa: F401`.

**Target:** `python -c "import launcher"` em ≤400ms.

### D) Hot-path otimizações (Fase 2b, data-driven)

Baseado no profile do commit B. Formas típicas:
- `iconbitmap` carrega o .ico file — pode ser `after_idle` (icon aparece pós-first-frame)
- `_configure_windows_dpi` faz ctypes call — pode cachear se for idempotente
- `tk_setPalette` varre widget defaults — pode reduzir escopo
- Widget creation loops — batch ou lazy

Aplicar 1-3 fixes targeted. Cada um commit separado (fácil de reverter).

## Fora de escopo (explícito)

- **`_collect_live_signals` paralelo** (trading core, high risk, zero ROI enquanto novel=0)
- **OHLCV cache** (já existe em `data/.cache/`)
- **CORE protegidos** (`config/params.py`, `core/signals.py`, `core/indicators.py`, `core/portfolio.py`)
- **Decomposição de `launcher.py`** (Fase 3)
- **pytest-xdist avançado** (sharding, load-balancing não-default — só `-n auto`)

## Riscos e mitigações

| # | Risco | Mitigação |
|---|-------|-----------|
| 1 | pytest-xdist quebra tests com shared state (tempdirs, DB SQLite writes sem lock, fixtures globais) | Detectar no commit 1. Marcar com `@pytest.mark.serial` + filter config pra xdist (commit 2). Se muitos: `--dist loadfile` (isola por arquivo) |
| 2 | Lazy imports quebram test mocking (`@patch("launcher.fetch_all")`) | Pré-commit: `grep -rn "patch.*launcher\\." tests/`. Preservar top-level re-export via `# noqa: F401` nos nomes mockados |
| 3 | Lazy move primeiro-call latency pra first-click (paga 300ms pandas na 1ª ação) | Aceito por design — boot > 1st click em ROI. Documentar no commit msg |
| 4 | `emit_timing_metric` adiciona overhead (irônico) | Cada call: ~1ms (1 log.info + 1 dict write). Ignorável |
| 5 | DPI skip/lazy quebra scaling em monitor HiDPI | Só mexer em DPI se profile indicar >200ms. Validar em monitor ≥125% scaling |
| 6 | iconbitmap lazy causa "flash" sem icon no primeiro frame | Imperceptível com after_idle. Grep tests pra verificar se algum valida icon presence |

## Estratégia de execução

### Branch e commits

Criar `feat/cleanup-phase-2` a partir de `chore/repo-cleanup` atualizado (inclui merge da Fase 1). Push no origin após cada commit. Merge-commit no final em `chore/repo-cleanup`.

### Ordem de commits

| # | Commit subject | Gate |
|---|----------------|------|
| 1 | `chore(deps): add pytest-xdist to [dev]` | `pytest -n auto` <25s, 1666 pass |
| 2 | `chore(tests): mark serial tests (if needed)` | opcional; só se commit 1 revelar flakies |
| 3 | `perf(launcher): instrument boot with timing metrics` | metric entries em screens.log |
| 4 | `perf(launcher): lazy-load pandas-heavy imports` | import <500ms |
| 5 | `perf(launcher): lazy-load chronos/analysis imports` | import <400ms |
| 6 | `perf(launcher): <hot-path fix from commit 3 profile>` | (1-3 commits data-driven) |

### Gates cumulativos

Cada commit tem gate de validação antes do próximo. Se gate falha: `git reset --hard <sha>` + diagnosticar + ajustar.

### Rollback

Push-per-commit dá checkpoints granulares. Rollback fácil via `git reset --hard <prev-sha>` + `git push --force-with-lease`.

## Critérios de sucesso (mensuráveis)

| Métrica | Baseline | Target | Medição |
|---------|----------|--------|---------|
| Test suite wall time | 62s | **≤25s** (ideal ≤20s) | `time pytest -n auto -q` |
| Test pass count | 1666 | **=1666** (zero regressão) | pytest output |
| Launcher import time | 829ms | **≤400ms** | `python -c "import time; t0=time.perf_counter(); import launcher; print(int((time.perf_counter()-t0)*1000))"` |
| Launcher boot total | ~2074ms | **≤1000ms** | `boot.until_shell_ready` em screens.log |
| F401 residuals | 0 | **0** (mantido) | `ruff check --select F401` |
| VPS services | 12/12 active | **12/12 active** | SSH check (sanity) |

**Go/No-Go pra merge:** TODAS as métricas atendidas.

**Go/No-Go pra Fase 3:** Fase 2 mergeada + dev loop validado pelo usuário em uso real.

## Dependências

- Pré-requisito: venv Py 3.11 + Fase 1 mergeada (já feito, commit 0c8ae97)
- Pré-requisito: ruff instalado (Fase 1)
- Tool novo: `pytest-xdist` instalado via `pip install -e ".[dev]"` durante Commit 1

## Não-decisões deferidas pra Fase 3

- Decomposição de `launcher.py` (13k LOC)
- Repensar boundaries `launcher_support/` vs `core/ui/` vs `core/ops/`
- Abstrações em torno de engines (consolidar paper/shadow runners)

## Referências

- `docs/superpowers/specs/2026-04-23-cleanup-phase-1-design.md` — Fase 1 spec (precedente)
- `docs/superpowers/plans/2026-04-23-cleanup-phase-1.md` — Fase 1 plan (executado)
- CLAUDE.md — regras de CORE protegido + session log
- `data/.launcher_logs/screens.log` — histórico de timings do launcher
