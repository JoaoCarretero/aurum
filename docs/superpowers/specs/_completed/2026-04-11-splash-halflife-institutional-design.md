# Splash HL1 Black Mesa Institutional Redesign

**Date:** 2026-04-11
**Author:** Joao + Claude
**Status:** Draft — awaiting user review
**Target file:** `launcher.py` (`_splash` method, currently the Bloomberg 3D 2×2 tile version)
**Related previous spec:** `docs/superpowers/specs/2026-04-11-launcher-main-menu-bloomberg-3d-design.md`

---

## 1. Motivação

O splash atual (pós-redesign Bloomberg 3D) usa 4 tiles interativos com live-data e drill-down complexo. O pedido do João é transformá-lo em uma **tela de entrada institucional atmosférica estilo Half Life 1 / Black Mesa**, onde o splash é apenas um portal visual — não uma hub de navegação. A lógica muda:

- Splash = intro atmosférica (decorativa + status)
- Click anywhere / ENTER / space → main menu (Fibonacci legacy)
- Setas e 1-4 **desativadas** — splash não é mais navegável por tile

A decisão vem de dois sinais: (1) o Joao quer "clicavel pra dai rodar o main menu" — ou seja, o splash é um portal, não um seletor; (2) a estética pedida é "institucional e bonito como se eu tivesse entrado no Half Life", que é uma experiência de *passagem*, não de operação.

---

## 2. Filosofia

Black Mesa Research Facility, 1998. Você entrou numa instalação secreta de alta segurança. O terminal mostra que você está autorizado (VAULT-3, Clearance OMEGA), que todos os sistemas estão nominais, e pede para você clicar para prosseguir. O tom é de gravidade institucional — isto não é um launcher de app, é um *terminal autorizado*.

Visualmente: gritty mas controlado. Warning stripes amarelo/preto nas bordas (não invasivas, só borderlines). Wordmark AURUM grande em block-font ASCII (reusa `BANNER` já existente). Um CD pequeno no canto como easter egg (continuidade do "disco lê a si mesmo"). Status block no estilo terminal CRT com dots preencedores. "CLICK TO PROCEED" pulsante.

Sem tiles. Sem drill-down. Sem navegação. É uma tela de *gate*.

---

## 3. Arquitetura visual

### 3.1 Layout (canvas único 920×640)

```
┌─────────────────────────────────────────────────────────────┐
│ ▓▓▒▒░░  ⚠ AUTHORIZED ACCESS ONLY ⚠  ░░▒▒▓▓    ← warning top │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ╱CD╲                                                       │
│ │◉◉◉│                    ┌─ STAMP ─┐      ┌─ STAMP ─┐       │
│ │LAS│                    │  VAULT  │      │ CLEARED │       │
│  ╲◉╱                     │   03    │      │  LVL-Ω  │       │
│                          └─────────┘      └─────────┘       │
│                                                             │
│               █▀▀█ █░░█ █▀▀█ █░░█ █▀▄▀█                     │
│               █▄▄█ █░░█ █▄▄▀ █░░█ █░▀░█                     │
│               █░░█ ░▀▀▀ ▀░▀▀ ░▀▀▀ █░░░█                     │
│                                                             │
│              F I N A N C I A L   T E R M I N A L            │
│                     · · · V A U L T - 3 · · ·               │
│                                                             │
│              ──────────────────────────────────             │
│                                                             │
│              > SYSTEM STATUS .......... NOMINAL             │
│              > MARKET FEED ............ ● LIVE              │
│              > CONNECTION ............. ● BINANCE           │
│              > TELEGRAM ................ ● ONLINE           │
│              > KILL-SWITCH ............. ARMED [3/3]        │
│              > CLEARANCE ............... OMEGA              │
│                                                             │
│              ──────────────────────────────────             │
│                                                             │
│                      [ CLICK TO PROCEED ]▊                  │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ ▓▓▒▒░░  © 2026 AURUM · O DISCO LÊ A SI MESMO  ░░▒▒▓▓        │
└─────────────────────────────────────────────────────────────┘
```

- Canvas: single `tk.Canvas` 920×640, bg=BG (#0a0a0a), highlightthickness=0.
- Content stack (top→bottom): warning top stripe, CD+stamps row, AURUM wordmark, subtitle, rule, status block, rule, click prompt, warning bottom stripe.

### 3.2 Warning stripes (top and bottom)

- Height: ~20px each.
- Implementation: solid yellow rectangle `fill="#ffd700"` spanning full canvas width, with hazard pattern simulated in pure text using the Consolas monospace charset — one `create_text` call centered over each rectangle.
- Top text: `▓▒░  ⚠ AUTHORIZED ACCESS ONLY ⚠  ░▒▓`
- Bottom text: `▓▒░  © 2026 AURUM · O DISCO LÊ A SI MESMO  ░▒▓`
- Font: `(FONT, 7, "bold")`, fill=`#1a1a00` (very dark — high contrast on yellow).
- No gradient. No hatch. No shader. Portable across all Tk builds.

### 3.3 CD small top-left

- Position: canvas coords (70, 100), radius 36.
- Implementation: add a `r=None` parameter to `_draw_cd_center(self, canvas, r=None)`. When `r is None`, use `self._active_cd_center` + `self._CD_R` (current default behavior, backward compatible). When `r` is passed, draw a smaller CD at the current `_active_cd_center` with the overridden radius. The splash sets `self._active_cd_center = (70, 100)` then calls `self._draw_cd_center(canvas, r=36)`.
- Animation: same rotation via `time.monotonic()`. No automatic repaint tick — the CD is static between redraws, which is fine for a splash screen (the pulse tick at 500ms can also redraw the CD if desired, but for v1 we leave it static after initial draw).

### 3.4 Stamps top-right

- 2 selos ASCII (pontilhados), each ~100×50 px, aligned right-center around (680, 100) and (800, 100).
- Contents:
  - Stamp 1: `VAULT / 03`
  - Stamp 2: `CLEARED / LVL-Ω`
- Drawn via dashed `create_rectangle(outline=AMBER, dash=(2,3), width=1)` + `create_text` for the 2 lines.

### 3.5 AURUM wordmark

- Reuse the existing module-level `BANNER` constant (verify its exact content via `grep "^BANNER = " launcher.py`). It's a multi-line ASCII block.
- Position: centered horizontally, y=190.
- Font: `(FONT, 11, "bold")`, fg=AMBER.

### 3.6 Subtitle

- `F I N A N C I A L   T E R M I N A L` (spaced letters), fg=AMBER_D, `(FONT, 9, "bold")`, centered at y=268.
- `· · · V A U L T - 3 · · ·`, fg=DIM, `(FONT, 7)`, centered at y=284.

### 3.7 Rules (top and bottom of status block)

- Thin amber rules, full-width minus ~120px padding, y=308 and y=440.
- `create_line` with fill=AMBER_D, width=1.

### 3.8 Status block

- 6 lines, monospace, left-justified at x≈220, right-padded to x≈720.
- Format: `> {LABEL} {dots}. {VALUE}` — dots fill the gap so labels and values are visually aligned.
- Each line is one `create_text` call with `text=f"> {label} {dot_fill} {value}"` constructed in Python.
- Colors:
  - SYSTEM STATUS → `NOMINAL` in GREEN
  - MARKET FEED → `● LIVE` in GREEN if online, `○ OFFLINE` in DIM if not
  - CONNECTION → `● BINANCE` in GREEN if keys exist, `○ OFFLINE` in DIM otherwise
  - TELEGRAM → `● ONLINE` in GREEN if token present, `○ OFFLINE` in DIM otherwise
  - KILL-SWITCH → `ARMED [3/3]` in RED (always — the kill-switch is sacred)
  - CLEARANCE → `OMEGA` in AMBER_B (hardcoded, thematic)
- Data sources (reuse existing splash logic where possible):
  - CONNECTION / TELEGRAM: use the existing keys.json reads from the current `_splash` body (already has `has_keys`, `has_tg`).
  - MARKET FEED: use `_conn.status_summary()` which already returns a market state (current splash uses it).
  - Everything else: hardcoded labels.

### 3.9 Click prompt

- Text: `[ CLICK TO PROCEED ]▊`.
- Position: centered at y=488.
- Font: `(FONT, 10, "bold")`, fg=AMBER_B when cursor visible, fg=AMBER when hidden.
- Cursor pulse: the trailing `▊` toggles visibility every 500ms via `self.after(500, ...)` re-scheduling a tiny callback `_splash_pulse_tick` that flips `self._splash_cursor_on` and redraws that single text item via `canvas.itemconfig(tag, text=...)`.
- The pulse must self-disarm when the splash is torn down (check `self._splash_canvas is canvas` or similar guard).

---

## 4. Interação

- **Click anywhere on the canvas** → `self._menu("main")`
- **ENTER** / **space** → `self._menu("main")`
- **Q** → `self._quit` (existing behavior)
- **Arrow keys / Tab / 1-4 / letters** → **unbound** (splash is no longer navigable by tile)
- **Escape** → unbound on splash (or optionally quit — align with existing `_splash` behavior: the old splash had `<Escape>` unbound, so keep it unbound)

The `_bind_global_nav()` existing helper is still called at the end of `_splash` to preserve the global keybinds that work from any screen (H hub, Q quit, etc).

---

## 5. Reuso e código

### 5.1 O que sai

- The 2×2 Bloomberg tile grid **is no longer drawn on splash**.
- `_menu_tile_focus`, `_menu_tile_focus_delta`, `_menu_tile_expand`, drill-down, `_splash_direct_jump`, `_splash_focus_delta` — these splash-specific handlers become unused. They stay in the file (dead code, reusable for other screens), but `_splash` no longer wires any of them.

### 5.2 O que fica

- `BANNER` module-level constant (reused for wordmark).
- `_draw_cd_center` (reused for the small top-left CD, with a new radius parameter).
- `_menu_live_fetch_async`, `_menu_live_apply`, `_menu_live_schedule` — **not used by splash v2**. They still power the dead `_menu_main_bloomberg` method. Not deleted.
- `_active_tile_slots`, `_active_cd_center` — still used by dead code; stay.
- `_fetch_tile_*` fetchers — still present, unused by splash v2.

### 5.3 O que muda

- `_splash` is rewritten. Old body deleted, new body per section 3.
- New class-level constant `_SPLASH_CD_SMALL = (100, 100)` (or similar) OR reuse `_active_cd_center` set to a small-CD position before drawing.
- New method `_splash_pulse_tick` for the 500ms cursor blink.
- New method `_draw_warning_stripe(canvas, y, height, text)` helper for the top/bottom bars.
- New method `_draw_stamp(canvas, cx, cy, w, h, lines)` helper for the 2 selos.
- New method `_draw_status_block(canvas, x, y, rows)` helper for the CRT-style rows.
- `_draw_cd_center` may need a small edit to accept a radius override — currently it uses `self._CD_R` directly. Add a parameter `r=None` that defaults to `self._CD_R` when not provided. Do NOT break the existing usage in `_menu_main_bloomberg` — keep default behavior intact.

### 5.4 State fields added to `App.__init__`

- `self._splash_cursor_on = True` (for the 500ms pulse)
- `self._splash_pulse_after_id = None` (for self-disarm)
- `self._splash_canvas = None` (tracks the canvas for the pulse guard)

---

## 6. Implementação passo-a-passo

(Formal plan lives in `docs/superpowers/plans/2026-04-11-splash-halflife-institutional.md` — to be written after user approval.)

Rough task sequence:
1. Add `_draw_cd_center` radius parameter (non-breaking change) + unit test.
2. Add splash state fields to `__init__`.
3. Add `_draw_warning_stripe`, `_draw_stamp`, `_draw_status_block` helpers.
4. Rewrite `_splash` body using those helpers.
5. Add `_splash_pulse_tick` 500ms cursor blink with self-disarm.
6. Delete or update splash unit tests (the previous splash tests for `_splash_direct_jump` and key-1 dispatch become invalid — remove them, add new tests for canvas presence, click bind, no arrow bind).
7. Update smoke test to exercise new splash (render + click simulation).
8. Manual walkthrough + merge.

---

## 7. Testes & validação

### 7.1 Pytest (unit)

Replace previous splash tests:
- **Remove:** `test_splash_key_1_dispatches_to_markets` — splash no longer has `_splash_direct_jump` behavior.
- **Keep:** `test_splash_creates_bloomberg_canvas` — rename to `test_splash_creates_canvas` and relax the item count from 20 to 15 (HL1 splash has fewer items than the tile grid).
- **Add:** `test_splash_click_routes_to_main` — monkey-patch `_menu` to record calls, call `_splash()`, trigger a synthetic click via `canvas.event_generate("<Button-1>")` OR simpler: locate the `<Button-1>` binding on `self.main` and invoke the handler directly.
- **Add:** `test_splash_arrow_keys_unbound` — `_splash()`, verify `self.bind_all("<Right>")` returns empty or the binding that splash v2 installed is a no-op / absent.
- **Add:** `test_splash_pulse_disarms_on_leave` — `_splash()`, call `_menu("main")`, verify `self._splash_pulse_after_id is None` (or the pending `after` callback early-returns without touching the canvas).

### 7.2 Smoke

The existing `call("_splash", app._splash)` continues to work. Optionally add a `call("_splash→menu", ...)` that exercises the click routing through a direct call. Not strictly required.

### 7.3 Manual walkthrough

1. Launch `python launcher.py`. Splash appears with warning stripes, CD top-left, AURUM wordmark centered, status block, "CLICK TO PROCEED".
2. Wait 2-3 seconds. Cursor `▊` blinks every 500ms. CD rotates.
3. Click anywhere on the splash. Main menu (legacy Fibonacci) appears.
4. Press ESC from main menu. Splash returns, pulse resumes.
5. Press Q. App exits.
6. Press ENTER on splash. Main menu appears (same path).
7. Press `→` on splash. Nothing happens (arrow keys unbound).

### 7.4 Regressão

- Smoke `_splash` → main menu flow still works.
- `_menu_main_bloomberg` and helpers still present (not deleted).
- `_brief`, `_config_*`, `_arbitrage_hub`, `_data_center` — untouched.

---

## 8. Escopo — o que fica de fora

- No changes to engines, signals, costs, sizing, risk logic, or any trading code.
- No changes to main menu (`_menu("main")` stays Fibonacci legacy).
- No new dependencies.
- No audio / particle effects / animations beyond CD rotation and cursor blink.
- No CRT scanline shader (would require PIL or heavy canvas draws).
- No dead-code cleanup — `_menu_main_bloomberg` and the 200+ lines of unused splash-tile helpers stay in the file. A future cleanup task can remove them if desired.

---

## 9. Riscos

| Risco | Mitigação |
|---|---|
| Warning stripe fill pattern não renderiza portátil | Use simple text with `▓▒░` chars instead of hatch fill |
| Cursor pulse vaza entre telas (after_id não cancela) | `_splash_pulse_tick` guarda `self._splash_canvas is canvas` antes de redrawar |
| BANNER multi-line não alinha no canvas | `create_text` com `font=Consolas` monospace preserva alinhamento; testar com tamanho 11 bold |
| Click bind conflita com existing `self.main.bind` | Atual `_splash` já usa este padrão; substituir preservando a semântica |
| Test `event_generate("<Button-1>")` não dispara em window withdrawn | Call o handler direto via `self.main.bind_all_callbacks` ou expose um pequeno `_splash_on_click` method testável |

---

## 10. Sucesso

- Splash mostra AURUM wordmark + status block + CD top-left + warning stripes.
- Click em qualquer lugar → main menu (Fibonacci).
- Cursor `▊` pisca a cada 500ms.
- CD gira na ~1 passo por tick.
- Arrow keys e 1-4 **não navegam** no splash.
- Main menu continua legacy Fibonacci 100%.
- Smoke test exit 0.
- Visual coerente com HL1 Black Mesa (gritty, institucional, amber/yellow).
- Zero mudança em trading logic.
