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
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import math
import logging
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.params import *
# Per-engine TF override (master battery 2026-04-13: 1h wins over 15m)
INTERVAL = ENGINE_INTERVALS.get("BRIDGEWATER", INTERVAL)
from core.chronos import enrich_with_regime
from core import (
    fetch_all, validate, indicators, swing_structure, omega,
    detect_macro, build_corr_matrix, portfolio_allows, check_aggregate_notional,
    position_size,
    calc_levels, label_trade,
)
from core.sentiment import (
    fetch_funding_rate, fetch_open_interest, fetch_long_short_ratio,
    funding_zscore, oi_delta_signal, ls_ratio_signal, composite_sentiment,
    cached_coverage,
)
from core.fs import atomic_write
from analysis.stats import equity_stats, calc_ratios
from analysis.montecarlo import monte_carlo
from analysis.walkforward import walk_forward

log = logging.getLogger("BRIDGEWATER")  # BRIDGEWATER (formerly THOTH) — Macro sentiment engine
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
    log.addHandler(_h)

SEP = "─" * 80

# ── RUN IDENTITY ─────────────────────────────────────────────
RUN_ID  = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
RUN_DIR = Path(f"data/bridgewater/{RUN_ID}")
(RUN_DIR / "reports").mkdir(parents=True, exist_ok=True)
(RUN_DIR / "logs").mkdir(parents=True, exist_ok=True)

_fh = logging.FileHandler(RUN_DIR / "logs" / "thoth.log", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
log.addHandler(_fh)

RUNTIME_PRESET_NAME = "legacy"
RUNTIME_STRICT_DIRECTION = False
RUNTIME_MIN_COMPONENTS = 0
RUNTIME_MIN_DIR_THRESH = None
RUNTIME_DISABLE_OI = False
RUNTIME_ALLOWED_MACRO_REGIMES = None
RUNTIME_POST_TRADE_COOLDOWN_BARS = 0
RUNTIME_REGIME_THRESHOLDS = None
RUNTIME_SYMBOL_HEALTH = None
RUNTIME_MIN_COVERAGE_FRACTION = 0.70


# ══════════════════════════════════════════════════════════════
#  SENTIMENT DATA COLLECTION
# ══════════════════════════════════════════════════════════════

def _sentiment_limits(window_days: int | None) -> tuple[int, int, int]:
    """Return (funding_limit, oi_limit, ls_limit) sized to cover ``window_days``.

    Historical Binance Futures coverage:
      * Funding rate: emitted every 8h → 3 ticks/day. /fundingRate capped at 1000.
      * Open interest (15m period): 96 ticks/day. /openInterestHist capped at 500.
      * Long/short ratio (15m period): 96 ticks/day. Same cap as OI.

    With a 20% buffer for weekends/outages. When ``window_days`` is None the
    function falls back to the legacy 100/200/200 defaults (which cover
    roughly a live session, not an OOS window).
    """
    if window_days is None or window_days <= 0:
        return 100, 200, 200
    funding = min(1000, max(100, int(window_days * 3 * 1.2)))
    oi      = min(500,  max(200, int(window_days * 96 * 1.1)))
    ls      = min(500,  max(200, int(window_days * 96 * 1.1)))
    return funding, oi, ls


def _scan_warmup_bars() -> int:
    return max(200, W_NORM, PIVOT_N * 3) + 10


def _scan_window_can_close_trades(n_candles: int) -> bool:
    return int(n_candles) > (MAX_HOLD + 2)


def _series_first_timestamp(series: pd.Series | None) -> pd.Timestamp | None:
    if series is None or len(series) == 0:
        return None
    idx = getattr(series, "index", None)
    if idx is None or len(idx) == 0:
        return None
    if pd.api.types.is_datetime64_any_dtype(idx):
        return pd.Timestamp(idx.min())
    return None


def _sentiment_coverage_start(sent: dict | None) -> pd.Timestamp | None:
    sent = sent or {}
    starts: list[pd.Timestamp] = []

    funding_z = sent.get("funding_z")
    funding_start = _series_first_timestamp(funding_z)
    if funding_start is not None:
        starts.append(funding_start)

    oi_df = sent.get("oi_df")
    if oi_df is not None and len(oi_df):
        starts.append(pd.to_datetime(oi_df["time"]).min())

    ls_signal = sent.get("ls_signal")
    ls_start = _series_first_timestamp(ls_signal)
    if ls_start is not None:
        starts.append(ls_start)

    return max(starts) if starts else None


def _coverage_scan_start_idx(df: pd.DataFrame, sent: dict | None, base_start_idx: int) -> int:
    start_ts = _sentiment_coverage_start(sent)
    if start_ts is None:
        return int(base_start_idx)
    candle_times = pd.to_datetime(df["time"])
    coverage_idx = int(candle_times.searchsorted(start_ts, side="left"))
    return max(int(base_start_idx), coverage_idx)


def _coverage_eligibility(
    df: pd.DataFrame,
    sent: dict | None,
    base_start_idx: int,
    *,
    min_fraction: float,
) -> dict[str, object]:
    scan_start_idx = _coverage_scan_start_idx(df, sent, base_start_idx)
    total_scan_candles = max(0, len(df) - int(base_start_idx))
    covered_scan_candles = max(0, len(df) - int(scan_start_idx))
    coverage_fraction = (
        covered_scan_candles / total_scan_candles
        if total_scan_candles > 0 else 0.0
    )
    closeable = _scan_window_can_close_trades(covered_scan_candles)
    eligible = closeable and coverage_fraction >= float(min_fraction)
    return {
        "scan_start_idx": int(scan_start_idx),
        "covered_scan_candles": int(covered_scan_candles),
        "total_scan_candles": int(total_scan_candles),
        "coverage_fraction": float(round(coverage_fraction, 4)),
        "closeable": bool(closeable),
        "eligible": bool(eligible),
    }


def collect_sentiment(symbols: list, end_time_ms: int | None = None,
                      window_days: int | None = None) -> dict:
    """
    Fetch all sentiment data for each symbol.

    Se `end_time_ms` é passado (backtest OOS), todas as 3 chamadas ao
    Binance respeitam o fim da janela — evita look-ahead. Sem isso, as
    chamadas voltam com a série mais recente encerrando AGORA, mesmo em
    backtest histórico.

    Returns dict[symbol] = {funding_z: Series, oi_signal: Series, ls_signal: Series}
    """
    funding_limit, oi_limit, ls_limit = _sentiment_limits(window_days)
    sentiment = {}
    missing_historical: list[str] = []
    for sym in symbols:
        log.info(f"  fetching sentiment  ·  {sym}  "
                 f"(funding={funding_limit} oi={oi_limit} ls={ls_limit})")
        data = {}

        # Funding rate
        fr_df = fetch_funding_rate(sym, limit=funding_limit, end_time_ms=end_time_ms)
        if fr_df is not None and len(fr_df) >= 10:
            data["funding_df"] = fr_df
            data["funding_z"] = funding_zscore(fr_df, window=THOTH_FUNDING_WINDOW)
        else:
            data["funding_z"] = None

        # Open Interest
        oi_df = fetch_open_interest(sym, period="15m", limit=oi_limit, end_time_ms=end_time_ms)
        data["oi_df"] = oi_df
        data["oi_ready"] = oi_df is not None and len(oi_df) >= 10

        # Long/Short ratio
        ls_df = fetch_long_short_ratio(sym, period="15m", limit=ls_limit, end_time_ms=end_time_ms)
        if ls_df is not None and len(ls_df) >= 5:
            data["ls_signal"] = ls_ratio_signal(ls_df)
            data["ls_df"] = ls_df
            data["ls_ready"] = True
        else:
            data["ls_signal"] = None
            data["ls_ready"] = False

        sentiment[sym] = data
        if end_time_ms is not None:
            reasons = []
            if data.get("funding_z") is None:
                reasons.append("funding")
            if not data.get("oi_ready"):
                cov = cached_coverage("open_interest", sym, "15m")
                reasons.append(
                    "oi(cache=empty)"
                    if cov is None
                    else f"oi(cache_end={cov['end']}, rows={cov['rows']})"
                )
            if not data.get("ls_ready"):
                cov = cached_coverage("long_short_ratio", sym, "15m")
                reasons.append(
                    "ls(cache=empty)"
                    if cov is None
                    else f"ls(cache_end={cov['end']}, rows={cov['rows']})"
                )
            if reasons:
                missing_historical.append(f"{sym}: {', '.join(reasons)}")
        log.info(f"    funding={'✓' if data.get('funding_z') is not None else '✗'}  "
                 f"oi={'✓' if oi_df is not None else '✗'}  "
                 f"ls={'✓' if data.get('ls_signal') is not None else '✗'}")

    if end_time_ms is not None and missing_historical:
        details = "; ".join(missing_historical[:5])
        if len(missing_historical) > 5:
            details += f"; ... (+{len(missing_historical) - 5} symbols)"
        raise RuntimeError(
            "historical sentiment unavailable for OOS window; "
            "run tools/prewarm_sentiment_cache.py for the target basket/window. "
            f"Missing coverage: {details}"
        )

    return sentiment


def _parse_symbols_override(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    symbols = []
    for token in raw.split(","):
        sym = token.strip().upper()
        if not sym:
            continue
        if not sym.endswith("USDT"):
            sym += "USDT"
        symbols.append(sym)
    return symbols or None


def _filter_stale_market_data(all_dfs: dict[str, pd.DataFrame], interval: str) -> tuple[dict[str, pd.DataFrame], list[str]]:
    if not all_dfs:
        return all_dfs, []
    tf_minutes = max(1, _TF_MINUTES.get(interval, 60))
    freshest = max(pd.to_datetime(df["time"]).max() for df in all_dfs.values() if df is not None and len(df))
    cutoff = freshest - pd.Timedelta(minutes=tf_minutes * 24)
    kept: dict[str, pd.DataFrame] = {}
    dropped: list[str] = []
    for sym, df in all_dfs.items():
        last_ts = pd.to_datetime(df["time"]).max()
        if last_ts < cutoff:
            dropped.append(sym)
            continue
        kept[sym] = df
    return kept, dropped


def _trade_sentiment_diagnostics(closed: list[dict]) -> dict:
    if not closed:
        return {
            "oi_zero_pct": 0.0,
            "oi_nonzero_trades": 0,
            "ls_zero_pct": 0.0,
            "ls_distribution": {},
            "funding_positive_pct": 0.0,
            "funding_negative_pct": 0.0,
        }

    oi_values = pd.Series([float(t.get("oi_signal", 0.0) or 0.0) for t in closed], dtype=float)
    ls_values = pd.Series([float(t.get("ls_signal", 0.0) or 0.0) for t in closed], dtype=float)
    funding_values = pd.Series([float(t.get("funding_z", 0.0) or 0.0) for t in closed], dtype=float)

    ls_distribution = {
        str(round(float(k), 3)): int(v)
        for k, v in ls_values.value_counts().sort_index().to_dict().items()
    }

    return {
        "oi_zero_pct": round(float((oi_values == 0.0).mean() * 100), 2),
        "oi_nonzero_trades": int((oi_values != 0.0).sum()),
        "ls_zero_pct": round(float((ls_values == 0.0).mean() * 100), 2),
        "ls_distribution": ls_distribution,
        "funding_positive_pct": round(float((funding_values > 0.0).mean() * 100), 2),
        "funding_negative_pct": round(float((funding_values < 0.0).mean() * 100), 2),
    }


def _resolve_runtime_preset(
    preset: str,
    *,
    strict_direction: bool,
    min_components: int,
    min_dir_thresh: float | None,
    disable_oi: bool,
    enable_symbol_health: bool,
    allowed_regimes: str | None,
    post_trade_cooldown_bars: int,
) -> dict:
    """Resolve effective runtime gates for a named preset."""
    name = (preset or "robust").strip().lower()
    parsed_regimes = None
    if allowed_regimes:
        parsed_regimes = {
            token.strip().upper()
            for token in str(allowed_regimes).split(",")
            if token.strip()
        } or None
    if name == "legacy":
        return {
            "preset": "legacy",
            "strict_direction": bool(strict_direction),
            "min_components": int(min_components),
            "min_dir_thresh": min_dir_thresh,
            "disable_oi": bool(disable_oi),
            "allowed_macro_regimes": parsed_regimes,
            "post_trade_cooldown_bars": max(0, int(post_trade_cooldown_bars)),
            "regime_thresholds": None,
            "symbol_health": None,
        }
    if name != "robust":
        raise ValueError(f"unknown preset: {preset}")
    return {
        "preset": "robust",
        "strict_direction": True if not strict_direction else bool(strict_direction),
        "min_components": max(2, int(min_components)),
        "min_dir_thresh": 0.35 if min_dir_thresh is None else float(min_dir_thresh),
        "disable_oi": True if not disable_oi else bool(disable_oi),
        "allowed_macro_regimes": parsed_regimes,
        "post_trade_cooldown_bars": max(0, int(post_trade_cooldown_bars)),
        "regime_thresholds": {"BEAR": 0.35, "BULL": 0.45, "CHOP": 0.55},
        "symbol_health": None if not enable_symbol_health else {
            "lookback": 8,
            "block_min_trades": 5,
            "block_expectancy": -0.35,
            "block_loss_rate": 0.80,
            "saturation_start": 6,
            "saturation_full": 10,
            "min_multiplier": 0.45,
        },
    }


def _resolve_direction_threshold(
    macro_bias: str,
    default_threshold: float,
    regime_thresholds: dict[str, float] | None,
) -> float:
    if not regime_thresholds:
        return float(default_threshold)
    regime = str(macro_bias or "CHOP").upper()
    return float(regime_thresholds.get(regime, default_threshold))


def _symbol_health_controls(
    recent_closed: list[dict],
    config: dict | None,
) -> tuple[float, str | None]:
    if not config:
        return 1.0, None

    lookback = max(1, int(config.get("lookback", 8)))
    block_min_trades = max(1, int(config.get("block_min_trades", 5)))
    saturation_start = max(1, int(config.get("saturation_start", 8)))
    saturation_full = max(saturation_start, int(config.get("saturation_full", 14)))
    min_multiplier = float(config.get("min_multiplier", 0.45))
    block_expectancy = float(config.get("block_expectancy", -12.0))
    block_loss_rate = float(config.get("block_loss_rate", 0.80))

    sample = recent_closed[-lookback:]
    if not sample:
        return 1.0, None

    quality_values = [
        float(
            t.get("r_multiple")
            if t.get("r_multiple") is not None
            else t.get("pnl", 0.0)
        ) or 0.0
        for t in sample
    ]
    expectancy = sum(quality_values) / len(sample)
    losses = sum(1 for q in quality_values if q < 0)

    loss_rate = losses / len(sample)

    if len(sample) >= block_min_trades and expectancy <= block_expectancy and loss_rate >= block_loss_rate:
        return 0.0, "symbol_health_block"

    mult = 1.0
    if len(sample) >= block_min_trades and expectancy < 0:
        mult *= 0.65
    if len(sample) > saturation_start:
        span = max(1, saturation_full - saturation_start)
        progress = min(1.0, (len(sample) - saturation_start) / span)
        mult *= 1.0 - (1.0 - min_multiplier) * progress
    if len(sample) >= block_min_trades and loss_rate >= 0.70:
        mult *= 0.75

    return max(min_multiplier, round(mult, 4)), None


_SENTIMENT_MAX_STALENESS_NS = 2 * 60 * 60 * 1_000_000_000  # 2h in ns


def _align_series_to_candles(
    candle_times: pd.Series,
    series: pd.Series | None,
    default: float = 0.0,
    max_staleness_ns: int = _SENTIMENT_MAX_STALENESS_NS,
) -> np.ndarray:
    """Align a series to candle timestamps, with a staleness guard.

    For each candle we take the most recent sentiment tick at or before the
    candle time. If that tick is older than ``max_staleness_ns``, the candle
    gets ``default`` instead — propagating a stale value across a long gap
    fabricates deterministic signal (Bug 4, 2026-04-17).

    Cache files can have large internal gaps (e.g. a BTCUSDT row from
    2023-11-14 followed by rows from 2026-04-12). Without a staleness guard,
    searchsorted propagates the 2023 value across 2.5 years of candles.
    """
    aligned = np.full(len(candle_times), default, dtype=float)
    if series is None or len(series) == 0:
        return aligned

    if not (
        hasattr(series.index, "dtype")
        and pd.api.types.is_datetime64_any_dtype(series.index)
    ):
        # Fallback: the caller supplied a Series without a DatetimeIndex. We
        # cannot align temporally — return ``default`` everywhere rather than
        # fake a positional mapping (Bug 1, 2026-04-17).
        return aligned

    values = pd.to_numeric(series, errors="coerce").fillna(default).to_numpy(dtype=float)
    idx_ns = np.asarray(series.index, dtype="datetime64[ns]").view("int64")
    candle_ns = np.asarray(pd.to_datetime(candle_times), dtype="datetime64[ns]").view("int64")
    pos = np.searchsorted(idx_ns, candle_ns, side="right") - 1
    valid = pos >= 0
    if valid.any():
        safe_pos = np.clip(pos, 0, len(values) - 1)
        gaps = candle_ns - idx_ns[safe_pos]
        fresh = valid & (gaps <= max_staleness_ns)
        aligned[fresh] = values[safe_pos[fresh]]
    return aligned


def _align_oi_signal_to_candles(
    candle_times: pd.Series,
    oi_signal_df: pd.DataFrame | None,
) -> np.ndarray:
    """Align OI signal to candles with a staleness-guarded asof merge.

    Bug 4 fix (2026-04-17): ``tolerance`` rejects candles whose most-recent OI
    tick is older than 2h. Without it, a cache row from 2023 could propagate
    forward across years of 2026 candles, fabricating deterministic signal.
    """
    aligned = np.zeros(len(candle_times), dtype=float)
    if oi_signal_df is None or oi_signal_df.empty:
        return aligned

    oi = oi_signal_df[["time", "oi_signal"]].dropna(subset=["time"]).copy()
    if oi.empty:
        return aligned
    oi["time"] = pd.to_datetime(oi["time"])
    oi = oi.sort_values("time")
    candles = pd.DataFrame({"time": pd.to_datetime(candle_times)})
    merged = pd.merge_asof(
        candles,
        oi,
        on="time",
        direction="backward",
        allow_exact_matches=True,
        tolerance=pd.Timedelta("2h"),
    )
    return pd.to_numeric(merged["oi_signal"], errors="coerce").fillna(0.0).to_numpy(dtype=float)


# ══════════════════════════════════════════════════════════════
#  SCAN ENGINE
# ══════════════════════════════════════════════════════════════

def scan_thoth(df: pd.DataFrame, symbol: str,
               macro_bias_series, corr: dict,
               htf_stack_dfs: dict | None = None,
               sentiment_data: dict | None = None,
               scan_start_idx: int = 0,
               *,
               disable_oi: bool = False,
               allowed_macro_regimes: set[str] | None = None,
               post_trade_cooldown_bars: int = 0,
               regime_thresholds: dict[str, float] | None = None,
               symbol_health: dict | None = None,
               strict_direction: bool = False,
               min_components: int = 0,
               min_dir_thresh: float | None = None,
               exit_on_reversal: bool = False) -> tuple[list, dict]:
    """
    Scan a symbol using sentiment + technical confirmation.

    Optional research gates (all default OFF — preserve calibrated baseline):

    strict_direction (bool):
        Require EXPLICIT match with structure or macro_bias. Removes the
        permissive fallback at scan_thoth:498-505 that accepted neutral
        struct as confirmation. Rationale (2026-04-17 audit): 20/20 Late
        losers in 31d BTC window had struct=NEUTRAL and macro opposing
        their direction — the fallback was the direct cause.

    min_components (int):
        Require at least N of {funding, oi, ls} signals to be non-zero
        simultaneously. Rationale: multi-signal convergence is a canonical
        quant pattern (Lo 2004, Asness 2013). Filters single-channel
        marginal setups. Default 0 = off.

    min_dir_thresh (float | None):
        Override THOTH_DIRECTION_THRESHOLD for this run. The calibrated
        default (0.20) is liberal. Raising to 0.35-0.40 filters marginal
        sentiment (|score|<0.35 were the 20 Late losers). None = use config.

    exit_on_reversal (bool):
        Close open position if composite sentiment reverses past
        -min_dir_thresh (for longs) or +min_dir_thresh (for shorts).
        Rationale: contrarian thesis assumes transient mispricing; if the
        crowd keeps building the wrong way, the thesis is invalidated and
        the trade should exit before the stop. NOT YET implemented in
        label_trade path — accepted as the gate param for future wiring.
    """
    # ── prepare indicators ──
    df = indicators(df)
    df = swing_structure(df)
    df = omega(df)
    df = enrich_with_regime(df)

    trades  = []
    vetos   = defaultdict(int)
    account = ACCOUNT_SIZE
    min_idx = max(_scan_warmup_bars(), int(scan_start_idx))

    # Get sentiment data for this symbol
    sent = (sentiment_data or {}).get(symbol, {})
    funding_z_series = sent.get("funding_z")
    oi_df = None if disable_oi else sent.get("oi_df")
    ls_signal_series = sent.get("ls_signal")

    # Build OI signal if available
    oi_signal_df = None
    _oi_available = False
    _oi_build_error = None
    if oi_df is not None and len(oi_df) >= 10:
        try:
            oi_signal_df = oi_delta_signal(oi_df, df, window=THOTH_OI_WINDOW)
            _oi_available = True
        except Exception as exc:
            _oi_build_error = exc

    # BRIDGEWATER's thesis is funding + OI + LS. If OI history exists but the
    # engine cannot transform it into a usable signal, skipping the symbol is
    # safer than silently degrading to a different strategy.
    if oi_df is not None and len(oi_df) >= 10 and not _oi_available:
        if _oi_build_error is not None:
            log.warning("OI signal build failed for %s: %s", symbol, _oi_build_error)
        else:
            log.warning("OI signal unavailable for %s despite ready OI history", symbol)
        return [], {"oi_signal_unavailable": 1}

    # Renormalize weights when OI is unavailable so composite score
    # can still reach [-1, 1] range using funding + LS only.
    if _oi_available:
        _w_f, _w_oi, _w_ls = THOTH_WEIGHT_FUNDING, THOTH_WEIGHT_OI, THOTH_WEIGHT_LS
    else:
        _total = THOTH_WEIGHT_FUNDING + THOTH_WEIGHT_LS
        _w_f  = THOTH_WEIGHT_FUNDING / _total if _total > 0 else 0.5
        _w_oi = 0.0
        _w_ls = THOTH_WEIGHT_LS / _total if _total > 0 else 0.5

    # (exit_idx, symbol, size, entry) — size/entry needed for L6 cap
    open_pos: list[tuple[int, str, float, float]] = []

    # [Backlog #3] Dynamic funding period denominator per candle interval.
    _funding_periods_per_8h = 8 * 60 / _TF_MINUTES.get(INTERVAL, 15)

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
    # HMM regime layer (observation-only)
    _hmm_lbl = df["hmm_regime_label"].values
    _hmm_cf  = df["hmm_confidence"].values
    _hmm_pb  = df["hmm_prob_bull"].values
    _hmm_pbr = df["hmm_prob_bear"].values
    _hmm_pc  = df["hmm_prob_chop"].values
    _times = pd.to_datetime(df["time"])
    _f_z_aligned = _align_series_to_candles(_times, funding_z_series)
    _ls_aligned = _align_series_to_candles(_times, ls_signal_series)
    _oi_aligned = _align_oi_signal_to_candles(_times, oi_signal_df)

    peak_equity        = ACCOUNT_SIZE
    consecutive_losses = 0
    cooldown_until     = -1
    sym_cooldown_until: dict[str, int] = {}
    recent_closed: list[dict] = []

    log.info(f"\n{'─'*60}\n  {symbol}\n{'─'*60}")

    for idx in range(min_idx, len(df) - MAX_HOLD - 2):
        open_pos = [(ei, s, sz, en) for ei, s, sz, en in open_pos if ei > idx]
        active_syms = [s for _, s, _, _ in open_pos]

        macro_b = "CHOP"
        if macro_bias_series is not None:
            macro_b = macro_bias_series.iloc[min(idx, len(macro_bias_series) - 1)]
        if allowed_macro_regimes and str(macro_b).upper() not in allowed_macro_regimes:
            vetos[f"macro_block:{str(macro_b).upper()}"] += 1
            continue

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
        f_z = float(_f_z_aligned[idx])
        oi_sig = float(_oi_aligned[idx])
        ls_sig = float(_ls_aligned[idx])

        # Composite sentiment
        sent_score = composite_sentiment(
            f_z, oi_sig, ls_sig,
            _w_f, _w_oi, _w_ls
        )

        # Direction from sentiment
        direction = None
        struct = _str[idx]

        _dir_thresh_base = min_dir_thresh if min_dir_thresh is not None else THOTH_DIRECTION_THRESHOLD
        _dir_thresh = _resolve_direction_threshold(macro_b, _dir_thresh_base, regime_thresholds)

        # Optional: multi-component convergence gate (research, default OFF).
        if min_components > 0:
            active_channels = int(f_z != 0) + int(oi_sig != 0) + int(ls_sig != 0)
            if active_channels < min_components:
                vetos["components_weak"] += 1
                continue

        if sent_score > _dir_thresh:
            # bullish sentiment
            if struct == "UP" or macro_b == "BULL":
                direction = "BULLISH"
            elif not strict_direction and struct != "DOWN":
                # permissive fallback — default path; --strict-direction disables this.
                direction = "BULLISH"
        elif sent_score < -_dir_thresh:
            # bearish sentiment
            if struct == "DOWN" or macro_b == "BEAR":
                direction = "BEARISH"
            elif not strict_direction and struct != "UP":
                direction = "BEARISH"

        if direction is None:
            vetos["no_signal"] += 1
            continue

        # Score: |sentiment| as quality metric
        score = min(abs(sent_score), 1.0)
        if score < THOTH_MIN_SCORE:
            vetos["score_baixo"] += 1; continue
        # Score reportado: rescalado 0.50-1.00 pra alinhar com CITADEL/outros
        # (sensitivity test em overfit_audit usa thresholds 0.50-0.56 hardcoded).
        # Gate + sizing continuam usando `score` raw.
        score_reported = 0.50 + score * 0.50

        # Extra check: sentiment must be strong enough
        # Respect the strategy thesis: do not run as funding-only when both
        # positioning channels are flat.
        if oi_sig == 0.0 and ls_sig == 0.0:
            vetos["positioning_absent"] += 1; continue
        if abs(f_z) < 1.0 and abs(oi_sig) < 0.3 and abs(ls_sig) < 0.3:
            vetos["sentiment_fraco"] += 1; continue

        # ── LEVELS ──
        levels = calc_levels(df, idx, direction)
        if levels is None:
            vetos["niveis"] += 1; continue
        entry, stop, target, rr = levels

        # ── LABEL TRADE ──
        result, duration, exit_p, exit_reason = label_trade(df, idx + 1, direction, entry, stop, target)
        if result == "OPEN":
            continue

        # ── POSITION SIZE ──
        size = position_size(account, entry, stop, max(score, 0.53),
                             macro_b, direction, vol_r, dd_scale,
                             peak_equity=peak_equity)
        health_mult, health_block = _symbol_health_controls(recent_closed, symbol_health)
        if health_block is not None:
            vetos[health_block] += 1
            continue
        if health_mult < 1.0:
            vetos["symbol_health_scale"] += 1
        size = round(size * corr_size_mult * trans_mult * THOTH_SIZE_MULT * health_mult, 4)

        # [L6] Aggregate notional cap.
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
        # Liquidation/margin-call simulation, if needed, should be modelled
        # at position-open time against the real liquidation price.
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
        if post_trade_cooldown_bars > 0:
            sym_cooldown_until[symbol] = max(
                sym_cooldown_until.get(symbol, -1),
                idx + int(post_trade_cooldown_bars),
            )

        open_pos.append((idx + 1 + duration, symbol, size, entry))

        ts = df["time"].iloc[idx].strftime("%d/%m %Hh")
        t = {
            "symbol":     symbol,
            "time":       ts,
            "timestamp":  df["time"].iloc[idx],
            "idx":        idx,
            "entry_idx":  idx + 1,
            "strategy":   "BRIDGEWATER",
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
            "health_mult": round(health_mult, 3),
            "in_transition": in_transition,
            "trans_mult":    round(trans_mult, 2),
            "entry":      entry, "stop": stop, "target": target,
            "exit_p":     round(float(exit_p), 6),
            "rr":         rr, "duration": duration, "result": result, "exit_reason": exit_reason, "pnl": pnl,
            "size":       round(size, 4),
            "score":      round(score_reported, 3),
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
            # Normalised trade outcome in R units
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
        recent_closed.append(t)
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
    print(f"  BRIDGEWATER v1.0  ·  {RUN_ID}")
    print(f"  {len(SYMBOLS)} ativos  ·  {INTERVAL}  ·  ${ACCOUNT_SIZE:,.0f}  ·  {LEVERAGE}x")
    print(f"  funding w={THOTH_WEIGHT_FUNDING}  oi w={THOTH_WEIGHT_OI}  ls w={THOTH_WEIGHT_LS}")
    print(f"  preset={RUNTIME_PRESET_NAME}  disable_oi={RUNTIME_DISABLE_OI}  strict_direction={RUNTIME_STRICT_DIRECTION}  min_components={RUNTIME_MIN_COMPONENTS}  min_dir_thresh={RUNTIME_MIN_DIR_THRESH}")
    print(f"  allowed_macro_regimes={sorted(RUNTIME_ALLOWED_MACRO_REGIMES) if RUNTIME_ALLOWED_MACRO_REGIMES else 'ALL'}  post_trade_cooldown={RUNTIME_POST_TRADE_COOLDOWN_BARS}")
    print(f"  regime_thresholds={RUNTIME_REGIME_THRESHOLDS or 'flat'}")
    print(f"  symbol_health={RUNTIME_SYMBOL_HEALTH or 'off'}")
    print(f"  min_coverage_fraction={RUNTIME_MIN_COVERAGE_FRACTION:.2f}")
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
    diagnostics = _trade_sentiment_diagnostics(closed)

    data = {
        "engine": "BRIDGEWATER",
        "version": "1.0",
        "run_id": RUN_ID,
        "timestamp": datetime.now().isoformat(),
        "interval": INTERVAL,
        "n_symbols": len(SYMBOLS),
        "account_size": ACCOUNT_SIZE,
        "leverage": LEVERAGE,
        "preset": RUNTIME_PRESET_NAME,
        "disable_oi": RUNTIME_DISABLE_OI,
        "strict_direction": RUNTIME_STRICT_DIRECTION,
        "min_components": RUNTIME_MIN_COMPONENTS,
        "min_dir_thresh": RUNTIME_MIN_DIR_THRESH,
        "allowed_macro_regimes": sorted(RUNTIME_ALLOWED_MACRO_REGIMES) if RUNTIME_ALLOWED_MACRO_REGIMES else None,
        "post_trade_cooldown_bars": RUNTIME_POST_TRADE_COOLDOWN_BARS,
        "regime_thresholds": RUNTIME_REGIME_THRESHOLDS,
        "symbol_health": RUNTIME_SYMBOL_HEALTH,
        "min_coverage_fraction": RUNTIME_MIN_COVERAGE_FRACTION,
        "n_trades": len(closed),
        "win_rate": round(wr, 2),
        "roi": round(ratios["ret"], 2),
        "sharpe": ratios["sharpe"],
        "sortino": ratios.get("sortino"),
        "final_equity": round(eq[-1], 2) if eq else ACCOUNT_SIZE,
        "sentiment_diagnostics": diagnostics,
        "trades": [{k: (v.isoformat() if isinstance(v, pd.Timestamp) else
                        float(v) if isinstance(v, (np.floating, np.integer)) else v)
                    for k, v in t.items()} for t in closed],
    }

    out = RUN_DIR / "reports" / f"bridgewater_{INTERVAL}_v1.json"
    atomic_write(out, json.dumps(data, indent=2, default=str))
    print(f"  json  ·  {out}")

    try:
        from core.db import save_run
        save_run("bridgewater", str(out))
    except Exception as e:
        log.warning(f"DB register failed: {e}")


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser(
        description="BRIDGEWATER - macro sentiment backtest",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _ap.add_argument("--days", type=int, default=None, help="Lookback window in days.")
    _ap.add_argument("--basket", type=str, default=None, help="Universe preset from BASKETS.")
    _ap.add_argument("--symbols", default=None, help="Optional comma-separated symbols; overrides --basket.")
    _ap.add_argument("--interval", type=str, default=INTERVAL, help="Execution timeframe override for this run.")
    _ap.add_argument("--leverage", type=float, default=None, help="Leverage override for this run.")
    _ap.add_argument("--no-menu", action="store_true")
    _ap.add_argument("--end", type=str, default=None,
                     help="End date YYYY-MM-DD for backtest window (pre-calibration OOS).")
    _ap.add_argument("--preset", choices=["robust", "legacy"], default="robust",
                     help="Runtime preset. robust=funding+LS with harder gates; legacy=historical baseline path.")
    _ap.add_argument("--disable-oi", action="store_true",
                     help="Disable OI channel for this run. Automatically enabled by preset=robust.")
    _ap.add_argument("--enable-symbol-health", action="store_true",
                     help="Enable adaptive per-symbol health control (research gate; default off).")
    _ap.add_argument("--allowed-regimes", default=None,
                     help="Optional comma-separated macro regimes to allow, e.g. BEAR or BEAR,BULL.")
    _ap.add_argument("--min-coverage-fraction", type=float, default=0.70,
                     help="Minimum fraction of the requested scan window that must have usable sentiment coverage.")
    _ap.add_argument("--post-trade-cooldown-bars", type=int, default=0,
                     help="Optional per-symbol cooldown after any closed trade. preset=robust defaults to 6.")
    # Research gates (default OFF — preserve calibrated baseline).
    # See scan_thoth docstring for rationale; wired for 2026-07-17 OOS battery.
    _ap.add_argument("--strict-direction", action="store_true",
                     help="Require explicit struct or macro match (removes neutral-struct fallback).")
    _ap.add_argument("--min-components", type=int, default=0,
                     help="Require at least N of {funding, oi, ls} signals non-zero (default 0 = off).")
    _ap.add_argument("--min-dir-thresh", type=float, default=None,
                     help="Override THOTH_DIRECTION_THRESHOLD for this run (default uses config).")
    _ap.add_argument("--exit-on-reversal", action="store_true",
                     help="(reserved) close position when composite sentiment reverses past threshold.")
    _args, _ = _ap.parse_known_args()
    END_TIME_MS = None
    if _args.end:
        import pandas as _pd_tmp
        END_TIME_MS = int(_pd_tmp.Timestamp(_args.end).timestamp() * 1000)

    if _args.interval:
        INTERVAL = _args.interval

    _runtime = _resolve_runtime_preset(
        _args.preset,
        strict_direction=_args.strict_direction,
        min_components=_args.min_components,
        min_dir_thresh=_args.min_dir_thresh,
        disable_oi=_args.disable_oi,
        enable_symbol_health=_args.enable_symbol_health,
        allowed_regimes=_args.allowed_regimes,
        post_trade_cooldown_bars=_args.post_trade_cooldown_bars,
    )
    RUNTIME_PRESET_NAME = _runtime["preset"]
    RUNTIME_STRICT_DIRECTION = _runtime["strict_direction"]
    RUNTIME_MIN_COMPONENTS = _runtime["min_components"]
    RUNTIME_MIN_DIR_THRESH = _runtime["min_dir_thresh"]
    RUNTIME_DISABLE_OI = _runtime["disable_oi"]
    RUNTIME_ALLOWED_MACRO_REGIMES = _runtime["allowed_macro_regimes"]
    RUNTIME_POST_TRADE_COOLDOWN_BARS = _runtime["post_trade_cooldown_bars"]
    RUNTIME_REGIME_THRESHOLDS = _runtime["regime_thresholds"]
    RUNTIME_SYMBOL_HEALTH = _runtime["symbol_health"]
    RUNTIME_MIN_COVERAGE_FRACTION = max(0.0, min(1.0, float(_args.min_coverage_fraction)))

    print(f"\n{SEP}")
    print(f"  BRIDGEWATER  ·  Macro Sentiment Contrarian")
    print(f"  {SEP}")

    if _args.days:
        SCAN_DAYS = _args.days
    elif not _args.no_menu:
        _days_in = safe_input(f"\n  periodo em dias [{SCAN_DAYS}] > ").strip()
        if _days_in.isdigit() and 7 <= int(_days_in) <= 1500:
            SCAN_DAYS = int(_days_in)
    # N_CANDLES scales with TF (15m=4/h, 1h=1/h, 4h=1/4h)
    _tf_per_hour = 60 / _TF_MINUTES.get(INTERVAL, 15)
    N_CANDLES = int(SCAN_DAYS * 24 * _tf_per_hour)
    WARMUP_BARS = _scan_warmup_bars()
    FETCH_CANDLES = N_CANDLES + WARMUP_BARS

    _symbols_override = _parse_symbols_override(_args.symbols)
    BASKET_NAME = "custom" if _symbols_override else (_args.basket or ENGINE_BASKETS.get("BRIDGEWATER", "default"))
    from config.params import BASKETS
    if _symbols_override:
        SYMBOLS = _symbols_override
    elif BASKET_NAME in BASKETS:
        SYMBOLS = BASKETS[BASKET_NAME]
    elif not _args.no_menu:
        SYMBOLS = select_symbols(SYMBOLS)

    if _args.leverage is not None:
        if 0.1 <= _args.leverage <= 125:
            LEVERAGE = _args.leverage
    elif not _args.no_menu:
        _lev_in = safe_input(f"  leverage [{LEVERAGE}x] > ").strip()
        if _lev_in:
            try:
                _lev_val = float(_lev_in.replace("x", ""))
                if 0.1 <= _lev_val <= 125:
                    LEVERAGE = _lev_val
            except ValueError:
                pass

    print(f"\n{SEP}")
    print(f"  BRIDGEWATER  ·  {SCAN_DAYS}d  ·  {len(SYMBOLS)} ativos  ·  {INTERVAL}")
    print(f"  ${ACCOUNT_SIZE:,.0f}  ·  {LEVERAGE}x")
    print(f"  preset={RUNTIME_PRESET_NAME}  disable_oi={RUNTIME_DISABLE_OI}  strict_direction={RUNTIME_STRICT_DIRECTION}  min_components={RUNTIME_MIN_COMPONENTS}  min_dir_thresh={RUNTIME_MIN_DIR_THRESH}")
    print(f"  allowed_macro_regimes={sorted(RUNTIME_ALLOWED_MACRO_REGIMES) if RUNTIME_ALLOWED_MACRO_REGIMES else 'ALL'}  post_trade_cooldown={RUNTIME_POST_TRADE_COOLDOWN_BARS}")
    print(f"  regime_thresholds={RUNTIME_REGIME_THRESHOLDS or 'flat'}")
    print(f"  symbol_health={RUNTIME_SYMBOL_HEALTH or 'off'}")
    print(f"  min_coverage_fraction={RUNTIME_MIN_COVERAGE_FRACTION:.2f}")
    print(f"  {RUN_DIR}/")
    print(SEP)
    if not _args.no_menu:
        safe_input("  enter para iniciar... ")

    log.info(f"BRIDGEWATER v1.0 iniciado — {RUN_ID}  tf={INTERVAL}  dias={SCAN_DAYS}")

    # ── FETCH OHLCV ──
    print(f"\n{SEP}\n  DADOS   {INTERVAL}   {FETCH_CANDLES:,} candles ({N_CANDLES:,} scan + {WARMUP_BARS} warmup)\n{SEP}")
    _fetch_syms = list(SYMBOLS)
    if MACRO_SYMBOL not in _fetch_syms:
        _fetch_syms.insert(0, MACRO_SYMBOL)
    all_dfs = fetch_all(
        _fetch_syms,
        INTERVAL,
        FETCH_CANDLES,
        futures=True,
        min_rows=min(300, FETCH_CANDLES),
        end_time_ms=END_TIME_MS,
    )
    all_dfs, stale_symbols = _filter_stale_market_data(all_dfs, INTERVAL)
    if stale_symbols:
        print(f"  stale symbols skipped: {', '.join(sorted(stale_symbols))}")
        log.warning(f"stale OHLCV skipped: {sorted(stale_symbols)}")
    for sym, df in all_dfs.items():
        validate(df, sym)
    if not all_dfs:
        print("  sem dados"); sys.exit(1)

    macro_bias = detect_macro(all_dfs)
    corr = build_corr_matrix(all_dfs)

    # ── FETCH SENTIMENT ──
    print(f"\n{SEP}\n  SENTIMENT DATA\n{SEP}")
    sentiment_data = collect_sentiment(
        [s for s in SYMBOLS if s in all_dfs],
        end_time_ms=END_TIME_MS,
        window_days=SCAN_DAYS,
    )
    eligible_symbols = [
        s for s in SYMBOLS
        if s in all_dfs
        and s in sentiment_data
        and sentiment_data[s].get("funding_z") is not None
        and sentiment_data[s].get("oi_ready", sentiment_data[s].get("oi_df") is not None)
        and sentiment_data[s].get("ls_ready", sentiment_data[s].get("ls_signal") is not None)
    ]
    skipped_sentiment = sorted([s for s in SYMBOLS if s in all_dfs and s not in eligible_symbols])
    if skipped_sentiment:
        print(f"  sentiment-incomplete symbols skipped: {', '.join(skipped_sentiment)}")
        log.warning(f"sentiment-incomplete symbols skipped: {skipped_sentiment}")
    if not eligible_symbols:
        print("  sem simbolos com sentiment completo"); sys.exit(1)
    all_dfs = {sym: all_dfs[sym] for sym in eligible_symbols}
    SYMBOLS = eligible_symbols

    if not _scan_window_can_close_trades(N_CANDLES):
        print(f"\n  insufficient sample: {N_CANDLES} candles <= MAX_HOLD {MAX_HOLD}")
        log.warning(f"insufficient sample for closed trades: n_candles={N_CANDLES} max_hold={MAX_HOLD}")
        sys.exit(0)

    print_header()

    # ── SCAN ──
    print(f"\n{SEP}\n  SCAN SENTIMENT\n{SEP}")
    all_trades = []
    all_vetos = defaultdict(int)
    insufficient_coverage_symbols: list[str] = []
    insufficient_coverage_details: list[str] = []

    for sym, df in all_dfs.items():
        coverage = _coverage_eligibility(
            df,
            sentiment_data.get(sym),
            max(0, len(df) - N_CANDLES),
            min_fraction=RUNTIME_MIN_COVERAGE_FRACTION,
        )
        symbol_scan_start_idx = int(coverage["scan_start_idx"])
        remaining_scan_candles = int(coverage["covered_scan_candles"])
        if not coverage["eligible"]:
            insufficient_coverage_symbols.append(sym)
            insufficient_coverage_details.append(
                f"{sym}({remaining_scan_candles}/{coverage['total_scan_candles']}="
                f"{coverage['coverage_fraction']:.0%}, closeable={coverage['closeable']})"
            )
            log.warning(
                "sentiment coverage insufficient: %s scan_candles=%s total_scan=%s coverage=%.2f closeable=%s min_required=%.2f",
                sym,
                remaining_scan_candles,
                coverage["total_scan_candles"],
                coverage["coverage_fraction"],
                coverage["closeable"],
                RUNTIME_MIN_COVERAGE_FRACTION,
            )
            continue
        trades, vetos = scan_thoth(df, sym, macro_bias, corr,
                                   sentiment_data=sentiment_data,
                                   scan_start_idx=symbol_scan_start_idx,
                                   disable_oi=RUNTIME_DISABLE_OI,
                                   allowed_macro_regimes=RUNTIME_ALLOWED_MACRO_REGIMES,
                                   post_trade_cooldown_bars=RUNTIME_POST_TRADE_COOLDOWN_BARS,
                                   regime_thresholds=RUNTIME_REGIME_THRESHOLDS,
                                   symbol_health=RUNTIME_SYMBOL_HEALTH,
                                   strict_direction=RUNTIME_STRICT_DIRECTION,
                                   min_components=RUNTIME_MIN_COMPONENTS,
                                   min_dir_thresh=RUNTIME_MIN_DIR_THRESH,
                                   exit_on_reversal=_args.exit_on_reversal)
        all_trades.extend(trades)
        for k, v in vetos.items():
            all_vetos[k] += v

    all_trades.sort(key=lambda t: t["timestamp"])

    closed = [t for t in all_trades if t["result"] in ("WIN", "LOSS")]
    if insufficient_coverage_symbols:
        skipped = ", ".join(sorted(insufficient_coverage_symbols))
        print(f"  insufficient sentiment coverage skipped: {skipped}")
        print(f"  coverage rule: need >= {RUNTIME_MIN_COVERAGE_FRACTION:.0%} of requested scan window with closeable sentiment history")
        for detail in sorted(insufficient_coverage_details)[:8]:
            print(f"    {detail}")
        if not closed:
            print(f"\n  insufficient sentiment coverage: need more cached OI/LS history to close trades")
            sys.exit(0)
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

    total_pnl = sum(pnl_list)
    mc = monte_carlo(pnl_list)
    wf = walk_forward(closed)

    if all_vetos:
        # Coalesce parametric vetos like "agg_cap(15344>9940)" into a single bucket
        import re as _re
        _coalesced: dict[str, int] = defaultdict(int)
        for k, v in all_vetos.items():
            base = _re.sub(r"\([^)]*\)", "", str(k)).strip() or str(k)
            _coalesced[base] += v
        print(f"\n{SEP}\n  VETOS\n{SEP}")
        for k, v in sorted(_coalesced.items(), key=lambda x: -x[1])[:10]:
            print(f"  {v:>6d}  {k}")

    # ── BY SYMBOL ──
    by_sym: dict[str, list] = defaultdict(list)
    for t in all_trades:
        by_sym[t["symbol"]].append(t)

    # ── WALK-FORWARD BY REGIME ──
    from analysis.walkforward import walk_forward_by_regime
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
    from core.run_manager import snapshot_config, save_run_artifacts, append_to_index

    roi = ratios["ret"]
    _config = snapshot_config()
    _config["BASKET_EFFECTIVE"] = BASKET_NAME
    _summary = {
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
        "engine": "BRIDGEWATER",
        "preset": RUNTIME_PRESET_NAME,
        "disable_oi": RUNTIME_DISABLE_OI,
        "strict_direction": RUNTIME_STRICT_DIRECTION,
        "min_components": RUNTIME_MIN_COMPONENTS,
        "min_dir_thresh": RUNTIME_MIN_DIR_THRESH,
        "allowed_macro_regimes": sorted(RUNTIME_ALLOWED_MACRO_REGIMES) if RUNTIME_ALLOWED_MACRO_REGIMES else None,
        "post_trade_cooldown_bars": RUNTIME_POST_TRADE_COOLDOWN_BARS,
        "regime_thresholds": RUNTIME_REGIME_THRESHOLDS,
        "symbol_health": RUNTIME_SYMBOL_HEALTH,
        "min_coverage_fraction": RUNTIME_MIN_COVERAGE_FRACTION,
    }

    save_run_artifacts(
        RUN_DIR, _config, all_trades, eq, _summary,
        overfit_results=audit_results,
    )
    append_to_index(RUN_DIR, _summary, _config, audit_results)

    # ── HTML Report ──
    try:
        from analysis.report_html import generate_report
        generate_report(
            all_trades, eq, mc, cond, ratios, mdd_pct, wf, wf_regime,
            by_sym, all_vetos, str(RUN_DIR), config_dict=_config,
            audit_results=audit_results,
            engine_name="BRIDGEWATER",
        )
        print(f"  HTML → {RUN_DIR / 'report.html'}")
    except Exception as _e:
        log.warning(f"HTML report failed: {_e}")

    # ── JSON export (legacy + DB) ──
    export_json(all_trades, eq, mc, ratios)

    print(f"\n{SEP}\n  output  ·  {RUN_DIR}/\n{SEP}\n")
