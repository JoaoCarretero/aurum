"""Compatibility shim — redirects core.engine_picker to core.ops.engine_picker.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.ops import engine_picker as _impl
sys.modules[__name__] = _impl
