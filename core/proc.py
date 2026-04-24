"""Compatibility shim — redirects core.proc to core.ops.proc.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.ops import proc as _impl
sys.modules[__name__] = _impl
