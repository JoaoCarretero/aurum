# DATA > ENGINES — Screen Polish Design

**Date:** 2026-04-24
**Author:** Claude (brainstormed with Joao)
**Scope:** Cosmetic polish of the unified `DATA > ENGINES` screen (split pane: run list on left, detail on right). Zero behavior change.
**Approach:** A — Conservative polish, standardize typography, dividers, and alignment. No redesign.

---

## 1. Context

The launcher desktop exposes `DATA > ENGINES` as the single operator view for every run — live, paper, shadow, backtest — across local disk, SQLite ops index, and VPS cockpit. Rendering lives in two files:

- `launcher_support/screens/engines.py` — thin wrapper that mounts the header (`ENGINES` title + subtitle) and delegates the body.
- `launcher_support/runs_history.py` — the 1415-line body: filter chips, column header, sectioned list (LIVE / STALE / FINISHED), and the right-side detail pane (header + 7 stacked sections + optional error banner).

Joao's diagnosis (condensed): "letras e enquadramento" — typography jumps between 6/7/8/11/12/14pt without a rule, two different section-header functions paint titles in two different colors, dividers alternate between DIM2 and BORDER without logic, numeric columns are left-aligned instead of right-aligned, and the right pane stacks 7 sections flat with no grouping.

The goal is **standardization, not redesign**. Every change in this spec touches fonts, colors, widths, or padding. No state, no new widgets, no new behaviors.

---

## 2. Typography system

Three sizes, two weights. Anything outside this table is a bug.

| Tier | Size | Weight | Used for |
|------|------|--------|----------|
| **H1** | 10 | bold | Screen title ("ENGINES"), engine name in detail header |
| **H2** | 8 | bold | Section headers (`● LIVE`, `TELEMETRY`, `TRADES`), filter chips, block headers, error-banner label, MODE/STATUS/SRC in detail header |
| **COL** | 7 | bold | Column headers (both left pane and TRADES table — 7pt bold preserves pixel-accurate width alignment with 7pt rows) |
| **BODY** | 7 | normal | All data cells, detail values, log tail, run_id in detail header, section counts |
| **BODY-emph** | 7 | bold | Identity + outcome in data tables. Run rows: `ENGINE`, `ROI`, `SIG` when > 0, `SRC`. Trades rows: `SYMBOL`, `PNL` |

**Rule:** when in doubt, use BODY normal. Bold is rare — reserved for true emphasis.

**Why COL is 7pt bold and not 8pt bold:** Tk's `width=N` parameter measures in the widget's font units. Mixing 8pt header and 7pt rows breaks pixel-wise column alignment (Consolas 8pt is ~15% wider than 7pt). Keeping headers at 7pt bold preserves alignment.

---

## 3. Divider rules

| Case | Thickness | Color |
|------|-----------|-------|
| Between major blocks (filter chips → column header; detail header → body; between RUNTIME/PERFORMANCE/LOG blocks in right pane) | 1px | `BORDER` |
| Between sub-sections within a block (below column header, below section header, below `_detail_section` title) | 1px | `DIM2` |
| Between rows of the same section | none (density preserved) | — |

---

## 4. Left pane changes

### 4.1 Filter chips (`_render_left_header`, lines 600-642)

**Before:** 7pt bold, `padx=5 pady=2`, no border when inactive, `BG3` fill when active.

**After:**
- Font: 8pt bold (H2).
- Active chip: 1px `BORDER` around the label (true box); inactive chip has no border.
- Padding: `padx=8 pady=4` (more air).
- Gap between chips: `padx=(0, 6)` (was `(0, 3)`).
- Wrapper row: `pady=(10, 8)` (was `(8, 6)`).
- Divider after chips block: **1px `BORDER`** (was `DIM2`) — separates filter block from table block.

### 4.2 Column header (`_render_left_header`, `_COLUMNS`)

**Before:** 7pt bold, `anchor="w"` everywhere, labels mixed (`ST / ENGINE / MODE / STARTED / DUR / TICKS / SIG / EQ / ROI / TR / SRC`), widths `3/8/6/13/7/6/5/9/7/4/4` (sum 72 chars).

**After:**
- Font: 7pt bold (COL tier), color `DIM`.
- Labels unified to full words: `ST / ENGINE / MODE / STARTED / DUR / TICKS / SIG / EQUITY / ROI / TRADES / SRC`.
- Widths recomputed: `2/11/6/13/7/6/5/9/8/6/5` (sum 78 chars) — ENGINE fits `RENAISSANCE`/`BRIDGEWATER`/`JANE_STREET` (11 chars) without truncation, ROI fits `+999.99%`, SRC fits `LOCAL`.
- Numeric columns (`TICKS`, `SIG`, `EQUITY`, `ROI`, `TRADES`) use `anchor="e"` (right-align).
- Text columns (`ST`, `ENGINE`, `MODE`, `STARTED`, `SRC`) keep `anchor="w"`.
- Divider after column header: 1px `DIM2` (sub-division within the table block).

### 4.3 Section headers (`_render_list_section_header`, lines 807-816)

**Before:** 7pt bold title + 7pt count, divider `DIM2` below.

**After:**
- Title (`● LIVE` / `◌ STALE` / `○ FINISHED`): 8pt bold (H2), semantic color preserved (GREEN / AMBER / DIM).
- Count: 7pt normal `DIM2` (one tier below title — discreet).
- Wrapper `pady=(10, 3)` (was `(6, 2)`) — more air above to mark "new section".
- Divider below section header: **1px `BORDER`** (structural — marks entry into new block).

### 4.4 Run rows (`_render_run_row`, lines 819-886)

**Before:** 11 cells, all `anchor="w"`, weights distributed without a rule, `pady=0`.

**After:**
- All cells: 7pt normal (BODY), **except four bold-by-rule fields**:
  - `ENGINE` (engine name — primary identity).
  - `ROI` (value — P&L is what operator scans for).
  - `SIG` (value — only when > 0, signals real activity).
  - `SRC` (VPS/LOCAL/DB — critical for data-confidence assessment).
- Numeric cells (`TICKS`, `SIG`, `EQUITY`, `ROI`, `TRADES`): `anchor="e"` (decimals line up).
- Text cells (`ST`, `ENGINE`, `MODE`, `STARTED`, `SRC`): `anchor="w"`.
- Row `pady=(1, 1)` — 2px breathing room (was `0`).
- Status dot (`●` / `○`) keeps semantic color (GREEN / RED / DIM2).
- No divider between rows (density preserved).

### 4.5 Empty-state message

**Before:** `"   — nenhum run visível (local ou VPS) —"` 7pt italic `DIM2`, `anchor="w"`, `pady=8`.

**After:** same text, same font, but `anchor="center"` and `pady=16` — doesn't collide with the header when the list is empty.

---

## 5. Right pane (detail) changes

### 5.1 Detail header (`_render_detail_header`, lines 1212-1232)

**Before:** dot 12pt / ENGINE 11pt bold / MODE 8pt bold / STATUS 7pt bold / run_id 7pt normal / SRC 7pt bold — sizes 12/11/8/7/7/7 jumble.

**After:**
- Dot: 10pt (matches H1 tier), semantic color (GREEN running / RED failed / DIM2 else).
- ENGINE: 10pt bold `WHITE` (H1).
- MODE: 8pt bold (H2), color from the semantic palette (`MODE_PAPER=CYAN`, `MODE_DEMO=GREEN`, `MODE_TESTNET=AMBER`, `MODE_LIVE=RED`; fallback `DIM` for shadow/unknown). Currently always `AMBER`.
- STATUS: 8pt bold (H2), color = dot color.
- run_id: 7pt normal `DIM` (BODY).
- SRC: 8pt bold (H2), semantic color preserved (VPS=GREEN, DB=AMBER_D, LOCAL=CYAN).
- Separators `  ·  `: 7pt normal `DIM`.
- Divider below header: 1px `BORDER` (structural).

### 5.2 Unify section-header helpers (`_detail_section`, delete `_section`)

**Before:** two helpers with divergent styles in the same pane — `_detail_section` paints title in 7pt bold `AMBER_D`, `_section` (used by TRADES and LOG TAIL) paints title in 7pt bold `AMBER`.

**After:** delete `_section`. `_detail_section` becomes polyvalent:

```python
def _detail_section(parent, title, rows=None, extra=None):
    # Title row (H2 AMBER_D + optional extra BODY DIM)
    # Divider 1px DIM2
    # If rows is None -> return early (caller builds custom body)
    # Else render label (7pt DIM)/value (7pt color) pairs
```

- Title: always 8pt bold `AMBER_D` (H2).
- Optional `extra` annotation next to title: 7pt normal `DIM`.
- `pady=(10, 2)` above the title — air for "new section" feel.
- Value rows: 7pt normal (was 8pt) — matches label tier and rest of pane.
- `rows=None` path: callers (TRADES, LOG TAIL) build their own tabular bodies below.

TRADES and LOG TAIL are refactored to call `_detail_section(box, "TRADES", extra=f"last {N}", rows=None)` and then render their custom table/text body.

### 5.3 Trades table (`_render_detail_trades`, lines 1289-1352)

**Before:** column header `SYMBOL / DIR / ENTRY / EXIT / PNL / R / REASON` in 6pt bold `DIM2` — too small, destoes from the rest.

**After:**
- Table column header: 7pt bold `DIM` (COL tier — same as left-pane column headers).
- Rows: 7pt normal, bold reserved for `SYMBOL` and `PNL`.
- Numeric cells (`ENTRY`, `EXIT`, `PNL`, `R`): `anchor="e"`.
- Text cells (`SYMBOL`, `DIR`, `REASON`): `anchor="w"`.
- Widths unchanged (`9/5/9/9/9/5/8`).
- Section title via unified `_detail_section` path (item 5.2).

### 5.4 Error banner (`_render_error_banner`, lines 1027-1038)

**Before:** label `LAST ERROR` in 6pt bold `RED` (too small), text 7pt `RED` `wraplength=260`.

**After:**
- Label: 8pt bold `RED` (H2 — operator sees immediately).
- Text: 7pt `RED` preserved, `wraplength=380` (uses more pane width when window is wide).

### 5.5 Block grouping — RUNTIME / PERFORMANCE / LOG (labeled, option 5b)

The 7 detail sections currently stack flat. Group into 3 named blocks with labeled dividers:

```
[DETAIL HEADER]
[ERROR BANNER]  (conditional)

RUNTIME ─────────────────────────
  TELEMETRY
  SCAN (last tick)
  HEALTH
  PROBE DIAGNOSTIC  (conditional, engine == PROBE)

PERFORMANCE ─────────────────────
  ACCOUNT
  TRADES

LOG ─────────────────────────────
  LOG TAIL
```

**Block header style:** H2 (8pt bold) label in `DIM`, followed by a 1px `BORDER` line that fills the remaining width (terminal-style). Same size as section titles inside the block (`TELEMETRY`, `ACCOUNT`, ...) but in `DIM` color instead of `AMBER_D` — size equal, color role distinguishes "structural container" from "content title". Inserted by a new helper:

```python
def _render_block_header(parent, label):
    row = tk.Frame(parent, bg=PANEL)
    row.pack(fill="x", pady=(14, 2))
    tk.Label(row, text=label, font=(FONT, 8, "bold"),
             fg=DIM, bg=PANEL, anchor="w").pack(side="left", padx=(0, 6))
    tk.Frame(row, bg=BORDER, height=1).pack(side="left", fill="x", expand=True, pady=(4, 0))
```

`_load_detail` (lines 964-1024) calls `_render_block_header(body, "RUNTIME")` before TELEMETRY, `"PERFORMANCE"` before ACCOUNT, `"LOG"` before LOG TAIL.

---

## 6. Screen-title header (`screens/engines.py`)

**Before:** `ENGINES` at 14pt bold, subtitle at 8pt normal.

**After:** `ENGINES` at **10pt bold** (H1 — consistent with the typography system). Subtitle text stays but font drops to **7pt** (BODY) for consistency with the rest of the pane.

---

## 7. Files touched

| File | Functions changed | Approx lines |
|------|-------------------|--------------|
| `launcher_support/runs_history.py` | `_render_left_header`, `_COLUMNS`, `_render_list_section_header`, `_render_run_row`, `_render_detail_header`, `_detail_section`, `_render_detail_trades`, `_render_detail_log_tail`, `_render_error_banner`, `_load_detail`; delete `_section` | ~150 |
| `launcher_support/screens/engines.py` | `build()` — title/subtitle font tweak | ~10 |
| **Total** | | **~160 lines** |

Single commit. No other files. No tests to add (pure visual change; existing smoke tests cover the render paths).

---

## 8. Behavior guarantees (non-changes)

The following are **explicitly unchanged**:

- Filter logic (`state["filter_mode"]` and the chip click handlers).
- Row click / selection (`_click`, `_load_detail`, highlight via `BG2`).
- Hover (`_hover_on`, `_hover_off`, BG3 hover fill).
- Auto-refresh cadence (5s via `_schedule_refresh`).
- VPS lazy heartbeat fetch (`lazy_fetch_heartbeat`, async path).
- Data sources (`collect_local_runs`, `collect_db_runs`, `collect_vps_runs`, `merge_runs`).
- Row limits (LIVE:20, STALE:20, FINISHED:60).
- Log tail path resolution, trades file fallback (shadow_trades.jsonl → trades.jsonl).
- `_engines_tab_active` signalling to suppress duplicate titles.

If anything listed above diverges, it's a bug introduced by implementation, not by design.

---

## 9. Validation

- **Smoke:** `python smoke_test.py --quiet` — must pass 156/156 unchanged.
- **Manual:** launcher → `DATA > ENGINES` with (a) empty list, (b) only LIVE rows, (c) mixed LIVE/STALE/FINISHED, (d) click through every section of a VPS run with heartbeat, (e) click through a local run with trades + logs, (f) trigger error banner by picking a run with `last_error` in heartbeat.
- **Pixel-check:** columns in header and rows must align pixel-wise. Numeric decimals must line up vertically within a column.

---

## 10. Out of scope (for this spec)

Explicitly NOT in this polish pass — save for future work if Joao wants them:

- Zebra striping on rows.
- Status bar at row edge (colored 2px strip replacing the `●`/`○` dot).
- Sort indicators (▲▼) on column headers.
- Tabs/accordions in the right pane.
- Dynamic `wraplength` for the error banner.
- New palette colors (error-tinted background, etc).
- Shortcut keys for tabs or block navigation.
