"""Compatibility shim — redirects core.health to core.ops.health.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.ops import health as _impl
sys.modules[__name__] = _impl
