# Aurum — Professional Fund Readiness

**Created:** 2026-04-11
**Owner:** João Carretero (solo dev + trader)
**Goal:** Take the aurum repo from working-bench state to something that can
run with real money under professional discipline — real-time observability,
immutable audit trails, safe process control, and explicit live-trading
guardrails.

This document is the canonical reference for the multi-phase work. Each phase
is independently shippable and MUST pass its verification before the next one
starts. Edit this doc as work progresses — check off tasks with `[x]`, update
the Status column, and add a dated entry to the Changelog at the bottom.

---

## Phases overview

| # | Title | Severity | Est. effort | Depends on | Status |
|---|---|---|---|---|---|
| 0 | Data hygiene + launcher data access | ALTO | ~1h | — | ✅ done 2026-04-11 |
| 1 | Identity-verified process control (D5) | **CRÍTICO** | ~1.5h | — | ✅ done 2026-04-11 |
| 2 | Process observability UI | ALTO | ~2h | Fase 1 | ✅ done 2026-04-11 |
| 3 | Per-strategy audit + L6/L7 across all engines | ALTO | multi-session | — | 🟡 3.1 + 3.2 done 2026-04-11; 3.3 pending |
| 4 | Live trading guardrails (design + impl) | **CRÍTICO** | multi-session | Fase 1, brainstorming | ⏳ pending |

**Severity legend:**
- **CRÍTICO** — blocks going live with real money. Must land before any production engine spawns with funded keys.
- **ALTO** — blocks comfort / correctness but not safety. Should land before scaling.
- **MÉDIO / BAIXO** — quality of life, paper cuts.

**Shipping order:** 0 → 1 → 2 → 3 → 4. Phase 3 can interleave with 2 since it
touches different files. Phase 4 MUST NOT start until Phase 1 is in place
(process control must be trustworthy before live orders hit a broker).

---

## Phase 0 — Data hygiene + launcher data access

**Why:** Three places in `launcher.py` still filter on `"reports" in str(r)`
or `"darwin" in str(r)`, which ignores the modern `data/runs/<run_id>/`
layout entirely. `data/index.json` has three known inconsistencies relative
to disk. Three process entries from 2026-04-09 are zombie in
`data/.aurum_procs.json`. None of this is dangerous but it blocks useful
observability and makes every "why don't I see X?" question expensive.

### 0.1 — Fix data access filters (D1, D2, D3)

**Files:** `launcher.py`

- [ ] `launcher.py:498-508` (splash "last backtest" row) — replace the
  `rglob("citadel_*.json") + "reports" in str(r)` scan with a helper
  `_latest_run_summary()` that reads `data/index.json` first, falls back to
  globbing `data/runs/*/summary.json` if the index is missing.
- [ ] `launcher.py:1125-1131` (`_results` fallback lookup) — same helper,
  fallback chain: `data/runs/<latest>/citadel_15m_v36.json` → legacy
  `data/reports/*.json`.
- [ ] `launcher.py:2432` (`_data` / Terminal > Reports & Logs) — broaden the
  filter to include any JSON inside `data/runs/<run>/`, `data/arbitrage/`,
  `data/darwin/`, `data/2026-04-09/reports/`. Make the screen show three
  columns: `{file, date, size}` + badge indicating which section
  (`RUNS`, `LEGACY`, `ARBITRAGE`, `DARWIN`).

**Acceptance:**
- `python smoke_test.py` → 150/150 passes.
- Manual: splash shows a real "last backtest" row (non-dim).
- Manual: Terminal > Reports & Logs scrolls through all 21 modern runs.

### 0.2 — Reconciliation tool (dry-run first)

**File:** new `tools/reconcile_runs.py`

Walks `data/runs/` and `data/index.json` and prints a plan:

```
ORPHAN DIRS (on disk, not in index):
  - citadel_2026-04-09_2350  (12 bytes, no summary.json — likely crashed mid-run)

DUPLICATED INDEX ROWS (same run_id, multiple entries):
  - citadel_2026-04-09_2356  ×2
      [0] pnl=1428.97 trades=188 hash=a11ed471...
      [1] pnl=19493.09 trades=183 hash=a11ed471...
    NOTE: PnLs differ → second run overwrote the first's dir. Only the
    second entry is observable on disk.
  - citadel_2026-04-10_1155  ×2
      [0] pnl=1832.23 trades=173
      [1] pnl=1832.23 trades=173
    NOTE: PnLs identical → index writer bug wrote the same entry twice.

RECOMMENDED ACTIONS:
  1. Delete orphan 2350 (directory has no summary.json, no downstream refs)
  2. Dedupe 2356 → keep [1] (matches disk)
  3. Dedupe 1155 → keep [0]
```

With `--apply`, the script mutates `data/index.json` (dedupe) and
optionally `rm -r data/runs/citadel_2026-04-09_2350`, asking Y/n per item.

- [ ] Write `tools/reconcile_runs.py` with `--dry-run` default and `--apply`.
- [ ] Add minimal unit check: run against a fixture dir with a fake orphan + fake dup.
- [ ] Self-check: refuses to run if `.worktrees/` contains a dirty version of `data/index.json`.

**Acceptance:**
- `python tools/reconcile_runs.py` runs without args and prints the plan.
- `python tools/reconcile_runs.py --apply` prompts per item.
- After apply, `python tools/reconcile_runs.py` prints "clean — no drift".

### 0.3 — Apply reconciliation

- [ ] Execute 0.2's tool with `--apply`, accept user's decisions on each item.
- [ ] Commit the updated `data/index.json` (the directory rm is a filesystem
  action, not a git change — it's already gitignored under `data/runs/`).

### 0.4 — Cleanup zombie procs

**File:** `core/proc.py`

- [ ] Extend `_cleanup()` (line 185) to also remove entries whose status is
  `finished` and whose `finished` timestamp is older than N days
  (configurable, default 1 day). Conservative default — we want entries to
  be visible for long enough to be useful post-mortem.
- [ ] Run `_cleanup()` once manually via a one-liner to clear the 3 zombies
  from 2026-04-09.

**Acceptance:**
- `python -c "from core.proc import list_procs; print(list_procs())"` returns `[]`.
- `data/.aurum_procs.json` contains `{"procs": {}}`.

### Phase 0 sign-off checklist

- [ ] All 4 subphases land in individual commits.
- [ ] `python smoke_test.py` → 150/150.
- [ ] User reopens launcher, confirms: splash last-backtest row is real, Reports & Logs scrolls, DELETE button appears on backtest run detail panel.

---

## Phase 1 — Identity-verified process control (D5)

**Why:** The current `_is_alive(pid)` in `core/proc.py:46-62` only asks
Windows "does a process with this PID exist and is it still running?" —
it never checks whether the process is the ORIGINAL one we spawned.
Windows reuses PIDs aggressively. Two concrete failure modes today:

1. `list_procs()` can report a zombie-but-recycled PID as `alive=True`.
2. `stop_proc(pid)` calls `taskkill /F /PID` blindly. If the PID was
   reused by a different process (browser, svchost, *any* Windows
   process), we kill that process instead. Unacceptable with live
   engines authorised to touch money.

**Goal:** `_is_alive` and `stop_proc` must verify process identity before
taking any action.

### 1.1 — Spawn captures identity

**File:** `core/proc.py` — `spawn()` (line 65-122)

After `proc = subprocess.Popen(...)` succeeds, capture and persist:

- `creation_time` — `GetProcessTimes.lpCreationTime` on Windows (low+high
  FILETIME → 100ns since 1601-01-01). On POSIX: `/proc/<pid>/stat` field 22
  (jiffies since boot) or `psutil.Process(pid).create_time()` — but we
  have no psutil dependency; prefer a pure-ctypes Windows path and a
  minimal POSIX fallback.
- `image_name` — on Windows: `QueryFullProcessImageNameW` → basename should
  be `python.exe` or `pythonw.exe`. On POSIX: read `/proc/<pid>/comm` or
  `/proc/<pid>/exe` resolve.

Persist both in the proc entry:
```json
{
  "engine": "newton",
  "pid": 22508,
  "started": "2026-04-09T16:28:15.993762",
  "creation_time": 132987654321000000,
  "image_name": "python.exe",
  "log_file": "...",
  "status": "running"
}
```

### 1.2 — `_is_alive` verifies identity

**File:** `core/proc.py` — `_is_alive()` (line 46-62)

New signature: `_is_alive(pid: int, expected: dict | None = None) -> bool`.

- Legacy call sites (`_is_alive(pid)`) keep the old behaviour: just a
  liveness check.
- New call sites pass the full proc entry as `expected`. Liveness AND:
  - `GetProcessTimes.CreationTime(current pid)` must equal
    `expected["creation_time"]` (exact match — these are nanoseconds, so
    there's no tolerance window, either it's the same process or it isn't).
  - `QueryFullProcessImageNameW(current pid)` basename must equal
    `expected["image_name"]`.
- If either check fails → return `False`. The PID was reused.

### 1.3 — `stop_proc` re-verifies before taskkill

**File:** `core/proc.py` — `stop_proc()` (line 139-153)

New signature: `stop_proc(pid: int, expected: dict | None = None) -> bool`.

- Always re-run `_is_alive(pid, expected=expected)` immediately before
  `taskkill`.
- If it returns `False`, abort with `raise RuntimeError("PID reuse detected
  — refusing to kill")` — fail LOUD, not silent.
- All call sites in the repo updated to pass the expected entry:
  - `list_procs()` iterates state entries, each has the entry
  - UI screens pass the entry from the row they clicked
  - `delete_proc(pid)` also updated

### 1.4 — `list_procs` uses identity check by default

**File:** `core/proc.py` — `list_procs()` (line 125-136)

For each state entry, call `_is_alive(pid, expected=info)`. This is what
gates the "status=running vs finished" transition AND what the UI reads.

**Acceptance:**
- Unit test in `tests/test_proc_identity.py`:
  - Spawn a short-lived subprocess, capture entry, verify `_is_alive(pid, expected=entry) == True`.
  - Wait for it to finish, verify `_is_alive(...) == False`.
  - Simulate PID reuse: mutate `expected["creation_time"]` to a wrong value, verify `_is_alive(...) == False`.
- `python smoke_test.py` → 150/150.
- Manual smoke: open Terminal > Processes screen, confirm no zombies reported.

### Phase 1 sign-off checklist

- [ ] `core/proc.py` handles identity correctly.
- [ ] `tests/test_proc_identity.py` written and passing.
- [ ] Call sites updated (UI screens, delete_proc, stop_proc callers).
- [ ] Smoke test passes.
- [ ] Commit: `fix(proc): identity-verified _is_alive and stop_proc (D5)`.

---

## Phase 2 — Process observability UI

**Why:** Today there is no runtime view of a running engine. João asked:
"how do I see logs, access runtime data, pause, stop?" The existing
`_procs` screen is a static list that only refreshes with `R` and depends
on the broken `_is_alive`. You cannot introspect a live engine without
opening a log file by hand.

### 2.1 — New screen `_procs_live`

**File:** `launcher.py` — new method, menu entry in Terminal section.

Layout (two columns):

```
LEFT  — running engines list, auto-refresh 2s
        columns: engine | pid | uptime | mem | last-log-line
        click a row → select it (highlights, streams its log on right)

RIGHT — log tail viewer for the selected engine
        tail -f equivalent: last 500 lines, auto-scroll to bottom
        buttons: [STOP] [KILL -9] [OPEN LOG IN EDITOR]
```

Bottom action bar:
- `SPAWN ▸` dropdown with all engines from `ENGINES` map in `core/proc.py`.
- `REFRESH` manual refresh (auto-refresh every 2s can be toggled).

### 2.2 — Log tail worker

- Background thread reads the log file with tail semantics (seek to EOF,
  read appends, never truncate).
- Sends new lines to the UI thread via `queue.Queue`.
- UI polls the queue in `after(200)` and appends to a `Text` widget
  (capped at 500 lines — oldest rolls off).
- On engine select: stop old tail thread, start new one on new log.

### 2.3 — Menu entry

- Add to `_terminal()` LOCAL DATA section: `("L", "Live Engines", "Running processes + log stream", True)`.
- Clicking routes to `_procs_live()`.
- Deprecate but don't delete the old `_procs()` — keep it as a simple fallback reachable via `P` in `_terminal`.

**Acceptance:**
- `python smoke_test.py` → 150/150 (smoke test extended to call `_procs_live()`).
- Manual: spawn a backtest, open Live Engines, see the log stream update in real time.
- STOP button gracefully terminates; KILL -9 force-kills; OPEN LOG opens the log file.

### Phase 2 sign-off checklist

- [ ] `_procs_live` screen works.
- [ ] Log tail thread is cleaned up on screen change (no leaked threads).
- [ ] SPAWN dropdown works for every engine in the map.
- [ ] Smoke test covers the new screen.
- [ ] Commit: `feat(launcher): live engines screen with log tail + spawn/stop`.

---

## Phase 3 — Per-strategy audit + L6/L7 across all engines

**Why:** Today the L6/L7 fixes only apply to `engines/backtest.py`. The
other engines (`mercurio`, `newton`, `thoth`, `harmonics`) still have the
exact same anti-patterns in their own scan loops. Any backtest result from
them is subject to the same inflation the core engine used to have.

Also: the 2026-04-10 audit only covered the SHARED core — per-strategy
decision logic was never audited against the L1-L12 checklist.

### 3.1 — Apply L6 (aggregate notional cap) to remaining engines

**Files:**
- `engines/mercurio.py`
- `engines/newton.py`
- `engines/thoth.py`
- `core/harmonics.py` (RENAISSANCE)

Each file needs:
- `open_pos` tuple extended to include `(exit_idx, symbol, size, entry)`
- Import `check_aggregate_notional` from `core.portfolio`
- Call the check immediately after final sizing, before trade commit

Note: NEWTON is a pair trading engine — `scan_pair` opens TWO legs per
trade. The aggregate cap needs to sum BOTH legs' notionals. Special-case it.

### 3.2 — Per-strategy audit

**Output:** `docs/audits/backtest-physics-strategies-2026-04-11.md`

For each of CITADEL, RENAISSANCE, DESHAW, JUMP, BRIDGEWATER, MILLENNIUM,
JANESTREET: apply the L1-L12 checklist from
`docs/superpowers/plans/2026-04-10-backtest-audit-and-technical-briefing.md`
to the specific scan loop and decision flow. One section per strategy,
using the template already defined in that plan.

### 3.3 — BRIEFINGS_V2 populate

**File:** `launcher.py` — new `BRIEFINGS_V2` dict, coexists with `BRIEFINGS`.

For each audited strategy, write the V2 entry:
- `source_files`, `main_function`
- `one_liner`
- `pseudocode`
- `params`, `formulas`, `invariants`

Wire `_brief` to prefer `BRIEFINGS_V2` when present, fall back to
`BRIEFINGS` otherwise. The existing VER CÓDIGO button (commit 4b24d07)
already opens the source; V2 just adds the technical view above the
narrative.

**Acceptance:**
- Audit doc has 7 sections, each with L1-L12 results + summary table.
- `BRIEFINGS_V2` has 7 entries, each with all required fields.
- Legacy engines run with aggregate cap and produce finite, non-negative equity.
- Smoke test still passes.

### Phase 3 sign-off checklist

- [ ] L6 in all 4 additional engines.
- [ ] Per-strategy audit doc complete (7 strategies).
- [ ] `BRIEFINGS_V2` populated for all 7.
- [ ] Commits: one per strategy audit + one for L6 rollout + one for V2 wire.

---

## Phase 4 — Live trading guardrails

**Why:** Everything that makes real-money trading safe that does NOT exist
in the repo today. Each sub-item needs a design conversation before code —
this phase is intentionally kept as an open question list, not an
implementation plan.

### 4.1 — API key storage & rotation

**Open questions (need brainstorming):**
- Storage: encrypted file, OS keyring, HashiCorp Vault, AWS Secrets Manager?
- Master password: user prompt per session? env var? hardware token?
- Rotation cadence: monthly? quarterly? after any security event?
- Permissions on the keys: READ-ONLY for monitoring vs TRADE for execution — separated?
- Per-venue separation: one file per venue or one file with venue sections?
- Backup strategy: how does João recover if the local machine dies?

**No code is written in this sub-item until the questions are answered.**

### 4.2 — Order audit trail

**Open questions:**
- Format: JSONL append-only, SQLite, Parquet?
- Schema: what fields are mandatory? (client_order_id, venue_order_id,
  timestamp, symbol, side, type, qty, price, status, venue_response_raw,
  engine, strategy_version, config_hash, intent_id)
- Retention: forever? rolling N months? offsite backup?
- Query layer: grep? a small CLI? a screen in the launcher?
- Immutability: append-only with hash chaining (each row references prev row's hash) for tamper-evidence?

### 4.3 — Kill switch

**Open questions:**
- Scope: one switch for all engines, or per-engine?
- Actions on trigger, in order: (a) stop new orders, (b) cancel open orders,
  (c) flatten all positions at market, (d) kill engine processes, (e) write
  reason to audit trail, (f) Telegram notification.
- Triggers: manual button, hotkey, external (Telegram command), automatic
  on circuit-breaker (see 4.5), automatic on reconciliation drift (see 4.4).
- Idempotency: re-pressing the button is a no-op if flatten already succeeded.
- Failure mode: if flatten fails, what happens? Retry how many times?
  Alarm how?

### 4.4 — Reconciliation loop

**Open questions:**
- Frequency: every N seconds? on engine tick? on order fill event?
- Scope: positions (qty per symbol), equity, open orders, realised PnL.
- Source of truth: broker state always wins.
- Drift tolerance: what's the threshold? (e.g. qty diff > 1 lot triggers alarm).
- Action on drift: alarm? auto-fix by forcing local state to match? kill switch?
- Persistence: log drift events to audit trail even if auto-fixed.

### 4.5 — Circuit breakers

**Open questions:**
- Account-level: max daily DD (%), max daily loss ($), max consecutive losses,
  max gross notional, max net exposure, max leverage actually used vs
  configured.
- Per-strategy: max concurrent positions, max PnL contribution, max drawdown.
- Time-based: no new entries in last N minutes of a session, no entries
  during high-impact news windows.
- Action on breach: pause new entries (soft), kill switch (hard). Who
  decides which?
- Reset condition: automatic at midnight UTC? manual? after review?

### 4.6 — Canary mode

**Open questions:**
- Capital: what % of total for the canary phase?
- Duration: how many days / how many trades before scaling?
- Promotion criteria: backtest-live correlation > X? Sharpe > Y? Max DD < Z?
- Demotion criteria: any anomaly? specific thresholds?
- Scaling schedule: linear ramp? step function? volatility-adjusted?

### Phase 4 sign-off checklist

- [ ] Brainstorming session with João on each sub-item.
- [ ] Write a separate implementation spec for each that the user approves.
- [ ] Each sub-item gets its own plan doc under `docs/superpowers/plans/`.
- [ ] Phase 4 is effectively a meta-phase — it spawns N sub-plans.

---

## Cross-cutting conventions

Applies to all phases:

1. **Atomic commits.** One logical change per commit, with a body
   explaining the why. No "wip" or "fixes" in subject lines.
2. **Smoke test every commit.** `python smoke_test.py` must be 150/150
   before every commit that touches `launcher.py` or `core/`.
3. **Audit trail mirror.** Every destructive operation (reconciliation
   dedupe, zombie proc cleanup, kill switch trigger) must write a row to
   `docs/audits/ops-log-<YYYY-MM>.md` with timestamp, actor, command,
   diff.
4. **No silent fallbacks in live code paths.** Live/order-related code
   raises on unexpected states; monitoring code logs and continues.
5. **PT-BR for user-facing strings, English for code/comments/docs.**
   Matches existing convention in launcher.py and engine files.
6. **Every new test file named `tests/test_<module>.py`.** Even a single
   sanity test is better than nothing.
7. **Plan doc staleness.** If anything in this doc becomes wrong during
   execution, UPDATE the doc in the same commit that makes it wrong.
   Never let the plan diverge from reality.

---

## Changelog

### 2026-04-11 — Plan created

Initial phase breakdown based on audit in the session transcript. Items:
D1-D9. Plan committed as part of Phase 0 kickoff.
