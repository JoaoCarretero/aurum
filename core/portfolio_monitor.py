"""Compatibility shim — redirects core.portfolio_monitor to core.ui.portfolio_monitor.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.ui import portfolio_monitor as _impl
sys.modules[__name__] = _impl
