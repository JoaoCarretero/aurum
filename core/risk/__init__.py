"""Canonical risk package surface.

New code should import risk gates through ``core.risk``. The historical
``core.risk_gates`` module remains a compatibility shim for older code
and monkey-patched tests.
"""
from __future__ import annotations

from importlib import import_module

_LAZY = {
    "RiskGateConfig": "core.risk.risk_gates:RiskGateConfig",
    "RiskState": "core.risk.risk_gates:RiskState",
    "GateDecision": "core.risk.risk_gates:GateDecision",
    "check_gates": "core.risk.risk_gates:check_gates",
    "load_gate_config": "core.risk.risk_gates:load_gate_config",
}


def __getattr__(name: str):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module 'core.risk' has no attribute {name!r}")
    modname, attr = target.split(":", 1)
    value = getattr(import_module(modname), attr)
    globals()[name] = value
    return value


def __dir__():
    return sorted(list(_LAZY.keys()) + list(globals().keys()))


__all__ = list(_LAZY.keys())
