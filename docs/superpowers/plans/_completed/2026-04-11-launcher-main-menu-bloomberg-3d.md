# Launcher Main Menu — Bloomberg 3D Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign `_menu("main")` in `launcher.py` as a Bloomberg-style 2×2 isometric tile grid around a central CD, with live mini-data per tile, multi-color accents, iPod-style navigation (1-4 + arrows + ENTER), and in-place drill-down — all gated behind a feature flag for safe rollback.

**Architecture:** Single-file change in `launcher.py`. New `MAIN_GROUPS` constant drives the 4-tile structure. All rendering happens in one `tk.Canvas` full-frame widget (tiles via `create_line`/`create_polygon`, CD via `create_oval`/arcs, text via `create_text`). A background thread refreshes live data every 5s into `self._menu_live` cache; render reads cache only. Feature flag `AURUM_MENU_STYLE` (env var) selects `bloomberg` (default) or `legacy` (old Fibonacci path, preserved verbatim).

**Tech Stack:** Python 3.14, Tkinter, stdlib only (no `psutil` — not a project dep). Tests use pytest with `conftest.py` already present. Smoke test pattern from `smoke_test.py` (headless `App().withdraw()`).

**Spec reference:** `docs/superpowers/specs/2026-04-11-launcher-main-menu-bloomberg-3d-design.md`

---

## File Structure

| File | Role | Action |
|---|---|---|
| `launcher.py` | Main app — add constants, new methods, wire `_menu("main")` | Modify |
| `tests/test_launcher_main_menu.py` | Unit tests for MAIN_GROUPS shape, fetcher fallbacks, render smoke, feature flag routing, sub-select dispatch | Create |
| `smoke_test.py` | Add coverage for Bloomberg main menu + drill-down + legacy flag | Modify |

Every task below operates on these three files only.

---

## Task 1: Add tile color constants + `MAIN_GROUPS` data structure

**Files:**
- Modify: `launcher.py:23-37` (add TILE_* colors near existing palette)
- Modify: `launcher.py:98-108` (add `MAIN_GROUPS` after `MAIN_MENU`)
- Create: `tests/test_launcher_main_menu.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_launcher_main_menu.py`:

```python
"""Tests for Bloomberg 3D main menu redesign in launcher.py."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_launcher():
    spec = importlib.util.spec_from_file_location("launcher", ROOT / "launcher.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_tile_colors_defined():
    mod = _load_launcher()
    assert mod.TILE_MARKETS == "#ff8c00"
    assert mod.TILE_EXECUTE == "#00c864"
    assert mod.TILE_RESEARCH == "#33aaff"
    assert mod.TILE_CONTROL == "#c864c8"


def test_main_groups_shape():
    mod = _load_launcher()
    groups = mod.MAIN_GROUPS
    assert len(groups) == 4, "must be exactly 4 tiles"

    labels = [g[0] for g in groups]
    assert labels == ["MARKETS", "EXECUTE", "RESEARCH", "CONTROL"]

    for label, key_num, color, children in groups:
        assert isinstance(label, str) and label.isupper()
        assert key_num in {"1", "2", "3", "4"}
        assert color.startswith("#") and len(color) == 7
        assert isinstance(children, list) and 1 <= len(children) <= 3
        for child_label, method_name in children:
            assert isinstance(child_label, str)
            assert method_name.startswith("_")


def test_main_groups_cover_all_legacy_destinations():
    """Every destination callable in MAIN_MENU must still be reachable via MAIN_GROUPS."""
    mod = _load_launcher()
    legacy_keys = {key for _, key, _ in mod.MAIN_MENU}
    # legacy_keys = {markets, connections, terminal, data, strategies,
    #                arbitrage (alchemy), risk, command, settings}
    # MAIN_GROUPS uses method names; build a mapping and verify coverage.
    reachable_methods = {
        method for _, _, _, children in mod.MAIN_GROUPS
        for _, method in children
    }
    required_methods = {
        "_markets", "_connections", "_terminal", "_data_center",
        "_strategies", "_arbitrage_hub", "_risk_menu",
        "_command_center", "_config", "_crypto_dashboard",
    }
    missing = required_methods - reachable_methods
    assert not missing, f"MAIN_GROUPS missing destinations: {missing}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_launcher_main_menu.py -v`
Expected: FAIL with `AttributeError: module 'launcher' has no attribute 'TILE_MARKETS'`

- [ ] **Step 3: Add tile color constants**

In `launcher.py`, immediately after line 37 (`FONT = "Consolas"`), add:

```python
# ─── BLOOMBERG 3D MENU — tile accents ────────────────────────
TILE_MARKETS  = "#ff8c00"   # AMBER    — quote + dash
TILE_EXECUTE  = "#00c864"   # GREEN    — strategies + arb + risk
TILE_RESEARCH = "#33aaff"   # CYAN     — terminal + data
TILE_CONTROL  = "#c864c8"   # MAGENTA  — connections + command + settings
TILE_DIM_FACTOR = 0.3       # idle brightness multiplier
```

- [ ] **Step 4: Add `MAIN_GROUPS` constant**

In `launcher.py`, immediately after the `MAIN_MENU = [...]` list (which currently ends at line 108), add:

```python
# ─── MAIN_GROUPS: 9 destinos agrupados em 4 tiles (Bloomberg 3D) ────
# Format: (label, key_num, color, [(child_label, method_name), ...])
# MAIN_MENU (above) kept for legacy Fibonacci fallback + descriptions.
MAIN_GROUPS = [
    ("MARKETS",  "1", TILE_MARKETS, [
        ("QUOTE BOARD", "_markets"),
        ("CRYPTO DASH", "_crypto_dashboard"),
    ]),
    ("EXECUTE",  "2", TILE_EXECUTE, [
        ("STRATEGIES", "_strategies"),
        ("ARBITRAGE",  "_arbitrage_hub"),
        ("RISK",       "_risk_menu"),
    ]),
    ("RESEARCH", "3", TILE_RESEARCH, [
        ("TERMINAL", "_terminal"),
        ("DATA",     "_data_center"),
    ]),
    ("CONTROL",  "4", TILE_CONTROL, [
        ("CONNECTIONS", "_connections"),
        ("COMMAND",     "_command_center"),
        ("SETTINGS",    "_config"),
    ]),
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_launcher_main_menu.py -v`
Expected: 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add launcher.py tests/test_launcher_main_menu.py
git commit -m "feat(launcher): add MAIN_GROUPS data + tile colors for Bloomberg 3D menu"
```

---

## Task 2: Initialize live-data cache and start time in `App.__init__`

**Files:**
- Modify: `launcher.py:740-748` (add to `__init__` body)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_launcher_main_menu.py`:

```python
def test_app_has_menu_live_cache():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        assert hasattr(app, "_menu_live")
        assert isinstance(app._menu_live, dict)
        for key in ("markets", "execute", "research", "control"):
            assert key in app._menu_live
            assert isinstance(app._menu_live[key], dict)
        assert hasattr(app, "_start_t")
        assert isinstance(app._start_t, float)
    finally:
        app.destroy()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_launcher_main_menu.py::test_app_has_menu_live_cache -v`
Expected: FAIL with `AttributeError: 'App' object has no attribute '_menu_live'`

- [ ] **Step 3: Initialize cache and start time**

In `launcher.py`, inside `App.__init__` (around line 740, right after `self.history = []`), add:

```python
        # ─── Bloomberg 3D main menu state ────────────────
        self._start_t = time.monotonic()
        self._menu_live = {
            "markets":  {},
            "execute":  {},
            "research": {},
            "control":  {},
        }
        self._menu_focused_tile = 0      # 0..3 index into MAIN_GROUPS
        self._menu_expanded_tile = None  # None or 0..3 when drilled in
        self._menu_sub_focus = 0         # 0..2 within expanded sub-menu
        self._menu_canvas = None         # tk.Canvas handle, set on render
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_launcher_main_menu.py::test_app_has_menu_live_cache -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add launcher.py tests/test_launcher_main_menu.py
git commit -m "feat(launcher): init _menu_live cache and _start_t in App"
```

---

## Task 3: Implement 4 fetcher methods with graceful fallback

**Files:**
- Modify: `launcher.py` (new methods after `_tick`, around line 838)

Each fetcher is a pure function that returns a dict of 4 string lines. Any exception → returns fallback dict with `"—"` values. No fetcher blocks the UI thread (called from worker).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_launcher_main_menu.py`:

```python
def test_fetch_markets_fallback_on_exception(monkeypatch):
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        # Force any internal dependency to raise — just confirm no exception leaks
        # and the returned dict has the expected keys with safe values.
        result = app._fetch_tile_markets()
        assert isinstance(result, dict)
        assert set(result.keys()) == {"line1", "line2", "line3", "line4"}
        for v in result.values():
            assert isinstance(v, str)
    finally:
        app.destroy()


def test_fetch_execute_returns_dict():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        result = app._fetch_tile_execute()
        assert set(result.keys()) == {"line1", "line2", "line3", "line4"}
    finally:
        app.destroy()


def test_fetch_research_returns_dict():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        result = app._fetch_tile_research()
        assert set(result.keys()) == {"line1", "line2", "line3", "line4"}
    finally:
        app.destroy()


def test_fetch_control_uptime_format():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        result = app._fetch_tile_control()
        assert set(result.keys()) == {"line1", "line2", "line3", "line4"}
        # line2 is uptime — must contain 'h' or 'm'
        assert "h" in result["line2"] or "m" in result["line2"] or result["line2"] == "—"
    finally:
        app.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_launcher_main_menu.py -v -k "fetch"`
Expected: 4 FAILs with `AttributeError: 'App' object has no attribute '_fetch_tile_markets'`

- [ ] **Step 3: Add the 4 fetcher methods**

In `launcher.py`, add these methods in the `App` class (place them after `_tick` around line 838, before `_splash`):

```python
    # ─── Bloomberg 3D menu — live data fetchers ──────────
    # Each fetcher returns {"line1","line2","line3","line4"} of strings.
    # Any failure → "—". Never raises. Called from a worker thread.

    @staticmethod
    def _fallback_lines() -> dict:
        return {"line1": "—", "line2": "—", "line3": "—", "line4": "—"}

    def _fetch_tile_markets(self) -> dict:
        try:
            from config.params import UNIVERSE
            lines = {"line1": "—", "line2": "—", "line3": "—", "line4": "—"}
            # Prices — best-effort, may be empty on offline
            try:
                from core.data import fetch_spot_price
                btc = fetch_spot_price("BTCUSDT")
                lines["line1"] = f"BTC {btc/1000:.1f}k" if btc else "BTC —"
            except Exception:
                lines["line1"] = "BTC —"
            try:
                from core.data import fetch_spot_price
                eth = fetch_spot_price("ETHUSDT")
                lines["line2"] = f"ETH {eth/1000:.2f}k" if eth else "ETH —"
            except Exception:
                lines["line2"] = "ETH —"
            lines["line3"] = f"{len(UNIVERSE)} pairs"
            try:
                from core.portfolio import detect_macro
                lines["line4"] = f"MACRO {detect_macro()}"
            except Exception:
                lines["line4"] = "MACRO —"
            return lines
        except Exception:
            return self._fallback_lines()

    def _fetch_tile_execute(self) -> dict:
        try:
            lines = self._fallback_lines()
            # procs
            try:
                from core import proc
                n = len(proc.list_active()) if hasattr(proc, "list_active") else 0
                lines["line1"] = f"procs {n}"
            except Exception:
                lines["line1"] = "procs 0"
            # paper PnL
            try:
                ps = json.loads((ROOT / "config" / "paper_state.json").read_text(encoding="utf-8"))
                pnl = float(ps.get("day_pnl", 0.0))
                sign = "+" if pnl >= 0 else ""
                lines["line2"] = f"pnl {sign}{pnl:.1f}%"
                pos = ps.get("open_positions", [])
                lines["line3"] = f"{len(pos)} pos" if isinstance(pos, list) else "0 pos"
            except Exception:
                lines["line2"] = "pnl —"
                lines["line3"] = "0 pos"
            # risk gates
            try:
                rg = json.loads((ROOT / "config" / "risk_gates.json").read_text(encoding="utf-8"))
                active = sum(1 for v in rg.values() if isinstance(v, dict) and v.get("active"))
                total = 5
                lines["line4"] = f"risk {active}/{total}"
            except Exception:
                lines["line4"] = "risk —/5"
            return lines
        except Exception:
            return self._fallback_lines()

    def _fetch_tile_research(self) -> dict:
        try:
            lines = self._fallback_lines()
            idx_path = ROOT / "data" / "index.json"
            if idx_path.exists():
                try:
                    runs = json.loads(idx_path.read_text(encoding="utf-8"))
                    if isinstance(runs, list) and runs:
                        last = runs[-1] if isinstance(runs[-1], dict) else {}
                        eng = str(last.get("engine", "—"))[:4].upper()
                        sharpe = last.get("sharpe") or last.get("metrics", {}).get("sharpe")
                        lines["line1"] = f"last {eng}"
                        lines["line2"] = f"sharpe {float(sharpe):.1f}" if sharpe else "sharpe —"
                        lines["line3"] = f"{len(runs)} runs"
                    else:
                        lines["line1"] = "no runs"
                        lines["line3"] = "0 runs"
                except Exception:
                    lines["line1"] = "last —"
                    lines["line3"] = "— runs"
            else:
                lines["line1"] = "no runs"
                lines["line3"] = "0 runs"
            # HMM status — best effort
            try:
                from core import chronos
                active = bool(getattr(chronos, "hmm_enabled", lambda: False)())
                lines["line4"] = "HMM active" if active else "HMM idle"
            except Exception:
                lines["line4"] = "HMM —"
            return lines
        except Exception:
            return self._fallback_lines()

    def _fetch_tile_control(self) -> dict:
        try:
            lines = self._fallback_lines()
            # connections up/total from config/connections.json
            try:
                conn = json.loads((ROOT / "config" / "connections.json").read_text(encoding="utf-8"))
                if isinstance(conn, dict):
                    items = conn.get("connections") or list(conn.values())
                elif isinstance(conn, list):
                    items = conn
                else:
                    items = []
                total = len(items)
                up = sum(1 for c in items
                         if isinstance(c, dict) and c.get("status", "").lower() in {"up", "ok", "connected"})
                lines["line1"] = f"conn {up}/{total}" if total else "conn —"
            except Exception:
                lines["line1"] = "conn —"
            # uptime via self._start_t (stdlib only — no psutil)
            try:
                elapsed = time.monotonic() - self._start_t
                h = int(elapsed // 3600)
                m = int((elapsed % 3600) // 60)
                lines["line2"] = f"up {h}h{m:02d}m"
            except Exception:
                lines["line2"] = "up —"
            # telegram online — best effort
            try:
                from bot import telegram as tg_mod
                ok = bool(getattr(tg_mod, "is_online", lambda: False)())
                lines["line3"] = "tg ONLINE" if ok else "tg OFFLINE"
            except Exception:
                lines["line3"] = "tg —"
            # vps — cached, cheap
            lines["line4"] = "vps —"  # Wired in a follow-up; placeholder is correct.
            return lines
        except Exception:
            return self._fallback_lines()
```

Note: any missing module (`core.data.fetch_spot_price`, `core.proc.list_active`, `core.chronos.hmm_enabled`, `bot.telegram.is_online`) must fall back gracefully — the try/except already handles that. Do not add new modules; just let the `—` appear.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_launcher_main_menu.py -v -k "fetch"`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add launcher.py tests/test_launcher_main_menu.py
git commit -m "feat(launcher): add 4 tile live-data fetchers with stdlib-only fallbacks"
```

---

## Task 4: Async live-data refresh worker + cache merge

**Files:**
- Modify: `launcher.py` (new method after the 4 fetchers)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_launcher_main_menu.py`:

```python
def test_menu_live_fetch_populates_cache():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        # Run sync version to avoid threading in tests
        app._menu_live_fetch_sync()
        for key in ("markets", "execute", "research", "control"):
            live = app._menu_live[key]
            assert isinstance(live, dict)
            assert set(live.keys()) == {"line1", "line2", "line3", "line4"}
    finally:
        app.destroy()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_launcher_main_menu.py::test_menu_live_fetch_populates_cache -v`
Expected: FAIL with `AttributeError: '_menu_live_fetch_sync'`

- [ ] **Step 3: Add sync + async refresh**

In `launcher.py`, right after the 4 fetcher methods, add:

```python
    def _menu_live_fetch_sync(self) -> None:
        """Populate self._menu_live in-thread. Used by tests and by the async worker."""
        self._menu_live["markets"]  = self._fetch_tile_markets()
        self._menu_live["execute"]  = self._fetch_tile_execute()
        self._menu_live["research"] = self._fetch_tile_research()
        self._menu_live["control"]  = self._fetch_tile_control()

    def _menu_live_fetch_async(self) -> None:
        """Spawn a worker thread that refreshes the cache, then schedules a repaint."""
        def _worker():
            try:
                self._menu_live_fetch_sync()
            except Exception:
                pass  # fetchers already guard; this is belt-and-braces
            try:
                # Schedule repaint on the main thread (only if the Bloomberg menu is active)
                self.after(0, self._menu_live_apply)
            except Exception:
                pass
        threading.Thread(target=_worker, daemon=True).start()

    def _menu_live_apply(self) -> None:
        """Main-thread: redraw tile texts from self._menu_live if the main menu is shown."""
        if self._menu_canvas is None:
            return
        try:
            self._menu_tiles_repaint_text()
        except Exception:
            pass  # never kill the loop
```

`_menu_tiles_repaint_text` is defined in Task 5 (the render task). Leave the call here; it will be wired next. If the test is run before Task 5, the outer try/except catches the missing method.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_launcher_main_menu.py::test_menu_live_fetch_populates_cache -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add launcher.py tests/test_launcher_main_menu.py
git commit -m "feat(launcher): add sync/async live data refresh for Bloomberg menu"
```

---

## Task 5: Canvas renderers — CD, spokes, tiles (no navigation yet)

**Files:**
- Modify: `launcher.py` (new rendering methods after `_menu_live_apply`)

This task introduces the pure drawing functions. They take an existing canvas and coordinates; they do not wire events, keybinds, or state — that comes in Task 6.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_launcher_main_menu.py`:

```python
def test_menu_main_bloomberg_renders_without_exception():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._menu_main_bloomberg()
        app.update_idletasks()
        # Canvas must exist and have drawn items
        assert app._menu_canvas is not None
        items = app._menu_canvas.find_all()
        assert len(items) > 20, f"expected many canvas items, got {len(items)}"
    finally:
        app.destroy()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_launcher_main_menu.py::test_menu_main_bloomberg_renders_without_exception -v`
Expected: FAIL with `AttributeError: '_menu_main_bloomberg'`

- [ ] **Step 3: Add canvas helpers and main renderer**

In `launcher.py`, after `_menu_live_apply`, add:

```python
    # ─── Bloomberg 3D menu — canvas renderers ────────────
    # All drawing happens on one full-frame canvas. Tiles are isometric
    # boxes built from lines/polygons; the CD at the center reuses the
    # existing _cd_draw style via direct oval/arc calls.

    # Tile anchor positions in the 960x~540 content area (2×2 grid)
    _TILE_SLOTS = [
        ("nw", 180, 150),  # tile 0: MARKETS    (top-left)
        ("ne", 640, 150),  # tile 1: EXECUTE    (top-right)
        ("sw", 180, 380),  # tile 2: RESEARCH   (bot-left)
        ("se", 640, 380),  # tile 3: CONTROL    (bot-right)
    ]
    _TILE_W = 200
    _TILE_H = 120
    _TILE_DEPTH = 16   # isometric offset

    _CD_CX = 460
    _CD_CY = 265
    _CD_R  = 68

    def _dim_color(self, hex_color: str, factor: float) -> str:
        """Scale an #rrggbb color by factor (0..1). Pure arithmetic, no PIL."""
        try:
            h = hex_color.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            r = max(0, min(255, int(r * factor)))
            g = max(0, min(255, int(g * factor)))
            b = max(0, min(255, int(b * factor)))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color

    def _tile_rect(self, idx: int) -> tuple[int, int, int, int]:
        """(x1,y1,x2,y2) front face rect for tile idx."""
        _, cx, cy = self._TILE_SLOTS[idx]
        w, h = self._TILE_W, self._TILE_H
        return (cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2)

    def _draw_isometric_tile(self, canvas, idx: int, focused: bool) -> None:
        """Draw one isometric tile with label + 4 live-data lines."""
        label, key_num, color, _children = MAIN_GROUPS[idx]
        x1, y1, x2, y2 = self._tile_rect(idx)
        d = self._TILE_DEPTH
        face_color = color if focused else self._dim_color(color, TILE_DIM_FACTOR)
        text_color = AMBER_B if focused else WHITE
        tag = f"tile{idx}"

        # Clear previous drawing for this tile
        canvas.delete(tag)

        # Top face (parallelogram)
        canvas.create_polygon(
            x1, y1,  x2, y1,  x2 + d, y1 - d,  x1 + d, y1 - d,
            outline=face_color, fill=BG, width=1, tags=tag,
        )
        # Right face
        canvas.create_polygon(
            x2, y1,  x2 + d, y1 - d,  x2 + d, y2 - d,  x2, y2,
            outline=face_color, fill=BG, width=1, tags=tag,
        )
        # Front face border
        canvas.create_rectangle(x1, y1, x2, y2, outline=face_color, width=2 if focused else 1, tags=tag)

        # Label header bar
        canvas.create_rectangle(
            x1, y1, x2, y1 + 18,
            outline=face_color, fill=face_color if focused else BG3, width=0, tags=tag,
        )
        canvas.create_text(
            x1 + 10, y1 + 9, anchor="w",
            text=f" {label}  [{key_num}]",
            font=(FONT, 9, "bold"),
            fill=BG if focused else face_color, tags=tag,
        )

        # 4 live-data lines (read from cache; fallback to "—")
        live_key = label.lower()
        live = self._menu_live.get(live_key, {}) if hasattr(self, "_menu_live") else {}
        for i, line_key in enumerate(("line1", "line2", "line3", "line4")):
            text = live.get(line_key, "—")
            canvas.create_text(
                x1 + 14, y1 + 36 + i * 18, anchor="w",
                text=text, font=(FONT, 9), fill=text_color, tags=tag,
            )

    def _draw_cd_center(self, canvas) -> None:
        """Draw rotating CD at the center — reuses the aesthetic of _cd_draw."""
        cx, cy, r = self._CD_CX, self._CD_CY, self._CD_R
        canvas.delete("cd")
        # Outer disc
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                           outline=AMBER, width=2, tags="cd")
        # Inner disc
        canvas.create_oval(cx - r + 10, cy - r + 10, cx + r - 10, cy + r - 10,
                           outline=AMBER_D, width=1, tags="cd")
        # Center hole
        canvas.create_oval(cx - 10, cy - 10, cx + 10, cy + 10,
                           outline=AMBER, width=1, fill=BG, tags="cd")
        # Rotating arc (uses time-based angle — picks up ticks from _tick)
        import math
        angle = int((time.monotonic() * 40) % 360)
        canvas.create_arc(cx - r + 4, cy - r + 4, cx + r - 4, cy + r - 4,
                          start=angle, extent=30, outline=AMBER_B, width=2,
                          style="arc", tags="cd")
        # Labels
        canvas.create_text(cx, cy - 4, text="AURUM", font=(FONT, 8, "bold"),
                           fill=AMBER, tags="cd")
        canvas.create_text(cx, cy + 6, text="LASER", font=(FONT, 7),
                           fill=DIM, tags="cd")
        canvas.create_text(cx, cy + r + 10, text="φ = 1.618",
                           font=(FONT, 7), fill=DIM2, tags="cd")

    def _draw_spokes(self, canvas, focused_idx: int) -> None:
        """4 dotted lines from each tile's nearest corner to the CD."""
        canvas.delete("spokes")
        for idx in range(4):
            x1, y1, x2, y2 = self._tile_rect(idx)
            # Nearest inner corner (pointing toward center)
            _, cx, cy = self._TILE_SLOTS[idx]
            anchor_x = x2 if cx < self._CD_CX else x1
            anchor_y = y2 if cy < self._CD_CY else y1
            _, _, color, _ = MAIN_GROUPS[idx]
            line_color = color if idx == focused_idx else DIM2
            width = 2 if idx == focused_idx else 1
            canvas.create_line(
                anchor_x, anchor_y, self._CD_CX, self._CD_CY,
                fill=line_color, width=width, dash=(2, 4), tags="spokes",
            )

    def _menu_tiles_repaint_text(self) -> None:
        """Redraw all 4 tiles (used after a live-data refresh)."""
        if self._menu_canvas is None:
            return
        for idx in range(4):
            self._draw_isometric_tile(self._menu_canvas, idx, idx == self._menu_focused_tile)

    def _menu_main_bloomberg(self) -> None:
        """Main entry for the 2×2 Bloomberg tile grid + CD center."""
        self._clr()
        self._clear_kb()
        self.history.clear()
        self.h_stat.configure(text="SELECIONAR", fg=AMBER_D)
        self.h_path.configure(text="> PRINCIPAL  ·  O DISCO LÊ A SI MESMO")
        self.f_lbl.configure(text="1-4 direto · ← ↑ ↓ → nav · ENTER · ESC sai")

        f = tk.Frame(self.main, bg=BG)
        f.pack(fill="both", expand=True)
        canvas = tk.Canvas(f, bg=BG, highlightthickness=0, width=920, height=540)
        canvas.pack(fill="both", expand=True)
        self._menu_canvas = canvas

        # Prime cache on first render so tiles aren't empty
        if not any(self._menu_live.get(k) for k in ("markets", "execute", "research", "control")):
            self._menu_live_fetch_async()

        # Initial draw
        self._draw_cd_center(canvas)
        self._draw_spokes(canvas, self._menu_focused_tile)
        for idx in range(4):
            self._draw_isometric_tile(canvas, idx, idx == self._menu_focused_tile)

        # Keybinds wired in Task 6
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_launcher_main_menu.py::test_menu_main_bloomberg_renders_without_exception -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add launcher.py tests/test_launcher_main_menu.py
git commit -m "feat(launcher): canvas renderers for tiles, CD, spokes"
```

---

## Task 6: Keyboard navigation and tile focus

**Files:**
- Modify: `launcher.py` (add methods + extend `_menu_main_bloomberg` with keybinds)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_launcher_main_menu.py`:

```python
def test_focus_moves_with_arrow_right():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._menu_main_bloomberg()
        app.update_idletasks()
        assert app._menu_focused_tile == 0
        app._menu_tile_focus(1)
        assert app._menu_focused_tile == 1
        app._menu_tile_focus_delta(+1)  # right = +1
        assert app._menu_focused_tile == 0  # wraps 1→2→3→0
    finally:
        app.destroy()


def test_focus_numeric_jump():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._menu_main_bloomberg()
        app._menu_tile_focus(3)
        assert app._menu_focused_tile == 3
    finally:
        app.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_launcher_main_menu.py -v -k "focus"`
Expected: 2 FAILs — `_menu_tile_focus` / `_menu_tile_focus_delta` missing.

- [ ] **Step 3: Add focus methods and wire keybinds**

In `launcher.py`, add these methods right after `_menu_main_bloomberg`:

```python
    def _menu_tile_focus(self, idx: int) -> None:
        """Move focus to tile idx (0..3) and repaint affected tiles + spokes."""
        if not (0 <= idx <= 3):
            return
        prev = self._menu_focused_tile
        self._menu_focused_tile = idx
        if self._menu_canvas is None:
            return
        # Repaint only the two tiles affected + all spokes
        self._draw_isometric_tile(self._menu_canvas, prev, False)
        self._draw_isometric_tile(self._menu_canvas, idx, True)
        self._draw_spokes(self._menu_canvas, idx)

    def _menu_tile_focus_delta(self, delta: int) -> None:
        """Cyclic focus shift by +/-1 or +/-2 (2 = next row)."""
        self._menu_tile_focus((self._menu_focused_tile + delta) % 4)
```

Then, at the bottom of `_menu_main_bloomberg` (replacing the `# Keybinds wired in Task 6` line), add:

```python
        # Keybinds — direct 1-4, arrow navigation, Enter to expand, Esc to splash
        for n in (1, 2, 3, 4):
            self._kb(f"<Key-{n}>",
                     lambda _n=n - 1: (self._menu_tile_focus(_n), self._menu_tile_expand(_n)))
        self._kb("<Right>",     lambda: self._menu_tile_focus_delta(+1))
        self._kb("<Left>",      lambda: self._menu_tile_focus_delta(-1))
        self._kb("<Down>",      lambda: self._menu_tile_focus_delta(+2))
        self._kb("<Up>",        lambda: self._menu_tile_focus_delta(-2))
        self._kb("<Tab>",       lambda: self._menu_tile_focus_delta(+1))
        self._kb("<Return>",    lambda: self._menu_tile_expand(self._menu_focused_tile))
        self._kb("<Escape>",    self._splash)
        self._bind_global_nav()
```

`_menu_tile_expand` is stubbed in the next task. To avoid a NameError if Return fires before Task 7 lands, add a stub:

```python
    def _menu_tile_expand(self, idx: int) -> None:
        """Stub — drill-down implementation arrives in Task 7."""
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_launcher_main_menu.py -v -k "focus"`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add launcher.py tests/test_launcher_main_menu.py
git commit -m "feat(launcher): Bloomberg menu focus navigation + keybinds"
```

---

## Task 7: Drill-down — tile expand in-place + sub-menu + dispatch

**Files:**
- Modify: `launcher.py` (replace `_menu_tile_expand` stub + add collapse/sub/dispatch)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_launcher_main_menu.py`:

```python
def test_expand_and_collapse_state():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._menu_main_bloomberg()
        app._menu_tile_expand(0)
        assert app._menu_expanded_tile == 0
        assert app._menu_sub_focus == 0
        app._menu_tile_collapse()
        assert app._menu_expanded_tile is None
    finally:
        app.destroy()


def test_sub_select_dispatches_to_method(monkeypatch):
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._menu_main_bloomberg()
        called = []
        monkeypatch.setattr(app, "_markets", lambda: called.append("markets"))
        app._menu_tile_expand(0)
        app._menu_sub_select(0, 0)  # tile MARKETS, child 0 = QUOTE BOARD → _markets
        assert called == ["markets"]
    finally:
        app.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_launcher_main_menu.py -v -k "expand or sub_select"`
Expected: 2 FAILs.

- [ ] **Step 3: Replace stub with full drill-down**

In `launcher.py`, replace the `_menu_tile_expand` stub with:

```python
    def _menu_tile_expand(self, idx: int) -> None:
        """Expand tile idx in-place: fade others, grow focused tile, draw sub-menu."""
        if not (0 <= idx <= 3):
            return
        if self._menu_canvas is None:
            return
        self._menu_expanded_tile = idx
        self._menu_sub_focus = 0

        canvas = self._menu_canvas
        # Fade-out: redraw all tiles with dimmed color, then full-clear CD + spokes
        for i in range(4):
            if i == idx:
                continue
            canvas.delete(f"tile{i}")
        canvas.delete("cd")
        canvas.delete("spokes")

        # Grow the focused tile to 80% of the canvas area
        _, _, color, children = MAIN_GROUPS[idx]
        label = MAIN_GROUPS[idx][0]
        canvas.delete(f"tile{idx}")
        x1, y1, x2, y2 = 80, 60, 840, 480
        canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=2, tags=f"tile{idx}")
        canvas.create_rectangle(x1, y1, x2, y1 + 26, outline=color, fill=color, width=0, tags=f"tile{idx}")
        canvas.create_text(x1 + 16, y1 + 13, anchor="w",
                           text=f" {label}  [{MAIN_GROUPS[idx][1]}]",
                           font=(FONT, 11, "bold"), fill=BG, tags=f"tile{idx}")

        self._menu_sub_render(idx)
        # Rebind keys for sub-menu mode
        self._clear_kb()
        for i, (_clabel, _method) in enumerate(children):
            n = i + 1
            self._kb(f"<Key-{n}>",
                     lambda _i=i: self._menu_sub_select(idx, _i))
        self._kb("<Down>",   lambda: self._menu_sub_focus_delta(+1))
        self._kb("<Up>",     lambda: self._menu_sub_focus_delta(-1))
        self._kb("<Return>", lambda: self._menu_sub_select(idx, self._menu_sub_focus))
        self._kb("<Escape>", self._menu_tile_collapse)
        self._kb("<Key-0>",  self._menu_tile_collapse)
        self._bind_global_nav()
        self.f_lbl.configure(text="1-N selecionar · ↑↓ nav · ENTER · ESC voltar")

    def _menu_sub_render(self, idx: int) -> None:
        """Draw the vertical sub-menu inside an expanded tile."""
        if self._menu_canvas is None:
            return
        canvas = self._menu_canvas
        canvas.delete("submenu")
        _, _, color, children = MAIN_GROUPS[idx]
        for i, (child_label, _method) in enumerate(children):
            y = 120 + i * 42
            focused = i == self._menu_sub_focus
            fg = AMBER_B if focused else WHITE
            bg = color if focused else BG3
            canvas.create_rectangle(140, y - 16, 780, y + 16,
                                    outline=color, fill=bg, width=1, tags="submenu")
            canvas.create_text(160, y, anchor="w",
                               text=f"  › {i+1}  {child_label}",
                               font=(FONT, 11, "bold"),
                               fill=(BG if focused else fg), tags="submenu")

    def _menu_sub_focus_delta(self, delta: int) -> None:
        if self._menu_expanded_tile is None:
            return
        children = MAIN_GROUPS[self._menu_expanded_tile][3]
        self._menu_sub_focus = (self._menu_sub_focus + delta) % len(children)
        self._menu_sub_render(self._menu_expanded_tile)

    def _menu_sub_select(self, tile_idx: int, sub_idx: int) -> None:
        """Dispatch to the destination method for a sub-menu item."""
        if not (0 <= tile_idx <= 3):
            return
        children = MAIN_GROUPS[tile_idx][3]
        if not (0 <= sub_idx < len(children)):
            return
        _, method_name = children[sub_idx]
        fn = getattr(self, method_name, None)
        if callable(fn):
            # Leaving the main menu — collapsed state is implicit since the
            # destination method calls self._clr() itself.
            self._menu_expanded_tile = None
            self._menu_canvas = None
            fn()

    def _menu_tile_collapse(self) -> None:
        """Return from expanded tile back to the 2×2 grid."""
        self._menu_expanded_tile = None
        self._menu_sub_focus = 0
        self._menu_main_bloomberg()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_launcher_main_menu.py -v -k "expand or sub_select"`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add launcher.py tests/test_launcher_main_menu.py
git commit -m "feat(launcher): drill-down expand + sub-menu dispatch for Bloomberg menu"
```

---

## Task 8: Wire `_menu("main")` with feature flag + legacy preservation

**Files:**
- Modify: `launcher.py:1033-1071` (the `_menu` method, specifically the `if key == "main"` branch)

This task routes the new renderer through a feature flag while leaving the legacy Fibonacci block untouched for rollback.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_launcher_main_menu.py`:

```python
def test_feature_flag_routes_to_bloomberg_by_default(monkeypatch):
    monkeypatch.delenv("AURUM_MENU_STYLE", raising=False)
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._menu("main")
        app.update_idletasks()
        assert app._menu_canvas is not None  # Bloomberg path creates canvas
    finally:
        app.destroy()


def test_feature_flag_legacy_disables_canvas(monkeypatch):
    monkeypatch.setenv("AURUM_MENU_STYLE", "legacy")
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._menu("main")
        app.update_idletasks()
        # Legacy path does NOT set _menu_canvas (it uses tk.Frame + Fibonacci)
        assert app._menu_canvas is None
    finally:
        app.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_launcher_main_menu.py -v -k "feature_flag"`
Expected: 2 FAILs (default path still uses legacy Fibonacci).

- [ ] **Step 3: Gate `_menu("main")` on env flag**

In `launcher.py`, locate the block starting at line 1054 (`if key == "main":`) inside `_menu`. The current code is:

```python
        if key == "main":
            self.history.clear()
            items = [(n, k, d) for n, k, d in MAIN_MENU]
            title = "PRINCIPAL"
            self.h_path.configure(text="")
            self.f_lbl.configure(text="ESC sair  |  H hub  |  S strategies  |  Q quit")
            self._kb("<Escape>", self._splash)
            self._bind_global_nav()
```

Directly **before** this block (right after the `if key == "main":` line), insert the Bloomberg short-circuit:

```python
        if key == "main":
            # ─── Feature flag: Bloomberg 3D menu (default) ───
            if os.environ.get("AURUM_MENU_STYLE", "bloomberg").lower() != "legacy":
                self._menu_main_bloomberg()
                return
            # ─── Legacy Fibonacci path (rollback) ────────────
            self.history.clear()
            items = [(n, k, d) for n, k, d in MAIN_MENU]
            # ... (rest of existing block unchanged)
```

Do not delete or modify any existing legacy code. The Fibonacci block (lines ~1073-1129) remains untouched and is reachable via `AURUM_MENU_STYLE=legacy`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_launcher_main_menu.py -v -k "feature_flag"`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add launcher.py tests/test_launcher_main_menu.py
git commit -m "feat(launcher): route _menu(main) via AURUM_MENU_STYLE flag"
```

---

## Task 9: Schedule recurring 5s live-data refresh

**Files:**
- Modify: `launcher.py` (extend `_menu_main_bloomberg` with a scheduled repeat)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_launcher_main_menu.py`:

```python
def test_live_refresh_schedule_registered():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._menu_main_bloomberg()
        # The app should have scheduled a repeat via self.after — look for an after-id
        assert hasattr(app, "_menu_live_after_id")
        assert app._menu_live_after_id is not None
    finally:
        app.destroy()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_launcher_main_menu.py::test_live_refresh_schedule_registered -v`
Expected: FAIL — `_menu_live_after_id` missing.

- [ ] **Step 3: Add scheduling**

In `launcher.py`, add a helper method right after `_menu_tile_collapse`:

```python
    def _menu_live_schedule(self) -> None:
        """Re-arm the 5s live-data refresh while the Bloomberg menu is active."""
        if self._menu_canvas is None:
            self._menu_live_after_id = None
            return
        self._menu_live_fetch_async()
        try:
            self._menu_live_after_id = self.after(5000, self._menu_live_schedule)
        except Exception:
            self._menu_live_after_id = None
```

At the end of `_menu_main_bloomberg` (right after `self._bind_global_nav()`), add:

```python
        # Kick off recurring live refresh (5s cadence, only while canvas alive)
        self._menu_live_schedule()
```

Also, in `__init__` (alongside the other `_menu_*` init lines added in Task 2), add:

```python
        self._menu_live_after_id = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_launcher_main_menu.py::test_live_refresh_schedule_registered -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add launcher.py tests/test_launcher_main_menu.py
git commit -m "feat(launcher): recurring 5s live-data refresh for Bloomberg menu"
```

---

## Task 10: Extend smoke_test.py to cover new main menu paths

**Files:**
- Modify: `smoke_test.py` (add Bloomberg coverage after the existing SPLASH section)

- [ ] **Step 1: Run existing smoke to record baseline**

Run: `python smoke_test.py --quiet`
Expected: Exit 0, pass count recorded. Note the number.

- [ ] **Step 2: Add coverage for Bloomberg menu + drill-down + legacy flag**

In `smoke_test.py`, after the `# ── SPLASH + TOP-LEVEL SCREENS ──` block (right after `call("_splash", app._splash)`), insert:

```python
    # ── BLOOMBERG 3D MAIN MENU ──
    section("BLOOMBERG MAIN MENU")
    call("_menu_main_bloomberg", app._menu_main_bloomberg)
    call("focus tile 1",         app._menu_tile_focus, 1)
    call("focus tile 2",         app._menu_tile_focus, 2)
    call("focus tile 3",         app._menu_tile_focus, 3)
    call("focus delta +1",       app._menu_tile_focus_delta, +1)
    call("expand tile 0",        app._menu_tile_expand, 0)
    call("sub focus +1",         app._menu_sub_focus_delta, +1)
    call("collapse",             app._menu_tile_collapse)
    call("expand tile 2",        app._menu_tile_expand, 2)
    call("collapse again",       app._menu_tile_collapse)
    call("live fetch sync",      app._menu_live_fetch_sync)
    call("live apply",           app._menu_live_apply)

    # ── LEGACY MAIN MENU (feature flag rollback) ──
    section("LEGACY FIBONACCI MENU")
    os.environ["AURUM_MENU_STYLE"] = "legacy"
    try:
        call("_menu(main) legacy", app._menu, "main")
    finally:
        os.environ.pop("AURUM_MENU_STYLE", None)
```

Ensure `import os` is already at the top of `smoke_test.py` (it isn't by default — `sys` is). Add `import os` to the imports block at the top of the file if missing.

- [ ] **Step 3: Run smoke again, expect higher pass count**

Run: `python smoke_test.py --quiet`
Expected: Exit 0, pass count = baseline + ~14 new OKs, 0 FAILs.

- [ ] **Step 4: Commit**

```bash
git add smoke_test.py
git commit -m "test(smoke): cover Bloomberg main menu + drill-down + legacy flag"
```

---

## Task 11: Full validation and session log

**Files:**
- Create/Modify: `docs/sessions/2026-04-11_HHMM.md` (session log per CLAUDE.md rule)

- [ ] **Step 1: Run pytest for all launcher menu tests**

Run: `python -m pytest tests/test_launcher_main_menu.py -v`
Expected: All tests PASS (16+ tests total).

- [ ] **Step 2: Run smoke test**

Run: `python smoke_test.py --quiet`
Expected: Exit 0, no FAILs. Record pass count.

- [ ] **Step 3: Manual UI walkthrough**

Run: `python launcher.py`. Check:

1. Splash appears, ENTER → Bloomberg 2×2 grid with 4 isometric tiles + CD.
2. Tile 0 (MARKETS) is focused by default (AMBER label highlighted).
3. Press `2` → tile EXECUTE expands in-place → sub-menu STRATEGIES/ARBITRAGE/RISK.
4. Press `↓` → sub-focus moves to ARBITRAGE, press ENTER → `_arbitrage_hub` opens.
5. Navigate back to splash (ESC repeatedly) → splash → ENTER → grid again.
6. Press `→` → focus moves to tile 1 (EXECUTE).
7. Press `↓` → focus moves to tile 3 (CONTROL).
8. Press `4` → CONTROL expands → 3 sub-items.
9. Press `ESC` → collapses back to grid.
10. Wait 5s → live-data lines update (values may still be `—` if offline).
11. Exit (`Q`). No Python tracebacks in stdout.

If any step fails, fix and re-run.

- [ ] **Step 4: Manual legacy flag test**

On Windows cmd: `set AURUM_MENU_STYLE=legacy && python launcher.py`
Expected: Old Fibonacci menu renders; new Bloomberg does not appear. ESC exits normally.

Unset: `set AURUM_MENU_STYLE=` or close terminal.

- [ ] **Step 5: Write session log**

Per CLAUDE.md "REGRA PERMANENTE — SESSION LOG", create `docs/sessions/2026-04-11_HHMM.md` (use the actual UTC time at commit). Follow the exact template in CLAUDE.md. Highlight that no trading logic was changed (pure UI).

- [ ] **Step 6: Final commit**

```bash
git add docs/sessions/2026-04-11_*.md
git commit -m "docs(sessions): Bloomberg 3D main menu redesign — session log"
```

---

## Verification Checklist

- [ ] `python -m pytest tests/test_launcher_main_menu.py` → all pass
- [ ] `python smoke_test.py --quiet` → exit 0, no FAILs
- [ ] Manual UI walkthrough completed (11 steps)
- [ ] Legacy flag `AURUM_MENU_STYLE=legacy` shows old Fibonacci menu
- [ ] Default (no flag) shows Bloomberg 2×2 grid
- [ ] All 9 legacy destinations reachable in ≤2 keystrokes
- [ ] No new dependencies added (`pip list` unchanged, stdlib only)
- [ ] Session log written per CLAUDE.md rules
- [ ] No modifications to engines, signals, costs, or risk logic
