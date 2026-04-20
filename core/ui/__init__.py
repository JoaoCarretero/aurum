"""Canonical UI package surface.

The top-level ``core.*`` UI modules remain available as compatibility
shims, but new code should import dashboard/UI helpers through
``core.ui``.
"""
from __future__ import annotations

from importlib import import_module

_LAZY = {
    "PortfolioMonitor": "core.ui.portfolio_monitor:PortfolioMonitor",
    "FundingScanner": "core.ui.funding_scanner:FundingScanner",
    "FundingOpp": "core.ui.funding_scanner:FundingOpp",
    "SpotPrice": "core.ui.funding_scanner:SpotPrice",
    "TickDriver": "core.ui.alchemy_ui:TickDriver",
    "render_cockpit": "core.ui.alchemy_ui:render_cockpit",
    "load_fonts": "core.ui.alchemy_ui:load_fonts",
    "font": "core.ui.alchemy_ui:font",
    "make_panel": "core.ui.alchemy_ui:make_panel",
    "hazard_strip": "core.ui.alchemy_ui:hazard_strip",
}


def __getattr__(name: str):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module 'core.ui' has no attribute {name!r}")
    modname, attr = target.split(":", 1)
    value = getattr(import_module(modname), attr)
    globals()[name] = value
    return value


def __dir__():
    return sorted(list(_LAZY.keys()) + list(globals().keys()))


__all__ = list(_LAZY.keys())
