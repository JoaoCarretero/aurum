"""
AURUM Longrun Battery — 1 teste longo por engine, basket bluechip.

Runs (sequencial):
  CITADEL      → data/runs/citadel_<ts>/
  RENAISSANCE  → data/renaissance/<ts>/
  DE SHAW      → data/deshaw/<ts>/
  JUMP         → data/jump/<ts>/
  BRIDGEWATER  → data/bridgewater/<ts>/

Output:
  data/exports/longrun_battery_<ts>/
    manifest.json       — paths + metadata por engine
    <engine>.stdout.log — stdout/stderr completo de cada engine

Uso:
  python tools/longrun_battery.py                # default: 360d bluechip, 5 engines
  python tools/longrun_battery.py --smoke        # smoke: 30d, só citadel
  python tools/longrun_battery.py --days 180     # override days
  python tools/longrun_battery.py --engines citadel,jump   # subset
"""
import sys
import json
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent

# engine_key → (script_path, run_dir_parent, run_id_prefix)
# prefix é usado pra filtrar novos dirs (CITADEL prefixa com "citadel_", os outros não)
ENGINES = {
    "citadel":     ("engines/citadel.py",     "data/runs",         "citadel_"),
    "renaissance": ("engines/renaissance.py", "data/renaissance",  ""),
    "deshaw":      ("engines/deshaw.py",      "data/deshaw",       ""),
    "jump":        ("engines/jump.py",        "data/jump",         ""),
    "bridgewater": ("engines/bridgewater.py", "data/bridgewater",  ""),
}

def _snapshot(parent: Path, prefix: str) -> set[str]:
    if not parent.exists():
        return set()
    return {p.name for p in parent.iterdir() if p.is_dir() and p.name.startswith(prefix)}

def _run_engine(key: str, days: int, basket: str, export_dir: Path) -> dict:
    script, parent_rel, prefix = ENGINES[key]
    parent = ROOT / parent_rel
    parent.mkdir(parents=True, exist_ok=True)

    before = _snapshot(parent, prefix)
    log_path = export_dir / f"{key}.stdout.log"

    cmd = [sys.executable, str(ROOT / script),
           "--days", str(days), "--basket", basket, "--no-menu"]
    t0 = datetime.now()
    print(f"  [{t0.strftime('%H:%M:%S')}] {key.upper():<12} launching: {' '.join(cmd[1:])}")

    with open(log_path, "wb") as logf:
        rc = subprocess.call(cmd, cwd=str(ROOT), stdout=logf, stderr=subprocess.STDOUT)

    t1 = datetime.now()
    elapsed = (t1 - t0).total_seconds()

    after = _snapshot(parent, prefix)
    new_dirs = sorted(after - before)
    run_dir = str(parent / new_dirs[-1]) if new_dirs else None

    status = "ok" if rc == 0 and run_dir else "failed"
    print(f"  [{t1.strftime('%H:%M:%S')}] {key.upper():<12} {status}  rc={rc}  {elapsed/60:.1f}min  → {run_dir or 'no run dir'}")

    return {
        "engine": key,
        "status": status,
        "returncode": rc,
        "started_at": t0.isoformat(timespec="seconds"),
        "finished_at": t1.isoformat(timespec="seconds"),
        "elapsed_sec": round(elapsed, 1),
        "run_dir": run_dir,
        "log_path": str(log_path),
        "cmd": cmd,
    }

def main():
    ap = argparse.ArgumentParser(description="AURUM Longrun Battery")
    ap.add_argument("--days", type=int, default=360)
    ap.add_argument("--basket", default="bluechip")
    ap.add_argument("--engines", default="citadel,renaissance,deshaw,jump,bridgewater")
    ap.add_argument("--smoke", action="store_true", help="override: days=30, engines=citadel")
    args = ap.parse_args()

    if args.smoke:
        args.days = 30
        args.engines = "citadel"

    engine_list = [e.strip() for e in args.engines.split(",") if e.strip()]
    unknown = [e for e in engine_list if e not in ENGINES]
    if unknown:
        print(f"unknown engines: {unknown}. valid: {list(ENGINES)}")
        sys.exit(2)

    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    export_dir = ROOT / "data" / "exports" / f"longrun_battery_{ts}"
    export_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n  LONGRUN BATTERY  —  {len(engine_list)} engines  ·  {args.days}d  ·  basket={args.basket}")
    print(f"  export dir: {export_dir}")
    print(f"  {'─'*70}")

    results = []
    t_start = datetime.now()
    for key in engine_list:
        try:
            r = _run_engine(key, args.days, args.basket, export_dir)
        except Exception as e:
            r = {"engine": key, "status": "crashed", "error": str(e),
                 "started_at": datetime.now().isoformat(timespec="seconds")}
            print(f"  CRASHED {key}: {e}")
        results.append(r)

        # write manifest incrementally so partial runs are recoverable
        manifest = {
            "ts": ts,
            "days": args.days,
            "basket": args.basket,
            "engines_requested": engine_list,
            "started_at": t_start.isoformat(timespec="seconds"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "results": results,
        }
        (export_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

    t_end = datetime.now()
    manifest["finished_at"] = t_end.isoformat(timespec="seconds")
    manifest["total_elapsed_sec"] = round((t_end - t_start).total_seconds(), 1)
    (export_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    print(f"\n  {'─'*70}")
    ok = sum(1 for r in results if r.get("status") == "ok")
    print(f"  DONE  {ok}/{len(results)} ok  ·  total {manifest['total_elapsed_sec']/60:.1f}min")
    print(f"  manifest: {export_dir / 'manifest.json'}")

if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
