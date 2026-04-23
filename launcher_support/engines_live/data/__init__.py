"""Data layer: cockpit_api client, procs snapshot, pure aggregation.

IMPORTANT: Modules in this package MUST NOT import tkinter. They run in
background threads; any UI callback must be dispatched via root.after(0, fn)
by the caller (view.py).
"""
