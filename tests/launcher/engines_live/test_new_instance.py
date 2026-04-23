"""Smoke tests for dialogs/new_instance.py."""
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


def test_import_open_new_instance_dialog():
    from launcher_support.engines_live.dialogs import new_instance
    assert callable(new_instance.open_new_instance_dialog)


def test_build_widgets_initializes_with_default_mode(root):
    from launcher_support.engines_live.dialogs.new_instance import _build_dialog_widgets

    top, widgets = _build_dialog_widgets(root, engine="citadel", default_mode="demo")
    try:
        assert widgets["mode_pills"].active == "DEMO"
        assert widgets["target_pills"].active == "LOCAL"
        assert widgets["label_var"].get() == ""
    finally:
        top.destroy()


def test_preview_updates_when_mode_changes(root):
    from launcher_support.engines_live.dialogs.new_instance import (
        _build_dialog_widgets,
        _refresh_preview,
    )

    top, widgets = _build_dialog_widgets(root, engine="citadel", default_mode="paper")
    try:
        widgets["mode_pills"].set_active("LIVE")
        _refresh_preview(widgets, engine="citadel")
        preview_text = str(widgets["preview"].cget("text"))
        assert "mode=live" in preview_text.lower() or "--mode=live" in preview_text.lower()
    finally:
        top.destroy()


def test_confirm_populates_result_cell(root):
    from launcher_support.engines_live.dialogs.new_instance import (
        _build_dialog_widgets,
        _on_confirm,
    )

    top, widgets = _build_dialog_widgets(root, engine="citadel", default_mode="paper")
    try:
        widgets["mode_pills"].set_active("DEMO")
        widgets["label_var"].set("mytest")
        widgets["target_pills"].set_active("VPS")

        result = {"value": None}
        _on_confirm(top, widgets, result)
        # top was destroyed inside _on_confirm — don't call operations on it
        assert result["value"] is not None
        assert result["value"]["mode"] == "demo"
        assert result["value"]["target"] == "vps"
        # label was sanitized
        assert result["value"]["label"] == "mytest"
    finally:
        if top.winfo_exists():
            top.destroy()
