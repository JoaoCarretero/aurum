"""
AURUM Finance — NEWTON Engine v1.0
Statistical Mean Reversion via Pairs Trading (Engle-Granger Cointegration)

Conceito: pares co-integrados divergem do equilíbrio e convergem.
Oposto do AZOTH — opera reversão à média em vez de trend-following.

Pipeline:
  1. Cointegração Engle-Granger entre todos os pares do universo
  2. Z-score do spread com rolling window
  3. Half-life via OLS (Ornstein-Uhlenbeck)
  4. Entry: |z| > 2.0, Exit: z cruza 0, Stop: |z| > 3.5
"""
import sys
import math
import logging
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from itertools import combinations

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.params import *
from core import (
    fetch_all, validate, indicators, swing_structure,
    detect_macro, build_corr_matrix, portfolio_allows, position_size,
)
from analysis.stats import equity_stats, calc_ratios
from analysis.montecarlo import monte_carlo
from analysis.walkforward import walk_forward, walk_forward_by_regime

try:
    from statsmodels.tsa.stattools import coint
    import statsmodels.api as sm
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False

log = logging.getLogger("NEWTON")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
    log.addHandler(_h)

SEP = "─" * 80

# ── RUN IDENTITY ─────────────────────────────────────────────
RUN_ID  = datetime.now().strftime("%Y-%m-%d_%H%M")
RUN_DIR = Path(f"data/newton/{RUN_ID}")
(RUN_DIR / "reports").mkdir(parents=True, exist_ok=True)
(RUN_DIR / "logs").mkdir(parents=True, exist_ok=True)

_fh = logging.FileHandler(RUN_DIR / "logs" / "newton.log", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
log.addHandler(_fh)


# ══════════════════════════════════════════════════════════════
#  COINTEGRATION ANALYSIS
# ══════════════════════════════════════════════════════════════

def find_cointegrated_pairs(all_dfs: dict, min_obs: int = 200) -> list[dict]:
    """
    Engle-Granger cointegration test on all symbol pairs.
    Returns list of valid pairs with stats.
    """
    if not HAS_STATSMODELS:
        log.warning("statsmodels not installed — cannot run cointegration")
        return []

    symbols = sorted(all_dfs.keys())
    pairs = []

    for sym_a, sym_b in combinations(symbols, 2):
        df_a = all_dfs[sym_a]
        df_b = all_dfs[sym_b]

        # align on time
        merged = pd.merge(
            df_a[["time", "close"]].rename(columns={"close": "a"}),
            df_b[["time", "close"]].rename(columns={"close": "b"}),
            on="time", how="inner",
        )
        if len(merged) < min_obs:
            continue

        a = merged["a"].values
        b = merged["b"].values

        try:
            score, pvalue, _ = coint(a, b)
        except Exception:
            continue

        if pvalue > NEWTON_COINT_PVALUE:
            continue

        # OLS hedge ratio: a = beta * b + alpha + epsilon
        b_with_const = sm.add_constant(b)
        model = sm.OLS(a, b_with_const).fit()
        beta = model.params[1]
        alpha = model.params[0]

        # spread
        spread = a - beta * b - alpha

        # half-life via Ornstein-Uhlenbeck
        spread_lag = np.roll(spread, 1)
        spread_lag[0] = spread[0]
        delta = spread[1:] - spread_lag[1:]
        lag_vals = spread_lag[1:]

        if np.std(lag_vals) < 1e-12:
            continue

        X_hl = sm.add_constant(lag_vals)
        model_hl = sm.OLS(delta, X_hl).fit()
        theta = model_hl.params[1]

        if theta >= 0:
            continue  # not mean-reverting

        half_life = -np.log(2) / theta
        if half_life < NEWTON_HALFLIFE_MIN or half_life > NEWTON_HALFLIFE_MAX:
            continue

        pairs.append({
            "sym_a": sym_a,
            "sym_b": sym_b,
            "pvalue": round(pvalue, 6),
            "beta": round(beta, 6),
            "alpha": round(alpha, 6),
            "half_life": round(half_life, 2),
            "spread_std": round(np.std(spread), 8),
        })

    # sort by p-value (most cointegrated first)
    pairs.sort(key=lambda p: p["pvalue"])
    log.info(f"  cointegration  ·  {len(list(combinations(symbols, 2)))} testados  ·  {len(pairs)} validos")
    for p in pairs:
        log.info(f"    {p['sym_a']}/{p['sym_b']}  p={p['pvalue']:.4f}  "
                 f"beta={p['beta']:.4f}  HL={p['half_life']:.1f}")
    return pairs


def calc_spread_zscore(df_a: pd.DataFrame, df_b: pd.DataFrame,
                       beta: float, alpha: float,
                       window: int = NEWTON_SPREAD_WINDOW) -> pd.DataFrame:
    """
    Calculate spread and z-score between two assets.
    Returns merged DataFrame with spread and zscore columns.
    """
    merged = pd.merge(
        df_a[["time", "open", "high", "low", "close", "vol", "tbb", "atr"]].rename(
            columns={c: f"a_{c}" if c != "time" else c for c in df_a.columns}),
        df_b[["time", "close"]].rename(columns={"close": "b_close"}),
        on="time", how="inner",
    )

    merged["spread"] = merged["a_close"] - beta * merged["b_close"] - alpha
    roll_mean = merged["spread"].rolling(window, min_periods=20).mean()
    roll_std = merged["spread"].rolling(window, min_periods=20).std()
    merged["zscore"] = (merged["spread"] - roll_mean) / roll_std.replace(0, np.nan)
    merged["zscore"] = merged["zscore"].fillna(0)

    return merged


# ══════════════════════════════════════════════════════════════
#  SCAN ENGINE
# ══════════════════════════════════════════════════════════════

def scan_pair(df_a: pd.DataFrame, df_b: pd.DataFrame,
              sym_a: str, sym_b: str, pair_info: dict,
              macro_bias_series, corr: dict) -> tuple[list, dict]:
    """
    Scan a cointegrated pair for mean-reversion trades.
    Returns trades in the standard AURUM format.
    """
    beta = pair_info["beta"]
    alpha = pair_info["alpha"]
    half_life = pair_info["half_life"]
    pvalue = pair_info["pvalue"]

    # prepare indicators on the primary asset (sym_a)
    df_a = indicators(df_a)
    df_a = swing_structure(df_a)

    merged = calc_spread_zscore(df_a, df_b, beta, alpha)
    if len(merged) < 300:
        return [], {}

    trades = []
    vetos = defaultdict(int)
    account = ACCOUNT_SIZE
    peak_equity = ACCOUNT_SIZE
    min_idx = max(200, NEWTON_SPREAD_WINDOW + 50)

    zscore = merged["zscore"].values
    a_close = merged["a_close"].values
    a_atr = merged["a_atr"].values if "a_atr" in merged.columns else None
    times = merged["time"].values

    in_trade = False
    trade_dir = None
    trade_entry_idx = None
    trade_entry_price = None
    trade_stop_z = None
    size_held = 0.0

    consecutive_losses = 0
    cooldown_until = -1

    for idx in range(min_idx, len(merged) - 2):
        z = zscore[idx]
        price = a_close[idx]
        atr = a_atr[idx] if a_atr is not None else price * 0.01

        # macro
        macro_b = "CHOP"
        if macro_bias_series is not None:
            ts = pd.Timestamp(times[idx])
            loc = macro_bias_series.index.get_indexer([ts], method="ffill")[0]
            if loc >= 0:
                macro_b = macro_bias_series.iloc[loc]

        peak_equity = max(peak_equity, account)
        current_dd = (peak_equity - account) / peak_equity if peak_equity > 0 else 0.0
        dd_scale = 1.0
        for dd_thresh in sorted(DD_RISK_SCALE.keys(), reverse=True):
            if current_dd >= dd_thresh:
                dd_scale = DD_RISK_SCALE[dd_thresh]
                break
        if dd_scale == 0.0:
            vetos["dd_pause"] += 1
            continue

        if idx <= cooldown_until:
            vetos["streak_cooldown"] += 1
            continue

        vol_r = "NORMAL"

        # ── EXIT check ──
        if in_trade:
            exit_now = False
            result = None

            if trade_dir == "BEARISH":
                # short spread: entered when z > entry_z, exit when z <= 0
                if z <= NEWTON_ZSCORE_EXIT:
                    exit_now = True
                    result = "WIN"
                elif z >= NEWTON_ZSCORE_STOP:
                    exit_now = True
                    result = "LOSS"
            else:
                # long spread: entered when z < -entry_z, exit when z >= 0
                if z >= NEWTON_ZSCORE_EXIT:
                    exit_now = True
                    result = "WIN"
                elif z <= -NEWTON_ZSCORE_STOP:
                    exit_now = True
                    result = "LOSS"

            # max hold
            duration = idx - trade_entry_idx
            if not exit_now and duration >= NEWTON_MAX_HOLD:
                exit_now = True
                # partial mean reversion?
                if trade_dir == "BEARISH":
                    result = "WIN" if z < zscore[trade_entry_idx] else "LOSS"
                else:
                    result = "WIN" if z > zscore[trade_entry_idx] else "LOSS"

            if exit_now:
                exit_p = price
                duration = idx - trade_entry_idx

                # PnL calculation
                entry_p = trade_entry_price
                slip_exit = SLIPPAGE + SPREAD
                if trade_dir == "BULLISH":
                    entry_cost = entry_p * (1 + COMMISSION)
                    ep_net = exit_p * (1 - COMMISSION - slip_exit)
                    funding = -(size_held * entry_p * FUNDING_PER_8H * duration / 32)
                    pnl = size_held * (ep_net - entry_cost) + funding
                else:
                    entry_cost = entry_p * (1 - COMMISSION)
                    ep_net = exit_p * (1 + COMMISSION + slip_exit)
                    funding = +(size_held * entry_p * FUNDING_PER_8H * duration / 32)
                    pnl = size_held * (entry_cost - ep_net) + funding
                pnl = round(pnl * LEVERAGE, 2)
                account = max(account + pnl, account * 0.5)

                if result == "LOSS":
                    consecutive_losses += 1
                    for n_losses in sorted(STREAK_COOLDOWN.keys(), reverse=True):
                        if consecutive_losses >= n_losses:
                            cooldown_until = idx + STREAK_COOLDOWN[n_losses]
                            break
                else:
                    consecutive_losses = 0

                # target for RR calc
                if trade_dir == "BULLISH":
                    stop_price = trade_entry_price - atr * 2.0
                    target_price = trade_entry_price + atr * 2.0
                else:
                    stop_price = trade_entry_price + atr * 2.0
                    target_price = trade_entry_price - atr * 2.0

                risk = abs(trade_entry_price - stop_price)
                rr = abs(exit_p - trade_entry_price) / risk if risk > 0 else 0.0

                ts_str = pd.Timestamp(times[trade_entry_idx]).strftime("%d/%m %Hh")
                t = {
                    "symbol":     sym_a,
                    "pair":       f"{sym_a}/{sym_b}",
                    "time":       ts_str,
                    "timestamp":  pd.Timestamp(times[trade_entry_idx]),
                    "idx":        trade_entry_idx,
                    "entry_idx":  trade_entry_idx + 1,
                    "strategy":   "NEWTON",
                    "direction":  trade_dir,
                    "trade_type": "MEAN-REV",
                    "struct":     macro_b,
                    "struct_str": 0.5,
                    "cascade_n":  0,
                    "taker_ma":   0.5,
                    "rsi":        50.0,
                    "dist_ema21": 0.0,
                    "macro_bias": macro_b,
                    "vol_regime": vol_r,
                    "dd_scale":   round(dd_scale, 2),
                    "corr_mult":  1.0,
                    "in_transition": False,
                    "trans_mult":    1.0,
                    "entry":      round(trade_entry_price, 8),
                    "stop":       round(stop_price, 4),
                    "target":     round(target_price, 4),
                    "exit_p":     round(exit_p, 6),
                    "rr":         round(rr, 2),
                    "duration":   duration,
                    "result":     result,
                    "pnl":        pnl,
                    "size":       round(size_held, 4),
                    "score":      round(1.0 - pvalue, 3),
                    "fractal_align": 1.0,
                    "omega_struct":   0.0, "omega_flow":     0.0,
                    "omega_cascade":  0.0, "omega_momentum": 0.0,
                    "omega_pullback": 0.0,
                    "chop_trade":     False,
                    "bb_mid":         0.0,
                    # newton-specific
                    "zscore_entry": round(zscore[trade_entry_idx], 3),
                    "zscore_exit":  round(z, 3),
                    "half_life":    half_life,
                    "coint_pvalue": pvalue,
                    "beta":         beta,
                    "trade_time":   ts_str,
                }
                trades.append(t)
                icon = "✓" if result == "WIN" else "✗"
                log.info(f"  {ts_str}  {icon}  {sym_a}/{sym_b}  {trade_dir:8s}  "
                         f"z={zscore[trade_entry_idx]:+.2f}→{z:+.2f}  ${pnl:+.2f}")

                in_trade = False
                trade_dir = None
                continue

        # ── ENTRY check ──
        if in_trade:
            continue

        # z-score entry conditions
        direction = None
        if z > NEWTON_ZSCORE_ENTRY:
            direction = "BEARISH"   # spread too high → short spread → short A, long B
        elif z < -NEWTON_ZSCORE_ENTRY:
            direction = "BULLISH"   # spread too low → long spread → long A, short B

        if direction is None:
            continue

        # vol filter
        if vol_r == "EXTREME":
            vetos["vol_extreme"] += 1
            continue

        # score based on cointegration strength and z-score extremity
        z_strength = min(abs(z) / 3.0, 1.0)
        coint_strength = 1.0 - pvalue / NEWTON_COINT_PVALUE
        score = 0.5 * coint_strength + 0.5 * z_strength

        # entry
        entry_p = price
        stop_dist = atr * 2.0
        if direction == "BULLISH":
            stop_p = entry_p - stop_dist
            target_p = entry_p + stop_dist * TARGET_RR
        else:
            stop_p = entry_p + stop_dist
            target_p = entry_p - stop_dist * TARGET_RR

        size = position_size(account, entry_p, stop_p, max(score, 0.53),
                             macro_b, direction, vol_r, dd_scale)
        size = round(size * NEWTON_SIZE_MULT, 4)

        if size <= 0:
            vetos["size_zero"] += 1
            continue

        in_trade = True
        trade_dir = direction
        trade_entry_idx = idx
        trade_entry_price = entry_p
        size_held = size

    closed = [t for t in trades if t["result"] in ("WIN", "LOSS")]
    w = sum(1 for t in closed if t["result"] == "WIN")
    log.info(f"  {sym_a}/{sym_b}  TOTAL: {len(trades)}  W={w}  L={len(closed)-w}  "
             f"PnL=${sum(t['pnl'] for t in closed):+,.0f}")
    return trades, dict(vetos)


def scan_newton(df: pd.DataFrame, symbol: str,
                macro_bias_series, corr: dict,
                htf_stack_dfs: dict | None = None,
                all_dfs: dict | None = None,
                pairs: list[dict] | None = None) -> tuple[list, dict]:
    """
    Standard scan interface for NEWTON.
    Scans all cointegrated pairs involving `symbol`.
    """
    if all_dfs is None or pairs is None:
        return [], {}

    all_trades = []
    all_vetos = defaultdict(int)

    for pair in pairs:
        if pair["sym_a"] == symbol:
            df_b = all_dfs.get(pair["sym_b"])
            if df_b is None:
                continue
            trades, vetos = scan_pair(
                df.copy(), df_b, symbol, pair["sym_b"], pair,
                macro_bias_series, corr)
        elif pair["sym_b"] == symbol:
            df_a = all_dfs.get(pair["sym_a"])
            if df_a is None:
                continue
            trades, vetos = scan_pair(
                df_a.copy(), df.copy(), pair["sym_a"], symbol, pair,
                macro_bias_series, corr)
        else:
            continue

        all_trades.extend(trades)
        for k, v in vetos.items():
            all_vetos[k] += v

    return all_trades, dict(all_vetos)


# ══════════════════════════════════════════════════════════════
#  RESULTS & EXPORT
# ══════════════════════════════════════════════════════════════

def print_header(n_pairs: int):
    print(f"\n{SEP}")
    print(f"  NEWTON v1.0  ·  {RUN_ID}")
    print(f"  {len(SYMBOLS)} ativos  ·  {n_pairs} pares  ·  {INTERVAL}  ·  ${ACCOUNT_SIZE:,.0f}  ·  {LEVERAGE}x")
    print(f"  z-entry {NEWTON_ZSCORE_ENTRY}  ·  z-stop {NEWTON_ZSCORE_STOP}  ·  HL {NEWTON_HALFLIFE_MIN}-{NEWTON_HALFLIFE_MAX}")
    print(f"  {RUN_DIR}/")
    print(SEP)


def print_results(all_trades: list):
    closed = [t for t in all_trades if t["result"] in ("WIN", "LOSS")]
    if not closed:
        print("  sem trades")
        return

    print(f"\n{SEP}\n  RESULTADOS POR PAR\n{SEP}")

    by_pair: dict[str, list] = {}
    for t in closed:
        pair = t.get("pair", t["symbol"])
        by_pair.setdefault(pair, []).append(t)

    print(f"  {'PAR':24s}  {'N':>4s}  {'WR':>6s}  {'PnL':>12s}")
    print(f"  {'─'*52}")
    for pair in sorted(by_pair):
        ts = by_pair[pair]
        w = sum(1 for t in ts if t["result"] == "WIN")
        wr = w / len(ts) * 100
        pnl = sum(t["pnl"] for t in ts)
        c = "✓" if pnl > 0 else "✗"
        print(f"  {c}  {pair:22s}  {len(ts):>4d}  {wr:>5.1f}%  ${pnl:>+10,.0f}")


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


def export_json(all_trades, eq, mc, ratios, pairs):
    import json
    closed = [t for t in all_trades if t["result"] in ("WIN", "LOSS")]
    wr = sum(1 for t in closed if t["result"] == "WIN") / max(len(closed), 1) * 100

    data = {
        "engine": "NEWTON",
        "version": "1.0",
        "run_id": RUN_ID,
        "timestamp": datetime.now().isoformat(),
        "interval": INTERVAL,
        "n_symbols": len(SYMBOLS),
        "n_pairs": len(pairs),
        "account_size": ACCOUNT_SIZE,
        "leverage": LEVERAGE,
        "n_trades": len(closed),
        "win_rate": round(wr, 2),
        "roi": round(ratios["ret"], 2),
        "sharpe": ratios["sharpe"],
        "sortino": ratios.get("sortino"),
        "final_equity": round(eq[-1], 2) if eq else ACCOUNT_SIZE,
        "max_dd_pct": round(ratios.get("max_dd_pct", 0), 2),
        "pairs": pairs,
        "trades": [{k: (v.isoformat() if isinstance(v, pd.Timestamp) else
                        float(v) if isinstance(v, (np.floating, np.integer)) else v)
                    for k, v in t.items()} for t in closed],
    }

    out = RUN_DIR / "reports" / f"newton_{INTERVAL}_v1.json"
    out.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print(f"  json  ·  {out}")
    log.info(f"JSON → {out}")

    # register in DB
    try:
        from core.db import register_run
        register_run(
            run_id=RUN_ID,
            engine="newton",
            json_path=str(out),
            roi=ratios["ret"],
            sharpe=ratios.get("sharpe"),
            sortino=ratios.get("sortino"),
            win_rate=wr,
            n_trades=len(closed),
            final_equity=eq[-1] if eq else ACCOUNT_SIZE,
            account_size=ACCOUNT_SIZE,
            interval=INTERVAL,
            n_symbols=len(SYMBOLS),
            version="1.0",
        )
    except Exception as e:
        log.warning(f"DB register failed: {e}")


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"\n{SEP}")
    print(f"  NEWTON  ·  Statistical Mean Reversion")
    print(f"  {SEP}")

    if not HAS_STATSMODELS:
        print("  statsmodels nao instalado — pip install statsmodels")
        sys.exit(1)

    _days_in = safe_input(f"\n  periodo em dias [{SCAN_DAYS}] > ").strip()
    if _days_in.isdigit() and 7 <= int(_days_in) <= 1500:
        SCAN_DAYS = int(_days_in)
    _tf_mult = {"1m": 60, "3m": 20, "5m": 12, "15m": 4, "30m": 2, "1h": 1, "2h": 0.5, "4h": 0.25}
    N_CANDLES = int(SCAN_DAYS * 24 * _tf_mult.get(INTERVAL, 4))

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
    print(f"  NEWTON  ·  {SCAN_DAYS}d  ·  {len(SYMBOLS)} ativos  ·  {INTERVAL}")
    print(f"  ${ACCOUNT_SIZE:,.0f}  ·  {LEVERAGE}x  ·  z-entry {NEWTON_ZSCORE_ENTRY}  ·  z-stop {NEWTON_ZSCORE_STOP}")
    print(f"  {RUN_DIR}/")
    print(SEP)
    safe_input("  enter para iniciar... ")

    log.info(f"NEWTON v1.0 iniciado — {RUN_ID}  tf={INTERVAL}  dias={SCAN_DAYS}")

    # ── FETCH DATA ──
    print(f"\n{SEP}\n  DADOS   {INTERVAL}   {N_CANDLES:,} candles\n{SEP}")
    all_dfs = fetch_all(SYMBOLS, INTERVAL, N_CANDLES)
    for sym, df in all_dfs.items():
        validate(df, sym)
    if not all_dfs:
        print("  sem dados")
        sys.exit(1)

    # ── MACRO & CORRELATION ──
    macro_bias = detect_macro(all_dfs)
    corr = build_corr_matrix(all_dfs)

    # ── COINTEGRATION ──
    print(f"\n{SEP}\n  COINTEGRATION ANALYSIS\n{SEP}")
    pairs = find_cointegrated_pairs(all_dfs)

    if len(pairs) < NEWTON_MIN_PAIRS:
        print(f"  apenas {len(pairs)} pares cointegrados (minimo: {NEWTON_MIN_PAIRS})")
        print(f"  tenta aumentar o periodo ou os simbolos")
        sys.exit(1)

    print_header(len(pairs))

    # ── SCAN ALL PAIRS ──
    print(f"\n{SEP}\n  SCAN PAIRS\n{SEP}")
    all_trades = []
    all_vetos = defaultdict(int)

    for pair in pairs:
        df_a = all_dfs.get(pair["sym_a"])
        df_b = all_dfs.get(pair["sym_b"])
        if df_a is None or df_b is None:
            continue

        trades, vetos = scan_pair(
            df_a.copy(), df_b.copy(), pair["sym_a"], pair["sym_b"], pair,
            macro_bias, corr)
        all_trades.extend(trades)
        for k, v in vetos.items():
            all_vetos[k] += v

    # sort by timestamp
    all_trades.sort(key=lambda t: t["timestamp"])

    closed = [t for t in all_trades if t["result"] in ("WIN", "LOSS")]
    if not closed:
        print(f"\n  sem trades fechados")
        sys.exit(1)

    print_results(all_trades)

    # ── METRICS ──
    pnl_list = [t["pnl"] for t in closed]
    eq, mdd, mdd_pct, max_streak = equity_stats(pnl_list)
    ratios = calc_ratios(pnl_list, n_days=SCAN_DAYS)
    ratios["max_dd_pct"] = mdd_pct

    wr = sum(1 for t in closed if t["result"] == "WIN") / len(closed) * 100
    total_pnl = sum(pnl_list)

    print(f"\n{SEP}\n  METRICAS\n{SEP}")
    print(f"  Trades    {len(closed)}")
    print(f"  WR        {wr:.1f}%")
    print(f"  ROI       {ratios['ret']:+.2f}%")
    print(f"  Sharpe    {ratios['sharpe']:.3f}" if ratios["sharpe"] else "  Sharpe    —")
    print(f"  Sortino   {ratios['sortino']:.3f}" if ratios.get("sortino") else "  Sortino   —")
    print(f"  MaxDD     {mdd_pct:.1f}%")
    print(f"  Final     ${eq[-1]:,.0f}")
    print(f"  Streak    {max_streak} losses")

    # ── MONTE CARLO ──
    mc = monte_carlo(pnl_list)
    if mc:
        print(f"\n{SEP}\n  MONTE CARLO   {MC_N}x   bloco={MC_BLOCK}\n{SEP}")
        print(f"  Positivo  {mc['pct_pos']:.0f}%")
        print(f"  Mediana   ${mc['median']:,.0f}")
        print(f"  P5/P95    ${mc['p5']:,.0f} / ${mc['p95']:,.0f}")
        print(f"  Risco     {mc['ror']:.1f}%")

    # ── WALK-FORWARD ──
    wf = walk_forward(closed)
    if wf:
        print(f"\n{SEP}\n  WALK-FORWARD   {len(wf)} janelas\n{SEP}")
        for w in wf:
            delta = w["test"]["wr"] - w["train"]["wr"]
            ok = "ok" if abs(delta) <= 15 else "xx"
            print(f"  {w['w']:>4d}  treino {w['train']['wr']:.1f}%  "
                  f"fora {w['test']['wr']:.1f}%  D {delta:+.1f}%  {ok}")

    # ── VEREDITO ──
    print_veredito(all_trades, eq, mdd_pct, mc, wf, ratios)

    # ── EXPORT ──
    export_json(all_trades, eq, mc, ratios, pairs)

    # ── VETOS ──
    if all_vetos:
        print(f"\n{SEP}\n  VETOS\n{SEP}")
        for k, v in sorted(all_vetos.items(), key=lambda x: -x[1]):
            print(f"  {v:>6d}  {k}")

    print(f"\n{SEP}\n  output  ·  {RUN_DIR}/\n{SEP}\n")
