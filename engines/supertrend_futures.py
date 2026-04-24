"""
AURUM Finance — SUPERTREND FUT Engine v1.0

Port da FSupertrendStrategy (Freqtrade futures lane), validada em lab
externo (C:\\ft_lab\\results\\shortlist_futures_code\\FSupertrendStrategy.py).

Origem
------
Autor original: Juan Carlos Soriano (@juankysoriano) — Freqtrade
user_data/strategies/futures/. Port sob requisito AURUM:
  - usa ``core.indicators.supertrend`` (ATR SMA-based, fiel ao original)
  - leitura de OHLC via core.data padrão AURUM (fetch_all, validate)
  - backtest standalone (sem depender de Freqtrade runtime)

Hipótese econômica
------------------
Trend-following com tripla confluência: três Supertrends com
period/multiplier distintos votam na direção. Entrada exige unanimidade
(3 votos "up" para LONG, 3 "down" para SHORT); saída precisa apenas do
supertrend #2 do lado oposto virar — assimetria clássica de
trend-follower, captura trends fortes e sai no primeiro sinal de
reversão. Futures + shorts = regime-agnóstico.

Regime esperado de melhor performance
-------------------------------------
TRENDING (bull ou bear com direcionalidade sustentada). Sofre em
mercado lateral/choppy (3 Supertrends raramente convergem).

Resultados de validação do lab externo (1h TF, BTC/ETH/SOL USDT futures,
leverage 2x, can_short)
----------------------
- OOS 2024 (bull):   Sharpe +0.55, ROI +7.95%, MaxDD 15.97%, 282 trades
- Q4 2024 (stress):  Sharpe +0.82, ROI +5.19%, MaxDD 15.97%, 140 trades
- Bear 2022:         Sharpe -0.08, ROI -1.73%, MaxDD 23.56%, 382 trades
    → sobreviveu o bear com perda contida via shorts. Perfil defensivo.

Status
------
PHASE 1 de 3: implementação + testes unitários. NÃO ativado no
ensemble (``live_ready=False``, ``stage="research"``). Ativação vem
depois de overfit audit 6/6 em ``feat/phi-engine``.

Nota de fidelidade
------------------
Stop/ROI/trailing seguem o original freqtrade:
  - stoploss: -26.5% (fixo, dá espaço pro trade respirar)
  - ROI inicial: +10% (target em entrada)
  - Exit adicional: supertrend oposto (#2) flip — matches populate_exit_trend
Sem uso de ``core.signals.calc_levels`` (swing-based) pra preservar a
validação do lab. AURUM tem outro modelo de stops/targets para engines
próprios (CITADEL/JUMP), não misturamos aqui.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from config.params import (
    ACCOUNT_SIZE, BASKETS, COMMISSION, MACRO_SYMBOL,
    SCAN_DAYS, SLIPPAGE, SPREAD, SYMBOLS,
)
from analysis.stats import calc_ratios, equity_stats
from core import fetch_all, validate
from core.indicators import supertrend
from core.ops.run_manager import append_to_index, save_run_artifacts, snapshot_config
from core.ops.fs import atomic_write


# ── OVERFIT-AUDIT SPLITS (hardcoded — anti-overfit protocol Passo 2) ─
# Registrados em docs/engines/supertrend_futures/grid.md. NÃO mudar sem
# reabrir o protocolo. Qualquer bateria precisa respeitar estas datas.
TRAIN_START: str = "2022-01-01"
TRAIN_END: str = "2024-01-01"
TEST_END: str = "2025-01-01"
HOLDOUT_END: str = "2026-04-22"

# ── ENGINE CONSTANTS (local; NÃO toca config/params.py) ──────────────
INTERVAL: str = "1h"
LEVERAGE: float = 2.0
CAN_SHORT: bool = True

# Freqtrade hyperopted defaults (BUY side) — 3 supertrends simultâneos
SUPERTREND_BUY_M1: int = 4
SUPERTREND_BUY_P1: int = 8
SUPERTREND_BUY_M2: int = 7
SUPERTREND_BUY_P2: int = 9
SUPERTREND_BUY_M3: int = 1
SUPERTREND_BUY_P3: int = 8

# Freqtrade hyperopted defaults (SELL side) — outros 3 supertrends
SUPERTREND_SELL_M1: int = 1
SUPERTREND_SELL_P1: int = 16
SUPERTREND_SELL_M2: int = 3
SUPERTREND_SELL_P2: int = 18
SUPERTREND_SELL_M3: int = 6
SUPERTREND_SELL_P3: int = 18

# Risk / exit params (fiel ao freqtrade)
STOPLOSS_PCT: float = 0.265   # -26.5%
INITIAL_ROI_PCT: float = 0.10  # +10% target inicial
MAX_HOLD_BARS: int = 120       # 5 dias @ 1h (freqtrade ROI table morre em 2h;
                               # MAX_HOLD alto + ROI-decay não-implementado
                               # = exit por supertrend flip ou stop prevalece).

# Metadata do engine — consumido por tools/registry/audit
ENGINE_METADATA: dict = {
    "name": "SUPERTREND_FUT",
    "display": "SUPERTREND FUT",
    "origin": "Freqtrade FSupertrendStrategy (futures lane; @juankysoriano)",
    "hypothesis": (
        "Three Supertrends with different (multiplier, period) vote on "
        "trend direction. Entry requires 3/3 confluence (up=LONG, "
        "down=SHORT); exit needs only the medium-period Supertrend of "
        "the opposing side to flip — trend-follower asymmetry."
    ),
    "best_regime": "TRENDING (bull or bear with sustained directionality)",
    "worst_regime": "CHOP / low-volatility lateral",
    "validation": {
        "lab": "C:\\ft_lab external backtest",
        "timeframe": "1h",
        "leverage": 2.0,
        "can_short": True,
        "pairs": ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"],
        "oos_bull_2024":   {"sharpe": 0.55,  "roi_pct": 7.95,  "dd_pct": 15.97, "trades": 282},
        "q4_2024_stress":  {"sharpe": 0.82,  "roi_pct": 5.19,  "dd_pct": 15.97, "trades": 140},
        "bear_2022":       {"sharpe": -0.08, "roi_pct": -1.73, "dd_pct": 23.56, "trades": 382},
    },
    "phase": 1,  # 1=port+unit tests, 2=overfit audit, 3=ensemble activation
}


RUN_ID = datetime.now().strftime("%Y-%m-%d_%H%M%S")
RUN_DIR = ROOT / "data" / "supertrend_futures" / RUN_ID
(RUN_DIR / "reports").mkdir(parents=True, exist_ok=True)
(RUN_DIR / "logs").mkdir(parents=True, exist_ok=True)

log = logging.getLogger("SUPERTREND_FUT")
log.setLevel(logging.INFO)
log.handlers.clear()
_fmt = logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s")
_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
_fh = logging.FileHandler(RUN_DIR / "logs" / "supertrend_futures.log", encoding="utf-8")
_fh.setFormatter(_fmt)
log.addHandler(_sh)
log.addHandler(_fh)

SEP = "-" * 80


# ── CORE LOGIC ───────────────────────────────────────────────────────

def _compute_supertrend_set(df: pd.DataFrame) -> pd.DataFrame:
    """Attach the 6 Supertrend direction columns to ``df``.

    Retorna um novo DataFrame (não muta ``df``), com colunas:
      buy_1, buy_2, buy_3, sell_1, sell_2, sell_3 — cada uma string
      {'up', 'down', ''}.
    """
    out = df.copy()
    configs = [
        ("buy_1",  SUPERTREND_BUY_M1,  SUPERTREND_BUY_P1),
        ("buy_2",  SUPERTREND_BUY_M2,  SUPERTREND_BUY_P2),
        ("buy_3",  SUPERTREND_BUY_M3,  SUPERTREND_BUY_P3),
        ("sell_1", SUPERTREND_SELL_M1, SUPERTREND_SELL_P1),
        ("sell_2", SUPERTREND_SELL_M2, SUPERTREND_SELL_P2),
        ("sell_3", SUPERTREND_SELL_M3, SUPERTREND_SELL_P3),
    ]
    for tag, mult, per in configs:
        st_df = supertrend(out, multiplier=mult, period=per)
        out[f"st_{tag}_line"] = st_df["st"].values
        out[f"st_{tag}"] = st_df["stx"].values
    return out


def _signal_confidence(df: pd.DataFrame, idx: int, direction: str) -> float:
    """Distância normalizada do close à linha medium-period (#2).

    Retorna float ∈ [0.0, 1.0]. A #2 é o "voto decisivo" (mesma usada
    para exit); quanto mais longe o close está da sua linha na direção
    favorável, mais forte o trend. Normalizamos por ATR local (SMA do
    TR, período = SUPERTREND_BUY_P2/SELL_P2) pra ficar scale-invariant.
    """
    close = df["close"].iat[idx]
    if direction == "BULLISH":
        line_col = "st_buy_2_line"
        per = SUPERTREND_BUY_P2
    else:
        line_col = "st_sell_2_line"
        per = SUPERTREND_SELL_P2
    line = df[line_col].iat[idx]
    if line is None or line == 0.0 or np.isnan(line):
        return 0.0
    h, l, c = df["high"], df["low"], df["close"]
    tr = np.maximum.reduce([
        (h - l).to_numpy(),
        (h - c.shift()).abs().to_numpy(),
        (l - c.shift()).abs().to_numpy(),
    ])
    atr_local = pd.Series(tr).rolling(per, min_periods=per).mean().iat[idx]
    if atr_local is None or atr_local == 0.0 or np.isnan(atr_local):
        return 0.0
    dist = abs(close - line) / atr_local
    # ATR-normalized distance. 1.0 ATR = confidence 0.5, 3+ ATR = sat.
    return float(np.clip(dist / 3.0, 0.0, 1.0))


def _label_supertrend_trade(
    df: pd.DataFrame,
    entry_idx: int,
    direction: str,
    entry: float,
    stop: float,
    target: float,
) -> tuple[str, int, float, str]:
    """Path-dependent exit: stop | target | supertrend flip | max_hold.

    Exit rule matches freqtrade's populate_exit_trend:
      LONG  exits if st_sell_2 flips to 'down'
      SHORT exits if st_buy_2  flips to 'up'
    Returns (result, duration_bars, exit_price, exit_reason).
    """
    end = min(entry_idx + MAX_HOLD_BARS, len(df))
    for j in range(entry_idx, end):
        h = df["high"].iat[j]
        l = df["low"].iat[j]
        c = df["close"].iat[j]
        if direction == "BULLISH":
            # Check stop first (defensive ordering)
            if l <= stop:
                return "LOSS", j - entry_idx, stop, "stop_initial"
            if h >= target:
                return "WIN", j - entry_idx, target, "target"
            # Exit-on-flip: st_sell_2 viraram 'down'
            if df["st_sell_2"].iat[j] == "down":
                result = "WIN" if c > entry else "LOSS"
                return result, j - entry_idx, c, "supertrend_flip"
        else:
            if h >= stop:
                return "LOSS", j - entry_idx, stop, "stop_initial"
            if l <= target:
                return "WIN", j - entry_idx, target, "target"
            if df["st_buy_2"].iat[j] == "up":
                result = "WIN" if c < entry else "LOSS"
                return result, j - entry_idx, c, "supertrend_flip"
    # Max hold — close at last available bar
    last = min(end - 1, len(df) - 1)
    close_last = df["close"].iat[last]
    if direction == "BULLISH":
        result = "WIN" if close_last > entry else "LOSS"
    else:
        result = "WIN" if close_last < entry else "LOSS"
    return result, last - entry_idx, close_last, "max_hold"


def scan_supertrend(
    df: pd.DataFrame,
    symbol: str,
    macro_bias_series=None,
    corr: dict | None = None,
    htf_stack_dfs: dict | None = None,
    live_mode: bool = False,
    live_tail_bars: int = 4,
) -> tuple[list, dict]:
    """Scan a symbol for Supertrend-confluence entries.

    Signature espelha scan_symbol (CITADEL) / scan_mercurio (JUMP) pra
    plug-in futuro no ensemble. Args ``macro_bias_series``, ``corr``,
    ``htf_stack_dfs`` são aceitos mas ignorados — Supertrend é
    standalone por design freqtrade. Mantemos a assinatura por
    consistência com o padrão.

    ``live_mode=True`` varre só as últimas ``live_tail_bars`` candles
    (default 4 = 4h @ 1h TF); hits emitem ``result='LIVE'`` sem
    labelagem path-dependent.

    Retorna ``(trades, vetos)``. Vetos contam motivos de rejeição.
    """
    del macro_bias_series, corr, htf_stack_dfs  # intencionalmente ignorados

    trades: list[dict] = []
    vetos: defaultdict[str, int] = defaultdict(int)

    if df is None or len(df) == 0:
        return trades, dict(vetos)

    df = _compute_supertrend_set(df)

    # Período de warm-up: maior dos P's usados
    warmup = max(
        SUPERTREND_BUY_P1, SUPERTREND_BUY_P2, SUPERTREND_BUY_P3,
        SUPERTREND_SELL_P1, SUPERTREND_SELL_P2, SUPERTREND_SELL_P3,
    ) + 2

    # Loop range — backtest precisa de MAX_HOLD forward bars pra rotular;
    # live_mode varre só a tail.
    if live_mode:
        loop_start = max(warmup, len(df) - live_tail_bars - 1)
        loop_end = len(df) - 1
    else:
        loop_start = warmup
        loop_end = len(df) - MAX_HOLD_BARS - 2
    if loop_end <= loop_start:
        return trades, dict(vetos)

    # Freqtrade semantics: 1 posição por vez. Após abrir em idx e durar
    # D bars, só reavalia entrada em idx+D+1 (cooldown = duração).
    # Sem isso, loop bar-by-bar multi-conta trades sobrepostos.
    idx = loop_start
    while idx < loop_end:
        vol = df["vol"].iat[idx] if "vol" in df.columns else 1.0
        if vol is None or vol <= 0 or np.isnan(vol):
            vetos["zero_volume"] += 1
            idx += 1
            continue

        # LONG: 3/3 buy supertrends "up"
        long_ok = (
            df["st_buy_1"].iat[idx] == "up"
            and df["st_buy_2"].iat[idx] == "up"
            and df["st_buy_3"].iat[idx] == "up"
        )
        # SHORT: 3/3 sell supertrends "down"
        short_ok = (
            df["st_sell_1"].iat[idx] == "down"
            and df["st_sell_2"].iat[idx] == "down"
            and df["st_sell_3"].iat[idx] == "down"
        )
        if not (long_ok or short_ok):
            vetos["no_confluence"] += 1
            idx += 1
            continue
        if long_ok and short_ok:
            vetos["both_sides_confluence"] += 1
            idx += 1
            continue

        if idx + 1 >= len(df):
            vetos["no_next_bar"] += 1
            idx += 1
            continue

        raw = df["open"].iat[idx + 1]
        slip = SLIPPAGE + SPREAD
        direction = "BULLISH" if long_ok else "BEARISH"
        if direction == "BULLISH":
            entry = raw * (1 + slip)
            stop = entry * (1 - STOPLOSS_PCT)
            target = entry * (1 + INITIAL_ROI_PCT)
        else:
            entry = raw * (1 - slip)
            stop = entry * (1 + STOPLOSS_PCT)
            target = entry * (1 - INITIAL_ROI_PCT)

        confidence = _signal_confidence(df, idx, direction)

        # Sizing simples — notional = ACCOUNT_SIZE * LEVERAGE * confidence_weight
        # (phase 1: sem integração com risk gates AURUM — overfit audit
        # depois decide se pluga no ensemble sizing)
        notional = ACCOUNT_SIZE * LEVERAGE * max(confidence, 0.25)
        size = notional / entry if entry > 0 else 0.0

        trade = {
            "symbol": symbol,
            "time": df["time"].iat[idx] if "time" in df.columns else idx,
            "timestamp": df["time"].iat[idx] if "time" in df.columns else idx,
            "idx": idx,
            "entry_idx": idx + 1,
            "strategy": "SUPERTREND_FUT",
            "direction": direction,
            "trade_type": "TREND_CONFLUENCE",
            "entry": round(entry, 8),
            "stop": round(stop, 8),
            "target": round(target, 8),
            "size": round(size, 4),
            "score": round(confidence, 4),
            "confidence": round(confidence, 4),
            "rr": round(abs(target - entry) / max(abs(entry - stop), 1e-9), 3),
            "leverage": LEVERAGE,
            "st_buy_1": df["st_buy_1"].iat[idx],
            "st_buy_2": df["st_buy_2"].iat[idx],
            "st_buy_3": df["st_buy_3"].iat[idx],
            "st_sell_1": df["st_sell_1"].iat[idx],
            "st_sell_2": df["st_sell_2"].iat[idx],
            "st_sell_3": df["st_sell_3"].iat[idx],
        }

        if live_mode:
            trade["result"] = "LIVE"
            trade["exit_reason"] = "live"
            trade["pnl"] = 0.0
            trade["duration"] = 0
            trade["exit_p"] = round(entry, 8)
            trade["r_multiple"] = 0.0
        else:
            result, duration, exit_p, reason = _label_supertrend_trade(
                df, idx + 1, direction, entry, stop, target,
            )
            # Gross PnL based on size * price diff, minus commission both sides.
            if direction == "BULLISH":
                gross = (exit_p - entry) * size
            else:
                gross = (entry - exit_p) * size
            fees = (entry * size + exit_p * size) * COMMISSION
            pnl = gross - fees
            risk_abs = abs(entry - stop) * size
            r_mult = (pnl / risk_abs) if risk_abs > 0 else 0.0
            trade.update({
                "result": result,
                "exit_reason": reason,
                "exit_p": round(exit_p, 8),
                "pnl": round(pnl, 4),
                "duration": duration,
                "r_multiple": round(r_mult, 3),
            })

        trades.append(trade)

        # Cooldown: pula pra idx + duration + 1 (só reavalia entrada
        # depois do trade ter saído). live_mode mantém step=1 pra varrer
        # todas as últimas N bars e reportar último sinal ativo.
        if live_mode:
            idx += 1
        else:
            idx += max(1, int(trade.get("duration", 1)) + 1)

    return trades, dict(vetos)


def get_regime_fit(macro_bias: str | None) -> float:
    """Fit score vs macro regime string ('BULL'|'BEAR'|'CHOP'|None).

    Based on lab validation: bull OOS Sharpe 0.55, Q4 stress 0.82,
    bear 2022 -0.08. Trend-friendly, chop-hostile.
    """
    if not macro_bias:
        return 0.5
    mb = str(macro_bias).upper()
    return {
        "BULL": 0.70,
        "BEAR": 0.55,
        "CHOP": 0.25,
    }.get(mb, 0.5)


def get_metadata() -> dict:
    """Return a copy of the engine metadata dict (safe for external use)."""
    return dict(ENGINE_METADATA)


# ── BACKTEST RUNNER ──────────────────────────────────────────────────

def _closed_stats(all_trades: list[dict]) -> tuple[list[dict], int, int, int, float]:
    closed = [t for t in all_trades if t.get("result") in ("WIN", "LOSS")]
    win_count = sum(1 for t in closed if t.get("result") == "WIN")
    loss_count = sum(1 for t in closed if t.get("result") == "LOSS")
    flat_count = len(closed) - win_count - loss_count
    win_rate = (win_count / len(closed) * 100.0) if closed else 0.0
    return closed, win_count, loss_count, flat_count, win_rate


def _export_json(
    all_trades: list[dict],
    ratios: dict,
    equity: list[float],
    vetos: dict[str, int],
    basket: str,
    days: int,
    summary: dict,
    config: dict,
    audit_results: dict | None = None,
) -> Path:
    closed, wins, losses, flat, wr = _closed_stats(all_trades)
    max_dd_pct = equity_stats([t["pnl"] for t in closed], ACCOUNT_SIZE)[2] if closed else 0.0
    payload = {
        "engine": "SUPERTREND_FUT",
        "version": "1.0",
        "run_id": RUN_ID,
        "timestamp": datetime.now().isoformat(),
        "interval": INTERVAL,
        "basket": basket,
        "period_days": days,
        "n_symbols": len({t.get("symbol") for t in all_trades}),
        "account_size": ACCOUNT_SIZE,
        "leverage": LEVERAGE,
        "n_trades": len(closed),
        "win_count": wins,
        "loss_count": losses,
        "flat_count": flat,
        "win_rate": round(wr, 2),
        "roi": round(ratios.get("ret", 0.0), 2),
        "sharpe": ratios.get("sharpe"),
        "sortino": ratios.get("sortino"),
        "final_equity": round(equity[-1], 2) if equity else ACCOUNT_SIZE,
        "max_dd_pct": round(max_dd_pct, 2),
        "vetos": vetos,
        "metadata": ENGINE_METADATA,
        "trades": [
            {
                k: (v.isoformat() if hasattr(v, "isoformat")
                    else float(v) if isinstance(v, (int, float)) and not isinstance(v, bool)
                    else v)
                for k, v in trade.items()
            }
            for trade in closed
        ],
    }
    out = RUN_DIR / "reports" / f"supertrend_futures_{INTERVAL}_v1.json"
    atomic_write(out, json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    save_run_artifacts(RUN_DIR, config, all_trades, equity, summary, overfit_results=audit_results)
    append_to_index(RUN_DIR, summary, config, audit_results)
    return out


def main() -> int:
    global LEVERAGE
    parser = argparse.ArgumentParser(description="SUPERTREND FUT standalone backtest")
    parser.add_argument("--days", type=int, default=SCAN_DAYS)
    parser.add_argument("--basket", default="default")
    parser.add_argument("--leverage", type=float, default=LEVERAGE)
    parser.add_argument("--end", type=str, default=None,
                        help="End date YYYY-MM-DD for OOS backtest window.")
    args, _ = parser.parse_known_args()
    LEVERAGE = float(args.leverage)
    end_time_ms = None
    if args.end:
        end_time_ms = int(pd.Timestamp(args.end).timestamp() * 1000)

    symbols = list(BASKETS.get(args.basket, SYMBOLS))
    # 1h timeframe → ~24 candles/day
    n_candles = args.days * 24 + 300  # warm-up buffer

    print(f"\n{SEP}")
    print(f"  SUPERTREND_FUT  |  {args.days}d  |  {len(symbols)} ativos  |  {INTERVAL}")
    print(f"  ${ACCOUNT_SIZE:,.0f}  |  {LEVERAGE}x  |  PHASE 1 (port + tests)")
    print(f"  {RUN_DIR}/")
    print(SEP)

    _fetch_syms = list(symbols)
    if MACRO_SYMBOL not in _fetch_syms:
        _fetch_syms.insert(0, MACRO_SYMBOL)
    all_dfs = fetch_all(
        _fetch_syms, interval=INTERVAL, n_candles=n_candles,
        futures=True, end_time_ms=end_time_ms,
    )
    for sym, df in all_dfs.items():
        validate(df, sym)
    if not all_dfs:
        print("  sem dados")
        return 1

    all_trades: list[dict] = []
    all_vetos: defaultdict[str, int] = defaultdict(int)

    print(f"\n{SEP}\n  SCAN SUPERTREND (tri-confluence)\n{SEP}")
    for sym, df in all_dfs.items():
        if sym == MACRO_SYMBOL and sym not in symbols:
            continue
        trades, vetos = scan_supertrend(df.copy(), sym)
        all_trades.extend(trades)
        for k, v in vetos.items():
            all_vetos[k] += v
        log.info(f"  {sym:12s}  trades={len(trades):>3d}  vetos={dict(vetos)}")

    all_trades.sort(key=lambda t: (str(t.get("timestamp")), t.get("symbol", "")))
    closed, wins, losses, flat, wr = _closed_stats(all_trades)
    pnl_list = [float(t.get("pnl", 0.0)) for t in closed]
    equity, _, max_dd_pct, _ = equity_stats(pnl_list, ACCOUNT_SIZE)
    ratios = calc_ratios(pnl_list, ACCOUNT_SIZE, n_days=args.days) if pnl_list else {
        "sharpe": None, "sortino": None, "calmar": None, "ret": 0.0,
    }

    final_equity = equity[-1] if equity else ACCOUNT_SIZE
    pnl = final_equity - ACCOUNT_SIZE
    config = snapshot_config()
    config.update({
        "ENGINE": "SUPERTREND_FUT",
        "RUN_ID": RUN_ID,
        "RUN_DIR": str(RUN_DIR),
        "BASKET_EFFECTIVE": args.basket,
        "SELECTED_SYMBOLS": symbols,
        "SCAN_DAYS_EFFECTIVE": args.days,
        "N_CANDLES_EFFECTIVE": n_candles,
        "SUPERTREND_PARAMS": {
            "BUY": [(SUPERTREND_BUY_M1, SUPERTREND_BUY_P1),
                    (SUPERTREND_BUY_M2, SUPERTREND_BUY_P2),
                    (SUPERTREND_BUY_M3, SUPERTREND_BUY_P3)],
            "SELL": [(SUPERTREND_SELL_M1, SUPERTREND_SELL_P1),
                     (SUPERTREND_SELL_M2, SUPERTREND_SELL_P2),
                     (SUPERTREND_SELL_M3, SUPERTREND_SELL_P3)],
            "STOPLOSS_PCT": STOPLOSS_PCT,
            "INITIAL_ROI_PCT": INITIAL_ROI_PCT,
            "MAX_HOLD_BARS": MAX_HOLD_BARS,
        },
    })
    summary = {
        "engine": "SUPERTREND_FUT",
        "run_id": RUN_ID,
        "interval": INTERVAL,
        "period_days": args.days,
        "basket": args.basket,
        "n_symbols": len(symbols),
        "n_candles": n_candles,
        "account_size": ACCOUNT_SIZE,
        "leverage": LEVERAGE,
        "n_trades": len(closed),
        "win_rate": round(wr, 2),
        "pnl": round(pnl, 2),
        "roi_pct": round(ratios.get("ret", 0.0), 2),
        "sharpe": ratios.get("sharpe"),
        "sortino": ratios.get("sortino"),
        "max_dd_pct": round(max_dd_pct, 2),
        "final_equity": round(final_equity, 2),
    }
    try:
        from analysis.overfit_audit import run_audit, print_audit_box
        audit_results = run_audit(all_trades)
        print_audit_box(audit_results)
    except Exception as _e:
        log.warning(f"overfit audit failed: {_e}")
        audit_results = None

    out = _export_json(
        all_trades, ratios, equity, dict(all_vetos), args.basket,
        args.days, summary, config, audit_results=audit_results,
    )

    print(f"\n{SEP}\n  METRICAS\n{SEP}")
    print(f"  Trades    {len(closed)}")
    print(f"  W/L/F     {wins}/{losses}/{flat}")
    print(f"  WR        {wr:.1f}%")
    print(f"  ROI       {ratios.get('ret', 0.0):+.2f}%")
    print(f"  Sharpe    {ratios.get('sharpe') if ratios.get('sharpe') is not None else '-'}")
    print(f"  Sortino   {ratios.get('sortino') if ratios.get('sortino') is not None else '-'}")
    print(f"  MaxDD     {max_dd_pct:.1f}%")
    print(f"  Final     ${final_equity:,.2f}")
    print(f"  PnL       ${pnl:+,.2f}")
    print(f"  json      {out}")
    print(f"\n{SEP}\n  output  |  {RUN_DIR}/\n{SEP}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
