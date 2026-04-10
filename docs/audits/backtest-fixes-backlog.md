# Backtest Fixes Backlog

**Generated:** 2026-04-10
**Source:** `docs/audits/backtest-physics-core-2026-04-10.md`
**Scope:** core engine only — `engines/backtest.py`, `core/signals.py`, `core/indicators.py`, `core/portfolio.py`, `core/htf.py`.

This backlog lists only items with status `⚠️ SMELL` or `✗ FAIL` from the audit above. Items are ordered by severity. **No fixes have been applied yet** — this document is the input for a future fixes-only implementation plan.

The good news up front: **no critical bugs.** The core engine is causally sound (no look-ahead), applies fees / slippage / funding correctly, and enforces stop/target geometry. See the audit doc for the 9 PASS checks.

---

## Totals

| Severity | Count |
|----------|-------|
| CRÍTICO  | 0     |
| ALTO     | 0     |
| MÉDIO    | 2     |
| BAIXO    | 0     |
| INFO     | 0     |
| **Total non-PASS** | **2** |

Plus 1 check marked `n/a` (L12 — survivorship bias, delegated to the caller that constructs `BASKETS`, outside the core).

---

## MÉDIO

### 1. L6 — Aggregate notional cap missing

**Location:** `core/portfolio.py:38-71` (`portfolio_allows`), `core/portfolio.py:101-141` (`position_size`), caller at `engines/backtest.py:~250-270`.

**Problem:**
Per-position sizing is safe — risk is bounded to a small fraction of `account` per trade. But there is no aggregate cap: the sum of notionals across currently open positions is never compared against `account × LEVERAGE`. Two or more concurrent trades can each be sized off the full account, and the combined leverage can exceed the intended ceiling.

**In practice:** unlikely to misreport badly at current parameters (risk per trade is ~1-2% of account, and `MAX_OPEN_POSITIONS` caps the count). But with tight stops, a high Omega score inflating the Kelly multiplier, and several symbols firing in the same bar window, combined notional could pass `account × LEVERAGE` and the backtest would happily allocate it — reporting equity curves that a real exchange margin system would have refused.

**What this does NOT do:** it does not insert phantom PnL or create look-ahead. It reports reachable-but-unsafe allocations.

**Recommended fix:**
In `portfolio_allows` (or directly in `scan_symbol` before calling `position_size`), compute
```python
open_notional = sum(p["size"] * p["entry"] for p in open_pos)
```
and reject (or scale down) any new entry that would push `open_notional + new_size * new_entry` above `account * LEVERAGE`. The cap should probably use a configurable `MAX_AGGREGATE_LEVERAGE` constant, defaulting to `LEVERAGE`.

**Estimated effort:** 1 small PR. 20-40 lines changed, plus a regression test that simulates 5 concurrent signals and asserts the cap.

**Severity:** MÉDIO. Not a correctness bug in the physics sense — PnL math is right — but it lets the backtest model a reality that real margin systems prohibit.

---

### 2. L7 — Liquidation simulation is a post-hoc clamp, not path-dependent

**Location:** `engines/backtest.py:292-295`.

**Problem:**
Current code:
```python
if LEVERAGE > 1.0 and abs(pnl) > account * 0.9 and pnl < 0:
    pnl = -round(account * 0.95, 2)
account = max(account + pnl, 0.0)
```

This runs AFTER `label_trade` has already simulated the full trade to its stop/target. Consequences:

1. A trade whose adverse excursion briefly breached liquidation mid-hold but recovered to a normal stop never triggers this branch. The final `pnl` doesn't cross the 90% threshold, so the code silently reports the recovered outcome — a real exchange would have closed the position at the liquidation price and delivered a much worse fill.
2. The `0.9` / `0.95` constants are hand-tuned and unrelated to the actual maintenance margin ratio that a given `LEVERAGE` would imply. At `LEVERAGE=10`, the real liquidation price is ~10% adverse, but here the trigger fires on the **net** loss including leverage, which is structurally different from the exchange's check.
3. `max(account + pnl, 0.0)` does prevent negative equity — that part is a correct floor.

**When this matters:**
Inert for `LEVERAGE` in the 1–3x range (the 90% threshold is never reached in practice).
Unreliable for `LEVERAGE > ~5x` on single-trade worst cases — the backtest will show trades surviving that real exchanges would have closed early, at a worse price.

**Recommended fix:**
Move liquidation inside `label_trade` (both in `core/signals.py` and its CHOP variant). Compute:
```python
maintenance_margin_ratio = 0.005  # exchange-specific, for futures ~0.5%
if direction == "BULLISH":
    liq_price = entry * (1 - 1/LEVERAGE + maintenance_margin_ratio)
else:
    liq_price = entry * (1 + 1/LEVERAGE - maintenance_margin_ratio)
```
Then in the per-bar exit scan, check `low <= liq_price` (long) or `high >= liq_price` (short) BEFORE checking stop/target, and if hit, return immediately with `pnl = -account_allocated`.

Remove the post-hoc clamp once this is in place.

**Estimated effort:** 1 medium PR. `label_trade` and `label_trade_chop` each gain ~15 lines. Needs a regression test that injects a synthetic bar with a huge wick and confirms liquidation triggers.

**Severity:** MÉDIO. At current typical leverage, this is effectively inert. It becomes material if the user increases leverage for stress tests — exactly when liquidation modeling matters most.

---

## Non-issues (explicitly cleared)

The audit also flagged a stylistic smell that is NOT on this backlog because it has no functional impact:

- `core/indicators.py:51` — `vol_escalation = hot & calm.shift(REGIME_TRANS_WINDOW).fillna(True)`. The `fillna(True)` would make `regime_transition` evaluate True on the earliest warm-up bars. But (a) `regime_transition` only scales size via `REGIME_TRANS_SIZE_MULT` — it does not emit signals; (b) the scan loop starts at `min_idx = max(200, W_NORM, PIVOT_N*3) + 5`, which is well past the warm-up region. No practical effect. Optional cleanup: use `fillna(False)` for aesthetic reasons.

Other observations in the audit (leverage scaling of fees/funding is correct; `label_trade` resolves stop-before-target pessimistically; indicators are pure dataframe transforms) are noted as positive design choices, not defects.

---

## Out of scope for this backlog

- **Per-strategy audits (CITADEL, JUMP, BRIDGEWATER, DE SHAW, MILLENNIUM, TWO SIGMA, JANE STREET)** — the full-scope plan (`docs/superpowers/plans/2026-04-10-backtest-audit-and-technical-briefing.md`) describes how to audit each of the 7 strategies individually. This session only ran the shared-core audit.
- **Symbol universe / survivorship (L12)** — delegated to `config/params.py` and `BASKETS` construction, outside the core files.
- **Funding correctness at 8h boundary level** — the audit verified the linear integration formula but could not run a synthetic dataset to rule out off-by-one errors for unusual `INTERVAL` values. Flag for future.
