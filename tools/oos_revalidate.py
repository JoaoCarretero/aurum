"""OOS Audit Revalidation orchestrator (Bloco 0).

Dispara runs dos 7 engines em até 3 janelas OOS, colhe summary.json,
monta tabelas markdown pra docs/audits/2026-04-17_oos_revalidation.md.

Uso:
    python tools/oos_revalidate.py --window bear   # 2022-01..2023-01 (baseline redo)
    python tools/oos_revalidate.py --window bull   # 2020-07..2021-07
    python tools/oos_revalidate.py --window chop   # 2019-06..2020-03
    python tools/oos_revalidate.py --all           # roda as 3

Não salva nada em data/ além do output normal dos engines. Consolidação
final em audit doc é manual (Task 9).
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Window:
    slug: str  # bear/bull/chop
    end: str   # YYYY-MM-DD
    days: int  # 360


WINDOWS: dict[str, Window] = {
    "bear": Window("bear", "2023-01-01", 360),
    "bull": Window("bull", "2021-07-01", 360),
    "chop": Window("chop", "2020-03-01", 360),
}


@dataclass(frozen=True)
class EngineSpec:
    key: str         # registry key
    script: str      # path rel to repo
    interval: str    # default TF pro engine
    basket: str      # default basket
    out_dir: str     # onde o engine escreve data/<X>/<run>/


ENGINES: list[EngineSpec] = [
    EngineSpec("citadel",     "engines/citadel.py",     "15m", "default",  "data/runs"),
    EngineSpec("renaissance", "engines/renaissance.py", "15m", "bluechip", "data/renaissance"),
    EngineSpec("jump",        "engines/jump.py",        "1h",  "bluechip", "data/jump"),
    EngineSpec("deshaw",      "engines/deshaw.py",      "1h",  "bluechip", "data/deshaw"),
    EngineSpec("bridgewater", "engines/bridgewater.py", "1h",  "bluechip", "data/bridgewater"),
    EngineSpec("kepos",       "engines/kepos.py",       "15m", "bluechip", "data/kepos"),
    EngineSpec("medallion",   "engines/medallion.py",   "15m", "bluechip", "data/medallion"),
]


def run_engine(spec: EngineSpec, window: Window, timeout_s: int = 900) -> dict:
    """Dispara engine, retorna dict com status + path do summary.json."""
    before = _snapshot_runs(spec)
    cmd = [
        sys.executable, spec.script,
        "--no-menu",
        "--days", str(window.days),
        "--basket", spec.basket,
        "--interval", spec.interval,
        "--end", window.end,
    ]
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=str(REPO), capture_output=True, text=True, timeout=timeout_s,
        )
        elapsed = time.time() - t0
        after = _snapshot_runs(spec)
        new_runs = sorted(after - before)
        if not new_runs:
            return {
                "engine": spec.key, "window": window.slug,
                "status": "NO_RUN_DIR", "stderr_tail": proc.stderr[-500:],
                "elapsed_s": round(elapsed, 1),
            }
        latest = new_runs[-1]
        summary_path = REPO / spec.out_dir / latest / "summary.json"
        if not summary_path.exists():
            return {
                "engine": spec.key, "window": window.slug,
                "status": "NO_SUMMARY", "run_id": latest,
                "elapsed_s": round(elapsed, 1),
            }
        summary = json.loads(summary_path.read_text())
        return {
            "engine": spec.key, "window": window.slug,
            "status": "OK", "run_id": latest, "summary": summary,
            "elapsed_s": round(elapsed, 1),
        }
    except subprocess.TimeoutExpired:
        return {"engine": spec.key, "window": window.slug, "status": "TIMEOUT"}
    except Exception as e:
        return {"engine": spec.key, "window": window.slug,
                "status": "EXCEPTION", "error": str(e)}


def _snapshot_runs(spec: EngineSpec) -> set[str]:
    d = REPO / spec.out_dir
    if not d.exists():
        return set()
    return {p.name for p in d.iterdir() if p.is_dir()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", choices=list(WINDOWS.keys()), default=None)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--engine", choices=[e.key for e in ENGINES], default=None,
                        help="Roda só um engine (útil pra debug).")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    if args.all:
        windows_to_run = list(WINDOWS.values())
    elif args.window:
        windows_to_run = [WINDOWS[args.window]]
    else:
        parser.error("Use --window <bear|bull|chop> ou --all")

    engines_to_run = [e for e in ENGINES if not args.engine or e.key == args.engine]

    results = []
    for w in windows_to_run:
        for e in engines_to_run:
            print(f">>> {e.key:12s}  window={w.slug:4s}  end={w.end}  ...", flush=True)
            r = run_engine(e, w, timeout_s=args.timeout)
            print(f"    status={r['status']}  elapsed={r.get('elapsed_s', '?')}s")
            results.append(r)

    out = REPO / "data" / "audit" / "oos_revalidate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(f"\n[done] {len(results)} runs, json em {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
