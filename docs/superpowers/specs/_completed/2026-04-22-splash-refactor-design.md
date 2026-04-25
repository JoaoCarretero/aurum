# Splash Refactor — Institutional Density

**Date:** 2026-04-22
**Author:** Joao + Claude
**Status:** Draft — awaiting user review
**Target file:** `launcher_support/screens/splash.py`
**Related previous spec:** `docs/superpowers/specs/2026-04-11-splash-halflife-institutional-design.md`

---

## 1. Motivação

O splash atual (pós-migração `launcher_support/screens/splash.py`) é um terminal institucional limpo: wordmark "OPERATOR DESK", painel único "SESSION OVERVIEW" com duas colunas (DESK / STATUS), prompt pulsante. Funciona, mas é estático — 1 painel, ~8 linhas de dado, zero pulse de mercado.

O pedido do Joao é tornar o splash **mais vivo, vibrante, instigante, profissional**. Após brainstorming, a direção escolhida foi **B — densidade institucional** (não mais animação, não mais decoração — mais dado real, estilo Bloomberg Terminal). Entre três approaches de layout, foi aprovado **Approach 2 — grid 2×3 de tiles**.

O resultado: splash vira um "heartbeat" do sistema antes mesmo do clique. Mostra que AURUM está vivo, saudável, e pronto — em 5 tiles de dado real (status, risk, market pulse, last session, engine roster).

Princípios que guiam o redesign:
- **Densidade > decoração** — cada pixel serve dado
- **Offline-first, live-second** — render em <150ms sem rede; async atualiza quando chega
- **Robusto a falhas** — nenhum cenário de erro bloqueia navegação
- **Core de trading intocado** — zero mudança em `core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py`

---

## 2. Filosofia

Bloomberg Terminal, mas em terminal monospace. Quando você abre o AURUM, a tela **já mostra que o sistema existe**: engine roster visível, último P&L conhecido, regime macro, conexões vivas. Você não está abrindo um launcher — você está **ocupando um posto de operador** que já está quente.

O splash não precisa gritar. Ele precisa ser **denso e certeiro**. Um profissional olha 1 segundo e sabe: sistema OK, sessão anterior foi +4.2R, BTC em BULL, kill-switch armado. Entra informado.

---

## 3. Arquitetura visual

### 3.1 Canvas 920×640 — layout top-down

```
y=0-30     breathing room
y=30       top rule (AMBER_D, x=48→872)
y=46       wordmark band "AURUM FINANCE" (fonte 7 bold, linhas âmbar nos lados)
y=72-140   logo aurum + "OPERATOR DESK" (fonte 18, WHITE) + "Quant operations console" (fonte 9, DIM2)
y=160      divider curto + tagline (fonte 8, DIM)
y=190      ── Row 1 tiles ──
y=190-340  [STATUS 264×150] [RISK 264×150] [MARKET PULSE 264×150]
y=356-506  [LAST SESSION 264×150] [ENGINE ROSTER 544×150]
y=530      separator rule (DIM2)
y=552      "[ ENTER TO ACCESS DESK ]_" prompt pulsante (AMBER_B, fonte 11 bold)
y=596      bottom rule (DIM2)
```

**Dimensões exatas dos tiles:**
- Content bounds: x=48 → x=872 (824 wide)
- Tile simples: 264w × 150h, gap 16
- Tile wide (ENGINE ROSTER): 544w (= 2 × 264 + 16) × 150h
- Padding interno: 14px

**Hierarquia tipográfica:**
- OPERATOR DESK: fonte 18 (reduzido de 22 — libera espaço pra tiles)
- Headers de tile: fonte 7 bold, AMBER, underline AMBER_D
- Labels KV: fonte 8, DIM
- Valores KV: fonte 8 bold, colored por estado

### 3.2 Anatomia de cada tile

```
┌─ STATUS ──────────────┐   ← header AMBER fonte 7 bold + linha AMBER_D
│                       │
│ MARKET    ● LIVE      │   ← label DIM / valor colorido
│ CONN    ● BINANCE     │      dot ● GREEN ok, ○ DIM offline
│ TG        ● ONLINE    │
│ API LAT      42ms     │
└───────────────────────┘   ← border BORDER 1px
```

Reusa `app._draw_panel(canvas, x1, y1, x2, y2, title=..., accent=AMBER, tag=...)` + `app._draw_kv_rows(...)`. Código novo = wrapper `_draw_splash_tile(canvas, x1, y1, x2, y2, title, rows)`.

### 3.3 Conteúdo dos 5 tiles

**Tile 1 — STATUS** (x=48..312)
- `MARKET ● LIVE` / `● OFFLINE` — de `conn.status_summary()`
- `CONN ● BINANCE` / `● OFFLINE` — de `keys.json` (binance demo/testnet/live)
- `TG ● ONLINE` / `● OFFLINE` — de `keys.json` (telegram bot_token)
- `API LAT 42ms` — medido live async (round-trip a `/trading/status` ou `exchange_api.ping`)

**Tile 2 — RISK** (x=328..592)
- `KILL-SW ARMED` — hardcoded RED (sempre armed; o kill-switch é sagrado)
- `DD VEL 0.3%` / `---` — de cockpit `/trading/status` (live)
- `AGG NOT 23%` / `---` — de cockpit `/trading/status` (live)
- `GATES 3/3 OK` / `---` — de cockpit `/trading/status` (live)

**Tile 3 — MARKET PULSE** (x=608..872)
- `BTC 67,240 +2.30% ▲` / `---` — de `core.data.market_data.MarketDataFetcher(["BTCUSDT", "ETHUSDT"]).fetch_all()` → `snapshot()["tickers"]["BTCUSDT"]`
- `ETH 3,180 +1.81% ▲` / `---` — mesmo fetcher
- `REG BULL · slope200+` / `---` — de klines 1d BTC + slope200 (simplificado; alternativa: omitir se requer fetch adicional e deixar só os 3 outros no tile)
- `FUND +0.012% /8h` / `---` — `funding_avg()` do mesmo `MarketDataFetcher`

**Tile 4 — LAST SESSION** (x=48..312)
- `2026-04-21 21:47` — timestamp do último run (offline, de `data/index.json`)
- `ENGINES 2` — count de engines no run
- `TRADES 7` — count de trades
- `PNL +4.2R` — GREEN se >0, RED se <0
- Fallback quando `data/index.json` missing: `NO SESSION DATA` em DIM

**Tile 5 — ENGINE ROSTER** (x=328..872, wide)
- Grid 2 colunas × 6 linhas = 12 slots; 11 engines preenchem, última célula vazia ou reservada
- Cada célula: `CITADEL ✅ 1.87` — nome (8 chars, left-align), status icon (✅/⚠️/🔴/🆕/🔧/⚪), Sharpe formatado `>5.2f` ou label curto ("AUDIT", "BUG", "NO_EDGE", "INSUF")
- Ordem (OOS audit 2026-04-17):
  - ✅ CITADEL, JUMP (2)
  - ⚠️ RENAISSANCE, BRIDGEWATER (2)
  - 🆕 PHI (1)
  - 🔧 ORNSTEIN (1)
  - ⚪ TWO_SIGMA, AQR (fora da bateria OOS) (2)
  - 🔴 DE_SHAW, KEPOS, MEDALLION (3)
  - Total: 11 engines; JANE_STREET, MILLENNIUM, WINTON, GRAHAM excluídos (arb/orchestrators/arquivado)
- Sharpe lê best-effort de `data/{engine}/latest/reports/*.json`; missing → mostra só label

### 3.4 Cores

Reusa paleta existente em `core.ui.ui_palette`: `AMBER`, `AMBER_B`, `AMBER_D`, `BG`, `BORDER`, `DIM`, `DIM2`, `FONT`, `GREEN`, `RED`, `WHITE`. **Sem cores novas.**

---

## 4. Data flow

### 4.1 Offline render (instantâneo, <100ms)

```
on_enter():
    1. _draw_wordmark(canvas)
    2. _read_offline_data() → dict com:
         - status: {market, conn, tg, api_lat="---"}
         - risk: {kill="ARMED", dd="---", agg="---", gates="---"}
         - pulse: cache load (se existe) ou {btc:"---", eth:"---", reg:"---", fund:"---"}
         - session: read_last_session() ou None
         - roster: read_engine_roster() [hardcoded labels + sharpe best-effort]
    3. _draw_offline_tiles(canvas, offline_data)
    4. _bind(canvas, "<Button-1>", _on_click)
    5. _pulse_tick() (prompt blink 500ms)
    6. _kick_async_fetch()
```

### 4.2 Async live update

```
_kick_async_fetch():
    self._cancel_event = threading.Event()
    thread = threading.Thread(target=self._fetch_live_worker, daemon=True)
    thread.start()

_fetch_live_worker():  # runs off UI thread
    for fetch in [_fetch_market_pulse, _fetch_cockpit_risk, _fetch_api_latency]:
        try:
            data = fetch(timeout=1.5)
        except Exception:
            continue
        if self._cancel_event.is_set():
            return
        self.container.after(0, lambda d=data: self._apply_live_data(d))

_apply_live_data(data):
    if self._cancel_event.is_set() or self.canvas is None:
        return
    for key, (text, color) in data.items():
        canvas.itemconfigure(f"tile-{key}-value", text=text, fill=color)
    if "pulse" in data:
        _save_splash_cache(data["pulse"])
```

Cada valor live tem tag única tipo `tile-btc-value`, `tile-dd-value`, etc. Update é in-place via `itemconfigure`.

### 4.3 Cleanup no on_exit

```
on_exit():
    if self._cancel_event:
        self._cancel_event.set()
    super().on_exit()  # cancela after_ids tracked (pulse tick)
```

A thread daemon morre sozinha quando o processo sai. Se usuário navega pra outra screen, o `cancel_event` evita que thread toque canvas destruído.

### 4.4 Cache local

`data/splash_cache.json` — escrito quando fetch async pulse completa com sucesso:
```json
{
  "btc": {"text": "67,240 +2.30% ▲", "color": "GREEN"},
  "eth": {"text": "3,180 +1.81% ▲", "color": "GREEN"},
  "reg": {"text": "BULL · slope200+", "color": "GREEN"},
  "fund": {"text": "+0.012% /8h", "color": "WHITE"},
  "ts": "2026-04-22T14:23:11"
}
```

Na próxima abertura, `_read_offline_data()` carrega cache e mostra com label `·cached` em DIM.

### 4.5 Falhas e fallbacks

| Falha | Comportamento |
|---|---|
| `keys.json` missing | STATUS tile: conn/tg = "OFFLINE" DIM |
| `data/index.json` missing ou malformed | LAST SESSION: "NO SESSION DATA" DIM |
| Cockpit unreachable | RISK live values ficam "---" |
| Exchange API down | MARKET PULSE fica "---" (ou cache) |
| Thread não retorna em 5s | Tudo fica como offline, splash ainda 100% operável |
| User clica ENTER antes do async | Splash fecha, thread checa cancel_event, não toca canvas |
| `data/splash_cache.json` corrompido | Parser retorna `{}`, render continua |
| Sharpe negativo (e.g., -0.32) | Format `>5.2f` garante alinhamento |

Nenhum cenário de erro bloqueia navegação ou crasha.

---

## 5. Reuso e código

### 5.1 O que reusa (zero mudança)

- `Screen` ABC (container, `_after`, `_bind`, `on_exit` tracking)
- `core.ui.ui_palette` (toda paleta)
- `app._draw_panel`, `app._draw_kv_rows`, `app._draw_aurum_logo`
- `app._apply_canvas_scale`
- `app._load_json` (lê keys.json)
- `app._splash_on_click`
- `app._bind_global_nav`
- `conn.status_summary()`
- `core.data.market_data.MarketDataFetcher` (bulk fetch de tickers + funding, já thread-safe, já com timeout 5s)
- `launcher_support.cockpit_client` (se configurado; fallback se missing)

### 5.2 O que sai (do splash atual)

- `_draw_session_overview` — substituído por grid de 5 tiles
- `_draw_overview_column_header` — substituído por header padrão de tile
- Constantes `_SESSION_PANEL_*`, `_SESSION_GUTTER`, `_SESSION_COLUMN_GAP`, `_SESSION_LABEL_VALUE_GAP`, `_SESSION_LINE_H` — substituídas por constantes de grid

### 5.3 O que entra (novo)

Em `launcher_support/screens/splash.py`:
- Constantes: `_TILE_W_SIMPLE`, `_TILE_W_WIDE`, `_TILE_H`, `_TILE_GAP`, `_ROW1_Y1`, `_ROW2_Y1`, `_PADDING`
- `_draw_splash_tile(canvas, x1, y1, x2, y2, title, rows_with_tags)` — wrapper que chama `_draw_panel` + `_draw_kv_rows` com tags individuais por valor
- `_read_offline_data()` — orquestra os 5 readers offline
- `_read_last_session()` — parsa `data/index.json`, retorna dict ou None
- `_read_engine_roster()` — merge hardcoded status + sharpe best-effort dos reports
- `_load_splash_cache()`, `_save_splash_cache(data)` — JSON local
- `_kick_async_fetch()`, `_fetch_live_worker()` — thread orchestration
- `_fetch_market_pulse()`, `_fetch_cockpit_risk()`, `_fetch_api_latency()` — network calls individuais com timeout
- `_apply_live_data(data)` — UI-thread callback que atualiza canvas via tags

Se `splash.py` passar de ~500 linhas, extrair readers/fetchers pra `launcher_support/screens/splash_data.py`.

### 5.4 State fields no `__init__`

- `self._cancel_event: threading.Event | None = None` — arm no `_kick_async_fetch`, set no `on_exit`

---

## 6. Testes & TDD

### 6.1 Unit (funções puras, sem GUI)

Arquivo novo: `tests/launcher/test_splash_data.py`

- `test_read_last_session_happy_path` — fixture `data/index.json` válido → tuple correto
- `test_read_last_session_missing_file` → None
- `test_read_last_session_malformed_json` → None, não crasha
- `test_read_engine_roster_with_sharpe_reports` — retorna (engine, status, sharpe)
- `test_read_engine_roster_no_reports` → só labels hardcoded, Sharpe = None
- `test_splash_cache_roundtrip`
- `test_splash_cache_load_missing_file` → {}
- `test_splash_cache_load_corrupt_json` → {}

### 6.2 GUI (tests/launcher/test_splash_screen.py, expandido)

**Mantém:**
- `test_splash_builds_canvas`
- `test_splash_header_labels_set_on_enter`
- `test_splash_pulse_timer_cancelled_on_exit`

**Reescreve (coordenadas mudaram):**
- `test_splash_draws_logo_panel_rows` → `test_splash_draws_five_tiles` — asserta `_draw_panel` chamado 5x com coords dos tiles novos

**Consolida** (eram duplicatas literais):
- `test_splash_intro_stays_above_session_panel` + `test_splash_hero_stays_above_session_panel` → 1 teste de invariante de layout

**Novos:**
- `test_splash_tiles_render_with_offline_data_only` — sem network stub, tiles renderizam com "---" sem crashar
- `test_splash_apply_live_data_updates_canvas_tags` — simula chegada de dado live, verifica `canvas.itemcget` retorna novo valor
- `test_splash_async_thread_cancelled_on_exit` — mock thread, `on_exit()`, verifica `cancel_event.is_set()`
- `test_splash_live_data_with_dead_cockpit_leaves_dashes` — mock cockpit raise ConnectionError → tile RISK stay "---"

### 6.3 Smoke

`smoke_test.py` já chama `call("_splash", app._splash)`. Adicionar `call("_splash→async→exit", ...)` que abre splash, dorme 100ms, chama exit, confirma zero after_ids pendentes.

### 6.4 Ordem TDD

1. Red → Green: cada reader puro (`_read_last_session`, `_read_engine_roster`, cache)
2. Red → Green: `_draw_splash_tile` wrapper
3. Red → Green: `_draw_offline_tiles` com coords
4. Red → Green: async thread + cancel
5. Refactor: se splash.py > 500 linhas, mover data pra `splash_data.py`
6. Smoke + pytest verde
7. Manual walkthrough

### 6.5 Verification antes de completar

- `python smoke_test.py --quiet` → 0 falhas
- `pytest tests/launcher/test_splash_screen.py tests/launcher/test_splash_data.py -v` → verde
- Manual: `python launcher.py` → splash renderiza → click leva a main menu → Q sai limpo
- `git diff --name-only` mostra só `launcher_support/screens/splash.py` (+ possivelmente `splash_data.py`), `tests/launcher/*`, `docs/superpowers/*`

---

## 7. Interação

- **Click anywhere no canvas** → `self.app._splash_on_click()` (já existe, leva ao main menu)
- **ENTER / space** → mesma coisa (via `_bind_global_nav`)
- **Q** → `_quit` (existente)
- **Arrow keys / tab / 1-4** → unbound (splash não é navegável por tile, igual hoje)

Nenhuma mudança de interação vs splash atual. Splash continua sendo um gate.

---

## 8. Escopo — o que fica de fora

- **Trading core intocado**: `core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py` — zero mudança
- **Main menu**: permanece Fibonacci legacy; splash só é portal pra ele
- **Animações**: sem scanlines, sem particles, sem CD girando (CD já existe estático no outro fluxo; não adicionamos ao splash). Única animação: prompt pulsante (já existe)
- **i18n**: tudo em EN
- **Novos endpoints**: zero novo endpoint; só consome `/trading/status` já existente
- **Novas deps**: zero (stdlib `threading`, `json`, `pathlib`, `time`, já tem)
- **Cockpit auth logic**: reusa `cockpit_client` se já estiver configurado; se não, RISK fica "---"
- **Histórico de sessões multi-linha**: LAST SESSION mostra só o último, não os últimos N
- **Equity curve sparkline**: Approach 3 foi rejeitado; não entra

---

## 9. Riscos

| Risco | Prob | Impacto | Mitigação |
|---|---|---|---|
| Thread toca canvas destruído após exit | Alta | Crash | `cancel_event` checado antes de cada `itemconfigure` |
| `exchange_api.ticker_24h` bloqueia sem timeout | Alta | Splash lento pra fechar | Thread daemon + timeout 1.5s hardcoded |
| `data/index.json` em formato inesperado | Média | LAST SESSION dado errado | Parser defensivo + "NO SESSION DATA" fallback |
| Cockpit `/trading/status` exige auth que splash não tem | Média | RISK não atualiza | Reusa `cockpit_client` existente; fallback "---" |
| Grid 2×3 aperta verticalmente | Média | Tiles truncam valores | Tile h=150, 4 linhas fonte 8 com padding cabem |
| Cache JSON corrompido entre sessões | Baixa | Dado velho errado | Parser defensivo → {} |
| Sharpe negativo quebra alinhamento | Baixa | Tile desalinhado | Format `>5.2f` largura fixa |
| Teste de coord quebra em refactor | Baixa | CI vermelho | Teste assere semântica (5 tiles), não pixel-perfect |

---

## 10. Sucesso

- Splash abre < 150ms (render offline)
- Tiles live chegam < 1.5s típico, < 5s worst case
- Clicar / ENTER navega instantâneo (não espera async)
- Exit cancela thread async sem callbacks pendentes
- 5 tiles visíveis (STATUS, RISK, MARKET PULSE, LAST SESSION, ENGINE ROSTER)
- Smoke + pytest launcher verde
- Zero arquivo de trading core no diff
- Joao olha o splash, reconhece o sistema todo em 1 segundo

---

## 11. Out of scope para esta spec — backlog

- CD rotating no canto (easter egg)
- Equity curve sparkline ASCII no ENGINE ROSTER
- Histórico multi-sessão
- Refresh manual do splash (tecla R)
- Warning stripes estilo HL1 (spec anterior arquivada)
- Tile interativo (hover → tooltip) — splash é gate, não navegação
