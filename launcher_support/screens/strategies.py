"""Strategies engine-picker screen — BACKTEST / LIVE / TOOLS / ALL.

Extracted from launcher.App._strategies. Same interface: render(app,
filter_group=None) mounts the picker into app.main. filter_group in
{"BACKTEST", "LIVE", "TOOLS", None} scopes which engines appear; None
shows all groups. Pill click loops back through app._strategies (the
App delegate) so the recursive refresh keeps working.
"""
from __future__ import annotations

import threading as _th
import tkinter as tk

from core.ui.ui_palette import (
    AMBER, AMBER_D,
    BG, BG3,
    DIM, FONT,
    GREEN, RED, TILE_RESEARCH,
)
from launcher_support.briefings import BRIEFINGS, BRIEFINGS_V2


# Edge-engines explicit list — Sharpe OOS positivo confirmado (CITADEL,
# JUMP) ou real post-inflation (RENAISSANCE ~2.4) ou multi-strategy
# orchestrator (MILLENNIUM). Não é derivado de ENGINES[stage] porque só
# CITADEL tem stage="validated"; os outros 3 estão como "research" /
# "bootstrap_staging" mas o João trata como edge na lista do BACKTEST.
_EDGE_SLUGS: frozenset[str] = frozenset({
    "citadel",
    "jump",
    "renaissance",
    "millennium",
})


def render(app, filter_group: str | None = None):
    """Build the engine picker screen.

    Layout: one-line strip (rail + title + segmented pills + counts)
    followed by the picker host. Running engines are marked via
    core.ops.proc.list_procs() and surface progress through the
    core.engine_picker handle. BACKTEST view is pure research (no
    cross-navigation pills); LIVE/TOOLS/None show all segments.
    """
    app._clr()
    app._clear_kb()
    # MARKETS + _conn are App-module globals; accessed via app.__module__
    # here so the screen module stays independent from launcher.py.
    import launcher as _launcher_mod
    market_label = _launcher_mod.MARKETS.get(
        _launcher_mod._conn.active_market, {}
    ).get("label", "UNKNOWN")

    _titles = {
        "BACKTEST": ("BACKTEST", "research · walkforward · Monte Carlo", TILE_RESEARCH),
        "LIVE": ("ENGINES LIVE", "paper · demo · testnet · safety gates", "#ff8c00"),
        "TOOLS": ("TOOLS", "utilities · research labs", AMBER_D),
        None: ("STRATEGIES", "all engines across groups", AMBER),
    }
    title, subtitle, title_hue = _titles.get(filter_group, _titles[None])
    app.h_path.configure(text=f"> {title}")
    app.h_stat.configure(text=market_label, fg=AMBER_D)
    app.f_lbl.configure(text="ESC main  |  ▲▼ select  |  ENTER run")
    app._kb("<Escape>", lambda: app._menu("main"))
    app._kb("<Key-0>", lambda: app._menu("main"))
    app._bind_global_nav()

    # Compact layout: ONE-LINE strip (rail · title · pills · counts) + picker.
    # Subtitle e MARKET chip removidos — h_path/h_stat já mostram contexto.
    root = tk.Frame(app.main, bg=BG)
    root.pack(fill="both", expand=True, padx=14, pady=10)

    # -- Single header strip: rail · title · pills · counts --
    strip = tk.Frame(root, bg=BG)
    strip.pack(fill="x")
    tk.Frame(strip, bg=title_hue, width=3, height=22).pack(
        side="left", padx=(0, 8))
    tk.Label(strip, text=title, font=(FONT, 12, "bold"),
             fg=title_hue, bg=BG).pack(side="left", padx=(0, 14))

    # Segmented pills inline with title.
    # BACKTEST should be a pure research surface, without the old
    # TOOLS/ALL cross-navigation noise.
    if filter_group == "BACKTEST":
        segments = []
    else:
        segments = [
            ("BACKTEST", "BACKTEST", TILE_RESEARCH),
            ("ENGINES", "LIVE", "#ff8c00"),
            ("TOOLS", "TOOLS", AMBER_D),
            ("ALL", None, AMBER),
        ]
    for seg_label, grp, hue in segments:
        active = grp == filter_group
        fg = "#000000" if active else hue
        bg = hue if active else BG3
        b = tk.Label(strip, text=f" {seg_label} ",
                     font=(FONT, 7, "bold"),
                     fg=fg, bg=bg, padx=8, pady=3,
                     cursor="hand2")
        b.pack(side="left", padx=(0, 3))
        if not active:
            b.bind("<Button-1>",
                   lambda _e, _g=grp: app._strategies(filter_group=_g))
            b.bind("<Enter>",
                   lambda _e, _b=b, _h=hue: _b.configure(bg=_h, fg="#000000"))
            b.bind("<Leave>",
                   lambda _e, _b=b, _h=hue: _b.configure(bg=BG3, fg=_h))

    # Status filter — só pra view BACKTEST. Triagem por stage do engine.
    status_filter = None
    if filter_group == "BACKTEST":
        status_filter = getattr(app, "_strategies_status_filter", None)
        # Separador visual discreto entre o rail/título e as pills de status
        tk.Frame(strip, bg=BG3, width=1, height=16).pack(
            side="left", padx=(4, 8))
        status_pills = [
            ("ALL",      None,        DIM),
            ("EDGE",     "EDGE",      GREEN),
            ("TESTING",  "TESTING",   AMBER),
            ("ARCHIVED", "ARCHIVED",  RED),
        ]
        for pill_label, pill_val, pill_hue in status_pills:
            active = pill_val == status_filter
            fg = "#000000" if active else pill_hue
            bg = pill_hue if active else BG3
            b = tk.Label(strip, text=f" {pill_label} ",
                         font=(FONT, 7, "bold"),
                         fg=fg, bg=bg, padx=8, pady=3,
                         cursor="hand2")
            b.pack(side="left", padx=(0, 3))
            if not active:
                def _apply(_e=None, _v=pill_val):
                    app._strategies_status_filter = _v
                    app._strategies(filter_group="BACKTEST")
                b.bind("<Button-1>", _apply)
                b.bind("<Enter>",
                       lambda _e, _b=b, _h=pill_hue: _b.configure(bg=_h, fg="#000000"))
                b.bind("<Leave>",
                       lambda _e, _b=b, _h=pill_hue: _b.configure(bg=BG3, fg=_h))

    # Right-side counts pill (populated after tracks load)
    counts_lbl = tk.Label(strip, text="", font=(FONT, 7, "bold"),
                          fg=DIM, bg=BG, padx=6)
    counts_lbl.pack(side="right")

    tk.Frame(root, bg=title_hue, height=1).pack(fill="x", pady=(8, 8))

    # Picker host — takes the rest of the screen
    picker_host = tk.Frame(root, bg=BG)
    picker_host.pack(fill="both", expand=True)

    # expose counts label so the later block can fill it in
    app._strategies_counts_lbl = counts_lbl
    # kept for compat with old code further down that expects `panel`
    panel = root

    try:
        from config.engines import ENGINES
        from core import engine_picker as ep
        from core.ops.proc import list_procs, stop_proc
    except Exception as e:
        tk.Label(picker_host, text=f"picker unavailable: {e}",
                 font=(FONT, 9), fg=RED, bg=BG).pack(pady=20)
        app._ui_back_row(panel, lambda: app._menu("main"))
        return

    _group_parent = {"BACKTEST": "backtest", "LIVE": "live", "TOOLS": "tools"}
    _proc_to_slug = {
        "backtest": "citadel",
        "mercurio": "jump",
        "thoth": "bridgewater",
        "newton": "deshaw",
        "multi": "millennium",
        "prometeu": "twosigma",
        "renaissance": "renaissance",
        "live": "live",
        "arb": "janestreet",
        "darwin": "aqr",
        "chronos": "winton",
    }
    running_map = {}
    try:
        for proc in list_procs():
            if proc.get("status") != "running" or not proc.get("alive"):
                continue
            slug = _proc_to_slug.get(proc.get("engine"))
            if slug:
                running_map[slug] = proc
    except Exception:
        running_map = {}

    def _run_for(slug, meta):
        name = meta.get("display", slug.upper())
        script = meta.get("script", "")
        desc = meta.get("desc", "")
        group = ep.DEFAULT_GROUPS.get(slug, "BACKTEST")
        parent_key = _group_parent.get(group, "backtest")
        is_live_view = filter_group == "LIVE"

        def _run(cfg=None,
                 n=name, s=script, d=desc, k=parent_key,
                 live=is_live_view):
            preset = (cfg or {}).get("preset", "custom")
            # LIVE view — RUN chip produces preset in {paper,demo,testnet,live}
            if live and preset in ("paper", "demo", "testnet", "live"):
                app._exec_live_inline(n, s, d, preset, cfg)
                return
            # BACKTEST inline
            if k == "backtest" and cfg:
                app._exec_backtest_inline(n, s, d, k, cfg)
                return
            # Fallback — brief screen
            app._brief(n, s, d, k)

        return _run

    def _stop_for(slug, _meta):
        def _stop():
            proc = running_map.get(slug)
            inline = getattr(app, "_strategies_inline_runs", {}).get(slug)
            try:
                if proc:
                    stop_proc(int(proc["pid"]), expected=proc)
                elif inline:
                    stop_proc(int(inline["pid"]))
            except Exception:
                return
            try:
                handle = getattr(app, "_strategies_picker", None)
                if handle:
                    handle["set_progress"](slug, 0.0, "stopped by operator", False)
            except Exception:
                pass
        return _stop

    def _brief_for(_slug, meta):
        """Merge BRIEFINGS (narrative) + BRIEFINGS_V2 (tecnico) num unico
        dict pro picker. V2 acrescenta formulas, params tecnicos e
        invariants que o chip BRIEF renderiza como math/entry explicito.
        """
        name = meta.get("display", _slug.upper())
        narrative = BRIEFINGS.get(name, {})
        tech = BRIEFINGS_V2.get(name, {})
        if not narrative and not tech:
            return None
        merged = dict(narrative)
        if tech:
            merged["one_liner"]    = tech.get("one_liner")
            merged["formulas"]     = tech.get("formulas")
            merged["params_tech"]  = tech.get("params")
            merged["invariants"]   = tech.get("invariants")
            merged["pseudocode"]   = tech.get("pseudocode")
            merged["source_files"] = tech.get("source_files")
        return merged

    tracks = ep.build_tracks_from_registry(
        ENGINES, on_run_for=_run_for, on_stop_for=_stop_for, brief_for=_brief_for,
    )
    for t in tracks:
        if t.slug in running_map:
            t.status = "running"
    if filter_group:
        # LIVE view now has its own cockpit (_strategies_live) — the
        # only remaining filter_group values that hit this path are
        # "BACKTEST" and "TOOLS".
        tracks = [t for t in tracks if t.group == filter_group]

    # Status filter — aplicado só pra BACKTEST. Buckets:
    #   EDGE     → _EDGE_SLUGS (lista explicita; ver comentario no topo)
    #   ARCHIVED → EXPERIMENTAL_SLUGS (canonical) + quarantined stage
    #   TESTING  → tudo em BACKTEST que nao cai em EDGE nem ARCHIVED
    total_before_status = len(tracks)
    if filter_group == "BACKTEST" and status_filter is not None:
        from config.engines import EXPERIMENTAL_SLUGS as _ARCHIVED_SLUGS

        def _in_bucket(t) -> bool:
            slug = t.slug
            stage = str(getattr(t, "stage", "") or "").lower()
            archived = slug in _ARCHIVED_SLUGS or stage == "quarantined"
            edge = slug in _EDGE_SLUGS
            if status_filter == "EDGE":
                return edge
            if status_filter == "ARCHIVED":
                return archived
            if status_filter == "TESTING":
                return not edge and not archived
            return True

        tracks = [t for t in tracks if _in_bucket(t)]

    # Counts pill — only RUNNING is meaningful, rest is noise
    running_n = sum(1 for t in tracks if t.status == "running")
    if filter_group == "BACKTEST" and status_filter is not None:
        counts_txt = f"{len(tracks)}/{total_before_status} {status_filter}"
    else:
        counts_txt = f"{len(tracks)} ENGINES"
    if running_n:
        counts_txt += f"  ·  {running_n} RUNNING"
    try:
        app._strategies_counts_lbl.configure(text=counts_txt, fg=AMBER_D)
    except Exception:
        pass

    picker_mode = "backtest"
    handle = ep.render(picker_host, tracks, mode=picker_mode)
    app._strategies_picker = handle

    # Hydrate metrics in background so render is instant. The DB query
    # is fast (<20ms) but doing it on the main thread before render
    # makes the menu feel "travado" on slower disks/OneDrive sync.
    _th.Thread(
        target=app._strategies_hydrate_metrics,
        args=(tracks, handle),
        daemon=True,
    ).start()
    for slug, proc in running_map.items():
        try:
            handle["set_progress"](slug, 6.0, f"managed pid {proc.get('pid')} | already running", True)
        except Exception:
            pass

    app._kb("<Down>", lambda: handle["delta"](+1))
    app._kb("<Up>", lambda: handle["delta"](-1))
    app._kb("<Return>", lambda: handle["run_current"]())
