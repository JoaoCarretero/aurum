# engines/live.py Extraction — Deferred to Dedicated Sprint

**Status:** DEFERRED (not this sprint).
**Created:** 2026-04-25
**Owner:** Joao (decision), Claude Code (eventual execution).
**Refs:**
- Audit: `docs/audits/2026-04-25_general_audit.md` Lane 1 finding #4 (HIGH).
- Baseline of current live.py: commit `bf7f2f3` (`feat(live): wire dd_velocity gate into LiveEngine — caller-side computation`).
- Pattern reference: `launcher.py` was already partially extracted to `launcher_support/` (~20 modules). Same shape applies here for `engines/live.py` → `engines/live/`.

---

## 1. Decision

**Extraction is deferred from the current sprint to a dedicated future sprint.**

`engines/live.py` is the highest-risk file in the repo (audit Lane 1 #4): 2560 lines, 7 distinct concerns, 23/59 functions type-annotated, real-money asyncio path. The audit recommends extracting each concern into its own module under `engines/live/`. The work is real, but **not now**.

Concerns to extract (current state in `engines/live.py`):

| # | Symbol | Lines (approx) | Role |
|---|---|---|---|
| 1 | `Position` (PositionState) | 317-379 | Open-position dataclass with trailing-stop bookkeeping. |
| 2 | `KillSwitch` + gate wiring (RiskEngine) | 381-446 | 3-layer statistical kill + risk_gates plumbing. |
| 3 | `ExecutionDrift` | 448-484 | Latency / fill-quality tracker. |
| 4 | `CandleBuffer` | 486-515 | Per-symbol OHLCV ring buffer. |
| 5 | `OrderManager` | 517-663 | Exchange order submission + state machine. |
| 6 | `SignalEngine` | 665-880 | Signal scan loop, integrates CandleBuffer + indicators. |
| 7 | `LiveEngine` | 882-2444 | Orchestrator owning the others. |

---

## 2. Why this sprint was wrong for it

The audit surfaced 4 CRIT items + 4 HIGH. Refactoring `live.py` was scored HIGH (#8) but **not** CRIT. Concretely, this sprint had higher-priority items active:

1. **CRIT items first.** BRIDGEWATER decision (`#5`), PHI verdict (`#9`), `gate_dd_velocity` wiring (done `bf7f2f3`), `gate_anomaly` (still pending). Each is either pra-edge (BW/PHI) or pra-safety (gates). A structural refactor competes for the same bandwidth and is none of those.
2. **Multi-Claude coordination risk.** Another Claude is in adjacent files — `launcher_support/engines_live_view.py` and the cockpit/live UI surface. Touching `engines/live.py` mid-flight risks merge conflicts in the **real-money path** (asyncio order state). AGENTS.md §2 conflict-of-lane rule: "quem chega depois faz rebase/merge". Better to wait for the adjacent lane to land.
3. **No bug, no urgency.** `live.py` is architecturally dense, not broken. Smoke 172/172. Suite 2129 passed. The recent dd_velocity wiring (`bf7f2f3`) integrated cleanly without needing extraction. There is no production fire forcing the move.
4. **Refactor regression risk in real-money path.** `live.py` is `LIVE` mode entry. A behavior-preserving refactor is still a refactor: import paths, side effects (logging setup, RUN_DIR), asyncio cancellation semantics. Doing it under deadline pressure is exactly when subtle bugs ship. Better in a dedicated sprint with no concurrent CRIT work and no parallel agent in adjacent files.

**Counter-considered and rejected:** "do it now while context is fresh." The audit context is captured here and in `docs/audits/2026-04-25_general_audit.md`. Freshness is preserved by the doc; risk is not lowered by haste.

---

## 3. Eventual extraction order (TDD per module, smallest/safest first)

The order maximizes safety: dataclasses and pure utilities first; orchestrator last. Each phase is one atomic commit.

| Phase | Concern | Target path | Why this order |
|---|---|---|---|
| **A** | `Position` (PositionState) | `engines/live/position.py` | Lowest coupling. Pure data + small methods. Easiest to characterize. |
| **B** | `CandleBuffer` | `engines/live/candle_buffer.py` | Pure ring buffer over OHLCV. No async, no exchange, no risk. |
| **C** | `ExecutionDrift` | `engines/live/execution_drift.py` | Latency / fill metrics. Append-only state, no I/O. |
| **D** | `RiskEngine` (`KillSwitch` + gates wiring) | `engines/live/risk_engine.py` | Wraps `KillSwitch` + the per-tick `risk_gates` plumbing into one object. Read-only against state. |
| **E** | `SignalEngine` | `engines/live/signal_engine.py` | Signal scan loop. Depends on CandleBuffer + indicators (already in `core/`). No order side-effects. |
| **F** | `OrderManager` | `engines/live/order_manager.py` | Exchange submission + state machine. The riskiest leaf — but by this phase, A-E are isolated and tested. |
| **G** | `LiveEngine` (slim final) | `engines/live/__init__.py` (or `engines/live/live_engine.py` re-exported via `__init__`) | Orchestrator only. Owns the others. CLI entrypoints (`_menu`, `_run_diagnostic`, `_launch`) move with it. |

**For each phase:**

1. **Characterization tests first.** Pin current behavior before moving any line. Tests live under `tests/engines/live/test_<module>.py`. They must be runnable against the **current** `engines/live.py` (importing the symbol directly) **and** survive the move untouched.
2. **Extract module.** Move the class/functions to the new file; update imports in `engines/live.py`. The original file keeps a re-export shim for one phase (so external callers keep working) until phase G replaces the shim with the real `__init__.py`.
3. **Verify.** Run `python smoke_test.py --quiet` (must be 172/172 or higher) AND full `pytest` (must pass with no new failures). Manual check: `python -m engines.live --diagnostic` (or whatever the current diagnostic entrypoint is).
4. **Commit atomically.** One module = one commit. Subject format: `refactor(live): extract <Concern> to engines/live/<module>.py`. Body lists the tests added and the verification commands run.

**Phase G note:** the final phase is the trickiest because `LiveEngine.__init__` instantiates and wires everything (logging, RUN_DIR, asyncio loop, telegram bot). The slim version owns only orchestration; A-F own their own state. Phase G's commit must be the smallest possible diff *given* A-F already landed.

---

## 4. Constraints that will apply when the sprint runs

These are non-negotiable per `CLAUDE.md` and the audit. Repeated here so the future-sprint executor (Claude or otherwise) does not have to re-derive them.

- **CORE files are protected.** `core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py` — none touched by this refactor. If any extraction "needs" a CORE change, the extraction is wrong, not CORE.
- **One module per commit, atomic.** No "and while I was at it..." commits. Phase A is Position only. Phase B is CandleBuffer only. Etc.
- **Smoke must pass after each commit.** `python smoke_test.py --quiet` returns 172/172 (or the current baseline at sprint start, whichever is higher). A failing smoke aborts the phase — fix forward or revert.
- **Full suite must pass after each commit.** `pytest` returns the current baseline-or-better (currently 2129 passed / 8 skipped / 0 failed at audit time). xdist optional — sequential is the contract.
- **No behavior changes.** Pure structural extraction. New modules expose the **same public surface** as the corresponding section of `live.py`. No method renames, no signature shuffles, no "while I'm here let me also...". If a behavior change is justified, it goes in a *separate* commit *after* the extraction lands.
- **Type annotations added for all public method signatures.** The audit found 23/59 functions annotated (~40%). Extraction is the natural moment to fix this — every public method on the new module gets explicit param + return types. Internal helpers can stay un-annotated if not exported.
- **No `config/keys.json` writes.** Standard rule, repeated here because `LiveEngine._load_keys` touches keys flow. Use `core.risk.key_store.load_runtime_keys` if anything needs to be re-routed.
- **Backwards-compat shim during transition.** `engines/live.py` keeps re-exporting symbols (`from engines.live.position import Position` etc.) until phase G consolidates. External callers (`launcher_support/engines_live_view.py`, `engines/millennium_live.py`, CLI entrypoints) must keep working with `from engines.live import LiveEngine`.

---

## 5. Effort estimate

- **Total wall-clock:** 1-2 weeks of focused sprint time.
- **Commits:** ~7 atomic (one per phase). +1-2 setup commits (test scaffolding under `tests/engines/live/`, optional `engines/live/__init__.py` skeleton). Realistic total: 8-9 commits.
- **Risk profile:** A-D are low-risk (small concerns, easy to characterize). E-F medium (more state, more callers). G high (the orchestrator stitch).
- **Pre-conditions before starting:**
  - No CRIT items active in `docs/audits/`.
  - No parallel Claude/Codex work in `engines/live.py` or `launcher_support/engines_live_view.py`.
  - Latest CITADEL/JUMP backtests reproducible from `main` (sanity that the rest of the system is not drifting under us mid-refactor).

---

## 6. Caveats / coordination warnings

- **Parallel-agent surface.** `launcher_support/engines_live_view.py` consumes `engines.live` symbols. The sprint executor must check `git log --since="7 days ago" -- launcher_support/engines_live_view.py engines/live.py` before starting and **abort** if either file has unmerged work in flight.
- **VPS shadow runner.** `deploy/install_shadow_vps.sh` and `millennium_shadow.service` import the live engine path. Phase G must not break the import surface used by the systemd unit. Verify on staging before merging.
- **Telegram bot binding.** `LiveEngine` constructs and owns the telegram bot lifecycle. When extracting orchestration (phase G), the bot lifecycle stays inside `LiveEngine` — do NOT split `bot/telegram.py` integration into a separate phase.
- **Backtest engines do NOT import `engines/live.py`.** Verified at audit time: `engines/citadel.py`, `engines/jump.py`, `engines/bridgewater.py` etc. never reach into `engines/live`. Backtests are unaffected by this refactor.
- **Documentation.** When the sprint lands, update `CLAUDE.md` "Estrutura de Ficheiros" to reflect `engines/live/` package, and add a session log + daily log per the standard rules.

---

## 7. Cross-references

- Audit: `docs/audits/2026-04-25_general_audit.md` (Lane 1 #4, also triangulated in Lane 4 + Lane 5).
- Baseline commit before extraction: `bf7f2f3` (live.py at 2560 lines, dd_velocity wired).
- Pattern reference: the `launcher_support/` extraction of `launcher.py` (still ongoing per audit Lane 1 #1) — same shape, smaller per-module risk.
- Project rules that govern this work: `CLAUDE.md` (CORE protected, no `keys.json` writes, session log requirement), `AGENTS.md` (lane coordination), `MEMORY.md` (anti-overfit rule does not apply here — this is structural, no signal change).

---

**Bottom line:** the work is real, the order is decided, the constraints are written. When the next dedicated window opens with no CRIT competing and no parallel lane in adjacent files, this doc is the spec to execute against.
