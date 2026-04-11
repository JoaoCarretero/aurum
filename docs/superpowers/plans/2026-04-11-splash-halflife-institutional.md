# Splash HL1 Black Mesa Institutional Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `_splash` in `launcher.py` as an atmospheric Half Life 1 / Black Mesa institutional gate — warning stripes, small CD top-left, AURUM wordmark, CRT-style status block, pulsing `CLICK TO PROCEED` cursor — where click/ENTER/space always routes to the main menu (Fibonacci legacy).

**Architecture:** Single-file change to `launcher.py`. All drawing on one 920×640 `tk.Canvas`. Reuses existing `_draw_cd_center` helper (extended with an optional `r` radius param). New private helpers `_draw_warning_stripe`, `_draw_stamp`, `_draw_status_block`, plus `_splash_pulse_tick` for the 500ms cursor blink. All navigation keybinds except ENTER/space/Q are unbound on the splash — it is a gate, not a hub.

**Tech Stack:** Python 3.14, Tkinter, stdlib only. Tests use pytest via the existing `tests/test_launcher_main_menu.py` loader pattern. No new dependencies.

**Spec reference:** `docs/superpowers/specs/2026-04-11-splash-halflife-institutional-design.md`

---

## File Structure

| File | Role | Action |
|---|---|---|
| `launcher.py` | Rewrite `_splash` body; extend `_draw_cd_center` with `r` param; add `_draw_warning_stripe`, `_draw_stamp`, `_draw_status_block`, `_splash_pulse_tick`; add state fields in `__init__` | Modify |
| `tests/test_launcher_main_menu.py` | Drop `test_splash_key_1_dispatches_to_markets` (obsolete); rename+relax `test_splash_creates_bloomberg_canvas`; add 3 new tests for canvas, click routing, pulse cleanup | Modify |
| `smoke_test.py` | Existing `_splash` call already covers it — verify it still passes | Verify only |

All work happens inside a new worktree `.worktrees/splash-halflife` on branch `feat/splash-halflife` to keep main clean.

---

## Task 1: Worktree setup + extend `_draw_cd_center` with optional radius

**Files:**
- Worktree: `.worktrees/splash-halflife` (new)
- Modify: `launcher.py` — `_draw_cd_center` method (currently does not accept `r` parameter)
- Modify: `tests/test_launcher_main_menu.py` (append 1 test)

### Step 1 — Create the worktree

Run (from main checkout):

```bash
git worktree add -b feat/splash-halflife .worktrees/splash-halflife HEAD
```

All subsequent steps run with `cd .worktrees/splash-halflife`.

### Step 2 — Write the failing test

Append to `tests/test_launcher_main_menu.py`:

```python


def test_draw_cd_center_accepts_radius_override():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        # Create a standalone canvas and verify _draw_cd_center accepts r=
        import tkinter as tk
        canvas = tk.Canvas(app, width=200, height=200, bg="#0a0a0a")
        # Set the active center so the helper has a target
        app._active_cd_center = (100, 100)
        app._draw_cd_center(canvas, r=36)
        canvas.update_idletasks()
        # The outer oval should live inside the 200×200 canvas
        items = canvas.find_all()
        assert len(items) >= 5, f"expected CD primitives, got {len(items)}"
        canvas.destroy()
    finally:
        app.destroy()
```

### Step 3 — Run the test, expect failure

```
python -m pytest tests/test_launcher_main_menu.py::test_draw_cd_center_accepts_radius_override -v
```

Expected: FAIL with `TypeError: _draw_cd_center() got an unexpected keyword argument 'r'`.

### Step 4 — Add the `r=None` parameter to `_draw_cd_center`

Open `launcher.py` and find the `_draw_cd_center` method. Its current signature is:

```python
    def _draw_cd_center(self, canvas) -> None:
```

Its body uses `cx, cy = self._active_cd_center` (or the class default `self._CD_CX, self._CD_CY`) and `r = self._CD_R`. Change the signature and the first lines of the body:

```python
    def _draw_cd_center(self, canvas, r=None) -> None:
        cx, cy = getattr(self, "_active_cd_center", (self._CD_CX, self._CD_CY))
        if r is None:
            r = self._CD_R
```

Everything else in the method stays exactly the same. Specifically, the rotation angle, the arcs, the inner hole, the labels — all untouched. Only the two lines that resolve `cx, cy, r` change.

### Step 5 — Run the test, expect pass

```
python -m pytest tests/test_launcher_main_menu.py::test_draw_cd_center_accepts_radius_override -v
```

Expected: PASS.

### Step 6 — Run the full test suite to ensure no regression

```
python -m pytest tests/test_launcher_main_menu.py -v
```

Expected: same pass count as before plus 1 new (the existing test flake on Tcl `msgcat` is environmental and unrelated — any pre-existing flaky test behavior stays pre-existing).

### Step 7 — Smoke test

```
python smoke_test.py --quiet
```

Expected: exit 0, no regression (currently 164/164).

### Step 8 — Commit

```
git add launcher.py tests/test_launcher_main_menu.py
git commit -m "feat(launcher): _draw_cd_center accepts optional radius override"
```

---

## Task 2: Add splash state fields to `App.__init__`

**Files:**
- Modify: `launcher.py` — `App.__init__`
- Modify: `tests/test_launcher_main_menu.py`

### Step 1 — Write the failing test

Append to `tests/test_launcher_main_menu.py`:

```python


def test_app_has_splash_pulse_state():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        assert hasattr(app, "_splash_cursor_on")
        assert isinstance(app._splash_cursor_on, bool)
        assert hasattr(app, "_splash_pulse_after_id")
        assert app._splash_pulse_after_id is None
        assert hasattr(app, "_splash_canvas")
        assert app._splash_canvas is None
    finally:
        app.destroy()
```

### Step 2 — Run, expect fail

```
python -m pytest tests/test_launcher_main_menu.py::test_app_has_splash_pulse_state -v
```

Expected: FAIL with `AttributeError: '_splash_cursor_on'`.

### Step 3 — Add the state fields

Open `launcher.py`, find `App.__init__`, and locate the Bloomberg 3D menu state block (added in a previous task — look for the comment `# ─── Bloomberg 3D main menu state ────────────────`). Immediately after that block, insert:

```python

        # ─── Splash HL1 gate state ────────────────────────
        self._splash_cursor_on = True
        self._splash_pulse_after_id = None
        self._splash_canvas = None
```

### Step 4 — Run, expect pass

```
python -m pytest tests/test_launcher_main_menu.py::test_app_has_splash_pulse_state -v
```

Expected: PASS.

### Step 5 — Commit

```
git add launcher.py tests/test_launcher_main_menu.py
git commit -m "feat(launcher): init splash HL1 pulse state in App"
```

---

## Task 3: Add `_draw_warning_stripe` helper

**Files:**
- Modify: `launcher.py` — add method near the other `_draw_*` helpers
- Modify: `tests/test_launcher_main_menu.py`

### Step 1 — Write the failing test

```python


def test_draw_warning_stripe_creates_rect_and_text():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        import tkinter as tk
        canvas = tk.Canvas(app, width=920, height=640, bg="#0a0a0a")
        app._draw_warning_stripe(canvas, y=0, height=20, text="TEST WARNING")
        canvas.update_idletasks()
        items = canvas.find_all()
        # One rectangle + one text = at least 2 items
        assert len(items) >= 2, f"expected >=2 items, got {len(items)}"
        canvas.destroy()
    finally:
        app.destroy()
```

### Step 2 — Run, expect fail

```
python -m pytest tests/test_launcher_main_menu.py::test_draw_warning_stripe_creates_rect_and_text -v
```

Expected: FAIL — `AttributeError: '_draw_warning_stripe'`.

### Step 3 — Add the helper

In `launcher.py`, find the existing `_draw_cd_center` method (already modified in Task 1). Immediately after it, add:

```python
    def _draw_warning_stripe(self, canvas, y: int, height: int, text: str) -> None:
        """Solid yellow bar with dark text — HL1 hazard stripe."""
        w = 920
        canvas.create_rectangle(0, y, w, y + height, fill="#ffd700",
                                outline="#ffd700", tags="warning")
        canvas.create_text(w // 2, y + height // 2,
                           text=text, font=(FONT, 7, "bold"),
                           fill="#1a1a00", tags="warning")
```

### Step 4 — Run, expect pass

```
python -m pytest tests/test_launcher_main_menu.py::test_draw_warning_stripe_creates_rect_and_text -v
```

Expected: PASS.

### Step 5 — Commit

```
git add launcher.py tests/test_launcher_main_menu.py
git commit -m "feat(launcher): _draw_warning_stripe helper for HL1 splash"
```

---

## Task 4: Add `_draw_stamp` helper

**Files:**
- Modify: `launcher.py`
- Modify: `tests/test_launcher_main_menu.py`

### Step 1 — Write the failing test

```python


def test_draw_stamp_creates_border_and_text():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        import tkinter as tk
        canvas = tk.Canvas(app, width=920, height=640, bg="#0a0a0a")
        app._draw_stamp(canvas, cx=300, cy=100, w=100, h=50,
                        lines=["VAULT", "03"])
        canvas.update_idletasks()
        items = canvas.find_all()
        # 1 border + N text lines = >= 3 items (for 2 lines)
        assert len(items) >= 3, f"expected >=3 items, got {len(items)}"
        canvas.destroy()
    finally:
        app.destroy()
```

### Step 2 — Run, expect fail

```
python -m pytest tests/test_launcher_main_menu.py::test_draw_stamp_creates_border_and_text -v
```

Expected: FAIL — `AttributeError: '_draw_stamp'`.

### Step 3 — Add the helper

In `launcher.py`, directly after `_draw_warning_stripe` (added in Task 3), add:

```python
    def _draw_stamp(self, canvas, cx: int, cy: int, w: int, h: int, lines: list) -> None:
        """Dashed rectangular stamp with N centered text lines — HL1 clearance tags."""
        x1, y1 = cx - w // 2, cy - h // 2
        x2, y2 = cx + w // 2, cy + h // 2
        canvas.create_rectangle(x1, y1, x2, y2,
                                outline=AMBER, width=1,
                                dash=(2, 3), tags="stamp")
        n = len(lines)
        if n == 0:
            return
        line_h = h // (n + 1)
        for i, line in enumerate(lines):
            canvas.create_text(cx, y1 + line_h * (i + 1),
                               text=line, font=(FONT, 8, "bold"),
                               fill=AMBER, tags="stamp")
```

### Step 4 — Run, expect pass

```
python -m pytest tests/test_launcher_main_menu.py::test_draw_stamp_creates_border_and_text -v
```

Expected: PASS.

### Step 5 — Commit

```
git add launcher.py tests/test_launcher_main_menu.py
git commit -m "feat(launcher): _draw_stamp helper for HL1 clearance stamps"
```

---

## Task 5: Add `_draw_status_block` helper

**Files:**
- Modify: `launcher.py`
- Modify: `tests/test_launcher_main_menu.py`

### Step 1 — Write the failing test

```python


def test_draw_status_block_creates_rows():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        import tkinter as tk
        canvas = tk.Canvas(app, width=920, height=640, bg="#0a0a0a")
        rows = [
            ("SYSTEM STATUS", "NOMINAL", "#00c864"),
            ("KILL-SWITCH",   "ARMED [3/3]", "#c83232"),
        ]
        app._draw_status_block(canvas, x=220, y=320, rows=rows)
        canvas.update_idletasks()
        items = canvas.find_all()
        # One text item per row
        assert len(items) >= len(rows)
        canvas.destroy()
    finally:
        app.destroy()
```

### Step 2 — Run, expect fail

```
python -m pytest tests/test_launcher_main_menu.py::test_draw_status_block_creates_rows -v
```

Expected: FAIL — `AttributeError: '_draw_status_block'`.

### Step 3 — Add the helper

In `launcher.py`, directly after `_draw_stamp`, add:

```python
    def _draw_status_block(self, canvas, x: int, y: int, rows: list) -> None:
        """CRT-style status rows: '> LABEL .......... VALUE' with per-row color.

        rows is a list of (label, value, color_hex) tuples. Dots fill the
        gap between label and value to a fixed column width so the values
        align vertically.
        """
        total_width = 48  # total chars including prompt + dots + value
        line_step = 18
        for i, (label, value, color) in enumerate(rows):
            prefix = f"> {label} "
            value_str = f" {value}"
            dots = "." * max(2, total_width - len(prefix) - len(value_str))
            text = f"{prefix}{dots}{value_str}"
            canvas.create_text(x, y + i * line_step, anchor="w",
                               text=text, font=(FONT, 9),
                               fill=color, tags="status")
```

### Step 4 — Run, expect pass

```
python -m pytest tests/test_launcher_main_menu.py::test_draw_status_block_creates_rows -v
```

Expected: PASS.

### Step 5 — Commit

```
git add launcher.py tests/test_launcher_main_menu.py
git commit -m "feat(launcher): _draw_status_block helper for HL1 CRT rows"
```

---

## Task 6: Rewrite `_splash` body

**Files:**
- Modify: `launcher.py` — `_splash` method (the current Bloomberg 3D version)
- Modify: `tests/test_launcher_main_menu.py`

This task is the biggest. It replaces the entire body of `_splash` with the HL1 Black Mesa version described in the spec.

### Step 1 — Write 2 failing tests

Remove (delete lines entirely) the current test `test_splash_key_1_dispatches_to_markets` from `tests/test_launcher_main_menu.py` — this behavior no longer exists. Then modify the existing `test_splash_creates_bloomberg_canvas` test: rename it to `test_splash_creates_canvas` and relax the item count from `> 20` to `> 15`. The new body:

```python
def test_splash_creates_canvas():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._splash()
        app.update_idletasks()
        assert app._menu_canvas is not None
        items = app._menu_canvas.find_all()
        assert len(items) > 15, f"expected >15 items on splash, got {len(items)}"
    finally:
        app.destroy()
```

Append a new test for click routing:

```python


def test_splash_click_routes_to_main(monkeypatch):
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._splash()
        called = []
        monkeypatch.setattr(app, "_menu", lambda key: called.append(key))
        # Simulate the click handler registered on self.main
        # The splash v2 binds <Button-1> on self.main — invoke it directly
        app._splash_on_click()
        assert called == ["main"]
    finally:
        app.destroy()
```

`_splash_on_click` is a new helper method we add in step 3 — it's trivially a lambda `lambda: self._menu("main")` wrapped in a named method so the test can call it without synthesizing a Tk event.

Append a third test for the pulse cleanup:

```python


def test_splash_pulse_disarms_on_menu_switch(monkeypatch):
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._splash()
        # After _splash, pulse should be armed
        assert app._splash_pulse_after_id is not None
        # When we switch away (simulate by tearing down _splash_canvas)
        app._splash_canvas = None
        # The next pulse tick should self-disarm without raising
        app._splash_pulse_tick()
        assert app._splash_pulse_after_id is None
    finally:
        app.destroy()
```

### Step 2 — Run all three tests, expect fails

```
python -m pytest tests/test_launcher_main_menu.py -v -k "splash_creates_canvas or splash_click or splash_pulse"
```

Expected: 3 FAILs (the rename/rewrite of the first means the new name doesn't exist yet; the other two reference methods that don't exist yet).

### Step 3 — Rewrite `_splash` body

Locate the current `_splash` method in `launcher.py`. Replace the **entire method** (from `def _splash(self):` down to the last line before the next `def`) with:

```python
    def _splash(self):
        """Half Life 1 institutional gate splash.

        Click anywhere / ENTER / space → main menu. Arrow keys unbound.
        CD small top-left, AURUM wordmark centered, CRT status block,
        pulsing CLICK TO PROCEED cursor. Warning stripes top and bottom.
        """
        self._clr()
        self._clear_kb()
        self.history.clear()
        self.h_path.configure(text="")
        self.h_stat.configure(text="PRONTO", fg=GREEN)
        self.f_lbl.configure(text="CLICK · ENTER · Q quit")

        f = tk.Frame(self.main, bg=BG)
        f.pack(fill="both", expand=True)
        canvas = tk.Canvas(f, bg=BG, highlightthickness=0, width=920, height=640)
        canvas.pack(fill="both", expand=True)
        self._menu_canvas = canvas
        self._splash_canvas = canvas

        # ── Warning stripes ──
        self._draw_warning_stripe(canvas, y=0,   height=20,
                                  text="▓▒░  ⚠ AUTHORIZED ACCESS ONLY ⚠  ░▒▓")
        self._draw_warning_stripe(canvas, y=618, height=22,
                                  text="▓▒░  © 2026 AURUM · O DISCO LÊ A SI MESMO  ░▒▓")

        # ── Small CD top-left ──
        self._active_cd_center = (70, 100)
        self._draw_cd_center(canvas, r=36)

        # ── Clearance stamps top-right ──
        self._draw_stamp(canvas, cx=680, cy=100, w=110, h=56,
                         lines=["VAULT", "03"])
        self._draw_stamp(canvas, cx=810, cy=100, w=130, h=56,
                         lines=["CLEARED", "LVL-Ω"])

        # ── AURUM wordmark (reuses BANNER module constant) ──
        canvas.create_text(460, 210, anchor="center",
                           text=BANNER, font=(FONT, 11, "bold"),
                           fill=AMBER, tags="wordmark")

        # ── Subtitle ──
        canvas.create_text(460, 272, anchor="center",
                           text="F I N A N C I A L   T E R M I N A L",
                           font=(FONT, 9, "bold"),
                           fill=AMBER_D, tags="subtitle")
        canvas.create_text(460, 288, anchor="center",
                           text="· · ·  V A U L T - 3  · · ·",
                           font=(FONT, 7),
                           fill=DIM, tags="subtitle")

        # ── Rule above status block ──
        canvas.create_line(180, 312, 740, 312,
                           fill=AMBER_D, width=1, tags="rule")

        # ── Status block (6 CRT rows) ──
        try:
            st = _conn.status_summary()
            market_val = st.get("market", "—")
        except Exception:
            market_val = "—"
        try:
            keys = self._load_json("keys.json")
            has_tg = bool(keys.get("telegram", {}).get("bot_token"))
            has_keys = bool(
                keys.get("demo", {}).get("api_key")
                or keys.get("testnet", {}).get("api_key")
            )
        except Exception:
            has_tg = False
            has_keys = False

        market_cell = "● LIVE" if market_val and market_val != "—" else "○ OFFLINE"
        market_col = GREEN if market_cell == "● LIVE" else DIM
        conn_cell = "● BINANCE" if has_keys else "○ OFFLINE"
        conn_col = GREEN if has_keys else DIM
        tg_cell = "● ONLINE" if has_tg else "○ OFFLINE"
        tg_col = GREEN if has_tg else DIM

        rows = [
            ("SYSTEM STATUS", "NOMINAL",     GREEN),
            ("MARKET FEED",   market_cell,   market_col),
            ("CONNECTION",    conn_cell,     conn_col),
            ("TELEGRAM",      tg_cell,       tg_col),
            ("KILL-SWITCH",   "ARMED [3/3]", RED),
            ("CLEARANCE",     "OMEGA",       AMBER_B),
        ]
        self._draw_status_block(canvas, x=220, y=334, rows=rows)

        # ── Rule below status block ──
        canvas.create_line(180, 448, 740, 448,
                           fill=AMBER_D, width=1, tags="rule")

        # ── Click-to-proceed prompt ──
        self._splash_cursor_on = True
        canvas.create_text(460, 488, anchor="center",
                           text="[ CLICK TO PROCEED ]▊",
                           font=(FONT, 10, "bold"),
                           fill=AMBER_B, tags="prompt")

        # ── Bind click / ENTER / space → main menu ──
        for ev in ("<Button-1>",):
            self.main.bind(ev, lambda e: self._splash_on_click())
        self._kb("<Return>", self._splash_on_click)
        self._kb("<space>",  self._splash_on_click)
        self._bind_global_nav()

        # ── Arm 500ms cursor pulse ──
        self._splash_pulse_after_id = self.after(500, self._splash_pulse_tick)
```

Also, replace the dead splash helpers we added in previous sessions. Directly AFTER the `_splash` method you just rewrote, add the following new methods (replacing any existing `_splash_direct_jump`, `_splash_focus_delta`, etc — delete those if you find them; they're now dead code):

```python
    def _splash_on_click(self) -> None:
        """Click / ENTER / space handler — cancel pulse and route to main menu."""
        if self._splash_pulse_after_id is not None:
            try:
                self.after_cancel(self._splash_pulse_after_id)
            except Exception:
                pass
            self._splash_pulse_after_id = None
        self._splash_canvas = None
        self._menu("main")

    def _splash_pulse_tick(self) -> None:
        """Blink the trailing cursor on the CLICK TO PROCEED prompt every 500ms."""
        canvas = self._splash_canvas
        if canvas is None:
            self._splash_pulse_after_id = None
            return
        self._splash_cursor_on = not self._splash_cursor_on
        new_text = (
            "[ CLICK TO PROCEED ]▊"
            if self._splash_cursor_on
            else "[ CLICK TO PROCEED ] "
        )
        new_color = AMBER_B if self._splash_cursor_on else AMBER
        try:
            canvas.itemconfig("prompt", text=new_text, fill=new_color)
        except Exception:
            self._splash_pulse_after_id = None
            return
        try:
            self._splash_pulse_after_id = self.after(500, self._splash_pulse_tick)
        except Exception:
            self._splash_pulse_after_id = None
```

**Important notes:**
- Delete the old `_splash_direct_jump` and `_splash_focus_delta` methods if they exist in the file — they are no longer referenced and the splash rewrite must leave the file coherent. If you cannot find them via grep, skip.
- Do NOT touch `_menu_main_bloomberg`, `_menu_tile_*`, `_menu_sub_*` — those stay as dead code for potential reuse.
- Do NOT delete `_cd_draw` — the old radar method — it stays as dead code too.
- `_conn` is the module-level `ConnectionManager` instance already imported at module top of `launcher.py`. Use it as the existing `_splash` did.

### Step 4 — Run the tests, expect pass

```
python -m pytest tests/test_launcher_main_menu.py -v -k "splash_creates_canvas or splash_click or splash_pulse"
```

Expected: 3 PASS.

### Step 5 — Run the full test suite

```
python -m pytest tests/test_launcher_main_menu.py -v
```

Expected: all tests pass (minus the known Tcl `msgcat` flake on Windows, which is environmental).

### Step 6 — Smoke test

```
python smoke_test.py --quiet
```

Expected: exit 0. The existing `call("_splash", app._splash)` in smoke will exercise the new splash render.

### Step 7 — AST parse sanity check

```
python -c "import ast; ast.parse(open('launcher.py', encoding='utf-8').read())"
```

Expected: no output (parse OK).

### Step 8 — Commit

```
git add launcher.py tests/test_launcher_main_menu.py
git commit -m "feat(launcher): HL1 Black Mesa splash — warning stripes, stamps, pulse"
```

---

## Task 7: Manual walkthrough + session log + merge

**Files:**
- Create: `docs/sessions/2026-04-11_HHMM.md`
- Main branch: fast-forward merge of `feat/splash-halflife`

### Step 1 — Manual UI walkthrough

From the worktree: `python launcher.py`. Verify:

1. Splash appears with:
   - Yellow warning stripe top with `⚠ AUTHORIZED ACCESS ONLY ⚠`
   - Small CD top-left (rotates)
   - Two stamps top-right: `VAULT 03` and `CLEARED LVL-Ω`
   - AURUM wordmark centered (from BANNER)
   - `F I N A N C I A L   T E R M I N A L` subtitle
   - `· · ·  V A U L T - 3  · · ·` sub-subtitle
   - Amber rule above status block
   - 6 CRT status rows with dot-padded alignment, correct colors
   - Amber rule below status block
   - `[ CLICK TO PROCEED ]▊` centered below
   - Yellow warning stripe bottom with `© 2026 AURUM · O DISCO LÊ A SI MESMO`
2. Wait 1-2 seconds. Cursor `▊` blinks every 500ms.
3. Press `→` (right arrow). Nothing happens.
4. Press `1`. Nothing happens.
5. Click anywhere on the splash. Main menu (Fibonacci) appears.
6. Press ESC from main menu → splash returns, pulse resumes.
7. Press Q. App exits.

If any step fails visually, stop and fix.

### Step 2 — Write session log

Create `docs/sessions/2026-04-11_HHMM.md` (use `date -u +"%Y-%m-%d_%H%M"` for the actual UTC timestamp). Follow the template in `CLAUDE.md` precisely. Highlight: pure UI change, zero trading logic touched, splash reverted from tile-navigation to atmospheric gate, all previous Bloomberg 3D tile infrastructure preserved as dead code for future reuse.

Commit:

```
git add docs/sessions/2026-04-11_*.md
git commit -m "docs(sessions): HL1 Black Mesa splash redesign — session log"
```

### Step 3 — Final smoke run in worktree

```
python smoke_test.py --quiet
```

Expected: exit 0, 164/164.

### Step 4 — Merge to main

From the parent checkout at `C:/Users/Joao/OneDrive/aurum.finance`:

```
git merge --ff-only feat/splash-halflife
python smoke_test.py --quiet
```

Expected: fast-forward succeeds; smoke on main passes (169/169 based on main's larger backtest index, or whatever the current count is — just verify exit 0).

### Step 5 — Clean up

```
git branch -D feat/splash-halflife
git worktree prune
```

Note: the OneDrive Windows file-lock issue may leave residual files in `.worktrees/splash-halflife` — that's inert and gitignored, ignore it.

---

## Verification Checklist

- [ ] `python -m pytest tests/test_launcher_main_menu.py` — all tests pass (modulo Tcl msgcat flake)
- [ ] `python smoke_test.py --quiet` — exit 0
- [ ] Manual UI walkthrough completed (7 steps)
- [ ] Click anywhere on splash → main menu
- [ ] Arrow keys and 1-4 do nothing on splash
- [ ] Cursor `▊` blinks every 500ms
- [ ] CD rotates on top-left
- [ ] Warning stripes yellow, institutional feel
- [ ] Status block shows 6 CRT-aligned rows
- [ ] No modifications to engines, signals, costs, or risk logic
- [ ] `_menu_main_bloomberg` and its helpers still present (dead code)
- [ ] Session log written per CLAUDE.md rules
- [ ] Fast-forward merge to main succeeds
