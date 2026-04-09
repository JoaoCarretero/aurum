"""
☿ AZOTH v3.6 — AURUM Finance Backtest Engine
==============================================
Main scan loop, reporting, and execution entry point.
"""
import os, sys, time, math, json, random, logging
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import datetime
from pathlib import Path as _Path

# ── Config ────────────────────────────────────────────────────
from config.params import *
from config.params import _tf_params, _TF_MINUTES

# ── Core modules ──────────────────────────────────────────────
from core.data import fetch, fetch_all, validate
from core.indicators import indicators, swing_structure, omega
from core.signals import (
    decide_direction, score_omega, score_chop,
    calc_levels, calc_levels_chop,
    label_trade, label_trade_chop,
)
from core.portfolio import (
    detect_macro, build_corr_matrix, portfolio_allows,
    position_size, _omega_risk_mult,
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

# ── Runtime setup ─────────────────────────────────────────────
from analysis.plots import plot_dashboard, plot_montecarlo, plot_trades
RUN_DATE = datetime.now().strftime("%Y-%m-%d")
RUN_TIME = datetime.now().strftime("%H%M")
RUN_ID   = f"{RUN_DATE}_{RUN_TIME}"
RUN_DIR  = _Path(f"data/{RUN_DATE}")
(RUN_DIR / "charts").mkdir(parents=True, exist_ok=True)
(RUN_DIR / "logs").mkdir(parents=True, exist_ok=True)
(RUN_DIR / "reports").mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(RUN_DIR / "logs" / "run.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("AZOTH")

_tl = logging.getLogger("AZOTH.trades")
_th = logging.FileHandler(RUN_DIR / "logs" / "trades.log", encoding="utf-8")
_th.setFormatter(logging.Formatter("%(message)s"))
_tl.addHandler(_th); _tl.setLevel(logging.DEBUG); _tl.propagate = False

_vl = logging.getLogger("AZOTH.val")
_vh = logging.FileHandler(RUN_DIR / "logs" / "validation.log", encoding="utf-8")
_vh.setFormatter(logging.Formatter("%(message)s"))
_vl.addHandler(_vh); _vl.setLevel(logging.DEBUG); _vl.propagate = False

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

    if MTF_ENABLED and htf_stack_dfs:
        df = merge_all_htf_to_ltf(df, htf_stack_dfs)

    trades  = []
    vetos   = defaultdict(int)
    account = ACCOUNT_SIZE
    min_idx = max(200, W_NORM, PIVOT_N*3) + 5

    open_pos: list[tuple[int, str]] = []

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

        open_pos    = [(ei, s) for ei, s in open_pos if ei > idx]
        active_syms = [s for _, s in open_pos]

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
            threshold   = base_thresh + 0.05 if vol_r_now == "HIGH" else base_thresh
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
            result, duration, exit_p = label_trade_chop(
                df, idx+1, direction, entry, stop, target)
        else:
            result, duration, exit_p = label_trade(
                df, idx+1, direction, entry, stop, target)

        if result == "OPEN": continue

        vol_r = str(row.get("vol_regime", "NORMAL"))
        size  = position_size(account, entry, stop, score,
                              macro_b, direction, vol_r, dd_scale,
                              is_chop_trade=is_chop_trade,
                              peak_equity=peak_equity)
        size  = round(size * corr_size_mult * trans_mult, 4)
        if not is_chop_trade:
            size = round(size * fractal_score, 4)

        ep = float(exit_p)
        slip_exit = SLIPPAGE + SPREAD          # C2: slippage na saída (market order)
        if direction == "BULLISH":
            entry_cost = entry * (1 + COMMISSION)              # C1: comissão entrada
            ep_net     = ep * (1 - COMMISSION - slip_exit)     # C2: comissão + slip saída
            funding    = -(size * entry * FUNDING_PER_8H * duration / 32)
            pnl        = size * (ep_net - entry_cost) + funding
        else:
            entry_cost = entry * (1 - COMMISSION)              # C1: comissão entrada
            ep_net     = ep * (1 + COMMISSION + slip_exit)     # C2: comissão + slip saída
            funding    = +(size * entry * FUNDING_PER_8H * duration / 32)
            pnl        = size * (entry_cost - ep_net) + funding
        pnl     = round(pnl * LEVERAGE, 2)          # alavancagem escala PnL linearmente
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
            "rr":         rr, "duration": duration, "result": result, "pnl": pnl,
            "size":       round(size, 4),
            "score":      score, "fractal_align": fractal_score,
            "omega_struct":   comps["struct"],   "omega_flow":     comps["flow"],
            "omega_cascade":  comps["cascade"],  "omega_momentum": comps["momentum"],
            "omega_pullback": comps["pullback"],
            "chop_trade":     is_chop_trade,
            "bb_mid":         chop_info.get("bb_mid", 0.0) if is_chop_trade else 0.0,
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
    print(f"  GRAVITON v3.6  ·  {RUN_ID}")
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


def export_json(all_trades, eq, mc, cond, ratios):
    closed = [t for t in all_trades if t["result"] in ("WIN","LOSS")]
    wr     = sum(1 for t in closed if t["result"]=="WIN")/max(len(closed),1)*100
    chop_n = sum(1 for t in closed if t.get("chop_trade"))
    payload = {
        "version": "azoth-3.6", "run_id": RUN_ID,
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
            "omega_risk_table": OMEGA_RISK_TABLE,
            "chop_bb_period": CHOP_BB_PERIOD, "chop_bb_std": CHOP_BB_STD,
            "chop_rsi_long": CHOP_RSI_LONG, "chop_rsi_short": CHOP_RSI_SHORT,
            "chop_rr": CHOP_RR, "chop_size_mult": CHOP_SIZE_MULT,
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
        "monte_carlo": {k:v for k,v in (mc or {}).items() if k not in ("paths","finals","dds")},
        "trades": [{k:(str(v) if k=="timestamp" else v) for k,v in t.items() if k!="timestamp"}
                   for t in all_trades],
        "equity": eq,
    }
    fname = str(RUN_DIR / "reports" / f"azoth_{INTERVAL}_v36.json")
    with open(fname,"w",encoding="utf-8") as f:
        json.dump(payload,f,ensure_ascii=False,indent=2,default=str)
    print(f"  JSON → {fname}")


if __name__ == "__main__":

    print("\n" + "═"*52)
    print("  ☿  AZOTH v3.6   AURUM Finance")
    print("  ── ALL-SCALE FRACTAL ENGINE ──────────────")
    print("  15m entrada × 1h × 4h × 1d  estrutura")
    print("  [U1]Ω-risk [U2]SoftCorr [U3]CHOP-MR")
    print("═"*52)

    print(f"\n  Exemplos: 30=1m  90=3m  180=6m  365=1ano  730=2anos")
    print(f"  (365 dias = ~35k candles 15m + 8.5k 1h + 2.4k 4h + 465 1d × 28 símbolos)")
    _days_in = input(f"  Período em dias [{SCAN_DAYS}] > ").strip()
    if _days_in.isdigit() and 7 <= int(_days_in) <= 1500:
        SCAN_DAYS = int(_days_in)

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

    SYMBOLS = select_symbols(SYMBOLS)

    _plot_ans = input("  Gerar graficos? [s/N] > ").strip().lower()
    GENERATE_PLOTS = _plot_ans in ("s", "sim", "y", "yes", "1")

    _lev_in = input(f"  Leverage [{LEVERAGE}x] > ").strip()
    if _lev_in:
        try:
            _lev_val = float(_lev_in.replace("x",""))
            if 0.1 <= _lev_val <= 125:
                LEVERAGE = _lev_val
        except ValueError:
            pass

    _total_req = (
        len(SYMBOLS) * (
            math.ceil(N_CANDLES / 1000) +
            math.ceil(HTF_N_CANDLES_MAP["1h"] / 1000) +
            math.ceil(HTF_N_CANDLES_MAP["4h"] / 1000) +
            math.ceil(HTF_N_CANDLES_MAP["1d"] / 1000)
        )
    )
    _est_mins = round(_total_req * 0.08 / 60, 1)

    print(f"\n{SEP}")
    print(f"  GRAVITON  ·  {SCAN_DAYS}d  ·  {len(SYMBOLS)} ativos  ·  {INTERVAL}")
    print(f"  ${ACCOUNT_SIZE:,.0f}  ·  {LEVERAGE}x  ·  risk {BASE_RISK*100:.1f}–{MAX_RISK*100:.1f}%  ·  RR {TARGET_RR}x")
    print(f"  {N_CANDLES:,} candles  ·  ~{_total_req} requests  ·  ~{_est_mins} min")
    if GENERATE_PLOTS: print(f"  charts on")
    print(f"  {RUN_DIR}/")
    print(SEP)
    input("  enter para iniciar... ")

    print_header()
    log.info(f"AZOTH v3.6 iniciado — {RUN_ID}  tf={INTERVAL}  nc={N_CANDLES}  plots={'on' if GENERATE_PLOTS else 'off'}")

    S = "─" * 80

    print(f"\n{S}\n  DADOS   {ENTRY_TF}   {N_CANDLES:,} candles   ({SCAN_DAYS} dias)\n{S}")
    _fetch_syms = list(SYMBOLS)
    if MACRO_SYMBOL not in _fetch_syms:
        _fetch_syms.insert(0, MACRO_SYMBOL)
    all_dfs = fetch_all(_fetch_syms)
    for sym, df in all_dfs.items():
        validate(df, sym)
    if not all_dfs: print("Sem dados."); sys.exit(1)

    htf_stack_by_sym: dict[str, dict] = {}
    if MTF_ENABLED:
        for tf in HTF_STACK:
            nc = HTF_N_CANDLES_MAP.get(tf, 300)
            print(f"\n{S}\n  HTF   {tf}   {nc:,} candles\n{S}")
            tf_dfs = fetch_all(list(all_dfs.keys()), interval=tf, n_candles=nc)
            for sym, df_h in tf_dfs.items():
                df_h = prepare_htf(df_h, htf_interval=tf)
                htf_stack_by_sym.setdefault(sym, {})[tf] = df_h

    print(f"\n{S}\n  PRÉ-PROCESSAMENTO\n{S}")
    macro_series = detect_macro(all_dfs)
    if macro_series is not None:
        bull_n = (macro_series=="BULL").sum()
        bear_n = (macro_series=="BEAR").sum()
        chop_n = (macro_series=="CHOP").sum()
        total  = bull_n + bear_n + chop_n
        print(f"  Macro ({MACRO_SYMBOL})    "
              f"↑ BULL {bull_n}c ({bull_n/total*100:.0f}%)   "
              f"↓ BEAR {bear_n}c ({bear_n/total*100:.0f}%)   "
              f"↔ CHOP {chop_n}c ({chop_n/total*100:.0f}%)")
    else:
        print("  Macro: N/A — usando CHOP")

    corr = build_corr_matrix(all_dfs)
    top_pairs = sorted([(k,v) for k,v in corr.items() if k[0]<k[1]], key=lambda x:-x[1])[:5]
    corr_str  = "   ".join(
        f"{a[0].replace('USDT','')}/{a[1].replace('USDT','')}: {v:.2f}"
        for a, v in top_pairs)
    print(f"  Correlação      {corr_str}")

    vol_summary = {}
    for sym, df in all_dfs.items():
        df_i = indicators(df)
        vc   = df_i["vol_regime"].value_counts().to_dict()
        vol_summary[sym.replace("USDT","")] = vc
    total_vc: dict = {}
    for vc in vol_summary.values():
        for k, v in vc.items(): total_vc[k] = total_vc.get(k,0) + v
    tot = sum(total_vc.values())
    vol_dist = "   ".join(f"{k} {v/tot*100:.0f}%" for k, v in
                          sorted(total_vc.items(), key=lambda x: ["LOW","NORMAL","HIGH","EXTREME"].index(x[0]) if x[0] in ["LOW","NORMAL","HIGH","EXTREME"] else 99))
    print(f"  Vol Regime      {vol_dist}")

    print(f"\n{S}")
    print(f"  SCAN   {'ATIVO':12s}  {'N':>5s}  {'W/L':>7s}  {'WR':>6s}  {'L/S':>6s}  {'Ω̄':>5s}  {'PnL':>10s}")
    print(S)
    all_trades: list = []
    all_vetos = defaultdict(int)
    for sym, df in all_dfs.items():
        if sym not in SYMBOLS:
            continue
        trades, vetos = scan_symbol(df, sym, macro_series, corr,
                                    htf_stack_by_sym.get(sym) if MTF_ENABLED else None)
        all_trades.extend(trades)
        for k, v in vetos.items(): all_vetos[k] += v
        closed = [t for t in trades if t["result"] in ("WIN","LOSS")]
        w    = sum(1 for t in closed if t["result"]=="WIN")
        l2   = len(closed) - w
        pnl  = sum(t["pnl"] for t in closed)
        bull = sum(1 for t in trades if t["direction"]=="BULLISH")
        bear = sum(1 for t in trades if t["direction"]=="BEARISH")
        avg  = sum(t["score"] for t in trades)/max(len(trades),1) if trades else 0.0
        wr2  = w/len(closed)*100 if closed else 0.0
        chop_mr = sum(1 for t in trades if t.get("chop_trade"))
        flag = "  ⚠ WR<25%" if wr2<25 and closed else ""
        chop_flag = f"  [MR:{chop_mr}]" if chop_mr > 0 else ""
        print(f"  ✓  {sym:12s}  {len(trades):>5d}  {w:>3d}/{l2:<3d}  {wr2:>5.1f}%  "
              f"L{bull}/S{bear}  {avg:.3f}  ${pnl:>+9,.0f}{flag}{chop_flag}")

    print(f"\n{S}\n  FILTROS DE VETO\n{S}")
    total_v = sum(all_vetos.values())
    for k, n in sorted(all_vetos.items(), key=lambda x: -x[1]):
        bar = "▓" * min(int(n/total_v*35), 35) if total_v else ""
        print(f"  {k:42s}  {n:>6d}  {n/total_v*100:>4.1f}%  {bar}")

    if not all_trades: print("\n  Sem trades."); sys.exit(1)
    all_trades.sort(key=lambda x: x["timestamp"])
    closed = [t for t in all_trades if t["result"] in ("WIN","LOSS")]
    if not closed: print("\n  Sem trades fechados."); sys.exit(1)

    pnl_s = [t["pnl"] for t in closed]
    eq, mdd, mdd_pct, ms = equity_stats(pnl_s)
    ratios = calc_ratios(pnl_s)

    print(f"\n{S}")
    print(f"  RESULTADOS   {'ATIVO':12s}  {'N':>3s}  {'W/L':>7s}  {'WR':>6s}  {'L/S':>6s}  {'Ω̄':>5s}  {'PnL':>12s}  OK")
    print(S)
    by_sym = defaultdict(list)
    for t in all_trades: by_sym[t["symbol"]].append(t)
    for sym in sorted(by_sym):
        ts  = by_sym[sym]
        c   = [t for t in ts if t["result"] in ("WIN","LOSS")]
        if not c: continue
        w2  = sum(1 for t in c if t["result"]=="WIN")
        wr2 = w2/len(c)*100
        ag  = sum(t["score"] for t in ts)/len(ts)
        p2  = sum(t["pnl"] for t in c)
        b2  = sum(1 for t in ts if t["direction"]=="BULLISH")
        s2  = sum(1 for t in ts if t["direction"]=="BEARISH")
        ico = "✓" if wr2>=50 and p2>0 else "~" if p2>0 else "✗"
        print(f"  {sym:12s}  {len(ts):>3d}  {w2:>3d}/{len(c)-w2:<3d}  {wr2:>5.1f}%  "
              f"L{b2}/S{s2}  {ag:.3f}  ${p2:>+10,.0f}  {ico}")

    print(f"\n{S}\n  MÉTRICAS DE PORTFÓLIO\n{S}")
    print(f"  Sharpe   {str(ratios['sharpe'] or '—'):>7s}     "
          f"Sortino  {str(ratios['sortino'] or '—'):>7s}     "
          f"Calmar  {str(ratios['calmar'] or '—'):>7s}")
    print(f"  Sharpe diário {str(ratios.get('sharpe_daily') or '—'):>5s}  "
          f"(benchmark-comparable, ann. 252d)")
    print(f"  ROI      {ratios['ret']:>6.2f}%     "
          f"MaxDD    {mdd_pct:>6.2f}%     "
          f"Streak  {ms:>5d} perdas")
    print(f"  Capital  ${ACCOUNT_SIZE:>8,.0f}  →  ${eq[-1]:>10,.0f}   (+${eq[-1]-ACCOUNT_SIZE:,.0f})")
    for lado, ts2 in [("LONG ", [t for t in closed if t["direction"]=="BULLISH"]),
                      ("SHORT", [t for t in closed if t["direction"]=="BEARISH"]),
                      ("MR   ", [t for t in closed if t.get("chop_trade")])]:
        if not ts2: continue
        w3  = sum(1 for t in ts2 if t["result"]=="WIN")
        wr3 = w3/len(ts2)*100
        p3  = sum(t["pnl"] for t in ts2)
        ico = "✓" if wr3>=50 and p3>0 else "~" if p3>0 else "✗"
        print(f"  {ico} {lado}   {w3:>3d}W / {len(ts2)-w3:<3d}L   "
              f"WR {wr3:>5.1f}%   PnL ${p3:>+10,.0f}   n={len(ts2)}")

    print(f"\n{S}\n  EDGE POR FAIXA Ω\n{S}")
    print(f"  {'Faixa':>10s}  {'N':>4s}  {'WR':>6s}  {'RR':>5s}  {'E/trade':>9s}  {'Total':>12s}  STATUS")
    cond = conditional_backtest(all_trades)
    for label, d in cond.items():
        if not d: print(f"  {label:>10s}  —  sem dados"); continue
        st = ("✓ EDGE" if d["wr"]>=55 and d["exp"]>0
              else "~ NEUTRO" if d["exp"]>0 else "✗ SEM EDGE")
        print(f"  {label:>10s}  {d['n']:>4d}  {d['wr']:>5.1f}%  {d['avg_rr']:>4.2f}×  "
              f"${d['exp']:>+8.2f}  ${d['total']:>+10,.0f}  {st}")

    mc = monte_carlo(pnl_s)
    print(f"\n{S}\n  MONTE CARLO   {MC_N}× simulações   bloco={MC_BLOCK}\n{S}")
    if mc:
        rlb = "✓ SEGURO" if mc["ror"]<1 else "⚠ ATENÇÃO" if mc["ror"]<5 else "✗ ALTO RISCO"
        print(f"  Positivos  {mc['pct_pos']:>5.1f}%   "
              f"p5 ${mc['p5']:>9,.0f}   Mediana ${mc['median']:>9,.0f}   p95 ${mc['p95']:>9,.0f}")
        print(f"  RoR        {mc['ror']:>5.1f}%   [{rlb}]   "
              f"DD médio {mc['avg_dd']:.1f}%   pior {mc['worst_dd']:.1f}%")
    else:
        print("  Amostra insuficiente")

    wf = walk_forward(all_trades)
    print(f"\n{S}\n  WALK-FORWARD GLOBAL   {len(wf)} janelas   treino={WF_TRAIN}  teste={WF_TEST}\n{S}")
    if wf:
        ok  = sum(1 for w in wf if abs(w["test"]["wr"]-w["train"]["wr"])<=15)
        pct = ok/len(wf)*100
        lbl = "✓ ESTÁVEL" if pct>=60 else "✗ INSTÁVEL"
        print(f"  {ok}/{len(wf)} estáveis ({pct:.0f}%)   {lbl}")
        print(f"\n  {'W':>3s}  {'TREINO':>6s}  {'FORA':>6s}  {'Δ':>6s}  OK?")
        for w in wf[-12:]:
            d  = w["test"]["wr"] - w["train"]["wr"]
            st = "✓" if abs(d)<=15 else "✗"
            print(f"  {w['w']:>3d}  {w['train']['wr']:>5.1f}%  "
                  f"{w['test']['wr']:>5.1f}%  {d:>+5.1f}%  {st}")
        if len(wf) > 12:
            print(f"  ... (+{len(wf)-12} janelas anteriores)")
    else:
        print("  Amostra insuficiente")

    wf_regime = walk_forward_by_regime(all_trades)
    print(f"\n{S}\n  WALK-FORWARD POR REGIME   (tolerância ±25%)\n{S}")
    print(f"  Isola o efeito de troca de regime — cada período avaliado no próprio contexto")
    print()
    print_wf_by_regime(wf_regime)
    regime_stabs = [d["stable_pct"] for d in wf_regime.values() if d["stable_pct"] is not None]
    if regime_stabs:
        bear_stab = wf_regime.get("BEAR", {}).get("stable_pct")
        if bear_stab is not None:
            print(f"\n  BEAR regime (principal): {bear_stab:.0f}% estável  "
                  f"{'✓' if bear_stab >= 60 else '~' if bear_stab >= 40 else '✗'}")

    print(f"\n{S}\n  RELATÓRIOS\n{S}")
    if GENERATE_PLOTS:
        plot_dashboard(all_trades, eq, cond, wf, ratios, mdd_pct, run_dir=RUN_DIR)
        plot_montecarlo(mc, eq, run_dir=RUN_DIR)
        top_syms = sorted(by_sym,
                          key=lambda s: len([t for t in by_sym[s]
                                             if t["result"] in ("WIN","LOSS")]),
                          reverse=True)[:6]
        for sym in top_syms:
            df = all_dfs.get(sym)
            if df is not None:
                plot_trades(omega(swing_structure(indicators(df))), by_sym[sym], sym, run_dir=RUN_DIR)
    else:
        print("  Plots desativados — exportando só JSON e métricas")
    export_json(all_trades, eq, mc, cond, ratios)

    print(f"\n{S}\n  ROBUSTEZ POR SÍMBOLO\n{S}")
    print_symbol_robustness(symbol_robustness(all_trades))

    print_chop_analysis(all_trades)

    yy = year_by_year_analysis(all_trades)
    if len([yr for yr, d in yy.items() if d]) >= 2:
        print(f"\n{S}\n  PERFORMANCE ANO A ANO\n{S}")
        print_year_by_year(yy)

    print(f"\n{S}\n  ANÁLISE DE REGIME   (Pitch Institucional)\n{S}")
    print_bear_market_enhanced(bear_market_analysis(all_trades), yy)

    print_veredito(all_trades, eq, mdd_pct, mc, wf, cond, ratios, wf_regime)

    print(f"{S}")
    print(f"  OUTPUT: {RUN_DIR}/")
    print(f"  ├── charts/    dashboard_{INTERVAL}.png   montecarlo_{INTERVAL}.png   trades_*")
    print(f"  ├── reports/   azoth_{INTERVAL}_v36.json")
    print(f"  └── logs/      run.log   trades.log   validation.log")
    print(f"{S}\n")

    # Auto-persist to DB
    try:
        from core.db import save_run
        _json = str(RUN_DIR / "reports" / f"azoth_{INTERVAL}_v36.json")
        save_run("backtest", _json)
        print(f"  DB: run persistido")
    except Exception as _e:
        print(f"  DB: {_e}")
