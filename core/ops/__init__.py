"""Canonical operational surface for non-trading core utilities.

This package is the preferred import path for filesystem / process /
runtime helpers that were split out of the historical ``core.*`` flat
namespace. Legacy root modules remain as compatibility shims.
"""
from __future__ import annotations

from importlib import import_module

_LAZY = {
    "EngineRuntime": "core.ops.engine_base:EngineRuntime",
    "HealthLedger": "core.ops.health:HealthLedger",
    "runtime_health": "core.ops.health:runtime_health",
    "atomic_write_text": "core.ops.persistence:atomic_write_text",
    "atomic_write_json": "core.ops.persistence:atomic_write_json",
    "atomic_write": "core.ops.fs:atomic_write",
    "robust_rmtree": "core.ops.fs:robust_rmtree",
    "SiteRunner": "core.ops.site_runner:SiteRunner",
    "MT5Bridge": "core.ops.mt5:MT5Bridge",
    "db": "core.ops.db",
    "proc": "core.ops.proc",
    "run_manager": "core.ops.run_manager",
    "versioned_state": "core.ops.versioned_state",
}


def __getattr__(name: str):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module 'core.ops' has no attribute {name!r}")
    if ":" in target:
        modname, attr = target.split(":", 1)
        value = getattr(import_module(modname), attr)
    else:
        value = import_module(target)
    globals()[name] = value
    return value


def __dir__():
    return sorted(list(_LAZY.keys()) + list(globals().keys()))


__all__ = list(_LAZY.keys())
