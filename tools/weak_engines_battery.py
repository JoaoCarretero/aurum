"""Weak engines salvage battery — 2026-04-17.

Runs a closed grid of (engine, config, window) combinations on the engines
flagged as NO_EDGE / INSUFFICIENT_SAMPLE to determine whether any mechanistic
variant produces a real edge before archiving.

Grid (closed, pre-registered):
  - PHI        : 4 presets (default, reversal_candidate, native_stack, fractal_stack)
  - DE_SHAW    : 2 configs (default, strict z_entry=2.5)
  - KEPOS      : 3 configs (default, invert H1-INV, soft eta=0.75 sustained=5)
  - MEDALLION  : 2 configs (default, ensemble_threshold=0.7)

Windows (two, same for every engine):
  - 180d recent (ending today)
  - 180d displaced (ending 2025-07-01)

Total : 11 configs × 2 windows = 22 runs.

Each run invokes the engine CLI as a subprocess and reads summary.json.
Output is written to data/_weak_salvage/<run_id>/ :
  - report.md        : human-readable summary table
  - report.json      : machine-readable full payload
  - runs/<tag>.json  : each individual summary
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

# ------------------------------------------------------------
# Closed grid
# ------------------------------------------------------------
WINDOWS = [
    ("180d_recent",   {"days": 180, "end": None}),
    ("180d_hist_jul", {"days": 180, "end": "2025-07-01"}),
]

GRID: list[dict] = [
    # ---------- PHI ----------
    {"engine": "phi", "tag": "phi_default",
     "mechanism": "Thresholds estritos da spec: confluences>=3, adx>=23.6, wick>=0.618. Mais seletivo = maior conviccção.",
     "args": ["--symbols", "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT"]},
    {"engine": "phi", "tag": "phi_reversal",
     "mechanism": "entry_mode=reversal. Golden Trigger (wick+RSI extremo) e tese de REVERSÃO, nao continuation.",
     "args": ["--symbols", "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT",
              "--preset", "reversal_candidate"]},
    {"engine": "phi", "tag": "phi_native",
     "mechanism": "TFs 4h..15m em vez de 1d..5m. Fractal confluence em TFs curtos = micro-estrutura.",
     "args": ["--symbols", "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT",
              "--preset", "native_stack"]},
    {"engine": "phi", "tag": "phi_fractal",
     "mechanism": "fractal_stack balanceia seletividade (conf>=2) + sample size.",
     "args": ["--symbols", "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT",
              "--preset", "fractal_stack"]},

    # ---------- DE SHAW ----------
    {"engine": "deshaw", "tag": "deshaw_default",
     "mechanism": "Baseline atual (z_entry=2.0).",
     "args": []},
    {"engine": "deshaw", "tag": "deshaw_strict",
     "mechanism": "z_entry=2.5, pvalue=0.03. Entradas mais extremas = reversao mais confiavel.",
     "args": ["--z-entry", "2.5", "--pvalue", "0.03"]},

    # ---------- KEPOS ----------
    {"engine": "kepos", "tag": "kepos_default",
     "mechanism": "Baseline (eta>=0.95 sustained=10).",
     "args": []},
    {"engine": "kepos", "tag": "kepos_invert",
     "mechanism": "H1-INV: cavalga extensao em vez de fade. Hipotese alternativa da tese Hawkes.",
     "args": ["--invert"]},
    {"engine": "kepos", "tag": "kepos_soft",
     "mechanism": "eta-critical=0.75 sustained=5. Accept que candle eta nao atinge 0.95 em dados reais.",
     "args": ["--eta-critical", "0.75", "--eta-exit", "0.5", "--eta-sustained", "5"]},

    # ---------- MEDALLION ----------
    {"engine": "medallion", "tag": "medallion_default",
     "mechanism": "Baseline atual.",
     "args": []},
    {"engine": "medallion", "tag": "medallion_strict",
     "mechanism": "ensemble_threshold=0.7, kelly=0.25. Mais seletivo + sizing defensivo.",
     "args": ["--ensemble-threshold", "0.7", "--kelly-fraction", "0.25"]},
]


def _run_one(combo: dict, window_tag: str, window_spec: dict, out_base: Path) -> dict:
    engine = combo["engine"]
    tag = f"{combo['tag']}_{window_tag}"
    out_dir = out_base / "runs" / tag
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [PYTHON, f"engines/{engine}.py"]
    cmd += combo["args"]
    cmd += ["--days", str(window_spec["days"])]
    if window_spec["end"] is not None:
        cmd += ["--end", window_spec["end"]]

    # Some engines need --no-menu so they don't prompt
    if engine in ("deshaw", "kepos", "medallion"):
        cmd += ["--no-menu"]

    # Capture pre-run state so we can identify the NEW run dir even if two
    # runs land in the same wall-clock minute (timestamped dirs collide).
    engine_dir = REPO / "data" / engine
    engine_dir.mkdir(parents=True, exist_ok=True)
    existing_dirs = {p for p in engine_dir.iterdir() if p.is_dir()}

    print(f"  [{tag}] running: {' '.join(cmd)}")
    start = datetime.now()
    try:
        res = subprocess.run(
            cmd, cwd=REPO, capture_output=True, text=True, timeout=900,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {"tag": tag, "status": "TIMEOUT", "elapsed_s": 900}
    elapsed = (datetime.now() - start).total_seconds()
    if res.returncode != 0:
        (out_dir / "stderr.txt").write_text(res.stderr or "", encoding="utf-8")
        (out_dir / "stdout.txt").write_text(res.stdout or "", encoding="utf-8")
        return {"tag": tag, "status": f"EXIT {res.returncode}", "elapsed_s": elapsed}

    # Identify the run dir this subprocess produced (new, or touched this run).
    new_dirs = [p for p in engine_dir.iterdir()
                if p.is_dir() and (p not in existing_dirs or p.stat().st_mtime >= start.timestamp() - 5)]
    new_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    summary = None
    for cand in new_dirs[:5]:
        sfile = cand / "summary.json"
        if sfile.exists():
            try:
                d = json.loads(sfile.read_text(encoding="utf-8"))
                summary = d.get("summary", d)
                (out_dir / "summary.json").write_text(sfile.read_text(encoding="utf-8"), encoding="utf-8")
                break
            except Exception:
                continue
    if summary is None:
        (out_dir / "stdout.txt").write_text(res.stdout or "", encoding="utf-8")
        return {"tag": tag, "status": "NO_SUMMARY", "elapsed_s": elapsed}

    return {
        "tag": tag,
        "status": "OK",
        "elapsed_s": round(elapsed, 1),
        "engine": engine,
        "config": combo["tag"],
        "window": window_tag,
        "mechanism": combo["mechanism"],
        "n_trades": summary.get("total_trades", 0),
        "sharpe": summary.get("sharpe"),
        "sortino": summary.get("sortino"),
        "pf": summary.get("profit_factor"),
        "wr": summary.get("win_rate"),
        "mdd": summary.get("max_drawdown"),
        "pnl": summary.get("total_pnl"),
    }


def _fmt_row(r: dict) -> str:
    if r.get("status") != "OK":
        return f"| {r['tag']:<32} | {r['status']:<10} | - | - | - | - |"
    n = r["n_trades"] or 0
    sharpe = r.get("sharpe") or 0.0
    pf = r.get("pf") or 0.0
    wr = (r.get("wr") or 0.0) * 100
    pnl = r.get("pnl") or 0.0
    return (f"| {r['tag']:<32} | {n:>4} | "
            f"{sharpe:>+7.3f} | {pf:>6.3f} | {wr:>5.1f}% | {pnl:>+8.2f} |")


def main() -> int:
    run_id = datetime.now().strftime("%Y-%m-%d_%H%M")
    out_base = REPO / "data" / "_weak_salvage" / run_id
    out_base.mkdir(parents=True, exist_ok=True)

    print(f"Weak-engines salvage battery @ {run_id}")
    print(f"Output: {out_base}")
    print(f"Total runs: {len(GRID) * len(WINDOWS)}")
    print()

    all_results: list[dict] = []
    for combo in GRID:
        for window_tag, window_spec in WINDOWS:
            r = _run_one(combo, window_tag, window_spec, out_base)
            print(f"    -> {r.get('status')} | "
                  f"n={r.get('n_trades','-')} sharpe={r.get('sharpe','-')}")
            all_results.append(r)

    # Write machine-readable + human-readable reports
    (out_base / "report.json").write_text(
        json.dumps(all_results, indent=2, default=str), encoding="utf-8"
    )

    lines = ["# Weak Engines Salvage Battery", "",
             f"run_id: `{run_id}`", "",
             "## Results", "",
             "| Tag | N | Sharpe | PF | WR | PnL |",
             "|-----|---|--------|----|----|-----|"]
    for r in all_results:
        lines.append(_fmt_row(r))
    lines += ["", "## Mechanisms", ""]
    seen = set()
    for combo in GRID:
        if combo["tag"] in seen:
            continue
        seen.add(combo["tag"])
        lines.append(f"- **{combo['tag']}** — {combo['mechanism']}")

    (out_base / "report.md").write_text("\n".join(lines), encoding="utf-8")

    print()
    print("=" * 80)
    print("\n".join(lines[2:]))  # skip the header h1
    print("=" * 80)
    print(f"\nReports saved to: {out_base}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
