# DATA > ENGINES inline detail page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir o split horizontal de DATA > ENGINES por um drill-down full-page (debug-first, 9 blocos) com lista expandida de 14 colunas — sem tocar CORE.

**Architecture:** A lista (left pane atual de runs_history) ganha modo `mode="list"` que skipa o pane direito; click numa row dispara `app.screens.show("engine_detail", run=r)`. Novo screen `EngineDetailScreen` em `launcher_support/screens/engine_detail.py` com helpers de render em `launcher_support/engine_detail_view.py`. Sharpe/win-rate/sortino centralizados em `core/analytics/run_metrics.py` pra alignment cross-tela. ESC + breadcrumb voltam pra lista preservando seleção.

**Tech Stack:** Python 3.14, Tkinter, pytest. Reusa `Screen` ABC + `ScreenManager` + `RunSummary` + collectors existentes em `launcher_support/runs_history.py`. Cockpit endpoints já existem (`/v1/runs/{id}/{trades,positions,account,equity,log,heartbeat}`); 1 endpoint novo (`/signals`).

**Spec:** [`docs/superpowers/specs/2026-04-25-engines-screen-inline-detail-design.md`](../specs/2026-04-25-engines-screen-inline-detail-design.md)

---

## File Structure

**Files to CREATE:**
- `launcher_support/screens/engine_detail.py` — `EngineDetailScreen(Screen)` class, navigation, auto-refresh wiring
- `launcher_support/engine_detail_view.py` — render helpers para os 9 blocos (TRIAGE, CADENCE, SCAN, DECISIONS, POSITIONS, EQUITY, TRADES, FRESHNESS, LOG, ADERENCIA)
- `core/analytics/run_metrics.py` — `sharpe_rolling`, `win_rate`, `avg_R`, `sortino` (helpers cross-tela)
- `core/analytics/__init__.py` (se ainda não existe)
- `tests/test_engine_detail_smoke.py` — mount/unmount + auto-refresh
- `tests/test_engine_detail_view.py` — block render contracts
- `tests/test_engines_navigation.py` — drill-down + ESC + breadcrumb
- `tests/test_run_metrics.py` — analytics helpers
- `tests/test_cockpit_signals_endpoint.py` — `/v1/runs/{id}/signals` contract

**Files to MODIFY:**
- `launcher_support/runs_history.py` — add `mode="list"|"split"` flag em `render_runs_history`; expand `_COLUMNS` 11→14
- `launcher_support/screens/engines.py` — passa `mode="list"` ao chamar `render_runs_history`; header text update
- `launcher_support/screens/registry.py` — register `engine_detail`
- `tools/cockpit_api.py` — add `/v1/runs/{id}/signals` endpoint

**Worktree:** `.worktrees/engines-detail` em branch `feat/engines-detail-page` off `feat/research-desk`.

---

## Task 0: Worktree setup

**Files:** none (logistical)

- [ ] **Step 0.1: Create worktree**

```bash
git worktree add -b feat/engines-detail-page .worktrees/engines-detail feat/research-desk
cd .worktrees/engines-detail
```

Expected: worktree criado, branch nova `feat/engines-detail-page` off `feat/research-desk`.

- [ ] **Step 0.2: Verify clean state**

```bash
git status --short
python tools/maintenance/verify_keys_intact.py
python smoke_test.py --quiet
```

Expected: working tree clean (mudanças WIP ficam no parent worktree); keys intact (exit 0); smoke 172/172.

---

## Task 1: List-only mode em runs_history.py + 14 cols (spec Step 1)

**Files:**
- Modify: `launcher_support/runs_history.py:519` (`render_runs_history`)
- Modify: `launcher_support/runs_history.py:649` (`_COLUMNS`)
- Modify: `launcher_support/runs_history.py:600` (`_render_left_header` — 14 cols)
- Modify: `launcher_support/screens/engines.py:101` (passa `mode="list"`)
- Test: `tests/test_runs_history_list_mode.py` (new)

**Why:** com pane direito morto, lista expande pra full width; adiciona SHARPE/DD%/#POS pra triagem visual sem clicar.

- [ ] **Step 1.1: Write failing test for mode="list" skips right pane**

Create `tests/test_runs_history_list_mode.py`:

```python
"""mode="list" em render_runs_history skipa criação do pane direito."""
import pytest
import tkinter as tk

from launcher_support.runs_history import render_runs_history


@pytest.fixture(scope="module")
def gui_root():
    try:
        root = tk.Tk()
    except Exception:
        pytest.skip("tk unavailable")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


class _FakeLauncher:
    def after(self, *_a, **_k):
        return "x"

    def after_cancel(self, *_a, **_k):
        pass


def test_list_mode_skips_right_pane(gui_root):
    parent = tk.Frame(gui_root)
    root = render_runs_history(parent, _FakeLauncher(),
                               client_factory=lambda: None,
                               mode="list")
    state = getattr(root, "_runs_history_state", None)
    assert state is not None
    assert state.get("detail_host") is None, \
        "list mode must not create detail pane"
    parent.destroy()


def test_split_mode_keeps_right_pane(gui_root):
    parent = tk.Frame(gui_root)
    root = render_runs_history(parent, _FakeLauncher(),
                               client_factory=lambda: None,
                               mode="split")
    state = getattr(root, "_runs_history_state", None)
    assert state is not None
    assert state.get("detail_host") is not None, \
        "split mode must preserve detail pane (default)"
    parent.destroy()
```

- [ ] **Step 1.2: Run test to verify it fails**

```bash
python -m pytest tests/test_runs_history_list_mode.py -v
```

Expected: FAIL — `render_runs_history` não aceita kwarg `mode`.

- [ ] **Step 1.3: Add `mode` param to render_runs_history**

In `launcher_support/runs_history.py:519`, change signature:

```python
def render_runs_history(parent: tk.Widget, launcher,
                        client_factory: Callable[[], object | None],
                        *,
                        mode: str = "split",
                        ) -> tk.Frame:
    """Full RUNS HISTORY screen.

    mode="split" (default): table esquerda + detail pane direita.
    mode="list":  table esquerda full-width, sem detail pane.
                  Click numa row dispara navegação via launcher.screens.show.
    """
```

Replace the right-pane block (around line 559-563) with:

```python
    if mode == "split":
        # RIGHT — detail
        right = tk.Frame(split, bg=PANEL,
                         highlightbackground=BORDER, highlightthickness=1)
        right.pack(side="right", fill="both", expand=True)
        state["detail_host"] = right
    else:
        state["detail_host"] = None
```

Replace the LEFT pane fixed-width block (line 549-552) with:

```python
    # LEFT — table
    if mode == "split":
        left = tk.Frame(split, bg=BG, width=640,
                        highlightbackground=BORDER, highlightthickness=1)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
    else:
        left = tk.Frame(split, bg=BG,
                        highlightbackground=BORDER, highlightthickness=1)
        left.pack(side="left", fill="both", expand=True)
```

- [ ] **Step 1.4: Run test to verify it passes**

```bash
python -m pytest tests/test_runs_history_list_mode.py -v
```

Expected: PASS (2/2).

- [ ] **Step 1.5: Write failing test for 14-col schema**

Append to `tests/test_runs_history_list_mode.py`:

```python
def test_columns_schema_has_14_cols():
    from launcher_support.runs_history import _COLUMNS

    labels = [label for label, _w in _COLUMNS]
    assert "SHARPE" in labels
    assert "DD%" in labels
    assert "#POS" in labels
    assert len(_COLUMNS) == 14
    # Order check: SHARPE/DD%/#POS aparecem entre ROI e TRADES
    roi_idx = labels.index("ROI")
    trades_idx = labels.index("TRADES")
    sharpe_idx = labels.index("SHARPE")
    dd_idx = labels.index("DD%")
    pos_idx = labels.index("#POS")
    assert roi_idx < dd_idx < sharpe_idx < pos_idx < trades_idx
```

- [ ] **Step 1.6: Run test to verify it fails**

```bash
python -m pytest tests/test_runs_history_list_mode.py::test_columns_schema_has_14_cols -v
```

Expected: FAIL — 11 cols hoje, falta SHARPE/DD%/#POS.

- [ ] **Step 1.7: Expand _COLUMNS to 14 entries**

In `launcher_support/runs_history.py:649`, replace `_COLUMNS`:

```python
_COLUMNS = [
    ("ST",      2),
    ("ENGINE",  14),   # bumped 11→14 (RENAISSANCE/BRIDGEWATER inteiros + folga)
    ("MODE",    6),
    ("STARTED", 13),
    ("DUR",     7),
    ("TICKS",   6),
    ("SIG",     5),
    ("EQUITY",  9),
    ("ROI",     8),
    ("DD%",     6),    # NEW — drawdown percent atual
    ("SHARPE",  7),    # NEW — sharpe rolling do run
    ("#POS",    5),    # NEW — open positions count
    ("TRADES",  6),
    ("SRC",     5),
]
```

In `_render_left_header` around line 637, expand the numeric set:

```python
    numeric = {"TICKS", "SIG", "EQUITY", "ROI", "DD%", "SHARPE", "#POS", "TRADES"}
```

- [ ] **Step 1.8: Run column test to verify it passes**

```bash
python -m pytest tests/test_runs_history_list_mode.py::test_columns_schema_has_14_cols -v
```

Expected: PASS.

- [ ] **Step 1.9: Update _render_run_row to render 3 new cols**

In `launcher_support/runs_history.py:827`, search for the row painter and add cells for DD%/SHARPE/#POS. Pattern follows existing cells:

```python
    # New cells aligned with new _COLUMNS entries.
    dd_pct = getattr(r, "drawdown_pct", None)
    sharpe = getattr(r, "sharpe_rolling", None)
    pos_count = getattr(r, "open_positions", None)

    tk.Label(row, text=("—" if dd_pct is None else f"{dd_pct:+.2f}%"),
             font=(FONT, 7), fg=(RED if dd_pct and dd_pct < -2 else DIM),
             bg=BG, width=6, anchor="e").pack(side="left", padx=(2, 0))
    tk.Label(row, text=("—" if sharpe is None else f"{sharpe:+.2f}"),
             font=(FONT, 7),
             fg=(GREEN if sharpe and sharpe > 1 else (RED if sharpe and sharpe < 0 else DIM)),
             bg=BG, width=7, anchor="e").pack(side="left", padx=(2, 0))
    tk.Label(row, text=("—" if pos_count is None else str(pos_count)),
             font=(FONT, 7), fg=(WHITE if pos_count else DIM),
             bg=BG, width=5, anchor="e").pack(side="left", padx=(2, 0))
```

`RunSummary` precisa dos 3 novos fields (read from heartbeat). Add to `RunSummary` dataclass at line 58:

```python
    drawdown_pct: float | None = None
    sharpe_rolling: float | None = None
    open_positions: int | None = None
```

In `_summary_from_local` (line 140) and `_collect_single_vps_run` (line 227), populate from heartbeat fields when present (else None — graceful):

```python
    # Em _summary_from_local e _collect_single_vps_run, dentro do hb dict:
    drawdown_pct = hb.get("drawdown_pct") or hb.get("dd_pct")
    sharpe_rolling = hb.get("sharpe_rolling")
    open_positions = hb.get("open_positions_count") or len(hb.get("positions") or [])
```

E passa pra `RunSummary(...)` no construtor.

- [ ] **Step 1.10: Update engines.py to pass mode="list"**

Edit `launcher_support/screens/engines.py:101`:

```python
            self._history_root = render_runs_history(
                self._body, self.app,
                client_factory=self._client_factory,
                mode="list",
            )
```

- [ ] **Step 1.11: Run smoke + tests**

```bash
python smoke_test.py --quiet
python -m pytest tests/test_runs_history.py tests/test_runs_history_list_mode.py -v
```

Expected: smoke 172/172, runs_history tests + new list_mode tests todos PASS.

- [ ] **Step 1.12: Commit**

```bash
git add tests/test_runs_history_list_mode.py launcher_support/runs_history.py launcher_support/screens/engines.py
git commit -m "feat(engines): list mode + 14 cols (SHARPE/DD%/#POS)

- render_runs_history ganha kwarg mode='list'|'split' (default split preserva runs_history quick-link)
- engines.py (DATA > ENGINES) passa mode='list' — full width, sem detail pane
- _COLUMNS 11→14: adiciona DD%/SHARPE/#POS entre ROI e TRADES
- ENGINE 11→14 chars (BRIDGEWATER/RENAISSANCE inteiros)
- RunSummary ganha drawdown_pct/sharpe_rolling/open_positions (graceful None)

Step 1 do plan 2026-04-25-engines-screen-inline-detail.md"
```

---

## Task 2: EngineDetailScreen skeleton + register (spec Step 2)

**Files:**
- Create: `launcher_support/screens/engine_detail.py`
- Modify: `launcher_support/screens/registry.py`
- Test: `tests/test_engine_detail_smoke.py` (new)

- [ ] **Step 2.1: Write failing smoke test**

Create `tests/test_engine_detail_smoke.py`:

```python
"""EngineDetailScreen mount/unmount + on_enter(run=...) skeleton."""
import pytest
import tkinter as tk

from launcher_support.runs_history import RunSummary


@pytest.fixture(scope="module")
def gui_root():
    try:
        root = tk.Tk()
    except Exception:
        pytest.skip("tk unavailable")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture
def fake_run():
    return RunSummary(
        run_id="2026-04-24_174017p_test",
        engine="MILLENNIUM",
        mode="paper",
        status="running",
        started_at="2026-04-24T17:40:17Z",
        stopped_at=None,
        last_tick_at="2026-04-24T20:30:00Z",
        ticks_ok=10,
        ticks_fail=0,
        novel=2,
        equity=10005.50,
        initial_balance=10000.0,
        roi_pct=0.055,
        trades_closed=1,
        source="vps",
        heartbeat={
            "last_error": None, "primed": True, "ks_state": "armed",
            "last_scan_scanned": 11, "last_scan_dedup": 8,
            "last_scan_stale": 1, "last_scan_live": 2,
        },
    )


def test_engine_detail_mounts_cleanly(gui_root, fake_run):
    from launcher_support.screens.engine_detail import EngineDetailScreen

    class _FakeApp:
        screens = None
        def _kb(self, *_a, **_k): pass
        h_path = type("L", (), {"configure": lambda *a, **k: None})()
        h_stat = type("L", (), {"configure": lambda *a, **k: None})()
        f_lbl  = type("L", (), {"configure": lambda *a, **k: None})()

    parent = tk.Frame(gui_root)
    screen = EngineDetailScreen(parent=parent, app=_FakeApp(),
                                client_factory=lambda: None)
    screen.mount()
    screen.on_enter(run=fake_run)
    screen.on_exit()
    parent.destroy()


def test_engine_detail_requires_run_kwarg(gui_root):
    from launcher_support.screens.engine_detail import EngineDetailScreen

    class _FakeApp:
        def _kb(self, *_a, **_k): pass

    parent = tk.Frame(gui_root)
    screen = EngineDetailScreen(parent=parent, app=_FakeApp(),
                                client_factory=lambda: None)
    screen.mount()
    with pytest.raises(TypeError):
        screen.on_enter()  # missing run kwarg
    screen.on_exit()
    parent.destroy()
```

- [ ] **Step 2.2: Run test to verify it fails**

```bash
python -m pytest tests/test_engine_detail_smoke.py -v
```

Expected: FAIL — `launcher_support.screens.engine_detail` não existe.

- [ ] **Step 2.3: Create EngineDetailScreen skeleton**

Create `launcher_support/screens/engine_detail.py`:

```python
"""EngineDetailScreen — full-page drill-down per run.

Substitui o detail pane direito de DATA > ENGINES (modo split, hoje
exclusivo de runs_history) por uma página inteira com 9 blocos
debug-first organizados por pergunta de diagnóstico:

  ❶ TRIAGE       — algo quebrou agora? (last_error, freshness, integrity)
  ❷ CADENCE      — engine alive? (tick drift, uptime, primed/ks_state)
  ❸ SCAN FUNNEL  — last tick scanned→dedup→stale→live→opened
  ❹ DECISIONS    — last 30 signals com REASON
  ❺ POSITIONS    — open positions + equity + exposure
  ❻ TRADES       — closed trades full audit + footer (sharpe/win_rate)
  ❼ FRESHNESS    — bar age per symbol + cache state
  ❽ LOG TAIL     — last 200 lines + level filter + tail-f
  ❾ ADERENCIA    — match% vs backtest replay (paper/shadow)

Auto-refresh 5s se status==running, snapshot estático se stopped.
ESC + breadcrumb voltam pra "engines" (preservando seleção).
"""
from __future__ import annotations

import tkinter as tk
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
        self._refresh_aid: Optional[str] = None

    def build(self) -> None:
        outer = tk.Frame(self.container, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=14)

        # Breadcrumb header — fixed at top, never scrolls.
        self._breadcrumb = tk.Frame(outer, bg=BG)
        self._breadcrumb.pack(fill="x")

        tk.Frame(outer, bg=DIM2, height=1).pack(fill="x", pady=(8, 8))

        # Scrollable body for the 9 blocks.
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
            raise TypeError("EngineDetailScreen.on_enter requires run=RunSummary")
        self._run = run
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

        # Auto-refresh apenas se RUNNING; snapshot pra demais status.
        if run.status == "running":
            self._refresh_aid = self._after(5000, self._tick)

    def on_exit(self) -> None:
        # _after cleanup já é automático via Screen base class.
        super().on_exit()
        self._refresh_aid = None

    def _navigate_back(self) -> None:
        if hasattr(self.app, "screens"):
            self.app.screens.show("engines")

    def _render_breadcrumb(self, run: RunSummary) -> None:
        for w in self._breadcrumb.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        # > DATA > ENGINES > {run summary}
        # Cada segmento é clicável (exceto o último); separador "›"
        def _seg(text: str, target: Optional[str] = None) -> None:
            fg = DIM if target else AMBER
            lbl = tk.Label(self._breadcrumb, text=text,
                           font=(FONT, 8, "bold"), fg=fg, bg=BG,
                           cursor="hand2" if target else "")
            lbl.pack(side="left")
            if target:
                lbl.bind("<Button-1>", lambda _e, t=target:
                         self.app.screens.show(t))

        _seg("> DATA ", "data_center")
        tk.Label(self._breadcrumb, text="› ", font=(FONT, 8),
                 fg=DIM2, bg=BG).pack(side="left")
        _seg("ENGINES ", "engines")
        tk.Label(self._breadcrumb, text="› ", font=(FONT, 8),
                 fg=DIM2, bg=BG).pack(side="left")
        _seg(f"{run.engine} {run.mode.upper()} · {run.run_id}", None)

    def _paint_body(self, run: RunSummary) -> None:
        body = self._body_frame
        if body is None:
            return
        for w in body.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        # Skeleton placeholder; blocos ❶-❾ preenchem em Tasks 4-9.
        tk.Label(body, text=f"[ENGINE DETAIL — {run.run_id}]",
                 font=(FONT, 10, "bold"), fg=AMBER, bg=BG,
                 anchor="w").pack(anchor="w", pady=20)
        tk.Label(body, text="(blocos ❶-❾ landed em Tasks 4-9)",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="w")

    def _tick(self) -> None:
        # Re-paint com fresh data. Em Task 10 isso re-fetcha heartbeat
        # e re-pinta blocks dinâmicos.
        if self._run is not None:
            self._paint_body(self._run)
        if self._run and self._run.status == "running":
            self._refresh_aid = self._after(5000, self._tick)
```

- [ ] **Step 2.4: Register engine_detail in registry**

Edit `launcher_support/screens/registry.py` — adicione no bloco de imports (linha 17-34):

```python
    from launcher_support.screens.engine_detail import EngineDetailScreen
```

E no fim da função (após o último `manager.register("engines", ...)` em linha 124-134):

```python
    manager.register(
        "engine_detail",
        lambda parent: EngineDetailScreen(
            parent=parent,
            app=app,
            client_factory=__import__(
                "launcher_support.engines_live_view",
                fromlist=["_get_cockpit_client"],
            )._get_cockpit_client,
        ),
    )
```

- [ ] **Step 2.5: Run smoke test to verify it passes**

```bash
python -m pytest tests/test_engine_detail_smoke.py -v
python smoke_test.py --quiet
```

Expected: 2 PASS; smoke 172/172.

- [ ] **Step 2.6: Commit**

```bash
git add launcher_support/screens/engine_detail.py launcher_support/screens/registry.py tests/test_engine_detail_smoke.py
git commit -m "feat(engines): EngineDetailScreen skeleton + registry

- novo screen full-page drill-down per run, blocos ❶-❾ pendentes
- breadcrumb DATA > ENGINES > <run> clicável
- ESC binding volta pra 'engines'
- auto-refresh 5s skeleton (sem block re-fetch ainda)
- registrado em screens.show('engine_detail', run=r)

Step 2 do plan 2026-04-25-engines-screen-inline-detail.md"
```

---

## Task 3: Wire row click → drill-down (spec Step 3)

**Files:**
- Modify: `launcher_support/runs_history.py:827` (`_render_run_row`)
- Test: `tests/test_engines_navigation.py` (new)

- [ ] **Step 3.1: Write failing test**

Create `tests/test_engines_navigation.py`:

```python
"""Drill-down: row click em mode='list' invoca screens.show('engine_detail', run=r)."""
import pytest
import tkinter as tk
from unittest.mock import MagicMock

from launcher_support.runs_history import RunSummary, render_runs_history


@pytest.fixture(scope="module")
def gui_root():
    try:
        root = tk.Tk()
    except Exception:
        pytest.skip("tk unavailable")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def _fake_run():
    return RunSummary(
        run_id="2026-04-24_174017p_test",
        engine="MILLENNIUM",
        mode="paper",
        status="running",
        started_at="2026-04-24T17:40:17Z",
        stopped_at=None,
        last_tick_at="2026-04-24T20:30:00Z",
        ticks_ok=10,
        ticks_fail=0,
        novel=2,
        equity=10005.50,
        initial_balance=10000.0,
        roi_pct=0.055,
        trades_closed=1,
        source="vps",
    )


def test_list_mode_row_click_triggers_drilldown(gui_root):
    parent = tk.Frame(gui_root)
    mock_screens = MagicMock()
    launcher = MagicMock()
    launcher.screens = mock_screens
    launcher.after = MagicMock(return_value="x")
    launcher.after_cancel = MagicMock()

    root = render_runs_history(parent, launcher,
                               client_factory=lambda: None,
                               mode="list")
    state = root._runs_history_state
    state["rows"] = [_fake_run()]
    from launcher_support.runs_history import _paint_rows
    _paint_rows(state)

    # Find first row widget; simulate click.
    table_wrap = state["table_wrap"]
    rows = [w for w in table_wrap.winfo_children() if w.winfo_children()]
    assert rows, "expected at least one row painted"
    first_row = rows[0]
    first_row.event_generate("<Button-1>")

    mock_screens.show.assert_called_with("engine_detail", run=_fake_run())
    parent.destroy()
```

(Note: `RunSummary.__eq__` precisa funcionar via dataclass auto-eq — verificar `@dataclass` em line 58.)

- [ ] **Step 3.2: Run test to verify it fails**

```bash
python -m pytest tests/test_engines_navigation.py -v
```

Expected: FAIL — row click hoje chama `_load_detail`, não `screens.show`.

- [ ] **Step 3.3: Update _render_run_row to dispatch differently in list mode**

In `launcher_support/runs_history.py:827` (`_render_run_row`), find the bind block for `<Button-1>` and dispatch by mode. Around the click handler:

```python
def _render_run_row(parent: tk.Widget, r: RunSummary, state: dict) -> None:
    # ... existing row painting ...

    # Row click: list mode = navega pra engine_detail; split mode = pinta detail pane.
    def _on_click(_e=None, _r=r, _state=state):
        mode = _state.get("mode", "split")
        launcher = _state.get("launcher")
        if mode == "list" and launcher is not None and hasattr(launcher, "screens"):
            try:
                launcher.screens.show("engine_detail", run=_r)
                return
            except Exception:
                pass  # fallback pra split-style behavior se nav falha
        _state["selected_run_id"] = _r.run_id
        _load_detail(_r, _state)

    row.bind("<Button-1>", _on_click)
    for child in row.winfo_children():
        try:
            child.bind("<Button-1>", _on_click)
        except Exception:
            pass
```

E armazene `mode` no state em `render_runs_history` (linha 530-543):

```python
    state: dict = {
        # ... existing fields ...
        "mode": mode,
    }
```

- [ ] **Step 3.4: Run test to verify it passes**

```bash
python -m pytest tests/test_engines_navigation.py -v tests/test_runs_history.py -v
```

Expected: navigation test PASS; existing runs_history tests still PASS.

- [ ] **Step 3.5: Commit**

```bash
git add launcher_support/runs_history.py tests/test_engines_navigation.py
git commit -m "feat(engines): wire row click → engine_detail drill-down

- mode='list': row click chama launcher.screens.show('engine_detail', run=r)
- mode='split': comportamento legacy preservado (_load_detail no pane direito)
- fallback pra split-style se navegação falha

Step 3 do plan 2026-04-25-engines-screen-inline-detail.md"
```

---

## Task 4: Block ❶ TRIAGE + ❷ CADENCE (spec Step 4)

**Files:**
- Create: `launcher_support/engine_detail_view.py`
- Modify: `launcher_support/screens/engine_detail.py:_paint_body`
- Test: `tests/test_engine_detail_view.py` (new)

- [ ] **Step 4.1: Write failing test for render_triage_block**

Create `tests/test_engine_detail_view.py`:

```python
"""engine_detail_view block render contracts."""
import pytest
import tkinter as tk

from launcher_support.runs_history import RunSummary


@pytest.fixture(scope="module")
def gui_root():
    try:
        root = tk.Tk()
    except Exception:
        pytest.skip("tk unavailable")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def _run_with_hb(hb=None, status="running", **kwargs):
    base = dict(
        run_id="rid", engine="MILLENNIUM", mode="paper", status=status,
        started_at="2026-04-24T17:40:17Z", stopped_at=None,
        last_tick_at="2026-04-24T20:30:00Z",
        ticks_ok=10, ticks_fail=0, novel=2, equity=10005.0,
        initial_balance=10000.0, roi_pct=0.05, trades_closed=1,
        source="vps", heartbeat=hb or {},
    )
    base.update(kwargs)
    return RunSummary(**base)


def test_triage_block_shows_last_error(gui_root):
    from launcher_support.engine_detail_view import render_triage_block

    parent = tk.Frame(gui_root)
    run = _run_with_hb({"last_error": "boom: traceback (most recent call last)"})
    render_triage_block(parent, run)

    labels = [w for w in parent.winfo_children()
              if isinstance(w, tk.Label) or hasattr(w, "winfo_children")]
    text_pool = " ".join(_collect_text(parent))
    assert "LAST ERROR" in text_pool
    assert "boom" in text_pool
    parent.destroy()


def test_triage_block_no_error_renders_clean_status(gui_root):
    from launcher_support.engine_detail_view import render_triage_block
    parent = tk.Frame(gui_root)
    run = _run_with_hb({"last_error": None})
    render_triage_block(parent, run)
    text_pool = " ".join(_collect_text(parent))
    assert "LAST ERROR" not in text_pool  # banner suprimido
    parent.destroy()


def test_cadence_block_shows_drift(gui_root):
    from launcher_support.engine_detail_view import render_cadence_block
    parent = tk.Frame(gui_root)
    run = _run_with_hb({
        "primed": True, "ks_state": "armed", "tick_sec": 900,
    })
    render_cadence_block(parent, run)
    text_pool = " ".join(_collect_text(parent))
    assert "TICK CADENCE" in text_pool or "CADENCE" in text_pool
    parent.destroy()


def _collect_text(widget):
    """DFS de todos os tk.Label.cget('text') em widget e descendants."""
    out = []
    if isinstance(widget, tk.Label):
        try:
            out.append(str(widget.cget("text")))
        except Exception:
            pass
    for child in widget.winfo_children():
        out.extend(_collect_text(child))
    return out
```

- [ ] **Step 4.2: Run test to verify it fails**

```bash
python -m pytest tests/test_engine_detail_view.py -v
```

Expected: FAIL — `engine_detail_view` não existe.

- [ ] **Step 4.3: Create engine_detail_view.py with TRIAGE + CADENCE blocks**

Create `launcher_support/engine_detail_view.py`:

```python
"""Render helpers para os 9 blocos da EngineDetailScreen.

Cada `render_*_block(parent, run)` recebe um Tk widget pai e a
RunSummary, pinta a seção, e retorna None. Skipa graceful (sem
levantar) se faltarem campos.

Blocos:
  ❶ render_triage_block       — last_error + freshness + integrity
  ❷ render_cadence_block      — tick drift + uptime + primed/ks_state
  ❸ render_scan_funnel_block  — scanned→dedup→stale→live→opened
  ❹ render_decisions_block    — last 30 signals com REASON
  ❺ render_positions_block    — open positions
  ❺ render_equity_block       — equity now/peak/dd
  ❻ render_trades_block       — closed trades full audit + footer
  ❼ render_freshness_block    — bar age per symbol
  ❽ render_log_tail_block     — last 200 lines + filter + tail-f
  ❾ render_aderencia_block    — match% vs backtest
"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime, timezone
from typing import Any

from core.ui.ui_palette import (
    AMBER, AMBER_D, BG, BORDER, DIM, DIM2, FONT, GREEN, PANEL, RED, WHITE,
)
from launcher_support.runs_history import RunSummary


# ─── Layout helpers ─────────────────────────────────────────────────


def _block_header(parent: tk.Widget, label: str) -> None:
    """H2 8pt bold + horizontal rule. Pattern from runs_history._render_block_header."""
    bar = tk.Frame(parent, bg=BG)
    bar.pack(fill="x", pady=(14, 4))
    tk.Label(bar, text=label, font=(FONT, 8, "bold"),
             fg=DIM, bg=BG, anchor="w").pack(side="left", padx=(0, 8))
    tk.Frame(bar, bg=BORDER, height=1).pack(side="left", fill="x", expand=True)


def _kv_row(parent: tk.Widget, k: str, v: str, vfg: str = WHITE) -> None:
    """key:value row; key DIM, value white-or-color. 7pt body."""
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", padx=12, pady=1)
    tk.Label(row, text=f"  {k}", font=(FONT, 7), fg=DIM, bg=BG,
             width=24, anchor="w").pack(side="left")
    tk.Label(row, text=v, font=(FONT, 7, "bold"), fg=vfg, bg=BG,
             anchor="w").pack(side="left")


def _format_age(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        secs = int((datetime.now(timezone.utc) - t).total_seconds())
        if secs < 60:
            return f"{secs}s ago"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            h, m = divmod(secs // 60, 60)
            return f"{h}h{m:02d}m ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return str(iso)[:16]


# ─── Block ❶ TRIAGE ─────────────────────────────────────────────────


def render_triage_block(parent: tk.Widget, run: RunSummary) -> None:
    """❶ TRIAGE — algo quebrou agora?

    Renderiza last_error banner em vermelho (se houver), freshness do
    heartbeat, status do serviço, e integridade do run_dir.
    """
    _block_header(parent, "❶ TRIAGE")
    hb = run.heartbeat or {}
    last_err = hb.get("last_error")

    if last_err:
        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill="x", padx=12, pady=(2, 6))
        tk.Label(bar, text="LAST ERROR", font=(FONT, 8, "bold"),
                 fg=RED, bg=BG, anchor="w").pack(anchor="w")
        tk.Label(bar, text=str(last_err)[:600], font=(FONT, 7),
                 fg=RED, bg=BG, anchor="w", justify="left",
                 wraplength=900).pack(anchor="w", pady=(2, 0))
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12)

    age = _format_age(run.last_tick_at)
    tick_sec = hb.get("tick_sec") or 900
    fresh_color = WHITE
    try:
        # heuristic: se age secs > 2× tick_sec, amber; > 4× red.
        from datetime import datetime as _dt, timezone as _tz
        if run.last_tick_at:
            t = _dt.fromisoformat(str(run.last_tick_at).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=_tz.utc)
            elapsed = (_dt.now(_tz.utc) - t).total_seconds()
            if elapsed > 4 * tick_sec:
                fresh_color = RED
            elif elapsed > 2 * tick_sec:
                fresh_color = AMBER
    except Exception:
        pass

    _kv_row(parent, "heartbeat freshness", age, fresh_color)
    _kv_row(parent, "service status", run.status,
            GREEN if run.status == "running" else (
                AMBER if run.status == "stale" else DIM))


# ─── Block ❷ CADENCE ────────────────────────────────────────────────


def render_cadence_block(parent: tk.Widget, run: RunSummary) -> None:
    """❷ TICK CADENCE — engine alive?

    Mostra tick_sec esperado vs real, uptime, primed/ks_state.
    """
    _block_header(parent, "❷ TICK CADENCE")
    hb = run.heartbeat or {}

    tick_sec = hb.get("tick_sec") or 900
    _kv_row(parent, "expected tick_sec", str(tick_sec))

    _kv_row(parent, "ticks_ok", str(run.ticks_ok or 0))
    _kv_row(parent, "ticks_fail", str(run.ticks_fail or 0),
            RED if (run.ticks_fail or 0) > 0 else DIM)

    primed = hb.get("primed")
    _kv_row(parent, "primed", str(primed) if primed is not None else "—",
            GREEN if primed else AMBER)

    ks_state = hb.get("ks_state")
    _kv_row(parent, "ks_state", str(ks_state) if ks_state else "—",
            GREEN if ks_state == "armed" else AMBER)

    started_age = _format_age(run.started_at)
    _kv_row(parent, "uptime", started_age)
```

- [ ] **Step 4.4: Wire blocks into EngineDetailScreen._paint_body**

Edit `launcher_support/screens/engine_detail.py:_paint_body`:

```python
    def _paint_body(self, run: RunSummary) -> None:
        body = self._body_frame
        if body is None:
            return
        for w in body.winfo_children():
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
        )
        render_triage_block(body, run)
        render_cadence_block(body, run)
```

- [ ] **Step 4.5: Run tests + smoke**

```bash
python -m pytest tests/test_engine_detail_view.py tests/test_engine_detail_smoke.py -v
python smoke_test.py --quiet
```

Expected: 5/5 PASS; smoke 172/172.

- [ ] **Step 4.6: Commit**

```bash
git add launcher_support/engine_detail_view.py launcher_support/screens/engine_detail.py tests/test_engine_detail_view.py
git commit -m "feat(engine_detail): blocos ❶ TRIAGE + ❷ CADENCE

- engine_detail_view.py com helpers _block_header / _kv_row / _format_age
- render_triage_block: last_error banner red + freshness + status
- render_cadence_block: tick_sec / ticks_ok|fail / primed / ks_state / uptime
- EngineDetailScreen._paint_body wire dos 2 blocos

Step 4 do plan 2026-04-25-engines-screen-inline-detail.md"
```

---

## Task 5: Block ❸ SCAN FUNNEL + ❹ DECISIONS + signals endpoint (spec Step 5)

**Files:**
- Modify: `tools/cockpit_api.py` (novo endpoint `/v1/runs/{id}/signals`)
- Modify: `launcher_support/engine_detail_view.py` (2 blocos)
- Modify: `launcher_support/screens/engine_detail.py:_paint_body`
- Test: `tests/test_cockpit_signals_endpoint.py` (new)
- Test: `tests/test_engine_detail_view.py` (extend)

- [ ] **Step 5.1: Write failing test for /v1/runs/{id}/signals endpoint**

Create `tests/test_cockpit_signals_endpoint.py`:

```python
"""Cockpit endpoint /v1/runs/{run_id}/signals lê tail de signals.jsonl."""
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from tools.cockpit_api import build_app


@pytest.fixture
def app_with_run(tmp_path, monkeypatch):
    """Cria run_dir fake com signals.jsonl e aponta cockpit pra ele."""
    monkeypatch.setenv("AURUM_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("COCKPIT_API_TOKEN_READ", "test-read")
    monkeypatch.setenv("COCKPIT_API_TOKEN_ADMIN", "test-admin")

    run_dir = tmp_path / "millennium_paper" / "2026-04-24_174017p_test" / "reports"
    run_dir.mkdir(parents=True)
    sig_path = run_dir / "signals.jsonl"
    rows = [
        {"ts": "2026-04-24T18:00:00Z", "symbol": "BTCUSDT",
         "decision": "opened", "score": 0.82, "reason": "score>thresh"},
        {"ts": "2026-04-24T18:15:00Z", "symbol": "ETHUSDT",
         "decision": "stale", "score": 0.71, "reason": "signal_age>2x"},
    ]
    sig_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                        encoding="utf-8")
    return build_app()


def test_signals_endpoint_returns_jsonl_tail(app_with_run):
    client = TestClient(app_with_run)
    resp = client.get(
        "/v1/runs/2026-04-24_174017p_test/signals?limit=10",
        headers={"Authorization": "Bearer test-read"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert "signals" in payload
    assert len(payload["signals"]) == 2
    assert payload["signals"][0]["symbol"] == "BTCUSDT"


def test_signals_endpoint_404_when_missing(app_with_run):
    client = TestClient(app_with_run)
    resp = client.get(
        "/v1/runs/nonexistent/signals",
        headers={"Authorization": "Bearer test-read"},
    )
    assert resp.status_code == 404
```

- [ ] **Step 5.2: Run test to verify it fails**

```bash
python -m pytest tests/test_cockpit_signals_endpoint.py -v
```

Expected: FAIL — endpoint não existe (`/v1/runs/{id}/signals` returns 404 "not found in routes").

- [ ] **Step 5.3: Add /v1/runs/{id}/signals endpoint**

Edit `tools/cockpit_api.py`. Find an existing run-scoped endpoint (e.g. `/v1/runs/{run_id}/log`, line 328) e adicione abaixo:

```python
    @app.get("/v1/runs/{run_id}/signals")
    def get_run_signals(run_id: str, limit: int = 30,
                         _auth: str = Depends(require_read)):
        """Tail de signals.jsonl do run_dir.

        Cada linha do JSONL é um decision record:
          {ts, symbol, decision, score, reason, ...features}
        decision ∈ {opened, stale, max_open, dir_conflict, corr_block, ...}.
        """
        run_dir = _resolve_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="run not found")
        sig_path = run_dir / "reports" / "signals.jsonl"
        if not sig_path.exists():
            return {"signals": [], "source": "missing"}
        # Tail last N lines.
        try:
            text = sig_path.read_text(encoding="utf-8")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        lines = [ln for ln in text.splitlines() if ln.strip()]
        tail = lines[-limit:]
        out = []
        for ln in tail:
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
        return {"signals": out, "source": "jsonl"}
```

(Helper `_resolve_run_dir` já deve existir em cockpit_api; se não, mirror do pattern usado pelos outros run-scoped endpoints.)

- [ ] **Step 5.4: Run endpoint test**

```bash
python -m pytest tests/test_cockpit_signals_endpoint.py -v
```

Expected: 2/2 PASS.

- [ ] **Step 5.5: Write failing test for SCAN + DECISIONS blocks**

Append to `tests/test_engine_detail_view.py`:

```python
def test_scan_funnel_block_shows_funnel_metrics(gui_root):
    from launcher_support.engine_detail_view import render_scan_funnel_block
    parent = tk.Frame(gui_root)
    run = _run_with_hb({
        "last_scan_scanned": 11, "last_scan_dedup": 8,
        "last_scan_stale": 1, "last_scan_live": 2,
        "last_scan_opened": 1,
    })
    render_scan_funnel_block(parent, run)
    text_pool = " ".join(_collect_text(parent))
    assert "scanned" in text_pool.lower()
    assert "11" in text_pool
    assert "opened" in text_pool.lower()
    parent.destroy()


def test_decisions_block_renders_recent_signals(gui_root, monkeypatch, tmp_path):
    from launcher_support.engine_detail_view import render_decisions_block
    # Provide a fake signals.jsonl reachable via run_dir.
    parent = tk.Frame(gui_root)
    run = _run_with_hb({}, source="local",
                       run_dir=str(tmp_path / "millennium_paper" / "rid" / "reports"))
    sig_dir = tmp_path / "millennium_paper" / "rid" / "reports"
    sig_dir.mkdir(parents=True)
    (sig_dir / "signals.jsonl").write_text(
        '{"ts":"t","symbol":"BTCUSDT","decision":"opened","score":0.8,"reason":"r"}\n',
        encoding="utf-8")
    render_decisions_block(parent, run)
    text_pool = " ".join(_collect_text(parent))
    assert "BTCUSDT" in text_pool
    assert "opened" in text_pool.lower()
    parent.destroy()
```

(Note: `RunSummary` precisa expor `run_dir` field — adicionar como `Path | None = None` ao dataclass se ainda não tem. Verificar via `grep "run_dir" launcher_support/runs_history.py` antes.)

- [ ] **Step 5.6: Run test to verify it fails**

```bash
python -m pytest tests/test_engine_detail_view.py::test_scan_funnel_block_shows_funnel_metrics -v
```

Expected: FAIL.

- [ ] **Step 5.7: Implement SCAN + DECISIONS blocks**

Append to `launcher_support/engine_detail_view.py`:

```python
# ─── Block ❸ SCAN FUNNEL ───────────────────────────────────────────


def render_scan_funnel_block(parent: tk.Widget, run: RunSummary) -> None:
    """❸ SCAN FUNNEL — last tick scanned→dedup→stale→live→opened."""
    _block_header(parent, "❸ SCAN FUNNEL (last tick)")
    hb = run.heartbeat or {}

    scanned = hb.get("last_scan_scanned") or 0
    dedup = hb.get("last_scan_dedup") or 0
    stale = hb.get("last_scan_stale") or 0
    live = hb.get("last_scan_live") or 0
    opened = hb.get("last_scan_opened") or 0

    _kv_row(parent, "scanned", str(scanned), WHITE if scanned else DIM)
    _kv_row(parent, "dedup", str(dedup), WHITE if dedup else DIM)
    _kv_row(parent, "stale", str(stale), AMBER_D if stale else DIM)
    _kv_row(parent, "live", str(live), GREEN if live else DIM)
    _kv_row(parent, "opened", str(opened), GREEN if opened else DIM)

    last_novel_at = hb.get("last_novel_at")
    _kv_row(parent, "last novel", _format_age(last_novel_at),
            AMBER if last_novel_at else DIM)


# ─── Block ❹ DECISIONS ─────────────────────────────────────────────


def render_decisions_block(parent: tk.Widget, run: RunSummary,
                           limit: int = 30) -> None:
    """❹ DECISIONS — last N signal decisions com REASON.

    Source: local signals.jsonl tail (se source==local) ou cockpit
    /v1/runs/{id}/signals (se source==vps). Skipa graceful se nenhum
    disponível.
    """
    _block_header(parent, f"❹ DECISIONS (last {limit})")

    rows = _fetch_signals(run, limit=limit)
    if not rows:
        tk.Label(parent, text="  (no signal records found)",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="w", padx=12)
        return

    # Header
    hdr = tk.Frame(parent, bg=BG)
    hdr.pack(fill="x", padx=12, pady=(2, 1))
    for label, w, anchor in (("TS", 16, "w"), ("SYMBOL", 10, "w"),
                              ("DECISION", 14, "w"), ("SCORE", 7, "e"),
                              ("REASON", 30, "w")):
        tk.Label(hdr, text=label, font=(FONT, 7, "bold"), fg=DIM,
                 bg=BG, width=w, anchor=anchor).pack(side="left", padx=(2, 0))

    for r in rows:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=12, pady=0)
        decision = str(r.get("decision", "?"))
        decision_color = {"opened": GREEN, "stale": AMBER_D,
                          "max_open": DIM, "dir_conflict": AMBER,
                          "corr_block": AMBER}.get(decision, WHITE)
        for val, w, anchor, color in (
            (str(r.get("ts", ""))[:16], 16, "w", DIM),
            (str(r.get("symbol", ""))[:10], 10, "w", WHITE),
            (decision, 14, "w", decision_color),
            (f"{float(r.get('score', 0)):.2f}", 7, "e", WHITE),
            (str(r.get("reason", ""))[:30], 30, "w", DIM),
        ):
            tk.Label(row, text=val, font=(FONT, 7), fg=color,
                     bg=BG, width=w, anchor=anchor).pack(side="left",
                                                          padx=(2, 0))


def _fetch_signals(run: RunSummary, limit: int) -> list[dict]:
    """Tail de signals.jsonl. Local: read file; VPS: cockpit endpoint."""
    import json
    rows: list[dict] = []
    if run.source == "local" and run.run_dir:
        from pathlib import Path
        sig_path = Path(run.run_dir) / "signals.jsonl"
        if not sig_path.exists():
            sig_path = Path(run.run_dir).parent / "reports" / "signals.jsonl"
        if sig_path.exists():
            try:
                for ln in sig_path.read_text(encoding="utf-8").splitlines()[-limit:]:
                    if ln.strip():
                        rows.append(json.loads(ln))
            except Exception:
                pass
    elif run.source == "vps":
        try:
            from launcher_support.engines_live_view import _get_cockpit_client
            client = _get_cockpit_client()
            if client is not None:
                resp = client.get(f"/v1/runs/{run.run_id}/signals?limit={limit}")
                if resp and isinstance(resp, dict):
                    rows = resp.get("signals", [])
        except Exception:
            pass
    return rows
```

- [ ] **Step 5.8: Wire SCAN + DECISIONS into _paint_body**

Edit `launcher_support/screens/engine_detail.py:_paint_body`, adicione após CADENCE:

```python
        from launcher_support.engine_detail_view import (
            render_triage_block, render_cadence_block,
            render_scan_funnel_block, render_decisions_block,
        )
        render_triage_block(body, run)
        render_cadence_block(body, run)
        render_scan_funnel_block(body, run)
        render_decisions_block(body, run)
```

- [ ] **Step 5.9: Run tests + smoke**

```bash
python -m pytest tests/test_engine_detail_view.py tests/test_cockpit_signals_endpoint.py -v
python smoke_test.py --quiet
```

Expected: all PASS; smoke 172/172.

- [ ] **Step 5.10: Commit**

```bash
git add launcher_support/engine_detail_view.py launcher_support/screens/engine_detail.py tools/cockpit_api.py tests/test_engine_detail_view.py tests/test_cockpit_signals_endpoint.py
git commit -m "feat(engine_detail): blocos ❸ SCAN FUNNEL + ❹ DECISIONS

- render_scan_funnel_block: scanned→dedup→stale→live→opened + last novel
- render_decisions_block: last 30 signal decisions com REASON colored
- _fetch_signals: local jsonl tail OR cockpit /v1/runs/{id}/signals
- novo endpoint /v1/runs/{id}/signals (tail de signals.jsonl)

Step 5 do plan 2026-04-25-engines-screen-inline-detail.md"
```

---

## Task 6: Block ❺ POSITIONS & EQUITY (spec Step 6)

**Files:**
- Modify: `launcher_support/engine_detail_view.py`
- Modify: `launcher_support/screens/engine_detail.py:_paint_body`
- Test: `tests/test_engine_detail_view.py` (extend)

- [ ] **Step 6.1: Write failing test**

Append to `tests/test_engine_detail_view.py`:

```python
def test_positions_block_renders_open_positions(gui_root):
    from launcher_support.engine_detail_view import render_positions_block
    parent = tk.Frame(gui_root)
    run = _run_with_hb({
        "positions": [
            {"symbol": "BTCUSDT", "direction": "long",
             "entry_price": 50000.0, "mark_price": 50500.0,
             "size_usd": 200.0, "pnl_usd": 2.0, "pnl_pct": 1.0,
             "stop": 49500.0, "target": 51000.0,
             "opened_at": "2026-04-24T18:00:00Z"},
        ],
    })
    render_positions_block(parent, run)
    text_pool = " ".join(_collect_text(parent))
    assert "BTCUSDT" in text_pool
    assert "long" in text_pool.lower()
    assert "50000" in text_pool or "50,000" in text_pool
    parent.destroy()


def test_equity_block_shows_drawdown(gui_root):
    from launcher_support.engine_detail_view import render_equity_block
    parent = tk.Frame(gui_root)
    run = _run_with_hb({
        "equity_now": 9850.0, "equity_peak": 10150.0,
        "drawdown_pct": -2.96, "exposure_pct": 18.0,
    }, equity=9850.0, initial_balance=10000.0)
    render_equity_block(parent, run)
    text_pool = " ".join(_collect_text(parent))
    assert "9850" in text_pool or "9,850" in text_pool
    assert "drawdown" in text_pool.lower() or "dd" in text_pool.lower()
    parent.destroy()
```

- [ ] **Step 6.2: Run test to verify fail**

```bash
python -m pytest tests/test_engine_detail_view.py::test_positions_block_renders_open_positions -v
```

Expected: FAIL.

- [ ] **Step 6.3: Implement POSITIONS + EQUITY blocks**

Append to `launcher_support/engine_detail_view.py`:

```python
# ─── Block ❺ POSITIONS ─────────────────────────────────────────────


def render_positions_block(parent: tk.Widget, run: RunSummary) -> None:
    """❺ POSITIONS — open positions agora."""
    _block_header(parent, "❺ OPEN POSITIONS")
    hb = run.heartbeat or {}
    positions = hb.get("positions") or []

    if not positions:
        tk.Label(parent, text="  (no open positions)",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="w", padx=12)
        return

    hdr = tk.Frame(parent, bg=BG)
    hdr.pack(fill="x", padx=12, pady=(2, 1))
    cols = (("SYMBOL", 10, "w"), ("DIR", 5, "w"),
            ("ENTRY", 11, "e"), ("MARK", 11, "e"),
            ("PNL$", 9, "e"), ("PNL%", 7, "e"),
            ("STOP", 11, "e"), ("TARGET", 11, "e"),
            ("AGE", 8, "w"))
    for label, w, anchor in cols:
        tk.Label(hdr, text=label, font=(FONT, 7, "bold"), fg=DIM,
                 bg=BG, width=w, anchor=anchor).pack(side="left", padx=(2, 0))

    for p in positions:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=12, pady=0)
        pnl_pct = p.get("pnl_pct") or 0.0
        pnl_color = GREEN if pnl_pct > 0 else (RED if pnl_pct < 0 else DIM)
        for val, w, anchor, color in (
            (str(p.get("symbol", ""))[:10], 10, "w", WHITE),
            (str(p.get("direction", ""))[:5], 5, "w",
             GREEN if str(p.get("direction")) == "long" else RED),
            (f"{p.get('entry_price', 0):.4f}", 11, "e", WHITE),
            (f"{p.get('mark_price', 0):.4f}", 11, "e", WHITE),
            (f"{p.get('pnl_usd', 0):+.2f}", 9, "e", pnl_color),
            (f"{pnl_pct:+.2f}%", 7, "e", pnl_color),
            (f"{p.get('stop', 0):.4f}", 11, "e", DIM),
            (f"{p.get('target', 0):.4f}", 11, "e", DIM),
            (_format_age(p.get("opened_at")), 8, "w", DIM),
        ):
            tk.Label(row, text=val, font=(FONT, 7), fg=color,
                     bg=BG, width=w, anchor=anchor).pack(side="left", padx=(2, 0))


# ─── Block ❺ EQUITY ────────────────────────────────────────────────


def render_equity_block(parent: tk.Widget, run: RunSummary) -> None:
    """❺ EQUITY — agora vs peak vs drawdown."""
    _block_header(parent, "❺ EQUITY")
    hb = run.heartbeat or {}

    eq_now = hb.get("equity_now") or run.equity
    eq_peak = hb.get("equity_peak")
    dd_now = hb.get("drawdown_pct")
    dd_max = hb.get("drawdown_max_pct")
    exposure = hb.get("exposure_pct")

    _kv_row(parent, "equity now", f"{eq_now:.2f}" if eq_now else "—")
    _kv_row(parent, "equity peak", f"{eq_peak:.2f}" if eq_peak else "—")
    _kv_row(parent, "drawdown now",
            f"{dd_now:+.2f}%" if dd_now is not None else "—",
            RED if dd_now and dd_now < -2 else DIM)
    _kv_row(parent, "drawdown max",
            f"{dd_max:+.2f}%" if dd_max is not None else "—",
            RED if dd_max and dd_max < -5 else DIM)
    _kv_row(parent, "exposure",
            f"{exposure:.1f}%" if exposure is not None else "—")
    _kv_row(parent, "ROI", f"{run.roi_pct:+.3f}%" if run.roi_pct is not None else "—",
            GREEN if (run.roi_pct or 0) > 0 else (RED if (run.roi_pct or 0) < 0 else DIM))
```

- [ ] **Step 6.4: Wire into _paint_body, run tests**

Edit `_paint_body` in `engine_detail.py` to import and call `render_positions_block` + `render_equity_block` after DECISIONS.

```bash
python -m pytest tests/test_engine_detail_view.py -v
python smoke_test.py --quiet
```

Expected: all new tests PASS; smoke 172/172.

- [ ] **Step 6.5: Commit**

```bash
git add launcher_support/engine_detail_view.py launcher_support/screens/engine_detail.py tests/test_engine_detail_view.py
git commit -m "feat(engine_detail): bloco ❺ POSITIONS + EQUITY

- render_positions_block: tabela open positions com pnl colored
- render_equity_block: now/peak/dd/exposure/ROI

Step 6 do plan 2026-04-25-engines-screen-inline-detail.md"
```

---

## Task 7: Block ❻ TRADES + run_metrics analytics (spec Step 7)

**Files:**
- Create: `core/analytics/__init__.py` (if absent)
- Create: `core/analytics/run_metrics.py`
- Modify: `launcher_support/engine_detail_view.py`
- Modify: `launcher_support/screens/engine_detail.py:_paint_body`
- Test: `tests/test_run_metrics.py` (new)
- Test: `tests/test_engine_detail_view.py` (extend)

- [ ] **Step 7.1: Write failing test for run_metrics**

Create `tests/test_run_metrics.py`:

```python
"""run_metrics — sharpe/win_rate/avg_R/sortino helpers."""
import math
import pytest

from core.analytics.run_metrics import (
    sharpe_rolling, win_rate, avg_r_multiple, sortino,
)


def test_win_rate_basic():
    trades = [{"pnl_usd": 1}, {"pnl_usd": -1}, {"pnl_usd": 2}]
    assert win_rate(trades) == pytest.approx(2/3)


def test_win_rate_empty():
    assert win_rate([]) == 0.0


def test_avg_r_multiple_basic():
    trades = [{"r_multiple": 1.5}, {"r_multiple": -1.0}, {"r_multiple": 2.0}]
    assert avg_r_multiple(trades) == pytest.approx(0.833, abs=0.01)


def test_sharpe_rolling_constant_returns():
    """All-zero std → sharpe defined as 0 (avoid div by zero)."""
    trades = [{"pnl_usd": 1, "ts_close": "2026-04-24T18:00:00Z"}] * 5
    assert sharpe_rolling(trades) == 0.0


def test_sharpe_rolling_basic():
    trades = [
        {"pnl_usd": 1.0, "ts_close": "2026-04-24T18:00:00Z"},
        {"pnl_usd": 2.0, "ts_close": "2026-04-24T19:00:00Z"},
        {"pnl_usd": -1.0, "ts_close": "2026-04-24T20:00:00Z"},
        {"pnl_usd": 1.5, "ts_close": "2026-04-24T21:00:00Z"},
    ]
    s = sharpe_rolling(trades)
    assert s is not None
    assert math.isfinite(s)


def test_sortino_only_downside_std():
    trades = [{"pnl_usd": 1}, {"pnl_usd": -1}, {"pnl_usd": 2}, {"pnl_usd": -2}]
    s = sortino(trades)
    assert s is not None
    assert math.isfinite(s)
```

- [ ] **Step 7.2: Run test to verify it fails**

```bash
python -m pytest tests/test_run_metrics.py -v
```

Expected: FAIL — module não existe.

- [ ] **Step 7.3: Implement run_metrics.py**

Create `core/analytics/__init__.py` (1 byte file with empty contents) if not present.

Create `core/analytics/run_metrics.py`:

```python
"""Run-level performance helpers — shared entre engine_detail_view e cockpit.

Single source of truth pra evitar drift cross-screen. Hoje cockpit
calcula sharpe/win_rate inline em vários sites — esses callers devem
migrar pra cá em um follow-up.
"""
from __future__ import annotations

import math
import statistics
from typing import Iterable


def win_rate(trades: Iterable[dict]) -> float:
    trades = list(trades)
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if (t.get("pnl_usd") or 0) > 0)
    return wins / len(trades)


def avg_r_multiple(trades: Iterable[dict]) -> float | None:
    rs = [t.get("r_multiple") for t in trades
          if t.get("r_multiple") is not None]
    if not rs:
        return None
    return sum(rs) / len(rs)


def sharpe_rolling(trades: Iterable[dict],
                   risk_free: float = 0.0) -> float | None:
    """Simple per-trade sharpe — annualised flag não aplica (curto-prazo).

    Returns 0.0 se std==0 (constant returns), None se < 2 trades.
    """
    pnls = [float(t.get("pnl_usd") or 0) for t in trades]
    if len(pnls) < 2:
        return None
    mean = statistics.mean(pnls) - risk_free
    std = statistics.pstdev(pnls)
    if std == 0:
        return 0.0
    s = mean / std
    return s if math.isfinite(s) else None


def sortino(trades: Iterable[dict], risk_free: float = 0.0) -> float | None:
    """Sortino ratio — only downside deviation no denominador."""
    pnls = [float(t.get("pnl_usd") or 0) for t in trades]
    if len(pnls) < 2:
        return None
    mean = statistics.mean(pnls) - risk_free
    downside = [p for p in pnls if p < 0]
    if not downside:
        return float("inf") if mean > 0 else 0.0
    dstd = math.sqrt(sum(p**2 for p in downside) / len(downside))
    if dstd == 0:
        return 0.0
    s = mean / dstd
    return s if math.isfinite(s) else None
```

- [ ] **Step 7.4: Run tests to verify pass**

```bash
python -m pytest tests/test_run_metrics.py -v
```

Expected: 6/6 PASS.

- [ ] **Step 7.5: Write failing test for TRADES block**

Append to `tests/test_engine_detail_view.py`:

```python
def test_trades_block_renders_full_table(gui_root):
    from launcher_support.engine_detail_view import render_trades_block
    parent = tk.Frame(gui_root)
    run = _run_with_hb({}, source="local",
                       run_dir="/tmp/no_such_run")  # forces empty fetch
    # Mock direct trades injection.
    trades = [
        {"ts": "2026-04-24T18:00:00Z", "symbol": "BTCUSDT",
         "direction": "long", "entry": 50000, "exit": 50500,
         "pnl_usd": 5.0, "r_multiple": 1.0,
         "exit_reason": "target", "slippage_usd": 0.1,
         "commission_usd": 0.05, "funding_usd": 0.02},
    ]
    render_trades_block(parent, run, trades_override=trades)
    text_pool = " ".join(_collect_text(parent))
    assert "BTCUSDT" in text_pool
    assert "5.00" in text_pool or "+5" in text_pool
    parent.destroy()
```

- [ ] **Step 7.6: Implement TRADES block**

Append to `launcher_support/engine_detail_view.py`:

```python
# ─── Block ❻ TRADES ────────────────────────────────────────────────


def render_trades_block(parent: tk.Widget, run: RunSummary,
                        *, trades_override: list[dict] | None = None,
                        ) -> None:
    """❻ TRADES — closed trades full audit + footer."""
    _block_header(parent, "❻ TRADES (closed)")

    trades = trades_override if trades_override is not None \
             else _fetch_trades(run)
    if not trades:
        tk.Label(parent, text="  (no closed trades)",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="w", padx=12)
        return

    # Header
    hdr = tk.Frame(parent, bg=BG)
    hdr.pack(fill="x", padx=12, pady=(2, 1))
    cols = (("TS", 16, "w"), ("SYM", 9, "w"), ("DIR", 5, "w"),
            ("ENTRY", 11, "e"), ("EXIT", 11, "e"), ("PNL$", 9, "e"),
            ("R", 6, "e"), ("EXIT_REASON", 14, "w"),
            ("SLIPP", 7, "e"), ("COMM", 7, "e"), ("FUND", 7, "e"))
    for label, w, anchor in cols:
        tk.Label(hdr, text=label, font=(FONT, 7, "bold"), fg=DIM,
                 bg=BG, width=w, anchor=anchor).pack(side="left", padx=(2, 0))

    for t in trades:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=12, pady=0)
        pnl = t.get("pnl_usd") or 0
        pnl_color = GREEN if pnl > 0 else (RED if pnl < 0 else DIM)
        for val, w, anchor, color in (
            (str(t.get("ts", ""))[:16], 16, "w", DIM),
            (str(t.get("symbol", ""))[:9], 9, "w", WHITE),
            (str(t.get("direction", ""))[:5], 5, "w",
             GREEN if t.get("direction") == "long" else RED),
            (f"{t.get('entry', 0):.4f}", 11, "e", WHITE),
            (f"{t.get('exit', 0):.4f}", 11, "e", WHITE),
            (f"{pnl:+.2f}", 9, "e", pnl_color),
            (f"{t.get('r_multiple', 0):+.2f}" if t.get('r_multiple') is not None else "—",
             6, "e", pnl_color),
            (str(t.get("exit_reason", ""))[:14], 14, "w", DIM),
            (f"{t.get('slippage_usd', 0):.3f}", 7, "e", DIM),
            (f"{t.get('commission_usd', 0):.3f}", 7, "e", DIM),
            (f"{t.get('funding_usd', 0):.3f}", 7, "e", DIM),
        ):
            tk.Label(row, text=val, font=(FONT, 7), fg=color,
                     bg=BG, width=w, anchor=anchor).pack(side="left", padx=(2, 0))

    # Footer agregado.
    from core.analytics.run_metrics import (
        sharpe_rolling, win_rate, avg_r_multiple, sortino,
    )
    s = sharpe_rolling(trades)
    wr = win_rate(trades)
    ar = avg_r_multiple(trades)
    so = sortino(trades)

    foot = tk.Frame(parent, bg=BG)
    foot.pack(fill="x", padx=12, pady=(6, 0))
    tk.Frame(parent, bg=DIM2, height=1).pack(fill="x", padx=12)
    foot2 = tk.Frame(parent, bg=BG)
    foot2.pack(fill="x", padx=12, pady=(2, 0))
    tk.Label(foot2,
             text=f"  total {len(trades)} · win {wr*100:.0f}% · "
                  f"avgR {ar:+.2f} · sharpe {s:+.2f} · sortino {so:+.2f}"
             if all(v is not None for v in (s, ar, so))
             else f"  total {len(trades)} · win {wr*100:.0f}%",
             font=(FONT, 7, "bold"), fg=AMBER, bg=BG).pack(anchor="w")


def _fetch_trades(run: RunSummary) -> list[dict]:
    """Local trades.jsonl tail OR cockpit /v1/runs/{id}/trades."""
    import json
    rows: list[dict] = []
    if run.source == "local" and run.run_dir:
        from pathlib import Path
        tp = Path(run.run_dir) / "trades.jsonl"
        if not tp.exists():
            tp = Path(run.run_dir).parent / "reports" / "trades.jsonl"
        if tp.exists():
            try:
                for ln in tp.read_text(encoding="utf-8").splitlines():
                    if ln.strip():
                        rows.append(json.loads(ln))
            except Exception:
                pass
    elif run.source == "vps":
        try:
            from launcher_support.engines_live_view import _get_cockpit_client
            client = _get_cockpit_client()
            if client is not None:
                resp = client.get(f"/v1/runs/{run.run_id}/trades")
                if resp and isinstance(resp, dict):
                    rows = resp.get("trades", [])
        except Exception:
            pass
    return rows
```

- [ ] **Step 7.7: Wire + run tests**

Edit `_paint_body` to call `render_trades_block(body, run)` after EQUITY.

```bash
python -m pytest tests/test_run_metrics.py tests/test_engine_detail_view.py -v
python smoke_test.py --quiet
```

Expected: all PASS; smoke 172/172.

- [ ] **Step 7.8: Commit**

```bash
git add core/analytics/__init__.py core/analytics/run_metrics.py launcher_support/engine_detail_view.py launcher_support/screens/engine_detail.py tests/test_run_metrics.py tests/test_engine_detail_view.py
git commit -m "feat(engine_detail): bloco ❻ TRADES + core/analytics/run_metrics

- core/analytics/run_metrics.py: sharpe/win_rate/avg_R/sortino (shared cross-screen)
- render_trades_block: full table com cost decomposition + footer agregado
- _fetch_trades: local jsonl OR cockpit endpoint

Step 7 do plan 2026-04-25-engines-screen-inline-detail.md"
```

---

## Task 8: Block ❼ DATA FRESHNESS + ❽ LOG TAIL (spec Step 8)

**Files:**
- Modify: `launcher_support/engine_detail_view.py`
- Modify: `launcher_support/screens/engine_detail.py:_paint_body`
- Test: `tests/test_engine_detail_view.py` (extend)

- [ ] **Step 8.1: Write failing test for FRESHNESS + LOG TAIL**

Append to `tests/test_engine_detail_view.py`:

```python
def test_freshness_block_skips_when_no_data(gui_root):
    from launcher_support.engine_detail_view import render_freshness_block
    parent = tk.Frame(gui_root)
    run = _run_with_hb({})  # no per-symbol bar age data
    render_freshness_block(parent, run)
    # Should still render header but show "—" or empty rows.
    text_pool = " ".join(_collect_text(parent))
    assert "FRESHNESS" in text_pool or "DATA" in text_pool
    parent.destroy()


def test_freshness_block_with_per_symbol_data(gui_root):
    from launcher_support.engine_detail_view import render_freshness_block
    parent = tk.Frame(gui_root)
    run = _run_with_hb({
        "data_freshness": {
            "BTCUSDT": {"last_bar_at": "2026-04-24T20:00:00Z", "source": "cache"},
            "ETHUSDT": {"last_bar_at": "2026-04-24T20:00:00Z", "source": "live"},
        },
    })
    render_freshness_block(parent, run)
    text_pool = " ".join(_collect_text(parent))
    assert "BTCUSDT" in text_pool
    assert "ETHUSDT" in text_pool
    parent.destroy()


def test_log_tail_block_renders_lines(gui_root, tmp_path):
    from launcher_support.engine_detail_view import render_log_tail_block
    log_path = tmp_path / "log.txt"
    log_path.write_text("\n".join(
        f"line {i} INFO some message" for i in range(50)
    ), encoding="utf-8")
    parent = tk.Frame(gui_root)
    run = _run_with_hb({}, source="local", run_dir=str(tmp_path))
    render_log_tail_block(parent, run, limit=10)
    text_pool = " ".join(_collect_text(parent))
    assert "line 49" in text_pool  # last line included
    parent.destroy()
```

- [ ] **Step 8.2: Implement FRESHNESS + LOG TAIL blocks**

Append to `launcher_support/engine_detail_view.py`:

```python
# ─── Block ❼ DATA FRESHNESS ────────────────────────────────────────


def render_freshness_block(parent: tk.Widget, run: RunSummary) -> None:
    """❼ DATA FRESHNESS — bar age per symbol + cache state."""
    _block_header(parent, "❼ DATA FRESHNESS")
    hb = run.heartbeat or {}
    fresh_map = hb.get("data_freshness") or {}

    if not fresh_map:
        tk.Label(parent, text="  (no per-symbol freshness data)",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="w", padx=12)
        return

    hdr = tk.Frame(parent, bg=BG)
    hdr.pack(fill="x", padx=12, pady=(2, 1))
    for label, w, anchor in (("SYMBOL", 12, "w"), ("LAST_BAR", 22, "w"),
                              ("AGE", 12, "w"), ("SOURCE", 8, "w")):
        tk.Label(hdr, text=label, font=(FONT, 7, "bold"), fg=DIM,
                 bg=BG, width=w, anchor=anchor).pack(side="left", padx=(2, 0))

    for symbol, info in sorted(fresh_map.items()):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=12, pady=0)
        last = info.get("last_bar_at", "—")
        age = _format_age(last)
        src = str(info.get("source", "?"))
        for val, w, anchor, color in (
            (str(symbol)[:12], 12, "w", WHITE),
            (str(last)[:22], 22, "w", DIM),
            (age, 12, "w", DIM),
            (src, 8, "w",
             GREEN if src == "cache" else (AMBER_D if src == "live" else DIM)),
        ):
            tk.Label(row, text=val, font=(FONT, 7), fg=color,
                     bg=BG, width=w, anchor=anchor).pack(side="left", padx=(2, 0))


# ─── Block ❽ LOG TAIL ──────────────────────────────────────────────


def render_log_tail_block(parent: tk.Widget, run: RunSummary,
                          limit: int = 200) -> None:
    """❽ LOG TAIL — last N lines do log.txt do run."""
    _block_header(parent, f"❽ LOG TAIL (last {limit})")

    lines = _fetch_log_tail(run, limit=limit)
    if not lines:
        tk.Label(parent, text="  (log unavailable)",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="w", padx=12)
        return

    # Use a Text widget pra preservar formatação + scrolling.
    txt_wrap = tk.Frame(parent, bg=BG)
    txt_wrap.pack(fill="both", expand=False, padx=12, pady=4)
    txt = tk.Text(txt_wrap, height=14, bg=BG, fg=WHITE,
                  font=(FONT, 7), wrap="none", state="normal",
                  highlightbackground=BORDER, highlightthickness=1)
    sb = tk.Scrollbar(txt_wrap, orient="vertical", command=txt.yview)
    txt.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    txt.pack(side="left", fill="both", expand=True)
    for ln in lines:
        # Color level prefix.
        if " ERROR" in ln:
            color = RED
        elif " WARN" in ln:
            color = AMBER
        elif " DEBUG" in ln:
            color = DIM
        else:
            color = WHITE
        txt.insert("end", ln + "\n", color)
        txt.tag_configure(color, foreground=color)
    txt.configure(state="disabled")
    txt.see("end")  # auto-scroll to bottom


def _fetch_log_tail(run: RunSummary, limit: int) -> list[str]:
    """Local log.txt tail OR cockpit /v1/runs/{id}/log."""
    rows: list[str] = []
    if run.source == "local" and run.run_dir:
        from pathlib import Path
        lp = Path(run.run_dir) / "log.txt"
        if not lp.exists():
            lp = Path(run.run_dir) / "logs" / "live.log"
        if lp.exists():
            try:
                rows = lp.read_text(encoding="utf-8",
                                    errors="replace").splitlines()[-limit:]
            except Exception:
                pass
    elif run.source == "vps":
        try:
            from launcher_support.engines_live_view import _get_cockpit_client
            client = _get_cockpit_client()
            if client is not None:
                resp = client.get(f"/v1/runs/{run.run_id}/log?limit={limit}")
                if resp and isinstance(resp, dict):
                    rows = resp.get("lines", []) or []
        except Exception:
            pass
    return rows
```

- [ ] **Step 8.3: Wire + run tests**

Edit `_paint_body`: import `render_freshness_block` + `render_log_tail_block`, call after TRADES.

```bash
python -m pytest tests/test_engine_detail_view.py -v
python smoke_test.py --quiet
```

Expected: all PASS; smoke 172/172.

- [ ] **Step 8.4: Commit**

```bash
git add launcher_support/engine_detail_view.py launcher_support/screens/engine_detail.py tests/test_engine_detail_view.py
git commit -m "feat(engine_detail): blocos ❼ FRESHNESS + ❽ LOG TAIL

- render_freshness_block: bar age per symbol + cache/live source
- render_log_tail_block: last 200 lines com level coloring (Text widget)

Step 8 do plan 2026-04-25-engines-screen-inline-detail.md"
```

---

## Task 9: Block ❾ ADERÊNCIA (spec Step 9)

**Files:**
- Modify: `launcher_support/engine_detail_view.py`
- Modify: `launcher_support/screens/engine_detail.py:_paint_body`
- Test: `tests/test_engine_detail_view.py` (extend)

- [ ] **Step 9.1: Write failing test**

Append to `tests/test_engine_detail_view.py`:

```python
def test_aderencia_block_skips_when_no_audit(gui_root, tmp_path, monkeypatch):
    from launcher_support.engine_detail_view import render_aderencia_block
    monkeypatch.setenv("AURUM_AUDIT_DIR", str(tmp_path))  # empty
    parent = tk.Frame(gui_root)
    run = _run_with_hb({})
    render_aderencia_block(parent, run)
    text_pool = " ".join(_collect_text(parent))
    assert "no audit" in text_pool.lower() or "—" in text_pool
    parent.destroy()


def test_aderencia_block_reads_latest_artifact(gui_root, tmp_path, monkeypatch):
    import json
    from launcher_support.engine_detail_view import render_aderencia_block

    monkeypatch.setenv("AURUM_AUDIT_DIR", str(tmp_path))
    audit = tmp_path / "2026-04-25.json"
    audit.write_text(json.dumps({
        "generated_at": "2026-04-25T00:00:00Z",
        "engines": {
            "millennium": {
                "match_pct": 87.5, "missed": [],
                "extra": [],
            }
        }
    }), encoding="utf-8")

    parent = tk.Frame(gui_root)
    run = _run_with_hb({}, engine="MILLENNIUM")
    render_aderencia_block(parent, run)
    text_pool = " ".join(_collect_text(parent))
    assert "87" in text_pool
    parent.destroy()
```

- [ ] **Step 9.2: Implement ADERÊNCIA block**

Append to `launcher_support/engine_detail_view.py`:

```python
# ─── Block ❾ ADERÊNCIA ─────────────────────────────────────────────


def render_aderencia_block(parent: tk.Widget, run: RunSummary) -> None:
    """❾ ADERÊNCIA — match% vs backtest replay (paper/shadow only).

    Source: data/audit/<YYYY-MM-DD>.json (latest by mtime).
    Skipa graceful se audit ausente ou se mode != paper/shadow.
    """
    _block_header(parent, "❾ ADERENCIA vs BACKTEST")

    if run.mode not in ("paper", "shadow"):
        tk.Label(parent, text="  (only paper/shadow runs have audit)",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="w", padx=12)
        return

    import json, os
    from pathlib import Path

    audit_dir = Path(os.environ.get("AURUM_AUDIT_DIR", "data/audit"))
    if not audit_dir.exists():
        tk.Label(parent, text="  (no audit data)",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="w", padx=12)
        return

    candidates = sorted(audit_dir.glob("*.json"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    candidates = [p for p in candidates if p.name[0].isdigit()]  # YYYY-*.json
    if not candidates:
        tk.Label(parent, text="  (no audit data)",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="w", padx=12)
        return

    latest = candidates[0]
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        tk.Label(parent, text=f"  (audit parse error: {latest.name})",
                 font=(FONT, 7), fg=RED, bg=BG).pack(anchor="w", padx=12)
        return

    engine_key = run.engine.lower()
    info = (payload.get("engines") or {}).get(engine_key)
    if info is None:
        tk.Label(parent, text=f"  ({engine_key} not in latest audit)",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="w", padx=12)
        return

    match = info.get("match_pct")
    color = GREEN if (match or 0) > 90 else (
        AMBER if (match or 0) > 70 else RED)
    _kv_row(parent, "match %",
            f"{match:.1f}%" if match is not None else "—", color)
    _kv_row(parent, "audit date", latest.stem)

    missed = info.get("missed") or []
    extra = info.get("extra") or []
    _kv_row(parent, "missed (bt→live)", str(len(missed)),
            RED if missed else DIM)
    _kv_row(parent, "extra (live→bt)", str(len(extra)),
            AMBER if extra else DIM)
```

- [ ] **Step 9.3: Wire + run tests**

Edit `_paint_body` to import `render_aderencia_block`, call after LOG TAIL.

```bash
python -m pytest tests/test_engine_detail_view.py -v
python smoke_test.py --quiet
```

Expected: all PASS; smoke 172/172.

- [ ] **Step 9.4: Commit**

```bash
git add launcher_support/engine_detail_view.py launcher_support/screens/engine_detail.py tests/test_engine_detail_view.py
git commit -m "feat(engine_detail): bloco ❾ ADERENCIA vs BACKTEST

- render_aderencia_block: lê data/audit/<YYYY-MM-DD>.json (latest)
- skipa graceful pra modes != paper/shadow ou audit ausente
- match%/missed/extra coloridos por threshold (90%/70%)

Step 9 do plan 2026-04-25-engines-screen-inline-detail.md"
```

---

## Task 10: Auto-refresh wiring (RUNNING vs STOPPED) (spec Step 10)

**Files:**
- Modify: `launcher_support/screens/engine_detail.py`
- Test: `tests/test_engine_detail_smoke.py` (extend)

- [ ] **Step 10.1: Write failing test**

Append to `tests/test_engine_detail_smoke.py`:

```python
def test_auto_refresh_armed_only_when_running(gui_root, fake_run):
    from launcher_support.screens.engine_detail import EngineDetailScreen

    class _FakeApp:
        screens = None
        def _kb(self, *_a, **_k): pass
        h_path = type("L", (), {"configure": lambda *a, **k: None})()
        h_stat = type("L", (), {"configure": lambda *a, **k: None})()
        f_lbl  = type("L", (), {"configure": lambda *a, **k: None})()

    parent = tk.Frame(gui_root)
    screen = EngineDetailScreen(parent=parent, app=_FakeApp(),
                                client_factory=lambda: None)
    screen.mount()

    # status=running → timer armed.
    screen.on_enter(run=fake_run)
    assert screen._refresh_aid is not None
    screen.on_exit()
    # After on_exit, _after_ids cleared; refresh_aid set to None.
    assert screen._refresh_aid is None

    # status=stopped → no timer.
    fake_run_stopped = fake_run._replace(status="stopped") \
        if hasattr(fake_run, "_replace") else fake_run
    # RunSummary é dataclass; usa dataclasses.replace.
    import dataclasses
    fake_run_stopped = dataclasses.replace(fake_run, status="stopped")
    screen.on_enter(run=fake_run_stopped)
    assert screen._refresh_aid is None, \
        "stopped run must not arm auto-refresh"
    screen.on_exit()
    parent.destroy()
```

- [ ] **Step 10.2: Run test (already PASS likely — Task 2 wiring covers this)**

```bash
python -m pytest tests/test_engine_detail_smoke.py::test_auto_refresh_armed_only_when_running -v
```

Expected: should PASS based on Task 2's `if run.status == "running"` guard. If FAIL, fix the on_enter logic to ensure `_refresh_aid` stays `None` for non-running.

- [ ] **Step 10.3: Add R-key reload binding for stopped runs**

Edit `engine_detail.py:on_enter`, after the auto-refresh guard:

```python
        if hasattr(app, "_kb"):
            app._kb("<Escape>", lambda: self._navigate_back())
            app._kb("r",         lambda: self._tick())
            app._kb("R",         lambda: self._tick())
```

- [ ] **Step 10.4: Commit**

```bash
git add launcher_support/screens/engine_detail.py tests/test_engine_detail_smoke.py
git commit -m "feat(engine_detail): auto-refresh 5s só se RUNNING + R reload manual

- status=running → timer armed via Screen._after(5000, _tick)
- status=stopped → snapshot estático
- R key fires _tick() em qualquer status (manual reload)

Step 10 do plan 2026-04-25-engines-screen-inline-detail.md"
```

---

## Task 11: Selection preservation + breadcrumb tests (spec Step 11)

**Files:**
- Modify: `launcher_support/runs_history.py` (preserve `selected_run_id` + scroll)
- Test: `tests/test_engines_navigation.py` (extend)

- [ ] **Step 11.1: Write failing test for selection preservation**

Append to `tests/test_engines_navigation.py`:

```python
def test_breadcrumb_engines_click_returns_to_list(gui_root):
    """Click no breadcrumb 'ENGINES' chama screens.show('engines')."""
    from launcher_support.screens.engine_detail import EngineDetailScreen

    parent = tk.Frame(gui_root)
    mock_screens = MagicMock()

    class _FakeApp:
        screens = mock_screens
        def _kb(self, *_a, **_k): pass
        h_path = type("L", (), {"configure": lambda *a, **k: None})()
        h_stat = type("L", (), {"configure": lambda *a, **k: None})()
        f_lbl  = type("L", (), {"configure": lambda *a, **k: None})()

    screen = EngineDetailScreen(parent=parent, app=_FakeApp(),
                                client_factory=lambda: None)
    screen.mount()
    screen.on_enter(run=_fake_run())

    # Find the "ENGINES " label in the breadcrumb and click it.
    bc = screen._breadcrumb
    eng_lbl = None
    for w in bc.winfo_children():
        try:
            txt = w.cget("text")
        except Exception:
            continue
        if "ENGINES" in str(txt):
            eng_lbl = w
            break
    assert eng_lbl is not None
    eng_lbl.event_generate("<Button-1>")
    mock_screens.show.assert_called_with("engines")
    screen.on_exit()
    parent.destroy()
```

- [ ] **Step 11.2: Run test**

```bash
python -m pytest tests/test_engines_navigation.py -v
```

Expected: PASS (breadcrumb already implemented in Task 2).

- [ ] **Step 11.3: Verify selection preservation**

The `selected_run_id` is already stored in `state` in Task 3. Confirm it survives screen flip:

In `runs_history.py:render_runs_history`, the screen-level state is recreated on each `render_runs_history` call. To preserve selection across navigation, leverage `EnginesScreen._mount` keeping the same root mounted — the state survives because `EnginesScreen` is cached via `ScreenManager`. Verify:

```bash
python -m pytest tests/test_engine_detail_smoke.py tests/test_engines_navigation.py -v
```

If selection isn't preserved by ScreenManager caching, add explicit selection restore:

In `launcher_support/screens/engines.py:_mount`, no rebuild se já montado — `runs_history.resume_runs_history(self._history_root, self.app)` preserva state.

- [ ] **Step 11.4: Commit (if any code changed)**

```bash
git add tests/test_engines_navigation.py
git commit -m "test(engine_detail): breadcrumb click + selection preservation

Step 11 do plan 2026-04-25-engines-screen-inline-detail.md"
```

---

## Task 12: Drift footer + cleanup (spec Step 12)

**Files:**
- Modify: `launcher_support/screens/engine_detail.py` (footer)
- Modify: `launcher_support/runs_history.py` (delete moved helpers — only if engine_detail_view fully covers)
- Test: `tests/test_engine_detail_smoke.py` (extend)

- [ ] **Step 12.1: Write failing test for footer**

Append to `tests/test_engine_detail_smoke.py`:

```python
def test_footer_shows_data_source_and_timestamp(gui_root, fake_run):
    from launcher_support.screens.engine_detail import EngineDetailScreen

    class _FakeApp:
        screens = None
        def _kb(self, *_a, **_k): pass
        h_path = type("L", (), {"configure": lambda *a, **k: None})()
        h_stat = type("L", (), {"configure": lambda *a, **k: None})()
        f_lbl  = type("L", (), {"configure": lambda *a, **k: None})()

    parent = tk.Frame(gui_root)
    screen = EngineDetailScreen(parent=parent, app=_FakeApp(),
                                client_factory=lambda: None)
    screen.mount()
    screen.on_enter(run=fake_run)

    # Walk all descendant labels for "source" or "vps" or refresh time.
    def _all_text(w):
        out = []
        if isinstance(w, tk.Label):
            try: out.append(str(w.cget("text")))
            except Exception: pass
        for c in w.winfo_children():
            out.extend(_all_text(c))
        return out
    pool = " ".join(_all_text(parent))
    assert "vps" in pool.lower() or "source" in pool.lower()
    screen.on_exit()
    parent.destroy()
```

- [ ] **Step 12.2: Implement footer**

Edit `launcher_support/screens/engine_detail.py:_paint_body`, add at end:

```python
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
```

- [ ] **Step 12.3: Run all tests + smoke**

```bash
python -m pytest tests/test_engine_detail_smoke.py tests/test_engine_detail_view.py tests/test_engines_navigation.py tests/test_run_metrics.py tests/test_runs_history_list_mode.py tests/test_cockpit_signals_endpoint.py tests/test_runs_history.py -v
python smoke_test.py --quiet
python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all targeted PASS; smoke 172/172; full suite 2139+ passed.

- [ ] **Step 12.4: Commit**

```bash
git add launcher_support/screens/engine_detail.py tests/test_engine_detail_smoke.py
git commit -m "feat(engine_detail): drift footer com source + refresh timestamp

- footer fixo no rodapé do scroll com source (local|vps|db) + UTC time
- evita drift silencioso entre cockpit/detail/runs_history

Step 12 do plan 2026-04-25-engines-screen-inline-detail.md"
```

---

## Task 13: Manual visual checklist + session log + push

**Files:**
- Create: `docs/sessions/2026-04-25_<HHMM>.md` (session log)
- Modify: `docs/days/2026-04-25.md` (daily log)

- [ ] **Step 13.1: Manual visual checklist**

Run launcher and walk through:

```bash
python launcher.py
```

Checklist:
1. Click DATA → ENGINES. Lista deve ocupar full width (sem pane direito).
2. Verificar 14 colunas: `ST · ENGINE · MODE · STARTED · DUR · TICKS · SIG · EQUITY · ROI · DD% · SHARPE · #POS · TRADES · SRC`.
3. Click numa run RUNNING (paper/shadow VPS). Página nova abre com 9 blocos.
4. ❶ TRIAGE — sem error banner se hb limpo; banner red se `last_error` presente.
5. ❷ CADENCE — ticks_ok crescente; primed=True; ks_state=armed.
6. ❸ SCAN FUNNEL — números last tick; last novel age.
7. ❹ DECISIONS — tabela populada (ou "no signal records found" pra runs novas).
8. ❺ POSITIONS — tabela se há posições abertas; "no open positions" caso contrário.
9. ❻ TRADES — tabela completa scrollable + footer com sharpe/win/avgR/sortino.
10. ❼ FRESHNESS — pode ser "(no per-symbol freshness data)" se hb não popula.
11. ❽ LOG TAIL — Text widget com last 200 lines, color-coded by level.
12. ❾ ADERENCIA — match% se audit existe; "(no audit data)" caso contrário.
13. ESC volta pra lista preservando seleção e scroll.
14. Click breadcrumb "ENGINES" volta pra lista.
15. R key força reload manual.
16. Auto-refresh 5s só pra runs running; runs stopped ficam estáticas.
17. Click numa run STOPPED — mesma página, sem timer, footer mostra source.

- [ ] **Step 13.2: Write session log**

Create `docs/sessions/2026-04-25_<HHMM>.md` per CLAUDE.md format. Inclui resumo, commits (todos os 12 da branch), arquivos modificados, manual checklist results, próximos passos.

- [ ] **Step 13.3: Update daily log**

Edit `docs/days/2026-04-25.md` (cria se não existe) — adiciona sessão no topo de "Sessões do dia", atualiza commits do dia.

- [ ] **Step 13.4: Final commit + push branch**

```bash
git add docs/sessions/2026-04-25_*.md docs/days/2026-04-25.md
git commit -m "docs(sessions+days): 2026-04-25 — DATA > ENGINES inline detail page"
git push -u origin feat/engines-detail-page
```

- [ ] **Step 13.5: Open PR (optional, Joao decision)**

```bash
gh pr create --title "feat(engines): inline detail page (debug-first, 9 blocos)" \
  --body-file docs/superpowers/specs/2026-04-25-engines-screen-inline-detail-design.md
```

---

## Done-when

- Suite verde: smoke 172/172, runs_history 48/48, engine_detail_view ~14, engine_detail_smoke ~5, engines_navigation ~3, run_metrics 6/6, cockpit_signals 2/2.
- CORE intocado (`core/{indicators,signals,portfolio}.py`, `config/params.py` zero-diff vs main).
- Manual checklist 17/17 OK.
- Session + daily log committed.
- Branch pushed.
