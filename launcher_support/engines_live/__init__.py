"""AURUM · Engines Live view — package split from engines_live_view.py.

This package owns the EXECUTE → ENGINES LIVE screen. It is split into:

- data/       pure data access (cockpit_api, procs, aggregate transforms)
- panes/      Tk widget factories for each layout region
- dialogs/    modal dialogs (new instance, LIVE ritual)
- widgets/    reusable Tk widgets (hold button, engine card, pill segment)

Top-level modules:
- view.py     orchestrator; owns repaint loop and pane lifecycle
- state.py    immutable StateSnapshot + reducer (pure)
- keyboard.py routing table for keyboard events (pure)
- helpers.py  re-exports of engines_live_helpers for backward compat

Threading:
- data/* modules run in background ThreadPoolExecutor
- UI updates MUST come back via root.after(0, fn)
- Panes/dialogs/widgets run only on the main Tk thread

Spec: docs/superpowers/specs/2026-04-23-engines-frontend-rebuild-design.md
"""
from __future__ import annotations
