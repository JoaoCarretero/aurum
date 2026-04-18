"""BRIDGEWATER channel-ablation battery.

Compare the current full thesis (funding + OI + LS) against the amputated
variant (funding + LS) on the exact same market/sentiment window.

The goal is diagnostic, not promotional: quantify whether OI contributes real
edge or merely adds noise. The script fetches OHLCV and sentiment once, then
runs both variants over the same symbol set. Output includes:
  - overall summary + overfit score
  - per-symbol breakdown
  - per-macro and per-HMM regime breakdown
  - sentiment-channel diagnostics
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent


def _resolve_bridgewater_module():
    import engines.bridgewater as bw

    return bw


def _parse_symbols_arg(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    symbols: list[str] = []
    for token in raw.split(","):
        sym = token.strip().upper()
        if not sym:
            continue
        if not sym.endswith("USDT"):
            sym += "USDT"
        symbols.append(sym)
    return symbols or None


def _resolve_symbols(bw, basket: str | None, symbols_raw: str | None) -> tuple[str, list[str]]:
    from config.params import BASKETS, ENGINE_BASKETS

    symbols_override = _parse_symbols_arg(symbols_raw)
    basket_name = "custom" if symbols_override else (basket or ENGINE_BASKETS.get("BRIDGEWATER", "default"))
    if symbols_override:
        return basket_name, symbols_override
    return basket_name, list(BASKETS[basket_name])


def _trade_summary(closed: list[dict], account_size: float, scan_days: int, calc_ratios, equity_stats) -> dict:
    pnl_list = [float(t.get("pnl", 0.0) or 0.0) for t in closed]
    eq, _mdd_abs, mdd_pct, _max_streak = equity_stats(pnl_list)
    ratios = calc_ratios(pnl_list, n_days=scan_days)
    wins = sum(1 for t in closed if t.get("result") == "WIN")
    return {
        "n_trades": len(closed),
        "win_rate": round((wins / max(len(closed), 1)) * 100, 2),
        "pnl": round(sum(pnl_list), 2),
        "roi_pct": round(float(ratios.get("ret") or 0.0), 2),
        "sharpe": ratios.get("sharpe"),
        "sortino": ratios.get("sortino"),
        "calmar": ratios.get("calmar"),
        "max_dd_pct": round(float(mdd_pct or 0.0), 2),
        "final_equity": round(eq[-1], 2) if eq else round(float(account_size), 2),
    }


def _aggregate_bucket(trades: list[dict], key: str) -> dict[str, dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for trade in trades:
        raw = trade.get(key)
        label = "UNKNOWN" if raw in (None, "", "nan") else str(raw)
        buckets[label].append(trade)

    out: dict[str, dict] = {}
    for label, rows in sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        wins = sum(1 for t in rows if t.get("result") == "WIN")
        pnl = sum(float(t.get("pnl", 0.0) or 0.0) for t in rows)
        avg_r = sum(float(t.get("r_multiple", 0.0) or 0.0) for t in rows) / max(len(rows), 1)
        out[label] = {
            "n": len(rows),
            "win_rate": round((wins / max(len(rows), 1)) * 100, 2),
            "pnl": round(pnl, 2),
            "avg_r": round(avg_r, 3),
        }
    return out


def _per_symbol(trades: list[dict]) -> dict[str, dict]:
    return _aggregate_bucket(trades, "symbol")


def _normalize_overfit(audit_results: dict | None) -> dict | None:
    if not audit_results:
        return None
    return {
        "passed": audit_results.get("passed"),
        "warnings": audit_results.get("warnings"),
        "failed": audit_results.get("failed"),
        "tests": {
            name: rec.get("status")
            for name, rec in (audit_results.get("tests") or {}).items()
        },
    }


def _variant_sentiment(sentiment_data: dict[str, dict], disable_oi: bool) -> dict[str, dict]:
    out = deepcopy(sentiment_data)
    if not disable_oi:
        return out
    for rec in out.values():
        rec["oi_df"] = None
        rec["oi_ready"] = False
    return out


def _run_variant(
    bw,
    *,
    variant_name: str,
    disable_oi: bool,
    all_dfs: dict[str, pd.DataFrame],
    sentiment_data: dict[str, dict],
    macro_bias,
    corr: dict,
    n_candles: int,
    scan_days: int,
    strict_direction: bool,
    min_components: int,
    min_dir_thresh: float | None,
    exit_on_reversal: bool,
) -> dict:
    variant_sentiment = _variant_sentiment(sentiment_data, disable_oi=disable_oi)
    all_trades: list[dict] = []
    all_vetos: dict[str, int] = defaultdict(int)
    insufficient_coverage_symbols: list[str] = []

    for sym, df in all_dfs.items():
        symbol_scan_start_idx = bw._coverage_scan_start_idx(
            df,
            variant_sentiment.get(sym),
            max(0, len(df) - n_candles),
        )
        remaining_scan_candles = len(df) - symbol_scan_start_idx
        if not bw._scan_window_can_close_trades(remaining_scan_candles):
            insufficient_coverage_symbols.append(sym)
            continue
        trades, vetos = bw.scan_thoth(
            df,
            sym,
            macro_bias,
            corr,
            sentiment_data=variant_sentiment,
            scan_start_idx=symbol_scan_start_idx,
            strict_direction=strict_direction,
            min_components=min_components,
            min_dir_thresh=min_dir_thresh,
            exit_on_reversal=exit_on_reversal,
        )
        all_trades.extend(trades)
        for key, value in vetos.items():
            all_vetos[key] += value

    all_trades.sort(key=lambda t: t["timestamp"])
    closed = [t for t in all_trades if t.get("result") in ("WIN", "LOSS")]
    summary = _trade_summary(
        closed,
        account_size=bw.ACCOUNT_SIZE,
        scan_days=scan_days,
        calc_ratios=bw.calc_ratios,
        equity_stats=bw.equity_stats,
    )
    diagnostics = bw._trade_sentiment_diagnostics(closed)

    try:
        from analysis.overfit_audit import run_audit

        overfit = _normalize_overfit(run_audit(all_trades))
    except Exception:
        overfit = None

    return {
        "variant": variant_name,
        "disable_oi": disable_oi,
        "summary": summary,
        "sentiment_diagnostics": diagnostics,
        "overfit": overfit,
        "insufficient_coverage_symbols": sorted(insufficient_coverage_symbols),
        "vetos": dict(sorted(all_vetos.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_symbol": _per_symbol(closed),
        "by_macro_bias": _aggregate_bucket(closed, "macro_bias"),
        "by_hmm_regime": _aggregate_bucket(closed, "hmm_regime"),
        "trades": closed,
    }


def _format_metric(value, pct: bool = False) -> str:
    if value is None:
        return "-"
    if pct:
        return f"{float(value):.2f}%"
    return f"{float(value):+.3f}"


def _report_md(run_id: str, meta: dict, rows: list[dict]) -> str:
    lines = [
        "# BRIDGEWATER Compare Battery",
        "",
        f"run_id: `{run_id}`",
        f"symbols: `{','.join(meta['symbols'])}`",
        f"days: `{meta['days']}` | interval: `{meta['interval']}` | basket: `{meta['basket']}`",
        "",
        "| Variant | Trades | WR | ROI | Sharpe | Sortino | MaxDD | PnL | Overfit | OI nonzero |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        s = row["summary"]
        d = row["sentiment_diagnostics"]
        ov = row.get("overfit") or {}
        ov_label = "-"
        if ov:
            ov_label = f"{ov.get('passed', '-') }P/{ov.get('warnings', '-') }W/{ov.get('failed', '-') }F"
        lines.append(
            f"| {row['variant']} | {s['n_trades']} | {s['win_rate']:.1f}% | "
            f"{s['roi_pct']:+.2f}% | {_format_metric(s['sharpe'])} | {_format_metric(s['sortino'])} | "
            f"{s['max_dd_pct']:.2f}% | {s['pnl']:+.2f} | {ov_label} | {d['oi_nonzero_trades']} |"
        )

    for row in rows:
        lines += ["", f"## {row['variant']} · by symbol", "", "| Symbol | N | WR | PnL | Avg R |", "|---|---|---|---|---|"]
        for label, rec in row["by_symbol"].items():
            lines.append(f"| {label} | {rec['n']} | {rec['win_rate']:.1f}% | {rec['pnl']:+.2f} | {rec['avg_r']:+.3f} |")

        lines += ["", f"## {row['variant']} · by macro bias", "", "| Macro | N | WR | PnL | Avg R |", "|---|---|---|---|---|"]
        for label, rec in row["by_macro_bias"].items():
            lines.append(f"| {label} | {rec['n']} | {rec['win_rate']:.1f}% | {rec['pnl']:+.2f} | {rec['avg_r']:+.3f} |")

        lines += ["", f"## {row['variant']} · by HMM regime", "", "| HMM | N | WR | PnL | Avg R |", "|---|---|---|---|---|"]
        for label, rec in row["by_hmm_regime"].items():
            lines.append(f"| {label} | {rec['n']} | {rec['win_rate']:.1f}% | {rec['pnl']:+.2f} | {rec['avg_r']:+.3f} |")

    return "\n".join(lines)


def main() -> int:
    bw = _resolve_bridgewater_module()

    ap = argparse.ArgumentParser(description="BRIDGEWATER funding+LS vs funding+OI+LS compare battery")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--basket", default="bluechip")
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--interval", default=bw.INTERVAL)
    ap.add_argument("--end", default=None)
    ap.add_argument("--strict-direction", action="store_true")
    ap.add_argument("--min-components", type=int, default=0)
    ap.add_argument("--min-dir-thresh", type=float, default=None)
    ap.add_argument("--exit-on-reversal", action="store_true")
    args = ap.parse_args()

    bw.INTERVAL = args.interval
    basket_name, symbols = _resolve_symbols(bw, args.basket, args.symbols)

    run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
    out_base = REPO / "data" / "_bridgewater_compare" / run_id
    out_base.mkdir(parents=True, exist_ok=True)

    end_time_ms = None
    if args.end:
        end_time_ms = int(pd.Timestamp(args.end).timestamp() * 1000)

    tf_per_hour = 60 / bw._TF_MINUTES.get(bw.INTERVAL, 15)
    n_candles = int(args.days * 24 * tf_per_hour)
    warmup_bars = bw._scan_warmup_bars()
    fetch_candles = n_candles + warmup_bars

    fetch_symbols = list(symbols)
    if bw.MACRO_SYMBOL not in fetch_symbols:
        fetch_symbols.insert(0, bw.MACRO_SYMBOL)

    print(f"BRIDGEWATER compare battery @ {run_id}")
    print(f"symbols={symbols} days={args.days} interval={bw.INTERVAL} basket={basket_name}")
    print("fetching OHLCV...")
    all_dfs = bw.fetch_all(
        fetch_symbols,
        bw.INTERVAL,
        fetch_candles,
        futures=True,
        min_rows=min(300, fetch_candles),
        end_time_ms=end_time_ms,
    )
    all_dfs, stale_symbols = bw._filter_stale_market_data(all_dfs, bw.INTERVAL)
    if stale_symbols:
        print(f"stale skipped: {', '.join(sorted(stale_symbols))}")
    for sym, df in all_dfs.items():
        bw.validate(df, sym)
    if not all_dfs:
        raise SystemExit("no market data")

    macro_bias = bw.detect_macro(all_dfs)
    corr = bw.build_corr_matrix(all_dfs)

    print("fetching sentiment...")
    sentiment_data = bw.collect_sentiment(
        [s for s in symbols if s in all_dfs],
        end_time_ms=end_time_ms,
        window_days=args.days,
    )

    eligible_symbols = [
        s for s in symbols
        if s in all_dfs
        and s in sentiment_data
        and sentiment_data[s].get("funding_z") is not None
        and sentiment_data[s].get("oi_ready", sentiment_data[s].get("oi_df") is not None)
        and sentiment_data[s].get("ls_ready", sentiment_data[s].get("ls_signal") is not None)
    ]
    if not eligible_symbols:
        raise SystemExit("no symbols with full sentiment coverage")
    all_dfs = {sym: all_dfs[sym] for sym in eligible_symbols}

    variants = [
        ("funding+oi+ls", False),
        ("funding+ls", True),
    ]
    rows = []
    for variant_name, disable_oi in variants:
        print(f"running {variant_name} ...")
        rows.append(
            _run_variant(
                bw,
                variant_name=variant_name,
                disable_oi=disable_oi,
                all_dfs=all_dfs,
                sentiment_data=sentiment_data,
                macro_bias=macro_bias,
                corr=corr,
                n_candles=n_candles,
                scan_days=args.days,
                strict_direction=args.strict_direction,
                min_components=args.min_components,
                min_dir_thresh=args.min_dir_thresh,
                exit_on_reversal=args.exit_on_reversal,
            )
        )

    meta = {
        "run_id": run_id,
        "days": args.days,
        "interval": bw.INTERVAL,
        "basket": basket_name,
        "symbols": eligible_symbols,
        "strict_direction": args.strict_direction,
        "min_components": args.min_components,
        "min_dir_thresh": args.min_dir_thresh,
        "end": args.end,
    }
    payload = {"meta": meta, "variants": rows}

    (out_base / "report.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (out_base / "report.md").write_text(_report_md(run_id, meta, rows), encoding="utf-8")

    print()
    print((out_base / "report.md").read_text(encoding="utf-8"))
    print()
    print(f"reports: {out_base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
