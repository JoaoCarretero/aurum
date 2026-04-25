"""Daily audit: compare backtest-replay trades against live shadow+paper
trades captured on disk. Every backtest trade in the overlap window
must have a matching live trade; any missing = signal the shadow or
paper did not pick up and Joao needs to know why.

Output:
  - data/audits/live_vs_backtest/YYYY-MM-DD.json  — full diff record
  - stdout summary table
  - optional Telegram notification (env AURUM_AUDIT_TG_CHAT / TOKEN)

Usage (manual):
  python tools/debug/audit_live_vs_backtest_daily.py --days 15

Usage (cron):
  systemd timer tools/deploy/aurum_audit_daily.timer fires daily at
  23:00 UTC on the VPS; the service unit runs this with --days 15
  --telegram.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.params import BASKETS, ENGINE_BASKETS, ENGINE_INTERVALS, MACRO_SYMBOL  # noqa: E402
from core.data import fetch_all, validate  # noqa: E402
from core.portfolio import build_corr_matrix, detect_macro  # noqa: E402

ENGINES = [
    ("renaissance", "RENAISSANCE", "core.harmonics", "scan_hermes"),
    ("citadel", "CITADEL", "engines.citadel", "scan_symbol"),
    # JUMP disabled — engines/jump.py:89 pre-existing bug (indicators
    # module-vs-function). Re-enable once fixed.
]


@dataclass
class TradeKey:
    engine: str
    symbol: str
    direction: str
    open_ts: str  # ISO / pandas timestamp str

    def as_tuple(self):
        return (self.engine.upper(), self.symbol.upper(),
                str(self.open_ts).replace(" ", "T")[:19])


@dataclass
class EngineAudit:
    engine: str
    n_backtest: int = 0
    n_live: int = 0
    matched: list[dict] = field(default_factory=list)
    missed: list[dict] = field(default_factory=list)  # bt without live match
    extra: list[dict] = field(default_factory=list)   # live without bt match

    def summary(self):
        return {
            "engine": self.engine,
            "n_backtest": self.n_backtest,
            "n_live": self.n_live,
            "matched": len(self.matched),
            "missed": len(self.missed),
            "extra": len(self.extra),
            "match_pct": (
                round(100 * len(self.matched) / max(self.n_backtest, 1), 1)
            ),
        }


def _bt_trades(engine_upper: str, scan_fn, days: int) -> list[dict]:
    tf = ENGINE_INTERVALS.get(engine_upper, "15m")
    basket_name = ENGINE_BASKETS.get(engine_upper, "default")
    basket = BASKETS.get(basket_name, ["BTCUSDT"])
    symbols = list(basket)
    if MACRO_SYMBOL and MACRO_SYMBOL not in symbols:
        symbols.insert(0, MACRO_SYMBOL)
    bars_per_day = {"5m": 288, "15m": 96, "30m": 48, "1h": 24, "4h": 6}.get(tf, 24)
    n_candles = days * bars_per_day + 200  # +200 for warmup
    with contextlib.redirect_stdout(io.StringIO()):
        dfs = fetch_all(symbols, interval=tf, n_candles=n_candles)
        for s, d in dfs.items():
            validate(d, s)
        macro = detect_macro(dfs)
        corr = build_corr_matrix(dfs)
    trades: list[dict] = []
    with contextlib.redirect_stdout(io.StringIO()):
        for sym in basket:
            df = dfs.get(sym)
            if df is None:
                continue
            arg = df.copy() if engine_upper == "JUMP" else df
            t, _ = scan_fn(arg, sym, macro, corr, None, live_mode=False)
            trades.extend(t)
    return trades


def _live_trade_keys(engine_lower: str, data_root: Path) -> dict[tuple, dict]:
    """Collect (engine, symbol, open_ts) tuples from every shadow/paper run
    dir on disk. Primed bootstrap records are excluded.
    Returns a dict keyed by (engine, symbol, open_ts) -> a minimal record
    so callers can show runtime info (pnl, exit_reason, etc.).
    """
    out: dict[tuple, dict] = {}
    for mode in ("shadow", "paper"):
        root = data_root / f"{engine_lower}_{mode}"
        if not root.exists():
            continue
        for run_dir in root.iterdir():
            for fname in ("shadow_trades.jsonl", "trades.jsonl", "signals.jsonl"):
                f = run_dir / "reports" / fname
                if not f.exists():
                    continue
                try:
                    for line in f.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except Exception:
                            continue
                        # Skip primed records (they're bootstrap, not a real
                        # live capture).
                        if rec.get("primed") is True:
                            continue
                        if rec.get("decision") == "skipped":
                            continue
                        engine = str(
                            rec.get("strategy") or rec.get("engine") or ""
                        ).upper()
                        symbol = str(rec.get("symbol") or "").upper()
                        direction = str(rec.get("direction") or "").upper()
                        # Prefer open_ts / signal_ts / timestamp / entry_at
                        open_ts = (
                            rec.get("open_ts")
                            or rec.get("signal_ts")
                            or rec.get("timestamp")
                            or rec.get("entry_at")
                            or ""
                        )
                        open_ts = str(open_ts).replace(" ", "T")[:19]
                        if not engine or not symbol or not open_ts:
                            continue
                        key = (engine, symbol, open_ts)
                        # Keep the richest record for this key
                        if key not in out or len(rec) > len(out[key]):
                            rec["_source"] = f"{mode}:{run_dir.name}:{fname}"
                            rec["_direction"] = direction
                            out[key] = rec
                except OSError:
                    continue
    return out


_DIR_NORMAL = {
    "BULL": "BUY", "BULLISH": "BUY", "LONG": "BUY", "BUY": "BUY",
    "BEAR": "SELL", "BEARISH": "SELL", "SHORT": "SELL", "SELL": "SELL",
}


def _norm_direction(d: str) -> str:
    return _DIR_NORMAL.get(str(d).upper(), str(d).upper())


def audit_engine(engine_lower: str, engine_upper: str, scan_fn,
                 live_map: dict[tuple, dict], days: int) -> EngineAudit:
    ea = EngineAudit(engine=engine_upper)
    bt_trades = _bt_trades(engine_upper, scan_fn, days)
    ea.n_backtest = len(bt_trades)

    # Audit-window cutoff in ISO — anything older than (now - days) is
    # outside scope. Without this the `extra` bucket catches every
    # historical live trade still on disk (49 in the 2026-04-24 baseline).
    from datetime import timedelta
    cutoff_iso = (
        (datetime.now(timezone.utc) - timedelta(days=days))
        .isoformat().replace("+00:00", "")[:19]
    )

    ea.n_live = sum(
        1 for k in live_map
        if k[0] == engine_upper and k[2] >= cutoff_iso
    )

    # For each backtest trade, try to match live by (engine, symbol, open_ts)
    # Direction normalization handles BULLISH/LONG/BUY and BEARISH/SHORT/SELL
    # variants consistently.
    for t in bt_trades:
        sym = str(t.get("symbol") or "").upper()
        direc_norm = _norm_direction(t.get("direction") or "")
        open_ts_raw = t.get("open_ts") or t.get("timestamp")
        open_ts = str(open_ts_raw).replace(" ", "T")[:19]
        key = (engine_upper, sym, open_ts)
        live_direc_norm = (
            _norm_direction(live_map[key].get("_direction", ""))
            if key in live_map else ""
        )
        if key in live_map and (
            not live_direc_norm  # empty → don't enforce
            or live_direc_norm == direc_norm
        ):
            ea.matched.append({
                "symbol": sym, "direction": direc_norm, "open_ts": open_ts,
                "entry": t.get("entry"), "stop": t.get("stop"),
                "target": t.get("target"),
                "bt_result": t.get("result"), "bt_pnl": t.get("pnl"),
                "live_source": live_map[key].get("_source"),
            })
        else:
            ea.missed.append({
                "symbol": sym, "direction": direc_norm, "open_ts": open_ts,
                "entry": t.get("entry"), "stop": t.get("stop"),
                "target": t.get("target"),
                "bt_result": t.get("result"), "bt_pnl": t.get("pnl"),
                "entropy_norm": t.get("entropy_norm"),
            })
    # Any live trade inside the window without a backtest equivalent
    bt_keys = {
        (engine_upper, str(t.get("symbol") or "").upper(),
         str(t.get("open_ts") or t.get("timestamp")).replace(" ", "T")[:19])
        for t in bt_trades
    }
    for key, rec in live_map.items():
        if key[0] != engine_upper:
            continue
        # Window gate: skip live records from before the audit window.
        if key[2] < cutoff_iso:
            continue
        if key not in bt_keys:
            ea.extra.append({
                "symbol": key[1], "direction": rec.get("_direction"),
                "open_ts": key[2],
                "entry": rec.get("entry") or rec.get("entry_price"),
                "source": rec.get("_source"),
                "entropy_norm": rec.get("entropy_norm"),
            })
    return ea


def _send_telegram(text: str) -> bool:
    token = os.environ.get("AURUM_AUDIT_TG_TOKEN") or os.environ.get(
        "TELEGRAM_BOT_TOKEN"
    )
    chat = os.environ.get("AURUM_AUDIT_TG_CHAT") or os.environ.get(
        "TELEGRAM_CHAT_ID"
    )
    if not token or not chat:
        return False
    try:
        import urllib.parse
        import urllib.request
        data = urllib.parse.urlencode({
            "chat_id": chat, "text": text, "parse_mode": "HTML",
        }).encode()
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception as exc:
        print(f"[telegram] send failed: {exc}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=15,
                    help="Days of history to audit (default 15).")
    ap.add_argument("--data-root", default=str(ROOT / "data"),
                    help="Root where engine_{mode} dirs live.")
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "audits" / "live_vs_backtest"),
                    help="Where to write the JSON report.")
    ap.add_argument("--telegram", action="store_true",
                    help="Send a summary via Telegram bot (requires "
                         "AURUM_AUDIT_TG_TOKEN + AURUM_AUDIT_TG_CHAT env).")
    args = ap.parse_args()

    data_root = Path(args.data_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    import importlib

    audits: list[EngineAudit] = []
    for eng_lower, eng_upper, module_name, fn_name in ENGINES:
        mod = importlib.import_module(module_name)
        scan_fn = getattr(mod, fn_name)
        live_map = _live_trade_keys(eng_lower, data_root)
        audits.append(audit_engine(eng_lower, eng_upper, scan_fn, live_map, args.days))

    # Summary
    print(f"=== Live ↔ Backtest Audit — last {args.days} days ===")
    print(f"{'Engine':<14} {'BT':>4} {'Live':>5} {'Match':>6} "
          f"{'Missed':>7} {'Extra':>6} {'Pct':>6}")
    for ea in audits:
        s = ea.summary()
        print(f"{s['engine']:<14} {s['n_backtest']:>4} {s['n_live']:>5} "
              f"{s['matched']:>6} {s['missed']:>7} {s['extra']:>6} "
              f"{s['match_pct']:>5}%")
    print()
    for ea in audits:
        if ea.missed:
            print(f"[{ea.engine}] MISSED (backtest emitted, live did not):")
            for m in ea.missed:
                print(f"  {m['open_ts']} {m['symbol']:<10} {m['direction']:<8} "
                      f"entry={m['entry']} bt_result={m['bt_result']} "
                      f"bt_pnl={m['bt_pnl']}")
    # JSON artifact
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = out_dir / f"{today}.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "days": args.days,
        "engines": {ea.engine: {
            **ea.summary(),
            "missed": ea.missed,
            "extra": ea.extra,
        } for ea in audits},
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nreport: {out_path}")

    # Telegram
    if args.telegram:
        lines = [f"<b>AURUM · live ↔ backtest audit ({args.days}d)</b>"]
        any_missed = False
        for ea in audits:
            s = ea.summary()
            icon = "✅" if s["missed"] == 0 else "⚠️"
            lines.append(
                f"{icon} <b>{s['engine']}</b>: bt={s['n_backtest']} "
                f"live={s['n_live']} match={s['match_pct']}% "
                f"missed={s['missed']} extra={s['extra']}"
            )
            if s["missed"]:
                any_missed = True
        if any_missed:
            lines.append("Missed detail in report file.")
        _send_telegram("\n".join(lines))

    # Exit code: 2 if any missed (actionable), else 0
    return 2 if any(ea.missed for ea in audits) else 0


if __name__ == "__main__":
    sys.exit(main())
