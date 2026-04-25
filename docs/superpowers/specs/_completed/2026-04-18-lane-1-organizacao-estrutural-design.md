# Lane 1 — Organização Estrutural — Design

**Data:** 2026-04-18
**Branch de origem:** `feat/phi-engine`
**Escopo:** reorganizar layout físico do código sem alterar lógica de trading.
**Motivação:** `launcher.py` com ~13k linhas, 39 módulos em `core/` sem hierarquia,
47 scripts em `tools/` com duplicação de boilerplate, 70 testes flat em `tests/`
com lixo de pytest runs versionado. Custo cognitivo alto pra navegar e pra
colaboração multiagente (Claude + Codex).

**Princípio-guia:** zero alteração em comportamento de trading. Toda mudança é
de layout/import path. Onde tocar módulo protegido do CORE (`indicators`,
`signals`, `portfolio`), fazer via **shim** — o ficheiro conceitual continua
no mesmo caminho lógico, só fisicamente realocado, com re-export explícito.

---

## 1. launcher.py — Split moderado (Opção B)

### Estado atual
- Ficheiro único: 12,887 linhas, 1 classe `App(tk.Tk)` com 251 métodos.
- `launcher_support/` já existe com precedentes: `bootstrap.py`, `engines_live_view.py`, `execution.py`, `menu_data.py`.
- Menu-driven (não Notebook/tabs).

### Alvo
- `launcher.py` reduzido a ~3-4k linhas: App shell, roteamento, handlers globais.
- Lógica de construção e handlers por painel extraída pra módulos dedicados em `launcher_support/`.

### Novos módulos
| Módulo | Responsabilidade |
|---|---|
| `launcher_support/menu_engines.py` | Seleção e lançamento de engine individual |
| `launcher_support/menu_results.py` | Viewer de runs, reports, HTML preview |
| `launcher_support/menu_live.py` | Painéis live: PnL, positions, portfolio monitor |
| `launcher_support/menu_backtest.py` | Walk-forward, OOS, bateria |
| `launcher_support/menu_arb.py` | Alchemy cockpit |
| `launcher_support/menu_settings.py` | Config, keys, connections |
| `launcher_support/header.py` | Topbar: ticker, clock, VPS status, splash |

### Padrão de interface
Cada módulo exporta funções puras que recebem `app: App` (ou uma interface
menor) como argumento e constroem/registram seu sub-árvore de widgets.

```python
# launcher_support/menu_engines.py
def build_menu_engines(app: App, parent: tk.Widget) -> tk.Widget: ...
def on_run_engine(app: App, engine_name: str) -> None: ...
```

`App` mantém estado global (root, status bar, active_run). Painéis
consomem via passagem explícita, não via globals.

### Protocolo de extração
Por módulo, sequencialmente:
1. Extrair ~1 painel por commit atômico.
2. Smoke test: abrir launcher, navegar pelo painel extraído, sair limpo.
3. Se quebrar → revert imediato. Se passar → próximo módulo.
4. Nunca refatorar lógica durante extract. Só mover + parametrizar.

### Riscos conhecidos
- Sem test suite de UI automatizada → validação é smoke manual.
- `self.X` estado partilhado pode exigir accessors temporários.

---

## 2. tools/ — Subdirs por concern (Opção A)

### Estado atual
47 scripts flat em `tools/`. Padrões visíveis de duplicação: `*_battery.py`,
`*_sweep.py`, `*_grid.py`, `*_focus_battery.py` repetem boilerplate (sys.path,
logger, CSV writer, argparse base).

### Alvo
Só mover ficheiros pra subdirs. Zero alteração de lógica. Extrair framework
comum (`tools/_lib/battery_runner.py`) marcado como **follow-up Lane 1.2b**,
não incluído neste design.

### Novo layout
```
tools/
├── batteries/         # *_battery, *_sweep, *_grid, *_focus_battery (~17 scripts)
├── audits/            # overfit_audit, lookahead_scan, forensics, oos_revalidate
├── maintenance/       # rebuild_db, normalize_run_ids, backfill, rotate_keys, encrypt_keys
├── capture/           # fixture_capture, phase_c_capture_report, prefetch, prewarm
├── reports/           # regen_report, reconcile_runs
└── _archive/          # one-offs: phase456_test, clean_workspace (se obsoleto), etc
```

### Protocolo
1. `git mv` por grupo (preserva history).
2. `grep -rn "tools/<old>.py" launcher.py api/ aurum_cli.py deploy/` para cada movido.
3. Atualizar call-sites.
4. Smoke: `python -m tools.batteries.phi_focus_battery --help` confirma pacote carrega.
5. Adicionar `tools/_lib/__init__.py` vazio se necessário para pacotes.

### Riscos conhecidos
- CI/deploy scripts podem hardcodar `tools/X.py` → grep em `deploy/` antes.
- Notebooks em `docs/` podem referenciar → grep `from tools` também.

---

## 3. core/ — Subdirs + shim layer (Opção B)

### Estado atual
39 módulos flat em `core/`. 63 imports de `core.*` em `engines/*.py`.
3 módulos protegidos (CORE de trading, requer aprovação pra mexer): `indicators.py`,
`signals.py`, `portfolio.py`.

### Aprovação explícita registrada
João aprovou em 2026-04-18 o toque nos 3 protegidos **estritamente como shim**:
o conteúdo antigo move pra subpacote, e o ficheiro antigo fica como 1 linha
`from core.<sub>.X import *`. Comportamento idêntico. Backtests calibrados
intactos.

### Novo layout
```
core/
├── data/          # data, cache, market_data, htf, htf_filter, exchange_api, connections, transport
├── signals/       # indicators ⚠️, signals ⚠️, harmonics, hawkes, chronos, sentiment
├── risk/          # portfolio ⚠️, risk_gates, failure_policy, audit_trail, key_store
├── ops/           # run_manager, engine_base, engine_picker, db, persistence, proc, fs,
│                  #   health, versioned_state, fixture_capture
├── ui/            # alchemy_ui, ui_palette, portfolio_monitor, funding_scanner
├── arb/           # arb_scoring, alchemy_state
└── analysis/      # analysis_export, evolution
```
⚠️ = protected trading core.

### Shim pattern
Para cada módulo movido, manter na raiz `core/` um shim de 1 linha:

```python
# core/indicators.py  (shim)
from core.signals.indicators import *  # noqa: F401,F403
```

Todos os 63 imports existentes continuam válidos. Código novo usa path novo
(`from core.signals.indicators import atr`). Shim marca caminho de migração
futura; remoção de shims fica para iteração posterior quando todos os
consumidores migrarem.

### Protocolo
1. Criar subdirs + `__init__.py` vazios.
2. `git mv` de cada módulo pra seu novo lar.
3. Criar shim no path antigo.
4. Executar `python smoke_test.py --quiet` — deve permanecer verde.
5. Rodar `pytest tests/contracts/` (ou o equivalente pós-Lane 1.4) — deve passar.
6. Commit atômico por subpacote (7 commits).

### Riscos conhecidos
- Imports circulares latentes podem emergir quando subpacotes se referenciam.
  Mitigação: ordem de migração bottom-up (data → signals → risk → ops → ui → arb → analysis).
- IDEs podem cachear imports antigos (resolve com reload).

---

## 4. tests/ — Subdirs + gitignore de temporários (Opção A)

### Estado atual
70 test files flat em `tests/`. Padrões: `test_*_contracts.py` (contract
tests), `test_<engine>.py` (engine-specific), módulos core soltos.
`tests/_tmp/` e `tests/_tmp_probe/` versionados com 20+ subdirs de pytest
runs antigos.

### Alvo
```
tests/
├── contracts/     # todos os test_*_contracts.py
├── engines/       # test_citadel.py, test_deshaw.py, test_phi.py, test_graham.py, etc
├── core/          # test_data.py, test_portfolio.py, test_signals.py, test_harmonics.py, etc
├── integration/   # test_api_contracts, test_aurum_cli, test_alchemy_snapshot, etc
├── fixtures/      # já existe, não tocar
└── conftest.py    # manter na raiz
```

### Limpeza de lixo
- Adicionar ao `.gitignore` se ausente: `tests/_tmp/`, `tests/_tmp_probe/`.
- `git rm -r` dos tracked temporários.
- Confirmar `conftest.py` direciona tmpdirs pra caminho gitignored (verificar antes de remover).

### Protocolo
1. Auditar `conftest.py`: fixtures com path absoluto/relativo que assumam layout flat.
2. `git mv` por grupo temático.
3. Rodar `pytest tests/ --collect-only` — deve descobrir os mesmos testes.
4. Rodar suite completa — mesma contagem de passed/skipped.

### Riscos conhecidos
- `conftest.py` pode ter `sys.path` hardcoded; rever antes.
- CI pode invocar `pytest tests/test_X.py` explicitamente; grep.

---

## Ordem de execução (menor risco → maior)

1. **Lane 1.4 — tests/** (isolado, não afeta runtime de trading)
2. **Lane 1.2 — tools/** (call-sites pontuais)
3. **Lane 1.3 — core/ + shims** (maior blast radius, mas shim protege)
4. **Lane 1.1 — launcher split** (maior volume, maior risco GUI)

Cada passo = commit atômico + checkpoint de smoke test.

## Checkpoints obrigatórios

Entre cada passo:
- `python smoke_test.py --quiet` → deve passar 156/156 (ou contagem atual; nunca reduzir).
- `pytest tests/ -q` → mesma contagem de pass/skip do baseline.
- Se Lane 1.1: abrir launcher, navegar cada menu extraído, fechar limpo.

Regressão em qualquer checkpoint → `git revert` e diagnosticar antes de seguir.

## Fora de escopo (explicitamente)

- Nenhuma alteração em lógica de indicadores, sinais, portfolio, risk gates.
- Nenhuma alteração em `config/params.py`.
- Framework comum pra batteries (seria Lane 1.2b).
- CLI unificado `aurum_cli battery ...` (seria Lane 1.2c).
- Reescrita da classe App em coordinator/painéis desacoplados (seria Lane 1.1c).
- Otimização de performance (isso é Lane 2).
- Automação de session log / workflow (isso é Lane 3).

## Critério de sucesso

- `launcher.py` ≤ 4,500 linhas.
- `tools/` flat listing vazio (tudo em subdir).
- `core/` raiz contém apenas shims + `__init__.py` + subpacotes.
- `tests/` raiz contém apenas `conftest.py` + `fixtures/` + subpacotes.
- Smoke 156/156. Suite pytest com mesma contagem. Launcher abre e navega sem erro em todos os menus.
