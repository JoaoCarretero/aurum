# Cleanup Phase 3 — "launcher.py decomposition" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduzir launcher.py de 9,574 LOC → ≤6,500 LOC extraindo 84 methods (`_arb*` 49, `_dash_home/portfolio/trades*` 11, `_eng*` 24) pros modules existentes em `launcher_support/screens/` via thin delegate pattern.

**Architecture:** Branch dedicada `feat/cleanup-phase-3` com 6 commits atômicos. Cada method extraído: body vira `render_<name>(app, ...)` no screen module, delegate 3-linhas permanece em launcher.py. Pattern já estabelecido em `launcher_support/screens/arbitrage_hub.py` e `dash_home.py`.

**Tech Stack:** Python 3.11.5 on Windows, pytest 8.4.2, git.

**Spec:** `docs/superpowers/specs/2026-04-23-cleanup-phase-3-design.md` (commit `dd245d6`)

**Descobertas durante mapeamento (atualização vs spec):**
- `_arb*` = **49 methods** (spec dizia 48 — contei `_arbitrage_hub` container também)
- `_dash_home/portfolio/trades*` sub-clusters = **11 methods** juntos (spec original dizia "_dash*" 42, mas apenas home/portfolio/trades sub-clusters estão no escopo; outros 30 `_dash*` — cockpit/backtest/common — ficam pra Fase 3.1)
- `_eng*` = **24 methods** (spec dizia 22 — contei `_engine_extra_cli_flags`, `_engines_now_playing`)
- **Total: 84 methods** (vs 112 no spec). Scope reduzido pelas descobertas, target 6,500 LOC ainda alcançável.

---

## File Structure

### Arquivos a MODIFICAR (body movido + delegate kept)

| File | Mudança |
|------|---------|
| `launcher.py` | Remove body de 84 methods (fica delegate 3-linhas cada). LOC: 9,574 → ≤6,500 |

### Arquivos que recebem body (EXISTENTES; expandir com novas funções)

| File | Methods recebidos | Count |
|------|-------------------|-------|
| `launcher_support/screens/arbitrage_hub.py` | Todos `_arb*` | 49 |
| `launcher_support/screens/dash_home.py` | `_dash_home_*` + `_dash_build_home_tab` | 3 |
| `launcher_support/screens/dash_portfolio.py` | `_dash_portfolio_*` + `_dash_build_portfolio_tab` + `_dash_paper_edit_dialog` | 5 |
| `launcher_support/screens/dash_trades.py` | `_dash_trades_*` + `_dash_build_trades_tab` | 3 |
| `launcher_support/screens/engines.py` | `_eng*` (maioria) | ~18 |
| `launcher_support/screens/engines_live.py` | `_eng_poll_logs`, `_eng_tail_*`, `_eng_scan_vps_runs`, `_engines_now_playing` (live-state-related) | ~6 |

### Arquivos intocados

- CORE: `config/params.py`, `core/signals.py`, `core/indicators.py`, `core/portfolio.py`
- Tests em `tests/` — se chamam `app._method()`, continuam funcionando via delegate
- Outros launcher_support modules (cockpit_tab, command_center, dashboard_controls)

### Pattern-por-method (referência)

**Before (launcher.py):**
```python
def _arb_render_opps(self, scan):
    """Render OPPS table."""
    for item in scan:
        self._arb_make_table(item)
    self._arb_update_status_strip()
```

**After (launcher_support/screens/arbitrage_hub.py — nova função):**
```python
def render_opps(app, scan):
    """Render OPPS table. Extracted from launcher.App._arb_render_opps."""
    for item in scan:
        app._arb_make_table(item)
    app._arb_update_status_strip()
```

**After (launcher.py — thin delegate):**
```python
def _arb_render_opps(self, scan):
    from launcher_support.screens.arbitrage_hub import render_opps
    return render_opps(self, scan)
```

Net LOC: method body ~15 lines → delegate ~3 lines = −12 lines per method. Average 30-50 LOC methods = 2,500-4,200 LOC total reduction.

---

## Task 1: Setup branch + baseline

**Files:** (no code changes — infra only)

- [ ] **Step 1: Create branch**

```bash
cd /c/Users/Joao/projects/aurum.finance
git checkout chore/repo-cleanup
git pull origin chore/repo-cleanup
git checkout -b feat/cleanup-phase-3
```

- [ ] **Step 2: Record baselines**

```bash
wc -l launcher.py
grep -c "^    def " launcher.py
.venv/Scripts/python.exe -m pytest tests/launcher/ tests/integration/test_launcher_main_menu.py --tb=no -q 2>&1 | tail -3
.venv/Scripts/python.exe -c "import time; t0=time.perf_counter(); import launcher; print(f'{(time.perf_counter()-t0)*1000:.0f}ms')"
```

Expected:
- launcher.py: **9,574 LOC**
- Methods: **296**
- Tests: pass count noted (baseline varies 1610-1666)
- Import time: ~149ms

Record these numbers — used as baseline throughout phase.

- [ ] **Step 3: Push empty branch**

```bash
git push -u origin feat/cleanup-phase-3
```

---

## Task 2: Extract `_arb*` methods — batch 1 (24 methods — rendering/painting/building)

**Files:**
- Modify: `launcher.py` — remove 24 method bodies, replace with delegates
- Modify: `launcher_support/screens/arbitrage_hub.py` — add 24 `render_*` / `paint_*` / etc. functions

**Methods in batch 1 (rendering + painting + building):**

```
_arbitrage_hub
_arb_render_opps
_arb_render_engine
_arb_render_history
_arb_render_positions
_arb_paint_basis
_arb_paint_opps
_arb_paint_pairs
_arb_paint_spot
_arb_build_detail_pane
_arb_build_filter_bar
_arb_build_viab_toolbar
_arb_show_detail
_arb_set_detail_size
_arb_toggle_detail_adv
_arb_basis_screen
_arb_basis_screen_legacy
_arb_basis_paint
_arb_spot_screen
_arb_spot_screen_legacy
_arb_spot_paint
_arb_make_table
_arb_rerender_current_tab
_arb_update_status_strip
```

- [ ] **Step 1: Inspect arbitrage_hub.py current state**

```bash
cd /c/Users/Joao/projects/aurum.finance
head -50 launcher_support/screens/arbitrage_hub.py
```

Note existing functions (likely just `render`). You'll add 24 new functions alongside.

- [ ] **Step 2: For EACH of the 24 methods, perform extraction**

**Sub-workflow per method (repeat 24 times):**

a) Find method body in launcher.py:
```bash
grep -n "def _arb_render_opps" launcher.py  # replace with current method
```

b) Read the full method body (from `def` line until next `def` or class end):
```bash
sed -n '<start>,<end>p' launcher.py
```

c) Append new function to `launcher_support/screens/arbitrage_hub.py`:

```python
def render_opps(app, scan):
    """<same docstring from original>
    
    Extracted from launcher.App._arb_render_opps in Fase 3 refactor.
    """
    # <body copied exactly, with self replaced by app>
```

Naming convention: strip the `_arb_` prefix to get the function name (e.g., `_arb_render_opps` → `render_opps`, `_arb_paint_basis` → `paint_basis`). Exception: `_arbitrage_hub` → `render_hub`.

d) Replace body in launcher.py with delegate:

```python
    def _arb_render_opps(self, scan):
        from launcher_support.screens.arbitrage_hub import render_opps
        return render_opps(self, scan)
```

e) Run quick smoke:
```bash
.venv/Scripts/python.exe -c "import launcher; launcher.App().destroy()"
```

**CRITICAL NOTES while extracting:**
- Replace `self.` with `app.` throughout the body
- Preserve exact function signature (positional args, defaults, kwargs)
- Preserve docstring exactly
- If method references inner closures or nested functions, extract them together
- If method uses locals that reference `self.__class__`, use `type(app)` instead

- [ ] **Step 3: After all 24 methods extracted, run gate**

```bash
.venv/Scripts/python.exe -c "import launcher; app = launcher.App(); app.destroy(); print('OK')"
```

Expected: `OK` (no exceptions during App creation).

- [ ] **Step 4: Run launcher tests**

```bash
.venv/Scripts/python.exe -m pytest tests/launcher/ tests/integration/test_launcher_main_menu.py --tb=no -q 2>&1 | tail -3
```

Expected: same pass count as Task 1 baseline (±5 for flakiness).

- [ ] **Step 5: LOC check**

```bash
wc -l launcher.py
grep -c "^    def _arb" launcher.py
```

Expected:
- launcher.py: **reduced by ~600-1,200 LOC** (24 methods × 25-50 LOC average)
- `_arb` method count: still **49** (delegates remain) — that's OK

- [ ] **Step 6: Commit**

```bash
git add launcher.py launcher_support/screens/arbitrage_hub.py
git commit -m "refactor(launcher): extract _arb_* methods (batch 1/2)

Move 24 rendering/painting/building methods from launcher.App to
launcher_support/screens/arbitrage_hub.py:

- render_hub (was _arbitrage_hub)
- render_opps, render_engine, render_history, render_positions
- paint_basis, paint_opps, paint_pairs, paint_spot
- build_detail_pane, build_filter_bar, build_viab_toolbar
- show_detail, set_detail_size, toggle_detail_adv
- basis_screen, basis_screen_legacy, basis_paint
- spot_screen, spot_screen_legacy, spot_paint
- make_table, rerender_current_tab, update_status_strip

Each App method now has a 3-line delegate calling the extracted
function. Pattern: render(app, ...) with self→app mapping.

LOC: launcher.py <before>→<after> (-<N>).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin feat/cleanup-phase-3
```

Fill `<before>`, `<after>`, `<N>` from Step 5 measurement.

---

## Task 3: Extract `_arb*` methods — batch 2 (25 methods — scan/filter/actions/helpers)

**Files:**
- Modify: `launcher.py`
- Modify: `launcher_support/screens/arbitrage_hub.py`

**Methods in batch 2 (remaining `_arb*`):**

```
_arb_scan_is_fresh
_arb_hub_scan_async
_arb_hub_telem_update
_arb_filter_and_score
_arb_filter_state
_arb_filters_path
_arb_load_filters
_arb_save_filters
_arb_fmt_filter
_arb_engine_start
_arb_engine_stop
_arb_feed_engine
_arb_open_as_paper
_arb_simulate
_arb_schedule_clock
_arb_schedule_refresh
_arb_score_fallback
_arb_set_grade_min
_arb_set_status_error
_arb_pair_label
_arb_venue_label
_arb_viab_reason
_arb_toggle_realistic
_arb_toggle_risky_venues
_arb_refresh_viab_toolbar
```

- [ ] **Step 1: For each method, repeat sub-workflow from Task 2 Step 2**

Same pattern: move body to arbitrage_hub.py as new function (strip `_arb_` prefix), replace original with delegate.

- [ ] **Step 2: Gate — launcher imports + boots**

```bash
.venv/Scripts/python.exe -c "import launcher; app = launcher.App(); app.destroy(); print('OK')"
```

- [ ] **Step 3: Gate — tests**

```bash
.venv/Scripts/python.exe -m pytest tests/launcher/ tests/integration/test_launcher_main_menu.py --tb=no -q 2>&1 | tail -3
```

- [ ] **Step 4: Gate — verify all `_arb*` methods are delegates**

```bash
grep -A 3 "def _arb" launcher.py | grep -A 2 "def _arb" | head -40
```

Each `_arb` function should be exactly 3 lines: `def` + `from ... import` + `return ...`.

- [ ] **Step 5: Commit**

```bash
git add launcher.py launcher_support/screens/arbitrage_hub.py
git commit -m "refactor(launcher): extract _arb_* methods (batch 2/2)

Move 25 remaining methods from launcher.App to arbitrage_hub.py:
- Scan: scan_is_fresh, hub_scan_async, hub_telem_update
- Filter: filter_and_score, filter_state, filters_path,
  load_filters, save_filters, fmt_filter
- Engine actions: engine_start, engine_stop, feed_engine
- Trading: open_as_paper, simulate
- Schedules: schedule_clock, schedule_refresh
- Helpers: score_fallback, set_grade_min, set_status_error,
  pair_label, venue_label, viab_reason
- Toggles: toggle_realistic, toggle_risky_venues, refresh_viab_toolbar

All 49 _arb* methods now thin delegates. arbitrage_hub.py is
the new home for arbitrage UI logic.

LOC: launcher.py <before>→<after> (-<N>).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin feat/cleanup-phase-3
```

---

## Task 4: Extract `_dash_home*` methods (3 methods)

**Files:**
- Modify: `launcher.py`
- Modify: `launcher_support/screens/dash_home.py`

**Methods:**

```
_dash_build_home_tab
_dash_home_fetch_async
_dash_home_render
```

- [ ] **Step 1: For each of the 3 methods, apply sub-workflow from Task 2 Step 2**

Function naming convention:
- `_dash_build_home_tab` → `build_home_tab(app)`
- `_dash_home_fetch_async` → `home_fetch_async(app)`
- `_dash_home_render` → `render(app)` if `render` doesn't exist yet in dash_home.py; otherwise `home_render(app)` to avoid collision.

Check dash_home.py state first:
```bash
grep "^def " launcher_support/screens/dash_home.py
```

If `render` already exists there, name the new function `home_render` or just replace the existing `render` (which is already extracted from `_dash_home_render`? — verify by reading).

- [ ] **Step 2: Gate — smoke**

```bash
.venv/Scripts/python.exe -c "import launcher; app = launcher.App(); app.destroy(); print('OK')"
```

- [ ] **Step 3: Gate — tests**

```bash
.venv/Scripts/python.exe -m pytest tests/launcher/ tests/integration/test_launcher_main_menu.py --tb=no -q 2>&1 | tail -3
```

- [ ] **Step 4: Commit**

```bash
git add launcher.py launcher_support/screens/dash_home.py
git commit -m "refactor(launcher): extract _dash_home_* methods

Move 3 home-tab methods from launcher.App to
launcher_support/screens/dash_home.py:
- build_home_tab (was _dash_build_home_tab)
- home_fetch_async (was _dash_home_fetch_async)
- home_render (was _dash_home_render)

All 3 App methods now thin delegates.

LOC: launcher.py <before>→<after> (-<N>).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin feat/cleanup-phase-3
```

---

## Task 5: Extract `_dash_portfolio*` methods (5 methods)

**Files:**
- Modify: `launcher.py`
- Modify: `launcher_support/screens/dash_portfolio.py`

**Methods:**

```
_dash_build_portfolio_tab
_dash_portfolio_fetch_async
_dash_portfolio_render
_dash_portfolio_repaint_account_btns
_dash_paper_edit_dialog
```

- [ ] **Step 1: For each of the 5 methods, apply sub-workflow**

Function naming:
- `_dash_build_portfolio_tab` → `build_portfolio_tab(app)`
- `_dash_portfolio_fetch_async` → `portfolio_fetch_async(app)`
- `_dash_portfolio_render` → `render(app)` or `portfolio_render(app)` if existing `render` collides
- `_dash_portfolio_repaint_account_btns` → `repaint_account_btns(app)`
- `_dash_paper_edit_dialog` → `paper_edit_dialog(app, ...)` (note: this is called from portfolio tab but could logically live elsewhere; keep in dash_portfolio.py for now since it's account-related)

Check dash_portfolio.py state first:
```bash
grep "^def " launcher_support/screens/dash_portfolio.py
```

- [ ] **Step 2-3: Gates (same as Task 4)**

- [ ] **Step 4: Commit**

```bash
git add launcher.py launcher_support/screens/dash_portfolio.py
git commit -m "refactor(launcher): extract _dash_portfolio_* methods

Move 5 portfolio-tab methods from launcher.App to
launcher_support/screens/dash_portfolio.py:
- build_portfolio_tab
- portfolio_fetch_async
- portfolio_render
- repaint_account_btns (was _dash_portfolio_repaint_account_btns)
- paper_edit_dialog (was _dash_paper_edit_dialog; account config modal)

All 5 App methods now thin delegates.

LOC: launcher.py <before>→<after> (-<N>).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin feat/cleanup-phase-3
```

---

## Task 6: Extract `_dash_trades*` methods (3 methods)

**Files:**
- Modify: `launcher.py`
- Modify: `launcher_support/screens/dash_trades.py`

**Methods:**

```
_dash_build_trades_tab
_dash_trades_page_change
_dash_trades_render
```

- [ ] **Step 1: For each of the 3 methods, apply sub-workflow**

Function naming:
- `_dash_build_trades_tab` → `build_trades_tab(app)`
- `_dash_trades_page_change` → `trades_page_change(app, ...)`
- `_dash_trades_render` → `render(app)` or `trades_render(app)` if `render` collides

Check dash_trades.py state first:
```bash
grep "^def " launcher_support/screens/dash_trades.py
```

- [ ] **Step 2-3: Gates (same as Task 4)**

- [ ] **Step 4: Commit**

```bash
git add launcher.py launcher_support/screens/dash_trades.py
git commit -m "refactor(launcher): extract _dash_trades_* methods

Move 3 trades-tab methods from launcher.App to
launcher_support/screens/dash_trades.py:
- build_trades_tab
- trades_page_change
- trades_render

All 3 App methods now thin delegates. The _dash_home/portfolio/trades
extraction is complete; remaining _dash_* (backtest, cockpit, common)
stay in launcher.py for now — Fase 3.1 can extract them.

LOC: launcher.py <before>→<after> (-<N>).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin feat/cleanup-phase-3
```

---

## Task 7: Extract `_eng*` methods (24 methods)

**Files:**
- Modify: `launcher.py`
- Modify: `launcher_support/screens/engines.py`
- Modify: `launcher_support/screens/engines_live.py`

**Methods — split by target module:**

**→ `screens/engines.py` (14 methods — registry/scanning/filtering):**

```
_eng_apply_entries
_eng_base_slug
_eng_fetch_entries
_eng_is_engine_row
_eng_known_slugs
_eng_load_entries
_eng_matches_mode_filter
_eng_normalize_local_proc
_eng_recency_key
_eng_refresh
_eng_refresh_filter_tabs
_eng_render_row
_eng_row_key
_eng_run_id_of
_eng_scan_historical_runs
_eng_select
_eng_set_mode_filter
_eng_uptime_of
_engine_extra_cli_flags
```

**→ `screens/engines_live.py` (5 methods — live-state/logs polling):**

```
_eng_poll_logs
_eng_tail_remote_worker
_eng_tail_worker
_eng_scan_vps_runs
_engines_now_playing
```

- [ ] **Step 1: Inspect both target modules' current state**

```bash
grep "^def " launcher_support/screens/engines.py
grep "^def " launcher_support/screens/engines_live.py
```

- [ ] **Step 2: For each method, apply sub-workflow, sending to correct module**

Function naming (strip `_eng_` prefix):
- `_eng_apply_entries` → `apply_entries(app, ...)`
- `_eng_base_slug` → `base_slug(...)` (if not using `self`, pure function)
- `_eng_fetch_entries` → `fetch_entries(app, ...)`
- etc.
- `_engine_extra_cli_flags` → `engine_extra_cli_flags(app, ...)` (note: `_engine_` prefix, goes in engines.py still)
- `_engines_now_playing` → `engines_now_playing(app)` (note: `_engines_` plural — goes in engines_live.py)

- [ ] **Step 3: Gate — smoke**

```bash
.venv/Scripts/python.exe -c "import launcher; app = launcher.App(); app.destroy(); print('OK')"
```

- [ ] **Step 4: Gate — tests**

```bash
.venv/Scripts/python.exe -m pytest tests/launcher/ tests/integration/test_launcher_main_menu.py --tb=no -q 2>&1 | tail -3
```

- [ ] **Step 5: Commit**

```bash
git add launcher.py launcher_support/screens/engines.py launcher_support/screens/engines_live.py
git commit -m "refactor(launcher): extract _eng* methods

Move 24 engine UI methods from launcher.App to:

launcher_support/screens/engines.py (19 methods):
- Registry/scanning: apply_entries, base_slug, fetch_entries,
  is_engine_row, known_slugs, load_entries, matches_mode_filter,
  normalize_local_proc, recency_key, refresh, refresh_filter_tabs,
  render_row, row_key, run_id_of, scan_historical_runs, select,
  set_mode_filter, uptime_of, engine_extra_cli_flags

launcher_support/screens/engines_live.py (5 methods):
- Live state: poll_logs, tail_remote_worker, tail_worker,
  scan_vps_runs, engines_now_playing

All 24 App methods now thin delegates.

LOC: launcher.py <before>→<after> (-<N>).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin feat/cleanup-phase-3
```

---

## Task 8: Final gates + merge back

**Files:** none modified (gates + git ops)

- [ ] **Step 1: Full metrics sweep**

```bash
cd /c/Users/Joao/projects/aurum.finance

# launcher.py LOC (target ≤6,500)
wc -l launcher.py

# App method count (target ≤200)
grep -c "^    def " launcher.py

# Launcher import time (baseline 149ms, target ≤200ms)
.venv/Scripts/python.exe -c "import time; t0=time.perf_counter(); import launcher; print(f'{(time.perf_counter()-t0)*1000:.0f}ms')"

# Launcher boot smoke
.venv/Scripts/python.exe -c "import launcher; app = launcher.App(); app.destroy(); print('boot OK')"

# Full pytest
.venv/Scripts/python.exe -m pytest tests/ --ignore=tests/test_cockpit_paper_endpoints.py --tb=no -q 2>&1 | tail -3
```

Expected:
- launcher.py: ≤ 6,500 LOC (target; ≤ 7,000 acceptable)
- Methods: ≤ 200 (target; ≤ 220 acceptable)
- Import time: ≤ 200ms
- Boot: `boot OK`
- Tests: 1666 pass (±20 flakiness)

- [ ] **Step 2: VPS sanity check**

```bash
ssh -o ConnectTimeout=10 -o BatchMode=yes -i /c/Users/Joao/.ssh/id_ed25519 root@37.60.254.151 '
count=0
for u in citadel_paper@desk-a citadel_shadow@desk-a jump_paper@desk-a jump_shadow@desk-a renaissance_paper@desk-a renaissance_shadow@desk-a millennium_paper@desk-paper-a millennium_paper@desk-paper-b millennium_shadow@desk-shadow-a millennium_shadow@desk-shadow-b aurum_probe@desk-a aurum_cockpit_api; do
  [ "$(systemctl is-active ${u}.service)" = "active" ] && count=$((count+1))
done
echo "$count/12 services active"
'
```

Expected: `12/12 services active`.

- [ ] **Step 3: Manual smoke (user-validated)**

Run launcher:
```bash
.venv/Scripts/python.exe launcher.py &
```

User opens, clicks:
- ARBITRAGE screen → renders OK, scan works, tabs switch
- DASHBOARD → HOME tab renders, PORTFOLIO tab renders, TRADES tab renders
- ENGINES screen → renders, registry entries visible, refresh works

If any screen crashes or renders blank, STOP and diagnose.

- [ ] **Step 4: Merge back**

```bash
git checkout chore/repo-cleanup
git merge --no-ff feat/cleanup-phase-3 -m "Merge feat/cleanup-phase-3 into chore/repo-cleanup

Phase 3 of software optimization roadmap: launcher.py decomposition.

- Extracted 84 methods from App class to launcher_support/screens/:
  - 49 _arb* methods → arbitrage_hub.py
  - 3 _dash_home_* → dash_home.py
  - 5 _dash_portfolio_* → dash_portfolio.py
  - 3 _dash_trades_* → dash_trades.py
  - 19 _eng* → engines.py
  - 5 _eng_*/_engines_* → engines_live.py

- Pattern: thin delegate (3 lines) in App; body in screens/ as
  render(app, ...) functions.
- All App method signatures preserved (tests + callers unchanged).

Metrics:
- launcher.py: 9,574 → <N> LOC (<P>% reduction)
- App methods: 296 → <N>
- Tests: 1666 pass (unchanged)
- Launcher import: 149ms → <N>ms
- VPS services: 12/12 active (no impact)

Remaining _dash_* (backtest/cockpit/common ~30 methods) stay in
launcher.py for Fase 3.1 if needed.

Spec: docs/superpowers/specs/2026-04-23-cleanup-phase-3-design.md
Plan: docs/superpowers/plans/2026-04-23-cleanup-phase-3.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin chore/repo-cleanup
```

Fill `<N>` and `<P>` placeholders with actual measurements.

- [ ] **Step 5: Print final report**

```bash
echo "=== FASE 3 LAUNCHER DECOMPOSITION — CONCLUÍDA ==="
echo "Branch feat/cleanup-phase-3 merged into chore/repo-cleanup"
echo ""
echo "Metrics:"
echo "  launcher.py: 9574 baseline → $(wc -l < launcher.py) LOC"
echo "  App methods: 296 baseline → $(grep -c '^    def ' launcher.py)"
echo ""
echo "Optimization roadmap: 3/3 phases complete."
```

---

## Self-Review (executed)

**Spec coverage:**
- ✅ Cluster `_arb*`: Tasks 2+3 (49 methods split em 24+25)
- ✅ `_dash_home_*`: Task 4 (3 methods)
- ✅ `_dash_portfolio_*`: Task 5 (5 methods — includes paper_edit_dialog)
- ✅ `_dash_trades_*`: Task 6 (3 methods)
- ✅ `_eng*`: Task 7 (24 methods, split em engines.py + engines_live.py)
- ✅ Gates cumulativos por commit: each Task tem smoke + pytest
- ✅ Rollback: push per commit
- ✅ VPS sanity: Task 8 Step 2
- ✅ Manual smoke: Task 8 Step 3

**Placeholder scan:** `<N>`, `<P>`, `<before>`, `<after>` são measurement outputs (não TBDs). Acceptable.

**Type consistency:** Method signatures preserved 1:1. `render(app, ...)` is the universal pattern.

**Risk coverage:**
- ✅ Risk 1 (self.after chains): delegate preserves name — continues resolving
- ✅ Risk 2 (self.<state>): sub-workflow says "replace self with app"
- ✅ Risk 3 (callback dicts): delegates preserve
- ✅ Risk 4 (test `app._method()`): delegates preserve
- ✅ Risk 5 (cross-cluster calls): `app.<other_method>` continues via delegate
- ✅ Risk 6 (closures over __init__ locals): flagged in Task 2 Step 2 "CRITICAL NOTES"

---

## Execution options

Plan complete and saved to `docs/superpowers/plans/2026-04-23-cleanup-phase-3.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch subagent per task, review between.

**2. Inline Execution** — execute in this session.
