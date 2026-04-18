"""Compatibility shim — redirects core.versioned_state to core.ops.versioned_state.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.ops import versioned_state as _impl
sys.modules[__name__] = _impl
