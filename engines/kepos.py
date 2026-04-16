"""
KEPOS — Critical Endogeneity Fade Engine (AURUM Finance)
========================================================
Fades overextended moves when Hawkes branching ratio η is sustained in the
critical regime (η ≥ 0.95). Named after Kepos Capital (PIMCO quant spin-off,
regime-focused).

Hypothesis (Filimonov-Sornette 2012, Hardiman-Bouchaud 2014)
-----------------------------------------------------------
When η ≥ 0.95 is sustained for several bars AND price is overextended in
units of its own 20-bar volatility AND ATR is expanding vs recent baseline,
the market is feedback-saturated and near reversal. Enter against the move.

Discipline
----------
- Local fixed-risk-% sizing. No coupling to CITADEL's `position_size` / Ω
  score; KEPOS pays for its own risk model from first principles.
- AURUM cost model (C1+C2: slippage + spread + commission + funding with
  LEVERAGE) — imported from config.params, not re-implemented.
- Backtest-first. Engine is registered in `config/engines.py` but does NOT
  enter `ENGINE_INTERVALS`/`ENGINE_BASKETS`/`FROZEN_ENGINES` until overfit
  6/6 audit passes.
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
    ATR_PERIOD,
    BASKETS,
    COMMISSION,
    FUNDING_PER_8H,
    INTERVAL,
    LEVERAGE,
    MACRO_SYMBOL,
    N_CANDLES,
    SCAN_DAYS,
    SLIPPAGE,
    SPREAD,
    SYMBOLS,
    _TF_MINUTES,
)
from core.data import fetch_all, validate
from core.fs import atomic_write
from core.hawkes import label_eta, rolling_branching_ratio
from core.indicators import indicators

log = logging.getLogger("KEPOS")
_tl = logging.getLogger("KEPOS.trades")


# ════════════════════════════════════════════════════════════════════
# Parameters
# ════════════════════════════════════════════════════════════════════

@dataclass
class KeposParams:
    """KEPOS tunable parameters. All values here are defaults — callers can
    override via CLI or by passing a custom dataclass."""

    # Hawkes
    hawkes_window_bars: int = 2000
    hawkes_refit_every: int = 100
    hawkes_k_sigma: float = 2.0
    hawkes_vol_lookback: int = 100
    hawkes_smooth_span: int = 5
    hawkes_min_events: int = 30

    # Regime trigger
    eta_critical: float = 0.95
    eta_exit: float = 0.85
    eta_sustained_bars: int = 5
    eta_exit_sustained_bars: int = 2

    # Price extension filter
    price_lookback: int = 20
    price_sigma_window: int = 100
    price_ext_sigma: float = 2.0

    # Volatility expansion filter
    atr_mean_window: int = 50
    atr_expansion_ratio: float = 1.3

    # Exit levels
    stop_atr_mult: float = 1.2
    tp_atr_mult: float = 1.8
    max_bars_in_trade: int = 40

    # Sizing (local fixed-risk-%)
    max_pct_equity: float = 0.02

    # Backtest metadata
    interval: str = field(default_factory=lambda: INTERVAL)


# ════════════════════════════════════════════════════════════════════
# Local sizing — fixed fractional risk per trade
# ════════════════════════════════════════════════════════════════════

def kepos_size(equity: float, entry: float, stop: float,
               target_pct: float = 0.02) -> float:
    """Position size (units) from fixed-risk-% per trade.

    size = (equity × target_pct) / |entry - stop|

    Isolated from CITADEL's `position_size` to avoid coupling to the
    Ω-score calibration. Returns 0 if distance is degenerate or inputs
    are invalid.
    """
    if equity <= 0 or not np.isfinite(equity):
        return 0.0
    dist = abs(entry - stop)
    if dist <= 0 or not np.isfinite(dist):
        return 0.0
    return round(equity * target_pct / dist, 4)


# ════════════════════════════════════════════════════════════════════
# Feature computation
# ════════════════════════════════════════════════════════════════════

def compute_features(df: pd.DataFrame, params: KeposParams) -> pd.DataFrame:
    """Enrich OHLCV with all features KEPOS needs.

    Adds:
      - atr, ema*, vol_regime, rsi, ... (from core.indicators.indicators)
      - eta_raw, eta_smooth (from core.hawkes.rolling_branching_ratio)
      - price_ext_sigma  = cum_N_bar_log_return / σ(cum_N_bar, window)
      - atr_ratio        = atr / shift(1) rolling mean of atr

    Uses shift(1) on denominators to avoid each bar's value contaminating
    its own normalization baseline.
    """
    df = indicators(df.copy())

    eta = rolling_branching_ratio(
        df,
        window_bars=params.hawkes_window_bars,
        refit_every=params.hawkes_refit_every,
        k_sigma=params.hawkes_k_sigma,
        vol_lookback=params.hawkes_vol_lookback,
        smoothing_span=params.hawkes_smooth_span,
        min_events=params.hawkes_min_events,
    )
    df = df.join(eta[["eta_raw", "eta_smooth", "n_events", "fit_bar"]])

    # Price extension: cum_N log-return in units of rolling σ
    close = df["close"].astype(float)
    cum_n = np.log(close / close.shift(params.price_lookback))
    sigma_cum = cum_n.rolling(
        params.price_sigma_window, min_periods=params.price_sigma_window // 2
    ).std().shift(1)
    df["kepos_cum_n"] = cum_n
    df["kepos_price_ext_sigma"] = cum_n / sigma_cum.replace(0, np.nan)

    # ATR expansion ratio
    atr_series = df["atr"].astype(float)
    atr_baseline = atr_series.rolling(
        params.atr_mean_window, min_periods=max(10, params.atr_mean_window // 2)
    ).mean().shift(1)
    df["kepos_atr_ratio"] = atr_series / atr_baseline.replace(0, np.nan)

    return df


# ════════════════════════════════════════════════════════════════════
# Entry logic
# ════════════════════════════════════════════════════════════════════

def _eta_sustained_critical(df: pd.DataFrame, t: int,
                            params: KeposParams) -> bool:
    """η_smooth ≥ ETA_CRITICAL for the last N bars ending at t."""
    need = params.eta_sustained_bars
    if t + 1 < need:
        return False
    window = df["eta_smooth"].iloc[t + 1 - need : t + 1].values
    if np.any(np.isnan(window)):
        return False
    return bool(np.all(window >= params.eta_critical))


def decide_direction(df: pd.DataFrame, t: int, params: KeposParams) -> int:
    """Return +1 (LONG), -1 (SHORT) or 0 (no signal) at bar t.

    Entry fires when ALL four are true:
      1. η_smooth ≥ ETA_CRITICAL for last N bars (sustained critical)
      2. |cum_N_return| > PRICE_EXT_SIGMA × σ_cum_N   (price overextended)
      3. ATR / ATR_rolling_mean > ATR_EXPANSION_RATIO (volatility expanding)
      4. No NaNs in any of the three feature columns at bar t
    Direction is the FADE of the extension: positive cum → short, negative → long.
    """
    if t < 1:
        return 0

    ext = df["kepos_price_ext_sigma"].iloc[t]
    atr_r = df["kepos_atr_ratio"].iloc[t]
    close = df["close"].iloc[t]
    if not np.isfinite(ext) or not np.isfinite(atr_r) or not np.isfinite(close):
        return 0

    if not _eta_sustained_critical(df, t, params):
        return 0
    if abs(ext) <= params.price_ext_sigma:
        return 0
    if atr_r <= params.atr_expansion_ratio:
        return 0

    return -1 if ext > 0 else +1


def calc_levels(df: pd.DataFrame, t: int, direction: int,
                params: KeposParams) -> Optional[tuple[float, float, float]]:
    """Return (entry, stop, tp). Entry is next-bar open; stop/tp are ATR-based."""
    if direction == 0:
        return None
    if t + 1 >= len(df):
        return None
    entry = float(df["open"].iloc[t + 1])
    atr = float(df["atr"].iloc[t])
    if not np.isfinite(entry) or not np.isfinite(atr) or atr <= 0:
        return None

    if direction == +1:
        stop = entry - params.stop_atr_mult * atr
        tp = entry + params.tp_atr_mult * atr
    else:
        stop = entry + params.stop_atr_mult * atr
        tp = entry - params.tp_atr_mult * atr
    return entry, stop, tp


# ════════════════════════════════════════════════════════════════════
# Exit logic (executed bar-by-bar inside the scan loop)
# ════════════════════════════════════════════════════════════════════

def _regime_exit_triggered(df: pd.DataFrame, t: int,
                           params: KeposParams) -> bool:
    """η_smooth below ETA_EXIT for the last N bars ending at t (inclusive)."""
    need = params.eta_exit_sustained_bars
    if t + 1 < need:
        return False
    window = df["eta_smooth"].iloc[t + 1 - need : t + 1].values
    if np.any(np.isnan(window)):
        return False
    return bool(np.all(window < params.eta_exit))


def _resolve_exit(df: pd.DataFrame, bar_idx: int,
                  entry_idx: int, direction: int,
                  entry: float, stop: float, tp: float,
                  params: KeposParams) -> Optional[tuple[str, float]]:
    """Check exit conditions at bar `bar_idx`. Return (reason, price) or None.

    Precedence within the bar:
      1. Stop hit (conservative: stop wins if both stop & tp in same bar)
      2. Take-profit hit
      3. Regime exit (η fallback sustained low)
      4. Time stop (bars_in_trade ≥ MAX)
    """
    high = float(df["high"].iloc[bar_idx])
    low = float(df["low"].iloc[bar_idx])
    close = float(df["close"].iloc[bar_idx])

    stop_hit = (low <= stop) if direction == +1 else (high >= stop)
    tp_hit = (high >= tp) if direction == +1 else (low <= tp)

    if stop_hit:
        return "stop", stop
    if tp_hit:
        return "tp", tp
    if _regime_exit_triggered(df, bar_idx, params):
        return "regime_exit", close
    if (bar_idx - entry_idx) >= params.max_bars_in_trade:
        return "time_stop", close
    return None


# ════════════════════════════════════════════════════════════════════
# Scan a single symbol
# ════════════════════════════════════════════════════════════════════

def scan_symbol(df: pd.DataFrame, symbol: str,
                params: Optional[KeposParams] = None,
                initial_equity: float = ACCOUNT_SIZE) -> tuple[list, dict]:
    """Scan one symbol's DataFrame, return (trades, veto_counts).

    Assumes df already passed `compute_features` (caller's responsibility).
    """
    params = params or KeposParams()
    trades: list[dict] = []
    vetos: dict[str, int] = defaultdict(int)

    if len(df) < params.hawkes_window_bars + params.price_lookback + 10:
        log.warning("%s: too few bars (%d); skipping", symbol, len(df))
        return [], {"too_few_bars": 1}

    account = float(initial_equity)
    n = len(df)
    min_idx = max(
        params.hawkes_window_bars,
        params.price_sigma_window,
        params.atr_mean_window,
        200,
    )

    funding_periods_per_8h = 8 * 60 / _TF_MINUTES.get(params.interval, 15)

    open_trade: Optional[dict] = None

    for t in range(min_idx, n - 1):
        if open_trade is not None:
            resolved = _resolve_exit(
                df, t,
                entry_idx=open_trade["entry_idx"],
                direction=open_trade["direction"],
                entry=open_trade["entry"],
                stop=open_trade["stop"],
                tp=open_trade["tp"],
                params=params,
            )
            if resolved is not None:
                reason, exit_price = resolved
                duration = t - open_trade["entry_idx"]
                pnl = _pnl_with_costs(
                    direction=open_trade["direction"],
                    entry=open_trade["entry"],
                    exit_p=exit_price,
                    size=open_trade["size"],
                    duration=duration,
                    funding_periods_per_8h=funding_periods_per_8h,
                )
                account = max(account + pnl, 0.0)
                open_trade.update({
                    "exit_idx": t,
                    "exit_time": df["time"].iloc[t] if "time" in df.columns else None,
                    "exit_price": round(exit_price, 6),
                    "exit_reason": reason,
                    "duration": duration,
                    "pnl": round(pnl, 4),
                    "result": "WIN" if pnl > 0 else "LOSS",
                    "account_after": round(account, 2),
                })
                trades.append(open_trade)
                if _tl.handlers:
                    _tl.info(
                        "  %s %s %+d  exit=%s  pnl=%+.2f  dur=%dbars",
                        symbol,
                        open_trade.get("entry_time", ""),
                        open_trade["direction"],
                        reason,
                        pnl,
                        duration,
                    )
                open_trade = None
            else:
                continue  # still holding

        # Already holding? skip signal check
        if open_trade is not None:
            continue

        direction = decide_direction(df, t, params)
        if direction == 0:
            vetos["no_signal"] += 1
            continue

        levels = calc_levels(df, t, direction, params)
        if levels is None:
            vetos["levels_unavailable"] += 1
            continue
        entry, stop, tp = levels

        size = kepos_size(account, entry, stop, target_pct=params.max_pct_equity)
        if size <= 0:
            vetos["size_zero"] += 1
            continue

        # Clamp size so notional never exceeds account * LEVERAGE. Tight
        # stops can push fixed-risk size above the notional ceiling; when
        # that happens we cap size rather than veto the trade (effective
        # risk becomes < target_pct, which is conservative).
        max_notional = account * LEVERAGE
        if size * entry > max_notional and entry > 0:
            size = round(max_notional / entry, 4)
            if size <= 0:
                vetos["size_zero_after_cap"] += 1
                continue

        open_trade = {
            "symbol": symbol,
            "direction": direction,
            "entry_idx": t + 1,
            "entry_time": df["time"].iloc[t + 1] if "time" in df.columns else None,
            "entry": round(entry, 6),
            "stop": round(stop, 6),
            "tp": round(tp, 6),
            "size": round(size, 4),
            "eta_at_entry": float(df["eta_smooth"].iloc[t]),
            "price_ext_sigma": float(df["kepos_price_ext_sigma"].iloc[t]),
            "atr_ratio": float(df["kepos_atr_ratio"].iloc[t]),
            "atr": float(df["atr"].iloc[t]),
            "account_at_entry": round(account, 2),
            "eta_label": label_eta(float(df["eta_smooth"].iloc[t])),
        }

    # Mark-to-market any trade still open at the end
    if open_trade is not None:
        exit_idx = len(df) - 1
        exit_price = float(df["close"].iloc[exit_idx])
        duration = exit_idx - open_trade["entry_idx"]
        pnl = _pnl_with_costs(
            direction=open_trade["direction"],
            entry=open_trade["entry"],
            exit_p=exit_price,
            size=open_trade["size"],
            duration=duration,
            funding_periods_per_8h=funding_periods_per_8h,
        )
        account = max(account + pnl, 0.0)
        open_trade.update({
            "exit_idx": exit_idx,
            "exit_time": df["time"].iloc[exit_idx] if "time" in df.columns else None,
            "exit_price": round(exit_price, 6),
            "exit_reason": "forced_mtm",
            "duration": duration,
            "pnl": round(pnl, 4),
            "result": "WIN" if pnl > 0 else "LOSS",
            "account_after": round(account, 2),
            "forced_mtm": True,
        })
        trades.append(open_trade)

    return trades, dict(vetos)


def _pnl_with_costs(direction: int, entry: float, exit_p: float, size: float,
                    duration: int, funding_periods_per_8h: float) -> float:
    """AURUM C1+C2 cost model. Matches citadel.py (see lines 336-349).

    C1: commission paid on entry and exit notional
    C2: slippage + spread paid on exit (market-order exit assumption)
    Funding: accrued per bar, sign depends on direction (long pays funding)
    LEVERAGE: linearly scales the net P&L
    """
    slip_exit = SLIPPAGE + SPREAD
    if direction == +1:
        entry_cost = entry * (1 + COMMISSION)
        exit_net = exit_p * (1 - COMMISSION - slip_exit)
        funding = -(size * entry * FUNDING_PER_8H * duration / funding_periods_per_8h)
        pnl = size * (exit_net - entry_cost) + funding
    else:
        entry_cost = entry * (1 - COMMISSION)
        exit_net = exit_p * (1 + COMMISSION + slip_exit)
        funding = +(size * entry * FUNDING_PER_8H * duration / funding_periods_per_8h)
        pnl = size * (entry_cost - exit_net) + funding
    return float(pnl * LEVERAGE)


# ════════════════════════════════════════════════════════════════════
# Backtest orchestrator
# ════════════════════════════════════════════════════════════════════

def run_backtest(
    all_dfs: dict[str, pd.DataFrame],
    params: Optional[KeposParams] = None,
    initial_equity: float = ACCOUNT_SIZE,
) -> tuple[list, dict, dict]:
    """Run KEPOS scan across all symbols. Returns (trades, vetos, per_sym_stats)."""
    params = params or KeposParams()
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
# Simple reporting (no MC/WF here — delegated to tools/ if needed)
# ════════════════════════════════════════════════════════════════════

def compute_summary(trades: list[dict], initial_equity: float = ACCOUNT_SIZE
                    ) -> dict:
    """Core performance metrics. No analysis.* dependencies — keep it tight."""
    n = len(trades)
    if n == 0:
        return {
            "n_trades": 0,
            "win_rate": 0.0,
            "pnl": 0.0,
            "roi_pct": 0.0,
            "final_equity": initial_equity,
            "max_dd_pct": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
        }

    pnls = np.asarray([t["pnl"] for t in trades], dtype=float)
    wins = int(np.sum(pnls > 0))
    wr = wins / n * 100.0
    total_pnl = float(pnls.sum())
    final_eq = initial_equity + total_pnl
    roi = total_pnl / initial_equity * 100.0

    equity_curve = initial_equity + np.cumsum(pnls)
    peak = np.maximum.accumulate(equity_curve)
    dd = (peak - equity_curve) / peak
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
# Persistence (data/kepos/<run_id>/...)
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
             params: KeposParams, vetos: dict, per_sym: dict,
             meta: dict) -> None:
    """Save artefacts to `run_dir`. Uses run_manager helpers when available
    but keeps our own simple JSON dump as a fallback (disciplined: we don't
    depend on CITADEL's full reporting pipeline)."""
    run_dir.mkdir(parents=True, exist_ok=True)

    serializable = _trades_to_serializable(trades)
    atomic_write(run_dir / "trades.json",
                 json.dumps(serializable, separators=(",", ":"), default=str))

    payload = {
        "engine": "KEPOS",
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

    # Try run_manager integration (optional — we don't require it)
    try:
        from core.run_manager import append_to_index, snapshot_config
        config_snapshot = snapshot_config()
        config_snapshot["KEPOS_PARAMS"] = asdict(params)
        append_to_index(run_dir, {
            **summary,
            "engine": "KEPOS",
            "basket": meta.get("basket"),
            "interval": params.interval,
            "period_days": meta.get("scan_days"),
            "n_symbols": len(per_sym),
            "account_size": ACCOUNT_SIZE,
            "leverage": LEVERAGE,
        }, config_snapshot, overfit_results=None)
    except Exception as e:  # pragma: no cover
        log.warning("append_to_index failed: %s", e)


# ════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════

def _setup_logging(run_dir: Path) -> None:
    fmt = logging.Formatter("%(asctime)s  %(levelname)s  %(message)s")
    fh = logging.FileHandler(run_dir / "log.txt", encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.setLevel(logging.INFO)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    # Avoid double handlers across multiple runs in same process
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(fh)
    root.addHandler(sh)

    th = logging.FileHandler(run_dir / "trades.log", encoding="utf-8")
    th.setFormatter(logging.Formatter("%(message)s"))
    _tl.handlers = [th]
    _tl.setLevel(logging.DEBUG)
    _tl.propagate = False


def _print_banner(basket: str, symbols: list[str], days: int,
                  n_candles: int, params: KeposParams) -> None:
    print()
    print("  ╔════════════════════════════════════════════════════════════╗")
    print("  ║ KEPOS · Critical Endogeneity Fade · AURUM Finance           ║")
    print("  ╠════════════════════════════════════════════════════════════╣")
    print(f"  ║ UNIVERSE   {len(symbols)} assets (basket: {basket})")
    print(f"  ║ PERIOD     {days} days · {n_candles:,} candles/asset")
    print(f"  ║ TIMEFRAME  {params.interval}")
    print(f"  ║ CAPITAL    ${ACCOUNT_SIZE:,.0f} · {LEVERAGE}x leverage")
    print(f"  ║ SIZING     fixed {params.max_pct_equity*100:.1f}% equity risk/trade (local)")
    print(f"  ║ ENTRY      η≥{params.eta_critical} sustained {params.eta_sustained_bars}b")
    print(f"  ║            + |cum{params.price_lookback}|>{params.price_ext_sigma}σ")
    print(f"  ║            + atr_ratio>{params.atr_expansion_ratio}")
    print(f"  ║ EXIT       stop {params.stop_atr_mult}xATR · tp {params.tp_atr_mult}xATR")
    print(f"  ║            regime_exit η<{params.eta_exit} · time_stop {params.max_bars_in_trade}b")
    print("  ╚════════════════════════════════════════════════════════════╝")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="KEPOS — Critical Endogeneity Fade")
    ap.add_argument("--days", type=int, default=SCAN_DAYS,
                    help="Scan period in days")
    ap.add_argument("--basket", type=str, default="bluechip",
                    help="Asset basket name (keys of BASKETS in config.params)")
    ap.add_argument("--interval", type=str, default=None,
                    help="Timeframe override (e.g. 1h, 15m). Default from config.params")
    ap.add_argument("--no-menu", action="store_true",
                    help="Disable post-run menu (kept for launcher compatibility)")
    # Regime-threshold overrides. Defaults match Filimonov-Sornette 2012 tick
    # literature; candle-level measurements usually need local calibration
    # (empirically η tops out around 0.84 on BTC 15m candles — see 2026-04-16
    # diagnostic run).
    ap.add_argument("--k-sigma", type=float, default=None,
                    help="Hawkes jump-detection threshold in σ units")
    ap.add_argument("--eta-critical", type=float, default=None,
                    help="η threshold for CRITICAL regime")
    ap.add_argument("--eta-exit", type=float, default=None,
                    help="η threshold for regime exit (must be < eta-critical)")
    ap.add_argument("--eta-sustained", type=int, default=None,
                    help="Bars of sustained η>=critical required to fire entry")
    args = ap.parse_known_args()[0]

    basket_name = args.basket or "default"
    symbols = BASKETS.get(basket_name, SYMBOLS)
    scan_days = int(args.days)
    interval = args.interval or INTERVAL
    tf_min = max(1, _TF_MINUTES.get(interval, 15))
    n_candles = scan_days * 24 * 60 // tf_min

    # Run dir
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    run_id = f"kepos_{stamp}"
    from config.paths import DATA_DIR
    run_dir = DATA_DIR / "kepos" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _setup_logging(run_dir)

    params = KeposParams()
    params.interval = interval
    if args.k_sigma is not None:
        params.hawkes_k_sigma = float(args.k_sigma)
    if args.eta_critical is not None:
        params.eta_critical = float(args.eta_critical)
    if args.eta_exit is not None:
        params.eta_exit = float(args.eta_exit)
    if args.eta_sustained is not None:
        params.eta_sustained_bars = int(args.eta_sustained)
    if params.eta_exit >= params.eta_critical:
        raise SystemExit(
            f"eta_exit ({params.eta_exit}) must be < eta_critical "
            f"({params.eta_critical}) for hysteresis to make sense"
        )
    _print_banner(basket_name, symbols, scan_days, n_candles, params)

    # Fetch
    print(f"  fetching {len(symbols)} symbols @ {interval} ...")
    all_dfs = fetch_all(symbols, interval=interval,
                        n_candles=n_candles, futures=True)
    if not all_dfs:
        print("  no data fetched.")
        return 1
    for s, df in all_dfs.items():
        validate(df, s)

    # Backtest
    print(f"  running scan on {len(all_dfs)} symbols ...")
    all_trades, vetos, per_sym = run_backtest(all_dfs, params, ACCOUNT_SIZE)
    summary = compute_summary(all_trades, ACCOUNT_SIZE)

    # Print summary
    print()
    print(f"  ┌─ KEPOS summary ({run_id}) " + "─" * 28 + "┐")
    print(f"  │ trades      {summary['n_trades']:>10d}")
    print(f"  │ win rate    {summary['win_rate']:>9.1f}%")
    print(f"  │ ROI         {summary['roi_pct']:>+9.2f}%")
    print(f"  │ PnL         ${summary['pnl']:>+12,.2f}")
    print(f"  │ final eq    ${summary['final_equity']:>12,.2f}")
    print(f"  │ max DD      {summary['max_dd_pct']:>9.2f}%")
    print(f"  │ Sharpe      {summary['sharpe']:>10.3f}")
    print(f"  │ Sortino     {summary['sortino']:>10.3f}")
    print("  └" + "─" * 54 + "┘")
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

    save_run(run_dir, all_trades, summary, params, vetos, per_sym,
             meta={"run_id": run_id, "basket": basket_name,
                   "scan_days": scan_days, "symbols": list(all_dfs.keys())})
    print(f"\n  run → {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
