# Arbitrage Hub — HL2 + Bloomberg Minimalist Redesign

**Date:** 2026-04-12
**Author:** Joao + Claude
**Status:** Draft — awaiting user review
**Target file:** `launcher.py` (`_arbitrage_hub` method, around line 2785)
**Sub-project of:** Arbitrage redesign backlog (5-phase plan, this is phase A — hub UI polish only)

---

## 1. Motivação

O hub de arbitragem atual (`_arbitrage_hub`) é um menu MP3-style minimalista com 3 linhas selecionáveis apenas por teclado (C/D/X ou setas+Enter). A UI não é clicável e não segue o padrão visual que evoluímos pro launcher (splash HL1, main menu Fibonacci). O João pediu para ficar "profissional como os outros e clicável" com vibe "Half Life 2".

Este spec cobre **só a camada visual/interativa do hub** (fase A da decomposição). Não toca em:
- `core/funding_scanner.py` (fase C — novas venues)
- Filtros ou dados novos (fase B)
- Novos tipos de arbitragem (fase D)
- Execução real (fase E)

Fases B–E são specs futuros, escritos após A ficar verde e mergeado.

---

## 2. Filosofia

Half Life 2 + Bloomberg Terminal. HL2 é minimalista, austero, espaço negativo como arma — o oposto do HL1 gritty do splash. Bloomberg Terminal é denso mas organizado, com cores sparse que chamam atenção. A interseção: UI institucional limpa, sem decoração, hierarquia forte por tamanho e cor, hover/click como única forma de interagir. Sem warning stripes. Sem ASCII art. Sem CRT scanlines. Só tipografia e cor.

Tres linhas grandes, clicáveis, com info suficiente pra decidir sem abrir. "Click row to enter" — o resto é silêncio.

---

## 3. Arquitetura visual

### 3.1 Layout

```
┌───────────────────────────────────────────────────┐
│  AURUM · ARBITRAGE DESK          12:34:56 UTC     │ ← header y 0..40
├───────────────────────────────────────────────────┤
│                                                   │
│                                                   │
│       A R B I T R A G E                           │ ← title y 80..140
│       ────────────                                │
│       funding · basis · spread                    │
│                                                   │
│                                                   │
│   ●  CEX ↔ CEX                     JANE ST        │ ← row 1 y 200..280
│      execution · top 12.3% APR · 24 pairs         │
│                                                   │
│   ●  DEX ↔ DEX                     3 VENUES       │ ← row 2 y 290..370
│      observation · best 45.2% · dydx              │
│                                                   │
│   ●  CEX ↔ DEX                     8 VENUES       │ ← row 3 y 380..460
│      observation · best 89.1% · hyperliquid       │
│                                                   │
│                                                   │
│       ───────────────────                         │
│       click row · C D X direct · ESC back         │ ← footer
│                                                   │
└───────────────────────────────────────────────────┘
```

### 3.2 Typography

| Elemento | Fonte | Tamanho | Cor | Peso |
|---|---|---|---|---|
| Header label ("AURUM · ARBITRAGE DESK") | Consolas | 8 | DIM | normal |
| Header clock | Consolas | 8 | DIM | bold |
| Title ("A R B I T R A G E") | Consolas | 18 | AMBER | bold |
| Title rule | — | 1px | AMBER_D | — |
| Subtitle ("funding · basis · spread") | Consolas | 8 | DIM | normal |
| Row bullet ("●") | Consolas | 14 | per-row color | bold |
| Row label ("CEX ↔ CEX") | Consolas | 14 | WHITE (idle), AMBER (hover) | bold |
| Row right-meta ("JANE ST") | Consolas | 10 | AMBER | bold |
| Row sub-line | Consolas | 8 | DIM | normal |
| Footer rule | — | 1px | AMBER_D | — |
| Footer text | Consolas | 7 | DIM2 | normal |

### 3.3 Cores por linha

| Row | Bullet cor idle | Bullet cor focus |
|---|---|---|
| CEX ↔ CEX (Jane Street, execution) | AMBER | AMBER_B |
| DEX ↔ DEX (observation) | AMBER | AMBER_B |
| CEX ↔ DEX (observation) | AMBER | AMBER_B |

Nota: os 3 ficam na mesma cor base (AMBER) — a diferenciação vem do texto à direita e da sub-line, não do bullet. HL2-style: cor é usada sparse.

### 3.4 Hover e click

- **Idle**: row bg = BG, label fg = WHITE, bullet fg = AMBER, sub-line fg = DIM.
- **Hover**: row bg = BG3, label fg = AMBER, bullet fg = AMBER_B, sub-line fg = AMBER_D.
- **Click**: chama `self._arb_hub_pick(idx)` (método já existente — faz `getattr` para o destino).
- **Cursor**: `hand2` nas 3 rows, cursor normal fora.

### 3.5 Espaçamento

- Canvas/Frame total: 920×640 (mesmo bounding do splash e main menu).
- Header bar: y 0..40 (40px).
- Espaço reservado entre header e title: 40px.
- Title + subtitle: y 80..140 (60px).
- Espaço entre title e rows: 60px.
- Rows: 80px each, centered horizontally. Row 1 y 200..280, row 2 y 290..370, row 3 y 380..460. 10px gap entre rows.
- Rule + footer: y 530..580.
- Bottom margin: 60px.

---

## 4. Interação

### 4.1 Keybinds

| Key | Ação |
|---|---|
| `<Button-1>` em row | `_arb_hub_pick(row_idx)` |
| `<Enter>` (mouse) em row | hover highlight |
| `<Leave>` (mouse) em row | remove hover |
| `<Key-c>` | `_arb_hub_pick(0)` (preservado) |
| `<Key-d>` | `_arb_hub_pick(1)` (preservado) |
| `<Key-x>` | `_arb_hub_pick(2)` (preservado) |
| `<Up>` / `<Down>` | move cursor teclado (preservado) |
| `<Return>` / `<space>` | pick current cursor row (preservado) |
| `<Escape>` | `_menu("main")` (preservado) |

### 4.2 Fluxo

O hub continua sendo chamado pelo main menu (atual: `_menu("main")` → escolha "ARBITRAGE" → `_arbitrage_hub()`). Sem mudança no upstream. Os destinos também são os mesmos:

- CEX ↔ CEX → `_alchemy_enter()` (Jane Street cockpit, já existe)
- DEX ↔ DEX → `_funding_scanner_screen("dex-dex")`
- CEX ↔ DEX → `_funding_scanner_screen("cex-dex")`

Nada nesses destinos muda neste spec.

---

## 5. Live data por row

### 5.1 Fonte

Todos os dados vêm do `FundingScanner` (`core/funding_scanner.py`), que já roda em background via `_arb_hub_scan_async()` (método existente). Esse método já retorna:
- `stats` (venues online por tipo, total perps)
- `top` (melhor oportunidade single-venue)
- `arb_dd` (melhores spreads DEX-DEX, filtrados)
- `arb_cd` (melhores spreads CEX-DEX, filtrados)

Tudo cached (CACHE_TTL=30s). Chamada barata.

### 5.2 Mapeamento por row

**Row 1 — CEX ↔ CEX (Jane Street)**
- Meta right: `"JANE ST"` (hardcoded, sempre)
- Sub-line: `"execution · top X.X% APR · N pairs"` onde:
  - top APR: se existir `top` do scanner e for CEX, usa `top.apr`; senão `—`
  - N pairs: contagem do universo de execução Jane Street (hardcoded default "24 pairs" por ora; pode ser parametrizado depois)
- Fallback: `"execution · — · —"`

**Row 2 — DEX ↔ DEX**
- Meta right: `"{dex_on} VENUES"` (dex_on vem de `stats["dex_online"]`)
- Sub-line: `"observation · best X.X% · {venue}"` do primeiro `arb_dd` entry; se vazio `"observation · — · —"`
- Fallback: `"observation · — · —"`

**Row 3 — CEX ↔ DEX**
- Meta right: `"{dex_on + cex_on} VENUES"` (total envolvido)
- Sub-line: `"observation · best X.X% · {venue}"` do primeiro `arb_cd`; se vazio `"observation · — · —"`
- Fallback: `"observation · — · —"`

### 5.3 Refresh

O `_arb_hub_scan_async()` já é disparado no render. Neste spec **não adicionamos auto-refresh recorrente** — o usuário está no hub por poucos segundos, os dados são ilustrativos, e o cache do scanner é de 30s. Se o usuário permanecer >30s e recarregar (ex: voltando do submenu), o próximo scan atualiza naturalmente.

YAGNI: sem timer recorrente no hub.

---

## 6. Implementação

### 6.1 Arquivo e método

- Arquivo: `launcher.py`
- Método: `_arbitrage_hub` (linha ~2785)
- Helpers novos no `App` class:
  - `_arb_hub_row_render(row_idx, focused, live)` — pinta uma linha
  - `_arb_hub_repaint()` — já existe, será atualizado
  - `_arb_hub_hover_enter(row_idx)` — novo
  - `_arb_hub_hover_leave(row_idx)` — novo

O método `_arb_hub_pick` (destinos), `_arb_hub_move` (cursor), `_arb_hub_scan_async` (live data), `_arb_hub_telem_update` permanecem — o telemetry strip morre, substituído pelos dados in-row.

### 6.2 Frame-based (não canvas)

Diferente do splash HL1 (que usou canvas único), este hub usa `tk.Frame` com rows separadas, porque:
- 3 rows clicáveis com hover são triviais com Frame + `cursor="hand2"` + `<Enter>/<Leave>/<Button-1>` binds por row.
- Canvas exigiria hit-testing manual em coordenadas — mais código, mais bugs.
- HL2 não tem decoração complexa que justifique canvas.

Layout:
```
tk.Frame (outer)
  ├── header_frame (40px)
  │     ├── label "AURUM · ARBITRAGE DESK"
  │     └── clock label
  ├── title_frame (100px)
  │     ├── title "A R B I T R A G E"
  │     ├── rule (1px amber)
  │     └── subtitle "funding · basis · spread"
  ├── rows_frame
  │     ├── row_frame[0] (80px)
  │     ├── row_frame[1] (80px)
  │     └── row_frame[2] (80px)
  └── footer_frame (40px)
        ├── rule (1px amber_d)
        └── hint "click row · C D X direct · ESC back"
```

### 6.3 Row frame structure

Cada `row_frame[i]` é um `tk.Frame` com:
- 4 child labels packed horizontalmente:
  - bullet label ("●", width 3, anchor "center")
  - big label ("CEX ↔ CEX", anchor "w", width 16)
  - spacer (expand=True)
  - right-meta label ("JANE ST", anchor "e")
- Abaixo, um segundo `tk.Frame` com 1 sub-line label ("execution · ...").
- Hover binds no row_frame E todos os child labels (Tkinter não propaga hover entre widgets).

### 6.4 Live data injection

Após `_arb_hub_scan_async` completar, o callback `_arb_hub_telem_update` passa a chamar `_arb_hub_repaint_with_live(stats, top, arb_dd, arb_cd)`. Este novo método:
1. Re-calcula os 3 sub-lines usando os mapeamentos da seção 5.2.
2. Atualiza os labels existentes via `label.configure(text=...)`.
3. Não reconstrói o Frame — só muda texto.

`_arb_hub_telem_update` existe hoje e mostra uma strip no topo. Remove a strip, joga os dados nas sub-lines.

### 6.5 Remoção do telemetry strip

A linha `self._arb_hub_telem` (topo do hub atual) sai. Os dados vão pras sub-lines das rows. Menos ruído, mais contexto.

### 6.6 O que NÃO muda

- `_alchemy_enter`, `_funding_scanner_screen`, `_arb_hub_pick`, `_arb_hub_move`, `_arb_hub_scan_async`.
- `core/funding_scanner.py`, `engines/arbitrage.py`, todo o backend.
- `_ARB_HUB_ITEMS` constant (mesma estrutura, só visual muda).
- Keybinds existentes (C/D/X/arrows/Enter/Esc).

---

## 7. Testes

### 7.1 Unit

`tests/test_launcher_main_menu.py` (existe) — adicionar:

- `test_arbitrage_hub_renders_with_3_rows` — chama `app._arbitrage_hub()`, verifica que 3 row_frames existem (via `winfo_children` do `rows_frame`).
- `test_arbitrage_hub_pick_dispatches` (já pode existir) — monkey-patches `_alchemy_enter`, chama `_arb_hub_pick(0)`, verifica chamada.
- `test_arbitrage_hub_hover_state` — chama `_arb_hub_hover_enter(1)`, verifica que row 1 está com label AMBER (ou via state attribute).

### 7.2 Smoke

`smoke_test.py` já tem `_arbitrage_hub` na cobertura — confirmar que ainda passa.

### 7.3 Manual

1. Do main menu, selecionar ARBITRAGE → hub aparece com layout HL2 (header, title, 3 rows grandes, footer).
2. Hover mouse sobre row 1 → bg fica BG3, label fica AMBER, cursor hand2.
3. Clicar na row 1 → abre Jane Street cockpit.
4. Voltar (ESC) → hub reaparece.
5. Tecla `d` → abre DEX scanner.
6. Voltar → teclar `x` → abre CEX-DEX scanner.
7. Voltar → setas ↓↑ movem cursor keyboard, ENTER escolhe.
8. ESC no hub → volta pro main menu.

---

## 8. Escopo — fora

- Novas DEX venues (fase C).
- Filtros configuráveis ou "worth it?" scoring (fase B).
- Spot-perp, spot-spot (fase D).
- Aba de operações reais (fase E).
- Refactor do `_funding_scanner_screen`.
- Mudanças em `engines/arbitrage.py` ou `core/funding_scanner.py`.
- Audio, animações complexas.

---

## 9. Riscos

| Risco | Mitigação |
|---|---|
| Frame-based rows não alinham verticalmente | Usar `grid` em vez de `pack` para controle fino, ou `place` com coordenadas absolutas |
| Hover binds escapam (child widget intercepta) | Bind em TODOS os child labels do row_frame, não só no frame |
| Scanner demora → rows aparecem com "—" | Fallback explícito, já está no design (seção 5.3) |
| `_arb_hub_telem_update` quebra se labels sumirem | Guard `if not hasattr(self, "_arb_hub_row_labels"): return` |

---

## 10. Sucesso

- Hub renderiza com layout HL2 minimalista: header + title + 3 rows + footer.
- 3 rows clicáveis com hover highlight (bg BG3, label AMBER).
- Click em row leva ao destino correto (Jane Street, DEX scanner, CEX-DEX scanner).
- Keybinds C/D/X/arrows/Enter/Esc preservados.
- Live data aparece nas sub-lines dentro de ~2s (cache hit) ou ~5s (cold scan).
- Fallbacks `—` quando offline ou cache vazio.
- Smoke test exit 0.
- Zero mudanças em `funding_scanner.py`, `engines/arbitrage.py`, ou qualquer backend.
