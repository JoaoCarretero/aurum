"""Tests for Bloomberg 3D main menu redesign in launcher.py."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_launcher():
    spec = importlib.util.spec_from_file_location("launcher", ROOT / "launcher.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_tile_colors_defined():
    mod = _load_launcher()
    assert mod.TILE_MARKETS == "#ff8c00"
    assert mod.TILE_EXECUTE == "#00c864"
    assert mod.TILE_RESEARCH == "#33aaff"
    assert mod.TILE_CONTROL == "#c864c8"


def test_main_groups_shape():
    mod = _load_launcher()
    groups = mod.MAIN_GROUPS
    assert len(groups) == 4, "must be exactly 4 tiles"

    labels = [g[0] for g in groups]
    assert labels == ["MARKETS", "EXECUTE", "RESEARCH", "CONTROL"]

    for label, key_num, color, children in groups:
        assert isinstance(label, str) and label.isupper()
        assert key_num in {"1", "2", "3", "4"}
        assert color.startswith("#") and len(color) == 7
        assert isinstance(children, list) and 1 <= len(children) <= 3
        for child_label, method_name in children:
            assert isinstance(child_label, str)
            assert method_name.startswith("_")


def test_main_groups_cover_all_legacy_destinations():
    """Every destination callable in MAIN_MENU must still be reachable via MAIN_GROUPS."""
    mod = _load_launcher()
    legacy_keys = {key for _, key, _ in mod.MAIN_MENU}
    reachable_methods = {
        method for _, _, _, children in mod.MAIN_GROUPS
        for _, method in children
    }
    required_methods = {
        "_markets", "_connections", "_terminal", "_data_center",
        "_strategies", "_arbitrage_hub", "_risk_menu",
        "_command_center", "_config", "_crypto_dashboard",
    }
    missing = required_methods - reachable_methods
    assert not missing, f"MAIN_GROUPS missing destinations: {missing}"
