#!/usr/bin/env python3
"""
DARWIN — Adaptive Strategy Evolution Engine
Simulates natural selection of trading strategies.
"""
import sys, json, logging
from pathlib import Path
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.params import *
from core.evolution import DarwinAllocator, calc_fitness
from core.fs import atomic_write
from analysis.stats import equity_stats, calc_ratios

SEP = "=" * 60
log = logging.getLogger("AQR")  # AQR (formerly DARWIN) — Adaptive allocation engine

def load_engine_trades(data_dir: str = "data") -> dict[str, list[dict]]:
    """
    Load trades from existing backtest reports.
    Returns dict: engine_name -> [trade_dicts]
    """
    engine_trades = defaultdict(list)
    data_path = Path(data_dir)

    # Scan for report JSON files
    for report_file in data_path.rglob("*.json"):
        if "reports" not in str(report_file):
            continue
        try:
            with open(report_file, "r", encoding="utf-8") as f:
                report = json.load(f)
            engine = report.get("config", {}).get("engine", "unknown")
            trades = report.get("trades", [])
            for t in trades:
                t["engine"] = engine  # ensure engine field
                engine_trades[engine].append(t)
        except Exception:
            continue

    return dict(engine_trades)


def simulate_evolution(all_trades: dict[str, list[dict]],
                       window: int = 30,
                       account: float = ACCOUNT_SIZE) -> dict:
    """
    Simulate Darwin evolution over historical trades.
    Processes trades chronologically, evaluating at each window boundary.
    """
    darwin = DarwinAllocator(engines=list(all_trades.keys()))

    # Merge all trades and sort by timestamp
    merged = []
    for eng, trades in all_trades.items():
        for t in trades:
            t["engine"] = eng
            merged.append(t)
    merged.sort(key=lambda t: str(t.get("timestamp", "")))

    # Process in windows
    current_window = defaultdict(list)
    total_trades = 0
    portfolio_equity = [account]
    engine_equity = {eng: account * darwin.allocations.get(eng, 1/len(all_trades))
                     for eng in all_trades}
    eval_points = []

    for trade in merged:
        eng = trade["engine"]
        current_window[eng].append(trade)
        total_trades += 1

        # Apply PnL to engine's allocated capital
        alloc = darwin.allocations.get(eng, 0.0)
        pnl = trade.get("pnl", 0) * alloc  # scale PnL by allocation
        engine_equity[eng] = engine_equity.get(eng, 0) + trade.get("pnl", 0) * alloc

        portfolio_pnl = sum(engine_equity.values())
        portfolio_equity.append(portfolio_pnl)

        # Evaluate at window boundaries
        window_total = sum(len(v) for v in current_window.values())
        if window_total >= window:
            allocations = darwin.evaluate(dict(current_window))

            # Re-distribute capital based on new allocations
            total_cap = sum(engine_equity.values())
            for e in engine_equity:
                engine_equity[e] = total_cap * allocations.get(e, 0.0)

            eval_points.append({
                "trade_idx": total_trades,
                "allocations": dict(allocations),
                "fitness": {e: darwin.population[e]["current_fitness"] for e in darwin.engines},
            })

            current_window = defaultdict(list)

    # Final dashboard
    dashboard = darwin.dashboard()

    # Portfolio metrics
    pnl_series = [portfolio_equity[i+1] - portfolio_equity[i]
                  for i in range(len(portfolio_equity)-1) if portfolio_equity[i+1] != portfolio_equity[i]]

    if pnl_series:
        eq, mdd, mdd_pct, ms = equity_stats(pnl_series, account)
        ratios = calc_ratios(pnl_series, account)
    else:
        eq, mdd, mdd_pct, ms = [account], 0, 0, 0
        ratios = {}

    return {
        "dashboard": dashboard,
        "portfolio_equity": portfolio_equity,
        "eval_points": eval_points,
        "final_allocations": dict(darwin.allocations),
        "generations": darwin.generation,
        "mdd_pct": mdd_pct,
        "ratios": ratios,
        "darwin": darwin,
    }


if __name__ == "__main__":
    # Setup
    print(f"\n{SEP}")
    print(f"  DARWIN — Adaptive Strategy Evolution Engine")
    print(f"  Natural selection of trading strategies")
    print(f"{SEP}\n")

    # 1. Load trades from existing reports
    print("  Loading engine trades from data/...")
    engine_trades = load_engine_trades()

    if not engine_trades:
        print("  No trades found. Run backtests first:")
        print("    python -m engines.citadel")
        print("    python -m engines.jump   # JUMP")
        print("    python -m engines.deshaw     # DE SHAW")
        sys.exit(1)

    for eng, trades in engine_trades.items():
        print(f"    {eng}: {len(trades)} trades loaded")

    # 2. Simulate evolution
    print(f"\n  Simulating evolution over {sum(len(t) for t in engine_trades.values())} total trades...")
    result = simulate_evolution(engine_trades)

    # 3. Print dashboard
    print(result["dashboard"])

    # 4. Print portfolio metrics
    print(f"\n  PORTFOLIO METRICS (Darwin-Managed)")
    print(f"  {'─' * 40}")
    ratios = result["ratios"]
    print(f"  Generations:     {result['generations']}")
    print(f"  MaxDD:           {result['mdd_pct']:.2f}%")
    if ratios:
        print(f"  Sharpe:          {ratios.get('sharpe', 'N/A')}")
        print(f"  Sortino:         {ratios.get('sortino', 'N/A')}")
        print(f"  Return:          {ratios.get('ret', 'N/A')}%")

    # 5. Final allocations
    print(f"\n  FINAL CAPITAL ALLOCATION:")
    for eng, alloc in sorted(result["final_allocations"].items(), key=lambda x: -x[1]):
        print(f"    {eng:<12} {alloc*100:>6.1f}%  {'█' * int(alloc * 40)}")

    # 6. Save report
    from config.paths import DATA_DIR
    report_dir = DATA_DIR / "aqr"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"darwin_report_{datetime.now().strftime('%Y-%m-%d_%H%M')}.json"
    atomic_write(report_path, json.dumps({
        "timestamp": datetime.now().isoformat(),
        "generations": result["generations"],
        "final_allocations": result["final_allocations"],
        "eval_points": result["eval_points"],
        "ratios": result["ratios"],
        "mdd_pct": result["mdd_pct"],
    }, indent=2, default=str))
    print(f"\n  Report saved: {report_path}")
    print(f"\n{SEP}\n")
