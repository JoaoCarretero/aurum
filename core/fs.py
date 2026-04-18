"""Compatibility shim — redirects core.fs to core.ops.fs.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.ops import fs as _impl
sys.modules[__name__] = _impl
