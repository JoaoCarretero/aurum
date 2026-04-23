"""AURUM Analysis — backtesting analytics suite."""
from analysis.stats import equity_stats, calc_ratios, conditional_backtest
from analysis.montecarlo import monte_carlo
from analysis.walkforward import walk_forward, walk_forward_by_regime, print_wf_by_regime
from analysis.robustness import symbol_robustness, print_symbol_robustness
