#!/usr/bin/env python3
"""Run THOTH engine standalone."""
import subprocess, sys
from pathlib import Path
sys.exit(subprocess.call([sys.executable, str(Path(__file__).parent / "engines" / "thoth.py")]))
