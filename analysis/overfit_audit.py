"""
AURUM Finance — Overfit Audit
6 reality checks on backtest trade data.
If it smells like overfit, it probably is.
"""
import json, sys, math
import numpy as np
from pathlib import Path

from config.params import LEVERAGE, COMMISSION, FUNDING_PER_8H


def _closed(trades):
    return [t for t in trades if t.get("result") in ("WIN", "LOSS")]


def _expectancy(trades):
    if not trades:
        return 0.0
    return sum(t["pnl"] for t in trades) / len(trades)


def _wr(trades):
    if not trades:
        return 0.0
    return sum(1 for t in trades if t["result"] == "WIN") / len(trades) * 100


def _total_pnl(trades):
    return sum(t["pnl"] for t in trades)


# ---------------------------------------------------------------------------
# TEST A — Walk-Forward Stability
# ---------------------------------------------------------------------------
def _test_walk_forward(trades):
    n = len(trades)
    if n < 5:
        return {"name": "walk-forward", "pass": None, "status": "SKIP",
                "detail": f"Only {n} trades, need >=5", "windows": []}

    size = n // 5
    windows = []
    for i in range(5):
        start = i * size
        end = start + size if i < 4 else n
        chunk = trades[start:end]
        exp = _expectancy(chunk)
        windows.append({
            "window": i + 1, "n": len(chunk),
            "wr": round(_wr(chunk), 1),
            "expectancy": round(exp, 4),
            "pnl": round(_total_pnl(chunk), 2),
        })

    neg_count = sum(1 for w in windows if w["expectancy"] <= 0)

    if neg_count == 0:
        status, passed = "PASS", True
        detail = "All 5 windows have positive expectancy"
    elif neg_count == 1:
        status, passed = "WARN", True
        detail = f"Window {[w['window'] for w in windows if w['expectancy'] <= 0][0]} has non-positive expectancy"
    else:
        status, passed = "FAIL", False
        detail = f"{neg_count}/5 windows have negative expectancy"

    return {"name": "walk-forward", "pass": passed, "status": status,
            "detail": detail, "windows": windows}


# ---------------------------------------------------------------------------
# TEST B — Parameter Sensitivity
# ---------------------------------------------------------------------------
def _test_sensitivity(trades):
    thresholds = [0.50, 0.51, 0.52, 0.53, 0.54, 0.55, 0.56]
    rows = []
    for th in thresholds:
        subset = [t for t in trades if t.get("score", 0) >= th]
        pnl = _total_pnl(subset) if subset else 0.0
        wr = _wr(subset) if subset else 0.0
        rows.append({"threshold": th, "n": len(subset), "wr": round(wr, 1),
                      "pnl": round(pnl, 2)})

    # Check for cliff: PnL drops >60% in one step
    cliff = False
    for i in range(1, len(rows)):
        prev_pnl = rows[i - 1]["pnl"]
        curr_pnl = rows[i]["pnl"]
        if prev_pnl > 0:
            drop = (prev_pnl - curr_pnl) / prev_pnl
            if drop > 0.60:
                cliff = True
                break
        if prev_pnl > 0 and curr_pnl < 0:
            cliff = True
            break

    if not cliff:
        status, passed = "PASS", True
        detail = "Smooth degradation across thresholds"
    else:
        status, passed = "FAIL", False
        detail = f"Cliff detected at threshold {rows[i]['threshold']:.2f}"

    return {"name": "sensitivity", "pass": passed, "status": status,
            "detail": detail, "thresholds": rows}


# ---------------------------------------------------------------------------
# TEST C — Symbol Concentration
# ---------------------------------------------------------------------------
def _test_concentration(trades):
    from collections import defaultdict
    by_sym = defaultdict(list)
    for t in trades:
        by_sym[t.get("symbol", "UNKNOWN")].append(t)

    total = _total_pnl(trades)
    if total == 0:
        return {"name": "concentration", "pass": None, "status": "SKIP",
                "detail": "Total PnL is zero", "symbols": []}

    sym_pnl = {s: round(_total_pnl(ts), 2) for s, ts in by_sym.items()}
    removals = {}
    for s in sym_pnl:
        remaining = total - sym_pnl[s]
        removals[s] = round(remaining, 2)

    top_sym = max(sym_pnl, key=lambda s: sym_pnl[s])
    top_share = sym_pnl[top_sym] / total * 100 if total != 0 else 0

    any_kills = any(v < 0 for v in removals.values())

    symbols_detail = [{"symbol": s, "pnl": sym_pnl[s],
                        "share_pct": round(sym_pnl[s] / total * 100, 1) if total else 0,
                        "pnl_without": removals[s]}
                       for s in sorted(sym_pnl, key=lambda s: sym_pnl[s], reverse=True)]

    if any_kills:
        status, passed = "FAIL", False
        killer = [s for s, v in removals.items() if v < 0]
        detail = f"Removing {killer[0]} makes PnL negative"
    elif top_share > 40:
        status, passed = "WARN", True
        detail = f"{top_sym}={top_share:.0f}% of PnL"
    else:
        status, passed = "PASS", True
        detail = f"Top={top_sym} {top_share:.0f}% of PnL"

    return {"name": "concentration", "pass": passed, "status": status,
            "detail": detail, "symbols": symbols_detail}


# ---------------------------------------------------------------------------
# TEST D — Regime Dependency
# ---------------------------------------------------------------------------
def _test_regime(trades):
    from collections import defaultdict
    by_regime = defaultdict(list)
    for t in trades:
        r = t.get("macro_bias", "UNKNOWN")
        by_regime[r].append(t)

    regime_stats = {}
    for r, ts in by_regime.items():
        regime_stats[r] = {"n": len(ts), "wr": round(_wr(ts), 1),
                           "pnl": round(_total_pnl(ts), 2),
                           "exp": round(_expectancy(ts), 4)}

    positive_regimes = [r for r, s in regime_stats.items() if s["pnl"] > 0]
    n_total = len(trades)

    if len(positive_regimes) >= 2:
        status, passed = "PASS", True
        detail = f"{len(positive_regimes)} regimes profitable"
    elif len(positive_regimes) == 1:
        dominant = positive_regimes[0]
        dom_n = regime_stats[dominant]["n"]
        dom_share = dom_n / n_total * 100 if n_total else 0
        if dom_n > 100:
            status, passed = "PASS", True
            detail = f"Only {dominant} profitable but {dom_n} trades"
        elif dom_share > 90:
            status, passed = "WARN", True
            detail = f"{dom_share:.0f}% trades in {dominant} (only positive regime)"
        elif dom_n < 50:
            status, passed = "FAIL", False
            detail = f"Only {dominant} positive with {dom_n} trades"
        else:
            status, passed = "WARN", True
            detail = f"Only {dominant} profitable ({dom_n} trades)"
    else:
        status, passed = "FAIL", False
        detail = "No regime with positive PnL"

    return {"name": "regime", "pass": passed, "status": status,
            "detail": detail, "regimes": regime_stats}


# ---------------------------------------------------------------------------
# TEST E — Temporal Decay
# ---------------------------------------------------------------------------
def _test_temporal_decay(trades):
    n = len(trades)
    if n < 4:
        return {"name": "temporal", "pass": None, "status": "SKIP",
                "detail": f"Only {n} trades", "halves": {}}

    mid = n // 2
    first = trades[:mid]
    second = trades[mid:]

    exp1 = _expectancy(first)
    exp2 = _expectancy(second)
    pnl1 = _total_pnl(first)
    pnl2 = _total_pnl(second)

    if exp1 == 0:
        decay = 100.0
    else:
        decay = (exp1 - exp2) / abs(exp1) * 100

    halves = {
        "first": {"n": len(first), "pnl": round(pnl1, 2),
                  "exp": round(exp1, 4), "wr": round(_wr(first), 1)},
        "second": {"n": len(second), "pnl": round(pnl2, 2),
                   "exp": round(exp2, 4), "wr": round(_wr(second), 1)},
        "decay_pct": round(decay, 1),
    }

    if exp2 < 0:
        status, passed = "FAIL", False
        detail = f"Second half negative exp (decay={decay:.0f}%)"
    elif decay > 75:
        status, passed = "WARN", True
        detail = f"Decay={decay:.0f}% (edge thinning)"
    elif decay > 50:
        status, passed = "WARN", True
        detail = f"Decay={decay:.0f}% (moderate)"
    else:
        status, passed = "PASS", True
        detail = f"Decay={decay:.0f}% (edge holds)"

    return {"name": "temporal", "pass": passed, "status": status,
            "detail": detail, "halves": halves}


# ---------------------------------------------------------------------------
# TEST F — Breakeven Slippage
# ---------------------------------------------------------------------------
def _test_slippage(trades, slippage_fn=None):
    be_slip = None

    # Try importing from diagnostics (suppress its stdout)
    if slippage_fn is None:
        try:
            import io, contextlib
            from analysis.diagnostics import execution_realism_test
            with contextlib.redirect_stdout(io.StringIO()):
                res = execution_realism_test(trades)
            be_slip = res.get("breakeven_slippage")
        except Exception:
            slippage_fn = None

    # Use provided function
    if slippage_fn is not None and be_slip is None:
        try:
            be_slip = slippage_fn(trades)
        except Exception:
            be_slip = None

    # Inline calculation as fallback
    if be_slip is None:
        for test_bp in range(1, 51):
            s = test_bp * 0.0001
            total = 0
            for t in trades:
                entry = t["entry"]
                exit_p = t["exit_p"]
                size = t["size"]
                d = t["direction"]
                dur = t.get("duration", 1)
                funding = FUNDING_PER_8H * dur / 32
                if d == "BULLISH":
                    pnl = size * (exit_p * (1 - COMMISSION - s) - entry * (1 + COMMISSION + s)) - size * entry * funding
                else:
                    pnl = size * (entry * (1 - COMMISSION - s) - exit_p * (1 + COMMISSION + s)) + size * entry * funding
                total += pnl * LEVERAGE
            if total <= 0:
                be_slip = s
                break

    if be_slip is None:
        be_bp = 50.0
        status, passed = "PASS", True
        detail = "breakeven>50bp"
    else:
        be_bp = be_slip * 10000
        if be_bp > 8:
            status, passed = "PASS", True
        elif be_bp >= 5:
            status, passed = "WARN", True
        else:
            status, passed = "FAIL", False
        detail = f"breakeven={be_bp:.0f}bp"

    return {"name": "slippage", "pass": passed, "status": status,
            "detail": detail, "breakeven_bp": round(be_bp, 1)}


# ---------------------------------------------------------------------------
# MAIN AUDIT
# ---------------------------------------------------------------------------
def run_audit(trades: list[dict], slippage_fn=None) -> dict:
    """Run 6 overfitting reality checks on backtest trades."""
    closed = _closed(trades)
    if not closed:
        return {"tests": {}, "passed": 0, "total": 6, "warnings": 0}

    # Sort chronologically
    closed.sort(key=lambda t: t.get("timestamp", t.get("time", "")))

    tests = {}
    tests["A"] = _test_walk_forward(closed)
    tests["B"] = _test_sensitivity(closed)
    tests["C"] = _test_concentration(closed)
    tests["D"] = _test_regime(closed)
    tests["E"] = _test_temporal_decay(closed)
    tests["F"] = _test_slippage(closed, slippage_fn)

    passed = sum(1 for t in tests.values() if t["status"] == "PASS")
    warnings = sum(1 for t in tests.values() if t["status"] == "WARN")

    return {"tests": tests, "passed": passed, "total": 6, "warnings": warnings}


# ---------------------------------------------------------------------------
# CLI OUTPUT
# ---------------------------------------------------------------------------
def print_audit_box(results: dict):
    """Print compact audit summary box."""
    tests = results.get("tests", {})
    p = results.get("passed", 0)
    w = results.get("warnings", 0)
    f = results.get("total", 6) - p - w

    header = f"OVERFIT AUDIT: {p}/{results['total']} PASS"
    if w:
        header += f"  {w} WARNING"
    if f:
        header += f"  {f} FAIL"

    width = 45
    print(f"  +-- {header} {'-' * max(1, width - len(header) - 6)}+")
    for key in sorted(tests):
        t = tests[key]
        name = t["name"][:14]
        status = t["status"]
        extra = ""
        if t.get("detail"):
            extra = f"  {t['detail'][:30]}"
        line = f"  {key} {name:<14s} {status:<4s}{extra}"
        pad = width - len(line)
        print(f"  |{line}{' ' * max(pad, 1)}|")
    print(f"  +{'-' * width}+")


# ---------------------------------------------------------------------------
# HTML OUTPUT
# ---------------------------------------------------------------------------
def build_audit_html(results: dict) -> str:
    """Build HTML fragment for embedding in backtest report."""
    _BG = "#0a0a12"
    _PANEL = "#0f0f1a"
    _GOLD = "#e8b84b"
    _GREEN = "#26d47c"
    _RED = "#e85d5d"
    _GRAY = "#9ca3af"
    _WHITE = "#f0f0f0"
    _BORDER = "#1e1e2e"
    _TEAL = "#2dd4bf"

    def _status_color(s):
        if s == "PASS":
            return _GREEN
        if s == "WARN":
            return _GOLD
        if s == "FAIL":
            return _RED
        return _GRAY

    tests = results.get("tests", {})
    p = results.get("passed", 0)
    w = results.get("warnings", 0)
    f = results.get("total", 6) - p - w

    # Summary header
    parts = [f'<span style="color:{_GREEN}">{p} PASS</span>']
    if w:
        parts.append(f'<span style="color:{_GOLD}">{w} WARN</span>')
    if f:
        parts.append(f'<span style="color:{_RED}">{f} FAIL</span>')
    summary_line = " &nbsp; ".join(parts)

    html = f'''<div style="background:{_PANEL};border:1px solid {_BORDER};border-radius:8px;padding:16px 20px;margin:16px 0;font-family:monospace;">
  <div style="font-size:14px;color:{_GOLD};font-weight:bold;margin-bottom:12px;">OVERFIT AUDIT &mdash; {summary_line}</div>
  <table style="width:100%;border-collapse:collapse;font-size:13px;">
    <tr style="color:{_GRAY};border-bottom:1px solid {_BORDER};">
      <th style="text-align:left;padding:4px 8px;">Test</th>
      <th style="text-align:left;padding:4px 8px;">Name</th>
      <th style="text-align:center;padding:4px 8px;">Status</th>
      <th style="text-align:left;padding:4px 8px;">Detail</th>
    </tr>'''

    for key in sorted(tests):
        t = tests[key]
        sc = _status_color(t["status"])
        html += f'''
    <tr style="border-bottom:1px solid {_BORDER};">
      <td style="color:{_WHITE};padding:4px 8px;font-weight:bold;">{key}</td>
      <td style="color:{_GRAY};padding:4px 8px;">{t["name"]}</td>
      <td style="text-align:center;padding:4px 8px;"><span style="color:{sc};font-weight:bold;">{t["status"]}</span></td>
      <td style="color:{_GRAY};padding:4px 8px;">{t.get("detail", "")}</td>
    </tr>'''

    html += '\n  </table>'

    # TEST A windows detail
    a = tests.get("A", {})
    windows = a.get("windows", [])
    if windows:
        html += f'''
  <div style="margin-top:14px;font-size:12px;">
    <div style="color:{_TEAL};font-weight:bold;margin-bottom:6px;">A. Walk-Forward Windows</div>
    <table style="width:100%;border-collapse:collapse;font-size:12px;">
      <tr style="color:{_GRAY};border-bottom:1px solid {_BORDER};">
        <th style="padding:3px 6px;text-align:center;">Window</th>
        <th style="padding:3px 6px;text-align:right;">N</th>
        <th style="padding:3px 6px;text-align:right;">WR%</th>
        <th style="padding:3px 6px;text-align:right;">Expectancy</th>
        <th style="padding:3px 6px;text-align:right;">PnL</th>
      </tr>'''
        for w in windows:
            ec = _GREEN if w["expectancy"] > 0 else _RED
            html += f'''
      <tr style="border-bottom:1px solid {_BORDER};">
        <td style="color:{_WHITE};padding:3px 6px;text-align:center;">{w["window"]}</td>
        <td style="color:{_GRAY};padding:3px 6px;text-align:right;">{w["n"]}</td>
        <td style="color:{_GRAY};padding:3px 6px;text-align:right;">{w["wr"]:.1f}%</td>
        <td style="color:{ec};padding:3px 6px;text-align:right;">${w["expectancy"]:+.4f}</td>
        <td style="color:{ec};padding:3px 6px;text-align:right;">${w["pnl"]:+.2f}</td>
      </tr>'''
        html += '\n    </table>\n  </div>'

    # TEST B sensitivity detail
    b = tests.get("B", {})
    thresholds = b.get("thresholds", [])
    if thresholds:
        html += f'''
  <div style="margin-top:14px;font-size:12px;">
    <div style="color:{_TEAL};font-weight:bold;margin-bottom:6px;">B. Parameter Sensitivity</div>
    <table style="width:100%;border-collapse:collapse;font-size:12px;">
      <tr style="color:{_GRAY};border-bottom:1px solid {_BORDER};">
        <th style="padding:3px 6px;text-align:center;">Threshold</th>
        <th style="padding:3px 6px;text-align:right;">N</th>
        <th style="padding:3px 6px;text-align:right;">WR%</th>
        <th style="padding:3px 6px;text-align:right;">PnL</th>
      </tr>'''
        for row in thresholds:
            pc = _GREEN if row["pnl"] > 0 else _RED
            html += f'''
      <tr style="border-bottom:1px solid {_BORDER};">
        <td style="color:{_WHITE};padding:3px 6px;text-align:center;">{row["threshold"]:.2f}</td>
        <td style="color:{_GRAY};padding:3px 6px;text-align:right;">{row["n"]}</td>
        <td style="color:{_GRAY};padding:3px 6px;text-align:right;">{row["wr"]:.1f}%</td>
        <td style="color:{pc};padding:3px 6px;text-align:right;">${row["pnl"]:+.2f}</td>
      </tr>'''
        html += '\n    </table>\n  </div>'

    # TEST C symbol concentration detail
    c = tests.get("C", {})
    symbols = c.get("symbols", [])
    if symbols:
        html += f'''
  <div style="margin-top:14px;font-size:12px;">
    <div style="color:{_TEAL};font-weight:bold;margin-bottom:6px;">C. Symbol Concentration</div>
    <table style="width:100%;border-collapse:collapse;font-size:12px;">
      <tr style="color:{_GRAY};border-bottom:1px solid {_BORDER};">
        <th style="padding:3px 6px;text-align:left;">Symbol</th>
        <th style="padding:3px 6px;text-align:right;">PnL</th>
        <th style="padding:3px 6px;text-align:right;">Share%</th>
        <th style="padding:3px 6px;text-align:right;">PnL Without</th>
      </tr>'''
        for s in symbols[:10]:
            sc = _GREEN if s["pnl_without"] > 0 else _RED
            html += f'''
      <tr style="border-bottom:1px solid {_BORDER};">
        <td style="color:{_WHITE};padding:3px 6px;">{s["symbol"]}</td>
        <td style="color:{_GRAY};padding:3px 6px;text-align:right;">${s["pnl"]:+.2f}</td>
        <td style="color:{_GRAY};padding:3px 6px;text-align:right;">{s["share_pct"]:.1f}%</td>
        <td style="color:{sc};padding:3px 6px;text-align:right;">${s["pnl_without"]:+.2f}</td>
      </tr>'''
        html += '\n    </table>\n  </div>'

    html += '\n</div>'
    return html


# ---------------------------------------------------------------------------
# STANDALONE
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analysis/overfit_audit.py <report.json>")
        sys.exit(1)

    path = Path(sys.argv[1])
    with open(path) as f:
        data = json.load(f)

    trades = data.get("trades", data if isinstance(data, list) else [])
    results = run_audit(trades)
    print_audit_box(results)

    # Detailed output
    tests = results.get("tests", {})
    for key in sorted(tests):
        t = tests[key]
        print(f"\n  [{key}] {t['name'].upper()} -- {t['status']}")
        print(f"      {t.get('detail', '')}")
        if key == "A" and t.get("windows"):
            for w in t["windows"]:
                tag = "+" if w["expectancy"] > 0 else "-"
                print(f"      W{w['window']}: n={w['n']}  WR={w['wr']:.1f}%  exp=${w['expectancy']:+.4f}  pnl=${w['pnl']:+.2f} {tag}")
        elif key == "B" and t.get("thresholds"):
            for row in t["thresholds"]:
                print(f"      >={row['threshold']:.2f}: n={row['n']}  WR={row['wr']:.1f}%  pnl=${row['pnl']:+.2f}")
        elif key == "C" and t.get("symbols"):
            for s in t["symbols"][:8]:
                print(f"      {s['symbol']:>12s}: pnl=${s['pnl']:+.2f}  share={s['share_pct']:.1f}%  without=${s['pnl_without']:+.2f}")
        elif key == "D" and t.get("regimes"):
            for r, s in t["regimes"].items():
                print(f"      {r:>6s}: n={s['n']}  WR={s['wr']:.1f}%  pnl=${s['pnl']:+.2f}")
        elif key == "E" and t.get("halves"):
            h = t["halves"]
            print(f"      First:  n={h['first']['n']}  exp=${h['first']['exp']:+.4f}  pnl=${h['first']['pnl']:+.2f}")
            print(f"      Second: n={h['second']['n']}  exp=${h['second']['exp']:+.4f}  pnl=${h['second']['pnl']:+.2f}")
            print(f"      Decay:  {h['decay_pct']:.1f}%")
        elif key == "F":
            print(f"      Breakeven: {t.get('breakeven_bp', '?')}bp")
