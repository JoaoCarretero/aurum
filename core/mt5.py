"""Compatibility shim — redirects core.mt5 to core.ops.mt5.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.ops import mt5 as _impl
sys.modules[__name__] = _impl
