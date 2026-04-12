# Arbitrage Hub — HL2 + Bloomberg Minimalist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `_arbitrage_hub` in `launcher.py` as a clickable HL2 + Bloomberg minimalist hub — 3 big rows with hover highlight, live mini-data per row from the existing `FundingScanner`, and preserved keyboard shortcuts (C/D/X/arrows/Enter/Esc).

**Architecture:** Single-file change to `launcher.py`. Frame-based (not canvas) — 3 `tk.Frame` rows with child labels (bullet, label, right-meta, sub-line), each row bound to click + hover handlers. Replaces the current MP3-style cursor-row design. Removes the telemetry strip at top; its data now lives inside the row sub-lines. No backend changes — the existing `_arb_hub_scan_async` continues to drive live data.

**Tech Stack:** Python 3.14, Tkinter, stdlib only. Tests in `tests/test_launcher_main_menu.py` using the existing headless `App().withdraw()` pattern.

**Spec reference:** `docs/superpowers/specs/2026-04-12-arbitrage-hub-hl2-bloomberg-design.md`

---

## File Structure

| File | Role | Action |
|---|---|---|
| `launcher.py` | Rewrite `_arbitrage_hub` body; update `_arb_hub_repaint`, `_arb_hub_telem_update`; add `_arb_hub_hover_enter`, `_arb_hub_hover_leave`; store `_arb_hub_row_widgets` state | Modify |
| `tests/test_launcher_main_menu.py` | Append 4 new tests: rows render, pick dispatches, hover highlights, live data populates sub-lines | Modify |

Work happens inside a new worktree `.worktrees/arb-hub-hl2` on branch `feat/arb-hub-hl2` to keep `main` clean.

---

## Task 1: Worktree + rewrite `_arbitrage_hub` body (HL2 layout)

**Files:**
- Worktree: `.worktrees/arb-hub-hl2` (new)
- Modify: `launcher.py:3352-3442` (the entire `_arbitrage_hub` method body) and `launcher.py:3450-3460` (`_arb_hub_repaint` to work on the new row widgets)
- Modify: `tests/test_launcher_main_menu.py` (append 1 test)

### Step 1 — create worktree

Run from parent checkout:

```bash
git worktree add -b feat/arb-hub-hl2 .worktrees/arb-hub-hl2 HEAD
```

All subsequent steps run with `cd .worktrees/arb-hub-hl2`.

### Step 2 — append failing test

Append to `tests/test_launcher_main_menu.py`:

```python


def test_arbitrage_hub_renders_three_rows():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._arbitrage_hub()
        app.update_idletasks()
        assert hasattr(app, "_arb_hub_row_widgets")
        assert len(app._arb_hub_row_widgets) == 3
        for w in app._arb_hub_row_widgets:
            assert "frame" in w
            assert "bullet" in w
            assert "label" in w
            assert "meta" in w
            assert "sub" in w
    finally:
        app.destroy()
```

### Step 3 — run test, expect fail

```
python -m pytest tests/test_launcher_main_menu.py::test_arbitrage_hub_renders_three_rows -v
```

Expected: FAIL with `AttributeError: 'App' object has no attribute '_arb_hub_row_widgets'` (the current method uses `_arb_hub_rows` with different keys: `cursor`, `name`, `desc`).

### Step 4 — rewrite `_arbitrage_hub` body

Open `launcher.py` and find the `_arbitrage_hub` method (starts around line 3352). Replace the **entire method body** (from `def _arbitrage_hub(self):` up to but NOT including `def _arb_hub_move(self, delta: int):`) with:

```python
    def _arbitrage_hub(self):
        """HL2 + Bloomberg minimalist hub: 3 clickable rows with live data.

        Rows: CEX-CEX (Jane Street execution), DEX-DEX (scanner),
        CEX-DEX (scanner). Click or C/D/X keyboard shortcuts. Hover
        highlights the row. ESC returns to the main menu.
        """
        self._clr(); self._clear_kb()
        self.history.append("main")
        self.h_path.configure(text="> ARBITRAGE DESK")
        self.h_stat.configure(text="HUB", fg=AMBER_D)
        self.f_lbl.configure(
            text="click row  |  C D X direct  |  \u2191\u2193 ENTER  |  ESC back"
        )
        self._kb("<Escape>", lambda: self._menu("main"))
        self._bind_global_nav()

        outer = tk.Frame(self.main, bg=BG)
        outer.pack(fill="both", expand=True)

        # ── Header bar (minimal: section label + clock) ──
        header = tk.Frame(outer, bg=BG, height=40)
        header.pack(fill="x", padx=40, pady=(14, 0))
        header.pack_propagate(False)
        tk.Label(header, text="AURUM  \u00b7  ARBITRAGE DESK",
                 font=(FONT, 8), fg=DIM, bg=BG).pack(side="left")
        self._arb_hub_clock = tk.Label(header, text="",
                                        font=(FONT, 8, "bold"),
                                        fg=DIM, bg=BG)
        self._arb_hub_clock.pack(side="right")
        try:
            self._arb_hub_clock.configure(
                text=datetime.now().strftime("%H:%M:%S  UTC"))
        except Exception:
            pass

        # ── Title block ──
        title_frame = tk.Frame(outer, bg=BG)
        title_frame.pack(fill="x", pady=(40, 0))
        tk.Label(title_frame, text="A R B I T R A G E",
                 font=(FONT, 18, "bold"), fg=AMBER, bg=BG).pack()
        tk.Frame(title_frame, bg=AMBER_D, height=1, width=220).pack(pady=(4, 4))
        tk.Label(title_frame, text="funding  \u00b7  basis  \u00b7  spread",
                 font=(FONT, 8), fg=DIM, bg=BG).pack()

        # ── Rows area ──
        rows_frame = tk.Frame(outer, bg=BG)
        rows_frame.pack(fill="x", pady=(48, 0), padx=80)

        self._arb_hub_idx = 0
        self._arb_hub_row_widgets: list[dict] = []

        # Row definitions — match self._ARB_HUB_ITEMS order
        row_defs = [
            ("CEX  \u2194  CEX", "JANE ST",    "execution  \u00b7  \u2014"),
            ("DEX  \u2194  DEX", "\u2014 VENUES", "observation  \u00b7  \u2014"),
            ("CEX  \u2194  DEX", "\u2014 VENUES", "observation  \u00b7  \u2014"),
        ]

        for i, (big_label, meta, sub) in enumerate(row_defs):
            row_frame = tk.Frame(rows_frame, bg=BG, cursor="hand2", height=78)
            row_frame.pack(fill="x", pady=(0, 10))
            row_frame.pack_propagate(False)

            top_line = tk.Frame(row_frame, bg=BG)
            top_line.pack(fill="x", pady=(10, 0))

            bullet_lbl = tk.Label(top_line, text="\u25cf",
                                  font=(FONT, 14, "bold"),
                                  fg=AMBER, bg=BG, width=3, anchor="center")
            bullet_lbl.pack(side="left")

            label_lbl = tk.Label(top_line, text=big_label,
                                 font=(FONT, 14, "bold"),
                                 fg=WHITE, bg=BG, anchor="w")
            label_lbl.pack(side="left", padx=(4, 0))

            meta_lbl = tk.Label(top_line, text=meta,
                                font=(FONT, 10, "bold"),
                                fg=AMBER, bg=BG, anchor="e")
            meta_lbl.pack(side="right", padx=(0, 12))

            sub_lbl = tk.Label(row_frame, text=sub,
                               font=(FONT, 8), fg=DIM, bg=BG, anchor="w")
            sub_lbl.pack(fill="x", padx=(48, 12), pady=(6, 0))

            widgets = {
                "frame":  row_frame,
                "top":    top_line,
                "bullet": bullet_lbl,
                "label":  label_lbl,
                "meta":   meta_lbl,
                "sub":    sub_lbl,
            }
            self._arb_hub_row_widgets.append(widgets)

            # Bind hover + click on frame AND all child labels
            targets = (row_frame, top_line, bullet_lbl, label_lbl, meta_lbl, sub_lbl)
            for t in targets:
                t.bind("<Enter>",    lambda _e, _i=i: self._arb_hub_hover_enter(_i))
                t.bind("<Leave>",    lambda _e, _i=i: self._arb_hub_hover_leave(_i))
                t.bind("<Button-1>", lambda _e, _i=i: self._arb_hub_pick(_i))

        # ── Keyboard shortcuts (preserved) ──
        self._kb("<Key-c>", lambda: self._arb_hub_pick(0))
        self._kb("<Key-d>", lambda: self._arb_hub_pick(1))
        self._kb("<Key-x>", lambda: self._arb_hub_pick(2))
        self._kb("<Up>",    lambda: self._arb_hub_move(-1))
        self._kb("<Down>",  lambda: self._arb_hub_move(1))
        self._kb("<Return>", lambda: self._arb_hub_pick(self._arb_hub_idx))
        self._kb("<space>",  lambda: self._arb_hub_pick(self._arb_hub_idx))

        self._arb_hub_repaint()

        # ── Footer hint ──
        footer = tk.Frame(outer, bg=BG)
        footer.pack(fill="x", pady=(24, 0))
        tk.Frame(footer, bg=AMBER_D, height=1, width=220).pack()
        tk.Label(footer,
                 text="click row  \u00b7  C  D  X  direct  \u00b7  ESC back",
                 font=(FONT, 7), fg=DIM2, bg=BG).pack(pady=(6, 0))

        # ── Kick off async scan for live data ──
        self._arb_hub_scan_async()
```

Now also update the existing `_arb_hub_repaint` method to work on the new `_arb_hub_row_widgets` structure. Find `_arb_hub_repaint` (around line 3450) and replace its body with:

```python
    def _arb_hub_repaint(self):
        """Repaint all 3 rows based on self._arb_hub_idx (keyboard cursor)."""
        rows = getattr(self, "_arb_hub_row_widgets", None) or []
        for i, w in enumerate(rows):
            if i == self._arb_hub_idx:
                w["frame"].configure(bg=BG3)
                w["top"].configure(bg=BG3)
                w["bullet"].configure(fg=AMBER_B, bg=BG3)
                w["label"].configure(fg=AMBER, bg=BG3)
                w["meta"].configure(fg=AMBER_B, bg=BG3)
                w["sub"].configure(fg=AMBER_D, bg=BG3)
            else:
                w["frame"].configure(bg=BG)
                w["top"].configure(bg=BG)
                w["bullet"].configure(fg=AMBER, bg=BG)
                w["label"].configure(fg=WHITE, bg=BG)
                w["meta"].configure(fg=AMBER, bg=BG)
                w["sub"].configure(fg=DIM, bg=BG)
```

`_arb_hub_move`, `_arb_hub_pick`, and `_arb_hub_scan_async` stay exactly as they are. `_arb_hub_telem_update` will be rewritten in Task 3.

### Step 5 — add stub methods `_arb_hub_hover_enter` / `_arb_hub_hover_leave`

Insert these two new methods immediately after `_arb_hub_repaint` and before `_arb_hub_pick`:

```python
    def _arb_hub_hover_enter(self, idx: int) -> None:
        """Mouse hover enters row idx — same visual as keyboard focus."""
        if not (0 <= idx < len(getattr(self, "_arb_hub_row_widgets", []))):
            return
        self._arb_hub_idx = idx
        self._arb_hub_repaint()

    def _arb_hub_hover_leave(self, idx: int) -> None:
        """Mouse hover leaves row idx — no-op for now; repaint is idempotent."""
        # Keeping the cursor on the last-hovered row feels natural — same as
        # Bloomberg terminal. If the user moves to another row, enter fires
        # there and repaints. No explicit cleanup needed.
        pass
```

### Step 6 — run test, expect pass

```
python -m pytest tests/test_launcher_main_menu.py::test_arbitrage_hub_renders_three_rows -v
```

Expected: PASS.

### Step 7 — run full test suite

```
python -m pytest tests/test_launcher_main_menu.py -v
```

Expected: all existing tests still pass; +1 new test (modulo the known Tcl `msgcat` flake on Windows, which is environmental).

### Step 8 — smoke test

```
python smoke_test.py --quiet
```

Expected: exit 0, no FAILs. The existing smoke call `call("_arbitrage_hub", app._arbitrage_hub)` — if absent, see Step 9 of Task 4.

### Step 9 — AST parse sanity

```
python -c "import ast; ast.parse(open('launcher.py', encoding='utf-8').read())"
```

Expected: no output.

### Step 10 — commit

```
git add launcher.py tests/test_launcher_main_menu.py
git commit -m "feat(launcher): HL2 Bloomberg arbitrage hub — 3 clickable rows"
```

---

## Task 2: Click dispatch test + `_arb_hub_pick` monkey-patch verification

**Files:**
- Modify: `tests/test_launcher_main_menu.py` (append 1 test)

This task is purely a test. No production code changes — `_arb_hub_pick` already exists and already dispatches via `getattr`. We verify it still works with the new row structure and click bindings.

### Step 1 — append failing test

```python


def test_arbitrage_hub_pick_dispatches_to_alchemy(monkeypatch):
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._arbitrage_hub()
        called = []
        monkeypatch.setattr(app, "_alchemy_enter",
                            lambda: called.append("alchemy"))
        app._arb_hub_pick(0)  # row 0 = CEX-CEX → _alchemy_enter
        assert called == ["alchemy"]
    finally:
        app.destroy()
```

### Step 2 — run, expect pass

```
python -m pytest tests/test_launcher_main_menu.py::test_arbitrage_hub_pick_dispatches_to_alchemy -v
```

Expected: PASS immediately — `_arb_hub_pick` is unchanged from the original implementation and still dispatches via `_ARB_HUB_ITEMS[0][3]` which is the string `"_alchemy_enter"`.

If it FAILS with "called != [alchemy]", check that `_ARB_HUB_ITEMS[0]` still points to `_alchemy_enter` (it should; we didn't touch the constant).

### Step 3 — commit

```
git add tests/test_launcher_main_menu.py
git commit -m "test(launcher): arbitrage hub pick dispatches to _alchemy_enter"
```

---

## Task 3: Rewrite `_arb_hub_telem_update` to populate sub-lines with live data

**Files:**
- Modify: `launcher.py:3508-3537` (the existing `_arb_hub_telem_update` method)
- Modify: `tests/test_launcher_main_menu.py` (append 1 test)

### Step 1 — append failing test

```python


def test_arbitrage_hub_telem_update_populates_sub_lines():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._arbitrage_hub()
        # Synthetic scan result
        class FakeTop:
            symbol = "BTC"
            apr = 42.3
            venue = "binance"
        stats = {"dex_online": 3, "cex_online": 5, "total": 1042}
        top = FakeTop()
        arb_dd = [{"symbol": "ETH", "net_apr": 18.7, "short_venue": "dydx", "long_venue": "hyperliquid"}]
        arb_cd = [{"symbol": "SOL", "net_apr": 95.2, "short_venue": "bybit", "long_venue": "paradex"}]
        app._arb_hub_telem_update(stats, top, arb_dd, arb_cd)
        app.update_idletasks()

        rows = app._arb_hub_row_widgets
        # Row 0 = CEX-CEX — meta stays "JANE ST", sub shows execution + top
        assert "JANE ST" in rows[0]["meta"].cget("text")
        # Row 1 = DEX-DEX — meta shows venue count
        assert "3" in rows[1]["meta"].cget("text")
        # Row 2 = CEX-DEX — meta shows total venues
        assert "8" in rows[2]["meta"].cget("text")
        # Sub-lines updated with best APR
        assert "18" in rows[1]["sub"].cget("text") or "19" in rows[1]["sub"].cget("text")
        assert "95" in rows[2]["sub"].cget("text") or "96" in rows[2]["sub"].cget("text")
    finally:
        app.destroy()
```

### Step 2 — run, expect fail

```
python -m pytest tests/test_launcher_main_menu.py::test_arbitrage_hub_telem_update_populates_sub_lines -v
```

Expected: FAIL — the current `_arb_hub_telem_update` writes to `self._arb_hub_telem` (a label that no longer exists after Task 1's rewrite), so the assertions never match.

### Step 3 — rewrite `_arb_hub_telem_update`

Open `launcher.py`, find `_arb_hub_telem_update` (around line 3508). Replace its entire body with:

```python
    def _arb_hub_telem_update(self, stats, top, arb_dd, arb_cd):
        """Populate the 3 hub rows with live data from the scanner.

        stats: dict with dex_online, cex_online, total from FundingScanner.stats()
        top:   FundingOpp or None — single best observation across all venues
        arb_dd: list of dex-dex spread pairs from scanner.arb_pairs("dex-dex")
        arb_cd: list of cex-dex spread pairs from scanner.arb_pairs("cex-dex")
        """
        rows = getattr(self, "_arb_hub_row_widgets", None)
        if not rows:
            return
        try:
            dex_on = stats.get("dex_online", 0)
            cex_on = stats.get("cex_online", 0)

            # Row 0 — CEX ↔ CEX (Jane Street execution)
            top_s = "\u2014"
            if top is not None and getattr(top, "apr", None) is not None:
                try:
                    top_s = f"top {float(top.apr):+.1f}%"
                except Exception:
                    top_s = "\u2014"
            rows[0]["meta"].configure(text="JANE ST")
            rows[0]["sub"].configure(
                text=f"execution  \u00b7  {top_s}  \u00b7  24 pairs")

            # Row 1 — DEX ↔ DEX
            rows[1]["meta"].configure(text=f"{dex_on} VENUES")
            if arb_dd:
                a = arb_dd[0]
                try:
                    best_s = f"best {float(a.get('net_apr', 0)):+.1f}%"
                    venue_s = str(a.get("long_venue") or a.get("short_venue") or "\u2014")
                except Exception:
                    best_s = "\u2014"
                    venue_s = "\u2014"
                rows[1]["sub"].configure(
                    text=f"observation  \u00b7  {best_s}  \u00b7  {venue_s}")
            else:
                rows[1]["sub"].configure(
                    text="observation  \u00b7  \u2014  \u00b7  \u2014")

            # Row 2 — CEX ↔ DEX
            rows[2]["meta"].configure(text=f"{dex_on + cex_on} VENUES")
            if arb_cd:
                a = arb_cd[0]
                try:
                    best_s = f"best {float(a.get('net_apr', 0)):+.1f}%"
                    venue_s = str(a.get("long_venue") or a.get("short_venue") or "\u2014")
                except Exception:
                    best_s = "\u2014"
                    venue_s = "\u2014"
                rows[2]["sub"].configure(
                    text=f"observation  \u00b7  {best_s}  \u00b7  {venue_s}")
            else:
                rows[2]["sub"].configure(
                    text="observation  \u00b7  \u2014  \u00b7  \u2014")
        except Exception:
            pass
```

### Step 4 — also fix the scanner failure path in `_arb_hub_scan_async`

The current `_arb_hub_scan_async` has a failure path (line ~3484 and ~3503) that writes to `self._arb_hub_telem` (the label that no longer exists). This will AttributeError or NameError at runtime if the scanner fails. Fix it by routing failures through a row-agnostic helper that either writes to the first row's sub-line or silently logs.

Find these two lines in `_arb_hub_scan_async`:

```python
            self._arb_hub_telem.configure(
                text=f"  scanner unavailable: {e}  ", fg=RED)
```

and

```python
                self.after(0, lambda: self._arb_hub_telem.configure(
                    text=f"  scan failed: {e}  ", fg=RED))
```

Replace the first with:

```python
            rows = getattr(self, "_arb_hub_row_widgets", None)
            if rows:
                rows[0]["sub"].configure(
                    text=f"scanner unavailable: {str(e)[:40]}", fg=RED)
            return
```

Replace the second with:

```python
                def _fail(err=e):
                    rs = getattr(self, "_arb_hub_row_widgets", None)
                    if rs:
                        try:
                            rs[0]["sub"].configure(
                                text=f"scan failed: {str(err)[:40]}", fg=RED)
                        except Exception:
                            pass
                self.after(0, _fail)
```

### Step 5 — run tests, expect pass

```
python -m pytest tests/test_launcher_main_menu.py -v
```

Expected: all pass (modulo known flake).

### Step 6 — smoke test

```
python smoke_test.py --quiet
```

Expected: exit 0.

### Step 7 — commit

```
git add launcher.py tests/test_launcher_main_menu.py
git commit -m "feat(launcher): arb hub telem update populates row sub-lines"
```

---

## Task 4: Hover bind verification test

**Files:**
- Modify: `tests/test_launcher_main_menu.py`

### Step 1 — append test

```python


def test_arbitrage_hub_hover_enter_moves_cursor():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._arbitrage_hub()
        app.update_idletasks()
        # Initial cursor at 0
        assert app._arb_hub_idx == 0
        # Simulate hover on row 2
        app._arb_hub_hover_enter(2)
        app.update_idletasks()
        assert app._arb_hub_idx == 2
        # Row 2 label should be AMBER (focused)
        assert app._arb_hub_row_widgets[2]["label"].cget("fg") == AMBER
        # Row 0 label should be WHITE (idle)
        assert app._arb_hub_row_widgets[0]["label"].cget("fg") == WHITE
    finally:
        app.destroy()
```

Note: `AMBER` and `WHITE` are module-level constants in `launcher.py`. Import them at the top of the test file if not already imported. Check the existing test file — it already uses `_load_launcher()` which returns the module; access via `mod.AMBER` and `mod.WHITE` instead:

```python
def test_arbitrage_hub_hover_enter_moves_cursor():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._arbitrage_hub()
        app.update_idletasks()
        assert app._arb_hub_idx == 0
        app._arb_hub_hover_enter(2)
        app.update_idletasks()
        assert app._arb_hub_idx == 2
        assert app._arb_hub_row_widgets[2]["label"].cget("fg") == mod.AMBER
        assert app._arb_hub_row_widgets[0]["label"].cget("fg") == mod.WHITE
    finally:
        app.destroy()
```

### Step 2 — run test, expect pass

```
python -m pytest tests/test_launcher_main_menu.py::test_arbitrage_hub_hover_enter_moves_cursor -v
```

Expected: PASS — `_arb_hub_hover_enter` was added in Task 1 and `_arb_hub_repaint` (also updated in Task 1) handles the AMBER/WHITE swap.

If it FAILS, inspect `_arb_hub_repaint` — the idle branch must set `label` fg to `WHITE` and the focused branch must set it to `AMBER`.

### Step 3 — commit

```
git add tests/test_launcher_main_menu.py
git commit -m "test(launcher): arb hub hover enter moves cursor + repaints"
```

---

## Task 5: Final validation + session log + merge

**Files:**
- Create: `docs/sessions/2026-04-12_HHMM.md`
- Main branch: fast-forward merge of `feat/arb-hub-hl2`

### Step 1 — run full pytest

```
python -m pytest tests/test_launcher_main_menu.py -v
```

Expected: all tests green except the known Tcl `msgcat` flake on Windows (environmental).

### Step 2 — run smoke test

```
python smoke_test.py --quiet
```

Expected: exit 0. Current baseline 164/164 in worktree.

### Step 3 — manual UI walkthrough

Run `python launcher.py` and verify:

1. Splash → click → main menu → select ARBITRAGE → hub appears.
2. Header shows `AURUM · ARBITRAGE DESK` left and UTC clock right.
3. Big title `A R B I T R A G E` centered with thin rule and subtitle `funding · basis · spread`.
4. 3 rows each with: `●` bullet, big label (`CEX ↔ CEX`, `DEX ↔ DEX`, `CEX ↔ DEX`), right-aligned meta (`JANE ST`, `— VENUES`, `— VENUES`), sub-line with mode.
5. Within 2-5 seconds, rows populate with live data (e.g., `3 VENUES`, `observation · best +45.2% · dydx`).
6. Hover row 2 with mouse → row highlights (bg BG3, label AMBER, bullet AMBER_B, sub AMBER_D).
7. Leave row 2 → highlight stays (cursor-follows-hover behavior — confirmed by spec).
8. Click row 1 → Jane Street cockpit opens.
9. ESC → hub returns.
10. Tecla `d` → DEX scanner opens.
11. ESC → hub.
12. Tecla `x` → CEX-DEX scanner opens.
13. ESC → hub.
14. Setas ↓↑ → move cursor keyboard between rows.
15. ENTER → picks highlighted row.
16. ESC no hub → volta pro main menu.

If any step fails visually, stop and fix.

### Step 4 — write session log

Create `docs/sessions/2026-04-12_HHMM.md` where `HHMM` is the UTC timestamp at commit time (use `date -u +"%Y-%m-%d_%H%M"`). Follow the CLAUDE.md session log template precisely. Highlight:
- Fase A of the arbitrage redesign (hub polish only).
- Zero backend changes.
- Zero trading logic changes.
- All keybinds preserved.
- Click + hover interaction added.
- Telemetry strip removed; live data now in-row.
- Phases B–E (filters, new venues, new arb types, real-ops) remain in backlog for future specs.

Commit:

```
git add docs/sessions/2026-04-12_*.md
git commit -m "docs(sessions): arbitrage hub HL2 Bloomberg redesign — session log"
```

### Step 5 — merge to main

From the parent checkout at `C:/Users/Joao/OneDrive/aurum.finance`:

```
git merge --ff-only feat/arb-hub-hl2
python smoke_test.py --quiet
```

Expected: fast-forward succeeds; smoke on main exits 0.

### Step 6 — cleanup

```
git branch -D feat/arb-hub-hl2
git worktree prune
```

Note: OneDrive Windows file-lock may leave residual directories in `.worktrees/arb-hub-hl2` after the branch is deleted. That's inert and gitignored — ignore it.

---

## Verification Checklist

- [ ] `python -m pytest tests/test_launcher_main_menu.py` — all tests pass (modulo Tcl msgcat flake)
- [ ] `python smoke_test.py --quiet` — exit 0
- [ ] Manual UI walkthrough (16 steps) completed
- [ ] Hub renders with header + title + 3 rows + footer (HL2 minimalist)
- [ ] Clicking a row opens the correct destination (alchemy / dex-dex / cex-dex)
- [ ] Hover highlights the row (bg BG3, label AMBER)
- [ ] Keyboard shortcuts C/D/X/arrows/Enter/Esc still work
- [ ] Live data appears in row sub-lines within ~5s
- [ ] No modifications to `core/funding_scanner.py`, `engines/arbitrage.py`, or any backend
- [ ] Session log written per CLAUDE.md rules
- [ ] Fast-forward merge to main succeeds
