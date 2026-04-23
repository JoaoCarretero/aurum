"""Top-level orchestrator for the ENGINES LIVE view.

Lifecycle:
1. render(launcher, parent, on_escape) builds the initial frame and returns
   a handle dict with "frame", "state", "destroy" keys.
2. render schedules periodic tick_refresh() via launcher.after(30_000, ...).
3. Each tick_refresh:
   a. kicks off background fetches (cockpit runs, procs) via ThreadPoolExecutor
   b. once data arrives, builds an EngineCard list via data.aggregate
   c. compares to last_snapshot; if changed, calls update_* on affected panes
4. Keyboard bindings dispatch (focus, keysym) through keyboard.route(),
   then apply state reducers + side effects.
5. handle["destroy"]() cancels all after jobs and destroys the frame.

Threading: data fetches use a module-level ThreadPoolExecutor; results
posted back via launcher.after(0, ...). View state is only mutated on the
Tk main thread (inside _done callbacks).
"""
from __future__ import annotations

import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from core.ui.ui_palette import BG
from launcher_support.engines_live import keyboard, state as statemod
from launcher_support.engines_live.data import aggregate, cockpit, procs
from launcher_support.engines_live.panes import (
    detail, footer, header, research_shelf, strip_grid,
)


_REFRESH_MS = 30_000

_executor = ThreadPoolExecutor(max_workers=2)


def render(
    launcher: Any,
    parent: tk.Widget,
    *,
    on_escape: Callable[[], None],
) -> dict:
    frame = tk.Frame(parent, bg=BG)
    frame.pack(fill="both", expand=True)

    ui_state: dict[str, Any] = {
        "snapshot": statemod.empty_state(),
        "data": {
            "cards": [],
            "runs": [],
            "not_running_engines": [],
            "instances": [],
            "kpis": {},
            "log_lines": [],
            "global_stats": {},
            "engine_display": "",
        },
    }
    after_jobs: list[Any] = []

    # --- Build panes ---
    hdr = header.build_header(frame, ui_state["snapshot"])
    hdr.pack(fill="x")

    # Forward-declare for closures; these are assigned below but lambdas
    # resolve names at call-time via Python's closure mechanism.
    panes: dict[str, Any] = {}

    grid = strip_grid.build_strip_grid(
        frame, cards=[], selected_engine=None,
        on_select=lambda eng: _handle_select(ui_state, panes, eng),
    )
    grid.pack(fill="x", pady=(6, 0))

    shelf = research_shelf.build_shelf(
        frame, not_running_engines=[], expanded=False,
        on_toggle=lambda: _handle_toggle_shelf(ui_state, panes),
        on_select=lambda eng: _handle_research_select(launcher, ui_state, eng),
    )
    shelf.pack(fill="x", pady=(6, 0))

    det = detail.build_detail(frame, ui_state["snapshot"], ui_state["data"])
    det.pack(fill="both", expand=True, pady=(6, 0))

    ftr = footer.build_footer(frame, ui_state["snapshot"])
    ftr.pack(fill="x", side="bottom")

    panes["hdr"] = hdr
    panes["grid"] = grid
    panes["shelf"] = shelf
    panes["det"] = det
    panes["ftr"] = ftr

    # --- Keyboard ---
    def _on_key(event):
        snap = ui_state["snapshot"]
        action = keyboard.route(snap, event.keysym)
        if action is None:
            return
        _apply_action(launcher, ui_state, panes, action, on_escape=on_escape)

    frame.bind_all("<Key>", _on_key)

    # --- Periodic refresh ---
    def _tick():
        _refresh_data(launcher, ui_state, panes)
        job = launcher.after(_REFRESH_MS, _tick)
        if job is not None:
            after_jobs.append(job)

    first_job = launcher.after(200, _tick)
    if first_job is not None:
        after_jobs.append(first_job)

    def _destroy():
        try:
            frame.unbind_all("<Key>")
        except Exception:
            pass
        for j in after_jobs:
            try:
                launcher.after_cancel(j)
            except Exception:
                pass
        try:
            frame.destroy()
        except Exception:
            pass

    return {
        "frame": frame,
        "state": ui_state,
        "destroy": _destroy,
    }


def _refresh_data(launcher: Any, ui_state: dict, panes: dict) -> None:
    def _worker():
        procs_rows = procs.list_procs()
        runs = cockpit.runs_cached()
        enriched = _enrich_procs(procs_rows, runs)
        cards = aggregate.build_engine_cards(enriched)
        return cards, runs

    def _done(cards, runs):
        ui_state["data"]["cards"] = cards
        ui_state["data"]["runs"] = runs
        strip_grid.update_strip_grid(
            panes["grid"], cards, ui_state["snapshot"].selected_engine,
        )
        detail.update_detail(
            panes["det"], ui_state["snapshot"], ui_state["data"],
        )
        header.update_header(panes["hdr"], ui_state["snapshot"])

    def _run():
        try:
            cards, runs = _worker()
        except Exception:
            return
        try:
            launcher.after(0, lambda: _done(cards, runs))
        except Exception:
            pass

    _executor.submit(_run)


def _enrich_procs(procs_rows: list[dict], runs: list[dict]) -> list[dict]:
    """Merge heartbeat + run data into proc rows."""
    runs_by_id = {r.get("run_id"): r for r in runs if r.get("run_id")}
    enriched: list[dict] = []
    for p in procs_rows:
        run_id = p.get("run_id")
        row = dict(p)
        run = runs_by_id.get(run_id) or {}
        row["ticks_ok"] = int(run.get("tick_count") or 0)
        row["novel_total"] = int(run.get("novel_count") or 0)
        row["equity"] = run.get("equity")
        row["ticks_fail"] = int(run.get("ticks_fail") or 0)
        enriched.append(row)
    return enriched


def _handle_select(ui_state: dict, panes: dict, engine: str) -> None:
    ui_state["snapshot"] = statemod.select_engine(ui_state["snapshot"], engine)
    strip_grid.update_strip_grid(
        panes["grid"], ui_state["data"]["cards"], engine,
    )
    detail.update_detail(panes["det"], ui_state["snapshot"], ui_state["data"])
    footer.update_footer(panes["ftr"], ui_state["snapshot"])


def _handle_toggle_shelf(ui_state: dict, panes: dict) -> None:
    ui_state["snapshot"] = statemod.toggle_shelf(ui_state["snapshot"])
    research_shelf.update_shelf(
        panes["shelf"],
        ui_state["data"].get("not_running_engines", []),
        ui_state["snapshot"].shelf_expanded,
    )


def _handle_research_select(launcher: Any, ui_state: dict, engine: str) -> None:
    from launcher_support.engines_live.dialogs.new_instance import (
        open_new_instance_dialog,
    )
    open_new_instance_dialog(
        launcher, engine, default_mode=ui_state["snapshot"].mode,
    )


def _apply_action(
    launcher: Any,
    ui_state: dict,
    panes: dict,
    action: Any,
    *,
    on_escape: Callable[[], None],
) -> None:
    from launcher_support.engines_live.keyboard import (
        BackToStrip,
        CycleFocus,
        CycleMode,
        ExitView,
        ToggleFollowTail,
        ToggleShelf,
    )

    snap = ui_state["snapshot"]

    if isinstance(action, ExitView):
        on_escape()
        return
    if isinstance(action, BackToStrip):
        ui_state["snapshot"] = statemod.reset_selection(snap)
    elif isinstance(action, CycleFocus):
        ui_state["snapshot"] = statemod.tab_focus(snap)
    elif isinstance(action, CycleMode):
        ui_state["snapshot"] = statemod.cycle_mode_state(snap)
    elif isinstance(action, ToggleShelf):
        ui_state["snapshot"] = statemod.toggle_shelf(snap)
    elif isinstance(action, ToggleFollowTail):
        ui_state["snapshot"] = statemod.toggle_follow(snap)
    else:
        # Other actions (Stop/Restart/Open*/Telegram) are dispatched by the
        # launcher-level integration in R4 — no-op here.
        return

    # Repaint affected panes
    header.update_header(panes["hdr"], ui_state["snapshot"])
    strip_grid.update_strip_grid(
        panes["grid"], ui_state["data"]["cards"],
        ui_state["snapshot"].selected_engine,
    )
    detail.update_detail(panes["det"], ui_state["snapshot"], ui_state["data"])
    footer.update_footer(panes["ftr"], ui_state["snapshot"])
    research_shelf.update_shelf(
        panes["shelf"],
        ui_state["data"].get("not_running_engines", []),
        ui_state["snapshot"].shelf_expanded,
    )
