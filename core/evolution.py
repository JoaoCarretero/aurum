"""Compatibility shim — redirects core.evolution to core.analysis.evolution.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.analysis import evolution as _impl
sys.modules[__name__] = _impl
