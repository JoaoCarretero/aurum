"""Compatibility shim — redirects core.fixture_capture to core.ops.fixture_capture.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.ops import fixture_capture as _impl
sys.modules[__name__] = _impl
