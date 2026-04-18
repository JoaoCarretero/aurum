"""Compatibility shim — redirects core.engine_base to core.ops.engine_base.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.ops import engine_base as _impl
sys.modules[__name__] = _impl
