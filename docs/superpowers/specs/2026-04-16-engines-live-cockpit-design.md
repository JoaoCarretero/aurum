# ENGINES LIVE — Cockpit Redesign

**Data:** 2026-04-16
**Escopo:** redesign completo da view `EXECUTE → ENGINES LIVE` no launcher Tkinter.
**Preserva:** paleta HL2/Source Engine (`core/ui_palette.py`), core de trading (indicators/signals/portfolio/params — intocados).
**Muda:** layout, hierarquia visual, fluxo de seleção de modo, organização das engines, arquitetura do código da view.

---

## Motivação

Hoje `launcher._strategies(filter_group="LIVE")` faz tudo: filtra engines, desenha pills, lista tracks via `core/engine_picker.py` compartilhado com BACKTEST. Resultado:
- Lista flat filtrada a 3 engines (`citadel`, `live`, `janestreet`) — hardcoded em `launcher.py:8378`.
- Faixa "NOW PLAYING" é estática e separada do fluxo principal.
- Modo de execução (paper/demo/testnet/live) é escolhido via modal do `engine_picker` na chip RUN — escondido e friccional.
- Não tem hierarquia visual entre engines prontas vs em research.
- Fluxo LIVE (real money) tem atrito igual ao PAPER — perigoso.

## Objetivo

Uma view híbrida master-detail que:
1. Mostra o estado "o que tá rodando agora" de cara (cockpit).
2. Organiza engines em 3 buckets de prontidão (LIVE · READY · RESEARCH).
3. Expõe modo global (PAPER/DEMO/TESTNET/LIVE) no header, sempre visível.
4. Adiciona atrito proporcional ao risco do modo (zero em paper, ritual em live).
5. Preserva a paleta HL2/VGUI existente.
6. Extrai a view do `launcher.py` (12k linhas) pra um módulo isolado.

---

## Layout Geral

3 zonas verticais:

```
┌─────────────────────────────────────────────────────────────────┐
│ › ENGINES   PAPER · [DEMO] · TESTNET · LIVE   CRYPTO FUT  14·2 │  ← HEADER
├───────────────────────────┬─────────────────────────────────────┤
│ ▌LIVE · 2                 │                                     │
│   ● CITADEL    DEMO  2h14 │       [DETAIL PANEL — skin          │
│   ● JANESTREET PAPER 42m  │        muda por estado da           │
│                           │        seleção: LIVE / READY /       │
│ ▌READY LIVE · 3           │        RESEARCH]                     │
│   CITADEL      15m · 4.43 │                                     │
│   JANESTREET              │                                     │
│   LIVE                    │                                     │
│                           │                                     │
│ ▌RESEARCH · 11            │                                     │
│   🔒 RENAISSANCE          │                                     │
│   🔒 JUMP                 │                                     │
│   🔒 DESHAW               │                                     │
│   ...                     │                                     │
├───────────────────────────┴─────────────────────────────────────┤
│ ESC main · ▲▼ select · ENTER run · S stop · M cycle mode        │  ← FOOTER
└─────────────────────────────────────────────────────────────────┘
```

- Split horizontal 38/62 (master/detail).
- Header strip: 38px, footer: 18px, body: resto.
- Sem subtítulo extra — `h_path` já mostra contexto.

---

## Componentes

### 1. Header Strip

- `› ENGINES` em `AMBER` bold 12pt.
- Segmented global mode: 4 pills `PAPER · DEMO · TESTNET · LIVE`. Cores:
  - PAPER → `CYAN` (`#7FA0B0`) — neutro, simulação local
  - DEMO → `GREEN` (`#7FA84A`) — simulação exchange (HL2 HP)
  - TESTNET → `AMBER` (`#D08F36`) — infra real, fake money
  - LIVE → `RED` (`#C44535`) — real money
- Pill ativa: fundo da cor + texto `BG` (invertido). Inativa: fundo `BG3` + texto na cor.
- Market label à direita (`market_label` de `MARKETS[active].label`).
- Counts: `14 engines · 2 live` em `DIM`.
- Se modo ativo = LIVE, borda inferior do header ganha 1px `RED`.

### 2. Master List (coluna esquerda)

3 buckets em ordem fixa (topo → baixo):

#### LIVE · N
- Só aparece se N>0.
- Cada linha:
  - Dot `●` verde (`GREEN`, 9pt bold)
  - Nome engine (WHITE, 9pt bold)
  - Mode pill mini (cor do modo)
  - Uptime em formato compacto (`2h14m` ou `42m`)
  - PnL color-coded (`GREEN`/`RED`) se disponível
- Item viva sempre no topo do bucket LIVE.

#### READY LIVE · N
- Engines com `live_ready: True` em `config/engines.py`.
- Cada linha:
  - Nome engine (WHITE, 9pt bold)
  - Subtítulo: `{TF} · Sh {sharpe} · {tag}` (EDGE/MARG/—) em `DIM`
- Engine que tá viva **não aparece aqui** (já está no bucket LIVE).

#### RESEARCH · N
- Engines sem entrypoint live validado.
- Cada linha:
  - Ícone lock `🔒` (DIM)
  - Nome engine em `DIM`
  - Subtítulo mínimo: `{TF} · Sh {sharpe}` em `DIM2`
- Visual inteiro dim pra comunicar "read-only neste contexto".

**Separador entre buckets:** barra vertical 3px `AMBER` à esquerda + título 7pt bold `AMBER` + `· N` em `DIM`, seguido de borda horizontal 1px `BORDER`.

**Seleção:** fundo `BG3`, borda esquerda 3px `AMBER_B`, texto `WHITE`.

**Navegação:**
- `▲`/`▼`: move entre items, pula entre buckets naturalmente.
- `ENTER`: dispara ação contextual do detail panel.
- Engine em RESEARCH: `ENTER` não faz nada (ou leva pra backtest).

**Scroll:** frame scrollável. LIVE bucket sticky no topo quando usuário scrolla.

### 3. Detail Panel (coluna direita)

Dispatch por estado da seleção:

#### 3A) Seleção LIVE (cockpit)

```
┌─ CITADEL ─────────────── ● DEMO · 02h14m ──┐
│                                             │
│  PnL       POSITIONS  TRADES  LAST SIGNAL   │
│  +$124.33  2 open     47      BUY BNB 15:42 │
│  +1.2%                                      │
│                                             │
│  ─── LOG TAIL ────────── [OPEN FULL] ──     │
│  15:42:11  signal BNB long ω=0.74          │
│  15:42:12  order placed price=625.4 qty=0.8│
│  15:43:00  fill confirmed                   │
│  [...últimas 15 linhas, auto-scroll]       │
│                                             │
│  [   STOP ENGINE   ]  [ REPORTS ] [ CONFIG ]│
└─────────────────────────────────────────────┘
```

- Header do painel: nome engine em `AMBER` 11pt bold. À direita: dot verde + modo + uptime.
- KPI strip: 4 colunas fixas (PnL, Positions, Trades, Last Signal). PnL em cor por sinal. Tamanho fonte 10pt.
- Log tail: frame `BG2` + borda `BORDER`, 15 linhas últimas em `Consolas 8pt`. Cores por nível: INFO=`DIM`, SIGNAL=`AMBER`, ORDER=`CYAN`, FILL=`GREEN`, ERROR=`RED`. Auto-scroll. Botão `[OPEN FULL]` abre viewer full.
- Botões:
  - `STOP ENGINE`: fundo `RED`, 14pt bold, hold-to-confirm 1.5s (progress fill amber por cima durante hold). Keybind `S`.
  - `REPORTS`: abre `data/{engine}/{run}/reports/` no explorer ou webview.
  - `CONFIG`: mostra config ativa em modal read-only (engine rodando — não pode editar).

#### 3B) Seleção READY (pronta pra ligar)

```
┌─ CITADEL ─────────────────────────────────┐
│  Systematic momentum · fractal 5D · 11 alt│
│                                            │
│  BEST CONFIG (battery-validated):          │
│  TF 15m · Sharpe 4.43 · DD -8.1% · 256t   │
│  ROI +51% (180d walkforward)               │
│                                            │
│  CONFIG:                                   │
│    Period    [30D] [90D*] [180D] [365D]   │
│    Basket    [DEFAULT ▾]                  │
│    Leverage  [1x] [2x*] [3x] [5x]         │
│                                            │
│  ╔════════════════════════════════════╗   │
│  ║     RUN IN DEMO MODE               ║   │  ← cor do modo global
│  ╚════════════════════════════════════╝   │
│                                            │
│  [ VIEW CODE ]  [ PAST RUNS ]             │
└────────────────────────────────────────────┘
```

- Desc curta da engine em `DIM`.
- Best config block: stats validados (vem de `BRIEFINGS` + DB). Uma linha compacta. Sem best config: mostra "no battery data yet" em `DIM`.
- Config inline: 3 rows (Period / Basket / Leverage). Segmented selectors. Valor ativo = fundo `AMBER` texto `BG`.
- Botão RUN gordo (todo o width, 40px altura). Cor = cor do modo global. Texto dinâmico: `RUN IN {MODE} MODE`. Keybind `ENTER`.
- Botões secundários: `VIEW CODE` (abre `code_viewer`), `PAST RUNS` (abre DATA filtrado pela engine).

**Modo LIVE — confirmação ritual:**
Click/ENTER com mode=LIVE → modal:
```
┌─ LIVE EXECUTION — CITADEL ─────────────────┐
│                                             │
│  Você está prestes a ligar a engine CITADEL │
│  em modo LIVE (real money, real orders).    │
│                                             │
│  Digite CITADEL pra confirmar:              │
│  [________________________]                 │
│                                             │
│  [ CANCEL ]           [ CONFIRM & RUN ]     │
└─────────────────────────────────────────────┘
```
- Botão CONFIRM desabilitado até input = nome da engine (case-sensitive).
- CANCEL ou ESC fecha sem rodar.
- Ao confirmar: chama `_exec_live_inline(name, script, desc, "live", cfg)` igual hoje.

#### 3C) Seleção RESEARCH (backtest only)

```
┌─ RENAISSANCE ─────────── [ RESEARCH ONLY ] ─┐
│  Pattern recognition · harmonic geometry    │
│                                             │
│  BACKTEST KPIs:                             │
│  TF 4h · Sharpe 2.1 · DD -12% · 142 trades │
│                                             │
│  ⚠  Essa engine ainda não tem entrypoint   │
│     live validado.                          │
│     Rode em backtest:                       │
│     EXECUTE → BACKTEST → RENAISSANCE        │
│                                             │
│  [ GO TO BACKTEST ]  [ VIEW CODE ]          │
└─────────────────────────────────────────────┘
```

- Header tem badge `[ RESEARCH ONLY ]` em `HAZARD` (`#E8C87A`).
- Sem botão RUN. Sem config inline.
- Nota em `HAZARD` explicando por quê. Não é erro — é barreira protetora.
- `GO TO BACKTEST` pula pra `_strategies_backtest()` com seleção pré-aplicada.

### 4. Footer

- Keybinds dinâmicos segundo estado:
  - Idle/Ready: `ESC main · ▲▼ select · ENTER run · M cycle mode`
  - Live selecionada: `ESC main · ▲▼ select · S stop · L open log · M cycle mode`
  - Research: `ESC main · ▲▼ select · B backtest · M cycle mode`
- Se mode=LIVE ativo: bloco extra `⚠ LIVE MODE — real orders will be placed` em `RED` 8pt.

---

## Fluxo de Mode Switcher

- Estado: `self._engines_live_mode` ∈ {"paper","demo","testnet","live"}.
- Default: "paper" na primeira carga; depois persiste em `data/ui_state.json` (chave `engines_live.mode`).
- Trocar: clique na pill ou keybind `M` (cicla paper → demo → testnet → live → paper).
- Trocar modo **não afeta engines vivas** — elas continuam no modo delas. Só muda o default do próximo RUN. Toast no footer por 3s: `mode changed to {MODE} — affects next run only`.
- LIVE ativo: header ganha linha vermelha 1px inferior + footer com warn bar.

---

## Paleta

**Nada novo em hex.** Aliases semânticos novos em `core/ui_palette.py`:

```python
# Mode colors (semantic aliases)
MODE_PAPER    = CYAN      # neutral — local sim
MODE_DEMO     = GREEN     # safe — exchange sim
MODE_TESTNET  = AMBER     # warning — real infra, fake money
MODE_LIVE     = RED       # danger — real money
```

Uso de tokens por elemento (mapa canônico):

| Elemento | Token |
|---|---|
| Fundo tela | `BG` |
| Cards / detail panel | `PANEL` + borda `BORDER` |
| Card selecionado | borda esquerda 3px `AMBER_B` |
| Bucket separator | barra 3px `AMBER` + título `AMBER` 7pt |
| Texto primário | `WHITE` |
| Metadado | `DIM` / `DIM2` |
| Engine viva (dot) | `GREEN` |
| PnL +/− | `GREEN` / `RED` |
| Research (lock + texto) | `DIM` |
| Hazard / warning | `HAZARD` |
| Botão STOP | fundo `RED` + texto `WHITE` |
| Botão RUN | fundo `MODE_{current}` + texto `BG` |
| Log INFO/SIGNAL/ORDER/FILL/ERROR | `DIM`/`AMBER`/`CYAN`/`GREEN`/`RED` |

---

## Arquitetura do Código

### Novo módulo: `launcher_support/engines_live_view.py`

Função pública:
```python
def render(launcher, parent, *, on_escape) -> dict:
    """Monta a view ENGINES LIVE. Retorna handle com:
    - refresh()           # re-renderiza após mudança de estado
    - cleanup()           # cancel after-callbacks
    - set_mode(mode)      # troca modo global programaticamente
    """
```

Internas (todas privadas ao módulo):
- `_build_header(parent, launcher, state)` → frame header
- `_build_master_list(parent, tracks, state, callbacks)` → frame esquerda
- `_render_bucket(parent, kind, tracks, state, callbacks)` → bucket individual
- `_build_detail(parent, selected, state, callbacks)` → dispatch
- `_render_detail_live(parent, track, proc, callbacks)`
- `_render_detail_ready(parent, track, state, callbacks)`
- `_render_detail_research(parent, track, callbacks)`
- `_build_footer(parent, state)` → keybinds hint bar
- `_confirm_live_modal(parent, engine_name, on_confirm)` → modal LIVE
- `_cycle_mode(state)` / `_persist_mode(mode)` / `_load_mode()`
- `_log_tail_poller(text_widget, proc)` → pull últimas N linhas do log da proc

### Mudança em `config/engines.py`

Adicionar campo `live_ready: bool` ao dicionário:
```python
ENGINES = {
    "citadel":     {"script": ..., "display": ..., "desc": ..., "live_ready": True},
    "janestreet":  {"script": ..., "display": ..., "desc": ..., "live_ready": True},
    "live":        {"script": ..., "display": ..., "desc": ..., "live_ready": True},
    "renaissance": {"script": ..., "display": ..., "desc": ..., "live_ready": False},
    ...
}

LIVE_READY_SLUGS = {k for k, v in ENGINES.items() if v.get("live_ready")}
```

Elimina o hardcode em `launcher.py:8378`.

### Mudança em `launcher.py`

`_strategies_live()` vira:
```python
def _strategies_live(self):
    self._clr(); self._clear_kb()
    self.h_path.configure(text="> ENGINES")
    self._bind_global_nav()
    from launcher_support import engines_live_view
    self._engines_live_handle = engines_live_view.render(
        self, self.main, on_escape=lambda: self._menu("main")
    )
```

~8 linhas vs. ~200 linhas hoje. O `_strategies()` flat-list com `filter_group="LIVE"` pode ser **removido**, porque essa view substitui. `_strategies_backtest()` continua usando o `engine_picker.py` compartilhado — intocado.

### Reuso do que já existe

- `core.proc.list_procs()` / `stop_proc()` — pra estado "vivo" e stop. Sem mudança.
- `self._exec_live_inline(name, script, desc, mode, cfg)` — já existe no launcher, continua sendo o entrypoint real de execução.
- `BRIEFINGS` dict — pra best_config stats. Sem mudança.
- `data/aurum.db runs table` — pra DB-hydrated metrics. Sem mudança.
- `code_viewer.CodeViewer` — pra botão VIEW CODE. Sem mudança.

### Estado persistido

`data/ui_state.json` (já existe ou criar):
```json
{
  "engines_live": {
    "mode": "paper",
    "last_selected_slug": "citadel",
    "config_defaults": {
      "citadel": {"period": "90", "basket": "", "leverage": "2.0"}
    }
  }
}
```

Load no `render()`, save no toggle/select/config change. Usa `core.persistence.atomic_write_json`.

---

## Fora de escopo (não mexer)

- `core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py` — CORE protegido.
- `core/engine_picker.py` — continua sendo usado pelo BACKTEST view, intocado.
- `_strategies_backtest()` — intocado.
- `engines/*.py` — nenhuma mudança em lógica de trading.
- `core/proc.py` — nenhuma mudança no process manager.
- `bot/telegram.py` — nenhuma integração nova aqui.

---

## Critérios de sucesso

1. Entrar em EXECUTE → ENGINES LIVE mostra a nova view com 3 buckets.
2. Sem engine rodando: bucket LIVE não aparece, foco inicial em primeira engine de READY.
3. Com engines rodando: bucket LIVE aparece no topo, primeira engine viva fica selecionada.
4. Pill mode clicável + keybind `M` cicla. Mudança persiste entre sessões.
5. RUN em mode=LIVE abre modal de confirmação por nome.
6. RUN em paper/demo/testnet sai direto pro `_exec_live_inline`.
7. Selecionar engine RESEARCH mostra painel sem RUN + nota em hazard.
8. STOP funciona com hold-to-confirm 1.5s.
9. Log tail atualiza em tempo real (poll 1s) quando engine viva selecionada.
10. Paleta inalterada — zero `#hex` novo, só aliases semânticos.
11. `launcher.py` fica menor (remoção do bloco LIVE do `_strategies`).

---

## Próximos passos

1. Usuário aprova este spec.
2. Invocar skill `writing-plans` pra gerar plano de implementação step-by-step com checkpoints de review.
3. Executar plano em subagents paralelos quando possível (ex: `engines_live_view.py` + `config/engines.py` em paralelo, launcher.py depois).
4. Smoke test manual: EXECUTE → ENGINES LIVE em cada modo, com/sem engine viva.
