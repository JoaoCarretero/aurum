"""AURUM Core — reusable trading engine components.

Top-level re-exports are resolved lazily via PEP 562 __getattr__. This
keeps ``from core.ui.ui_palette import BG`` (and other narrow imports)
cheap — they no longer trigger eager pandas / indicator loading.

Callers that want the convenient ``from core import fetch`` or
``core.fetch`` still work unchanged — the first access triggers the real
import on demand.
"""
from __future__ import annotations

# Map attribute name -> "<submodule>:<attr>" to import on first access.
_LAZY = {
    # core.data
    "fetch": "core.data:fetch",
    "fetch_all": "core.data:fetch_all",
    "validate": "core.data:validate",
    # core.indicators (module + selected attrs)
    "indicators": "core.indicators:indicators",
    "swing_structure": "core.indicators:swing_structure",
    "omega": "core.indicators:omega",
    "cvd": "core.indicators:cvd",
    "cvd_divergence": "core.indicators:cvd_divergence",
    "volume_imbalance": "core.indicators:volume_imbalance",
    "liquidation_proxy": "core.indicators:liquidation_proxy",
    # core.signals
    "decide_direction": "core.signals:decide_direction",
    "score_omega": "core.signals:score_omega",
    "score_chop": "core.signals:score_chop",
    "calc_levels": "core.signals:calc_levels",
    "calc_levels_chop": "core.signals:calc_levels_chop",
    "label_trade": "core.signals:label_trade",
    "label_trade_chop": "core.signals:label_trade_chop",
    # core.portfolio
    "detect_macro": "core.portfolio:detect_macro",
    "build_corr_matrix": "core.portfolio:build_corr_matrix",
    "portfolio_allows": "core.portfolio:portfolio_allows",
    "check_aggregate_notional": "core.portfolio:check_aggregate_notional",
    "_wr": "core.portfolio:_wr",
    "position_size": "core.portfolio:position_size",
    # core.htf
    "prepare_htf": "core.htf:prepare_htf",
    "merge_all_htf_to_ltf": "core.htf:merge_all_htf_to_ltf",
}


def __getattr__(name: str):
    if name not in _LAZY:
        raise AttributeError(f"module 'core' has no attribute {name!r}")
    import importlib
    modname, attr = _LAZY[name].split(":")
    mod = importlib.import_module(modname)
    value = getattr(mod, attr)
    globals()[name] = value  # cache for subsequent accesses
    return value


# Resolve collisions eagerly: when a lazy attr shares its name with the
# submodule it lives in (e.g. ``indicators`` is both a submodule and a
# function inside it), Python's import machinery sets
# ``core.indicators = <submodule>`` as a side-effect of the first
# ``import core.indicators`` call elsewhere in the codebase — this
# shadows the lazy ``__getattr__`` and callers get the module instead
# of the function. Force-resolve these eagerly so ``from core import
# indicators`` always lands on the callable. Cheap: one import per
# colliding name (only ``indicators`` today, which the engines import
# immediately anyway).
def _resolve_shadow_collisions():
    import importlib
    for name, target in _LAZY.items():
        modname, attr = target.split(":")
        submodule_name = modname.rsplit(".", 1)[-1]
        if name == submodule_name:
            mod = importlib.import_module(modname)
            globals()[name] = getattr(mod, attr)


_resolve_shadow_collisions()


def __dir__():
    """Public attribute listing — lazy names + already-resolved public globals."""
    public_globals = {
        name for name in globals()
        if not name.startswith("_") and name != "annotations"
    }
    return sorted(set(_LAZY.keys()) | public_globals)


__all__ = list(_LAZY.keys())
