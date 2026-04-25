# Arbitrage Hub v2 — Density & Type Matrix

**Data:** 2026-04-22
**Estado atual do hub:** 3 tabs (OPPS / POSITIONS / HISTORY), 6 colunas no OPPS, REALISTIC filter, simulator no detail pane (commits `600f6fc`/`91b9985`/`4f4b20f`/`552e283`/`8fd315c`/`3a79cdd`).
**Trigger:** "gostei do hub de arbitragem mas ainda ta muito cru, eu quero algo como isso aqui https://arbitragescanner.io/pt, organizar mais os dados".

## Resumo

Reorganizar o Arbitrage Hub pra aumentar densidade de informação por linha (mais colunas concretas de execução) e separar oportunidades por tipo de venue/instrumento (matriz de 5 tabs novas). Mantém intocado: status strip, simulator do detail pane, REALISTIC filter, GRADE MIN, CORE de trading.

## Decisões (brainstorming 2026-04-22)

| # | Pergunta | Decisão |
|---|----------|---------|
| 1 | O que do arbitragescanner.io atrai | A — mais densidade por linha |
| 2 | Quais colunas novas | Curadoria: PROFIT$ / LIFETIME / DEPTH; remover SCORE |
| 3 | Sort default sem SCORE | A — `(grade asc, BKEVN asc, PROFIT$ desc)` (assumido) |
| 4 | Como separar tipos | C — matriz completa, 5 tabs de tipo + POS + HIST = 8 tabs, overlap aceitável |
| 5 | Quais filtros novos | 1+2+4: `PROFIT$ mín`, `LIFETIME mín`, `VENUE allowlist` |

Disposição visual: top bar (estende viab toolbar). Sub-filtros dentro das tabs: não.

## Design

### Tabs (8)

```
[1 CEX-CEX (N)] [2 DEX-DEX (N)] [3 CEX-DEX (N)] [4 PERP-PERP (N)] [5 SPOT-SPOT (N)] [6 BASIS (N)] | [7 POS] [8 HIST]
```

- Cada tab = lente independente sobre o set unificado de oportunidades emitido pelo scanner.
- Counter `(N)` = # de opps que sobrevivem aos filtros ativos pra aquela tab.
- Overlap esperado: o mesmo trade pode aparecer em duas tabs (ex.: `binance-perp ↔ bybit-perp BTC` aparece em CEX-CEX e PERP-PERP). Documentar no behaviour, não evitar.
- Predicate por tab (sobre o pair record que o scanner já emite):

| Tab | Predicate |
|-----|-----------|
| CEX-CEX | `is_cex(leg_a.venue) and is_cex(leg_b.venue)` |
| DEX-DEX | `is_dex(leg_a.venue) and is_dex(leg_b.venue)` |
| CEX-DEX | `is_cex(leg_a.venue) != is_cex(leg_b.venue)` |
| PERP-PERP | `leg_a.kind == "perp" and leg_b.kind == "perp"` |
| SPOT-SPOT | `leg_a.kind == "spot" and leg_b.kind == "spot"` |
| BASIS | `leg_a.kind != leg_b.kind and leg_a.symbol == leg_b.symbol` |

`is_cex` lê de uma allowlist hardcoded em `core/arb/` (binance, bybit, okx, kucoin, etc.); o resto é DEX. `kind` precisa ser garantido no record do scanner — se hoje só vem perp, SPOT-SPOT e BASIS ficam vazios até spot scanning entrar.

### Tabs labels — compactação

Ordem de preferência: forma cheia. Se a barra exceder a largura útil, encolher pelo seguinte protocolo (mesmo helper que o splash usa pra densidade):

1. Drop counters: `1 CEX-CEX` em vez de `1 CEX-CEX (24)`
2. Encurtar separador: `1 CEX/CEX`
3. Abreviar: `1 CC`, `2 DD`, `3 CD`, `4 PP`, `5 SS`, `6 BAS`, `7 POS`, `8 HIS` (mostrar tooltip com nome cheio)

Decisão de qual nível usar é runtime, baseado em `winfo_reqwidth` do tabs_frame após primeiro layout pass.

### Colunas (8)

```
VIAB  SYM (TYPE)  VENUES                  APR     PROFIT$/$1k 24h  LIFE   BKEVN   DEPTH$1k
```

| Coluna | Origem | Notas |
|--------|--------|-------|
| VIAB | já existe (`grade_bucket` em score_opp) | Semáforo 🟢 GO / 🟡 WAIT / ⚪ SKIP |
| SYM (TYPE) | já existe + sufixo derivado dos kinds | TYPE = `(P-P)` / `(S-S)` / `(P-S)` — distingue overlap entre tabs |
| VENUES | já existe | `long → short` |
| APR | já existe | % anualizado |
| PROFIT$/$1k 24h | **novo** — calc em `score_opp` | `apr/100 × $1000 × 24/8760 − fees_rt`; `fees_rt` = 30bps em $1k = $3 (constante de simulator atual) |
| LIFE | **novo** — lifecycle tracker | Tempo desde primeira observação do `(symbol, leg_a, leg_b)` no scanner. Formato `Nm` se <60min, `NhMm` senão |
| BKEVN | já existe | Hours até pagar fees_rt; `>24h` se >24 |
| DEPTH$1k | **novo** — calc em `score_opp` | `slippage_bps_for($1k_notional, leg.book_depth)`; depende de orderbook depth no scan record |

Ordem horizontal acima é a ordem de display. Sort default: `(grade_bucket asc, BKEVN asc, PROFIT$ desc)`.

`SCORE` é removido da view (continua sendo computado em `score_opp` por uso interno; só não vira coluna).

### Filtros (top bar)

Estende `_arb_build_viab_toolbar` (atualmente: `[REALISTIC] [GRADE MIN]`):

```
[ REALISTIC ✓ ]  [ GRADE MIN: WAIT ▼ ]  [ PROFIT$ ≥ 5 ]  [ LIFE ≥ 30m ]  [ VENUES: bin/byb/okx ▼ ]   3 ativos · 24/47
```

| Chip | Tipo de input | Default |
|------|---------------|---------|
| PROFIT$ ≥ X | popover com Entry numérico | `0` (off) |
| LIFE ≥ X | popover com Entry + sufixo `m`/`h` | `0` (off) |
| VENUES allowlist | popover com checkboxes lendo `connections.json` | todas marcadas (off) |

Persistência via `_arb_save_filters` / `_arb_load_filters` (já existem). O contador à direita (`3 ativos · 24/47`) lê o estado atual e o ratio da tabela ativa.

Filtros se aplicam **antes** do predicate de tab (i.e., um trade filtrado por PROFIT$<5 some de todas as 6 tabs de tipo).

### Status strip

Mantém intacto: `● LIVE · CEX N · DEX N · SCAN Ns ago · TOP <best> · ENGINE pill · ACCT · DD`.

### Detail pane (click numa row)

Mantém intacto: chips de size $500/$1k/$2.5k/$5k → tabela HOLD/FUNDING/FEES/NET em 8h/24h/72h, decay scenario, RISK block (liq distances, slippage, venue tier), `▶ ADVANCED` (factor breakdown), `▶ OPEN AS PAPER — $X`.

Click numa row de tab diferente reusa o pane (não fecha, só re-renderiza).

### Auto-refresh / cache / lazy detail

Mantém intacto: scan async every 15s, 10s scan cache reuso entre tab-switches, lazy detail render.

## Implementation outline (alto nível)

Detalhamento de arquivos exatos vai pro plan (writing-plans). Aqui só ordem alta:

1. **`_ARB_TAB_DEFS` reescrito** — 8 tuples `(key, tid, label_full, label_compact, predicate, color)`. Coloca também `category="type"|"meta"` pra separador `|` antes de POS/HIST.
2. **Renderer único** `_arb_render_tab_filtered(parent, predicate)` substitui as funções por tab. `render_map` em `arbitrage_hub.py:179` mapeia todos os 6 type-tabs pro mesmo callback com predicate diferente.
3. **`score_opp` enriquece o ScoreResult** — adiciona `profit_usd_per_1k_24h`, `depth_pct_at_1k`. Mantém `score` existente pro detail/internal.
4. **Lifetime tracker** — `app._arb_lifetimes: dict[str, float]` (key = stable hash de `(symbol, leg_a.venue, leg_b.venue, kind_a, kind_b)`, value = first_seen ts). Inserido em `_arb_hub_telem_update`. Format helper produz string `LIFE`.
5. **Filtros novos** — `_arb_filter_state` ganha `profit_min: float`, `life_min_seconds: int`, `venues_allow: set[str] | None`. `_arb_build_viab_toolbar` ganha 3 chips. Cada chip abre `_arb_open_filter_popover(name)`. Persistência reusa `_arb_save_filters`.
6. **Sort comparator novo** — substitui o atual em `_arb_render_tab_filtered`.
7. **Tabs auto-compact** — após mount, mede `winfo_reqwidth` do tabs_frame; se exceder largura útil, re-renderiza com label level seguinte (cheio → sem counter → slash → abreviado). Idempotente.
8. **Counter por tab** — após scan + filtros aplicados, conta opps que satisfazem cada predicate; atualiza label. Roda dentro de `_arb_hub_telem_update`.
9. **Fallback gracioso** — se `kind` não vier no scanner record, SPOT-SPOT/BASIS mostram empty state com mensagem "scanner não emite spot kind ainda".

## Out of scope (fase 2 ou nunca)

- NET FEE (network/gas) como coluna — vira info do detail pane, não da tabela.
- VOL/OI explícito — DEPTH cobre o conceito útil.
- VENUE TIER — vira tooltip no hover de VENUES.
- PERSISTÊNCIA (decay-aware filter), DEPTH MAX%, PAR allowlist, NETWORK filter — fase 2 se virar útil.
- Side panel de filtros (estilo arbitragescanner) — top bar é mais Bloomberg-y e cabe melhor em Tk.
- Sub-filtros dentro das tabs.
- Agrupamento visual por par/venue dentro da tabela (opção C do brainstorming) — só se a tabela ficar visualmente confusa após o redesign.
- Header clicável pra sort por coluna (opção D do brainstorming pergunta 3) — só se sort default não satisfizer.
- Mudanças no detail pane (simulator), status strip, REALISTIC filter, GRADE MIN dropdown.

## Dependencies / risk

- **CORE de trading** (`indicators.py`, `signals.py`, `portfolio.py`, `params.py`): zero alteração. Toda mudança é UI + `core/arb/` (que não é CORE).
- **Scanner record shape**: precisa garantir `kind ∈ {"perp","spot"}` por leg. Se não vier, SPOT-SPOT e BASIS ficam vazias (fallback documentado).
- **Orderbook depth no record**: DEPTH$1k requer profundidade de book. Se scanner não trouxer, DEPTH mostra `—` e a coluna fica vazia até dataset enriquecer.
- **Lifetime persistence**: tracker é em-memória, perde entre sessões. Se quiser persistir, fica fase 2.
- **Compactação de tabs**: estimar largura em Tk depende de fonte renderizada (Consolas 9pt) — mede após primeiro mount, não em design time.

## Testing strategy

- **Predicate por tab** — unit test em `tests/launcher/` com fake pair records (CEX-CEX, DEX-DEX, etc.) → cada tab vê só os esperados.
- **Lifetime tracker** — unit test: insert + age + reformat (`90s → 1m30s`, `4500s → 1h15m`).
- **Sort comparator** — unit test: 3 fake opps com grades misturados → ordem esperada.
- **Filtros** — unit test: pair com profit_usd=4 sob filtro `profit_min=5` é cortado; venue não em allowlist é cortado.
- **Counter update** — integration smoke: telem update com fake opps → labels têm counts corretos.
- **Compactação** — não testa unitariamente (depende de Tk render); valida visualmente.

`smoke_test.py` deve passar 100% pós-merge.

## Acceptance criteria

1. Hub abre na tab CEX-CEX (default), mostra 8 colunas com PROFIT$/LIFE/DEPTH preenchidos pra opps que tenham os dados.
2. Tabs `1`-`6` filtram por tipo conforme predicate; `7`/`8` mantêm POSITIONS/HISTORY como hoje.
3. Counter `(N)` atualiza após cada scan + filtro.
4. 3 chips novos no top bar respondem a click abrindo popover; valor escolhido reflete nos dados; persistência sobrevive a relaunch.
5. Sort default é `(grade asc, BKEVN asc, PROFIT$ desc)`. Linhas GO sempre acima de WAIT/SKIP.
6. `SCORE` desaparece da view.
7. Click numa row abre o simulator existente sem regressão.
8. CORE de trading: `git diff main...HEAD -- core/indicators.py core/signals.py core/portfolio.py config/params.py` retorna vazio.
9. `python smoke_test.py --quiet` passa.
10. Tests novos (>=8) passam.

## Notas pro plan

- A reescrita do `_ARB_TAB_DEFS` quebra a API de `_arbitrage_hub(tab=...)` (hoje aceita `cex-cex`/`dex-dex`/`opps`/etc). Garantir back-compat por aliases ou aceitar a mudança.
- `score_opp` é shared com simulator — adicionar campos sem remover os atuais.
- `core/arb/engine.py` (SimpleArbEngine) usa fees_rt=30bps; o cálculo de PROFIT$ deve usar a mesma constante (não hardcodar de novo).
