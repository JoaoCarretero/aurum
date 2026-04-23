"""Backward compatibility — redirects to new package structure."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from config.params import *
from config.params import _tf_params, _TF_MINUTES
from core import *
from analysis.stats import equity_stats, calc_ratios, conditional_backtest
from analysis.montecarlo import monte_carlo
from analysis.walkforward import walk_forward, walk_forward_by_regime, print_wf_by_regime
from analysis.robustness import symbol_robustness, print_symbol_robustness
from analysis.benchmark import (
    bear_market_analysis, year_by_year_analysis,
    print_year_by_year, print_bear_market_enhanced, print_benchmark,
)
from analysis.plots import plot_dashboard, plot_montecarlo, plot_trades
import engines.backtest as _bt
from engines.backtest import (
    scan_symbol, setup_run, print_header, print_veredito, print_chop_analysis,
    export_json, log,
)
# RUN_DIR and RUN_ID are lazy — access via engines.backtest module after setup_run()
RUN_DIR = _bt.RUN_DIR
RUN_ID  = _bt.RUN_ID
