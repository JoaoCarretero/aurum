# DATA > ENGINES — Screen Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply cosmetic polish to the unified `DATA > ENGINES` launcher screen — standardize typography, unify section-header helpers, right-align numeric columns, group the detail pane into 3 labeled blocks (RUNTIME / PERFORMANCE / LOG). Zero behavior change.

**Architecture:** Two files touched — `launcher_support/runs_history.py` (~150 lines across 10 functions) and `launcher_support/screens/engines.py` (~10 lines, title/subtitle fonts). All changes are pure Tk widget configuration: font tuples, colors, anchors, widths, padding. No new state, no new event handlers, no new data paths.

**Tech Stack:** Python 3.14, Tkinter, pytest, Consolas monospace (from `core.ui.ui_palette.FONT`).

**Spec:** `docs/superpowers/specs/2026-04-24-engines-screen-polish-design.md`

---

## Pre-flight

- [ ] **Step 0.1: Verify current state before any change**

Run: `python smoke_test.py --quiet`

Expected: all tests pass (currently 156/156). If this fails, STOP — do not start implementation. Fix baseline first.

Run: `python -m pytest tests/test_runs_history.py -v`

Expected: all tests pass. Capture count for later comparison.

- [ ] **Step 0.2: Confirm target files match spec line ranges**

Run: `wc -l launcher_support/runs_history.py launcher_support/screens/engines.py`

Expected: `runs_history.py` = 1415 lines, `engines.py` = 415 lines. If the counts have drifted significantly, re-read the spec and confirm line references are still accurate before patching.

---

### Task 1: Screen title + subtitle typography (`screens/engines.py`)

**Files:**
- Modify: `launcher_support/screens/engines.py:40-48`

Context: the wrapper that mounts "ENGINES" above the runs_history body. Currently title is 14pt bold and subtitle is 8pt. Per spec §2 + §6, title is H1 (10pt bold) and subtitle is BODY (7pt).

- [ ] **Step 1.1: Apply the font change**

Edit `launcher_support/screens/engines.py`, in the `build()` method at lines 41-48, change the two `tk.Label` calls inside `head`:

```python
        tk.Label(head, text="ENGINES", font=(FONT, 10, "bold"),
                 fg=AMBER, bg=BG, anchor="w").pack(anchor="w")
        tk.Label(head,
                 text="Timeline unificada de runs — local + VPS merged. "
                      "Click row pra heartbeat, scan funnel, health, probe, "
                      "log tail e trades — tudo num so detail pane.",
                 font=(FONT, 7), fg=DIM, bg=BG, anchor="w"
                 ).pack(anchor="w", pady=(3, 8))
```

Only the font tuples change (14→10 on title, 8→7 on subtitle). Everything else is identical.

- [ ] **Step 1.2: Verify the screen still renders**

Run: `python -m pytest tests/launcher/ -v -k "engines or screen_entrypoints" --tb=short`

Expected: tests pass. If a smoke test explicitly asserts font "14" it will fail — update the assertion to "10". Grep first:

Run: `grep -rn "ENGINES.*14" tests/ launcher_support/`

Expected: the only match should be the test you need to update (if any). If no matches, proceed.

- [ ] **Step 1.3: Commit**

```bash
git add launcher_support/screens/engines.py
git commit -m "style(engines): title H1 (10pt bold), subtitle BODY (7pt)

Align the DATA > ENGINES screen header with the typography system
defined in docs/superpowers/specs/2026-04-24-engines-screen-polish-design.md.
No behavior change."
```

---

### Task 2: Column schema (`runs_history.py:_COLUMNS`)

**Files:**
- Modify: `launcher_support/runs_history.py:645-657`

Context: the `_COLUMNS` constant is consumed by `_render_left_header` to paint column titles and by `_render_run_row` implicitly (each cell uses the same width). Per spec §4.2, labels go full-word and widths grow to fit `RENAISSANCE`/`BRIDGEWATER`/`JANE_STREET` (11 chars), `+999.99%` (8 chars), `LOCAL` (5 chars), `TRADES` (6 chars).

- [ ] **Step 2.1: Replace the `_COLUMNS` constant**

In `launcher_support/runs_history.py`, replace lines 645-657 with:

```python
_COLUMNS = [
    ("ST",      2),
    ("ENGINE",  11),
    ("MODE",    6),
    ("STARTED", 13),
    ("DUR",     7),
    ("TICKS",   6),
    ("SIG",     5),
    ("EQUITY",  9),
    ("ROI",     8),
    ("TRADES",  6),
    ("SRC",     5),
]
```

Only the labels (`EQ`→`EQUITY`, `TR`→`TRADES`) and widths changed. Order is identical.

- [ ] **Step 2.2: Add an assertion test on `_COLUMNS`**

Append to `tests/test_runs_history.py`:

```python
def test_columns_schema():
    """_COLUMNS defines 11 cells in a fixed order. Widths fit the longest
    realistic value (RENAISSANCE for engine, +999.99% for roi, LOCAL for src)."""
    from launcher_support.runs_history import _COLUMNS
    labels = [c[0] for c in _COLUMNS]
    assert labels == ["ST", "ENGINE", "MODE", "STARTED", "DUR",
                      "TICKS", "SIG", "EQUITY", "ROI", "TRADES", "SRC"]
    widths = dict(_COLUMNS)
    assert widths["ENGINE"] == 11
    assert widths["ROI"] == 8
    assert widths["SRC"] == 5
    assert widths["TRADES"] == 6
```

- [ ] **Step 2.3: Run the assertion**

Run: `python -m pytest tests/test_runs_history.py::test_columns_schema -v`

Expected: PASS.

- [ ] **Step 2.4: Commit**

```bash
git add launcher_support/runs_history.py tests/test_runs_history.py
git commit -m "style(engines): column schema — full-word labels, widths fit longest values

ENGINE=11 (RENAISSANCE/BRIDGEWATER/JANE_STREET), ROI=8 (+999.99%),
TRADES=6, SRC=5 (LOCAL). Labels EQ→EQUITY, TR→TRADES for uniform
naming. No behavior change."
```

---

### Task 3: Left header — chips + column header rendering (`runs_history.py:_render_left_header`)

**Files:**
- Modify: `launcher_support/runs_history.py:600-642`

Context: paints the filter chips and the column header row. Per spec §4.1 + §4.2 + §3, chips become H2 (8pt bold) with a 1px BORDER box when active, column headers are 7pt bold (COL tier) with numeric cells right-aligned, dividers follow the rule (BORDER between blocks, DIM2 for sub-divisions).

- [ ] **Step 3.1: Replace `_render_left_header`**

In `launcher_support/runs_history.py`, replace lines 600-642 with:

```python
def _render_left_header(parent: tk.Widget, state: dict, launcher) -> None:
    """Filter chips + column header for the runs table.

    Chips are 1px BORDER boxes when active (H2 8pt bold). Column headers
    are COL tier (7pt bold) to preserve pixel-accurate width alignment
    with 7pt rows. Numeric columns right-aligned to match rows.
    Divider rule: BORDER between blocks, DIM2 for sub-divisions.
    """
    current = state.get("filter_mode", "all")
    f_row = tk.Frame(parent, bg=BG)
    f_row.pack(fill="x", padx=10, pady=(10, 8))
    for idx, label in enumerate(("ALL", "SHADOW", "PAPER"), start=1):
        key = label.lower()
        is_active = (current == "all" and key == "all") or (current == key)

        def _pick(_e=None, _k=key):
            state["filter_mode"] = "all" if _k == "all" else _k
            fn = state.get("refresh_fn")
            if fn:
                fn()
        chip = tk.Label(
            f_row, text=f" {idx}:{label} ",
            font=(FONT, 8, "bold"),
            fg=AMBER_D if is_active else DIM,
            bg=BG3 if is_active else BG,
            cursor="hand2", padx=8, pady=4,
            highlightbackground=BORDER if is_active else BG,
            highlightthickness=1,
        )
        chip.pack(side="left", padx=(0, 6))
        chip.bind("<Button-1>", _pick)

    # Divider between filter block and table block — BORDER (structural).
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=10)

    # Column header — 7pt bold (COL tier, preserves alignment with rows).
    # Numeric columns right-aligned.
    numeric = {"TICKS", "SIG", "EQUITY", "ROI", "TRADES"}
    col_hdr = tk.Frame(parent, bg=BG)
    col_hdr.pack(fill="x", padx=10, pady=(6, 2))
    for label, w in _COLUMNS:
        anchor = "e" if label in numeric else "w"
        tk.Label(col_hdr, text=label, fg=DIM, bg=BG,
                 font=(FONT, 7, "bold"), width=w,
                 anchor=anchor).pack(side="left", padx=(2, 0))
    # Divider below column header — DIM2 (sub-division within table block).
    tk.Frame(parent, bg=DIM2, height=1).pack(fill="x", padx=10)
```

Key changes vs original:
- Chip font 7→8 bold, padx 5→8, pady 2→4, gap 3→6, `highlightthickness=1 + highlightbackground=BORDER` when active.
- Wrapper pady `(8, 6)` → `(10, 8)`.
- Divider after chips now `bg=BORDER` (was `DIM2`).
- Column header loop now checks `numeric` set to pick `anchor="e"` for the 5 numeric columns.

- [ ] **Step 3.2: Smoke-render the screen in a hidden root**

Append to `tests/test_runs_history.py`:

```python
def test_render_left_header_smoke(gui_root):
    """_render_left_header paints chips + column header without exception.
    Validates the structural contract post-polish: no crash, widgets created."""
    from launcher_support.runs_history import _render_left_header
    frame = tk.Frame(gui_root)
    state = {"filter_mode": "all", "refresh_fn": lambda: None}
    _render_left_header(frame, state, None)
    # Sanity: at least the chip row and the column header row were packed.
    children = frame.winfo_children()
    assert len(children) >= 3  # chip row + divider + col header row (+ optional divider)
```

Add `import tkinter as tk` if not present at the top.

Run: `python -m pytest tests/test_runs_history.py::test_render_left_header_smoke -v`

Expected: PASS.

- [ ] **Step 3.3: Commit**

```bash
git add launcher_support/runs_history.py tests/test_runs_history.py
git commit -m "style(engines): filter chips as bordered H2, column header COL tier

Chips: 8pt bold with 1px BORDER box when active (was flat 7pt with
BG3 fill only). Column header: 7pt bold with anchor='e' on numeric
columns (TICKS/SIG/EQUITY/ROI/TRADES) to align decimals with rows.
Divider rule enforced: BORDER after chips block, DIM2 below column
header. No behavior change."
```

---

### Task 4: Section headers (`runs_history.py:_render_list_section_header`)

**Files:**
- Modify: `launcher_support/runs_history.py:807-816`

Context: paints `● LIVE · N` / `◌ STALE · N` / `○ FINISHED · N` above each row group. Per spec §4.3, title goes to H2 (8pt bold), count drops to BODY DIM2, divider below becomes BORDER.

- [ ] **Step 4.1: Replace `_render_list_section_header`**

Replace lines 807-816 with:

```python
def _render_list_section_header(parent: tk.Widget, title: str,
                                 count: int, color: str) -> None:
    """Section header separating LIVE / STALE / FINISHED in the list pane.

    Title is H2 (8pt bold, semantic color). Count is BODY (7pt normal
    DIM2). Divider below is BORDER (structural — marks new block).
    """
    hdr = tk.Frame(parent, bg=BG)
    hdr.pack(fill="x", padx=10, pady=(10, 3))
    tk.Label(hdr, text=title, font=(FONT, 8, "bold"),
             fg=color, bg=BG).pack(side="left")
    tk.Label(hdr, text=f"  ·  {count}", font=(FONT, 7),
             fg=DIM2, bg=BG).pack(side="left")
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=10, pady=(1, 2))
```

Changes: title font 7→8, count weight dropped from bold implicit to normal, count color DIM2 (unchanged), wrapper pady `(6, 2)` → `(10, 3)`, divider `bg=DIM2` → `bg=BORDER`.

- [ ] **Step 4.2: Smoke test**

Append to `tests/test_runs_history.py`:

```python
def test_render_list_section_header_smoke(gui_root):
    from launcher_support.runs_history import _render_list_section_header
    from core.ui.ui_palette import GREEN
    frame = tk.Frame(gui_root)
    _render_list_section_header(frame, "● LIVE", 7, color=GREEN)
    children = frame.winfo_children()
    # hdr row + divider
    assert len(children) == 2
```

Run: `python -m pytest tests/test_runs_history.py::test_render_list_section_header_smoke -v`

Expected: PASS.

- [ ] **Step 4.3: Commit**

```bash
git add launcher_support/runs_history.py tests/test_runs_history.py
git commit -m "style(engines): section header H2 title + BORDER divider

LIVE/STALE/FINISHED titles move to 8pt bold (H2), count stays at 7pt
DIM2, divider below becomes BORDER (structural) — matches the rule
for new-block markers. No behavior change."
```

---

### Task 5: Run rows (`runs_history.py:_render_run_row`)

**Files:**
- Modify: `launcher_support/runs_history.py:819-886`

Context: the cells in each run row. Per spec §4.4, all cells are 7pt normal except four bold-by-rule fields (ENGINE, ROI, SIG when > 0, SRC); numeric cells get `anchor="e"`; row `pady=(1, 1)`.

- [ ] **Step 5.1: Replace the cell list + pack loop in `_render_run_row`**

Replace lines 840-859 (the `cells = [...]` block and the `for text, color, w, weight in cells:` loop) with:

```python
    # Cells: (text, color, width, weight, anchor).
    # Weight rule: bold only on identity + outcome — ENGINE, ROI, SRC,
    # and SIG when > 0. Anchor rule: right-align numerics for decimal
    # alignment, left-align text for readability.
    cells = [
        (dot, dot_color, 2, "bold", "w"),
        (r.engine[:11], WHITE, 11, "bold", "w"),
        (r.mode[:6], mode_color, 6, "normal", "w"),
        (fmt_started(r.started_at), DIM, 13, "normal", "w"),
        (dur, WHITE, 7, "normal", "w"),
        (ticks, WHITE if (r.ticks_ok or 0) > 0 else DIM2, 6, "normal", "e"),
        (sig, AMBER_B if (r.novel or 0) > 0 else DIM2, 5,
         "bold" if (r.novel or 0) > 0 else "normal", "e"),
        (fmt_equity(r.equity), WHITE, 9, "normal", "e"),
        (roi_txt, roi_color, 8, "bold", "e"),
        (tr, WHITE, 6, "normal", "e"),
        (r.source.upper(), src_color, 5, "bold", "w"),
    ]
    labels = []
    for text, color, w, weight, anchor in cells:
        lbl = tk.Label(row, text=text, fg=color, bg=bg,
                       font=(FONT, 7, weight), width=w,
                       anchor=anchor)
        lbl.pack(side="left", padx=(2, 0))
        labels.append(lbl)
```

Also change the row packing line (currently at line 823):

```python
    row.pack(fill="x", padx=10, pady=(1, 1))
```

(was `pady=0`).

Also extend the engine slice from `[:8]` to `[:11]` and the `r.source` stays `.upper()[:5]` implicitly via width=5.

- [ ] **Step 5.2: Verify column widths match `_COLUMNS` order**

Grep to confirm every width in `cells` matches the corresponding entry in `_COLUMNS`:

Run: `python -c "from launcher_support.runs_history import _COLUMNS; print(_COLUMNS)"`

Expected output:
```
[('ST', 2), ('ENGINE', 11), ('MODE', 6), ('STARTED', 13), ('DUR', 7), ('TICKS', 6), ('SIG', 5), ('EQUITY', 9), ('ROI', 8), ('TRADES', 6), ('SRC', 5)]
```

Cross-check against the widths in the `cells` list: 2, 11, 6, 13, 7, 6, 5, 9, 8, 6, 5. They must match exactly — if not, the table is misaligned.

- [ ] **Step 5.3: Smoke test with a synthetic run**

Append to `tests/test_runs_history.py`:

```python
def test_render_run_row_smoke(gui_root):
    """_render_run_row paints without exception. Verifies cell count
    matches _COLUMNS (11 cells, no drift after polish)."""
    from launcher_support.runs_history import _render_run_row, _COLUMNS, RunSummary
    frame = tk.Frame(gui_root)
    r = RunSummary(
        run_id="test-1", engine="RENAISSANCE", mode="shadow",
        status="running", started_at="2026-04-20T10:00:00+00:00",
        stopped_at=None, last_tick_at="2026-04-20T10:30:00+00:00",
        ticks_ok=120, ticks_fail=0, novel=3,
        equity=1050.0, initial_balance=1000.0, roi_pct=5.0,
        trades_closed=2, source="vps", run_dir=None, heartbeat={},
    )
    _render_run_row(frame, r, {"selected_run_id": None})
    rows = frame.winfo_children()
    assert len(rows) == 1  # one row frame
    cells = rows[0].winfo_children()
    assert len(cells) == len(_COLUMNS)  # 11 cells, matches column schema
```

Run: `python -m pytest tests/test_runs_history.py::test_render_run_row_smoke -v`

Expected: PASS.

- [ ] **Step 5.4: Commit**

```bash
git add launcher_support/runs_history.py tests/test_runs_history.py
git commit -m "style(engines): run rows — bold identity/outcome, right-align numerics

Bold reserved for ENGINE, ROI, SIG (when > 0), SRC — identity and
outcome fields. Numeric cells (TICKS, SIG, EQUITY, ROI, TRADES) use
anchor='e' to line up decimals vertically. Row pady=(1, 1) for
breathing room. ENGINE slice bumped 8→11 to fit RENAISSANCE/
BRIDGEWATER/JANE_STREET in full. No behavior change."
```

---

### Task 6: Empty-state message (`runs_history.py:_paint_rows`)

**Files:**
- Modify: `launcher_support/runs_history.py:753-757`

Context: tiny change — when `rows` is empty, centered message with more vertical air. Per spec §4.5.

- [ ] **Step 6.1: Adjust the `tk.Label` inside the `if not rows:` branch**

Replace lines 753-757 with:

```python
    if not rows:
        tk.Label(wrap,
                 text="— nenhum run visível (local ou VPS) —",
                 fg=DIM2, bg=BG,
                 font=(FONT, 7, "italic")).pack(pady=16)
        return
```

Changes: removed leading spaces from the text (replaced with centered pack), removed `anchor="w"`, removed `padx=12`, bumped `pady=8` → `pady=16`.

- [ ] **Step 6.2: Commit**

```bash
git add launcher_support/runs_history.py
git commit -m "style(engines): empty-state message centered with 16px vertical air

Replaces left-anchored '   — nenhum run visível —' with a centered
label that doesn't collide with the column header when the list is
empty. No behavior change."
```

---

### Task 7: Unify `_section` and `_detail_section` (`runs_history.py`)

**Files:**
- Modify: `launcher_support/runs_history.py:1257-1271` (`_detail_section`)
- Modify: `launcher_support/runs_history.py:1289-1352` (`_render_detail_trades` — replace call to `_section`)
- Modify: `launcher_support/runs_history.py:1355-1388` (`_render_detail_log_tail` — replace call to `_section`)
- Delete: `launcher_support/runs_history.py:1391-1399` (`_section`)

Context: two divergent helpers paint section titles in two different colors. Consolidate to `_detail_section` with an `extra=` annotation and an `rows=None` early-return for custom-body callers. Per spec §5.2.

- [ ] **Step 7.1: Replace `_detail_section` signature + body**

Replace lines 1257-1271 with:

```python
def _detail_section(parent: tk.Widget, title: str,
                    rows: list[tuple[str, str, str]] | None = None,
                    extra: str | None = None) -> None:
    """Section header + optional label/value rows.

    Title is H2 (8pt bold AMBER_D). `extra` is a discreet annotation
    (e.g. 'last 10') shown in BODY (7pt normal DIM) next to the title.
    If `rows` is None, the caller builds a custom body below — useful
    for tables (TRADES) and streamed text (LOG TAIL).
    """
    hdr_row = tk.Frame(parent, bg=PANEL)
    hdr_row.pack(fill="x", pady=(10, 2))
    tk.Label(hdr_row, text=title,
             font=(FONT, 8, "bold"), fg=AMBER_D, bg=PANEL,
             anchor="w").pack(side="left")
    if extra:
        tk.Label(hdr_row, text=f"  ·  {extra}",
                 font=(FONT, 7), fg=DIM, bg=PANEL,
                 anchor="w").pack(side="left")
    tk.Frame(parent, bg=DIM2, height=1).pack(fill="x")
    if rows is None:
        return
    for k, v, color in rows:
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=0)
        tk.Label(row, text=k, font=(FONT, 7),
                 fg=DIM, bg=PANEL, anchor="w", width=10).pack(side="left")
        tk.Label(row, text=str(v), font=(FONT, 7),
                 fg=color, bg=PANEL, anchor="w").pack(side="left")
```

Key changes vs original:
- Signature gains `extra: str | None = None` and makes `rows` optional.
- Title font 7 → 8 bold (H2).
- Title wrapper `pady=(8, 2)` → `(10, 2)`.
- Value font 8 → 7 (matches label tier).
- Label font drops `bold` weight (was `(FONT, 7, "bold")` → now `(FONT, 7)`) — label bold was noise on tiny strings.
- Early return when `rows is None`.

- [ ] **Step 7.2: Refactor `_render_detail_trades` to use the unified helper**

In `_render_detail_trades` (lines 1289-1352), locate the block that does:

```python
    box = tk.Frame(parent, bg=PANEL)
    box.pack(fill="x", pady=(6, 2))
    _section(box, "TRADES", extra=f"last {len(lines)}")
    tbl = tk.Frame(box, bg=PANEL)
    tbl.pack(fill="x", pady=(1, 4))
```

Replace with:

```python
    box = tk.Frame(parent, bg=PANEL)
    box.pack(fill="x", pady=(6, 2))
    _detail_section(box, "TRADES", extra=f"last {len(lines)}")
    tbl = tk.Frame(box, bg=PANEL)
    tbl.pack(fill="x", pady=(1, 4))
```

Only `_section` → `_detail_section`. Signature-compatible (both accept `extra`).

- [ ] **Step 7.3: Refactor `_render_detail_log_tail` to use the unified helper**

In `_render_detail_log_tail` (lines 1355-1388), locate:

```python
    box = tk.Frame(parent, bg=PANEL)
    box.pack(fill="both", expand=True, pady=(6, 6))
    _section(box, "LOG TAIL", extra=log_path.name)
```

Replace with:

```python
    box = tk.Frame(parent, bg=PANEL)
    box.pack(fill="both", expand=True, pady=(6, 6))
    _detail_section(box, "LOG TAIL", extra=log_path.name)
```

- [ ] **Step 7.4: Delete `_section` (lines 1391-1399)**

Remove the entire function:

```python
def _section(parent: tk.Widget, title: str, extra: str | None = None) -> None:
    row = tk.Frame(parent, bg=PANEL)
    row.pack(fill="x")
    tk.Label(row, text=title.upper(), fg=AMBER, bg=PANEL,
             font=(FONT, 7, "bold")).pack(side="left")
    if extra:
        tk.Label(row, text=f"  ·  {extra}", fg=DIM, bg=PANEL,
                 font=(FONT, 7)).pack(side="left")
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(1, 2))
```

- [ ] **Step 7.5: Verify no callers of `_section` remain**

Run: `grep -n "_section(" launcher_support/runs_history.py`

Expected: zero matches (only the definition was named `_section`, and the two callers were just refactored). `_detail_section` will match — that's fine, it's the keep.

- [ ] **Step 7.6: Add an assertion test**

Append to `tests/test_runs_history.py`:

```python
def test_section_helper_deleted():
    """_section is replaced by the polyvalent _detail_section."""
    import launcher_support.runs_history as rh
    assert not hasattr(rh, "_section"), \
        "_section should be deleted — _detail_section replaces it"
    assert callable(rh._detail_section)


def test_detail_section_optional_rows(gui_root):
    """_detail_section(rows=None) emits header only, no crash."""
    from launcher_support.runs_history import _detail_section
    frame = tk.Frame(gui_root)
    _detail_section(frame, "TRADES", extra="last 3", rows=None)
    # Just the header row + divider.
    assert len(frame.winfo_children()) == 2
```

Run: `python -m pytest tests/test_runs_history.py::test_section_helper_deleted tests/test_runs_history.py::test_detail_section_optional_rows -v`

Expected: both PASS.

- [ ] **Step 7.7: Commit**

```bash
git add launcher_support/runs_history.py tests/test_runs_history.py
git commit -m "refactor(engines): unify _section into _detail_section

Two helpers were painting section titles in divergent colors (AMBER_D
vs AMBER) inside the same detail pane. _detail_section now accepts
extra= and rows=None, subsuming _section's use cases (TRADES and LOG
TAIL). Title: H2 8pt bold AMBER_D, value rows 7pt matching label tier.
Callers refactored, _section deleted. No behavior change."
```

---

### Task 8: Detail header (`runs_history.py:_render_detail_header`)

**Files:**
- Modify: `launcher_support/runs_history.py:1212-1232`

Context: the bar at the top of the right pane (dot + ENGINE + MODE + STATUS + run_id + SRC). Per spec §5.1, tighten to H1/H2/BODY and adopt semantic MODE_* palette colors.

- [ ] **Step 8.1: Replace `_render_detail_header`**

Replace lines 1212-1232 with:

```python
def _render_detail_header(parent: tk.Widget, r: RunSummary) -> None:
    """Detail pane header — dot + ENGINE (H1) + MODE/STATUS/SRC (H2) +
    run_id (BODY).

    MODE color uses the semantic palette (paper=CYAN, demo=GREEN,
    testnet=AMBER, live=RED); shadow/unknown fall back to DIM. Status
    and SRC keep their existing semantic mappings. Divider below is
    BORDER (structural).
    """
    from core.ui.ui_palette import MODE_PAPER, MODE_DEMO, MODE_TESTNET, MODE_LIVE
    bar = tk.Frame(parent, bg=BG)
    bar.pack(fill="x")
    inner = tk.Frame(bar, bg=BG)
    inner.pack(fill="x", padx=10, pady=7)
    dot_color = GREEN if r.status == "running" else (
        RED if r.status == "failed" else DIM2)
    mode_map = {
        "paper": MODE_PAPER, "demo": MODE_DEMO,
        "testnet": MODE_TESTNET, "live": MODE_LIVE,
    }
    mode_color = mode_map.get(r.mode, DIM)
    src_color = GREEN if r.source == "vps" else (
        AMBER_D if r.source == "db" else CYAN)
    tk.Label(inner, text="●", fg=dot_color, bg=BG,
             font=(FONT, 10)).pack(side="left", padx=(0, 6))
    tk.Label(inner, text=r.engine, fg=WHITE, bg=BG,
             font=(FONT, 10, "bold")).pack(side="left")
    tk.Label(inner, text=f"  {r.mode.upper()}",
             fg=mode_color, bg=BG,
             font=(FONT, 8, "bold")).pack(side="left")
    tk.Label(inner, text=f"  ·  {r.status.upper()}",
             fg=dot_color, bg=BG,
             font=(FONT, 8, "bold")).pack(side="left")
    tk.Label(inner, text=f"  ·  run {r.run_id}", fg=DIM, bg=BG,
             font=(FONT, 7)).pack(side="left")
    tk.Label(inner, text=f"  ·  {r.source.upper()}",
             fg=src_color, bg=BG,
             font=(FONT, 8, "bold")).pack(side="left")
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")
```

Key changes:
- Dot font 12 → 10.
- ENGINE font 11 → 10 (H1).
- MODE font stays 8 bold, but color now comes from `mode_map` (semantic) instead of always AMBER.
- STATUS font 7 → 8 (H2).
- run_id font 7 (unchanged, BODY).
- SRC font 7 → 8 (H2). Color logic moved to a named `src_color` var for clarity.

- [ ] **Step 8.2: Smoke render for each mode value**

Append to `tests/test_runs_history.py`:

```python
@pytest.mark.parametrize("mode", ["paper", "demo", "testnet", "live", "shadow", "unknown"])
def test_render_detail_header_mode_colors(gui_root, mode):
    """_render_detail_header paints without exception for every mode value."""
    from launcher_support.runs_history import _render_detail_header, RunSummary
    frame = tk.Frame(gui_root)
    r = RunSummary(
        run_id="test", engine="CITADEL", mode=mode, status="running",
        started_at=None, stopped_at=None, last_tick_at=None,
        ticks_ok=0, ticks_fail=0, novel=0,
        equity=None, initial_balance=None, roi_pct=None,
        trades_closed=None, source="vps", run_dir=None, heartbeat={},
    )
    _render_detail_header(frame, r)
    assert frame.winfo_children()
```

Run: `python -m pytest tests/test_runs_history.py::test_render_detail_header_mode_colors -v`

Expected: 6 PASS (one per parameter).

- [ ] **Step 8.3: Commit**

```bash
git add launcher_support/runs_history.py tests/test_runs_history.py
git commit -m "style(engines): detail header tightened to H1/H2/BODY + semantic MODE colors

ENGINE 11→10 bold (H1). MODE/STATUS/SRC all 8 bold (H2). Dot 12→10
pixel. run_id stays 7pt (BODY). MODE color now uses the MODE_* palette
(paper=CYAN, demo=GREEN, testnet=AMBER, live=RED, shadow/unknown=DIM)
instead of always AMBER. No behavior change."
```

---

### Task 9: Error banner (`runs_history.py:_render_error_banner`)

**Files:**
- Modify: `launcher_support/runs_history.py:1027-1038`

Context: the red strip shown below the detail header when a run's last tick errored. Per spec §5.4, label goes to H2 (8pt bold), wraplength grows 260→380.

- [ ] **Step 9.1: Update the label font + wraplength**

Replace lines 1027-1038 with:

```python
def _render_error_banner(parent: tk.Widget, err: str) -> None:
    """Red banner shown when the last heartbeat carries `last_error`.
    Label is H2 (8pt bold RED) so the operator registers the alert at
    first glance; text stays BODY (7pt RED) with wraplength tuned for
    the wider panes used by the cockpit-class displays."""
    bar = tk.Frame(parent, bg=BG)
    bar.pack(fill="x")
    inner = tk.Frame(bar, bg=BG)
    inner.pack(fill="x", padx=10, pady=(4, 6))
    tk.Label(inner, text="LAST ERROR", font=(FONT, 8, "bold"),
             fg=RED, bg=BG, anchor="w").pack(anchor="w")
    tk.Label(inner, text=err[:300], font=(FONT, 7),
             fg=RED, bg=BG, anchor="w", justify="left",
             wraplength=380).pack(anchor="w", pady=(1, 0))
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")
```

Changes: label font 6 → 8, wraplength 260 → 380. Everything else unchanged.

- [ ] **Step 9.2: Commit**

```bash
git add launcher_support/runs_history.py
git commit -m "style(engines): error banner label H2 + wider wraplength

Label 'LAST ERROR' goes from 6pt to 8pt bold (H2 — operator can't
miss it). Text wraplength 260 → 380 so long errors breathe on wide
cockpits. No behavior change."
```

---

### Task 10: Block headers — RUNTIME / PERFORMANCE / LOG (`runs_history.py`)

**Files:**
- Add helper: `launcher_support/runs_history.py` (new function, place right above `_render_detail_header` at line ~1212)
- Modify: `launcher_support/runs_history.py:1015-1024` (`_load_detail` section-render sequence)

Context: the right pane currently stacks 7 sections flat. Per spec §5.5, insert 3 labeled block headers to group them — RUNTIME (telemetry + scan + health + probe), PERFORMANCE (account + trades), LOG (log tail).

- [ ] **Step 10.1: Add `_render_block_header` helper**

Add this function immediately before `_render_detail_header` (line 1212):

```python
def _render_block_header(parent: tk.Widget, label: str) -> None:
    """Block header separating RUNTIME / PERFORMANCE / LOG in the right pane.

    H2 (8pt bold DIM) label followed by a 1px BORDER line that fills
    the remaining width. Same size as section titles inside the block,
    but DIM (not AMBER_D) to distinguish structural container from
    content title.
    """
    row = tk.Frame(parent, bg=PANEL)
    row.pack(fill="x", pady=(14, 2))
    tk.Label(row, text=label, font=(FONT, 8, "bold"),
             fg=DIM, bg=PANEL, anchor="w").pack(side="left", padx=(0, 6))
    tk.Frame(row, bg=BORDER, height=1).pack(
        side="left", fill="x", expand=True, pady=(6, 0))
```

- [ ] **Step 10.2: Update `_load_detail` to insert block headers**

In `_load_detail` (around lines 1015-1024), replace the section-render block:

```python
    body = tk.Frame(host, bg=PANEL)
    body.pack(fill="both", expand=True, padx=10, pady=(4, 0))

    _render_detail_telemetry(body, r)
    _render_detail_scan(body, r)
    _render_detail_health(body, r)
    _render_detail_probe(body, r)
    _render_detail_equity_metrics(body, r)
    _render_detail_trades(body, r)
    _render_detail_log_tail(body, r)
```

With:

```python
    body = tk.Frame(host, bg=PANEL)
    body.pack(fill="both", expand=True, padx=10, pady=(4, 0))

    # RUNTIME — what the engine is doing right now.
    _render_block_header(body, "RUNTIME")
    _render_detail_telemetry(body, r)
    _render_detail_scan(body, r)
    _render_detail_health(body, r)
    _render_detail_probe(body, r)

    # PERFORMANCE — how it's doing.
    _render_block_header(body, "PERFORMANCE")
    _render_detail_equity_metrics(body, r)
    _render_detail_trades(body, r)

    # LOG — raw engine output.
    _render_block_header(body, "LOG")
    _render_detail_log_tail(body, r)
```

Only the three `_render_block_header(body, ...)` calls are added. Section call order and arguments unchanged.

- [ ] **Step 10.3: Smoke test**

Append to `tests/test_runs_history.py`:

```python
def test_render_block_header_smoke(gui_root):
    from launcher_support.runs_history import _render_block_header
    frame = tk.Frame(gui_root)
    _render_block_header(frame, "RUNTIME")
    # The helper should create one row frame with 2 children (label + divider).
    outer = frame.winfo_children()
    assert len(outer) == 1
    row = outer[0]
    assert len(row.winfo_children()) == 2
```

Run: `python -m pytest tests/test_runs_history.py::test_render_block_header_smoke -v`

Expected: PASS.

- [ ] **Step 10.4: Commit**

```bash
git add launcher_support/runs_history.py tests/test_runs_history.py
git commit -m "feat(engines): group detail pane into RUNTIME/PERFORMANCE/LOG blocks

Seven flat sections become three labeled blocks: RUNTIME (telemetry,
scan, health, probe), PERFORMANCE (account, trades), LOG (log tail).
Block headers are 8pt bold DIM label + BORDER line filling the
remaining width — terminal style. Same size as section titles inside
but DIM color so container visually reads different from content.
No behavior change — all sections still render unconditionally with
the same data."
```

---

### Task 11: Trades table header (`runs_history.py:_render_detail_trades`)

**Files:**
- Modify: `launcher_support/runs_history.py` inside `_render_detail_trades` (lines 1318-1326 and the row rendering loop around 1336-1352)

Context: the trades mini-table has its own column header. Per spec §5.3, that header moves from 6pt bold DIM2 to 7pt bold DIM (COL tier), and numeric cells get `anchor="e"`.

- [ ] **Step 11.1: Update column-header font and anchor**

Replace lines 1320-1326 (the `hdr` block inside `_render_detail_trades`):

```python
    hdr = tk.Frame(tbl, bg=BG)
    hdr.pack(fill="x")
    numeric_trade = {"ENTRY", "EXIT", "PNL", "R"}
    for lbl, w in [("SYMBOL", 9), ("DIR", 5), ("ENTRY", 9), ("EXIT", 9),
                   ("PNL", 9), ("R", 5), ("REASON", 8)]:
        anchor = "e" if lbl in numeric_trade else "w"
        tk.Label(hdr, text=lbl, fg=DIM, bg=BG,
                 font=(FONT, 7, "bold"), width=w,
                 anchor=anchor).pack(side="left", padx=(3, 0))
```

Changes: fg `DIM2` → `DIM`, font 6 → 7, anchor becomes conditional.

- [ ] **Step 11.2: Update row anchor (decimal alignment)**

In the same function, replace the `cells = [...]` block inside the `for t in lines:` loop (around lines 1336-1346):

```python
        cells = [
            (str(t.get("symbol", "?"))[:9], WHITE, 9, "bold", "w"),
            (direction, (GREEN if direction.startswith(("L", "B"))
                          else RED), 5, "bold", "w"),
            (f"{float(ep):.5g}" if ep is not None else "—", WHITE, 9, "normal", "e"),
            (f"{float(xp):.5g}" if xp is not None else "—", WHITE, 9, "normal", "e"),
            (f"{pnl:+.2f}", pnl_color, 9, "bold", "e"),
            (f"{float(r_mul):+.2f}" if r_mul is not None else "—",
             pnl_color, 5, "normal", "e"),
            (reason, DIM, 8, "normal", "w"),
        ]
        row = tk.Frame(tbl, bg=PANEL)
        row.pack(fill="x")
        for text, color, w, weight, anchor in cells:
            tk.Label(row, text=text, fg=color, bg=PANEL,
                     font=(FONT, 7, weight), width=w,
                     anchor=anchor).pack(side="left", padx=(3, 0))
```

Key changes: added `anchor` as the 5th tuple element; ENTRY/EXIT/PNL/R right-aligned; SYMBOL/DIR/REASON left-aligned. SYMBOL and PNL keep bold (identity + outcome).

- [ ] **Step 11.3: Smoke render with a fake trades file**

Append to `tests/test_runs_history.py`:

```python
def test_render_detail_trades_smoke(gui_root, tmp_path):
    """_render_detail_trades paints a trades table for a run with a
    reports/trades.jsonl file, using the COL tier header."""
    from launcher_support.runs_history import _render_detail_trades, RunSummary
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "trades.jsonl").write_text(
        '{"symbol":"BTCUSDT","direction":"LONG","entry_price":65000,'
        '"exit_price":66000,"pnl_after_fees":100,"r_multiple":1.5,'
        '"exit_reason":"target"}\n',
        encoding="utf-8",
    )
    r = RunSummary(
        run_id="t", engine="CITADEL", mode="paper", status="stopped",
        started_at=None, stopped_at=None, last_tick_at=None,
        ticks_ok=0, ticks_fail=0, novel=0,
        equity=1100, initial_balance=1000, roi_pct=10,
        trades_closed=1, source="local", run_dir=tmp_path, heartbeat={},
    )
    frame = tk.Frame(gui_root)
    _render_detail_trades(frame, r)
    # box → _detail_section header + divider + tbl frame
    assert frame.winfo_children()
```

Run: `python -m pytest tests/test_runs_history.py::test_render_detail_trades_smoke -v`

Expected: PASS.

- [ ] **Step 11.4: Commit**

```bash
git add launcher_support/runs_history.py tests/test_runs_history.py
git commit -m "style(engines): trades table header COL tier + right-aligned numerics

Column header 6pt bold DIM2 → 7pt bold DIM (COL tier — same as left
pane). Numeric cells (ENTRY, EXIT, PNL, R) use anchor='e' so decimals
line up vertically. SYMBOL and PNL keep bold (identity + outcome
rule). No behavior change."
```

---

### Task 12: Final validation

**Files:** none (validation only)

- [ ] **Step 12.1: Run the full smoke suite**

Run: `python smoke_test.py --quiet`

Expected: same pass count as Pre-flight step 0.1 (typically 156/156). If any test fails, diagnose before closing out.

- [ ] **Step 12.2: Run the full runs_history test file**

Run: `python -m pytest tests/test_runs_history.py -v`

Expected: all baseline tests + the new assertion/smoke tests added in Tasks 2/3/4/5/7/8/10/11 PASS.

- [ ] **Step 12.3: Launch the launcher and visually verify**

Launch: `python launcher.py`

Navigate: `DATA > ENGINES`.

Visual checklist:
- [ ] Screen title "ENGINES" renders at H1 size — not the old oversized 14pt.
- [ ] Filter chips `1:ALL / 2:SHADOW / 3:PAPER` have a 1px border when active.
- [ ] Column header labels show full words (`EQUITY`, `TRADES`, not `EQ`, `TR`).
- [ ] `TICKS`, `SIG`, `EQUITY`, `ROI`, `TRADES` align to the right in both header and rows.
- [ ] A row with `RENAISSANCE` or `BRIDGEWATER` shows the engine name in full (no truncation).
- [ ] Section headers `● LIVE`, `◌ STALE`, `○ FINISHED` are visibly one size larger than column headers.
- [ ] Click a VPS-backed row with heartbeat data; right pane shows three block labels: `RUNTIME`, `PERFORMANCE`, `LOG`, each with a BORDER line trailing the label.
- [ ] Detail header `ENGINE` line uses semantic MODE color (try a paper/live run if available — paper should be CYAN, live should be RED).
- [ ] If any run has `last_error` in heartbeat, the banner reads `LAST ERROR` clearly (8pt), not the previous tiny 6pt version.
- [ ] Click a run with trades history; table column header shows 7pt bold DIM labels; numeric columns (ENTRY/EXIT/PNL/R) right-align.

If any of the above doesn't match, reopen the corresponding task.

- [ ] **Step 12.4: Capture before/after screenshots (optional, for PR description)**

If opening a PR, take screenshots of `DATA > ENGINES` in these states:
- Empty list (filter SHADOW with no shadow runs).
- Mixed LIVE + STALE + FINISHED sections populated.
- Detail pane open on a VPS run showing all three blocks.
- Detail pane open on a run with `last_error` (error banner visible).

- [ ] **Step 12.5: Session log**

Per project CLAUDE.md, generate `docs/sessions/YYYY-MM-DD_HHMM.md` summarizing the polish work. No trading logic changed, so mark "Nenhuma mudança em lógica de trading" in the Mudanças Críticas section.

---

## Summary of changes

| File | Functions touched | Approx diff |
|------|-------------------|-------------|
| `launcher_support/runs_history.py` | `_render_left_header`, `_COLUMNS`, `_render_list_section_header`, `_render_run_row`, `_paint_rows` (empty state), `_detail_section`, `_render_detail_trades`, `_render_detail_log_tail`, `_render_error_banner`, `_render_detail_header`, `_render_block_header` (new), `_load_detail`, **delete** `_section` | ~150 lines |
| `launcher_support/screens/engines.py` | `build()` — title/subtitle fonts | ~10 lines |
| `tests/test_runs_history.py` | 8 new tests (schema + smoke per function) | ~120 lines |
| **Total** | | **~280 lines** |

12 commits, each self-contained and reversible.
