# Cockpit Trade History + Candle Chart Popup — Design

**Status:** approved (brainstorm 2026-04-24)
**Scope:** PAPER + SHADOW panes do `engines_live` (launcher)
**Out of scope:** LIVE trading pane, website, research desk

---

## 1. Goal

Tornar as panes PAPER e SHADOW do cockpit mais completas:

1. **Histórico de trades clicável** — lista uniforme pros dois modos, logo abaixo do detail pane existente, com métricas-chave por linha.
2. **Popup matplotlib com candlestick** — ao clicar numa linha, abre Toplevel Tk com gráfico de candles marcando entry / stop / target / exit (ou preço atual se LIVE). Header + footer minimalistas, sem painel lateral, sem indicadores técnicos.

Filosofia: Bloomberg terminal minimalista. Coeso com o resto do launcher (amber-on-black, Consolas, pills/frames já existentes). Zero novas janelas HTML, zero server side novo.

---

## 2. Non-goals (v1)

- Indicadores técnicos no gráfico (EMA/RSI/BB).
- Zoom/pan interativo (mplfinance default estático basta).
- Export PNG/PDF.
- Filtros na lista (engine, outcome, símbolo).
- Comparação side-by-side de trades.
- Suporte ao modo LIVE (Binance real) — v1 só PAPER + SHADOW. LIVE herda quando chegar.
- Mexer em `config/params.py`, `core/signals.py`, `core/indicators.py`, `core/portfolio.py` (CORE protegido).

---

## 3. Arquitetura

### 3.1 Novos arquivos (2)

| Arquivo | Responsabilidade | LOC estimado |
|---|---|---|
| `launcher_support/trade_history_panel.py` | Render da lista de trades + click handler. Formatters puros (`format_trade_row`, `format_r_multiple`, `format_duration`, `resolve_exit_marker`) unit-testáveis. | ~200 |
| `launcher_support/trade_chart_popup.py` | Toplevel Tk com Figure matplotlib embedded. Fetch de candles Binance, build de markers, live refresh loop. Formatters puros (`derive_candle_window`, `build_marker_specs`, `fetch_binance_candles`). | ~350 |

### 3.2 Arquivos modificados (2)

| Arquivo | Mudança |
|---|---|
| `launcher_support/engines_live_view.py` | Nas funções que renderizam PAPER detail e SHADOW detail, substituir o render inline de trades (hoje no SHADOW) + adicionar o novo no PAPER. Chama `trade_history_panel.render(parent, trades, on_click=_open_chart, colors=..., font=FONT)`. |
| `requirements.txt` | `+ mplfinance>=0.12.10b0` (única dep nova). |

`launcher_support/cockpit_client.py` **não** é modificado — `get_trades(run_id, limit=200)` já existe e basta.

### 3.3 Testes (3 arquivos novos)

| Arquivo | Conteúdo | Testes |
|---|---|---|
| `tests/launcher_support/test_trade_history_panel.py` | Unit — formatters puros | 12-15 |
| `tests/launcher_support/test_trade_chart_popup.py` | Unit — `derive_candle_window`, `build_marker_specs`, `fetch_binance_candles` com `responses` mock | 10-12 |
| `tests/launcher_support/test_trade_chart_popup_smoke.py` | Smoke — monta popup em root Tk headless, verifica sem crash, trade closed + trade live | 2 |

---

## 4. Dados

### 4.1 Fonte — lista de trades

Endpoint: `GET /v1/runs/{run_id}/trades?limit=200` (cockpit API, já existe).

Cliente: `launcher_support/cockpit_client.py` → `client.get_trades(run_id, limit=200)`.

Retorna `{"run_id": str, "count": int, "trades": list[dict]}`. O API abstrai diferença entre `reports/trades.jsonl` (paper) e `reports/shadow_trades.jsonl` (shadow).

### 4.2 Schema unificado do trade (exatamente como vem do API)

Campos obrigatórios pro v1 funcionar:

| Campo | Tipo | Descrição |
|---|---|---|
| `symbol` | str | ex `"SANDUSDT"` |
| `strategy` | str | engine name (`"JUMP"`, `"CITADEL"`, `"RENAISSANCE"`) |
| `direction` | str | `"BULLISH"` / `"BEARISH"` (normaliza pra LONG/SHORT no display) |
| `timestamp` | str | ISO8601 entry ts |
| `entry` | float | entry price |
| `stop` | float | stop price (0 ou None → omite linha) |
| `target` | float | TP price (0 ou None → omite linha) |
| `exit_p` | float | exit price (se fechado) ou último seen (se LIVE) |
| `result` | str | `"LIVE"` / `"WIN"` / `"LOSS"` |
| `exit_reason` | str | `"live"` / `"stop"` / `"target"` / `"trail"` / `"time"` |
| `pnl` | float | $ PnL (0 se LIVE) |
| `r_multiple` | float | R realizado (0 se LIVE) |
| `duration` | int | candles no mercado (0 se LIVE) |
| `size` | float | position size |

Campos opcionais (nice-to-have, fallback DM se ausente):

| Campo | Uso |
|---|---|
| `trade_time` | display-friendly ts (fallback timestamp) |
| `score` | omega/bayes score (display no footer só se presente) |

### 4.3 Fonte — candles

Binance Futures public klines (no auth needed):

```
GET https://fapi.binance.com/fapi/v1/klines
    ?symbol={symbol}
    &interval={tf}
    &startTime={ms}
    &endTime={ms}
    &limit={n}
```

Response: `[[open_ts, O, H, L, C, V, close_ts, ...], ...]` — array de arrays. Parse em DataFrame mplfinance-compatível (`Open, High, Low, Close, Volume` indexado por DatetimeIndex).

### 4.4 Timeframe por engine

Map estático (mantém em `trade_chart_popup.py` — single source, ajustável):

| Engine | TF |
|---|---|
| `CITADEL` | `1h` |
| `RENAISSANCE` | `4h` |
| `JUMP` | `5m` |
| `DE_SHAW` | `1h` |
| `BRIDGEWATER` | `4h` |
| `KEPOS` | `15m` |
| `MEDALLION` | `1h` |
| `AQR` | `1d` |
| `TWO_SIGMA` | `1h` |
| `PHI` | `4h` |
| default | `1h` |

### 4.5 Derivação do exit timestamp

Trade não carrega `exit_ts` explícito. Deriva:

```
tf_seconds = TF_MAP[strategy]  # 1h=3600, 4h=14400, 5m=300
exit_ts = entry_ts + duration * tf_seconds
```

Se `duration == 0` e `result != "LIVE"`: edge case raro (trade fechado no mesmo candle do entry) — usa `entry_ts + tf_seconds` como fallback.

Se `result == "LIVE"`: `exit_ts = None`, marker vira `● current price` na última candle disponível.

### 4.6 Janela do gráfico (C2 auto)

```python
def derive_candle_window(entry_ts, exit_ts, tf_seconds):
    if exit_ts is None:  # LIVE
        duration_candles = 20  # minimum show
    else:
        duration_candles = max(1, (exit_ts - entry_ts) // tf_seconds)
    window = max(20, int(duration_candles * 1.6))  # 60% buffer total
    pad = (window - duration_candles) // 2
    start = entry_ts - pad * tf_seconds
    end = (exit_ts or now()) + pad * tf_seconds
    return start, end
```

Limite hard: `window <= 500 candles` (rate limit + render speed).

---

## 5. UI — trade history panel

### 5.1 Localização

Dentro das panes PAPER e SHADOW do `engines_live_view.py`, inserido **abaixo do detail existente e acima do log stream** (quando log aberto). Header próprio "TRADE HISTORY (N)" amber bar idêntica aos outros blocos.

### 5.2 Layout da linha

Fixed-width, 1 linha por trade, scroll se > 20 trades:

```
▲ SANDUSDT    JUMP      SHORT   0.0776→0.0742   +1.80R  +$24.30    2h14m   TP_HIT
▼ NEARUSDT    CITADEL   LONG    4.85→4.92       LIVE    +$8.20     45m     —
▲ LINKUSDT    RENAI..   SHORT   15.20→15.80     -1.00R  -$15.00    1h20m   STOP
```

Colunas (char-aligned):

| Col | Width | Contenido |
|---|---|---|
| 1 | 2 | `▲` (green) ou `▼` (red) — direction |
| 2 | 12 | symbol (trunc com `..`) |
| 3 | 10 | engine (trunc) |
| 4 | 7 | `LONG` / `SHORT` |
| 5 | 18 | `entry→exit` (se closed) ou `entry→current` (se LIVE) |
| 6 | 8 | `+X.XXR` (if closed) ou `LIVE` (amber) |
| 7 | 10 | `+$X.XX` (green/red) |
| 8 | 8 | duration (`2h14m`, `45m`, `3d`) |
| 9 | 8 | exit_reason (`TP_HIT` / `STOP` / `TRAIL` / `TIME` / `—` se LIVE) |

### 5.3 Interação

- Cursor `hand2` na row inteira
- Hover: bg `BG2` (levemente lighter)
- Click `<Button-1>`: chama `on_click(trade_dict)` — wire em `engines_live_view.py` pra abrir o popup
- Click duplo na mesma row (popup já aberto): traz popup pra frente em vez de duplicar (registry em `launcher._trade_popups: dict[pos_id, Toplevel]`)

### 5.4 Estado vazio

```
  — no trades yet —
```

Dim text. Sem framing dramatic.

### 5.5 Palette / fonts

Reusa imports existentes (`core.ui.ui_palette`):

- `AMBER` header bar
- `WHITE` symbol
- `DIM` engine, duration
- `GREEN`/`RED` direction + pnl
- `AMBER_D` LIVE tag
- `FONT = "Consolas"`, size 8 row, size 7 header

---

## 6. UI — trade chart popup

### 6.1 Janela

- `Toplevel(launcher)` com `transient(launcher)` + `grab_set` (modal soft — usuário pode clicar fora mas popup fica on top)
- Tamanho fixo 900×600 px
- Bind `<Escape>` e X button → `destroy()`
- Ao destruir: remove do `launcher._trade_popups` + cancela after ID do live refresh

### 6.2 Layout (3 rows: header 28px / chart expand / footer 40px)

```
┌────────────────────────────────────────────────────────────────┐
│  SANDUSDT  ·  JUMP  ·  SHORT  ·  +1.80R  ·  +$24.30      [✕]  │  header BG amber-accent
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  candlestick dark theme (mplfinance style='nightclouds' base) │
│  ── entry ──────────────────── yellow solid                    │
│  ── stop ───────────────────── red dashed                      │
│  ── target ─────────────────── green dashed                    │
│       ▼ exit marker amber (or ● current green pulsing)        │
│                                                                │
├────────────────────────────────────────────────────────────────┤
│  entry 0.0776 · stop 0.0810 · tp 0.0742 · exit 0.0742 (TP_HIT) │
│  size 16784 · 2h14m · 2026-04-21 23:00 → 2026-04-22 01:14 UTC  │
└────────────────────────────────────────────────────────────────┘
```

Header cor: `AMBER` bg, `BG` fg (invertido — chama atenção mas coeso)
Footer cor: `DIM`, `BG` bg (discreto)

### 6.3 Chart tech

- `matplotlib.figure.Figure(figsize=(9, 4.5), facecolor=BG)`
- `FigureCanvasTkAgg(fig, master=popup)` + `canvas.get_tk_widget().pack(fill="both", expand=True)`
- `mplfinance.plot(df, type='candle', ax=ax, style=style, ...)` com style custom (dark bg, amber/green/red candles)
- Linhas horizontais: `ax.axhline(y=entry, color='#FFB000', linewidth=1.2, alpha=0.9)`, idem stop (red, dashed), target (green, dashed)
- Marker exit: `ax.scatter([exit_idx], [exit_p], marker='v', color='#FFB000', s=120, zorder=5)` se closed; `marker='o'` + animate pulse se LIVE

### 6.4 Live refresh (trade LIVE)

Só ativa quando `trade.result == "LIVE"`:

```python
def _live_tick():
    if not popup.winfo_exists() or trade_result_changed():
        return
    new_candles = fetch_binance_candles(symbol, tf, start, now)
    current_px = new_candles[-1].close
    redraw_current_price_marker(ax, current_px)
    canvas.draw_idle()
    popup._after_id = popup.after(5000, _live_tick)
```

- Poll a cada 5s (mesmo ritmo do cockpit poller)
- Para quando: popup destruído, trade virou closed (result != LIVE — detecta via re-fetch do trades endpoint)
- Se Binance falha consecutivamente 3x: desativa refresh, exibe "— live feed stalled —" no footer

### 6.5 Popup registry

```python
launcher._trade_popups: dict[str, tk.Toplevel] = {}
# key = f"{run_id}:{symbol}:{entry_ts}" (fallback quando pos_id ausente)

def open_trade_chart(launcher, trade, run_id):
    key = _trade_key(trade, run_id)
    existing = launcher._trade_popups.get(key)
    if existing and existing.winfo_exists():
        existing.lift()
        existing.focus_force()
        return
    popup = TradeChartPopup(launcher, trade, run_id)
    launcher._trade_popups[key] = popup
```

---

## 7. Error handling

| Cenário | Comportamento |
|---|---|
| Binance API timeout/5xx no fetch inicial | Popup abre com placeholder no chart area ("— candles indisponíveis —", retry button). Header + footer renderizam normalmente. Retry button re-tenta fetch. |
| Binance rate limit (429) | Exponencial backoff 2s/4s/8s, depois mesmo placeholder. |
| Símbolo não listado na Binance | Mesma fallback + log warning no launcher console. |
| Trade sem `exit_p` e `result=LIVE` | Marker vira `●` verde pulsante na última candle, live refresh ativa. |
| Trade sem `duration` útil (=0) e `result=WIN/LOSS` | Janela fixa 100 candles centrada em entry, marker `▼` no candle mais próximo do `exit_p` por proximidade de preço. |
| `stop`/`target` == 0 ou None | Omite a linha horizontal correspondente, não quebra render. |
| API cockpit offline (circuit breaker open) | Lista de trades usa cache (`_load_cache`). Se cache vazio, renderiza "— no trade history (cockpit offline) —". |
| Popup já aberto pro mesmo trade | `popup.lift()` + `focus_force()`, não duplica. |
| Trade record malformado (missing entry) | Skip row na lista, log warning. Popup nunca abre com trade inválido. |

---

## 8. Testing strategy

### 8.1 Unit — `test_trade_history_panel.py`

Formatters puros:

- `format_trade_row(trade)` → dict com `symbol`, `engine`, `dir`, `levels`, `r`, `pnl`, `duration`, `exit_reason` formatados
- `format_r_multiple(r)` → `"+1.80R"`, `"-1.00R"`, `"LIVE"` (when 0 and result=LIVE), `"—"` (none)
- `format_duration(candles, tf_sec)` → `"2h14m"`, `"45m"`, `"3d"`, `"<1m"`
- `resolve_exit_marker(trade)` → `"TP_HIT"`, `"STOP"`, `"TRAIL"`, `"TIME"`, `"—"`

Edge cases: null/missing fields, zero duration, extreme r values, direction aliases (BULLISH/BEARISH/LONG/SHORT).

### 8.2 Unit — `test_trade_chart_popup.py`

Formatters puros:

- `derive_candle_window(entry_ts, exit_ts, tf_sec)` → (start, end) com limites
- `build_marker_specs(trade)` → list of matplotlib-compatible dicts
- `fetch_binance_candles(symbol, tf, start, end)` com `unittest.mock` pra urllib → DataFrame parsed
- `tf_seconds(engine)` → map lookup + default fallback
- `normalize_direction("BULLISH")` → `"LONG"`, idem BEARISH→SHORT

### 8.3 Smoke — `test_trade_chart_popup_smoke.py`

2 testes:

- `test_closed_trade_popup_renders()` — cria root Tk, passa trade WIN completo, verifica popup.winfo_exists() + não raise
- `test_live_trade_popup_renders()` — mesmo com result=LIVE, verifica live refresh agendado

Usa `@pytest.fixture` pra Tk root + cleanup. Skip em CI headless se `DISPLAY` ausente (já pattern do projeto).

### 8.4 Não adicionar

- Integration test novo em `engines_live_view` (arquivo já over-tested, mudança é aditiva e trivialmente wired)
- E2E com Binance real (lento, flaky)

---

## 9. Rollout

1. Branch: `feat/cockpit-trade-chart` a partir de `feat/research-desk` (atual)
2. Commits atômicos (5 esperados):
   - `feat(trade-history): panel + formatters + tests`
   - `feat(trade-chart): matplotlib popup + Binance fetch + tests`
   - `feat(engines-live): wire trade_history_panel in PAPER + SHADOW`
   - `chore(deps): add mplfinance`
   - `docs: update CLAUDE.md / CONTEXT.md se necessário` (provavelmente não — é additive)
3. Smoke test local: `python smoke_test.py --quiet`
4. Manual test: abrir launcher → ENGINES → JUMP shadow → clicar trade → validar popup
5. PR pra `main` quando aprovado pelo Joao

---

## 10. Risk / open questions

**Riscos aceitos:**

- `mplfinance` dep nova (~2MB). Alternativa seria custom candlestick em matplotlib puro (~100 linhas frágeis). Aceito.
- Exit timestamp derivado pode errar por 1 candle se `duration` foi arredondada pelo engine. Aceitável — footer mostra ts precise entry/exit.
- Binance public API sem auth → se rate-limit apertar, graceful degrade (retry w/ backoff). Uso humano é trivial; não precisa rate-limiter interno.

**Open questions:** nenhuma. Tudo resolvido no brainstorm.

---

## 11. Success criteria

- Clicar em qualquer trade da lista PAPER abre popup ≤ 2s (sem Binance lag)
- Popup renderiza header/chart/footer sem crash em trade closed e LIVE
- Trade LIVE atualiza preço a cada 5s visualmente
- Zero regression no existing SHADOW render (já tinha click handler pra selected_trade — ainda funciona)
- `smoke_test.py --quiet` passa (156/156 ou equivalente)
- Novos testes: ~25-30 unit + 2 smoke, todos green
