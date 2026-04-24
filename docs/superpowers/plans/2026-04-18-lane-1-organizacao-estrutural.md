# Lane 1 — Organização Estrutural — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganizar layout físico do código (launcher.py split, tools/ subdirs, core/ subdirs+shim, tests/ subdirs) sem alterar comportamento de trading.

**Architecture:** Mover por etapas com checkpoints de regressão zero. Core protegido via shim (path antigo re-exporta do novo). Launcher quebrado em módulos de `launcher_support/`. Cada etapa commit atômico + smoke test.

**Tech Stack:** Python 3.14, pytest, Tkinter (launcher), pandas.

**Spec:** `docs/superpowers/specs/2026-04-18-lane-1-organizacao-estrutural-design.md`

---

## Phase 0 — Baseline (obrigatório antes de qualquer alteração)

### Task 0.1: Capturar baseline de regressão

**Files:**
- Create: `data/refactor_baseline/2026-04-18_lane1.json`

- [ ] **Step 1: Rodar smoke test e capturar contagem**

Run: `python smoke_test.py --quiet 2>&1 | tee data/refactor_baseline/2026-04-18_lane1_smoke.txt`
Expected: saída com linha final do tipo `156 passed` (ou contagem atual).

- [ ] **Step 2: Rodar suite pytest e capturar contagem**

Run: `pytest tests/ -q 2>&1 | tee data/refactor_baseline/2026-04-18_lane1_pytest.txt`
Expected: resumo com N passed, M skipped.

- [ ] **Step 3: Gerar digest de um backtest curto de referência**

Run: `python aurum_cli.py --engine citadel --days 30 --out data/refactor_baseline/citadel_30d.csv`
Run: `python -c "import hashlib; print(hashlib.sha256(open('data/refactor_baseline/citadel_30d.csv','rb').read()).hexdigest())" > data/refactor_baseline/citadel_30d.sha256`
Expected: hash SHA-256 do CSV.

- [ ] **Step 4: Criar manifest JSON de baseline**

Write `data/refactor_baseline/2026-04-18_lane1.json`:
```json
{
  "date": "2026-04-18",
  "branch": "feat/phi-engine",
  "smoke_count": "<lido do step 1>",
  "pytest_count": "<lido do step 2>",
  "reference_backtest": "citadel_30d",
  "reference_backtest_sha256": "<do step 3>"
}
```

- [ ] **Step 5: Commit baseline**

```bash
git add data/refactor_baseline/
git commit -m "chore(lane1): capturar baseline de regressao antes da reorganizacao"
```

---

## Phase 1 — tests/ subdirs (Lane 1.4)

Razão: isolado, zero dependência de runtime.

### Task 1.1: Auditar `tests/conftest.py` e `.gitignore`

**Files:**
- Read: `tests/conftest.py`
- Modify: `.gitignore`

- [ ] **Step 1: Verificar se conftest tem paths hardcoded pra testes específicos**

Run: `grep -nE "tests/test_|tests/fixtures" tests/conftest.py`
Expected: só referências genéricas; nenhum path hardcoded de test file específico. Se houver, anotar pra corrigir na Task 1.3.

- [ ] **Step 2: Confirmar gitignore bloqueia temporários**

Run: `grep -nE "tests/_tmp|tests/_tmp_probe" .gitignore`
Expected: se ausente, adicionar.

- [ ] **Step 3: Adicionar ao `.gitignore` se ausente**

Edit `.gitignore` — adicionar após linhas existentes de tests:
```
tests/_tmp/
tests/_tmp_probe/
```

- [ ] **Step 4: Remover `_tmp/` e `_tmp_probe/` tracked**

Run: `git rm -rf tests/_tmp tests/_tmp_probe 2>/dev/null; true`
(pode não haver tracked files; OK se sair silencioso)

- [ ] **Step 5: Commit**

```bash
git add .gitignore
git commit -m "chore(tests): gitignore _tmp/_tmp_probe + remover tracked"
```

### Task 1.2: Criar subdirs e mover contract tests

**Files:**
- Create: `tests/contracts/`
- Move: `tests/test_*_contracts.py` → `tests/contracts/`

- [ ] **Step 1: Criar diretório com `__init__.py` vazio**

Run: `mkdir -p tests/contracts && touch tests/contracts/__init__.py`

- [ ] **Step 2: Mover todos os `test_*_contracts.py` preservando history**

Run: `git mv tests/test_*_contracts.py tests/contracts/`

- [ ] **Step 3: Verificar pytest ainda colete os mesmos testes**

Run: `pytest tests/ --collect-only -q 2>&1 | tail -5`
Expected: mesma contagem de testes descobertos que o baseline (Task 0.1 Step 2).

- [ ] **Step 4: Rodar suite completa — sem regressão**

Run: `pytest tests/ -q`
Expected: mesma contagem passed/skipped do baseline.

- [ ] **Step 5: Commit**

```bash
git add tests/contracts/
git commit -m "refactor(tests): mover contract tests para tests/contracts/"
```

### Task 1.3: Mover engine tests

**Files:**
- Create: `tests/engines/`
- Move: `tests/test_<engine>.py` (não-contracts) → `tests/engines/`

- [ ] **Step 1: Criar diretório**

Run: `mkdir -p tests/engines && touch tests/engines/__init__.py`

- [ ] **Step 2: Listar engine tests não-contracts**

Run: `ls tests/ | grep -E "^test_(citadel|bridgewater|deshaw|jump|renaissance|phi|graham|twosigma|aqr|millennium|kepos|medallion|janestreet|meanrev|ornstein|jumpdiffusion)" | grep -v contracts`
Registrar lista exata que o comando devolver.

- [ ] **Step 3: Mover por `git mv` cada arquivo da lista**

```bash
# Exemplo; substituir pela lista real do Step 2:
git mv tests/test_graham.py tests/engines/
git mv tests/test_<outros>.py tests/engines/
```

- [ ] **Step 4: Verificar coleta e suite**

Run: `pytest tests/ --collect-only -q | tail -5`
Run: `pytest tests/ -q`
Expected: contagem baseline mantida.

- [ ] **Step 5: Commit**

```bash
git add tests/engines/
git commit -m "refactor(tests): mover engine tests para tests/engines/"
```

### Task 1.4: Mover core tests

**Files:**
- Create: `tests/core/`
- Move: `tests/test_<modulo core>.py` (não-contracts, não-engine) → `tests/core/`

- [ ] **Step 1: Criar diretório**

Run: `mkdir -p tests/core && touch tests/core/__init__.py`

- [ ] **Step 2: Listar core tests**

Run: `ls tests/ | grep -E "^test_(alchemy|arb|audit|cache|chronos|data|db|engine_base|engine_picker|evolution|failure|fs|funding|harmonics|hawkes|health|htf|indicators|key_store|market|persistence|portfolio|proc|risk|run_manager|sentiment|signals|versioned)" | grep -v contracts`
Registrar lista.

- [ ] **Step 3: Mover cada arquivo da lista**

```bash
# Substituir pela lista real:
git mv tests/test_<arquivo>.py tests/core/
```

- [ ] **Step 4: Verificar**

Run: `pytest tests/ -q`
Expected: contagem baseline.

- [ ] **Step 5: Commit**

```bash
git add tests/core/
git commit -m "refactor(tests): mover core tests para tests/core/"
```

### Task 1.5: Mover integration tests

**Files:**
- Create: `tests/integration/`
- Move: `test_api_contracts.py` (fica em contracts/), `test_aurum_cli*.py`, `test_engines_live_view.py`, `test_alchemy_snapshot.py` → `tests/integration/`

- [ ] **Step 1: Criar diretório**

Run: `mkdir -p tests/integration && touch tests/integration/__init__.py`

- [ ] **Step 2: Identificar integration tests remanescentes**

Run: `ls tests/*.py 2>/dev/null | grep -v conftest`
Esperado: lista curta. Inclui tudo que não é unit de um core module nem contract.

- [ ] **Step 3: Mover**

```bash
# Para cada arquivo da lista do Step 2 que for integration:
git mv tests/<arquivo>.py tests/integration/
```

- [ ] **Step 4: Verificar sobrou só conftest + __init__ + pastas no root de tests/**

Run: `ls tests/*.py`
Expected: só `tests/conftest.py`.

- [ ] **Step 5: Rodar suite completa**

Run: `pytest tests/ -q`
Expected: contagem baseline.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/ tests/
git commit -m "refactor(tests): mover integration tests e concluir reorganizacao"
```

### Task 1.6: Checkpoint Phase 1

- [ ] **Step 1: Smoke test completo**

Run: `python smoke_test.py --quiet`
Expected: mesma contagem do baseline (Task 0.1 Step 1).

- [ ] **Step 2: Pytest completo**

Run: `pytest tests/ -q`
Expected: mesma contagem do baseline (Task 0.1 Step 2).

- [ ] **Step 3: Se divergir → revert commits desta phase e investigar**

Se divergência, rodar: `git log --oneline HEAD~6..HEAD` pra ver commits, `git revert` do que quebrou, e abrir issue em `docs/audits/`.

---

## Phase 2 — tools/ subdirs (Lane 1.2)

### Task 2.1: Criar estrutura e mover batteries

**Files:**
- Create: `tools/batteries/`, `tools/audits/`, `tools/maintenance/`, `tools/capture/`, `tools/reports/`, `tools/_archive/`
- Move: scripts `tools/*.py` para seus subdirs

- [ ] **Step 1: Criar todos os subdirs com __init__.py**

```bash
for d in batteries audits maintenance capture reports _archive; do
  mkdir -p tools/$d && touch tools/$d/__init__.py
done
```

- [ ] **Step 2: Mover batteries**

```bash
git mv tools/longrun_battery.py tools/master_battery.py tools/autonomous_battery.py \
       tools/battery_test.py tools/bridgewater_long_battery.py \
       tools/jump_focus_battery.py tools/phi_focus_battery.py tools/phi_tf_battery.py \
       tools/phi_sweep.py tools/phi_sweep_stage_b.py tools/phi_stage_c.py \
       tools/renaissance_focus_battery.py tools/weak_engines_battery.py \
       tools/ornstein_compare_battery.py tools/meanrev_variant_search.py \
       tools/millennium_battery.py tools/millennium_gate_grid.py \
       tools/millennium_minscore_sweep.py tools/medallion_grid.py \
       tools/medallion_finalize.py tools/param_search.py \
       tools/threshold_sensitivity.py tools/ablation_test.py \
       tools/htf_ab_test.py \
       tools/batteries/
```

- [ ] **Step 3: Mover audits**

```bash
git mv tools/oos_revalidate.py tools/phi_overfit_audit.py tools/phi_trade_forensics.py \
       tools/ornstein_overfit_audit.py tools/lookahead_scan.py \
       tools/engine_validation.py \
       tools/audits/
```

- [ ] **Step 4: Mover maintenance**

```bash
git mv tools/rebuild_db.py tools/normalize_run_ids.py tools/backfill_db_from_disk.py \
       tools/bridgewater_cache_backfill.py tools/rotate_keys.py tools/encrypt_keys.py \
       tools/clean_workspace.py tools/millennium_live_tuner.py tools/millennium_shadow.py \
       tools/maintenance/
```

- [ ] **Step 5: Mover capture**

```bash
git mv tools/prefetch.py tools/prewarm_sentiment_cache.py \
       tools/phase_c_capture_report.py \
       tools/capture/
```

- [ ] **Step 6: Mover reports**

```bash
git mv tools/regen_report.py tools/reconcile_runs.py tools/reports/
```

- [ ] **Step 7: Mover one-offs pra _archive**

```bash
git mv tools/phase456_test.py tools/_archive/
```

- [ ] **Step 8: Verificar raiz de tools/ limpa**

Run: `ls tools/*.py 2>/dev/null`
Expected: vazio ou só `__init__.py`.

- [ ] **Step 9: Adicionar `tools/__init__.py` vazio se ausente**

Run: `test -f tools/__init__.py || touch tools/__init__.py`

### Task 2.2: Atualizar call-sites

**Files:**
- Modify: `launcher.py`, `launcher_support/*.py`, `aurum_cli.py`, `deploy/*.sh`, `api/**/*.py` — qualquer referência a `tools/X.py`

- [ ] **Step 1: Encontrar todos os call-sites**

Run: `grep -rnE "tools/(longrun_battery|oos_revalidate|rebuild_db|prefetch|reconcile_runs|rotate_keys|regen_report|phi_focus_battery|phi_sweep|master_battery|millennium_shadow|prewarm|normalize_run_ids)" launcher.py launcher_support/ aurum_cli.py deploy/ api/ docs/ 2>/dev/null`
Registrar a lista.

- [ ] **Step 2: Atualizar cada call-site**

Para cada ocorrência, substituir path antigo pelo novo:
- `tools/longrun_battery.py` → `tools/batteries/longrun_battery.py`
- `tools/oos_revalidate.py` → `tools/audits/oos_revalidate.py`
- `tools/rebuild_db.py` → `tools/maintenance/rebuild_db.py`
- (…etc, seguir mapeamento da Task 2.1)

Use Edit tool com `old_string`/`new_string` por ocorrência.

- [ ] **Step 3: Testar um script de cada subdir**

```bash
python -m tools.batteries.phi_focus_battery --help
python -m tools.audits.oos_revalidate --help
python -m tools.maintenance.rebuild_db --help
python -m tools.capture.prefetch --help
python -m tools.reports.regen_report --help
```
Expected: cada um imprime help sem ImportError.

- [ ] **Step 4: Smoke test**

Run: `python smoke_test.py --quiet`
Expected: baseline mantida.

- [ ] **Step 5: Commit**

```bash
git add tools/ launcher.py launcher_support/ aurum_cli.py deploy/ api/ docs/
git commit -m "refactor(tools): subdirs por concern + atualizar call-sites"
```

### Task 2.3: Checkpoint Phase 2

- [ ] **Step 1: Smoke + pytest + help dos scripts**

Run:
```bash
python smoke_test.py --quiet
pytest tests/ -q
python -m tools.batteries.phi_focus_battery --help
```
Expected: baseline mantida; help funcional.

---

## Phase 3 — core/ subdirs + shim (Lane 1.3)

### Task 3.1: Criar estrutura de subpacotes

**Files:**
- Create: `core/data/__init__.py`, `core/signals/__init__.py`, `core/risk/__init__.py`, `core/ops/__init__.py`, `core/ui/__init__.py`, `core/arb/__init__.py`, `core/analysis/__init__.py`

- [ ] **Step 1: Criar todos os subpacotes vazios**

```bash
for d in data signals risk ops ui arb analysis; do
  mkdir -p core/$d && touch core/$d/__init__.py
done
```

- [ ] **Step 2: Confirmar que nada quebrou**

Run: `python smoke_test.py --quiet`
Expected: baseline.

- [ ] **Step 3: Commit**

```bash
git add core/
git commit -m "refactor(core): criar subpacotes vazios (data/signals/risk/ops/ui/arb/analysis)"
```

### Task 3.2: Migrar core/data (bottom-up, módulos sem dependência interna)

**Files:**
- Move: `core/data.py`, `core/cache.py`, `core/market_data.py`, `core/htf.py`, `core/htf_filter.py`, `core/exchange_api.py`, `core/connections.py`, `core/transport.py` → `core/data/`
- Create: shim em cada path antigo

- [ ] **Step 1: Mover data.py**

```bash
git mv core/data.py core/data/base.py
```
(renomeado pra `base.py` pra evitar colisão com subpacote `data`)

- [ ] **Step 2: Criar shim `core/data.py`? Não — `core/data/` já é pacote. Ajustar shims diferentemente.**

Como `core/data/` agora é um subpacote, ler `from core.data import fetch` resolveria contra `core/data/__init__.py`. Então o shim correto é em `core/data/__init__.py`:

Edit `core/data/__init__.py`:
```python
"""Compatibility shim — re-export submodules for legacy consumers."""
from core.data.base import *  # noqa: F401,F403
```

- [ ] **Step 3: Mover cache.py, market_data.py, htf.py, etc**

```bash
git mv core/cache.py core/data/cache.py
git mv core/market_data.py core/data/market_data.py
git mv core/htf.py core/data/htf.py
git mv core/htf_filter.py core/data/htf_filter.py
git mv core/exchange_api.py core/data/exchange_api.py
git mv core/connections.py core/data/connections.py
git mv core/transport.py core/data/transport.py
```

- [ ] **Step 4: Criar shims no path antigo (raiz de core/) para cada módulo**

Para cada módulo movido (exceto `data.py` que virou subpacote), criar arquivo em `core/<nome>.py`:

```python
# core/cache.py
from core.data.cache import *  # noqa: F401,F403
```

Repetir para: `market_data.py`, `htf.py`, `htf_filter.py`, `exchange_api.py`, `connections.py`, `transport.py`.

- [ ] **Step 5: Verificar imports existentes funcionam**

Run:
```bash
python -c "from core.data import fetch, fetch_all; print('ok data')"
python -c "from core.cache import read, write; print('ok cache')"
python -c "from core.market_data import *; print('ok market_data')"
python -c "from core.htf import prepare_htf; print('ok htf')"
```
Expected: cada linha imprime "ok ..." sem ImportError.

- [ ] **Step 6: Smoke + pytest**

Run:
```bash
python smoke_test.py --quiet
pytest tests/ -q
```
Expected: baseline.

- [ ] **Step 7: Commit**

```bash
git add core/
git commit -m "refactor(core): migrar data/cache/market_data/htf/exchange para core.data/ com shims"
```

### Task 3.3: Migrar core/signals (⚠️ PROTEGIDO — shim only)

**Files:**
- Move: `core/indicators.py`, `core/signals.py`, `core/harmonics.py`, `core/hawkes.py`, `core/chronos.py`, `core/sentiment.py` → `core/signals/`
- Create: shim em cada path antigo

⚠️ **indicators.py e signals.py são CORE PROTEGIDO.** Aprovação registrada no design. Zero mudança de conteúdo; só move + shim.

- [ ] **Step 1: Mover `signals.py` pra evitar colisão**

```bash
git mv core/signals.py core/signals/core.py
```
(renomeado pra `core.py` dentro do subpacote pra evitar colisão com o nome do subpacote)

- [ ] **Step 2: Mover `indicators.py` e outros**

```bash
git mv core/indicators.py core/signals/indicators.py
git mv core/harmonics.py core/signals/harmonics.py
git mv core/hawkes.py core/signals/hawkes.py
git mv core/chronos.py core/signals/chronos.py
git mv core/sentiment.py core/signals/sentiment.py
```

- [ ] **Step 3: Criar shim em `core/signals.py`**

Write `core/signals.py`:
```python
"""Compatibility shim — re-export signals core.
Original module lives at core.signals.core.
"""
from core.signals.core import *  # noqa: F401,F403
```

- [ ] **Step 4: Criar shims em `core/indicators.py`, etc**

```python
# core/indicators.py
from core.signals.indicators import *  # noqa: F401,F403
```

Repetir para: `harmonics.py`, `hawkes.py`, `chronos.py`, `sentiment.py`.

- [ ] **Step 5: Atualizar `core/signals/__init__.py`**

Edit `core/signals/__init__.py` para expor os submódulos:
```python
"""core.signals — trading signals subpackage.
Legacy `from core.signals import *` continues to work via re-export from core.
"""
from core.signals.core import *  # noqa: F401,F403
```

- [ ] **Step 6: Verificar imports legados**

Run:
```bash
python -c "from core.indicators import ema, rsi, atr; print('ok indicators')"
python -c "from core.signals import decide_direction, calc_levels, label_trade; print('ok signals')"
python -c "from core.harmonics import *; print('ok harmonics')"
python -c "from core.hawkes import *; print('ok hawkes')"
python -c "from core.chronos import *; print('ok chronos')"
python -c "from core.sentiment import *; print('ok sentiment')"
```
Expected: todos "ok ...".

- [ ] **Step 7: Smoke + pytest + backtest de referência**

```bash
python smoke_test.py --quiet
pytest tests/ -q
python aurum_cli.py --engine citadel --days 30 --out /tmp/citadel_30d_post_signals.csv
python -c "import hashlib; print(hashlib.sha256(open('/tmp/citadel_30d_post_signals.csv','rb').read()).hexdigest())"
```
Expected: SHA-256 **idêntico** ao baseline (Task 0.1 Step 3).

- [ ] **Step 8: Se SHA-256 divergir → REVERT imediato**

```bash
git revert HEAD  # ou reset se ainda não commitado
```
E abrir issue em `docs/audits/2026-04-18_lane1_signals_regression.md` descrevendo o que divergiu.

- [ ] **Step 9: Commit (se SHA-256 bateu)**

```bash
git add core/
git commit -m "refactor(core): migrar signals/indicators/harmonics para core.signals/ com shims (SHA match)"
```

### Task 3.4: Migrar core/risk (⚠️ portfolio.py PROTEGIDO)

**Files:**
- Move: `core/portfolio.py`, `core/risk_gates.py`, `core/failure_policy.py`, `core/audit_trail.py`, `core/key_store.py` → `core/risk/`
- Create: shims

- [ ] **Step 1: Mover arquivos**

```bash
git mv core/portfolio.py core/risk/portfolio.py
git mv core/risk_gates.py core/risk/risk_gates.py
git mv core/failure_policy.py core/risk/failure_policy.py
git mv core/audit_trail.py core/risk/audit_trail.py
git mv core/key_store.py core/risk/key_store.py
```

- [ ] **Step 2: Criar shims**

```python
# core/portfolio.py
from core.risk.portfolio import *  # noqa: F401,F403
```

Repetir para: `risk_gates.py`, `failure_policy.py`, `audit_trail.py`, `key_store.py`.

- [ ] **Step 3: Verificar imports**

```bash
python -c "from core.portfolio import position_size, detect_macro, portfolio_allows, check_aggregate_notional; print('ok portfolio')"
python -c "from core.risk_gates import *; print('ok risk_gates')"
```
Expected: "ok ...".

- [ ] **Step 4: Smoke + pytest + backtest SHA check**

```bash
python smoke_test.py --quiet
pytest tests/ -q
python aurum_cli.py --engine citadel --days 30 --out /tmp/citadel_30d_post_risk.csv
python -c "import hashlib; print(hashlib.sha256(open('/tmp/citadel_30d_post_risk.csv','rb').read()).hexdigest())"
```
Expected: SHA bate com baseline.

- [ ] **Step 5: Commit**

```bash
git add core/
git commit -m "refactor(core): migrar portfolio/risk_gates para core.risk/ com shims (SHA match)"
```

### Task 3.5: Migrar core/ops, core/ui, core/arb, core/analysis

**Files:**
- Move: múltiplos módulos → subpacotes respectivos
- Create: shims

Ops: `run_manager.py`, `engine_base.py`, `engine_picker.py`, `db.py`, `persistence.py`, `proc.py`, `fs.py`, `health.py`, `versioned_state.py`, `fixture_capture.py`, `mt5.py`, `site_runner.py`
UI: `alchemy_ui.py`, `ui_palette.py`, `portfolio_monitor.py`, `funding_scanner.py`
Arb: `arb_scoring.py`, `alchemy_state.py`
Analysis: `analysis_export.py`, `evolution.py`

- [ ] **Step 1: Mover core/ops**

```bash
for f in run_manager engine_base engine_picker db persistence proc fs health versioned_state fixture_capture mt5 site_runner; do
  git mv core/$f.py core/ops/$f.py
done
```

- [ ] **Step 2: Shims ops**

Para cada arquivo movido, criar `core/<nome>.py` com:
```python
from core.ops.<nome> import *  # noqa: F401,F403
```

- [ ] **Step 3: Mover core/ui**

```bash
git mv core/alchemy_ui.py core/ui/alchemy_ui.py
git mv core/ui_palette.py core/ui/ui_palette.py
git mv core/portfolio_monitor.py core/ui/portfolio_monitor.py
git mv core/funding_scanner.py core/ui/funding_scanner.py
```

Criar shims para cada um.

- [ ] **Step 4: Mover core/arb**

```bash
git mv core/arb_scoring.py core/arb/arb_scoring.py
git mv core/alchemy_state.py core/arb/alchemy_state.py
```

Criar shims.

- [ ] **Step 5: Mover core/analysis**

```bash
git mv core/analysis_export.py core/analysis/analysis_export.py
git mv core/evolution.py core/analysis/evolution.py
```

Criar shims.

- [ ] **Step 6: Verificar tudo que sobrou em `core/` raiz**

Run: `ls core/*.py 2>/dev/null`
Expected: apenas shims + `__init__.py` + `core/signals.py` (shim explícito).

- [ ] **Step 7: Testar imports de cada subpacote**

```bash
python -c "from core.run_manager import *; print('ok ops.run_manager')"
python -c "from core.alchemy_ui import *; print('ok ui.alchemy_ui')"
python -c "from core.arb_scoring import *; print('ok arb.arb_scoring')"
python -c "from core.evolution import *; print('ok analysis.evolution')"
```
Expected: cada "ok ...".

- [ ] **Step 8: Smoke + pytest + backtest SHA**

```bash
python smoke_test.py --quiet
pytest tests/ -q
python aurum_cli.py --engine citadel --days 30 --out /tmp/citadel_30d_post_ops.csv
python -c "import hashlib; print(hashlib.sha256(open('/tmp/citadel_30d_post_ops.csv','rb').read()).hexdigest())"
```
Expected: baseline.

- [ ] **Step 9: Commit**

```bash
git add core/
git commit -m "refactor(core): migrar ops/ui/arb/analysis para subpacotes com shims"
```

### Task 3.6: Adicionar `core/README.md` com mapa

**Files:**
- Create: `core/README.md`

- [ ] **Step 1: Escrever README**

Write `core/README.md`:
```markdown
# core/ — Subpacotes

Organizado em 7 subpacotes por responsabilidade. Ficheiros na raiz são
**shims de compatibilidade** que re-exportam do subpacote novo.

| Subpacote | Responsabilidade | Módulos |
|-----------|------------------|---------|
| `core/data/` | OHLCV fetch, cache, exchange I/O, HTF | base, cache, market_data, htf, htf_filter, exchange_api, connections, transport |
| `core/signals/` ⚠️ | Indicadores, decisões, harmonics, regime | core (ex-signals.py), indicators, harmonics, hawkes, chronos, sentiment |
| `core/risk/` ⚠️ | Portfolio sizing, risk gates, audit | portfolio, risk_gates, failure_policy, audit_trail, key_store |
| `core/ops/` | Runtime: engine base, DB, proc, fs, health | run_manager, engine_base, engine_picker, db, persistence, proc, fs, health, versioned_state, fixture_capture, mt5, site_runner |
| `core/ui/` | Componentes UI (launcher/alchemy) | alchemy_ui, ui_palette, portfolio_monitor, funding_scanner |
| `core/arb/` | Arbitragem | arb_scoring, alchemy_state |
| `core/analysis/` | Export, evolution | analysis_export, evolution |

⚠️ = contém ficheiros do CORE PROTEGIDO de trading (indicators, signals, portfolio). Não alterar sem aprovação explícita.

## Shims

Todo ficheiro em `core/*.py` (raiz) é shim de 1 linha re-exportando do
subpacote novo. `from core.indicators import atr` continua funcionando.

Código novo deve usar path novo (`from core.signals.indicators import atr`).
```

- [ ] **Step 2: Commit**

```bash
git add core/README.md
git commit -m "docs(core): README com mapa de subpacotes e shims"
```

### Task 3.7: Checkpoint Phase 3

- [ ] **Step 1: Smoke + pytest + SHA-256 do backtest de referência**

```bash
python smoke_test.py --quiet
pytest tests/ -q
python aurum_cli.py --engine citadel --days 30 --out /tmp/citadel_30d_final_phase3.csv
python -c "import hashlib; print(hashlib.sha256(open('/tmp/citadel_30d_final_phase3.csv','rb').read()).hexdigest())"
```
Expected:
- Smoke/pytest = baseline.
- SHA-256 = baseline (Task 0.1 Step 3).

- [ ] **Step 2: Se SHA divergir → REVERT toda Phase 3 e diagnosticar**

Phase 3 é 100% shim. SHA divergente = bug de shim. Abrir issue.

---

## Phase 4 — launcher.py split (Lane 1.1)

### Task 4.1: Mapear método → módulo alvo

**Files:**
- Create: `docs/audits/2026-04-18_launcher_method_map.md`

- [ ] **Step 1: Listar todos os métodos da classe App**

Run: `grep -nE "^    def " launcher.py > /tmp/launcher_methods.txt`
Expected: ~251 linhas.

- [ ] **Step 2: Classificar cada método por área funcional**

Write `docs/audits/2026-04-18_launcher_method_map.md` com tabela:
| Linha | Método | Módulo alvo |
|-------|--------|-------------|
| N | `_build_engine_menu` | `menu_engines` |
| N | `_show_results` | `menu_results` |
| ... | ... | ... |

Classificação guiada por prefixo/conteúdo:
- `*_engine*`, `_run_*` → `menu_engines`
- `*_results*`, `*_report*`, `*_run_detail*` → `menu_results`
- `*_live*`, `*_pnl*`, `*_position*`, `*_portfolio_monitor*` → `menu_live`
- `*_backtest*`, `*_walkforward*`, `*_oos*` → `menu_backtest`
- `*_arb*`, `*_alchemy*` → `menu_arb`
- `*_settings*`, `*_config*`, `*_keys*`, `*_connections*` → `menu_settings`
- `*_header*`, `*_ticker*`, `*_clock*`, `*_vps*`, `*_splash*` → `header`
- restantes (bootstrap, roteamento, callbacks globais) → **ficam em launcher.py**

- [ ] **Step 3: Commit mapa**

```bash
git add docs/audits/2026-04-18_launcher_method_map.md
git commit -m "docs(lane1): mapa de classificacao de metodos do launcher"
```

### Task 4.2: Extrair `launcher_support/header.py`

**Files:**
- Create: `launcher_support/header.py`
- Modify: `launcher.py` — remover métodos extraídos, adicionar import + delegação

- [ ] **Step 1: Criar módulo com função de interface**

Write `launcher_support/header.py`:
```python
"""Header/topbar construction for the main launcher window.

Builds ticker area, clock, VPS status light and splash banner.
All functions take the App instance explicitly; no globals.
"""
from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from launcher import App


def build_header(app: "App", parent: tk.Widget) -> tk.Widget:
    """Create and return the header widget. Registers app.header refs."""
    # (copiar corpo dos métodos de header classificados no mapa Task 4.1)
    ...
```

- [ ] **Step 2: Copiar (não cortar) corpos dos métodos de header da classe App pro novo módulo**

Editar `launcher_support/header.py`: copiar métodos relevantes do mapa,
converter `def _build_header(self, parent):` → `def build_header(app, parent):`
e substituir `self.` por `app.` dentro.

- [ ] **Step 3: No launcher.py, substituir corpos dos métodos originais por delegação**

Exemplo:
```python
# launcher.py (antes)
def _build_header(self, parent):
    # (100 linhas de código)

# launcher.py (depois)
def _build_header(self, parent):
    from launcher_support.header import build_header
    return build_header(self, parent)
```

- [ ] **Step 4: Smoke + abrir launcher**

```bash
python smoke_test.py --quiet
python launcher.py &
# manual: verificar header aparece, ticker atualiza, clock roda
```

- [ ] **Step 5: Commit**

```bash
git add launcher.py launcher_support/header.py
git commit -m "refactor(launcher): extrair header/topbar para launcher_support.header"
```

### Task 4.3: Extrair `launcher_support/menu_engines.py`

Repetir padrão da Task 4.2 para métodos classificados como `menu_engines`:

- [ ] **Step 1: Criar `launcher_support/menu_engines.py` com funções `build_menu_engines(app, parent)` + handlers**

- [ ] **Step 2: Copiar corpos dos métodos correspondentes, convertendo self → app**

- [ ] **Step 3: Substituir corpos no launcher.py por delegação (shim method)**

- [ ] **Step 4: Smoke + abrir launcher + clicar em Engines menu**

- [ ] **Step 5: Commit**

```bash
git add launcher.py launcher_support/menu_engines.py
git commit -m "refactor(launcher): extrair menu_engines para launcher_support"
```

### Task 4.4: Extrair `launcher_support/menu_results.py`

Mesma estrutura da Task 4.3, para métodos classificados como `menu_results`.

- [ ] **Step 1: Criar módulo**

- [ ] **Step 2: Copiar métodos**

- [ ] **Step 3: Substituir por delegação**

- [ ] **Step 4: Smoke + abrir launcher + abrir um run no viewer**

- [ ] **Step 5: Commit**

```bash
git add launcher.py launcher_support/menu_results.py
git commit -m "refactor(launcher): extrair menu_results para launcher_support"
```

### Task 4.5: Extrair `launcher_support/menu_live.py`

Métodos classificados como `menu_live`.

- [ ] **Step 1: Criar módulo**
- [ ] **Step 2: Copiar**
- [ ] **Step 3: Substituir por delegação**
- [ ] **Step 4: Smoke + abrir launcher + ir em live panel**
- [ ] **Step 5: Commit**

```bash
git add launcher.py launcher_support/menu_live.py
git commit -m "refactor(launcher): extrair menu_live para launcher_support"
```

### Task 4.6: Extrair `launcher_support/menu_backtest.py`

Métodos de backtest/walk-forward/OOS.

- [ ] **Step 1: Criar módulo**
- [ ] **Step 2: Copiar**
- [ ] **Step 3: Substituir por delegação**
- [ ] **Step 4: Smoke + abrir launcher + ir em backtest menu**
- [ ] **Step 5: Commit**

```bash
git add launcher.py launcher_support/menu_backtest.py
git commit -m "refactor(launcher): extrair menu_backtest para launcher_support"
```

### Task 4.7: Extrair `launcher_support/menu_arb.py`

Métodos de alchemy cockpit.

- [ ] **Step 1-5: mesma estrutura**

```bash
git add launcher.py launcher_support/menu_arb.py
git commit -m "refactor(launcher): extrair menu_arb para launcher_support"
```

### Task 4.8: Extrair `launcher_support/menu_settings.py`

Métodos de config/keys/connections.

- [ ] **Step 1-5: mesma estrutura**

```bash
git add launcher.py launcher_support/menu_settings.py
git commit -m "refactor(launcher): extrair menu_settings para launcher_support"
```

### Task 4.9: Verificação final launcher

- [ ] **Step 1: Contar linhas finais**

Run: `wc -l launcher.py`
Expected: ≤ 4,500 linhas.

- [ ] **Step 2: Smoke + abrir launcher + navegar por TODOS os menus sequencialmente**

```bash
python smoke_test.py --quiet
python launcher.py
# manual:
#  - header: ticker, clock, VPS light visíveis
#  - Engines menu: abrir, selecionar, fechar
#  - Results menu: abrir um run, fechar
#  - Live menu: abrir painel, fechar
#  - Backtest menu: abrir bateria, cancelar
#  - Arb menu: abrir alchemy, fechar
#  - Settings menu: abrir config, fechar
#  - Fechar launcher limpo (sem crash)
```

- [ ] **Step 3: Se qualquer menu crashar → revert do commit correspondente**

Usar `git log --oneline` e `git revert` do que estiver com problema.

- [ ] **Step 4: Commit de checkpoint (se tudo OK)**

```bash
git commit --allow-empty -m "checkpoint(lane1): launcher split completo — todos os menus funcionais"
```

---

## Phase 5 — Encerramento Lane 1

### Task 5.1: Re-validar baseline completo

- [ ] **Step 1: Rodar baseline completo**

```bash
python smoke_test.py --quiet > /tmp/smoke_final.txt
pytest tests/ -q > /tmp/pytest_final.txt
python aurum_cli.py --engine citadel --days 30 --out /tmp/citadel_30d_final.csv
python -c "import hashlib; print(hashlib.sha256(open('/tmp/citadel_30d_final.csv','rb').read()).hexdigest())" > /tmp/sha_final.txt
```

- [ ] **Step 2: Comparar com baseline (Task 0.1)**

Diff:
- smoke count vs `data/refactor_baseline/2026-04-18_lane1_smoke.txt`
- pytest count vs `data/refactor_baseline/2026-04-18_lane1_pytest.txt`
- SHA vs `data/refactor_baseline/citadel_30d.sha256`

Expected: todos iguais.

- [ ] **Step 3: Se divergir → investigar antes de fechar**

Não fechar Lane 1 com regressão. Git bisect do commit que introduziu divergência.

### Task 5.2: Session log Lane 1

- [ ] **Step 1: Gerar session log**

Seguir regra permanente do CLAUDE.md. Criar `docs/sessions/YYYY-MM-DD_HHMM.md` com o trabalho da Lane 1.

- [ ] **Step 2: Atualizar daily log**

Criar/atualizar `docs/days/YYYY-MM-DD.md`.

- [ ] **Step 3: Commit final Lane 1**

```bash
git add docs/sessions/ docs/days/
git commit -m "docs(sessions): Lane 1 organizacao estrutural fechada"
```

---

## Critérios de sucesso (duros)

- `launcher.py` ≤ 4,500 linhas (de 12,887 → redução ≥ 65%).
- `tools/` flat raiz vazia (exceto `__init__.py`).
- `core/` raiz contém apenas shims + subpacotes + `__init__.py` + `README.md`.
- `tests/` raiz contém apenas `conftest.py` + `fixtures/` + subpacotes.
- Smoke = baseline.
- Pytest = baseline.
- SHA-256 do backtest de referência = baseline (bit-identical).

---

## Self-Review Checklist (autor deste plano)

- [x] Spec coverage: launcher split (Phase 4), tools subdirs (Phase 2), core subdirs+shim (Phase 3), tests subdirs (Phase 1), gitignore fix (Task 1.1).
- [x] Placeholder scan: sem "TBD" em steps de código. Task 4.1 requer listagem manual (inerente ao método).
- [x] Type/path consistency: paths antigos vs novos consistentes entre tasks.
- [x] Sem "similar to Task N" sem repetir código — reusa pattern mas cada task tem steps explícitos.
- [x] Baseline captura em Phase 0 é referenciada em todas as checkpoints.
