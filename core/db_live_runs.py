"""Compatibility shim — redirects core.db_live_runs to core.ops.db_live_runs.
Mirrors the pattern in core/db.py so monkey-patching works in tests.
"""
import sys
from core.ops import db_live_runs as _impl
sys.modules[__name__] = _impl
