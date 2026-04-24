"""ENGINES LIVE launcher screen."""
from __future__ import annotations

import tkinter as tk
from typing import Any

from core.data.connections import MARKETS
from core.ui.ui_palette import AMBER_D
from launcher_support.screens.base import Screen


class EnginesLiveScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any, conn: Any):
        super().__init__(parent)
        self.app = app
        self.conn = conn
        self.host: tk.Frame | None = None

    def build(self) -> None:
        self.host = tk.Frame(self.container)
        self.host.pack(fill="both", expand=True)

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        host = self.host
        if host is None:
            return

        app.h_path.configure(text="> ENGINES")
        market_label = MARKETS.get(self.conn.active_market, {}).get("label", "UNKNOWN")
        app.h_stat.configure(text=market_label, fg=AMBER_D)
        app.f_lbl.configure(text="ESC main  |  ▲▼ select  |  ENTER run  |  M cycle mode")
        app._bind_global_nav()
        # engines_live renders its own rich footer (hints + TUNNEL color)
        # inside the screen root — hide the app-wide footer here so the
        # bottom of the window shows one clear strip instead of two.
        if hasattr(app, "_hide_app_footer"):
            app._hide_app_footer()

        prior = getattr(app, "_engines_live_handle", None)
        prior_root = prior.get("root") if isinstance(prior, dict) else None
        if (
            isinstance(prior, dict)
            and prior_root is not None
            and getattr(prior_root, "winfo_exists", lambda: False)()
        ):
            try:
                rebind = prior.get("rebind")
                if callable(rebind):
                    rebind()
                refresh = prior.get("refresh")
                if callable(refresh):
                    refresh()
                return
            except Exception:
                pass

        for child in host.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass

        from launcher_support import engines_live_view

        if hasattr(app, "_schedule_first_paint_metric"):
            try:
                app._schedule_first_paint_metric("engines_live")
            except Exception:
                pass
        app._engines_live_handle = engines_live_view.render(
            app,
            host,
            on_escape=lambda: app._menu("main"),
        )

    def on_exit(self) -> None:
        super().on_exit()
        app = self.app
        prior = getattr(app, "_engines_live_handle", None)
        if prior and callable(prior.get("cleanup")):
            try:
                prior["cleanup"]()
            except Exception:
                pass
        # Restore the app-wide footer when leaving engines_live so the
        # next screen (which relies on app.f_lbl) stays visible.
        if hasattr(app, "_show_app_footer"):
            app._show_app_footer()


# ─────────────────────────────────────────────────────────────────────────────
# Functions extracted from launcher.App in Fase 3 refactor (Task 7)
# ─────────────────────────────────────────────────────────────────────────────

def tail_remote_worker(app, run_id: str, stop_event) -> None:
    """Background worker to tail a remote (VPS) engine log.

    Extracted from launcher.App._eng_tail_remote_worker in Fase 3 refactor.
    """
    from launcher_support import engine_logs_view

    engine_logs_view.tail_remote_worker(app, run_id, stop_event)


def tail_worker(app, log_path, stop_event) -> None:
    """Background worker to tail a local engine log file.

    Extracted from launcher.App._eng_tail_worker in Fase 3 refactor.
    """
    from launcher_support import engine_logs_view

    engine_logs_view.tail_worker(app, log_path, stop_event)


def poll_logs(app) -> None:
    """UI-thread poll: drain the log queue, update the text widget.

    Extracted from launcher.App._eng_poll_logs in Fase 3 refactor.
    """
    from launcher_support import engine_logs_view

    engine_logs_view.poll_logs(app)


def scan_vps_runs_live(limit: int = 10) -> list:
    """Resolve VPS engine-log rows (live module variant).

    Extracted from launcher.App._eng_scan_vps_runs in Fase 3 refactor.
    Canonical version is in launcher_support.screens.engines.scan_vps_runs.
    """
    from launcher_support.screens.engines import scan_vps_runs
    return scan_vps_runs(limit=limit)


def engines_now_playing(app, host, tracks, running_map) -> None:
    """NOW PLAYING strip -- running live engines as clickable pills above
    the picker. Clicking a pill: focuses that track + opens the LOG chip
    on the right panel so the user lands on the live tail (iPod feel).

    Extracted from launcher.App._engines_now_playing in Fase 3 refactor.
    """
    import tkinter as tk
    from datetime import datetime as _dt
    try:
        from core.ui.ui_palette import BG, BG2, BG3, BORDER, DIM, FONT, GREEN, WHITE
    except ImportError:
        BG = BG2 = BG3 = "#1a1a1a"
        BORDER = "#333333"
        DIM = "#888888"
        FONT = "Consolas"
        GREEN = "#00ff88"
        WHITE = "#ffffff"

    bar = tk.Frame(host, bg=BG2,
                   highlightbackground=BORDER, highlightthickness=1)
    bar.pack(fill="x", pady=(0, 6))
    tk.Label(bar, text="  NOW PLAYING ", font=(FONT, 7, "bold"),
             fg=BG, bg=GREEN, padx=6, pady=2).pack(side="left", padx=(4, 8), pady=4)

    slug_to_idx = {t.slug: i for i, t in enumerate(tracks)}
    for slug, proc in running_map.items():
        idx = slug_to_idx.get(slug)
        if idx is None:
            continue
        name = tracks[idx].name
        up_lbl = "—"
        try:
            started = proc.get("started")
            if started:
                t0 = _dt.fromisoformat(started)
                secs = (_dt.now() - t0).total_seconds()
                h, rem = divmod(int(secs), 3600)
                m, _ = divmod(rem, 60)
                up_lbl = f"{h}h{m:02d}m" if h else f"{m}m"
        except Exception:
            pass

        pill = tk.Frame(bar, bg=BG3,
                        highlightbackground=GREEN, highlightthickness=1,
                        cursor="hand2")
        pill.pack(side="left", padx=2, pady=4)
        tk.Label(pill, text="●", font=(FONT, 9, "bold"),
                 fg=GREEN, bg=BG3, padx=4).pack(side="left")
        tk.Label(pill, text=name, font=(FONT, 8, "bold"),
                 fg=WHITE, bg=BG3).pack(side="left", padx=(0, 4))
        tk.Label(pill, text=f" {up_lbl} ", font=(FONT, 7),
                 fg=DIM, bg=BG3).pack(side="left")

        def _focus(_e=None, _i=idx):
            handle = getattr(app, "_strategies_picker", None)
            if not handle:
                return
            try:
                handle["select_index"](_i)
            except Exception:
                pass
            try:
                handle["open_chip"]("LOG")
            except Exception:
                pass
        for w in (pill,) + tuple(pill.winfo_children()):
            w.bind("<Button-1>", _focus)
