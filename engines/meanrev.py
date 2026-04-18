"""
MEANREV — AURUM Simplified Mean-Reversion Engine
================================================
Design: docs/engines/meanrev/2026-04-18_design.md

Thesis: price deviation from EMA50 + RSI confirmation = edge. Nothing
else. No multi-TF consensus. No OU/Hurst/ADF/VR battery. Single layer of
discrimination, single timeframe (15m).

Followup do archive do ornstein v1 (2026-04-18). Entrada: preço X ATRs
fora do EMA50 + RSI em extremo. Alvo: EMA50. Stop: Y * ATR do entry.

Discipline
----------
- Uses core.indicators.indicators() for EMA/RSI/ATR (protected core, import-only).
- AURUM cost model (C1+C2) from config.params.
- NOT in FROZEN_ENGINES / OPERATIONAL_ENGINES. Research-only.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from config.params import (
    ACCOUNT_SIZE,
    BASKETS,
    COMMISSION,
    FUNDING_PER_8H,
    LEVERAGE,
    SLIPPAGE,
    SPREAD,
)
from core.data import fetch_all, validate
from core.fs import atomic_write
from core.indicators import indicators as core_indicators
from analysis.stats import calc_ratios, equity_stats

log = logging.getLogger("MEANREV")


@dataclass
class MeanRevParams:
    tf_exec: str = "15m"
    deviation_enter: float = 2.0
    rsi_long_max: float = 30.0
    rsi_short_min: float = 70.0
    atr_stop_mult: float = 2.0
    time_stop_bars: int = 96
    risk_per_trade: float = 0.01
    notional_cap: float = 0.05
    min_atr_pct: float = 0.001  # skip bars with degenerate ATR
    # Diagnostic: flip direction to test if signals are trend-continuation
    # rather than mean-reversion. If --reverse produces positive edge, the
    # engine's name is wrong but the signal has value.
    reverse_direction: bool = False
    # Regime gate: "any" = no gate. "low_vol" = only vol_regime in {LOW, NORMAL}.
    # "high_vol" = only {HIGH, EXTREME}. Uses core.indicators vol_regime.
    regime_filter: str = "any"
    # Mean anchor: "ema50" = deviation from EMA50 (default). "vwap_daily" =
    # deviation from session VWAP (rolling daily).
    anchor_type: str = "ema50"
    # Side gate: "both" (default), "long_only", "short_only".
    side_filter: str = "both"


# ── Features ────────────────────────────────────────────────────

def _daily_vwap(df: pd.DataFrame) -> pd.Series:
    """Rolling daily VWAP. Resets at UTC midnight per bar.

    Falls back to cumsum over the whole frame if a datetime index isn't
    available (ok for test data).
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical * df["vol"]
    if isinstance(df.index, pd.DatetimeIndex):
        day = df.index.normalize()
        cum_pv = pv.groupby(day).cumsum()
        cum_v = df["vol"].groupby(day).cumsum()
    else:
        cum_pv = pv.cumsum()
        cum_v = df["vol"].cumsum()
    vwap = cum_pv / cum_v.replace(0, np.nan)
    return vwap


def compute_features(df: pd.DataFrame, params: MeanRevParams | None = None) -> pd.DataFrame:
    """Attach ema50, rsi, atr, and deviation = (close - anchor) / atr."""
    df = core_indicators(df)
    atr = df["atr"].replace(0, np.nan)
    if params is not None and params.anchor_type == "vwap_daily":
        if "vol" in df.columns:
            df["vwap_daily"] = _daily_vwap(df)
            anchor = df["vwap_daily"]
        else:
            anchor = df["ema50"]
    else:
        anchor = df["ema50"]
    df["deviation"] = (df["close"] - anchor) / atr
    df["anchor"] = anchor
    return df


# ── Entry decision ──────────────────────────────────────────────

_LOW_VOL_REGIMES = {"LOW", "NORMAL"}
_HIGH_VOL_REGIMES = {"HIGH", "EXTREME"}


def decide_entry(row: pd.Series, params: MeanRevParams) -> int:
    """Return +1 (long), -1 (short), or 0 (no entry)."""
    dev = row.get("deviation", np.nan)
    rsi = row.get("rsi", np.nan)
    atr_pct = row.get("atr_pct", np.nan)
    if np.isnan(dev) or np.isnan(rsi):
        return 0
    if not np.isnan(atr_pct) and atr_pct < params.min_atr_pct * 100:
        return 0

    # Regime gate
    if params.regime_filter != "any":
        regime = row.get("vol_regime", "NORMAL")
        if params.regime_filter == "low_vol" and regime not in _LOW_VOL_REGIMES:
            return 0
        if params.regime_filter == "high_vol" and regime not in _HIGH_VOL_REGIMES:
            return 0

    long_sig = dev <= -params.deviation_enter and rsi <= params.rsi_long_max
    short_sig = dev >= +params.deviation_enter and rsi >= params.rsi_short_min

    if params.side_filter == "long_only":
        short_sig = False
    elif params.side_filter == "short_only":
        long_sig = False

    if long_sig:
        return -1 if params.reverse_direction else +1
    if short_sig:
        return +1 if params.reverse_direction else -1
    return 0


# ── Trade simulation ────────────────────────────────────────────

def _cost_per_notional() -> float:
    """Round-trip cost per unit of notional (open+close)."""
    return 2.0 * (SLIPPAGE + SPREAD + COMMISSION)


def simulate_trade(df: pd.DataFrame, entry_idx: int, direction: int,
                   params: MeanRevParams) -> dict | None:
    """Simulate from entry_idx+1 onward. Entry at next bar's open.

    Returns None if entry bar is last bar in df.
    """
    if entry_idx + 1 >= len(df):
        return None

    entry_row = df.iloc[entry_idx]
    open_bar = df.iloc[entry_idx + 1]
    entry_px = float(open_bar["open"])
    atr_at_entry = float(entry_row["atr"])
    anchor_at_entry = float(entry_row.get("anchor", entry_row.get("ema50")))

    if direction == +1:
        stop = entry_px - params.atr_stop_mult * atr_at_entry
        if params.reverse_direction:
            # Trend-continuation target: symmetric to stop (RR=1:1)
            target = entry_px + params.atr_stop_mult * atr_at_entry
        else:
            target = anchor_at_entry
    else:
        stop = entry_px + params.atr_stop_mult * atr_at_entry
        if params.reverse_direction:
            target = entry_px - params.atr_stop_mult * atr_at_entry
        else:
            target = anchor_at_entry

    stop_distance = abs(entry_px - stop)
    if stop_distance <= 0:
        return None

    # Size by risk: stop_distance * size (notional) = risk_per_trade * account
    # But we express size as fraction of account (notional/equity).
    account = ACCOUNT_SIZE
    notional = (params.risk_per_trade * account * entry_px) / stop_distance
    max_notional = params.notional_cap * account * LEVERAGE
    notional = min(notional, max_notional)
    if notional <= 0:
        return None

    # Simulate path bar-by-bar from entry_idx+1 to entry_idx+time_stop_bars
    exit_idx = None
    exit_px = None
    reason = None

    for i in range(entry_idx + 1, min(entry_idx + 1 + params.time_stop_bars, len(df))):
        bar = df.iloc[i]
        high, low, close = float(bar["high"]), float(bar["low"]), float(bar["close"])
        if direction == +1:
            if low <= stop:
                exit_idx, exit_px, reason = i, stop, "sl"
                break
            if high >= target:
                exit_idx, exit_px, reason = i, target, "tp"
                break
        else:
            if high >= stop:
                exit_idx, exit_px, reason = i, stop, "sl"
                break
            if low <= target:
                exit_idx, exit_px, reason = i, target, "tp"
                break

    if exit_idx is None:
        last_i = min(entry_idx + params.time_stop_bars, len(df) - 1)
        exit_idx = last_i
        exit_px = float(df.iloc[last_i]["close"])
        reason = "time_stop"

    # PnL in dollars
    pnl_pct = (exit_px - entry_px) / entry_px * direction
    costs_pct = _cost_per_notional()
    net_pnl_pct = pnl_pct - costs_pct
    pnl_usd = net_pnl_pct * notional / entry_px * entry_px  # = net_pnl_pct * notional
    pnl_usd = net_pnl_pct * notional

    r_multiple = (pnl_pct - costs_pct) / (stop_distance / entry_px) if stop_distance else 0.0

    return {
        "entry_idx": entry_idx + 1,
        "exit_idx": exit_idx,
        "direction": direction,
        "entry": entry_px,
        "exit": exit_px,
        "stop": stop,
        "target": target,
        "atr_at_entry": atr_at_entry,
        "notional": notional,
        "pnl_pct": pnl_pct,
        "net_pnl_pct": net_pnl_pct,
        "pnl_usd": pnl_usd,
        "r_multiple": r_multiple,
        "reason": reason,
        "bars_held": exit_idx - (entry_idx + 1),
    }


# ── Per-symbol scan ─────────────────────────────────────────────

def scan_symbol(df: pd.DataFrame, symbol: str,
                params: MeanRevParams) -> tuple[list[dict], dict[str, int]]:
    """Return list of trades and veto distribution for one symbol."""
    df = compute_features(df, params)
    trades: list[dict] = []
    vetos: dict[str, int] = {
        "no_signal": 0, "position_open": 0, "degenerate_atr": 0, "end_of_data": 0,
    }

    in_trade_until = -1
    n = len(df)
    for i in range(n - 1):
        if i <= in_trade_until:
            vetos["position_open"] += 1
            continue

        row = df.iloc[i]
        atr_val = row.get("atr")
        if pd.isna(atr_val) or float(atr_val) <= 0:
            vetos["degenerate_atr"] += 1
            continue

        direction = decide_entry(row, params)
        if direction == 0:
            vetos["no_signal"] += 1
            continue

        trade = simulate_trade(df, i, direction, params)
        if trade is None:
            vetos["end_of_data"] += 1
            continue

        trade["symbol"] = symbol
        trades.append(trade)
        in_trade_until = trade["exit_idx"]

    return trades, vetos


# ── Backtest orchestration ─────────────────────────────────────

def run_backtest(symbols: list[str], params: MeanRevParams,
                 days: int = 180) -> tuple[list[dict], dict]:
    all_trades: list[dict] = []
    all_vetos: dict[str, int] = {
        "no_signal": 0, "position_open": 0, "degenerate_atr": 0, "end_of_data": 0,
    }
    per_sym: dict[str, dict] = {}

    candles_needed = int(days * 96)  # 15m = 96 bars/day
    cache = fetch_all(symbols, interval=params.tf_exec, n_candles=candles_needed)

    for sym in symbols:
        df = cache.get(sym)
        if df is None or df.empty or not validate(df, sym):
            log.warning("skip %s (no/invalid data)", sym)
            per_sym[sym] = {"n_trades": 0, "error": "no_data"}
            continue
        t0 = len(all_trades)
        trades, vetos = scan_symbol(df, sym, params)
        log.info("[%s] n_trades=%d", sym, len(trades))
        all_trades.extend(trades)
        for k, v in vetos.items():
            all_vetos[k] = all_vetos.get(k, 0) + v
        per_sym[sym] = {
            "n_trades": len(trades),
            "total_pnl": sum(t["pnl_usd"] for t in trades),
        }

    # Aggregate summary
    pnls = [t["pnl_usd"] for t in all_trades]
    ratios = calc_ratios(pnls, start=ACCOUNT_SIZE, n_days=days)
    eq, mdd_usd, mdd_pct, max_streak = equity_stats(pnls, start=ACCOUNT_SIZE)
    n_win = sum(1 for p in pnls if p > 0)
    n_loss = sum(1 for p in pnls if p < 0)
    r_mults = [t["r_multiple"] for t in all_trades]

    summary = {
        "total_trades": len(all_trades),
        "win_rate": (n_win / len(pnls)) if pnls else 0.0,
        "n_win": n_win,
        "n_loss": n_loss,
        "gross_profit": sum(p for p in pnls if p > 0),
        "gross_loss": sum(p for p in pnls if p < 0),
        "profit_factor": (sum(p for p in pnls if p > 0) /
                          abs(sum(p for p in pnls if p < 0))) if n_loss else 0.0,
        "sharpe": ratios["sharpe"] or 0.0,
        "sortino": ratios["sortino"] or 0.0,
        "calmar": ratios["calmar"] or 0.0,
        "max_drawdown": mdd_pct / 100.0,
        "max_drawdown_usd": mdd_usd,
        "max_loss_streak": max_streak,
        "total_pnl": sum(pnls),
        "final_equity": eq[-1] if eq else ACCOUNT_SIZE,
        "expectancy_r": (sum(r_mults) / len(r_mults)) if r_mults else 0.0,
        "vetos": all_vetos,
        "per_symbol": per_sym,
    }
    return all_trades, summary


# ── Persistence ─────────────────────────────────────────────────

def save_run(run_dir: Path, trades: list[dict], summary: dict,
             params: MeanRevParams, meta: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    trades_ser = [{**t, "direction": int(t["direction"])} for t in trades]
    atomic_write(run_dir / "trades.json",
                 json.dumps(trades_ser, indent=2, default=str))
    atomic_write(run_dir / "summary.json",
                 json.dumps({
                     "engine": "MEANREV",
                     "version": "1.0.0",
                     "run_id": meta.get("run_id"),
                     "timestamp": datetime.now().isoformat(),
                     "params": asdict(params),
                     "summary": summary,
                     "meta": meta,
                 }, indent=2, default=str))


def _print_summary(summary: dict) -> None:
    print("\n  MEANREV — Simplified Mean-Reversion Engine")
    print("  ============================================================")
    print(f"  Total trades       : {summary['total_trades']}")
    print(f"  Win rate           : {summary['win_rate'] * 100:.2f}%")
    print(f"  Profit factor      : {summary['profit_factor']:.3f}")
    print(f"  Sharpe             : {summary['sharpe']:.3f}")
    print(f"  Sortino            : {summary['sortino']:.3f}")
    print(f"  Calmar             : {summary['calmar']:.3f}")
    print(f"  Max drawdown       : {summary['max_drawdown'] * 100:.2f}%")
    print(f"  Expectancy (R)     : {summary['expectancy_r']:.3f}")
    print(f"  Final equity       : ${summary['final_equity']:,.2f}")
    print(f"  Total PnL          : ${summary['total_pnl']:,.2f}")
    if summary["vetos"]:
        print("\n  Vetos:")
        for k, v in sorted(summary["vetos"].items(), key=lambda kv: -kv[1]):
            print(f"    {k:<24} {v:>8}")


# ── CLI ─────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MEANREV — AURUM Mean-Reversion Engine")
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--basket", default=None)
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--deviation", type=float, default=None)
    ap.add_argument("--rsi-long-max", type=float, default=None)
    ap.add_argument("--rsi-short-min", type=float, default=None)
    ap.add_argument("--stop-mult", type=float, default=None)
    ap.add_argument("--reverse", action="store_true",
                    help="Flip entry direction (diagnostic for trend-continuation)")
    ap.add_argument("--out", default="data/meanrev")
    ap.add_argument("--no-menu", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s - %(message)s")

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    elif args.basket:
        symbols = list(BASKETS[args.basket])
    else:
        symbols = list(BASKETS["bluechip_active"])

    params = MeanRevParams()
    if args.deviation is not None:
        params.deviation_enter = args.deviation
    if args.rsi_long_max is not None:
        params.rsi_long_max = args.rsi_long_max
    if args.rsi_short_min is not None:
        params.rsi_short_min = args.rsi_short_min
    if args.stop_mult is not None:
        params.atr_stop_mult = args.stop_mult
    if args.reverse:
        params.reverse_direction = True

    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    run_dir = Path(args.out) / ts
    log.info("MEANREV run starting: symbols=%s run_dir=%s", symbols, run_dir)

    trades, summary = run_backtest(symbols, params, days=args.days)
    meta = {
        "run_id": ts,
        "symbols": symbols,
        "days": args.days,
        "initial_equity": float(ACCOUNT_SIZE),
    }
    save_run(run_dir, trades, summary, params, meta)
    _print_summary(summary)
    print(f"\n  Run saved to: {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
