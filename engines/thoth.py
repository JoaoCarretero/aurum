"""
AURUM Finance — THOTH Engine v1.0
Sentiment Quantificado

Conceito: extremos de sentiment precedem reversões.
Combina funding rate, open interest e long/short ratio com regime macro.

Pipeline:
  1. Fetch funding rate → z-score → contrarian signal
  2. Fetch OI → delta vs price → accumulation/squeeze detection
  3. Fetch LS ratio → contrarian signal
  4. Composite score → combine com technical (structure + vol regime)
  5. Entry quando sentiment + técnico concordam
"""
import sys
import math
import logging
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.params import *
from core import (
    fetch_all, validate, indicators, swing_structure, omega,
    detect_macro, build_corr_matrix, portfolio_allows, position_size,
    calc_levels, label_trade,
)
from core.sentiment import (
    fetch_funding_rate, fetch_open_interest, fetch_long_short_ratio,
    funding_zscore, oi_delta_signal, ls_ratio_signal, composite_sentiment,
)
from analysis.stats import equity_stats, calc_ratios
from analysis.montecarlo import monte_carlo
from analysis.walkforward import walk_forward

log = logging.getLogger("THOTH")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
    log.addHandler(_h)

SEP = "─" * 80

# ── RUN IDENTITY ─────────────────────────────────────────────
RUN_ID  = datetime.now().strftime("%Y-%m-%d_%H%M")
RUN_DIR = Path(f"data/thoth/{RUN_ID}")
(RUN_DIR / "reports").mkdir(parents=True, exist_ok=True)
(RUN_DIR / "logs").mkdir(parents=True, exist_ok=True)

_fh = logging.FileHandler(RUN_DIR / "logs" / "thoth.log", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
log.addHandler(_fh)


# ══════════════════════════════════════════════════════════════
#  SENTIMENT DATA COLLECTION
# ══════════════════════════════════════════════════════════════

def collect_sentiment(symbols: list) -> dict:
    """
    Fetch all sentiment data for each symbol.
    Returns dict[symbol] = {funding_z: Series, oi_signal: Series, ls_signal: Series}
    """
    sentiment = {}
    for sym in symbols:
        log.info(f"  fetching sentiment  ·  {sym}")
        data = {}

        # Funding rate
        fr_df = fetch_funding_rate(sym, limit=100)
        if fr_df is not None and len(fr_df) >= 10:
            data["funding_df"] = fr_df
            data["funding_z"] = funding_zscore(fr_df, window=THOTH_FUNDING_WINDOW)
        else:
            data["funding_z"] = None

        # Open Interest
        oi_df = fetch_open_interest(sym, period="15m", limit=200)
        data["oi_df"] = oi_df

        # Long/Short ratio
        ls_df = fetch_long_short_ratio(sym, period="15m", limit=200)
        if ls_df is not None and len(ls_df) >= 5:
            data["ls_signal"] = ls_ratio_signal(ls_df)
            data["ls_df"] = ls_df
        else:
            data["ls_signal"] = None

        sentiment[sym] = data
        log.info(f"    funding={'✓' if data.get('funding_z') is not None else '✗'}  "
                 f"oi={'✓' if oi_df is not None else '✗'}  "
                 f"ls={'✓' if data.get('ls_signal') is not None else '✗'}")

    return sentiment


# ══════════════════════════════════════════════════════════════
#  SCAN ENGINE
# ══════════════════════════════════════════════════════════════

def scan_thoth(df: pd.DataFrame, symbol: str,
               macro_bias_series, corr: dict,
               htf_stack_dfs: dict | None = None,
               sentiment_data: dict | None = None) -> tuple[list, dict]:
    """
    Scan a symbol using sentiment + technical confirmation.
    """
    # ── prepare indicators ──
    df = indicators(df)
    df = swing_structure(df)
    df = omega(df)

    trades  = []
    vetos   = defaultdict(int)
    account = ACCOUNT_SIZE
    min_idx = max(200, W_NORM, PIVOT_N * 3) + 10

    # Get sentiment data for this symbol
    sent = (sentiment_data or {}).get(symbol, {})
    funding_z_series = sent.get("funding_z")
    oi_df = sent.get("oi_df")
    ls_signal_series = sent.get("ls_signal")

    # Build OI signal if available
    oi_signal_df = None
    if oi_df is not None and len(oi_df) >= 10:
        try:
            oi_signal_df = oi_delta_signal(oi_df, df, window=THOTH_OI_WINDOW)
        except Exception:
            pass

    open_pos: list[tuple[int, str]] = []

    # pre-extract arrays
    _rsi   = df["rsi"].values
    _atr   = df["atr"].values
    _volr  = df["vol_regime"].values
    _str   = df["trend_struct"].values
    _stre  = df["struct_strength"].values
    _trans = df["regime_transition"].values
    _cls   = df["close"].values
    _tkma  = df["taker_ma"].values
    _dist  = df["dist_ema21"].values

    peak_equity        = ACCOUNT_SIZE
    consecutive_losses = 0
    cooldown_until     = -1
    sym_cooldown_until: dict[str, int] = {}

    log.info(f"\n{'─'*60}\n  {symbol}\n{'─'*60}")

    for idx in range(min_idx, len(df) - MAX_HOLD - 2):
        open_pos = [(ei, s) for ei, s in open_pos if ei > idx]
        active_syms = [s for _, s in open_pos]

        macro_b = "CHOP"
        if macro_bias_series is not None:
            macro_b = macro_bias_series.iloc[min(idx, len(macro_bias_series) - 1)]

        peak_equity = max(peak_equity, account)
        current_dd = (peak_equity - account) / peak_equity if peak_equity > 0 else 0.0
        dd_scale = 1.0
        for dd_thresh in sorted(DD_RISK_SCALE.keys(), reverse=True):
            if current_dd >= dd_thresh:
                dd_scale = DD_RISK_SCALE[dd_thresh]
                break
        if dd_scale == 0.0:
            vetos["dd_pause"] += 1; continue

        if idx <= cooldown_until:
            vetos["streak_cooldown"] += 1; continue
        if idx <= sym_cooldown_until.get(symbol, -1):
            vetos["sym_cooldown"] += 1; continue

        ok, motivo_p, corr_size_mult = portfolio_allows(symbol, active_syms, corr)
        if not ok:
            vetos[motivo_p] += 1; continue

        vol_r = str(_volr[idx])
        if vol_r == "EXTREME":
            vetos["vol_extreme"] += 1; continue

        in_transition = bool(_trans[idx])
        trans_mult = REGIME_TRANS_SIZE_MULT if in_transition else 1.0

        # ── SENTIMENT SIGNAL ──
        # Get latest sentiment values (match by time or use latest available)
        candle_time = df["time"].iloc[idx]

        # Funding z-score
        f_z = 0.0
        if funding_z_series is not None and len(funding_z_series) > 0:
            f_z = float(funding_z_series.iloc[-1])  # use latest available

        # OI signal
        oi_sig = 0.0
        if oi_signal_df is not None and len(oi_signal_df) > 0:
            # find closest time
            time_diffs = (oi_signal_df["time"] - candle_time).abs()
            closest_idx = time_diffs.idxmin()
            oi_sig = float(oi_signal_df["oi_signal"].iloc[closest_idx])

        # LS signal
        ls_sig = 0.0
        if ls_signal_series is not None and len(ls_signal_series) > 0:
            ls_sig = float(ls_signal_series.iloc[-1])

        # Composite sentiment
        sent_score = composite_sentiment(
            f_z, oi_sig, ls_sig,
            THOTH_WEIGHT_FUNDING, THOTH_WEIGHT_OI, THOTH_WEIGHT_LS
        )

        # Direction from sentiment
        direction = None
        struct = _str[idx]

        if sent_score > 0.3:
            # bullish sentiment — confirm with struct or macro
            if struct == "UP" or macro_b == "BULL":
                direction = "BULLISH"
            elif struct != "DOWN":
                direction = "BULLISH"  # neutral struct is ok
        elif sent_score < -0.3:
            # bearish sentiment — confirm with struct or macro
            if struct == "DOWN" or macro_b == "BEAR":
                direction = "BEARISH"
            elif struct != "UP":
                direction = "BEARISH"

        if direction is None:
            vetos["no_signal"] += 1
            continue

        # Score: |sentiment| as quality metric
        score = min(abs(sent_score), 1.0)
        if score < THOTH_MIN_SCORE:
            vetos["score_baixo"] += 1; continue

        # Extra check: sentiment must be strong enough
        if abs(f_z) < 1.0 and abs(oi_sig) < 0.3 and abs(ls_sig) < 0.3:
            vetos["sentiment_fraco"] += 1; continue

        # ── LEVELS ──
        levels = calc_levels(df, idx, direction)
        if levels is None:
            vetos["niveis"] += 1; continue
        entry, stop, target, rr = levels

        # ── LABEL TRADE ──
        result, duration, exit_p = label_trade(df, idx + 1, direction, entry, stop, target)
        if result == "OPEN":
            continue

        # ── POSITION SIZE ──
        size = position_size(account, entry, stop, max(score, 0.53),
                             macro_b, direction, vol_r, dd_scale,
                             peak_equity=peak_equity)
        size = round(size * corr_size_mult * trans_mult * THOTH_SIZE_MULT, 4)

        # ── PnL ──
        ep = float(exit_p)
        slip_exit = SLIPPAGE + SPREAD
        if direction == "BULLISH":
            entry_cost = entry * (1 + COMMISSION)
            ep_net = ep * (1 - COMMISSION - slip_exit)
            funding = -(size * entry * FUNDING_PER_8H * duration / 32)
            pnl = size * (ep_net - entry_cost) + funding
        else:
            entry_cost = entry * (1 - COMMISSION)
            ep_net = ep * (1 + COMMISSION + slip_exit)
            funding = +(size * entry * FUNDING_PER_8H * duration / 32)
            pnl = size * (entry_cost - ep_net) + funding
        pnl = round(pnl * LEVERAGE, 2)
        account = max(account + pnl, account * 0.5)

        if result == "LOSS":
            consecutive_losses += 1
            for n_losses in sorted(STREAK_COOLDOWN.keys(), reverse=True):
                if consecutive_losses >= n_losses:
                    cooldown_until = idx + STREAK_COOLDOWN[n_losses]
                    break
            sym_cooldown_until[symbol] = idx + SYM_LOSS_COOLDOWN
        else:
            consecutive_losses = 0

        open_pos.append((idx + 1 + duration, symbol))

        ts = df["time"].iloc[idx].strftime("%d/%m %Hh")
        t = {
            "symbol":     symbol,
            "time":       ts,
            "timestamp":  df["time"].iloc[idx],
            "idx":        idx,
            "entry_idx":  idx + 1,
            "strategy":   "THOTH",
            "direction":  direction,
            "trade_type": "SENTIMENT",
            "struct":     struct,
            "struct_str": round(float(_stre[idx]), 3),
            "cascade_n":  0,
            "taker_ma":   round(float(_tkma[idx]), 4),
            "rsi":        round(float(_rsi[idx]), 2),
            "dist_ema21": round(float(_dist[idx]), 3),
            "macro_bias": macro_b,
            "vol_regime": vol_r,
            "dd_scale":   round(dd_scale, 2),
            "corr_mult":  round(corr_size_mult, 2),
            "in_transition": in_transition,
            "trans_mult":    round(trans_mult, 2),
            "entry":      entry, "stop": stop, "target": target,
            "exit_p":     round(float(exit_p), 6),
            "rr":         rr, "duration": duration, "result": result, "pnl": pnl,
            "size":       round(size, 4),
            "score":      round(score, 3),
            "fractal_align": 1.0,
            "omega_struct":   0.0, "omega_flow":     0.0,
            "omega_cascade":  0.0, "omega_momentum": 0.0,
            "omega_pullback": 0.0,
            "chop_trade":     False,
            "bb_mid":         0.0,
            # thoth-specific
            "funding_z":      round(f_z, 3),
            "oi_signal":      round(oi_sig, 3),
            "ls_signal":      round(ls_sig, 3),
            "sentiment":      round(sent_score, 3),
            "trade_time":     ts,
        }
        trades.append(t)
        icon = "✓" if result == "WIN" else "✗"
        log.info(f"  {ts}  {icon}  {direction:8s}  sent={sent_score:+.2f}  "
                 f"fz={f_z:+.1f}  oi={oi_sig:+.1f}  ls={ls_sig:+.1f}  ${pnl:+.2f}")

    closed = [t for t in trades if t["result"] in ("WIN", "LOSS")]
    w = sum(1 for t in closed if t["result"] == "WIN")
    log.info(f"  {symbol} TOTAL: {len(trades)}  W={w}  L={len(closed)-w}  "
             f"PnL=${sum(t['pnl'] for t in closed):+,.0f}")
    return trades, dict(vetos)


# ══════════════════════════════════════════════════════════════
#  RESULTS & EXPORT
# ══════════════════════════════════════════════════════════════

def print_header():
    print(f"\n{SEP}")
    print(f"  THOTH v1.0  ·  {RUN_ID}")
    print(f"  {len(SYMBOLS)} ativos  ·  {INTERVAL}  ·  ${ACCOUNT_SIZE:,.0f}  ·  {LEVERAGE}x")
    print(f"  funding w={THOTH_WEIGHT_FUNDING}  oi w={THOTH_WEIGHT_OI}  ls w={THOTH_WEIGHT_LS}")
    print(f"  {RUN_DIR}/")
    print(SEP)


def print_results(all_trades: list):
    closed = [t for t in all_trades if t["result"] in ("WIN", "LOSS")]
    if not closed:
        print("  sem trades"); return

    print(f"\n{SEP}\n  RESULTADOS POR SIMBOLO\n{SEP}")
    by_sym: dict[str, list] = {}
    for t in closed:
        by_sym.setdefault(t["symbol"], []).append(t)

    for sym in sorted(by_sym):
        ts = by_sym[sym]
        w = sum(1 for t in ts if t["result"] == "WIN")
        wr = w / len(ts) * 100
        pnl = sum(t["pnl"] for t in ts)
        c = "✓" if pnl > 0 else "✗"
        print(f"  {c}  {sym:12s}  n={len(ts):>3d}  WR={wr:>5.1f}%  ${pnl:>+10,.0f}")


def export_json(all_trades, eq, mc, ratios):
    import json
    closed = [t for t in all_trades if t["result"] in ("WIN", "LOSS")]
    wr = sum(1 for t in closed if t["result"] == "WIN") / max(len(closed), 1) * 100

    data = {
        "engine": "THOTH",
        "version": "1.0",
        "run_id": RUN_ID,
        "timestamp": datetime.now().isoformat(),
        "interval": INTERVAL,
        "n_symbols": len(SYMBOLS),
        "account_size": ACCOUNT_SIZE,
        "leverage": LEVERAGE,
        "n_trades": len(closed),
        "win_rate": round(wr, 2),
        "roi": round(ratios["ret"], 2),
        "sharpe": ratios["sharpe"],
        "sortino": ratios.get("sortino"),
        "final_equity": round(eq[-1], 2) if eq else ACCOUNT_SIZE,
        "trades": [{k: (v.isoformat() if isinstance(v, pd.Timestamp) else
                        float(v) if isinstance(v, (np.floating, np.integer)) else v)
                    for k, v in t.items()} for t in closed],
    }

    out = RUN_DIR / "reports" / f"thoth_{INTERVAL}_v1.json"
    out.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print(f"  json  ·  {out}")

    try:
        from core.db import register_run
        register_run(
            run_id=RUN_ID, engine="thoth", json_path=str(out),
            roi=ratios["ret"], sharpe=ratios.get("sharpe"),
            sortino=ratios.get("sortino"), win_rate=wr,
            n_trades=len(closed), final_equity=eq[-1] if eq else ACCOUNT_SIZE,
            account_size=ACCOUNT_SIZE, interval=INTERVAL,
            n_symbols=len(SYMBOLS), version="1.0",
        )
    except Exception as e:
        log.warning(f"DB register failed: {e}")


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"\n{SEP}")
    print(f"  THOTH  ·  Sentiment Quantificado")
    print(f"  {SEP}")

    _days_in = input(f"\n  periodo em dias [{SCAN_DAYS}] > ").strip()
    if _days_in.isdigit() and 7 <= int(_days_in) <= 1500:
        SCAN_DAYS = int(_days_in)
    N_CANDLES = SCAN_DAYS * 24 * 4

    _lev_in = input(f"  leverage [{LEVERAGE}x] > ").strip()
    if _lev_in:
        try:
            _lev_val = float(_lev_in.replace("x", ""))
            if 0.1 <= _lev_val <= 125:
                LEVERAGE = _lev_val
        except ValueError:
            pass

    print(f"\n{SEP}")
    print(f"  THOTH  ·  {SCAN_DAYS}d  ·  {len(SYMBOLS)} ativos  ·  {INTERVAL}")
    print(f"  ${ACCOUNT_SIZE:,.0f}  ·  {LEVERAGE}x")
    print(f"  {RUN_DIR}/")
    print(SEP)
    input("  enter para iniciar... ")

    log.info(f"THOTH v1.0 iniciado — {RUN_ID}  tf={INTERVAL}  dias={SCAN_DAYS}")

    # ── FETCH OHLCV ──
    print(f"\n{SEP}\n  DADOS   {INTERVAL}   {N_CANDLES:,} candles\n{SEP}")
    all_dfs = fetch_all(SYMBOLS, INTERVAL, N_CANDLES)
    for sym, df in all_dfs.items():
        validate(df, sym)
    if not all_dfs:
        print("  sem dados"); sys.exit(1)

    macro_bias = detect_macro(all_dfs)
    corr = build_corr_matrix(all_dfs)

    # ── FETCH SENTIMENT ──
    print(f"\n{SEP}\n  SENTIMENT DATA\n{SEP}")
    sentiment_data = collect_sentiment(list(all_dfs.keys()))

    print_header()

    # ── SCAN ──
    print(f"\n{SEP}\n  SCAN SENTIMENT\n{SEP}")
    all_trades = []
    all_vetos = defaultdict(int)

    for sym, df in all_dfs.items():
        trades, vetos = scan_thoth(df.copy(), sym, macro_bias, corr,
                                   sentiment_data=sentiment_data)
        all_trades.extend(trades)
        for k, v in vetos.items():
            all_vetos[k] += v

    all_trades.sort(key=lambda t: t["timestamp"])

    closed = [t for t in all_trades if t["result"] in ("WIN", "LOSS")]
    if not closed:
        print(f"\n  sem trades fechados"); sys.exit(1)

    print_results(all_trades)

    # ── METRICS ──
    pnl_list = [t["pnl"] for t in closed]
    eq, mdd, mdd_pct, max_streak = equity_stats(pnl_list)
    ratios = calc_ratios(pnl_list, n_days=SCAN_DAYS)

    wr = sum(1 for t in closed if t["result"] == "WIN") / len(closed) * 100

    print(f"\n{SEP}\n  METRICAS\n{SEP}")
    print(f"  Trades    {len(closed)}")
    print(f"  WR        {wr:.1f}%")
    print(f"  ROI       {ratios['ret']:+.2f}%")
    print(f"  Sharpe    {ratios['sharpe']:.3f}" if ratios["sharpe"] else "  Sharpe    —")
    print(f"  MaxDD     {mdd_pct:.1f}%")
    print(f"  Final     ${eq[-1]:,.0f}")

    mc = monte_carlo(pnl_list)
    wf = walk_forward(closed)

    export_json(all_trades, eq, mc, ratios)

    if all_vetos:
        print(f"\n{SEP}\n  VETOS\n{SEP}")
        for k, v in sorted(all_vetos.items(), key=lambda x: -x[1])[:10]:
            print(f"  {v:>6d}  {k}")

    print(f"\n{SEP}\n  output  ·  {RUN_DIR}/\n{SEP}\n")
