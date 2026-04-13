# Sacred Logic Contract

This document freezes the behavior-critical logic in the AURUM codebase.

Scope:
- Phase B structural work may reorganize infrastructure around this logic.
- Phase B must not change formulas, thresholds, filters, vetoes, sizing, exits,
  ranking, reconciliation semantics, execution order, parameter values, or
  call order in behavior-critical paths.
- If a function listed here must move, the move must be mechanical and preserve
  the exact logic body and invocation order.

## Core Principle

There are two classes of code in this repository:

1. Sacred logic
   This code directly affects whether capital is deployed, how it is sized,
   when it exits, how opportunities are ranked, or when runtime safety systems
   block or flatten exposure.

2. Support and infrastructure
   This code may be upgraded structurally as long as it does not alter the
   observable behavior of the sacred logic.

## Sacred Logic Boundaries

### 1. Signal Formation

The following functions define signal semantics and must not change:

- `core.indicators.indicators`
- `core.indicators.swing_structure`
- `core.indicators.omega`
- `core.indicators.cvd`
- `core.indicators.cvd_divergence`
- `core.indicators.volume_imbalance`
- `core.indicators.liquidation_proxy`
- `core.signals.decide_direction`
- `core.signals.score_omega`
- `core.signals.score_chop`
- `core.signals.calc_levels`
- `core.signals.calc_levels_chop`
- `core.signals.label_trade`
- `core.signals.label_trade_chop`
- `core.signals._liq_prices`

Protected behaviors:
- entry direction
- filter and veto semantics
- chop vs trend path selection
- score component construction
- level geometry
- liquidation, break-even, trailing, and same-bar exit ordering

### 2. Portfolio and Sizing

The following functions define capital deployment and must not change:

- `core.portfolio.detect_macro`
- `core.portfolio.build_corr_matrix`
- `core.portfolio.portfolio_allows`
- `core.portfolio.check_aggregate_notional`
- `core.portfolio._omega_risk_mult`
- `core.portfolio._wr`
- `core.portfolio._global_risk_mult`
- `core.portfolio.position_size`

Protected behaviors:
- macro regime classification
- correlation vetoes and soft multipliers
- aggregate notional limits
- risk fraction mapping
- drawdown scaling
- volatility scaling
- regime scaling
- sizing output

### 3. Backtest Decision Order

The following backtest path is sacred:

- `engines.backtest.scan_symbol`

Protected behaviors:
- pre-trade veto ordering
- speed/session/hour gating
- drawdown and cooldown behavior
- HMM gate semantics
- chop fallback behavior
- score thresholding
- position sizing order
- PnL realization order
- trade bookkeeping fields

### 4. Live Decision Path and Runtime Safety

The following live path is sacred:

- `engines.live.SignalEngine.check_signal`
- `engines.live.SignalEngine.build_signal_dict`
- `engines.live.LiveEngine._startup_reconcile`
- `engines.live.LiveEngine._reconciliation_loop`
- `engines.live.LiveEngine._kill_switch_trigger`

Protected behaviors:
- live signal generation and veto ordering
- live sizing semantics
- symbol rank blocking and drift penalty
- startup reconcile semantics
- reconciliation escalation semantics
- kill-switch activation semantics

### 5. Arbitrage Ranking and State Transitions

The following arbitrage path is sacred:

- `engines.arbitrage.omega_score`
- `engines.arbitrage.scan_all`
- `engines.arbitrage.Engine._open`
- `engines.arbitrage.Engine._close`
- `engines.arbitrage.Engine._kill_switch_trigger`

Protected behaviors:
- scanner ranking
- opportunity construction by type
- pair selection and gating
- sizing and hedge-break handling
- open/close execution order
- position state transitions
- PnL realization

### 6. Strategy-Specific Sacred Zones

The following strategy engines contain independent edge logic and must not
change behavior:

- `engines.mercurio.scan_mercurio`
- `engines.thoth.scan_thoth`
- `engines.newton.find_cointegrated_pairs`
- `engines.newton.calc_spread_zscore`
- `engines.newton.scan_pair`
- `engines.multistrategy.ensemble_reweight`

## Structural Work Allowed In Phase B

Allowed:
- move-only refactors around sacred logic
- extracting helpers from support code
- typed read-only config wrappers
- atomic persistence helpers
- transport wrappers that preserve request semantics
- failure policy and health-ledger infrastructure
- module splits at non-sacred seams

Not allowed:
- changing formulas or constants
- changing control flow inside sacred logic
- changing parameter defaults or values
- reordering calls in sacred decision paths
- changing result payload structure where downstream behavior depends on it
- changing live/backtest parity behavior

## Current Support-Code Upgrade Targets

Safe-upgrade candidates identified in the audit:
- run artifact persistence
- analysis export persistence
- transport/session utilities
- typed config access
- logging and failure taxonomy
- state-write atomicity
- launcher/UI organization

## Risk Notes

The following areas are structurally risky and require extra care even for
behavior-preserving work:

- `config.params` global import surface
- `core.htf` temporary mutation of module globals
- `engines.live` async/sync runtime boundary
- `engines.arbitrage` combined scanner/execution/state monolith
- recovery and restore paths based on informal JSON schemas

## Change Discipline

Any future Phase B change must answer:
- Is the touched code sacred or support?
- If sacred, is the change move-only and mechanically identical?
- If support, can the behavior change still leak into sacred runtime paths?
- What remains explicitly untouched because it is still too risky?
