# Resume Note — 2026-04-10

This session (with Claude Code) produced a spec and a plan for a much larger piece of
work than we ended up executing. Most of the plan is still unexecuted and waiting for a
future session. This note explains **exactly where we stopped, why, and how to pick up**.

---

## What the session set out to do

Two coupled pieces of work, described by the user in a single request:

1. **Audit** the "physical correctness" of the backtest engine and the 7 strategies.
2. **Refactor** the strategy briefing menu in `launcher.py` to show a technical view
   (pseudocode, parameter table, formulas, invariants) with a "VER CÓDIGO" button that
   opens the actual running source of each strategy.

We went through the full process: brainstorming → spec → plan → subagent-driven
execution.

---

## What was actually committed to `main`

Four deliverables, each as a standalone commit. None of them modify running code —
they are all new files.

| Commit    | Path                                                                      | What it is |
|-----------|---------------------------------------------------------------------------|---|
| `2a3891d` | `.gitignore`                                                              | Added `.worktrees/` so `.worktrees/experiment` doesn't pollute git status |
| `dbcaa54` | `docs/superpowers/specs/2026-04-10-backtest-audit-and-technical-briefing-design.md` | **Design spec.** 476 lines. Full design for audit + menu refactor. |
| `bdf68fc` | `docs/superpowers/plans/2026-04-10-backtest-audit-and-technical-briefing.md`       | **Implementation plan.** 1741 lines, 17 tasks in 4 phases. |
| *(this session)* | `docs/audits/backtest-physics-core-2026-04-10.md`                       | **Mini audit of the core engine only.** Not full plan scope. See below. |
| *(this session)* | `docs/audits/backtest-fixes-backlog.md`                                 | Short backlog — 2 MÉDIO items — generated from the mini audit. |
| *(this session)* | `code_viewer.py` (repo root)                                            | **Standalone `CodeViewer` Tk class.** New file. Not yet wired into `launcher.py`. |
| *(this session)* | `docs/superpowers/plans/RESUME-NOTE-2026-04-10.md`                      | This note. |

---

## Why we stopped mid-plan: `launcher.py` WIP conflict

When the subagent started executing Task 1 of the plan, I discovered that
`launcher.py` in the **main working tree** has **+1464 uncommitted lines** compared to
the committed version in the `.worktrees/experiment` branch (where the plan was
supposed to execute).

- Working tree: 5593 lines
- HEAD (also what `.worktrees/experiment` sees): 4129 lines

I wrote the plan by reading the main working tree (5593-line version), but the plan
was supposed to execute in the worktree (4129-line version). The line numbers and
structural references in the plan are calibrated to the working-tree version; the
worktree has an older `launcher.py` that is missing significant WIP work (including
`MAIN_MENU` with items like MARKETS / CONNECTIONS / TERMINAL / STRATEGIES / RISK /
COMMAND CENTER / SETTINGS, `COMMAND_ROADMAPS` with DEPLOY / SERVERS / DATABASES /
SERVICES, and a `from core.connections import ConnectionManager, MARKETS` import).

Running the plan in the worktree would produce a refactor that conflicts massively
with the working-tree WIP when merged back. Running it on `main` directly would mix
Claude's refactor with João's in-progress edits, which is worse.

**So we stopped.** Rather than sit idle, we did the maximum amount of work that did
NOT touch `launcher.py`:

1. Ran a focused **mini audit** of the shared core engine (the 3 files every strategy
   inherits from — `engines/backtest.py`, `core/signals.py`, `core/indicators.py`,
   plus `core/portfolio.py` and `core/htf.py` as needed).
2. Extracted findings into a fixes backlog.
3. Implemented `CodeViewer` as a **standalone new file** (`code_viewer.py` at repo
   root) — zero conflict risk because it's a new file, not a modification. When
   `launcher.py` stabilizes, wiring it in is a 1-line `from code_viewer import
   CodeViewer` plus instantiation at the click handler.

---

## Mini audit — headline results

Full text: `docs/audits/backtest-physics-core-2026-04-10.md` (9 PASS / 2 SMELL / 0 FAIL / 1 n/a).

**No critical bugs.** The core is causally sound:

- No look-ahead: decision features at `idx` are read strictly from `[idx]` arrays
  (`engines/backtest.py:139-154`). Entry price is `open[idx+1]` (`core/signals.py:154, 179`).
  Trade simulation runs forward from `entry_idx = idx + 1` (`engines/backtest.py:261-265`).
- Fees applied on both legs (`engines/backtest.py:282-290`).
- Slippage applied on entry AND exit (`core/signals.py:155-165`, `engines/backtest.py:279-288`).
- Funding rate contabilized with correct sign (long pays when funding > 0)
  (`engines/backtest.py:280-289`).
- Indicators all causal (`core/indicators.py` read end-to-end, no `shift(-k)` anywhere).
- Stop/target geometry asserted (`core/signals.py:171-172, 196-197`).
- Warm-up defended by `min_idx = max(200, W_NORM, PIVOT_N*3) + 5` (`engines/backtest.py:103`).
- MTF alignment uses `merge_asof(direction="backward")` with HTF timestamp shifted to
  candle close — no `ffill` look-ahead (`core/htf.py:58-80`).

**Two SMELLs** (both MÉDIO, both in the backlog):

1. **L6 — No aggregate notional cap.** `portfolio_allows` caps the **count** of open
   positions and correlation, but never sums `open_notional` and compares against
   `account × LEVERAGE`. Multiple concurrent trades can combine to exceed the intended
   leverage ceiling. Inert at current conservative parameters; material if user pushes
   Kelly + high Omega thresholds simultaneously. Fix: add
   `sum(size[i] * entry[i]) ≤ account * LEVERAGE` gate.

2. **L7 — Liquidation is a post-hoc clamp, not path-dependent.** At `engines/backtest.py:292-295`,
   if the computed loss exceeds 90% of account equity, it's clamped to 95%. This does
   not catch trades whose adverse excursion briefly breached liquidation mid-hold but
   then recovered. Inert for leverage 1-3x; unreliable above ~5x. Fix: move liquidation
   check inside `label_trade`, comparing bar `low/high` to a proper liquidation price.

Full rationale, line numbers, and recommended fixes are in the audit doc and the backlog.

---

## `code_viewer.py` — what it is and how to use it

Standalone, self-contained module at the repo root. Demonstrated to work:

```bash
python code_viewer.py   # opens a small demo window; click to view itself
```

**How to wire it into `launcher.py` later** (in the refactor session):

```python
from code_viewer import CodeViewer   # at top of launcher.py

# Inside your strategy briefing click handler, after the briefing is displayed:
def _open_code(self, data):
    CodeViewer(
        self.root,                        # or whatever attribute is your Tk root
        source_files=data["source_files"],
        main_function=data["main_function"],
    )
```

`source_files` is a list of paths (absolute or relative to cwd). `main_function` is a
`(file_path, function_name)` tuple — the viewer auto-scrolls that tab to the first
`def <function_name>` line.

Syntax highlight: 5 categories (keyword / string / comment / number / def-name),
regex-based, VSCode-ish dark theme. Uses the Bloomberg palette (`BG`, `AMBER`,
`WHITE`, `DIM`) inlined at the top of the file, matching `launcher.py`'s aesthetic.

Read-only (`state="disabled"`). Modal (`transient` + `grab_set`). ESC closes. Import
tested (`python -c "import code_viewer"` passes). Regex tested (all 5 passes verified
against a small Python fixture in session).

---

## How to pick up this work in a future session

### Option A — Resume the full plan

Recommended if the `launcher.py` WIP is either committed or abandoned.

1. Make sure `launcher.py` is in a stable state (either commit the WIP or roll it back).
2. Remove the stale `.worktrees/experiment` worktree:
   ```bash
   git worktree remove .worktrees/experiment
   git branch -D feature/experiment   # optional
   ```
3. Create a fresh worktree from the current `main`:
   ```bash
   git worktree add .worktrees/backtest-briefing -b feature/backtest-briefing
   ```
4. Open Claude Code and say:
   > "Continue the backtest-audit-and-technical-briefing work. Re-read the spec at
   > `docs/superpowers/specs/2026-04-10-backtest-audit-and-technical-briefing-design.md`
   > and the plan at `docs/superpowers/plans/2026-04-10-backtest-audit-and-technical-briefing.md`.
   > Note: `launcher.py` line numbers in the plan are stale — re-read the file first.
   > Also: the mini audit of the core is already done (see
   > `docs/audits/backtest-physics-core-2026-04-10.md`), so Task 6 of the plan is
   > partially pre-filled. Skip to Task 2 (Phase 1 — `BRIEFINGS_V2` scaffold and
   > `CodeViewer` integration). `code_viewer.py` already exists at repo root — import
   > it instead of inlining the class into `launcher.py`."
5. Execute Phase 1 (Tasks 2-5) first, then Phase 2 (CITADEL audit + populate), then
   Phase 3 (other 6 strategies), then Phase 4 (backlog + smoke + finish).

**Key deltas from the original plan:**

- Task 1 is DONE (grep confirmed BRIEFINGS is launcher-local).
- Task 3 (CodeViewer class) is DONE as a standalone module. The integration step is
  now `from code_viewer import CodeViewer` instead of pasting ~150 lines of class
  definition into `launcher.py`.
- Task 6 (audit CITADEL) is partially DONE — the shared core is audited. What
  remains is to apply L1-L12 to CITADEL-specific behavior (how it uses omega score,
  chop mode, the decision flow in its particular scan loop branches). Audit doc can
  be extended with a `## CITADEL` section.
- Tasks 9-14 (audit remaining 6 strategies) are UNCHANGED — still need to run.
- Everything else unchanged.

### Option B — Apply only the audit fixes

If you just want the L6 and L7 SMELLs fixed and don't care about the menu refactor:

1. Read `docs/audits/backtest-fixes-backlog.md` — it has the exact fix for both.
2. Apply L6 fix: add aggregate notional check in `core/portfolio.py`.
3. Apply L7 fix: move liquidation into `label_trade` in `core/signals.py`.
4. Run a regression backtest (e.g., CITADEL on a known dataset) and confirm PnL
   differs only in ways consistent with the new checks.
5. Commit as `fix(core): aggregate notional cap + path-dependent liquidation`.

### Option C — Wire CodeViewer now without the full refactor

If you want the "VER CÓDIGO" button working IMMEDIATELY without waiting for the full
menu refactor:

1. In `launcher.py` (after committing or stashing your WIP), add at the top:
   ```python
   from code_viewer import CodeViewer
   ```
2. In `_brief`, find the action button section and add a new button that calls
   `CodeViewer(self.root, [script], (script, "scan_symbol"))` or similar — `script`
   is the second argument to `_brief`, which is already the path to the strategy
   file. You don't need `BRIEFINGS_V2` for this — the existing narrative briefing
   plus a "VER CÓDIGO" button is a valid intermediate state.
3. Commit.

This is the 10-minute version. It gives you half of the ask without touching the
briefing content model.

---

## Git state at end of session

```
main (HEAD):
  + .worktrees/experiment  (worktree, branch feature/experiment — unused)
  + code_viewer.py         (new, committed)
  + docs/audits/backtest-physics-core-2026-04-10.md     (new, committed)
  + docs/audits/backtest-fixes-backlog.md               (new, committed)
  + docs/superpowers/specs/2026-04-10-backtest-audit-and-technical-briefing-design.md  (committed earlier)
  + docs/superpowers/plans/2026-04-10-backtest-audit-and-technical-briefing.md         (committed earlier)
  + docs/superpowers/plans/RESUME-NOTE-2026-04-10.md    (this file, new, committed)
  + .gitignore  (modified earlier, committed)

Still uncommitted in main working tree (YOUR WIP, UNTOUCHED):
  M aurum_cli.py
  M config/connections.json
  M core/market_data.py
  M core/portfolio_monitor.py
  M launcher.py            ← the 1464-line WIP
  ?? config/paper_state.json
  ?? .superpowers/
  ?? .claude/settings.local.json  (modified)

feature/experiment branch:
  Exists but has no commits beyond the fork point (2a3891d). The worktree at
  .worktrees/experiment has a `.plan-notes/task-01-briefings-usage.md` file
  that was written by the Task 1 subagent and not committed (ephemeral).
```

Nothing destructive was done. Your WIP is exactly as you left it.
