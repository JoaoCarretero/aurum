"""MILLENNIUM battery — runs op=1 (CORE OPERATIONAL) across multiple
windows, captures per-trade lineage + per-strategy metrics + portfolio
metrics, and generates a consolidated comparison report.

Outputs under ``data/millennium/battery_<run_id>/``:
    battery_summary.md      - comparative table (Sharpe, Sortino, ROI, DD, n)
    battery_summary.json    - same data, machine-readable
    battery_trades_all.csv  - every trade across every window + window tag
    w<days>d/
        config.json         - SCAN_DAYS, symbols, account size
        summary.json        - portfolio-level (n, pnl, sharpe, sortino, dd)
        per_strategy.json   - per-engine breakdown
        trades.csv          - one row per trade, full lineage
        trades.jsonl        - same trades as JSONL for tooling
        report.html         - polished AURUM HTML report
        logs/               - multistrategy.log

Usage:
    python tools/batteries/millennium_battery.py
    python tools/batteries/millennium_battery.py --windows 90 180 360 720
    python tools/batteries/millennium_battery.py --windows 180 --account 25000
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Trade fields serialized to CSV. Ordered for readability (identity first,
# then execution, then signal context, then reweight/portfolio diagnostics).
TRADE_CSV_FIELDS = [
    # identity
    "window_days", "run_id", "strategy", "symbol", "direction", "trade_type",
    "timestamp", "entry_idx", "trade_time",
    # execution / risk
    "entry", "stop", "target", "exit_p", "exit_reason", "duration",
    "size", "pnl", "pnl_pre_ensemble", "r_multiple", "rr", "result",
    # signal / scoring
    "score", "fractal_align",
    "omega_struct", "omega_flow", "omega_cascade", "omega_momentum", "omega_pullback",
    "rsi", "taker_ma", "dist_ema21", "chop_trade", "struct", "struct_str",
    # macro / regime
    "macro_bias", "vol_regime", "regime_at_trade",
    "hmm_regime", "hmm_confidence", "hmm_prob_bull", "hmm_prob_bear", "hmm_prob_chop",
    # sentiment
    "funding_z", "oi_signal", "ls_signal", "sentiment",
    # reweight / portfolio
    "dd_scale", "corr_mult", "in_transition", "trans_mult",
    "ensemble_w", "recent_drawdown_r",
    "portfolio_gate", "portfolio_leader", "portfolio_leader_w",
    "portfolio_weight_gap", "portfolio_bars_since_trade",
    "portfolio_bars_since_strategy",
]


def _get(d: dict, key: str, default=""):
    v = d.get(key, default)
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return ""
    return v


def _register_window_run(
    *,
    battery_root: Path,
    window_dir: Path,
    days: int,
    summary: dict,
    config: dict,
) -> None:
    from core.ops.run_manager import append_to_index

    battery_id = battery_root.name.replace("battery_", "", 1)
    run_id = f"millennium_battery_{battery_id}_w{days}d"
    summary_path = window_dir / "summary.json"
    config_path = window_dir / "config.json"
    report_html = window_dir / "report.html"
    interval_minutes = int(config.get("interval_minutes") or 15)
    report_json = window_dir / _report_json_name(days, interval_minutes)

    append_to_index(
        window_dir,
        summary=summary,
        config=config,
        entry_overrides={
            "run_id": run_id,
            "engine": "millennium",
            "interval": config.get("INTERVAL"),
            "period_days": days,
            "n_symbols": len(config.get("symbols") or []),
            "n_candles": config.get("N_CANDLES"),
            "win_rate": summary.get("win_rate_pct"),
            "pnl": summary.get("total_pnl"),
            "roi_pct": summary.get("roi_pct"),
            "sharpe": summary.get("sharpe"),
            "sortino": summary.get("sortino"),
            "calmar": summary.get("calmar"),
            "max_dd_pct": summary.get("max_dd_pct"),
            "run_dir": str(window_dir),
            "summary_path": str(summary_path),
            "config_path": str(config_path),
            "report_html_path": str(report_html) if report_html.exists() else "",
            "report_json_path": str(report_json) if report_json.exists() else "",
            "source": "millennium_battery",
        },
    )


def _report_json_name(days: int, interval_minutes: int) -> str:
    return f"millennium_{interval_minutes}m_{days}d.json"


def _write_report_json(
    *,
    window_dir: Path,
    days: int,
    interval_minutes: int,
    account_size: float,
    trades: list[dict],
    summary: dict,
    per_strat: dict,
    config_payload: dict,
) -> Path:
    """Emit canonical report JSON consumed by the launcher METRICS tab.

    Schema matches what ``_show_results`` / ``_normalize_summary`` expect:
    flat ``summary`` block, ``trades`` list, ``equity`` curve, empty
    ``monte_carlo`` / ``bear_market`` placeholders, plus the battery-specific
    ``per_strategy`` and ``config`` for reference.
    """
    closed = [t for t in trades if t.get("result") in ("WIN", "LOSS")]
    ordered = sorted(closed, key=lambda t: t.get("timestamp", ""))
    equity = [account_size]
    acct = account_size
    for t in ordered:
        acct += float(t.get("pnl", 0.0) or 0.0)
        equity.append(round(acct, 2))

    payload = {
        "version": "millennium_battery_v1",
        "run_id": f"millennium_battery_w{days}d",
        "engine": "MILLENNIUM",
        "config": config_payload,
        "summary": summary,
        "per_strategy": per_strat,
        "monte_carlo": {},
        "bear_market": {},
        "hmm_regime_analysis": {},
        "trades": [
            {k: (str(v) if k == "timestamp" else v) for k, v in t.items()}
            for t in trades
        ],
        "equity": equity,
        "account_size": account_size,
        "final_equity": equity[-1] if equity else account_size,
        # Top-level aliases for launcher `_normalize_summary` (it scans
        # data[src] at top level, not inside data["summary"]).
        "total_pnl": summary.get("total_pnl"),
        "pnl": summary.get("total_pnl"),
        "roi_pct": summary.get("roi_pct"),
        "ret": summary.get("roi_pct"),
        "sharpe": summary.get("sharpe"),
        "sortino": summary.get("sortino"),
        "calmar": summary.get("calmar"),
        "max_dd_pct": summary.get("max_dd_pct"),
        "n_trades": summary.get("n_trades"),
        "win_rate": summary.get("win_rate_pct"),
    }

    path = window_dir / _report_json_name(days, interval_minutes)
    path.write_text(
        json.dumps(payload, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _write_trades(trades: list[dict], run_id: str, window_days: int,
                  out_dir: Path) -> None:
    """Write trades to both CSV (Excel-friendly) and JSONL (tool-friendly)."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # JSONL — full fidelity, one trade per line
    with open(out_dir / "trades.jsonl", "w", encoding="utf-8") as f:
        for t in trades:
            f.write(json.dumps(t, default=str) + "\n")

    # CSV — curated columns, sorted by timestamp
    ordered = sorted(trades, key=lambda t: t.get("timestamp", ""))
    with open(out_dir / "trades.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(TRADE_CSV_FIELDS)
        for t in ordered:
            enriched = {**t, "window_days": window_days, "run_id": run_id}
            w.writerow([_get(enriched, k) for k in TRADE_CSV_FIELDS])


def _per_strategy(trades: list[dict]) -> dict:
    """Aggregate by engine: n, wins, losses, WR, PnL, Sharpe-like ratio,
    avg R-multiple, max consecutive losses."""
    from collections import defaultdict
    buckets: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        if t.get("result") in ("WIN", "LOSS"):
            buckets[t.get("strategy", "UNKNOWN")].append(t)

    out = {}
    for strat, ts in buckets.items():
        if not ts:
            continue
        n = len(ts)
        wins = sum(1 for t in ts if t["result"] == "WIN")
        losses = n - wins
        pnl = sum(t.get("pnl", 0.0) for t in ts)
        rms = [t.get("r_multiple", 0.0) or 0.0 for t in ts]
        avg_rm = sum(rms) / len(rms) if rms else 0.0
        # max consecutive losses
        max_streak, cur = 0, 0
        for t in sorted(ts, key=lambda x: x.get("timestamp", "")):
            if t["result"] == "LOSS":
                cur += 1; max_streak = max(max_streak, cur)
            else:
                cur = 0
        # by direction
        longs = sum(1 for t in ts if t.get("direction") == "BULLISH")
        shorts = n - longs
        out[strat] = {
            "n": n,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(wins / n * 100, 2),
            "longs": longs,
            "shorts": shorts,
            "total_pnl": round(pnl, 2),
            "avg_pnl_per_trade": round(pnl / n, 2),
            "avg_r_multiple": round(avg_rm, 3),
            "max_consec_losses": max_streak,
        }
    return out


def _portfolio_summary(trades: list[dict], days: int, account_size: float) -> dict:
    from analysis.stats import equity_stats, calc_ratios
    closed = [t for t in trades if t.get("result") in ("WIN", "LOSS")]
    if not closed:
        return {"n_trades": 0, "note": "no closed trades"}
    closed.sort(key=lambda t: t.get("timestamp", ""))
    pnl_s = [t["pnl"] for t in closed]
    eq, mdd, mdd_pct, max_streak = equity_stats(pnl_s)
    ratios = calc_ratios(pnl_s, n_days=days)
    wins = sum(1 for t in closed if t["result"] == "WIN")

    return {
        "n_trades": len(closed),
        "wins": wins,
        "losses": len(closed) - wins,
        "win_rate_pct": round(wins / len(closed) * 100, 2),
        "total_pnl": round(sum(pnl_s), 2),
        "account_start": account_size,
        "final_equity": round(account_size + sum(pnl_s), 2),
        "roi_pct": round(sum(pnl_s) / account_size * 100, 2),
        "sharpe": ratios.get("sharpe"),
        "sharpe_daily": ratios.get("sharpe_daily"),
        "sortino": ratios.get("sortino"),
        "calmar": ratios.get("calmar"),
        "max_dd_pct": round(mdd_pct, 2),
        "max_consec_losses": max_streak,
        "period_days": days,
    }


def _fmt_metric(v, fmt: str = "{:.2f}", dash: str = "—") -> str:
    if v is None:
        return dash
    try:
        return fmt.format(v)
    except (TypeError, ValueError):
        return str(v)


def _print_window_metrics(days: int, summary: dict, per_strat: dict, dt: float) -> None:
    """Print all portfolio metrics + per-engine breakdown to stdout."""
    print(f"\n  {'─'*70}")
    print(f"  [w{days}d] PORTFOLIO  ·  {summary['n_trades']} trades  ·  {dt:.1f}s")
    print(f"  {'─'*70}")
    print(
        f"    WR        {_fmt_metric(summary.get('win_rate_pct'), '{:.2f}%'):>10}"
        f"    ROI       {_fmt_metric(summary.get('roi_pct'), '{:.2f}%'):>10}"
        f"    PnL       ${_fmt_metric(summary.get('total_pnl'), '{:,.2f}'):>10}"
    )
    print(
        f"    Sharpe    {_fmt_metric(summary.get('sharpe')):>10}"
        f"    Sortino   {_fmt_metric(summary.get('sortino')):>10}"
        f"    Calmar    {_fmt_metric(summary.get('calmar')):>10}"
    )
    print(
        f"    MaxDD     {_fmt_metric(summary.get('max_dd_pct'), '{:.2f}%'):>10}"
        f"    SharpeD   {_fmt_metric(summary.get('sharpe_daily')):>10}"
        f"    MaxStreak {str(summary.get('max_consec_losses', '—')):>10}"
    )
    if per_strat:
        print(f"\n    Per-engine:")
        print(
            f"      {'Engine':<14} {'n':>5} {'WR%':>7} {'L/S':>10} "
            f"{'PnL':>10} {'AvgR':>7} {'Streak':>7}"
        )
        print(f"      {'-'*62}")
        for eng, s in per_strat.items():
            ls = f"{s.get('longs', 0)}L/{s.get('shorts', 0)}S"
            print(
                f"      {eng:<14} {s.get('n', 0):>5} "
                f"{_fmt_metric(s.get('win_rate_pct'), '{:.2f}'):>7} {ls:>10} "
                f"${_fmt_metric(s.get('total_pnl'), '{:,.0f}'):>9} "
                f"{_fmt_metric(s.get('avg_r_multiple'), '{:.3f}'):>7} "
                f"{s.get('max_consec_losses', 0):>7}"
            )
    print()


def _print_battery_summary(results: list[dict]) -> None:
    """Reprint markdown summary table to stdout at end of battery."""
    print(f"\n{'#'*72}")
    print(f"#  MILLENNIUM BATTERY — CONSOLIDATED METRICS")
    print(f"{'#'*72}")
    print(
        f"  {'Window':>8} {'Trades':>7} {'WR%':>7} {'ROI%':>8} "
        f"{'Sharpe':>8} {'Sortino':>8} {'Calmar':>8} {'MaxDD%':>8} {'PnL':>12}"
    )
    print(f"  {'-'*85}")
    for r in results:
        if r.get("n_trades", 0) == 0:
            print(f"  {r['window_days']:>7}d  (sem trades)")
            continue
        print(
            f"  {r['window_days']:>7}d "
            f"{r.get('n_trades', 0):>7} "
            f"{_fmt_metric(r.get('win_rate_pct'), '{:.2f}'):>7} "
            f"{_fmt_metric(r.get('roi_pct'), '{:.2f}'):>8} "
            f"{_fmt_metric(r.get('sharpe')):>8} "
            f"{_fmt_metric(r.get('sortino')):>8} "
            f"{_fmt_metric(r.get('calmar')):>8} "
            f"{_fmt_metric(r.get('max_dd_pct'), '{:.2f}'):>8} "
            f"${_fmt_metric(r.get('total_pnl'), '{:,.0f}'):>11}"
        )
    print()


def _write_html_report(trades: list[dict], summary: dict, by_strategy: dict,
                       window_dir: Path, engine_label: str,
                       account_size: float) -> None:
    """Generate polished AURUM HTML report for this window."""
    from analysis.report_html import generate_report
    closed = [t for t in trades if t.get("result") in ("WIN", "LOSS")]

    # Equity curve
    account = account_size
    equity = [account]
    for t in sorted(closed, key=lambda x: x.get("timestamp", "")):
        account += t["pnl"]
        equity.append(round(account, 2))

    from collections import defaultdict
    by_sym = defaultdict(list)
    for t in trades:
        by_sym[t.get("symbol", "UNKNOWN")].append(t)

    ratios = {
        "ret": summary.get("roi_pct", 0.0) or 0.0,
        "sharpe": summary.get("sharpe"),
        "sharpe_daily": summary.get("sharpe_daily"),
        "sortino": summary.get("sortino"),
        "calmar": summary.get("calmar"),
        "max_consec_losses": summary.get("max_consec_losses"),
    }
    mdd_pct = summary.get("max_dd_pct", 0.0) or 0.0

    config_dict = {
        "ENGINE": engine_label,
        "SCAN_DAYS": summary.get("period_days"),
        "ACCOUNT_SIZE": account_size,
        "N_TRADES": summary.get("n_trades"),
    }

    generate_report(
        all_trades=trades, eq=equity, mc={}, cond={}, ratios=ratios,
        mdd_pct=mdd_pct, wf=[], wf_regime={}, by_sym=dict(by_sym),
        all_vetos={}, run_dir=window_dir, config_dict=config_dict,
        engine_name=engine_label,
    )


def _reset_millennium_globals(days: int, interval_minutes: int = 15) -> None:
    """Mutate millennium + citadel module globals for the target window.

    Mirrors what MILLENNIUM's interactive ``_ask_periodo`` does, but
    programmatic and idempotent.
    """
    import engines.millennium as ms
    from engines import citadel as _bt
    bars_per_day = int(24 * 60 / interval_minutes)  # 15m → 96, 1h → 24
    n_candles = days * bars_per_day
    htf_map = {"1h": days * 24 + 200, "4h": days * 6 + 100, "1d": days + 100}
    ms.SCAN_DAYS = days
    ms.N_CANDLES = n_candles
    ms.HTF_N_CANDLES_MAP = htf_map
    _bt.SCAN_DAYS = days
    _bt.N_CANDLES = n_candles
    _bt.HTF_N_CANDLES_MAP = htf_map


def _run_window(days: int, battery_root: Path, account_size: float,
                 interval_minutes: int = 15) -> dict:
    """Run MILLENNIUM op=1 for a single window. Return summary dict."""
    import engines.millennium as ms

    window_dir = battery_root / f"w{days}d"
    window_dir.mkdir(parents=True, exist_ok=True)
    (window_dir / "logs").mkdir(exist_ok=True)

    # Per-window log handler — fresh file per window, no stacking
    _win_log = window_dir / "logs" / "multistrategy.log"
    fh = logging.FileHandler(_win_log, encoding="utf-8", mode="w")
    fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
    ms.log.addHandler(fh)
    try:
        print(f"\n{'='*72}")
        print(f"  MILLENNIUM BATTERY  ·  window = {days}d  ·  output: {window_dir}")
        print(f"{'='*72}")
        t0 = time.time()

        _reset_millennium_globals(days, interval_minutes=interval_minutes)

        # Point MS_RUN_DIR at the battery window dir so MILLENNIUM's own
        # index.json / DB writes land inside the battery output tree.
        ms.MS_RUN_DIR = window_dir
        ms.RUN_ID = f"battery_w{days}d"

        ms.log.info(f"BATTERY window={days}d  account=${account_size:,.0f}  start")

        engine_contexts = ms._load_operational_contexts()
        _, all_trades = ms._collect_operational_trades(engine_contexts=engine_contexts)
        if not all_trades:
            print(f"  [w{days}d] sem trades — skip")
            return {"window_days": days, "n_trades": 0, "status": "no_trades"}

        portfolio_trades = ms.operational_core_reweight(all_trades)

        summary = _portfolio_summary(portfolio_trades, days, account_size)
        summary["engine"] = "MILLENNIUM"
        per_strat = _per_strategy(portfolio_trades)
        config_payload = {
            "window_days": days,
            "SCAN_DAYS": days,
            "INTERVAL": f"{interval_minutes}m",
            "N_CANDLES": int(getattr(ms, "N_CANDLES", 0) or 0),
            "interval_minutes": interval_minutes,
            "native_intervals": dict(getattr(ms, "ENGINE_NATIVE_INTERVALS", {})),
            "symbols": list(getattr(ms, "SYMBOLS", [])),
            "account_size": account_size,
            "base_weights": dict(ms.BASE_CAPITAL_WEIGHTS),
            "timestamp": datetime.now().isoformat(),
        }

        # Persist
        (window_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, default=str), encoding="utf-8"
        )
        (window_dir / "per_strategy.json").write_text(
            json.dumps(per_strat, indent=2, default=str), encoding="utf-8"
        )
        (window_dir / "config.json").write_text(
            json.dumps(config_payload, indent=2, default=str),
            encoding="utf-8",
        )

        _write_trades(portfolio_trades, ms.RUN_ID, days, window_dir)

        # Canonical engine report JSON — picked up by launcher METRICS button.
        # Schema mirrors CITADEL (config/summary/trades/equity/monte_carlo/...) so
        # _show_results can render the overview tab without format branching.
        _write_report_json(
            window_dir=window_dir,
            days=days,
            interval_minutes=interval_minutes,
            account_size=account_size,
            trades=portfolio_trades,
            summary=summary,
            per_strat=per_strat,
            config_payload=config_payload,
        )

        try:
            _write_html_report(
                portfolio_trades, summary, per_strat,
                window_dir, f"MILLENNIUM · {days}d", account_size,
            )
        except Exception as e:
            print(f"  [w{days}d] report.html falhou: {e}")
            ms.log.warning(f"HTML report failed: {e}")

        _register_window_run(
            battery_root=battery_root,
            window_dir=window_dir,
            days=days,
            summary=summary,
            config=config_payload,
        )

        dt = time.time() - t0
        _print_window_metrics(days, summary, per_strat, dt)

        return {"window_days": days, **summary, "per_strategy": per_strat}
    finally:
        ms.log.removeHandler(fh)
        fh.close()


def _write_battery_summary(results: list[dict], battery_root: Path,
                            account_size: float) -> None:
    """Write markdown + json comparison across windows."""
    import engines.millennium as _ms
    weights_str = " · ".join(
        f"{eng} ({_ms.BASE_CAPITAL_WEIGHTS[eng]})"
        for eng in _ms.OPERATIONAL_ENGINES
    )

    (battery_root / "battery_summary.json").write_text(
        json.dumps({
            "run_at": datetime.now().isoformat(),
            "account_size": account_size,
            "operational_engines": list(_ms.OPERATIONAL_ENGINES),
            "base_weights": dict(_ms.BASE_CAPITAL_WEIGHTS),
            "results": results,
        }, indent=2, default=str),
        encoding="utf-8",
    )

    lines = []
    lines.append(f"# MILLENNIUM Battery — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    lines.append(f"**Account:** ${account_size:,.0f} · **Engine:** MILLENNIUM op=1 (CORE OPERATIONAL)\n")
    lines.append(f"**Sub-engines:** {weights_str}\n")

    lines.append("\n## Portfolio metrics per window\n")
    lines.append("| Window | Trades | WR% | ROI% | Sharpe | Sortino | Calmar | MaxDD% | PnL |")
    lines.append("|-------:|-------:|----:|-----:|-------:|--------:|-------:|-------:|----:|")
    for r in results:
        if r.get("n_trades", 0) == 0:
            lines.append(f"| {r['window_days']}d | — | — | — | — | — | — | — | — |")
            continue
        lines.append(
            f"| {r['window_days']}d | {r.get('n_trades')} | "
            f"{r.get('win_rate_pct', '—')} | {r.get('roi_pct', '—')} | "
            f"{r.get('sharpe', '—')} | {r.get('sortino', '—')} | "
            f"{r.get('calmar', '—')} | {r.get('max_dd_pct', '—')} | "
            f"${r.get('total_pnl', 0):,.0f} |"
        )

    lines.append("\n## Per-strategy breakdown\n")
    for r in results:
        if r.get("n_trades", 0) == 0:
            continue
        lines.append(f"\n### Window {r['window_days']}d\n")
        lines.append("| Engine | n | WR% | L/S | PnL | Avg R | MaxStreak |")
        lines.append("|--------|--:|----:|:---:|----:|------:|----------:|")
        per = r.get("per_strategy", {})
        for eng in _ms.OPERATIONAL_ENGINES:
            s = per.get(eng)
            if not s:
                lines.append(f"| {eng} | 0 | — | — | — | — | — |")
                continue
            lines.append(
                f"| {eng} | {s['n']} | {s['win_rate_pct']} | "
                f"{s['longs']}L/{s['shorts']}S | ${s['total_pnl']:,.0f} | "
                f"{s['avg_r_multiple']} | {s['max_consec_losses']} |"
            )

    lines.append("\n## Artifacts\n")
    for r in results:
        d = r["window_days"]
        lines.append(
            f"- **{d}d**: [trades.csv](w{d}d/trades.csv) · "
            f"[trades.jsonl](w{d}d/trades.jsonl) · "
            f"[summary.json](w{d}d/summary.json) · "
            f"[per_strategy.json](w{d}d/per_strategy.json) · "
            f"[report.html](w{d}d/report.html)"
        )

    (battery_root / "battery_summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _write_all_trades_csv(battery_root: Path) -> None:
    """Merge trades.csv from every window into one file with window column."""
    out = battery_root / "battery_trades_all.csv"
    with open(out, "w", encoding="utf-8", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(TRADE_CSV_FIELDS)
        for sub in sorted(battery_root.glob("w*d")):
            f = sub / "trades.csv"
            if not f.exists():
                continue
            with open(f, "r", encoding="utf-8", newline="") as fi:
                r = csv.reader(fi)
                header = next(r, None)
                if header is None:
                    continue
                for row in r:
                    w.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser(description="MILLENNIUM battery runner")
    ap.add_argument("--windows", nargs="+", type=int, default=[90, 180, 360],
                    help="Scan windows in days (default: 90 180 360)")
    ap.add_argument("--account", type=float, default=None,
                    help="Account size override (default: ACCOUNT_SIZE from params.py)")
    ap.add_argument("--interval-minutes", type=int, default=15,
                    help="Bars/day inferred from this (default: 15m)")
    ap.add_argument("--output-root", type=str, default=None,
                    help="Override battery root dir")
    args = ap.parse_args()

    # Battery run_id + output root
    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    battery_root = Path(args.output_root) if args.output_root else (
        ROOT / "data" / "millennium" / f"battery_{ts}"
    )
    battery_root.mkdir(parents=True, exist_ok=True)

    from config.params import ACCOUNT_SIZE
    account_size = args.account if args.account is not None else ACCOUNT_SIZE

    print(f"\n{'#'*72}")
    print(f"#  MILLENNIUM BATTERY")
    print(f"#  windows: {args.windows}  ·  account: ${account_size:,.0f}")
    print(f"#  output:  {battery_root}")
    print(f"{'#'*72}")

    results: list[dict] = []
    for days in args.windows:
        try:
            r = _run_window(days, battery_root, account_size,
                             interval_minutes=args.interval_minutes)
            results.append(r)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  [w{days}d] FALHOU: {e}")
            results.append({"window_days": days, "status": "error", "error": str(e)})

    _write_battery_summary(results, battery_root, account_size)
    _write_all_trades_csv(battery_root)

    _print_battery_summary(results)

    print(f"{'#'*72}")
    print(f"#  BATTERY COMPLETE")
    print(f"#  summary: {battery_root / 'battery_summary.md'}")
    print(f"{'#'*72}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
