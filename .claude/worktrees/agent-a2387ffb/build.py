#!/usr/bin/env python3
"""
Build AURUM Finance into standalone .exe files
Usage: python build.py
"""
import PyInstaller.__main__
import sys
from pathlib import Path

ROOT = Path(__file__).parent

# ── BUILD 1: GUI Launcher (windowed) ──
print("Building AURUM Launcher (GUI)...")
PyInstaller.__main__.run([
    str(ROOT / "launcher.py"),
    "--name=AURUM",
    "--onefile",
    "--windowed",
    f"--icon={ROOT / 'server' / 'logo' / 'logo_04_favicon.png'}",
    # Include all packages
    "--hidden-import=config",
    "--hidden-import=config.params",
    "--hidden-import=core",
    "--hidden-import=core.data",
    "--hidden-import=core.db",
    "--hidden-import=core.indicators",
    "--hidden-import=core.signals",
    "--hidden-import=core.portfolio",
    "--hidden-import=core.htf",
    "--hidden-import=core.proc",
    "--hidden-import=core.sentiment",
    "--hidden-import=core.evolution",
    "--hidden-import=core.chronos",
    "--hidden-import=engines",
    "--hidden-import=engines.backtest",
    "--hidden-import=engines.live",
    "--hidden-import=engines.newton",
    "--hidden-import=engines.mercurio",
    "--hidden-import=engines.thoth",
    "--hidden-import=engines.prometeu",
    "--hidden-import=engines.darwin",
    "--hidden-import=engines.multistrategy",
    "--hidden-import=engines.arbitrage",
    "--hidden-import=analysis",
    "--hidden-import=analysis.stats",
    "--hidden-import=analysis.montecarlo",
    "--hidden-import=analysis.walkforward",
    "--hidden-import=analysis.robustness",
    "--hidden-import=analysis.benchmark",
    "--hidden-import=analysis.plots",
    "--hidden-import=bot",
    "--hidden-import=bot.telegram",
    # Data files
    f"--add-data={ROOT / 'config'}:config",
    # Optimize
    "--noupx",
    "--clean",
    # Work dirs
    f"--distpath={ROOT / 'dist'}",
    f"--workpath={ROOT / 'build'}",
    f"--specpath={ROOT}",
])

print("\n" + "=" * 50)
print("  dist/AURUM.exe  (GUI launcher)")
print("=" * 50)
