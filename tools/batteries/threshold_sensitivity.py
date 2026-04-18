"""Threshold sensitivity test for CITADEL.

Varies key thresholds ±20% and measures impact on Sharpe.
Fragile thresholds (>30% Sharpe change) suggest curve-fitting.

Usage:
    python tools/threshold_sensitivity.py [--days 180]
"""
import subprocess, json, re, sys, os, time
from pathlib import Path

ROOT = Path(__file__).parent.parent
PARAMS_FILE = ROOT / "config" / "params.py"
OUT_DIR = ROOT / "data" / "validation" / time.strftime("%Y-%m-%d")
OUT_DIR.mkdir(parents=True, exist_ok=True)

DAYS = 180
if len(sys.argv) > 1 and sys.argv[1] == "--days":
    DAYS = int(sys.argv[2])

# (param_name, low, base, high)
THRESHOLDS = [
    ("SCORE_THRESHOLD", 0.42, 0.53, 0.64),
    ("STOP_ATR_M", 1.44, 1.80, 2.16),
    ("TARGET_RR", 1.60, 2.00, 2.40),
    ("REGIME_MIN_STRENGTH", 0.20, 0.25, 0.30),
]


def set_param(name: str, value):
    """Temporarily override a param in params.py."""
    text = PARAMS_FILE.read_text(encoding="utf-8")
    # Match patterns like: SCORE_THRESHOLD = 0.53 or STOP_ATR_M = 1.8
    pattern = rf'^({name}\s*=\s*)[\d.]+(\s*#?.*)$'
    replacement = rf'\g<1>{value}\2'
    new_text = re.sub(pattern, replacement, text, flags=re.MULTILINE)
    if new_text == text:
        print(f"    WARNING: could not find {name} in params.py")
        return False
    PARAMS_FILE.write_text(new_text, encoding="utf-8")
    return True


def restore_param(name: str, value):
    set_param(name, value)


def run_backtest(days: int) -> dict:
    cmd = [
        sys.executable, str(ROOT / "engines" / "backtest.py"),
        "--days", str(days), "--holdout-pct", "0", "--no-menu",
    ]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    result = subprocess.run(cmd, capture_output=True, timeout=600,
                            cwd=str(ROOT), env=env)
    output = result.stdout.decode("utf-8", errors="replace") + \
             result.stderr.decode("utf-8", errors="replace")

    metrics = {"n_trades": 0, "wr": 0.0, "pnl": 0.0, "sharpe": 0.0, "max_dd_pct": 0.0}
    m = re.search(r'(\d+)\s+trades\s+·\s+WR\s+([\d.]+)%\s+·\s+Sharpe\s+([\d.-]+)\s+·\s+MaxDD\s+([\d.-]+)%', output)
    if m:
        metrics["n_trades"] = int(m.group(1))
        metrics["wr"] = float(m.group(2))
        metrics["sharpe"] = float(m.group(3))
        metrics["max_dd_pct"] = float(m.group(4))
    m2 = re.search(r'\(\+?\$?([\d,.-]+)\)\s+ROI\s+([\d.+-]+)%', output)
    if m2:
        metrics["pnl"] = float(m2.group(1).replace(",", ""))
    return metrics


def main():
    print(f"╔══════════════════════════════════════════════════════╗")
    print(f"║  THRESHOLD SENSITIVITY — CITADEL                    ║")
    print(f"║  {DAYS} days · {len(THRESHOLDS)} params × 3 values = {len(THRESHOLDS)*3} runs       ║")
    print(f"╚══════════════════════════════════════════════════════╝")

    results = []

    for param_name, low, base, high in THRESHOLDS:
        print(f"\n  ═══ {param_name} ═══")
        row = {"param": param_name, "low_val": low, "base_val": base, "high_val": high}

        for label, value in [("-20%", low), ("BASE", base), ("+20%", high)]:
            print(f"    ► {label} ({param_name}={value})")
            if set_param(param_name, value):
                try:
                    m = run_backtest(DAYS)
                    row[f"sharpe_{label}"] = m["sharpe"]
                    row[f"trades_{label}"] = m["n_trades"]
                    row[f"wr_{label}"] = m["wr"]
                    row[f"pnl_{label}"] = m.get("pnl", 0)
                    print(f"      Trades={m['n_trades']}  Sharpe={m['sharpe']:.3f}  WR={m['wr']:.1f}%  PnL=${m.get('pnl',0):+,.0f}")
                except Exception as e:
                    print(f"      ERROR: {e}")
                    row[f"sharpe_{label}"] = None
            restore_param(param_name, base)

        # Compute fragility
        s_low = row.get("sharpe_-20%")
        s_base = row.get("sharpe_BASE")
        s_high = row.get("sharpe_+20%")
        if s_base and s_base != 0 and s_low is not None and s_high is not None:
            delta = abs(s_low - s_high) / abs(s_base)
            row["fragility"] = round(delta, 3)
            verdict = "FRAGILE" if delta > 0.30 else ("MODERATE" if delta > 0.15 else "ROBUST")
            row["verdict"] = verdict
            print(f"    → Fragility: {delta:.1%}  [{verdict}]")
        else:
            row["fragility"] = None
            row["verdict"] = "UNKNOWN"

        results.append(row)

    # Save
    json_path = OUT_DIR / "threshold_sensitivity.json"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    md_lines = [
        "# Threshold Sensitivity Results",
        f"\n**Date:** {time.strftime('%Y-%m-%d %H:%M')}",
        f"**Period:** {DAYS} days\n",
        "| Param | -20% | BASE | +20% | Sharpe Low | Sharpe Base | Sharpe High | Fragility | Verdict |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        md_lines.append(
            f"| {r['param']} | {r['low_val']} | {r['base_val']} | {r['high_val']} | "
            f"{r.get('sharpe_-20%', '—')} | {r.get('sharpe_BASE', '—')} | {r.get('sharpe_+20%', '—')} | "
            f"{r.get('fragility', '—')} | {r.get('verdict', '—')} |"
        )
    md_lines.extend([
        "\n## Interpretation",
        "- **ROBUST** (< 15%): Threshold is stable, edge likely real",
        "- **MODERATE** (15-30%): Some sensitivity, monitor in live",
        "- **FRAGILE** (> 30%): Edge may be curve-fitted to this value",
    ])

    md_path = OUT_DIR / "threshold_sensitivity.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"\n  JSON → {json_path}")
    print(f"  Report → {md_path}")


if __name__ == "__main__":
    main()
