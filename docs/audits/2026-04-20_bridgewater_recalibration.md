# BRIDGEWATER Recalibration Audit

Date: 2026-04-20
Engine: `bridgewater`
Status: In Progress

## Summary

- Best current disciplined config:
  - `--preset robust`
  - `robust` now defaults to `BEAR,CHOP`, so the best path no longer depends on an extra operator flag
  - reproduced historical-equivalent 30d result: `170 trades`, `ROI +7.67%`, `Sharpe 7.848`, `MaxDD 3.19%`
- Channel verdict:
  - under the same `robust + BEAR,CHOP` gates, `funding+LS` wins `3/4` cuts in the rolling compare battery
  - the OI path only wins when `oi_zero_pct` stays low (`20.00%`); it loses every cut where OI zeros drift to roughly `40%+`
  - OI can participate in profitable windows, but it is not the stronger default path
- OOS verdict:
  - still bounded to recent history only
  - historical reproducibility is now fixed enough to test valid 30d cuts inside the covered window
  - basket cap remains `46.25` valid scan days at `1h`
- Current decision:
  - `keep_quarantine`
  - preserve `robust + funding+LS` as the best research path
  - keep OI isolated behind `preset=oi_research` instead of treating it as a mainline runtime

## Fixed Hypothesis

Cross-sectional contrarian sentiment still has usable edge when:
- the path is amputated to `funding + LS`
- entries are restricted to `BEAR,CHOP` by default in `robust`
- direction is strict

Open interest should be treated as optional evidence, not a required pillar, until it proves additive value under matched gates.

Historical path fixes required to make that comparison honest:
- OI/LS OOS requests must use cache-backed uncapped limits rather than the API cap of `500`
- partial cached OI/LS history should be accepted and judged later by coverage gating
- funding history with `end_time_ms` must use `startTime + endTime`

## Grid

- Current useful slice of the round-1 grid:
  - `robust / all regimes`
  - `robust / BEAR,CHOP`
  - `robust / BEAR,CHOP + cooldown`
  - `robust / BEAR,CHOP + symbol_health`
- Channel ablation battery:
  - `funding+oi+ls`
  - `funding+ls`
  - both run under `robust + BEAR,CHOP` gates for a fair comparison

## Results

### Train

Recent 30d exploratory window:
- `robust / all regimes`
  - run: `2026-04-20_155254_114064`
  - `182 trades`, `ROI +6.91%`, `Sharpe 7.117`, `MaxDD 3.0%`
- `robust / BEAR,CHOP`
  - run: `2026-04-20_155441_420834`
  - `158 trades`, `ROI +6.94%`, `Sharpe 7.353`, `MaxDD 3.0%`
- `robust / BEAR,CHOP + symbol_health`
  - run: `2026-04-20_160611_581332`
  - `159 trades`, `ROI +5.79%`, `Sharpe 6.886`, `MaxDD 3.4%`
- `robust / BEAR,CHOP + cooldown 4`
  - earlier run collapsed to negative performance
  - not worth promoting further
- historical-equivalent check
  - run: `2026-04-20_162754_969284`
  - `170 trades`, `ROI +7.67%`, `Sharpe 7.848`, `MaxDD 3.19%`
  - confirms the recent path reproduces after historical funding/cache fixes

### OOS Bear

Blocked for now.

Reason:
- valid OI/LS basket coverage is only continuous from roughly `2026-03-17/18` onward
- older windows such as `2023-01-01` are still out of scope
- with `min_fraction=0.70` and `MAX_HOLD=200`, the current basket blocker is `ETHUSDT`, leaving only `46.25` valid scan days

### OOS Chop

Blocked for now for the same continuity reason.

### OOS Recent

Validated only inside the currently available sentiment history.

Channel ablation under `robust + BEAR,CHOP`, end aligned to the latest covered window:
- run: `2026-04-20_162754_969284` with compare battery counterpart
- `funding+oi+ls`
  - `157 trades`, `ROI +0.79%`, `Sharpe 1.149`, `MaxDD 5.17%`
- `funding+ls`
  - `170 trades`, `ROI +7.67%`, `Sharpe 7.848`, `MaxDD 3.19%`

Earlier 30d cut ending `2026-04-10`:
- `funding+oi+ls`
  - `69 trades`, `ROI +4.47%`, `Sharpe 9.070`, `MaxDD 1.86%`
- `funding+ls`
  - `60 trades`, `ROI +6.16%`, `Sharpe 10.425`, `MaxDD 1.89%`

Rolling compare battery over 4 recent valid cuts:
- run: `2026-04-20_165132`
- `2026-04-05T19:00:00`
  - winner: `funding+oi+ls`
  - OI+LS `ROI +5.76%`, `Sharpe 13.937`, `oi_zero_pct 20.00%`
  - LS `ROI +3.74%`, `Sharpe 9.781`
- `2026-04-10T19:00:00`
  - winner: `funding+ls`
  - OI+LS `ROI +4.31%`, `Sharpe 8.345`, `oi_zero_pct 40.00%`
  - LS `ROI +6.78%`, `Sharpe 10.749`
- `2026-04-15T19:00:00`
  - winner: `funding+ls`
  - OI+LS `ROI +1.97%`, `Sharpe 2.933`, `oi_zero_pct 46.85%`
  - LS `ROI +8.05%`, `Sharpe 8.383`
- `2026-04-20T19:00:00`
  - winner: `funding+ls`
  - OI+LS `ROI +0.79%`, `Sharpe 1.149`, `oi_zero_pct 42.68%`
  - LS `ROI +7.67%`, `Sharpe 7.848`

Conclusion from this step:
- OI can still produce profitable slices
- but after fixing the historical path, `funding+LS` wins on the majority of tested recent cuts and dominates the more recent half of the window
- the degradation lines up with OI data quality drift rather than with a stronger OI hypothesis; once `oi_zero_pct` reaches ~`40%`, the OI path is no longer the right default

Regime filter battery over the same 4 valid cuts:
- run: `2026-04-20_170626`
- `BEAR,CHOP` wins `3/4`, ties `1/4`, loses `0/4` against `ALL`
- `2026-04-05T19:00:00`
  - tie: both `Sharpe 4.026`, `ROI +0.83%`, `4 trades`
- `2026-04-10T19:00:00`
  - `ALL`: `104 trades`, `ROI +5.99%`, `Sharpe 8.683`
  - `BEAR,CHOP`: `76 trades`, `ROI +6.78%`, `Sharpe 10.749`
- `2026-04-15T19:00:00`
  - `ALL`: `195 trades`, `ROI +6.95%`, `Sharpe 6.956`
  - `BEAR,CHOP`: `163 trades`, `ROI +8.05%`, `Sharpe 8.383`
- `2026-04-20T19:00:00`
  - `ALL`: `194 trades`, `ROI +7.64%`, `Sharpe 7.610`
  - `BEAR,CHOP`: `170 trades`, `ROI +7.67%`, `Sharpe 7.848`

Decision from this step:
- `BEAR,CHOP` is now promoted into the `robust` preset default
- `ALL` remains reachable only by explicit override if needed for research

Dedicated OI research preset check:
- run: `2026-04-20_170145_348797`
- command: `--preset oi_research --end 2026-04-20T19:00:00`
- result: `157 trades`, `ROI +0.79%`, `Sharpe 1.149`, `MaxDD 5.17%`
- reading:
  - the stricter `min_coverage_fraction=0.85` cleanly separates this from the main path
  - but it does not rescue OI on the latest covered cut, so OI remains research-only

## Interpretation

The useful improvement was not just tuning; it was fixing the historical path so the engine could actually be judged.

- `BEAR,CHOP` is a cleaner runtime restriction than all-regimes
- `symbol_health` does not improve the current path
- `post_trade_cooldown` hurts materially
- after historical reproducibility fixes, OI still loses to `funding+LS` under matched gates in most recent cuts

That leaves the present best research configuration close to the simplest viable form:
- `robust`
- implicit `BEAR,CHOP`
- no OI by default
- no extra cooldown
- no symbol-health overlay

Research branch:
- `oi_research`
- `BEAR,CHOP`
- OI enabled
- `min_coverage_fraction=0.85`
- not promotable unless future covered cuts show additive value again

Operationally, the research constraint is explicit:
- use [bridgewater_sentiment_window_audit.py](C:/Users/Joao/OneDrive/aurum.finance/tools/audits/bridgewater_sentiment_window_audit.py) before selecting any OOS window
- do not schedule basket windows longer than ~`46` scan days unless historical OI/LS continuity is extended
- keep OI as a research-only branch until the target window can hold `oi_zero_pct` materially below the recent degraded band (~`40%+`)

## Decision

- `keep_quarantine`
- rationale:
  - there is reproducible recent edge on the disciplined amputated path
  - there is not yet enough trustworthy historical sentiment coverage to claim durable long-horizon OOS robustness
