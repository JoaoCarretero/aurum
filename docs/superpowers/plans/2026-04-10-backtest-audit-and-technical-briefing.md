# Backtest Physics Audit + Technical Briefing Menu — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Audit the "physical correctness" of the backtest engine + 7 strategies, and replace the narrative strategy briefing menu with a structured technical view that includes pseudocode, parameters table, formulas, invariants, and an inline source viewer.

**Architecture:** Two parallel artifacts per strategy, produced from the same code-reading pass: (1) an entry in `docs/audits/backtest-physics-2026-04-10.md` with the 12-point "physical law" checklist; (2) a new structured entry in `BRIEFINGS_V2` inside `launcher.py` with 7 fields feeding 4 rendered blocks. UI changes are additive: `BRIEFINGS_V2` coexists with the legacy `BRIEFINGS` dict, and `_brief` dispatches by name. A new `CodeViewer` Tk class (`tk.Toplevel`, `ttk.Notebook` tabs, regex-based highlight) opens when the user clicks "VER CÓDIGO".

**Tech Stack:** Python 3.14 (system global, no venv), tkinter + ttk (bundled), no external dependencies added. Target: Windows Desktop (Consolas font assumed).

**Spec reference:** `docs/superpowers/specs/2026-04-10-backtest-audit-and-technical-briefing-design.md`

**Execution worktree:** `.worktrees/experiment` (already exists, on branch `feature/experiment`). All commits in this plan go to that branch unless noted.

---

## Plan Adjustments vs Spec

These corrections were found while reading the actual `launcher.py` after the spec was approved. They replace the corresponding parts of the spec where they conflict.

1. **`_brief` signature is `(self, name, script, desc, parent_menu)`** — 5 args, not 4. The `desc` argument is the short description shown in the menu row. It will be preserved in the refactor.
2. **Current `BRIEFINGS` has 6 strategies, not 7** — CITADEL, JUMP, BRIDGEWATER, DE SHAW, MILLENNIUM, TWO SIGMA. `JANE STREET` (arbitrage) is in the `live` menu currently and has no briefing. This plan **adds** a briefing for JANE STREET, bringing BRIEFINGS_V2 to 7 entries.
3. **`BRIEFINGS` stays alive** for the live modes (`PAPER`/`DEMO`/`TESTNET`/`LIVE` share one entry) and any future non-strategy items. `_brief` will dispatch: `if name in BRIEFINGS_V2: render_technical(...)` else `render_legacy(...)`. **No deletion of `BRIEFINGS`** — spec §8 step 11 is obsolete.
4. **Use the Bloomberg palette that already exists in `launcher.py:21-33`** (`BG`, `AMBER`, `WHITE`, `DIM`, `BG3`, `AMBER_D`, `GREEN`, `RED`) — do not invent new colors. `CodeViewer` uses `BG`, `AMBER`, `WHITE`, `DIM` matched to the launcher aesthetic.
5. **`ttk` must be imported** — add `from tkinter import ttk` alongside the existing `from tkinter import messagebox` at `launcher.py:16`.

---

## Shared References

### Audit checklist (L1-L12)

Full text lives in the spec at §4.1. Summary for convenience:

| # | Invariant | Grep / read patterns | Severity |
|---|---|---|---|
| L1 | No look-ahead: decision at `idx` uses no data from `idx+k, k≥1` | `shift(-`, `.iloc[i+`, `.iloc[idx+`, `fillna(True)` after a `shift()` | CRÍTICO |
| L2 | Execution delay: order generated at `idx` fills at `open[idx+1]` earliest | trace `label_trade` callers for `entry_idx=idx+1` | CRÍTICO |
| L3 | Fees in + fees out subtracted from PnL | trace `pnl` variable to return; look for `fee_in`, `fee_out`, `commission` | ALTO |
| L4 | Slippage applied (fill ≠ pure open/close) | `* (1 ± slippage)`, `slippage_bps`, `slip` | ALTO |
| L5 | Funding rate accounted per 8h period during trade | funding block in engine; respect sign (long pays when funding>0) | ALTO |
| L6 | Position sizing respects capital: `sum(open_notionals) ≤ capital × max_leverage` | `sum(open_notionals)`, `portfolio_allows`, notional aggregation | ALTO |
| L7 | Liquidation simulated: loss > margin → forced close with PnL = −margin | `liquidation`, `forced_close`, `margin_call` | MÉDIO |
| L8 | Indicators causal: use only `[0..idx]`, no negative shift | read `core/indicators.py` end-to-end; flag `shift(-k)` anywhere | CRÍTICO |
| L9 | NaN warmup doesn't fire trades: loop starts at `min_idx ≥ warmup` | find `min_idx = ...` assignment | MÉDIO |
| L10 | Timeframe alignment without ffill look-ahead | `merge_asof`, `reindex(method="ffill")` — must be BEFORE decision point | ALTO |
| L11 | Stop/target geometrically coherent: stop behind, target ahead per direction | `calc_levels` logic for long vs short | ALTO |
| L12 | Symbol universe free of survivorship bias (dynamic vs static) | how `symbols` is loaded — static list is a flag | INFO |

### Audit section template (markdown)

Every strategy section in `docs/audits/backtest-physics-2026-04-10.md` uses this exact template. Replace `<STRATEGY_NAME>` and each check's status + content.

```markdown
## <STRATEGY_NAME>

**Source files audited:** `<file1>`, `<file2>`, …
**Main function:** `<file>::<function_name>`
**Bars read:** <N lines of actual code read in this pass>

### L1 — Sem look-ahead: <STATUS>
<one-paragraph explanation with file:line refs>
<if not PASS, also:>
- **Severidade:** <CRÍTICO|ALTO|MÉDIO|BAIXO|INFO>
- **Repro:** <exact steps to observe>
- **Fix recomendado:** <specific code change>

### L2 — Delay de execução: <STATUS>
…

<repeat for L3 through L12>

### Resumo CITADEL
| L# | Status | Severidade |
|----|--------|------------|
| L1 | ✓ PASS | — |
| … |        |            |
```

Valid statuses: `✓ PASS`, `⚠️ SMELL`, `✗ FAIL`, `n/a` (use `n/a` only for checks that don't apply — e.g., L5 funding for a spot-only strategy; L12 survivorship if the strategy doesn't iterate over a symbol universe).

### BRIEFINGS_V2 entry template

Every strategy entry in `BRIEFINGS_V2` uses this exact schema. No placeholders remain in the final version.

```python
"<STRATEGY_NAME>": {
    "source_files": ["path/to/main.py", "path/to/helper.py", ...],
    "main_function": ("path/to/main.py", "function_name"),
    "one_liner": "<one-sentence technical summary, max ~80 chars>",
    "pseudocode": """\
<multi-line Python-like block showing the decision loop>
""",
    "params": [
        {"name": "PARAM_NAME", "default": <value>, "range": "<range_str>",
         "unit": "<unit>", "effect": "<short effect description>"},
        ...
    ],
    "formulas": [
        "<formula 1 in Unicode notation>",
        ...
    ],
    "invariants": [
        "<invariant 1>",
        ...
    ],
},
```

Field requirements:

- `source_files`: list of 1-4 relative paths from repo root. Order = relevance. First entry = main file.
- `main_function`: tuple `(file_path, function_name)`. `file_path` MUST equal `source_files[0]`.
- `one_liner`: single sentence, pure technical (no marketing adjectives).
- `pseudocode`: multi-line string (use `"""\`), minimum 5 lines, maximum ~25 lines. Python-like but not required to run. Use real parameter names.
- `params`: list of dicts, minimum 3 entries, maximum 10. Every dict has exactly the 5 keys: `name`, `default`, `range`, `unit`, `effect`. `default` is any JSON-serializable value. `range`, `unit`, `effect` are strings. Use `"—"` for no unit.
- `formulas`: list of strings, minimum 2 entries, maximum 8. Unicode allowed (`·`, `²`, `√`, `Σ`, `α`, `β`). Single line each.
- `invariants`: list of strings, minimum 3 entries, maximum 8. Each is a pre-condition or assumption the strategy relies on.

### Smoke test script

Every smoke test is manual — run `python launcher.py` in the worktree. The steps below are the checklist per strategy. Save as notes in the task description; don't script it.

```
1. Open launcher: `cd .worktrees/experiment && python launcher.py`
2. Navigate to the appropriate menu (BACKTEST for CITADEL/JUMP/BRIDGEWATER/DE SHAW/MILLENNIUM/TWO SIGMA; LIVE for JANE STREET)
3. Click the strategy row
4. Verify:
   a. Header shows strategy name + one_liner
   b. PSEUDOCODE block is visible, mono font, dark bg
   c. PARAMETERS table is visible with 5 columns (name / default / range / unit / effect)
   d. FORMULAS block is visible, mono font
   e. INVARIANTS block is visible as bullet list
   f. "VER CÓDIGO" button is present
   g. "CONFIGURAR & RODAR" (or equivalent) button is still present
5. Click VER CÓDIGO
6. Verify:
   a. A new Toplevel window opens
   b. It has tabs for each file in source_files
   c. First tab = main source file, scrolled near the `def <main_function>` line
   d. Syntax highlight is visible (keywords blue, strings green, comments grey, numbers orange, def names yellow)
   e. ESC key closes the window
7. Back in briefing, click CONFIGURAR & RODAR
8. Verify the backtest (or live) configuration screen opens normally — we didn't break the downstream flow
9. ESC back to main menu, done
```

---

## File Structure

**Created in this plan:**

- `docs/audits/backtest-physics-2026-04-10.md` — growing document, one section per strategy (plus one for the engine core)
- `docs/audits/backtest-fixes-backlog.md` — generated at the end from the audit doc

**Modified in this plan:**

- `launcher.py`:
  - Add import: `from tkinter import ttk` (line ~16)
  - Add new `BRIEFINGS_V2` dict (after existing `BRIEFINGS`, around line ~260)
  - Add new `CodeViewer` class (before the main `class App:` that contains `_brief`)
  - Refactor `_brief()` method (currently at line 753) to dispatch V2 vs legacy
  - Add new helper methods: `_render_technical_brief`, `_render_pseudocode`, `_render_params_table`, `_render_formulas`, `_render_invariants`, `_open_code_viewer`
  - **Do not touch** the legacy `BRIEFINGS` dict (lines 173-258)
  - **Do not touch** `_config_backtest`, `_config_live`, `_exec`, ticker, VPS, anything else

**Out of scope (explicitly untouched):**

- `engines/*.py`, `core/*.py` — read only, never written
- `config/*`, `data/*`, tests (none exist), any other file

---

## Phase 1 — Infrastructure (Tasks 1–5)

This phase adds the UI scaffolding with placeholder data for CITADEL only. After Phase 1 the user can run the launcher and see the new technical layout rendering placeholder data, but no real audit has happened yet.

---

### Task 1: Pre-flight grep for `BRIEFINGS` usage

**Files:**
- Read: `launcher.py`
- Read (grep target): entire repo

**Purpose:** Confirm `BRIEFINGS` is referenced only in `_brief()` before we add `BRIEFINGS_V2` alongside it. If there are other callers we haven't seen, they might break.

- [ ] **Step 1: Grep for all references to BRIEFINGS in the repo**

Run:
```
grep -rn "BRIEFINGS" --include="*.py" .
```

Expected output:
```
launcher.py:173:BRIEFINGS = {
launcher.py:248:BRIEFINGS["PAPER"] = BRIEFINGS["DEMO"] = ...
launcher.py:760:        brief = BRIEFINGS.get(name, {})
launcher.py:774:        if brief.get("philosophy"):
launcher.py:779:        if brief.get("logic"):
launcher.py:789:        if brief.get("edge") or brief.get("risk"):
launcher.py:793:            if brief.get("edge"):
launcher.py:798:            if brief.get("risk"):
```

All references should be inside `launcher.py`. If any reference appears in a different file, **stop and investigate** before proceeding — the plan assumes `BRIEFINGS` is launcher-local.

- [ ] **Step 2: Document the finding**

Create a file `.plan-notes/task-01-briefings-usage.md` with the grep output. This note is ephemeral (for the implementing agent's reference) and not committed.

Contents:
```
Grep result for "BRIEFINGS" in repo (2026-04-10):

<paste the grep output here>

All references live in launcher.py — safe to add BRIEFINGS_V2 alongside.
```

- [ ] **Step 3: No commit** — this task produces no code changes. Proceed to Task 2.

---

### Task 2: Add `ttk` import + empty `BRIEFINGS_V2` scaffold

**Files:**
- Modify: `launcher.py:16` (add import)
- Modify: `launcher.py:~260` (add BRIEFINGS_V2 after existing BRIEFINGS block)

- [ ] **Step 1: Read the current imports in launcher.py**

Read lines 1-20 of `launcher.py` and confirm line 16 is `from tkinter import messagebox`.

- [ ] **Step 2: Add `ttk` import**

Edit `launcher.py:16`:

Change:
```python
from tkinter import messagebox
```

To:
```python
from tkinter import messagebox, ttk
```

- [ ] **Step 3: Locate the insertion point for BRIEFINGS_V2**

Read lines 245-262 of `launcher.py`. The shared live briefing assignment ends at line 258 or 259. Find the first blank line AFTER that assignment and before the next non-briefing code.

- [ ] **Step 4: Insert the empty BRIEFINGS_V2 dict**

Immediately after the `BRIEFINGS["PAPER"] = ...` block, insert:

```python

# ═══════════════════════════════════════════════════════════
# STRATEGY BRIEFINGS V2 — structured technical view
# Each entry drives the new _brief technical rendering.
# Schema: see docs/superpowers/plans/2026-04-10-backtest-audit-and-technical-briefing.md
# ═══════════════════════════════════════════════════════════
BRIEFINGS_V2 = {
    "CITADEL": {
        "source_files": ["engines/backtest.py"],
        "main_function": ("engines/backtest.py", "scan_symbol"),
        "one_liner": "Placeholder — will be populated during Phase 2 audit.",
        "pseudocode": "# placeholder\nfor idx in range(n):\n    pass\n",
        "params": [
            {"name": "PLACEHOLDER", "default": 0, "range": "0-1", "unit": "—", "effect": "placeholder"},
            {"name": "PLACEHOLDER_2", "default": 0, "range": "0-1", "unit": "—", "effect": "placeholder"},
            {"name": "PLACEHOLDER_3", "default": 0, "range": "0-1", "unit": "—", "effect": "placeholder"},
        ],
        "formulas": [
            "placeholder_formula = a + b",
            "another = c · d",
        ],
        "invariants": [
            "Placeholder invariant 1",
            "Placeholder invariant 2",
            "Placeholder invariant 3",
        ],
    },
}
```

Only CITADEL is scaffolded in this task. The other 6 strategies get added in Phase 2 (CITADEL real) and Phase 3 (others). Until populated, `_brief` will only render V2 layout for CITADEL; everything else still uses the legacy path.

- [ ] **Step 5: Write a schema validator script**

Create a **non-committed** validator script `.plan-notes/validate_briefings_v2.py`:

```python
"""Run: python .plan-notes/validate_briefings_v2.py

Asserts BRIEFINGS_V2 schema correctness. Returns exit 0 on success, 1 on failure.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from launcher import BRIEFINGS_V2

REQUIRED_FIELDS = {"source_files", "main_function", "one_liner",
                   "pseudocode", "params", "formulas", "invariants"}
PARAM_KEYS = {"name", "default", "range", "unit", "effect"}

def main() -> int:
    errors = []
    for name, entry in BRIEFINGS_V2.items():
        if not isinstance(entry, dict):
            errors.append(f"{name}: not a dict")
            continue
        missing = REQUIRED_FIELDS - entry.keys()
        if missing:
            errors.append(f"{name}: missing fields {missing}")
            continue
        if not isinstance(entry["source_files"], list) or not entry["source_files"]:
            errors.append(f"{name}: source_files must be non-empty list")
        if not (isinstance(entry["main_function"], tuple) and len(entry["main_function"]) == 2):
            errors.append(f"{name}: main_function must be (path, name) tuple")
        elif entry["main_function"][0] != entry["source_files"][0]:
            errors.append(f"{name}: main_function[0] must match source_files[0]")
        if not isinstance(entry["one_liner"], str) or not entry["one_liner"]:
            errors.append(f"{name}: one_liner must be non-empty str")
        if not isinstance(entry["pseudocode"], str) or len(entry["pseudocode"].splitlines()) < 2:
            errors.append(f"{name}: pseudocode must be multi-line str")
        if not isinstance(entry["params"], list) or len(entry["params"]) < 3:
            errors.append(f"{name}: params must be list of ≥3")
        else:
            for i, p in enumerate(entry["params"]):
                if set(p.keys()) != PARAM_KEYS:
                    errors.append(f"{name}: params[{i}] keys {set(p.keys())} != {PARAM_KEYS}")
        if not isinstance(entry["formulas"], list) or len(entry["formulas"]) < 2:
            errors.append(f"{name}: formulas must be list of ≥2")
        if not isinstance(entry["invariants"], list) or len(entry["invariants"]) < 3:
            errors.append(f"{name}: invariants must be list of ≥3")

    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print(f"  • {e}")
        return 1
    print(f"OK — {len(BRIEFINGS_V2)} entries valid")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Run the validator**

Run:
```
python .plan-notes/validate_briefings_v2.py
```

Expected output:
```
OK — 1 entries valid
```

Note: the validator accepts placeholder content as long as the SHAPE is correct. It only checks schema, not content quality.

- [ ] **Step 7: Smoke-check that launcher still imports**

Run:
```
python -c "import launcher; print('import OK')"
```

Expected output:
```
import OK
```

No tracebacks.

- [ ] **Step 8: Commit**

```
git add launcher.py
git commit -m "feat(launcher): add ttk import + empty BRIEFINGS_V2 scaffold with placeholder CITADEL"
```

---

### Task 3: Implement `CodeViewer` class

**Files:**
- Modify: `launcher.py` — add new class BEFORE the main `class App` (or wherever the class that owns `_brief` starts). Search for `class ` to find the right spot. The insertion goes AFTER BRIEFINGS_V2 and BEFORE the class containing `_brief`.

**Purpose:** Isolated, self-contained read-only code viewer. Can be instantiated from anywhere that has a parent Tk widget.

- [ ] **Step 1: Locate insertion point**

Search `launcher.py` for the first `class ` after `BRIEFINGS_V2`. The `CodeViewer` class goes immediately before it.

- [ ] **Step 2: Insert the CodeViewer class**

Insert this complete class (no placeholders):

```python

# ═══════════════════════════════════════════════════════════
# CODE VIEWER — read-only syntax-highlighted source panel
# ═══════════════════════════════════════════════════════════
import re as _re_cv

class CodeViewer(tk.Toplevel):
    """Read-only syntax-highlighted viewer for strategy source files.

    Opens as a modal Toplevel with one ttk.Notebook tab per source file.
    The first tab is scrolled near the def of main_function. ESC closes.
    """

    KEYWORDS = frozenset({
        "def", "class", "for", "if", "elif", "else", "return",
        "import", "from", "while", "in", "not", "and", "or",
        "True", "False", "None", "try", "except", "finally",
        "with", "as", "lambda", "yield", "raise", "pass",
        "break", "continue", "global", "nonlocal", "is",
    })

    def __init__(self, parent, source_files: list, main_function: tuple):
        super().__init__(parent)
        self.title(f"source — {main_function[1]}")
        self.geometry("1100x750")
        self.configure(bg=BG)
        self.transient(parent)
        self.grab_set()
        self.bind("<Escape>", lambda e: self.destroy())
        self._build_ui(source_files, main_function)

    def _build_ui(self, files: list, main_fn: tuple):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=4, pady=4)

        main_tab_frame = None
        main_tab_text = None

        for path in files:
            frame = ttk.Frame(nb)
            txt = tk.Text(
                frame, wrap="none",
                font=(FONT, 10),
                bg=BG, fg=WHITE,
                insertbackground=WHITE,
                selectbackground=AMBER_D,
                selectforeground=BG,
                padx=8, pady=8,
                borderwidth=0, highlightthickness=0,
            )
            sb_y = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
            sb_x = ttk.Scrollbar(frame, orient="horizontal", command=txt.xview)
            txt.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)

            full_path = ROOT / path
            try:
                content = full_path.read_text(encoding="utf-8")
            except Exception as e:
                content = f"# error reading {path}: {e}"

            txt.insert("1.0", content)
            self._highlight(txt, content)
            txt.config(state="disabled")

            sb_y.pack(side="right", fill="y")
            sb_x.pack(side="bottom", fill="x")
            txt.pack(side="left", fill="both", expand=True)

            tab_label = Path(path).name
            nb.add(frame, text=tab_label)

            if path == main_fn[0]:
                main_tab_frame = frame
                main_tab_text = txt

        if main_tab_frame is not None:
            nb.select(main_tab_frame)
            self._scroll_to_function(main_tab_text,
                                     full_path.read_text(encoding="utf-8") if main_tab_text else "",
                                     main_fn[1])

    def _highlight(self, text_widget: tk.Text, content: str) -> None:
        """Regex-based highlight. 5 passes. Imperfect — strings with # inside
        may be mis-tagged. Good enough for a viewer, not a compiler."""

        text_widget.tag_configure("kw",      foreground="#569cd6")  # blue
        text_widget.tag_configure("string",  foreground="#6a9955")  # green
        text_widget.tag_configure("comment", foreground=DIM)        # grey
        text_widget.tag_configure("number",  foreground="#d7ba7d")  # orange
        text_widget.tag_configure("defname", foreground="#dcdcaa")  # yellow

        # Pass 1: strings (naive — handles "..." and '...' but not triple)
        for m in _re_cv.finditer(r'"[^"\n]*"|\'[^\'\n]*\'', content):
            self._tag_span(text_widget, m.start(), m.end(), "string")

        # Pass 2: comments (to end of line)
        for m in _re_cv.finditer(r'#.*$', content, flags=_re_cv.MULTILINE):
            self._tag_span(text_widget, m.start(), m.end(), "comment")

        # Pass 3: keywords
        pat = r'\b(' + '|'.join(self.KEYWORDS) + r')\b'
        for m in _re_cv.finditer(pat, content):
            self._tag_span(text_widget, m.start(), m.end(), "kw")

        # Pass 4: numbers
        for m in _re_cv.finditer(r'\b\d+\.?\d*\b', content):
            self._tag_span(text_widget, m.start(), m.end(), "number")

        # Pass 5: def/class names
        for m in _re_cv.finditer(r'\b(?:def|class)\s+(\w+)', content):
            self._tag_span(text_widget, m.start(1), m.end(1), "defname")

    def _tag_span(self, text_widget: tk.Text, start_char: int, end_char: int, tag: str) -> None:
        start_index = f"1.0 + {start_char} chars"
        end_index = f"1.0 + {end_char} chars"
        text_widget.tag_add(tag, start_index, end_index)

    def _scroll_to_function(self, text_widget: tk.Text, content: str, fn_name: str) -> None:
        idx = content.find(f"def {fn_name}")
        if idx < 0:
            return
        line = content.count("\n", 0, idx) + 1
        text_widget.see(f"{max(1, line - 3)}.0")
```

- [ ] **Step 3: Verify launcher imports cleanly**

Run:
```
python -c "import launcher; print('import OK')"
```

Expected output:
```
import OK
```

- [ ] **Step 4: Smoke test CodeViewer in isolation**

Create a temporary script `.plan-notes/smoke_code_viewer.py`:

```python
"""Smoke test: opens CodeViewer on launcher.py itself, no App context."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tkinter as tk
from launcher import CodeViewer

root = tk.Tk()
root.geometry("400x200")
tk.Label(root, text="Click to open CodeViewer").pack(pady=20)
btn = tk.Button(
    root,
    text="Open",
    command=lambda: CodeViewer(
        root,
        source_files=["launcher.py"],
        main_function=("launcher.py", "_brief"),
    ),
)
btn.pack(pady=10)
root.mainloop()
```

Run:
```
python .plan-notes/smoke_code_viewer.py
```

Expected behavior:
- A small Tk window opens with one button.
- Clicking "Open" launches a new Toplevel with a single tab labeled `launcher.py`.
- The Text widget shows the launcher source with Consolas font.
- Keywords (`def`, `class`, `for`, etc.) are blue.
- Strings are green.
- Comments are grey.
- Numbers are orange.
- `def` and `class` names are yellow.
- The viewer is scrolled near `def _brief`.
- ESC closes the viewer; the small window remains.
- Closing the small window (X) ends the script.

If any of the above fails visually, fix before committing. Do not commit the smoke test script.

- [ ] **Step 5: Commit**

```
git add launcher.py
git commit -m "feat(launcher): add CodeViewer class — tk.Toplevel with regex syntax highlight"
```

---

### Task 4: Refactor `_brief()` + add render helpers

**Files:**
- Modify: `launcher.py:753-820` (the existing `_brief` method)
- Add new methods adjacent to `_brief`

**Purpose:** Make `_brief` dispatch to a new technical path when the strategy has a `BRIEFINGS_V2` entry. Preserve the legacy path unchanged for everything else.

- [ ] **Step 1: Read the current `_brief` method**

Read `launcher.py:753-830` (roughly). Confirm the signature `def _brief(self, name, script, desc, parent_menu)` and the button layout at the bottom (`CONFIGURAR & RODAR`, `SELECIONAR MODO & RODAR`, etc.).

- [ ] **Step 2: Replace `_brief` with a dispatching version**

Edit `launcher.py`. Find the exact text of the existing `_brief` method and replace it with:

```python
    # ─── STRATEGY BRIEFING ──────────────────────────────
    def _brief(self, name, script, desc, parent_menu):
        """Show strategy briefing before running.

        Dispatches on BRIEFINGS_V2 presence:
          - If name in BRIEFINGS_V2 → render technical view (pseudocode, params, formulas, invariants, VER CÓDIGO button).
          - Else → legacy narrative view (philosophy, logic, edge, risk).
        """
        self._clr(); self._clear_kb()
        self.h_path.configure(text=f"> {parent_menu.upper()} > {name}")
        self.h_stat.configure(text="BRIEFING", fg=AMBER_D)
        self.f_lbl.configure(text="ENTER executar  |  ESC voltar")

        if name in BRIEFINGS_V2:
            self._render_technical_brief(name, script, desc, parent_menu)
        else:
            self._render_legacy_brief(name, script, desc, parent_menu)
```

- [ ] **Step 3: Extract the OLD body of `_brief` into `_render_legacy_brief`**

Immediately after the new `_brief` method, paste the ENTIRE old body (what was inside the method before the refactor) as a new method `_render_legacy_brief`. The ONLY changes:

1. Method name: `_render_legacy_brief` instead of `_brief`
2. Signature: same `(self, name, script, desc, parent_menu)`
3. Remove the first 4 lines (`self._clr()`, path, stat, f_lbl) — those already ran in the dispatcher

Expected body (preserve exactly — this is the current working code):

```python
    def _render_legacy_brief(self, name, script, desc, parent_menu):
        """Legacy narrative briefing (philosophy/logic/edge/risk)."""
        brief = BRIEFINGS.get(name, {})

        f = tk.Frame(self.main, bg=BG)
        f.pack(fill="both", expand=True, padx=30, pady=16)

        # Header
        hdr = tk.Frame(f, bg=BG)
        hdr.pack(fill="x", pady=(0, 12))
        tk.Label(hdr, text=f" {name} ", font=(FONT, 10, "bold"), fg=BG, bg=AMBER).pack(side="left")
        tk.Label(hdr, text=f"  {desc}", font=(FONT, 9), fg=DIM, bg=BG).pack(side="left", padx=6)

        tk.Frame(f, bg=AMBER_D, height=1).pack(fill="x", pady=(0, 14))

        # Philosophy (italic feel with dimmer color)
        if brief.get("philosophy"):
            tk.Label(f, text='"' + brief["philosophy"] + '"', font=(FONT, 9), fg=AMBER_D,
                     bg=BG, wraplength=700, justify="left", anchor="w").pack(fill="x", pady=(0, 14))

        # Logic steps
        if brief.get("logic"):
            tk.Label(f, text="LÓGICA", font=(FONT, 8, "bold"), fg=AMBER, bg=BG, anchor="w").pack(anchor="w")
            tk.Frame(f, bg=DIM2, height=1).pack(fill="x", pady=(2, 6))
            for i, step in enumerate(brief["logic"]):
                row = tk.Frame(f, bg=BG)
                row.pack(fill="x", pady=1)
                tk.Label(row, text=f"  {i+1}.", font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, width=4, anchor="e").pack(side="left")
                tk.Label(row, text=step, font=(FONT, 8), fg=WHITE, bg=BG, anchor="w").pack(side="left", padx=4)

        # Edge + Risk side by side
        if brief.get("edge") or brief.get("risk"):
            tk.Frame(f, bg=BG, height=10).pack()
            er = tk.Frame(f, bg=BG)
            er.pack(fill="x")
            if brief.get("edge"):
                ef = tk.Frame(er, bg=BG)
                ef.pack(side="left", fill="x", expand=True)
                tk.Label(ef, text="VANTAGEM", font=(FONT, 7, "bold"), fg=GREEN, bg=BG, anchor="w").pack(anchor="w")
                tk.Label(ef, text=brief["edge"], font=(FONT, 8), fg=DIM, bg=BG, anchor="w", wraplength=350).pack(anchor="w")
            if brief.get("risk"):
                rf = tk.Frame(er, bg=BG)
                rf.pack(side="right", fill="x", expand=True)
                tk.Label(rf, text="RISCO", font=(FONT, 7, "bold"), fg=RED, bg=BG, anchor="w").pack(anchor="w")
                tk.Label(rf, text=brief["risk"], font=(FONT, 8), fg=DIM, bg=BG, anchor="w", wraplength=350).pack(anchor="w")

        tk.Frame(f, bg=BG, height=14).pack()

        self._render_action_buttons(f, name, script, desc, parent_menu)
```

**Note:** the original `_brief` had the action-button logic inlined. Extract that logic into a shared helper `_render_action_buttons` in Step 5 and call it from here.

- [ ] **Step 4: Add `_render_technical_brief` method**

After `_render_legacy_brief`, insert:

```python
    def _render_technical_brief(self, name, script, desc, parent_menu):
        """Technical briefing: pseudocode + params + formulas + invariants + VER CÓDIGO.

        Layout order matters for Tk packer:
          1. Header + divider (top, fixed height)
          2. Bottom action bar (side=bottom, packed BEFORE scroll so it reserves space)
          3. Scrollable middle (side=top, expand=True — claims remaining space)
        """
        data = BRIEFINGS_V2[name]

        f = tk.Frame(self.main, bg=BG)
        f.pack(fill="both", expand=True, padx=30, pady=12)

        # ─── Header (top) ───
        hdr = tk.Frame(f, bg=BG)
        hdr.pack(side="top", fill="x", pady=(0, 8))
        tk.Label(hdr, text=f" {name} ", font=(FONT, 11, "bold"), fg=BG, bg=AMBER).pack(side="left")
        tk.Label(hdr, text=f"  {data['one_liner']}", font=(FONT, 9), fg=WHITE, bg=BG, anchor="w").pack(side="left", padx=8)
        tk.Frame(f, bg=AMBER_D, height=1).pack(side="top", fill="x", pady=(0, 10))

        # ─── Bottom action bar (packed BEFORE scroll frame to reserve space) ───
        bottom_bar = tk.Frame(f, bg=BG)
        bottom_bar.pack(side="bottom", fill="x", pady=(8, 0))
        self._render_action_buttons(bottom_bar, name, script, desc, parent_menu, data=data)

        # ─── Scrollable middle (claims remaining vertical space) ───
        scroll_frame = tk.Frame(f, bg=BG)
        scroll_frame.pack(side="top", fill="both", expand=True)

        canvas = tk.Canvas(scroll_frame, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(scroll_frame, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # Mousewheel scroll — bind_all is global, unbind on destroy to avoid leaking
        def _on_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_wheel)
        f.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        self._render_pseudocode(inner, data["pseudocode"])
        self._render_params_table(inner, data["params"])
        self._render_formulas(inner, data["formulas"])
        self._render_invariants(inner, data["invariants"])
```

- [ ] **Step 5: Add `_render_pseudocode` helper**

After `_render_technical_brief`, insert:

```python
    def _render_pseudocode(self, parent, pseudocode_str):
        tk.Label(parent, text="PSEUDOCODE", font=(FONT, 8, "bold"),
                 fg=AMBER, bg=BG, anchor="w").pack(anchor="w", pady=(4, 2))
        tk.Frame(parent, bg=DIM2, height=1).pack(fill="x", pady=(0, 4))

        box = tk.Frame(parent, bg=BG3, padx=10, pady=8)
        box.pack(fill="x", pady=(0, 10))
        tk.Label(box, text=pseudocode_str.rstrip(),
                 font=(FONT, 9), fg=WHITE, bg=BG3,
                 anchor="w", justify="left").pack(anchor="w")
```

- [ ] **Step 6: Add `_render_params_table` helper**

After `_render_pseudocode`, insert:

```python
    def _render_params_table(self, parent, params_list):
        tk.Label(parent, text="PARAMETERS", font=(FONT, 8, "bold"),
                 fg=AMBER, bg=BG, anchor="w").pack(anchor="w", pady=(4, 2))
        tk.Frame(parent, bg=DIM2, height=1).pack(fill="x", pady=(0, 4))

        style = ttk.Style()
        style.theme_use("default")
        style.configure("Brief.Treeview",
                        background=BG3, fieldbackground=BG3, foreground=WHITE,
                        rowheight=22, borderwidth=0, font=(FONT, 9))
        style.configure("Brief.Treeview.Heading",
                        background=BG, foreground=AMBER, borderwidth=0, font=(FONT, 8, "bold"))
        style.map("Brief.Treeview",
                  background=[("selected", AMBER_D)], foreground=[("selected", BG)])

        tv = ttk.Treeview(parent, columns=("name", "default", "range", "unit", "effect"),
                          show="headings", height=min(len(params_list), 8),
                          style="Brief.Treeview")
        tv.heading("name", text="name")
        tv.heading("default", text="default")
        tv.heading("range", text="range")
        tv.heading("unit", text="unit")
        tv.heading("effect", text="effect")
        tv.column("name",    width=160, anchor="w")
        tv.column("default", width=90,  anchor="w")
        tv.column("range",   width=110, anchor="w")
        tv.column("unit",    width=70,  anchor="w")
        tv.column("effect",  width=350, anchor="w")

        for p in params_list:
            tv.insert("", "end", values=(p["name"], p["default"], p["range"], p["unit"], p["effect"]))
        tv.pack(fill="x", pady=(0, 10))
```

- [ ] **Step 7: Add `_render_formulas` helper**

After `_render_params_table`, insert:

```python
    def _render_formulas(self, parent, formulas_list):
        tk.Label(parent, text="FORMULAS", font=(FONT, 8, "bold"),
                 fg=AMBER, bg=BG, anchor="w").pack(anchor="w", pady=(4, 2))
        tk.Frame(parent, bg=DIM2, height=1).pack(fill="x", pady=(0, 4))

        box = tk.Frame(parent, bg=BG3, padx=10, pady=6)
        box.pack(fill="x", pady=(0, 10))
        for formula in formulas_list:
            tk.Label(box, text="  " + formula, font=(FONT, 9),
                     fg=WHITE, bg=BG3, anchor="w", justify="left").pack(anchor="w", pady=1)
```

- [ ] **Step 8: Add `_render_invariants` helper**

After `_render_formulas`, insert:

```python
    def _render_invariants(self, parent, invariants_list):
        tk.Label(parent, text="INVARIANTS", font=(FONT, 8, "bold"),
                 fg=AMBER, bg=BG, anchor="w").pack(anchor="w", pady=(4, 2))
        tk.Frame(parent, bg=DIM2, height=1).pack(fill="x", pady=(0, 4))

        box = tk.Frame(parent, bg=BG, padx=6)
        box.pack(fill="x", pady=(0, 10))
        for inv in invariants_list:
            row = tk.Frame(box, bg=BG)
            row.pack(fill="x", pady=1)
            tk.Label(row, text="  •  ", font=(FONT, 9, "bold"),
                     fg=AMBER_D, bg=BG).pack(side="left")
            tk.Label(row, text=inv, font=(FONT, 8),
                     fg=WHITE, bg=BG, anchor="w", justify="left",
                     wraplength=850).pack(side="left", fill="x", expand=True)
```

- [ ] **Step 9: Add `_render_action_buttons` helper**

After `_render_invariants`, insert:

```python
    def _render_action_buttons(self, parent, name, script, desc, parent_menu, data=None):
        tk.Frame(parent, bg=BG, height=10).pack()

        is_bt = parent_menu == "backtest"
        is_live = parent_menu == "live"
        is_tool = parent_menu == "tools"

        btn_f = tk.Frame(parent, bg=BG)
        btn_f.pack()

        # VER CÓDIGO button — only shown if data (V2 entry) is provided
        if data is not None:
            src_btn = tk.Label(
                btn_f, text="  VER CÓDIGO  ",
                font=(FONT, 10, "bold"), fg=AMBER, bg=BG3,
                padx=10, pady=6, cursor="hand2",
            )
            src_btn.pack(side="left", padx=(0, 12))
            src_btn.bind("<Enter>", lambda e: src_btn.configure(bg=AMBER_D, fg=BG))
            src_btn.bind("<Leave>", lambda e: src_btn.configure(bg=BG3, fg=AMBER))
            src_btn.bind("<Button-1>", lambda e: self._open_code_viewer(data))

        if is_bt:
            next_fn = lambda: self._config_backtest(name, script, desc, parent_menu)
            btn_text = "  CONFIGURAR & RODAR  "
        elif is_live:
            next_fn = lambda: self._config_live(name, script, desc, parent_menu)
            btn_text = "  SELECIONAR MODO & RODAR  "
        else:
            next_fn = lambda: self._exec(name, script, desc, parent_menu, [], [])
            btn_text = "  RODAR  "

        go_btn = tk.Label(
            btn_f, text=btn_text,
            font=(FONT, 10, "bold"), fg=BG, bg=AMBER,
            padx=10, pady=6, cursor="hand2",
        )
        go_btn.pack(side="left")
        go_btn.bind("<Enter>", lambda e: go_btn.configure(bg=AMBER_B))
        go_btn.bind("<Leave>", lambda e: go_btn.configure(bg=AMBER))
        go_btn.bind("<Button-1>", lambda e: next_fn())

        self._kb("<Return>", lambda e=None: next_fn())
        self._kb("<Escape>", lambda e=None: self._menu(parent_menu))

    def _open_code_viewer(self, data):
        CodeViewer(self.root, data["source_files"], data["main_function"])
```

**Important:** the `_kb` and `_menu` calls assume that's how the existing launcher wires keybindings and navigation. Read `launcher.py` to confirm those helper names. If they differ (e.g., `_bind_key` instead of `_kb`), match the existing pattern.

Also, `self.root` is assumed to be the Tk root. If the launcher uses a different attribute (e.g., `self.master`, `self.app`, `self.tk`), substitute. Check during the task by reading the `__init__` of the class that owns `_brief`.

- [ ] **Step 10: Run the schema validator**

```
python .plan-notes/validate_briefings_v2.py
```

Expected:
```
OK — 1 entries valid
```

- [ ] **Step 11: Verify import**

```
python -c "import launcher; print('import OK')"
```

Expected:
```
import OK
```

No tracebacks.

- [ ] **Step 12: Commit**

```
git add launcher.py
git commit -m "feat(launcher): refactor _brief to dispatch V2 technical vs legacy narrative"
```

---

### Task 5: Placeholder smoke test — layout with stub CITADEL

**Files:**
- Read only: `launcher.py`

**Purpose:** Visually verify the new rendering works end-to-end with placeholder data before filling in real content.

- [ ] **Step 1: Run the launcher**

```
cd .worktrees/experiment && python launcher.py
```

Expected: launcher opens normally. Ticker starts populating.

- [ ] **Step 2: Navigate to BACKTEST menu**

Press `s` (or click the BACKTEST menu option). The menu should list CITADEL, JUMP, BRIDGEWATER, DE SHAW, MILLENNIUM, TWO SIGMA.

- [ ] **Step 3: Click CITADEL**

Expected:
- The new technical briefing renders.
- Header: `CITADEL` (amber box) + `Placeholder — will be populated during Phase 2 audit.` (white text).
- PSEUDOCODE section: small box with `# placeholder` text.
- PARAMETERS section: ttk.Treeview with 3 placeholder rows (PLACEHOLDER / PLACEHOLDER_2 / PLACEHOLDER_3).
- FORMULAS section: 2 placeholder lines.
- INVARIANTS section: 3 bullet points.
- Buttons at the bottom: `VER CÓDIGO` (amber on dark) and `CONFIGURAR & RODAR` (dark on amber).

- [ ] **Step 4: Click VER CÓDIGO**

Expected:
- Toplevel opens with one tab: `backtest.py`.
- Content of `engines/backtest.py` is shown.
- Scrolled near `def scan_symbol`.
- Syntax highlight visible (blue keywords, green strings, grey comments).
- ESC closes the viewer.

- [ ] **Step 5: Click CONFIGURAR & RODAR**

Expected: the configuration screen opens normally (the existing flow wasn't broken).

- [ ] **Step 6: Press ESC to go back**

Expected: returns to BACKTEST menu.

- [ ] **Step 7: Click JUMP**

Expected: LEGACY briefing renders (philosophy / logic / edge / risk). Because `JUMP` is not in `BRIEFINGS_V2` yet, the dispatcher falls back to the old path. This verifies backward compat.

- [ ] **Step 8: Close launcher**

Close the window.

- [ ] **Step 9: No commit**

Phase 1 produces no new commit in Task 5. The launcher works with placeholder data; we're ready to do the real audit in Phase 2.

**CHECKPOINT:** Stop and tell the user: "Phase 1 complete. Layout verified with placeholder CITADEL. Ready for real audit — proceed to Phase 2?"

---

## Phase 2 — CITADEL pilot (Tasks 6–8)

This is the first real audit + population. It establishes the format and catches issues before replicating across 6 more strategies. The user should review the CITADEL output before we proceed to Phase 3.

---

### Task 6: Create audit doc skeleton + audit CITADEL

**Files:**
- Create: `docs/audits/backtest-physics-2026-04-10.md`
- Read: `engines/backtest.py`, `core/signals.py`, `core/indicators.py`

**Purpose:** Produce the CITADEL section of the audit document. This is a code-reading task; the deliverable is a markdown document.

- [ ] **Step 1: Create the audit doc skeleton**

Write `docs/audits/backtest-physics-2026-04-10.md`:

```markdown
# Backtest Physics Audit — 2026-04-10

**Scope:** `engines/backtest.py`, `core/signals.py`, `core/indicators.py` (shared core)
plus the 7 strategies: CITADEL, JUMP, BRIDGEWATER, DE SHAW, MILLENNIUM, TWO SIGMA, JANE STREET.

**Checklist:** L1-L12 (defined in `docs/superpowers/specs/2026-04-10-backtest-audit-and-technical-briefing-design.md` §4.1).

**Status legend:** `✓ PASS` | `⚠️ SMELL` | `✗ FAIL` | `n/a`.

---

## Executive summary

| Strategy     | PASS | SMELL | FAIL | n/a | Critical findings |
|--------------|------|-------|------|-----|-------------------|
| CITADEL      | —    | —     | —    | —   | (filled in Phase 2) |
| JUMP         | —    | —     | —    | —   | (filled in Phase 3) |
| BRIDGEWATER  | —    | —     | —    | —   | (filled in Phase 3) |
| DE SHAW      | —    | —     | —    | —   | (filled in Phase 3) |
| MILLENNIUM   | —    | —     | —    | —   | (filled in Phase 3) |
| TWO SIGMA    | —    | —     | —    | —   | (filled in Phase 3) |
| JANE STREET  | —    | —     | —    | —   | (filled in Phase 3) |

---
```

- [ ] **Step 2: Read `engines/backtest.py` completely**

Read the full file. Take notes on:
- Function `scan_symbol`: loop bounds, entry index, exit logic
- Where fees are applied
- Where slippage is applied
- Where funding rate is applied
- Where position sizing happens
- Where liquidation is simulated
- What indicators are called
- What `min_idx` is and why

- [ ] **Step 3: Read `core/signals.py` completely**

Take notes on:
- `calc_levels` — how entry/stop/target are computed for long vs short
- `decide_direction` — what data it reads, any `shift(-k)` calls
- `label_trade` — the entry_idx parameter, how it simulates the trade forward

- [ ] **Step 4: Read `core/indicators.py` completely**

Take notes on:
- Every indicator function
- Any use of `shift()` — positive or negative
- Any `fillna()` calls — what value and whether it biases initial bars
- Whether outputs are causal at index `idx` (use only `[0..idx]`)

- [ ] **Step 5: Apply L1-L12 to CITADEL and append to audit doc**

For each of the 12 checks, write the entry. Use the template from "Shared References" above. Example for L1:

```markdown
## CITADEL

**Source files audited:** `engines/backtest.py`, `core/signals.py`, `core/indicators.py`
**Main function:** `engines/backtest.py::scan_symbol`
**Bars read:** <actual line count>

### L1 — Sem look-ahead: <STATUS>
<finding text with engines/backtest.py:<line> refs>
<if not PASS:>
- **Severidade:** <level>
- **Repro:** <steps>
- **Fix recomendado:** <specific change>

### L2 — Delay de execução: <STATUS>
<…>

<continue through L12>
```

- [ ] **Step 6: Fill in the CITADEL row of the executive summary**

Count PASS / SMELL / FAIL / n/a across L1-L12 for CITADEL and update the table at the top of the audit doc.

- [ ] **Step 7: Commit**

```
git add docs/audits/backtest-physics-2026-04-10.md
git commit -m "audit: CITADEL physics audit (L1-L12) + engine core findings"
```

---

### Task 7: Populate `BRIEFINGS_V2["CITADEL"]` from audit

**Files:**
- Modify: `launcher.py` — replace the CITADEL placeholder entry in `BRIEFINGS_V2`
- Read: `docs/audits/backtest-physics-2026-04-10.md` (just-committed)

**Purpose:** Distill the audit findings into the 7-field schema.

- [ ] **Step 1: Extract the CITADEL entry**

Using the audit findings, build the entry. Use the template from "Shared References". Rules:

- `source_files`: 3 files audited → `["engines/backtest.py", "core/signals.py", "core/indicators.py"]`
- `main_function`: `("engines/backtest.py", "scan_symbol")`
- `one_liner`: one sentence, ≤80 chars, describing what CITADEL actually does (trend-following multi-TF with omega score, chop mode reversal)
- `pseudocode`: distilled loop — entry condition, filters, exit. Pull the actual variable and function names from the read of `scan_symbol`. 8-20 lines.
- `params`: extract the ACTUAL constants used by CITADEL from the source — `MAX_HOLD`, `KELLY_FRAC`, thresholds, etc. For each, find the default value in the source and write a short effect description. Minimum 3, maximum 10. If you can only find 3 that are strategy-specific, that's fine.
- `formulas`: extract from the indicator definitions in `core/indicators.py`. Use Unicode notation. Minimum 2 formulas. Include at least: the omega composition if present, RSI, ATR, Kelly sizing. 2-8 formulas.
- `invariants`: extract from audit. Include at least: minimum warmup bars, execution-at-idx+1 rule, portfolio correlation gate if present, timeframe assumptions. Minimum 3.

- [ ] **Step 2: Replace the placeholder in `launcher.py`**

Find the CITADEL entry in `BRIEFINGS_V2` (currently placeholder) and replace it with the real entry from Step 1. Keep it valid Python — escape quotes in strings properly, use `"""\` for multi-line strings.

- [ ] **Step 3: Run the schema validator**

```
python .plan-notes/validate_briefings_v2.py
```

Expected:
```
OK — 1 entries valid
```

If the validator reports errors, fix the entry until the schema is correct.

- [ ] **Step 4: Verify import**

```
python -c "import launcher; print('import OK')"
```

- [ ] **Step 5: Commit**

```
git add launcher.py
git commit -m "feat(launcher): populate BRIEFINGS_V2[CITADEL] from audit"
```

---

### Task 8: Smoke test CITADEL + checkpoint

**Files:** none modified (manual test)

- [ ] **Step 1: Run the launcher and click CITADEL**

```
cd .worktrees/experiment && python launcher.py
```

Navigate to BACKTEST → CITADEL.

- [ ] **Step 2: Visual validation**

Verify:
- one_liner reads natural, describes the strategy factually
- PSEUDOCODE shows real function calls and parameter names from `scan_symbol`
- PARAMETERS table has real values (not placeholders), fits in the window
- FORMULAS render with Unicode correctly (·, ², Σ, etc.)
- INVARIANTS read as real constraints from the code

- [ ] **Step 3: VER CÓDIGO test**

Click VER CÓDIGO. Verify:
- 3 tabs: `backtest.py`, `signals.py`, `indicators.py`
- First tab = `backtest.py`, scrolled to `def scan_symbol`
- Highlight works on all 3 files
- ESC closes

- [ ] **Step 4: CONFIGURAR & RODAR still works**

Click CONFIGURAR & RODAR. Verify the config screen opens normally. ESC back.

- [ ] **Step 5: CHECKPOINT — tell the user**

Stop and report to the user:

> "Phase 2 complete. CITADEL audited (L1-L12 in `docs/audits/backtest-physics-2026-04-10.md`) and populated in `BRIEFINGS_V2`. Launcher renders the real technical briefing. Please review the CITADEL section of the audit doc and the rendered briefing before I proceed to the other 6 strategies (Phase 3).
>
> If you want to adjust the format, profundity, or layout — tell me now. Otherwise, Phase 3 replicates this exact process for JUMP, BRIDGEWATER, DE SHAW, MILLENNIUM, TWO SIGMA, JANE STREET."

**Wait for user approval before proceeding to Phase 3.**

---

## Phase 3 — Remaining strategies (Tasks 9–14)

Each task in Phase 3 is the same shape as Tasks 6+7 combined, applied to a different strategy. The tasks are independent and can be parallelized using `superpowers:subagent-driven-development` — each subagent takes one task, reads the files, writes the audit section, populates the `BRIEFINGS_V2` entry, commits.

After Phase 2 is approved, assign one task per strategy.

---

### Task 9: Audit + populate JUMP

**Files:**
- Modify: `docs/audits/backtest-physics-2026-04-10.md` (append JUMP section)
- Modify: `launcher.py` (add JUMP entry to `BRIEFINGS_V2`)
- Read: `engines/mercurio.py` (contains `scan_mercurio`)

- [ ] **Step 1: Read `engines/mercurio.py` completely**

Take notes on: main scan function, indicators used (CVD, volume imbalance, liquidation proxy), parameters, entry/exit logic, fee/slippage handling.

- [ ] **Step 2: Apply L1-L12 to JUMP**

Write the JUMP section in `docs/audits/backtest-physics-2026-04-10.md` using the template from "Shared References". Each check gets PASS / SMELL / FAIL / n/a + (if not PASS) severity/repro/fix.

- [ ] **Step 3: Update executive summary**

Fill in the JUMP row in the table at the top of the audit doc.

- [ ] **Step 4: Build the `BRIEFINGS_V2["JUMP"]` entry**

Schema from "Shared References". Fields:

- `source_files`: `["engines/mercurio.py"]` (plus any core module that mercurio reads — check with grep)
- `main_function`: `("engines/mercurio.py", "scan_mercurio")`
- `one_liner`: factual description of order-flow logic
- `pseudocode`: distilled decision loop, 8-20 lines
- `params`: real constants from mercurio (CVD windows, imbalance thresholds), 3-10 entries with 5 keys each
- `formulas`: 2-8, include CVD definition, imbalance ratio formula
- `invariants`: 3-8 pre-conditions (requires liquid pairs, minimum volume, etc.)

- [ ] **Step 5: Insert the entry into `BRIEFINGS_V2`**

Add after the CITADEL entry in `launcher.py`.

- [ ] **Step 6: Run validator**

```
python .plan-notes/validate_briefings_v2.py
```

Expected: `OK — 2 entries valid`

- [ ] **Step 7: Verify import**

```
python -c "import launcher; print('import OK')"
```

- [ ] **Step 8: Smoke test**

```
cd .worktrees/experiment && python launcher.py
```

Navigate to BACKTEST → JUMP. Verify: technical briefing renders, real data, VER CÓDIGO opens mercurio.py scrolled to scan_mercurio, highlight works.

- [ ] **Step 9: Commit**

```
git add docs/audits/backtest-physics-2026-04-10.md launcher.py
git commit -m "audit+feat: JUMP physics audit + BRIEFINGS_V2 entry"
```

---

### Task 10: Audit + populate BRIDGEWATER

**Files:**
- Modify: `docs/audits/backtest-physics-2026-04-10.md` (append BRIDGEWATER section)
- Modify: `launcher.py` (add BRIDGEWATER entry to `BRIEFINGS_V2`)
- Read: `engines/thoth.py` (contains `scan_thoth`)

- [ ] **Step 1: Read `engines/thoth.py` completely**

Take notes on: main scan function, macro sentiment inputs (funding rate z-score, OI delta, long/short ratio), parameters, entry/exit logic, how external data (funding, OI) is fetched/cached.

- [ ] **Step 2: Apply L1-L12 to BRIDGEWATER**

Note: L5 (funding applied to held trades) and the use of funding AS A SIGNAL (BRIDGEWATER uses it as a feature, not just a cost) are distinct — audit both aspects. If funding is only used as a signal and not as a cost deduction, flag under L5.

Write the BRIDGEWATER section in the audit doc.

- [ ] **Step 3: Update executive summary**

- [ ] **Step 4: Build `BRIEFINGS_V2["BRIDGEWATER"]`**

- `source_files`: `["engines/thoth.py"]` (+ any shared modules)
- `main_function`: `("engines/thoth.py", "scan_thoth")`
- `one_liner`: macro sentiment reversal via funding/OI/LS extremes
- `pseudocode`: show funding z-score calculation and contrarian entry
- `params`: thresholds for z-score, OI delta cutoff, LS ratio cutoff, weight composition
- `formulas`: z-score formula, composition formula (`0.4·funding_z + 0.3·oi_delta + 0.3·ls_ratio`)
- `invariants`: requires funding rate data, requires OI history, requires LS ratio feed

- [ ] **Step 5: Insert, validate, import check, smoke test**

Same as Task 9 steps 5-8.

- [ ] **Step 6: Commit**

```
git add docs/audits/backtest-physics-2026-04-10.md launcher.py
git commit -m "audit+feat: BRIDGEWATER physics audit + BRIEFINGS_V2 entry"
```

---

### Task 11: Audit + populate DE SHAW

**Files:**
- Modify: `docs/audits/backtest-physics-2026-04-10.md`
- Modify: `launcher.py`
- Read: `engines/newton.py` (contains `scan_newton`)

- [ ] **Step 1: Read `engines/newton.py` completely**

Take notes on: Engle-Granger cointegration test, z-score of spread, half-life estimation, entry/exit thresholds, pair selection.

- [ ] **Step 2: Apply L1-L12 to DE SHAW**

Note: as a market-neutral pairs strategy, some checks change meaning. L5 (funding): must be applied to BOTH legs. L6 (position sizing): notional is doubled (two legs). L12 (survivorship): pair selection methodology matters.

- [ ] **Step 3: Update executive summary**

- [ ] **Step 4: Build `BRIEFINGS_V2["DE SHAW"]`**

Note: key is `"DE SHAW"` with a space (matches MENUS).

- `source_files`: `["engines/newton.py"]`
- `main_function`: `("engines/newton.py", "scan_newton")`
- `one_liner`: pairs cointegration with mean-reversion on z-score spread
- `pseudocode`: cointegration test, spread z-score, entry at |z| > 2, exit at z = 0, stop at |z| > 3.5
- `params`: z entry threshold, z exit, z stop, half-life window, cointegration p-value cutoff, rolling OLS window
- `formulas`: spread = p1 − β·p2, z = (spread − μ) / σ, half-life = −ln(2) / λ
- `invariants`: requires pairs cointegrated; both legs same TF; funding applied per leg; cointegration re-tested periodically

- [ ] **Step 5: Insert, validate, import check, smoke test**

- [ ] **Step 6: Commit**

```
git add docs/audits/backtest-physics-2026-04-10.md launcher.py
git commit -m "audit+feat: DE SHAW physics audit + BRIEFINGS_V2 entry"
```

---

### Task 12: Audit + populate MILLENNIUM

**Files:**
- Modify: `docs/audits/backtest-physics-2026-04-10.md`
- Modify: `launcher.py`
- Read: `engines/multistrategy.py` (contains `scan_ensemble`)

- [ ] **Step 1: Read `engines/multistrategy.py` completely**

Take notes on: how it invokes the other engines, how signals are aggregated (trade-level or signal-level), how weights are computed (Sortino per regime?), kill-switch logic.

- [ ] **Step 2: Apply L1-L12 to MILLENNIUM**

Special considerations:
- L1 (look-ahead): if weights depend on Sortino of past N trades, is N correctly anchored at `idx` and not `idx+k`?
- L6 (capital cap): critical here — multiple engines opening trades simultaneously could blow past cap
- L12 (survivorship): if kill-switched engines are silently removed from stats, that's survivorship

- [ ] **Step 3: Update executive summary**

- [ ] **Step 4: Build `BRIEFINGS_V2["MILLENNIUM"]`**

- `source_files`: `["engines/multistrategy.py"]` + list the engines it orchestrates (`engines/backtest.py`, `engines/mercurio.py`, etc.) — up to 4 entries total so the tab count stays manageable
- `main_function`: `("engines/multistrategy.py", "scan_ensemble")`
- `one_liner`: ensemble orchestrator with Sortino-weighted allocation across engines
- `pseudocode`: show the ensemble loop — invoke each engine, aggregate, weight by Sortino, filter by kill-switch
- `params`: Sortino window, kill-switch threshold, rebalance frequency, correlation cap
- `formulas`: Sortino = (R − R_f) / σ_down, weight_i = Sortino_i / Σ Sortino_j
- `invariants`: requires all child engines to be runnable on same data; capital is shared; kill-switch pauses but doesn't delete

- [ ] **Step 5: Insert, validate, import check, smoke test**

- [ ] **Step 6: Commit**

```
git add docs/audits/backtest-physics-2026-04-10.md launcher.py
git commit -m "audit+feat: MILLENNIUM physics audit + BRIEFINGS_V2 entry"
```

---

### Task 13: Audit + populate TWO SIGMA

**Files:**
- Modify: `docs/audits/backtest-physics-2026-04-10.md`
- Modify: `launcher.py`
- Read: `engines/prometeu.py` (contains `run_training` and inference)

- [ ] **Step 1: Read `engines/prometeu.py` completely**

Take notes on: LightGBM model, feature engineering (regime, volatility, Hurst, etc.), target construction (best engine over next N trades), training window, inference loop.

- [ ] **Step 2: Apply L1-L12 to TWO SIGMA**

CRITICAL AUDIT FOCUS for TWO SIGMA:
- **L1 (look-ahead) is the #1 concern for ML strategies.** Check: is the target (`best_engine_next_N`) computed with future data and then used in training on past? That's expected — it's supervised learning. But at inference time, does the model use features that reference `idx+k`? That would be fatal.
- Check: train/test split — is there any time leak? Walk-forward should be strictly causal.
- Check: feature engineering — every feature at `idx` must use only data from `[0..idx]`.

- [ ] **Step 3: Update executive summary**

- [ ] **Step 4: Build `BRIEFINGS_V2["TWO SIGMA"]`**

- `source_files`: `["engines/prometeu.py"]`
- `main_function`: `("engines/prometeu.py", "run_training")` or `"predict"` — pick the inference entry point (what runs during a backtest bar), not the training job. If training and inference are in different functions, prefer inference for the main scroll target.
- `one_liner`: LightGBM meta-ensemble selecting best engine per regime
- `pseudocode`: feature construction → model.predict → select engine → delegate
- `params`: training window size, feature list count, LightGBM hyperparams (num_leaves, learning_rate), walk-forward step
- `formulas`: loss = multilogloss or similar; feature importance; walk-forward split formula
- `invariants`: requires labeled history; train/test split strictly causal; features at idx use only [0..idx]; model retrained every K bars

- [ ] **Step 5: Insert, validate, import check, smoke test**

Extra smoke test: VER CÓDIGO should open `prometeu.py` and scroll to the chosen main_function. Confirm the highlight works on this file too (may contain more complex strings/comments).

- [ ] **Step 6: Commit**

```
git add docs/audits/backtest-physics-2026-04-10.md launcher.py
git commit -m "audit+feat: TWO SIGMA physics audit + BRIEFINGS_V2 entry"
```

---

### Task 14: Audit + populate JANE STREET

**Files:**
- Modify: `docs/audits/backtest-physics-2026-04-10.md`
- Modify: `launcher.py`
- Read: `engines/arbitrage.py` (contains `scan_arbitrage`)

**Special notes:** JANE STREET is in the `live` menu (not `backtest`). This task handles that — the technical briefing should still render for it because `_brief` dispatches by name, not by menu. No menu restructuring.

- [ ] **Step 1: Read `engines/arbitrage.py` completely**

Take notes on: cross-venue arb (Binance/Bybit/OKX/Gate), funding/basis spread detection, delta-neutral leg management, exchange API rate limits, latency assumptions.

- [ ] **Step 2: Apply L1-L12 to JANE STREET**

Special considerations:
- L1 (look-ahead): arbitrage across venues — is there clock skew or look-ahead via aggregated cross-venue price?
- L5 (funding): arbitrage often EARNS funding (short perp, long spot) — must be accounted with correct sign
- L6 (capital): doubled (one leg per venue)
- L10 (timeframe alignment): multi-venue data must be aligned to the same timestamp — huge look-ahead risk if not
- L12: survivorship of venues — what if one exchange was offline historically?

- [ ] **Step 3: Update executive summary**

- [ ] **Step 4: Build `BRIEFINGS_V2["JANE STREET"]`**

Note: key is `"JANE STREET"` with a space (matches MENUS `live` entry).

- `source_files`: `["engines/arbitrage.py"]`
- `main_function`: `("engines/arbitrage.py", "scan_arbitrage")`
- `one_liner`: cross-venue funding/basis arbitrage, delta-neutral across Binance/Bybit/OKX/Gate
- `pseudocode`: fetch basis per venue → find widest pair → open both legs → hold until basis narrows or funding flips
- `params`: minimum basis spread to enter, max hold, venue list, latency budget
- `formulas`: basis = perp − spot, funding_pnl = Σ funding_k · notional, hedge ratio = 1 (perfect delta-neutral) or rolling beta
- `invariants`: requires connectivity to all venues simultaneously; requires spot AND perp on each venue; funding earned when short perp; capital doubled per trade

- [ ] **Step 5: Smoke test — navigate to LIVE menu, click JANE STREET**

Expected: technical briefing renders (not legacy), VER CÓDIGO opens `arbitrage.py` scrolled to `scan_arbitrage`. The existing `SELECIONAR MODO & RODAR` button should still work (it's the live path).

- [ ] **Step 6: Commit**

```
git add docs/audits/backtest-physics-2026-04-10.md launcher.py
git commit -m "audit+feat: JANE STREET physics audit + BRIEFINGS_V2 entry"
```

---

## Phase 4 — Finalization (Tasks 15–17)

---

### Task 15: Generate `backlog.md` from audit findings

**Files:**
- Create: `docs/audits/backtest-fixes-backlog.md`
- Read: `docs/audits/backtest-physics-2026-04-10.md` (completed)

- [ ] **Step 1: Read the full audit doc**

Read `docs/audits/backtest-physics-2026-04-10.md` end-to-end. Extract every check that is NOT `✓ PASS` and NOT `n/a`.

- [ ] **Step 2: Organize by severity**

Group the findings by severity level: CRÍTICO → ALTO → MÉDIO → BAIXO → INFO.

- [ ] **Step 3: Write the backlog document**

Create `docs/audits/backtest-fixes-backlog.md`:

```markdown
# Backtest Fixes Backlog — generated 2026-04-10

Generated from `docs/audits/backtest-physics-2026-04-10.md`. Only items with status
`⚠️ SMELL` or `✗ FAIL`. Ordered by severity: CRÍTICO → ALTO → MÉDIO → BAIXO → INFO.

This is the input for the next implementation plan (fixes). **Do not fix these items in
the current plan** — the current plan only documents them.

## CRÍTICO
<list critical findings, one per strategy/check, with file:line refs and the fix recommended>

## ALTO
<…>

## MÉDIO
<…>

## BAIXO
<…>

## INFO
<…>

## Totals
- CRÍTICO: N
- ALTO: N
- MÉDIO: N
- BAIXO: N
- INFO: N
- Total non-PASS: N
```

Each item has:

```markdown
- **<STRATEGY> / L<#>** — <one-line description>
  - File: `<path>:<line>`
  - Fix: <specific change recommended from the audit>
```

- [ ] **Step 4: Verify consistency with audit doc**

Cross-check: every SMELL/FAIL in the audit doc appears in the backlog. Every backlog item has a matching audit entry.

- [ ] **Step 5: Commit**

```
git add docs/audits/backtest-fixes-backlog.md
git commit -m "audit: generate backtest-fixes-backlog from physics audit findings"
```

---

### Task 16: Full smoke test across all 7 strategies

**Files:** none (manual test)

- [ ] **Step 1: Run launcher**

```
cd .worktrees/experiment && python launcher.py
```

- [ ] **Step 2: For each of the 7 strategies, run the full smoke test from "Shared References"**

Strategies to test: CITADEL, JUMP, BRIDGEWATER, DE SHAW, MILLENNIUM, TWO SIGMA (all in BACKTEST menu), JANE STREET (in LIVE menu).

For each strategy, execute all 9 steps of the smoke test script from the Shared References section.

- [ ] **Step 3: Record any failures in a checklist**

If any strategy fails any step, note it. Fix the issue (typically a missing field, malformed pseudocode, or mis-matched source_files path) and re-test.

- [ ] **Step 4: Also test a legacy entry**

Navigate to LIVE → PAPER (which is in the legacy BRIEFINGS). Verify the OLD narrative layout renders — this confirms we didn't break backward compat.

- [ ] **Step 5: Final validator run**

```
python .plan-notes/validate_briefings_v2.py
```

Expected: `OK — 7 entries valid`

- [ ] **Step 6: Final import check**

```
python -c "import launcher; print('import OK')"
```

- [ ] **Step 7: No commit if no fixes needed**

If any fixes were needed, commit them with:
```
git commit -am "fix(launcher): smoke-test corrections to BRIEFINGS_V2 / rendering"
```

---

### Task 17: Final wrap-up + PR/merge decision

**Files:** none modified

- [ ] **Step 1: Clean up plan notes**

Delete the `.plan-notes/` directory (non-committed):

```
rm -rf .plan-notes
```

- [ ] **Step 2: Summary for the user**

Tell the user:

> "Implementation complete on branch `feature/experiment` (in `.worktrees/experiment`). Artifacts:
>
> - `docs/audits/backtest-physics-2026-04-10.md` — full audit, 7 strategies × 12 checks.
> - `docs/audits/backtest-fixes-backlog.md` — ordered list of fixes to do next.
> - `launcher.py` — `BRIEFINGS_V2` (7 entries), new `CodeViewer` class, refactored `_brief` dispatching V2 vs legacy, 6 render helpers.
>
> Smoke tested: all 7 strategies render the new technical briefing, VER CÓDIGO opens the correct source file scrolled to the correct function, legacy PAPER/DEMO/TESTNET/LIVE still render the narrative briefing via the legacy path.
>
> Next options:
> 1. **Merge to main** — `git checkout main && git merge feature/experiment`
> 2. **Review first** — open each file, read the changes, then decide
> 3. **Open a PR** — if you want a formal review step
> 4. **Proceed to the fixes plan** — use the backlog as input for a new spec/plan that actually applies the bug fixes
>
> Which do you want to do?"

- [ ] **Step 3: Invoke `superpowers:finishing-a-development-branch`**

Hand off to the branch-finishing skill to guide the merge/PR decision.

---

## Dependency graph

```
Task 1 (grep) → Task 2 (scaffold) → Task 3 (CodeViewer) → Task 4 (refactor) → Task 5 (smoke)
                                                                                    │
                                                                                    ▼
                                                                       Task 6 (CITADEL audit)
                                                                                    │
                                                                                    ▼
                                                                       Task 7 (CITADEL populate)
                                                                                    │
                                                                                    ▼
                                                                       Task 8 (CITADEL smoke + CHECKPOINT)
                                                                                    │
                                        ┌─────────┬───────────┬────────┴───────┬────────┬────────┐
                                        ▼         ▼           ▼                ▼        ▼        ▼
                                    Task 9    Task 10    Task 11         Task 12  Task 13  Task 14
                                    (JUMP)  (BRIDGEW)  (DE SHAW)       (MILLEN)  (2 SIG)  (JANE)
                                        └─────────┴───────────┴────────┬───────┴────────┴────────┘
                                                                       ▼
                                                           Task 15 (backlog)
                                                                       │
                                                                       ▼
                                                           Task 16 (full smoke)
                                                                       │
                                                                       ▼
                                                           Task 17 (wrap-up)
```

Phase 3 (Tasks 9-14) is parallelizable. All other tasks are sequential.

---

## Appendix A — Fallback strategies if things break

**If `ttk.Treeview` looks bad at 5 columns:** replace the `_render_params_table` helper with a plaintext table rendered in a `tk.Text` widget (`state="disabled"`). Keep same 5 columns, use `str.ljust` for alignment, monospace font.

**If Unicode in formulas doesn't render:** fall back to ASCII:
- `·` → `*`
- `²` → `^2`
- `√` → `sqrt`
- `Σ` → `sum`
- `α`, `β` → `alpha`, `beta`

Update the `formulas` entries in `BRIEFINGS_V2` to use the ASCII variant.

**If `CodeViewer` highlight is unreadable on some files (regex mis-match):** disable highlight temporarily by commenting out the call to `self._highlight(txt, content)` in `_build_ui`. Plain text is acceptable as a viewer; highlight is nice-to-have.

**If the scroll canvas in `_render_technical_brief` misbehaves:** fall back to packing all render blocks directly in `f` without the canvas wrapper. The window will be fixed-size — if content overflows, it clips. Acceptable trade-off — the window is big (~900px tall by default).

**If a strategy's source file has no clear "main function":** use the module's primary scan/run function, or whatever the entry point is called. If there's no function at all (module-level code), set `main_function` to `("path.py", "<module>")` and skip the `_scroll_to_function` call (it'll return early since `def <module>` won't be found).

---

## Appendix B — Coverage check against spec

Every spec requirement maps to at least one plan task:

| Spec section | Requirement | Task(s) |
|---|---|---|
| §2 Scope (included) | Audit checklist L1-L12 per strategy | Tasks 6, 9, 10, 11, 12, 13, 14 |
| §2 Scope (included) | Refactor `_brief` with 4 technical blocks | Task 4 |
| §2 Scope (included) | New `BRIEFINGS_V2` dict, 7 entries | Tasks 2, 7, 9-14 |
| §2 Scope (included) | New `CodeViewer` class | Task 3 |
| §2 Scope (included) | Backlog of bugs | Task 15 |
| §2 Scope (excluded) | No fixes applied | Enforced throughout — plan never modifies `engines/` or `core/` |
| §3.2 Schema | 7 fields per entry | Task 2 (scaffold) + Task 7, 9-14 (real data); validated by `.plan-notes/validate_briefings_v2.py` |
| §3.2 CodeViewer constraints | Read-only, modal, Toplevel, 5-category highlight, ESC closes | Task 3 |
| §4 Audit format | Sectioned markdown with L1-L12 per strategy + exec summary | Tasks 6, 9-14, 15 |
| §5.1 Audit acceptance | No TODO, consistent backlog, exec summary filled | Task 15 + Task 16 verification |
| §5.2 Menu acceptance | All 7 entries, 4 blocks, VER CÓDIGO functional, tabs work | Tasks 2, 4, 16 |
| §5.3 Manual smoke test | 11-step × 7 strategies | Task 16 (uses Shared References script) |
| §5.4 Regression gate | `python -c "import launcher"` passes every commit | Every task has an import check |
| §6 Risks | Mitigations for Tk behaviors, Unicode, highlight | Appendix A of this plan |
| §8 Transition | Ordered tasks — scaffold → CodeViewer → refactor → CITADEL pilot → others → backlog → smoke | Tasks 1-17 |

No gaps found. The plan covers every spec requirement.
