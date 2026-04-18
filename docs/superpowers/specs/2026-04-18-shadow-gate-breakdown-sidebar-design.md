# Shadow Enriched Detail + Sidebar Institucional — Fase 2a+2b Design

**Data:** 2026-04-18 (revisto após leitura do código em 2026-04-18 PM)
**Branch de trabalho:** `feat/phi-engine` (ou nova `feat/shadow-sidebar`)
**Autor:** Claude (Opus 4.7), discussão com João
**Status:** Revisto — aguarda review do João antes de gerar plano.
**Pré-requisitos:** Fase 1a (cockpit API read-only) e Fase 1b (auto-tunnel + last signals) já entregues.

---

## Contexto

O MILLENNIUM shadow roda no VPS (`vmi3200601`) desde 2026-04-18 02:29 UTC.
O launcher Windows lê heartbeat + últimos 10 trades via SSH tunnel →
cockpit API FastAPI → disco. Painel SHADOW mostra ticks_ok, novel_total,
uptime, e tabela com `timestamp/symbol/direction/entry`.

**Descoberta durante análise (2026-04-18 PM):**

O `shadow_trades.jsonl` já contém **trades pós-filtro com outcome conhecido**.
Sample real (1 linha):

```json
{
  "symbol": "ARBUSDT", "timestamp": "2026-01-20 04:45:00",
  "strategy": "CITADEL", "direction": "BEARISH",
  "entry": 0.19304, "stop": 0.19490, "target": 0.18740, "exit_p": 0.19036,
  "rr": 3.0, "duration": 5, "result": "WIN", "exit_reason": "trailing",
  "pnl": 68.45, "size": 27633.13, "score": 0.5363, "r_multiple": 1.445,
  "macro_bias": "BEAR", "vol_regime": "NORMAL", "struct": "DOWN",
  "struct_str": 0.75, "cascade_n": 1, "taker_ma": 0.468, "rsi": 49.33,
  "omega_struct": 0.75, "omega_flow": 0.858, "omega_cascade": 0.25,
  "omega_momentum": 0.667, "omega_pullback": 0.933,
  "chop_trade": false, "dd_scale": 1.0, "corr_mult": 1.0,
  "hmm_regime": null, ...
}
```

**Conclusão:** a data rica existe. O problema é puramente de apresentação:
o launcher renderiza só 4 das ~30 colunas. A pergunta do João ("quero
saber se entra trade") se resolve mostrando **mais colunas da tabela**,
não criando stream novo.

**Implicação no escopo original:**

| Original | Revisto |
|----------|---------|
| Criar `GateOutcome` model | ❌ Removido — não há stream de "signal rejected" |
| `would_enter` + `filter_reason` | ❌ Removido — todos trades no jsonl teriam entrado |
| Hook em `millennium_shadow.py` | ❌ Removido — runner não muda |
| Gate breakdown per signal | ❌ Removido — gates são internos ao backtest |
| Sidebar institucional multi-engine | ✅ Mantido |
| Tabela LAST SIGNALS enriquecida | ✅ Expandido (mais colunas) |
| Row click → detail completo | ✅ Novo — popup com todos omega + struct |

**Objetivo Fase 2a+2b revisto:** surface toda a info que já existe
no trade record, num layout institucional multi-engine. Zero backend.

**Não-objetivo:**
- Stream de sinais pre-filter (exigiria instrumentar `engines/millennium.py`)
- Detecção de "quase-entrou" (inexistente no código atual)
- Editor de VPS settings / remote start-stop / asset basket (Fases 3a-3d)
- Alterar `core/*` protegido ou `config/params.py`

---

## Arquitetura

```
┌─ VPS (vmi3200601) ────────────────────────────────────────┐
│  tools/maintenance/millennium_shadow.py   (INALTERADO)     │
│  tools/cockpit_api.py                     (INALTERADO)     │
│                                                            │
│  Trade records já têm size/stop/target/rr/result/pnl/      │
│  regime/omega_* — só precisam ser transportados.           │
└─────────────┬──────────────────────────────────────────────┘
              │ SSH tunnel (launcher-managed)
              │ localhost:8787
┌─────────────┴──────────────────────────────────────────────┐
│  Launcher (Windows)                                         │
│                                                             │
│  core/shadow_contract.py                 (MINIMAL EXTEND)   │
│    └─ TradeRecord ganha campos opcionais pros dados que     │
│       já existem no disk (stop, target, rr, result, pnl,    │
│       size, score, macro_bias, vol_regime, omega_*, etc).   │
│       extra='allow' já funciona, mas tipagem explícita      │
│       ajuda o cockpit_client e os tests.                    │
│                                                             │
│  launcher_support/cockpit_client.py      (INALTERADO)       │
│  launcher_support/shadow_poller.py       (INALTERADO)       │
│                                                             │
│  launcher_support/engines_sidebar.py     (NOVO)             │
│    ├─ render_sidebar(parent, engines, selected, on_select)  │
│    └─ render_detail(parent, run_ctx)                        │
│       ├─ health_section(heartbeat)                          │
│       ├─ run_info_section(manifest)                         │
│       ├─ signals_table(trades)   ← colunas expandidas       │
│       └─ actions_row(run_id)                                │
│                                                             │
│  launcher_support/signal_detail_popup.py (NOVO)             │
│    └─ show(trade_record) — TkToplevel modal com             │
│       todas as omega scores + struct + cascade + regime     │
│                                                             │
│  launcher_support/engines_live_view.py   (REFATORADO)       │
│    └─ _render_detail_shadow delega pra engines_sidebar      │
│    └─ Mesmo sidebar aplicado aos modos paper/demo/testnet/  │
│       live (source muda: _PROCS_CACHE em vez de shadow      │
│       poller, mas component é o mesmo)                      │
└─────────────────────────────────────────────────────────────┘
```

**Decisões chave:**

- **Backend zero.** `millennium_shadow.py`, `cockpit_api.py`, engines
  e `config/params.py` ficam intactos. Sem CORE tocado.
- **Contrato estende, não redefine.** Todos campos novos em
  `TradeRecord` são `Optional`, default `None`. Legacy records
  deserializam sem erro. `extra='allow'` vira redundante mas
  tipagem explícita documenta o que o UI espera.
- **Sidebar é componente reutilizável.** O MESMO sidebar renderiza
  tanto modo SHADOW (dados do VPS via poller) quanto paper/demo/
  testnet/live (dados locais via `_PROCS_CACHE`). Source data difere,
  component layer é único.
- **Row click → popup em vez de inline expand.** Popup TkToplevel
  mantém a tabela densa (institucional) e evita re-layout do painel
  quando user quer drill-down. Click outra row = popup refresh.

---

## Contrato de dados — `core/shadow_contract.py`

### `TradeRecord` — extend com campos opcionais

Só tipagem. Nenhum campo obrigatório novo. Valores vêm do disco.

```python
class TradeRecord(BaseModel):
    # Campos existentes (inalterados)
    timestamp: datetime
    symbol: str
    strategy: str
    direction: str
    entry: float | None = None
    exit: float | None = None
    pnl: float | None = None
    shadow_observed_at: datetime | None = None

    # NOVOS — todos opcionais, refletem o shape do shadow_trades.jsonl atual
    stop: float | None = None
    target: float | None = None
    exit_p: float | None = None            # preço real de saída
    rr: float | None = None                # risk:reward ratio planejado
    duration: int | None = None            # candles até saída
    result: Literal["WIN", "LOSS"] | None = None
    exit_reason: str | None = None         # "trailing", "stop_initial", "target", ...
    size: float | None = None              # notional USD
    score: float | None = None             # engine-specific entry score
    r_multiple: float | None = None        # pnl / risk_inicial

    # Regime context at entry
    macro_bias: Literal["BULL", "BEAR", "CHOP"] | None = None
    vol_regime: Literal["LOW", "NORMAL", "HIGH"] | None = None

    # Omega breakdown (5D fractal — nem sempre presente; ex: JUMP não emite todos)
    omega_struct: float | None = None
    omega_flow: float | None = None
    omega_cascade: float | None = None
    omega_momentum: float | None = None
    omega_pullback: float | None = None

    # Structural context (optional; surface in popup if present)
    struct: str | None = None              # "UP" | "DOWN" | ...
    struct_str: float | None = None        # strength 0-1
    rsi: float | None = None
    dist_ema21: float | None = None
    chop_trade: bool | None = None

    # Scaling / risk multipliers (transparência)
    dd_scale: float | None = None
    corr_mult: float | None = None

    # HMM regime (raramente presente — opcional)
    hmm_regime: str | None = None
    hmm_confidence: float | None = None

    # Shadow-specific provenance (já existe)
    shadow_run_id: str | None = None

    model_config = ConfigDict(extra="allow")
```

### Invariantes

| Invariante | Regra |
|-----------|-------|
| Retrocompat | Record legacy (só campos antigos) deserializa OK — defaults kickam in |
| Extra fields | `extra='allow'` preservado — runner pode evoluir shape sem quebrar client |
| Ordem semântica | Campos agrupados por tema (entry/exit, regime, omega, struct) pra leitura |

---

## Runner e Cockpit API

**Zero mudanças.** Runner emite dicts com 30+ campos via `_append_trade`.
Cockpit API serializa via pydantic com `extra='allow'`. Já funciona.

---

## Launcher UI

### Novo componente — `launcher_support/engines_sidebar.py`

```python
"""Sidebar institucional + detail renderer reusável.

Consumido por engines_live_view.py pra renderizar cockpit master-detail
em todos os modos (shadow, paper, demo, testnet, live).

Source data varia por modo (ShadowPoller cache pro shadow, _PROCS_CACHE
pros locais), mas o component layer é único — garante consistência
visual e DRY.
"""
from __future__ import annotations
import tkinter as tk
from typing import Callable

from core.shadow_contract import Heartbeat, Manifest, TradeRecord
from core.ui_palette import (
    AMBER_B, BG, BORDER, DIM, DIM2, GREEN, RED, WHITE, PANEL, FONT,
)

# SIDEBAR_WIDTH é fixa — aproximação de 180px em FONT monospace
SIDEBAR_WIDTH = 24  # char width


class EngineRow:
    def __init__(self, slug: str, display: str, active: bool,
                 ticks: int | None, signals: int | None):
        self.slug = slug
        self.display = display       # "MILLENNIUM"
        self.active = active         # tem run vivo?
        self.ticks = ticks           # ticks_ok do heartbeat
        self.signals = signals       # novel_total do heartbeat


def render_sidebar(
    parent: tk.Widget,
    engines: list[EngineRow],
    selected_slug: str | None,
    on_select: Callable[[str], None],
) -> tk.Frame:
    """Lista de engines fixa à esquerda. Return frame parent."""
    ...


def render_detail(
    parent: tk.Widget,
    engine: str,
    mode: str,
    heartbeat: Heartbeat | None,
    manifest: Manifest | None,
    trades: list[TradeRecord],
    on_row_click: Callable[[TradeRecord], None],
) -> tk.Frame:
    """Detail pane flex. 4 seções."""
    ...
```

### Layout

```
┌─ ENGINES LIVE — mode: [SHADOW] paper demo testnet live ──────────────────┐
│                                                                           │
│ ┌─ ENGINES ──────┐ ┌─ MILLENNIUM · shadow · [REMOTE] ──────────────────┐ │
│ │ ▸ MILLENNIUM   │ │ HEALTH                                             │ │
│ │   ✓ 41t · 625s │ │   ticks_ok  41         uptime  12h 4m              │ │
│ │ ○ CITADEL      │ │   ticks_fail 0         novel   625                 │ │
│ │   —            │ │                                                     │ │
│ │ ○ JUMP         │ │ RUN INFO                                           │ │
│ │   —            │ │   run_id  2026-04-18_0229   commit  9c1b877        │ │
│ │ ○ RENAISSANCE  │ │   started 02:29 UTC         branch  feat/phi-engine│ │
│ │   —            │ │                                                     │ │
│ │ ○ BRIDGEWATER  │ │ LAST SIGNALS (click row for detail)                │ │
│ │   —            │ │   time  sym   dir  entry    stop    rr  size  res  │ │
│ │ ○ DE_SHAW      │ │   19:02 BTC   L    65432.0  65120   3.0 $285  WIN  │ │
│ │   —            │ │   18:47 ETH   S    3210.5   3228.1  3.0 $147  WIN  │ │
│ │ ○ JANE_STREET  │ │   18:45 LINK  L    14.23    14.02   3.0 $94   LOSS │ │
│ │   —            │ │   18:30 SOL   L    142.8    140.1   3.0 $156  WIN  │ │
│ │                │ │   ...                                               │ │
│ │                │ │                                                     │ │
│ │                │ │ ACTIONS  [REFRESH]  [VIEW LOGS]  [KILL]            │ │
│ └────────────────┘ └─────────────────────────────────────────────────────┘ │
│                                                                           │
│ hints: ↑↓ select · ENTER expand · M cycle mode · ESC main                │
└───────────────────────────────────────────────────────────────────────────┘
```

### Tabela LAST SIGNALS — colunas

| Col | Field | Format | Width |
|-----|-------|--------|-------|
| time | `timestamp` | `%H:%M` | 6 |
| sym | `symbol` | truncate 4 chars + pad | 5 |
| dir | `direction` | `L` for BULLISH/LONG, `S` for BEARISH/SHORT | 3 |
| entry | `entry` | `%.4g` (4 sig figs) | 9 |
| stop | `stop` | `%.4g` | 9 |
| rr | `rr` | `%.1f` | 4 |
| size | `size` | `$%.0f` | 7 |
| res | `result` | `WIN` em GREEN, `LOSS` em RED, `—` em DIM se None | 5 |

Linhas clicáveis. Click → `show_signal_detail_popup(trade_record)`.

### Novo componente — `launcher_support/signal_detail_popup.py`

Popup TkToplevel modal sobre o launcher. Seções:

```
┌─ TRADE DETAIL — BTCUSDT · LONG · 19:02 ──────────────┐
│                                                        │
│ OUTCOME                                               │
│   result    WIN          exit_reason  trailing        │
│   pnl       +$285.40     exit_price   66210           │
│   r_multiple 1.44        duration     5 candles       │
│                                                        │
│ ENTRY                                                  │
│   entry  65432.0    stop  65120   target  66950       │
│   rr     3.0        size  $285    score   0.54        │
│                                                        │
│ REGIME                                                 │
│   macro_bias  BULL     vol_regime  NORMAL             │
│   hmm_regime  —        chop_trade  false              │
│   dd_scale    1.00     corr_mult   1.00               │
│                                                        │
│ OMEGA 5D                                              │
│   struct    0.75   ████████░░                         │
│   flow      0.86   █████████░                         │
│   cascade   0.25   ███░░░░░░░                         │
│   momentum  0.67   ███████░░░                         │
│   pullback  0.93   █████████▉                         │
│                                                        │
│ STRUCTURE                                              │
│   struct  DOWN     struct_str  0.75                   │
│   rsi     49.3     dist_ema21  0.10   cascade_n  1    │
│                                                        │
│                                           [ESC close] │
└────────────────────────────────────────────────────────┘
```

Omega bars são chars unicode (`█▉░`), monospace-aligned, compat
TkInter. Sem libs de chart.

Rules:
- Campos com valor `None` no record: renderiza `—` em DIM
- Popup fecha com ESC, click fora, ou botão X
- Non-modal: próximo click em outra row refreshe o mesmo popup

### Paleta

Reutiliza `core/ui_palette.py` — zero cor nova:
- `AMBER_B` — highlight selected row/engine
- `GREEN` — `WIN` / omega >= 0.66
- `RED` — `LOSS` / omega < 0.33
- `DIM` / `DIM2` — valores None, campos inativos
- `PANEL` + `BORDER` — backgrounds

### Refactor em `engines_live_view.py`

- `_render_detail_shadow` delega pra `engines_sidebar.render_detail`
- Modos paper/demo/testnet/live: `_render_live_panel` usa mesmo
  sidebar + detail; source é `_PROCS_CACHE` em vez de poller
- Antigo layout full-width preservado como fallback (comment-tagged
  `# TODO remove após 2b stable` — deletar em PR de follow-up)

---

## Testing

### Suite atual
Baseline: `1223 passed, 7 skipped`
Meta pós-feature: `≥1235 passed` (≥12 tests novos)

### Arquivos de teste

| Arquivo | Novo/Extend | Cenários |
|---------|-------------|----------|
| `tests/test_shadow_contract.py` | extend | `TradeRecord` com novos campos; legacy sem; extra fields passam; `result` Literal valida; defaults None funcionam |
| `tests/test_engines_sidebar.py` | NOVO | `EngineRow` construction; `render_sidebar` lista todas engines do registry (não só ativas); selected highlight AMBER_B; engine inactive mostra `—` DIM2; `render_detail` renderiza 4 seções; signals table renderiza N rows com colunas corretas |
| `tests/test_signal_detail_popup.py` | NOVO | `show()` cria Toplevel com 5 seções; campos None renderizam `—`; omega bars corretos pra 0.0 / 0.5 / 1.0; ESC fecha; refresh com outro trade atualiza |
| `tests/test_engines_live_view_cockpit.py` | extend | Sidebar aparece em modo SHADOW; mesma sidebar aparece em modo paper (source diferente, componente igual); row click dispara `signal_detail_popup.show` |

### Smoke manual (pós-deploy)

1. `python launcher.py` → EXECUTE → ENGINES LIVE
2. Sidebar à esquerda com 9 engines (MILLENNIUM, CITADEL, JUMP,
   RENAISSANCE, BRIDGEWATER, DE_SHAW, JANE_STREET, TWO_SIGMA, AQR)
3. Engine inactive (sem run) = texto DIM2 + `—`
4. MILLENNIUM selecionado, detail populado com LAST SIGNALS rica
5. Click em uma row → popup aparece com 5 seções, omega bars
6. ESC fecha popup
7. `M` cycla pra paper mode → mesma sidebar, detail muda pra data local

### Regression

- `git diff feat/phi-engine -- core/indicators.py core/signals.py core/portfolio.py core/risk/portfolio.py config/params.py`
  deve retornar vazio. Verificado em step do plano.
- `tools/maintenance/millennium_shadow.py` também **NÃO** toca
  (apesar de não protegido, mudança arriscada pra runner que já tá
  rodando no VPS).

---

## Rollout

### Ordem implementação

1. **Contrato (shadow_contract.py)** — extend TradeRecord + tests
2. **engines_sidebar.py** — render_sidebar + render_detail + tests
3. **signal_detail_popup.py** — popup + tests
4. **Refactor engines_live_view.py** — use novos componentes no modo SHADOW
5. **Aplicar sidebar aos outros modos** (paper/demo/testnet/live)
6. **Smoke manual** + commit

### Deploy sequence

1. Merge branch → `feat/phi-engine` → push
2. VPS: **nenhuma ação** (zero backend)
3. Launcher local: reabrir pra pegar código novo
4. Observa UX 5min — tabela rica, row click, popup, modo cycle

### Rollback

- Se componente novo bugar, reverter em launcher fica trivial:
  `_render_detail_shadow` antigo ainda existe na função (só deprecated)
- Zero risco no runner ou cockpit — não tocados

---

## Backlog pós-Fase 2

Rastreado no session log final:

1. **Fase 3a — VPS settings UI** (host/port/tokens dentro do launcher)
2. **Fase 3b — Remote start/stop** (POST admin API)
3. **Fase 3c — Asset basket editor**
4. **Fase 3d — Multi-engine orchestrator** (N runners simultâneos no VPS)
5. **Fase 3e — VPN/tunnel hardening** (opcional)
6. Signal detail popup: chart de mini-candles se render leve o permitir
7. LAST SIGNALS column sort/filter
8. Se quiser stream de pre-filter signals no futuro: exigiria
   instrumentar `engines/millennium.py` e upstream — novo spec
9. Deletar fallback antigo em `engines_live_view.py` após 2b stable

---

## Regras seguidas

- ✅ Zero linha em `core/indicators.py`, `core/signals.py`,
  `core/risk/portfolio.py`, `config/params.py` (CORE protegido — CLAUDE.md)
- ✅ Zero linha em `tools/maintenance/millennium_shadow.py` e
  `tools/cockpit_api.py` (runner + API rodando no VPS — evita regressão)
- ✅ Anti-overfit: não aplicável (observability, não é tune)
- ✅ YAGNI: componente `engines_sidebar` implementado mínimo;
  extras (sort/filter/chart) deferidos
- ✅ Single source of truth: um componente sidebar para todos modos
- ✅ Retrocompat: `TradeRecord` novos campos são Optional
- ✅ Testes caracterizam comportamento — zero "ajustar código pra teste passar"
