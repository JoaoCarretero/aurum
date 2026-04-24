# Cleanup Phase 1 — "Clear The Decks"

**Data:** 2026-04-23
**Branch alvo:** `feat/cleanup-phase-1` (de `chore/repo-cleanup`)
**Fase:** 1 de 3 no roadmap de otimização (ver "Contexto" abaixo)

## Contexto

O request original era "otimizar o software inteiro" — amplo demais pra um spec único. Decompomos em **3 fases sequenciais**, cada uma com seu próprio spec/plan/implement:

1. **Fase 1 — Clear The Decks** (este spec): code quality + deps. Baixo risco, prepara terreno.
2. **Fase 2 — Performance & Dev Loop:** boot launcher, pytest paralelo, scan paralelo.
3. **Fase 3 — Arquitetura:** decompor `launcher.py` (13k LOC), refatorar boundaries.

A ordem é por **dependência + risco crescente**. Esta fase reduz ruído pra facilitar profiling na Fase 2 e refactor na Fase 3.

## Objetivo

Reduzir LOC e ruído do codebase removendo:
- Engines arquivados sem edge (deshaw, kepos, medallion, ornstein)
- Imports não-usados em todo o codebase (via `ruff F401`)
- Dependências que ficam órfãs após remoção dos engines

**Meta numérica:** ≥ 5,000 LOC deletadas, 0 regressões em tests, VPS services intactos.

## Escopo

### A) Engines arquivados — DELETE completo

4 arquivos principais totalizando 5,187 LOC:

| Engine | LOC | Audit verdict |
|--------|-----|---------------|
| `engines/deshaw.py` | 1,539 | `docs/audits/2026-04-22_deshaw_phi_ornstein_archive_verdict.md` — 4 gates do overfit audit falharam |
| `engines/kepos.py` | 961 | `docs/audits/2026-04-20_kepos_recalibration.md` — "rodável mas sem edge em mercado atual" |
| `engines/medallion.py` | 998 | Grid-best in-sample foi overfit canônico (Codex audit flag, per config/engines.py:69) |
| `engines/ornstein.py` | 1,689 | `docs/audits/2026-04-22_deshaw_phi_ornstein_archive_verdict.md` — regime mismatch |

Também deletar:
- Tests: `tests/engines/test_kepos.py`, `test_ornstein.py`, `test_medallion.py` (deshaw sem teste)
- Registry: entries em `config/engines.py` (`ENGINES` dict + `EXPERIMENTAL_SLUGS`)
- Callsites em `tools/` e `engines/millennium.py` (se existirem — detectado via grep)
- Docs de params/grid em `docs/engines/{deshaw,kepos,medallion,ornstein}/` se existirem

**Preservado:**
- Audits em `docs/audits/*{deshaw,kepos,medallion,ornstein}*.md` — são justificativa do delete
- Branches backup no origin: `feat/claude-deshaw`, `feat/claude-kepos`, `feat/claude-medallion` (pushed earlier in session)
- Git history (sempre recuperável)

### B) Unused imports — ruff F401 autofix

- `ruff check --select F401 --fix` no codebase inteiro
- Inspecionar diff manualmente antes de commit (risco de false-positive em lazy/dynamic imports)

### C) Deps órfãs pós-archive

- Verificar com grep se `hmmlearn`, `arch`, `statsmodels` têm uso fora dos engines deletados
- Remover de `pyproject.toml [ml]` o que ficar órfão
- Reinstalar venv: `pip install -e ".[all,dev]"`

## Fora de escopo (explícito)

- **CORE de trading** (`config/params.py`, `core/signals.py`, `core/indicators.py`, `core/portfolio.py`) — protegido por CLAUDE.md, não mexer
- **Scripts em `tools/`** (rabbit hole; fica pra auditoria dedicada depois)
- **Refactor de `launcher.py`** (Fase 3)
- **Session logs, audits, docs históricos** — ficam intactos
- **Code duplication audit** — não cobrimos `grep` de padrões duplicados fora do que ruff pega
- **Deploy scripts em `deploy/`** (múltiplos `install_*_vps.sh` variantes) — rabbit hole

## Riscos e mitigações

| # | Risco | Mitigação |
|---|-------|-----------|
| 1 | Millennium pod chama engines arquivados | `grep -n "deshaw\|kepos\|medallion\|ornstein" engines/millennium.py` antes do delete. Limpar refs no mesmo commit. |
| 2 | Deps órfãs são usadas em CORE indireto | `grep -rln "from arch\|import arch\b\|from hmmlearn\|import hmmlearn" --include="*.py"` em `core/`, `engines/` não-arquivados, `tools/`. Só remover se zero matches. |
| 3 | ruff F401 remove lazy/dynamic imports | `ruff check --diff` primeiro (preview). Scan manual do diff — se remove import de `engines.`, `core.`, `config.`, verificar uso via string/getattr. Se dúvida, `# noqa: F401`. |
| 4 | Launcher tem entradas de menu pra engines arquivados | `grep -rn "deshaw\|kepos\|medallion\|ornstein" launcher_support/ launcher.py`. Atualizar no mesmo commit do registry. |
| 5 | Tests de integração importam engines arquivados | `grep -rln "deshaw\|kepos\|medallion\|ornstein" tests/`. Ajustar ou deletar tests conforme achado. |

## Estratégia de execução

### Branch e commits

Criar `feat/cleanup-phase-1` a partir de `chore/repo-cleanup`. Push no origin após cada commit. Merge-commit (não squash) de volta em `chore/repo-cleanup` ao final — preserva commits atômicos no history.

### Ordem de commits

| # | Commit | Por quê |
|---|--------|---------|
| 1 | `chore(config): remove archived engines from registry` | Remove de `ENGINES` dict + `EXPERIMENTAL_SLUGS`. Faz essa ordem primeiro: se alguém bater em `ENGINES["deshaw"]` vai falhar loud em vez de importar arquivo stale em seguida. |
| 2 | `chore(engines): delete archived engines + tests` | Delete dos 4 `.py` + 3 tests. Junto: refs em `tools/` e `engines/millennium.py` se grep achou. |
| 3 | `chore(deps): remove orphaned deps post-archive` | Se `hmmlearn`/`arch`/`statsmodels` ficaram órfãs em `pyproject.toml [ml]`, remover. Reinstall venv. |
| 4 | `chore(imports): ruff F401 autofix` | Rodar `ruff check --select F401 --fix`. Diff inspecionado. |
| 5 | `chore: delete archived engine docs/` (opcional) | Se `docs/engines/{deshaw,kepos,medallion,ornstein}/` existir, deletar. **Audits em `docs/audits/` FICAM.** |

### Gates de validação (cumulativos, um por commit)

#### Após (1) — registry cleanup
- `pytest tests/ -q --ignore=tests/test_cockpit_paper_endpoints.py` passa
- `python -c "import launcher"` sem exception
- `python -c "from engines.millennium import _scan_one_engine_live; _scan_one_engine_live('citadel')"` funciona

#### Após (2) — files delete
- Todos os gates de (1), mais:
- `grep -r "import deshaw\|import kepos\|import medallion\|import ornstein" --include="*.py"` retorna vazio (exceto `_archive/` e `docs/`)

#### Após (3) — deps órfãs
- `pip install -e ".[all,dev]"` reinstala limpo
- `pytest tests/engines/` passa (137 esperados nos 6 engines restantes)
- `python -c "import launcher"` OK

#### Após (4) — ruff F401
- Todos os gates anteriores, mais:
- `ruff check --select F401 --no-fix | wc -l` → 0

#### Gate final (antes de merge em chore/repo-cleanup)
- **Local**: `pytest tests/ --ignore=tests/test_cockpit_paper_endpoints.py -q` — baseline mantido (~1660-1700 pass esperado, accounting for deleted tests)
- **VPS**: SSH loop `systemctl is-active {11 services}` continua `active`

### Rollback

Se qualquer gate falhar:
1. `git reset --hard <commit-anterior>`
2. Diagnosticar root cause
3. Ajustar commit
4. Re-rodar gate

Push ao origin após cada commit dá checkpoint granular — rollback é sempre recuperável.

## Critérios de sucesso (mensuráveis)

| Métrica | Alvo | Como medir |
|---------|------|------------|
| LOC deletadas | ≥ 5,000 | `git diff --shortstat chore/repo-cleanup..feat/cleanup-phase-1` |
| Tests passing | **1,681** (1,740 baseline − 59 tests deletados: 32 kepos + 22 ornstein + 5 medallion) | `pytest tests/ -q --ignore=tests/test_cockpit_paper_endpoints.py` |
| Novos test failures | 0 | Comparar com baseline pre-Fase-1 |
| Launcher boot | Sem crash, < 3s ideal | `python -c "import launcher"` + boot real |
| VPS services | 11/11 `active` | SSH + `systemctl is-active` |
| Venv size | medir antes/depois (provável ganho se deps removidas) | `du -sh .venv/` |
| F401 residuais | 0 | `ruff check --select F401 --no-fix \| wc -l` |

**Go/No-Go pra merge:** TODAS as métricas atendidas.

**Go/No-Go pra Fase 2:** Fase 1 mergeada em `chore/repo-cleanup` + VPS smoke OK + Joao aprovou.

## Dependências

- **Pré-requisito:** venv Python 3.11 funcional (já setup nesta sessão)
- **Pré-requisito:** baseline pytest 1,740 pass já estabelecido (commit `0a25031` desta sessão)
- **Tool:** `ruff` — não está instalado no venv atual (confirmado 2026-04-23). Primeiro passo da execução: `pip install ruff` (dep ad-hoc, não precisa ir no pyproject se for uso one-off; se ficar recorrente nas fases seguintes, adicionar em `[dev]`)

## Não-decisões deferidas pra Fase 2+

- Profiling detalhado de boot launcher (Fase 2)
- Tests paralelos via `pytest-xdist` (Fase 2)
- Decomposição do launcher.py 13k LOC (Fase 3)
- Auditoria em `tools/` pra scripts mortos (depois de Fase 3, rabbit hole)

## Referências

- CLAUDE.md — regras de CORE protegido + session log
- `docs/audits/2026-04-22_deshaw_phi_ornstein_archive_verdict.md` — justificativa archive
- `docs/audits/2026-04-20_kepos_recalibration.md`
- `config/engines.py` — registry atual com comentários de archive
- Branches backup no origin: `feat/claude-deshaw`, `feat/claude-kepos`, `feat/claude-medallion`
