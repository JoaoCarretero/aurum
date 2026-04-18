"""Compatibility shim — redirects core.run_manager to core.ops.run_manager.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.ops import run_manager as _impl
sys.modules[__name__] = _impl
