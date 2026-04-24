# BACKTEST Panel Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the crypto dashboard BACKTEST tab into a 3-layer hierarchy (engine → run → metrics). Left panel becomes a list of engines; right panel splits into metrics (top) + runs of the active engine (bottom). Zero change to `core/`, `engines/`, `config/params.py` or any trading/backtest logic.

**Architecture:** Pure UI refactor in `launcher.py`. Add two module-level constants (`_ENGINE_BADGES`, `_BT_RUN_COLS`) and one helper method (`_bt_group_runs_by_engine`). Add three new App methods (`_dash_backtest_render_engines`, `_dash_backtest_render_runs`, `_dash_backtest_select_engine`). Rewrite `_dash_build_backtest_tab` and `_dash_backtest_render`. Reuse `_dash_backtest_select` (metrics panel populator) unchanged. The existing delete flow auto-benefits because it already calls `_dash_backtest_render()` after a delete.

**Tech Stack:** Python 3.14 · Tkinter · existing launcher theme constants (`BG`, `PANEL`, `AMBER`, `AMBER_B`, `AMBER_D`, `GREEN`, `RED`, `DIM`, `DIM2`, `BG3`, `WHITE`, `BORDER`, `FONT`).

**Testing note:** The launcher has no headless Tk test suite. Verification per task uses `python -c "import launcher"` (syntax/import check) plus `python smoke_test.py --quiet` (repo-wide). Final visual validation runs in Task 5 by launching the app.

---

### Task 1: Add module-level constants (`_ENGINE_BADGES`, `_BT_RUN_COLS`)

**Files:**
- Modify: `launcher.py:1008-1020` (insert new constants right after `_BT_COLS`)

- [ ] **Step 1: Locate the insertion point**

Open `launcher.py` and find `_BT_COLS` around line 1008. The new constants go immediately after the closing `]` of `_BT_COLS` (line 1020), before `class App(tk.Tk):` on line 1023.

- [ ] **Step 2: Insert the constants**

Add the following block between line 1020 and line 1023 (i.e., after the `_BT_COLS = [ ... ]` list and before `class App(tk.Tk):`):

```python


# ═══════════════════════════════════════════════════════════
# BACKTEST RUNS TABLE — per-engine view (ENGINE column dropped)
# ═══════════════════════════════════════════════════════════
# Used by the right-bottom runs list in the BACKTEST tab after
# the engine → run → metrics hierarchy refactor. Same char widths
# as _BT_COLS so the existing row renderer can be reused; the
# STRATEGY column is omitted because the list is already filtered
# to a single engine (picked in the left panel).
_BT_RUN_COLS: list[tuple[str, int]] = [
    ("DATE / TIME",  19),
    ("TF",            5),
    ("DAYS",          5),
    ("BASKET",       10),
    ("RUN",          14),
    ("TRADES",        8),
    ("WIN%",          8),
    ("PNL",          12),
    ("SHARPE",        8),
    ("DD",            8),
]


# ═══════════════════════════════════════════════════════════
# BACKTEST ENGINE BADGES — OOS status glyphs for the left panel
# ═══════════════════════════════════════════════════════════
# Static map: CLAUDE.md engine table + 2026-04-16 OOS audit
# verdicts. Keys cover both institutional slugs and their legacy
# lowercase aliases (e.g. "thoth" → bridgewater) so runs written
# before the engine rename still get the right glyph.
_ENGINE_BADGES: dict[str, str] = {
    "citadel":            "✅",
    "backtest":           "✅",
    "jump":               "✅",
    "mercurio":           "✅",
    "renaissance":        "⚠️",
    "harmonics":          "⚠️",
    "harmonics_backtest": "⚠️",
    "bridgewater":        "🔴",
    "thoth":              "🔴",
    "deshaw":             "🔴",
    "de_shaw":            "🔴",
    "newton":             "🔴",
    "kepos":              "🔴",
    "medallion":          "🔴",
    "phi":                "🆕",
    "two_sigma":          "⚪",
    "twosigma":           "⚪",
    "prometeu":           "⚪",
    "aqr":                "⚪",
    "darwin":             "⚪",
    "jane_street":        "⚪",
    "janestreet":         "⚪",
    "arbitrage":          "⚪",
    "millennium":         "·",
    "multistrategy":      "·",
    "winton":             "·",
    "graham":             "🗄️",
}
```

- [ ] **Step 3: Import check**

Run: `python -c "import launcher; print('OK')"`
Expected: `OK` (no traceback). If a `SyntaxError` appears, re-check indentation and quotes.

- [ ] **Step 4: Smoke test**

Run: `python smoke_test.py --quiet`
Expected: all-green output (same count as pre-change baseline).

- [ ] **Step 5: Commit**

```bash
git add launcher.py
git commit -m "$(cat <<'EOF'
feat(launcher): add backtest engine badges + per-engine run cols

Module-level constants for the BACKTEST tab hierarchy refactor:
_ENGINE_BADGES maps slugs to OOS status glyphs, _BT_RUN_COLS drops
the ENGINE column from the runs table (redundant after filtering).
No behavior change yet — wiring lands in the next tasks.
EOF
)"
```

---

### Task 2: Add `_bt_group_runs_by_engine` helper

**Files:**
- Modify: `launcher.py:11139` (add new method on `App`, right before `_bt_collect_runs`)

- [ ] **Step 1: Locate insertion point**

Open `launcher.py` and find `def _bt_collect_runs(self) -> list[dict]:` at line 11139. Insert the new method immediately before it (same indentation — 4 spaces, method of `App`).

- [ ] **Step 2: Insert the helper**

Paste this method right above `def _bt_collect_runs`:

```python
    def _bt_group_runs_by_engine(self, runs: list[dict]) -> list[tuple[str, list[dict]]]:
        """Group runs by engine slug, preserving each group's internal order.

        Input `runs` comes from _bt_collect_runs() already sorted by
        timestamp desc, so the first run seen per engine is that engine's
        most recent. Returns a list of (engine_slug, runs) tuples ordered
        by each engine's most-recent-run desc — engine that ran most
        recently appears first. Runs with empty/missing engine slug are
        skipped (defensive — they'd have no home in the UI anyway).
        """
        groups: dict[str, list[dict]] = {}
        order: list[str] = []
        for run in runs:
            slug = str(run.get("engine") or "").lower().strip()
            if not slug:
                continue
            if slug not in groups:
                groups[slug] = []
                order.append(slug)
            groups[slug].append(run)
        return [(slug, groups[slug]) for slug in order]
```

- [ ] **Step 3: Import check**

Run: `python -c "import launcher; print('OK')"`
Expected: `OK`.

- [ ] **Step 4: Smoke test**

Run: `python smoke_test.py --quiet`
Expected: all-green.

- [ ] **Step 5: Commit**

```bash
git add launcher.py
git commit -m "$(cat <<'EOF'
feat(launcher): add _bt_group_runs_by_engine helper

Groups runs by engine slug preserving most-recent-first ordering of
both engines and each engine's internal run list. Feeds the new
BACKTEST hierarchy; not wired into UI yet.
EOF
)"
```

---

### Task 3: Add new render + selector methods (dormant)

**Files:**
- Modify: `launcher.py:11269` (insert three new methods right before `_dash_backtest_render`)

These methods reference widget keys (`bt_engines`, `bt_runs`, `bt_active_engine`) that don't exist yet. Each one early-returns if its widget is absent, so they're safely dormant until Task 4 wires them in.

- [ ] **Step 1: Locate insertion point**

Open `launcher.py` and find `def _dash_backtest_render(self):` at line 11269. Insert the three new methods immediately before it (same indentation — 4 spaces, methods of `App`).

- [ ] **Step 2: Insert `_dash_backtest_render_engines`**

Paste this method right above `def _dash_backtest_render`:

```python
    def _dash_backtest_render_engines(self, groups: list[tuple[str, list[dict]]]) -> None:
        """Paint the left-panel engines list from grouped runs.

        Each row: ● (only on active engine) · DISPLAY NAME · badge · count.
        Clicking a row delegates to _dash_backtest_select_engine.
        """
        wrap = self._dash_widgets.get(("bt_engines",))
        if wrap is None:
            return
        try:
            if not wrap.winfo_exists():
                return
        except Exception:
            return

        for w in wrap.winfo_children():
            try: w.destroy()
            except Exception: pass

        _ENGINE_NAMES = {
            "backtest": "CITADEL", "citadel": "CITADEL",
            "thoth": "BRIDGEWATER", "bridgewater": "BRIDGEWATER",
            "mercurio": "JUMP", "jump": "JUMP",
            "newton": "DE SHAW", "deshaw": "DE SHAW", "de_shaw": "DE SHAW",
            "prometeu": "TWO SIGMA", "twosigma": "TWO SIGMA", "two_sigma": "TWO SIGMA",
            "darwin": "AQR", "aqr": "AQR",
            "multistrategy": "MILLENNIUM", "millennium": "MILLENNIUM",
            "harmonics": "RENAISSANCE", "harmonics_backtest": "RENAISSANCE",
            "renaissance": "RENAISSANCE",
            "arbitrage": "JANE STREET", "jane_street": "JANE STREET",
            "janestreet": "JANE STREET",
        }

        active = getattr(self, "_bt_active_engine", None)

        if not groups:
            tk.Label(wrap, text="  — no engines found —",
                     font=(FONT, 8), fg=DIM, bg=BG,
                     anchor="w").pack(fill="x", pady=10)
            return

        for slug, engine_runs in groups:
            display = _ENGINE_NAMES.get(slug, slug.replace("_", " ").upper())
            badge = _ENGINE_BADGES.get(slug, " ")
            count = len(engine_runs)
            is_active = (slug == active)

            row = tk.Frame(wrap, bg=BG, cursor="hand2")
            row.pack(fill="x", pady=0)

            dot = tk.Label(row, text="●" if is_active else " ",
                           font=(FONT, 10, "bold"),
                           fg=AMBER if is_active else BG, bg=BG, width=2,
                           anchor="w")
            dot.pack(side="left")
            name_lbl = tk.Label(row, text=display, font=(FONT, 9, "bold"),
                                fg=AMBER if is_active else WHITE, bg=BG,
                                width=13, anchor="w")
            name_lbl.pack(side="left")
            badge_lbl = tk.Label(row, text=badge, font=(FONT, 9),
                                 fg=DIM2, bg=BG, width=3, anchor="w")
            badge_lbl.pack(side="left")
            count_lbl = tk.Label(row, text=f"{count:>3}",
                                 font=(FONT, 8), fg=DIM, bg=BG,
                                 width=4, anchor="e")
            count_lbl.pack(side="left")

            labels = [dot, name_lbl, badge_lbl, count_lbl]

            def _select(_e=None, s=slug):
                self._dash_backtest_select_engine(s)

            def _enter(_e=None, lbls=labels):
                for l in lbls:
                    try: l.configure(bg=BG3)
                    except Exception: pass

            def _leave(_e=None, lbls=labels):
                for l in lbls:
                    try: l.configure(bg=BG)
                    except Exception: pass

            for w in (row, *labels):
                w.bind("<Button-1>", _select)
                w.bind("<Enter>", _enter)
                w.bind("<Leave>", _leave)
```

- [ ] **Step 3: Insert `_dash_backtest_render_runs`**

Paste this method immediately after `_dash_backtest_render_engines`:

```python
    def _dash_backtest_render_runs(self, engine: str | None, runs: list[dict]) -> None:
        """Paint the right-bottom runs list, filtered to `engine`.

        Same row format as the legacy flat list minus the ENGINE column.
        Clicking a row delegates to _dash_backtest_select (the existing
        metrics-panel populator; unchanged).
        """
        wrap = self._dash_widgets.get(("bt_runs",))
        if wrap is None:
            return
        try:
            if not wrap.winfo_exists():
                return
        except Exception:
            return

        for w in wrap.winfo_children():
            try: w.destroy()
            except Exception: pass

        if engine is None or not runs:
            tk.Label(wrap,
                     text="  ← select an engine to view runs",
                     font=(FONT, 8), fg=DIM, bg=BG,
                     anchor="w").pack(fill="x", pady=10)
            return

        def _fmt_n(v, suffix=""): return f"{v:.2f}{suffix}" if v is not None else "—"
        def _fmt_m(v): return f"${v:+,.0f}" if v is not None else "—"

        _L6_FIX_DATE = "2026-04-11"
        _L6_AFFECTED = {"mercurio", "thoth", "harmonics", "newton", "multistrategy"}

        for run in runs[:100]:
            run_id = run.get("run_id", "?")
            ts_raw = run.get("timestamp") or ""
            ts     = self._bt_fmt_timestamp(ts_raw)
            tf     = str(run.get("interval") or "—")
            days   = run.get("period_days")
            days_s = f"{int(days)}" if days else "—"
            basket = str(run.get("basket") or "—")[:9]
            n_tr   = run.get("n_trades") or 0
            wr     = run.get("win_rate")
            pnl    = run.get("pnl")
            sh     = run.get("sharpe")
            dd     = run.get("max_dd_pct")

            pre_l6 = (engine in _L6_AFFECTED
                      and isinstance(ts_raw, str)
                      and ts_raw < _L6_FIX_DATE)

            row = tk.Frame(wrap, bg=BG, cursor="hand2")
            row.pack(fill="x", pady=0)

            pnl_col = GREEN if (pnl or 0) > 0 else (RED if (pnl or 0) < 0 else DIM)
            short_id = run_id
            for prefix in (
                "citadel_", "thoth_", "bridgewater_", "newton_", "deshaw_",
                "mercurio_", "jump_", "multistrategy_", "millennium_",
                "prometeu_", "twosigma_", "renaissance_", "harmonics_",
            ):
                if short_id.startswith(prefix):
                    short_id = short_id[len(prefix):]
                    break
            if pre_l6:
                short_id = ("! " + short_id)[:13]
            else:
                short_id = short_id[:13]

            (_dw, _tfw, _dyw, _bkw, _rw, _tw, _ww, _pw, _shw, _ddw) = [w for _, w in _BT_RUN_COLS]
            run_col = RED if pre_l6 else AMBER
            cells = [
                (ts,                  _dw,  WHITE,   "normal"),
                (tf,                  _tfw, AMBER_D, "normal"),
                (days_s,              _dyw, WHITE,   "normal"),
                (basket,              _bkw, WHITE,   "normal"),
                (short_id,            _rw,  run_col, "bold"),
                (f"{n_tr}",           _tw,  WHITE,   "normal"),
                (_fmt_n(wr),          _ww,  WHITE,   "normal"),
                (_fmt_m(pnl),         _pw,  pnl_col, "bold"),
                (_fmt_n(sh),          _shw, WHITE,   "normal"),
                (_fmt_n(dd, "%"),     _ddw,
                 RED if (dd or 0) > 5 else DIM, "normal"),
            ]
            row_labels = []
            for text, width, color, weight in cells:
                lbl = tk.Label(row, text=text,
                               font=(FONT, 8, weight),
                               fg=color, bg=BG, width=width, anchor="w")
                lbl.pack(side="left")
                row_labels.append(lbl)

            def _select(_e=None, rid=run_id):
                self._dash_backtest_select(rid)

            def _enter(_e=None, labels=row_labels):
                for l in labels:
                    try: l.configure(bg=BG3)
                    except Exception: pass

            def _leave(_e=None, labels=row_labels):
                for l in labels:
                    try: l.configure(bg=BG)
                    except Exception: pass

            for w in (row, *row_labels):
                w.bind("<Button-1>", _select)
                w.bind("<Enter>", _enter)
                w.bind("<Leave>", _leave)
```

- [ ] **Step 4: Insert `_dash_backtest_select_engine`**

Paste this method immediately after `_dash_backtest_render_runs`:

```python
    def _dash_backtest_select_engine(self, engine: str) -> None:
        """Mark `engine` as the active one, repaint both lists, and
        auto-select its most recent run so the metrics panel updates
        in one click."""
        runs = self._bt_collect_runs()
        groups = self._bt_group_runs_by_engine(runs)
        engine_map = dict(groups)
        if engine not in engine_map:
            return
        self._bt_active_engine = engine
        self._dash_backtest_render_engines(groups)
        self._dash_backtest_render_runs(engine, engine_map[engine])
        latest = engine_map[engine][0]
        rid = latest.get("run_id")
        if rid:
            self._dash_backtest_select(rid)
```

- [ ] **Step 5: Import check**

Run: `python -c "import launcher; print('OK')"`
Expected: `OK`.

- [ ] **Step 6: Smoke test**

Run: `python smoke_test.py --quiet`
Expected: all-green.

- [ ] **Step 7: Commit**

```bash
git add launcher.py
git commit -m "$(cat <<'EOF'
feat(launcher): add dormant engine/runs renderers for BACKTEST tab

Three new methods wired to widget keys (bt_engines, bt_runs) that do
not exist yet — each early-returns until Task 4 restructures the tab
layout. No user-visible change.
EOF
)"
```

---

### Task 4: Swap the BACKTEST tab layout and entry render

This task makes the new hierarchy visible. It replaces the body of `_dash_build_backtest_tab` (new layout) and rewrites `_dash_backtest_render` (coordinator: collect → group → paint → auto-select).

**Files:**
- Modify: `launcher.py:10777-10868` (entire `_dash_build_backtest_tab` body)
- Modify: `launcher.py:11269-11418` (entire `_dash_backtest_render` body)

- [ ] **Step 1: Replace `_dash_build_backtest_tab`**

Find `def _dash_build_backtest_tab(self, parent):` at line 10777 and replace the whole method (through line 10868, ending with `self._dash_backtest_render()`) with this exact code. Keep the 4-space class indentation.

```python
    def _dash_build_backtest_tab(self, parent):
        """Three-region layout for the BACKTEST hierarchy:
        engines list (left) + details column (right), where the
        details column stacks metrics (top) and the runs list filtered
        to the active engine (bottom). Clicking an engine repaints the
        runs list and auto-loads the most recent run's metrics."""
        wrap = tk.Frame(parent, bg=BG); wrap.pack(fill="both", expand=True, padx=14, pady=8)

        hdr = tk.Frame(wrap, bg=BG); hdr.pack(fill="x")
        tk.Label(hdr, text="[ BACKTEST ]", font=(FONT, 9, "bold"),
                 fg=AMBER, bg=BG).pack(side="left")
        count_l = tk.Label(hdr, text="", font=(FONT, 7), fg=DIM, bg=BG)
        count_l.pack(side="right")
        self._dash_widgets[("bt_count",)] = count_l
        tk.Frame(wrap, bg=AMBER_D, height=1).pack(fill="x", pady=(2, 8))

        # Main split: engines (left, fixed 220px) + detail column (right, rest)
        split = tk.Frame(wrap, bg=BG); split.pack(fill="both", expand=True)

        # ── LEFT: engines list ──
        left = tk.Frame(split, bg=BG, width=220)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)

        tk.Label(left, text="ENGINE", font=(FONT, 8, "bold"),
                 fg=DIM, bg=BG, anchor="w").pack(fill="x")
        tk.Frame(left, bg=DIM2, height=1).pack(fill="x", pady=(1, 2))

        engines_wrap = tk.Frame(left, bg=BG)
        engines_wrap.pack(fill="both", expand=True)
        self._dash_widgets[("bt_engines",)] = engines_wrap

        # ── RIGHT: details column (metrics on top, runs on bottom) ──
        right = tk.Frame(split, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        # ── RIGHT TOP: metrics panel (fixed height so runs list always
        # has a predictable share of the vertical space) ──
        detail_frame = tk.Frame(right, bg=PANEL,
                                highlightbackground=BORDER, highlightthickness=1,
                                height=340)
        detail_frame.pack(side="top", fill="x", pady=(0, 6))
        detail_frame.pack_propagate(False)

        tk.Label(detail_frame, text=" [ DETAILS ] ",
                 font=(FONT, 7, "bold"), fg=BG, bg=AMBER,
                 padx=6, pady=2).pack(anchor="nw", padx=6, pady=(6, 2))

        detail_body = tk.Frame(detail_frame, bg=PANEL)
        detail_body.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        self._dash_widgets[("bt_detail",)] = detail_body

        tk.Label(detail_body,
                 text="\n← click an engine to load its runs",
                 font=(FONT, 8), fg=DIM, bg=PANEL,
                 justify="left").pack(anchor="w")

        # ── RIGHT BOTTOM: runs list (filtered to active engine) ──
        runs_frame = tk.Frame(right, bg=BG)
        runs_frame.pack(side="top", fill="both", expand=True)

        # Column headers — widths from _BT_RUN_COLS (no ENGINE column)
        hrow = tk.Frame(runs_frame, bg=BG); hrow.pack(fill="x")
        for label, width in _BT_RUN_COLS:
            tk.Label(hrow, text=label, font=(FONT, 8, "bold"),
                     fg=DIM, bg=BG, width=width,
                     anchor="w").pack(side="left")
        tk.Frame(runs_frame, bg=DIM2, height=1).pack(fill="x", pady=(1, 2))

        # Scrollable runs list (Canvas + inner frame)
        canvas_wrap = tk.Frame(runs_frame, bg=BG)
        canvas_wrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(canvas_wrap, bg=BG, bd=0, highlightthickness=0)
        scroll = tk.Scrollbar(canvas_wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        inner = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        def _on_configure(event, c=canvas): c.configure(scrollregion=c.bbox("all"))
        inner.bind("<Configure>", _on_configure)

        # Mouse wheel — scoped to the runs canvas only (bind_all is
        # toggled on enter/leave so it doesn't leak to other tabs)
        def _on_wheel(event, c=canvas):
            try: c.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except tk.TclError: pass
        def _enter(_e=None, c=canvas):
            c.bind_all("<MouseWheel>", _on_wheel)
        def _leave(_e=None, c=canvas):
            try: c.unbind_all("<MouseWheel>")
            except tk.TclError: pass
        canvas.bind("<Enter>", _enter)
        canvas.bind("<Leave>", _leave)
        inner.bind("<Enter>", _enter)
        inner.bind("<Leave>", _leave)

        self._dash_widgets[("bt_runs",)] = inner
        self._dash_widgets[("bt_runs_canvas",)] = canvas

        self.f_lbl.configure(
            text="BACKTEST · click engine for runs · click run for details · "
                 "1=Home 2=Market 3=Portfolio 4=Trades 5=Backtest 6=Cockpit · R refresh"
        )

        self._bt_active_engine = None
        self._dash_backtest_render()
```

- [ ] **Step 2: Replace `_dash_backtest_render`**

Find `def _dash_backtest_render(self):` at line 11269 and replace the whole method (through line 11418 — the original method ends right before `def _dash_backtest_select(self, run_id: str):`) with this exact code:

```python
    def _dash_backtest_render(self) -> None:
        """BACKTEST tab entry point: collect runs, group by engine,
        paint the engines list + runs list, and auto-select the active
        engine's most recent run so the metrics panel is populated at
        steady state. Called on tab open and after a delete."""
        count_l = self._dash_widgets.get(("bt_count",))
        runs = self._bt_collect_runs()
        groups = self._bt_group_runs_by_engine(runs)

        if count_l is not None:
            try:
                count_l.configure(text=f"{len(groups)} engines · {len(runs)} runs")
            except tk.TclError:
                pass

        if not groups:
            self._bt_active_engine = None
            self._dash_backtest_render_engines(groups)
            self._dash_backtest_render_runs(None, [])
            body = self._dash_widgets.get(("bt_detail",))
            if body is not None:
                try:
                    for w in body.winfo_children():
                        w.destroy()
                    tk.Label(body,
                             text="\n← run a backtest first",
                             font=(FONT, 8), fg=DIM, bg=PANEL,
                             justify="left").pack(anchor="w")
                except tk.TclError:
                    pass
            return

        engine_map = dict(groups)
        active = getattr(self, "_bt_active_engine", None)
        if active not in engine_map:
            active = groups[0][0]
        self._bt_active_engine = active

        self._dash_backtest_render_engines(groups)
        self._dash_backtest_render_runs(active, engine_map[active])

        latest = engine_map[active][0]
        rid = latest.get("run_id")
        if rid:
            self._dash_backtest_select(rid)
```

- [ ] **Step 3: Import check**

Run: `python -c "import launcher; print('OK')"`
Expected: `OK`. A `SyntaxError` here means the method replacement overran or fell short — re-check the begin/end boundaries.

- [ ] **Step 4: Sanity grep — old widget keys must be gone**

Run (via the Grep tool, not shell): search `launcher.py` for the string `bt_list`.
Expected: zero matches. Same for `bt_canvas`. If any remain, the rewrite missed a spot.

- [ ] **Step 5: Smoke test**

Run: `python smoke_test.py --quiet`
Expected: all-green.

- [ ] **Step 6: Commit**

```bash
git add launcher.py
git commit -m "$(cat <<'EOF'
feat(launcher): switch BACKTEST tab to engine → run → metrics layout

_dash_build_backtest_tab now builds a 3-region layout (engines left,
metrics top-right, runs bottom-right). _dash_backtest_render becomes
a coordinator: group runs by engine, paint both lists, auto-select
the most-recent engine's most-recent run so metrics load on tab open.
Old flat list + bt_list/bt_canvas widgets retired.
EOF
)"
```

---

### Task 5: Visual validation in the live launcher

No code change. This task confirms the UI behaves as the spec says by running the app and walking the flow. Any defect found here loops back and fixes it before marking the task done.

**Files:**
- None (read-only verification)

- [ ] **Step 1: Launch the app**

Run: `python launcher.py`
Expected: splash → main menu opens with no traceback in the terminal.

- [ ] **Step 2: Navigate to BACKTEST tab**

From the main menu, open DATA → crypto dashboard (or use the existing route). Press `4` to switch to the BACKTEST tab.
Expected:
- Left panel shows a vertical list of engines, one row each (CITADEL, JUMP, etc.), with the most recently run engine at the top and a `●` next to it.
- Right-top panel shows PERFORMANCE / TRADES / CONFIG for that engine's latest run (metrics already loaded — zero clicks needed).
- Right-bottom panel shows that engine's runs, newest first, with no ENGINE column.
- Header counter reads `N engines · M runs`.

- [ ] **Step 3: Click another engine**

Click on a different engine in the left panel (e.g. RENAISSANCE).
Expected:
- `●` jumps to the clicked row; previous active row dims back to `WHITE`.
- Right-bottom runs list repaints with that engine's runs.
- Right-top metrics update to that engine's most recent run.

- [ ] **Step 4: Click a different run of the same engine**

Click on a non-first run in the right-bottom list.
Expected:
- Right-top metrics swap to the clicked run.
- Left panel and runs list are unchanged.
- `●` stays on the same engine.

- [ ] **Step 5: Exercise buttons**

- Click `OPEN HTML` → `report.html` opens in the default browser. Close browser tab.
- Click `METRICS` → full-screen metrics dashboard opens. Press ESC → returns to BACKTEST tab with the same active engine and run.

- [ ] **Step 6: Exercise DELETE**

Click `DELETE` on a non-last run of the active engine → confirm dialog → yes.
Expected:
- Run disappears from the right-bottom list.
- Right-top metrics repopulate with the engine's new most-recent run.
- Header counter decrements by 1.

(Optional) Repeat until you delete the engine's last remaining run:
Expected:
- That engine disappears from the left panel entirely.
- `●` jumps to the next engine in the list; its metrics load.

- [ ] **Step 7: Keyboard refresh**

Press `R`.
Expected: tab re-renders without losing the active engine selection (active engine should persist across a refresh as long as it still has ≥1 run).

- [ ] **Step 8: Final smoke**

Close the launcher. Run: `python smoke_test.py --quiet`
Expected: all-green, same counts as baseline.

- [ ] **Step 9: Update session log**

Per `CLAUDE.md`, create `docs/sessions/YYYY-MM-DD_HHMM.md` and update/create `docs/days/YYYY-MM-DD.md` summarizing this work. Commit them alongside any visual-validation fixes:

```bash
git add docs/sessions/ docs/days/ launcher.py
git commit -m "docs(sessions): backtest panel hierarchy refactor"
```

---

## Rollback

Each task ends in its own commit. If Task 4 introduces a visible defect and a quick fix isn't obvious, `git revert <hash-of-task-4>` restores the flat-list UI without touching the helpers added in Tasks 1-3. Those stay dormant until re-wired.
