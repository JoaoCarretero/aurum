# Launcher Main Menu — Bloomberg 3D Redesign

**Date:** 2026-04-11
**Author:** Joao + Claude
**Status:** Draft — awaiting user review
**Target file:** `launcher.py` (specifically `_menu("main")` at line 1033)

---

## 1. Motivação

O menu principal atual (`_menu("main")`) mostra 9 itens planos sobre uma
espiral de Fibonacci. Funciona, mas:

- Os 9 destinos são hierarquicamente heterogêneos (MARKETS é quote board;
  COMMAND CENTER é infra). Apresentá-los no mesmo nível achata a intenção.
- O overlay de Fibonacci é decorativo, não funcional — não guia a leitura.
- Nenhum dado vivo aparece no menu; o usuário entra "no escuro".
- A identidade visual do projeto ("o disco lê a si mesmo", CD + laser) está
  no splash mas desaparece quando o menu principal entra.

O redesign agrupa os 9 destinos em **4 tiles Bloomberg-style isométricos**
arranjados em torno de um **CD central** que representa a leitura do mercado
pelo AURUM. Cada tile mostra live mini-data e se expande in-place quando
selecionado.

---

## 2. Filosofia de design

**Tudo converge no disco.** Os 4 tiles são setores do CD; o CD central é o
core do sistema; o laser é a seleção do usuário. Quando o usuário seleciona
um tile, o laser "lê" aquele setor (flash no spoke correspondente) e o tile
expande. A metáfora é consistente com CLAUDE.md ("O disco lê a si mesmo. O
universo roda em um CD. AURUM é o laser.").

Estética: Bloomberg Terminal encontrando iPod Classic. Tiles em ASCII
isométrico sobre canvas Tk, cores Bloomberg distintas por grupo, navegação
hierárquica iPod-style (1-4 direto, setas + ENTER, ESC volta).

---

## 3. Arquitetura visual

### 3.1 Layout (2×2 + CD central)

```
  ┌─────────────────────────────────────────────┐
  │  AURUM FINANCE       O DISCO LÊ A SI MESMO  │
  │  > PRINCIPAL              READY             │
  ├─────────────────────────────────────────────┤
  │                                             │
  │   ╱─MARKETS─╲              ╱─EXECUTE─╲      │
  │  ╱   [1]    ╲             ╱    [2]   ╲      │
  │ │ BTC 64.2k  │╲          ╱│ procs 3   │     │
  │ │ ETH 3.14k  │ ╲        ╱ │ pnl +2.1% │     │
  │ │ 11 pairs   │  ╲      ╱  │ 4 pos     │     │
  │ │ MACRO BULL │   ╲····╱   │ risk 2/5  │     │
  │  ╲__________╱    ╲  ╱      ╲_________╱      │
  │        ╲          ╲╱          ╱             │
  │         ╲       ╱────╲       ╱              │
  │          ╲     ╱ ◉◉◉ ╲      ╱               │
  │           ╲   │ AURUM │    ╱                │
  │            ╲  │ LASER │   ╱                 │
  │             ╲ │◉ φ ◉  │  ╱                  │
  │              ╲╲◉◉◉◉◉╱╱                      │
  │               ╲    ╱                        │
  │        ╱      ╱··╲      ╲                   │
  │   ╱─RESEARCH╲╱    ╲╱─CONTROL─╲              │
  │  ╱    [3]   ╱      ╲   [4]   ╲              │
  │ │ CITA 1.8  │       │ conn 4/5 │            │
  │ │ 42 runs   │       │ cpu 32%  │            │
  │ │ HMM idle  │       │ tg ONLINE│            │
  │  ╲_________╱         ╲________╱             │
  │                                             │
  │  φ                                         φ│
  ├─────────────────────────────────────────────┤
  │  1-4 direct · ← ↑ ↓ → nav · ENTER · ESC sai │
  └─────────────────────────────────────────────┘
```

- **Header:** chrome existente (`h_path`, `h_stat`), tagline no topo
  direito: "O DISCO LÊ A SI MESMO".
- **4 tiles isométricos:** desenhados em Canvas via `create_line` +
  `create_polygon`. Cada tile é um cubo truncado visto do topo-esquerda:
  linha superior `╱───╲`, tampa `╱___╱`, paredes laterais. O 3D é fake
  (offset diagonal) — não há gradiente.
- **CD central:** reuso adaptado de `_cd_draw()` (linha 961). Diâmetro
  ~140px, gira 1 passo por tick de 200ms (já é o cadence de `_tick`).
- **4 spokes:** linhas pontilhadas do centro de cada tile até o CD. DIM2
  em estado idle; pulsam na cor do tile focado.
- **2 `φ` pequenos** nos cantos inferiores (easter egg, resquício do
  design Fibonacci anterior).
- **Footer:** chrome existente (`f_lbl`) com novo texto de ajuda.

### 3.2 Mapeamento 9→4

Zero destinos são perdidos. Apenas agrupamento visual; os submenus atuais
continuam acessíveis via drill-down.

```
MARKETS   [1]  AMBER    #ff8c00
  └─ 1  QUOTE BOARD       → _markets()
  └─ 2  CRYPTO DASH       → _crypto_dashboard()

EXECUTE   [2]  GREEN    #00c864
  └─ 1  STRATEGIES        → _strategies()     (backtest + live)
  └─ 2  ARBITRAGE         → _arbitrage_hub()
  └─ 3  RISK              → _risk_menu()

RESEARCH  [3]  CYAN     #33aaff
  └─ 1  TERMINAL          → _terminal()       (charts/macro)
  └─ 2  DATA              → _data_center()    (backtests/logs)

CONTROL   [4]  MAGENTA  #c864c8
  └─ 1  CONNECTIONS       → _connections()
  └─ 2  COMMAND CENTER    → _command_center()
  └─ 3  SETTINGS          → _config()
```

`MAIN_MENU` (linha 98 de `launcher.py`) **não é removido** — permanece como
fonte de labels/descrições e fallback. Nova constante `MAIN_GROUPS` é
adicionada como fonte de verdade para o render 2×2.

---

## 4. Interação

### 4.1 Estados

- **Idle:** CD gira, 4 tiles DIM (30% de sua cor), spokes DIM2, live-data
  aparece nos tiles mas sem destaque.
- **Focus (hover ou teclado):** tile focado pinta borda na cor cheia, label
  em AMBER_B (brilho), spoke correspondente pulsa na cor do tile, laser do
  CD aponta para o setor do tile.
- **Selected (ENTER ou 1-4):** flash curto (200ms) no spoke cor cheia, CD
  "lê" (arco do setor ilumina), tile expande in-place.

### 4.2 Drill-down (tile expand in-place)

- Os outros 3 tiles + CD fazem fade-out em 150ms (alpha decrescente via
  redraw em tons progressivamente DIM).
- O tile focado cresce até ~80% da tela.
- Dentro do tile expandido, sub-menu vertical iPod-style: 2-3 itens
  numerados, item 1 pré-selecionado, `↓`/`↑` navega, `1`/`2`/`3` atalho
  direto, ENTER confirma, ESC colapsa de volta.
- Selecionar um sub-item chama a função de destino existente
  (`_markets()`, `_strategies()`, etc).
- ESC ou `0` no tile expandido colapsa de volta para o grid 2×2.

### 4.3 Keybinds

```
1-4       → foca tile + auto-enter (expande)
↑ ↓ ← →   → foca tile vizinho (grid 2×2 cyclic)
TAB       → próximo tile (cyclic)
ENTER     → expande o tile focado
ESC       → se expandido: colapsa; se grid: volta ao splash
BackSpace → alias de ESC (comportamento existente)
H         → hub global (comportamento existente)
Q         → quit (comportamento existente)
```

---

## 5. Live data por tile

Dois ticks distintos:

- **Render tick = 200ms** (já é o `_tick()` existente). CD gira, hover
  pulse, redraws leves.
- **Data refresh tick = 5s** (novo, via `self.after(5000, …)` ou contador
  no `_tick`). Dispara `_menu_live_fetch_async()` em thread separada; o
  fetch atualiza `self._menu_live` e agenda um redraw parcial dos tiles.

Cada fetch roda em `threading.Thread` com try/except amplo; qualquer falha
mostra `—` no lugar do valor e não propaga.

Cache local: `self._menu_live = {'markets': {...}, 'execute': {...}, ...}`.
O render lê do cache; o fetch atualiza o cache. Render nunca bloqueia em
I/O.

### 5.1 Tiles

**MARKETS** (AMBER)
```
linha 1: BTC {last}k               binance ticker BTCUSDT
linha 2: ETH {last}k               binance ticker ETHUSDT
linha 3: {N} pairs                 len(UNIVERSE) de config.params
linha 4: MACRO {tag}               core.portfolio.detect_macro()
fallback: "— / — / — / —"
```

**EXECUTE** (GREEN)
```
linha 1: procs {N}                 core.proc.list_active()
linha 2: pnl {±x.x%}                config/paper_state.json day_pnl
linha 3: {N} pos                   config/paper_state.json open_positions
linha 4: risk {gates_open}/5       config/risk_gates.json active gates
fallback: "procs 0 / — / — / —"
```

**RESEARCH** (CYAN)
```
linha 1: last {ENGINE}             último run de data/index.json
linha 2: sharpe {x.x}              último report.json
linha 3: {N} runs                  count de data/index.json
linha 4: HMM {active/idle}         core.chronos state
fallback: "no runs yet"
```

**CONTROL** (MAGENTA)
```
linha 1: conn {up}/{total}         config/connections.json ping cache
linha 2: uptime {Hh}{Mm}           time.monotonic() - self._start_t
linha 3: tg {ONLINE/OFFLINE}       bot.telegram heartbeat
linha 4: vps {UP/DOWN}             ssh ping cache
fallback: "— / — / —"
```

**Nota stdlib-only:** O projeto não usa `psutil` (nenhum import no repo) e a
convenção é não adicionar dependências novas. Qualquer métrica system-level
deve usar stdlib (`shutil.disk_usage`, `time.monotonic`, `os.stat`) ou ser
removida. CPU% foi trocado por uptime do launcher por isso.

### 5.2 Regras de falha

- Qualquer fetch com exceção → registra `—` e segue.
- Nenhuma rota bloqueante no render path.
- Offline total → menu ainda renderiza, só com `—` em todas as linhas.
- psutil, binance API, telegram: todos com timeout curto (≤2s).

---

## 6. Implementação

### 6.1 Constantes (topo de `launcher.py`, ~linha 35)

```python
TILE_MARKETS  = "#ff8c00"   # AMBER (alias do atual)
TILE_EXECUTE  = "#00c864"   # GREEN
TILE_RESEARCH = "#33aaff"   # CYAN
TILE_CONTROL  = "#c864c8"   # MAGENTA
TILE_DIM_FACTOR = 0.3       # brilho em estado idle

MAIN_GROUPS = [
    # (label, key_num, color, [submenu_children_in_order])
    ("MARKETS",  "1", TILE_MARKETS,
        [("QUOTE BOARD", "_markets"),
         ("CRYPTO DASH", "_crypto_dashboard")]),
    ("EXECUTE",  "2", TILE_EXECUTE,
        [("STRATEGIES", "_strategies"),
         ("ARBITRAGE",  "_arbitrage_hub"),
         ("RISK",       "_risk_menu")]),
    ("RESEARCH", "3", TILE_RESEARCH,
        [("TERMINAL", "_terminal"),
         ("DATA",     "_data_center")]),
    ("CONTROL",  "4", TILE_CONTROL,
        [("CONNECTIONS", "_connections"),
         ("COMMAND",     "_command_center"),
         ("SETTINGS",    "_config")]),
]
```

`MAIN_MENU` continua no arquivo (compat histórico + descrições longas).

### 6.2 Novos métodos (na classe `App`)

```
_menu_main_bloomberg()      Render principal: 2×2 grid + CD + spokes
_menu_tile_render(canvas,   Desenha 1 tile isométrico no canvas
    tile_idx, state)        state ∈ {idle, focus, expanding}
_menu_tile_focus(idx)       Troca foco pro tile idx (0-3)
_menu_tile_expand(idx)      Anima fade-out + expansão do tile
_menu_tile_collapse()       Volta do expandido pro grid 2×2
_menu_sub_render(tile_idx)  Desenha sub-menu iPod dentro do tile expandido
_menu_sub_select(tile_idx,
    sub_idx)                Chama a função de destino
_menu_live_fetch_async()    Thread: atualiza self._menu_live
_menu_live_apply()          Main thread: lê cache, redraw tiles
_menu_cd_center(canvas,     Reuso adaptado de _cd_draw
    cx, cy, r)
_menu_spokes(canvas,
    focus_idx)              Desenha as 4 linhas tile↔CD
```

### 6.3 Mudanças cirúrgicas em `_menu()`

- `_menu("main")`: delega a `_menu_main_bloomberg()`.
- O bloco Fibonacci (linhas 1073-1129) é removido. Mantém o `φ` nos cantos.
- O bloco de submenu (linhas 1173-1230, key != "main") **não muda** — o
  drill-down expandido in-place NÃO substitui os submenus existentes; ele
  cria uma camada nova, e cada sub-item do tile expandido ainda rota para
  os destinos usuais (`_markets`, `_strategies`, etc).

### 6.4 Canvas-first

Todo o render do grid 2×2 acontece em **um único `tk.Canvas`** (full-frame).
Tiles, spokes, CD, texto — tudo via `create_line`/`create_polygon`/`create_oval`/
`create_text`. Redraw parcial: hover só redesenha o tile afetado (não a tela toda).

### 6.5 O que NÃO muda

- `_splash`, `_cd_draw`, `_chrome`, `_tick`, `_kb`, `_bind_global_nav`.
- Submenus `backtest`, `live`, briefings, `_brief`, `_config_backtest`,
  `_config_live`.
- Telas terminais (`_markets`, `_terminal`, `_data_center`, `_arbitrage_hub`,
  `_risk_menu`, `_config`, `_connections`, `_command_center`,
  `_strategies`, `_crypto_dashboard`).
- `config/params.py`, qualquer lógica de trading.

### 6.6 Compat e rollback

- Flag de ambiente `AURUM_MENU_STYLE=legacy` (lido em `_menu("main")`)
  cai de volta no render Fibonacci antigo. Default = `bloomberg`.
- Nenhuma migração necessária; o menu é stateless.

---

## 7. Testes & validação

### 7.1 Smoke

```bash
python smoke_test.py --quiet
```
Deve continuar passando 156/156 (o menu não toca em nada de trading).

### 7.2 Manual

1. `python launcher.py` → splash → ENTER → ver grid 2×2 + CD central.
2. Teclar `1` → MARKETS expande in-place → sub-menu `QUOTE BOARD` /
   `CRYPTO DASH`.
3. ESC → colapsa → teclar `2` → EXECUTE expande → 3 sub-itens.
4. Setas `← ↑ ↓ →` no grid → ver foco mudar, spoke pulsar, label brilhar.
5. Ver live-data atualizar a cada 5s (trocar de janela e voltar).
6. Desligar net → ver fallbacks `—` aparecerem em MARKETS/CONTROL sem
   crash; RESEARCH/EXECUTE (dados locais) continuam populados.
7. ESC no grid → volta pro splash.
8. Voltar do splash → grid volta ao estado idle correto (sem foco
   persistente indevido).

### 7.3 Regressão visual

- Tirar screenshot do `_brief`, `_config_backtest`, `_arbitrage_hub`,
  `_data_center` antes e depois. Devem ser idênticos.

### 7.4 Kill path

- Setar `AURUM_MENU_STYLE=legacy` e rodar launcher. Menu antigo aparece.
  Feature flag funciona.

---

## 8. Escopo — o que fica de fora

- Nenhuma mudança em engines, sinais, custos, sizing, risco.
- Nenhum refactor em `_splash`, `_cd_draw`, ou qualquer submenu.
- Nenhuma mudança em `MAIN_MENU` como estrutura (apenas adição de
  `MAIN_GROUPS`).
- Nenhum novo módulo fora de `launcher.py` — toda a mudança é local.
- Som / áudio / animações complexas: fora de escopo.
- Mouse drag / gestures: fora de escopo (teclado + click simples).

---

## 9. Riscos

| Risco | Mitigação |
|---|---|
| Canvas pesado em redraw 5s | Redraw parcial por tile; CD gira em seu próprio rect |
| Fetch travando UI | Thread separada, timeouts curtos, fallback `—` |
| Quebrar navegação existente | Feature flag `AURUM_MENU_STYLE=legacy` |
| ASCII isométrico ilegível em fonte diferente | Forçar Consolas (FONT atual) no canvas |
| Expansão in-place confunde usuário | ESC colapsa; footer sempre mostra "ESC sai" |

---

## 10. Sucesso

- Menu principal mostra 4 grupos claros com live-data.
- Todos os 9 destinos originais continuam acessíveis em ≤2 teclas.
- Smoke 156/156.
- Feature flag legacy funciona.
- Visual coerente com a filosofia do CD/laser.
- Offline: menu não trava, mostra `—`.
