# ENGINES LIVE — E2E Visual Checklist

Reusable regression checklist for the `EXECUTE → ENGINES LIVE` view.
Run this after any change that touches `launcher_support/engines_live/`,
`launcher_support/screens/engines_live.py`, or related widgets.

**How to run:**
1. Boot: `python launcher.py` on Windows with VPS reachable.
2. Navigate: main menu → `EXECUTE` → `ENGINES LIVE`.
3. Walk each item below; mark ✅ pass / ❌ fail / ⚠️ partial.
4. Record deltas in the current session log.

---

## Header

- [ ] Header shows `› ENGINES` in AMBER bold (left)
- [ ] Counts placeholder present (e.g., `N live · M engines` — may be empty on first load until first data tick)
- [ ] Mode pill bar shows `PAPER | DEMO | TESTNET | LIVE` with the current mode highlighted (colored bg, dark text)
- [ ] Clicking a mode pill cycles the active mode
- [ ] Selecting `LIVE` mode paints a 1px RED horizontal line below the header
- [ ] Switching back to non-LIVE hides the RED line

## Strip Grid

- [ ] Grid auto-calculates columns based on window width (3 → 4 → 5 cols as you widen)
- [ ] Each running engine rendered as one V3 card (200×104 px)
- [ ] Card shows: display name (AMBER bold), instance count + status dots (● green / ! hazard / ✕ red)
- [ ] Card body lines: `mode · uptime` (DIM), `N/M nvl/t` (WHITE bold), `eq $X` (GREEN if > 0 else DIM2)
- [ ] Card order: errors first (if any), then by `sort_weight` ascending, alphabetical tiebreak
- [ ] `+ NEW ENGINE` card appears at the end of the grid (DIM border, AMBER "+ NEW ENGINE" text)
- [ ] Clicking an engine card highlights it with AMBER_B 2px border, opens detail view below
- [ ] Clicking `+ NEW ENGINE` opens the new-instance dialog

## Research Shelf

- [ ] Shelf shows title "RESEARCH · N engines not running" (DIM)
- [ ] Collapsed by default with `▸` arrow on the right
- [ ] Comma-separated engine names shown inline in DIM
- [ ] Clicking the `▸` arrow expands to `▾` and renders minimal cards (160×60)
- [ ] Each minimal card has engine name + `[START]` + `[BACKTEST]` buttons
- [ ] Clicking `[START]` fires the start callback; `[BACKTEST]` fires backtest callback

## Detail Pane — Empty State

- [ ] With no engine selected, detail pane shows `N engines live` (AMBER big), total ticks 24h, total equity paper
- [ ] Hint text `← Select an engine above` (DIM) at the bottom

## Detail Pane — Filled (engine selected)

- [ ] Horizontal split: left 40% (instances + KPIs + actions), right 60% (log tail)
- [ ] Left header: `Detail: {ENGINE}` (AMBER bold)
- [ ] Instances list: one row per instance with `mode.label ● uptime Xt/Ynv eq $Z`
- [ ] Selected instance row has `BG2` background (highlighted)
- [ ] Clicking an instance row selects it + populates the right column log
- [ ] KPIs grid below: total equity / instances / ticks / novel
- [ ] Instance action row: `[STOP]` + `[RESTART]` HoldButtons (1.5s hold)
- [ ] Engine action row: `[STOP ALL]` HoldButton + `[+] NEW` + `[C]ONFIG` plain buttons

## Detail Pane — Log Tail (right column)

- [ ] Status strip: `● FOLLOWING` in GREEN (when follow mode ON) or `○ paused` in DIM (when OFF)
- [ ] Log lines color-coded per level:
  - INFO → DIM
  - SIGNAL → AMBER bold
  - ORDER → CYAN
  - FILL → GREEN
  - EXIT → WHITE bold
  - WARN → HAZARD
  - ERROR → RED bold
- [ ] Bottom button row: `[O] OPEN FULL`, `[F] FOLLOW`, `[T] TELEGRAM TEST`
- [ ] `[F]` toggle: activates follow mode + auto-scroll to end on new lines
- [ ] No `run_id` selected → placeholder `(no instance selected — pick one to see live log)`

## Hold-to-Confirm Buttons

- [ ] Press and hold a HoldButton — amber progress fills left→right over 1.5s
- [ ] Release before 1.5s → fill resets, no action dispatched
- [ ] Hold full 1.5s → flashes GREEN for 300ms, callback fires, then resets
- [ ] Label changes during hold: `"HOLD TO STOP..."` (or equivalent)

## New Instance Dialog (`+` card or `+ NEW` button)

- [ ] Toplevel modal opens (grabbed focus; parent dimmed-ish)
- [ ] Mode pills (pre-selected to current global mode)
- [ ] Label Entry (empty by default)
- [ ] Target pills (LOCAL/VPS)
- [ ] Command preview updates live as you change mode/label/target
- [ ] CONFIRM button is a HoldButton when mode is LIVE, plain button otherwise
- [ ] Cancel button and `Escape` key close dialog returning None
- [ ] WM_DELETE (X button) closes dialog returning None

## Live Ritual Dialog

- [ ] When mode=LIVE + confirming a new instance: ritual dialog appears
- [ ] RED warning label: `⚠ Real money. Real orders.`
- [ ] Instruction: `Type the engine name (citadel) to confirm:`
- [ ] Entry field; CONFIRM button starts disabled (DIM fg)
- [ ] Typing partial or wrong name → CONFIRM stays disabled
- [ ] Typing exact engine name (case-sensitive) → CONFIRM enables (RED fg)
- [ ] Clicking CONFIRM returns True; Cancel/Escape return False

## Keyboard Navigation

- [ ] `↑ ↓ ← →` navigates engine cards in the strip
- [ ] `Enter` on strip card → opens detail view
- [ ] `Escape` on detail view → returns to strip focus
- [ ] `Escape` on strip → exits to main menu (same as the existing flow)
- [ ] `Tab` cycles focus: strip → detail_instances → detail_log → strip
- [ ] `m` cycles mode (paper → demo → testnet → live → paper)
- [ ] `s` on detail_instances → stops selected instance (HoldButton path, so requires 1.5s hold via click if that's the dispatch — pure keyboard `s` is a direct call)
- [ ] `+` on detail_instances → opens new instance dialog for the selected engine
- [ ] `f` on detail_log → toggles follow mode
- [ ] `?` shows help (R4.3 may not be fully wired; flag if missing)

## Footer

- [ ] Footer label shows context-sensitive keybind hints in DIM
- [ ] Hints change when focus moves between strip / detail_instances / detail_log / shelf
- [ ] e.g., strip: `↑↓←→ nav · Enter detail · + new · m mode · / filter · ? help · Esc exit`
- [ ] e.g., detail_log: `f follow · o open full · t telegram test · Esc back`

## Refresh Cycle / Background

- [ ] Data updates every ~30s without visible flicker
- [ ] No freezing during refresh (async fetch off main thread)
- [ ] Initial load: cards appear within a few seconds of entering the view

## Exit / Cleanup

- [ ] `Escape` from strip (or main menu button) exits cleanly
- [ ] No stale widgets left in the host frame after exit
- [ ] Re-entering rebuilds the view (new render call) without duplicated rows
- [ ] `handle["destroy"]()` gets called exactly once per exit (no leaks)

---

## Delta log

Record here during/after validation, linked to session log.

| Date | Item | Status | Note |
|------|------|--------|------|
| 2026-04-23 | R4.3 (initial creation) | pending | Checklist committed. Joao validation pending on next launcher run. |
