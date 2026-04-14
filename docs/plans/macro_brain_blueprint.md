# AURUM Macro Brain — Blueprint

**Status:** Fase 1 scaffolding em andamento
**Owner:** Joao
**Última atualização:** 2026-04-14

---

## Missão

Camada autônoma de investidor macro-fundamentalista, horizonte semanas/meses, baseada em ML. **Independente** das trade engines existentes — P&L, lógica e decisão separados. Expansível para forex/equities depois do MVP crypto.

## Arquitetura pirâmide

```
┌──────────────────────────────────────────────────────────────┐
│  CAMADA 1  ·  MACRO BRAIN (NOVO)                             │
│  Investidor macro, horizonte semanas/meses, P&L próprio      │
│  Decisão: regime macro + teses ML + sizing por convicção     │
└──────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────┐
│  CAMADA 2  ·  TRADE ENGINES (EXISTENTE, NÃO TOCADO)          │
│  CITADEL · BRIDGEWATER · JUMP · DE SHAW · RENAISSANCE        │
│  Quant de curto prazo (minutos-dias), P&L próprio            │
└──────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────┐
│  CAMADA 3  ·  INFRAESTRUTURA COMPARTILHADA (READ-ONLY)       │
│  core.exchange_api · audit_trail · risk_gates · connections  │
└──────────────────────────────────────────────────────────────┘
```

**Regra crítica:** Macro Brain NÃO modifica código das trade engines. Usa infraestrutura compartilhada (ordens, audit, conexões) via interfaces existentes. Account/book separado, tag `source="macro_brain"` em todas as ordens.

---

## Estrutura de pastas

```
aurum.finance/
├── macro_brain/                    ← NOVO namespace isolado
│   ├── __init__.py
│   ├── brain.py                    orquestrador + scheduler (TBD)
│   ├── data_ingestion/
│   │   ├── base.py                 Collector ABC ✓
│   │   ├── monetary.py             FRED ✓
│   │   ├── news.py                 NewsAPI + GDELT (TBD)
│   │   ├── sentiment.py            Fear&Greed (TBD)
│   │   └── commodities.py          CoinGecko (TBD)
│   ├── ml_engine/
│   │   ├── features.py             (TBD)
│   │   ├── regime.py               rule-based classifier (TBD)
│   │   └── scoring.py              per-asset scoring (TBD)
│   ├── thesis/
│   │   ├── generator.py            (TBD)
│   │   ├── templates.py            (TBD)
│   │   └── validator.py            (TBD)
│   ├── position/
│   │   ├── manager.py              (TBD)
│   │   ├── sizing.py               (TBD)
│   │   └── pnl_ledger.py           (TBD)
│   ├── persistence/
│   │   └── store.py                SQLite CRUD ✓
│   └── dashboard_view.py           launcher tab (TBD)
│
├── config/
│   └── macro_params.py             ✓
│
├── data/macro/                     ✓
│   ├── macro_brain.db              ✓ (empty schema initialized)
│   ├── raw/                        dumps JSON por fonte
│   └── models/                     artefatos ML
│
└── docs/
    ├── plans/macro_brain_blueprint.md   (este doc)
    └── macro/                      methodology, whitepapers
```

---

## Módulos e responsabilidades

| Módulo | Responsabilidade | Status |
|---|---|---|
| `brain.py` | Scheduler async, coordena fases do pipeline | TBD |
| `data_ingestion/base.py` | `Collector` ABC + `.run()` pipeline fetch→persist | ✓ |
| `data_ingestion/monetary.py` | FRED API (rates, CPI, yields, DXY, VIX, WTI, GOLD) | ✓ |
| `data_ingestion/news.py` | NewsAPI + GDELT events | TBD |
| `data_ingestion/sentiment.py` | Crypto Fear&Greed Index | TBD |
| `data_ingestion/commodities.py` | CoinGecko prices + market cap + dominance | TBD |
| `ml_engine/features.py` | z-scores, YoY, sentiment EMAs, rolling stats | TBD |
| `ml_engine/regime.py` | Rule-based classifier → `RegimeSnapshot` | TBD |
| `ml_engine/scoring.py` | Per-asset direcional score | TBD |
| `thesis/generator.py` | Regime + scores → theses com rationale | TBD |
| `thesis/templates.py` | Templates hardcoded de teses | TBD |
| `thesis/validator.py` | Rejeita teses que quebram constraints | TBD |
| `position/sizing.py` | Convicção × regime_scale × exposure cap | TBD |
| `position/manager.py` | Lifecycle: open, monitor, close-on-invalidation | TBD |
| `position/pnl_ledger.py` | Log P&L separado em `pnl_ledger` table | TBD |
| `persistence/store.py` | SQLite CRUD layer | ✓ |
| `dashboard_view.py` | tk panel pra launcher | TBD |

---

## Data sources (MVP)

Free/freemium prioritário — expande só depois de validar edge.

| Fonte | Categoria | Rate limit | Auth | Status |
|---|---|---|---|---|
| **FRED** | monetary + macro | ilimitado | free key | ✓ wired |
| **NewsAPI** | news | 500 req/dia free | free key | TBD |
| **GDELT** | news geopolitics | bulk free | — | TBD |
| **Fear & Greed** | sentiment | ilimitado | — | TBD |
| **CoinGecko** | commodities crypto | 10-30/min | free | TBD |
| **CFTC COT** | positioning | semanal free | — | Fase 2 |

Paid (Fase 3 se validar): Bloomberg, LSEG, S&P.

---

## Schemas de dados (SQLite)

**DB:** `data/macro/macro_brain.db` — isolado de `data/aurum.db`

### `events`
news, geopolitics, sentiment qualitativo
```
id, ts, ingested_ts, source, category, headline, body, entities,
sentiment (-1 a +1), impact (0-1), raw_json
```

### `macro_data`
FRED-style time-series numéricos
```
id, ts, metric, value, prev, expected, surprise, source
UNIQUE(ts, metric, source)  -- dedupe
```

### `regime_snapshots`
history do classificador de regime
```
id, ts, regime (risk_on|risk_off|transition|uncertainty),
confidence (0-1), features_json, model_version, reason
```

### `theses`
teses geradas + lifecycle
```
id, created_ts, regime_id, direction, asset, confidence,
rationale, supporting_events, target_horizon_days,
invalidation_json, status, closed_ts, close_reason
```

### `positions`
book separado do trade engine
```
id, thesis_id, asset, side, size_usd, leverage, entry_ts,
entry_price, exit_ts, exit_price, pnl_realized, pnl_unrealized, status
```

### `pnl_ledger`
append-only P&L events
```
id, ts, event_type, position_id, asset, pnl_delta, account_equity
```

---

## Pipeline completo

```
SCHEDULER (brain.py)
  ├─ news ingest:    every 15min
  ├─ macro ingest:   daily (calendar-driven)
  ├─ regime calc:    every 4h
  ├─ thesis gen:     daily + on high-impact event
  └─ position review: hourly

  │
  ▼
DATA INGESTION (Collector.run())
  fetch → normalize → dedupe → SQLite + raw JSON dump
  │
  ▼
FEATURE BUILDER (ml_engine/features.py)
  Rolling z-scores, YoY, EMAs, event counts
  │
  ▼
REGIME CLASSIFIER (ml_engine/regime.py)
  MVP: rule-based decision tree
  → RegimeSnapshot(regime, confidence, features, reason)
  │
  ▼
SIGNAL SCORING (ml_engine/scoring.py)
  Per-asset score combinando regime bias + sensibilidades específicas
  → {BTCUSDT: +0.6, ETHUSDT: -0.3, ...}
  │
  ▼
THESIS GENERATOR (thesis/generator.py)
  Matches templates → theses com rationale + invalidation
  Validator rejeita se conf<MIN, correlação, exposure cap
  │
  ▼
POSITION MANAGER (position/manager.py)
  sizing → risk_gates check → audit_trail log →
  exchange_api submit (tag source="macro_brain")
  Hourly review: check invalidation, close se premise quebrou
```

**Frequency:**
- News: 15min (rate-limit budget)
- Regime: 4h (macro é lento, não precisa de tick-by-tick)
- Thesis: diário + event-driven
- Position review: horário

---

## Contratos / interfaces

```python
# Collector ABC
class Collector(ABC):
    name: str
    category: str
    def fetch(since: datetime | None) -> Iterable[dict]: ...
    def run(since) -> dict: ...  # {inserted, skipped, errors}

# Regime
@dataclass
class RegimeSnapshot:
    ts: datetime
    regime: Literal["risk_on","risk_off","transition","uncertainty"]
    confidence: float  # 0-1
    features: dict
    reason: str

# Thesis
@dataclass
class Thesis:
    id: str
    direction: Literal["long","short"]
    asset: str
    confidence: float
    rationale: str
    horizon_days: int
    invalidation: list[dict]
```

---

## Sizing + risco

### Formula de sizing
```
size_usd = MACRO_ACCOUNT_SIZE
         × BASE_RISK_PER_THESIS (1%)
         × (0.5 + confidence × MAX_CONFIDENCE_MULT)   # 0.5-2.5x
         × regime_alignment (1.0 se alinha, 0.5 se transição)
capped at MAX_SINGLE_POSITION (10%)
```

### Risk rules (config/macro_params.py)
| Rule | Valor | Por quê |
|---|---|---|
| `MACRO_MAX_CONCURRENT_THESES` | 5 | diversificação sem dispersão |
| `MACRO_MAX_GROSS_EXPOSURE` | 50% | conservador p/ macro |
| `MACRO_MAX_SINGLE_POSITION` | 10% | concentration cap |
| `MACRO_MAX_CORRELATED_THESES` | 2 | evita dupla exposure |
| `MACRO_DRAWDOWN_KILL_SWITCH` | 15% | pausa novas em -15% |
| `MACRO_TIME_STOP_DAYS` | 90 | fecha tese parada |
| `MACRO_MIN_THESIS_CONFIDENCE` | 0.55 | threshold p/ aprovar |

**Diferença crítica vs trade engines:** stops são *fundamentais* (invalidation da premise), não técnicos. Fecha independente do P&L se premise quebrar.

---

## Integração sem tocar engines

### Não modifica
- `engines/*.py` — zero changes
- `core/portfolio.py::position_size` — continua dos trade engines
- `config/params.py` — macro tem `config/macro_params.py`
- Backtest pipeline — intocado

### Usa read-only
- `core.exchange_api.submit_order(..., tag="macro_brain")` — ordens
- `core.audit_trail.log_intent()` — auditoria imutável
- `core.risk_gates.check(book="macro")` — checks L0
- `core.connections` — connection pool
- `core.key_store` — credenciais

### Adiciona
- `config/macro_params.py` (novo)
- `macro_brain/` namespace completo
- `data/macro/` dir (SQLite + raw + models)
- Tabelas novas em `macro_brain.db` (DB separado)

---

## Dashboard (launcher tab)

Adicionar **"MACRO BRAIN"** na main menu do launcher:

```
> MACRO BRAIN                           [LIVE]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CURRENT REGIME
  risk_off   confidence 72%
  [████████████░░░░]
  Since: 2026-04-12 · Duration: 2d 4h
  Reason: DXY spike +2σ, VIX >25

ACTIVE THESES (3)
  SHORT BTCUSDT  conf 68%  12d old  OK
  SHORT ETHUSDT  conf 55%  5d old   OK
  LONG  GOLD     conf 80%  8d old   OK

P&L (MACRO BOOK)
  Today: +$124   7d: +$892   MTD: +$2,340
  Equity: $12,340   DD: -3.1%

NEWS FEED (24h, impact-filtered)
  ...

DATA HEALTH
  FRED ✓ 2min   NewsAPI ✓ 14min   CoinGecko ✓ 1h
```

`macro_brain/dashboard_view.py::render(parent_frame)` → launcher chama.

---

## MVP (Fase 1) vs futuro

### MVP Fase 1
| Componente | Escopo MVP |
|---|---|
| Sources | FRED + NewsAPI + Fear&Greed + CoinGecko (4) |
| Features | z-scores, YoY, sentiment EMA (15) |
| Regime | **Rule-based** (não ML ainda) |
| Scoring | 3-4 regras simples |
| Thesis | 3-5 templates hardcoded |
| Position | **Paper only**, 1% risk, max 3 concurrent |
| Dashboard | read-only tab |

### Fase 2 (1-2 meses depois)
- Regime via logistic regression
- News sentiment via BERT/GPT-4
- +COT, ECB, commodities granulares
- Thesis invalidation automática
- Telegram alerts
- Live trading

### Fase 3 (3+ meses)
- LLM thesis generation (GPT-4 rationale)
- Multi-asset cross-correlation
- Forex/equities
- Bayesian portfolio optimization

---

## Riscos, limitações, trade-offs

### Riscos
1. Free tier rate limits (NewsAPI 500/dia)
2. Data latency (GDELT 15min lag — news pode já estar no preço)
3. Overfit ao último regime (crypto ~10 anos, poucos ciclos)
4. LLM hallucination (Fase 3)
5. Paper→live slippage em positions grandes

### Limitações
- Macro é lento: expect 2-10 teses/mês
- Crypto 24/7 mas macro data 9-5 NY
- Sem ground-truth de "regime" (labels sempre ex-post)

### Trade-offs
| Decisão | Escolhido | Alternativa | Por quê |
|---|---|---|---|
| DB | SQLite | Postgres | Zero setup, migration depois |
| Regime MVP | Rule-based | ML direto | Interpretável, debugável |
| Account | Separado | Shared | P&L cleaner |
| News primária | FRED+GDELT+NewsAPI | Bloomberg | $0 vs $$$$ |

---

## Ordem de implementação

**Semana 1 — Foundation** (✓ completa)
- [x] `macro_brain/` folder + `config/macro_params.py`
- [x] SQLite schema + `persistence/store.py`
- [x] `data_ingestion/base.py::Collector` ABC
- [x] 1 collector end-to-end: `monetary.py::FREDCollector`
- [x] Smoke test DB init

**Semana 1-2 — Ingestion completa**
- [ ] `news.py::NewsAPICollector` + `GDELTCollector`
- [ ] `sentiment.py::FearGreedCollector`
- [ ] `commodities.py::CoinGeckoCollector`
- [ ] `brain.py` scheduler (asyncio)
- [ ] Health monitoring

**Semana 2 — Features + Regime**
- [ ] `ml_engine/features.py`
- [ ] `ml_engine/regime.py` rule-based v1
- [ ] Regime history persistence

**Semana 2-3 — Thesis + Position**
- [ ] `thesis/templates.py` (3-5)
- [ ] `thesis/generator.py` + `validator.py`
- [ ] `position/sizing.py` + `manager.py` (paper)
- [ ] `pnl_ledger.py`

**Semana 3 — Dashboard**
- [ ] `dashboard_view.py`
- [ ] Launcher SUB_MENUS hook
- [ ] UI polling

**Semana 4 — Polish**
- [ ] Telegram alerts
- [ ] Audit trail integration
- [ ] Runbook docs

**Fase 2+** (após MVP validado)
- [ ] ML regime classifier
- [ ] GPT-4 rationale
- [ ] Live mode
