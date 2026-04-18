"""Compatibility shim — redirects core.site_runner to core.ops.site_runner.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.ops import site_runner as _impl
sys.modules[__name__] = _impl
