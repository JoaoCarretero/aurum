"""MILLENNIUM — portfolio-gate grid runner.

Runs a pre-registered grid of gate configs (JUMP_MIN_SCORE_* tiers,
PORTFOLIO_MIN_WEIGHT, CHALLENGER_RATIO, cooldown multipliers) against
the operational core (CITADEL + RENAISSANCE + JUMP) and prints a
comparison table.

Pre-registration (anti-overfit): the grid list in `GRID` below must be
committed BEFORE running. No mid-flight tuning. We run all configs,
rank them by the hard metric (Sharpe stable + JUMP trade count), and
commit the winner once.

The engine scans run once per window — we cache `_collect_operational_trades`
per window across all grid rows. Reweight + gate runs per row.

Usage:
    python tools/batteries/millennium_gate_grid.py --days 180
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines import millennium as M  # noqa: E402
from engines import citadel as BT  # noqa: E402


# ─── Pre-registered grid ─────────────────────────────────────────────
#
# Each row overrides a subset of millennium globals. Field names match
# the globals in engines/millennium.py so we can monkey-patch safely.
#
# DO NOT add rows after inspecting results — that's post-hoc fishing.
# If none of A/B/C/D wins, the honest move is to archive the exercise,
# not to add E/F/G looking for a number.

@dataclass
class GateConfig:
    name: str
    note: str
    jump_min_base: float = 0.80
    jump_min_weak: float = 0.82
    jump_min_stressed: float = 0.84
    portfolio_min_weight_jump: float = 0.32
    portfolio_min_weight_renaissance: float = 0.22
    portfolio_min_weight_citadel: float = 0.18
    challenger_ratio: float = 0.92
    challenger_max_gap: float = 0.06
    regime_cooldown_bull: float = 1.0
    regime_cooldown_bear: float = 1.5
    regime_cooldown_chop: float = 2.0
    min_accepted_share_jump: float = 0.25
    min_accepted_share_renaissance: float = 0.22
    min_accepted_share_citadel: float = 0.12


GRID: list[GateConfig] = [
    GateConfig(
        name="A_baseline",
        note="current committed config",
    ),
    GateConfig(
        name="B_soften_jump",
        note="reduce JUMP score floors (WEAK/STRESSED) + lower min_weight",
        jump_min_weak=0.805,
        jump_min_stressed=0.815,
        portfolio_min_weight_jump=0.28,
        min_accepted_share_jump=0.30,
    ),
    GateConfig(
        name="C_relax_gate",
        note="looser challenger ratio + milder CHOP cooldown (keeps JUMP scores)",
        challenger_ratio=0.85,
        regime_cooldown_chop=1.5,
    ),
    GateConfig(
        name="D_liberal",
        note="combine C + B, broader entry, expect more trades",
        jump_min_base=0.79,
        jump_min_weak=0.80,
        jump_min_stressed=0.81,
        portfolio_min_weight_jump=0.25,
        challenger_ratio=0.85,
        regime_cooldown_chop=1.5,
        min_accepted_share_jump=0.35,
    ),
]


@dataclass
class GridResult:
    config: str
    note: str
    total_trades: int
    wr_pct: float
    sharpe: float
    sortino: float
    mdd_pct: float
    pnl: float
    by_engine: dict[str, dict[str, Any]] = field(default_factory=dict)


# ─── Metric helpers ──────────────────────────────────────────────────

def _sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    import statistics as stat
    mean = sum(returns) / len(returns)
    std = stat.pstdev(returns)
    if std < 1e-9:
        return 0.0
    return mean / std * (len(returns) ** 0.5)


def _sortino(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    import statistics as stat
    downs = [r for r in returns if r < 0]
    if not downs:
        return 0.0
    d_std = stat.pstdev(downs)
    if d_std < 1e-9:
        return 0.0
    mean = sum(returns) / len(returns)
    return mean / d_std * (len(returns) ** 0.5)


def _mdd_pct(returns: list[float], start_equity: float = 10000.0) -> float:
    eq = start_equity
    peak = eq
    mdd = 0.0
    for r in returns:
        eq += r
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100 if peak > 0 else 0.0
        mdd = max(mdd, dd)
    return mdd


def _summarize(reweighted_trades: list[dict]) -> dict:
    closed = [t for t in reweighted_trades if t.get("result") in ("WIN", "LOSS")
              and t.get("gate_accepted", True)]
    n = len(closed)
    if n == 0:
        return {"total": 0, "wr": 0.0, "sharpe": 0.0, "sortino": 0.0,
                "mdd": 0.0, "pnl": 0.0, "by_engine": {}}
    wins = sum(1 for t in closed if t["result"] == "WIN")
    pnls = [float(t.get("pnl", 0.0)) for t in closed]
    by_engine: dict = {}
    for t in closed:
        eng = t.get("strategy", "?")
        b = by_engine.setdefault(eng, {"n": 0, "wins": 0, "pnl": 0.0})
        b["n"] += 1
        if t["result"] == "WIN":
            b["wins"] += 1
        b["pnl"] += float(t.get("pnl", 0.0))
    for eng, b in by_engine.items():
        b["wr"] = b["wins"] / b["n"] * 100 if b["n"] > 0 else 0.0

    return {
        "total": n,
        "wr": wins / n * 100,
        "sharpe": _sharpe(pnls),
        "sortino": _sortino(pnls),
        "mdd": _mdd_pct(pnls),
        "pnl": sum(pnls),
        "by_engine": by_engine,
    }


# ─── Grid execution ──────────────────────────────────────────────────

def _apply_config(cfg: GateConfig) -> None:
    """Monkey-patch millennium globals to match cfg. Safe because the grid
    runner restores snapshot between rows."""
    M.JUMP_MIN_SCORE_BASE = cfg.jump_min_base
    M.JUMP_MIN_SCORE_WEAK = cfg.jump_min_weak
    M.JUMP_MIN_SCORE_STRESSED = cfg.jump_min_stressed
    M.PORTFOLIO_MIN_WEIGHT = {
        "JUMP":        cfg.portfolio_min_weight_jump,
        "RENAISSANCE": cfg.portfolio_min_weight_renaissance,
        "CITADEL":     cfg.portfolio_min_weight_citadel,
    }
    M.PORTFOLIO_CHALLENGER_RATIO = cfg.challenger_ratio
    M.PORTFOLIO_CHALLENGER_MAX_GAP = cfg.challenger_max_gap
    M.PORTFOLIO_REGIME_COOLDOWN_MULT = {
        "BULL": cfg.regime_cooldown_bull,
        "BEAR": cfg.regime_cooldown_bear,
        "CHOP": cfg.regime_cooldown_chop,
    }
    M.PORTFOLIO_MIN_ACCEPTED_SHARE = {
        "JUMP":        cfg.min_accepted_share_jump,
        "RENAISSANCE": cfg.min_accepted_share_renaissance,
        "CITADEL":     cfg.min_accepted_share_citadel,
    }


def _snapshot_globals() -> dict:
    return {
        "JUMP_MIN_SCORE_BASE":          M.JUMP_MIN_SCORE_BASE,
        "JUMP_MIN_SCORE_WEAK":          M.JUMP_MIN_SCORE_WEAK,
        "JUMP_MIN_SCORE_STRESSED":      M.JUMP_MIN_SCORE_STRESSED,
        "PORTFOLIO_MIN_WEIGHT":         dict(M.PORTFOLIO_MIN_WEIGHT),
        "PORTFOLIO_CHALLENGER_RATIO":   M.PORTFOLIO_CHALLENGER_RATIO,
        "PORTFOLIO_CHALLENGER_MAX_GAP": M.PORTFOLIO_CHALLENGER_MAX_GAP,
        "PORTFOLIO_REGIME_COOLDOWN_MULT": dict(M.PORTFOLIO_REGIME_COOLDOWN_MULT),
        "PORTFOLIO_MIN_ACCEPTED_SHARE": dict(M.PORTFOLIO_MIN_ACCEPTED_SHARE),
    }


def _restore_globals(snap: dict) -> None:
    for k, v in snap.items():
        setattr(M, k, v)


def run_grid(days: int) -> list[GridResult]:
    # Adjust period once.
    BT.SCAN_DAYS = days
    BT.N_CANDLES = days * 24 * 4
    BT.HTF_N_CANDLES_MAP = {"1h": days * 24 + 200, "4h": days * 6 + 100, "1d": days + 100}
    M.SCAN_DAYS = days
    M.N_CANDLES = days * 24 * 4
    M.HTF_N_CANDLES_MAP = dict(BT.HTF_N_CANDLES_MAP)

    # Setup once — run dir + logger (silenced stdout).
    M.setup_multistrategy()

    # Fetch + scan once; reweight is what varies per config.
    print(f"\n[grid] fetching and scanning operational core for {days}d "
          f"(one-shot, cached across rows)...")
    t0 = time.time()
    with contextlib.redirect_stdout(io.StringIO()):
        all_dfs, htf_stack, macro_series, corr = M._load_dados(False)
        engine_trades, all_trades = M._collect_operational_trades(
            all_dfs, htf_stack, macro_series, corr,
        )
    print(f"[grid] scan done in {time.time() - t0:.1f}s  "
          f"total raw signals: {len(all_trades)}  "
          f"per engine: { {k: len(v) for k, v in engine_trades.items()} }")

    results: list[GridResult] = []
    baseline_snap = _snapshot_globals()

    for cfg in GRID:
        _apply_config(cfg)
        print(f"\n[grid] running config {cfg.name}  —  {cfg.note}")
        t0 = time.time()
        with contextlib.redirect_stdout(io.StringIO()):
            reweighted = M.operational_core_reweight(all_trades)
        summary = _summarize(reweighted)
        res = GridResult(
            config=cfg.name,
            note=cfg.note,
            total_trades=summary["total"],
            wr_pct=summary["wr"],
            sharpe=summary["sharpe"],
            sortino=summary["sortino"],
            mdd_pct=summary["mdd"],
            pnl=summary["pnl"],
            by_engine=summary["by_engine"],
        )
        results.append(res)
        _restore_globals(baseline_snap)
        print(f"[grid] {cfg.name:15s} n={res.total_trades:4d}  "
              f"WR={res.wr_pct:5.1f}%  Sharpe={res.sharpe:+5.2f}  "
              f"Sortino={res.sortino:+5.2f}  MDD={res.mdd_pct:5.1f}%  "
              f"PnL=${res.pnl:+,.0f}  ({time.time()-t0:.1f}s)")
    return results


def print_ranking(results: list[GridResult]) -> None:
    print(f"\n{'='*88}")
    print(f"  GRID RANKING — {len(results)} configs · {len(GRID[0].__dict__)} params")
    print(f"{'='*88}")
    header = (f"  {'CONFIG':18s} {'TRADES':>7s}  {'WR%':>5s}  {'SHARPE':>7s}  "
              f"{'SORTINO':>7s}  {'MDD%':>5s}  {'PNL':>10s}  "
              f"{'JUMP':>5s}  {'REN':>5s}  {'CIT':>5s}")
    print(header)
    print(f"  {'-'*86}")
    for r in results:
        jump_n = r.by_engine.get("JUMP", {}).get("n", 0)
        ren_n = r.by_engine.get("RENAISSANCE", {}).get("n", 0)
        cit_n = r.by_engine.get("CITADEL", {}).get("n", 0)
        print(f"  {r.config:18s} {r.total_trades:7d}  {r.wr_pct:5.1f}  "
              f"{r.sharpe:+7.2f}  {r.sortino:+7.2f}  {r.mdd_pct:5.1f}  "
              f"${r.pnl:+9,.0f}  {jump_n:5d}  {ren_n:5d}  {cit_n:5d}")

    # Pareto dominance: higher Sharpe AND lower MDD vs baseline.
    baseline = next((r for r in results if r.config == "A_baseline"), None)
    if baseline:
        print(f"\n  vs A_baseline:")
        for r in results:
            if r.config == "A_baseline":
                continue
            sharpe_delta = r.sharpe - baseline.sharpe
            mdd_delta = r.mdd_pct - baseline.mdd_pct
            trades_delta = r.total_trades - baseline.total_trades
            verdict = "✓" if (sharpe_delta >= -0.2 and mdd_delta <= 1.0
                               and trades_delta >= 20) else "✗"
            print(f"    {r.config:18s} ΔSharpe={sharpe_delta:+.2f}  "
                  f"ΔMDD={mdd_delta:+.1f}%  Δtrades={trades_delta:+d}  {verdict}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=180,
                    help="backtest window in days (default 180)")
    ap.add_argument("--json", type=str, default=None,
                    help="optional path to dump structured results as JSON")
    args = ap.parse_args()

    results = run_grid(args.days)
    print_ranking(results)

    if args.json:
        payload = [
            {"config": r.config, "note": r.note, "total": r.total_trades,
             "wr": r.wr_pct, "sharpe": r.sharpe, "sortino": r.sortino,
             "mdd": r.mdd_pct, "pnl": r.pnl, "by_engine": r.by_engine}
            for r in results
        ]
        Path(args.json).write_text(json.dumps(payload, indent=2))
        print(f"\n[grid] structured results written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
