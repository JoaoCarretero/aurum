"""Tk pane factories. Each module exposes build_<name>(parent, state) -> Frame.

Panes read StateSnapshot and render Tk widgets. They MUST NOT mutate global
state or talk to data/ directly — view.py owns the pull loop.
"""
