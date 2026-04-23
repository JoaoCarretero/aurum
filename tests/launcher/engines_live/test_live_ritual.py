"""Smoke tests for dialogs/live_ritual.py."""
from __future__ import annotations

import tkinter as tk

import pytest


@pytest.fixture
def root():
    try:
        r = tk.Tk()
        r.withdraw()
    except tk.TclError:
        pytest.skip("no display")
    yield r
    r.destroy()


def test_import_open_live_ritual():
    from launcher_support.engines_live.dialogs import live_ritual
    assert callable(live_ritual.open_live_ritual)


def test_confirm_disabled_until_name_matches(root):
    from launcher_support.engines_live.dialogs.live_ritual import (
        _build_ritual_widgets,
        _refresh_confirm_state,
    )

    top, widgets = _build_ritual_widgets(root, engine="citadel")
    try:
        # Initially empty
        _refresh_confirm_state(widgets, engine="citadel")
        assert str(widgets["confirm"].cget("state")) == "disabled"

        widgets["name_var"].set("wrong")
        _refresh_confirm_state(widgets, engine="citadel")
        assert str(widgets["confirm"].cget("state")) == "disabled"

        widgets["name_var"].set("citadel")
        _refresh_confirm_state(widgets, engine="citadel")
        assert str(widgets["confirm"].cget("state")) == "normal"
    finally:
        top.destroy()


def test_confirm_case_sensitive(root):
    from launcher_support.engines_live.dialogs.live_ritual import (
        _build_ritual_widgets,
        _refresh_confirm_state,
    )

    top, widgets = _build_ritual_widgets(root, engine="citadel")
    try:
        widgets["name_var"].set("Citadel")
        _refresh_confirm_state(widgets, engine="citadel")
        assert str(widgets["confirm"].cget("state")) == "disabled"
    finally:
        top.destroy()


def test_cancel_returns_false(root):
    from launcher_support.engines_live.dialogs.live_ritual import (
        _build_ritual_widgets,
        _on_cancel_ritual,
    )

    top, widgets = _build_ritual_widgets(root, engine="citadel")
    try:
        result = {"value": True}  # start True so we can assert it flips to False
        _on_cancel_ritual(top, result)
        assert result["value"] is False
    finally:
        if top.winfo_exists():
            top.destroy()
