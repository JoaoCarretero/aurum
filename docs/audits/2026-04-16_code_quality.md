# Code Quality and Architecture Audit -- 2026-04-16

## Sumario

**Saude geral: FAIR** -- nucleo (core/, config/) esta limpo e disciplinado,
mas ha tres pontos estruturais que vao doer cada vez mais conforme o
projecto cresce.

**Top 3 problemas estruturais:**

1. **launcher.py e monolito de 12.524 linhas com uma unica classe App
   contendo 412 metodos** (linhas 957..fim). Metodos individuais chegam
   a 491 linhas (`_data_lake`), 326 (`_dash_portfolio_render`), 251
   (`_results_build_overview`). Diz a CLAUDE.md que "cada funcao faz uma
   coisa" -- aqui nao faz.

2. **millennium.py importa de 5 engines siblings** (citadel, deshaw,
   jump, bridgewater, twosigma) -- violando a regra "engines importam de
   core.* e config.params, nunca entre si". CLAUDE.md documenta uma
   excepcao para `multistrategy -> engines/backtest` mas esse modulo nao
   existe; o codigo real e `millennium.py` importando 5 engines reais.
   Documentacao esta obsoleta.

3. **Duplicacao massiva de boilerplate por engine** --
   `_setup_logging`, `save_run`, `export_json`, `setup_run` estao
   copy-pasted em graham/kepos/medallion/phi (`save_run`) e em
   citadel/bridgewater/jump/deshaw/renaissance (`export_json`). O
   `core/engine_base.py::EngineRuntime` existe para resolver isso, mas
   **nenhum engine o usa** -- so aparece em `tests/test_structure_contracts.py`.

## Metrics at a glance

- **Total LoC**: ~71.973 linhas (.py, excluindo `__pycache__`, `data/`, `tests/_tmp`).
- **Engines**: 14 ficheiros em `engines/` (+ `__init__.py`). Media ~900 LoC.
  Soma: ~14.500 LoC.
- **Core**: 40 modulos em `core/`, ~13.000 LoC.
- **Launcher**: 12.524 LoC num unico ficheiro (~17% do codebase).
- **Tests**: 52 ficheiros, ~955 `def test_*` (pytest IDs).

**Top 5 maiores ficheiros:**

| # | Ficheiro | LoC |
|---|----------|-----|
| 1 | `launcher.py` | 12.524 |
| 2 | `engines/live.py` | 2.438 |
| 3 | `engines/janestreet.py` | 2.434 |
| 4 | `analysis/report_html.py` | 1.840 |
| 5 | `core/engine_picker.py` | 1.531 |

**Funcoes/metodos problematicos (>200 LoC):**
- `launcher.App._data_lake` -- **491 LoC**
- `launcher.App._dash_portfolio_render` -- 326
- `engines/live.py::LiveEngine.__init__` (linhas 857..1408) -- **~551 LoC num `__init__`**
- `engines/graham.py::export_json` -- 476
- `engines/kepos.py::export_json` -- 387
- `launcher.App._results_build_overview` -- 251
- `launcher.App._exec` -- 225
- `launcher.App._menu` -- 221
- `launcher.App._strategies` -- 210

## Findings

### Critical (technical debt a bloquear progresso)

**C1. `engines/live.py::LiveEngine.__init__` tem ~550 linhas** (linhas 857-1408).
Um construtor desse tamanho significa que toda a configuracao de estado
(buffer, signal_e, orders, kill_sw, drift, audit, risk_cfg, dezenas de
outros) vive inline, impossivel de testar em partes. Acrescenta friccao
em qualquer mudanca em live trading -- a parte mais sensivel do sistema.
**Risco**: uma mudanca de codigo defensivo esconde-se facilmente entre
as ~550 linhas.

**C2. `launcher.py` e um God Object.** Uma unica classe `App` com 412
metodos encapsulando navegacao, rendering, process management, portfolio,
exec tracking, data lake, dashboard, etc. O ficheiro tem 236 `except
Exception` e 87 ocorrencias do padrao silent `except Exception: pass`.
Qualquer bug em UI pode ser mascarado por um desses. **Nao e critico
para trading, mas e critico para velocidade de desenvolvimento do launcher.**

**C3. CLAUDE.md esta factualmente desactualizado.**
- Tabela de engines lista 10, mas `config/engines.py` tem 15 (faltam
  kepos, graham, medallion, phi, winton na doc).
- Seccao "Estrutura de Ficheiros" menciona `multistrategy.py` como
  excepcao -- esse ficheiro nao existe; o caso real e `millennium.py`.
- CLAUDE.md diz "~26.000+ linhas" -- a contagem real e ~72k.
- Risco: agentes (Claude, Codex) recebem contexto errado sobre o projecto.

### High (deve ser corrigido)

**H1. `millennium.py` importa 5 engines.** Linhas 25, 1153, 1170, 1181,
1204, 1216, 1223, 1264, 1276, 1283, 1292. Regra do CLAUDE.md: engines
nunca se importam entre si. Excepcao documentada esta incorrecta
(diz `multistrategy` em vez de `millennium`). Ou actualizar a doc
para reconhecer millennium como orquestrador legitimo, ou refactorar
extraindo `scan_symbol`/`scan_pair`/`scan_mercurio` para `core/` como
funcoes puras reutilizaveis.

**H2. Duplicacao em `save_run`/`export_json`/`_setup_logging`.**
- `save_run` quase identico em `graham.py:714`, `kepos.py:619`,
  `medallion.py:773`, `phi.py:1022` (~20-40 linhas cada).
- `export_json` em 5 engines: `citadel.py:512`, `bridgewater.py:491`,
  `deshaw.py:665`, `jump.py:436`, `renaissance.py:59`.
- `_setup_logging` quase identico em graham/kepos/medallion/phi.

Total estimado: ~400 linhas duplicadas. `core/engine_base.py` existe
como scaffold mas **nao e usado por nenhum engine**.

**H3. `core/engine_base.py::EngineRuntime` e codigo fantasma.**
Ninguem importa excepto `tests/test_structure_contracts.py:10`. Ha duas
possibilidades: (a) WIP abandonado, ou (b) scaffold a espera de migracao.
Precisa decisao: ou adoptar em todos os engines novos (resolve H2), ou
remover.

**H4. Duas APIs de escrita atomica coexistem.**
- `core/fs.py::atomic_write(path, data: str)` -- usado por 13 engines + rotate_keys + test_fs.
- `core/persistence.py::atomic_write_json / atomic_write_text` -- usado por 10 modulos core + launcher + tools/medallion_finalize + tools/reconcile_runs.

Nenhuma e incorrecta, mas a convencao esta fragmentada por camadas
(engines -> fs.py; infra -> persistence.py). Risco: nova pessoa/agente
nao sabe qual usar.

**H5. Cobertura de testes assimetrica.**
Engines com teste dedicado: **phi, graham, kepos, hawkes** (os novos).
Engines **sem** teste dedicado: **citadel, bridgewater, jump, deshaw,
twosigma, aqr, millennium, medallion, renaissance, janestreet
(so characterization), live**. Backtests calibrados vivem aqui -- core
de trading sem testes unitarios proprios. Os contract tests cobrem
`core/*` mas nao a logica do scan_symbol de cada engine.

### Medium

**M1. `except Exception:` e epidemia controlada.** 273 ocorrencias em
44 ficheiros. 236 so no launcher (95% das quais em UI code), 135 sao
`except Exception: pass`. No `launcher.py` e razoavel (Tk throws
volateis). Mas algumas estao em `engines/` (jump, graham, medallion,
phi, bridgewater, renaissance) onde podem mascarar bugs silenciosos.
Recomenda-se logar o erro antes do pass, nem que seja em DEBUG.

**M2. `engines/janestreet.py` nao tem docstring de modulo.** So um
header de comentario (`# AURUM Finance - Arbitrage Engine v5.0`). E o
engine de arbitragem live -- documentacao em docstring e importante.
Mesmo problema em `engines/millennium.py`. `kepos.py`, `medallion.py`,
`phi.py`, `graham.py` tem docstrings bons -- usar como modelo.

**M3. `launcher.py` tem metodos grandes (>200 LoC) que sao
refactoraveis independentemente.** `_data_lake` (491), `_exec` (225),
`_menu` (221), `_strategies` (210). Candidatos a serem extraidos para
`launcher_support/` (ja existe como package).

**M4. Type hints inconsistentes.** 148 funcoes em `core/` sem return
type; 226 com return type. Nao ha convencao forcada por lint. Nao e
bloqueante, mas a ausencia em funcoes publicas (`core/signals.py`,
`core/indicators.py`) enfraquece contratos.

**M5. Registry `PROC_ENGINES` em `config/engines.py:38-114`** tem aliases
legacy (`backtest`, `multi`, `arb`, `newton`, `mercurio`, `thoth`,
`prometeu`, `darwin`, `chronos`). Bom que estejam num unico lugar. Mas
`launcher.py:55-78` tem **outro** `LEGACY_ENGINE_ALIASES` paralelo. Duas
fontes da mesma verdade -- consolidar em `config/engines.py`.

### Low / nitpicks

**L1.** `engines/__init__.py`, `engines/millennium.py`,
`engines/janestreet.py` sem docstrings.

**L2.** `analysis/plots.py` usa `from config.params import *` mas nao
e engine -- unico nao-engine/nao-core-trading-helper com wildcard.
Pequena violacao de convencao.

**L3.** `engines/janestreet.py:71` tem encadeamento de statements com
semi-colons numa linha -- violacao do estilo global do projecto
(todos os outros engines usam 1 statement por linha).

**L4.** `bot/telegram.py` faz import dinamico de `engines.live` (linhas
30, 162, 200). Defensavel (evita circular import), mas merece comentario.

**L5.** `core/__init__.py` re-exporta funcoes de core (data, indicators,
signals, portfolio, htf) -- permite a `millennium.py:14` fazer
`from core import (fetch_all, validate, ...)`. Bom. Mas `harmonics`,
`chronos`, `sentiment` nao sao re-exportados -- inconsistencia.

## Strengths

- **`config/params.py` como SSOT funciona**: 15 ficheiros fazem
  `from config.params import *`, todos em engines ou core de trading.
  Nenhum sneak wildcard alem disso.
- **`core/` tem baixo acoplamento interno**: nenhum import circular;
  `indicators -> signals -> portfolio -> htf` e uma DAG limpa.
- **Engines novos (phi, graham, kepos, medallion) tem qualidade claramente
  superior aos antigos**: docstrings, imports explicitos (nao wildcard),
  dataclasses para params, testes dedicados.
- **`config/engines.py` como registry canonico** resolve correctamente o
  problema de aliases legacy -- so falta launcher.py adoptar.
- **Contract tests (~48 ficheiros `test_*_contracts.py`)** cobrem a
  fronteira de `core/` bem -- e essa a camada mais importante para
  estabilidade.
- **Loggers espelham o nome do engine** consistentemente (CITADEL, KEPOS,
  PHI, etc.) -- facilita grep de logs.

## Refactoring opportunities (ranked by ROI)

1. **Adoptar `EngineRuntime` nos 4 engines novos (phi/graham/kepos/medallion)
   como piloto. ROI alto, risco baixo.**
   Remove ~200 LoC duplicadas, da base para retrofit dos outros 10 engines
   depois. Pode ser feito sem tocar nos 4 ficheiros do CORE DE TRADING
   protegido. Comecar pelos engines novos que ainda nao estao em
   `FROZEN_ENGINES`. Se correr bem, migrar citadel/bridgewater/jump/deshaw
   depois (esses exigem re-rodar smoke para garantir paridade).

2. **Partir `launcher.py` em modulos por responsabilidade.** Ja existe
   `launcher_support/` -- expandir o padrao:
   - `launcher_support/screens_exec.py` <- `_exec*`, `_clr` (~800 LoC)
   - `launcher_support/screens_data.py` <- `_data_lake`, `_data_engines`,
     `_data_backtests` (~1.000 LoC)
   - `launcher_support/screens_dashboard.py` <- `_dash_*` (~1.200 LoC)

   Cada extraccao deve vir com teste de snapshot para nao quebrar a UI.
   ROI alto: todo o iteration loop no launcher acelera. Risco medio: Tk
   tem estado interno vicioso, mas ajuda desacoplar.

3. **Consolidar `core/fs.atomic_write` e `core/persistence.atomic_write_*`
   numa unica API.** Decidir: `persistence` e o novo, `fs.atomic_write` e
   o velho. Migrar os 13 engines + tests + rotate_keys para
   `persistence.atomic_write_text`. ROI medio (limpa convencao), risco
   muito baixo (APIs equivalentes, facil grep-replace).

4. **Actualizar CLAUDE.md**: tabela de engines (adicionar os 5 novos),
   contar LoC real (~72k), substituir "multistrategy -> engines/backtest"
   pela realidade actual (millennium importa 5 engines), adicionar
   `launcher_support/` na estrutura de ficheiros.

5. **Quebrar `LiveEngine.__init__` do `engines/live.py`.** Extrair em
   `_setup_audit()`, `_setup_risk_gates()`, `_setup_telemetry()`,
   `_setup_ws()`. Como toca codigo de live trading, exige MUITA
   disciplina -- fazer so se o Joao aprovar, com smoke test 156/156 antes
   e depois. ROI alto em manutenibilidade, risco alto em live.

6. **Adicionar testes unitarios para engines antigos (citadel,
   bridgewater, jump, deshaw) no estilo `test_phi.py`.** Fixar
   `scan_symbol` com uma fixture pequena de dados. Protege a
   calibracao walk-forward contra regressoes silenciosas.

---

**Surpresas:**

- `EngineRuntime` existir e nao ser usado (dead scaffold).
- `launcher.py` ter **412 metodos numa classe so** -- maior monolito
  obvio do projecto.
- A tabela de engines no CLAUDE.md estar 3 engines atras da realidade.
- `LiveEngine.__init__` com ~550 linhas -- o segundo maior offensor.
- Nenhum engine antigo (citadel/bridgewater/jump/etc.) ter teste
  dedicado; so contract tests cobrem a camada core.
