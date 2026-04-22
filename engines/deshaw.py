"""
AURUM Finance — DE SHAW Engine v1.0 (ARCHIVED)
Statistical Mean Reversion via Pairs Trading (Engle-Granger Cointegration)

🗄️ ARCHIVED 2026-04-22 — NO_EDGE veredito confirmado

Audit verdict (docs/audits/2026-04-22_deshaw_phi_ornstein_archive_verdict.md):
- Backtest 360d bluechip 1h (2026-04-22): Sharpe −0.19, ROI −0.33%
- 4 gates do overfit audit falharam:
  - Walk-forward FAIL: 3/5 windows negativas (W2 −1.43, W5 −4.29)
  - Regime concentration FAIL: 98/101 trades em BULL (esperado CHOP-only)
  - Symbol concentration FAIL: FETUSDT 363% do PnL negativo
  - Temporal decay FAIL: 246% deterioracao entre halves
- Edge de 2026-04-16 (Sharpe +1.15 730d z=3.0 pvalue=0.15) era overfit
  massivo. Colapsou em janela recente.

Grid esgotado: z-entry (2.0→4.0), pvalue (0.05→0.15), half-life
(100→300), regime gates (CHOP, CHOP+BULL), HMM thresholds — todas
combinacoes razoaveis testadas sem edge OOS.

Mecanismo quebrado em crypto: cointegracao pressupoe relacao
estrutural persistente e regime-independente. Crypto e regime-
dependent — BEAR correlacoes colapsam, BULL spreads desacoplam,
CHOP reversion e fragil.

Nao reformular, nao re-tunar. Se aparecer evidencia nova (e.g.,
pares intra-setor stable+stable, ou nova janela de dados com
cointegration robusta), reabrir com NOVA hipotese, nao novo grid.

Conceito original abaixo, mantido pra referencia historica.

---

Conceito: pares co-integrados divergem do equilíbrio e convergem.
Oposto do AZOTH — opera reversão à média em vez de trend-following.

Pipeline:
  1. Cointegração Engle-Granger entre todos os pares do universo
  2. Z-score do spread com rolling window
  3. Half-life via OLS (Ornstein-Uhlenbeck)
  4. Entry: |z| > 2.0, Exit: z cruza 0, Stop: |z| > 3.5

CLI overrides --z-entry / --z-exit / --z-stop / --pvalue / --hl-max /
--max-hold / --size-mult enable sweeps without touching config.params.
"""
import sys
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import logging
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from itertools import combinations

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.params import *
# Calibrated TF (longrun battery 2026-04-14: 1h >> 15m/4h)
INTERVAL = ENGINE_INTERVALS.get("DESHAW", INTERVAL)
from core.chronos import enrich_with_regime
from core import (
    fetch_all, validate, indicators, swing_structure,
    detect_macro, build_corr_matrix, portfolio_allows, check_aggregate_notional,
    position_size,
)
from core.ops.fs import atomic_write
from analysis.stats import equity_stats, calc_ratios
from analysis.montecarlo import monte_carlo
from analysis.walkforward import walk_forward, walk_forward_by_regime

try:
    from statsmodels.tsa.stattools import coint
    import statsmodels.api as sm
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False

log = logging.getLogger("DE_SHAW")  # DE SHAW (formerly NEWTON) — Statistical arb engine
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
    log.addHandler(_h)

SEP = "─" * 80

# ── RUN IDENTITY ─────────────────────────────────────────────
RUN_ID  = datetime.now().strftime("%Y-%m-%d_%H%M%S")
RUN_DIR = Path(f"data/deshaw/{RUN_ID}")
(RUN_DIR / "reports").mkdir(parents=True, exist_ok=True)
(RUN_DIR / "logs").mkdir(parents=True, exist_ok=True)

_fh = logging.FileHandler(RUN_DIR / "logs" / "newton.log", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
log.addHandler(_fh)

_BETA_MIN = float(globals().get("NEWTON_BETA_MIN", 0.10))
_BETA_MAX = float(globals().get("NEWTON_BETA_MAX", 4.00))
_MAX_REUSE_PER_SYMBOL = int(globals().get("NEWTON_MAX_REUSE_PER_SYMBOL", 2))
_MIN_EDGE_COST_MULT = float(globals().get("NEWTON_MIN_EDGE_COST_MULT", 1.5))
_ROLLING_MIN_SIGHTINGS = int(globals().get("NEWTON_ROLLING_MIN_SIGHTINGS", 2))
_PAIR_EDGE_COST_MULT = float(globals().get("NEWTON_PAIR_EDGE_COST_MULT", 1.0))
_PAIR_MIN_TRAIN_TRADES = int(globals().get("NEWTON_PAIR_MIN_TRAIN_TRADES", 3))
_PAIR_MIN_PROFIT_FACTOR = float(globals().get("NEWTON_PAIR_MIN_PROFIT_FACTOR", 1.1))
_ENTRY_CHOP_ONLY = bool(globals().get("NEWTON_ENTRY_CHOP_ONLY", True))
_ALLOWED_MACRO_ENTRY = {
    token.strip().upper()
    for token in str(globals().get("NEWTON_ALLOWED_MACRO_ENTRY", "CHOP,BULL")).split(",")
    if token.strip()
}
_MIN_HMM_CHOP_PROB = float(globals().get("NEWTON_MIN_HMM_CHOP_PROB", 0.35))
_MAX_HMM_TREND_PROB = float(globals().get("NEWTON_MAX_HMM_TREND_PROB", 0.55))
_MAX_REVALIDATION_MISSES = int(globals().get("NEWTON_MAX_REVALIDATION_MISSES", 1))


def _spread_regime_input(merged: pd.DataFrame) -> pd.DataFrame:
    """Build a HMM input frame from the spread residual itself.

    DE SHAW's thesis is about mean reversion of the *relationship* between
    legs, not the absolute trend regime of leg A. We therefore derive the
    regime signal from the residual spread (`spread - spread_mean`) and shift
    it into positive territory so chronos can safely compute log returns.
    """
    spread = merged["spread"].astype(float)
    spread_mean = merged["spread_mean"].astype(float)
    residual = (spread - spread_mean).fillna(0.0)
    floor = max(float(residual.std(ddof=0)) * 0.1, 1.0)
    synthetic_close = residual - float(residual.min()) + floor
    regime_df = merged.copy()
    regime_df["close"] = synthetic_close
    return regime_df


def _runtime_newton_snapshot() -> dict:
    """Capture the effective DE SHAW runtime params after CLI overrides."""
    return {
        "NEWTON_ZSCORE_ENTRY": float(NEWTON_ZSCORE_ENTRY),
        "NEWTON_ZSCORE_EXIT": float(NEWTON_ZSCORE_EXIT),
        "NEWTON_ZSCORE_STOP": float(NEWTON_ZSCORE_STOP),
        "NEWTON_COINT_PVALUE": float(NEWTON_COINT_PVALUE),
        "NEWTON_HALFLIFE_MIN": int(NEWTON_HALFLIFE_MIN),
        "NEWTON_HALFLIFE_MAX": int(NEWTON_HALFLIFE_MAX),
        "NEWTON_SPREAD_WINDOW": int(NEWTON_SPREAD_WINDOW),
        "NEWTON_RECALC_EVERY": int(NEWTON_RECALC_EVERY),
        "NEWTON_MAX_HOLD": int(NEWTON_MAX_HOLD),
        "NEWTON_SIZE_MULT": float(NEWTON_SIZE_MULT),
        "NEWTON_MIN_PAIRS": int(NEWTON_MIN_PAIRS),
        "NEWTON_ENTRY_CHOP_ONLY": bool(_ENTRY_CHOP_ONLY),
        "NEWTON_ALLOWED_MACRO_ENTRY": ",".join(sorted(_ALLOWED_MACRO_ENTRY)),
        "NEWTON_MIN_HMM_CHOP_PROB": float(_MIN_HMM_CHOP_PROB),
        "NEWTON_MAX_HMM_TREND_PROB": float(_MAX_HMM_TREND_PROB),
        "NEWTON_MAX_REVALIDATION_MISSES": int(_MAX_REVALIDATION_MISSES),
    }


def _apply_runtime_snapshot_overrides(config: dict, basket_name: str) -> dict:
    """Patch snapshot_config() output with the effective engine-local runtime."""
    patched = dict(config)
    patched.update(_runtime_newton_snapshot())
    patched["INTERVAL"] = INTERVAL
    patched["SCAN_DAYS"] = int(SCAN_DAYS)
    patched["N_CANDLES"] = int(N_CANDLES)
    patched["LEVERAGE"] = float(LEVERAGE)
    patched["SYMBOLS"] = list(SYMBOLS)
    patched["BASKET_EFFECTIVE"] = basket_name
    return patched


def _pair_stats_from_prices(a: np.ndarray, b: np.ndarray) -> dict | None:
    if not HAS_STATSMODELS:
        return None
    if len(a) < 2 or len(b) < 2:
        return None

    try:
        _, pvalue, _ = coint(a, b)
    except Exception:
        return None

    if pvalue > NEWTON_COINT_PVALUE:
        return None

    try:
        b_with_const = sm.add_constant(b)
        model = sm.OLS(a, b_with_const).fit()
        beta = float(model.params[1])
        alpha = float(model.params[0])
    except Exception:
        return None

    if abs(beta) < _BETA_MIN or abs(beta) > _BETA_MAX:
        return None

    if not _pair_has_economic_width(a, b, beta, alpha):
        return None

    spread = a - beta * b - alpha
    spread_lag = np.roll(spread, 1)
    spread_lag[0] = spread[0]
    delta = spread[1:] - spread_lag[1:]
    lag_vals = spread_lag[1:]
    if np.std(lag_vals) < 1e-12:
        return None

    try:
        X_hl = sm.add_constant(lag_vals)
        model_hl = sm.OLS(delta, X_hl).fit()
        theta = float(model_hl.params[1])
    except Exception:
        return None

    if theta >= 0:
        return None

    half_life = -np.log(2) / theta
    if half_life < NEWTON_HALFLIFE_MIN or half_life > NEWTON_HALFLIFE_MAX:
        return None

    return {
        "pvalue": round(pvalue, 6),
        "beta": round(beta, 6),
        "alpha": round(alpha, 6),
        "half_life": round(float(half_life), 2),
        "spread_std": round(float(np.std(spread)), 8),
    }


def _pair_has_economic_width(a: np.ndarray, b: np.ndarray, beta: float, alpha: float) -> bool:
    if len(a) == 0 or len(b) == 0:
        return False
    spread = a - beta * b - alpha
    spread_std = float(np.std(spread))
    median_notional = float(np.median(np.abs(a) + np.abs(beta) * np.abs(b)))
    if median_notional <= 1e-9:
        return False
    gross_edge_frac = spread_std / median_notional
    roundtrip_cost_frac = 2.0 * (SLIPPAGE + SPREAD + COMMISSION)
    return gross_edge_frac >= roundtrip_cost_frac * _PAIR_EDGE_COST_MULT


def _pair_payoff_stats_window(df_a: pd.DataFrame, df_b: pd.DataFrame, pair_info: dict) -> dict:
    beta = pair_info["beta"]
    alpha = pair_info["alpha"]

    df_a = indicators(df_a.copy())
    merged = calc_spread_zscore(df_a, df_b.copy(), beta, alpha)
    if len(merged) < max(80, NEWTON_SPREAD_WINDOW + 20):
        return {"n_trades": 0, "pnl": 0.0, "expectancy": 0.0, "profit_factor": 0.0}

    zscore = merged["zscore"].values
    spread_vals = merged["spread"].values
    spread_mean_vals = merged["spread_mean"].values
    a_open = merged["a_open"].values if "a_open" in merged.columns else merged["a_close"].values
    a_close = merged["a_close"].values
    a_high = merged["a_high"].values if "a_high" in merged.columns else a_close
    a_low = merged["a_low"].values if "a_low" in merged.columns else a_close
    b_open = merged["b_open"].values if "b_open" in merged.columns else merged["b_close"].values
    b_close = merged["b_close"].values
    a_atr = merged["a_atr"].values if "a_atr" in merged.columns else None

    _MAINT_MARGIN = 0.005

    def _liq_price(entry: float, direction: str) -> float:
        if LEVERAGE <= 1.0:
            return -1.0 if direction == "BULLISH" else entry * 10.0
        if direction == "BULLISH":
            return entry * (1 - 1 / LEVERAGE + _MAINT_MARGIN)
        return entry * (1 + 1 / LEVERAGE - _MAINT_MARGIN)

    pnls = []
    min_idx = max(40, NEWTON_SPREAD_WINDOW)
    in_trade = False
    trade_dir = None
    trade_entry_idx = None
    trade_entry_price = None
    trade_entry_price_b = None
    size_held = 1.0

    for idx in range(min_idx, len(merged) - 2):
        z = zscore[idx]
        atr = a_atr[idx] if a_atr is not None else a_close[idx] * 0.01

        if in_trade:
            exit_now = False
            result = None
            if trade_dir == "BULLISH":
                if a_low[idx] <= _liq_price(trade_entry_price, "BULLISH"):
                    exit_now = True
                    result = "LOSS"
            else:
                if a_high[idx] >= _liq_price(trade_entry_price, "BEARISH"):
                    exit_now = True
                    result = "LOSS"

            if not exit_now and trade_dir == "BEARISH":
                if z <= NEWTON_ZSCORE_EXIT:
                    exit_now = True
                    result = "WIN"
                elif z >= NEWTON_ZSCORE_STOP:
                    exit_now = True
                    result = "LOSS"
            elif not exit_now:
                if z >= NEWTON_ZSCORE_EXIT:
                    exit_now = True
                    result = "WIN"
                elif z <= -NEWTON_ZSCORE_STOP:
                    exit_now = True
                    result = "LOSS"

            duration = idx - trade_entry_idx
            if not exit_now and duration >= NEWTON_MAX_HOLD:
                exit_now = True
                result = "WIN" if (
                    (trade_dir == "BEARISH" and z < zscore[trade_entry_idx]) or
                    (trade_dir == "BULLISH" and z > zscore[trade_entry_idx])
                ) else "LOSS"

            if exit_now:
                pnl = _pair_pnl(
                    direction=trade_dir,
                    beta=beta,
                    entry_a_raw=trade_entry_price,
                    exit_a_raw=float(a_close[idx]),
                    entry_b_raw=trade_entry_price_b,
                    exit_b_raw=float(b_close[idx]),
                    size_a=size_held,
                    duration=duration,
                )
                pnls.append(float(pnl))
                in_trade = False
                continue

        if in_trade:
            continue

        direction = None
        if z > NEWTON_ZSCORE_ENTRY:
            direction = "BEARISH"
        elif z < -NEWTON_ZSCORE_ENTRY:
            direction = "BULLISH"
        if direction is None:
            continue

        if idx + 1 >= len(merged):
            continue
        raw_entry = float(a_open[idx + 1])
        raw_entry_b = float(b_open[idx + 1])
        spread_deviation = float(spread_vals[idx] - spread_mean_vals[idx]) if not pd.isna(spread_mean_vals[idx]) else 0.0
        if not _pair_has_edge_after_costs(
            spread_deviation=spread_deviation,
            notional_a=raw_entry,
            notional_b=abs(beta) * raw_entry_b,
        ):
            continue
        if atr <= 0:
            continue

        in_trade = True
        trade_dir = direction
        trade_entry_idx = idx
        trade_entry_price = raw_entry
        trade_entry_price_b = raw_entry_b

    if not pnls:
        return {"n_trades": 0, "pnl": 0.0, "expectancy": 0.0, "profit_factor": 0.0}

    gains = sum(p for p in pnls if p > 0)
    losses = abs(sum(p for p in pnls if p < 0))
    profit_factor = gains / losses if losses > 1e-9 else (999.0 if gains > 0 else 0.0)
    total_pnl = float(sum(pnls))
    expectancy = total_pnl / len(pnls)
    return {
        "n_trades": len(pnls),
        "pnl": round(total_pnl, 2),
        "expectancy": round(expectancy, 4),
        "profit_factor": round(float(profit_factor), 4),
    }


def _pair_is_tradeable_window(df_a: pd.DataFrame, df_b: pd.DataFrame, pair_info: dict) -> bool:
    stats = _pair_payoff_stats_window(df_a, df_b, pair_info)
    pair_info.update({
        "train_n_trades": stats["n_trades"],
        "train_pnl": stats["pnl"],
        "train_expectancy": stats["expectancy"],
        "train_profit_factor": stats["profit_factor"],
    })
    return (
        stats["n_trades"] >= _PAIR_MIN_TRAIN_TRADES and
        stats["pnl"] > 0 and
        stats["expectancy"] > 0 and
        stats["profit_factor"] >= _PAIR_MIN_PROFIT_FACTOR
    )


def _revalidate_pair_window(df_a: pd.DataFrame, df_b: pd.DataFrame,
                            end_idx: int, window_bars: int) -> dict | None:
    start_idx = max(0, end_idx - window_bars + 1)
    a = df_a["close"].iloc[start_idx:end_idx + 1].to_numpy(dtype=float)
    b = df_b["close"].iloc[start_idx:end_idx + 1].to_numpy(dtype=float)
    if len(a) < max(50, NEWTON_SPREAD_WINDOW):
        return None
    return _pair_stats_from_prices(a, b)


def _apply_pair_selection_limits(pairs: list[dict]) -> list[dict]:
    pairs = sorted(
        pairs,
        key=lambda p: (
            -float(p.get("train_profit_factor", 0.0)),
            -float(p.get("train_pnl", 0.0)),
            p["pvalue"],
        ),
    )
    selected = []
    symbol_usage = defaultdict(int)
    for pair in pairs:
        if symbol_usage[pair["sym_a"]] >= _MAX_REUSE_PER_SYMBOL:
            continue
        if symbol_usage[pair["sym_b"]] >= _MAX_REUSE_PER_SYMBOL:
            continue
        selected.append(pair)
        symbol_usage[pair["sym_a"]] += 1
        symbol_usage[pair["sym_b"]] += 1
    return selected


# ══════════════════════════════════════════════════════════════
#  COINTEGRATION ANALYSIS
# ══════════════════════════════════════════════════════════════

def find_cointegrated_pairs(all_dfs: dict, min_obs: int = 200,
                            log_results: bool = True) -> list[dict]:
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

        pair_stats = _pair_stats_from_prices(a, b)
        if pair_stats is None:
            continue

        pairs.append({
            "sym_a": sym_a,
            "sym_b": sym_b,
            **pair_stats,
        })

    pairs = _apply_pair_selection_limits(pairs)
    if log_results:
        log.info(f"  cointegration  ·  {len(list(combinations(symbols, 2)))} testados  ·  {len(pairs)} validos")
        for p in pairs:
            log.info(f"    {p['sym_a']}/{p['sym_b']}  p={p['pvalue']:.4f}  "
                     f"beta={p['beta']:.4f}  HL={p['half_life']:.1f}")
    return pairs


def discover_cointegrated_pairs_over_time(all_dfs: dict, min_obs: int = 200,
                                          window_bars: int | None = None,
                                          step_bars: int | None = None) -> list[dict]:
    if not all_dfs:
        return []

    sample_df = next(iter(all_dfs.values()))
    if sample_df is None or len(sample_df) < min_obs:
        return []

    window_bars = window_bars or max(min_obs, NEWTON_SPREAD_WINDOW + 50, int(NEWTON_RECALC_EVERY) * 4)
    step_bars = step_bars or max(1, int(NEWTON_RECALC_EVERY))
    last_idx = len(sample_df) - 1
    checkpoints = range(window_bars - 1, last_idx + 1, step_bars)

    best_by_pair: dict[tuple[str, str], dict] = {}
    sightings: dict[tuple[str, str], int] = defaultdict(int)
    for end_idx in checkpoints:
        sliced = {}
        start_idx = max(0, end_idx - window_bars + 1)
        for sym, df in all_dfs.items():
            sub = df.iloc[start_idx:end_idx + 1].copy()
            if len(sub) >= min_obs:
                sliced[sym] = sub
        if len(sliced) < 2:
            continue
        for pair in find_cointegrated_pairs(sliced, min_obs=min_obs, log_results=False):
            if not _pair_is_tradeable_window(sliced[pair["sym_a"]], sliced[pair["sym_b"]], pair):
                continue
            key = (pair["sym_a"], pair["sym_b"])
            sightings[key] += 1
            prev = best_by_pair.get(key)
            if prev is None or pair["pvalue"] < prev["pvalue"]:
                best_by_pair[key] = pair

    persistent = [
        pair for key, pair in best_by_pair.items()
        if sightings[key] >= _ROLLING_MIN_SIGHTINGS
    ]
    pairs = _apply_pair_selection_limits(persistent)
    log.info(
        f"  cointegration rolling  ·  {len(best_by_pair)} candidatos unicos  ·  "
        f"{len(persistent)} persistentes  ·  {len(pairs)} apos limites"
    )
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
        df_b[["time", "open", "high", "low", "close"]].rename(
            columns={c: f"b_{c}" if c != "time" else c for c in ("time", "open", "high", "low", "close")}
        ),
        on="time", how="inner",
    )

    merged["spread"] = merged["a_close"] - beta * merged["b_close"] - alpha
    roll_mean = merged["spread"].rolling(window, min_periods=20).mean()
    roll_std = merged["spread"].rolling(window, min_periods=20).std()
    merged["zscore"] = (merged["spread"] - roll_mean) / roll_std.replace(0, np.nan)
    merged["zscore"] = merged["zscore"].fillna(0)
    merged["spread_mean"] = roll_mean
    merged["spread_std_roll"] = roll_std

    return merged


def _leg_fill_price(raw_price: float, side: str, phase: str) -> float:
    slip = SLIPPAGE + SPREAD
    if phase == "entry":
        return raw_price * (1 + slip) if side == "LONG" else raw_price * (1 - slip)
    return raw_price * (1 - slip) if side == "LONG" else raw_price * (1 + slip)


def _leg_pnl(entry_raw: float, exit_raw: float, units: float, side: str) -> float:
    entry_fill = _leg_fill_price(entry_raw, side, "entry")
    exit_fill = _leg_fill_price(exit_raw, side, "exit")
    if side == "LONG":
        entry_net = entry_fill * (1 + COMMISSION)
        exit_net = exit_fill * (1 - COMMISSION)
        return units * (exit_net - entry_net)
    entry_net = entry_fill * (1 - COMMISSION)
    exit_net = exit_fill * (1 + COMMISSION)
    return units * (entry_net - exit_net)


def _hedge_side(direction: str, beta: float) -> str:
    if direction == "BULLISH":
        return "SHORT" if beta >= 0 else "LONG"
    return "LONG" if beta >= 0 else "SHORT"


def _pair_pnl(*, direction: str, beta: float,
              entry_a_raw: float, exit_a_raw: float,
              entry_b_raw: float, exit_b_raw: float,
              size_a: float, duration: int) -> float:
    hedge_units = size_a * abs(beta)
    pnl_a = _leg_pnl(entry_a_raw, exit_a_raw, size_a, "LONG" if direction == "BULLISH" else "SHORT")
    pnl_b = _leg_pnl(entry_b_raw, exit_b_raw, hedge_units, _hedge_side(direction, beta))
    gross_notional = size_a * entry_a_raw + hedge_units * entry_b_raw
    funding = -(gross_notional * FUNDING_PER_8H * duration / 32)
    return round((pnl_a + pnl_b + funding) * LEVERAGE, 2)


def _pair_has_edge_after_costs(*, spread_deviation: float, notional_a: float, notional_b: float) -> bool:
    gross_notional = max(1e-9, abs(notional_a) + abs(notional_b))
    gross_edge_frac = abs(spread_deviation) / gross_notional
    roundtrip_cost_frac = 2.0 * (SLIPPAGE + SPREAD + COMMISSION)
    return gross_edge_frac >= roundtrip_cost_frac * _MIN_EDGE_COST_MULT


def _spread_state_at_idx(a_close: np.ndarray, b_close: np.ndarray, idx: int,
                         beta: float, alpha: float,
                         window: int = NEWTON_SPREAD_WINDOW) -> dict | None:
    start_idx = max(0, idx - window + 1)
    spread_window = a_close[start_idx:idx + 1] - beta * b_close[start_idx:idx + 1] - alpha
    if len(spread_window) < 20:
        return None
    mean = float(np.mean(spread_window))
    std = float(np.std(spread_window))
    current_spread = float(spread_window[-1])
    if std < 1e-12:
        z = 0.0
    else:
        z = (current_spread - mean) / std
    return {
        "spread": current_spread,
        "mean": mean,
        "std": std,
        "zscore": float(z),
    }


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
    active_pair = dict(pair_info)
    beta = active_pair["beta"]
    alpha = active_pair["alpha"]

    # prepare indicators on the primary asset (sym_a)
    df_a = indicators(df_a)
    df_a = swing_structure(df_a)

    merged = calc_spread_zscore(df_a, df_b, beta, alpha)
    if len(merged) < 300:
        return [], {}

    # Run regime detection on the spread residual, not on leg A outright.
    # The thesis is spread mean reversion; using leg A's price regime would
    # gate a relative-value signal with an unrelated absolute-trend object.
    merged = enrich_with_regime(_spread_regime_input(merged))

    trades = []
    vetos = defaultdict(int)
    account = ACCOUNT_SIZE
    peak_equity = ACCOUNT_SIZE
    min_idx = max(200, NEWTON_SPREAD_WINDOW + 50)

    a_close = merged["a_close"].values
    # HMM regime arrays (observation-only)
    _hmm_lbl = merged["hmm_regime_label"].values
    _hmm_cf  = merged["hmm_confidence"].values
    _hmm_pb  = merged["hmm_prob_bull"].values
    _hmm_pbr = merged["hmm_prob_bear"].values
    _hmm_pc  = merged["hmm_prob_chop"].values
    # [Backlog #1] a_open needed for next-bar entry fill (not same-bar close).
    # a_high/a_low needed for path-dependent liquidation check [Backlog #4].
    a_open  = merged["a_open"].values  if "a_open"  in merged.columns else a_close
    a_high  = merged["a_high"].values  if "a_high"  in merged.columns else a_close
    a_low   = merged["a_low"].values   if "a_low"   in merged.columns else a_close
    b_open  = merged["b_open"].values  if "b_open"  in merged.columns else merged["b_close"].values
    b_high  = merged["b_high"].values  if "b_high"  in merged.columns else merged["b_close"].values
    b_low   = merged["b_low"].values   if "b_low"   in merged.columns else merged["b_close"].values
    b_close = merged["b_close"].values
    a_atr   = merged["a_atr"].values   if "a_atr"   in merged.columns else None
    times   = merged["time"].values

    # [Backlog #4] Liquidation boundaries per direction. At LEVERAGE<=1 these
    # collapse to sentinels that never fire. At higher leverage, the scan's
    # exit loop compares a_high/a_low against these before the z-score gate.
    _MAINT_MARGIN = 0.005
    def _liq_price(entry: float, direction: str) -> float:
        if LEVERAGE <= 1.0:
            return -1.0 if direction == "BULLISH" else entry * 10.0
        if direction == "BULLISH":
            return entry * (1 - 1 / LEVERAGE + _MAINT_MARGIN)
        return entry * (1 + 1 / LEVERAGE - _MAINT_MARGIN)

    in_trade = False
    trade_dir = None
    trade_entry_idx = None
    trade_entry_price = None
    trade_entry_price_b = None
    trade_alpha = None
    trade_beta = None
    trade_half_life = None
    trade_pvalue = None
    trade_entry_z = None
    trade_stop_z = None
    size_held = 0.0
    pair_active = True
    last_recalc_idx = None
    pair_reactivate_at = -1
    recalc_window = max(200, NEWTON_SPREAD_WINDOW + 50, int(NEWTON_RECALC_EVERY) * 4)
    revalidation_misses = 0

    consecutive_losses = 0
    cooldown_until = -1

    for idx in range(min_idx, len(merged) - 2):
        price = a_close[idx]
        atr = a_atr[idx] if a_atr is not None else price * 0.01

        # macro
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
            vetos["dd_pause"] += 1
            continue

        if idx <= cooldown_until:
            vetos["streak_cooldown"] += 1
            continue

        vol_r = "NORMAL"

        # ── EXIT check ──
        if in_trade:
            exit_state = _spread_state_at_idx(a_close, b_close, idx, trade_beta, trade_alpha)
            z = exit_state["zscore"] if exit_state is not None else 0.0
            exit_now = False
            result = None
            exit_reason = None

            # [Backlog #4] Path-dependent liquidation guard. Check raw price
            # adverse excursion of the primary asset BEFORE the z-score gate
            # so a catastrophic wick closes the trade at liq_price regardless
            # of where z happens to be. Inert at LEVERAGE<=1.
            bar_low, bar_high = a_low[idx], a_high[idx]
            if trade_dir == "BULLISH":
                liq_p = _liq_price(trade_entry_price, "BULLISH")
                if bar_low <= liq_p:
                    exit_now = True
                    result = "LOSS"
                    exit_reason = "liquidation"
                    liq_exit_price = liq_p
            else:
                liq_p = _liq_price(trade_entry_price, "BEARISH")
                if bar_high >= liq_p:
                    exit_now = True
                    result = "LOSS"
                    exit_reason = "liquidation"
                    liq_exit_price = liq_p

            if not exit_now and trade_dir == "BEARISH":
                # short spread: entered when z > entry_z, exit when z <= 0
                if z <= NEWTON_ZSCORE_EXIT:
                    exit_now = True
                    result = "WIN"
                    exit_reason = "mean_revert"
                elif z >= NEWTON_ZSCORE_STOP:
                    exit_now = True
                    result = "LOSS"
                    exit_reason = "stop"
            elif not exit_now:
                # long spread: entered when z < -entry_z, exit when z >= 0
                if z >= NEWTON_ZSCORE_EXIT:
                    exit_now = True
                    result = "WIN"
                    exit_reason = "mean_revert"
                elif z <= -NEWTON_ZSCORE_STOP:
                    exit_now = True
                    result = "LOSS"
                    exit_reason = "stop"

            # max hold
            duration = idx - trade_entry_idx
            if not exit_now and duration >= NEWTON_MAX_HOLD:
                exit_now = True
                exit_reason = "max_hold"
                # partial mean reversion?
                if trade_dir == "BEARISH":
                    result = "WIN" if z < trade_entry_z else "LOSS"
                else:
                    result = "WIN" if z > trade_entry_z else "LOSS"

            if exit_now:
                # If the liquidation branch fired, the exit price is the
                # liquidation threshold, not the current close — match a
                # real exchange's fill behavior under forced close.
                if result == "LOSS" and "liq_exit_price" in dir():
                    try:
                        exit_p = liq_exit_price
                    except NameError:
                        exit_p = price
                    finally:
                        del liq_exit_price
                else:
                    exit_p = price
                exit_p_b = float(b_close[idx])
                duration = idx - trade_entry_idx

                # PnL calculation
                entry_p = trade_entry_price
                pnl = _pair_pnl(
                    direction=trade_dir,
                    beta=trade_beta,
                    entry_a_raw=trade_entry_price,
                    exit_a_raw=exit_p,
                    entry_b_raw=trade_entry_price_b,
                    exit_b_raw=exit_p_b,
                    size_a=size_held,
                    duration=duration,
                )
                # Apply real PnL. The previous `max(account + pnl, account * 0.5)`
                # silently clamped per-trade losses at 50% of pre-trade account,
                # inflating sharpe / maxDD / final equity in backtest reports.
                # Liquidation simulation, if needed, should be modelled at
                # position-open time against the real liquidation price.
                account = account + pnl

                if result == "LOSS":
                    consecutive_losses += 1
                    if exit_reason in {"stop", "liquidation"}:
                        pair_active = False
                        pair_reactivate_at = idx + int(NEWTON_RECALC_EVERY)
                        vetos["pair_stop_cooldown"] += 1
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
                    "strategy":   "DE SHAW",
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
                    "entry_b":    round(trade_entry_price_b, 8),
                    "stop":       round(stop_price, 4),
                    "target":     round(target_price, 4),
                    "exit_p":     round(exit_p, 6),
                    "exit_p_b":   round(exit_p_b, 6),
                    "rr":         round(rr, 2),
                    "duration":   duration,
                    "result":     result,
                    "pnl":        pnl,
                    "size":       round(size_held, 4),
                    "hedge_size": round(size_held * abs(beta), 4),
                    "score":      round(1.0 - pvalue, 3),
                    "fractal_align": 1.0,
                    "omega_struct":   0.0, "omega_flow":     0.0,
                    "omega_cascade":  0.0, "omega_momentum": 0.0,
                    "omega_pullback": 0.0,
                    "chop_trade":     False,
                    "bb_mid":         0.0,
                    # newton-specific
                    "zscore_entry": round(trade_entry_z, 3),
                    "zscore_exit":  round(z, 3),
                    "half_life":    trade_half_life,
                    "coint_pvalue": trade_pvalue,
                    "beta":         trade_beta,
                    "trade_time":   ts_str,
                    # Normalised trade outcome in R units
                    "r_multiple":   round(
                        (abs(exit_p - trade_entry_price) / risk) * (1 if result == "WIN" else -1),
                        4,
                    ) if risk > 0 else 0.0,
                    # HMM regime layer (observation-only) — sampled at entry bar
                    "hmm_regime":      (None if _hmm_lbl[trade_entry_idx] is None or (isinstance(_hmm_lbl[trade_entry_idx], float) and pd.isna(_hmm_lbl[trade_entry_idx])) else str(_hmm_lbl[trade_entry_idx])),
                    "hmm_confidence":  (None if pd.isna(_hmm_cf[trade_entry_idx])  else round(float(_hmm_cf[trade_entry_idx]),  4)),
                    "hmm_prob_bull":   (None if pd.isna(_hmm_pb[trade_entry_idx])  else round(float(_hmm_pb[trade_entry_idx]),  4)),
                    "hmm_prob_bear":   (None if pd.isna(_hmm_pbr[trade_entry_idx]) else round(float(_hmm_pbr[trade_entry_idx]), 4)),
                    "hmm_prob_chop":   (None if pd.isna(_hmm_pc[trade_entry_idx])  else round(float(_hmm_pc[trade_entry_idx]),  4)),
                }
                trades.append(t)
                icon = "✓" if result == "WIN" else "✗"
                log.info(f"  {ts_str}  {icon}  {sym_a}/{sym_b}  {trade_dir:8s}  "
                         f"z={trade_entry_z:+.2f}→{z:+.2f}  ${pnl:+.2f}")

                in_trade = False
                trade_dir = None
                trade_alpha = None
                trade_beta = None
                trade_half_life = None
                trade_pvalue = None
                trade_entry_z = None
                continue

        # ── ENTRY check ──
        if in_trade:
            continue

        if idx < pair_reactivate_at:
            vetos["pair_cooldown_active"] += 1
            continue

        if idx >= recalc_window and (
            last_recalc_idx is None or idx - last_recalc_idx >= int(NEWTON_RECALC_EVERY)
        ):
            refreshed = _revalidate_pair_window(df_a, df_b, idx, recalc_window)
            last_recalc_idx = idx
            if refreshed is None:
                revalidation_misses += 1
                if revalidation_misses > _MAX_REVALIDATION_MISSES:
                    if pair_active:
                        vetos["pair_decay"] += 1
                    pair_active = False
                else:
                    vetos["pair_revalidation_grace"] += 1
            else:
                revalidation_misses = 0
                pair_active = True
                active_pair.update(refreshed)

        if not pair_active:
            vetos["pair_inactive"] += 1
            continue

        beta = active_pair["beta"]
        alpha = active_pair["alpha"]
        half_life = active_pair["half_life"]
        pvalue = active_pair["pvalue"]
        signal_state = _spread_state_at_idx(a_close, b_close, idx, beta, alpha)
        if signal_state is None:
            continue
        z = signal_state["zscore"]

        # z-score entry conditions
        direction = None
        if z > NEWTON_ZSCORE_ENTRY:
            direction = "BEARISH"   # spread too high → short spread → short A, long B
        elif z < -NEWTON_ZSCORE_ENTRY:
            direction = "BULLISH"   # spread too low → long spread → long A, short B

        if direction is None:
            continue

        macro_entry = str(macro_b).upper()
        if _ENTRY_CHOP_ONLY and macro_entry not in _ALLOWED_MACRO_ENTRY:
            vetos[f"macro_block:{macro_entry}"] += 1
            continue

        hmm_chop = _hmm_pc[idx] if idx < len(_hmm_pc) else np.nan
        hmm_bull = _hmm_pb[idx] if idx < len(_hmm_pb) else np.nan
        hmm_bear = _hmm_pbr[idx] if idx < len(_hmm_pbr) else np.nan
        if np.isfinite(hmm_chop) and hmm_chop < _MIN_HMM_CHOP_PROB:
            vetos["hmm_not_chop"] += 1
            continue
        if np.isfinite(hmm_bull) and hmm_bull > _MAX_HMM_TREND_PROB:
            vetos["hmm_trend_bull"] += 1
            continue
        if np.isfinite(hmm_bear) and hmm_bear > _MAX_HMM_TREND_PROB:
            vetos["hmm_trend_bear"] += 1
            continue

        # vol filter
        if vol_r == "EXTREME":
            vetos["vol_extreme"] += 1
            continue

        # score based on cointegration strength and z-score extremity
        z_strength = min(abs(z) / 3.0, 1.0)
        coint_strength = 1.0 - pvalue / NEWTON_COINT_PVALUE
        score = 0.5 * coint_strength + 0.5 * z_strength

        # [Backlog #1] Execution delay + entry slippage. Entry fills at
        # open[idx+1] with slippage applied per direction — matches the
        # shared-core engine's execution model. Previous code used
        # a_close[idx] with no slippage (same-bar, no fill drift), which
        # biased reported PnL favorably.
        if idx + 1 >= len(merged):
            continue
        raw_entry = float(a_open[idx + 1])
        raw_entry_b = float(b_open[idx + 1])
        entry_p = raw_entry
        spread_deviation = float(signal_state["spread"] - signal_state["mean"])
        if not _pair_has_edge_after_costs(
            spread_deviation=spread_deviation,
            notional_a=raw_entry,
            notional_b=abs(beta) * raw_entry_b,
        ):
            vetos["edge_lt_cost"] += 1
            continue
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

        # [L6] Single-position notional cap.
        # Newton opens at most one spread trade per pair at a time, so the
        # aggregate list is always empty here — the check degenerates to
        # `size * entry ≤ account × LEVERAGE`. In normal conditions this
        # is guaranteed by position_size (risk-based sizing), but a very
        # tight stop combined with a high LEVERAGE could in theory push
        # the nominal exposure over the margin ceiling. The guard makes
        # the constraint explicit and consistent across all engines.
        hedge_notional = size * abs(beta) * raw_entry_b
        ok_agg, motivo_agg = check_aggregate_notional(
            size * entry_p + hedge_notional, [], account, LEVERAGE)
        if not ok_agg:
            vetos[motivo_agg] += 1
            continue

        in_trade = True
        trade_dir = direction
        trade_entry_idx = idx
        trade_entry_price = entry_p
        trade_entry_price_b = raw_entry_b
        trade_alpha = alpha
        trade_beta = beta
        trade_half_life = half_life
        trade_pvalue = pvalue
        trade_entry_z = z
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
    Standard scan interface for DE SHAW.
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
    print(f"  DE SHAW v1.0  ·  {RUN_ID}")
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
        "engine": "DE SHAW",
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

    out = RUN_DIR / "reports" / f"deshaw_{INTERVAL}_v1.json"
    atomic_write(out, json.dumps(data, indent=2, default=str))
    print(f"  json  ·  {out}")
    log.info(f"JSON → {out}")

    # register in DB
    try:
        from core.ops.db import register_run
        register_run(
            run_id=RUN_ID,
            engine="deshaw",
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
    import argparse
    _ap = argparse.ArgumentParser(description="DE SHAW — pairs cointegration")
    _ap.add_argument("--days", type=int, default=None)
    _ap.add_argument("--basket", type=str, default=None)
    _ap.add_argument("--interval", type=str, default=None, help="Execution timeframe override (e.g. 1h, 4h)")
    _ap.add_argument("--no-menu", action="store_true")
    # Experimental tuning overrides (do not modify config.params).
    # When provided, these override the NEWTON_* globals for this run only.
    _ap.add_argument("--z-entry", type=float, default=None,
                     help="Override NEWTON_ZSCORE_ENTRY (default from config.params)")
    _ap.add_argument("--z-exit", type=float, default=None,
                     help="Override NEWTON_ZSCORE_EXIT")
    _ap.add_argument("--z-stop", type=float, default=None,
                     help="Override NEWTON_ZSCORE_STOP")
    _ap.add_argument("--pvalue", type=float, default=None,
                     help="Override NEWTON_COINT_PVALUE")
    _ap.add_argument("--hl-max", type=int, default=None,
                     help="Override NEWTON_HALFLIFE_MAX")
    _ap.add_argument("--max-hold", type=int, default=None,
                     help="Override NEWTON_MAX_HOLD")
    _ap.add_argument("--size-mult", type=float, default=None,
                     help="Override NEWTON_SIZE_MULT")
    _ap.add_argument("--allowed-macro-entry", type=str, default=None,
                     help="Comma-separated macro regimes allowed at entry (e.g. CHOP,BULL)")
    _ap.add_argument("--min-hmm-chop-prob", type=float, default=None,
                     help="Override NEWTON_MIN_HMM_CHOP_PROB")
    _ap.add_argument("--max-hmm-trend-prob", type=float, default=None,
                     help="Override NEWTON_MAX_HMM_TREND_PROB")
    _ap.add_argument("--max-revalidation-misses", type=int, default=None,
                     help="Override NEWTON_MAX_REVALIDATION_MISSES")
    _ap.add_argument("--end", type=str, default=None,
                     help="End date YYYY-MM-DD for backtest window (pre-calibration OOS).")
    _args, _ = _ap.parse_known_args()
    END_TIME_MS = None
    if _args.end:
        import pandas as _pd_tmp
        END_TIME_MS = int(_pd_tmp.Timestamp(_args.end).timestamp() * 1000)
    # Apply overrides before any scan logic runs.
    if _args.z_entry is not None:
        NEWTON_ZSCORE_ENTRY = float(_args.z_entry)
    if _args.z_exit is not None:
        NEWTON_ZSCORE_EXIT = float(_args.z_exit)
    if _args.z_stop is not None:
        NEWTON_ZSCORE_STOP = float(_args.z_stop)
    if _args.pvalue is not None:
        NEWTON_COINT_PVALUE = float(_args.pvalue)
    if _args.hl_max is not None:
        NEWTON_HALFLIFE_MAX = int(_args.hl_max)
    if _args.max_hold is not None:
        NEWTON_MAX_HOLD = int(_args.max_hold)
    if _args.size_mult is not None:
        NEWTON_SIZE_MULT = float(_args.size_mult)
    if _args.allowed_macro_entry is not None:
        _ALLOWED_MACRO_ENTRY = {
            token.strip().upper()
            for token in str(_args.allowed_macro_entry).split(",")
            if token.strip()
        }
    if _args.min_hmm_chop_prob is not None:
        _MIN_HMM_CHOP_PROB = float(_args.min_hmm_chop_prob)
    if _args.max_hmm_trend_prob is not None:
        _MAX_HMM_TREND_PROB = float(_args.max_hmm_trend_prob)
    if _args.max_revalidation_misses is not None:
        _MAX_REVALIDATION_MISSES = int(_args.max_revalidation_misses)

    print(f"\n{SEP}")
    print(f"  DE SHAW  ·  Statistical Mean Reversion")
    print(f"  {SEP}")

    if not HAS_STATSMODELS:
        print("  statsmodels nao instalado — pip install statsmodels")
        sys.exit(1)

    if _args.days:
        SCAN_DAYS = _args.days
    elif not _args.no_menu:
        _days_in = safe_input(f"\n  periodo em dias [{SCAN_DAYS}] > ").strip()
        if _days_in.isdigit() and 7 <= int(_days_in) <= 1500:
            SCAN_DAYS = int(_days_in)
    if _args.interval:
        INTERVAL = _args.interval
    _tf_mult = {"1m": 60, "3m": 20, "5m": 12, "15m": 4, "30m": 2, "1h": 1, "2h": 0.5, "4h": 0.25}
    N_CANDLES = int(SCAN_DAYS * 24 * _tf_mult.get(INTERVAL, 4))

    BASKET_NAME = _args.basket or ENGINE_BASKETS.get("DESHAW", "default")
    from config.params import BASKETS
    if BASKET_NAME in BASKETS:
        SYMBOLS = BASKETS[BASKET_NAME]
    elif not _args.no_menu:
        SYMBOLS = select_symbols(SYMBOLS)

    if not _args.no_menu:
        _lev_in = safe_input(f"  leverage [{LEVERAGE}x] > ").strip()
        if _lev_in:
            try:
                _lev_val = float(_lev_in.replace("x", ""))
                if 0.1 <= _lev_val <= 125:
                    LEVERAGE = _lev_val
            except ValueError:
                pass

    print(f"\n{SEP}")
    print(f"  DE SHAW  ·  {SCAN_DAYS}d  ·  {len(SYMBOLS)} ativos  ·  {INTERVAL}")
    print(f"  ${ACCOUNT_SIZE:,.0f}  ·  {LEVERAGE}x  ·  z-entry {NEWTON_ZSCORE_ENTRY}  ·  z-stop {NEWTON_ZSCORE_STOP}")
    print(f"  {RUN_DIR}/")
    print(SEP)
    if not _args.no_menu:
        safe_input("  enter para iniciar... ")

    log.info(f"DE SHAW v1.0 iniciado — {RUN_ID}  tf={INTERVAL}  dias={SCAN_DAYS}")

    # ── FETCH DATA ──
    print(f"\n{SEP}\n  DADOS   {INTERVAL}   {N_CANDLES:,} candles\n{SEP}")
    _fetch_syms = list(SYMBOLS)
    if MACRO_SYMBOL not in _fetch_syms:
        _fetch_syms.insert(0, MACRO_SYMBOL)
    all_dfs = fetch_all(_fetch_syms, INTERVAL, N_CANDLES, end_time_ms=END_TIME_MS)
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
    pairs = discover_cointegrated_pairs_over_time(all_dfs)

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

    # ── VETOS ──
    if all_vetos:
        print(f"\n{SEP}\n  VETOS\n{SEP}")
        for k, v in sorted(all_vetos.items(), key=lambda x: -x[1]):
            print(f"  {v:>6d}  {k}")

    # ── BY SYMBOL ──
    by_sym = defaultdict(list)
    for t in all_trades:
        by_sym[t["symbol"]].append(t)

    # ── WALK-FORWARD BY REGIME ──
    wf_regime = walk_forward_by_regime(all_trades)

    # ── OVERFIT AUDIT ──
    try:
        from analysis.overfit_audit import run_audit, print_audit_box
        audit_results = run_audit(all_trades)
        print_audit_box(audit_results)
    except Exception:
        audit_results = None

    # ── CONDITIONAL ──
    try:
        from analysis.stats import conditional_backtest
        cond = conditional_backtest(all_trades)
    except Exception:
        cond = {}

    # ══════════════════════════════════════════════════════════════
    #  PERSISTÊNCIA — alinhado com CITADEL
    # ══════════════════════════════════════════════════════════════
    from core.ops.run_manager import snapshot_config, save_run_artifacts, append_to_index

    roi = ratios["ret"]
    _config = _apply_runtime_snapshot_overrides(snapshot_config(), BASKET_NAME)
    _summary = {
        "engine": "DE SHAW",
        "run_id": RUN_ID,
        "basket": BASKET_NAME,
        "n_trades": len(closed),
        "win_rate": round(wr, 2),
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
        "n_pairs": len(pairs),
    }

    save_run_artifacts(
        RUN_DIR, _config, all_trades, eq, _summary,
        overfit_results=audit_results,
        diagnostics={
            "vetos": all_vetos,
            "conditional": cond,
            "walk_forward": wf,
            "walk_forward_by_regime": wf_regime,
            "by_symbol_trade_counts": {sym: len(ts) for sym, ts in by_sym.items()},
        },
    )
    append_to_index(RUN_DIR, _summary, _config, audit_results)

    # ── HTML Report ──
    try:
        from analysis.report_html import generate_report
        generate_report(
            all_trades, eq, mc, cond, ratios, mdd_pct, wf, wf_regime,
            by_sym, all_vetos, str(RUN_DIR), config_dict=_config,
            audit_results=audit_results,
            engine_name="DE SHAW",
        )
        print(f"  HTML → {RUN_DIR / 'report.html'}")
    except Exception as _e:
        log.warning(f"HTML report failed: {_e}")

    # ── JSON export (legacy + DB) ──
    export_json(all_trades, eq, mc, ratios, pairs)

    print(f"\n{SEP}\n  output  ·  {RUN_DIR}/\n{SEP}\n")
