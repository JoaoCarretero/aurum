# ENGINES frontend — rebuild design

**Data:** 2026-04-23
**Escopo:** reconstrução completa do frontend `EXECUTE → ENGINES LIVE` no launcher TkInter. Refactor arquitetural (A) + redesign visual/UX (B) num único projeto. Sem replatform pra web — tudo continua em TkInter dentro do launcher.
**Supersede:** `docs/superpowers/specs/2026-04-16-engines-live-cockpit-design.md` (design original, divergiu muito via iterações).
**Complementa (não conflita):** `docs/superpowers/specs/2026-04-23-cleanup-phase-3-design.md` — Phase 3 extrai `_eng*` methods de `launcher.py` pra `launcher_support/screens/engines_live.py` (thin delegate). Este spec reorganiza o payload real em `launcher_support/engines_live_view.py` + `engines_sidebar.py` → pacote `engines_live/`. Os dois projetos operam em camadas diferentes. Ordem sugerida: Phase 3 primeiro (estabiliza thin delegate), depois este rebuild (reestrutura o conteúdo que o delegate chama).
**Preserva:** paleta HL2/VGUI (`core/ui/ui_palette.py`), core de trading (indicators/signals/portfolio/params — intocados), cockpit_api backend, procs contract (`.aurum_procs.json`), run dir structure, Telegram.

---

## 1 · Motivação

Estado atual:

- `launcher_support/engines_live_view.py` = **4025 linhas** num único arquivo
- `launcher_support/engines_sidebar.py` = **1009 linhas**
- `launcher_support/engines_live_helpers.py` = **273 linhas**
- Total: **5307 linhas** num fluxo monolítico

Pain points (confirmados com o Joao — "tudo"):

1. Densidade errada (vazio em lugares, apertado em outros)
2. Hierarquia não revela "o que importa agora"
3. Fluxo LIVE/PAPER/SHADOW confuso — modo escondido, atrito pra trocar
4. Log tail e telemetria não atualizam bem, ficam rasos
5. Stop/start/restart escondidos ou sem proteção contextual
6. Multi-instância (desk-a, desk-b, paper vs shadow) polui a lista
7. VPS vs local não fica claro de onde vem o dado
8. Performance — UI congela em refresh de detail, flicker em rebuild

Objetivo: um rebuild que endereça todos os 8 pontos **sem sair do TkInter** e **sem quebrar fluxos existentes** (cockpit_api, Telegram, systemd units no VPS, procs contract).

---

## 2 · Escopo

**In:**
- Refactor de `engines_live_view.py` + `engines_sidebar.py` → pacote `launcher_support/engines_live/` de módulos coesos (3400 linhas projetadas, -1900 linhas de dead weight).
- Redesign visual: layout α (Bloomberg max-density) com cards V3 (1 engine = 1 card agregado, instâncias no detail) e detail pane D2 (instances+KPIs na esquerda, log wide na direita).
- Diff-based rendering pra matar flicker atual.
- Hold-to-confirm pra ações destrutivas.
- Color-coded log tail com modos default/follow/open-full.
- Keyboard model global (ESC/TAB/▲▼/ENTER/M/// ?) + detail-local (S/R/A/+/C/L/F/T).
- Fluxo "+ NEW INSTANCE" com target LOCAL ou VPS + ritual de LIVE.

**Out:**
- Replatform web (React/webview/standalone) — descartado.
- Mudanças no core de trading (`core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py`) — PROTEGIDOS por CLAUDE.md, nada toca.
- Novos endpoints do cockpit_api — a view consome o que já existe. Se algum dado faltar, escrever em backlog pra fase futura.
- Mudanças na estrutura de run dirs ou no `aurum.db`.

---

## 3 · Layout geral

```
┌─ › ENGINES ─── 11 live · 6 engines ───── PAPER · DEMO · TESTNET · LIVE ─ CRYPTO FUT ─┐
│                                                                                      │  HEADER (36px)
├──────────────────────────────────────────────────────────────────────────────────────┤
│ ╭ CITADEL ── 2●● ╮ ╭ JUMP ─── 2●● ╮ ╭ RENAISSANCE ─ 2●● ╮ ╭ MILLENNIUM ─ 4●●●● ╮   │
│ │ p+s · 15m       │ │ p+s · 15m    │ │ p+s · 15m          │ │ 2p+2s · 1h04m       │   │
│ │ 0/17 novel/tick │ │ 0/17 nvl/t   │ │ 0/17 novel/tick    │ │ 0/17 novel/tick     │   │  STRIP GRID
│ │ eq $10k · 0dd%  │ │ eq $10k      │ │ eq $10k · 0dd%     │ │ eq $40k · 0dd%      │   │  (running)
│ ╰─────────────────╯ ╰──────────────╯ ╰────────────────────╯ ╰─────────────────────╯   │
│ ╭ PROBE ─ 1● ╮ ╭ + NEW ENGINE ╮                                                      │
│ │ desk-a · 1h│ │ pick+start    │                                                      │
│ ╰────────────╯ ╰───────────────╯                                                      │
│                                                                                      │
│ ─── RESEARCH / READY ────────────────────────────────────────────────── ▾ expand ─   │  SHELF (collapsed)
│ 🔒 DESHAW · 🔒 BRIDGEWATER · 🔒 TWOSIGMA · 🔒 AQR · 🔒 WINTON · 🔒 PHI · ...          │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ ─── Detail: CITADEL ──────────────────────────── score 14.0 · macro BULL ─────────   │
│ ┌─ INSTANCES ──────────────────────────┬─ LOG (citadel.paper.desk-a) ────────────┐   │
│ │ › p.desk-a ● 15m  17t/0nvl  $10,000  │ 19:37:31 INFO  TICK ok=17 novel=0       │   │  DETAIL PANE
│ │   s.desk-a ● 15m  17t/0nvl      —    │ 19:22:16 INFO  TICK ok=16 novel=0       │   │  (~40% viewport)
│ │                                      │ 19:07:11 INFO  TICK ok=15 novel=0       │   │
│ │ 2 inst · agg $10k · macro BULL       │ 18:51:55 INFO  TICK ok=14 novel=0       │   │
│ │                                      │ ...                                     │   │
│ │ [S]top  [R]estart  [+] inst  [C]onfig│ [O] open full  [F] follow  [T] tg test │   │
│ └──────────────────────────────────────┴─────────────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ ESC main · ▲▼←→ nav · ENTER drill · S stop · R restart · N new · C config · M mode  │  FOOTER (18px)
└──────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.1 Header (36px)

- `› ENGINES` em AMBER bold 12pt (à esquerda)
- Contadores: `N live · M engines` em DIM (centro-esquerda)
- Mode pills segmented: `PAPER · DEMO · TESTNET · LIVE`
  - PAPER → CYAN (`#7FA0B0`)
  - DEMO → GREEN (`#7FA84A`)
  - TESTNET → AMBER (`#D08F36`)
  - LIVE → RED (`#C44535`)
  - Ativa: fundo da cor, texto BG. Inativa: fundo BG3, texto na cor.
  - **Semântica: default pra novas instâncias, não filtro visual.**
- Market label à direita (ex.: `CRYPTO FUT`)
- Se modo ativo = LIVE, linha inferior do header vira RED 1px.
- Se cockpit offline: badge `OFFLINE` AMBER. Se VPS unreachable: badge `VPS UNREACHABLE` AMBER_B.

### 3.2 Strip grid (cards V3)

Grid de cards uniformes (1 card por engine com ≥1 instância rodando). Cada card:

```
╭ CITADEL ── 2●● ╮   ← nome AMBER bold 10pt · dots de instâncias
│ p+s · 15m      │   ← tipos de instância + max uptime (DIM 9pt)
│ 0/17 nvl/t     │   ← sum(novel) / sum(ticks) (WHITE bold 9pt)
│ eq $10k · 0dd% │   ← equity agregada + max DD (GREEN ou RED por sinal)
╰────────────────╯
```

**Dots no header do card:**
- `●` verde = instância LIVE (heartbeat fresco)
- `!` amber = STALE (heartbeat > 2× tick_sec)
- `✕` vermelho = ERROR (ticks_fail > 0 ou processo morto)
- 1 dot por instância, ordem: live → stale → error

**Subtitle "p+s · 15m":**
- `p` = tem paper · `s` = shadow · `l` = live
- `15m` = max uptime entre todas instâncias (format: `Xm` / `Xh0Ym` / `XdYh`)

**Card states:**
| Estado | Border | Cor do nome | Dots |
|---|---|---|---|
| Normal | BORDER | AMBER | `●●` verde |
| Selected | AMBER_B 2px | AMBER | sem mudar |
| Stale | HAZARD | HAZARD | `!!` amber |
| Error | RED | RED | `✕✕` vermelho |
| Not running | DIM (só no shelf) | DIM | `○` |

**Grid responsivo:**
- Card width fixo ~180-220px (auto-calculado do conteúdo mais largo em Consolas 10pt; ~22 caracteres)
- Height fixo: 5 linhas de conteúdo + borda (~100-110px total)
- Wrap: 3 cards/row se viewport < 1000px, 4 se 1000-1400px, 5 se > 1400px. Gap 8px entre cards.
- Card `+ NEW ENGINE` sempre no fim da última row

**Ordem dos cards (estável):**
1. Cards com erro (top-left)
2. Cards saudáveis, por `ENGINES[*].sort_weight` ascendente (CITADEL=10, BRIDGEWATER=20, JUMP=40, RENAISSANCE=50, MILLENNIUM=60, etc.)
3. Empate = alfabético
4. Card `+ NEW ENGINE` ao final

Não reordena por uptime/equity/novel — ordem estável evita dança visual.

### 3.3 Research shelf (colapsável)

Linha compacta entre strip grid e detail. Colapsada por default:

```
─── RESEARCH / READY ──────────────────────────── ▾ expand ─
🔒 DESHAW · 🔒 BRIDGEWATER · 🔒 TWOSIGMA · 🔒 AQR · ...
```

Expandida:

```
─── RESEARCH / READY ──────────────────────────── ▸ collapse ─
┌─ DESHAW ──────────┐ ┌─ BRIDGEWATER ────┐ ┌─ TWOSIGMA ──────┐
│ 🔒 not validated  │ │ 🔒 not validated │ │ 🔒 not validated │
│ [START] [BACKTEST]│ │ ...              │ │ ...              │
└───────────────────┘ └──────────────────┘ └──────────────────┘
```

- Research engines (sem `live_ready` em `config/engines.py`) mostram `⚠ not validated for live` no new-instance dialog e **só permitem modo PAPER**.
- ENTER sobre engine da shelf = direto pro new instance dialog (bypassa strip grid).

### 3.4 Detail pane (D2)

Ocupa ~40% do viewport inferior. 2 colunas:

**Esquerda (largura ~40 cols):**
```
─ Instances ──────────────────────────────
› p.desk-a   ● 15m   17t/0nvl   $10,000
  s.desk-a   ● 15m   17t/0nvl        —

─ Aggregate ─────────────
inst 2 · 2 live · 0 novel / 34 ticks
equity   $10,000.00  +0.00% (paper only)
max dd   0.00%
last sig —
last novel —

─ Instance actions ──────
[S]top p.desk-a  [R]estart  [L]ogs

─ Engine actions ────────
[A]stop all  [+] new inst  [C]onfig
```

Lista de instâncias:
- Formato: `mode.label  ●status  uptime  Xt/Ynvl  equity`
- Selecionada = setinha `›` + background BG3
- Ordem: live (verde) → stale (amber) → error (vermelho). Dentro: uptime desc.

**Direita (largura restante):**
```
─ Log (citadel.paper.desk-a) ────────────────
19:37:31 INFO   TICK ok=17 novel=0 open=0 eq=10000
19:22:16 INFO   TICK ok=16 novel=0 open=0 eq=10000
...
[O] open full log   [F] follow tail   [T] telegram test
```

- 14 linhas visíveis (Consolas 9pt)
- Color por nível:
  - `INFO` → DIM
  - `SIGNAL` → AMBER bold
  - `ORDER` → CYAN
  - `FILL` → GREEN
  - `EXIT` → WHITE bold
  - `WARN` → HAZARD
  - `ERROR` → RED bold
- Modos: default (polling), follow (auto-scroll + 3s poll), open-full (viewer inline pesquisável)

**Placeholder (nada selecionado):**
- Stats globais: N engines live, total novels/ticks 24h, total equity paper
- "← Select an engine above" em DIM

### 3.5 Footer (18px)

Linha de keybind hints, muda conforme contexto:
- STRIP foco: `ESC main · ▲▼←→ nav · ENTER drill · N new · M mode · / filter · ? help`
- DETAIL/instances: `ESC strip · ▲▼ inst · TAB log · S stop · R restart · L logs · C config`
- DETAIL/log: `ESC instances · TAB strip · F follow · O open · T tg test`

---

## 4 · Live updates & data flow

### 4.1 Cadências de repaint

| Pane | Repaint cadence | Fonte |
|---|---|---|
| Strip grid + counts | 30s | cockpit_api `/v1/runs` + procs snapshot |
| Detail pane (default) | 15s | heartbeat + log tail + instances snapshot |
| Detail pane (follow mode) | 3s | log tail append-only |
| Header counts | 30s (junto com grid) | — |

**Diff-based**: comparar `StateSnapshot` anterior vs novo, chamar `.update(state)` em cada pane. Não destroy+recreate. Evita flicker.

### 4.2 Event-driven repaints (imediato)

Eventos que disparam repaint antes da cadência normal:
- Stop/restart/start dispara invalidação + repaint imediato do pane afetado
- Crash detectado (ticks_fail > 0 nova) → repaint grid (mostra ✕ vermelho)
- Nova instância registrada → strip ganha dot novo com fade-in 200ms

### 4.3 Caches

| Cache | TTL | Onde |
|---|---|---|
| `/v1/runs` (cockpit) | 60s | `data/cockpit.py` |
| Paper snapshot por run | 60s | `data/cockpit.py` |
| Shadow snapshot por run | 60s | `data/cockpit.py` |
| Procs snapshot local | 60s | `data/procs.py` |
| Heartbeat por run | 30s | `data/procs.py` |

Lock por chave de cache. Invalidação explícita em ações destrutivas.

### 4.4 Tk threading

- Cockpit polls rodam em `ThreadPoolExecutor` background.
- UI updates voltam pro main loop via `root.after(0, fn)`.
- Regra documentada em `data/__init__.py`: nunca tocar Tk de thread não-main.

### 4.5 Degradação graciosa

| Evento | Comportamento |
|---|---|
| Cockpit offline | Badge `OFFLINE` AMBER; mantém últimos valores conhecidos; polling continua (reconecta auto). |
| VPS unreachable | Badge `VPS UNREACHABLE` AMBER_B; local-only cards continuam; start dialog muda default pra LOCAL. |
| Heartbeat stale (>2×tick) | Dot da instância vira `!` amber; border do card HAZARD. |
| Processo morto (detectado via procs snapshot) | Dot vira `✕`; border RED; detail mostra último erro + [RESTART]. |

---

## 5 · Keyboard model

### 5.1 Globais

| Key | Ação |
|---|---|
| `ESC` | voltar / cancelar / sair pro main menu |
| `TAB` | STRIP → DETAIL/instances → DETAIL/log → STRIP (ciclo) |
| `▲▼←→` | navega elementos dentro do pane focado |
| `ENTER` | drill down (strip→detail; shelf→start dialog) |
| `M` | cycle mode global (PAPER → DEMO → TESTNET → LIVE → PAPER) |
| `/` | search/filter engines |
| `?` | overlay de help do contexto |

### 5.2 DETAIL locais

| Key | Ação | Hold |
|---|---|---|
| `S` | stop instância selecionada | 1.5s |
| `R` | restart instância selecionada | 1.5s |
| `A` | stop ALL instâncias do engine | 1.5s |
| `+` / `N` | new instance dialog | — |
| `C` | config viewer (read-only se running) | — |
| `L` | open full log viewer | — |
| `F` | toggle follow tail mode | — |
| `T` | telegram test | — |

### 5.3 Hold-to-confirm

Ações com Hold (S/R/A):
1. Press → background do botão começa preencher AMBER left→right (1.5s)
2. Label muda pra `HOLD TO STOP...`
3. Release antes dos 1.5s → aborta, sem efeito
4. Completou 1.5s → executa; flash GREEN 300ms, label volta

### 5.4 Routing

Módulo `keyboard.py` expõe função pura:
```python
def route(context: FocusContext, key: str) -> Action | None
```
`context` = estado da UI (qual pane tem foco, qual engine/instância selecionada, modo atual, etc.).
`Action` = discriminated union (`StopInstance`, `RestartAll`, `OpenNewInstanceDialog`, etc.).
Panes despacham eventos crus; não tratam keys internamente.

---

## 6 · "+ NEW INSTANCE" flow

### 6.1 Dialog

Disparado por `+` ou `N` com engine selecionada (ou ENTER na shelf):

```
┌─ NEW INSTANCE · CITADEL ───────────────────────────────┐
│  Mode     [PAPER] [DEMO] [TESTNET] [LIVE]              │  ← pre-select = mode pill global
│  Label    [desk-a_____________]                        │  ← free text, sanitized
│  Target   [LOCAL] [VPS]                                │  ← default VPS se reachable
│                                                         │
│  Command preview:                                       │
│  $ citadel_paper@desk-a.service start (vps: 37.60...)  │
│                                                         │
│  [ CANCEL ]                    [ CONFIRM · START ]     │
└─────────────────────────────────────────────────────────┘
```

- **Mode**: pre-selecionado no mode pill global. Pode trocar antes de confirmar.
- **Label**: sanitized via `tools/operations/run_id.sanitize_label` (já existe).
- **Target**: LOCAL (subprocess + `.aurum_procs.json`) ou VPS (systemctl via SSH + key_store). Default = VPS se reachable, senão LOCAL.
- **Command preview**: mostra comando exato que vai rodar (transparência).

### 6.2 Ritual LIVE

Se `mode == LIVE`, CONFIRM dispara segundo dialog:

```
┌─ LIVE EXECUTION · CITADEL ─────────────────────────────┐
│  ⚠  Real money. Real orders.                            │
│                                                         │
│  Type CITADEL to confirm:                               │
│  [____________]                                         │
│                                                         │
│  [ CANCEL ]                    [ CONFIRM ]  (disabled)  │
└─────────────────────────────────────────────────────────┘
```

- Botão CONFIRM fica disabled até input == nome da engine (case-sensitive).
- CANCEL/ESC fecha sem rodar.
- Confirmou → chama entry point live existente (ex.: `_exec_live_inline`).

### 6.3 Research engines na shelf

- Se engine não tem `live_ready` em `config/engines.py`:
  - Banner AMBER `⚠ not validated for live` no topo do dialog
  - Mode pills DEMO/TESTNET/LIVE disabled (só PAPER permitido)

---

## 7 · Refactor — nova estrutura

### 7.1 Árvore

```
launcher_support/engines_live/
├── __init__.py                 ── re-exports render_view(), _get_cockpit_client()
├── view.py               ~300  ── orchestrator: monta panes, ciclo de repaint
├── state.py              ~200  ── selection, focus, mode, prefs (pure)
│
├── data/
│   ├── __init__.py
│   ├── cockpit.py        ~150  ── wrapper do cockpit_api client + cache TTL
│   ├── procs.py          ~150  ── snapshot .aurum_procs.json + heartbeats
│   ├── aggregate.py      ~120  ── PURE: colapsa instâncias → engine cards
│   └── log_tail.py       ~130  ── leitor de log (follow + color parse)
│
├── panes/
│   ├── header.py         ~150  ── título · counts · mode pills · market
│   ├── strip_grid.py     ~280  ── grid responsivo de engine cards
│   ├── research_shelf.py ~200  ── linha colapsável de not-running engines
│   ├── detail.py         ~180  ── orquestra left/right e TAB switching
│   ├── detail_left.py    ~230  ── instances list + KPIs + actions
│   ├── detail_right.py   ~200  ── log tail + color code + follow mode
│   ├── detail_empty.py   ~100  ── placeholder "welcome" quando nada sel
│   └── footer.py          ~80  ── keybind hints contextuais
│
├── dialogs/
│   ├── new_instance.py   ~180  ── + new instance modal (mode/label/target)
│   └── live_ritual.py     ~90  ── LIVE confirmation (type engine name)
│
├── widgets/
│   ├── hold_button.py    ~120  ── hold-to-confirm 1.5s com progress fill
│   ├── engine_card.py    ~150  ── render de 1 strip (states normal/stale/err)
│   └── pill_segment.py    ~80  ── mode pills segmented control
│
├── keyboard.py           ~150  ── routing: contexto → ação
└── helpers.py            ~200  ── re-export de engines_live_helpers.py (bw compat)
```

Total ~3400 linhas (vs 5307 atual). Economia ~1900 linhas de acoplamento implícito + dead code.

### 7.2 Princípios de isolamento

1. **Pure vs Tk**: `data/` e `state.py` NÃO importam `tkinter`. Testáveis sem mock Tk. `panes/`, `dialogs/`, `widgets/` tocam Tk mas recebem data como argumento.
2. **Cada pane é um widget composto**: módulo exporta classe ou factory (`build_strip_grid(parent, state) → Frame`). Sem globals mutáveis compartilhados.
3. **Data layer single-responsibility**: `cockpit.py` só cockpit_api; `procs.py` só procs+heartbeats; `aggregate.py` puro transform. Caches ficam contidos.
4. **Diff-based render**: `view.py` compara snapshots, chama `.update(state)` por pane.
5. **Keyboard centralizado**: `keyboard.py` tem tabela (contexto, key) → action. Panes despacham eventos crus.
6. **Backward compat**: `engines_live_helpers.py` continua existindo (ou re-exportado). Imports em `launcher.py` e testes não quebram na transição.

---

## 8 · Migração — 5 fases incrementais

| Fase | Escopo | PR scope |
|---|---|---|
| **R1** | Criar pacote vazio. Mover `engines_sidebar.render_detail` pra `panes/detail.py`. Testes verdes. | Pequena, puro move. |
| **R2** | Extrair data layer: `_get_cockpit_client`, caches, heartbeat readers → `data/`. Pure isolado. | Média. |
| **R3** | Extrair panes como widgets compostos: strip_grid, detail_left, detail_right, footer. `view.py` vira fino. | Grande (refactor estrutural). |
| **R4** | Aplicar design novo (V3 cards, D2 detail, hold-to-confirm, color log). Parte "B". | Grande (novo UX). |
| **R5** | Cleanup: `engines_live_view.py` original vira shim de 5 linhas. Arquiva `engines_sidebar.py`. | Pequena. |

Cada fase = 1 PR, revisável, suite verde. Launcher continua funcional o tempo inteiro. Sem big-bang.

---

## 9 · Testes

| Tipo | Cobertura | Onde |
|---|---|---|
| Pure unit | `data/*`, `state.py`, `aggregate.py` | `tests/launcher/engines_live/` |
| Smoke headless | panes/widgets instanciados com Tk root invisível, assert estrutura/labels/cores | `tests/integration/test_engines_live_*.py` |
| Keyboard table-driven | `route(context, key) == expected_action` | `tests/launcher/engines_live/test_keyboard.py` |
| E2E manual | checklist no spec, rodar `python launcher.py` → EXECUTE → ENGINES LIVE | documentado em `docs/testing/engines_live_e2e.md` |

Critério de "done": suite de testes verde (incluindo regressão dos existentes em `tests/integration/test_engines_live_view.py`) + checklist E2E manual passado.

---

## 10 · Riscos

| Risco | Mitigação |
|---|---|
| Import circularity launcher.py ↔ engines_live/ | launcher.py importa só `render_view` do `__init__`. engines_live/ nunca importa launcher. |
| Caches dessincronizando entre panes | Lock por chave de cache; invalidação explícita em ações (stop/restart invalida). |
| Tk threading (cockpit polls em thread) | Regra documentada em `data/__init__.py`: UI updates só via `root.after(0, fn)`. |
| Backward compat de testes que importam internals | Manter re-exports temporários em `helpers.py`. Marcar deprecation, remover em PR futura. |
| Regression visual entre fases | Cada fase passa suite integration existente; R3 e R4 ganham screenshots manuais no PR. |
| Flicker ao migrar pra diff-based | Testar ao vivo durante R4 com VPS ativo; comparar antes/depois via vídeo curto. |

---

## 11 · Preservação explícita (não toca)

Estes arquivos/contratos não podem ser modificados por este projeto:

- `core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py` — CORE de trading (CLAUDE.md).
- `tools/cockpit_api.py` endpoints — contrato estável. Se algum dado faltar, backlog pra fase futura.
- `.aurum_procs.json` schema — procs contract.
- `data/<engine>/<run>/` structure — run dirs.
- `aurum.db` schema (live_runs etc.).
- `config/engines.py` ENGINES registry — view consome, não edita.
- `core/ui/ui_palette.py` — paleta preservada integralmente.

---

## 12 · Sucesso

Rebuild é bem-sucedido se:

1. ✅ `engines_live/` é pacote com módulos < 300 linhas cada
2. ✅ Suite de testes verde (todos os existentes + novos unit + smoke)
3. ✅ Checklist E2E manual passado (abrir engine, ver instâncias, stop, restart, new, live ritual, log follow, modo switch)
4. ✅ Zero flicker visual em repaints
5. ✅ Zero regressão de cockpit_api / telegram / systemd integrations
6. ✅ Joao valida visualmente que os 8 pain points iniciais foram endereçados

Se algum critério falhar, fica pending até fixar. Sem "good enough".
