"""
CITADEL v3.6 — AURUM Finance Systematic Momentum Engine
========================================================
# CITADEL (formerly AZOTH) — Trend-following + fractal alignment
Main scan loop, reporting, and execution entry point.
"""
import os, sys, time, math, json, random, logging
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path as _Path

# ── Config ────────────────────────────────────────────────────
from config.params import *
from config.params import _tf_params, _TF_MINUTES
# Calibrated TF (longrun battery 2026-04-14: 15m default = sweet spot)
INTERVAL = ENGINE_INTERVALS.get("CITADEL", INTERVAL)

# ── Core modules ──────────────────────────────────────────────
from core.data import fetch, fetch_all, validate
from core.fs import atomic_write
from core.indicators import indicators, swing_structure, omega
from core.chronos import enrich_with_regime
from analysis.stats import regime_analysis as _hmm_regime_analysis


def _regime_analysis_safe(trades: list) -> dict:
    """Wrap regime_analysis so a failure never breaks the export."""
    try:
        return _hmm_regime_analysis(trades)
    except Exception:
        return {}
from core.signals import (
    decide_direction, score_omega, score_chop,
    calc_levels, calc_levels_chop,
    label_trade, label_trade_chop,
)
from core.portfolio import (
    detect_macro, build_corr_matrix, portfolio_allows, check_aggregate_notional,
    position_size,
)
from core.htf import prepare_htf, merge_all_htf_to_ltf, HTF_INTERVAL

# ── Analysis modules ──────────────────────────────────────────
from analysis.stats import equity_stats, calc_ratios, conditional_backtest
from analysis.montecarlo import monte_carlo
from analysis.walkforward import walk_forward, walk_forward_by_regime, print_wf_by_regime
from analysis.robustness import symbol_robustness, print_symbol_robustness
from analysis.benchmark import (
    bear_market_analysis, year_by_year_analysis,
    print_year_by_year, print_bear_market_enhanced, print_benchmark,
)

# ── Runtime setup (lazy — only runs when setup_run() is called) ──

RUN_DATE: str = ""
RUN_TIME: str = ""
RUN_ID: str   = ""
RUN_DIR: _Path = _Path(".")
log = logging.getLogger("CITADEL")
_tl = logging.getLogger("CITADEL.trades")
_vl = logging.getLogger("CITADEL.val")


def setup_run(engine_name: str = "citadel") -> tuple[str, _Path]:
    """Initialise RUN_DIR, logging, and file handlers. Call once at startup."""
    global RUN_DATE, RUN_TIME, RUN_ID, RUN_DIR

    from core.run_manager import create_run_dir

    RUN_ID, RUN_DIR = create_run_dir(engine_name)
    # UTC so RUN_IDs generated on the Windows dev box and on the Linux VPS
    # agree regardless of the host's local timezone.
    _run_dt = datetime.now(timezone.utc)
    RUN_DATE = _run_dt.strftime("%Y-%m-%d")
    RUN_TIME = _run_dt.strftime("%H%M")

    # Logging: DEBUG to file, WARNING+ to terminal
    _fmt = logging.Formatter("%(asctime)s  %(levelname)s  %(message)s")
    _fh = logging.FileHandler(RUN_DIR / "log.txt", encoding="utf-8")
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(_fmt)
    _sh = logging.StreamHandler(sys.stdout)
    _sh.setLevel(logging.WARNING)
    _sh.setFormatter(_fmt)
    logging.basicConfig(level=logging.DEBUG, handlers=[_fh, _sh], force=True)

    for _h in list(_tl.handlers):
        try:
            _h.close()
        except Exception:
            pass
    _tl.handlers.clear()
    _th = logging.FileHandler(RUN_DIR / "trades.log", encoding="utf-8")
    _th.setFormatter(logging.Formatter("%(message)s"))
    _tl.addHandler(_th); _tl.setLevel(logging.DEBUG); _tl.propagate = False

    for _h in list(_vl.handlers):
        try:
            _h.close()
        except Exception:
            pass
    _vl.handlers.clear()
    _vh = logging.FileHandler(RUN_DIR / "log.txt", mode="a", encoding="utf-8")
    _vh.setFormatter(logging.Formatter("%(message)s"))
    _vl.addHandler(_vh); _vl.setLevel(logging.DEBUG); _vl.propagate = False

    return RUN_ID, RUN_DIR

SEP = "─" * 80

# ══════════════════════════════════════════════════════════════
# SCAN SYMBOL
# ══════════════════════════════════════════════════════════════
def scan_symbol(df: pd.DataFrame, symbol: str,
                macro_bias_series, corr: dict,
                htf_stack_dfs: dict | None = None) -> tuple[list, dict]:
    df = indicators(df)
    df = swing_structure(df)
    df = omega(df)
    df = enrich_with_regime(df)

    if MTF_ENABLED and htf_stack_dfs:
        df = merge_all_htf_to_ltf(df, htf_stack_dfs)

    trades  = []
    vetos   = defaultdict(int)
    account = ACCOUNT_SIZE
    min_idx = max(200, W_NORM, PIVOT_N*3) + 5

    # (exit_idx, symbol, size, entry) — size/entry needed for L6 aggregate notional cap
    open_pos: list[tuple[int, str, float, float]] = []

    # pre-extract numpy arrays — evita df.iloc[idx] no loop (3-5x mais rapido)
    _rsi   = df["rsi"].values;          _atr   = df["atr"].values
    _volr  = df["vol_regime"].values;   _tkma  = df["taker_ma"].values
    _sl21  = df["slope21"].values;      _sl200 = df["slope200"].values
    _dist  = df["dist_ema21"].values;   _str   = df["trend_struct"].values
    _stre  = df["struct_strength"].values
    _trans = df["regime_transition"].values
    _cup   = df["casc_up"].values;      _cdn   = df["casc_down"].values
    _ofb   = df["omega_flow_bull"].values; _ofbr = df["omega_flow_bear"].values
    _omb   = df["omega_mom_bull"].values;  _ombr = df["omega_mom_bear"].values
    _opu   = df["omega_pullback"].values
    _osu   = df["omega_struct_up"].values; _osd  = df["omega_struct_down"].values
    _bbu   = df["bb_upper"].values;     _bbl   = df["bb_lower"].values
    _bbm   = df["bb_mid"].values;       _bbw   = df["bb_width"].values
    _cls   = df["close"].values
    # HMM regime layer (observation-only in Fase 3 — no gate yet)
    _hmm_lbl = df["hmm_regime_label"].values
    _hmm_cf  = df["hmm_confidence"].values
    _hmm_pb  = df["hmm_prob_bull"].values
    _hmm_pbr = df["hmm_prob_bear"].values
    _hmm_pc  = df["hmm_prob_chop"].values
    # Live/backtest parity: speed filter precomputado (mesma fórmula do live check_signal)
    _speed = (
        ((df["high"] - df["low"]) / df["close"])
        .rolling(SPEED_WINDOW).mean().values
    )
    _htfm  = df[f"htf{len(HTF_STACK)}_macro"].values if MTF_ENABLED and f"htf{len(HTF_STACK)}_macro" in df.columns else None
    _htfs  = {i: {k: df[f"htf{i}_{k}"].values for k in ["struct","strength","score","macro"] if f"htf{i}_{k}" in df.columns}
              for i in range(1, len(HTF_STACK)+1)} if MTF_ENABLED else {}

    peak_equity        = ACCOUNT_SIZE
    prev_dd            = 0.0          # DD anterior para calcular velocidade
    consecutive_losses = 0
    cooldown_until     = -1
    sym_cooldown_until: dict[str, int] = {}

    _tl.info(f"\n{'═'*72}\n  {symbol}  [{df['time'].iloc[0].date()} → {df['time'].iloc[-1].date()}]\n{'═'*72}")

    for idx in range(min_idx, len(df)-MAX_HOLD-2):
        # build row from pre-extracted arrays (no Series overhead)
        row = {"trend_struct":_str[idx],"struct_strength":_stre[idx],
               "slope21":_sl21[idx],"slope200":_sl200[idx],
               "vol_regime":_volr[idx],"dist_ema21":_dist[idx],
               "rsi":_rsi[idx],"taker_ma":_tkma[idx],
               "casc_up":_cup[idx],"casc_down":_cdn[idx],
               "omega_flow_bull":_ofb[idx],"omega_flow_bear":_ofbr[idx],
               "omega_mom_bull":_omb[idx],"omega_mom_bear":_ombr[idx],
               "omega_pullback":_opu[idx],"omega_struct_up":_osu[idx],
               "omega_struct_down":_osd[idx],
               "close":_cls[idx],"bb_upper":_bbu[idx],"bb_lower":_bbl[idx],
               "bb_mid":_bbm[idx],"bb_width":_bbw[idx]}
        if MTF_ENABLED:
            for i,cols in _htfs.items():
                for k,arr in cols.items(): row[f"htf{i}_{k}"]=arr[idx]

        open_pos    = [(ei, s, sz, en) for ei, s, sz, en in open_pos if ei > idx]
        active_syms = [s for _, s, _, _ in open_pos]

        # EMPIRICAL — validate OOS: 20-24h UTC tem WR=47.5%
        if VETO_HOURS_UTC:
            _hour = df["time"].iloc[idx].hour
            if _hour in VETO_HOURS_UTC:
                vetos["hour_filter"] += 1; continue

        # Paridade com live: session block (UTC) — off por default
        if SESSION_BLOCK_ACTIVE:
            _hour = df["time"].iloc[idx].hour
            if _hour in SESSION_BLOCK_HOURS:
                vetos["sessao_baixa_liquidez"] += 1; continue

        # Paridade com live: speed filter (mercado lento → sem edge direcional)
        _sp = _speed[idx]
        if not np.isnan(_sp) and _sp < SPEED_MIN:
            vetos["mercado_lento"] += 1; continue

        macro_b = "CHOP"
        if MTF_ENABLED:
            macro_b = str(row.get("htf_macro", "CHOP"))
        elif macro_bias_series is not None:
            macro_b = macro_bias_series.iloc[min(idx, len(macro_bias_series)-1)]

        peak_equity = max(peak_equity, account)
        current_dd  = (peak_equity - account) / peak_equity if peak_equity > 0 else 0.0
        dd_scale    = 1.0
        for dd_thresh in sorted(DD_RISK_SCALE.keys(), reverse=True):
            if current_dd >= dd_thresh:
                dd_scale = DD_RISK_SCALE[dd_thresh]
                break
        if dd_scale == 0.0:
            vetos["dd_pause"] += 1; continue

        # DD velocity: se drawdown está a acelerar, reduz risco extra
        dd_velocity = current_dd - prev_dd
        if dd_velocity > 0.005 and current_dd > 0.03:   # DD a crescer >0.5pp e acima de 3%
            dd_scale *= max(0.5, 1.0 - dd_velocity * 10) # extra cut proporcional à velocidade
        prev_dd = current_dd

        in_transition = bool(_trans[idx])
        trans_mult    = REGIME_TRANS_SIZE_MULT if in_transition else 1.0

        if idx <= cooldown_until:
            vetos["streak_cooldown"] += 1; continue
        if idx <= sym_cooldown_until.get(symbol, -1):
            vetos["sym_cooldown"] += 1; continue

        ok, motivo_p, corr_size_mult = portfolio_allows(symbol, active_syms, corr)
        if not ok:
            vetos[motivo_p] += 1; continue

        # HMM gate — Fase 6 scaffold. Default HMM_GATE_ENABLED=False means
        # this block is inert; the layer is observation-only. Operator
        # flips the flag after reviewing regime_analysis on a long run.
        if HMM_GATE_ENABLED:
            _hmm_r = _hmm_lbl[idx]
            _hmm_c = _hmm_cf[idx]
            if _hmm_r is not None and not (isinstance(_hmm_r, float) and pd.isna(_hmm_r)):
                _hmm_r = str(_hmm_r)
                if not pd.isna(_hmm_c) and float(_hmm_c) >= HMM_MIN_CONFIDENCE:
                    _blocked = HMM_BLOCK_REGIMES.get(_hmm_r, [])
                    if "CITADEL" in _blocked:
                        vetos["hmm_gate"] += 1
                        continue

        direction, motivo, fractal_score = decide_direction(row, macro_b)

        is_chop_trade = False
        chop_bb_mid   = None
        chop_info     = {}

        if direction is None and motivo.startswith("chop"):
            chop_dir, chop_score, chop_info = score_chop(row)
            if chop_dir is not None and chop_score >= 0.30:
                direction     = chop_dir
                motivo        = "ok"
                fractal_score = 1.0
                is_chop_trade = True
                chop_bb_mid   = chop_info.get("bb_mid")
                vetos["chop_tentativa"] = vetos.get("chop_tentativa", 0)
            else:
                vetos[motivo] += 1; continue
        elif direction is None:
            vetos[motivo] += 1; continue

        if not is_chop_trade:
            score, comps = score_omega(row, direction)
            if score == 0.0:
                vetos["casc_zero"] += 1; continue

            weak = [k for k,v in comps.items() if v < OMEGA_MIN_COMPONENT]
            if len(weak) >= 3:
                vetos["comp_fraco"] += 1; continue

            vol_r_now   = str(_volr[idx])
            base_thresh = SCORE_BY_REGIME.get(macro_b, SCORE_THRESHOLD)
            if vol_r_now == "HIGH":
                threshold = max(base_thresh, SCORE_THRESHOLD_HIGH_VOL)
            elif vol_r_now == "LOW":
                threshold = max(base_thresh, SCORE_THRESHOLD_LOW_VOL)
            else:
                threshold = base_thresh
            if score < threshold:
                vetos["score_baixo"] += 1; continue
        else:
            _, score, _ = score_chop(row)
            comps = {"struct": 0.0, "flow": 0.0, "cascade": 0.0,
                     "momentum": chop_info.get("rsi_extreme", 0.0),
                     "pullback": chop_info.get("band_dist", 0.0)}

        if is_chop_trade:
            levels = calc_levels_chop(df, idx, direction, chop_bb_mid)
        else:
            levels = calc_levels(df, idx, direction)

        if levels is None:
            vetos["niveis"] += 1; continue

        entry, stop, target, rr = levels

        if is_chop_trade:
            result, duration, exit_p, exit_reason = label_trade_chop(
                df, idx+1, direction, entry, stop, target)
        else:
            result, duration, exit_p, exit_reason = label_trade(
                df, idx+1, direction, entry, stop, target)

        # Mark-to-market: force-close at last bar's close rather than
        # silently discarding the trade. label_trade already returns the
        # last-bar close as exit_p and MAX_HOLD as duration for OPEN.
        forced_mtm = False
        if result == "OPEN":
            forced_mtm = True
            raw_pnl = (float(exit_p) - entry) if direction == "BULLISH" else (entry - float(exit_p))
            result   = "WIN" if raw_pnl > 0 else "LOSS"

        vol_r = str(row.get("vol_regime", "NORMAL"))
        size  = position_size(account, entry, stop, score,
                              macro_b, direction, vol_r, dd_scale,
                              is_chop_trade=is_chop_trade,
                              peak_equity=peak_equity,
                              regime_scale=ENGINE_RISK_SCALE_BY_REGIME.get("CITADEL"))
        size  = round(size * corr_size_mult * trans_mult, 4)
        if not is_chop_trade:
            size = round(size * fractal_score, 4)

        # [L6] Aggregate notional cap across concurrently open positions.
        # Blocks entries that, when summed with existing open_notional, would
        # exceed account × LEVERAGE — the ceiling a real margin system enforces.
        if size > 0:
            ok_agg, motivo_agg = check_aggregate_notional(
                size * entry, open_pos, account, LEVERAGE)
            if not ok_agg:
                vetos[motivo_agg] += 1
                continue

        ep = float(exit_p)
        slip_exit = SLIPPAGE + SPREAD          # C2: slippage na saída (market order)
        _funding_periods_per_8h = 8 * 60 / _TF_MINUTES.get(INTERVAL, 15)
        if direction == "BULLISH":
            entry_cost = entry * (1 + COMMISSION)              # C1: comissão entrada
            ep_net     = ep * (1 - COMMISSION - slip_exit)     # C2: comissão + slip saída
            funding    = -(size * entry * FUNDING_PER_8H * duration / _funding_periods_per_8h)
            pnl        = size * (ep_net - entry_cost) + funding
        else:
            entry_cost = entry * (1 - COMMISSION)              # C1: comissão entrada
            ep_net     = ep * (1 + COMMISSION + slip_exit)     # C2: comissão + slip saída
            funding    = +(size * entry * FUNDING_PER_8H * duration / _funding_periods_per_8h)
            pnl        = size * (entry_cost - ep_net) + funding
        pnl     = round(pnl * LEVERAGE, 2)          # alavancagem escala PnL linearmente
        # [L7] Post-hoc 90%/95% clamp removed — liquidation is now enforced
        # inside label_trade at the path level (see core.signals._liq_prices).
        # The floor at 0 stays: account cannot go negative, but any genuine
        # liquidation has already been reflected in `pnl` via the liq exit price.
        account = max(account + pnl, 0.0)

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
        trade_type = "CHOP-MR" if is_chop_trade else direction
        t = {
            "symbol":     symbol,
            "time":       ts,
            "timestamp":  df["time"].iloc[idx],
            "idx":        idx,
            "entry_idx":  idx+1,
            "direction":  direction,
            "trade_type": trade_type,
            "struct":     str(row["trend_struct"]),
            "struct_str": round(float(row["struct_strength"]),3),
            "cascade_n":  int(row["casc_up" if direction=="BULLISH" else "casc_down"]) if not is_chop_trade else 0,
            "taker_ma":   round(float(row["taker_ma"]),4) if not pd.isna(row["taker_ma"]) else 0,
            "rsi":        round(float(row["rsi"]),2)      if not pd.isna(row["rsi"])      else 0,
            "dist_ema21": round(float(row["dist_ema21"]),3),
            "macro_bias": macro_b,
            "vol_regime": vol_r,
            "dd_scale":   round(dd_scale, 2),
            "corr_mult":  round(corr_size_mult, 2),
            "in_transition": in_transition,
            "trans_mult":    round(trans_mult, 2),
            "entry":      entry, "stop": stop, "target": target,
            "exit_p":     round(float(exit_p),6),
            "rr":         rr, "duration": duration, "result": result, "exit_reason": exit_reason, "pnl": pnl,
            "size":       round(size, 4),
            "score":      score, "fractal_align": fractal_score,
            "omega_struct":   comps["struct"],   "omega_flow":     comps["flow"],
            "omega_cascade":  comps["cascade"],  "omega_momentum": comps["momentum"],
            "omega_pullback": comps["pullback"],
            "chop_trade":     is_chop_trade,
            "forced_mtm":     forced_mtm,
            "bb_mid":         chop_info.get("bb_mid", 0.0) if is_chop_trade else 0.0,
            # Normalised trade outcome in R units — required by regime_analysis
            "r_multiple": (
                (float(exit_p) - entry) / (entry - stop)
                if direction == "BULLISH" and (entry - stop) != 0
                else (entry - float(exit_p)) / (stop - entry)
                if direction == "BEARISH" and (stop - entry) != 0
                else 0.0
            ),
            # HMM regime layer (observation-only in Fase 3 — informs analysis, not gating)
            "hmm_regime":      (None if _hmm_lbl[idx] is None or (isinstance(_hmm_lbl[idx], float) and pd.isna(_hmm_lbl[idx])) else str(_hmm_lbl[idx])),
            "hmm_confidence":  (None if pd.isna(_hmm_cf[idx])  else round(float(_hmm_cf[idx]),  4)),
            "hmm_prob_bull":   (None if pd.isna(_hmm_pb[idx])  else round(float(_hmm_pb[idx]),  4)),
            "hmm_prob_bear":   (None if pd.isna(_hmm_pbr[idx]) else round(float(_hmm_pbr[idx]), 4)),
            "hmm_prob_chop":   (None if pd.isna(_hmm_pc[idx])  else round(float(_hmm_pc[idx]),  4)),
        }
        trades.append(t)
        icon = "✓" if result=="WIN" else "✗"
        type_lbl = "[CHOP]" if is_chop_trade else ""
        _tl.info(f"  {ts}  {icon}  {direction:8s}{type_lbl}  Ω={score:.3f}  ${pnl:+.2f}  "
                 f"macro={macro_b}  vol={vol_r}  str={t['struct_str']:.2f}")

    closed = [t for t in trades if t["result"] in ("WIN","LOSS")]
    w = sum(1 for t in closed if t["result"]=="WIN")
    _tl.info(f"  TOTAL: {len(trades)}  W={w}  L={len(closed)-w}  "
             f"PnL=${sum(t['pnl'] for t in closed):+,.0f}\n")
    return trades, dict(vetos)


def print_header():
    print(f"\n{SEP}")
    tf_label = f"{INTERVAL}+{HTF_INTERVAL}(MTF)" if MTF_ENABLED else INTERVAL
    print(f"  CITADEL v3.6  ·  {RUN_ID}")
    print(f"  {len(SYMBOLS)} ativos  ·  {tf_label}  ·  {N_CANDLES:,} candles  ·  ${ACCOUNT_SIZE:,.0f}  ·  {LEVERAGE}x")
    print(f"  Risk {BASE_RISK*100:.1f}–{MAX_RISK*100:.1f}%  ·  RR {TARGET_RR}x  ·  MaxPos {MAX_OPEN_POSITIONS}")
    print(f"  {RUN_DIR}/")
    print(SEP)


def print_chop_analysis(all_trades: list):
    """[U3] Análise específica dos trades CHOP-MR."""
    chop_trades = [t for t in all_trades if t.get("chop_trade") and t["result"] in ("WIN","LOSS")]
    if not chop_trades:
        print(f"\n  CHOP-MR: sem trades gerados")
        return

    wins = sum(1 for t in chop_trades if t["result"] == "WIN")
    wr   = wins / len(chop_trades) * 100
    pnl  = sum(t["pnl"] for t in chop_trades)

    by_sym: dict = defaultdict(list)
    for t in chop_trades: by_sym[t["symbol"]].append(t)

    print(f"\n  CHOP-MR [U3]   n={len(chop_trades)}  WR={wr:.1f}%  PnL=${pnl:+,.0f}")
    print(f"  {'─'*60}")
    print(f"  {'ATIVO':12s}  {'N':>3s}  {'WR':>6s}  {'PnL':>10s}  {'RR_med':>6s}")
    for sym in sorted(by_sym):
        ts  = by_sym[sym]
        w2  = sum(1 for t in ts if t["result"]=="WIN")
        wr2 = w2/len(ts)*100
        p2  = sum(t["pnl"] for t in ts)
        rr2 = sum(t["rr"] for t in ts)/len(ts)
        ico = "✓" if wr2>=50 and p2>0 else "~" if p2>0 else "✗"
        print(f"  {ico} {sym:12s}  {len(ts):>3d}  {wr2:>5.1f}%  ${p2:>+8,.0f}  {rr2:>5.2f}×")


def print_veredito(all_trades, eq, mdd_pct, mc, wf, cond, ratios, wf_regime=None):
    closed = [t for t in all_trades if t["result"] in ("WIN","LOSS")]
    wr     = sum(1 for t in closed if t["result"]=="WIN")/max(len(closed),1)*100
    exp    = sum(t["pnl"] for t in closed)/max(len(closed),1)
    top    = cond.get("0.65+") or cond.get("0.59-0.65") or cond.get("0.53-0.59")

    bear_stab = (wf_regime or {}).get("BEAR", {}).get("stable_pct")
    if bear_stab is not None:
        wf_ok = bear_stab >= 60
        wf_label = f"BEAR regime {bear_stab:.0f}%"
    elif wf:
        pct_g = sum(1 for w in wf if abs(w["test"]["wr"]-w["train"]["wr"])<=15)/len(wf)*100
        wf_ok = pct_g >= 60
        wf_label = f"global {pct_g:.0f}%"
    else:
        wf_ok = False; wf_label = "sem dados"

    checks = [
        ("Trades suficientes (≥30)",        len(closed)>=30),
        ("Win Rate ≥ 50%",                  wr>=50),
        ("Expectativa positiva",            exp>0),
        ("Edge faixa alta Ω",               top and top["wr"]>=55 and top["exp"]>0),
        ("MaxDD < 20%",                     mdd_pct<20),
        ("Sharpe ≥ 1.0 (annualizado)",      ratios["sharpe"] and ratios["sharpe"]>=1.0),
        ("Monte Carlo ≥ 70% positivo",      mc and mc["pct_pos"]>=70 and mc["p5"]>ACCOUNT_SIZE*0.75),
        (f"Walk-Forward estável ({wf_label})", wf_ok),
    ]
    passou = sum(1 for _,v in checks if v)
    print(f"\n{SEP}\n  VEREDITO\n{SEP}")
    for nome, ok in checks: print(f"  {'✓' if ok else '✗'}  {nome}")
    verdict = ("EDGE CONFIRMADO" if passou>=7
               else "PROMISSOR" if passou>=5
               else "FRAGIL")
    print(f"\n  {passou}/8  ·  {verdict}\n{SEP}\n")
    log.info(f"Veredito: {passou}/8  ROI={ratios['ret']:.2f}%  WR={wr:.1f}%  MaxDD={mdd_pct:.1f}%")
    try:
        print_benchmark(
            azoth_roi    = ratios["ret"],
            azoth_sharpe = ratios["sharpe"] or 0.0,
            azoth_mdd    = mdd_pct,
            n_days       = SCAN_DAYS
        )
    except Exception as e:
        log.warning(f"Benchmark falhou: {e}")


def export_json(all_trades, eq, mc, cond, ratios, price_data=None):
    closed = [t for t in all_trades if t["result"] in ("WIN","LOSS")]
    wr     = sum(1 for t in closed if t["result"]=="WIN")/max(len(closed),1)*100
    chop_n = sum(1 for t in closed if t.get("chop_trade"))
    payload = {
        "version": "citadel-3.6", "run_id": RUN_ID,
        "timestamp": datetime.now().isoformat(),
        "config": {
            "interval": INTERVAL, "n_candles": N_CANDLES, "symbols": SYMBOLS,
            "score_threshold": SCORE_THRESHOLD, "regime_min": REGIME_MIN_STRENGTH,
            "cascade_min": CASCADE_MIN, "omega_min": OMEGA_MIN_COMPONENT,
            "stop_atr_m": STOP_ATR_M, "target_rr": TARGET_RR,
            "base_risk": BASE_RISK, "max_risk": MAX_RISK,
            "max_open_positions": MAX_OPEN_POSITIONS, "corr_threshold": CORR_THRESHOLD,
            "corr_soft_threshold": CORR_SOFT_THRESHOLD, "corr_soft_mult": CORR_SOFT_MULT,
            "macro_symbol": MACRO_SYMBOL,
            "chop_bb_period": CHOP_BB_PERIOD, "chop_bb_std": CHOP_BB_STD,
            "chop_rsi_long": CHOP_RSI_LONG, "chop_rsi_short": CHOP_RSI_SHORT,
            "chop_rr": CHOP_RR,
            "regime_trans_window":    REGIME_TRANS_WINDOW,
            "regime_trans_atr_jump":  REGIME_TRANS_ATR_JUMP,
            "regime_trans_size_mult": REGIME_TRANS_SIZE_MULT,
        },
        "summary": {
            "total_trades": len(all_trades), "closed": len(closed),
            "win_rate": round(wr,2), "total_pnl": round(sum(t["pnl"] for t in closed),2),
            "final_equity": round(eq[-1],2),
            "chop_mr_trades": chop_n,
            **{k: ratios.get(k) for k in ("sharpe","sortino","calmar","ret")},
        },
        "conditional": cond,
        "bear_market": {r: d for r, d in bear_market_analysis(all_trades).items() if d},
        "monte_carlo": mc or {},
        "hmm_regime_analysis": _regime_analysis_safe(closed),
        "trades": [{k:(str(v) if k=="timestamp" else v) for k,v in t.items() if k!="timestamp"}
                   for t in all_trades],
        "equity": eq,
    }
    if price_data:
        payload["price_data"] = price_data
    fname = str(RUN_DIR / f"citadel_{INTERVAL}_v36.json")
    _Path(fname).parent.mkdir(parents=True, exist_ok=True)
    atomic_write(_Path(fname), json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    print(f"  JSON → {fname}")


if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser(description="CITADEL v3.6 — AURUM Finance Backtest")
    _ap.add_argument("--days",        type=int,   default=SCAN_DAYS,  help="Scan period in days")
    _ap.add_argument("--basket",      type=str,   default="default",  help="Asset basket name")
    _ap.add_argument("--leverage",    type=float, default=LEVERAGE,   help="Leverage multiplier")
    _ap.add_argument("--no-menu",     action="store_true",            help="Skip post-run interactive menu")
    _ap.add_argument("--holdout-pct", type=float, default=0.0,        help="Reserve last N%% of data as pure OOS holdout (0 = disabled, matches other engines)")
    _ap.add_argument("--end",         type=str,   default=None,       help="End date YYYY-MM-DD for backtest window (pre-calibration OOS). Default: now.")
    _args, _ = _ap.parse_known_args()

    SCAN_DAYS = _args.days
    LEVERAGE = _args.leverage
    BASKET_NAME = _args.basket or ENGINE_BASKETS.get("CITADEL", "default")
    END_TIME_MS = None
    if _args.end:
        import pandas as _pd_tmp
        END_TIME_MS = int(_pd_tmp.Timestamp(_args.end).timestamp() * 1000)
    if BASKET_NAME in BASKETS:
        SYMBOLS = BASKETS[BASKET_NAME]

    N_CANDLES = SCAN_DAYS * 24 * 4
    HTF_N_CANDLES_MAP = {
        "1h": SCAN_DAYS * 24       + 200,
        "4h": SCAN_DAYS *  6       + 100,
        "1d": SCAN_DAYS            + 100,
    }
    _TFP         = _tf_params(ENTRY_TF)
    MIN_STOP_PCT = _TFP["min_stop_pct"]
    SLOPE_N      = _TFP["slope_n"]
    CHOP_S21     = _TFP["chop_s21"]
    CHOP_S200    = _TFP["chop_s200"]
    PIVOT_N      = _TFP["pivot_n"]
    MAX_HOLD     = _TFP["max_hold"]

    setup_run()

    # ── Helpers para inline progress ──
    def _progress_bar(done, total, width=20):
        filled = int(done / max(total, 1) * width)
        return "█" * filled + "░" * (width - filled)

    def _write(txt):
        sys.stdout.write(f"\r  {txt}")
        sys.stdout.flush()

    def _writeln(txt):
        sys.stdout.write(f"\r  {txt}\n")
        sys.stdout.flush()

    # ══════════════════════════════════════════════════════════════
    #  BANNER INSTITUCIONAL
    # ══════════════════════════════════════════════════════════════
    _BW = 62
    def _bl(txt): return f"  ║  {txt:{_BW-4}s}║"
    def _bh():    return f"  ╠{'═'*_BW}╣"

    _basket_name = BASKET_NAME
    _sym_list = ", ".join(s.replace("USDT","") for s in SYMBOLS[:5])
    if len(SYMBOLS) > 5: _sym_list += f", ... (+{len(SYMBOLS)-5})"

    print(f"\n  ╔{'═'*_BW}╗")
    _abl_label = f" [ABLATION: -{ABLATION_DISABLE}]" if ABLATION_DISABLE else ""
    print(_bl(f"CITADEL v3.6 · AZOTH Engine · AURUM Finance{_abl_label}"))
    print(_bh())
    print(_bl(f"UNIVERSO       {len(SYMBOLS)} ativos (basket: {_basket_name})"))
    print(_bl(f"PERÍODO        {SCAN_DAYS} dias · {N_CANDLES:,} candles/ativo"))
    print(_bl(f"TIMEFRAME      {INTERVAL}"))
    print(_bl(f"LEVERAGE       {LEVERAGE}x"))
    print(_bl(f"CAPITAL        ${ACCOUNT_SIZE:,.0f}"))
    print(_bh())
    print(_bl("ESTRATÉGIA"))
    print(_bl(""))
    print(_bl("1. SIGNAL  Score Omega fractal 5D"))
    print(_bl(f"   Componentes: struct({OMEGA_WEIGHTS['struct']:.0%})  "
              f"flow({OMEGA_WEIGHTS['flow']:.0%})"))
    print(_bl(f"   cascade({OMEGA_WEIGHTS['cascade']:.0%})  "
              f"momentum({OMEGA_WEIGHTS['momentum']:.0%})  "
              f"pullback({OMEGA_WEIGHTS['pullback']:.0%})"))
    print(_bl(f"   Entry threshold: {SCORE_THRESHOLD} (BEAR)  "
              f"{SCORE_BY_REGIME.get('BULL', SCORE_THRESHOLD)} (BULL)"))
    print(_bl(""))
    print(_bl("2. FILTER  Regime + Veto"))
    print(_bl(f"   Regime: macro slope ({MACRO_SYMBOL})"))
    print(_bl(f"   Veto hours UTC: {list(VETO_HOURS_UTC) if VETO_HOURS_UTC else 'off'}"))
    print(_bl(""))
    print(_bl("3. SIZING  Convex Kelly fraccional"))
    print(_bl(f"   Risk {BASE_RISK*100:.1f}-{MAX_RISK*100:.1f}%  "
              f"Kelly {KELLY_FRAC}  MaxPos {MAX_OPEN_POSITIONS}"))
    print(_bl(""))
    print(_bl("4. EXIT    Estrutural + trailing"))
    print(_bl(f"   Stop {STOP_ATR_M}x ATR  Target {TARGET_RR}x RR  "
              f"MaxHold {MAX_HOLD}"))
    print(_bl(""))
    print(_bl("5. RISK    3-layer kill switch"))
    _dd_levels = "  ".join(f"DD>{k*100:.0f}%={v*100:.0f}%sz" for k,v in
                           sorted(DD_RISK_SCALE.items(), reverse=True)[:3])
    print(_bl(f"   {_dd_levels}"))
    print(_bh())
    print(_bl("CUSTOS MODELADOS"))
    print(_bl(f"C1 comissao    {COMMISSION*100:.2f}%   "
              f"C2 slippage    {SLIPPAGE*100:.2f}%"))
    print(_bl(f"Spread         {SPREAD*100:.2f}%   "
              f"Funding/8h     {FUNDING_PER_8H*100:.2f}%"))
    print(_bh())
    print(_bl("PIPELINE: download > indicators > signals > backtest >"))
    print(_bl("          integrity > overfit(6) > report"))
    print(f"  ╚{'═'*_BW}╝")

    log.info(f"CITADEL v3.6 — {RUN_ID}  tf={INTERVAL}  nc={N_CANDLES}  "
             f"days={SCAN_DAYS}  basket={_basket_name}  lev={LEVERAGE}")

    # ══════════════════════════════════════════════════════════════
    #  FASE 2 — FETCH (inline progress)
    # ══════════════════════════════════════════════════════════════
    _fetch_syms = list(SYMBOLS)
    if MACRO_SYMBOL not in _fetch_syms:
        _fetch_syms.insert(0, MACRO_SYMBOL)

    _fetch_ok: list[str] = []
    _fetch_fail: list[str] = []
    def _fetch_progress(sym, done, total, ok):
        if ok: _fetch_ok.append(sym)
        else:  _fetch_fail.append(sym)
        bar = _progress_bar(done, total)
        names = "  ".join(s.replace("USDT","") + " ✓" for s in _fetch_ok[-6:])
        _write(f"FETCHING  [{bar}] {done}/{total}   {names}   ")

    print()
    all_dfs = fetch_all(_fetch_syms, n_candles=N_CANDLES, futures=True,
                        on_progress=_fetch_progress, end_time_ms=END_TIME_MS)
    for sym, df in all_dfs.items():
        validate(df, sym)
    if not all_dfs:
        print("\n  Sem dados."); sys.exit(1)

    # Fetch summary
    _first = None; _last = None
    for df in all_dfs.values():
        t0 = df['time'].iloc[0]; t1 = df['time'].iloc[-1]
        if _first is None or t0 < _first: _first = t0
        if _last is None or t1 > _last: _last = t1
    _nc_actual = max(len(df) for df in all_dfs.values())
    _span_str = f"{_first.strftime('%b %d')} → {_last.strftime('%b %d')}" if _first else ""
    _writeln(f"✓ {len(all_dfs)}/{len(_fetch_syms)} símbolos · {_nc_actual:,} candles · {_span_str}")

    htf_stack_by_sym: dict[str, dict] = {}
    if MTF_ENABLED:
        for tf in HTF_STACK:
            nc = HTF_N_CANDLES_MAP.get(tf, 300)
            tf_dfs = fetch_all(list(all_dfs.keys()), interval=tf, n_candles=nc, end_time_ms=END_TIME_MS)
            for sym, df_h in tf_dfs.items():
                df_h = prepare_htf(df_h, htf_interval=tf)
                htf_stack_by_sym.setdefault(sym, {})[tf] = df_h

    # ── Pre-processing (silent) ──
    macro_series = detect_macro(all_dfs)
    corr = build_corr_matrix(all_dfs)

    # ── OOS Holdout split ──
    # Last _holdout_pct% of candles per symbol is reserved as pure holdout.
    # These rows NEVER enter the walk-forward IS period.
    _holdout_pct = _args.holdout_pct
    _holdout_enabled = _holdout_pct > 0
    _train_dfs:   dict[str, pd.DataFrame] = {}
    _holdout_dfs: dict[str, pd.DataFrame] = {}
    for _sym, _df in all_dfs.items():
        if _holdout_enabled:
            _hstart = int(len(_df) * (1 - _holdout_pct / 100))
            _train_dfs[_sym]   = _df.iloc[:_hstart].reset_index(drop=True)
            _holdout_dfs[_sym] = _df.iloc[_hstart:].reset_index(drop=True)
        else:
            _train_dfs[_sym]   = _df
            _holdout_dfs[_sym] = pd.DataFrame()

    if _holdout_enabled:
        _ex_sym = next(iter(_train_dfs))
        _ho_candles = len(_holdout_dfs[_ex_sym])
        _tr_candles = len(_train_dfs[_ex_sym])
        print(f"\n  HOLDOUT  {_holdout_pct:.0f}%  →  train {_tr_candles:,} candles  |  holdout {_ho_candles:,} candles")

    # Recompute macro/corr on train-only data so holdout is not contaminated
    _macro_train = detect_macro(_train_dfs) if _holdout_enabled else macro_series
    _corr_train  = build_corr_matrix(_train_dfs) if _holdout_enabled else corr

    # ══════════════════════════════════════════════════════════════
    #  FASE 3 — SCAN (inline progress)
    # ══════════════════════════════════════════════════════════════
    all_trades: list = []
    all_vetos = defaultdict(int)
    _scan_syms = [s for s in all_dfs if s in SYMBOLS]
    _scan_done = 0
    for sym in _scan_syms:
        df = _train_dfs[sym]
        _scan_done += 1
        _nt = len(all_trades)
        bar = _progress_bar(_scan_done, len(_scan_syms))
        _write(f"SCANNING  [{bar}] {_scan_done}/{len(_scan_syms)}  {sym:12s}  trades: {_nt}   ")

        trades, vetos = scan_symbol(df, sym, _macro_train, _corr_train,
                                    htf_stack_by_sym.get(sym) if MTF_ENABLED else None)
        all_trades.extend(trades)
        for k, v in vetos.items(): all_vetos[k] += v

    if not all_trades:
        print("\n  Sem trades."); sys.exit(1)
    all_trades.sort(key=lambda x: x["timestamp"])
    closed = [t for t in all_trades if t["result"] in ("WIN","LOSS")]
    if not closed:
        print("\n  Sem trades fechados."); sys.exit(1)

    w_total = sum(1 for t in closed if t["result"]=="WIN")
    l_total = len(closed) - w_total
    wr_total = w_total/len(closed)*100
    _writeln(f"✓ {len(closed)} trades · {w_total}W / {l_total}L · WR {wr_total:.1f}%")

    # ══════════════════════════════════════════════════════════════
    #  FASE 3b — HOLDOUT SCAN (pure OOS — never in IS period)
    # ══════════════════════════════════════════════════════════════
    holdout_trades: list = []
    if _holdout_enabled:
        _macro_holdout = detect_macro(_holdout_dfs)
        _corr_holdout  = build_corr_matrix(_holdout_dfs)
        _ho_syms = [s for s in _holdout_dfs if s in SYMBOLS and len(_holdout_dfs[s]) > 0]
        _ho_done = 0
        for sym in _ho_syms:
            df_ho = _holdout_dfs[sym]
            _ho_done += 1
            bar = _progress_bar(_ho_done, len(_ho_syms))
            _write(f"HOLDOUT   [{bar}] {_ho_done}/{len(_ho_syms)}  {sym:12s}  trades: {len(holdout_trades)}   ")
            try:
                ho_t, _ = scan_symbol(df_ho, sym, _macro_holdout, _corr_holdout,
                                      htf_stack_by_sym.get(sym) if MTF_ENABLED else None)
                for t in ho_t:
                    t["holdout"] = True
                holdout_trades.extend(ho_t)
            except Exception as _ho_err:
                log.warning(f"Holdout scan failed for {sym}: {_ho_err}")

        ho_closed = [t for t in holdout_trades if t["result"] in ("WIN", "LOSS")]
        if ho_closed:
            ho_w   = sum(1 for t in ho_closed if t["result"] == "WIN")
            ho_wr  = ho_w / len(ho_closed) * 100
            ho_pnl = sum(t["pnl"] for t in ho_closed)
            _writeln(f"✓ HOLDOUT {len(ho_closed)} trades · {ho_w}W / {len(ho_closed)-ho_w}L · WR {ho_wr:.1f}%")
            print(f"\n  ┌─ HOLDOUT OOS ({_holdout_pct:.0f}% últimos candles) {'─'*22}┐")
            print(f"  │  Trades : {len(ho_closed):<5d}  W={ho_w}  L={len(ho_closed)-ho_w}{'':>26}│")
            print(f"  │  WR     : {ho_wr:>5.1f}%{'':>38}│")
            print(f"  │  PnL    : ${ho_pnl:>+12,.2f}  (IS PnL ${sum(t['pnl'] for t in closed):>+,.0f}){'':>5}│")
            _wr_delta = ho_wr - wr_total
            _delta_ico = "✓" if abs(_wr_delta) <= 10 else "⚠"
            print(f"  │  ΔWR vs IS : {_wr_delta:>+5.1f}pp  {_delta_ico}{'':>33}│")
            print(f"  └{'─'*52}┘")
            log.info(f"HOLDOUT: n={len(ho_closed)}  WR={ho_wr:.1f}%  PnL=${ho_pnl:+,.2f}  ΔWR={_wr_delta:+.1f}pp")
        else:
            _writeln("HOLDOUT: sem trades gerados no período reservado")

    # ══════════════════════════════════════════════════════════════
    #  FASE 4 — RESULTADO COMPACTO
    # ══════════════════════════════════════════════════════════════
    pnl_s = [t["pnl"] for t in closed]
    eq, mdd, mdd_pct, ms = equity_stats(pnl_s)
    ratios = calc_ratios(pnl_s)

    total_pnl = sum(pnl_s)
    roi = ratios['ret']
    sh = ratios['sharpe'] or 0.0
    has_edge = wr_total >= 50 and total_pnl > 0 and sh >= 1.0
    edge_lbl = "EDGE DETECTADO" if has_edge else "SEM EDGE"
    edge_ico = "✓" if has_edge else "✗"
    _RW = 58
    def _rb(txt): return f"  ║  {txt:{_RW-4}s}║"
    print(f"\n  ╔{'═'*_RW}╗")
    print(_rb(f"${ACCOUNT_SIZE:,.0f} → ${eq[-1]:,.0f}  ({'+' if total_pnl>=0 else ''}${total_pnl:,.0f})  ROI {roi:+.2f}%"))
    print(_rb(f"{len(closed)} trades · WR {wr_total:.1f}% · Sharpe {sh:.3f} · MaxDD {mdd_pct:.2f}%"))
    print(_rb(f"{edge_ico} {edge_lbl}"))
    print(f"  ╚{'═'*_RW}╝")

    # ── Tabela de símbolos (2 colunas) ──
    by_sym = defaultdict(list)
    for t in all_trades: by_sym[t["symbol"]].append(t)
    sym_rows = []
    for sym in sorted(by_sym, key=lambda s: sum(t["pnl"] for t in by_sym[s] if t["result"] in ("WIN","LOSS")), reverse=True):
        ts = by_sym[sym]
        c  = [t for t in ts if t["result"] in ("WIN","LOSS")]
        if not c: continue
        w2 = sum(1 for t in c if t["result"]=="WIN")
        wr2 = w2/len(c)*100
        p2 = sum(t["pnl"] for t in c)
        ico = "✓" if wr2>=50 and p2>0 else "✗"
        sym_rows.append(f"{sym.replace('USDT',''):6s} {len(c):>3d}t  {wr2:>4.1f}%  ${p2:>+7,.0f}  {ico}")

    print(f"\n  POR SÍMBOLO")
    for i in range(0, len(sym_rows), 2):
        left = sym_rows[i]
        right = sym_rows[i+1] if i+1 < len(sym_rows) else ""
        print(f"  {left:38s}  {right}")

    # ══════════════════════════════════════════════════════════════
    #  ANÁLISE
    # ══════════════════════════════════════════════════════════════
    from analysis.stats import extended_metrics
    cond = conditional_backtest(all_trades)
    mc = monte_carlo(pnl_s)
    wf = walk_forward(all_trades)
    wf_regime = walk_forward_by_regime(all_trades)
    ext = extended_metrics(pnl_s)

    # ── Overfit audit ──
    from analysis.overfit_audit import run_audit, print_audit_box
    audit_results = run_audit(all_trades)
    print_audit_box(audit_results)

    # ══════════════════════════════════════════════════════════════
    #  MÉTRICAS COMPLETAS NO TERMINAL
    # ══════════════════════════════════════════════════════════════
    def _m(label, val, label2, val2):
        return f"  │ {label:<14s} {val:>10s}     {label2:<16s} {val2:>10s}  │"

    _sep = "  ├" + "─" * 52 + "┤"
    print(f"\n  ┌─ PERFORMANCE {'─'*37}┐")
    print(_m("ROI",         f"{roi:+.2f}%",      "Final Equity",  f"${eq[-1]:,.0f}"))
    print(_m("Sharpe",      f"{sh:.3f}",          "Sortino",       f"{ratios.get('sortino') or 0:.3f}"))
    print(_m("Calmar",      f"{ratios.get('calmar') or 0:.3f}",
                                                  "Profit Factor", f"{ext.get('profit_factor', 0):.2f}"))
    print(_m("Expectancy",  f"${ext.get('expectancy', 0):.2f}/t",
                                                  "Max Consec L",  f"{ext.get('max_consec_loss', 0)}"))
    print(_m("Avg Win",     f"${ext.get('avg_win', 0):.2f}",
                                                  "Avg Loss",      f"${ext.get('avg_loss', 0):.2f}"))
    print(_m("Best Trade",  f"${ext.get('best_trade', 0):.2f}",
                                                  "Worst Trade",   f"${ext.get('worst_trade', 0):.2f}"))
    print(_m("Win Rate",    f"{wr_total:.1f}%",   "Payoff Ratio",  f"{ext.get('payoff_ratio', 0):.2f}"))
    print(_m("Max DD",      f"{mdd_pct:.2f}%",    "Max DD $",      f"${ext.get('max_dd_dollars', 0):,.0f}"))
    print(_m("Recovery",    f"{ext.get('recovery_trades', 0)}t",
                                                  "Ulcer Index",   f"{ext.get('ulcer_index', 0):.2f}"))

    # Walk-Forward summary
    print(_sep.replace("─", "─").replace("├", "├").replace("┤", "┤"))
    _wf_ok = sum(1 for w in wf if abs(w["test"]["wr"]-w["train"]["wr"])<=15) if wf else 0
    _wf_pct = round(_wf_ok/len(wf)*100) if wf else 0
    _oos_wr = round(sum(w["test"]["wr"] for w in wf)/len(wf), 1) if wf else 0
    _is_wr = round(sum(w["train"]["wr"] for w in wf)/len(wf), 1) if wf else 0
    print(f"  │ WALK-FORWARD {'─'*37}│")
    print(_m("Windows",     f"{_wf_ok}/{len(wf)}", "Stable%",      f"{_wf_pct}%"))
    print(_m("OOS WR",      f"{_oos_wr}%",         "OOS vs IS",     f"{_oos_wr - _is_wr:+.1f}pp"))
    for _r in ("BEAR", "BULL"):
        _rd = wf_regime.get(_r, {})
        _rs = _rd.get("stable_pct")
        if _rs is not None:
            print(f"  │ {_r} regime   {_rs:.0f}% stable{'':>{36-len(_r)}}│")

    # Monte Carlo summary
    if mc:
        print(f"  │ MONTE CARLO (1000x) {'─'*31}│")
        print(_m("Median Final", f"${mc['median']:,.0f}",
                                                  "P5 (worst 5%)", f"${mc['p5']:,.0f}"))
        print(_m("P95 (best)",   f"${mc['p95']:,.0f}",
                                                  "% Positivo",    f"{mc['pct_pos']:.0f}%"))
        print(_m("Median MaxDD", f"{mc['avg_dd']:.1f}%",
                                                  "P95 MaxDD",     f"{mc['worst_dd']:.1f}%"))

    # Regime breakdown (macro: BTC slope200)
    print(f"  │ REGIME BREAKDOWN (macro) {'─'*25}│")
    for _regime in ("BEAR", "BULL", "CHOP"):
        _rts = [t for t in closed if t.get("macro_bias") == _regime]
        if _rts:
            _rw = sum(1 for t in _rts if t["result"]=="WIN")
            _rwr = _rw/len(_rts)*100
            _rpnl = sum(t["pnl"] for t in _rts)
            _rexp = _rpnl/len(_rts)
            print(f"  │ {_regime:5s} {len(_rts):>3d}t  WR {_rwr:>4.0f}%  "
                  f"${_rpnl:>+7,.0f}   avg ${_rexp:>+.0f}/trade{'':>5s}│")

    # Regime breakdown (HMM — Fase 3 observation layer)
    try:
        from analysis.stats import regime_analysis as _regime_analysis
        _hmm_stats = _regime_analysis(closed)
    except Exception as _e:
        _hmm_stats = {}
        log.debug(f"regime_analysis failed: {_e}")
    if any(_hmm_stats.get(r, {}).get("n", 0) for r in ("BULL", "BEAR", "CHOP")):
        print(f"  │ REGIME BREAKDOWN (HMM)  {'─'*26}│")
        for _regime in ("BEAR", "BULL", "CHOP"):
            _st = _hmm_stats.get(_regime, {})
            if _st.get("n", 0):
                _hpnl = sum(t["pnl"] for t in closed if t.get("hmm_regime") == _regime)
                print(f"  │ {_regime:5s} {_st['n']:>3d}t  WR {_st['wr']:>4.0f}%  "
                      f"${_hpnl:>+7,.0f}   avgR {_st['avg_r']:>+.2f}  sort {_st['sortino']:>+.2f}│")

    # Conditional omega
    print(f"  │ CONDITIONAL Omega SCORE {'─'*27}│")
    for _cl, _cd in cond.items():
        if _cd:
            print(f"  │ {_cl:11s}  WR {_cd['wr']:>4.0f}%  n={_cd['n']:<3d}  "
                  f"exp ${_cd['exp']:>+.2f}{'':>14s}│")

    # Top 5 veto filters (parametric vetos coalesced)
    _veto_total = sum(all_vetos.values()) if all_vetos else 0
    if _veto_total:
        import re as _re_v
        _coalesced_vetos: dict[str, int] = defaultdict(int)
        for _vk, _vv in all_vetos.items():
            _vbase = _re_v.sub(r"\([^)]*\)", "", str(_vk)).strip() or str(_vk)
            _coalesced_vetos[_vbase] += _vv
        print(f"  │ TOP VETO FILTERS {'─'*34}│")
        _sorted_vetos = sorted(_coalesced_vetos.items(), key=lambda kv: kv[1], reverse=True)[:5]
        for _name, _count in _sorted_vetos:
            _pct = _count / _veto_total * 100
            _bar_w = max(1, int(_pct / 5))   # 20-slot bar (5% per slot)
            _bar = "▓" * min(_bar_w, 20) + "·" * max(0, 20 - _bar_w)
            _label = str(_name)[:18]
            print(f"  │ {_label:<18s} {_count:>6d}  {_pct:>4.1f}%  {_bar}  │")

    print(f"  └{'─'*52}┘")

    # ── OHLC persistence for the launcher Trade Inspector ──
    # Saved to <run_dir>/price_data.json so the launcher can render candles
    # for any historical run without re-fetching from Binance.
    _price_data = {}
    for sym, df in all_dfs.items():
        if sym in by_sym:
            _price_data[sym] = {
                "open":  [round(float(v), 6) for v in df["open"].values],
                "high":  [round(float(v), 6) for v in df["high"].values],
                "low":   [round(float(v), 6) for v in df["low"].values],
                "close": [round(float(v), 6) for v in df["close"].values],
            }
    try:
        atomic_write(RUN_DIR / "price_data.json",
                     json.dumps(_price_data, separators=(",", ":")))
    except Exception as _e:
        log.warning(f"Failed to persist price_data.json: {_e}")

    # ══════════════════════════════════════════════════════════════
    #  PERSISTÊNCIA — tudo numa pasta por run
    # ══════════════════════════════════════════════════════════════
    from core.run_manager import (
        snapshot_config, save_run_artifacts, append_to_index, TeeLogger,
    )

    _config = snapshot_config()
    _config["BASKET_EFFECTIVE"] = BASKET_NAME
    _summary = {
        "engine": "CITADEL",
        "basket": BASKET_NAME,
        "n_trades": len(closed),
        "win_rate": round(wr_total, 2),
        "pnl": round(total_pnl, 2),
        "total_pnl": round(total_pnl, 2),
        "roi_pct": round(roi, 2),
        "roi": round(roi, 2),
        "sharpe": ratios.get("sharpe"),
        "sortino": ratios.get("sortino"),
        "calmar": ratios.get("calmar"),
        "max_dd_pct": round(mdd_pct, 2),
        "max_dd": round(mdd_pct, 2),
        "final_equity": round(eq[-1], 2),
        "n_symbols": len(SYMBOLS),
        "n_candles": N_CANDLES,
        "account_size": ACCOUNT_SIZE,
        "leverage": LEVERAGE,
        "interval": INTERVAL,
        "period_days": SCAN_DAYS,
    }

    # Salvar artefactos no run dir
    save_run_artifacts(
        RUN_DIR, _config, all_trades, eq, _summary,
        overfit_results=audit_results,
    )

    # ── Append ao index global ──
    append_to_index(RUN_DIR, _summary, _config, audit_results)

    # ── HTML Report ──
    try:
        from analysis.report_html import generate_report
        generate_report(
            all_trades, eq, mc, cond, ratios, mdd_pct, wf, wf_regime,
            by_sym, all_vetos, str(RUN_DIR), config_dict=_config,
            price_data=_price_data, audit_results=audit_results,
            engine_name="CITADEL",
        )
        print(f"  HTML → {RUN_DIR / 'report.html'}")
    except Exception as _e:
        log.warning(f"HTML report generation failed: {_e}")

    # ── Auto-persist to DB (backwards compat) ──
    try:
        from core.db import save_run as _db_save
        export_json(all_trades, eq, mc, cond, ratios)
        _json = str(RUN_DIR / f"citadel_{INTERVAL}_v36.json")
        if _Path(_json).exists():
            _db_save("citadel", _json)
    except Exception:
        pass

    # ── Output link ──
    print(f"\n  run → {RUN_DIR}/")

    # ══════════════════════════════════════════════════════════════
    #  DASHBOARD GUI — explorar resultados visualmente
    # ══════════════════════════════════════════════════════════════
    if not _args.no_menu:
        safe_input("\n  enter para abrir dashboard visual... ")
        _gui_ok = False
        try:
            from analysis.results_gui import ResultsDashboard
            app = ResultsDashboard(
                all_trades, eq, mc, cond, ratios, wf, wf_regime,
                mdd_pct, by_sym, all_vetos, str(RUN_DIR))
            app.mainloop()
            _gui_ok = True
        except Exception as e:
            print(f"  (GUI indisponível: {e})")

        # Fallback text menu
        while True:
            choice = safe_input("  [0] sair  [r] reabrir dashboard  > ").strip().lower()
            if choice == "0" or not choice:
                break
            if choice == "r" and _gui_ok:
                try:
                    app = ResultsDashboard(
                        all_trades, eq, mc, cond, ratios, wf, wf_regime,
                        mdd_pct, by_sym, all_vetos, str(RUN_DIR))
                    app.mainloop()
                except Exception:
                    pass
