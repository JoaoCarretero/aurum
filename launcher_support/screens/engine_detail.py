"""EngineDetailScreen — full-page drill-down per run.

Substitui o detail pane direito de DATA > ENGINES (modo split, hoje
exclusivo de runs_history) por uma página inteira com 9 blocos
debug-first organizados por pergunta de diagnóstico:

  ❶ TRIAGE       — algo quebrou agora?
  ❷ CADENCE      — engine alive?
  ❸ SCAN FUNNEL  — last tick scanned->dedup->stale->live->opened
  ❹ DECISIONS    — last 30 signals com REASON
  ❺ POSITIONS    — open positions + equity + exposure
  ❻ TRADES       — closed trades full audit + footer
  ❼ FRESHNESS    — bar age per symbol + cache state
  ❽ LOG TAIL     — last 200 lines + level filter
  ❾ ADERENCIA    — match% vs backtest replay (paper/shadow)

Auto-refresh 5s se status==running, snapshot estático se stopped.
ESC + breadcrumb voltam pra "engines" preservando seleção.

Skeleton — blocos 1-9 landed em Tasks 4-9.
"""
from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from typing import Any, Callable, Optional

from core.ui.ui_palette import (
    AMBER, AMBER_D, BG, BORDER, DIM, DIM2, FONT, PANEL,
)
from launcher_support.runs_history import RunSummary
from launcher_support.screens.base import Screen


class EngineDetailScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any,
                 client_factory: Callable[[], object | None]):
        super().__init__(parent)
        self.app = app
        self._client_factory = client_factory
        self._run: Optional[RunSummary] = None
        self._scroll_canvas: Optional[tk.Canvas] = None
        self._body_frame: Optional[tk.Frame] = None
        self._breadcrumb: Optional[tk.Frame] = None
        self._refresh_aid: Optional[str] = None

    def build(self) -> None:
        outer = tk.Frame(self.container, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=14)

        self._breadcrumb = tk.Frame(outer, bg=BG)
        self._breadcrumb.pack(fill="x")

        tk.Frame(outer, bg=DIM2, height=1).pack(fill="x", pady=(8, 8))

        canvas_wrap = tk.Frame(outer, bg=BG)
        canvas_wrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(canvas_wrap, bg=BG, highlightthickness=0)
        vbar = tk.Scrollbar(canvas_wrap, orient="vertical",
                            command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        body = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(
            int(-1 * (e.delta / 120)), "units"))

        self._scroll_canvas = canvas
        self._body_frame = body

    def on_enter(self, *, run: RunSummary, **_kwargs: Any) -> None:
        if not isinstance(run, RunSummary):
            raise TypeError(
                "EngineDetailScreen.on_enter requires run=RunSummary")
        self._run = run
        self._refresh_run_snapshot()
        run = self._run or run
        self._render_breadcrumb(run)
        self._paint_body(run)

        app = self.app
        if hasattr(app, "h_path"):
            app.h_path.configure(
                text=f"> DATA > ENGINES > {run.engine} {run.mode.upper()}")
        if hasattr(app, "h_stat"):
            app.h_stat.configure(text=run.status.upper(), fg=AMBER_D)
        if hasattr(app, "f_lbl"):
            app.f_lbl.configure(text="ESC voltar  |  R recarregar")
        if hasattr(app, "_kb"):
            app._kb("<Escape>", lambda: self._navigate_back())
            app._kb("r",         lambda: self._tick())
            app._kb("R",         lambda: self._tick())

        if run.status == "running":
            self._refresh_aid = self._after(5000, self._tick)

    def on_exit(self) -> None:
        super().on_exit()
        self._refresh_aid = None

    def _navigate_back(self) -> None:
        if hasattr(self.app, "screens") and self.app.screens is not None:
            self.app.screens.show("engines")

    def _render_breadcrumb(self, run: RunSummary) -> None:
        if self._breadcrumb is None:
            return
        for w in self._breadcrumb.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        def _seg(text: str, target: Optional[str] = None) -> None:
            fg = AMBER if target else DIM
            lbl = tk.Label(self._breadcrumb, text=text,
                           font=(FONT, 8, "bold"), fg=fg, bg=BG,
                           cursor="hand2" if target else "")
            lbl.pack(side="left")
            if target:
                lbl.bind(
                    "<Button-1>",
                    lambda _e, t=target: (
                        self.app.screens.show(t)
                        if hasattr(self.app, "screens")
                        and self.app.screens is not None
                        else None
                    ),
                )

        _seg("> DATA ", "data_center")
        tk.Label(self._breadcrumb, text="> ", font=(FONT, 8),
                 fg=DIM2, bg=BG).pack(side="left")
        _seg("ENGINES ", "engines")
        tk.Label(self._breadcrumb, text="> ", font=(FONT, 8),
                 fg=DIM2, bg=BG).pack(side="left")
        _seg(f"{run.engine} {run.mode.upper()} - {run.run_id}", None)

    def _paint_body(self, run: RunSummary) -> None:
        body = self._body_frame
        if body is None:
            return
        try:
            children = list(body.winfo_children())
        except tk.TclError:
            return  # body widget destroyed mid-tick
        for w in children:
            try:
                w.destroy()
            except Exception:
                pass
        # Header card.
        head = tk.Frame(body, bg=BG)
        head.pack(fill="x", pady=(4, 8))
        tk.Label(head, text=f"{run.engine} · {run.mode.upper()} · {run.status}",
                 font=(FONT, 10, "bold"), fg=AMBER, bg=BG,
                 anchor="w").pack(anchor="w")
        tk.Label(head, text=f"run_id: {run.run_id}",
                 font=(FONT, 7), fg=DIM, bg=BG, anchor="w").pack(anchor="w")

        from launcher_support.engine_detail_view import (
            render_triage_block, render_cadence_block,
            render_scan_funnel_block, render_decisions_block,
            render_positions_block, render_equity_block,
            render_trades_block, render_freshness_block,
            render_log_tail_block, render_aderencia_block,
        )
        render_triage_block(body, run)
        render_cadence_block(body, run)
        render_scan_funnel_block(body, run)
        render_decisions_block(body, run)
        render_positions_block(body, run)
        render_equity_block(body, run)
        render_trades_block(body, run)
        render_freshness_block(body, run)
        render_log_tail_block(body, run)
        render_aderencia_block(body, run)

        # Drift footer — quem deu os dados, quando.
        from datetime import datetime, timezone
        foot = tk.Frame(body, bg=BG)
        foot.pack(fill="x", pady=(20, 4))
        tk.Frame(foot, bg=BORDER, height=1).pack(fill="x", padx=12)
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        tk.Label(foot,
                 text=f"  source: {run.source}  ·  refreshed {ts}",
                 font=(FONT, 7), fg=DIM, bg=BG,
                 anchor="w").pack(anchor="w", padx=12, pady=(4, 0))

    def _refresh_run_snapshot(self) -> None:
        """Refresh heartbeat/account/positions before repainting detail.

        The list screen intentionally loads VPS rows cheaply, with
        heartbeat=None. Detail needs the richer endpoints or every block
        reads `{}` and looks empty/stale even while the runner is healthy.
        """
        run = self._run
        if run is None or run.source != "vps":
            return
        try:
            client = self._client_factory()
        except Exception:
            client = None
        if client is None:
            return

        hb = dict(run.heartbeat or {})
        account: dict = {}
        positions: dict = {}
        try:
            fresh_hb = client.get_heartbeat(run.run_id)
            if isinstance(fresh_hb, dict):
                hb.update(fresh_hb)
        except Exception:
            pass
        try:
            account = client.get_run_account(run.run_id)
        except Exception:
            account = {}
        try:
            positions = client.get_run_positions(run.run_id)
        except Exception:
            positions = {}

        if isinstance(account, dict) and account.get("available", True):
            for key in (
                "equity", "drawdown_pct", "ks_state", "primed",
                "account_size", "positions_open", "trades_closed",
            ):
                if key in account:
                    hb[key] = account[key]
            metrics = account.get("metrics")
            if isinstance(metrics, dict):
                hb["metrics"] = metrics

        if isinstance(positions, dict):
            pos_rows = positions.get("positions")
            if isinstance(pos_rows, list):
                hb["positions"] = pos_rows
                hb["positions_open"] = len(pos_rows)
                hb["open_positions_count"] = len(pos_rows)

        equity = run.equity
        initial = run.initial_balance
        trades_closed = run.trades_closed
        drawdown_pct = run.drawdown_pct
        sharpe_rolling = run.sharpe_rolling
        open_positions = run.open_positions
        if isinstance(account, dict) and account.get("available", True):
            try:
                equity = float(account.get("equity"))
            except (TypeError, ValueError):
                pass
            try:
                initial = float(account.get("initial_balance"))
            except (TypeError, ValueError):
                pass
            try:
                trades_closed = int(account.get("trades_closed"))
            except (TypeError, ValueError):
                pass
            try:
                drawdown_pct = float(account.get("drawdown_pct"))
            except (TypeError, ValueError):
                pass
            metrics = account.get("metrics")
            if isinstance(metrics, dict):
                try:
                    sharpe_rolling = float(
                        metrics.get("sharpe_rolling") or metrics.get("sharpe")
                    )
                except (TypeError, ValueError):
                    pass
        if isinstance(positions, dict):
            try:
                open_positions = int(positions.get("count"))
            except (TypeError, ValueError):
                pass

        roi = run.roi_pct
        if equity is not None and initial:
            roi = (equity - initial) / initial * 100.0

        def _as_int(value: object, fallback: int | None) -> int | None:
            try:
                return int(value) if value is not None else fallback
            except (TypeError, ValueError):
                return fallback

        self._run = replace(
            run,
            heartbeat=hb,
            last_tick_at=hb.get("last_tick_at") or run.last_tick_at,
            ticks_ok=_as_int(hb.get("ticks_ok"), run.ticks_ok),
            ticks_fail=_as_int(hb.get("ticks_fail"), run.ticks_fail),
            equity=equity,
            initial_balance=initial,
            roi_pct=roi,
            trades_closed=trades_closed,
            drawdown_pct=drawdown_pct,
            sharpe_rolling=sharpe_rolling,
            open_count=open_positions,
            open_positions=open_positions,
        )

    def _tick(self) -> None:
        """Re-paint body and re-arm 5s timer if status==running.

        Called by Screen._after; also invoked manually by R-key reload binding.
        Idempotent — refreshes rich VPS snapshots, then repaints the body.
        """
        if self._run is not None:
            self._refresh_run_snapshot()
            self._paint_body(self._run)
        if self._run and self._run.status == "running":
            self._refresh_aid = self._after(5000, self._tick)
