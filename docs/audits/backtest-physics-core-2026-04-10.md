# Backtest Physics Audit — Core Engine

**Date:** 2026-04-10
**Scope:** `engines/backtest.py`, `core/signals.py`, `core/indicators.py` (shared core used by all 7 strategies)
**Checklist:** L1-L12 (12-point physical-law invariants)
**Auditor:** automated pass via Claude Code subagent
**Method:** full file reads, no code execution, no modifications

## Executive summary

| L#  | Invariant                          | Status     | Severity (if not PASS) |
|-----|-------------------------------------|------------|------------------------|
| L1  | No look-ahead bias                  | PASS       | —                      |
| L2  | Execution delay (signal -> fill)    | PASS       | —                      |
| L3  | Entry + exit fees applied           | PASS       | —                      |
| L4  | Slippage applied                    | PASS       | —                      |
| L5  | Funding rate contabilized           | PASS       | —                      |
| L6  | Position sizing respects capital    | SMELL      | medium                 |
| L7  | Liquidation simulated               | SMELL      | medium                 |
| L8  | Indicators are causal               | PASS       | —                      |
| L9  | NaN warm-up doesn't fire trades     | PASS       | —                      |
| L10 | Timeframe alignment                 | PASS       | —                      |
| L11 | Stop/target geometry                | PASS       | —                      |
| L12 | Survivorship bias in symbols        | n/a        | —                      |

**Totals:** 9 PASS / 2 SMELL / 0 FAIL / 1 n/a.

**Critical findings (if any):** none. No clear FAIL items — the core obeys causality and applies costs correctly. Two SMELLs (aggregate notional cap missing, and a hand-wavy liquidation rule) deserve a human review but do not fabricate fake PnL.

---

## L1 — No look-ahead bias: PASS

The scan loop reads decision features from precomputed numpy arrays indexed strictly at `idx` (`engines/backtest.py:139-154`). The row dict assembled on every bar draws exclusively from `[idx]` slots — `_rsi[idx]`, `_atr[idx]`, `_str[idx]`, etc. — so the signal decision (`decide_direction`, `score_omega`, `score_chop`) cannot see data at `idx+k` for any `k >= 1`.

The only forward read in the whole decision flow is the entry price lookup `raw = df["open"].iloc[idx+1]` inside `calc_levels` / `calc_levels_chop` (`core/signals.py:154, 179`). This is **intentional** and required by L2 — the fill happens on the next bar's open, which is the correct causal fill.

`label_trade` and `label_trade_chop` iterate over `[entry_idx, end)` with `entry_idx = idx + 1` (`engines/backtest.py:261-265`), so the exit simulation only looks at bars strictly after the signal bar.

I searched both files for `shift(-`, `iloc[i+`, `iloc[idx+`, and `fillna(True)` patterns that could retroactively mark signals. The only hit was `calm.shift(REGIME_TRANS_WINDOW).fillna(True)` at `core/indicators.py:51`, which is a **past-tense** shift (default direction is forward in time, so `shift(N)` reads from N bars earlier). The `fillna(True)` only fills the warm-up prefix of the series and cannot retroactively alter a later bar's value. No look-ahead.

## L2 — Execution delay (signal -> fill): PASS

Evidence in `core/signals.py:154` (CHOP) and `core/signals.py:179` (trend):
```python
raw = df["open"].iloc[idx+1]
```
The entry price is explicitly `open[idx+1]`, and the downstream call to `label_trade(df, idx+1, ...)` at `engines/backtest.py:261-265` passes `entry_idx = idx + 1`, so exit scanning begins at the same bar. Trade record confirms it: `"entry_idx": idx+1` (`engines/backtest.py:316`). The one-bar execution delay is consistent across both the signal path and the simulation path.

## L3 — Entry + exit fees applied: PASS

Both legs are charged at `engines/backtest.py:282-290`:

```python
if direction == "BULLISH":
    entry_cost = entry * (1 + COMMISSION)              # entry fee
    ep_net     = ep * (1 - COMMISSION - slip_exit)     # exit fee + slip
    ...
    pnl        = size * (ep_net - entry_cost) + funding
else:
    entry_cost = entry * (1 - COMMISSION)
    ep_net     = ep * (1 + COMMISSION + slip_exit)
    ...
    pnl        = size * (entry_cost - ep_net) + funding
```
`COMMISSION` is subtracted on both entry and exit for both directions. The sign convention is correct: long buys higher (entry cost up), sells lower (exit proceeds down); short sells lower, buys back higher.

Note: entry-side slippage is applied inside `calc_levels*` via `entry = raw * (1 ± SLIPPAGE + SPREAD)` (`core/signals.py:158, 165, 182, 188`). So slippage is on both sides too — see L4.

## L4 — Slippage applied: PASS

Entry slippage is baked into the fill price in `core/signals.py:155-165` and `:180-188`:
```python
slip = SLIPPAGE + SPREAD
if direction == "BULLISH":
    entry = raw * (1 + slip)
else:
    entry = raw * (1 - slip)
```
Exit slippage is applied symmetrically in `engines/backtest.py:279-288`:
```python
slip_exit = SLIPPAGE + SPREAD
...
ep_net = ep * (1 - COMMISSION - slip_exit)   # long sell
ep_net = ep * (1 + COMMISSION + slip_exit)   # short buy-back
```
Neither leg uses pure `open`/`close`. Slippage magnitude comes from config (`SLIPPAGE`, `SPREAD`) — not audited here.

## L5 — Funding rate contabilized: PASS

`engines/backtest.py:280-289`:
```python
_funding_periods_per_8h = 8 * 60 / _TF_MINUTES.get(INTERVAL, 15)
if direction == "BULLISH":
    funding = -(size * entry * FUNDING_PER_8H * duration / _funding_periods_per_8h)
else:
    funding = +(size * entry * FUNDING_PER_8H * duration / _funding_periods_per_8h)
```
The division converts bar-count `duration` into 8h-periods (for 15m, `_funding_periods_per_8h = 32`, so 32 bars = 1 funding period). Notional × rate_per_8h × periods = total funding cost. Sign convention is the textbook perp rule: long pays when funding is positive (`-` on the long PnL), short receives (`+` on the short PnL). The funding is added into `pnl` before leverage scaling (line 291), which is correct because funding scales with position notional, not equity.

Minor observation (not a defect): the model pays continuously as a linear fraction of duration rather than only crossing discrete 8h UTC boundaries. This smooths out the cost and slightly underestimates realized variance at funding settlements, but the expected total cost is identical.

## L6 — Position sizing respects capital: SMELL (medium)

Per-position risk is handled correctly in `core/portfolio.py:101-141`: risk is a fraction of `account`, sized to `dist = |entry - stop|`, bounded by `BASE_RISK*0.25` and `MAX_RISK*1.25`. So no single trade blows the account.

The gap is the **aggregate** cap. `portfolio_allows` (`core/portfolio.py:38-71`) only caps the **number** of concurrent positions (`MAX_OPEN_POSITIONS`) and correlation. It does **not** sum the notionals of currently open positions and compare against `account * max_leverage`. The `position_size` function at `core/portfolio.py:101` receives `account` alone — not `account - notional_in_use` — so two concurrent positions can each be sized off the full account, and the combined leverage can exceed the intended cap.

In practice the risk-fraction formula (roughly 1-2% account per trade) keeps aggregate notional far below danger even at `MAX_OPEN_POSITIONS`, so this is unlikely to produce obviously wrong backtests. But with tight stops and a high Omega score producing a large `kelly` multiplier, several trades firing in the same bar window could push combined notional over `account * LEVERAGE`. The backtest would happily allocate it and the reported PnL would implicitly assume infinite margin.

Recommended fix: inside `scan_symbol` or `portfolio_allows`, track `sum(size[i] * entry[i])` across `open_pos` and refuse entries that would exceed `account * LEVERAGE` (or scale down `size` to fit). Today that aggregate is never computed.

Severity: medium. It does not silently insert phantom PnL, but it does let the backtest report equity curves that a real exchange margin system would have refused.

## L7 — Liquidation simulated: SMELL (medium)

Present but primitive. `engines/backtest.py:292-295`:
```python
if LEVERAGE > 1.0 and abs(pnl) > account * 0.9 and pnl < 0:
    pnl = -round(account * 0.95, 2)
account = max(account + pnl, 0.0)
```
This is a post-hoc cap: if a computed loss exceeds 90% of account equity, clamp it to 95% of account. It does **not** simulate liquidation at the moment the mark price crosses the maintenance margin during the trade — the stop/target logic in `label_trade` runs to completion first, and only then is the (possibly enormous) loss rounded down. Consequences:

1. A trade whose adverse excursion briefly breached liquidation mid-hold but then recovered to a normal stop would never trigger this branch (the final `pnl` never crosses the threshold).
2. The 0.9 / 0.95 constants are hand-tuned and unrelated to the actual maintenance margin that a given `LEVERAGE` would imply. At e.g. `LEVERAGE=10`, a 10% adverse move fully liquidates in reality, but here the losses are scaled by `LEVERAGE` (line 291) **before** the check, so the trigger fires correctly in magnitude but is decoupled from the geometric path.
3. `max(account + pnl, 0.0)` does prevent negative equity, which is a correct floor.

Severity: medium. For low `LEVERAGE` (1-3x) this is effectively inert and harmless. For high `LEVERAGE` settings it masks the path-dependent liquidation that would actually have closed the position earlier and at a worse price. Backtests with leverage > ~5x should not be trusted on single-trade worst cases from this engine.

Recommended fix: inside `label_trade`, compute a liquidation price from entry + maintenance_margin_ratio and short-circuit the loop when `low/high` crosses it, returning `-account_allocated_to_trade` directly.

## L8 — Indicators are causal: PASS

`core/indicators.py` was read top-to-bottom. Every operation is backward-looking:

- EMAs via `ewm(..., adjust=False)` (line 9) — streaming, causal.
- RSI via `ewm` on deltas (lines 10-13) — causal.
- ATR via `ewm` over `max(high-low, |high-prev_close|, |low-prev_close|)` (lines 14-16) — `.shift()` with no negative argument = past-only.
- Rolling stats (`bb_mid`, `bb_std`, `vol_pct_rank`, `rsi_score`, CVD rolls) all use `rolling(...).mean/std/rank/max/min` without a `center=True` flag, so they are right-anchored.
- `pct_change(SLOPE_N)` (lines 21-22) reads `close[t] vs close[t-N]` — causal.
- `sign_past = np.sign(s200.shift(REGIME_TRANS_WINDOW))` (line 46) — positive shift, past-only.
- `swing_structure` at `core/indicators.py:61-83` uses `h[max(0,i-PIVOT_N):i+1]` windows — the upper bound is `i+1` (exclusive `i+2`), so the pivot-N check looks at bars `[i-PIVOT_N .. i]` only. No forward peek.

One stylistic smell at `core/indicators.py:51`:
```python
vol_escalation = hot & calm.shift(REGIME_TRANS_WINDOW).fillna(True)
```
The `fillna(True)` fills the leading warm-up rows where the shifted series is NaN. This could make `regime_transition` evaluate True on the earliest bars of the sample. However, (a) `regime_transition` only scales size via `REGIME_TRANS_SIZE_MULT`, it does not emit signals; (b) the scan loop starts at `min_idx = max(200, W_NORM, PIVOT_N*3) + 5` (`engines/backtest.py:103`) which is well past the warm-up region for the usual config. No look-ahead, no practical effect, but the `fillna(True)` is aesthetically loud — I'd prefer `fillna(False)`.

No `shift(-k)` anywhere in the file.

## L9 — NaN warm-up doesn't fire trades: PASS

`engines/backtest.py:103`:
```python
min_idx = max(200, W_NORM, PIVOT_N*3) + 5
```
`200` covers `ema200`, `W_NORM` covers the volume / flow percentile ranks, `PIVOT_N*3` covers the swing structure sliding window, `+5` is a safety cushion. The for-loop at line 139 is `for idx in range(min_idx, len(df)-MAX_HOLD-2):` — both bounds are defended, and the upper bound `len(df)-MAX_HOLD-2` guarantees enough forward bars remain for `label_trade` to run its full `MAX_HOLD` horizon without overflowing. The `-2` additionally leaves room for `open[idx+1]` fills.

Additional warm-up defense: `calc_levels` returns `None` if `atr` is NaN or zero at `idx` (`core/signals.py:177-178`), and `decide_direction` bails on zero strength (`core/signals.py:9-10`), so even if a NaN leaked into the entry window it would short-circuit before sizing.

## L10 — Timeframe alignment: PASS

MTF alignment lives in `core/htf.py` (read for this check since it's imported directly into `scan_symbol`). The merge logic at `core/htf.py:58-80`:

```python
htf["time"] = (htf["time"] + pd.Timedelta(minutes=mins)).astype("datetime64[ms]")
...
df_ltf = pd.merge_asof(
    df_ltf.sort_values("time").reset_index(drop=True),
    htf.sort_values("time").reset_index(drop=True),
    on="time", direction="backward")
```

This is the correct pattern. The HTF timestamp is the **open** time of the HTF candle; the code shifts it forward by `mins` (the full HTF period), making the timestamp the **close** time = the first moment that HTF candle's state is knowable. Then `merge_asof(direction="backward")` attaches the latest *already-closed* HTF row to each LTF bar. There is no `reindex(..., method="ffill")` that could leak a not-yet-closed HTF value onto earlier LTF bars.

The `fillna` calls at lines 76-79 only fill the prefix where the LTF series starts before the first HTF candle has closed — they default to NEUTRAL / 0.0 / CHOP, which are inert in `decide_direction`. No leakage.

## L11 — Stop/target geometry: PASS

Both `calc_levels` and `calc_levels_chop` explicitly assert the geometry after computing levels (`core/signals.py:171-172, 196-197`):

```python
if direction == "BULLISH" and (stop >= entry or target <= entry): return None
if direction == "BEARISH" and (stop <= entry or target >= entry): return None
```

This hard-rejects any accidental sign flip before the trade can be logged. The construction itself is also correct by inspection:

- BULLISH: `stop = min(..., entry*(1-MIN_STOP_PCT))` so stop < entry; `target = entry + abs(entry-stop)*TARGET_RR` so target > entry.
- BEARISH: `stop = max(..., entry*(1+MIN_STOP_PCT))` so stop > entry; `target = entry - abs(stop-entry)*TARGET_RR` so target < entry.

The CHOP variant uses `target = bb_mid` directly and relies on the same sanity gate to reject cases where `bb_mid` is on the wrong side of `entry`.

## L12 — Survivorship bias in symbols: n/a

The core files under audit (`engines/backtest.py`, `core/signals.py`, `core/indicators.py`) receive the symbol universe from `SYMBOLS` / `BASKETS` at runtime (`engines/backtest.py:496-497`). The universe origin is upstream of this audit — it comes from `config/params.py` and/or `BASKETS`, which are explicitly out of scope per the instructions. The core itself takes whatever list it is handed and scans each symbol independently; it does not filter by "currently listed on exchange", so the bias question belongs to the caller that constructs `BASKETS`. Marked n/a with this caveat.

---

## Observations and notes

- Very clean separation between indicators (`core/indicators.py`) and signals (`core/signals.py`). Indicators are pure dataframe transforms, signals are pure row-level decisions — easy to audit.
- `engines/backtest.py:107-126` pre-extracts numpy arrays from the dataframe before the scan loop, which is the right pattern for speed. It's also easier to audit (no risk of `iloc` magic tricks inside hot paths).
- `label_trade` resolves intra-bar ambiguity by checking stop before target (`core/signals.py:215-241`). This is pessimistic (good for an honest backtest) but it means a single bar that ranges across both levels is always counted as a LOSS for a BULLISH trade. Worth noting but not a physics violation.
- The regime-transition flag and dd_velocity braking (`engines/backtest.py:192-199`) are nice touches but increase the chance that SMELL-grade warm-up noise at the start of the sample wiggles the first few trades. Mitigated by `min_idx = max(200, W_NORM, PIVOT_N*3) + 5`.
- Leverage scaling at `engines/backtest.py:291` multiplies **net** PnL by `LEVERAGE`. This is correct for a notional-scaled model but means fees and funding are also scaled — which matches reality (real leveraged positions pay fees on notional, not margin). Good.

## Files read

- `engines/backtest.py` — 901 lines, read completely (lines 1-300 in full detail, 300-600 and 600-901 skimmed for structure; the PnL / liquidation / sizing logic at 270-310 and the scan loop bounds at 90-175 are the load-bearing sections and were read in full).
- `core/signals.py` — 261 lines, read completely.
- `core/indicators.py` — 176 lines, read completely.
- `core/htf.py` — lines 1-120, read to verify L10 (`merge_asof` alignment).
- `core/portfolio.py` — lines 30-141, read to verify L6 (`position_size`, `portfolio_allows`).

## Limitations

- **Funding correctness at the 8h boundary level is not verified.** The audit confirms the linear integration over duration produces the correct expected cost, but a synthetic dataset with known funding payments at exact 8h boundaries would be needed to rule out off-by-one errors in the conversion `duration / _funding_periods_per_8h` for unusual `INTERVAL` values (e.g. 3m, 30m) that don't divide 8h cleanly.
- **L6 aggregate-cap severity is inferred, not measured.** Without running a backtest with extreme Kelly / score conditions, I cannot confirm how often combined open notional actually exceeds `account * LEVERAGE`. It may be never in practice for current parameters.
- **L7 liquidation pathing is not verified against real exchange maintenance margin rules.** The 0.9 / 0.95 constants should be replaced with a model-driven liquidation price, but confirming the magnitude of the error requires a worst-case trade replay.
- **L12 is delegated upstream.** Symbol universe sourcing is out of scope for this audit.
- The audit did not execute any code. All conclusions are static-analysis grade.
