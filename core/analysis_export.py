"""Compatibility shim — redirects core.analysis_export to core.analysis.analysis_export.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.analysis import analysis_export as _impl
sys.modules[__name__] = _impl
