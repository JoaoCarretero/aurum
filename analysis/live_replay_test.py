"""
☿ AURUM Finance — Live replay test
===================================
Feeds historical candles through LiveEngine.on_candle_close() and compares
the resulting trades to what engines.citadel.scan_symbol() produces on the
same data. Use this to verify backtest/live parity after changes to either.

Known caveat:
  backtest.scan_symbol() applies portfolio/max-position constraints PER SYMBOL
  (each symbol has its own local open-position list), while LiveEngine applies
  them GLOBALLY across all symbols. In windows where many symbols fire at once
  live will open fewer trades than backtest. The script reports this as
  "concurrency skew" at the end of the diff.

Usage:
  python analysis/live_replay_test.py --days 30
  python analysis/live_replay_test.py --days 14 --symbols BTCUSDT,ETHUSDT
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd  # noqa: E402

from config.params import SYMBOLS, MACRO_SYMBOL  # noqa: E402
from core.data import fetch_all, validate  # noqa: E402
from core.risk.portfolio import detect_macro, build_corr_matrix  # noqa: E402
from engines import citadel as bt_module  # noqa: E402
from engines.live import LiveEngine  # noqa: E402


class _NullTelegram:
    """Drop-in replacement for TelegramNotifier — all notifications are no-ops."""
    async def notify_open(self, *a, **k): pass
    async def notify_close(self, *a, **k): pass
    async def notify_killswitch(self, *a, **k): pass
    async def notify_startup(self, *a, **k): pass
    async def notify_shutdown(self, *a, **k): pass


class ReplayEngine(LiveEngine):
    """LiveEngine subclass that strips out side effects (telegram, state files, logs)."""

    def __init__(self):
        super().__init__()
        self.telegram = _NullTelegram()

    def _save_state(self):  # override: no disk writes
        pass

    def _heartbeat(self):   # override: keep stdout clean
        pass


# ── BACKTEST PHASE ───────────────────────────────────────────
def run_backtest(all_dfs: dict, syms: list[str]) -> list[dict]:
    macro = detect_macro(all_dfs)
    corr  = build_corr_matrix(all_dfs)
    out: list[dict] = []
    for sym in syms:
        df = all_dfs.get(sym)
        if df is None:
            continue
        trades, _ = bt_module.scan_symbol(df, sym, macro, corr)
        out.extend(trades)
    return [t for t in out if t.get("result") in ("WIN", "LOSS")]


# ── LIVE REPLAY PHASE ────────────────────────────────────────
async def run_replay(all_dfs: dict, warmup: int = 300) -> list[dict]:
    engine = ReplayEngine()

    # Prime macro/corr from the warmup slice so first signals have a baseline.
    warm_dfs = {sym: df.iloc[:warmup].copy() for sym, df in all_dfs.items() if len(df) > warmup}
    engine.macro_series = detect_macro(warm_dfs)
    engine.corr         = build_corr_matrix(warm_dfs)
    for sym, wdf in warm_dfs.items():
        engine.buffer.seed(sym, wdf)

    # Determine the longest shared history and iterate forward.
    max_len = max(len(df) for df in all_dfs.values())
    # Macro first so detect_macro() inside on_candle_close sees fresh BTC state.
    ordered = [MACRO_SYMBOL] + [s for s in all_dfs if s != MACRO_SYMBOL]

    for i in range(warmup, max_len):
        for sym in ordered:
            df = all_dfs.get(sym)
            if df is None or i >= len(df):
                continue
            candle = {
                "time":  df["time"].iloc[i],
                "open":  float(df["open"].iloc[i]),
                "high":  float(df["high"].iloc[i]),
                "low":   float(df["low"].iloc[i]),
                "close": float(df["close"].iloc[i]),
                "vol":   float(df["vol"].iloc[i])  if "vol"  in df.columns else 0.0,
                "tbb":   float(df["tbb"].iloc[i])  if "tbb"  in df.columns else 0.0,
            }
            await engine.on_candle_close(sym, candle)

    return engine.closed_trades


# ── DIFF ─────────────────────────────────────────────────────
def _key(symbol: str, direction: str, entry: float) -> tuple:
    return (symbol, direction, round(float(entry), 6))


def diff_trades(bt_trades: list[dict], lv_trades: list[dict],
                entry_tol: float = 1e-4, pnl_tol: float = 0.50):
    bt_by: dict[tuple, list[dict]] = {}
    for t in bt_trades:
        bt_by.setdefault(_key(t["symbol"], t["direction"], t["entry"]), []).append(t)
    lv_by: dict[tuple, list[dict]] = {}
    for t in lv_trades:
        lv_by.setdefault(_key(t["symbol"], t["direction"], t["entry"]), []).append(t)

    only_bt: list[dict] = []
    only_lv: list[dict] = []
    mismatches: list[tuple[dict, dict, dict]] = []
    matched = 0

    for k, bts in bt_by.items():
        lvs = lv_by.get(k, [])
        for i, bt in enumerate(bts):
            if i < len(lvs):
                lv = lvs[i]
                matched += 1
                bt_exit = float(bt.get("exit_p", bt.get("exit", 0)))
                lv_exit = float(lv.get("exit",  lv.get("exit_p", 0)))
                bt_pnl  = float(bt["pnl"])
                lv_pnl  = float(lv["pnl"])
                entry_d = abs(float(bt["entry"]) - float(lv["entry"]))
                exit_d  = abs(bt_exit - lv_exit)
                pnl_d   = abs(bt_pnl - lv_pnl)
                if entry_d > entry_tol or exit_d > entry_tol or pnl_d > pnl_tol:
                    mismatches.append({
                        "key": k, "bt": bt, "lv": lv,
                        "entry_diff": entry_d, "exit_diff": exit_d, "pnl_diff": pnl_d,
                    })
            else:
                only_bt.append(bt)

    for k, lvs in lv_by.items():
        bts = bt_by.get(k, [])
        if len(lvs) > len(bts):
            only_lv.extend(lvs[len(bts):])

    return {
        "matched":    matched,
        "only_bt":    only_bt,
        "only_lv":    only_lv,
        "mismatches": mismatches,
    }


def print_report(bt_trades: list[dict], lv_trades: list[dict], d: dict) -> None:
    sep = "─" * 72
    print(f"\n{sep}")
    print(f"  BACKTEST vs LIVE REPLAY — PARITY REPORT")
    print(sep)
    print(f"  backtest trades : {len(bt_trades)}")
    print(f"  live trades     : {len(lv_trades)}")
    print(f"  matched         : {d['matched']}")
    print(f"  only backtest   : {len(d['only_bt'])}")
    print(f"  only live       : {len(d['only_lv'])}")
    print(f"  mismatches      : {len(d['mismatches'])}")

    if d["only_bt"]:
        print(f"\n  --- Only in backtest (top 10) ---")
        for t in d["only_bt"][:10]:
            print(f"    {t['symbol']:12s} {t['direction']:8s} "
                  f"entry={float(t['entry']):.6f} "
                  f"pnl={float(t['pnl']):+.2f} "
                  f"t={t.get('time','?')}")

    if d["only_lv"]:
        print(f"\n  --- Only in live replay (top 10) ---")
        for t in d["only_lv"][:10]:
            print(f"    {t['symbol']:12s} {t['direction']:8s} "
                  f"entry={float(t['entry']):.6f} "
                  f"pnl={float(t['pnl']):+.2f} "
                  f"open_ts={t.get('open_ts','?')}")

    if d["mismatches"]:
        print(f"\n  --- Matched trades with diff (top 10) ---")
        for m in d["mismatches"][:10]:
            k = m["key"]
            print(f"    {k[0]:12s} {k[1]:8s}  entry={k[2]:.6f}")
            print(f"       entry_diff={m['entry_diff']:.6f}  "
                  f"exit_diff={m['exit_diff']:.6f}  "
                  f"pnl_diff={m['pnl_diff']:.2f}")
            print(f"       bt: exit={float(m['bt'].get('exit_p',0)):.6f} pnl={float(m['bt']['pnl']):+.2f}")
            print(f"       lv: exit={float(m['lv'].get('exit',0)):.6f} pnl={float(m['lv']['pnl']):+.2f}")

    skew = len(d["only_bt"]) - len(d["only_lv"])
    print(f"\n  concurrency skew (bt - lv) = {skew:+d}")
    print(f"  (positive means backtest took trades live skipped due to MAX_OPEN_POSITIONS)")
    print(sep)


# ── MAIN ─────────────────────────────────────────────────────
async def _main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days",    type=int, default=14,
                    help="Days of 15m history to fetch (default 14)")
    ap.add_argument("--symbols", type=str, default=None,
                    help="Comma-separated symbol list (default: first 4 of SYMBOLS)")
    ap.add_argument("--warmup",  type=int, default=300,
                    help="Warmup candles before replay begins (default 300)")
    args = ap.parse_args()

    syms = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else SYMBOLS[:4]
    fetch_syms = list(syms)
    if MACRO_SYMBOL not in fetch_syms:
        fetch_syms.insert(0, MACRO_SYMBOL)

    n_candles = args.days * 24 * 4
    print(f"  fetching {n_candles} candles for {len(fetch_syms)} symbols...")
    all_dfs = fetch_all(fetch_syms, n_candles=n_candles, futures=True)
    for sym, df in all_dfs.items():
        validate(df, sym)

    if not all_dfs:
        print("  no data — aborting.")
        return 1

    print(f"  running backtest on {len(syms)} symbols...")
    bt_trades = run_backtest(all_dfs, syms)
    print(f"    {len(bt_trades)} backtest trades")

    print(f"  replaying through LiveEngine (warmup={args.warmup})...")
    lv_trades = await run_replay(all_dfs, warmup=args.warmup)
    print(f"    {len(lv_trades)} live replay trades")

    report = diff_trades(bt_trades, lv_trades)
    print_report(bt_trades, lv_trades, report)

    if report["only_bt"] or report["only_lv"] or report["mismatches"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
