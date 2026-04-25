"""Tests do TabStrip widget."""
from __future__ import annotations
import tkinter as tk

from launcher_support.research_desk.tab_strip import TabStrip


def test_tab_strip_click_fires_callback():
    root = tk.Tk()
    try:
        selected = []
        strip = TabStrip(
            root,
            tabs=[("overview", "OVERVIEW"), ("RESEARCH", "RESEARCH")],
            on_select=lambda k: selected.append(k),
            initial_key="overview",
        )
        label = strip._labels["RESEARCH"]
        label.event_generate("<Button-1>")
        assert selected == ["RESEARCH"]
    finally:
        root.destroy()


def test_tab_strip_set_active_updates_visual_without_firing_callback():
    root = tk.Tk()
    try:
        selected = []
        strip = TabStrip(
            root,
            tabs=[("overview", "OVERVIEW"), ("BUILD", "BUILD")],
            on_select=lambda k: selected.append(k),
            initial_key="overview",
        )
        strip.set_active("BUILD")
        assert selected == []
        assert strip._active == "BUILD"
    finally:
        root.destroy()


def test_tab_strip_initial_key_is_active():
    root = tk.Tk()
    try:
        strip = TabStrip(
            root, tabs=[("a", "A"), ("b", "B")],
            on_select=lambda _k: None, initial_key="b",
        )
        assert strip._active == "b"
    finally:
        root.destroy()
