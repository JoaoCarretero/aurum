# AURUM Agents — Alignment & Organization (Phase 1)

**Date**: 2026-04-24
**Status**: ⚠️ **SUPERSEDED** — this design proposed creating `docs/AGENT_PIPELINE.md`. During implementation, Joao was independently building `AGENTS.md`/`MEMORY.md`/`CONTEXT.md`/`SKILLS.md` at the repo root plus per-operative personas at `docs/agents/<key>.md`. The final design dropped `AGENT_PIPELINE.md` in favor of placing the pipeline-specific content (TIPO 1/2/AUDIT workflows, spec template, closure) in a single new file `docs/agents/WORKFLOWS.md`. The 5 Paperclip agent instruction files were rewritten as thin pointers that read the 5 root files + `WORKFLOWS.md` + their own persona. Implementation completed 2026-04-24. Kept for historical context.
**Scope**: Phase 1 of a two-phase effort. Phase 2 (CURATOR as alignment guardian) is previewed but out of scope here.

---

## 1. Context & problem

The AURUM Research Desk runs 5 Paperclip agents (SCRYER, CURATOR, ARBITER, ARTIFEX, ORACLE) against the `aurum.finance` repo via `claude_local` adapter with `--add-dir C:/Users/Joao/projects/aurum.finance`. Each agent has a free-form `AGENTS.md` instruction file in `~/.paperclip/instances/default/companies/{cid}/agents/{aid}/instructions/`.

**The drift problem**: those AGENTS.md files were written when the repo looked different. They now contain stale or wrong information:

| Area | AGENTS.md says | Reality |
|---|---|---|
| Engine roster (SCRYER) | AZOTH, HERMES, PROMETEU, QUANTUM, MERCURIO, THOTH, NEWTON, DARWIN, ARBITRAGE | None of these exist. Registry in `config/engines.py`: citadel, renaissance, jump, bridgewater, millennium, janestreet, twosigma, aqr, graham, phi, live, millennium_live, supertrend_futures |
| Spec path | `docs/specs/YYYY-MM-DD_*_spec.md` | `docs/superpowers/specs/YYYY-MM-DD-*-design.md` |
| Root modules (ARBITER, ARTIFEX) | `backtest.py`, `multistrategy.py`, `live.py` at root | Absent. `live.py` is under `engines/`. Orchestration is in `engines/millennium.py` |
| Protected files | Missing from 4/5 agents: `config/params.py`, `config/keys.json`, `launcher.py` | All three are canonical protected per CLAUDE.md §4 |
| Reference engines (ARTIFEX) | "kepos, graham, ornstein" as mature examples | `kepos.py` and `ornstein.py` are archived (worktree-only after OOS audits). Only `graham.py` lives on main |
| Integration pattern (ARTIFEX) | "Engine appears automatically in backtest.py/multistrategy.py/launcher.py" | Registration is `config/engines.py`. Launcher integration already automatic via registry |

Observed failure mode: AUR-8 ticket description explicitly said "IGNORE the reviewer's suggestion to reuse JANE STREET / filter BRIDGEWATER, those are based on stale AGENTS.md". This is a drift tax paid by the Board on every ticket.

## 2. Goals & non-goals

**Goals**
- Eliminate drift between agent instructions and repo reality as of 2026-04-24.
- Establish a sustainable architecture where common operational facts live in one place (not duplicated across 5 AGENTS.md).
- Reduce AGENTS.md total size from ~24 KB to ~10 KB (cut tokens paid per run ×N turns).
- Align agent behavior with AURUM culture end-to-end: philosophy, code style, backtest conventions, engine pattern, DB access, directory organization.

**Non-goals**
- Not rewriting `CLAUDE.md` (395 lines, actively maintained, out of scope).
- Not redesigning the 5 roles (Joao confirmed "ajustar" scope, not "repensar").
- Not implementing the automated drift-detection loop (that is Phase 2).
- Not changing Paperclip agent configs (model, budget, turns, timeout) — this is a separate optimization axis.
- Not fixing ORACLE's current `status: error` state (separate operational issue; unrelated to alignment).

## 3. Architecture

Three-layer instruction stack per agent run:

```
┌──────────────────────────────────────────────────────────┐
│ 1. CLAUDE.md  (aurum.finance/CLAUDE.md)                  │ auto-loaded
│    Philosophy, anti-overfit, core protection, session   │ by Claude Code
│    logging. ~20 KB. Source of truth for repo rules.     │ via --add-dir
└──────────────────────────────────────────────────────────┘
                           ↓ referenced by
┌──────────────────────────────────────────────────────────┐
│ 2. AGENT_PIPELINE.md  (aurum.finance/docs/AGENT_PIPELINE │ read explicitly
│    .md — NEW)                                            │ at start of run
│    Agent roster, workflows (TIPO 1/2/AUDIT), protected  │ per AGENTS.md
│    files canonical list, engine roster (points to       │ instruction
│    config/engines.py), directory conventions, spec      │
│    template §9, DB access, closure workflow. ~5 KB.     │
└──────────────────────────────────────────────────────────┘
                           ↓ specialized by
┌──────────────────────────────────────────────────────────┐
│ 3. AGENTS.md  (one per agent, in Paperclip instance dir) │ loaded as
│    Identity, scope, "not your job", inputs, outputs,    │ primary system
│    agent-specific rules, stop conditions, budget.       │ instruction by
│    ~1–1.5 KB each (ORACLE ~4 KB due to 6-block audit    │ Paperclip
│    template).                                            │ adapter
└──────────────────────────────────────────────────────────┘
```

**Key properties**:
- CLAUDE.md is auto-loaded by Claude Code when `--add-dir` points to a directory containing it. Agents get it for free.
- AGENT_PIPELINE.md is a regular file; AGENTS.md must explicitly instruct the agent to read it at start of run.
- Common facts (protected files, engine roster, workflows) live once in the canon doc. Changes propagate to all 5 agents via next run, no per-agent edit needed.
- Where possible, canon doc **points to** authoritative repo files (e.g., `config/engines.py` for engine roster) rather than duplicating content — prevents drift within the canon itself.

## 4. `AGENT_PIPELINE.md` outline

Proposed section structure (~5 KB target):

1. **Roster & roles** — 1-liner per agent.
2. **Workflows** — TIPO 1 (spec review), TIPO 2 (code review, with ITERATE loop), AUDIT (ORACLE 6-block), CURATION (on-demand).
3. **Protected files** — canonical list with rationale; flagged as snapshot sourced from CLAUDE.md §4.
4. **Engine roster** — points to `config/engines.py` as source of truth; lists current stage groups (LIVE_READY, BOOTSTRAP, RESEARCH, QUARANTINED, EXPERIMENTAL).
5. **Directory & naming conventions** — specs, reviews, audits, session logs, branches, worktrees.
6. **Engine implementation pattern** — Python 3.11, core/ reuse rule, `config/engines.py` registration, test conventions, stage progression.
7. **Backtest & validation** — points to `docs/methodology/anti_overfit_protocol.md` as source.
8. **DB & persistence** — `core/db.py`, `core/db_live_runs.py`, `core/run_manager.py`, `core/versioned_state.py`; agents go through these functions, not direct writes.
9. **Spec template** — sections 1-9 for strategy specs (edge thesis → falsifiability).
10. **Closure workflow** — final comment, `PATCH /api/issues/{id} {"status":"done"}`, session log, daily log update.
11. **Budgets** — snapshot table; API is authoritative source.

## 5. Thin `AGENTS.md` template

```markdown
# {AGENT_NAME} — {Title}

## Identidade
[1-2 lines: role + archetype/voice if distinctive]

## Antes de cada run (obrigatório)
Ler por esta ordem:
1. C:/Users/Joao/projects/aurum.finance/CLAUDE.md
2. C:/Users/Joao/projects/aurum.finance/docs/AGENT_PIPELINE.md
3. Este ficheiro

## Scope
[2-3 bullets — what this agent does]

## Not your job
[What this agent does NOT do — prevents role creep]

## Inputs
[Ticket shape expected]

## Outputs
[Specific artifact paths; reference AGENT_PIPELINE.md §5 for conventions]

## Agent-specific rules
[ONLY rules unique to this agent; do NOT duplicate canon content]

## Stop conditions
[When to halt and ask the Board]

## Budget
${X}/month
```

**Size target**: 4/5 agents under 2 KB; ORACLE ~4 KB due to unique 6-block audit template.

**Worked example (SCRYER, 4.7 KB → ~1.3 KB)**: see Appendix A of this doc or the full draft alongside the implementation plan.

## 6. Per-agent drift fixes

### SCRYER
- Remove stale engine list.
- Fix spec path to `docs/superpowers/specs/`.
- Remove spec-format template (→ canon §9).
- Remove closure workflow (→ canon §10).
- Keep: research sources list, "2+ independent sources" rule, "never implement" mandate.

### CURATOR
- Add to protected files: `config/params.py`, `config/keys.json`, `launcher.py`.
- Remove closure workflow (→ canon §10).
- Keep: audit types taxonomy, "two implementations > one stub" policy, CURATOR → ARBITER merge flow.

### ARBITER
- Add to protected files: `config/params.py`, `config/keys.json`, `launcher.py`.
- Remove references to `backtest.py`, `multistrategy.py`, `live.py` at root (nonexistent).
- Update reference engines from "kepos/graham/ornstein" to LIVE_READY set or pointer.
- Remove closure workflow (→ canon §10).
- Keep: TIPO 1 and TIPO 2 criteria, "novelty is not a criterion" policy, SHIP/ITERATE/KILL verdict semantics.

### ARTIFEX
- Add to protected files: `config/params.py`, `config/keys.json`, `launcher.py`.
- Fix spec path.
- Update reference engines pointer.
- Rewrite integration section: remove backtest.py/multistrategy.py/launcher.py references; state that `config/engines.py` registration is the complete integration.
- Remove closure workflow (→ canon §10).
- Keep: TDD workflow, Codex anti-patterns, implementation philosophy, inter-engine dependency policy.

### ORACLE
- Fix spec paths in output template.
- Add full protected files canonical list (in inviolable rules §1-2).
- Remove closure workflow (→ canon §10).
- Keep: oracular voice, 6-block audit protocol, full output template (unique and critical).

### Files to create
1. `aurum.finance/docs/AGENT_PIPELINE.md` — new, ~5 KB.
2. (Optional) 3-5 line addition to `aurum.finance/CLAUDE.md` pointing to `docs/AGENT_PIPELINE.md` under a new "Agent Pipeline" subsection. Can be skipped — agents read both via AGENTS.md instruction anyway.

### Files to rewrite
Five AGENTS.md files at:
- `~/.paperclip/instances/default/companies/{cid}/agents/c28d2218-…/instructions/AGENTS.md` (SCRYER)
- `~/.paperclip/instances/default/companies/{cid}/agents/a424432d-…/instructions/AGENTS.md` (CURATOR)
- `~/.paperclip/instances/default/companies/{cid}/agents/246a2339-…/instructions/AGENTS.md` (ARBITER)
- `~/.paperclip/instances/default/companies/{cid}/agents/34d56cfa-…/instructions/AGENTS.md` (ARTIFEX)
- `~/.paperclip/instances/default/companies/{cid}/agents/2f790a10-…/instructions/AGENTS.md` (ORACLE)

Paperclip auto-creates backups (existing `_backup_v2_AGENTS.md`, `_backup_v3_AGENTS.md` visible), so rewrites are recoverable.

## 7. Success criteria

1. **Size**: total AGENTS.md payload across 5 agents drops from ~24 KB to ~10 KB.
2. **Zero stale strings**: grep for `AZOTH|HERMES|PROMETEU|MERCURIO|THOTH|NEWTON|DARWIN|QUANTUM` in any AGENTS.md returns empty. These are engine names that never existed in the repo (as opposed to KEPOS/ORNSTEIN/MEDALLION/DE SHAW, which exist in `.worktrees/` or as legitimate hedge-fund references in research sources — those may legitimately appear).
3. **Zero nonexistent paths**: grep for `backtest\.py|multistrategy\.py` in AGENTS.md returns empty.
4. **Protected files alignment**: all 5 AGENTS.md either list or reference the same canonical set (`core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py`, `config/keys.json`, `launcher.py`, existing `engines/*.py`).
5. **No workaround clauses needed in tickets**: the next ticket issued to any agent does not need "IGNORE X" or "do not trust AGENTS.md about Y" framing.
6. **`docs/AGENT_PIPELINE.md` exists** and contains sections 1-11 per §4 of this design.

## 8. Phase 2 preview (out of scope here)

CURATOR gains an `alignment_drift` audit type:
- Reads the 5 AGENTS.md and the canon (CLAUDE.md + AGENT_PIPELINE.md + `config/engines.py` + `docs/methodology/anti_overfit_protocol.md`).
- Reports drift: stale paths, engines cited but absent from registry, divergent protected-file lists, convention changes not propagated.
- Output: `docs/audits/repo/YYYY-MM-DD_alignment_drift_audit.md`.
- Trigger: `/schedule` weekly + manual on-demand.
- Escalation: on critical drift, CURATOR self-assigns a ticket (on `chore/align-*` branch) proposing a PR.

Phase 2 gets its own design doc after Phase 1 ships and a drift baseline has had time to form.

---

## Appendix A — SCRYER worked example

Full proposed new SCRYER `AGENTS.md` (provided separately during implementation plan; draft available in brainstorming transcript 2026-04-24).

## Appendix B — Risks

- **R1**: AGENT_PIPELINE.md becomes its own drift source. *Mitigation*: sections 3, 4, 7 explicitly point to authoritative repo files (CLAUDE.md, `config/engines.py`, `anti_overfit_protocol.md`) rather than duplicating. Only sections 5, 6, 9, 10 contain canonical content, and those are convention-level (change rarely).
- **R2**: Agents skip reading AGENT_PIPELINE.md despite instruction. *Mitigation*: each AGENTS.md starts with explicit "Ler por esta ordem" block. Can be reinforced later via a launcher-side pre-flight check (Phase 2 scope).
- **R3**: Thin AGENTS.md loses behavioral guardrails that were in the bloated version. *Mitigation*: drift-fixes list above is explicit about "Keep" vs "Remove" per agent. SCRYER example demonstrates no behavioral loss.
- **R4**: ORACLE's 6-block template is long and re-duplicating it feels wasteful. *Mitigation*: keep it in AGENTS.md — it is ORACLE-unique and not worth factoring into canon. 4 KB AGENTS.md for ORACLE is the acceptable ceiling.
