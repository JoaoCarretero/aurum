"""Structural adherence: scan(live_mode=True) must emit the same signal
as scan(live_mode=False) for the same candle.

Guarantees: if a candle N in the full backtest scan produces a trade,
then running the same scan on df[:N+2] with live_mode=True (the path
shadow/paper take in production) also produces the trade with identical
direction, entry, stop, target, and feature values (entropy_norm, etc).

Without this guarantee any live runner's "missed" signal could be caused
by the scanner itself diverging between modes — which would be a latent
bug much worse than a tick-cadence problem. The 2026-04-24 audit
confirmed the scanner is adherent by hand; this test prevents regression.

Note: uses live Binance data via fetch_all. Skip if no network OR the
API returns empty data. This is intentional — the test measures real
production paths, not synthetic fixtures.
"""
from __future__ import annotations

import contextlib
import io

import pytest

from config.params import BASKETS, ENGINE_BASKETS, ENGINE_INTERVALS, MACRO_SYMBOL
from core.data import fetch_all
from core.portfolio import build_corr_matrix, detect_macro


@contextlib.contextmanager
def _silent():
    with contextlib.redirect_stdout(io.StringIO()):
        yield


def _fetch_context(engine_upper: str):
    tf = ENGINE_INTERVALS.get(engine_upper, "15m")
    basket_name = ENGINE_BASKETS.get(engine_upper, "default")
    basket = BASKETS.get(basket_name, ["BTCUSDT"])
    symbols = list(basket)
    if MACRO_SYMBOL and MACRO_SYMBOL not in symbols:
        symbols.insert(0, MACRO_SYMBOL)
    with _silent():
        dfs = fetch_all(symbols, interval=tf, n_candles=8640)
    if not dfs:
        pytest.skip("fetch_all returned no data (network?)")
    with _silent():
        macro = detect_macro(dfs)
        corr = build_corr_matrix(dfs)
    return dfs, macro, corr, basket


def _assert_signal_adheres(scan_fn, dfs, macro, corr, basket,
                            newest_bt_trade, sym, feature_keys,
                            score_tolerance: float = 0.0):
    """Assert that live_mode=True at cutoff=bar_i+2 re-emits the trade
    backtest-mode produced at that bar, with matching entry/stop/target
    and all feature keys.

    score_tolerance: absolute tolerance for the `score` field (default
    0.0 = exact). Needed for engines where the Bayesian score depends
    on cumulative WIN/LOSS history from earlier bars — live_mode=True
    sees only the tail, so bayes stays at the prior and produces a
    different score than backtest. This is a known gap (see task:
    warm-up bayes in live_mode for full parity).
    """
    bar_i = int(newest_bt_trade["idx"])
    dfs_trunc = {s: d.iloc[:bar_i + 2].reset_index(drop=True)
                  for s, d in dfs.items()}
    df_live = dfs_trunc[sym]
    with _silent():
        m2 = detect_macro(dfs_trunc)
        c2 = build_corr_matrix(dfs_trunc)
        live_trades, live_vetos = scan_fn(
            df_live, sym, m2, c2, None, live_mode=True,
        )
    # Match by (direction, idx) — nearby bars can fire multiple times
    # so picking by direction alone is ambiguous. The newest-bar assertion
    # is that live emits THE SAME bar the backtest picked as newest.
    matching = [t for t in live_trades
                 if t.get("direction") == newest_bt_trade["direction"]
                 and int(t.get("idx") or -1) == bar_i]
    assert matching, (
        f"live_mode=True at cutoff={bar_i+2} emitted {len(live_trades)} "
        f"trades (none matching backtest direction "
        f"{newest_bt_trade['direction']} at idx={bar_i}); "
        f"live_idxs={[t.get('idx') for t in live_trades]}; "
        f"vetos={dict(live_vetos) if live_vetos else {}}"
    )
    lt = matching[0]
    # Core level adherence: entry/stop/target must match exactly — these
    # determine risk and outcome, so any divergence is a real bug.
    for key in ("entry", "stop", "target"):
        assert lt[key] == newest_bt_trade[key], (
            f"{sym} bar {bar_i}: {key} diverges "
            f"live={lt[key]} vs bt={newest_bt_trade[key]}"
        )
    # Feature adherence: non-path-dependent features must match exactly.
    # `score` is path-dependent via Bayesian prior, handled separately.
    for key in feature_keys:
        if key == "score":
            continue
        if key in newest_bt_trade:
            assert lt.get(key) == newest_bt_trade.get(key), (
                f"{sym} bar {bar_i}: {key} diverges "
                f"live={lt.get(key)} vs bt={newest_bt_trade.get(key)}"
            )
    # Score: allow tolerance for Bayes warm-up gap in live_mode.
    if "score" in feature_keys and "score" in newest_bt_trade:
        live_score = float(lt.get("score") or 0)
        bt_score = float(newest_bt_trade.get("score") or 0)
        diff = abs(live_score - bt_score)
        assert diff <= score_tolerance, (
            f"{sym} bar {bar_i}: score diverges more than tolerance "
            f"({score_tolerance}): live={live_score} bt={bt_score} "
            f"diff={diff}"
        )


def test_scan_hermes_adherence_on_newest_signal_per_symbol():
    """RENAISSANCE: pra cada symbol que tem ao menos 1 signal no backtest,
    o último signal deve ser reproduzido pelo scan em live_mode=True.
    """
    from core.harmonics import scan_hermes
    dfs, macro, corr, basket = _fetch_context("RENAISSANCE")
    checked = 0
    for sym in basket:
        df = dfs.get(sym)
        if df is None:
            continue
        with _silent():
            bt_trades, _ = scan_hermes(df, sym, macro, corr, None, live_mode=False)
        if not bt_trades:
            continue
        # Pick newest by idx (bar index) — more robust than lexicographic
        # timestamp comparison (which mis-orders trades with None/NaT ts).
        newest = max(bt_trades, key=lambda t: int(t.get("idx") or 0))
        _assert_signal_adheres(
            scan_hermes, dfs, macro, corr, basket, newest, sym,
            feature_keys=("entropy_norm", "hurst", "score", "pattern"),
            # Bayes score must match exactly: live_mode=True warms up
            # the Bayesian prior by pre-processing all labelable
            # historical patterns before entering the emission loop,
            # so p_win(pat) == backtest p_win(pat) at the tail bar.
            score_tolerance=0.0001,  # float round-trip tolerance
        )
        checked += 1
    assert checked >= 1, "No RENAISSANCE backtest signal found to validate adherence"


def test_scan_mercurio_adherence_on_newest_signal_per_symbol():
    """JUMP: per-symbol newest signal live=backtest adherence."""
    from engines.jump import scan_mercurio
    dfs, macro, corr, basket = _fetch_context("JUMP")
    checked = 0
    for sym in basket:
        df = dfs.get(sym)
        if df is None:
            continue
        with _silent():
            bt_trades, _ = scan_mercurio(df.copy(), sym, macro, corr, None, live_mode=False)
        if not bt_trades:
            continue
        # Pick newest by idx (bar index) — more robust than lexicographic
        # timestamp comparison (which mis-orders trades with None/NaT ts).
        newest = max(bt_trades, key=lambda t: int(t.get("idx") or 0))
        _assert_signal_adheres(
            scan_mercurio, dfs, macro, corr, basket, newest, sym,
            feature_keys=("score",),
            score_tolerance=0.05,
        )
        checked += 1
    if checked == 0:
        pytest.skip("No JUMP backtest signal in current data")


def test_scan_symbol_adherence_on_newest_signal_per_symbol():
    """CITADEL: per-symbol newest signal live=backtest adherence."""
    from engines.citadel import scan_symbol
    dfs, macro, corr, basket = _fetch_context("CITADEL")
    checked = 0
    for sym in basket:
        df = dfs.get(sym)
        if df is None:
            continue
        with _silent():
            bt_trades, _ = scan_symbol(df, sym, macro, corr, None, live_mode=False)
        if not bt_trades:
            continue
        # Pick newest by idx (bar index) — more robust than lexicographic
        # timestamp comparison (which mis-orders trades with None/NaT ts).
        newest = max(bt_trades, key=lambda t: int(t.get("idx") or 0))
        _assert_signal_adheres(
            scan_symbol, dfs, macro, corr, basket, newest, sym,
            feature_keys=("score", "omega_struct", "omega_flow"),
            score_tolerance=0.05,
        )
        checked += 1
    if checked == 0:
        pytest.skip("No CITADEL backtest signal in current data")
