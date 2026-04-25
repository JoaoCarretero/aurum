# LIVE RUNS refactor — design spec

**Date:** 2026-04-20
**Author:** Claude Opus 4.7
**Status:** Draft — awaiting user review before writing implementation plan

## Problem

A tela `_data_engines` (ENGINE LOGS) mistura duas responsabilidades: **processos
rodando agora** (live procs com tail) e **histórico de runs em modos
live/paper/shadow/demo/testnet**. O filesystem sob `data/` acumula 860 run
dirs em 29 subpastas, com research dirs (`_bridgewater_*`, `anti_overfit/`,
`audit/`, `param_search/`, `perf_profile/`, `validation/`) e runs legacy em
`data/runs/` (10 dirs com naming antigo `<engine>_YYYY-MM-DD_*`)
ocupando espaço e poluindo qualquer browse. `nexus.db` tem 0 rows há semanas
(schema de feature do website abandonado). Não há fonte canônica pras runs
live — a UI faz FS scan toda vez que renderiza.

Baseline empírico: `on_enter` da tela equivalente (`data_center`) gastava
132 ms por visita só fazendo rglob de engine dirs; o ENGINE LOGS legacy
reporta `legacy_rebuild ms=264` em `screens.log`. Ambos são puro custo de
scan de disco.

## Goal

1. **Separar conceitos.** LIVE RUNS passa a ser histórico de runs em modos
   live/paper/shadow/demo/testnet, espelho visual de BACKTESTS. Processos
   rodando saem 100% dessa tela e vão pra PROCESSES.
2. **Fonte canônica no DB.** Nova tabela `live_runs` em `aurum.db` com
   backfill dos dirs existentes. Runners escrevem no DB a cada tick. UI lê
   do DB (sub-ms), não do FS.
3. **Limpeza do disco.** Research dirs vão pra `data/_archive/research/`;
   `data/runs/` legacy é consolidado nos engine dirs próprios; `nexus.db`
   vira arquivo de archive.
4. **Design profissional.** Paridade visual com BACKTESTS (left list +
   right detail + DETAILS pane scrollable + filter bar + auto-select
   newest).

## Non-goals

- Não mudar os runners live (paper/shadow/live) além de adicionar 1 hook
  de upsert por tick. Zero mudança na lógica de sinais ou portfolio.
- Não tocar em `index.json` (continua sendo a fonte canônica de backtests).
- Não tocar em CORE PROTEGIDO (`core/indicators.py`, `core/signals.py`,
  `core/portfolio.py`, `config/params.py`).
- Não unificar BACKTESTS e LIVE RUNS numa tela só (decisão: opção B
  do brainstorm, não C).
- Não fazer retenção automática — polish da Fase 3, opcional.

## Phasing

Três fases sequenciais. Fase 1 é infraestrutura isolada (testável sem
UI). Fase 2 é a UI, consumindo o DB da Fase 1. Fase 3 é polish opcional.

### Fase 1 — Infra (cleanup + DB)

Infraestrutura que pode ser shipada sozinha, validada e commitada antes
de qualquer mudança de UI.

#### 1.1 Cleanup de disco

Script `tools/maintenance/cleanup_data_layout.py` — **reversível,
idempotente, dry-run por default**.

Operações (todas `mv`, nunca `rm`):

| Origem                                       | Destino                                       |
|---------------------------------------------|-----------------------------------------------|
| `data/_bridgewater_compare/`                 | `data/_archive/research/_bridgewater_compare/` |
| `data/_bridgewater_regime_filter/`           | `data/_archive/research/_bridgewater_regime_filter/` |
| `data/_bridgewater_rolling_compare/`         | `data/_archive/research/_bridgewater_rolling_compare/` |
| `data/anti_overfit/`                         | `data/_archive/research/anti_overfit/`        |
| `data/audit/`                                | `data/_archive/research/audit/`               |
| `data/param_search/`                         | `data/_archive/research/param_search/`        |
| `data/perf_profile/`                         | `data/_archive/research/perf_profile/`        |
| `data/validation/`                           | `data/_archive/research/validation/`          |
| `data/runs/<engine>_YYYY-MM-DD_*/`           | `data/<engine>/<timestamp suffix>/`           |
| `data/nexus.db*`                             | `data/_archive/db/nexus.db.<timestamp>`       |

Regras:
- **Dry-run default.** Flag `--apply` necessária pra mover.
- **Idempotente.** Se dest já existe com mesmo nome, skip e logar.
- **Soft-delete.** `nexus.db` vai pra `_archive/db/` (não deletar), em
  caso de decisão futura.
- **Preserva `index.json`.** Não toca em nenhum dir que tem entrada em
  `data/index.json` como backtest válido — consulta lookup antes.
- **Rollback doc.** Script printa comando inverso no final pra cada mv.

Testes (unit, em tmp_path fixtures):
- dry-run só lista, não move
- `--apply` move corretamente
- idempotente (rodar 2× não duplica nem erra)
- preserva dirs em `index.json`
- rollback command printado é executável

#### 1.2 DB schema — tabela `live_runs`

Migration via script `tools/db/migrations/001_live_runs.py`. DDL:

```sql
CREATE TABLE IF NOT EXISTS live_runs (
    run_id       TEXT PRIMARY KEY,
    engine       TEXT NOT NULL,
    mode         TEXT NOT NULL CHECK(mode IN ('live','paper','shadow','demo','testnet')),
    started_at   TEXT NOT NULL,              -- ISO 8601 UTC
    ended_at     TEXT,                       -- null = ainda rodando
    status       TEXT NOT NULL DEFAULT 'unknown',  -- running/stopped/crashed/unknown
    tick_count   INTEGER NOT NULL DEFAULT 0,
    novel_count  INTEGER NOT NULL DEFAULT 0,
    open_count   INTEGER NOT NULL DEFAULT 0,
    equity       REAL,
    last_tick_at TEXT,
    host         TEXT,                       -- localhost / vps hostname
    label        TEXT,                       -- multi-instance label
    run_dir      TEXT NOT NULL,              -- path relativo a ROOT
    notes        TEXT                        -- stub pra futuros tags
);

CREATE INDEX IF NOT EXISTS idx_live_runs_mode_started
    ON live_runs(mode, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_live_runs_engine_started
    ON live_runs(engine, started_at DESC);
```

Notas:
- `run_id` é `<engine>_<mode>_<YYYY-MM-DD_HHMM>[_<label>]`, mesmo que já é
  usado pelos runners hoje (`data/millennium_paper/2026-04-20_1156/` etc).
  Mantém compatibilidade.
- `mode` restricted via CHECK — runner inválido falha explícito.
- Ambos índices pra query comum: filter por mode + sort DESC, filter por
  engine + sort DESC.

#### 1.3 Backfill one-shot

Script `tools/db/backfill_live_runs.py`:

1. Scan dirs `data/millennium_{live,paper,shadow}/`, `data/live/`,
   `data/{engine}_live/` (glob de naming conhecido).
2. Pra cada dir, ler `run_meta.json` ou `heartbeat.json` se existe;
   senão, parsear do path (engine + mode + timestamp).
3. Inferir `status`:
   - heartbeat.json com `last_tick_at` < 10min → `running`
   - heartbeat.json existe mas stale → `stopped`
   - nenhum heartbeat → `stopped`
4. `INSERT OR REPLACE` — idempotente.

Testes:
- fixture com 3 dirs live fake → linhas corretas no DB
- re-rodar não duplica
- dir sem heartbeat → status `stopped`
- dir com heartbeat recente → status `running`

#### 1.4 Runtime hook

Em `tools/operations/millennium_paper.py`,
`tools/maintenance/millennium_shadow.py` e `engines/live.py`, adicionar
chamada `core.db.live_runs.upsert(run_id, **state)` a cada tick. Nova
função simples em `core/db/live_runs.py`:

```python
def upsert(run_id: str, **fields: Any) -> None:
    """Insert-or-update single live_run row. Barato (single row UPDATE)."""
```

Campos atualizáveis: `tick_count`, `novel_count`, `open_count`, `equity`,
`last_tick_at`, `status`, `ended_at`. `engine`/`mode`/`started_at`/`host`
são setados no primeiro tick (INSERT).

Testes:
- upsert cria row na primeira chamada
- upsert atualiza row nas chamadas seguintes
- concurrent upsert não corrompe (WAL mode)

---

### Fase 2 — UI (tela LIVE RUNS)

Entra depois que Fase 1 tá commitada e backfill rodou.

#### 2.1 Screen

`launcher_support/screens/live_runs.py` — classe `LiveRunsScreen(Screen)`.

Registrada em `registry.py`:
```python
manager.register("live_runs",
    lambda parent: LiveRunsScreen(parent=parent, app=app))
```

Layout (paridade com BACKTESTS):
- Header: "LIVE RUNS" + subtitle "Histórico live/paper/shadow/demo/testnet"
- Filter bar horizontal: `ALL` / `LIVE` / `PAPER` / `SHADOW` / `DEMO` /
  `TESTNET` (teclas 1-6 mantidas do legacy)
- Engine dropdown (default "all")
- Time range dropdown: `7d` / `30d` / `90d` / `all` (default `30d`)
- Split horizontal:
  - Left (60% weight): run list scrollable, cols `[STATUS, ENGINE, MODE,
    STARTED, DURATION, TICKS, SIG, EQUITY]`
  - Right (40% weight): detail panel scrollable

#### 2.2 Detail panel

Seções:
- **IDENTITY**: engine, mode, run_id, label, host, run_dir
- **TIMELINE**: started_at, ended_at, duration, last_tick_at (+ age)
- **PERFORMANCE**: equity, realized_pnl (if available), open_count,
  max_drawdown (se presente em heartbeat)
- **ACTIVITY**: tick_count, novel_count, last tick age badge (verde se
  <3× tick_sec, amarelo <10×, vermelho >10×)
- **ACTIONS**: `OPEN DIR` / `TAIL LOG` (popup window com últimas N
  linhas) / `STOP` (if running, via `core.ops.proc.stop_proc`) /
  `ARCHIVE` (soft-delete: mv pra `data/_archive/live/`)

Auto-select newest na primeira visita — igual BACKTESTS.

#### 2.3 Data access

Nova função em `core/db/live_runs.py`:

```python
def list_live_runs(
    *,
    mode: str | None = None,       # None = all
    engine: str | None = None,
    since: datetime | None = None,
    limit: int = 200,
) -> list[LiveRun]:
    """Query live_runs table, newest first."""

def get_live_run(run_id: str) -> LiveRun | None:
    """Single row fetch for detail panel."""
```

Cache TTL 3s na camada Screen (padrão já estabelecido em
`DataCenterScreen._get_counts`).

#### 2.4 Menu & key binding

- `DATA CENTER > LIVE RUNS` — nova entry com key `L` (antes era
  engine logs com key `E`).
- `DATA CENTER > ENGINE LOGS` (key `E`) — mantém mas redireciona
  pra PROCESSES com mensagem "moved". Stub por 2 sessões, depois
  remove o entry mas deixa a key E mapeada pra PROCESSES (backward
  compat).
- MAIN menu > PROCESSES continua como está (já tem proc list +
  tail completo — é o que era `_data_engines` tirando o histórico).

#### 2.5 Tests (unit + integration)

Unit:
- `test_live_runs_screen.py` — build + on_enter + filter switch + detail
  render (fake db via monkeypatch `list_live_runs`)
- `test_live_runs_db.py` — upsert/list/get coverage
- TTL cache igual `test_data_center_screen.py`

Integration:
- `test_launcher_live_runs.py` — abrir tela via ScreenManager, clicar
  row, validar detail. Real Tk.

### Fase 3 — Polish (opcional)

- `tools/maintenance/archive_old_live_runs.py` — retenção configurável
  (default 90d → mv pra `data/_archive/live/`)
- Sparkline real de equity no detail panel (Canvas, reuso de helper do
  dashboard)
- Deep link pra Telegram message se a run disparou alert

## Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Cleanup move dir em uso por proc running | Check `core.ops.proc.list_procs()` antes de cada mv — skip se dir alvo está em `cwd` de algum proc alive |
| Backfill categoriza errado (mode) | Naming convention consistente; scripts assumem `<engine>_live` = live, `millennium_paper` = paper, etc. Ambíguos vão pra `unknown` e flag no log |
| DB schema drift | Migration script em `tools/db/migrations/` numerado, rodado via tool explícito (não auto) |
| Runtime hook custa latency | `upsert` é single-row UPDATE em WAL mode — <1ms. Benchmark na fase 1 antes de wire |
| nexus.db era usado e ninguém sabia | Soft-delete em `_archive/db/`, recuperável via `mv` reverso |
| Contract tests quebram | Zero toque em CORE PROTEGIDO. Tests novos são aditivos. Smoke 178/178 + contracts 835/835 precisam continuar passing |

## Success criteria

**Fase 1:**
- Script de cleanup dry-run mostra todas as moves, `--apply` executa
  corretamente, re-executar é no-op.
- `aurum.db` tem tabela `live_runs` com N ≥ 350 linhas (48+43+57+248+11 =
  ~407 dirs live no estado atual).
- Runners paper/shadow escrevem no DB sem aumentar latency do tick
  (medido: delta <5ms per tick).
- Testes novos 100% passing. Smoke 178/178. Contracts 835/835.

**Fase 2:**
- `LIVE RUNS` reentry <5ms (paridade com outras migradas).
- Filter switch instantâneo (query DB, não FS).
- Auto-select newest funciona.
- Actions (OPEN DIR, TAIL LOG, STOP, ARCHIVE) funcionam end-to-end.
- Screen registrada no ScreenManager, não usa legacy destroy+rebuild.

## Non-requirements flagged

- Websocket feed de equity ao vivo na detail panel — Fase 3 se demanda.
- Integrações Grafana/Prometheus — fora de escopo.
- Export CSV do filter atual — se user pedir depois.
- Multi-run compare — fora de escopo (BACKTESTS também não tem).
