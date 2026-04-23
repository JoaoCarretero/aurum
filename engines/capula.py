"""
CAPULA — Funding Rate Carry Engine (AURUM Finance)
===================================================
Delta-neutral capture of perpetual-futures funding rate carry. When the
rolling z-score of funding crosses an extreme, CAPULA enters a hedged
position (short perp + long spot when funding is positive, long perp +
short spot when funding is negative) and collects per-period funding
until the z-score reverts, a kill-switch fires, or max-hold elapses.

Named after Capula Investment Management (UK quant fixed-income /
relative-value specialist) — fits the carry-style, market-neutral theme.

Hypothesis (Liu-Tsyvinski 2021 / Avellaneda-Lee 2010 analogue)
--------------------------------------------------------------
Extreme funding rates in perpetuals reflect transient crowding of one
side of the market. The hedged carry trade collects funding until
leverage unwinds and the rate reverts. Delta-neutral construction
isolates the carry from price drift, so PnL is dominated by funding
income minus round-trip execution costs on two legs.

Scope (MVP — matches AUR-8 ticket)
----------------------------------
- Standalone. No dependency on JANE STREET or BRIDGEWATER engines.
- Does not touch protected files (portfolio.py, signals.py, etc.).
- Quarter-Kelly sizing; max_pct_equity caps notional at account × cap.
- Kill-switches: |z| beyond `kill_switch_z` prevents entry and force-exits.
- Fetcher for live use reads public Binance fundingRate endpoint via
  core.sentiment; backtest accepts a pre-populated `funding_rate` column.

Falsification
-------------
Random-sign funding series (or shuffled rates) should show zero edge.
Real edge from structural crowding should be positive net of costs on
bluechip perps with |z| ≥ 2. If not, reject the hypothesis.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

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
    INTERVAL,
    LEVERAGE,
    SCAN_DAYS,
    SLIPPAGE,
    SPREAD,
    SYMBOLS,
    _TF_MINUTES,
)
from core.fs import atomic_write

log = logging.getLogger("CAPULA")
_tl = logging.getLogger("CAPULA.trades")


# ════════════════════════════════════════════════════════════════════
# Parameters
# ════════════════════════════════════════════════════════════════════

@dataclass
class CapulaParams:
    """CAPULA tunable parameters. Defaults chosen for 8h funding cadence on
    bluechip perps — override via CLI for other venues."""

    # Z-score of funding
    z_window: int = 168                # ~8 weeks at 8h cadence
    z_entry: float = 2.0               # enter when |z| > 2
    z_exit: float = 0.5                # reversion exit when |z| < 0.5

    # Duration cap
    max_hold_periods: int = 90         # ~30 days at 8h

    # Kill-switches
    kill_switch_z: float = 5.0         # |z| > 5 → no-entry / force-exit

    # Sizing (quarter-Kelly * max notional fraction)
    kelly_fraction: float = 0.25
    max_pct_equity: float = 0.10

    # Data schema
    funding_col: str = "funding_rate"
    # funding_interval_h — publication cadence of the funding rate on
    # the source venue. Binance perps publish every 8h; some venues
    # (Bybit, dYdX) use 1h. ``scan_symbol`` multiplies per-bar funding
    # by ``bar_minutes / (funding_interval_h * 60)`` so PnL reflects
    # the fractional share of one full funding period — see AUR-10
    # MAJOR 1. Do not remove.
    funding_interval_h: float = 8.0

    # Backtest metadata
    interval: str = field(default_factory=lambda: INTERVAL)


# ════════════════════════════════════════════════════════════════════
# Sizing — quarter-Kelly notional
# ════════════════════════════════════════════════════════════════════

def capula_size(equity: float, kelly_fraction: float,
                max_pct_equity: float) -> float:
    """Notional size in USD for a delta-neutral carry position.

    notional = equity × min(kelly_fraction, 1.0) × max_pct_equity

    kelly_fraction is clamped at 1 — Kelly above full-Kelly is imprudent
    and for a conservative quarter-Kelly default this never binds, but
    guards against accidental over-sizing if callers pass a raw Kelly
    value > 1. Returns 0 for non-finite / non-positive equity or zero
    fractions.
    """
    if equity <= 0 or not np.isfinite(equity):
        return 0.0
    if kelly_fraction <= 0 or max_pct_equity <= 0:
        return 0.0
    clamped = min(float(kelly_fraction), 1.0)
    return round(equity * clamped * max_pct_equity, 4)


# ════════════════════════════════════════════════════════════════════
# PnL primitives
# ════════════════════════════════════════════════════════════════════

def _period_funding_pnl(direction: int, notional: float, rate: float) -> float:
    """Per-period funding income for a delta-neutral carry.

    A SHORT perp (direction=-1) receives positive funding when rate > 0.
    A LONG perp (direction=+1) receives negative-sign funding, i.e. earns
    when rate < 0. The hedging spot leg carries no funding so the whole
    funding income equals the perp leg alone:

        pnl = -direction × rate × notional

    Verification:
      direction=-1, rate=+0.01 → -(-1) × 0.01 × notional = +rate × notional
      direction=+1, rate=-0.01 → -(+1) × -0.01 × notional = +|rate| × notional
    """
    if notional <= 0 or not np.isfinite(rate):
        return 0.0
    return -float(direction) * float(rate) * float(notional)


def _delta_neutral_cost(notional: float) -> float:
    """Round-trip execution cost for a two-leg (perp + spot) structure.

    AURUM cost model: each leg pays (COMMISSION + SLIPPAGE + SPREAD) on
    both open and close → 4 × cost × notional total. Treated as a single
    charge at trade close (entry + exit bundled) so the scan loop doesn't
    need to split it across bars.
    """
    per_fill = COMMISSION + SLIPPAGE + SPREAD
    return 4.0 * per_fill * float(notional)


# ════════════════════════════════════════════════════════════════════
# Feature computation
# ════════════════════════════════════════════════════════════════════

def compute_features(df: pd.DataFrame, params: CapulaParams) -> pd.DataFrame:
    """Add `capula_funding_z` column. Missing `funding_col` yields NaN z."""
    df = df.copy()
    col = params.funding_col
    if col not in df.columns:
        df["capula_funding_z"] = np.nan
        return df

    fr = df[col].astype(float)
    min_periods = max(5, params.z_window // 4)
    roll_mean = fr.rolling(params.z_window, min_periods=min_periods).mean().shift(1)
    roll_std = fr.rolling(params.z_window, min_periods=min_periods).std().shift(1)
    z = (fr - roll_mean) / roll_std.replace(0, np.nan)
    df["capula_funding_z"] = z
    return df


# ════════════════════════════════════════════════════════════════════
# Entry logic
# ════════════════════════════════════════════════════════════════════

def decide_direction(df: pd.DataFrame, t: int, params: CapulaParams) -> int:
    """+1 LONG perp, -1 SHORT perp, 0 no signal.

    Rules:
      1. z and funding_rate finite at bar t
      2. |z| >= z_entry (extreme) but |z| < kill_switch_z (not catastrophic)
      3. sign(z) must match sign(funding_rate) — otherwise the current
         print contradicts the regime signal, likely a one-off flip; skip
      4. Positive funding → SHORT perp to collect; negative → LONG perp.
    """
    z = float(df["capula_funding_z"].iloc[t])
    rate = float(df[params.funding_col].iloc[t]) if params.funding_col in df.columns \
        else np.nan
    if not np.isfinite(z) or not np.isfinite(rate):
        return 0

    abs_z = abs(z)
    if abs_z < params.z_entry:
        return 0
    if abs_z >= params.kill_switch_z:
        return 0

    if z > 0 and rate > 0:
        return -1  # short perp collects positive funding
    if z < 0 and rate < 0:
        return +1  # long perp collects negative funding
    return 0


# ════════════════════════════════════════════════════════════════════
# Exit logic
# ════════════════════════════════════════════════════════════════════

def resolve_exit(df: pd.DataFrame, t: int, trade: dict,
                 params: CapulaParams) -> Optional[tuple[str, float]]:
    """Check exit conditions at bar `t`. Returns (reason, z_at_exit) or None.

    Precedence:
      1. Never exit on entry bar itself (duration 0 would strip costs only)
      2. Kill-switch: |z| ≥ kill_switch_z — liquidity regime has blown out
      3. Reversion: |z| ≤ z_exit — carry edge gone
      4. Max-hold: bars since entry ≥ max_hold_periods
    """
    if t <= trade["entry_idx"]:
        return None

    z = float(df["capula_funding_z"].iloc[t])
    if np.isfinite(z):
        if abs(z) >= params.kill_switch_z:
            return "kill_switch", z
        if abs(z) <= params.z_exit:
            return "reversion", z

    if (t - trade["entry_idx"]) >= params.max_hold_periods:
        return "max_hold", z if np.isfinite(z) else 0.0
    return None


# ════════════════════════════════════════════════════════════════════
# Scan a single symbol
# ════════════════════════════════════════════════════════════════════

def _infer_bar_minutes(df: pd.DataFrame, params: CapulaParams) -> float:
    """Minutes per bar, inferred from the ``time`` column when present.

    Funding rates publish every ``funding_interval_h`` hours but candles
    can be finer (e.g. 15m). ``merge_asof(backward)`` forward-fills the
    same funding value onto every intra-period bar, so per-bar accrual
    must be scaled by ``bar_minutes / funding_interval_minutes`` to avoid
    counting each forward-filled bar as a full funding event.

    Uses the median of ``time.diff()`` to be robust to gaps; falls back
    to ``_TF_MINUTES[params.interval]`` when the DataFrame lacks a time
    column or has fewer than two rows.
    """
    if "time" in df.columns and len(df) > 1:
        times = pd.to_datetime(df["time"])
        deltas = times.diff().dropna().dt.total_seconds() / 60.0
        if len(deltas):
            m = float(deltas.median())
            if np.isfinite(m) and m > 0:
                return m
    return float(_TF_MINUTES.get(params.interval, 15))


def scan_symbol(df: pd.DataFrame, symbol: str,
                params: Optional[CapulaParams] = None,
                initial_equity: float = ACCOUNT_SIZE) -> tuple[list, dict]:
    """Scan one symbol's DataFrame, return (trades, veto_counts).

    Expects `compute_features` already applied. Trades accumulate funding
    PnL period-by-period, scaled by ``bar_minutes / (funding_interval_h
    * 60)`` so per-bar accrual reflects the fractional share of a full
    funding period — critical when bars are finer than the funding
    cadence (AUR-10 MAJOR 1). Round-trip cost is charged at exit.
    LEVERAGE multiplier applies to net PnL, matching KEPOS/GRAHAM.
    """
    params = params or CapulaParams()
    trades: list[dict] = []
    vetos: dict[str, int] = defaultdict(int)

    min_bars = params.z_window + 10
    if len(df) < min_bars:
        log.warning("%s: too few bars (%d); skipping", symbol, len(df))
        return [], {"too_few_bars": 1}

    if "capula_funding_z" not in df.columns:
        return [], {"missing_features": 1}

    account = float(initial_equity)
    n = len(df)
    open_trade: Optional[dict] = None
    accrued_funding = 0.0

    # AUR-10 MAJOR 1: scale per-bar funding accrual by
    # bar_minutes / (funding_interval_h × 60) so a forward-filled
    # funding rate contributes only its fractional per-bar share. For
    # matched cadence (8h bars + 8h funding) this is 1.0; for 15m bars
    # + 8h funding it is 1/32, preventing PnL inflation.
    bar_minutes = _infer_bar_minutes(df, params)
    funding_interval_min = float(params.funding_interval_h) * 60.0
    funding_scale = (bar_minutes / funding_interval_min
                     if funding_interval_min > 0 else 1.0)

    for t in range(params.z_window, n):
        # Accrue funding for any open trade for this bar
        if open_trade is not None:
            rate = float(df[params.funding_col].iloc[t]) \
                if params.funding_col in df.columns else np.nan
            period_pnl = _period_funding_pnl(
                direction=open_trade["direction"],
                notional=open_trade["notional"],
                rate=rate,
            ) * funding_scale
            accrued_funding += period_pnl

            resolved = resolve_exit(df, t, open_trade, params)
            if resolved is not None:
                reason, z_exit = resolved
                cost = _delta_neutral_cost(open_trade["notional"])
                gross_pnl = accrued_funding
                net_pnl = (gross_pnl - cost) * LEVERAGE
                account = max(account + net_pnl, 0.0)
                duration = t - open_trade["entry_idx"]
                open_trade.update({
                    "exit_idx": t,
                    "exit_time": df["time"].iloc[t] if "time" in df.columns else None,
                    "exit_reason": reason,
                    "z_at_exit": round(float(z_exit), 4),
                    "duration": duration,
                    "gross_funding_pnl": round(gross_pnl, 6),
                    "cost": round(cost, 6),
                    "pnl": round(net_pnl, 6),
                    "result": "WIN" if net_pnl > 0 else "LOSS",
                    "account_after": round(account, 2),
                })
                trades.append(open_trade)
                if _tl.handlers:
                    _tl.info(
                        "  %s  exit=%s  dur=%db  gross=%+.4f  cost=%.4f  net=%+.4f",
                        symbol, reason, duration, gross_pnl, cost, net_pnl,
                    )
                open_trade = None
                accrued_funding = 0.0
                continue
            else:
                continue

        # No position — check for new signal
        direction = decide_direction(df, t, params)
        if direction == 0:
            vetos["no_signal"] += 1
            continue

        notional = capula_size(
            equity=account,
            kelly_fraction=params.kelly_fraction,
            max_pct_equity=params.max_pct_equity,
        )
        if notional <= 0:
            vetos["size_zero"] += 1
            continue

        entry_rate = float(df[params.funding_col].iloc[t]) \
            if params.funding_col in df.columns else np.nan
        open_trade = {
            "symbol": symbol,
            "direction": direction,
            "entry_idx": t,
            "entry_time": df["time"].iloc[t] if "time" in df.columns else None,
            "notional": round(notional, 4),
            "entry_rate": round(entry_rate, 6) if np.isfinite(entry_rate) else None,
            "z_at_entry": round(float(df["capula_funding_z"].iloc[t]), 4),
            "account_at_entry": round(account, 2),
        }
        accrued_funding = 0.0

    # Mark-to-market any trade still open at the end
    if open_trade is not None:
        exit_idx = n - 1
        cost = _delta_neutral_cost(open_trade["notional"])
        net_pnl = (accrued_funding - cost) * LEVERAGE
        account = max(account + net_pnl, 0.0)
        duration = exit_idx - open_trade["entry_idx"]
        z_final = float(df["capula_funding_z"].iloc[exit_idx])
        open_trade.update({
            "exit_idx": exit_idx,
            "exit_time": df["time"].iloc[exit_idx] if "time" in df.columns else None,
            "exit_reason": "forced_mtm",
            "z_at_exit": round(z_final, 4) if np.isfinite(z_final) else None,
            "duration": duration,
            "gross_funding_pnl": round(accrued_funding, 6),
            "cost": round(cost, 6),
            "pnl": round(net_pnl, 6),
            "result": "WIN" if net_pnl > 0 else "LOSS",
            "account_after": round(account, 2),
            "forced_mtm": True,
        })
        trades.append(open_trade)

    return trades, dict(vetos)


# ════════════════════════════════════════════════════════════════════
# Backtest orchestrator
# ════════════════════════════════════════════════════════════════════

def run_backtest(all_dfs: dict[str, pd.DataFrame],
                 params: Optional[CapulaParams] = None,
                 initial_equity: float = ACCOUNT_SIZE,
                 ) -> tuple[list, dict, dict]:
    """Run CAPULA across all symbols. Returns (trades, vetos, per_sym_stats)."""
    params = params or CapulaParams()
    all_trades: list[dict] = []
    all_vetos: dict[str, int] = defaultdict(int)
    per_sym: dict[str, dict] = {}

    for sym, df in all_dfs.items():
        log.info("scanning %s (%d bars)", sym, len(df))
        df_feat = compute_features(df, params)
        trades, vetos = scan_symbol(df_feat, sym, params, initial_equity)
        all_trades.extend(trades)
        for k, v in vetos.items():
            all_vetos[k] += v
        wins = sum(1 for t in trades if t["result"] == "WIN")
        per_sym[sym] = {
            "n_trades": len(trades),
            "wins": wins,
            "losses": len(trades) - wins,
            "pnl": round(sum(t["pnl"] for t in trades), 2),
        }

    return all_trades, dict(all_vetos), per_sym


# ════════════════════════════════════════════════════════════════════
# Summary
# ════════════════════════════════════════════════════════════════════

def compute_summary(trades: list[dict], initial_equity: float = ACCOUNT_SIZE
                    ) -> dict:
    n = len(trades)
    if n == 0:
        return {
            "n_trades": 0, "win_rate": 0.0, "pnl": 0.0, "roi_pct": 0.0,
            "final_equity": initial_equity, "max_dd_pct": 0.0,
            "sharpe": 0.0, "sortino": 0.0,
        }

    pnls = np.asarray([t["pnl"] for t in trades], dtype=float)
    wins = int(np.sum(pnls > 0))
    wr = wins / n * 100.0
    total_pnl = float(pnls.sum())
    final_eq = initial_equity + total_pnl
    roi = total_pnl / initial_equity * 100.0

    equity_curve = initial_equity + np.cumsum(pnls)
    peak = np.maximum.accumulate(equity_curve)
    dd = (peak - equity_curve) / np.where(peak > 0, peak, 1.0)
    max_dd_pct = float(dd.max()) * 100.0

    mean_pnl = float(pnls.mean())
    std_pnl = float(pnls.std(ddof=1)) if n > 1 else 0.0
    sharpe = mean_pnl / std_pnl * np.sqrt(n) if std_pnl > 0 else 0.0

    neg = pnls[pnls < 0]
    downside = float(neg.std(ddof=1)) if len(neg) > 1 else 0.0
    sortino = mean_pnl / downside * np.sqrt(n) if downside > 0 else 0.0

    return {
        "n_trades": n,
        "win_rate": round(wr, 2),
        "pnl": round(total_pnl, 2),
        "roi_pct": round(roi, 2),
        "final_equity": round(float(final_eq), 2),
        "max_dd_pct": round(max_dd_pct, 2),
        "sharpe": round(float(sharpe), 3),
        "sortino": round(float(sortino), 3),
    }


# ════════════════════════════════════════════════════════════════════
# Funding-rate fetcher (standalone — live / warmup use)
# ════════════════════════════════════════════════════════════════════

def fetch_funding_history(symbol: str, limit: int = 500,
                          end_time_ms: Optional[int] = None
                          ) -> Optional[pd.DataFrame]:
    """Fetch recent funding history for `symbol` from Binance Futures.

    Returns DataFrame with columns ['time', 'funding_rate'] sorted by time.
    Returns None on network / venue error so callers can fall back to
    candle-only backtest (no funding column) and abstain cleanly.

    ``end_time_ms`` anchors the fetch window to a historical instant —
    required for OOS/backtest reproducibility (AUR-10 MAJOR 2). Without
    it the API returns the most recent ``limit`` rates ending NOW,
    introducing look-ahead and making re-runs non-deterministic. Live
    or fresh-warmup callers can omit it.

    Standalone — does not depend on JANE STREET or BRIDGEWATER. Uses the
    shared `core.sentiment.fetch_funding_rate` utility which talks to the
    public `fapi.binance.com` endpoint (no auth).
    """
    try:
        from core.sentiment import fetch_funding_rate
        return fetch_funding_rate(symbol, limit=limit,
                                  end_time_ms=end_time_ms)
    except Exception as e:  # pragma: no cover — network path
        log.warning("fetch_funding_history(%s) failed: %s", symbol, e)
        return None


def join_funding_to_candles(candles: pd.DataFrame,
                            funding: pd.DataFrame) -> pd.DataFrame:
    """Left-join funding rates onto an OHLCV candle DataFrame by timestamp.

    Expects `candles` to have a 'time' column (datetime64) and `funding`
    to have ['time', 'funding_rate']. Forward-fills funding between
    publications (funding is published every 1h or 8h depending on
    venue; candles may be finer). Returns a new DataFrame — does not
    mutate input.
    """
    out = candles.copy()
    if funding is None or funding.empty or "funding_rate" in out.columns:
        return out
    f = funding[["time", "funding_rate"]].copy()
    f["time"] = pd.to_datetime(f["time"])
    out["time"] = pd.to_datetime(out["time"])
    out = pd.merge_asof(
        out.sort_values("time"),
        f.sort_values("time"),
        on="time",
        direction="backward",
    )
    return out.reset_index(drop=True)


# ════════════════════════════════════════════════════════════════════
# Persistence
# ════════════════════════════════════════════════════════════════════

def _trades_to_serializable(trades: list[dict]) -> list[dict]:
    out = []
    for t in trades:
        tt = dict(t)
        for key in ("entry_time", "exit_time"):
            v = tt.get(key)
            if v is None:
                continue
            try:
                tt[key] = pd.Timestamp(v).isoformat()
            except Exception:
                tt[key] = str(v)
        out.append(tt)
    return out


def save_run(run_dir: Path, trades: list[dict], summary: dict,
             params: CapulaParams, vetos: dict, per_sym: dict,
             meta: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(run_dir / "trades.json",
                 json.dumps(_trades_to_serializable(trades),
                            separators=(",", ":"), default=str))
    payload = {
        "engine": "CAPULA",
        "version": "0.1.0",
        "run_id": meta.get("run_id"),
        "timestamp": datetime.now().isoformat(),
        "params": asdict(params),
        "summary": summary,
        "per_symbol": per_sym,
        "vetos": vetos,
        "meta": meta,
    }
    atomic_write(run_dir / "summary.json",
                 json.dumps(payload, indent=2, default=str))


# ════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════

def _setup_logging(run_dir: Path) -> None:
    fmt = logging.Formatter("%(asctime)s  %(levelname)s  %(message)s")
    fh = logging.FileHandler(run_dir / "log.txt", encoding="utf-8")
    fh.setFormatter(fmt); fh.setLevel(logging.DEBUG)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt); sh.setLevel(logging.INFO)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(fh); root.addHandler(sh)


def _print_banner(basket: str, symbols: list[str], days: int,
                  params: CapulaParams) -> None:
    print()
    print("  ╔════════════════════════════════════════════════════════════╗")
    print("  ║ CAPULA · Funding Rate Carry · AURUM Finance                 ║")
    print("  ╠════════════════════════════════════════════════════════════╣")
    print(f"  ║ UNIVERSE   {len(symbols)} assets (basket: {basket})")
    print(f"  ║ PERIOD     {days} days")
    print(f"  ║ CAPITAL    ${ACCOUNT_SIZE:,.0f} · {LEVERAGE}x leverage")
    print(f"  ║ SIZING     quarter-Kelly (k={params.kelly_fraction}) · "
          f"cap {params.max_pct_equity*100:.1f}% equity")
    print(f"  ║ ENTRY      |z| ≥ {params.z_entry} (funding rolling-{params.z_window}")
    print(f"  ║ EXIT       |z| ≤ {params.z_exit} OR hold ≥ {params.max_hold_periods}p"
          f" OR |z| ≥ {params.kill_switch_z}")
    print("  ╚════════════════════════════════════════════════════════════╝")
    print()


def _print_summary(label: str, summary: dict) -> None:
    print(f"\n  ┌─ {label} " + "─" * max(0, 50 - len(label)) + "┐")
    print(f"  │ trades      {summary['n_trades']:>10d}")
    print(f"  │ win rate    {summary['win_rate']:>9.1f}%")
    print(f"  │ ROI         {summary['roi_pct']:>+9.2f}%")
    print(f"  │ PnL         ${summary['pnl']:>+12,.2f}")
    print(f"  │ final eq    ${summary['final_equity']:>12,.2f}")
    print(f"  │ max DD      {summary['max_dd_pct']:>9.2f}%")
    print(f"  │ Sharpe      {summary['sharpe']:>10.3f}")
    print(f"  │ Sortino     {summary['sortino']:>10.3f}")
    print("  └" + "─" * 54 + "┘")


def _build_dataset(symbols: list[str], interval: str,
                   n_candles: int) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV + funding, join, return {symbol: df_with_funding}."""
    from core.data import fetch_all, validate
    log.info("fetching %d symbols @ %s (%d candles each) …",
             len(symbols), interval, n_candles)
    all_dfs = fetch_all(symbols, interval=interval,
                        n_candles=n_candles, futures=True)
    out: dict[str, pd.DataFrame] = {}
    for sym, df in all_dfs.items():
        validate(df, sym)
        # Anchor funding fetch to the dataset's last candle so OOS re-runs
        # are reproducible (AUR-10 MAJOR 2).
        end_time_ms: Optional[int] = None
        if "time" in df.columns and len(df):
            end_time_ms = int(
                pd.Timestamp(df["time"].iloc[-1]).value // 1_000_000
            )
        funding = fetch_funding_history(
            sym,
            limit=max(200, n_candles // 24),
            end_time_ms=end_time_ms,
        )
        if funding is None:
            log.warning(
                "%s: funding fetch returned None — symbol will abstain "
                "(missing funding_rate column)", sym,
            )
        out[sym] = join_funding_to_candles(df, funding)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="CAPULA — Funding Rate Carry")
    ap.add_argument("--days", type=int, default=SCAN_DAYS)
    ap.add_argument("--basket", type=str, default="bluechip")
    ap.add_argument("--interval", type=str, default=None)
    ap.add_argument("--z-entry", type=float, default=None)
    ap.add_argument("--z-exit", type=float, default=None)
    ap.add_argument("--kelly", type=float, default=None,
                    help="Kelly fraction (default 0.25 = quarter-Kelly)")
    ap.add_argument("--no-menu", action="store_true")
    args = ap.parse_known_args()[0]

    basket_name = args.basket or "default"
    symbols = BASKETS.get(basket_name, SYMBOLS)
    scan_days = int(args.days)
    interval = args.interval or INTERVAL
    tf_min = max(1, _TF_MINUTES.get(interval, 15))
    n_candles = scan_days * 24 * 60 // tf_min

    params = CapulaParams()
    params.interval = interval
    if args.z_entry is not None:
        params.z_entry = float(args.z_entry)
    if args.z_exit is not None:
        params.z_exit = float(args.z_exit)
    if args.kelly is not None:
        params.kelly_fraction = float(args.kelly)
    if params.z_exit >= params.z_entry:
        raise SystemExit(
            f"z_exit ({params.z_exit}) must be < z_entry ({params.z_entry})"
        )

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    run_id = f"capula_{stamp}"
    from config.paths import DATA_DIR
    run_dir = DATA_DIR / "capula" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _setup_logging(run_dir)
    _print_banner(basket_name, symbols, scan_days, params)

    all_dfs = _build_dataset(symbols, interval, n_candles)
    if not all_dfs:
        print("  no data fetched.")
        return 1

    trades, vetos, per_sym = run_backtest(all_dfs, params, ACCOUNT_SIZE)
    summary = compute_summary(trades, ACCOUNT_SIZE)
    _print_summary(f"CAPULA summary ({run_id})", summary)

    if per_sym:
        print("\n  per symbol:")
        for s, st in sorted(per_sym.items()):
            print(f"    {s:<12s}  n={st['n_trades']:>3d}  "
                  f"W={st['wins']:>2d}  L={st['losses']:>2d}  "
                  f"pnl=${st['pnl']:>+10,.2f}")
    if vetos:
        print("\n  vetoes:")
        for k, v in sorted(vetos.items(), key=lambda kv: -kv[1])[:5]:
            print(f"    {k:<22s}  {v:>6d}")

    save_run(run_dir, trades, summary, params, vetos, per_sym,
             meta={"run_id": run_id, "basket": basket_name,
                   "scan_days": scan_days, "symbols": list(all_dfs.keys())})
    print(f"\n  run → {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
