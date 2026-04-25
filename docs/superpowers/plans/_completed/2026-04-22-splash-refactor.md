# Splash Refactor — Institutional Density Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refatorar o splash screen do launcher para grid 2×3 de tiles (STATUS, RISK, MARKET PULSE, LAST SESSION, ENGINE ROSTER) com render offline-first em <150ms e atualização async via daemon thread.

**Architecture:** Offline-first render usa leituras de disco (keys.json, data/index.json, cache local). Daemon thread paralela busca dado live (market data via `core.data.market_data.MarketDataFetcher`, risk via cockpit_client) e atualiza canvas in-place via tags únicas por valor. `cancel_event` garante limpeza em `on_exit`.

**Tech Stack:** Python stdlib (`threading`, `json`, `pathlib`), Tkinter canvas, pytest, MagicMock. Reusa `core.ui.ui_palette`, `App._draw_panel`, `App._draw_aurum_logo`, `App._apply_canvas_scale`, `core.data.market_data.MarketDataFetcher`.

**Reference:** spec em `docs/superpowers/specs/2026-04-22-splash-refactor-design.md`. **Core de trading protegido** — zero mudança em `core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py`.

---

## File Structure

**New files:**
- `launcher_support/screens/splash_data.py` — módulo puro (sem Tkinter) com readers e cache. Testável sem GUI.
- `tests/launcher/test_splash_data.py` — unit tests das funções puras.

**Modified files:**
- `launcher_support/screens/splash.py` — reescrito. Importa `splash_data`. Tem o tile rendering e async orchestration.
- `tests/launcher/test_splash_screen.py` — atualizado: remove duplicatas, coordenadas novas, novos testes de tiles/async.

**Why this split:**
- `splash_data.py` é pure functions. Testa sem GUI, reusável, foca em file I/O.
- `splash.py` é UI + lifecycle + threading. Depende do Tk.
- Async fetch fica dentro de `splash.py` porque é lifecycle-coupled (cancel_event, after() marshalling).

---

## Task 1: Pure reader — `_read_last_session`

**Files:**
- Create: `launcher_support/screens/splash_data.py`
- Test: `tests/launcher/test_splash_data.py`

- [ ] **Step 1: Write the failing test**

Create `tests/launcher/test_splash_data.py`:

```python
"""Unit tests for pure data readers used by SplashScreen."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from launcher_support.screens.splash_data import read_last_session


def _write_index(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "index.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    return p


def test_read_last_session_returns_most_recent(tmp_path):
    idx = _write_index(tmp_path, [
        {"engine": "citadel", "timestamp": "2026-04-20T10:00:00",
         "n_trades": 3, "pnl": 120.0, "sharpe": 1.4},
        {"engine": "jump", "timestamp": "2026-04-21T15:30:00",
         "n_trades": 7, "pnl": 420.0, "sharpe": 2.1},
        {"engine": "citadel", "timestamp": "2026-04-19T09:00:00",
         "n_trades": 2, "pnl": -30.0, "sharpe": 0.5},
    ])
    result = read_last_session(idx)
    assert result is not None
    assert result["engine"] == "jump"
    assert result["timestamp"] == "2026-04-21T15:30:00"
    assert result["n_trades"] == 7
    assert result["pnl"] == 420.0


def test_read_last_session_missing_file_returns_none(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    assert read_last_session(missing) is None


def test_read_last_session_malformed_json_returns_none(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert read_last_session(p) is None


def test_read_last_session_empty_list_returns_none(tmp_path):
    idx = _write_index(tmp_path, [])
    assert read_last_session(idx) is None


def test_read_last_session_skips_rows_without_timestamp(tmp_path):
    idx = _write_index(tmp_path, [
        {"engine": "citadel", "n_trades": 1, "pnl": 50.0},
        {"engine": "jump", "timestamp": "2026-04-21T15:30:00",
         "n_trades": 7, "pnl": 420.0},
    ])
    result = read_last_session(idx)
    assert result is not None
    assert result["engine"] == "jump"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/launcher/test_splash_data.py -v`

Expected: ImportError or ModuleNotFoundError — module doesn't exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `launcher_support/screens/splash_data.py`:

```python
"""Pure data readers for SplashScreen. No Tkinter, no threading — testable headless.

Responsibilities:
  - read last session entry from data/index.json
  - read engine roster (status + last Sharpe)
  - load/save splash cache (market pulse between openings)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def read_last_session(index_path: Path) -> Optional[dict]:
    """Retorna o run mais recente do index.json, ou None se ausente/malformado."""
    try:
        with open(index_path, "r", encoding="utf-8") as fh:
            rows = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(rows, list) or not rows:
        return None
    dated = [r for r in rows if isinstance(r, dict) and r.get("timestamp")]
    if not dated:
        return None
    dated.sort(key=lambda r: r["timestamp"], reverse=True)
    return dated[0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/launcher/test_splash_data.py -v`

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/screens/splash_data.py tests/launcher/test_splash_data.py
git commit -m "feat(splash): add read_last_session pure reader"
```

---

## Task 2: Pure reader — `read_engine_roster`

**Files:**
- Modify: `launcher_support/screens/splash_data.py`
- Test: `tests/launcher/test_splash_data.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/launcher/test_splash_data.py`:

```python
from launcher_support.screens.splash_data import (
    read_engine_roster,
    ENGINE_ROSTER_LAYOUT,
)


def test_engine_roster_layout_has_11_engines():
    assert len(ENGINE_ROSTER_LAYOUT) == 11
    names = [row[0] for row in ENGINE_ROSTER_LAYOUT]
    assert "CITADEL" in names
    assert "PHI" in names
    assert "ORNSTEIN" in names
    # orchestrators & arquivados excluídos
    assert "MILLENNIUM" not in names
    assert "GRAHAM" not in names


def test_read_engine_roster_merges_sharpe_from_index(tmp_path):
    idx = _write_index(tmp_path, [
        {"engine": "citadel", "timestamp": "2026-04-20T10:00:00", "sharpe": 1.87},
        {"engine": "citadel", "timestamp": "2026-04-19T10:00:00", "sharpe": 1.50},
        {"engine": "jump",    "timestamp": "2026-04-20T10:00:00", "sharpe": 1.42},
    ])
    roster = read_engine_roster(idx)
    citadel = next(r for r in roster if r["name"] == "CITADEL")
    jump    = next(r for r in roster if r["name"] == "JUMP")
    phi     = next(r for r in roster if r["name"] == "PHI")
    assert citadel["sharpe"] == 1.87  # mais recente vence
    assert jump["sharpe"] == 1.42
    assert phi["sharpe"] is None      # no run registrado


def test_read_engine_roster_no_index_returns_labels_only(tmp_path):
    missing = tmp_path / "absent.json"
    roster = read_engine_roster(missing)
    assert len(roster) == 11
    assert all(r["sharpe"] is None for r in roster)
    assert all(r["status"] in {"✅", "⚠️", "🆕", "🔧", "⚪", "🔴"} for r in roster)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/launcher/test_splash_data.py::test_engine_roster_layout_has_11_engines -v`

Expected: ImportError — `ENGINE_ROSTER_LAYOUT` / `read_engine_roster` don't exist.

- [ ] **Step 3: Write minimal implementation**

Append to `launcher_support/screens/splash_data.py`:

```python
# OOS audit 2026-04-17 — (engine_key_in_index, DISPLAY_NAME, status_icon)
# ordenado: edges primeiro, mixed, novos, fora-da-bateria, falhados
ENGINE_ROSTER_LAYOUT: list[tuple[str, str, str]] = [
    ("citadel",     "CITADEL",     "✅"),
    ("jump",        "JUMP",        "✅"),
    ("renaissance", "RENAISS",     "⚠️"),
    ("bridgewater", "BRIDGEW",     "⚠️"),
    ("phi",         "PHI",         "🆕"),
    ("ornstein",    "ORNSTEIN",    "🔧"),
    ("twosigma",    "TWOSIGMA",    "⚪"),
    ("aqr",         "AQR",         "⚪"),
    ("deshaw",      "DE_SHAW",     "🔴"),
    ("kepos",       "KEPOS",       "🔴"),
    ("medallion",   "MEDALLION",   "🔴"),
]


def read_engine_roster(index_path: Path) -> list[dict]:
    """Cruza status hardcoded com Sharpe mais recente do index.json por engine.

    Retorna uma lista de dicts: [{name, status, sharpe}]. sharpe é None se
    nao ha run registrado para o engine.
    """
    try:
        with open(index_path, "r", encoding="utf-8") as fh:
            rows = json.load(fh)
        if not isinstance(rows, list):
            rows = []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        rows = []

    latest_by_engine: dict[str, tuple[str, float]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        key = r.get("engine")
        ts = r.get("timestamp")
        sh = r.get("sharpe")
        if not key or not ts or sh is None:
            continue
        try:
            sh_f = float(sh)
        except (TypeError, ValueError):
            continue
        cur = latest_by_engine.get(key)
        if cur is None or ts > cur[0]:
            latest_by_engine[key] = (ts, sh_f)

    out: list[dict] = []
    for key, display, status in ENGINE_ROSTER_LAYOUT:
        entry = latest_by_engine.get(key)
        out.append({
            "name": display,
            "status": status,
            "sharpe": entry[1] if entry else None,
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/launcher/test_splash_data.py -v`

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/screens/splash_data.py tests/launcher/test_splash_data.py
git commit -m "feat(splash): add read_engine_roster merging OOS status with index sharpe"
```

---

## Task 3: Cache — `load_splash_cache` / `save_splash_cache`

**Files:**
- Modify: `launcher_support/screens/splash_data.py`
- Test: `tests/launcher/test_splash_data.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/launcher/test_splash_data.py`:

```python
from launcher_support.screens.splash_data import (
    load_splash_cache,
    save_splash_cache,
)


def test_splash_cache_roundtrip(tmp_path):
    cache_path = tmp_path / "splash_cache.json"
    save_splash_cache(cache_path, {"btc": "67,240", "eth": "3,180"})
    assert load_splash_cache(cache_path) == {"btc": "67,240", "eth": "3,180"}


def test_splash_cache_load_missing_returns_empty_dict(tmp_path):
    assert load_splash_cache(tmp_path / "never.json") == {}


def test_splash_cache_load_corrupt_returns_empty_dict(tmp_path):
    p = tmp_path / "corrupt.json"
    p.write_text("not json {", encoding="utf-8")
    assert load_splash_cache(p) == {}


def test_splash_cache_save_creates_parent_dirs(tmp_path):
    cache_path = tmp_path / "nested" / "subdir" / "cache.json"
    save_splash_cache(cache_path, {"a": 1})
    assert cache_path.exists()
    assert load_splash_cache(cache_path) == {"a": 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/launcher/test_splash_data.py::test_splash_cache_roundtrip -v`

Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Append to `launcher_support/screens/splash_data.py`:

```python
def load_splash_cache(cache_path: Path) -> dict:
    """Le cache do mercado salvo na sessao anterior. Falha silenciosa → {}."""
    try:
        with open(cache_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_splash_cache(cache_path: Path, data: dict) -> None:
    """Escreve cache. Cria pasta pai se necessario. Falha silenciosa."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
    except OSError:
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/launcher/test_splash_data.py -v`

Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/screens/splash_data.py tests/launcher/test_splash_data.py
git commit -m "feat(splash): add load/save splash cache with defensive error handling"
```

---

## Task 4: Layout constants in SplashScreen

**Files:**
- Modify: `launcher_support/screens/splash.py`

- [ ] **Step 1: Replace old layout constants with grid constants**

Edit `launcher_support/screens/splash.py`. Replace the class-level constants block (lines ~16-40) with:

```python
class SplashScreen(Screen):
    # Canvas dimensions come from app._SPLASH_DESIGN_W / _H (920×640).

    # Top band + wordmark
    _CENTER_X = 460
    _TOP_RULE_Y = 30
    _BOTTOM_RULE_Y = 596
    _RULE_X1 = 48
    _RULE_X2 = 872

    _WORDMARK_BAND_Y = 46
    _WORDMARK_BAND_GAP = 78
    _LOGO_Y = 96
    _TITLE_Y = 132
    _SUBTITLE_Y = 152
    _TAGLINE_Y = 174
    _TAGLINE_DIVIDER_HALF = 170

    # Tile grid 2×3 (row 2 has wide tile in slot 2-3)
    _CONTENT_X1 = 48          # = _RULE_X1
    _CONTENT_X2 = 872         # = _RULE_X2
    _TILE_GAP = 16
    _TILE_W_SIMPLE = 264      # (824 - 2*16) / 3
    _TILE_W_WIDE = 544        # 2 simples + 1 gap
    _TILE_H = 150
    _TILE_PAD = 14
    _TILE_LINE_H = 19

    _ROW1_Y1 = 190
    _ROW1_Y2 = _ROW1_Y1 + _TILE_H       # 340
    _ROW2_Y1 = _ROW1_Y2 + _TILE_GAP     # 356
    _ROW2_Y2 = _ROW2_Y1 + _TILE_H       # 506

    _PROMPT_DIVIDER_Y = 530
    _PROMPT_Y = 552
```

- [ ] **Step 2: No test for constants; just verify they parse**

Run: `python -c "from launcher_support.screens.splash import SplashScreen; print(SplashScreen._TILE_W_SIMPLE, SplashScreen._ROW2_Y1)"`

Expected: `264 356`

- [ ] **Step 3: Commit**

```bash
git add launcher_support/screens/splash.py
git commit -m "refactor(splash): replace session-panel constants with tile-grid constants"
```

---

## Task 5: Tile helper — `_draw_splash_tile`

**Files:**
- Modify: `launcher_support/screens/splash.py`
- Test: `tests/launcher/test_splash_screen.py`

- [ ] **Step 1: Write the failing test**

Open `tests/launcher/test_splash_screen.py`. Replace the body `test_splash_draws_logo_panel_rows` test (lines 62-78) with:

```python
@pytest.mark.gui
def test_splash_draws_five_tiles(gui_root, fake_app, fake_conn):
    s = SplashScreen(parent=gui_root, app=fake_app, conn=fake_conn, tagline="TEST TAGLINE")
    s.mount()
    s.on_enter()
    # 5 panels = STATUS, RISK, MARKET PULSE, LAST SESSION, ENGINE ROSTER
    assert fake_app._draw_panel.call_count == 5
    titles = [call.kwargs.get("title", "") for call in fake_app._draw_panel.call_args_list]
    assert "STATUS" in titles
    assert "RISK" in titles
    assert "MARKET PULSE" in titles
    assert "LAST SESSION" in titles
    assert "ENGINE ROSTER" in titles


@pytest.mark.gui
def test_splash_tile_row2_wide_has_expected_width(gui_root, fake_app, fake_conn):
    s = SplashScreen(parent=gui_root, app=fake_app, conn=fake_conn, tagline="TEST TAGLINE")
    s.mount()
    s.on_enter()
    roster_call = next(
        c for c in fake_app._draw_panel.call_args_list
        if c.kwargs.get("title") == "ENGINE ROSTER"
    )
    x1, y1, x2, y2 = roster_call.args[1:5]
    assert x2 - x1 == SplashScreen._TILE_W_WIDE
    assert y2 - y1 == SplashScreen._TILE_H
```

Also delete lines 89-95 (`test_splash_hero_stays_above_session_panel` duplicate of `test_splash_intro_stays_above_session_panel`) — consolidated.

Update the remaining invariant test (lines 81-87):

```python
@pytest.mark.gui
def test_splash_wordmark_stays_above_row1(gui_root, fake_app, fake_conn):
    s = SplashScreen(parent=gui_root, app=fake_app, conn=fake_conn, tagline="TEST TAGLINE")
    s.mount()
    s.on_enter()
    assert s._TAGLINE_Y < s._ROW1_Y1
    assert s._ROW1_Y2 < s._ROW2_Y1
    assert s._ROW2_Y2 < s._PROMPT_Y
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/launcher/test_splash_screen.py::test_splash_draws_five_tiles -v`

Expected: FAIL — current `on_enter` draws 1 panel, not 5.

- [ ] **Step 3: Write minimal implementation**

Add a method `_draw_splash_tile` to `SplashScreen` (put it after `_draw_session_overview` or delete the old method):

```python
def _draw_splash_tile(
    self,
    canvas: tk.Canvas,
    *,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    title: str,
    rows: list[tuple[str, str, str, str]],
) -> None:
    """Desenha um tile do splash: panel + linhas kv com tags unicas por valor.

    rows: [(row_key, label, value, color)] — row_key vira tag
    'tile-{row_key}-value' para permitir itemconfigure async.
    """
    self.app._draw_panel(
        canvas, x1, y1, x2, y2,
        title=title, accent=AMBER, tag="splash",
    )
    x_label = x1 + self._TILE_PAD
    x_value = x1 + self._TILE_PAD + 96
    y_start = y1 + 36  # abaixo do title chip
    for i, (row_key, label, value, color) in enumerate(rows):
        yy = y_start + i * self._TILE_LINE_H
        canvas.create_text(
            x_label, yy, anchor="w", text=label,
            font=(FONT, 8), fill=DIM, tags=("splash", f"tile-{row_key}-label"),
        )
        canvas.create_text(
            x_value, yy, anchor="w", text=value,
            font=(FONT, 8, "bold"), fill=color,
            tags=("splash", f"tile-{row_key}-value"),
        )
```

Don't wire it up yet — just add the method.

- [ ] **Step 4: Run the parse-only check**

Run: `python -c "from launcher_support.screens.splash import SplashScreen; s = SplashScreen; print(hasattr(s, '_draw_splash_tile'))"`

Expected: `True`

- [ ] **Step 5: Commit**

```bash
git add launcher_support/screens/splash.py tests/launcher/test_splash_screen.py
git commit -m "refactor(splash): add _draw_splash_tile helper with per-value canvas tags"
```

(The 5-tiles test will still fail — that gets fixed in Task 7. We're staging the helper first.)

---

## Task 6: Replace `on_enter` offline body

**Files:**
- Modify: `launcher_support/screens/splash.py`

- [ ] **Step 1: Write the replacement `on_enter` + helpers**

In `launcher_support/screens/splash.py`, replace the entire body of `on_enter` (lines ~82-136) and delete `_draw_session_overview`, `_draw_overview_column_header`. Keep `_draw_wordmark` but adjust to new y-coordinates (see below).

First update imports at top of file:

```python
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from typing import Any

from core.ui.ui_palette import (
    AMBER, AMBER_B, AMBER_D, BG, BORDER, DIM, DIM2, FONT,
    GREEN, RED, WHITE,
)

from launcher_support.screens.base import Screen
from launcher_support.screens.splash_data import (
    ENGINE_ROSTER_LAYOUT,
    load_splash_cache,
    read_engine_roster,
    read_last_session,
    save_splash_cache,
)
```

Replace `__init__` body, adding two fields:

```python
def __init__(self, parent: tk.Misc, app: Any, conn: Any, tagline: str):
    super().__init__(parent)
    self.app = app
    self.conn = conn
    self.tagline = tagline
    self.canvas: tk.Canvas | None = None
    self._design_w = app._SPLASH_DESIGN_W
    self._design_h = app._SPLASH_DESIGN_H
    self._cancel_event: threading.Event | None = None
    self._index_path = Path("data/index.json")
    self._cache_path = Path("data/splash_cache.json")
```

Replace `on_enter`:

```python
def on_enter(self, **kwargs: Any) -> None:
    del kwargs
    app = self.app
    app.h_path.configure(text="")
    app.h_stat.configure(text="READY", fg=AMBER_B)
    app.f_lbl.configure(text="ENTER proceed  |  CLICK proceed  |  Q quit")

    canvas = self.canvas
    if canvas is None:
        return

    canvas.delete("splash")
    offline = self._read_offline_data()
    self._draw_offline_tiles(canvas, offline)

    self._bind(canvas, "<Button-1>", lambda e: app._splash_on_click())
    app._bind_global_nav()
    self._after(500, self._pulse_tick)
    self._bind(canvas, "<Configure>", self._render_resize)
    self._render_resize()
    self._kick_async_fetch()
```

Add `_read_offline_data` method:

```python
def _read_offline_data(self) -> dict:
    app = self.app
    try:
        st = self.conn.status_summary()
        market_val = st.get("market", "-")
    except Exception:
        market_val = "-"
    try:
        keys = app._load_json("keys.json")
        has_tg = bool(keys.get("telegram", {}).get("bot_token"))
        has_keys = bool(
            keys.get("demo", {}).get("api_key")
            or keys.get("testnet", {}).get("api_key")
        )
    except Exception:
        has_tg = False
        has_keys = False

    market_txt = "● LIVE" if market_val and market_val != "-" else "○ OFFLINE"
    market_col = GREEN if "LIVE" in market_txt else DIM
    conn_txt = "● BINANCE" if has_keys else "○ OFFLINE"
    conn_col = GREEN if has_keys else DIM
    tg_txt = "● ONLINE" if has_tg else "○ OFFLINE"
    tg_col = GREEN if has_tg else DIM

    session = read_last_session(self._index_path)
    roster = read_engine_roster(self._index_path)
    cache = load_splash_cache(self._cache_path)

    return {
        "status": {
            "market": (market_txt, market_col),
            "conn":   (conn_txt, conn_col),
            "tg":     (tg_txt, tg_col),
            "apilat": ("---", DIM),
        },
        "risk": {
            "killsw":  ("ARMED", RED),
            "ddvel":   ("---", DIM),
            "aggnot":  ("---", DIM),
            "gates":   ("---", DIM),
        },
        "pulse": {
            "btc":  (cache.get("btc",  "---"), cache.get("btc_col",  DIM)),
            "eth":  (cache.get("eth",  "---"), cache.get("eth_col",  DIM)),
            "reg":  (cache.get("reg",  "---"), cache.get("reg_col",  DIM)),
            "fund": (cache.get("fund", "---"), cache.get("fund_col", DIM)),
        },
        "session": session,
        "roster": roster,
    }
```

- [ ] **Step 2: Add `_draw_offline_tiles`**

```python
def _draw_offline_tiles(self, canvas: tk.Canvas, data: dict) -> None:
    self._draw_wordmark(canvas)
    gap = self._TILE_GAP
    w = self._TILE_W_SIMPLE

    # Row 1: STATUS | RISK | MARKET PULSE
    r1_x_starts = [
        self._CONTENT_X1,
        self._CONTENT_X1 + w + gap,
        self._CONTENT_X1 + 2 * (w + gap),
    ]
    self._draw_splash_tile(
        canvas,
        x1=r1_x_starts[0], y1=self._ROW1_Y1,
        x2=r1_x_starts[0] + w, y2=self._ROW1_Y2,
        title="STATUS",
        rows=[
            ("market", "MARKET", *data["status"]["market"]),
            ("conn",   "CONN",   *data["status"]["conn"]),
            ("tg",     "TG",     *data["status"]["tg"]),
            ("apilat", "API LAT", *data["status"]["apilat"]),
        ],
    )
    self._draw_splash_tile(
        canvas,
        x1=r1_x_starts[1], y1=self._ROW1_Y1,
        x2=r1_x_starts[1] + w, y2=self._ROW1_Y2,
        title="RISK",
        rows=[
            ("killsw", "KILL-SW", *data["risk"]["killsw"]),
            ("ddvel",  "DD VEL",  *data["risk"]["ddvel"]),
            ("aggnot", "AGG NOT", *data["risk"]["aggnot"]),
            ("gates",  "GATES",   *data["risk"]["gates"]),
        ],
    )
    self._draw_splash_tile(
        canvas,
        x1=r1_x_starts[2], y1=self._ROW1_Y1,
        x2=r1_x_starts[2] + w, y2=self._ROW1_Y2,
        title="MARKET PULSE",
        rows=[
            ("btc",  "BTC",  *data["pulse"]["btc"]),
            ("eth",  "ETH",  *data["pulse"]["eth"]),
            ("reg",  "REG",  *data["pulse"]["reg"]),
            ("fund", "FUND", *data["pulse"]["fund"]),
        ],
    )

    # Row 2: LAST SESSION (simples) | ENGINE ROSTER (wide)
    self._draw_last_session_tile(canvas, x1=self._CONTENT_X1, y1=self._ROW2_Y1, data=data["session"])
    self._draw_roster_tile(
        canvas,
        x1=self._CONTENT_X1 + w + gap,
        y1=self._ROW2_Y1,
        roster=data["roster"],
    )

    # Prompt
    canvas.create_line(
        self._RULE_X1, self._PROMPT_DIVIDER_Y, self._RULE_X2, self._PROMPT_DIVIDER_Y,
        fill=DIM2, width=1, tags="splash",
    )
    canvas.create_text(
        self._CENTER_X, self._PROMPT_Y,
        anchor="center", text="[ ENTER TO ACCESS DESK ]_",
        font=(FONT, 11, "bold"), fill=AMBER_B, tags=("splash", "prompt2"),
    )
```

- [ ] **Step 3: Add `_draw_last_session_tile` and `_draw_roster_tile`**

```python
def _draw_last_session_tile(self, canvas: tk.Canvas, *, x1: int, y1: int, data: dict | None) -> None:
    x2 = x1 + self._TILE_W_SIMPLE
    y2 = y1 + self._TILE_H
    if data is None:
        self.app._draw_panel(canvas, x1, y1, x2, y2, title="LAST SESSION", accent=AMBER, tag="splash")
        canvas.create_text(
            x1 + self._TILE_W_SIMPLE // 2, y1 + self._TILE_H // 2,
            anchor="center", text="NO SESSION DATA",
            font=(FONT, 9, "bold"), fill=DIM, tags="splash",
        )
        return
    ts_txt = str(data.get("timestamp", "-"))[:19].replace("T", " ")
    trades = int(data.get("n_trades") or 0)
    pnl_val = data.get("pnl")
    if isinstance(pnl_val, (int, float)):
        pnl_txt = f"{pnl_val:+.2f}"
        pnl_col = GREEN if pnl_val >= 0 else RED
    else:
        pnl_txt = "---"
        pnl_col = DIM
    engine_txt = str(data.get("engine", "-")).upper()[:10]
    self._draw_splash_tile(
        canvas,
        x1=x1, y1=y1, x2=x2, y2=y2,
        title="LAST SESSION",
        rows=[
            ("sess_ts",     "WHEN",    ts_txt,     WHITE),
            ("sess_engine", "ENGINE",  engine_txt, AMBER_B),
            ("sess_trades", "TRADES",  str(trades), WHITE),
            ("sess_pnl",    "PNL",     pnl_txt,    pnl_col),
        ],
    )


def _draw_roster_tile(self, canvas: tk.Canvas, *, x1: int, y1: int, roster: list[dict]) -> None:
    x2 = x1 + self._TILE_W_WIDE
    y2 = y1 + self._TILE_H
    self.app._draw_panel(canvas, x1, y1, x2, y2, title="ENGINE ROSTER", accent=AMBER, tag="splash")

    # 2 colunas × 6 linhas. Grid interno:
    col_w = (self._TILE_W_WIDE - 2 * self._TILE_PAD) // 2
    col_x = [x1 + self._TILE_PAD, x1 + self._TILE_PAD + col_w]
    line_h = 15
    y_start = y1 + 32

    for i, entry in enumerate(roster):
        col = i % 2
        row = i // 2
        x = col_x[col]
        yy = y_start + row * line_h
        name = entry["name"]
        status = entry["status"]
        sh = entry["sharpe"]
        sh_txt = f"{sh:>5.2f}" if isinstance(sh, (int, float)) else "  —  "
        canvas.create_text(
            x, yy, anchor="w",
            text=f"{name:<8} {status}  {sh_txt}",
            font=(FONT, 8, "bold"), fill=WHITE, tags=("splash", f"roster-{name.lower()}"),
        )
```

- [ ] **Step 4: Update `_draw_wordmark` for the new layout y-coordinates**

Replace the body of `_draw_wordmark` (was ~lines 159-252) with:

```python
def _draw_wordmark(self, canvas: tk.Canvas) -> None:
    logo_cx, logo_cy = self._CENTER_X, self._LOGO_Y
    band_gap = self._WORDMARK_BAND_GAP

    # top rule (full width)
    canvas.create_line(
        self._RULE_X1, self._TOP_RULE_Y, self._RULE_X2, self._TOP_RULE_Y,
        fill=AMBER_D, width=1, tags="splash",
    )
    # AURUM FINANCE wordmark band
    canvas.create_line(
        self._RULE_X1, self._WORDMARK_BAND_Y,
        self._CENTER_X - band_gap, self._WORDMARK_BAND_Y,
        fill=AMBER_D, width=1, tags="splash",
    )
    canvas.create_line(
        self._CENTER_X + band_gap, self._WORDMARK_BAND_Y,
        self._RULE_X2, self._WORDMARK_BAND_Y,
        fill=AMBER_D, width=1, tags="splash",
    )
    canvas.create_text(
        self._CENTER_X, self._WORDMARK_BAND_Y,
        anchor="center", text="AURUM FINANCE",
        font=(FONT, 7, "bold"), fill=AMBER, tags="splash",
    )

    self.app._draw_aurum_logo(canvas, logo_cx, logo_cy, scale=18, tag="splash")

    canvas.create_text(
        logo_cx, self._TITLE_Y, anchor="center", text="OPERATOR DESK",
        font=(FONT, 18, "bold"), fill=WHITE, tags="splash",
    )
    canvas.create_text(
        logo_cx, self._SUBTITLE_Y, anchor="center",
        text="Quant operations console",
        font=(FONT, 9), fill=DIM2, tags="splash",
    )
    canvas.create_line(
        logo_cx - self._TAGLINE_DIVIDER_HALF, self._TAGLINE_Y - 8,
        logo_cx + self._TAGLINE_DIVIDER_HALF, self._TAGLINE_Y - 8,
        fill=BORDER, width=1, tags="splash",
    )
    canvas.create_text(
        logo_cx, self._TAGLINE_Y, anchor="center", text=self.tagline,
        font=(FONT, 8), fill=DIM, tags="splash",
    )

    # bottom rule
    canvas.create_line(
        self._RULE_X1, self._BOTTOM_RULE_Y, self._RULE_X2, self._BOTTOM_RULE_Y,
        fill=DIM2, width=1, tags="splash",
    )
```

- [ ] **Step 5: Stub out `_kick_async_fetch` (implemented later in Task 9)**

```python
def _kick_async_fetch(self) -> None:
    """Stub: async fetch lands in Task 9. Por enquanto no-op."""
    pass
```

- [ ] **Step 6: Delete `_draw_session_overview` and `_draw_overview_column_header`**

Remove the two obsolete methods (were at lines ~254-339 in the old file).

- [ ] **Step 7: Keep `build` method as-is**

No change to `build` — canvas creation is unchanged.

- [ ] **Step 8: Run the tile rendering test**

Run: `pytest tests/launcher/test_splash_screen.py::test_splash_draws_five_tiles tests/launcher/test_splash_screen.py::test_splash_tile_row2_wide_has_expected_width -v`

Expected: 2 passed.

- [ ] **Step 9: Run the full splash test suite**

Run: `pytest tests/launcher/test_splash_screen.py tests/launcher/test_splash_data.py -v`

Expected: all pass. If `test_splash_builds_canvas`, `test_splash_header_labels_set_on_enter`, `test_splash_pulse_timer_cancelled_on_exit`, `test_splash_wordmark_stays_above_row1` fail, diagnose. Do NOT ship broken tests.

- [ ] **Step 10: Commit**

```bash
git add launcher_support/screens/splash.py tests/launcher/test_splash_screen.py
git commit -m "refactor(splash): grid 2x3 offline render (stub async kick)"
```

---

## Task 7: Offline-only data render test

**Files:**
- Modify: `tests/launcher/test_splash_screen.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/launcher/test_splash_screen.py`:

```python
@pytest.mark.gui
def test_splash_renders_with_missing_index_json(gui_root, fake_app, fake_conn, tmp_path, monkeypatch):
    """Sem data/index.json → tiles mostram NO SESSION DATA + roster sem Sharpe, no crash."""
    monkeypatch.chdir(tmp_path)  # data/ nao existe no cwd isolado
    s = SplashScreen(parent=gui_root, app=fake_app, conn=fake_conn, tagline="ISO")
    s.mount()
    s.on_enter()
    # LAST SESSION deveria exibir fallback:
    texts = [
        s.canvas.itemcget(item, "text")
        for item in s.canvas.find_withtag("splash")
        if s.canvas.type(item) == "text"
    ]
    assert any("NO SESSION DATA" in t for t in texts)
```

- [ ] **Step 2: Run test**

Run: `pytest tests/launcher/test_splash_screen.py::test_splash_renders_with_missing_index_json -v`

Expected: PASS (logic from Task 6 already handles this path).

- [ ] **Step 3: Commit**

```bash
git add tests/launcher/test_splash_screen.py
git commit -m "test(splash): verify offline render fallback when index.json missing"
```

---

## Task 8: Async worker — market pulse fetch

**Files:**
- Modify: `launcher_support/screens/splash.py`
- Test: `tests/launcher/test_splash_screen.py`

- [ ] **Step 1: Add `_fetch_market_pulse` method**

In `launcher_support/screens/splash.py`, add after `_read_offline_data`:

```python
def _fetch_market_pulse(self) -> dict:
    """Bloqueante. Pode levantar. Retorna dict com chaves btc/eth/reg/fund."""
    from core.data.market_data import MarketDataFetcher
    fetcher = MarketDataFetcher(["BTCUSDT", "ETHUSDT"])
    fetcher.fetch_all()  # timeout interno 5s
    tickers = fetcher.tickers
    fund = fetcher.funding_avg()
    out: dict[str, tuple[str, str]] = {}
    for sym, key in (("BTCUSDT", "btc"), ("ETHUSDT", "eth")):
        t = tickers.get(sym)
        if not t:
            out[key] = ("---", DIM)
            continue
        price = t["price"]
        pct = t["pct"]
        arrow = "▲" if pct >= 0 else "▼"
        col = GREEN if pct >= 0 else RED
        out[key] = (f"{price:>8,.0f} {pct:+5.2f}% {arrow}", col)
    if fund is not None:
        fund_pct = fund * 100.0
        out["fund"] = (f"{fund_pct:+.3f}% /8h", WHITE)
    else:
        out["fund"] = ("---", DIM)
    out["reg"] = ("---", DIM)  # v1: sem regime macro; Task 12 pode adicionar
    return out
```

- [ ] **Step 2: Add `_apply_live_data`**

```python
def _apply_live_data(self, data: dict) -> None:
    """UI-thread callback. Atualiza valores por tag."""
    if self._cancel_event is not None and self._cancel_event.is_set():
        return
    canvas = self.canvas
    if canvas is None:
        return
    for key, (text, color) in data.items():
        tag = f"tile-{key}-value"
        try:
            canvas.itemconfigure(tag, text=text, fill=color)
        except tk.TclError:
            return  # canvas destruído
```

- [ ] **Step 3: Add test**

Append to `tests/launcher/test_splash_screen.py`:

```python
from launcher_support.screens.splash import SplashScreen as _Splash


@pytest.mark.gui
def test_splash_apply_live_data_updates_tagged_value(gui_root, fake_app, fake_conn):
    s = SplashScreen(parent=gui_root, app=fake_app, conn=fake_conn, tagline="T")
    s.mount()
    s.on_enter()
    s._apply_live_data({"btc": ("67,240 +2.30% ▲", "#00ff00")})
    items = s.canvas.find_withtag("tile-btc-value")
    assert items, "tile-btc-value tag must exist on canvas"
    assert s.canvas.itemcget(items[0], "text") == "67,240 +2.30% ▲"
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/launcher/test_splash_screen.py::test_splash_apply_live_data_updates_tagged_value -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/screens/splash.py tests/launcher/test_splash_screen.py
git commit -m "feat(splash): _apply_live_data updates canvas via per-value tags"
```

---

## Task 9: Async orchestration — thread kick + cancel

**Files:**
- Modify: `launcher_support/screens/splash.py`
- Test: `tests/launcher/test_splash_screen.py`

- [ ] **Step 1: Replace stub `_kick_async_fetch` with real impl**

```python
def _kick_async_fetch(self) -> None:
    """Dispara daemon thread que busca dados live e atualiza canvas."""
    self._cancel_event = threading.Event()
    thread = threading.Thread(target=self._fetch_live_worker, daemon=True)
    thread.start()

def _fetch_live_worker(self) -> None:
    """Roda off UI thread. Tenta market pulse; marshalls updates via after()."""
    if self._cancel_event is not None and self._cancel_event.is_set():
        return
    try:
        pulse = self._fetch_market_pulse()
    except Exception:
        pulse = None
    if self._cancel_event is not None and self._cancel_event.is_set():
        return
    if pulse:
        try:
            self.container.after(0, lambda d=pulse: self._apply_live_data(d))
            self._save_pulse_to_cache(pulse)
        except tk.TclError:
            return  # container destroyed

def _save_pulse_to_cache(self, pulse: dict) -> None:
    plain = {k: v[0] for k, v in pulse.items()}
    for k, v in pulse.items():
        plain[f"{k}_col"] = v[1]
    save_splash_cache(self._cache_path, plain)
```

- [ ] **Step 2: Extend `on_exit` for cancel**

Replace `on_exit` by adding the cancel-event trigger before the parent cleanup:

```python
def on_exit(self) -> None:
    if self._cancel_event is not None:
        self._cancel_event.set()
    super().on_exit()
```

- [ ] **Step 3: Add test — cancel event set on exit**

Append to `tests/launcher/test_splash_screen.py`:

```python
@pytest.mark.gui
def test_splash_cancel_event_set_on_exit(gui_root, fake_app, fake_conn):
    s = SplashScreen(parent=gui_root, app=fake_app, conn=fake_conn, tagline="T")
    s.mount()
    s.on_enter()
    assert s._cancel_event is not None
    assert not s._cancel_event.is_set()
    s.on_exit()
    assert s._cancel_event.is_set()
```

- [ ] **Step 4: Add test — apply_live_data ignores call when cancelled**

```python
@pytest.mark.gui
def test_splash_apply_live_data_noop_after_cancel(gui_root, fake_app, fake_conn):
    s = SplashScreen(parent=gui_root, app=fake_app, conn=fake_conn, tagline="T")
    s.mount()
    s.on_enter()
    before = s.canvas.itemcget(s.canvas.find_withtag("tile-btc-value")[0], "text")
    s._cancel_event.set()
    s._apply_live_data({"btc": ("SHOULD_NOT_APPLY", "#fff")})
    after = s.canvas.itemcget(s.canvas.find_withtag("tile-btc-value")[0], "text")
    assert after == before
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/launcher/test_splash_screen.py::test_splash_cancel_event_set_on_exit tests/launcher/test_splash_screen.py::test_splash_apply_live_data_noop_after_cancel -v`

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add launcher_support/screens/splash.py tests/launcher/test_splash_screen.py
git commit -m "feat(splash): daemon thread + cancel_event for safe async live updates"
```

---

## Task 10: Integration — full splash suite green

**Files:** (no edits unless test failures reveal bugs)

- [ ] **Step 1: Run full splash test suite**

Run: `pytest tests/launcher/test_splash_screen.py tests/launcher/test_splash_data.py -v`

Expected: all green. If any failure, diagnose — do not skip.

- [ ] **Step 2: Run smoke test**

Run: `python smoke_test.py --quiet`

Expected: previous count (156/156 or current baseline) minus 0 new failures.

- [ ] **Step 3: Inspect line count**

Run: `wc -l launcher_support/screens/splash.py launcher_support/screens/splash_data.py`

Expected: `splash.py` < 500 lines. If exceeded, move `_read_offline_data` helpers or `_fetch_market_pulse` into `splash_data.py` + re-run tests.

- [ ] **Step 4: Commit (only if any fix applied in steps 1-3)**

```bash
git add -p
git commit -m "fix(splash): <describe>"
```

If nothing to commit, skip.

---

## Task 11: Manual walkthrough

**Files:** none (manual test).

- [ ] **Step 1: Launch the launcher**

Run: `python launcher.py`

- [ ] **Step 2: Validate splash — visual checklist**

- [ ] Wordmark "AURUM FINANCE" band no topo
- [ ] Logo + "OPERATOR DESK" title + "Quant operations console" subtitle
- [ ] Tagline abaixo do divisor
- [ ] Row 1: tiles STATUS, RISK, MARKET PULSE visíveis lado a lado
- [ ] Row 2: tile LAST SESSION (narrow) + ENGINE ROSTER (wide) lado a lado
- [ ] STATUS tile mostra estado real (MARKET, CONN, TG com dot colorido)
- [ ] RISK tile mostra KILL-SW ARMED em vermelho
- [ ] MARKET PULSE começa com "---" e atualiza em 1-3s com BTC/ETH price
- [ ] LAST SESSION mostra último run do `data/index.json` OU "NO SESSION DATA"
- [ ] ENGINE ROSTER mostra 11 engines com status icon + Sharpe
- [ ] Prompt "[ ENTER TO ACCESS DESK ]_" pulsa a cada 500ms
- [ ] Click em qualquer lugar → main menu Fibonacci abre
- [ ] ENTER → main menu abre
- [ ] Q → app sai limpo, sem erro no console

- [ ] **Step 3: Validate async doesn't crash on early exit**

Abrir splash, aguardar <1s, pressionar Q rapidamente. Não deve aparecer stack trace no console sobre `itemconfigure on destroyed widget`.

- [ ] **Step 4: Validate diff is clean**

Run: `git diff --name-only main`

Expected: só estes paths:
- `launcher_support/screens/splash.py`
- `launcher_support/screens/splash_data.py`
- `tests/launcher/test_splash_screen.py`
- `tests/launcher/test_splash_data.py`
- `docs/superpowers/specs/2026-04-22-splash-refactor-design.md`
- `docs/superpowers/plans/2026-04-22-splash-refactor.md`

Zero arquivo em `core/`, `engines/`, `config/params.py`. Se aparecer, reverter.

- [ ] **Step 5: Commit final cleanup if needed**

Se alguma coisa mudou, commit. Se não, pronto.

- [ ] **Step 6: Gerar session log e daily log**

Per CLAUDE.md regra permanente: gerar `docs/sessions/2026-04-22_HHMM.md` e atualizar `docs/days/2026-04-22.md`.

```bash
git add docs/sessions/ docs/days/
git commit -m "docs(session): splash institutional-density refactor — 2026-04-22"
```

---

## Appendix A — Engine roster layout (reference)

Hardcoded em `splash_data.ENGINE_ROSTER_LAYOUT`. Ordem pre-registrada:

| Col 1          | Col 2          |
|---------------|---------------|
| CITADEL ✅     | JUMP ✅        |
| RENAISS ⚠️     | BRIDGEW ⚠️     |
| PHI 🆕         | ORNSTEIN 🔧    |
| TWOSIGMA ⚪    | AQR ⚪         |
| DE_SHAW 🔴    | KEPOS 🔴      |
| MEDALLION 🔴  | (vazio)       |

Atualizar este layout quando o status OOS mudar (e.g., PHI sai de overfit_audit → ✅/🔴, ORNSTEIN termina tuning).

---

## Appendix B — What NOT to do

- **Não tocar em `core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py`.** Zero mudança no trading core.
- **Não sobrescrever `config/keys.json`**. Splash só LÊ via `app._load_json("keys.json")` (leitura existente).
- **Não usar `_draw_kv_rows` da App pra valores live-updatáveis** — ele não tagueia per-valor. Use `_draw_splash_tile` com tags `tile-{key}-value`.
- **Não bloquear UI thread com network.** Todo fetch live roda em daemon thread.
- **Não rebuild o canvas em every async update.** Só `itemconfigure` on tagged items.
- **Não crashar em nenhum caminho de erro.** Todo fetch swallows exception e deixa "---".

---

## Appendix C — Deferred para v1.1

Estes valores ficam como "---" no v1 entregue por este plano. São follow-up dedicado:

| Item | Spec ref | Razão do deferral |
|---|---|---|
| RISK · DD VEL, AGG NOT, GATES live | §3.3 Tile 2 | Exige `CockpitClient` configurado com tokens do `keys.json` + tratamento de `CircuitOpen`. Escopo grande o suficiente pra valer uma Task dedicada. |
| STATUS · API LAT live | §3.3 Tile 1 | Depende do cockpit ou de uma métrica de ping. Sem cockpit, sem número pra mostrar. |
| MARKET PULSE · REG (regime macro) | §3.3 Tile 3 | Exige fetch de klines 1d BTC + cálculo de slope200 na thread worker; não é barato. |

**Plano de v1.1 (futuro, não neste ciclo):**
1. Adicionar `_fetch_cockpit_risk()` que constrói `CockpitClient` de `keys.json`, chama `healthz()` + endpoint de trading (quando existir) e mede round-trip pra API LAT
2. Adicionar `_fetch_regime()` que busca klines 1d BTC (via `MarketDataFetcher` ou direto `requests`) e computa slope200 simples
3. Estender `_fetch_live_worker` pra rodar os 3 fetches em paralelo (`ThreadPoolExecutor` ou threads separadas)
4. Estender `_apply_live_data` (já suporta qualquer key — só adicionar entradas no dict)
5. Tests: mock `CockpitClient.healthz` → valida RISK tile atualiza

**Critério pra promover de v1.1 pra v1:** se o João olhar o splash v1 e disser "faltou dado de risco aí", a v1.1 vira Task do próximo ciclo. Se o splash v1 já satisfaz, v1.1 fica no backlog indefinido.
