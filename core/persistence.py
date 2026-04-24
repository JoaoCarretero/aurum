"""Compatibility shim — redirects core.persistence to core.ops.persistence.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.ops import persistence as _impl
sys.modules[__name__] = _impl
