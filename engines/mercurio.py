"""
AURUM Finance — MERCURIO Engine v1.0
Order Flow / Microstructure Analysis

Conceito: edge do fluxo de ordens — quem está a comprar/vender agressivamente.
Tudo derivado de OHLCV + tbb (taker buy base) que já temos.

Pipeline:
  1. CVD (Cumulative Volume Delta)
  2. CVD Divergence (preço vs fluxo)
  3. Volume Imbalance (taker buy ratio)
  4. Liquidation Proxy (spikes de volume + ATR)
  5. Entry: divergence + imbalance + structure alignment
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
from core.chronos import enrich_with_regime
from core import (
    fetch_all, validate, indicators, swing_structure, omega,
    cvd, cvd_divergence, volume_imbalance, liquidation_proxy,
    detect_macro, build_corr_matrix, portfolio_allows, check_aggregate_notional,
    position_size,
    calc_levels, label_trade,
)
from analysis.stats import equity_stats, calc_ratios
from analysis.montecarlo import monte_carlo
from analysis.walkforward import walk_forward, walk_forward_by_regime

log = logging.getLogger("JUMP")  # JUMP (formerly MERCURIO) — Order flow engine
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
    log.addHandler(_h)

SEP = "─" * 80

# ── RUN IDENTITY ─────────────────────────────────────────────
RUN_ID  = datetime.now().strftime("%Y-%m-%d_%H%M")
RUN_DIR = Path(f"data/mercurio/{RUN_ID}")
(RUN_DIR / "reports").mkdir(parents=True, exist_ok=True)
(RUN_DIR / "logs").mkdir(parents=True, exist_ok=True)

_fh = logging.FileHandler(RUN_DIR / "logs" / "mercurio.log", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
log.addHandler(_fh)


# ══════════════════════════════════════════════════════════════
#  SCAN ENGINE
# ══════════════════════════════════════════════════════════════

def scan_mercurio(df: pd.DataFrame, symbol: str,
                  macro_bias_series, corr: dict,
                  htf_stack_dfs: dict | None = None) -> tuple[list, dict]:
    """
    Scan a symbol for order-flow based entries.
    Same interface as scan_symbol / scan_hermes.
    """
    # ── prepare indicators ──
    df = indicators(df)
    df = swing_structure(df)
    df = omega(df)
    df = enrich_with_regime(df)
    df = cvd(df)
    df = cvd_divergence(df, lookback=MERCURIO_CVD_DIV_BARS)
    df = volume_imbalance(df, window=MERCURIO_VIMB_WINDOW)
    df = liquidation_proxy(df, vol_mult=MERCURIO_LIQ_VOL_MULT,
                           atr_mult=MERCURIO_LIQ_ATR_MULT)

    trades  = []
    vetos   = defaultdict(int)
    account = ACCOUNT_SIZE
    min_idx = max(200, W_NORM, PIVOT_N * 3, MERCURIO_CVD_WINDOW) + 10

    # (exit_idx, symbol, size, entry) — size/entry needed for L6 cap
    open_pos: list[tuple[int, str, float, float]] = []

    # [Backlog #3] Dynamic funding period denominator per candle interval.
    _funding_periods_per_8h = 8 * 60 / _TF_MINUTES.get(INTERVAL, 15)

    # pre-extract arrays
    _cvd_div_bull = df["cvd_div_bull"].values
    _cvd_div_bear = df["cvd_div_bear"].values
    _vimb         = df["vimb"].values
    _liq          = df["liq_proxy"].values
    _vdelta       = df["vdelta"].values
    _rsi          = df["rsi"].values
    _atr          = df["atr"].values
    _volr         = df["vol_regime"].values
    _tkma         = df["taker_ma"].values
    _str          = df["trend_struct"].values
    _stre         = df["struct_strength"].values
    _trans        = df["regime_transition"].values
    _cls          = df["close"].values
    _sl21         = df["slope21"].values
    _dist         = df["dist_ema21"].values
    # HMM regime layer (observation-only)
    _hmm_lbl = df["hmm_regime_label"].values
    _hmm_cf  = df["hmm_confidence"].values
    _hmm_pb  = df["hmm_prob_bull"].values
    _hmm_pbr = df["hmm_prob_bear"].values
    _hmm_pc  = df["hmm_prob_chop"].values

    peak_equity        = ACCOUNT_SIZE
    consecutive_losses = 0
    cooldown_until     = -1
    sym_cooldown_until: dict[str, int] = {}

    log.info(f"\n{'─'*60}\n  {symbol}\n{'─'*60}")

    for idx in range(min_idx, len(df) - MAX_HOLD - 2):
        open_pos = [(ei, s, sz, en) for ei, s, sz, en in open_pos if ei > idx]
        active_syms = [s for _, s, _, _ in open_pos]

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

        # ── ORDER FLOW SIGNAL ──
        div_bull = _cvd_div_bull[idx]
        div_bear = _cvd_div_bear[idx]
        vimb     = _vimb[idx]
        liq      = _liq[idx]
        struct   = _str[idx]

        direction = None
        score_components = {}

        # CVD trend (rolling sum of vdelta)
        cvd_window = min(MERCURIO_CVD_WINDOW, idx)
        cvd_sum = np.sum(_vdelta[max(0, idx - cvd_window):idx + 1])
        cvd_trend = "BULL" if cvd_sum > 0 else "BEAR"

        # LONG signal: CVD bullish divergence + volume imbalance > threshold + struct UP
        if div_bull > 0 and vimb >= MERCURIO_VIMB_LONG and struct == "UP":
            direction = "BULLISH"
            score_components = {
                "cvd_div": float(div_bull),
                "vimb": float(vimb),
                "struct_align": 1.0,
                "liq_boost": float(liq),
                "cvd_trend": 1.0 if cvd_trend == "BULL" else 0.3,
            }

        # SHORT signal: CVD bearish divergence + volume imbalance < threshold + struct DOWN
        elif div_bear > 0 and vimb <= MERCURIO_VIMB_SHORT and struct == "DOWN":
            direction = "BEARISH"
            score_components = {
                "cvd_div": float(div_bear),
                "vimb": float(1 - vimb),
                "struct_align": 1.0,
                "liq_boost": float(liq),
                "cvd_trend": 1.0 if cvd_trend == "BEAR" else 0.3,
            }

        if direction is None:
            continue

        # composite score
        score = (
            0.30 * score_components["cvd_div"] +
            0.25 * score_components["vimb"] +
            0.20 * score_components["struct_align"] +
            0.15 * score_components["cvd_trend"] +
            0.10 * score_components["liq_boost"]
        )

        if score < MERCURIO_MIN_SCORE:
            vetos["score_baixo"] += 1; continue

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
        size = round(size * corr_size_mult * trans_mult * MERCURIO_SIZE_MULT, 4)

        # [L6] Aggregate notional cap across concurrently open positions.
        # Inert at LEVERAGE=1 (default), load-bearing when leverage scales.
        if size > 0:
            ok_agg, motivo_agg = check_aggregate_notional(
                size * entry, open_pos, account, LEVERAGE)
            if not ok_agg:
                vetos[motivo_agg] += 1
                continue

        # ── PnL ──
        ep = float(exit_p)
        slip_exit = SLIPPAGE + SPREAD
        if direction == "BULLISH":
            entry_cost = entry * (1 + COMMISSION)
            ep_net = ep * (1 - COMMISSION - slip_exit)
            funding = -(size * entry * FUNDING_PER_8H * duration / _funding_periods_per_8h)
            pnl = size * (ep_net - entry_cost) + funding
        else:
            entry_cost = entry * (1 - COMMISSION)
            ep_net = ep * (1 + COMMISSION + slip_exit)
            funding = +(size * entry * FUNDING_PER_8H * duration / _funding_periods_per_8h)
            pnl = size * (entry_cost - ep_net) + funding
        pnl = round(pnl * LEVERAGE, 2)
        # Apply real PnL. The previous `max(account + pnl, account * 0.5)`
        # silently clamped per-trade losses at 50% of pre-trade account,
        # inflating sharpe / maxDD / final equity in backtest reports.
        # Liquidation simulation, if needed, should be modelled at
        # position-open time against the real liquidation price.
        account = account + pnl

        if result == "LOSS":
            consecutive_losses += 1
            for n_losses in sorted(STREAK_COOLDOWN.keys(), reverse=True):
                if consecutive_losses >= n_losses:
                    cooldown_until = idx + STREAK_COOLDOWN[n_losses]
                    break
            sym_cooldown_until[symbol] = idx + SYM_LOSS_COOLDOWN
        else:
            consecutive_losses = 0

        open_pos.append((idx + 1 + duration, symbol, size, entry))

        ts = df["time"].iloc[idx].strftime("%d/%m %Hh")
        t = {
            "symbol":     symbol,
            "time":       ts,
            "timestamp":  df["time"].iloc[idx],
            "idx":        idx,
            "entry_idx":  idx + 1,
            "strategy":   "MERCURIO",
            "direction":  direction,
            "trade_type": "ORDER-FLOW",
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
            "omega_struct":   score_components.get("struct_align", 0),
            "omega_flow":     score_components.get("vimb", 0),
            "omega_cascade":  0.0,
            "omega_momentum": score_components.get("cvd_div", 0),
            "omega_pullback": score_components.get("cvd_trend", 0),
            "chop_trade":     False,
            "bb_mid":         0.0,
            # mercurio-specific
            "cvd_div_bull":   float(div_bull),
            "cvd_div_bear":   float(div_bear),
            "vimb":           round(float(vimb), 4),
            "liq_proxy":      float(liq),
            "cvd_trend":      cvd_trend,
            "trade_time":     ts,
            # Normalised trade outcome in R units — required by regime_analysis
            "r_multiple": (
                (float(exit_p) - entry) / (entry - stop)
                if direction == "BULLISH" and (entry - stop) != 0
                else (entry - float(exit_p)) / (stop - entry)
                if direction == "BEARISH" and (stop - entry) != 0
                else 0.0
            ),
            # HMM regime layer (observation-only)
            "hmm_regime":      (None if _hmm_lbl[idx] is None or (isinstance(_hmm_lbl[idx], float) and pd.isna(_hmm_lbl[idx])) else str(_hmm_lbl[idx])),
            "hmm_confidence":  (None if pd.isna(_hmm_cf[idx])  else round(float(_hmm_cf[idx]),  4)),
            "hmm_prob_bull":   (None if pd.isna(_hmm_pb[idx])  else round(float(_hmm_pb[idx]),  4)),
            "hmm_prob_bear":   (None if pd.isna(_hmm_pbr[idx]) else round(float(_hmm_pbr[idx]), 4)),
            "hmm_prob_chop":   (None if pd.isna(_hmm_pc[idx])  else round(float(_hmm_pc[idx]),  4)),
        }
        trades.append(t)
        icon = "✓" if result == "WIN" else "✗"
        log.info(f"  {ts}  {icon}  {direction:8s}  score={score:.3f}  "
                 f"vimb={vimb:.2f}  ${pnl:+.2f}")

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
    print(f"  MERCURIO v1.0  ·  {RUN_ID}")
    print(f"  {len(SYMBOLS)} ativos  ·  {INTERVAL}  ·  ${ACCOUNT_SIZE:,.0f}  ·  {LEVERAGE}x")
    print(f"  vimb L>{MERCURIO_VIMB_LONG} S<{MERCURIO_VIMB_SHORT}  ·  min score {MERCURIO_MIN_SCORE}")
    print(f"  {RUN_DIR}/")
    print(SEP)


def print_results(all_trades: list):
    closed = [t for t in all_trades if t["result"] in ("WIN", "LOSS")]
    if not closed:
        print("  sem trades")
        return

    print(f"\n{SEP}\n  RESULTADOS POR SIMBOLO\n{SEP}")
    by_sym: dict[str, list] = {}
    for t in closed:
        by_sym.setdefault(t["symbol"], []).append(t)

    print(f"  {'ATIVO':12s}  {'N':>4s}  {'WR':>6s}  {'PnL':>12s}")
    print(f"  {'─'*40}")
    for sym in sorted(by_sym):
        ts = by_sym[sym]
        w = sum(1 for t in ts if t["result"] == "WIN")
        wr = w / len(ts) * 100
        pnl = sum(t["pnl"] for t in ts)
        c = "✓" if pnl > 0 else "✗"
        print(f"  {c}  {sym:12s}  {len(ts):>4d}  {wr:>5.1f}%  ${pnl:>+10,.0f}")


def print_veredito(all_trades, eq, mdd_pct, mc, wf, ratios):
    closed = [t for t in all_trades if t["result"] in ("WIN", "LOSS")]
    wr = sum(1 for t in closed if t["result"] == "WIN") / max(len(closed), 1) * 100
    exp = sum(t["pnl"] for t in closed) / max(len(closed), 1)

    wf_ok = False
    if wf:
        pct_g = sum(1 for w in wf if abs(w["test"]["wr"] - w["train"]["wr"]) <= 15) / len(wf) * 100
        wf_ok = pct_g >= 60

    checks = [
        ("Trades suficientes (>=30)", len(closed) >= 30),
        ("Win Rate >= 50%", wr >= 50),
        ("Expectativa positiva", exp > 0),
        ("MaxDD < 20%", mdd_pct < 20),
        ("Sharpe >= 1.0", ratios["sharpe"] is not None and ratios["sharpe"] >= 1.0),
        ("Monte Carlo >= 70%", mc is not None and mc["pct_pos"] >= 70),
        ("Walk-Forward estavel", wf_ok),
    ]
    passou = sum(1 for _, v in checks if v)
    print(f"\n{SEP}\n  VEREDITO\n{SEP}")
    for nome, ok in checks:
        print(f"  {'✓' if ok else '✗'}  {nome}")
    verdict = ("EDGE CONFIRMADO" if passou >= 6
               else "PROMISSOR" if passou >= 4
               else "FRAGIL")
    print(f"\n  {passou}/7  ·  {verdict}\n{SEP}\n")
    log.info(f"Veredito: {passou}/7  ROI={ratios['ret']:.2f}%  WR={wr:.1f}%  MaxDD={mdd_pct:.1f}%")


def export_json(all_trades, eq, mc, ratios):
    import json
    closed = [t for t in all_trades if t["result"] in ("WIN", "LOSS")]
    wr = sum(1 for t in closed if t["result"] == "WIN") / max(len(closed), 1) * 100

    data = {
        "engine": "MERCURIO",
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

    out = RUN_DIR / "reports" / f"mercurio_{INTERVAL}_v1.json"
    out.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print(f"  json  ·  {out}")
    log.info(f"JSON → {out}")

    try:
        from core.db import register_run
        register_run(
            run_id=RUN_ID, engine="mercurio", json_path=str(out),
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
    print(f"  MERCURIO  ·  Order Flow Analysis")
    print(f"  {SEP}")

    _days_in = safe_input(f"\n  periodo em dias [{SCAN_DAYS}] > ").strip()
    if _days_in.isdigit() and 7 <= int(_days_in) <= 1500:
        SCAN_DAYS = int(_days_in)
    N_CANDLES = SCAN_DAYS * 24 * 4

    SYMBOLS = select_symbols(SYMBOLS)

    _lev_in = safe_input(f"  leverage [{LEVERAGE}x] > ").strip()
    if _lev_in:
        try:
            _lev_val = float(_lev_in.replace("x", ""))
            if 0.1 <= _lev_val <= 125:
                LEVERAGE = _lev_val
        except ValueError:
            pass

    print(f"\n{SEP}")
    print(f"  MERCURIO  ·  {SCAN_DAYS}d  ·  {len(SYMBOLS)} ativos  ·  {INTERVAL}")
    print(f"  ${ACCOUNT_SIZE:,.0f}  ·  {LEVERAGE}x")
    print(f"  {RUN_DIR}/")
    print(SEP)
    safe_input("  enter para iniciar... ")

    log.info(f"MERCURIO v1.0 iniciado — {RUN_ID}  tf={INTERVAL}  dias={SCAN_DAYS}")

    # ── FETCH DATA ──
    print(f"\n{SEP}\n  DADOS   {INTERVAL}   {N_CANDLES:,} candles\n{SEP}")
    all_dfs = fetch_all(SYMBOLS, INTERVAL, N_CANDLES)
    for sym, df in all_dfs.items():
        validate(df, sym)
    if not all_dfs:
        print("  sem dados"); sys.exit(1)

    macro_bias = detect_macro(all_dfs)
    corr = build_corr_matrix(all_dfs)

    print_header()

    # ── SCAN ALL SYMBOLS ──
    print(f"\n{SEP}\n  SCAN ORDER FLOW\n{SEP}")
    all_trades = []
    all_vetos = defaultdict(int)

    for sym, df in all_dfs.items():
        trades, vetos = scan_mercurio(df.copy(), sym, macro_bias, corr)
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
    ratios["max_dd_pct"] = mdd_pct

    wr = sum(1 for t in closed if t["result"] == "WIN") / len(closed) * 100

    print(f"\n{SEP}\n  METRICAS\n{SEP}")
    print(f"  Trades    {len(closed)}")
    print(f"  WR        {wr:.1f}%")
    print(f"  ROI       {ratios['ret']:+.2f}%")
    print(f"  Sharpe    {ratios['sharpe']:.3f}" if ratios["sharpe"] else "  Sharpe    —")
    print(f"  Sortino   {ratios['sortino']:.3f}" if ratios.get("sortino") else "  Sortino   —")
    print(f"  MaxDD     {mdd_pct:.1f}%")
    print(f"  Final     ${eq[-1]:,.0f}")

    mc = monte_carlo(pnl_list)
    if mc:
        print(f"\n{SEP}\n  MONTE CARLO   {MC_N}x\n{SEP}")
        print(f"  Positivo  {mc['pct_pos']:.0f}%")
        print(f"  Mediana   ${mc['median']:,.0f}")
        print(f"  P5/P95    ${mc['p5']:,.0f} / ${mc['p95']:,.0f}")

    wf = walk_forward(closed)
    if wf:
        print(f"\n{SEP}\n  WALK-FORWARD   {len(wf)} janelas\n{SEP}")
        for w in wf:
            delta = w["test"]["wr"] - w["train"]["wr"]
            ok = "ok" if abs(delta) <= 15 else "xx"
            print(f"  {w['w']:>4d}  treino {w['train']['wr']:.1f}%  "
                  f"fora {w['test']['wr']:.1f}%  D {delta:+.1f}%  {ok}")

    print_veredito(all_trades, eq, mdd_pct, mc, wf, ratios)
    export_json(all_trades, eq, mc, ratios)

    if all_vetos:
        print(f"\n{SEP}\n  VETOS\n{SEP}")
        for k, v in sorted(all_vetos.items(), key=lambda x: -x[1]):
            print(f"  {v:>6d}  {k}")

    print(f"\n{SEP}\n  output  ·  {RUN_DIR}/\n{SEP}\n")
