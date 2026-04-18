"""Ablation test for CITADEL Omega score components.

Runs the backtest 6 times: baseline + 5 with each component disabled.
Compares metrics to identify which components contribute to the edge.

Usage:
    python tools/ablation_test.py [--days 180]
"""
import subprocess, json, re, sys, os, time
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
PARAMS_FILE = ROOT / "config" / "params.py"
OUT_DIR = ROOT / "data" / "validation" / time.strftime("%Y-%m-%d")
OUT_DIR.mkdir(parents=True, exist_ok=True)

COMPONENTS = [
    ("BASELINE", ""),
    ("-struct", "struct"),
    ("-flow", "flow"),
    ("-cascade", "cascade"),
    ("-momentum", "momentum"),
    ("-pullback", "pullback"),
]

DAYS = 180
if len(sys.argv) > 1 and sys.argv[1] == "--days":
    DAYS = int(sys.argv[2])


def set_ablation(value: str):
    """Set ABLATION_DISABLE in params.py."""
    text = PARAMS_FILE.read_text(encoding="utf-8")
    text = re.sub(
        r'ABLATION_DISABLE\s*=\s*"[^"]*"',
        f'ABLATION_DISABLE = "{value}"',
        text,
    )
    PARAMS_FILE.write_text(text, encoding="utf-8")


def run_backtest(days: int) -> dict:
    """Run CITADEL backtest and extract metrics from stdout."""
    cmd = [
        sys.executable, str(ROOT / "engines" / "backtest.py"),
        "--days", str(days),
        "--holdout-pct", "0",
        "--no-menu",
    ]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    result = subprocess.run(
        cmd, capture_output=True, timeout=600,
        cwd=str(ROOT), env=env,
    )
    output = result.stdout.decode("utf-8", errors="replace") + \
             result.stderr.decode("utf-8", errors="replace")

    # Extract metrics from the compact result block
    metrics = {
        "n_trades": 0, "wr": 0.0, "pnl": 0.0,
        "sharpe": 0.0, "max_dd_pct": 0.0, "roi": 0.0,
    }

    # Pattern: "N trades · WR X.X% · Sharpe X.XXX · MaxDD X.XX%"
    m = re.search(r'(\d+)\s+trades\s+·\s+WR\s+([\d.]+)%\s+·\s+Sharpe\s+([\d.-]+)\s+·\s+MaxDD\s+([\d.-]+)%', output)
    if m:
        metrics["n_trades"] = int(m.group(1))
        metrics["wr"] = float(m.group(2))
        metrics["sharpe"] = float(m.group(3))
        metrics["max_dd_pct"] = float(m.group(4))

    # Pattern: "$X,XXX → $Y,YYY  (+$Z,ZZZ)  ROI +X.XX%"
    m2 = re.search(r'\(\+?\$?([\d,.-]+)\)\s+ROI\s+([\d.+-]+)%', output)
    if m2:
        metrics["pnl"] = float(m2.group(1).replace(",", ""))
        metrics["roi"] = float(m2.group(2))

    # Win/Loss counts
    m3 = re.search(r'(\d+)W\s*/\s*(\d+)L', output)
    if m3:
        metrics["wins"] = int(m3.group(1))
        metrics["losses"] = int(m3.group(2))

    return metrics


def main():
    print(f"╔══════════════════════════════════════════════════════╗")
    print(f"║  ABLATION TEST — CITADEL Omega Components           ║")
    print(f"║  {DAYS} days · {len(COMPONENTS)} runs                              ║")
    print(f"╚══════════════════════════════════════════════════════╝")

    results = []
    baseline_pnl = None

    for label, ablation_value in COMPONENTS:
        print(f"\n  ► Run: {label:12s}  (ABLATION_DISABLE={ablation_value!r})")
        set_ablation(ablation_value)
        try:
            metrics = run_backtest(DAYS)
            metrics["label"] = label
            metrics["ablation"] = ablation_value

            if baseline_pnl is None:
                baseline_pnl = metrics["pnl"]
                metrics["delta_pnl_pct"] = 0.0
            else:
                if baseline_pnl != 0:
                    metrics["delta_pnl_pct"] = round(
                        (metrics["pnl"] - baseline_pnl) / abs(baseline_pnl) * 100, 1)
                else:
                    metrics["delta_pnl_pct"] = 0.0

            results.append(metrics)
            print(f"    Trades={metrics['n_trades']}  WR={metrics['wr']:.1f}%  "
                  f"PnL=${metrics['pnl']:+,.0f}  Sharpe={metrics['sharpe']:.3f}  "
                  f"MaxDD={metrics['max_dd_pct']:.1f}%  ΔPnL={metrics['delta_pnl_pct']:+.1f}%")
        except subprocess.TimeoutExpired:
            print(f"    TIMEOUT — skipped")
            results.append({"label": label, "ablation": ablation_value, "error": "timeout"})
        except Exception as e:
            print(f"    ERROR: {e}")
            results.append({"label": label, "ablation": ablation_value, "error": str(e)})

    # Restore baseline
    set_ablation("")
    print(f"\n  ✓ ABLATION_DISABLE restored to empty")

    # Save JSON
    json_path = OUT_DIR / "ablation_results.json"
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  JSON → {json_path}")

    # Generate markdown report
    md_lines = [
        "# Ablation Test Results",
        f"\n**Date:** {time.strftime('%Y-%m-%d %H:%M')}",
        f"**Period:** {DAYS} days",
        f"**Holdout:** 0% (full IS for ablation comparison)\n",
        "| Component OFF | Trades | WR | PnL | Sharpe | MaxDD | ΔPnL vs Base |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if "error" in r:
            md_lines.append(f"| {r['label']} | ERROR | — | — | — | — | {r.get('error','')} |")
            continue
        delta_str = f"{r.get('delta_pnl_pct',0):+.1f}%"
        if abs(r.get("delta_pnl_pct", 0)) < 5:
            verdict = "noise"
        elif r.get("delta_pnl_pct", 0) < -20:
            verdict = "**CORE**"
        elif r.get("delta_pnl_pct", 0) < -5:
            verdict = "contributes"
        else:
            verdict = "noise/negative"
        md_lines.append(
            f"| {r['label']} | {r['n_trades']} | {r['wr']:.1f}% | "
            f"${r['pnl']:+,.0f} | {r['sharpe']:.3f} | {r['max_dd_pct']:.1f}% | "
            f"{delta_str} {verdict} |"
        )

    md_lines.extend([
        "\n## Interpretation",
        "- **ΔPnL < -20%**: Component is CORE — removing it kills the edge",
        "- **ΔPnL -5% to -20%**: Component contributes but is not essential",
        "- **ΔPnL ±5%**: Component is noise — candidate for removal",
        "- **ΔPnL > +5%**: Component hurts performance — should be removed",
    ])

    md_path = OUT_DIR / "ablation_report.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"  Report → {md_path}")


if __name__ == "__main__":
    main()
