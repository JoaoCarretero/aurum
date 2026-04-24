# TWO SIGMA Status

Blocked: requires trade history from 2+ validated engines.

Unblock condition:
- `CITADEL` plus at least one other validated engine
- both producing enough trade history to feed the meta-ensemble
- preferably from paper trading or other authentic runtime data, not synthetic reconstruction

Current reason:
- `engines/prometeu.py` is a meta-ensemble reweighting layer
- standalone execution does not emit its own comparable backtest metrics
- it depends on pre-collected trades from other engines
