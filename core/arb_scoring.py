"""Compatibility shim — redirects core.arb_scoring to core.arb.arb_scoring.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.arb import arb_scoring as _impl
sys.modules[__name__] = _impl
