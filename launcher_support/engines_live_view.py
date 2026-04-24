"""AURUM — ENGINES LIVE cockpit view.

Hybrid master-detail UI for the EXECUTE → ENGINES LIVE entry.
Separates engines into three buckets by readiness:

    LIVE        — currently running live/demo/testnet/paper
    READY       — has a validated live runner (ENGINES[*].live_ready)
    RESEARCH    — backtest-only, not exposed for live execution

Pure helpers here are testable; Tkinter rendering is smoke-tested
via `python launcher.py` → EXECUTE → ENGINES LIVE.

Spec: docs/superpowers/specs/2026-04-16-engines-live-cockpit-design.md
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from core.ops.python_runtime import preferred_python_executable
from core.ops import run_catalog
from core.risk.key_store import KeyStoreError, load_runtime_keys
from core.ui.ui_palette import (
    BG, BG2, BG3, PANEL,
    BORDER, BORDER_H,
    AMBER, AMBER_B, AMBER_D, WHITE, DIM, DIM2,
    GREEN, RED, CYAN, HAZARD,
    FONT,
)
from launcher_support.engines_sidebar import (
    render_detail,
)
from launcher_support.engines_live_helpers import (
    _MODE_ORDER, _REPO_ROOT,
    _MODE_COLORS, _ENGINE_DIR_MAP,
    _stage_badge,
    footer_hints,
    cockpit_summary,
    bucket_header_title,
    row_action_label,
    initial_selection,
    assign_bucket,
    cycle_mode,
    load_mode,
    save_mode,
    live_confirm_ok,
    format_uptime,
    _use_remote_shadow_cache,
    _safe_float,
    _uptime_seconds,
    running_slugs_from_procs,
    _sanitize_instance_label,
)
from launcher_support.screens._metrics import emit_timing_metric
# signal_detail_popup.render_inline eh chamado via engines_sidebar.render_detail
# (inline, sem Toplevel). show() legacy continua disponivel no modulo.

_PROCS_CACHE: dict[str, object] = {"ts": 0.0, "rows": []}
# TTLs raised to 60s. The paper/shadow runners tick every 15 min —
# rendering the detail pane more than once per minute gives the operator
# zero new information (heartbeat, equity, positions all update per-tick).
# Lower TTLs caused worker-driven rebuilds at 5s intervals: each cache
# miss fired a worker, the worker's completion scheduled a refresh, the
# refresh's sig-check saw new data (equity bumped by 0.01), rebuild of the
# whole detail pane fired. Net effect: 500-1000ms UI stall every few
# seconds. 60s matches the "inspect once per minute is enough" contract.
_COCKPIT_RUNS_CACHE_TTL_S = 60.0
_PAPER_SNAPSHOT_CACHE_TTL_S = 60.0
_SHADOW_SNAPSHOT_CACHE_TTL_S = 60.0
_COCKPIT_RUNS_CACHE: dict[str, object] = {"ts": 0.0, "runs": None, "loading": False}
_COCKPIT_RUNS_LOCK = threading.Lock()
_PAPER_SNAPSHOT_CACHE: dict[str, tuple[float, tuple[dict | None, list[dict], list[float], dict | None, list[dict]]]] = {}
_PAPER_SNAPSHOT_LOADING: set[str] = set()
_PAPER_SNAPSHOT_LOCK = threading.Lock()
_SHADOW_SNAPSHOT_CACHE: dict[str, tuple[float, tuple[Path | None, dict | None, list[dict]]]] = {}
_SHADOW_SNAPSHOT_LOADING = False
_SHADOW_SNAPSHOT_LOCK = threading.Lock()
_REMOTE_SHADOW_RUN_CACHE: dict[str, tuple[float, tuple[Path | None, dict | None, list[dict]]]] = {}
_REMOTE_SHADOW_RUN_LOADING: set[str] = set()
_REMOTE_SHADOW_RUN_LOCK = threading.Lock()


def _show_new_instance_dialog(launcher, state) -> None:
    """Toplevel dialog pra startar uma nova MILLENNIUM instance com label.

    Spawn local subprocess (paper ou shadow conforme mode atual).
    Corrida em processo separado, terminal novo no Windows pra output
    visivel. Run grava em data/millennium_{mode}/<run_id>/ normalmente
    e aparece em Runs History (le disco) apos o primeiro tick.

    Nao-bloqueante — dialog fecha imediatamente apos spawn. Multi-instance
    na VPS requer systemd template unit (Fase 6), nao coberto aqui.
    """
    import subprocess

    mode = state.get("mode") or "paper"
    if mode not in ("paper", "shadow"):
        _toast(launcher,
               f"NEW INSTANCE suporta paper/shadow, mode atual: {mode}",
               error=True)
        return

    dlg = tk.Toplevel(launcher)
    dlg.title("NEW INSTANCE")
    dlg.configure(bg=PANEL)
    dlg.transient(launcher)
    dlg.grab_set()
    try:
        dlg.geometry(f"360x220+{launcher.winfo_rootx() + 100}+"
                     f"{launcher.winfo_rooty() + 100}")
    except Exception:
        dlg.geometry("360x220")

    tk.Label(dlg, text=f"NEW  MILLENNIUM  {mode.upper()}",
             fg=AMBER, bg=PANEL, font=(FONT, 9, "bold")).pack(
             anchor="w", padx=14, pady=(12, 2))
    tk.Frame(dlg, bg=BORDER, height=1).pack(fill="x", padx=12, pady=(2, 10))

    # Label input
    tk.Label(dlg, text="LABEL (a-z, 0-9, -, max 40)", fg=DIM, bg=PANEL,
             font=(FONT, 6)).pack(anchor="w", padx=14)
    label_var = tk.StringVar()
    label_entry = tk.Entry(dlg, textvariable=label_var, bg=BG, fg=WHITE,
                           insertbackground=WHITE,
                           highlightbackground=BORDER, highlightthickness=1,
                           relief="flat", font=(FONT, 8))
    label_entry.pack(fill="x", padx=14, pady=(2, 8))

    # Account size (paper only)
    size_var = tk.StringVar(value="10000")
    if mode == "paper":
        tk.Label(dlg, text="ACCOUNT SIZE (USD)", fg=DIM, bg=PANEL,
                 font=(FONT, 6)).pack(anchor="w", padx=14)
        size_entry = tk.Entry(dlg, textvariable=size_var, bg=BG, fg=WHITE,
                              insertbackground=WHITE,
                              highlightbackground=BORDER, highlightthickness=1,
                              relief="flat", font=(FONT, 8))
        size_entry.pack(fill="x", padx=14, pady=(2, 8))

    # Warning strip — clarifies local vs VPS semantics
    tk.Label(dlg,
             text=("LOCAL cria processo aqui.\n"
                   "VPS usa systemd template millennium_"
                   f"{mode}@<label>.service."),
             fg=AMBER, bg=PANEL, font=(FONT, 6),
             wraplength=320, justify="left").pack(anchor="w", padx=14,
                                                   pady=(4, 6))

    def _start():
        label = _sanitize_instance_label(label_var.get())
        if not label:
            _toast(launcher, "label obrigatorio", error=True)
            return
        args = [preferred_python_executable(), "-m",
                f"tools.{'operations' if mode == 'paper' else 'maintenance'}"
                f".millennium_{mode}",
                "--label", label]
        if mode == "paper":
            try:
                size = float(size_var.get().strip() or "10000")
            except ValueError:
                _toast(launcher, "account size invalido", error=True)
                return
            args += ["--account-size", str(size)]
        try:
            creation = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            subprocess.Popen(args, creationflags=creation)
        except Exception as exc:
            _toast(launcher, f"spawn falhou: {exc}", error=True)
            return
        _toast(launcher, f"new {mode} instance '{label}' spawned locally")
        dlg.destroy()

    def _start_vps():
        label = _sanitize_instance_label(label_var.get())
        if not label:
            _toast(launcher, "label obrigatorio", error=True)
            return
        client = _get_cockpit_client()
        if client is None or not getattr(client.cfg, "admin_token", None):
            _toast(launcher, "admin_token ausente para start remoto", error=True)
            return
        service = f"millennium_{mode}@{label}"
        try:
            result = client._post(f"/v1/shadow/start?service={service}", admin=True)
        except Exception as exc:
            _toast(launcher, f"VPS start falhou: {exc}", error=True)
            return
        if isinstance(result, dict) and result.get("status") == "started":
            _toast(launcher, f"VPS {mode} '{label}' started")
            _clear_cockpit_view_caches()
            _schedule_state_refresh(launcher, state)
            dlg.destroy()
            return
        _toast(launcher, f"VPS start retornou: {result}", error=True)

    btn_row = tk.Frame(dlg, bg=PANEL)
    btn_row.pack(fill="x", padx=14, pady=(6, 10))
    start = tk.Label(btn_row, text=" ▶ START LOCAL ", fg=BG, bg=GREEN,
                     font=(FONT, 7, "bold"), cursor="hand2", padx=6, pady=2)
    start.pack(side="left")
    start.bind("<Button-1>", lambda _e: _start())
    start_vps = tk.Label(btn_row, text=" ⤴ START VPS ", fg=BG, bg=AMBER,
                         font=(FONT, 7, "bold"), cursor="hand2", padx=6, pady=2)
    start_vps.pack(side="left", padx=(6, 0))
    start_vps.bind("<Button-1>", lambda _e: _start_vps())
    cancel = tk.Label(btn_row, text=" CANCEL ", fg=WHITE, bg=BG2,
                      font=(FONT, 7, "bold"), cursor="hand2", padx=6, pady=2)
    cancel.pack(side="right")
    cancel.bind("<Button-1>", lambda _e: dlg.destroy())

    label_entry.focus_set()


def _vps_running_slugs(*, mode: str, launcher=None, state=None,
                       allow_sync: bool = False) -> set[str]:
    """Query cockpit /v1/runs and return distinct engine slugs currently running.

    Shadow/paper modes dont run processes locally — the RUNNING counter
    must reflect VPS state. Returns empty set on cockpit failure (caller
    falls back to local-proc count, so no hard dependency on the VPS).

    Runs with status='running' but whose last_tick_at is older than the
    stale threshold (cockpit leaves them stuck after process death) are
    filtered out via ``is_run_stale`` — otherwise zombie runs inflate the
    RUNNING counter beyond what's actually live on the VPS.
    """
    from core.ops.run_catalog import is_run_stale
    runs = _load_cockpit_runs_cached(
        launcher=launcher,
        state=state,
        allow_sync=allow_sync,
    )
    slugs: set[str] = set()
    for r in runs:
        if r.get("status") != "running":
            continue
        if mode and r.get("mode") != mode:
            continue
        if is_run_stale(r):
            continue
        engine = r.get("engine")
        if engine:
            slugs.add(engine)
    return slugs


def _vps_running_instance_count(
    *,
    mode: str,
    launcher=None,
    state=None,
) -> int:
    """Count live VPS run *instances* (not engine slugs).

    ``_vps_running_slugs`` returns a deduplicated set — when MILLENNIUM
    has 2 paper + 2 shadow runs, that set has 1 entry. The RUNNING
    counter in the header should reflect the true number of live
    instances in the current mode (2 papers = 2, 2 shadows = 2).

    Stale entries (status='running' but last_tick too old) are excluded
    via ``is_run_stale`` so the counter tracks processes that are still
    actually ticking.
    """
    from core.ops.run_catalog import is_run_stale
    runs = _load_cockpit_runs_cached(launcher=launcher, state=state)
    count = 0
    for r in runs:
        if str(r.get("status") or "").lower() != "running":
            continue
        if mode and str(r.get("mode") or "").lower() != mode:
            continue
        if is_run_stale(r):
            continue
        count += 1
    return count


def _list_procs_cached(*, force: bool = False, ttl_s: float = 0.75) -> list[dict]:
    now = time.monotonic()
    cached_rows = _PROCS_CACHE.get("rows")
    cached_ts = float(_PROCS_CACHE.get("ts") or 0.0)
    if not force and cached_rows is not None and (now - cached_ts) <= ttl_s:
        return list(cached_rows)  # type: ignore[arg-type]
    try:
        from core.ops.proc import list_procs
        rows = list_procs()
    except Exception:
        rows = []
    _PROCS_CACHE["ts"] = now
    _PROCS_CACHE["rows"] = list(rows)
    return rows


def _master_list_sig(state, launcher=None) -> tuple:
    """Signature of everything the master-list render depends on.

    Cheap to compute (hits only already-cached data sources). When this
    matches the previously rendered sig, refresh() skips the rebuild
    entirely — prevents the flicker storm when periodic refresh timers
    fire without any actual state change.
    """
    try:
        procs = _list_procs_cached()
    except Exception:
        procs = []
    running = tuple(sorted(running_slugs_from_procs(procs).keys()))
    mode = state.get("mode")
    vps_running: tuple = ()
    if mode in ("shadow", "paper"):
        try:
            vps = _vps_running_slugs(mode=mode, launcher=launcher, state=state)
            vps_running = tuple(sorted(vps))
        except Exception:
            vps_running = ()
    collapsed = tuple(sorted((state.get("bucket_collapsed") or {}).items()))
    return (
        mode,
        state.get("selected_slug"),
        state.get("selected_bucket"),
        running,
        vps_running,
        collapsed,
        bool(state.get("master_collapsed")),
    )


def _schedule_state_refresh(launcher, state) -> None:
    """Debounced refresh scheduler, called from async worker completions.

    Workers complete concurrently (cockpit runs + paper snapshot + shadow
    snapshot), so a naive ``after(1, refresh)`` stacks three rerenders in
    the same ms — the main loop ends up starved of user input events, so
    the cockpit flickers and absorbs clicks on the sidebar. Coalesce via
    a pending flag on the state dict; 150 ms gives the UI breathing room.
    """
    if not isinstance(state, dict):
        return
    refresh = state.get("refresh")
    if not callable(refresh):
        return
    if state.get("_refresh_scheduled"):
        return
    state["_refresh_scheduled"] = True

    def _run_refresh() -> None:
        state["_refresh_scheduled"] = False
        try:
            refresh()
        except Exception:
            pass

    try:
        launcher.after(150, _run_refresh)
    except Exception:
        state["_refresh_scheduled"] = False


def _load_cockpit_runs_sync() -> list[dict]:
    client = _get_cockpit_client()
    if client is None:
        return []
    try:
        runs = client.list_runs() if hasattr(client, "list_runs") else \
            client._get("/v1/runs")
    except Exception:
        return []
    return list(runs) if isinstance(runs, list) else []


def _load_cockpit_runs_cached(*, launcher=None, state=None,
                              allow_sync: bool = False,
                              ttl_s: float = _COCKPIT_RUNS_CACHE_TTL_S) -> list[dict]:
    now = time.monotonic()
    with _COCKPIT_RUNS_LOCK:
        cached_runs = _COCKPIT_RUNS_CACHE.get("runs")
        cached_ts = float(_COCKPIT_RUNS_CACHE.get("ts") or 0.0)
        if cached_runs is not None and (now - cached_ts) <= ttl_s:
            return list(cached_runs)
        if allow_sync:
            _COCKPIT_RUNS_CACHE["loading"] = True
        elif _COCKPIT_RUNS_CACHE.get("loading"):
            return list(cached_runs or [])
        else:
            _COCKPIT_RUNS_CACHE["loading"] = True

            def _worker() -> None:
                rows = _load_cockpit_runs_sync()
                with _COCKPIT_RUNS_LOCK:
                    _COCKPIT_RUNS_CACHE["ts"] = time.monotonic()
                    _COCKPIT_RUNS_CACHE["runs"] = list(rows)
                    _COCKPIT_RUNS_CACHE["loading"] = False
                _schedule_state_refresh(launcher, state)

            threading.Thread(
                target=_worker,
                name="engines-live-runs-cache",
                daemon=True,
            ).start()
            return list(cached_runs or [])
    rows = _load_cockpit_runs_sync()
    with _COCKPIT_RUNS_LOCK:
        _COCKPIT_RUNS_CACHE["ts"] = time.monotonic()
        _COCKPIT_RUNS_CACHE["runs"] = list(rows)
        _COCKPIT_RUNS_CACHE["loading"] = False
    return rows


def _clear_cockpit_view_caches() -> None:
    global _SHADOW_SNAPSHOT_LOADING
    with _COCKPIT_RUNS_LOCK:
        _COCKPIT_RUNS_CACHE["ts"] = 0.0
        _COCKPIT_RUNS_CACHE["runs"] = None
        _COCKPIT_RUNS_CACHE["loading"] = False
    with _PAPER_SNAPSHOT_LOCK:
        _PAPER_SNAPSHOT_CACHE.clear()
        _PAPER_SNAPSHOT_LOADING.clear()
    with _SHADOW_SNAPSHOT_LOCK:
        _SHADOW_SNAPSHOT_CACHE.clear()
        _SHADOW_SNAPSHOT_LOADING = False
    with _REMOTE_SHADOW_RUN_LOCK:
        _REMOTE_SHADOW_RUN_CACHE.clear()
        _REMOTE_SHADOW_RUN_LOADING.clear()


def _cockpit_runs_loading() -> bool:
    with _COCKPIT_RUNS_LOCK:
        return bool(_COCKPIT_RUNS_CACHE.get("loading"))


# ════════════════════════════════════════════════════════════════
# Tkinter rendering — smoke-tested via launcher, not unit-tested
# ════════════════════════════════════════════════════════════════

def render(launcher, parent, *, on_escape) -> dict:
    """Mount the ENGINES LIVE cockpit view onto `parent`.

    `launcher` is the AurumTerminal instance (for _kb/_exec/_clr utilities).
    `on_escape` is a no-arg callable invoked when ESC is pressed.

    Returns a handle dict:
        {"refresh": callable, "cleanup": callable, "set_mode": callable,
         "rebind": callable, "root": widget}
    """
    state: dict = {
        "mode":           load_mode(),
        "selected_slug":  None,
        "selected_bucket": None,
        "after_handles":  [],
        "bound_keys":     [],
        "initial_refresh_done": False,
        "render_started_at": time.perf_counter(),
        "detail_refresh_after_id": None,
    }

    root = tk.Frame(parent, bg=BG)
    root.pack(fill="both", expand=True)
    # Backref so nested widgets can reach the state when rebinding.
    root._engines_live_state = state  # type: ignore[attr-defined]

    header = _build_header(root, launcher, state)
    header.pack(fill="x", padx=14, pady=(10, 0))

    body = tk.Frame(root, bg=BG)
    body.pack(fill="both", expand=True, padx=14, pady=(8, 0))
    state["body"] = body

    # Split 30/70 master/detail by default. `_apply_master_layout` may
    # switch to a fixed-width rail when state["master_collapsed"] is set.
    _apply_master_layout(body, collapsed=False)

    state["master_host"] = tk.Frame(body, bg=BG)
    # Reduced right gutter 8 → 4 — the sidebar content wasn't reaching the
    # column edge; operator feedback "sidebar nao preenche pra direita"
    # (2026-04-24). Detail pane still gets breathing room via its own
    # padding on the left.
    state["master_host"].grid(row=0, column=0, sticky="nsew", padx=(0, 4))

    state["detail_host"] = tk.Frame(body, bg=BG)
    state["detail_host"].grid(row=0, column=1, sticky="nsew")

    footer = _build_footer(root, state)
    footer.pack(fill="x", padx=14, pady=(6, 10))
    state["footer_frame"] = footer

    def _kb(seq, fn):
        launcher._kb(seq, fn)
        state["bound_keys"].append(seq)

    def _bind_keys():
        state["bound_keys"] = []
        _kb("<Escape>", on_escape)
        _kb("<Key-0>", on_escape)
        _kb("<KeyPress-m>", lambda _e=None: set_mode(cycle_mode(state["mode"])))
        _kb("<KeyPress-M>", lambda _e=None: set_mode(cycle_mode(state["mode"])))
        for idx, mode_name in enumerate(_MODE_ORDER, start=1):
            if idx > 9:
                break
            _kb(f"<KeyPress-{idx}>",
                lambda _e=None, _m=mode_name: set_mode(_m))
        _kb("<Up>", lambda _e=None: _move_selection(state, -1))
        _kb("<Down>", lambda _e=None: _move_selection(state, 1))
        _kb("<Left>", lambda _e=None: _move_live_selection(state, -1))
        _kb("<Right>", lambda _e=None: _move_live_selection(state, 1))
        _kb("<Return>", lambda _e=None: _activate_selection(state, launcher))
        _kb("<KeyPress-l>", lambda _e=None: _open_selected_log(state, launcher))
        _kb("<KeyPress-L>", lambda _e=None: _open_selected_log(state, launcher))
        _kb("<KeyPress-s>", lambda _e=None: _stop_selected_live(state, launcher))
        _kb("<KeyPress-S>", lambda _e=None: _stop_selected_live(state, launcher))
        _kb("<KeyPress-b>", lambda _e=None: _open_selected_backtest(state, launcher))
        _kb("<KeyPress-B>", lambda _e=None: _open_selected_backtest(state, launcher))
        _kb("<KeyPress-c>", lambda _e=None: _toggle_master_collapsed(state))
        _kb("<KeyPress-C>", lambda _e=None: _toggle_master_collapsed(state))

    def _cancel_pending_detail_refresh():
        aid = state.pop("detail_refresh_after_id", None)
        if aid is not None:
            try:
                root.after_cancel(aid)
            except Exception:
                pass

    def _emit_initial_refresh_metric():
        if state.get("initial_refresh_done"):
            return
        state["initial_refresh_done"] = True
        emit_timing_metric(
            "content.engines_live.full",
            ms=(time.perf_counter() - state["render_started_at"]) * 1000.0,
        )

    def _render_detail_stage():
        state["detail_refresh_after_id"] = None
        if not getattr(root, "winfo_exists", lambda: False)():
            return
        _render_detail(state, launcher)
        _emit_initial_refresh_metric()

    def refresh(*, stage_detail: bool = True):
        _cancel_pending_detail_refresh()
        new_sig = _master_list_sig(state, launcher)
        if new_sig != state.get("master_last_render_sig"):
            state["master_last_render_sig"] = new_sig
            _render_master_list(state, launcher)
        _refresh_header(state)
        _refresh_footer(state)
        if not stage_detail:
            _render_detail(state, launcher)
            _emit_initial_refresh_metric()
            return
        try:
            state["detail_refresh_after_id"] = root.after_idle(_render_detail_stage)
        except Exception:
            _render_detail_stage()

    def _cancel_refresh_timers():
        """Cancel every after() slot that schedules a mode-specific rerender.

        Must run before set_mode/cleanup — without this, the prior mode's
        refresh chain keeps firing every 5s on top of the new mode's one,
        stacking destroy+rebuild cycles that freeze the main loop.
        """
        for key in ("shadow_after_id", "shadow_refresh_aid",
                    "paper_refresh_aid"):
            aid = state.pop(key, None)
            if aid is not None:
                try:
                    launcher.after_cancel(aid)
                except Exception:
                    pass

    def cleanup():
        for aid in list(state.get("after_handles", [])):
            try:
                launcher.after_cancel(aid)
            except Exception:
                pass
        state["after_handles"] = []
        _cancel_pending_detail_refresh()
        initial_aid = state.pop("initial_refresh_after_id", None)
        if initial_aid is not None:
            try:
                root.after_cancel(initial_aid)
            except Exception:
                pass
        _cancel_refresh_timers()

    def set_mode(mode):
        if mode not in _MODE_ORDER:
            return
        if mode == state.get("mode"):
            return
        # Kill the prior mode's refresh timers BEFORE touching state so no
        # callback lands on a detail_host that's about to be destroyed.
        _cancel_refresh_timers()
        state["mode"] = mode
        try:
            save_mode(mode)
        except Exception:
            pass
        refresh()

    state["refresh"] = refresh
    state["set_mode"] = set_mode

    _bind_keys()
    def _initial_refresh():
        state["initial_refresh_after_id"] = None
        if not getattr(root, "winfo_exists", lambda: False)():
            return
        refresh()

    try:
        state["initial_refresh_after_id"] = root.after_idle(_initial_refresh)
    except Exception:
        state["initial_refresh_after_id"] = None
        refresh()
    return {
        "refresh": refresh,
        "cleanup": cleanup,
        "set_mode": set_mode,
        "rebind": _bind_keys,
        "root": root,
    }


def _build_header(parent, launcher, state) -> tk.Frame:
    h = tk.Frame(parent, bg=BG)
    top = tk.Frame(h, bg=BG)
    top.pack(fill="x")
    brand = tk.Frame(top, bg=BG)
    brand.pack(side="left", padx=(0, 12))
    logo = tk.Canvas(brand, width=18, height=18, bg=BG, highlightthickness=0)
    logo.pack(side="left", padx=(0, 6))
    try:
        logo.after(10, lambda: launcher._draw_aurum_logo(logo, 9, 9, scale=5, tag="engines-live"))
    except Exception:
        pass
    tk.Label(brand, text="AURUM", font=(FONT, 8, "bold"),
             fg=WHITE, bg=BG).pack(side="left", padx=(0, 10))
    tk.Frame(top, bg=AMBER, width=3, height=22).pack(side="left", padx=(0, 8))
    tk.Label(top, text="LIVE COCKPIT", font=(FONT, 12, "bold"),
             fg=AMBER, bg=BG).pack(side="left", padx=(0, 14))

    pill_row = tk.Frame(top, bg=BG)
    pill_row.pack(side="left")
    state["mode_pills"] = {}
    for mode in _MODE_ORDER:
        pill = tk.Label(pill_row, text=f" {mode.upper()} ",
                        font=(FONT, 7, "bold"),
                        padx=6, pady=3, cursor="hand2")
        pill.pack(side="left", padx=(0, 3))
        pill.bind("<Button-1>",
                  lambda _e, _m=mode: state["set_mode"](_m))
        state["mode_pills"][mode] = pill

    right = tk.Frame(top, bg=BG)
    right.pack(side="right")
    state["desk_lbl"] = tk.Label(right, text="", font=(FONT, 6, "bold"),
                                 fg=DIM2, bg=BG)
    state["desk_lbl"].pack(side="right", padx=(8, 0))
    state["counts_lbl"] = tk.Label(right, text="", font=(FONT, 7, "bold"),
                                    fg=DIM, bg=BG)
    state["counts_lbl"].pack(side="right", padx=(8, 0))
    state["summary_row"] = tk.Frame(h, bg=BG)
    state["summary_row"].pack(fill="x", pady=(8, 0))

    # Header bottom rule — turns RED when mode=live (set in _refresh_header)
    rule = tk.Frame(parent, bg=BORDER, height=1)
    rule.pack(fill="x", pady=(8, 0))
    state["header_rule"] = rule
    return h


def _refresh_header(state):
    for mode, pill in state.get("mode_pills", {}).items():
        color = _MODE_COLORS[mode]
        if mode == state["mode"]:
            pill.configure(fg=BG, bg=color)
        else:
            pill.configure(fg=color, bg=BG3)
    desk_lbl = state.get("desk_lbl")
    if desk_lbl is not None:
        desk_lbl.configure(text=f"DESK {state['mode'].upper()}")
    rule = state.get("header_rule")
    if rule is not None:
        rule.configure(bg=(RED if state["mode"] == "live" else BORDER))


def _build_footer(parent, state) -> tk.Frame:
    f = tk.Frame(parent, bg=BG)
    state["footer_lbl"] = tk.Label(f, text="", font=(FONT, 7),
                                    fg=DIM, bg=BG, anchor="w")
    state["footer_lbl"].pack(side="left", fill="x", expand=True)
    state["footer_warn_lbl"] = tk.Label(f, text="", font=(FONT, 7, "bold"),
                                         fg=RED, bg=BG)
    state["footer_warn_lbl"].pack(side="right")
    # Minimal tunnel indicator à direita do footer — substitui a antiga
    # barra "VPS · TUNNEL" que ficava no topo do detail pane e ocupava
    # espaço em todas as abas. Aqui o status fica visível em qualquer
    # modo sem roubar espaço vertical do conteúdo principal.
    state["footer_tunnel_lbl"] = tk.Label(f, text="", font=(FONT, 7, "bold"),
                                           fg=DIM2, bg=BG)
    state["footer_tunnel_lbl"].pack(side="right", padx=(0, 12))
    return f


def _refresh_footer(state):
    hints, warn = footer_hints(
        selected_bucket=state.get("selected_bucket"),
        mode=state["mode"],
    )
    state["footer_lbl"].configure(text=hints)
    state["footer_warn_lbl"].configure(text=warn)
    tunnel_lbl = state.get("footer_tunnel_lbl")
    if tunnel_lbl is not None:
        tun_text, tun_fg = _get_tunnel_status_label()
        tunnel_lbl.configure(text=f"TUNNEL {tun_text}", fg=tun_fg)


def _load_shadow_snapshot_sync(engine: str = "millennium") -> tuple[Path | None, dict | None, list[dict]]:
    """Fetch latest shadow run for ``engine``. Default stays millennium pra
    compatibilidade; callers novos (per-engine runners 2026-04-22) passam
    citadel/jump/renaissance.

    Perf: apos latest_run() devolver run_id, heartbeat + trades rodam em
    paralelo via ThreadPoolExecutor (antes era 3 calls seriais via SSH
    tunnel, ~600-900ms tipico -> agora ~300-450ms).
    """
    client = _get_cockpit_client()
    if client is None:
        return None, None, []
    try:
        run = client.latest_run(engine=engine, mode="shadow")
    except TypeError:
        try:
            run = client.latest_run(engine=engine)
        except Exception:
            return None, None, []
    except Exception:
        return None, None, []
    if not isinstance(run, dict) or not run.get("run_id"):
        return None, None, []
    run_id = str(run["run_id"])
    run_dir = Path(f"remote://{run_id}")

    def _fetch_hb():
        try:
            return client.get_heartbeat(run_id)
        except Exception:
            return None

    def _fetch_trades():
        try:
            payload = client.get_trades(run_id, limit=20)
            raw = (payload or {}).get("trades") or []
            return [t for t in raw if isinstance(t, dict)]
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=2) as pool:
        hb_fut = pool.submit(_fetch_hb)
        trades_fut = pool.submit(_fetch_trades)
        hb = hb_fut.result()
        trades = trades_fut.result()

    if hb is None:
        hb = {
            "run_id": run_id,
            "status": run.get("status", "unknown"),
            "ticks_ok": 0,
            "ticks_fail": 0,
            "novel_total": run.get("novel_total", 0),
            "last_tick_at": run.get("last_tick_at"),
            "last_error": "heartbeat fetch failed",
            "tick_sec": 0,
        }
    return run_dir, hb, trades


def _call_load_shadow_snapshot_sync(engine: str) -> tuple[Path | None, dict | None, list[dict]]:
    """Call shadow snapshot loader while tolerating legacy zero-arg shims."""
    import inspect

    try:
        params = inspect.signature(_load_shadow_snapshot_sync).parameters
    except (TypeError, ValueError):
        params = {"engine": object()}
    if len(params) == 0:
        return _load_shadow_snapshot_sync()  # type: ignore[call-arg]
    return _load_shadow_snapshot_sync(engine)


def _load_shadow_snapshot_cached(*, launcher=None, state=None,
                                 allow_sync: bool = False,
                                 engine: str = "millennium") -> tuple[Path | None, dict | None, list[dict]]:
    """Cached shadow snapshot fetch per engine. Cache is keyed by engine
    so citadel/jump/renaissance nao colidem com millennium nem entre si.
    """
    global _SHADOW_SNAPSHOT_LOADING
    cache_key = f"latest:{engine}"
    now = time.monotonic()
    with _SHADOW_SNAPSHOT_LOCK:
        cached = _SHADOW_SNAPSHOT_CACHE.get(cache_key)
        if cached is not None and (now - cached[0]) <= _SHADOW_SNAPSHOT_CACHE_TTL_S:
            return cached[1]
        if allow_sync:
            _SHADOW_SNAPSHOT_LOADING = True
        elif _SHADOW_SNAPSHOT_LOADING:
            return cached[1] if cached is not None else (None, None, [])
        else:
            _SHADOW_SNAPSHOT_LOADING = True

            def _worker() -> None:
                global _SHADOW_SNAPSHOT_LOADING
                payload = _call_load_shadow_snapshot_sync(engine)
                with _SHADOW_SNAPSHOT_LOCK:
                    _SHADOW_SNAPSHOT_CACHE[cache_key] = (time.monotonic(), payload)
                    _SHADOW_SNAPSHOT_LOADING = False
                _schedule_state_refresh(launcher, state)

            threading.Thread(
                target=_worker,
                name=f"engines-live-shadow-{engine}",
                daemon=True,
            ).start()
            return cached[1] if cached is not None else (None, None, [])
    payload = _call_load_shadow_snapshot_sync(engine)
    with _SHADOW_SNAPSHOT_LOCK:
        _SHADOW_SNAPSHOT_CACHE[cache_key] = (time.monotonic(), payload)
        _SHADOW_SNAPSHOT_LOADING = False
    return payload


def _fetch_remote_shadow_run_sync(run_id: str) -> tuple[Path | None, dict | None, list[dict]]:
    client = _get_cockpit_client()
    if client is None:
        return None, None, []
    try:
        hb = client.get_heartbeat(run_id)
    except Exception:
        hb = None
    if hb is None:
        return Path(f"remote://{run_id}"), None, []
    try:
        trades_payload = client.get_trades(run_id, limit=20)
        raw_trades = (trades_payload or {}).get("trades") or []
        trades = [trade for trade in raw_trades if isinstance(trade, dict)]
    except Exception:
        trades = []
    return Path(f"remote://{run_id}"), hb, trades


def _fetch_remote_shadow_run_cached(
    run_id: str,
    *,
    launcher=None,
    state=None,
    allow_sync: bool = False,
) -> tuple[Path | None, dict | None, list[dict]]:
    now = time.monotonic()
    with _REMOTE_SHADOW_RUN_LOCK:
        cached = _REMOTE_SHADOW_RUN_CACHE.get(run_id)
        if cached is not None and (now - cached[0]) <= _SHADOW_SNAPSHOT_CACHE_TTL_S:
            return cached[1]
        if allow_sync:
            _REMOTE_SHADOW_RUN_LOADING.add(run_id)
        elif run_id in _REMOTE_SHADOW_RUN_LOADING:
            return cached[1] if cached is not None else (None, None, [])
        else:
            _REMOTE_SHADOW_RUN_LOADING.add(run_id)

            def _worker() -> None:
                payload = _fetch_remote_shadow_run_sync(run_id)
                with _REMOTE_SHADOW_RUN_LOCK:
                    _REMOTE_SHADOW_RUN_CACHE[run_id] = (time.monotonic(), payload)
                    _REMOTE_SHADOW_RUN_LOADING.discard(run_id)
                _schedule_state_refresh(launcher, state)

            threading.Thread(
                target=_worker,
                name=f"engines-live-shadow-{run_id}",
                daemon=True,
            ).start()
            return cached[1] if cached is not None else (None, None, [])
    payload = _fetch_remote_shadow_run_sync(run_id)
    with _REMOTE_SHADOW_RUN_LOCK:
        _REMOTE_SHADOW_RUN_CACHE[run_id] = (time.monotonic(), payload)
        _REMOTE_SHADOW_RUN_LOADING.discard(run_id)
    return payload


def _shadow_active_slugs(*, launcher=None, state=None) -> set[str]:
    """Return the set of engine slugs with an active shadow run visible.

    Pre 2026-04-22: um unico slug via poller.engine. Com runners per-engine
    (citadel/jump/renaissance), merge com cockpit /v1/runs cache pra que
    o sidebar LIVE bucket inclua TODAS as shadows rodando — nao so a que
    o ShadowPoller esta seguindo.
    """
    slugs: set[str] = set()
    # Shadow poller (usually tracks MILLENNIUM, legacy path)
    try:
        from launcher_support.tunnel_registry import get_shadow_poller
        poller = get_shadow_poller()
    except Exception:
        poller = None
    if poller is not None:
        eng = getattr(poller, "engine", None)
        if isinstance(eng, str) and eng:
            slugs.add(eng.lower())

    # Cockpit /v1/runs cache — pega TODOS os engine+mode=shadow runs
    try:
        cached_runs = _COCKPIT_RUNS_CACHE.get("runs") or []
    except Exception:
        cached_runs = []
    for r in cached_runs:
        if str(r.get("mode") or "").lower() != "shadow":
            continue
        if str(r.get("status") or "").lower() != "running":
            continue
        eng = str(r.get("engine") or "").lower()
        if eng:
            slugs.add(eng)
    return slugs


def _fetch_shadow_snapshot(*, launcher=None, state=None) -> tuple[Path | None, dict | None, list[dict]]:
    """Return latest shadow snapshot from poller cache or cockpit API.

    ``state.selected_slug`` controla qual engine — quando o usuario seleciona
    citadel/jump/renaissance na sidebar, buscamos o shadow run dele em vez
    de cair sempre no millennium.
    """
    picked_run_id = _fetch_shadow_run_id(state)
    selected_slug = str((state or {}).get("selected_slug") or "millennium").lower()

    # Fast-path: if _COCKPIT_RUNS_CACHE (60s TTL, background-warmed) já sabe
    # que o run pedido está running, pula o run_catalog.list_runs_catalog.
    cached_runs = _COCKPIT_RUNS_CACHE.get("runs") or []
    target_row: dict | None = None
    if picked_run_id and cached_runs:
        target_row = next(
            (r for r in cached_runs
             if str(r.get("run_id") or "") == picked_run_id),
            None,
        )
    elif cached_runs and not picked_run_id:
        target_row = next(
            (r for r in cached_runs
             if str(r.get("engine") or "").lower() == selected_slug
             and str(r.get("mode") or "").lower() == "shadow"
             and str(r.get("status") or "").lower() == "running"),
            None,
        )
    if target_row and str(target_row.get("status") or "").lower() == "running":
        remote_rid = str(target_row.get("run_id") or "")
        if remote_rid:
            return _fetch_remote_shadow_run_cached(
                remote_rid,
                launcher=launcher,
                state=state,
                allow_sync=(launcher is None and state is None),
            )

    local_row = (
        run_catalog.get_run_summary(picked_run_id, client=_get_cockpit_client())
        if picked_run_id else
        run_catalog.latest_active_run(engine=selected_slug.upper(), mode="shadow")
    )
    if local_row is not None and str(local_row.status or "").lower() != "running":
        local_row = None
    if local_row is not None and local_row.run_dir is not None:
        hb = dict(local_row.heartbeat or {})
        if local_row.started_at and "started_at" not in hb:
            hb["started_at"] = local_row.started_at
        if local_row.last_tick_at and "last_tick_at" not in hb:
            hb["last_tick_at"] = local_row.last_tick_at
        if local_row.status and "status" not in hb:
            hb["status"] = local_row.status
        if local_row.run_id and "run_id" not in hb:
            hb["run_id"] = local_row.run_id
        trades_path = local_row.run_dir / "reports" / "shadow_trades.jsonl"
        trades = []
        if trades_path.exists():
            try:
                trades = run_catalog._tail_jsonl_records(trades_path, limit=20)
            except Exception:
                trades = []
        return local_row.run_dir, hb, trades
    if local_row is not None and local_row.run_id:
        return _fetch_remote_shadow_run_cached(
            local_row.run_id,
            launcher=launcher,
            state=state,
            allow_sync=(launcher is None and state is None),
        )

    try:
        from launcher_support.tunnel_registry import get_shadow_poller
        poller = get_shadow_poller()
    except Exception:
        poller = None
    if poller is not None:
        try:
            cached = poller.get_cached()
        except Exception:
            cached = None
        if cached is not None:
            run_dir, hb = cached
            try:
                trades = poller.get_trades_cached()
            except Exception:
                trades = []
            return run_dir, hb, trades
    return _load_shadow_snapshot_cached(
        launcher=launcher,
        state=state,
        allow_sync=(launcher is None and state is None),
        engine=selected_slug,
    )


def _apply_master_layout(body: tk.Widget, *, collapsed: bool) -> None:
    """Configure the master/detail grid weights on the body container.

    Row weight=1 is CRITICAL — without it the grid row does not stretch
    and master_host/detail_host collapse to their natural content height,
    leaving a dead zone between the panes and the footer. This regressed
    when the column-weight setup moved into this helper; the row config
    must live here too so every call path keeps the stretch.

    Expanded: 30/70 horizontal split via uniform groups with a 260px
    floor on the master column, so engine names + instance labels
    breathe without truncation on narrow windows (operator feedback
    2026-04-24: "sidebar preencha mais ainda ta pra esquerda").
    Collapsed: fixed ~52px rail for col 0, detail takes everything else.
    """
    body.grid_rowconfigure(0, weight=1)
    if collapsed:
        body.grid_columnconfigure(0, weight=0, minsize=52, uniform="")
        body.grid_columnconfigure(1, weight=1, minsize=0, uniform="")
    else:
        body.grid_columnconfigure(0, weight=30, minsize=260, uniform="body")
        body.grid_columnconfigure(1, weight=70, minsize=0, uniform="body")


def _toggle_master_collapsed(state: dict) -> None:
    state["master_collapsed"] = not bool(state.get("master_collapsed"))
    body = state.get("body")
    if body is not None:
        _apply_master_layout(body, collapsed=state["master_collapsed"])
    refresh = state.get("refresh")
    if callable(refresh):
        refresh()


def _render_master_handle(host: tk.Widget, state: dict) -> None:
    """Top bar inside master_host — matches the detail pane's header bar.

    Same bg (BG), same vertical padding, same trailing 1px separator so
    the master pane's top line sits at the same y-coordinate as the
    detail pane's ``_hl2_header`` divider. Contains the ENGINES title on
    the left and the collapse chevron on the right.
    """
    collapsed = bool(state.get("master_collapsed"))
    bar = tk.Frame(host, bg=BG)
    bar.pack(fill="x")
    inner = tk.Frame(bar, bg=BG)
    inner.pack(fill="x", padx=8, pady=6)
    tk.Frame(inner, bg=DIM2, width=2, height=16).pack(side="left",
                                                        padx=(0, 6))
    if not collapsed:
        # Title tone matches the institutional aesthetic — caps + bold
        # but dim-white instead of amber, so the eye doesn't land on
        # the heading first. Amber is reserved for actionable/selected
        # state (bucket badges, selected row).
        tk.Label(inner, text="ENGINES", fg=WHITE, bg=BG,
                 font=(FONT, 9, "bold")).pack(side="left")
    chev = tk.Label(inner, text=("⟩" if collapsed else "⟨"),
                    fg=DIM, bg=BG, font=(FONT, 10, "bold"),
                    cursor="hand2", padx=4)
    chev.pack(side="right")
    chev.bind("<Button-1>", lambda _e: _toggle_master_collapsed(state))
    # Separator line mirrors the one under the detail pane header so the
    # horizontal rule lines up across both panes. Breathing room below
    # comes from the first bucket header's pady=(8, 4), which matches
    # the telemetry strip's top pad on the detail side.
    tk.Frame(host, bg=BORDER, height=1).pack(fill="x")


def _render_master_rail(host: tk.Widget, state: dict, *,
                        live_n: int, ready_n: int, research_n: int) -> None:
    """Compact rail shown when the master pane is collapsed.

    Three stacked badges (LIVE / RDY / LAB) + the selected engine's
    short code so the operator still knows what's on screen without
    expanding. Clicking any badge re-expands the pane.
    """
    rail = tk.Frame(host, bg=PANEL,
                    highlightbackground=BORDER, highlightthickness=1)
    rail.pack(fill="both", expand=True, padx=(0, 2), pady=(0, 4))

    def _cell(label: str, n: int, tint: str) -> None:
        cell = tk.Frame(rail, bg=PANEL, cursor="hand2")
        cell.pack(fill="x", pady=(8, 0))
        tk.Label(cell, text=label, fg=DIM2, bg=PANEL,
                 font=(FONT, 6, "bold")).pack()
        badge_bg = tint if n else BG2
        badge_fg = BG if n else DIM2
        tk.Label(cell, text=str(n), fg=badge_fg, bg=badge_bg,
                 font=(FONT, 8, "bold"), width=3, padx=2).pack(pady=(1, 0))
        cell.bind("<Button-1>", lambda _e: _toggle_master_collapsed(state))
        for c in cell.winfo_children():
            c.bind("<Button-1>", lambda _e: _toggle_master_collapsed(state))

    _cell("LIVE", live_n, GREEN)
    _cell("RDY", ready_n, AMBER_B)
    _cell("LAB", research_n, DIM)

    slug = state.get("selected_slug")
    if slug:
        tk.Frame(rail, bg=BORDER, height=1).pack(fill="x", pady=(10, 4),
                                                  padx=4)
        try:
            from config.engines import ENGINES
            display = str((ENGINES.get(slug) or {}).get("display") or slug).upper()
        except Exception:
            display = str(slug).upper()
        tk.Label(rail, text="SEL", fg=DIM2, bg=PANEL,
                 font=(FONT, 6, "bold")).pack()
        tk.Label(rail, text=display[:3], fg=AMBER_B, bg=PANEL,
                 font=(FONT, 7, "bold")).pack(pady=(1, 6))


def _render_master_list(state, launcher):
    """Mount the 3-bucket master list on state['master_host']."""
    host = state["master_host"]
    for w in host.winfo_children():
        w.destroy()

    from config.engines import (
        ENGINES, LIVE_BOOTSTRAP_SLUGS, LIVE_READY_SLUGS, EXPERIMENTAL_SLUGS,
    )
    procs = _list_procs_cached()
    running = running_slugs_from_procs(procs)

    # VPS-backed modes (shadow, paper): popular running set PRIMEIRO pra
    # garantir que _COCKPIT_RUNS_CACHE está quente antes de calcular
    # shadow_slugs. Ordem anterior travava CITADEL/JUMP/RENAISSANCE no
    # render inicial porque _shadow_active_slugs lia cache vazio e
    # retornava so {millennium} do poller legado — filtrando outras
    # engines visíveis do LIVE bucket. (2026-04-22 fix.)
    current_mode = state.get("mode")
    if current_mode in ("shadow", "paper"):
        # Sync load na primeira chamada: sem isso, _COCKPIT_RUNS_CACHE fica
        # vazio no primeiro render e CITADEL/JUMP/RENAISSANCE nao aparecem
        # no LIVE bucket até o worker assíncrono popular o cache. Com
        # allow_sync=True, o primeiro render espera a resposta (~500ms)
        # mas ja mostra tudo certo. Subsequentes usam o cache TTL=60s.
        cache_is_empty = _COCKPIT_RUNS_CACHE.get("runs") is None
        vps_running = _vps_running_slugs(
            mode=current_mode,
            launcher=launcher,
            state=state,
            allow_sync=cache_is_empty,
        )
        if vps_running:
            # Enrich each VPS proc with started_at (earliest among instances
            # of the same engine) so the sidebar row can show uptime. Without
            # started_at the _row_metric helper short-circuits to "" and the
            # right-edge column reads blank even though the engine is up.
            cockpit_rows = _COCKPIT_RUNS_CACHE.get("runs") or []
            earliest_started: dict[str, str] = {}
            for row in cockpit_rows:
                slug = str(row.get("engine") or "").lower()
                if not slug or slug not in vps_running:
                    continue
                if row.get("status") != "running":
                    continue
                if current_mode and row.get("mode") != current_mode:
                    continue
                started = row.get("started_at")
                if not started:
                    continue
                prev = earliest_started.get(slug)
                if prev is None or str(started) < str(prev):
                    earliest_started[slug] = str(started)
            running = {
                **running,
                **{
                    slug: {
                        "status": "running",
                        "alive": True,
                        "source": "vps",
                        "started_at": earliest_started.get(slug),
                        "engine_mode": current_mode,
                        "mode": current_mode,
                    }
                    for slug in vps_running
                },
            }

    # No modo SHADOW, so engines com shadow run visivel no poller
    # aparecem. Agora lê _COCKPIT_RUNS_CACHE (populado acima) pra cobrir
    # todas as shadows rodando (poller legado so segue uma).
    is_shadow_mode = current_mode == "shadow"
    shadow_slugs = _shadow_active_slugs(launcher=launcher, state=state) if is_shadow_mode else set()

    live_items: list[tuple[str, dict, dict]] = []
    ready_items: list[tuple[str, dict]] = []
    research_items: list[tuple[str, dict]] = []
    experimental_items: list[tuple[str, dict]] = []
    for slug, meta in ENGINES.items():
        live_ready = slug in LIVE_READY_SLUGS
        live_bootstrap = slug in LIVE_BOOTSTRAP_SLUGS
        bucket = assign_bucket(
            slug=slug,
            is_running=slug in running,
            live_ready=live_ready,
            live_bootstrap=live_bootstrap,
        )
        if bucket == "LIVE":
            live_items.append((slug, meta, running[slug]))
        elif bucket == "READY":
            ready_items.append((slug, meta))
        elif slug in EXPERIMENTAL_SLUGS:
            # Split RESEARCH into a dedicated EXPERIMENTAL cluster so
            # quarantined / no-edge engines don't get mixed with honest
            # research candidates.
            experimental_items.append((slug, meta))
        else:
            research_items.append((slug, meta))

    if is_shadow_mode:
        live_items = [t for t in live_items if t[0] in shadow_slugs]
        ready_items = [t for t in ready_items if t[0] in shadow_slugs]
        research_items = [t for t in research_items if t[0] in shadow_slugs]
        experimental_items = [
            t for t in experimental_items if t[0] in shadow_slugs]

    state["live_running_slugs"] = [slug for slug, _meta, _proc in live_items]
    state["ordered_items"] = (
        [(slug, "LIVE") for slug, _meta, _proc in live_items] +
        [(slug, "READY") for slug, _meta in ready_items] +
        [(slug, "RESEARCH") for slug, _meta in research_items] +
        [(slug, "RESEARCH") for slug, _meta in experimental_items]
    )

    # Default selection: first LIVE, else first READY, else first RESEARCH,
    # falling back to the EXPERIMENTAL cluster when it is the only content.
    if state.get("selected_slug") is None:
        selected = initial_selection(
            live_items=live_items,
            ready_items=ready_items,
            research_items=research_items,
            experimental_items=experimental_items,
        )
        if selected is not None:
            state["selected_slug"], state["selected_bucket"] = selected

    # Running counter: for VPS-backed modes (shadow, paper) count actual
    # run *instances* in the cockpit cache — otherwise a single engine
    # with 2+ instances registers as "1 running".
    if current_mode in ("shadow", "paper"):
        running_instances = _vps_running_instance_count(
            mode=current_mode, launcher=launcher, state=state,
        )
    else:
        running_instances = len(live_items)

    _render_master_handle(host, state)

    if state.get("master_collapsed"):
        _render_master_rail(
            host, state,
            live_n=running_instances,
            ready_n=len(ready_items),
            research_n=len(research_items) + len(experimental_items),
        )
    else:
        # Scrollable bucket list. Canvas + inner bg matches the detail
        # pane's body bg (PANEL) so the empty space below the last row
        # doesn't read as a hard black void — instead it flows like a
        # continuation of the panel.
        canvas = tk.Canvas(host, bg=PANEL, highlightthickness=0)
        vbar = tk.Scrollbar(host, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=PANEL)
        inner.bind("<Configure>",
                   lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        vbar.pack(side="right", fill="y")

        _render_bucket(inner, "LIVE", live_items, state)
        _render_bucket(inner, "READY LIVE", ready_items, state)
        _render_bucket(inner, "RESEARCH", research_items, state)
        _render_bucket(inner, "EXPERIMENTAL", experimental_items, state)

    _render_summary_row(
        state,
        live_count=running_instances,
        ready_count=len(ready_items),
        research_count=len(research_items) + len(experimental_items),
    )

    total = (len(live_items) + len(ready_items)
             + len(research_items) + len(experimental_items))
    state["counts_lbl"].configure(
        text=f"{total} engines  ·  {running_instances} running")


def _render_summary_row(state, *, live_count: int, ready_count: int, research_count: int):
    host = state.get("summary_row")
    if host is None:
        return
    for w in host.winfo_children():
        w.destroy()
    for label, value, color in cockpit_summary(
        mode=state["mode"],
        live_count=live_count,
        ready_count=ready_count,
        research_count=research_count,
    ):
        card = tk.Frame(host, bg=BG2, highlightbackground=BORDER, highlightthickness=1)
        card.pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Label(card, text=label, fg=DIM2, bg=BG2,
                 font=(FONT, 6, "bold")).pack(anchor="w", padx=8, pady=(6, 1))
        tk.Label(card, text=value, fg=color, bg=BG2,
                 font=(FONT, 9, "bold")).pack(anchor="w", padx=8, pady=(0, 6))


_COLLAPSIBLE_BUCKETS = {"READY LIVE", "RESEARCH", "EXPERIMENTAL"}


def _bucket_collapse_key(title: str) -> str:
    return f"bucket_collapsed_{title.replace(' ', '_')}"


def _is_bucket_collapsed(state, title: str) -> bool:
    collapsed = state.get("bucket_collapsed") or {}
    # Default-collapse READY LIVE in paper mode — the operator's focus is
    # the running pod, and the launch list eats half the sidebar otherwise.
    if title not in collapsed:
        if title == "READY LIVE" and state.get("mode") == "paper":
            return True
        if title in ("RESEARCH", "EXPERIMENTAL"):
            return True
    return bool(collapsed.get(title, False))


def _toggle_bucket(state, title: str) -> None:
    collapsed = state.setdefault("bucket_collapsed", {})
    collapsed[title] = not _is_bucket_collapsed(state, title)
    refresh = state.get("refresh")
    if callable(refresh):
        refresh()


def _render_bucket(parent, title, items, state):
    if not items:
        return
    bucket = "LIVE" if title == "LIVE" else "RESEARCH" if title in ("RESEARCH", "EXPERIMENTAL") else "READY"
    collapsible = title in _COLLAPSIBLE_BUCKETS
    collapsed = collapsible and _is_bucket_collapsed(state, title)

    # Bucket header uses the SAME 4-column grid as _render_nav_row so the
    # accent / badge-slot / title / count columns align per-pixel with the
    # rows underneath. Before this, the header was pack-based and the
    # chevron+title drift (variable-width chevron label + padx) pushed the
    # title left of where the row names started, which read as misalignment.
    header = tk.Frame(parent, bg=BG2, cursor="hand2" if collapsible else "",
                      highlightbackground=BORDER, highlightthickness=1)
    header.pack(fill="x", pady=(8, 4), padx=0)
    header.grid_columnconfigure(2, weight=1)

    # Col 0 — accent strip (4px, matches _row_base).
    tk.Frame(header, bg=AMBER, width=4).grid(row=0, column=0, sticky="nsw")

    # Col 1 — chevron occupies the same 2ch slot as the row badge, so
    # badges and chevrons stack vertically per-pixel across header/rows.
    chev_text = (">" if collapsed else "v") if collapsible else " "
    tk.Label(header, text=chev_text, fg=AMBER, bg=BG2,
             font=(FONT, 7, "bold"), width=_ROW_BADGE_W,
             cursor="hand2" if collapsible else "").grid(
                 row=0, column=1, padx=(8, 7), pady=5, sticky="n")

    # Col 2 — title, flex like the row-name column.
    tk.Label(header, text=bucket_header_title(title), fg=AMBER, bg=BG2,
             font=(FONT, 7, "bold"), anchor="w",
             cursor="hand2" if collapsible else "").grid(
                 row=0, column=2, sticky="ew", pady=5)

    # Col 3 — count pill sits in the same slot as the row metric (width=7
    # so the right edges align even when counts are 1-digit vs 2-digit).
    tk.Label(header, text=str(len(items)), fg=BG,
             bg=AMBER if title == "LIVE" else DIM,
             font=(FONT, 7, "bold"), width=_ROW_METRIC_W,
             cursor="hand2" if collapsible else "").grid(
                 row=0, column=3, padx=(6, 8), pady=5, sticky="e")

    if collapsible:
        def _on_click(_e=None, _t=title, _s=state):
            _toggle_bucket(_s, _t)
        for w in (header,) + tuple(header.winfo_children()):
            w.bind("<Button-1>", _on_click)

    if collapsed:
        return

    is_live_bucket = title == "LIVE"
    # RESEARCH + EXPERIMENTAL share the locked-style row renderer —
    # EXPERIMENTAL is a visual sub-cluster for quarantined engines.
    is_research_like = title in ("RESEARCH", "EXPERIMENTAL")
    for tup in items:
        if is_live_bucket:
            slug, meta, proc = tup
            _render_nav_row(parent, bucket="LIVE", slug=slug, meta=meta,
                            proc=proc, state=state)
            # Instance sub-rows under the selected LIVE engine. Previously
            # lived in a second table (the ENGINES sidebar rail inside the
            # detail pane) — operator found it redundant. Keep everything
            # in a single master list with indented instances under the
            # active engine, filtered by the current mode.
            if state.get("selected_slug") == slug:
                _render_live_instance_subrows(parent, slug, state)
        elif is_research_like:
            slug, meta = tup
            _render_nav_row(parent, bucket="RESEARCH", slug=slug,
                            meta=meta, proc=None, state=state)
        else:
            slug, meta = tup
            _render_nav_row(parent, bucket="READY", slug=slug, meta=meta,
                            proc=None, state=state)


def _select_slug(state, slug, bucket):
    """Update selection and re-render master + detail."""
    state["selected_slug"] = slug
    state["selected_bucket"] = bucket
    state["refresh"]()


def _move_selection(state, delta):
    ordered = state.get("ordered_items") or []
    if not ordered:
        return
    current = (state.get("selected_slug"), state.get("selected_bucket"))
    try:
        idx = ordered.index(current)
    except ValueError:
        idx = 0
    slug, bucket = ordered[(idx + delta) % len(ordered)]
    _select_slug(state, slug, bucket)


def _move_live_selection(state, delta):
    running = state.get("live_running_slugs") or []
    if state.get("selected_bucket") != "LIVE" or not running:
        return
    slug = state.get("selected_slug")
    try:
        idx = running.index(slug)
    except ValueError:
        idx = 0
    _select_slug(state, running[(idx + delta) % len(running)], "LIVE")


def _activate_selection(state, launcher):
    slug = state.get("selected_slug")
    bucket = state.get("selected_bucket")
    if not slug or not bucket:
        return
    from config.engines import ENGINES
    meta = ENGINES.get(slug, {})
    if bucket == "READY":
        _run_engine(launcher, slug, meta, state)
    elif bucket == "RESEARCH":
        _go_to_backtest(launcher, slug)


def _selected_proc(state):
    if state.get("selected_bucket") != "LIVE":
        return None
    running = running_slugs_from_procs(_list_procs_cached())
    return running.get(state.get("selected_slug"))


def _open_selected_log(state, launcher):
    proc = _selected_proc(state)
    if proc:
        _open_full_log(launcher, proc)


def _stop_selected_live(state, launcher):
    proc = _selected_proc(state)
    if proc:
        _stop_engine(launcher, state, proc)


def _open_selected_backtest(state, launcher):
    if state.get("selected_bucket") == "RESEARCH":
        _go_to_backtest(launcher, state.get("selected_slug"))


# Master-list row layout — single-line 4-column grid shared across
# LIVE / READY / RESEARCH so badges, names, and right-edge metrics
# align per-pixel across buckets. Character widths are fixed on the
# labels because each row is its own Frame with its own grid — grid
# columns don't share widths across separate frames.
#
#   col 0  accent strip       4px       sticky="nsw"
#   col 1  status badge       width=2   RN / RD / LB (bucket-colored)
#   col 2  display name       flex      up to 18ch, bold WHITE/DIM
#   col 3  right-edge metric  width=7   uptime (LIVE) / stage (READY/RES)
#
# Pre 2026-04-24 this row had a subtitle line, an action label column
# (MONITOR/LAUNCH/BACKTEST), and a chevron — all removed when the
# operator asked for a denser, single-line sidebar. The row-click
# handler covers what the action word used to spell out.
_ROW_BADGE_W = 2
_ROW_METRIC_W = 7


def _row_base(parent, slug, state, is_selected):
    bg = BG2 if is_selected else PANEL
    row = tk.Frame(parent, bg=bg, cursor="hand2",
                   highlightbackground=AMBER_B if is_selected else BORDER,
                   highlightthickness=1)
    tk.Frame(row, bg=(AMBER_B if is_selected else BORDER), width=4).grid(
        row=0, column=0, sticky="nsw")
    row.grid_columnconfigure(2, weight=1)
    row.pack(fill="x", pady=(0, 3), padx=0)
    return row


def _bind_nav_row(row: tk.Widget, slug: str, bucket: str, state: dict) -> None:
    def _click(_e, _s=slug, _b=bucket):
        _select_slug(state, _s, _b)

    for w in (row,) + tuple(row.winfo_children()):
        try:
            w.bind("<Button-1>", _click)
        except Exception:
            pass


def _row_metric(bucket: str, meta: dict, proc: dict | None) -> tuple[str, str]:
    """Right-edge metric for a master-list row.

    LIVE rows show uptime ("2h15m" / "45m"); READY and RESEARCH rows
    show the stage label ("PROD" / "STAG" / "LAB" / "ARQV") so the
    column reads consistently across buckets. Returns (text, color).
    """
    if bucket == "LIVE" and proc is not None:
        secs = _uptime_seconds(proc)
        if secs is not None:
            return (format_uptime(seconds=secs), WHITE)
        return ("", DIM2)
    stage_label, stage_color = _stage_badge(meta)
    return (stage_label, stage_color)


def _render_nav_row(parent, *, bucket: str, slug: str, meta: dict,
                    proc: dict | None, state: dict) -> None:
    """Single-line master-list row shared across LIVE / READY / RESEARCH.

    Only the badge text/color and the right-edge metric differ per
    bucket; the 4-column grid is identical so rows align per-pixel.
    """
    sel = state.get("selected_slug") == slug
    row = _row_base(parent, slug, state, is_selected=sel)
    bg = row["bg"]
    _stage_text, stage_color = _stage_badge(meta)

    # Col 1 — 2-char badge, bucket-colored. GREEN = LIVE running;
    # stage color = READY/RESEARCH readiness verdict.
    if bucket == "LIVE":
        badge_text, badge_bg = "RN", GREEN
    elif bucket == "READY":
        badge_text, badge_bg = "RD", stage_color
    else:
        badge_text, badge_bg = "LB", stage_color
    tk.Label(row, text=badge_text, fg=BG, bg=badge_bg,
             font=(FONT, 6, "bold"), padx=3, pady=1,
             width=_ROW_BADGE_W).grid(
                 row=0, column=1, padx=(8, 7), pady=6, sticky="n")

    # Col 2 — display name (up to 18ch). RESEARCH rows are dimmed when
    # unselected to read as "locked / not runnable".
    name_fg = DIM if (bucket == "RESEARCH" and not sel) else WHITE
    tk.Label(row, text=str(meta.get("display", slug.upper()))[:18],
             fg=name_fg, bg=bg, font=(FONT, 8, "bold"),
             anchor="w").grid(row=0, column=2, sticky="ew", pady=6)

    # Col 3 — right-edge metric. 7-char fixed width keeps the right
    # gutter aligned even when a row has no metric to show.
    metric_text, metric_color = _row_metric(bucket, meta, proc)
    metric_fg = AMBER_B if (sel and bucket == "LIVE") else metric_color
    tk.Label(row, text=metric_text[:7], fg=metric_fg, bg=bg,
             font=(FONT, 7, "bold"), anchor="e",
             width=_ROW_METRIC_W).grid(
                 row=0, column=3, padx=(6, 8), pady=6, sticky="e")

    _bind_nav_row(row, slug, bucket, state)


def _render_live_instance_subrows(parent, slug: str, state: dict) -> None:
    current_mode = str(state.get("mode") or "").lower()
    if current_mode not in ("paper", "shadow"):
        return

    instances = _active_engine_runs(
        slug, launcher=None, state=state, mode=current_mode,
    )
    if not instances:
        return

    cur_rid = state.get(
        "selected_paper_run_id" if current_mode == "paper"
        else "selected_shadow_run_id"
    )
    active_rid = str(cur_rid) if cur_rid else None
    mode_color = _MODE_COLORS.get(current_mode, DIM2)
    tray = tk.Frame(parent, bg=BG)
    tray.pack(fill="x", padx=(16, 2), pady=(0, 6))

    for inst in instances:
        rid = str(inst.get("run_id") or "")
        label = str(inst.get("label") or "") or (
            f"#{rid.split('_')[-1][:6]}" if rid else "?"
        )
        ticks = inst.get("ticks_ok") or 0
        is_active = rid == active_rid
        row_bg = BG2 if is_active else PANEL
        item = tk.Frame(tray, bg=row_bg, cursor="hand2",
                        highlightbackground=mode_color if is_active else BORDER,
                        highlightthickness=1)
        item.pack(fill="x", pady=(0, 2))
        tk.Frame(item, bg=mode_color if is_active else BORDER, width=3).pack(
            side="left", fill="y")
        tk.Label(item, text=current_mode[:1].upper(), fg=BG, bg=mode_color,
                 font=(FONT, 6, "bold"), width=2).pack(side="left", padx=(7, 5), pady=3)
        tk.Label(item, text=label[:16], fg=WHITE if is_active else DIM,
                 bg=row_bg, font=(FONT, 7, "bold" if is_active else "normal"),
                 anchor="w").pack(side="left", fill="x", expand=True)
        tk.Label(item, text=f"{ticks}t", fg=AMBER_B if is_active else DIM2,
                 bg=row_bg, font=(FONT, 6, "bold")).pack(side="right", padx=(4, 7))

        def _click(_e, _rid=rid, _mode=current_mode):
            if _mode == "paper":
                state["selected_paper_run_id"] = _rid
            else:
                state["selected_shadow_run_id"] = _rid
            refresh = state.get("refresh")
            if callable(refresh):
                refresh()

        for w in (item,) + tuple(item.winfo_children()):
            w.bind("<Button-1>", _click)


def _render_detail(state, launcher):
    host = state["detail_host"]

    slug = state.get("selected_slug")
    bucket = state.get("selected_bucket")
    mode = state.get("mode")

    if mode == "paper":
        # Pre 2026-04-22: forcava slug="millennium" + bucket="LIVE" no
        # paper mode. Com runners per-engine (citadel/jump/renaissance),
        # paper tem tambem as 3 engines — preservar selecao do usuario.
        # Defaults so aplicam quando nada foi selecionado ainda.
        if not slug:
            slug = "millennium"
        if not bucket:
            bucket = "LIVE"
        state["selected_slug"] = slug
        state["selected_bucket"] = bucket

    shell_mode = state.get("_detail_shell_mode")
    layout = state.get("_detail_layout")
    sidebar_host = state.get("_sidebar_host")
    detail_inner = state.get("_detail_inner")
    reuse_shell = (
        shell_mode == mode
        and layout is not None and getattr(layout, "winfo_exists", lambda: False)()
        and sidebar_host is not None and getattr(sidebar_host, "winfo_exists", lambda: False)()
        and detail_inner is not None and getattr(detail_inner, "winfo_exists", lambda: False)()
    )

    # Skip full detail rebuild when nothing material changed. Uses the
    # _cheap variants so this check never blocks on HTTP or lock
    # acquisition — the fallback sig is "loading" when caches are empty,
    # which triggers exactly one rebuild per cache warmup (acceptable).
    if reuse_shell and mode in ("paper", "shadow") and slug:
        if mode == "paper":
            new_sig = ("paper", slug, _paper_content_sig_cheap(state))
        else:
            new_sig = ("shadow", slug, _shadow_content_sig_cheap(state))
        last_sig = state.get("_detail_last_render_sig")
        if new_sig == last_sig:
            return
        state["_detail_last_render_sig"] = new_sig
    else:
        state["_detail_last_render_sig"] = None

    if not reuse_shell:
        for w in host.winfo_children():
            w.destroy()
        # Master-detail com sidebar universal: renderiza sidebar primeiro
        # (todas as engines do registry) e depois dispatcha o detail pane
        # especifico do modo/bucket dentro de detail_inner.
        layout = tk.Frame(host, bg=PANEL)
        layout.pack(fill="both", expand=True)

        sidebar_host = tk.Frame(layout, bg=PANEL)
        sidebar_host.pack(side="left", fill="y")

        detail_inner = tk.Frame(layout, bg=PANEL)
        detail_inner.pack(side="left", fill="both", expand=True)

        state["_detail_layout"] = layout
        state["_sidebar_host"] = sidebar_host
        state["_detail_inner"] = detail_inner
        state["_detail_shell_mode"] = mode
    else:
        for w in sidebar_host.winfo_children():
            w.destroy()
        for w in detail_inner.winfo_children():
            w.destroy()

    # Heartbeats: em SHADOW vem do poller remoto; em modos locais,
    # marca engines com PID ativo no _PROCS_CACHE como "active".
    heartbeats: dict[str, dict] = {}
    if mode == "shadow":
        _run_dir, hb, _trades = _fetch_shadow_snapshot(launcher=launcher, state=state)
        if hb is not None and slug:
            heartbeats[slug] = hb
    else:
        # Non-shadow modes nao tem poller com contadores — so marcamos
        # o engine como active (sidebar renderiza ✓ sem numeros).
        for proc_row in (_PROCS_CACHE.get("rows") or []):
            proc_slug = proc_row.get("slug") or ""
            if not proc_slug:
                continue
            heartbeats[proc_slug] = {"status": "running"}

    # Sidebar rail DENTRO do detail pane foi removida (antes duplicava
    # a master list da esquerda — operador reportou "duas barras fazem
    # a mesma coisa"). Selecao + lista de engines vive so na master
    # list agora. sidebar_host fica como placeholder 0-width pra
    # preservar refs de layout (shell reuse checa winfo_exists).

    # SHADOW mode: path dedicado (telemetria do VPS cockpit API).
    if mode == "shadow":
        # Status do tunnel agora vive no footer global; aqui o detail
        # pane vai direto pro engine card pra ganhar espaço vertical.
        if not slug:
            _render_shadow_empty_state(detail_inner, launcher, state)
            return
        from config.engines import ENGINES
        meta = ENGINES.get(slug, {})
        card = tk.Frame(detail_inner, bg=PANEL,
                        highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True)
        _render_detail_shadow(card, slug, meta, state, launcher)
        return

    # PAPER mode: pod sim tracking equity + positions via cockpit API.
    if mode == "paper":
        if not slug:
            _render_paper_empty_state(detail_inner, launcher, state)
            return
        from config.engines import ENGINES
        meta = ENGINES.get(slug, {})
        card = tk.Frame(detail_inner, bg=PANEL,
                        highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True)
        _render_detail_paper(card, slug, meta, state, launcher)
        return

    if not slug:
        tk.Label(detail_inner, text="(no selection)", fg=DIM, bg=BG,
                 font=(FONT, 8)).pack(pady=20)
        return

    from config.engines import ENGINES
    meta = ENGINES.get(slug, {})

    card = tk.Frame(detail_inner, bg=PANEL,
                    highlightbackground=BORDER, highlightthickness=1)
    card.pack(fill="both", expand=True)

    if bucket == "RESEARCH":
        _render_detail_research(card, slug, meta, state, launcher)
    elif bucket == "READY":
        _render_detail_ready(card, slug, meta, state, launcher)
    elif bucket == "LIVE":
        _render_detail_live(card, slug, meta, state, launcher)


def _render_detail_research(parent, slug, meta, state, launcher):
    """Compact research panel: 1 header line + 1 status line + action row.
    Research engines dont trade — no need for big warning boxes. Keep it tight."""
    name = meta.get("display", slug.upper())
    desc = meta.get("desc", "")
    stage_label, stage_color = _stage_badge(meta)

    # Single-line header: dot · name · stage · RESEARCH badge
    head = tk.Frame(parent, bg=PANEL)
    head.pack(fill="x", padx=8, pady=(6, 2))
    tk.Label(head, text="○", fg=DIM2, bg=PANEL,
             font=(FONT, 10)).pack(side="left", padx=(0, 4))
    tk.Label(head, text=name, fg=AMBER, bg=PANEL,
             font=(FONT, 10, "bold")).pack(side="left")
    tk.Label(head, text=f"  {stage_label} ",
             fg=BG, bg=stage_color, font=(FONT, 6, "bold"),
             padx=4).pack(side="left", padx=(6, 4))
    tk.Label(head, text=" RESEARCH ",
             fg=BG, bg=HAZARD, font=(FONT, 6, "bold"),
             padx=4).pack(side="left")

    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=8, pady=(4, 6))

    # Single status line replacing the big warning box
    if desc:
        tk.Label(parent, text=desc, fg=DIM, bg=PANEL,
                 font=(FONT, 7), anchor="w", justify="left",
                 wraplength=520).pack(fill="x", padx=8, pady=(0, 4))

    tk.Label(parent, text="sem entrypoint live — valide em backtest",
             fg=HAZARD, bg=PANEL, font=(FONT, 7, "italic"),
             anchor="w").pack(fill="x", padx=8, pady=(0, 8))

    # Compact action row
    actions = tk.Frame(parent, bg=PANEL)
    actions.pack(fill="x", padx=8, pady=(0, 8))
    _action_btn(actions, "BACKTEST", AMBER,
                lambda: _go_to_backtest(launcher, slug))
    _action_btn(actions, "CODE", DIM,
                lambda: _view_code(launcher, meta.get("script", "")))


def _action_btn(parent, label, color, cmd):
    b = tk.Label(parent, text=f"  {label}  ",
                 fg=color, bg=BG3,
                 font=(FONT, 8, "bold"),
                 cursor="hand2", padx=4, pady=6)
    b.pack(side="left", padx=(0, 8))
    b.bind("<Button-1>", lambda _e: cmd())
    b.bind("<Enter>", lambda _e, _b=b, _c=color: _b.configure(fg=BG, bg=_c))
    b.bind("<Leave>", lambda _e, _b=b, _c=color: _b.configure(fg=_c, bg=BG3))
    return b


def _go_to_backtest(launcher, slug):
    """Bounce to EXECUTE → BACKTEST, pre-selecting this engine if possible."""
    fn = getattr(launcher, "_strategies_backtest", None)
    if callable(fn):
        fn()


def _view_code(launcher, script_path):
    if not script_path:
        return
    try:
        from code_viewer import CodeViewer
        CodeViewer(launcher, script_path)
    except Exception:
        pass


_LEVERAGE_OPTS = [("1x", "1.0"), ("2x", "2.0"), ("3x", "3.0"), ("5x", "5.0")]
_LIVE_FS_CACHE_TTL_S = 1.0
_LATEST_RUN_DIR_CACHE: dict[str, tuple[float, Path | None]] = {}
_POSITIONS_CACHE: dict[str, tuple[float, list[dict]]] = {}
_LOG_TAIL_CACHE: dict[tuple[str, int], tuple[float, list[str]]] = {}
_SHADOW_LATEST_CACHE: dict[str, tuple[float, tuple[Path, dict] | None]] = {}


def _cache_get(cache: dict, key):
    entry = cache.get(key)
    if entry is None:
        return None
    stamp, value = entry
    if (time.monotonic() - stamp) > _LIVE_FS_CACHE_TTL_S:
        cache.pop(key, None)
        return None
    return value


def _cache_put(cache: dict, key, value) -> None:
    cache[key] = (time.monotonic(), value)


def _clear_live_fs_caches() -> None:
    _LATEST_RUN_DIR_CACHE.clear()
    _POSITIONS_CACHE.clear()
    _LOG_TAIL_CACHE.clear()
    _SHADOW_LATEST_CACHE.clear()


def _latest_run_dir(slug: str) -> Path | None:
    cached = _cache_get(_LATEST_RUN_DIR_CACHE, slug)
    if cached is not None or slug in _LATEST_RUN_DIR_CACHE:
        return cached
    root = Path(__file__).resolve().parent.parent / "data"
    eng_dir = root / _ENGINE_DIR_MAP.get(slug, slug)
    if not eng_dir.is_dir():
        _cache_put(_LATEST_RUN_DIR_CACHE, slug, None)
        return None
    try:
        runs = sorted([d for d in eng_dir.iterdir() if d.is_dir()],
                      key=lambda d: d.stat().st_mtime, reverse=True)
    except OSError:
        _cache_put(_LATEST_RUN_DIR_CACHE, slug, None)
        return None
    latest = runs[0] if runs else None
    _cache_put(_LATEST_RUN_DIR_CACHE, slug, latest)
    return latest


def _load_positions_for_slug(slug: str) -> list[dict]:
    cached = _cache_get(_POSITIONS_CACHE, slug)
    if cached is not None:
        return [dict(item) for item in cached]
    run_dir = _latest_run_dir(slug)
    if run_dir is None:
        return []
    path = run_dir / "state" / "positions.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        rows = [dict(item) if isinstance(item, dict) else {"value": item} for item in data]
        _cache_put(_POSITIONS_CACHE, slug, rows)
        return [dict(item) for item in rows]
    if isinstance(data, dict):
        rows = [{"symbol": k, **(v if isinstance(v, dict) else {"value": v})} for k, v in data.items()]
        _cache_put(_POSITIONS_CACHE, slug, rows)
        return [dict(item) for item in rows]
    return []


def _resolve_log_path(slug: str, proc: dict) -> Path | None:
    for key in ("log", "log_path", "log_file"):
        val = proc.get(key)
        if val:
            p = Path(val)
            if p.exists():
                return p
    run_dir = _latest_run_dir(slug)
    if run_dir is None:
        return None
    for cand in (run_dir / "logs" / "live.log", run_dir / "logs" / "engine.log", run_dir / "log.txt"):
        if cand.is_file():
            return cand
    return None


_LOG_TAIL_WINDOW_BYTES = 16 * 1024

# Log level classifier — first match wins, priority order matters.
# ERROR > WARN > EXIT > FILL > ORDER > SIGNAL > INFO.
_LOG_LEVEL_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ERROR",  re.compile(r"\b(ERROR|FATAL|CRITICAL|Traceback)\b")),
    ("WARN",   re.compile(r"\b(WARNING|WARN|STALE|SKIP)\b", re.IGNORECASE)),
    ("EXIT",   re.compile(r"\bEXIT\b")),
    ("FILL",   re.compile(r"\bFILL\b")),
    ("ORDER",  re.compile(r"\bORDER\b")),
    ("SIGNAL", re.compile(r"\bSIGNAL\b|\bnovel=[1-9]\d*")),
]

# (foreground, bold) — INFO dimmed so noise fades back; SIGNAL/EXIT/ERROR
# bold so the operator's eye lands on the lines that matter.
_LOG_LEVEL_STYLE: dict[str, tuple[str, bool]] = {
    "INFO":   (DIM,    False),
    "SIGNAL": (AMBER,  True),
    "ORDER":  (CYAN,   False),
    "FILL":   (GREEN,  False),
    "EXIT":   (WHITE,  True),
    "WARN":   (HAZARD, False),
    "ERROR":  (RED,    True),
}


def _classify_log_level(line: str) -> str:
    for name, pat in _LOG_LEVEL_PATTERNS:
        if pat.search(line):
            return name
    return "INFO"


def _read_log_tail(path: Path | None, n: int = 18) -> list[str]:
    if path is None:
        return []
    cache_key = (str(path), int(n))
    cached = _cache_get(_LOG_TAIL_CACHE, cache_key)
    if cached is not None:
        return list(cached)
    try:
        # Read at most the trailing window — avoids slurping multi-MB logs
        # on every 1s cache miss. 16KB buffer is plenty for ~200 log lines.
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            start = max(0, size - _LOG_TAIL_WINDOW_BYTES)
            f.seek(start)
            chunk = f.read().decode("utf-8", errors="ignore")
        # Drop the first partial line if we didn't start at byte 0.
        if start > 0:
            nl = chunk.find("\n")
            if nl != -1:
                chunk = chunk[nl + 1:]
        lines = chunk.splitlines()[-n:]
        _cache_put(_LOG_TAIL_CACHE, cache_key, list(lines))
        return lines
    except OSError:
        return []


def _runtime_snapshot(slug: str, proc: dict) -> dict:
    positions = _load_positions_for_slug(slug)
    log_path = _resolve_log_path(slug, proc)
    tail = _read_log_tail(log_path)
    pnl = proc.get("pnl")
    if pnl is None:
        vals = [_safe_float(p.get("pnl", p.get("unrealized_pnl"))) for p in positions]
        vals = [v for v in vals if v is not None]
        pnl = sum(vals) if vals else None
    return {
        "positions": positions,
        "positions_count": len(positions),
        "log_path": log_path,
        "tail": tail,
        "pnl": pnl,
        "last_signal": proc.get("last_signal") or (tail[-1] if tail else "-"),
    }


def _pnl_color(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return WHITE
    return GREEN if f > 0 else RED if f < 0 else WHITE


def _desk_metric(parent, label, value, color):
    box = tk.Frame(parent, bg=BG3, highlightbackground=BORDER, highlightthickness=1)
    box.pack(side="left", fill="x", expand=True, padx=(0, 4))
    tk.Label(box, text=label, fg=DIM, bg=BG3, font=(FONT, 6, "bold")).pack(anchor="w", padx=8, pady=(5, 1))
    tk.Label(box, text=str(value), fg=color, bg=BG3, font=(FONT, 8, "bold")).pack(anchor="w", padx=8, pady=(0, 5))


def _render_live_book(parent, state, running):
    if not running:
        return
    box = tk.Frame(parent, bg=BG2, highlightbackground=BORDER_H, highlightthickness=1)
    box.pack(fill="x", padx=12, pady=(12, 0))
    head = tk.Frame(box, bg=BG2)
    head.pack(fill="x", padx=10, pady=(8, 4))
    tk.Label(head, text="LIVE FLEET", fg=AMBER_B, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="left")
    tk.Label(head, text=f"{len(running)} ACTIVE", fg=DIM2, bg=BG2,
             font=(FONT, 6, "bold")).pack(side="right")
    tk.Label(box, text="LEFT / RIGHT SWITCH THE ACTIVE ENGINE ON DESK",
             fg=DIM2, bg=BG2, font=(FONT, 6)).pack(anchor="w", padx=10, pady=(0, 4))
    grid = tk.Frame(box, bg=BG2)
    grid.pack(fill="x", padx=8, pady=(0, 8))
    cols = 3
    for idx, (slug, proc) in enumerate(running.items()):
        snap = _runtime_snapshot(slug, proc)
        active = state.get("selected_slug") == slug
        card = tk.Frame(grid, bg=(PANEL if active else BG3),
                        highlightbackground=(AMBER_B if active else BORDER),
                        highlightthickness=1, cursor="hand2")
        card.grid(row=idx // cols, column=idx % cols, sticky="ew", padx=3, pady=3)
        grid.grid_columnconfigure(idx % cols, weight=1)
        inner = tk.Frame(card, bg=card["bg"])
        inner.pack(fill="both", expand=True, padx=8, pady=6)
        tk.Label(inner, text=slug.upper(), fg=WHITE, bg=card["bg"], font=(FONT, 8, "bold")).pack(anchor="w")
        tk.Label(inner, text=f"{str(proc.get('engine_mode') or proc.get('mode') or 'paper').upper()}  ·  {format_uptime(seconds=_uptime_seconds(proc))}",
                 fg=DIM2, bg=card["bg"], font=(FONT, 6)).pack(anchor="w", pady=(1, 0))
        tk.Label(inner, text=f"{snap['positions_count']} OPEN  ·  {_fmt_pnl(snap['pnl'])}",
                 fg=_pnl_color(snap["pnl"]), bg=card["bg"], font=(FONT, 7, "bold")).pack(anchor="w", pady=(3, 0))
        for w in (card, inner) + tuple(inner.winfo_children()):
            w.bind("<Button-1>", lambda _e, s=slug: _select_slug(state, s, "LIVE"))


def _render_positions_panel(parent, column, positions):
    box = tk.Frame(parent, bg=BG2, highlightbackground=BORDER, highlightthickness=1)
    box.grid(row=0, column=column, sticky="nsew", padx=(0, 4) if column == 0 else (4, 0))
    tk.Label(box, text="POSITIONS", fg=AMBER_D, bg=BG2, font=(FONT, 7, "bold")).pack(anchor="w", padx=10, pady=(8, 4))
    if not positions:
        tk.Label(box, text="NO OPEN BOOK", fg=DIM, bg=BG2, font=(FONT, 8)).pack(anchor="w", padx=10, pady=(0, 8))
        return
    hdr = tk.Frame(box, bg=BG3)
    hdr.pack(fill="x", padx=10)
    for text, width in (("SYMBOL", 9), ("SIDE", 7), ("ENTRY", 10), ("P/L", 10)):
        tk.Label(hdr, text=text, fg=DIM, bg=BG3, font=(FONT, 6, "bold"),
                 width=width, anchor="w", padx=3, pady=4).pack(side="left")
    body = tk.Frame(box, bg=BG2)
    body.pack(fill="both", expand=True, padx=10, pady=(0, 8))
    for p in positions[:7]:
        row = tk.Frame(body, bg=BG2)
        row.pack(fill="x")
        side = str(p.get("side", p.get("direction", "?"))).upper()
        for txt, width, color in (
            (str(p.get("symbol", "?")), 9, WHITE),
            (side, 7, GREEN if side == "LONG" else RED if side == "SHORT" else WHITE),
            (str(p.get("entry", p.get("entry_price", "-"))), 10, AMBER_B),
            (_fmt_pnl(p.get("pnl", p.get("unrealized_pnl"))), 10, _pnl_color(p.get("pnl", p.get("unrealized_pnl")))),
        ):
            tk.Label(row, text=txt, fg=color, bg=BG2, font=(FONT, 8),
                     width=width, anchor="w", padx=3, pady=2).pack(side="left")


def _render_log_panel(parent, column, state, launcher, proc, snap):
    box = tk.Frame(parent, bg=BG2, highlightbackground=BORDER, highlightthickness=1)
    box.grid(row=0, column=column, sticky="nsew", padx=(0, 4) if column == 0 else (4, 0))
    head = tk.Frame(box, bg=BG2)
    head.pack(fill="x", padx=10, pady=(8, 4))
    tk.Label(head, text="LOG", fg=AMBER_D, bg=BG2, font=(FONT, 7, "bold")).pack(side="left")
    if snap["log_path"] is not None:
        tk.Label(head, text=snap["log_path"].name, fg=DIM2, bg=BG2,
                 font=(FONT, 6)).pack(side="left", padx=(8, 0))
    _action_btn(head, "OPEN FULL", DIM, lambda: _open_full_log(launcher, proc))
    log_box = tk.Text(box, height=16, bg=BG, fg=WHITE, font=(FONT, 8),
                      wrap="none", highlightbackground=BORDER, highlightthickness=0,
                      state="disabled")
    log_box.pack(fill="both", expand=True, padx=10, pady=(0, 8))
    for _lvl, (_fg, _bold) in _LOG_LEVEL_STYLE.items():
        if _bold:
            log_box.tag_configure(_lvl, foreground=_fg,
                                  font=(FONT, 8, "bold"))
        else:
            log_box.tag_configure(_lvl, foreground=_fg)
    state["log_box"] = log_box
    _schedule_log_tail(state, launcher, proc)


_COCKPIT_CLIENT_SINGLETON: object | None = None


def _get_cockpit_client():
    """Lazy singleton. Returns None se config ausente ou invalida.

    Config vem do runtime key store bloco 'cockpit_api'. Só cacheia
    resultado POSITIVO — tentativas que falham voltam None mas deixam
    o singleton em None pra retry na próxima chamada. Durante o boot
    o keys.json pode estar sendo lido concorrentemente (backup hook,
    worktree sync) e uma falha transitória travaria o cockpit pelo
    resto da sessão se fosse cached.
    """
    global _COCKPIT_CLIENT_SINGLETON
    if _COCKPIT_CLIENT_SINGLETON is not None:
        return _COCKPIT_CLIENT_SINGLETON
    try:
        data = load_runtime_keys()
        block = data.get("cockpit_api")
        if not block or not block.get("base_url") or not block.get("read_token"):
            return None
        from launcher_support.cockpit_client import CockpitClient, CockpitConfig
        cfg = CockpitConfig(
            base_url=block["base_url"],
            read_token=block["read_token"],
            admin_token=block.get("admin_token"),
            timeout_sec=float(block.get("timeout_sec", 5.0)),
        )
        _COCKPIT_CLIENT_SINGLETON = CockpitClient(
            cfg, cache_dir=Path("data/.cockpit_cache"))
        return _COCKPIT_CLIENT_SINGLETON
    except (KeyStoreError, ValueError, TypeError):
        return None


def _is_remote_run(run_dir: Path) -> bool:
    # Path() on Windows normaliza "remote://x" pra "remote:\x" ou "remote:/x".
    # Aceita as três formas pra robustez cross-platform.
    s = str(run_dir).replace("\\", "/")
    return s.startswith("remote:/") or s.startswith("remote://")


def _remote_run_id(run_dir: Path) -> str:
    s = str(run_dir).replace("\\", "/")
    if s.startswith("remote://"):
        return s[len("remote://"):]
    if s.startswith("remote:/"):
        return s[len("remote:/"):]
    return s


def _get_tunnel_status_label() -> tuple[str, str]:
    """Return (text, fg_color) pro badge TUNNEL na linha de status.

    Le do launcher_support.tunnel_registry (nao de `launcher` direto)
    pra escapar do __main__-vs-launcher: quando roda `python launcher.py`,
    `from launcher import X` carrega UM SEGUNDO modulo com singleton None.
    O registry em launcher_support é sempre a mesma instancia.
    """
    try:
        from launcher_support.tunnel_registry import (
            get_tunnel_manager, get_tunnel_boot_error,
        )
        tm = get_tunnel_manager()
        boot_err = get_tunnel_boot_error()
    except Exception:
        tm = None
        boot_err = None
    if tm is None:
        # Manager never booted — surface the specific reason if any.
        # "CFG ERR" > generic "—" because user sees it's actionable,
        # not just a missing optional dependency.
        return ("CFG ERR" if boot_err else "—", RED if boot_err else DIM2)
    status = getattr(tm, "status", None)
    if status is None:
        return ("—", DIM2)
    # TunnelStatus.value is a lowercase string: up/reconnecting/...
    val = str(status.value).upper()
    color_map = {
        "UP": GREEN,
        "STARTING": AMBER_B,
        "RECONNECTING": AMBER_B,
        "OFFLINE": RED,
        "STOPPING": DIM2,
        "IDLE": DIM2,
        "DISABLED": DIM2,
    }
    return (val, color_map.get(val, DIM2))


def _get_tunnel_error_hint() -> str | None:
    """Short diagnostic shown in empty-state cards when VPS data is missing."""
    try:
        from launcher_support.tunnel_registry import (
            get_tunnel_manager, get_tunnel_boot_error,
        )
        tm = get_tunnel_manager()
        boot_err = get_tunnel_boot_error()
    except Exception:
        tm = None
        boot_err = None
    if tm is None:
        return boot_err
    err = getattr(tm, "last_error", None)
    if err:
        return str(err)
    return None


def _find_latest_shadow_run() -> tuple[Path, dict] | None:
    """Return (run_dir, heartbeat_payload) for the most recent shadow run.

    Le do ShadowPoller cache (atualizado em background thread) em vez
    de fazer HTTP sync aqui no UI thread — HTTP sync congela TkInter
    por ate timeout_sec quando o tunnel esta lento/down. Se nao tem
    poller ativo, cai pro disco local (dev workflow preservado).
    """
    if Path.cwd().resolve() == _REPO_ROOT.resolve():
        latest = run_catalog.latest_active_run(engine="MILLENNIUM", mode="shadow")
        if latest is not None and latest.run_dir is not None:
            hb = dict(latest.heartbeat or {})
            if latest.started_at and "started_at" not in hb:
                hb["started_at"] = latest.started_at
            if latest.last_tick_at and "last_tick_at" not in hb:
                hb["last_tick_at"] = latest.last_tick_at
            if latest.status and "status" not in hb:
                hb["status"] = latest.status
            if latest.run_id and "run_id" not in hb:
                hb["run_id"] = latest.run_id
            return latest.run_dir, hb

    # Remote path via poller cache (nunca bloqueia)
    if _use_remote_shadow_cache():
        run_dir, hb, _trades = _fetch_shadow_snapshot(launcher=launcher, state=state)
        if run_dir is not None and hb is not None:
            return (run_dir, hb)

    # Local disk fallback (layout existente)
    root = Path("data/millennium_shadow")
    cache_key = str(root.resolve()) if root.exists() else str(root)
    cached = _cache_get(_SHADOW_LATEST_CACHE, cache_key)
    if cached is not None or cache_key in _SHADOW_LATEST_CACHE:
        return cached
    if not root.exists():
        _cache_put(_SHADOW_LATEST_CACHE, cache_key, None)
        return None
    candidates: list[tuple[float, Path, dict]] = []
    for sub in root.iterdir():
        if not sub.is_dir():
            continue
        hb = sub / "state" / "heartbeat.json"
        if not hb.exists():
            continue
        try:
            payload = json.loads(hb.read_text(encoding="utf-8"))
            mtime = hb.stat().st_mtime
        except (OSError, json.JSONDecodeError):
            continue
        candidates.append((mtime, sub, payload))
    if not candidates:
        _cache_put(_SHADOW_LATEST_CACHE, cache_key, None)
        return None
    candidates.sort(key=lambda row: row[0], reverse=True)
    _, run_dir, payload = candidates[0]
    result = (run_dir, payload)
    _cache_put(_SHADOW_LATEST_CACHE, cache_key, result)
    return result


def _drop_shadow_kill(run_dir: Path, launcher, state) -> None:
    """Drop a `.kill` flag so the shadow loop exits after the current tick.

    Remote runs (virtual_dir = 'remote://<run_id>') route via cockpit
    client POST /kill. Local runs write the file directly (previous behavior).
    """
    # Remote path via cockpit API
    if _is_remote_run(run_dir):
        client = _get_cockpit_client()
        if client is None or not getattr(client.cfg, "admin_token", None):
            _toast(launcher, "admin_token ausente em keys.json — STOP indisponivel",
                   error=True)
            try:
                launcher.h_stat.configure(
                    text="SHADOW KILL: admin_token ausente",
                    fg=RED)
            except Exception:
                pass
            return
        run_id = _remote_run_id(run_dir)
        try:
            client.drop_kill(run_id)
        except Exception as exc:
            _toast(launcher, f"STOP falhou: {type(exc).__name__}: {exc}",
                   error=True)
            try:
                launcher.h_stat.configure(
                    text=f"SHADOW KILL fail: {type(exc).__name__}", fg=RED)
            except Exception:
                pass
            return
        _toast(launcher, f"STOP dispatched → {run_id} · para em <=15s")
        try:
            launcher.h_stat.configure(
                text=f"SHADOW KILL dispatched ({run_id})", fg=AMBER)
        except Exception:
            pass
        # Trigger cache invalidation + re-render em 3s (da tempo pro runner
        # processar o .kill e systemd marcar stopped). Evita UI mostrar dados
        # stale de "running 625 signals" apos user ja ter parado.
        try:
            launcher.after(3000,
                           lambda: _force_refresh_shadow(launcher, state))
        except Exception:
            pass
        refresh = state.get("refresh")
        if callable(refresh):
            try:
                launcher.after(250, refresh)
            except Exception:
                refresh()
        return

    # Local path — preserves original file-write behavior
    kill_path = run_dir / ".kill"
    try:
        kill_path.write_text("killed via cockpit\n", encoding="utf-8")
    except OSError as exc:
        try:
            launcher.h_stat.configure(
                text=f"SHADOW KILL fail: {type(exc).__name__}", fg=RED)
        except Exception:
            pass
        return
    try:
        launcher.h_stat.configure(
            text=f"SHADOW KILL flag dropped ({run_dir.name})", fg=AMBER)
    except Exception:
        pass
    refresh = state.get("refresh")
    if callable(refresh):
        try:
            launcher.after(250, refresh)
        except Exception:
            refresh()


def _render_shadow_panel(parent, launcher, state, slug: str) -> None:
    """Render SHADOW LOOP status card inside the MILLENNIUM detail.

    Reads `data/millennium_shadow/<latest>/state/heartbeat.json` and shows
    ticks_ok / ticks_fail / signals / last tick + STOP CTA when running.
    Only active for the millennium slug — noop otherwise, so other engines
    keep their existing detail layout untouched.

    Auto-refreshes every 5s while a run is active so the cockpit reflects
    tick progress without needing to navigate away and back.
    """
    if slug != "millennium":
        return

    # Cancel any prior shadow auto-refresh timer so a fresh render doesn't
    # leak `after` callbacks every time the user bounces between engines.
    old_aid = state.pop("shadow_after_id", None)
    if old_aid is not None:
        try:
            launcher.after_cancel(old_aid)
        except Exception:
            pass

    result = _find_latest_shadow_run()

    shadow = tk.Frame(parent, bg=BG2,
                      highlightbackground=BORDER_H, highlightthickness=1)
    shadow.pack(fill="x", padx=12, pady=(0, 10))
    # Stash the frame so the scheduled refresh can rebuild only this card.
    state["shadow_panel_frame"] = shadow
    state["shadow_panel_parent"] = parent
    top = tk.Frame(shadow, bg=BG2)
    top.pack(fill="x", padx=10, pady=(8, 4))
    tk.Label(top, text="SHADOW LOOP", fg=AMBER_B, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="left")

    if result is None:
        tk.Label(top, text="NONE", fg=DIM2, bg=BG2,
                 font=(FONT, 7, "bold")).pack(side="right")
        tun_text, tun_fg = _get_tunnel_status_label()
        tun_row = tk.Frame(shadow, bg=BG2)
        tun_row.pack(fill="x", padx=10, pady=(2, 4))
        tk.Label(tun_row, text="TUNNEL:", fg=DIM2, bg=BG2,
                 font=(FONT, 7, "bold")).pack(side="left")
        tk.Label(tun_row, text=f" {tun_text}", fg=tun_fg, bg=BG2,
                 font=(FONT, 7, "bold")).pack(side="left")
        tk.Label(
            shadow,
            text=("Nenhum shadow run encontrado.\n"
                  "Rode:  python tools/maintenance/millennium_shadow.py "
                  "--tick-sec 900 --run-hours 24"),
            fg=DIM2, bg=BG2, font=(FONT, 7), justify="left", anchor="w",
        ).pack(fill="x", padx=10, pady=(0, 8))
        return

    run_dir, hb = result
    status = str(hb.get("status") or "unknown").upper()
    status_color = GREEN if status == "RUNNING" else DIM2
    tk.Label(top, text=f" {status} ", fg=BG, bg=status_color,
             font=(FONT, 7, "bold"), padx=4).pack(side="right")

    facts = tk.Frame(shadow, bg=BG2)
    facts.pack(fill="x", padx=8, pady=(0, 4))
    fail_n = int(hb.get("ticks_fail", 0) or 0)
    _desk_metric(facts, "TICKS OK",
                 str(hb.get("ticks_ok", 0)), GREEN)
    _desk_metric(facts, "FAIL",
                 str(fail_n), RED if fail_n > 0 else DIM2)
    _desk_metric(facts, "SIGNALS",
                 str(hb.get("novel_total", 0)), AMBER_B)
    _desk_metric(facts, "TICK",
                 f"{int(hb.get('tick_sec', 0) or 0)}s", WHITE)

    tun_text, tun_fg = _get_tunnel_status_label()
    tun_row = tk.Frame(shadow, bg=BG2)
    tun_row.pack(fill="x", padx=10, pady=(0, 2))
    tk.Label(tun_row, text="TUNNEL:", fg=DIM2, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="left")
    tk.Label(tun_row, text=f" {tun_text}", fg=tun_fg, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="left")

    last = hb.get("last_tick_at") or hb.get("stopped_at") or "—"
    source = "REMOTE" if _is_remote_run(run_dir) else "LOCAL"
    tk.Label(shadow,
             text=f"[{source}]  RUN {hb.get('run_id','?')}  ·  last {last}",
             fg=DIM, bg=BG2, font=(FONT, 7), anchor="w").pack(
                 fill="x", padx=10, pady=(0, 4))

    if status == "RUNNING":
        # STOP SHADOW chip removido pra não ocupar espaço — controle heavy
        # vive via systemctl no VPS. Poll do heartbeat continua rodando
        # pra manter a UI viva sem precisar navegar pra outra aba.
        try:
            aid = launcher.after(
                5000,
                lambda: _refresh_shadow_panel(launcher, state),
            )
            state["shadow_after_id"] = aid
        except Exception:
            pass
    else:
        reason = hb.get("stopped_reason") or "—"
        tk.Label(shadow, text=f"stopped: {reason}",
                 fg=DIM2, bg=BG2, font=(FONT, 7), anchor="w").pack(
                     fill="x", padx=10, pady=(0, 8))


def _refresh_shadow_panel(launcher, state) -> None:
    """Rebuild the shadow card in-place from the latest heartbeat.

    Only replaces the shadow frame — other widgets on the detail stay put.
    Silently aborts if the user has navigated away (frame destroyed).
    """
    frame = state.get("shadow_panel_frame")
    parent = state.get("shadow_panel_parent")
    if frame is None or parent is None:
        return
    try:
        if not frame.winfo_exists():
            return
    except Exception:
        return
    # Only refresh while a shadow-capable engine is still the active
    # selection. Antes: hardcoded millennium. Agora: qualquer engine com
    # shadow runner (citadel/jump/renaissance passaram a ter o seu em
    # 2026-04-22). Usa selected_slug pra re-renderizar o painel certo.
    slug = state.get("selected_slug")
    if not slug:
        return
    try:
        frame.destroy()
    except Exception:
        return
    _render_shadow_panel(parent, launcher, state, slug)


# ─── SHADOW mode detail view ───────────────────────────────────────
# Layout completo dedicado pro modo SHADOW. Le do ShadowPoller cache
# (nunca bloqueia o UI thread) e se auto-refresh a cada 5s via
# launcher.after. Se a cache esta vazia, renderiza empty-state.

def _engine_registry_for_sidebar(state) -> list[dict]:
    """Return list de {slug, display} pra sidebar. Inclui todas engines
    exibidas no bucket LIVE/READY atual — evita depender de import
    circular com launcher.ENGINES.

    Antes 2026-04-22: paper mode hardcoded pra so mostrar MILLENNIUM.
    Agora CITADEL/JUMP/RENAISSANCE tem runners paper+shadow proprios
    (per-engine runners 2e065db); a sidebar cobre todas as engines
    com runs ao vivo no bucket LIVE.
    """
    by_bucket = state.get("engines_by_bucket") or {}
    if state.get("mode") == "paper":
        for bucket in ("READY", "LIVE"):
            for item in by_bucket.get(bucket, []):
                if item.get("slug") == "millennium":
                    return [{
                        "slug": "millennium",
                        "display": item.get("display") or "MILLENNIUM",
                    }]
        return [{"slug": "millennium", "display": "MILLENNIUM"}]
    seen: set[str] = set()
    out: list[dict] = []
    for bucket in ("LIVE", "READY"):
        for item in by_bucket.get(bucket, []):
            slug = item.get("slug") or ""
            if not slug or slug in seen:
                continue
            seen.add(slug)
            out.append({
                "slug": slug,
                "display": item.get("display") or slug.upper(),
            })
    if not out:
        slug = state.get("selected_slug") or "millennium"
        out.append({"slug": slug, "display": slug.upper()})
    return out


def _render_detail_shadow(parent, slug, meta, state, launcher):
    """Render SHADOW cockpit detail pane — sidebar eh renderizada pelo
    _render_detail upstream. Aqui soh cuidamos do detail pane + actions.
    """
    name = meta.get("display", slug.upper())

    # Instance picker antes ficava aqui (vertical table no detail pane).
    # Agora foi merged na sidebar ENGINES — ve-se engine + instancias
    # juntos, uma so tabela em vez de duas. Call site removido.

    run_dir, hb, trades = _fetch_shadow_snapshot(launcher=launcher, state=state)

    # Detail pane
    if hb is None:
        _render_shadow_no_run(parent, launcher, state)
        _schedule_shadow_refresh(launcher, state)
        return

    tun_text, tun_color = _get_tunnel_status_label()
    status = str(hb.get("status") or "unknown").upper()
    status_color = GREEN if status == "RUNNING" else DIM2

    # Drill-down inline: click em row seta selected_trade e rerender;
    # click em ✕ limpa e volta pra tabela. Tudo dentro do proprio
    # detail pane — sem Toplevel modal.
    def _on_row_click(trade: dict):
        state["shadow_selected_trade"] = trade
        _render_detail(state, launcher)

    def _on_close_detail():
        state.pop("shadow_selected_trade", None)
        _render_detail(state, launcher)

    selected = state.get("shadow_selected_trade")
    # Se o trade selecionado nao esta mais na lista de trades (ex. sumiu
    # do cache apos poll novo), limpa selection pra evitar stale state.
    if selected is not None and trades:
        sel_key = (selected.get("strategy"), selected.get("symbol"),
                   selected.get("timestamp"))
        known_keys = {(t.get("strategy"), t.get("symbol"), t.get("timestamp"))
                      for t in trades}
        if sel_key not in known_keys:
            state.pop("shadow_selected_trade", None)
            selected = None

    detail_frame = render_detail(
        parent=parent,
        engine_display=name,
        mode="shadow",
        heartbeat=hb,
        manifest=None,
        trades=trades,
        on_row_click=_on_row_click,
        status_badge_text=f"TUNNEL {tun_text}  ·  {status}",
        status_badge_color=status_color,
        selected_trade=selected,
        on_close_detail=_on_close_detail,
    )

    # Actions row — só START (quando parado) + REFRESH. STOP e RESTART
    # foram removidos do cockpit pra não ocupar espaço: controle pesado
    # vive via SSH/systemctl no VPS quando preciso. REFRESH fica porque
    # força re-fetch do cache local quando dados parecem stale.
    # Pinned to the bottom of detail_frame so the signal feed above can
    # stretch into the middle — without side="bottom" the actions row
    # glues itself to the end of the content and leaves a dead zone
    # between the signal feed and the footer.
    actions = tk.Frame(detail_frame, bg=PANEL)
    actions.pack(side="bottom", fill="x", padx=8, pady=(4, 10))
    if not (status == "RUNNING" and run_dir is not None):
        start_btn = tk.Label(actions, text=" START SHADOW ON VPS ",
                             fg=BG, bg=GREEN, font=(FONT, 7, "bold"),
                             cursor="hand2", padx=8, pady=3)
        start_btn.pack(side="left")
        start_btn.bind("<Button-1>",
                       lambda _e: _start_shadow_via_cockpit(launcher, state))
    refresh_btn = tk.Label(actions, text=" REFRESH ",
                           fg=WHITE, bg=BG3, font=(FONT, 7, "bold"),
                           cursor="hand2", padx=8, pady=3)
    refresh_btn.pack(side="left", padx=(6, 0) if status != "RUNNING" else (0, 0))
    refresh_btn.bind("<Button-1>",
                     lambda _e: _force_refresh_shadow(launcher, state))

    # Cada render completa (scheduled OU click-triggered) atualiza o sig
    # pra que o proximo ciclo de refresh compare corretamente.
    state["shadow_last_render_sig"] = _shadow_content_sig(state, launcher)
    _schedule_shadow_refresh(launcher, state)


def _schedule_shadow_refresh(launcher, state) -> None:
    """Agenda re-render em 5s. Usa single-slot state['shadow_refresh_aid']
    e cancela qualquer handle pendente antes de agendar — evita leak de
    720 handles/hora ao re-renderizar a cada ciclo."""
    prev_aid = state.pop("shadow_refresh_aid", None)
    if prev_aid is not None:
        try:
            launcher.after_cancel(prev_aid)
        except Exception:
            pass
    try:
        aid = launcher.after(60000,
                             lambda: _refresh_shadow_detail(launcher, state))
        state["shadow_refresh_aid"] = aid
    except Exception:
        pass


def _paper_content_sig_cheap(state) -> tuple:
    """Cache-only paper detail signature. NO HTTP, NO lock acquisition.

    Reads from _COCKPIT_RUNS_CACHE and _PAPER_SNAPSHOT_CACHE directly via
    plain dict .get(). Dict reads are atomic in CPython (GIL guarantees
    it); the sig is advisory anyway — a transient stale read just means
    one extra rebuild when caches catch up. The whole function must stay
    under 1ms because the render-skip path runs on every refresh on the
    tk main loop. The heavyweight _paper_content_sig kept for callers
    that need full fidelity after a worker completes.
    """
    cached_runs = _COCKPIT_RUNS_CACHE.get("runs")
    if not cached_runs:
        return ("loading",)
    run_id: str | None = None
    for r in cached_runs:
        if (str(r.get("engine") or "").lower() == "millennium"
                and str(r.get("mode") or "").lower() == "paper"
                and str(r.get("status") or "").lower() == "running"):
            run_id = str(r.get("run_id") or "")
            if run_id:
                break
    if run_id is None:
        return ("no-run",)
    picked = (state or {}).get("selected_paper_run_id")
    if picked:
        run_id = picked
    cached = _PAPER_SNAPSHOT_CACHE.get(run_id)
    if cached is None:
        return ("loading", run_id)
    _ts, payload = cached
    hb, positions, series, _account, trades = payload
    if hb is None:
        return ("loading", run_id)
    last_trade_ts = trades[-1].get("timestamp") if trades else None
    return (
        run_id,
        hb.get("status"),
        hb.get("last_tick_at"),
        hb.get("novel_total"),
        len(positions),
        len(series),
        len(trades),
        last_trade_ts,
    )


def _shadow_content_sig_cheap(state) -> tuple:
    """Cache-only shadow detail signature. Same contract as the paper
    version — never blocks, reads dict .get() only.

    Bug fix: a sig PRECISA incluir selected_shadow_run_id. Se o operador
    clica em outro shadow run no picker, _render_detail compara sig nova
    vs antiga; se a selecao nao aparece na tupla, sig permanece igual,
    _render_detail early-returns e a tela nao atualiza — picker parece
    "morto". Paper faz isso certo via `picked = state.get(...)` em
    _paper_content_sig_cheap.
    """
    picked = (state or {}).get("selected_shadow_run_id") or ""
    if not _SHADOW_SNAPSHOT_CACHE:
        return ("loading", picked)
    # Pick any cached run — the actual selection happens on real render.
    # Sig only needs to detect *change*, not fidelity.
    try:
        _k, entry = next(iter(_SHADOW_SNAPSHOT_CACHE.items()))
    except StopIteration:
        return ("loading", picked)
    _ts, payload = entry
    run_dir, hb, trades = payload
    if hb is None:
        return ("loading", picked)
    return (
        state.get("selected_slug"),
        picked,                        # <-- NEW: muda → sig muda → re-render
        str(run_dir or ""),
        hb.get("status"),
        hb.get("last_tick_at"),
        hb.get("novel_total"),
        len(trades) if trades else 0,
    )


def _shadow_content_sig(state, launcher=None) -> tuple:
    """Assinatura barata do conteudo que o shadow detail renderiza —
    usada pra pular re-render quando nada mudou, cortando o destroy+
    rebuild de ~150ms/ciclo que causava flicker visível."""
    run_dir, hb, trades = _fetch_shadow_snapshot(launcher=launcher, state=state)
    if hb is None:
        return (None,)
    hb_sig = None
    if hb is not None:
        hb_sig = (
            hb.get("status"),
            hb.get("ticks_ok"),
            hb.get("ticks_fail"),
            hb.get("novel_total"),
            hb.get("last_tick_at"),
            hb.get("stopped_at"),
            hb.get("last_error"),
        )
    trades_sig = None
    if trades:
        last = trades[-1]
        trades_sig = (
            len(trades),
            last.get("shadow_observed_at") or last.get("timestamp"),
            last.get("symbol"),
            last.get("strategy"),
        )
    selected = state.get("shadow_selected_trade")
    selected_sig = None
    if selected is not None:
        selected_sig = (selected.get("strategy"), selected.get("symbol"),
                        selected.get("timestamp"))
    return (state.get("selected_slug"), str(run_dir or ""), hb_sig, trades_sig,
            selected_sig, state.get("selected_shadow_run_id"))


def _refresh_shadow_detail(launcher, state) -> None:
    """Rebuild the detail pane from the latest poller cache.

    Sai cedo se o user navegou pra outro modo — evita rodar de novo
    quando o detail pane ja nao e shadow. Skip re-render quando
    content signature bate com a ultima — economia grande (e fim do
    flicker) quando nao ha tick novo.
    """
    if state.get("mode") != "shadow":
        return
    try:
        # Se o master_host nao existe mais (cockpit desmontado), aborta.
        host = state.get("detail_host")
        if host is None or not host.winfo_exists():
            return
    except Exception:
        return
    sig = _shadow_content_sig(state, launcher)
    last_sig = state.get("shadow_last_render_sig")
    if sig == last_sig and last_sig is not None:
        # Nada mudou — so reagenda o proximo ciclo.
        _schedule_shadow_refresh(launcher, state)
        return
    state["shadow_last_render_sig"] = sig
    _render_detail(state, launcher)


def _shadow_metric_card(parent, label, value, subtitle, color):
    """Cartao compacto com titulo + valor + subtitulo explicativo."""
    card = tk.Frame(parent, bg=BG2,
                    highlightbackground=BORDER, highlightthickness=1)
    card.pack(side="left", fill="both", expand=True, padx=(0, 6))
    tk.Label(card, text=label, fg=DIM2, bg=BG2,
             font=(FONT, 6, "bold")).pack(anchor="w", padx=8, pady=(6, 1))
    tk.Label(card, text=value, fg=color, bg=BG2,
             font=(FONT, 11, "bold")).pack(anchor="w", padx=8, pady=(0, 0))
    tk.Label(card, text=subtitle, fg=DIM, bg=BG2,
             font=(FONT, 6)).pack(anchor="w", padx=8, pady=(0, 6))


def _shadow_info_row(parent, key, value, fg=WHITE):
    row = tk.Frame(parent, bg=PANEL)
    row.pack(fill="x", pady=(0, 2))
    tk.Label(row, text=f"{key}:", fg=DIM2, bg=PANEL,
             font=(FONT, 7, "bold"), width=12, anchor="w").pack(
                 side="left", padx=(0, 4))
    tk.Label(row, text=str(value), fg=fg, bg=PANEL,
             font=(FONT, 7), anchor="w").pack(
                 side="left", fill="x", expand=True)


def _render_signals_table(parent, trades):
    """Render compact table of signals. `trades` ordered newest-first."""
    if not trades:
        tk.Label(parent,
                 text="(sem sinais ainda — aguardando primeiros ticks)",
                 fg=DIM, bg=PANEL, font=(FONT, 7, "italic")).pack(
                     anchor="w", pady=(4, 4))
        return
    # Header row
    hdr = tk.Frame(parent, bg=BG2)
    hdr.pack(fill="x", pady=(2, 0))
    cols = [("TIME", 16), ("SYMBOL", 10), ("STRAT", 10),
            ("DIR", 6), ("ENTRY", 12)]
    for col_name, w in cols:
        tk.Label(hdr, text=col_name, fg=DIM2, bg=BG2,
                 font=(FONT, 6, "bold"),
                 width=w, anchor="w").pack(side="left", padx=(4, 0))
    # Data rows
    for trade in trades:
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=(1, 0))
        ts_raw = str(trade.get("timestamp", "—"))
        ts = ts_raw[:19].replace("T", " ")
        symbol = str(trade.get("symbol", "—"))
        strat = str(trade.get("strategy", "—"))[:10]
        direction = str(trade.get("direction", "—"))
        dir_upper = direction.upper()
        if dir_upper == "LONG":
            dir_color = GREEN
        elif dir_upper == "SHORT":
            dir_color = RED
        else:
            dir_color = DIM
        entry = trade.get("entry")
        try:
            entry_str = (f"{float(entry):,.4f}"
                         if entry is not None else "—")
        except (TypeError, ValueError):
            entry_str = str(entry)[:12]
        tk.Label(row, text=ts, fg=DIM, bg=PANEL, font=(FONT, 6),
                 width=16, anchor="w").pack(side="left", padx=(4, 0))
        tk.Label(row, text=symbol, fg=WHITE, bg=PANEL,
                 font=(FONT, 6, "bold"),
                 width=10, anchor="w").pack(side="left", padx=(4, 0))
        tk.Label(row, text=strat, fg=DIM, bg=PANEL, font=(FONT, 6),
                 width=10, anchor="w").pack(side="left", padx=(4, 0))
        tk.Label(row, text=direction, fg=dir_color, bg=PANEL,
                 font=(FONT, 6, "bold"),
                 width=6, anchor="w").pack(side="left", padx=(4, 0))
        tk.Label(row, text=entry_str, fg=WHITE, bg=PANEL, font=(FONT, 6),
                 width=12, anchor="w").pack(side="left", padx=(4, 0))


def _render_hl2_empty(parent, *, title: str, blurb: str,
                      actions: list[tuple[str, str, callable]],
                      hint: str | None = None) -> None:
    """Unified HL2 empty-state block — used by every engines mode when
    there's no run / no selection. Consistent tone, consistent spacing.

    `actions` is a list of (label, color, handler). Rendered as chips
    side-by-side under the blurb. `hint` prints a smaller dim footer
    (for SSH fallbacks).
    """
    bg = BG
    box = tk.Frame(parent, bg=bg)
    box.pack(fill="both", expand=True, padx=18, pady=16)

    # Title
    tk.Label(box, text=title.upper(), fg=AMBER, bg=bg,
             font=(FONT, 11, "bold")).pack(anchor="w")
    tk.Frame(box, bg=BORDER, height=1).pack(fill="x", pady=(3, 8))

    # Tunnel row (always shown — users wait for this to be UP)
    tun_text, tun_fg = _get_tunnel_status_label()
    t_row = tk.Frame(box, bg=bg)
    t_row.pack(fill="x", pady=(0, 8))
    tk.Label(t_row, text="TUNNEL", fg=DIM2, bg=bg,
             font=(FONT, 6, "bold")).pack(side="left")
    tk.Label(t_row, text=f"  {tun_text}", fg=tun_fg, bg=bg,
             font=(FONT, 8, "bold")).pack(side="left")

    # Blurb
    tk.Label(box, text=blurb, fg=DIM, bg=bg, font=(FONT, 7),
             justify="left", anchor="w").pack(anchor="w", pady=(0, 10))

    # Actions
    if actions:
        a_row = tk.Frame(box, bg=bg)
        a_row.pack(anchor="w")
        for label, color, handler in actions:
            chip = tk.Label(a_row, text=f"  {label}  ", fg=BG, bg=color,
                            font=(FONT, 8, "bold"), cursor="hand2",
                            padx=10, pady=5)
            chip.pack(side="left", padx=(0, 6))
            chip.bind("<Button-1>", lambda _e, h=handler: h())

    if hint:
        tk.Label(box, text=hint, fg=DIM2, bg=bg, font=(FONT, 6),
                 justify="left", anchor="w").pack(anchor="w", pady=(12, 0))


def _render_shadow_no_run(parent, launcher, state=None):
    """Shadow selected but poller has no cached heartbeat."""
    diag = _get_tunnel_error_hint()
    blurb = ("Nenhum shadow run detectado via cockpit API.\n"
             "Pode ser: tunnel caiu, VPS runner parou, ou primeira vez.")
    if diag:
        blurb += f"\n\nDiagnostico do tunnel: {diag}"
    _render_hl2_empty(
        parent,
        title="NO SHADOW RUN VISIBLE",
        blurb=blurb,
        actions=[("▶ START SHADOW ON VPS", GREEN,
                  lambda: _start_shadow_via_cockpit(launcher, state or {}))],
        hint="Ou manual via SSH:\n  sudo systemctl start millennium_shadow.service",
    )


def _render_shadow_empty_state(parent, launcher, state):
    """Shadow mode landing — no slug selected."""
    _render_hl2_empty(
        parent,
        title="SHADOW MODE",
        blurb=("Shadow roda estratégias no VPS em modo observacional:\n"
               "simula trades sem executar, mede edge real em OHLCV vivo.\n\n"
               "Selecione um engine na sidebar, ou inicie um run via o\n"
               "botão abaixo (chama systemctl start via cockpit admin)."),
        actions=[("▶ START SHADOW", GREEN,
                  lambda: _start_shadow_via_cockpit(launcher, state))],
    )
    _schedule_shadow_refresh(launcher, state)


# ─── PAPER mode detail view ─────────────────────────────────────
# Paper mode fetches state/account.json + state/positions.json + reports/
# equity.jsonl via cockpit API endpoints added in feat/millennium-paper.
# Shows full trading dashboard via render_detail paper kwargs.

def _render_run_instance_picker(
    parent,
    *,
    active_runs: list[dict],
    state: dict,
    launcher,
    state_key: str,
    title: str = "INSTANCES:",
) -> None:
    # "RUNNING NOW" strip — horizontal tab bar above the detail pane.
    # Matches the master-list bucket aesthetic: amber rule + caps heading,
    # clickable tabs showing label / source / tick count / live indicator.
    container = tk.Frame(parent, bg=BG)
    container.pack(fill="x", padx=0, pady=(0, 6))

    header = tk.Frame(container, bg=BG)
    header.pack(fill="x", padx=0, pady=(0, 0))
    tk.Frame(header, bg=AMBER, width=3, height=14).pack(side="left", padx=(0, 6))
    tk.Label(header, text="ENGINES", font=(FONT, 7, "bold"),
             fg=AMBER, bg=BG).pack(side="left")
    tk.Label(header, text=f"  ·  {len(active_runs)}", font=(FONT, 7),
             fg=DIM, bg=BG).pack(side="left")
    tk.Frame(container, bg=BORDER, height=1).pack(fill="x", pady=(2, 4))

    row = tk.Frame(container, bg=BG)
    row.pack(fill="x")

    current = state.get(state_key)
    effective = current if current and any(
        r.get("run_id") == current for r in active_runs
    ) else (active_runs[0].get("run_id") if active_runs else None)

    def _make_click(rid: str):
        def _click(_event=None):
            state[state_key] = rid
            _render_detail(state, launcher)
        return _click

    for r in active_runs:
        rid = r.get("run_id") or ""
        label = r.get("label") or (f"#{rid.split('_')[-1][:6]}" if rid else "?")
        source = str(r.get("source") or "").lower()
        source_tag = "VPS" if source == "vps" else "LOCAL"
        ticks = r.get("ticks_ok", 0)
        is_active = rid == effective
        tab_bg = BG2 if is_active else BG
        tab_fg = AMBER if is_active else WHITE
        border = AMBER if is_active else BORDER

        tab = tk.Frame(
            row, bg=tab_bg,
            highlightbackground=border, highlightthickness=1,
            cursor="hand2",
        )
        tab.pack(side="left", padx=(0, 6), pady=(0, 2))

        dot = "●" if is_active else "○"
        tk.Label(tab, text=dot, fg=GREEN if is_active else DIM,
                 bg=tab_bg, font=(FONT, 9, "bold"),
                 padx=(8 if is_active else 8)).pack(side="left", padx=(6, 0), pady=6)
        tk.Label(tab, text=label, fg=tab_fg, bg=tab_bg,
                 font=(FONT, 9, "bold"), padx=4).pack(side="left", padx=(4, 0), pady=6)
        tk.Label(tab, text=f"{source_tag}", fg=DIM if is_active else DIM2,
                 bg=tab_bg, font=(FONT, 7)).pack(side="left", padx=(6, 0), pady=6)
        tk.Label(tab, text=f"  {ticks} tk  ", fg=tab_fg, bg=tab_bg,
                 font=(FONT, 8)).pack(side="left", padx=(6, 8), pady=6)

        for w in (tab,) + tuple(tab.winfo_children()):
            w.bind("<Button-1>", _make_click(rid))


def _render_paper_instance_picker(parent, active_runs: list[dict],
                                  state: dict, launcher) -> None:
    """Compact row of clickable instance tags above the paper detail."""
    _render_run_instance_picker(
        parent,
        active_runs=active_runs,
        state=state,
        launcher=launcher,
        state_key="selected_paper_run_id",
    )


def _active_engine_runs(
    slug: str,
    *,
    launcher=None,
    state=None,
    mode: str | None = None,
) -> list[dict]:
    """Live runs for a given engine slug, newest first.

    ``mode`` filters the list: "paper" → only paper instances, "shadow"
    → only shadow instances, ``None`` → both (cross-mode picker).
    Operator feedback: each mode panel (paper/shadow) should list only
    its own instances so the menu stays focused — the cross-mode badge
    view was confusing when navigating.
    """
    paper: list[dict] = []
    shadow: list[dict] = []
    if mode in (None, "paper"):
        paper = _active_paper_runs(launcher, state, engine=slug)
        for r in paper:
            r.setdefault("mode", "paper")
    if mode in (None, "shadow"):
        shadow = _active_shadow_runs(launcher=launcher, state=state, engine=slug)
        for r in shadow:
            r.setdefault("mode", "shadow")
    combined = list(paper) + list(shadow)
    # Filter by engine slug when available. MILLENNIUM-orchestrated runs
    # surface ``millennium`` in the _raw payload; leave the filter lenient
    # so non-labelled rows (legacy) still render.
    if slug:
        want = slug.lower()
        combined = [
            r for r in combined
            if (str(r.get("engine") or r.get("_raw", {}).get("engine") or slug).lower() == want)
        ]
    combined.sort(key=lambda r: (str(r.get("mode") or ""), str(r.get("label") or "")))
    return combined


def _render_engine_instance_picker(
    parent,
    *,
    active_runs: list[dict],
    state: dict,
    launcher,
) -> None:
    """Vertical RUNNING NOW list showing every paper + shadow instance
    of the currently-selected engine. Compact one-line rows, built to
    scale to many runs (scroll when needed). Click to swap mode + focus.
    """
    if not active_runs:
        return

    container = tk.Frame(parent, bg=BG)
    container.pack(fill="x", padx=0, pady=(0, 6))

    header = tk.Frame(container, bg=BG)
    header.pack(fill="x")
    tk.Frame(header, bg=AMBER, width=3, height=12).pack(side="left", padx=(0, 5))
    tk.Label(header, text="ENGINES", font=(FONT, 7, "bold"),
             fg=AMBER, bg=BG).pack(side="left")
    tk.Label(header, text=f"  ·  {len(active_runs)}", font=(FONT, 7),
             fg=DIM, bg=BG).pack(side="left")
    tk.Frame(container, bg=BORDER, height=1).pack(fill="x", pady=(2, 2))

    # Scrollable body — caps at 6 visible rows (~138 px) before scrolling
    # so the picker never dominates the detail pane.
    max_visible_rows = 6
    row_h_px = 23
    body_h = min(len(active_runs), max_visible_rows) * row_h_px + 2
    if len(active_runs) > max_visible_rows:
        canvas = tk.Canvas(container, bg=BG, highlightthickness=0, height=body_h)
        vbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)
        inner.bind("<Configure>",
                   lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vbar.set)
        canvas.pack(side="left", fill="x", expand=True)
        vbar.pack(side="right", fill="y")
        body = inner
    else:
        body = tk.Frame(container, bg=BG)
        body.pack(fill="x")

    current_mode = state.get("mode")
    current_paper = state.get("selected_paper_run_id")
    current_shadow = state.get("selected_shadow_run_id")

    def _make_click(rid: str, target_mode: str):
        def _click(_event=None):
            if target_mode == "paper":
                state["selected_paper_run_id"] = rid
            elif target_mode == "shadow":
                state["selected_shadow_run_id"] = rid
            set_mode = state.get("set_mode")
            if target_mode != current_mode and callable(set_mode):
                set_mode(target_mode)
            else:
                _render_detail(state, launcher)
        return _click

    for r in active_runs:
        rid = r.get("run_id") or ""
        label = r.get("label") or (f"#{rid.split('_')[-1][:6]}" if rid else "?")
        mode = str(r.get("mode") or "").lower()
        ticks = r.get("ticks_ok", 0)
        is_active = (
            mode == current_mode
            and rid == (current_paper if mode == "paper" else current_shadow)
        )
        mode_color = _MODE_COLORS.get(mode, CYAN)
        row_bg = BG2 if is_active else BG
        row_fg = mode_color if is_active else WHITE
        border = mode_color if is_active else BORDER

        r_row = tk.Frame(
            body, bg=row_bg,
            highlightbackground=border, highlightthickness=1,
            cursor="hand2",
        )
        r_row.pack(fill="x", padx=0, pady=1)

        dot = "●" if is_active else "○"
        tk.Label(r_row, text=dot, fg=GREEN if is_active else DIM,
                 bg=row_bg, font=(FONT, 8, "bold")).pack(
            side="left", padx=(6, 4), pady=1)
        tk.Label(r_row, text=f"{mode.upper():<6}", fg=mode_color,
                 bg=row_bg, font=(FONT, 7, "bold")).pack(
            side="left", padx=(0, 6), pady=1)
        tk.Label(r_row, text=label, fg=row_fg, bg=row_bg,
                 font=(FONT, 8, "bold")).pack(side="left", padx=(0, 6), pady=1)
        tk.Label(r_row, text=f"{ticks} tk", fg=DIM if is_active else DIM2,
                 bg=row_bg, font=(FONT, 7)).pack(side="right", padx=(0, 8), pady=1)

        for w in (r_row,) + tuple(r_row.winfo_children()):
            w.bind("<Button-1>", _make_click(rid, mode))


def _active_mode_runs(mode: str, *, launcher=None, state=None,
                      engine: str | None = None) -> list[dict]:
    """List active runs for ``mode`` filtered by ``engine`` (default None =
    all engines).

    Pre 2026-04-22: hardcoded a MILLENNIUM. Com runners per-engine
    (citadel/jump/renaissance) publicando no mesmo live_runs, o filter
    passou a ser parametrico. Default None mostra todas as engines; o
    sidebar filtra depois via `_active_engine_runs(slug, ...)`.
    """
    wanted = (engine or "").lower()
    cached_runs = _load_cockpit_runs_cached(launcher=launcher, state=state)
    matches_by_id: dict[str, dict] = {}
    for row in cached_runs:
        row_engine = str(row.get("engine") or "").lower()
        if wanted and row_engine != wanted:
            continue
        if str(row.get("mode") or "").lower() != mode:
            continue
        if str(row.get("status") or "").lower() != "running":
            continue
        run_id = str(row.get("run_id") or "")
        if not run_id:
            continue
        matches_by_id[run_id] = {
            "run_id": run_id,
            "engine": row_engine,
            "label": row.get("label"),
            "ticks_ok": int(row.get("novel_total") or 0),
            "novel_total": int(row.get("novel_total") or 0),
            "started_at": row.get("started_at"),
            "last_tick_at": row.get("last_tick_at"),
            "status": row.get("status"),
            "source": "vps",
        }

    # VPS is source-of-truth; DB is fallback only when VPS answered empty
    # for this mode (tunnel offline / pre-warmup).
    vps_has_runs_for_mode = any(
        str(r.get("mode") or "").lower() == mode
        and str(r.get("status") or "").lower() == "running"
        for r in cached_runs
    )
    for row in run_catalog.collect_db_runs(mode=mode, limit=100):
        row_engine = str(row.engine or "").lower()
        if wanted and row_engine != wanted:
            continue
        if str(row.status or "").lower() != "running":
            continue
        payload = matches_by_id.get(row.run_id)
        if payload is None:
            if vps_has_runs_for_mode:
                continue
            matches_by_id[row.run_id] = {
                "run_id": row.run_id,
                "engine": row_engine,
                "label": row.label,
                "ticks_ok": row.ticks_ok or 0,
                "novel_total": row.novel or 0,
                "started_at": row.started_at,
                "last_tick_at": row.last_tick_at,
                "status": row.status,
                "source": row.source,
            }
            continue
        if row.label and not payload.get("label"):
            payload["label"] = row.label
        if row.ticks_ok is not None:
            payload["ticks_ok"] = row.ticks_ok
        if row.novel is not None:
            payload["novel_total"] = row.novel

    matches = list(matches_by_id.values())
    matches.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
    return matches


def _active_paper_runs(launcher, state: dict | None = None,
                       engine: str | None = None) -> list[dict]:
    return _active_mode_runs("paper", launcher=launcher, state=state, engine=engine)


def _active_shadow_runs(launcher=None, state: dict | None = None,
                        engine: str | None = None) -> list[dict]:
    return _active_mode_runs("shadow", launcher=launcher, state=state, engine=engine)


def _fetch_shadow_run_id(state: dict | None = None) -> str | None:
    shadow_runs = _active_shadow_runs(state=state)
    if not shadow_runs:
        return None
    active = [r for r in shadow_runs if str(r.get("status") or "").lower() == "running"]
    if state is not None:
        picked = state.get("selected_shadow_run_id")
        if picked and any(r.get("run_id") == picked for r in active):
            return picked
    if active:
        return active[0].get("run_id")
    return shadow_runs[0].get("run_id")


def _fetch_paper_run_id(launcher, state: dict | None = None) -> str | None:
    """Resolve which paper run_id the detail pane should render.

    Precedence:
      1. ``state["selected_paper_run_id"]`` — if it points at a still-active
         paper run (operator picked this explicitly via the instance
         picker).
      2. Most recent active paper run.
      3. Most recent paper run of any status (legacy fallback so stopped
         runs still surface when nothing else is alive).
      4. ``None`` — cockpit unreachable or no paper runs at all.
    """
    paper_runs = _active_paper_runs(launcher, state)
    if not paper_runs:
        return None
    active = [r for r in paper_runs if str(r.get("status") or "").lower() == "running"]
    if state is not None:
        picked = state.get("selected_paper_run_id")
        if picked and any(r.get("run_id") == picked for r in active):
            return picked
    if active:
        return active[0].get("run_id")
    return paper_runs[0].get("run_id")


def _fetch_paper_extras_sync(run_id: str) -> tuple[dict | None, list[dict], list[float], dict | None, list[dict]]:
    """Fetch heartbeat + account + positions + equity + trades via cockpit API.
    Returns (heartbeat, positions, equity_series, account_snapshot, trades).

    Trades are the closed-trade history (reports/trades.jsonl locally,
    /v1/runs/{id}/trades remotely). Primed signals (status markers from
    first-N-ticks) are filtered out so the paper pane only shows real
    executed trades.
    """
    summary = run_catalog.get_run_summary(run_id, client=_get_cockpit_client())
    if summary is not None and summary.run_dir is not None:
        hb = dict(summary.heartbeat or {})
        if summary.started_at and "started_at" not in hb:
            hb["started_at"] = summary.started_at
        if summary.last_tick_at and "last_tick_at" not in hb:
            hb["last_tick_at"] = summary.last_tick_at
        if summary.status and "status" not in hb:
            hb["status"] = summary.status
        if summary.run_id and "run_id" not in hb:
            hb["run_id"] = summary.run_id

        # Track whether ANY state file actually existed on disk. A VPS-only
        # run has summary.run_dir set (via merge_runs from the DB) but none
        # of the state files exist locally — if we early-return on that
        # partial state, the /v1/runs/{id}/trades endpoint never runs and
        # the operator sees a blank TRADE HISTORY. Only take the local path
        # when at least one state file was real on disk.
        had_disk_data = False

        positions: list[dict] = []
        positions_path = summary.run_dir / "state" / "positions.json"
        if positions_path.exists():
            had_disk_data = True
            try:
                payload = json.loads(positions_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    positions = list(payload.get("positions") or [])
                elif isinstance(payload, list):
                    positions = payload
            except Exception:
                positions = []

        account: dict | None = None
        account_path = summary.run_dir / "state" / "account.json"
        if account_path.exists():
            had_disk_data = True
            try:
                payload = json.loads(account_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    account = payload
            except Exception:
                account = None

        series: list[float] = []
        equity_path = summary.run_dir / "reports" / "equity.jsonl"
        if equity_path.exists():
            had_disk_data = True
            try:
                points = run_catalog._tail_jsonl_records(equity_path, limit=200)
                series = [float(point.get("equity") or 0.0) for point in points]
            except Exception:
                series = []

        trades: list[dict] = []
        trades_path = summary.run_dir / "reports" / "trades.jsonl"
        if trades_path.exists():
            had_disk_data = True
            try:
                records = run_catalog._tail_jsonl_records(trades_path, limit=50)
                trades = [r for r in records if not r.get("primed", False)]
            except Exception:
                trades = []

        if had_disk_data:
            if account is None and hb:
                account = {
                    "equity": hb.get("equity", 0.0),
                    "drawdown_pct": hb.get("drawdown_pct", 0.0),
                    "initial_balance": hb.get("account_size", 10_000.0),
                    "realized_pnl": 0.0,
                    "unrealized_pnl": 0.0,
                    "ks_state": hb.get("ks_state", "NORMAL"),
                    "metrics": {},
                }
            return hb or None, positions, series, account, trades

    client = _get_cockpit_client()
    if client is None:
        return None, [], [], None, []
    hb: dict | None = None
    positions: list[dict] = []
    series: list[float] = []
    account: dict | None = None
    trades: list[dict] = []
    endpoints = {
        "heartbeat": f"/v1/runs/{run_id}/heartbeat",
        "positions": f"/v1/runs/{run_id}/positions",
        "equity": f"/v1/runs/{run_id}/equity?tail=200",
        "account": f"/v1/runs/{run_id}/account",
        "trades": f"/v1/runs/{run_id}/trades?limit=50",
    }
    with ThreadPoolExecutor(max_workers=len(endpoints)) as pool:
        futures = {
            pool.submit(client._get, path): name
            for name, path in endpoints.items()
        }
        for future in as_completed(futures):
            try:
                payload = future.result()
            except Exception:
                continue
            name = futures[future]
            if name == "heartbeat" and isinstance(payload, dict):
                hb = payload
            elif name == "positions" and isinstance(payload, dict):
                positions = list(payload.get("positions") or [])
            elif name == "equity" and isinstance(payload, dict):
                series = [
                    float(point.get("equity") or 0.0)
                    for point in (payload.get("points") or [])
                ]
            elif name == "account" and isinstance(payload, dict) and payload.get("available"):
                account = payload
            elif name == "trades" and isinstance(payload, dict):
                trades = [
                    t for t in (payload.get("trades") or [])
                    if isinstance(t, dict) and not t.get("primed", False)
                ]
    # Fallback: if /account endpoint missing (older cockpit), build minimal
    # snapshot from heartbeat fields (equity, drawdown_pct, ks_state, account_size).
    if account is None and hb is not None:
        account = {
            "equity": hb.get("equity", 0.0),
            "drawdown_pct": hb.get("drawdown_pct", 0.0),
            "initial_balance": hb.get("account_size", 10_000.0),
            "realized_pnl": 0.0, "unrealized_pnl": 0.0,
            "ks_state": hb.get("ks_state", "NORMAL"),
            "metrics": {},
        }
    return hb, positions, series, account, trades


def _fetch_paper_extras(run_id: str, *, launcher=None, state=None,
                        allow_sync: bool = False) -> tuple[dict | None, list[dict], list[float], dict | None, list[dict]]:
    now = time.monotonic()
    with _PAPER_SNAPSHOT_LOCK:
        cached = _PAPER_SNAPSHOT_CACHE.get(run_id)
        if cached is not None and (now - cached[0]) <= _PAPER_SNAPSHOT_CACHE_TTL_S:
            return cached[1]
        if allow_sync:
            _PAPER_SNAPSHOT_LOADING.add(run_id)
        elif run_id in _PAPER_SNAPSHOT_LOADING:
            return cached[1] if cached is not None else (None, [], [], None, [])
        else:
            _PAPER_SNAPSHOT_LOADING.add(run_id)

            def _worker() -> None:
                payload = _fetch_paper_extras_sync(run_id)
                with _PAPER_SNAPSHOT_LOCK:
                    _PAPER_SNAPSHOT_CACHE[run_id] = (time.monotonic(), payload)
                    _PAPER_SNAPSHOT_LOADING.discard(run_id)
                _schedule_state_refresh(launcher, state)

            threading.Thread(
                target=_worker,
                name=f"engines-live-paper-{run_id}",
                daemon=True,
            ).start()
            return cached[1] if cached is not None else (None, [], [], None, [])
    payload = _fetch_paper_extras_sync(run_id)
    with _PAPER_SNAPSHOT_LOCK:
        _PAPER_SNAPSHOT_CACHE[run_id] = (time.monotonic(), payload)
        _PAPER_SNAPSHOT_LOADING.discard(run_id)
    return payload


def _paper_content_sig(state, launcher=None) -> tuple:
    run_id = _fetch_paper_run_id(launcher, state)
    if run_id is None:
        return ("no-run", bool(_cockpit_runs_loading()))
    hb, positions, series, account, trades = _fetch_paper_extras(
        run_id,
        launcher=launcher,
        state=state,
    )
    if hb is None:
        return ("loading", run_id)
    last_equity = series[-1] if series else None
    account_sig = None
    if isinstance(account, dict):
        account_sig = (
            account.get("equity"),
            account.get("drawdown_pct"),
            account.get("available"),
            account.get("ks_state"),
        )
    positions_sig = (
        len(positions),
        tuple(
            (p.get("symbol"), p.get("side"), p.get("qty"), p.get("pnl", p.get("unrealized_pnl")))
            for p in positions[:8]
        ),
    )
    hb_sig = (
        hb.get("status"),
        hb.get("last_tick_at"),
        hb.get("equity"),
        hb.get("drawdown_pct"),
        hb.get("novel_total"),
    )
    trades_sig = (
        len(trades),
        trades[-1].get("timestamp") if trades else None,
    )
    return (
        run_id,
        hb_sig,
        positions_sig,
        len(series),
        last_equity,
        account_sig,
        trades_sig,
        state.get("selected_paper_run_id"),
    )


def _render_detail_paper(parent, slug, meta, state, launcher) -> None:
    """Render PAPER mode detail pane with full trading dashboard.
    Reuses render_detail (mode='paper') extended kwargs: account_snapshot,
    open_positions, equity_series, on_stop_paper, on_flatten_paper.
    """
    name = meta.get("display", slug.upper())

    # Instance picker antes ficava aqui (vertical table no detail pane).
    # Agora foi merged na sidebar ENGINES — ve-se engine + instancias
    # juntos, uma so tabela em vez de duas. Call site removido.

    # Discover which paper run_id the detail pane should render
    run_id = _fetch_paper_run_id(launcher, state)
    if run_id is None:
        if _cockpit_runs_loading():
            _render_hl2_empty(
                parent,
                title="LOADING PAPER RUNS",
                blurb=("Consultando o cockpit sem travar a abertura da tela.\n"
                       "As instancias paper aparecem assim que /v1/runs responder."),
                actions=[],
            )
            _schedule_paper_refresh(launcher, state)
        else:
            _render_paper_no_run(parent, launcher, state)
        return

    hb, positions, series, account, trades = _fetch_paper_extras(
        run_id,
        launcher=launcher,
        state=state,
    )
    if hb is None:
        _render_hl2_empty(
            parent,
            title="LOADING PAPER TELEMETRY",
            blurb=("Abrindo o cockpit sem bloquear a UI.\n"
                   "Heartbeat, positions e equity vao hidratar em seguida."),
            actions=[],
            hint="Se o tunnel/VPS estiver lento, os dados entram no proximo refresh.",
        )
        _schedule_paper_refresh(launcher, state)
        return

    tun_text, tun_color = _get_tunnel_status_label()
    status = str(hb.get("status") or "unknown").upper()
    status_color = GREEN if status == "RUNNING" else DIM2

    # Paper trade history comes through now (reports/trades.jsonl locally,
    # /v1/runs/{id}/trades via VPS). Was passed as empty until 2026-04-24
    # when the operator asked where closed-trade telemetry went.
    def _on_paper_row_click(trade: dict):
        state["paper_selected_trade"] = trade
        _render_detail(state, launcher)

    def _on_paper_close_detail():
        state.pop("paper_selected_trade", None)
        _render_detail(state, launcher)

    # Drop stale selection if the trade fell off the tail window.
    paper_selected = state.get("paper_selected_trade")
    if paper_selected is not None and trades:
        sel_key = (paper_selected.get("symbol"), paper_selected.get("timestamp"))
        known_keys = {(t.get("symbol"), t.get("timestamp")) for t in trades}
        if sel_key not in known_keys:
            state.pop("paper_selected_trade", None)
            paper_selected = None

    detail_frame = render_detail(
        parent=parent,
        engine_display=name,
        mode="paper",
        heartbeat=hb,
        manifest=None,
        trades=trades,
        on_row_click=_on_paper_row_click,
        status_badge_text=f"TUNNEL {tun_text}  ·  {status}  ·  run {run_id}",
        status_badge_color=status_color,
        account_snapshot=account,
        open_positions=positions,
        equity_series=series,
        selected_trade=paper_selected,
        on_close_detail=_on_paper_close_detail,
    )

    state["paper_last_render_sig"] = _paper_content_sig(state, launcher)

    # Re-render every 5s to keep dashboard live
    _schedule_paper_refresh(launcher, state)


def _render_paper_empty_state(parent, launcher, state):
    """Paper landing — no slug selected."""
    _render_hl2_empty(
        parent,
        title="PAPER MODE",
        blurb=("Paper runner executa MILLENNIUM (CITADEL + JUMP + RENAISSANCE)\n"
               "com posições simuladas, equity ao vivo, drawdown tracking e\n"
               "KS fast-halt. Account configurável.\n\n"
               "Selecione um engine na sidebar ou inicie o runner VPS abaixo."),
        actions=[("▶ START PAPER", GREEN,
                  lambda: _start_paper_via_cockpit(launcher, state))],
        hint="Manual:  sudo systemctl start millennium_paper.service",
    )
    _schedule_paper_refresh(launcher, state)


def _render_paper_no_run(parent, launcher, state):
    """Paper slug selected but cockpit shows no paper run."""
    diag = _get_tunnel_error_hint()
    blurb = ("Nenhum paper run detectado via cockpit API.\n"
             "Tunnel offline, runner parado, ou ainda nÃ£o iniciado.")
    if diag:
        blurb += f"\n\nDiagnostico do tunnel: {diag}"
    _render_hl2_empty(
        parent,
        title="NO PAPER RUN VISIBLE",
        blurb=("Nenhum paper run detectado via cockpit API.\n"
               "Tunnel offline, runner parado, ou ainda não iniciado."),
        actions=[("▶ START PAPER ON VPS", GREEN,
                  lambda: _start_paper_via_cockpit(launcher, state))],
        hint="Manual:  sudo systemctl start millennium_paper.service",
    )
    _schedule_paper_refresh(launcher, state)


def _start_paper_via_cockpit(launcher, state) -> None:
    """POST /v1/shadow/start?service=millennium_paper (admin-scoped).
    Same whitelist endpoint used for shadow; paper just picks different service."""
    client = _get_cockpit_client()
    if client is None:
        _toast(launcher,
               "cockpit_api nao configurado em config/keys.json",
               error=True)
        return
    if not client.cfg.admin_token:
        _toast(launcher,
               "admin_token ausente — apenas read disponivel", error=True)
        return
    try:
        result = client._post("/v1/shadow/start?service=millennium_paper",
                              admin=True)
    except Exception as exc:
        _toast(launcher, f"paper start failed: {exc}", error=True)
        return
    status = result.get("status") if isinstance(result, dict) else None
    if status == "started":
        _toast(launcher, "paper started — aparece em 5-15s")
        _schedule_paper_refresh(launcher, state)
    else:
        _toast(launcher, f"paper start retornou: {result}", error=True)


def _stop_paper_via_cockpit(launcher, state, run_id: str) -> None:
    """POST /v1/runs/<run_id>/kill (admin-scoped). Drops .kill flag in run dir."""
    client = _get_cockpit_client()
    if client is None or not client.cfg.admin_token:
        _toast(launcher, "admin_token ausente em keys.json", error=True)
        return
    try:
        client.drop_kill(run_id)
    except Exception as exc:
        _toast(launcher, f"paper STOP falhou: {type(exc).__name__}",
               error=True)
        return
    _toast(launcher, f"paper STOP dispatched → {run_id} · para em <=15s")
    _schedule_paper_refresh(launcher, state)


def _schedule_paper_refresh(launcher, state) -> None:
    """Agenda re-render em 5s. Single-slot handle cancelado antes de agendar
    pra evitar leak de handles. Espelha _schedule_shadow_refresh."""
    prev_aid = state.pop("paper_refresh_aid", None)
    if prev_aid is not None:
        try:
            launcher.after_cancel(prev_aid)
        except Exception:
            pass
    try:
        aid = launcher.after(60000,
                             lambda: _refresh_paper_detail(launcher, state))
        state["paper_refresh_aid"] = aid
    except Exception:
        pass


def _refresh_paper_detail(launcher, state) -> None:
    """Re-render paper detail if still in paper mode."""
    if state.get("mode") != "paper":
        return
    try:
        host = state.get("detail_host")
        if host is None or not host.winfo_exists():
            return
    except Exception:
        return
    sig = _paper_content_sig(state, launcher)
    last_sig = state.get("paper_last_render_sig")
    if sig == last_sig and last_sig is not None:
        _schedule_paper_refresh(launcher, state)
        return
    state["paper_last_render_sig"] = sig
    _render_detail(state, launcher)


# Canonical VPS services — one systemd unit per (engine, mode, instance).
# Matches what ``deploy/install_paper_multi_vps.sh`` and friends install.
# Keeping order stable so the control bar doesn't reorder on refresh.
VPS_CANONICAL_SERVICES = (
    "citadel_shadow@desk-a",
    "citadel_paper@desk-a",
    "jump_shadow@desk-a",
    "jump_paper@desk-a",
    "renaissance_shadow@desk-a",
    "renaissance_paper@desk-a",
    "millennium_shadow@desk-shadow-a",
    "millennium_shadow@desk-shadow-b",
    "millennium_paper@desk-paper-a",
    "millennium_paper@desk-paper-b",
)
_VPS_MANAGED_ENGINES = {"citadel", "jump", "renaissance", "millennium"}


def _vps_service_display_name(svc: str) -> str:
    """``citadel_paper@desk-a`` → ``CITADEL PAPER A``.
    ``millennium_shadow@desk-shadow-b`` → ``MILLENNIUM SHADOW B``."""
    base, _, inst = svc.partition("@")
    eng_mode = base.replace("_", " ").upper()
    if not inst:
        return eng_mode
    # Last token after '-' disambiguates instance (desk-a → A, desk-paper-a → A).
    tail = inst.rsplit("-", 1)[-1].upper()
    return f"{eng_mode} {tail}"


def _render_vps_control_bar(parent, launcher, state) -> None:
    """HL2/institutional VPS control rail pinned above the detail pane.

    One labelled row per service rendered as a grid:

        ┌─ VPS · TUNNEL UP ─────────────────────────────────────┐
        │ ●  CITADEL PAPER A     RUNNING   [■STOP][↻RESTART]    │
        │ ○  JUMP PAPER A        STOPPED   [▶START]             │
        │ ●  MILLENNIUM SHADOW B RUNNING   [■STOP][↻RESTART]    │
        └──────────────────────────────────────────────────────┘

    Status inferred from /v1/runs (cheaper than systemctl is-active).
    Runs use ``(engine, mode, label)`` to build the systemd unit name —
    this matches the ``{engine}_{mode}@{label}.service`` units installed
    by ``deploy/install_paper_multi_vps.sh``. Services discovered from
    runs data are merged with ``VPS_CANONICAL_SERVICES`` so rows for
    stopped engines still show a START chip instead of disappearing.
    """
    bar = tk.Frame(parent, bg=BG, highlightbackground=BORDER,
                   highlightthickness=1)
    bar.pack(fill="x", padx=0, pady=(0, 4))

    # Header strip — institutional caps, tunnel badge inline
    hdr = tk.Frame(bar, bg=BG)
    hdr.pack(fill="x", padx=10, pady=(5, 3))
    tk.Label(hdr, text="VPS", fg=AMBER, bg=BG,
             font=(FONT, 7, "bold")).pack(side="left")
    tk.Label(hdr, text="  ·  TUNNEL ", fg=DIM2, bg=BG,
             font=(FONT, 6, "bold")).pack(side="left")
    tun_text, tun_fg = _get_tunnel_status_label()
    tk.Label(hdr, text=tun_text, fg=tun_fg, bg=BG,
             font=(FONT, 7, "bold")).pack(side="left")

    tk.Frame(bar, bg=BORDER, height=1).pack(fill="x", padx=10)

    # Seed with canonical services (so stopped ones still render a row),
    # then flip to "running" for each live run matching our managed set.
    services_state: dict[str, str] = {
        svc: "stopped" for svc in VPS_CANONICAL_SERVICES
    }
    runs = _load_cockpit_runs_cached(launcher=launcher, state=state)
    if runs:
        for r in runs:
            engine = str(r.get("engine") or "").lower()
            mode = r.get("mode")
            label = str(r.get("label") or "")
            status = r.get("status")
            if (engine not in _VPS_MANAGED_ENGINES
                    or mode not in ("paper", "shadow")
                    or not label):
                continue
            svc = f"{engine}_{mode}@{label}"
            # Pick up runs on unexpected labels too (e.g. desk-b on citadel).
            if status == "running":
                services_state[svc] = "running"
            elif svc not in services_state:
                services_state[svc] = "stopped"

    # Rows — institutional grid (fixed-width columns so pair aligns)
    for svc, svc_state in services_state.items():
        nice_name = _vps_service_display_name(svc)
        row = tk.Frame(bar, bg=BG)
        row.pack(fill="x", padx=10, pady=2)

        running = svc_state == "running"
        dot = "●" if running else "○"
        dot_color = (GREEN if running else
                     (DIM2 if svc_state == "stopped" else AMBER))
        tk.Label(row, text=dot, fg=dot_color, bg=BG,
                 font=(FONT, 9)).pack(side="left", padx=(0, 6))

        tk.Label(row, text=nice_name, fg=WHITE, bg=BG,
                 font=(FONT, 7, "bold"), width=20,
                 anchor="w").pack(side="left")

        state_text = svc_state.upper()
        state_color = (GREEN if running else
                       (DIM if svc_state == "stopped" else AMBER))
        tk.Label(row, text=state_text, fg=state_color, bg=BG,
                 font=(FONT, 7, "bold"), width=9,
                 anchor="w").pack(side="left")

        def _make_action(_svc, _action):
            return lambda _e: _systemctl_via_cockpit(
                launcher, state, _svc, _action)

        if running:
            chips = [("■ STOP", RED, "stop"),
                     ("↻ RESTART", AMBER, "restart")]
        else:
            chips = [("▶ START", GREEN, "start")]
        for label, color, action in chips:
            chip = tk.Label(row, text=f" {label} ", fg=BG, bg=color,
                            font=(FONT, 6, "bold"), cursor="hand2",
                            padx=5, pady=1)
            chip.pack(side="left", padx=(4, 0))
            chip.bind("<Button-1>", _make_action(svc, action))

    # Bottom spacing
    tk.Frame(bar, bg=BG, height=4).pack(fill="x")


def _systemctl_via_cockpit(launcher, state, service: str, action: str) -> None:
    """Dispara systemctl <action> <service> via /v1/systemctl/<action>.
    Whitelist do backend rejeita anything fora de ALLOWED_ACTIONS/SERVICES."""
    client = _get_cockpit_client()
    if client is None or not getattr(client.cfg, "admin_token", None):
        _toast(launcher, "admin_token ausente em keys.json", error=True)
        return
    try:
        result = client._post(
            f"/v1/systemctl/{action}?service={service}", admin=True)
    except Exception as exc:
        _toast(launcher, f"{service} {action} falhou: {exc}", error=True)
        return
    rc = result.get("returncode", -1) if isinstance(result, dict) else -1
    if rc == 0:
        _toast(launcher, f"{service} {action} OK — aparece em 5-15s")
    else:
        stderr = result.get("stderr", "") if isinstance(result, dict) else ""
        _toast(launcher, f"{service} {action} rc={rc}: {stderr[:80]}",
               error=True)
    # Clear cache so next render shows fresh state
    try:
        launcher.after(2500,
                       lambda: _force_refresh_shadow(launcher, state))
    except Exception:
        pass


def _restart_shadow_via_cockpit(launcher, state, run_dir) -> None:
    """Stop current shadow run + start new one. Espera ~5s entre as duas
    acoes pra systemd processar o stop antes do start."""
    client = _get_cockpit_client()
    if client is None or not getattr(client.cfg, "admin_token", None):
        _toast(launcher, "admin_token ausente — RESTART indisponivel",
               error=True)
        return
    # Drop kill flag first
    if _is_remote_run(run_dir):
        run_id = _remote_run_id(run_dir)
        try:
            client.drop_kill(run_id)
        except Exception as exc:
            _toast(launcher, f"RESTART stop failed: {exc}", error=True)
            return
        _toast(launcher, f"RESTART: stopping {run_id}, new run em ~10s...")
        # Schedule the start after 10s (tick grace)
        try:
            launcher.after(10_000, lambda: _start_shadow_via_cockpit(
                launcher, state))
        except Exception:
            _start_shadow_via_cockpit(launcher, state)
    else:
        _toast(launcher, "RESTART local run: use STOP + manual start",
               error=True)


def _force_refresh_shadow(launcher, state) -> None:
    """Clear stale poller cache + trigger immediate re-fetch from VPS.
    Use quando heartbeat parece stale (UI mostra dados antigos apesar
    do VPS ter mudado)."""
    try:
        from launcher_support.tunnel_registry import get_shadow_poller
        poller = get_shadow_poller()
    except Exception:
        poller = None
    if poller is not None:
        # Tenta metodos conhecidos pra invalidar cache. Poller pode ter
        # set_cache/invalidate/clear_cache segundo implementacao.
        for method_name in ("invalidate_cache", "clear_cache", "force_refresh"):
            fn = getattr(poller, method_name, None)
            if callable(fn):
                try:
                    fn()
                    break
                except Exception:
                    pass
    # Also clear local cache files
    try:
        from pathlib import Path as _Path
        cache_dir = _Path("data/.cockpit_cache")
        for f in cache_dir.glob("heartbeat_*.json"):
            try:
                f.unlink()
            except OSError:
                pass
    except Exception:
        pass
    _toast(launcher, "cache limpo — re-fetching...")
    # Trigger render immediately
    _refresh_shadow_detail(launcher, state)


def _start_shadow_via_cockpit(launcher, state) -> None:
    """POST /v1/shadow/start (admin token) + feedback inline no cockpit."""
    client = _get_cockpit_client()
    if client is None:
        _toast(launcher,
               "cockpit_api nao configurado em config/keys.json — nao da pra start remoto",
               error=True)
        return
    if not client.cfg.admin_token:
        _toast(launcher,
               "admin_token ausente em cockpit_api config — apenas read disponivel",
               error=True)
        return
    try:
        # CockpitClient._post handle circuit breaker + HTTP; retorna dict.
        result = client._post("/v1/shadow/start", admin=True)
    except Exception as exc:  # noqa: BLE001
        _toast(launcher, f"start failed: {exc}", error=True)
        return
    status = result.get("status") if isinstance(result, dict) else None
    if status == "started":
        _toast(launcher, "shadow started — aparece em 5-15s")
        _schedule_shadow_refresh(launcher, state)
    else:
        _toast(launcher, f"start retornou: {result}", error=True)


def _toast(launcher, msg: str, error: bool = False) -> None:
    """Feedback transient: label flutuante que some em 4s. Evita popup modal."""
    try:
        from launcher_support.audio import notify as _audio_notify

        _audio_notify(launcher, error=error)
        color = RED if error else GREEN
        top = tk.Toplevel(launcher)
        top.overrideredirect(True)
        top.configure(bg=PANEL)
        top.attributes("-topmost", True)
        tk.Label(top, text=f"  {msg}  ", fg=BG, bg=color,
                 font=(FONT, 8, "bold"), padx=12, pady=6).pack()
        # Posiciona perto do centro-topo da janela principal
        launcher.update_idletasks()
        x = launcher.winfo_rootx() + launcher.winfo_width() // 2 - 150
        y = launcher.winfo_rooty() + 80
        top.geometry(f"+{x}+{y}")
        top.after(4000, top.destroy)
    except Exception:
        pass


def _render_detail_ready(parent, slug, meta, state, launcher):
    name = meta.get("display", slug.upper())
    desc = meta.get("desc", "")
    mode = state["mode"]
    run_color = _MODE_COLORS[mode]
    meta_stage_label, meta_stage_color = _stage_badge(meta)
    is_bootstrap = bool(meta.get("live_bootstrap")) and not bool(meta.get("live_ready"))
    stage_label = " BOOTSTRAP READY " if is_bootstrap else " DEPLOY READY "
    runner_label = "BOOTSTRAP" if is_bootstrap else "VALIDATED"
    role_label = "STAGING" if is_bootstrap else "LAB"
    route_label = "PREFLIGHT" if is_bootstrap else "UNIFIED"
    mandate_text = (
        "BOOTSTRAP -> PREFLIGHT -> ADAPTER BUILD\nNO REAL EXECUTION LOOP YET"
        if is_bootstrap else
        "RESEARCH -> EXECUTION\nSIGNAL -> RISK GATE -> MARKET"
    )
    cta_text = f"  {'BOOTSTRAP' if is_bootstrap else 'DEPLOY'} IN {mode.upper()}  "

    head = tk.Frame(parent, bg=PANEL)
    head.pack(fill="x", padx=12, pady=(8, 2))
    tk.Label(head, text=name, fg=AMBER, bg=PANEL,
             font=(FONT, 11, "bold")).pack(side="left")
    tk.Label(head, text=f" {meta_stage_label} ", fg=BG, bg=meta_stage_color,
             font=(FONT, 7, "bold"), padx=6, pady=1).pack(side="right", padx=(0, 6))
    tk.Label(head, text=stage_label, fg=BG, bg=GREEN,
             font=(FONT, 7, "bold"), padx=6, pady=1).pack(side="right")

    if desc:
        tk.Label(parent, text=desc.upper(), fg=DIM2, bg=PANEL,
                 font=(FONT, 7), anchor="w", justify="left",
                 wraplength=520).pack(fill="x", padx=12, pady=(0, 4))

    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12)

    # EXECUTION DESK — funde DEPLOY DECK + EXECUTION PROFILE. Mode pills
    # no header ja cobrem PAPER/DEMO/TESTNET/LIVE, entao ENVIRONMENT BANK
    # foi removido.
    desk = tk.Frame(parent, bg=BG2, highlightbackground=BORDER_H, highlightthickness=1)
    desk.pack(fill="x", padx=12, pady=(6, 4))
    top = tk.Frame(desk, bg=BG2)
    top.pack(fill="x", padx=10, pady=(6, 2))
    tk.Label(top, text="EXECUTION DESK", fg=AMBER_B, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="left")
    tk.Label(top, text=f"NEXT {mode.upper()}", fg=run_color, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="right")
    facts = tk.Frame(desk, bg=BG2)
    facts.pack(fill="x", padx=8, pady=(0, 4))
    _desk_metric(facts, "RUNNER", runner_label, GREEN)
    _desk_metric(facts, "ROUTING", route_label, WHITE)
    _desk_metric(facts, "ACCOUNT", mode.upper(), run_color)
    _desk_metric(facts, "RISK", "DESK LIMITS", WHITE)
    lev = tk.Frame(desk, bg=BG2)
    lev.pack(fill="x", padx=10, pady=(0, 6))
    tk.Label(lev, text="LEV", fg=DIM, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="left", padx=(0, 6))
    cfg_store = state.setdefault("config", {})
    cfg = cfg_store.setdefault(slug, {"leverage": "2.0"})
    for disp, val in _LEVERAGE_OPTS:
        active = cfg.get("leverage") == val
        pill = tk.Label(lev, text=f" {disp} ",
                        fg=(BG if active else DIM2),
                        bg=(AMBER if active else BG3),
                        font=(FONT, 7, "bold"),
                        cursor="hand2", padx=4, pady=0)
        pill.pack(side="left", padx=(0, 3))
        pill.bind("<Button-1>",
                  lambda _e, _v=val, _d=cfg, _s=state: _set_cfg(_d, "leverage", _v, _s))

    run = tk.Label(parent, text=cta_text,
                   fg=BG, bg=run_color, font=(FONT, 10, "bold"),
                   cursor="hand2", padx=8, pady=6)
    run.pack(fill="x", padx=12, pady=(0, 4))
    run.bind("<Button-1>", lambda _e: _run_engine(launcher, slug, meta, state))

    mandate = tk.Frame(parent, bg=BG2, highlightbackground=BORDER, highlightthickness=1)
    mandate.pack(fill="x", padx=12, pady=(0, 4))
    tk.Label(mandate, text=f"MANDATE  ·  {mandate_text.replace(chr(10), '  ·  ')}",
             fg=DIM2, bg=BG2, font=(FONT, 7), anchor="w",
             justify="left", wraplength=540).pack(
                 fill="x", padx=10, pady=(6, 6))

    # Shadow telemetry lives no modo dedicado SHADOW agora — nao polui
    # mais os modos paper/demo/testnet/live.

    actions = tk.Frame(parent, bg=PANEL)
    actions.pack(fill="x", padx=12, pady=(0, 12))
    _action_btn(actions, "VIEW CODE", DIM, lambda: _view_code(launcher, meta.get("script", "")))
    _action_btn(actions, "PAST RUNS", DIM, lambda: _past_runs(launcher, slug))


def _set_cfg(cfg_dict, key, val, state):
    cfg_dict[key] = val
    refresh = state.get("refresh")
    if callable(refresh):
        refresh()


def _run_engine(launcher, slug, meta, state):
    mode = state["mode"]
    raw_cfg = (state.get("config") or {}).get(slug) or {}
    cfg = {"leverage": raw_cfg.get("leverage", "2.0")}
    name = meta.get("display", slug.upper())
    script = meta.get("script", "")
    desc = meta.get("desc", "")

    def _spawn():
        fn = getattr(launcher, "_exec_live_inline", None)
        if callable(fn):
            fn(name, script, desc, mode, cfg)

    if mode == "live":
        _confirm_live_modal(launcher, name, on_confirm=_spawn)
    else:
        _spawn()


def _confirm_live_modal(launcher, engine_name, *, on_confirm):
    top = tk.Toplevel()
    top.title("LIVE EXECUTION")
    top.configure(bg=BG)
    top.geometry("420x240")
    top.resizable(False, False)
    top.transient()
    top.grab_set()

    tk.Label(top, text=f"LIVE EXECUTION — {engine_name}",
             fg=RED, bg=BG, font=(FONT, 10, "bold")).pack(pady=(14, 4))
    tk.Label(top, text=(f"Você está prestes a ligar {engine_name} em modo LIVE.\n"
                        "REAL MONEY. REAL ORDERS."),
             fg=WHITE, bg=BG, font=(FONT, 8), justify="center").pack(pady=(0, 10))
    tk.Label(top, text=f"DIGITE {engine_name} PRA CONFIRMAR:",
             fg=DIM, bg=BG, font=(FONT, 8)).pack()

    var = tk.StringVar()
    entry = tk.Entry(top, textvariable=var, bg=BG3, fg=WHITE,
                     insertbackground=WHITE, font=(FONT, 10),
                     width=28, justify="center",
                     highlightbackground=BORDER, highlightthickness=1)
    entry.pack(pady=8)
    entry.focus_set()

    row = tk.Frame(top, bg=BG)
    row.pack(pady=(6, 0))
    cancel = tk.Label(row, text="  CANCEL  ", fg=DIM, bg=BG3,
                      font=(FONT, 8, "bold"), cursor="hand2",
                      padx=4, pady=6)
    cancel.pack(side="left", padx=8)
    cancel.bind("<Button-1>", lambda _e: top.destroy())

    confirm = tk.Label(row, text="  CONFIRM & RUN  ",
                       fg=DIM2, bg=BG3,
                       font=(FONT, 8, "bold"), cursor="arrow",
                       padx=4, pady=6)
    confirm.pack(side="left", padx=8)

    def _on_change(*_):
        ok = live_confirm_ok(engine_name=engine_name, user_input=var.get())
        if ok:
            confirm.configure(fg=BG, bg=RED, cursor="hand2")
            confirm.bind("<Button-1>", lambda _e: (top.destroy(), on_confirm()))
        else:
            confirm.configure(fg=DIM2, bg=BG3, cursor="arrow")
            confirm.unbind("<Button-1>")
    var.trace_add("write", _on_change)
    top.bind("<Escape>", lambda _e: top.destroy())


def _past_runs(launcher, slug):
    fn = getattr(launcher, "_data_center", None)
    if callable(fn):
        fn()


def _render_detail_live(parent, slug, meta, state, launcher):
    name = meta.get("display", slug.upper())
    stage_label, stage_color = _stage_badge(meta)
    procs = _list_procs_cached()
    running = running_slugs_from_procs(procs)
    proc = running.get(slug, {})
    snap = _runtime_snapshot(slug, proc)
    mode_key = (proc.get("engine_mode") or proc.get("mode") or "paper").lower()
    mode_color = _MODE_COLORS.get(mode_key, CYAN)
    fleet = state.get("live_running_slugs") or []
    fleet_pos = (fleet.index(slug) + 1) if slug in fleet else 1

    _render_live_book(parent, state, running)

    head = tk.Frame(parent, bg=PANEL)
    head.pack(fill="x", padx=12, pady=(10, 4))
    tk.Label(head, text=name, fg=AMBER, bg=PANEL,
             font=(FONT, 11, "bold")).pack(side="left")
    tk.Label(head, text=f" {stage_label} ",
             fg=BG, bg=stage_color, font=(FONT, 7, "bold"),
             padx=6, pady=2).pack(side="left", padx=(8, 0))
    right = tk.Frame(head, bg=PANEL)
    right.pack(side="right")
    tk.Label(right, text=f"{fleet_pos}/{max(len(fleet), 1)}", fg=DIM2, bg=PANEL,
             font=(FONT, 7, "bold")).pack(side="left", padx=(0, 8))
    tk.Label(right, text="●", fg=GREEN, bg=PANEL,
             font=(FONT, 9, "bold")).pack(side="left")
    tk.Label(right, text=f" {mode_key.upper()} ",
             fg=BG, bg=mode_color, font=(FONT, 7, "bold"),
             padx=4, pady=1).pack(side="left", padx=(4, 0))
    # Same UTC-normalization as _uptime_seconds — naive `started` is
    # treated as UTC so Brazil-local clock doesn't drift short durations
    # (bug 2026-04-24). Prefers `started_at` from VPS API when available.
    started = proc.get("started_at") or proc.get("started")
    if started:
        try:
            from datetime import datetime as _dt, timezone as _tz
            parsed = _dt.fromisoformat(str(started).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_tz.utc)
            secs = (_dt.now(_tz.utc) - parsed).total_seconds()
            tk.Label(right, text=f" · {format_uptime(seconds=secs)}",
                     fg=DIM, bg=PANEL, font=(FONT, 8)).pack(side="left")
        except Exception:
            pass

    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12, pady=(4, 0))

    kpis = tk.Frame(parent, bg=PANEL)
    kpis.pack(fill="x", padx=12, pady=(8, 6))
    _kpi_col(kpis, "P/L",    _fmt_pnl(snap["pnl"]), _pnl_color(snap["pnl"]))
    _kpi_col(kpis, "OPEN",   str(snap["positions_count"]), WHITE)
    _kpi_col(kpis, "TRADES", str(proc.get("trades") or 0), WHITE)
    _kpi_col(kpis, "PID",    str(proc.get("pid") or "-"), DIM2)
    _kpi_col(kpis, "SIGNAL", str(snap["last_signal"])[:28], WHITE)

    # ENVIRONMENT BANK removido: mode pills no header ja indicam PAPER/
    # DEMO/TESTNET/LIVE. Operating map fica mais compacto.
    ops = tk.Frame(parent, bg=BG2, highlightbackground=BORDER_H, highlightthickness=1)
    ops.pack(fill="x", padx=12, pady=(4, 4))
    top = tk.Frame(ops, bg=BG2)
    top.pack(fill="x", padx=10, pady=(6, 2))
    tk.Label(top, text="OPERATING MAP", fg=AMBER_B, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="left")
    tk.Label(top, text="LAB -> LIVE", fg=mode_color, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="right")
    facts = tk.Frame(ops, bg=BG2)
    facts.pack(fill="x", padx=8, pady=(0, 4))
    _desk_metric(facts, "MODE", mode_key.upper(), mode_color)
    _desk_metric(facts, "UPTIME", format_uptime(seconds=_uptime_seconds(proc)), WHITE)
    _desk_metric(facts, "DESK", f"{fleet_pos}/{max(len(fleet), 1)}", WHITE)
    _desk_metric(facts, "RISK", f"{snap['positions_count']} BOOKS", WHITE)
    _desk_metric(facts, "FEED", "ATTACHED" if snap["log_path"] else "OFFLINE",
                 GREEN if snap["log_path"] else RED)

    lower = tk.Frame(parent, bg=PANEL)
    lower.pack(fill="both", expand=True, padx=12, pady=(0, 10))
    lower.grid_columnconfigure(0, weight=40, uniform="lower")
    lower.grid_columnconfigure(1, weight=60, uniform="lower")
    lower.grid_rowconfigure(0, weight=1)
    _render_positions_panel(lower, 0, snap["positions"])
    _render_log_panel(lower, 1, state, launcher, proc, snap)

    actions = tk.Frame(parent, bg=PANEL)
    actions.pack(fill="x", padx=12, pady=(0, 12))
    stop_btn = tk.Label(actions, text="  STOP ENGINE  ",
                        fg=WHITE, bg=RED,
                        font=(FONT, 10, "bold"),
                        cursor="hand2", padx=12, pady=8)
    stop_btn.pack(side="left", padx=(0, 8))
    _bind_hold_to_confirm(stop_btn,
                          on_confirm=lambda: _stop_engine(launcher, state, proc),
                          duration_ms=1500)
    _action_btn(actions, "OPEN LOG", DIM,
                lambda: _open_full_log(launcher, proc))
    _action_btn(actions, "REPORTS", DIM,
                lambda: _past_runs(launcher, slug))
    _action_btn(actions, "VIEW CODE", DIM,
                lambda: _view_code(launcher, meta.get("script", "")))


def _kpi_col(parent, label, value, color=WHITE):
    col = tk.Frame(parent, bg=PANEL)
    col.pack(side="left", fill="x", expand=True)
    tk.Label(col, text=label, fg=DIM, bg=PANEL,
             font=(FONT, 6, "bold")).pack(anchor="w")
    tk.Label(col, text=value, fg=color, bg=PANEL,
             font=(FONT, 8, "bold")).pack(anchor="w")


def _fmt_pnl(v):
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)[:10]
    return f"{'+' if f >= 0 else ''}${f:,.2f}"


def _schedule_log_tail(state, launcher, proc):
    box = state.get("log_box")
    if not box or not proc:
        return
    slug = state.get("selected_slug")
    if not slug:
        return
    lines = _read_log_tail(_resolve_log_path(slug, proc), n=18)
    box.configure(state="normal")
    box.delete("1.0", "end")
    if lines:
        for i, ln in enumerate(lines):
            if i > 0:
                box.insert("end", "\n")
            box.insert("end", ln, _classify_log_level(ln))
    else:
        box.insert("end", "(no log available)")
    box.configure(state="disabled")
    box.see("end")
    try:
        aid = launcher.after(1000,
                             lambda: _schedule_log_tail(state, launcher, proc))
        state["after_handles"].append(aid)
    except Exception:
        pass


def _open_full_log(launcher, proc):
    log_path = proc.get("log") or proc.get("log_path") or proc.get("log_file")
    if not log_path:
        return
    try:
        os.startfile(log_path)
    except Exception:
        pass


def _bind_hold_to_confirm(widget, *, on_confirm, duration_ms):
    tok = {"aid": None}

    def _down(_e=None):
        tok["aid"] = widget.after(duration_ms, _fire)

    def _up(_e=None):
        if tok["aid"]:
            try:
                widget.after_cancel(tok["aid"])
            except Exception:
                pass
            tok["aid"] = None

    def _fire():
        tok["aid"] = None
        on_confirm()

    widget.bind("<ButtonPress-1>", _down)
    widget.bind("<ButtonRelease-1>", _up)
    widget.bind("<Leave>", _up)


def _stop_engine(launcher, state, proc):
    try:
        from core.ops.proc import stop_proc
        stop_proc(int(proc["pid"]), expected=proc)
    except Exception:
        return
    refresh = state.get("refresh")
    if callable(refresh):
        refresh()
