# MILLENNIUM Paper Runner — Design

**Data:** 2026-04-19
**Branch de origem:** `feat/phi-engine` (commit `34c5404`)
**Branch de trabalho:** `feat/millennium-paper`
**Escopo:** Adicionar runner paper para o pod MILLENNIUM (CITADEL +
JUMP + RENAISSANCE) com execução simulada posição-por-posição, account
size configurável, tracking de equity/PnL/métricas ao vivo, e cockpit
UI integrada. Shadow permanece independente e inalterado.

## Decisões Arquiteturais (Q1-Q5)

| # | Pergunta | Decisão |
|---|----------|---------|
| Q1 | Persistência | **Fresh per run** — cada execução começa do `account_size` configurado; sem carry-over de equity entre runs |
| Q2 | Execução | **Híbrida pragmática** — signal detection reusa `_collect_operational_trades` (scan backtest), position state tracked tick-a-tick com OHLCV real, exits por stop/target em barras reais (NÃO usa exit pré-computado do backtest) |
| Q3 | Risk gates | **Backtest stack + KS live** — `position_size()`, `portfolio_allows()`, `check_aggregate_notional()` reusados; kill-switch ladder (fast/slow thresholds) espelhado de `engines/live.py` |
| Q4 | Topologia | **Serviço systemd separado** — `millennium_paper.service` paralelo a shadow no VPS. Scan roda 2x por tick (shadow + paper, cada um seu); CPU extra aceitável (~2% tick). Blast radius isolado |
| Q5 | Cockpit UI | **Full trading dashboard** — HEADER + HEALTH (com EQUITY + DD) + RUN INFO + OPEN POSITIONS table + EQUITY CURVE sparkline + METRICS cards + LAST SIGNALS |

## Arquitetura & Boundaries

### Componentes novos

```
tools/operations/millennium_paper.py       ← runner standalone (entrypoint systemd)
  ├─ PaperAccount          balance, equity, refs de posições abertas, lista de trades fechados
  ├─ PaperExecutor         signal → open position (aplica slippage + spread + commission)
  ├─ PositionManager       MTM a cada tick + detecção stop/target intrabar
  ├─ KSLiveGate            fast/slow DD ladder, halt-all-on-breach
  └─ MetricsStreamer       Sharpe/Sortino/WR/PF/MaxDD incremental

tests/test_paper_*                        ← unit + integration
deploy/millennium_paper.service           ← systemd unit
deploy/install_paper_vps.sh               ← one-shot installer
```

### Reuso zero CORE tocado

- `engines.millennium._collect_operational_trades` — scan idêntico ao shadow
- `core.portfolio.position_size` — sizing (via scaling hack abaixo)
- `core.portfolio.portfolio_allows` + `check_aggregate_notional` — risk gates
- `core.shadow_contract.Heartbeat/Manifest/RunSummary` — contratos JSON
- `_compute_trade_metrics` (em millennium_shadow) — extraído para helper shared
- `_tg_send/_tg_signal` (em millennium_shadow) — adaptados mínimo pra paper

### Scaling hack para `ACCOUNT_SIZE` configurável

`config.params.ACCOUNT_SIZE` é lido direto pelo `position_size()` e hardcoded. Pra permitir account_size configurável sem tocar CORE PROTECTED, aplicar fator linear pos-call:

```python
ACCOUNT_SIZE_DEFAULT = config.params.ACCOUNT_SIZE  # sempre 10_000
scale = args.account_size / ACCOUNT_SIZE_DEFAULT
size_actual = size_from_core * scale
```

Preserva relações de risco (Kelly, convex, DD scale, omega) porque a escala é linear e o risco é sempre proporcional a `account * BASE_RISK`. Documentado inline como "não é decorator, é escalamento pos-call — se algum dia `position_size` virar não-linear em equity, esse hack precisa revisão".

### Data flow por tick (cada 900s)

```
fetch OHLCV last 180d (fresh)
  ↓
_collect_operational_trades → list[Trade] com entry+stop+target resolved
  ↓
filter(entry_idx == latest_closed_bar) → new_signals
  ↓
for each signal:
  risk_check(signal, account, open_positions) → skip se denied
  PaperExecutor.open(signal, account.equity)
    ├ size = position_size(...) * SCALE
    ├ apply SLIPPAGE + SPREAD na entry
    ├ commission deducted imediato
    └ record em state/positions.json + reports/fills.jsonl
  ↓
for each open position:
  PositionManager.check_exit(new_bars_since_last_check)
    ├ stop hit intrabar → close at stop, realized_pnl
    ├ target hit intrabar → close at target, realized_pnl
    ├ both hit same bar → stop wins (conservative)
    └ neither → MTM com last_bar.close, update unrealized_pnl
  apply_funding(pos, tick_sec)
  ↓
KSLiveGate.check(account)
  ├ (equity - peak) < fast_threshold → FAST_HALT → flatten all
  └ (equity - peak) < slow_threshold → SLOW_HALT → halt new opens
  ↓
MetricsStreamer.update(closed_trades, equity_curve)
  ↓
atomic_write:
  state/heartbeat.json
  state/positions.json
  state/account.json
  reports/trades.jsonl (append on close)
  reports/equity.jsonl (append cada tick)
  reports/fills.jsonl (append cada event)
  reports/signals.jsonl (append inclui skipped)
```

### Blast radius

- Paper crash não afeta shadow (serviços systemd separados)
- Position state em disk (atomic_write cada tick) → restart retoma
- KS live gate pode abortar o run sem derrubar a máquina
- Cockpit API crash não afeta nenhum runner

## Run Directory Layout

```
data/millennium_paper/<RUN_ID>/
├── state/
│   ├── manifest.json       ← commit, branch, host, account_size, config_hash
│   ├── heartbeat.json      ← tick counters (status, ticks_ok, novel_since_prime...)
│   ├── positions.json      ← snapshot atomic: posições abertas no momento
│   ├── account.json        ← snapshot atomic: balance, equity, KS state, metrics running
│   └── .kill               ← flag file (touch → kill limpo)
├── reports/
│   ├── trades.jsonl        ← append-only: cada trade fechado
│   ├── equity.jsonl        ← append-only: tick → equity point
│   ├── fills.jsonl         ← append-only: cada open/close event
│   ├── signals.jsonl       ← append-only: signal detectado (inclui skipped)
│   └── summary.json        ← computed no stop: Sharpe/Sortino/WR/PF/MaxDD/ROI + per-engine
└── logs/
    └── paper.log           ← log estruturado tick-a-tick
```

### Schemas JSON (contratos estáveis)

**positions.json** (snapshot, rewrite atomic cada tick):
```json
{
  "as_of": "ISO8601",
  "count": 2,
  "positions": [
    {
      "id": "pos_1234",
      "engine": "CITADEL",
      "symbol": "BTCUSDT",
      "direction": "LONG",
      "entry_price": 65432.5,
      "stop": 65120.0,
      "target": 66890.0,
      "size": 0.0760,
      "notional": 4976.0,
      "opened_at": "ISO8601",
      "opened_at_idx": 8456,
      "unrealized_pnl": 12.30,
      "r_multiple": 0.14,
      "mtm_price": 65594.5,
      "bars_held": 6
    }
  ]
}
```

**account.json** (snapshot):
```json
{
  "as_of": "ISO8601",
  "initial_balance": 10000.0,
  "current_balance": 10068.45,
  "realized_pnl": 68.45,
  "unrealized_pnl": 12.30,
  "equity": 10080.75,
  "peak_equity": 10120.00,
  "drawdown": 39.25,
  "drawdown_pct": 0.39,
  "ks_state": "NORMAL | SLOW_HALT | FAST_HALT | LOCKED",
  "ks_last_trigger": null,
  "positions_open": 2,
  "trades_closed": 1,
  "metrics": {
    "wins": 1, "losses": 0, "win_rate": 1.0,
    "profit_factor": 0.0, "sharpe": 0.0,
    "maxdd": 0.0, "roi_pct": 0.685
  }
}
```

**trades.jsonl** (append-only, 1 linha por fechamento):
```json
{"id":"pos_1234","engine":"CITADEL","symbol":"BTCUSDT","direction":"LONG","entry_price":65432.5,"stop":65120.0,"target":66890.0,"size":0.076,"entry_at":"ISO","exit_at":"ISO","exit_price":66890.0,"exit_reason":"target","pnl":110.77,"pnl_after_fees":103.44,"r_multiple":3.04,"bars_held":3,"primed":false}
```

**equity.jsonl** (append-only, 1 linha por tick):
```json
{"tick":42,"ts":"ISO","equity":10080.75,"balance":10068.45,"realized":68.45,"unrealized":12.30,"drawdown":39.25,"positions_open":2}
```

**fills.jsonl** (append-only, 1 linha por evento):
```json
{"event":"open","pos_id":"pos_1234","ts":"ISO","engine":"CITADEL","symbol":"BTCUSDT","direction":"LONG","price":65432.5,"size":0.076,"slippage":19.63,"commission":19.89}
{"event":"close","pos_id":"pos_1234","ts":"ISO","reason":"target","price":66890.0,"pnl":110.77,"pnl_after_fees":103.44,"commission":20.30}
```

**signals.jsonl** (audit incluindo skipped):
```json
{"ts":"ISO","engine":"CITADEL","symbol":"BTCUSDT","direction":"LONG","entry":65432.5,"stop":65120.0,"target":66890.0,"decision":"opened","pos_id":"pos_1234"}
{"ts":"ISO","engine":"JUMP","symbol":"ETHUSDT","direction":"SHORT","entry":3450.0,"stop":3478.0,"target":3380.0,"decision":"skipped","reason":"portfolio_allows_denied(corr>0.80)"}
```

## Position Lifecycle & Risk Gates

### State machine

```
OPEN ──┬─ hit stop intrabar  → CLOSED (stop)
       ├─ hit target intrabar → CLOSED (target)
       ├─ funding tick        → apply funding cost, keep OPEN
       ├─ kill-switch         → CLOSED (ks_abort) — flatten all
       └─ (V2) timeout        → CLOSED (timeout)
```

### Regra de fill (entry)

```python
# Signal fires no bar N; entry idx = N+1
entry_px_sim = bar[N+1].open
entry_fill = entry_px_sim * (1 + SLIPPAGE if LONG else 1 - SLIPPAGE) + SPREAD
commission_paid = entry_fill * size * COMMISSION
account.balance -= commission_paid
```

Espelha `engines/live.py::OrderManager.paper_fill`.

### Regra de exit (check per tick)

```python
for pos in open_positions:
    for bar in new_bars_since_last_tick:
        if pos.direction == LONG:
            if bar.low <= pos.stop:  close_at(pos.stop, "stop"); break
            if bar.high >= pos.target: close_at(pos.target, "target"); break
        else:  # SHORT
            if bar.high >= pos.stop: close_at(pos.stop, "stop"); break
            if bar.low <= pos.target: close_at(pos.target, "target"); break
    else:
        pos.mtm_price = last_bar.close
        pos.unrealized_pnl = (mtm - entry) * size * dir_sign
```

**V1: fixed stop + target only.** Trailing stops estão em `core.signals.label_trade` (CORE PROTECTED); reimplementar em paper duplicaria lógica. V2 pode integrar via call-through (forward slice + label_trade) se se justificar.

**Both stop AND target hit same bar → stop wins** (conservador; espelha comportamento do backtest em caso ambíguo).

### Funding

```python
funding_delta = pos.notional * FUNDING_PER_8H * (tick_sec / (8 * 3600))
account.balance -= funding_delta if pos.direction == LONG else +funding_delta
```

Aplicado a cada tick proporcional — simplificação vs 8h-exato (aceitável em 15min tick).

### Risk gates (avaliados em ordem antes de abrir)

```python
def should_open(signal, account, open_positions) -> (bool, str):
    if ks_state in ("FAST_HALT", "LOCKED"):
        return False, f"ks_{ks_state}"
    if not portfolio_allows(signal, open_positions, ...):
        return False, "portfolio_denied"
    proposed_size = position_size(account.equity, ...) * scale
    if not check_aggregate_notional(open_positions, signal, proposed_size):
        return False, "aggregate_cap"
    return True, "ok"
```

KS check primeiro (mais crítico, short-circuit).

### KS Live Gate

**V1: só fast_halt** (única constante KS existente hoje é `KS_FAST_DD_MULT=2.0` em `engines/live.py:153`). Slow_halt com multiplier separado é V2.

```python
from engines.live import KS_FAST_DD_MULT  # = 2.0
from config.params import BASE_RISK        # = 0.005

# Threshold escalado com args.account_size
fast_threshold = -KS_FAST_DD_MULT * args.account_size * BASE_RISK
# Ex: -2.0 * 10_000 * 0.005 = -$100

# Per tick:
dd = account.equity - account.peak_equity
if dd < fast_threshold:
    ks_state = "FAST_HALT"
    flatten_all_positions()  # close at MTM
    stop_run()
```

State V1: `NORMAL → FAST_HALT → LOCKED`. Retomada NÃO automática — requer restart manual.

**V2 (fora escopo):** adicionar `KS_SLOW_DD_MULT` em params.py (requer aprovação do Joao — mexe em params.py CORE PROTECTED) + SLOW_HALT state que impede novas aberturas sem flatten existing.

## Cockpit API + UI Surface

### API — zero endpoints novos, contrato extendido

`GET /v1/runs` já descobre runs via `core.shadow_contract.find_runs`. Extender heuristic em `_engine_from_dir` pra reconhecer `*_paper/` suffix (adicionar mode `"paper"` ao contrato).

**Endpoints novos específicos pra paper (read-only):**

```
GET /v1/runs/{run_id}/positions
    → le state/positions.json (snapshot atual)

GET /v1/runs/{run_id}/equity?tail=200
    → le reports/equity.jsonl e retorna ultimos N pontos
```

Ambos via `Bearer <read_token>` existente.

### Cockpit UI — reuso máximo

`engines_sidebar.py::render_detail` já é genérico. Paper passa `mode="paper"` e aciona adições:

**HEALTH cards extendidos:**
- TICKS OK / FAIL / SIGNALS / UPTIME / LAST SIG (já existem)
- **EQUITY** ($10,080) — novo, cor verde se > initial, vermelho se <
- **DD** (-0.39%) — novo, cor amber/vermelho se > 2%/5%
- **NET** (+$80) — novo, realized + unrealized

**Seção OPEN POSITIONS** (nova, após RUN INFO):
- Tabela: TIME / SYM / DIR / ENTRY / STOP / TARGET / NOTIONAL / U_PNL / BARS
- Click em row → `render_inline` drill-down com seções OUTCOME (em progresso) + ENTRY + REGIME + MTM bar
- Empty state: "(sem posições abertas)"

**Seção EQUITY CURVE** (nova, entre OPEN POSITIONS e METRICS):
- Sparkline unicode chars ▁▂▃▄▅▆▇█ dos últimos 200 pontos de `equity.jsonl`
- Range low/high marcado abaixo
- Fallback de API para client-side: client fetcha `/equity?tail=200`

**Seção METRICS** (nova, após EQUITY CURVE):
- Cards: WR / PF / Sharpe / Sortino / MaxDD / ROI% / NetPnL
- Lidos de `state/account.json` (metrics nested dict)

**LAST SIGNALS** (já existe, inalterado):
- Tabela igual shadow, mas coluna RESULT reflete exit real (WIN/LOSS/OPEN)
- Click em row → drill-down inline (já implementado)

**Botões de action:**
- **STOP PAPER** (vermelho) — dropkilla `.kill`. Flag `--flatten-on-stop` no runner
- **FORCE FLATTEN** (amber) — fecha todas posições MTM (emergency)
- **START PAPER** (no empty state) — POST `/v1/shadow/start?service=millennium_paper`

### Mudança 1 linha em cockpit_api.py

```python
# shadow_start endpoint
ALLOWED = {"millennium_shadow", "millennium_paper"}
```

## Service, Deploy & Config

### Systemd unit (`deploy/millennium_paper.service`)

Baseado em `millennium_shadow.service`, diferenças:
- `Description`: "AURUM · MILLENNIUM paper runner (pod sim, tracks equity + positions)"
- `EnvironmentFile=/etc/aurum/paper.env` (define `AURUM_PAPER_ACCOUNT_SIZE`)
- `ExecStart=/usr/bin/python3 tools/operations/millennium_paper.py --account-size ${AURUM_PAPER_ACCOUNT_SIZE} --tick-sec 900 --run-hours 0`
- `MemoryMax=1G CPUQuota=150%` (mais generoso que shadow)
- `SyslogIdentifier=aurum-paper`

### Installer (`deploy/install_paper_vps.sh`)

Baseado em `install_shadow_vps.sh`. Steps:
1. Valida repo path existe
2. Smoke: `python tools/operations/millennium_paper.py --help`
3. Cria `/etc/aurum/paper.env` se não existir:
   ```
   AURUM_PAPER_ACCOUNT_SIZE=10000
   ```
4. Instala unit file com User + WorkingDirectory adaptados via sed
5. `systemctl daemon-reload && systemctl enable && systemctl start`
6. Probe: heartbeat.json aparece em ≤ 30s

### Config de account_size (precedência)

```
CLI arg --account-size 25000         (maior)
  ↓ fallback
AURUM_PAPER_ACCOUNT_SIZE env var     (systemd unit)
  ↓ fallback
config.params.ACCOUNT_SIZE = 10000.0 (default)
```

### Telegram (reuso `_tg_send`/`_tg_signal` adaptados)

Eventos:
- START: "MILLENNIUM paper START · run: X · account: $10k"
- POSITION OPEN: "PAPER · CITADEL LONG BTCUSDT · entry 65432 · stop 65120 · size $4,976"
- POSITION CLOSE: "PAPER · CITADEL BTCUSDT · TARGET · +$110 (R=3.0) · equity $10,080"
- KS FAST HALT: "⚠ KS FAST · dd -$128 · account halted · equity $9,872"
- STOP: "MILLENNIUM paper STOP · equity $10,080 · ROI +0.80% · Sharpe 1.8"

## Testing Strategy

### Unit tests

- `test_paper_account.py` — PaperAccount math (initial balance, realized, equity, peak, drawdown)
- `test_paper_executor.py` — fill logic (slippage LONG/SHORT, commission, sizing scale)
- `test_paper_position_manager.py` — exit detection (stop/target intrabar, both-hit=stop, MTM, funding)
- `test_paper_ks_gate.py` — KS thresholds, state machine, scaling com account_size
- `test_paper_metrics.py` — reuso + extensão `_compute_trade_metrics` + sparkline helper

### Integration tests

- `test_paper_runner_tick.py` — fake OHLCV → signal → open → target hit → trades.jsonl + equity.jsonl consistent
- `test_paper_runner_ks.py` — sequência bars trigger fast_halt → flatten + stop + summary com ks_triggered

### Contract tests

- `test_cockpit_paper_endpoints.py` — extende `test_cockpit_api.py`:
  - `/v1/runs` lista paper + shadow
  - `/v1/runs/{id}/positions` retorna positions.json
  - `/v1/runs/{id}/equity?tail=50` retorna tail
  - `/v1/shadow/start?service=millennium_paper` whitelist ok
  - `/v1/shadow/start?service=evil` rejeita 400

### Smoke test manual

```bash
python tools/operations/millennium_paper.py \
  --account-size 10000 --tick-sec 15 --run-hours 0.01
ls data/millennium_paper/<last_run>/
# esperado: state/ reports/ logs/ com artefatos
```

### Gate de aceitação pro merge

- [ ] Full suite passa (1266 existentes + ~30 novos)
- [ ] Smoke test manual gera artefatos válidos
- [ ] `python launcher.py` renderiza paper mode sem exception
- [ ] Deploy VPS: `systemctl start` → heartbeat em 30s → Telegram START ping

## Escopo Explicitamente Fora (V2+)

- **Trailing stops** — V1 usa fixed stop/target. V2 integra `core.signals.label_trade` via forward-slice se justificado
- **Persistência cross-run** — cada run começa fresh. Se precisar persistência, arquitetar depois como "accounts" nomeadas
- **Multi-account paralelo** — V1 roda 1 service = 1 account. V2 pode expandir com `--account-id` param e multi-unit
- **Backfill de historical trades** — paper só opera trades fresh da barra atual; retroativos não contam
- **Live trading** — este runner é só paper/sim. `engines/live.py` cobre o path real; o design dele não muda

## Riscos & Mitigações

| Risco | Mitigação |
|-------|-----------|
| Scaling hack quebra se `position_size` virar não-linear em equity | Teste que valida size(10k account) * 2 == size(20k account); documentação inline |
| Restart mid-run perde posições in-flight | `state/positions.json` atomic cada tick; runner no startup lê e retoma estado |
| Paper e shadow rodam scan 2x (CPU) | Aceitável (~2% tick); Lane 2b HMM speedup beneficia ambos |
| `find_runs` não descobre `*_paper/` | Extender heuristic em `core/shadow_contract.py` + test que cubra |
| KS thresholds mal-calibrados pra accounts pequenas ($1k) | Thresholds escalam linearmente com account_size; teste em fixtures $1k, $10k, $100k |
| Trade entry timestamp mismatch (scan vs real clock) | Use `bar[N+1].timestamp` (bar next) não `datetime.now()` pra entries — determinismo |

## Gates Explícitos

- **Zero CORE tocado**: `core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py` inalterados. Scaling hack em CALLER side.
- **Zero shadow tocado**: `tools/maintenance/millennium_shadow.py` permanece exato — só `_compute_trade_metrics` extraído pra helper shared se/quando paper reusar.
- **Suite verde**: merge exige 1266+ passes.
- **Deploy reversível**: `systemctl stop millennium_paper.service` encerra; nenhuma mutação persistente em config/exchanges/keys.
