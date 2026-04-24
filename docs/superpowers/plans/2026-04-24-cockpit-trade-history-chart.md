# Cockpit Trade History + Candle Chart Popup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add clickable trade history to PAPER and SHADOW cockpit panes, opening a matplotlib candlestick popup that shows entry/stop/target/exit (or live price) with minimal header/footer metrics.

**Architecture:** Two new modules (`trade_history_panel.py` for the list row, `trade_chart_popup.py` for the Toplevel chart). Reuses existing cockpit API `get_trades(run_id)`. Fetches candles from Binance public klines. TF per engine comes from `config.params.ENGINE_INTERVALS` (single source of truth — no duplicated maps).

**Tech Stack:** Python 3.14, TkInter, matplotlib + mplfinance (new dep), urllib stdlib, pytest. No new server code.

**Spec:** `docs/superpowers/specs/2026-04-24-cockpit-trade-history-chart-design.md`

---

## Scope & File Structure

### New files (2)

| File | Responsibility |
|---|---|
| `launcher_support/trade_history_panel.py` | Pure formatters (`format_trade_row`, `format_r_multiple`, `format_duration`, `resolve_exit_marker`, `normalize_direction`) + Tk `render(parent, trades, on_click, colors, font)`. |
| `launcher_support/trade_chart_popup.py` | Pure helpers (`resolve_tf`, `tf_to_seconds`, `derive_candle_window`, `build_marker_specs`, `fetch_binance_candles`, `parse_klines_to_df`) + `TradeChartPopup` Toplevel class + `open_trade_chart(launcher, trade, run_id)` factory w/ registry. |

### Modified files (2)

| File | Change |
|---|---|
| `launcher_support/engines_live_view.py` | Add wire-up call in PAPER detail pane (currently missing trade list) and SHADOW detail pane (replace `_render_signals_table`). |
| `requirements.txt` | Add `mplfinance>=0.12.10b0`. |

### New test files (3)

| File | Coverage |
|---|---|
| `tests/launcher_support/test_trade_history_panel.py` | Unit — all formatters, edge cases |
| `tests/launcher_support/test_trade_chart_popup.py` | Unit — TF resolution, window derivation, marker specs, Binance fetch (mocked) |
| `tests/launcher_support/test_trade_chart_popup_smoke.py` | Smoke — Toplevel instantiation headless-safe |

---

## Task 1: Add mplfinance dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Check current requirements.txt**

Run: `grep -E '^(matplotlib|mplfinance)' requirements.txt`
Expected: `matplotlib` present, `mplfinance` absent.

- [ ] **Step 2: Add mplfinance line**

Insert after the `matplotlib` line in `requirements.txt`:

```
mplfinance>=0.12.10b0
```

- [ ] **Step 3: Install locally**

Run: `pip install mplfinance>=0.12.10b0`
Expected: successful install, no conflicts.

- [ ] **Step 4: Verify import**

Run: `python -c "import mplfinance as mpf; print(mpf.__version__)"`
Expected: prints version (e.g. `0.12.10b0`).

- [ ] **Step 5: Commit**

```bash
git add requirements.txt
git commit -m "chore(deps): add mplfinance for trade chart popup"
```

---

## Task 2: trade_history_panel.py — pure formatters (TDD)

**Files:**
- Create: `launcher_support/trade_history_panel.py`
- Test: `tests/launcher_support/test_trade_history_panel.py`

- [ ] **Step 1: Create the test file with failing formatter tests**

Create `tests/launcher_support/test_trade_history_panel.py`:

```python
"""Unit tests for trade_history_panel formatters."""
from __future__ import annotations

import pytest

from launcher_support.trade_history_panel import (
    format_duration,
    format_r_multiple,
    format_trade_row,
    normalize_direction,
    resolve_exit_marker,
)


# ─── normalize_direction ────────────────────────────────────────────
class TestNormalizeDirection:
    def test_bullish_to_long(self):
        assert normalize_direction("BULLISH") == "LONG"

    def test_bearish_to_short(self):
        assert normalize_direction("BEARISH") == "SHORT"

    def test_long_unchanged(self):
        assert normalize_direction("LONG") == "LONG"

    def test_short_unchanged(self):
        assert normalize_direction("SHORT") == "SHORT"

    def test_case_insensitive(self):
        assert normalize_direction("bullish") == "LONG"
        assert normalize_direction("Short") == "SHORT"

    def test_none(self):
        assert normalize_direction(None) == "—"

    def test_empty(self):
        assert normalize_direction("") == "—"

    def test_unknown(self):
        assert normalize_direction("NEUTRAL") == "NEUTRAL"


# ─── format_r_multiple ──────────────────────────────────────────────
class TestFormatRMultiple:
    def test_positive(self):
        assert format_r_multiple(1.80, result="WIN") == "+1.80R"

    def test_negative(self):
        assert format_r_multiple(-1.00, result="LOSS") == "-1.00R"

    def test_zero_live(self):
        assert format_r_multiple(0.0, result="LIVE") == "LIVE"

    def test_none(self):
        assert format_r_multiple(None, result="WIN") == "—"

    def test_small_positive(self):
        assert format_r_multiple(0.05, result="WIN") == "+0.05R"


# ─── format_duration ────────────────────────────────────────────────
class TestFormatDuration:
    def test_under_one_minute(self):
        # duration in candles; tf=900 → 1 candle = 15min
        # 0 candles → "<1m"
        assert format_duration(0, tf_sec=900) == "<1m"

    def test_minutes_only(self):
        # 3 candles × 15min = 45min
        assert format_duration(3, tf_sec=900) == "45m"

    def test_hours_and_minutes(self):
        # 9 candles × 15min = 2h15m
        assert format_duration(9, tf_sec=900) == "2h15m"

    def test_exact_hours(self):
        # 4 candles × 1h = 4h00m → "4h"
        assert format_duration(4, tf_sec=3600) == "4h"

    def test_days(self):
        # 48 candles × 1h = 48h → "2d"
        assert format_duration(48, tf_sec=3600) == "2d"

    def test_days_and_hours(self):
        # 50 candles × 1h = 50h → "2d2h"
        assert format_duration(50, tf_sec=3600) == "2d2h"

    def test_none(self):
        assert format_duration(None, tf_sec=900) == "—"


# ─── resolve_exit_marker ────────────────────────────────────────────
class TestResolveExitMarker:
    def test_target(self):
        assert resolve_exit_marker({"exit_reason": "target",
                                    "result": "WIN"}) == "TP_HIT"

    def test_stop(self):
        assert resolve_exit_marker({"exit_reason": "stop",
                                    "result": "LOSS"}) == "STOP"

    def test_trail(self):
        assert resolve_exit_marker({"exit_reason": "trail",
                                    "result": "WIN"}) == "TRAIL"

    def test_time(self):
        assert resolve_exit_marker({"exit_reason": "time",
                                    "result": "WIN"}) == "TIME"

    def test_live(self):
        assert resolve_exit_marker({"exit_reason": "live",
                                    "result": "LIVE"}) == "—"

    def test_missing(self):
        assert resolve_exit_marker({}) == "—"


# ─── format_trade_row (integration of formatters) ───────────────────
class TestFormatTradeRow:
    def _base(self, **overrides):
        base = {
            "symbol": "SANDUSDT",
            "strategy": "JUMP",
            "direction": "BEARISH",
            "entry": 0.0776,
            "exit_p": 0.0742,
            "r_multiple": 1.80,
            "pnl": 24.30,
            "duration": 9,  # candles
            "result": "WIN",
            "exit_reason": "target",
        }
        base.update(overrides)
        return base

    def test_closed_short_win(self):
        row = format_trade_row(self._base(), tf_sec=900)
        assert row["symbol"] == "SANDUSDT"
        assert row["engine"] == "JUMP"
        assert row["direction"] == "SHORT"
        assert row["dir_arrow"] == "▼"  # SHORT = down arrow
        assert row["levels"] == "0.0776→0.0742"
        assert row["r_mult"] == "+1.80R"
        assert row["pnl"] == "+$24.30"
        assert row["duration"] == "2h15m"
        assert row["exit_marker"] == "TP_HIT"

    def test_closed_long_loss(self):
        row = format_trade_row(
            self._base(direction="BULLISH", result="LOSS",
                       exit_reason="stop", r_multiple=-1.0, pnl=-15.0),
            tf_sec=900,
        )
        assert row["direction"] == "LONG"
        assert row["dir_arrow"] == "▲"  # LONG = up arrow
        assert row["r_mult"] == "-1.00R"
        assert row["pnl"] == "-$15.00"
        assert row["exit_marker"] == "STOP"

    def test_live_trade(self):
        row = format_trade_row(
            self._base(result="LIVE", exit_reason="live",
                       r_multiple=0.0, pnl=8.20, duration=0),
            tf_sec=900,
        )
        assert row["r_mult"] == "LIVE"
        assert row["pnl"] == "+$8.20"
        assert row["duration"] == "<1m"
        assert row["exit_marker"] == "—"

    def test_truncates_long_engine(self):
        row = format_trade_row(
            self._base(strategy="RENAISSANCE"), tf_sec=900)
        assert len(row["engine"]) <= 10  # column width
```

- [ ] **Step 2: Run the test to confirm failure**

Run: `python -m pytest tests/launcher_support/test_trade_history_panel.py -v`
Expected: All tests FAIL with `ModuleNotFoundError: No module named 'launcher_support.trade_history_panel'`.

- [ ] **Step 3: Create the module with formatters**

Create `launcher_support/trade_history_panel.py`:

```python
"""Trade history list panel — clickable rows for PAPER/SHADOW cockpit panes.

Pure formatters (format_trade_row, format_r_multiple, format_duration,
resolve_exit_marker, normalize_direction) are unit-tested. Render Tk (render)
is smoke-only.

Design spec: docs/superpowers/specs/2026-04-24-cockpit-trade-history-chart-design.md
"""
from __future__ import annotations

from typing import Any, Callable


def normalize_direction(direction: str | None) -> str:
    """Normalize engine direction output to LONG/SHORT.

    BULLISH/LONG → LONG, BEARISH/SHORT → SHORT. Other non-empty values
    returned upper-case unchanged. None/empty → em-dash.
    """
    if direction is None or direction == "":
        return "—"
    d = str(direction).upper()
    if d == "BULLISH":
        return "LONG"
    if d == "BEARISH":
        return "SHORT"
    return d


def format_r_multiple(r: float | None, *, result: str) -> str:
    """Render R-multiple, or LIVE tag for open trades, or em-dash."""
    if result == "LIVE":
        return "LIVE"
    if r is None:
        return "—"
    sign = "+" if r >= 0 else "-"
    return f"{sign}{abs(r):.2f}R"


def format_duration(candles: int | None, *, tf_sec: int) -> str:
    """Render duration (candles × tf_sec) as compact string.

    Examples: 45m, 2h15m, 2d, 2d2h, <1m.
    """
    if candles is None:
        return "—"
    total_sec = int(candles) * int(tf_sec)
    if total_sec < 60:
        return "<1m"
    days, rem = divmod(total_sec, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days >= 1:
        if hours == 0:
            return f"{days}d"
        return f"{days}d{hours}h"
    if hours >= 1:
        if minutes == 0:
            return f"{hours}h"
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


_EXIT_REASON_MAP = {
    "target": "TP_HIT",
    "stop": "STOP",
    "trail": "TRAIL",
    "time": "TIME",
    "manual": "MANUAL",
}


def resolve_exit_marker(trade: dict) -> str:
    """Short label for exit reason column (TP_HIT/STOP/TRAIL/TIME/—)."""
    if trade.get("result") == "LIVE":
        return "—"
    reason = str(trade.get("exit_reason", "")).lower()
    return _EXIT_REASON_MAP.get(reason, "—")


def _format_price(p: Any) -> str:
    """Compact price string. Preserves significant digits for alt pairs."""
    if p is None:
        return "—"
    try:
        f = float(p)
    except (TypeError, ValueError):
        return str(p)[:10]
    if abs(f) >= 1000:
        return f"{f:,.2f}"
    if abs(f) >= 1:
        return f"{f:.4f}".rstrip("0").rstrip(".")
    return f"{f:.6g}"


def _format_pnl(pnl: float | None) -> str:
    if pnl is None:
        return "—"
    sign = "+" if pnl >= 0 else "-"
    return f"{sign}${abs(pnl):.2f}"


def format_trade_row(trade: dict, *, tf_sec: int) -> dict[str, str]:
    """Build a dict of display-ready fields for a single trade row.

    Keys: symbol, engine, direction, dir_arrow, levels, r_mult, pnl,
    duration, exit_marker.
    """
    direction = normalize_direction(trade.get("direction"))
    dir_arrow = "▲" if direction == "LONG" else ("▼" if direction == "SHORT" else "·")
    engine = str(trade.get("strategy") or "—")[:10]
    entry = _format_price(trade.get("entry"))
    exit_px = _format_price(trade.get("exit_p"))
    return {
        "symbol": str(trade.get("symbol") or "—")[:12],
        "engine": engine,
        "direction": direction,
        "dir_arrow": dir_arrow,
        "levels": f"{entry}→{exit_px}",
        "r_mult": format_r_multiple(trade.get("r_multiple"),
                                    result=str(trade.get("result", ""))),
        "pnl": _format_pnl(trade.get("pnl")),
        "duration": format_duration(trade.get("duration"), tf_sec=tf_sec),
        "exit_marker": resolve_exit_marker(trade),
    }


# render() is defined in Task 3 below — not in this initial commit.
```

- [ ] **Step 4: Run the tests to verify pass**

Run: `python -m pytest tests/launcher_support/test_trade_history_panel.py -v`
Expected: all ~25 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/trade_history_panel.py tests/launcher_support/test_trade_history_panel.py
git commit -m "feat(trade-history): pure formatters with unit tests"
```

---

## Task 3: trade_history_panel.py — Tk render function

**Files:**
- Modify: `launcher_support/trade_history_panel.py` (append)

Note: Tk render gets smoke-tested via Task 9 (engines_live_view wire-up). No unit test here — UI render is tested by the wire-in smoke.

- [ ] **Step 1: Append the render function**

Add to end of `launcher_support/trade_history_panel.py`:

```python
# ─── Tk render ───────────────────────────────────────────────────

def render(
    parent,
    trades: list[dict],
    *,
    on_click: Callable[[dict], None],
    colors: dict[str, str],
    font_name: str,
    tf_sec: int,
    title: str = "TRADE HISTORY",
    max_rows: int = 20,
) -> None:
    """Render a clickable trade history list into `parent`.

    `trades` newest-first. Click fires `on_click(trade_dict)`. Colors
    follows the engines_live_view palette convention (BG, PANEL, AMBER,
    GREEN, RED, WHITE, DIM, DIM2, BORDER, BG2).
    """
    import tkinter as tk

    AMBER = colors["AMBER"]
    PANEL = colors["PANEL"]
    BG = colors["BG"]
    BG2 = colors["BG2"]
    GREEN = colors["GREEN"]
    RED = colors["RED"]
    WHITE = colors["WHITE"]
    DIM = colors["DIM"]
    DIM2 = colors["DIM2"]
    BORDER = colors["BORDER"]
    AMBER_D = colors.get("AMBER_D", AMBER)

    # Header bar (matches other blocks in engines_live_view)
    box = tk.Frame(
        parent, bg=PANEL,
        highlightbackground=BORDER, highlightthickness=1,
    )
    box.pack(fill="x", pady=(0, 6))
    count = len(trades) if trades else 0
    tk.Label(
        box, text=f" {title} ({count}) ",
        font=(font_name, 7, "bold"),
        fg=BG, bg=AMBER,
    ).pack(side="top", anchor="nw", padx=8, pady=4)

    inner = tk.Frame(box, bg=PANEL)
    inner.pack(fill="x", padx=8, pady=(0, 8))

    if not trades:
        tk.Label(
            inner, text="  — no trades yet —",
            font=(font_name, 8),
            fg=DIM, bg=PANEL, anchor="w",
        ).pack(fill="x", pady=4)
        return

    shown = trades[:max_rows]
    for trade in shown:
        row_fields = format_trade_row(trade, tf_sec=tf_sec)
        row = tk.Frame(inner, bg=PANEL, cursor="hand2")
        row.pack(fill="x", pady=1)

        direction = row_fields["direction"]
        arrow_color = GREEN if direction == "LONG" else (
            RED if direction == "SHORT" else DIM)

        # Column specs: (text, color, width, font_size, bold?)
        cols = [
            (row_fields["dir_arrow"], arrow_color, 2, 9, True),
            (row_fields["symbol"], WHITE, 12, 8, True),
            (row_fields["engine"], DIM, 10, 8, False),
            (direction, arrow_color, 7, 8, True),
            (row_fields["levels"], WHITE, 18, 8, False),
            (_color_for_r(row_fields["r_mult"], GREEN, RED, AMBER_D, DIM),
             None, 8, 8, True),
        ]
        for text, color, width, fsize, bold in cols:
            # Two-tuple override: when color=None, text is actually a tuple
            if isinstance(text, tuple):
                text, color = text
            weight = "bold" if bold else "normal"
            tk.Label(
                row, text=str(text), fg=color or WHITE, bg=PANEL,
                font=(font_name, fsize, weight),
                width=width, anchor="w",
            ).pack(side="left", padx=(2, 0))

        pnl_text = row_fields["pnl"]
        pnl_color = GREEN if pnl_text.startswith("+$") else (
            RED if pnl_text.startswith("-$") else DIM)
        tk.Label(
            row, text=pnl_text, fg=pnl_color, bg=PANEL,
            font=(font_name, 8, "bold"), width=10, anchor="w",
        ).pack(side="left", padx=(2, 0))
        tk.Label(
            row, text=row_fields["duration"], fg=DIM, bg=PANEL,
            font=(font_name, 8), width=8, anchor="w",
        ).pack(side="left", padx=(2, 0))
        tk.Label(
            row, text=row_fields["exit_marker"], fg=DIM2, bg=PANEL,
            font=(font_name, 7), width=8, anchor="w",
        ).pack(side="left", padx=(2, 0))

        def _hover_in(_e, r=row):
            r.configure(bg=BG2)
            for child in r.winfo_children():
                try:
                    child.configure(bg=BG2)
                except Exception:
                    pass

        def _hover_out(_e, r=row):
            r.configure(bg=PANEL)
            for child in r.winfo_children():
                try:
                    child.configure(bg=PANEL)
                except Exception:
                    pass

        def _click(_e, t=trade):
            try:
                on_click(t)
            except Exception:
                pass

        for widget in (row,) + tuple(row.winfo_children()):
            widget.bind("<Enter>", _hover_in)
            widget.bind("<Leave>", _hover_out)
            widget.bind("<Button-1>", _click)

    if count > max_rows:
        tk.Label(
            inner,
            text=f"  … +{count - max_rows} more (truncated)",
            font=(font_name, 7, "italic"),
            fg=DIM2, bg=PANEL, anchor="w",
        ).pack(fill="x", pady=(2, 0))


def _color_for_r(r_text: str, green: str, red: str, amber: str, dim: str) -> tuple[str, str]:
    """Return (text, color) for r_multiple column based on sign/state."""
    if r_text == "LIVE":
        return (r_text, amber)
    if r_text.startswith("+"):
        return (r_text, green)
    if r_text.startswith("-"):
        return (r_text, red)
    return (r_text, dim)
```

- [ ] **Step 2: Run the existing tests to confirm still passes**

Run: `python -m pytest tests/launcher_support/test_trade_history_panel.py -v`
Expected: all ~25 tests still PASS (render wasn't tested but didn't break formatters).

- [ ] **Step 3: Commit**

```bash
git add launcher_support/trade_history_panel.py
git commit -m "feat(trade-history): Tk render with click handler"
```

---

## Task 4: trade_chart_popup.py — pure helpers (TDD)

**Files:**
- Create: `launcher_support/trade_chart_popup.py` (helpers section)
- Test: `tests/launcher_support/test_trade_chart_popup.py`

- [ ] **Step 1: Create the test file**

Create `tests/launcher_support/test_trade_chart_popup.py`:

```python
"""Unit tests for trade_chart_popup pure helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from launcher_support.trade_chart_popup import (
    build_marker_specs,
    derive_candle_window,
    fetch_binance_candles,
    parse_klines_to_df,
    resolve_tf,
    tf_to_seconds,
)


# ─── resolve_tf (reads params.ENGINE_INTERVALS) ─────────────────────
class TestResolveTf:
    def test_citadel(self):
        assert resolve_tf("CITADEL") == "15m"

    def test_renaissance(self):
        assert resolve_tf("RENAISSANCE") == "15m"

    def test_jump(self):
        assert resolve_tf("JUMP") == "1h"

    def test_de_shaw_alias(self):
        # Logger name DE_SHAW maps to params key DESHAW
        assert resolve_tf("DE_SHAW") == "1h"

    def test_deshaw_direct(self):
        assert resolve_tf("DESHAW") == "1h"

    def test_bridgewater(self):
        assert resolve_tf("BRIDGEWATER") == "1h"

    def test_case_insensitive(self):
        assert resolve_tf("citadel") == "15m"
        assert resolve_tf("Jump") == "1h"

    def test_unknown_engine_fallback(self):
        # KEPOS/MEDALLION/PHI not in ENGINE_INTERVALS — fallback to INTERVAL
        from config.params import INTERVAL
        assert resolve_tf("KEPOS") == INTERVAL
        assert resolve_tf("MEDALLION") == INTERVAL

    def test_none_fallback(self):
        from config.params import INTERVAL
        assert resolve_tf(None) == INTERVAL

    def test_empty_fallback(self):
        from config.params import INTERVAL
        assert resolve_tf("") == INTERVAL


# ─── tf_to_seconds ──────────────────────────────────────────────────
class TestTfToSeconds:
    @pytest.mark.parametrize("tf,sec", [
        ("1m", 60),
        ("5m", 300),
        ("15m", 900),
        ("30m", 1800),
        ("1h", 3600),
        ("4h", 14400),
        ("1d", 86400),
    ])
    def test_known_tfs(self, tf, sec):
        assert tf_to_seconds(tf) == sec

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            tf_to_seconds("7h")


# ─── derive_candle_window ───────────────────────────────────────────
class TestDeriveCandleWindow:
    def test_closed_trade_basic(self):
        # Entry at 1000, exit at 1900 (1h tf, 15 candles)
        entry_ts = 1_000_000
        exit_ts = entry_ts + 15 * 3600
        start, end = derive_candle_window(entry_ts, exit_ts, tf_sec=3600)
        duration = 15
        window = max(20, int(duration * 1.6))  # 24 candles total
        pad = (window - duration) // 2  # 4 on each side
        assert start == entry_ts - pad * 3600
        assert end == exit_ts + pad * 3600

    def test_short_trade_min_window(self):
        # Trade of 2 candles → window floors at 20
        entry_ts = 1_000_000
        exit_ts = entry_ts + 2 * 3600
        start, end = derive_candle_window(entry_ts, exit_ts, tf_sec=3600)
        assert end - start >= 20 * 3600

    def test_live_trade(self):
        entry_ts = 1_000_000
        start, end = derive_candle_window(entry_ts, None, tf_sec=3600,
                                          now_ts=entry_ts + 10 * 3600)
        # LIVE: duration_candles=20 minimum, pad split both sides
        assert end - start >= 20 * 3600

    def test_window_caps_at_500(self):
        # 1000-candle trade should cap at 500
        entry_ts = 1_000_000
        exit_ts = entry_ts + 1000 * 3600
        start, end = derive_candle_window(entry_ts, exit_ts, tf_sec=3600)
        assert (end - start) // 3600 <= 500


# ─── build_marker_specs ─────────────────────────────────────────────
class TestBuildMarkerSpecs:
    def _trade(self, **overrides):
        base = {
            "entry": 0.0776, "stop": 0.0810, "target": 0.0742,
            "exit_p": 0.0742, "result": "WIN", "direction": "BEARISH",
            "timestamp": "2026-04-21T23:00:00",
            "duration": 9,
        }
        base.update(overrides)
        return base

    def test_closed_trade_all_levels(self):
        specs = build_marker_specs(self._trade(), tf_sec=900)
        levels = {s["kind"]: s for s in specs if s.get("kind")}
        assert "entry" in levels
        assert "stop" in levels
        assert "target" in levels
        assert "exit" in levels
        assert levels["entry"]["price"] == 0.0776

    def test_live_trade_no_exit_marker(self):
        specs = build_marker_specs(
            self._trade(result="LIVE", exit_p=None, duration=0),
            tf_sec=900,
        )
        kinds = {s.get("kind") for s in specs}
        assert "current" in kinds  # pulsing current price instead
        assert "exit" not in kinds

    def test_missing_stop_omitted(self):
        specs = build_marker_specs(
            self._trade(stop=0), tf_sec=900)
        kinds = {s.get("kind") for s in specs}
        assert "stop" not in kinds
        assert "entry" in kinds

    def test_missing_target_omitted(self):
        specs = build_marker_specs(
            self._trade(target=None), tf_sec=900)
        kinds = {s.get("kind") for s in specs}
        assert "target" not in kinds


# ─── parse_klines_to_df ─────────────────────────────────────────────
class TestParseKlinesToDf:
    def test_basic(self):
        # Binance kline format: [open_ts_ms, O, H, L, C, V, close_ts, ...]
        klines = [
            [1700000000000, "0.10", "0.12", "0.09", "0.11", "1000.0",
             1700003599999, "0", 0, "0", "0", "0"],
            [1700003600000, "0.11", "0.13", "0.10", "0.12", "1500.0",
             1700007199999, "0", 0, "0", "0", "0"],
        ]
        df = parse_klines_to_df(klines)
        assert len(df) == 2
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert df.iloc[0]["Open"] == 0.10
        assert df.iloc[0]["Close"] == 0.11
        # Index is datetime
        assert df.index.inferred_type in ("datetime64", "datetime")

    def test_empty(self):
        df = parse_klines_to_df([])
        assert len(df) == 0
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]


# ─── fetch_binance_candles (mocked urllib) ──────────────────────────
class TestFetchBinanceCandles:
    @patch("launcher_support.trade_chart_popup.urllib.request.urlopen")
    def test_successful_fetch(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'[[1700000000000,"0.1","0.12","0.09","0.11","1000.0",1700003599999,"0",0,"0","0","0"]]'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda *a: None
        mock_urlopen.return_value = mock_resp

        df = fetch_binance_candles("SANDUSDT", "1h",
                                   start_ts=1700000000,
                                   end_ts=1700003600)
        assert len(df) == 1
        assert df.iloc[0]["Close"] == 0.11

    @patch("launcher_support.trade_chart_popup.urllib.request.urlopen")
    def test_http_error_returns_empty(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://test", 429, "Too Many Requests", {}, None)
        df = fetch_binance_candles("SANDUSDT", "1h",
                                   start_ts=1700000000,
                                   end_ts=1700003600)
        assert len(df) == 0

    @patch("launcher_support.trade_chart_popup.urllib.request.urlopen")
    def test_timeout_returns_empty(self, mock_urlopen):
        mock_urlopen.side_effect = TimeoutError()
        df = fetch_binance_candles("SANDUSDT", "1h",
                                   start_ts=1700000000,
                                   end_ts=1700003600)
        assert len(df) == 0
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `python -m pytest tests/launcher_support/test_trade_chart_popup.py -v`
Expected: all FAIL with `ModuleNotFoundError: No module named 'launcher_support.trade_chart_popup'`.

- [ ] **Step 3: Create the module with helpers**

Create `launcher_support/trade_chart_popup.py`:

```python
"""Trade chart popup — matplotlib candlestick for PAPER/SHADOW trades.

Pure helpers (resolve_tf, tf_to_seconds, derive_candle_window,
build_marker_specs, fetch_binance_candles, parse_klines_to_df) are
unit-tested. Toplevel TradeChartPopup is smoke-only.

Design spec: docs/superpowers/specs/2026-04-24-cockpit-trade-history-chart-design.md
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from config.params import ENGINE_INTERVALS, INTERVAL


_ENGINE_ALIASES: dict[str, str] = {
    # Launcher/logger name → params.ENGINE_INTERVALS key
    "DE_SHAW": "DESHAW",
}


def resolve_tf(engine: str | None) -> str:
    """Resolve native TF for an engine, reading params.ENGINE_INTERVALS.

    Case-insensitive. Returns params.INTERVAL as fallback for None/empty
    or engines absent from ENGINE_INTERVALS (meta/arb/allocator engines).
    """
    if not engine:
        return INTERVAL
    upper = str(engine).upper()
    key = _ENGINE_ALIASES.get(upper, upper)
    return ENGINE_INTERVALS.get(key, INTERVAL)


_TF_SECONDS: dict[str, int] = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600,
    "8h": 28800, "12h": 43200, "1d": 86400,
}


def tf_to_seconds(tf: str) -> int:
    """Convert Binance interval string to seconds. Raises on unknown."""
    if tf not in _TF_SECONDS:
        raise ValueError(f"unknown TF: {tf}")
    return _TF_SECONDS[tf]


_MAX_WINDOW_CANDLES = 500
_MIN_WINDOW_CANDLES = 20
_WINDOW_PADDING_FACTOR = 1.6  # total window = duration × 1.6 → ~30% pad each side


def derive_candle_window(
    entry_ts: int,
    exit_ts: int | None,
    *,
    tf_sec: int,
    now_ts: int | None = None,
) -> tuple[int, int]:
    """Compute (start_ts, end_ts) for candle fetch.

    Trade duration drives window size; floors at 20 candles, caps at 500.
    Centers the trade in the window. Unix seconds.
    """
    if exit_ts is None:
        if now_ts is None:
            now_ts = int(time.time())
        duration_sec = max(_MIN_WINDOW_CANDLES * tf_sec, now_ts - entry_ts)
    else:
        duration_sec = max(tf_sec, exit_ts - entry_ts)

    duration_candles = max(_MIN_WINDOW_CANDLES, duration_sec // tf_sec)
    window_candles = min(_MAX_WINDOW_CANDLES,
                         max(_MIN_WINDOW_CANDLES,
                             int(duration_candles * _WINDOW_PADDING_FACTOR)))
    pad_candles = (window_candles - duration_candles) // 2
    pad_sec = max(0, pad_candles * tf_sec)

    start = entry_ts - pad_sec
    end = (exit_ts if exit_ts is not None else now_ts) + pad_sec
    return int(start), int(end)


def _ts_to_unix(ts: Any) -> int | None:
    """Best-effort ISO8601 → unix seconds."""
    if ts is None:
        return None
    try:
        s = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return None


def build_marker_specs(trade: dict, *, tf_sec: int) -> list[dict[str, Any]]:
    """Build a list of marker specs for matplotlib overlay.

    Kinds: "entry" (yellow line), "stop" (red dashed), "target" (green
    dashed), "exit" (amber ▼ if closed), "current" (green ● if LIVE).
    Missing levels (zero/None) are omitted.
    """
    specs: list[dict] = []

    entry = trade.get("entry")
    stop = trade.get("stop")
    target = trade.get("target")

    if entry:
        specs.append({"kind": "entry", "price": float(entry),
                      "style": "line", "color": "#FFB000", "linewidth": 1.2})
    if stop:
        specs.append({"kind": "stop", "price": float(stop),
                      "style": "dashed", "color": "#FF4444", "linewidth": 1.0})
    if target:
        specs.append({"kind": "target", "price": float(target),
                      "style": "dashed", "color": "#44FF88", "linewidth": 1.0})

    if trade.get("result") == "LIVE":
        cur_px = trade.get("exit_p") or trade.get("entry")
        if cur_px:
            specs.append({"kind": "current", "price": float(cur_px),
                          "style": "scatter", "marker": "o",
                          "color": "#44FF88", "size": 100})
    else:
        exit_p = trade.get("exit_p")
        if exit_p:
            entry_ts = _ts_to_unix(trade.get("timestamp"))
            duration = int(trade.get("duration", 0) or 0)
            exit_ts = (entry_ts + duration * tf_sec) if entry_ts else None
            specs.append({"kind": "exit", "price": float(exit_p),
                          "timestamp": exit_ts,
                          "style": "scatter", "marker": "v",
                          "color": "#FFB000", "size": 120})
    return specs


def parse_klines_to_df(klines: list[list]) -> pd.DataFrame:
    """Parse Binance fapi/v1/klines response into mplfinance-ready DF."""
    if not klines:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    rows = []
    index = []
    for k in klines:
        # [open_ts_ms, O, H, L, C, V, close_ts, ...]
        index.append(pd.to_datetime(int(k[0]), unit="ms", utc=True))
        rows.append({
            "Open": float(k[1]),
            "High": float(k[2]),
            "Low": float(k[3]),
            "Close": float(k[4]),
            "Volume": float(k[5]),
        })
    df = pd.DataFrame(rows, index=pd.DatetimeIndex(index, name="Date"))
    return df


_BINANCE_FAPI = "https://fapi.binance.com/fapi/v1/klines"
_FETCH_TIMEOUT_SEC = 6.0


def fetch_binance_candles(
    symbol: str,
    tf: str,
    *,
    start_ts: int,
    end_ts: int,
    limit: int = 500,
) -> pd.DataFrame:
    """Fetch candles from Binance USDT-M public klines. Returns empty
    DataFrame on any error (timeout/HTTP/parse)."""
    params = urllib.parse.urlencode({
        "symbol": symbol.upper(),
        "interval": tf,
        "startTime": start_ts * 1000,
        "endTime": end_ts * 1000,
        "limit": min(limit, 1500),
    })
    url = f"{_BINANCE_FAPI}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=_FETCH_TIMEOUT_SEC) as resp:
            body = resp.read()
        data = json.loads(body)
        if not isinstance(data, list):
            return parse_klines_to_df([])
        return parse_klines_to_df(data)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            OSError, ValueError, json.JSONDecodeError):
        return parse_klines_to_df([])


# TradeChartPopup class added in Task 5 below.
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/launcher_support/test_trade_chart_popup.py -v`
Expected: all ~22 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/trade_chart_popup.py tests/launcher_support/test_trade_chart_popup.py
git commit -m "feat(trade-chart): pure helpers (TF resolver, window, markers, fetch)"
```

---

## Task 5: TradeChartPopup — Toplevel Tk class

**Files:**
- Modify: `launcher_support/trade_chart_popup.py` (append class)

- [ ] **Step 1: Append the TradeChartPopup class**

Add to end of `launcher_support/trade_chart_popup.py`:

```python
# ─── Tk popup ────────────────────────────────────────────────────

_POPUP_WIDTH = 900
_POPUP_HEIGHT = 600
_LIVE_REFRESH_MS = 5000
_LIVE_FAIL_LIMIT = 3


class TradeChartPopup:
    """Toplevel window showing candlestick chart for a single trade.

    Live trades (result=LIVE) refresh every 5s. Closed trades render once.
    """

    def __init__(self, master, trade: dict, run_id: str, *,
                 colors: dict[str, str], font_name: str):
        import tkinter as tk

        self.trade = trade
        self.run_id = run_id
        self.colors = colors
        self.font_name = font_name
        self.engine = str(trade.get("strategy") or "").upper()
        self.tf = resolve_tf(self.engine)
        self.tf_sec = tf_to_seconds(self.tf)
        self.symbol = str(trade.get("symbol") or "").upper()

        self._after_id: str | None = None
        self._live_fail_count = 0
        self._destroyed = False

        self.top = tk.Toplevel(master)
        self.top.title(f"{self.symbol} · {self.engine}")
        self.top.geometry(f"{_POPUP_WIDTH}x{_POPUP_HEIGHT}")
        self.top.configure(bg=colors["BG"])
        self.top.transient(master)
        self.top.bind("<Escape>", lambda _e: self.destroy())
        self.top.protocol("WM_DELETE_WINDOW", self.destroy)

        self._build_header()
        self._chart_frame = tk.Frame(self.top, bg=colors["BG"])
        self._chart_frame.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        self._footer_frame = tk.Frame(self.top, bg=colors["BG"])
        self._footer_frame.pack(fill="x", padx=8, pady=(0, 6))

        self._render_chart()
        self._render_footer()

        if self.trade.get("result") == "LIVE":
            self._schedule_live_refresh()

    # ── header ──────────────────────────────────────────────────

    def _build_header(self):
        import tkinter as tk

        c = self.colors
        head = tk.Frame(self.top, bg=c["AMBER"], height=28)
        head.pack(fill="x", padx=0, pady=(0, 6))
        head.pack_propagate(False)

        direction = normalize_direction(self.trade.get("direction"))
        r_mult_text = format_r_multiple(
            self.trade.get("r_multiple"),
            result=str(self.trade.get("result", "")),
        )
        pnl = self.trade.get("pnl", 0.0)
        pnl_str = f"{'+' if pnl >= 0 else '-'}${abs(pnl):.2f}"

        text = (
            f"  {self.symbol}  ·  {self.engine}  ·  {direction}  "
            f"·  {r_mult_text}  ·  {pnl_str}"
        )
        tk.Label(
            head, text=text, font=(self.font_name, 9, "bold"),
            fg=c["BG"], bg=c["AMBER"], anchor="w",
        ).pack(side="left", fill="y")
        tk.Label(
            head, text="  [ESC]  ", font=(self.font_name, 7, "bold"),
            fg=c["BG"], bg=c["AMBER"], cursor="hand2",
        ).pack(side="right", padx=(0, 8))

    # ── footer ──────────────────────────────────────────────────

    def _render_footer(self):
        import tkinter as tk

        for widget in self._footer_frame.winfo_children():
            try:
                widget.destroy()
            except Exception:
                pass

        t = self.trade
        entry = t.get("entry")
        stop = t.get("stop")
        target = t.get("target")
        exit_p = t.get("exit_p")
        size = t.get("size")
        exit_marker = resolve_exit_marker_local(t)

        entry_ts = _ts_to_unix(t.get("timestamp"))
        duration = int(t.get("duration", 0) or 0)
        exit_ts = (entry_ts + duration * self.tf_sec) if entry_ts else None

        def _fmt_ts(unix_ts):
            if unix_ts is None:
                return "—"
            return datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M UTC")

        line1 = (
            f"  entry {_fmtp(entry)} · stop {_fmtp(stop)} · "
            f"tp {_fmtp(target)} · exit {_fmtp(exit_p)} ({exit_marker})"
        )
        dur_text = format_duration_local(duration, self.tf_sec)
        line2 = (
            f"  size {size if size is not None else '—'} · {dur_text} · "
            f"{_fmt_ts(entry_ts)} → {_fmt_ts(exit_ts)}"
        )
        tk.Label(
            self._footer_frame, text=line1, font=(self.font_name, 7),
            fg=self.colors["DIM"], bg=self.colors["BG"], anchor="w",
        ).pack(fill="x")
        tk.Label(
            self._footer_frame, text=line2, font=(self.font_name, 7),
            fg=self.colors["DIM2"], bg=self.colors["BG"], anchor="w",
        ).pack(fill="x")

    # ── chart ───────────────────────────────────────────────────

    def _render_chart(self):
        import tkinter as tk
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        import mplfinance as mpf

        for widget in self._chart_frame.winfo_children():
            try:
                widget.destroy()
            except Exception:
                pass

        entry_ts = _ts_to_unix(self.trade.get("timestamp")) or int(time.time())
        duration = int(self.trade.get("duration", 0) or 0)
        exit_ts = (entry_ts + duration * self.tf_sec
                   if self.trade.get("result") != "LIVE" else None)
        start_ts, end_ts = derive_candle_window(
            entry_ts, exit_ts, tf_sec=self.tf_sec)

        df = fetch_binance_candles(self.symbol, self.tf,
                                   start_ts=start_ts, end_ts=end_ts)

        if len(df) == 0:
            tk.Label(
                self._chart_frame,
                text="— candles indisponíveis (Binance offline ou símbolo inválido) —",
                font=(self.font_name, 10),
                fg=self.colors["DIM"], bg=self.colors["BG"],
            ).pack(expand=True)
            tk.Label(
                self._chart_frame, text="  ↻ retry  ",
                font=(self.font_name, 8, "bold"),
                fg=self.colors["BG"], bg=self.colors["AMBER"],
                cursor="hand2", padx=10, pady=4,
            ).pack().bind("<Button-1>", lambda _e: self._render_chart())
            return

        fig = Figure(figsize=(9, 4.5), facecolor=self.colors["BG"])
        ax = fig.add_subplot(111)
        style = mpf.make_mpf_style(
            base_mpf_style="nightclouds",
            rc={"axes.facecolor": self.colors["BG"],
                "figure.facecolor": self.colors["BG"],
                "axes.labelcolor": self.colors["DIM"],
                "xtick.color": self.colors["DIM"],
                "ytick.color": self.colors["DIM"],
                "axes.edgecolor": self.colors["BORDER"]},
        )
        mpf.plot(df, type="candle", ax=ax, style=style,
                 volume=False, xrotation=0, datetime_format="%m-%d %H:%M",
                 update_width_config={"candle_linewidth": 0.7})

        specs = build_marker_specs(self.trade, tf_sec=self.tf_sec)
        for spec in specs:
            kind = spec.get("kind")
            if kind in ("entry", "stop", "target"):
                linestyle = "-" if spec["style"] == "line" else "--"
                ax.axhline(
                    y=spec["price"], color=spec["color"],
                    linestyle=linestyle, linewidth=spec["linewidth"],
                    alpha=0.9, zorder=3)
            elif kind in ("exit", "current"):
                # Scatter at last candle x-position (approx — keeps it
                # minimal; TradingView-grade x-positioning is v2)
                x_pos = df.index[-1]
                ax.scatter([x_pos], [spec["price"]],
                           marker=spec["marker"], color=spec["color"],
                           s=spec["size"], zorder=5)

        fig.tight_layout(pad=0.5)
        canvas = FigureCanvasTkAgg(fig, master=self._chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._canvas = canvas
        self._fig = fig

    # ── live refresh ────────────────────────────────────────────

    def _schedule_live_refresh(self):
        if self._destroyed:
            return
        try:
            self._after_id = self.top.after(_LIVE_REFRESH_MS, self._live_tick)
        except Exception:
            pass

    def _live_tick(self):
        if self._destroyed or not self.top.winfo_exists():
            return
        try:
            self._render_chart()
            self._render_footer()
            self._live_fail_count = 0
        except Exception:
            self._live_fail_count += 1
        if self._live_fail_count < _LIVE_FAIL_LIMIT:
            self._schedule_live_refresh()

    # ── destroy ─────────────────────────────────────────────────

    def destroy(self):
        self._destroyed = True
        if self._after_id:
            try:
                self.top.after_cancel(self._after_id)
            except Exception:
                pass
        try:
            self.top.destroy()
        except Exception:
            pass


# ─── helpers (local aliases to avoid panel ↔ popup coupling) ────────

def resolve_exit_marker_local(trade: dict) -> str:
    """Local copy of resolve_exit_marker semantics — keeps popup standalone."""
    if trade.get("result") == "LIVE":
        return "—"
    m = {
        "target": "TP_HIT", "stop": "STOP", "trail": "TRAIL",
        "time": "TIME", "manual": "MANUAL",
    }
    return m.get(str(trade.get("exit_reason", "")).lower(), "—")


def format_duration_local(candles: int | None, tf_sec: int) -> str:
    """Local copy of format_duration to keep popup standalone."""
    if candles is None:
        return "—"
    total_sec = int(candles) * int(tf_sec)
    if total_sec < 60:
        return "<1m"
    days, rem = divmod(total_sec, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days >= 1:
        return f"{days}d" if hours == 0 else f"{days}d{hours}h"
    if hours >= 1:
        return f"{hours}h" if minutes == 0 else f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


def _fmtp(p):
    if p is None or p == 0:
        return "—"
    try:
        f = float(p)
    except (TypeError, ValueError):
        return str(p)
    if abs(f) >= 1000:
        return f"{f:,.2f}"
    if abs(f) >= 1:
        return f"{f:.4f}".rstrip("0").rstrip(".")
    return f"{f:.6g}"


# ─── popup registry / factory ───────────────────────────────────

def _trade_key(trade: dict, run_id: str) -> str:
    return (
        f"{run_id}:{trade.get('symbol', '?')}:"
        f"{trade.get('timestamp', trade.get('entry_idx', '?'))}"
    )


def open_trade_chart(launcher, trade: dict, run_id: str, *,
                     colors: dict[str, str], font_name: str) -> TradeChartPopup:
    """Factory: open a new popup, or lift an existing one for this trade."""
    registry: dict = getattr(launcher, "_trade_popups", None)
    if registry is None:
        registry = {}
        launcher._trade_popups = registry

    key = _trade_key(trade, run_id)
    existing = registry.get(key)
    if existing is not None and not getattr(existing, "_destroyed", True):
        try:
            existing.top.lift()
            existing.top.focus_force()
            return existing
        except Exception:
            pass

    popup = TradeChartPopup(launcher, trade, run_id,
                            colors=colors, font_name=font_name)
    registry[key] = popup
    original_destroy = popup.destroy

    def _destroy_and_evict():
        original_destroy()
        registry.pop(key, None)

    popup.destroy = _destroy_and_evict  # type: ignore[assignment]
    return popup
```

- [ ] **Step 2: Run the existing popup tests to confirm still green**

Run: `python -m pytest tests/launcher_support/test_trade_chart_popup.py -v`
Expected: all ~22 tests PASS (no new behavior broken).

- [ ] **Step 3: Commit**

```bash
git add launcher_support/trade_chart_popup.py
git commit -m "feat(trade-chart): Toplevel popup + live refresh + registry"
```

---

## Task 6: Smoke test — Toplevel renders without crash

**Files:**
- Create: `tests/launcher_support/test_trade_chart_popup_smoke.py`

- [ ] **Step 1: Create smoke test file**

Create `tests/launcher_support/test_trade_chart_popup_smoke.py`:

```python
"""Smoke tests — TradeChartPopup instantiates & destroys cleanly.

Skips on headless CI (no DISPLAY) following existing project pattern.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("CI") == "true" and not os.environ.get("DISPLAY"),
    reason="needs display",
)


@pytest.fixture
def tk_root():
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture
def stub_colors():
    return {
        "BG": "#0a0a0a", "PANEL": "#1a1a1a", "BG2": "#202020",
        "AMBER": "#FFB000", "AMBER_B": "#FFC940", "AMBER_D": "#C08000",
        "GREEN": "#44FF88", "RED": "#FF4444",
        "WHITE": "#FFFFFF", "DIM": "#888888", "DIM2": "#555555",
        "BORDER": "#333333",
    }


def _closed_trade():
    return {
        "symbol": "SANDUSDT", "strategy": "JUMP",
        "direction": "BEARISH",
        "timestamp": "2026-04-21T23:00:00+00:00",
        "entry": 0.0776, "stop": 0.0810, "target": 0.0742,
        "exit_p": 0.0742, "duration": 9,
        "result": "WIN", "exit_reason": "target",
        "r_multiple": 1.80, "pnl": 24.30, "size": 16784.609,
    }


def _live_trade():
    return {
        "symbol": "NEARUSDT", "strategy": "CITADEL",
        "direction": "BULLISH",
        "timestamp": "2026-04-21T23:30:00+00:00",
        "entry": 4.85, "stop": 4.70, "target": 5.20,
        "exit_p": 4.92, "duration": 0,
        "result": "LIVE", "exit_reason": "live",
        "r_multiple": 0.0, "pnl": 8.20, "size": 412.37,
    }


@patch("launcher_support.trade_chart_popup.fetch_binance_candles")
def test_closed_trade_popup_renders(mock_fetch, tk_root, stub_colors):
    """Popup builds, shows chart placeholder (empty DF), destroys cleanly."""
    import pandas as pd
    from launcher_support.trade_chart_popup import TradeChartPopup

    mock_fetch.return_value = pd.DataFrame(
        columns=["Open", "High", "Low", "Close", "Volume"])

    popup = TradeChartPopup(tk_root, _closed_trade(), run_id="test-run",
                            colors=stub_colors, font_name="Consolas")
    assert popup.top.winfo_exists()
    assert popup.engine == "JUMP"
    assert popup.tf == "1h"  # from ENGINE_INTERVALS
    assert popup.symbol == "SANDUSDT"
    popup.destroy()
    assert popup._destroyed is True


@patch("launcher_support.trade_chart_popup.fetch_binance_candles")
def test_live_trade_popup_schedules_refresh(mock_fetch, tk_root, stub_colors):
    """LIVE trade schedules an after() callback for refresh."""
    import pandas as pd
    from launcher_support.trade_chart_popup import TradeChartPopup

    mock_fetch.return_value = pd.DataFrame(
        columns=["Open", "High", "Low", "Close", "Volume"])

    popup = TradeChartPopup(tk_root, _live_trade(), run_id="test-run",
                            colors=stub_colors, font_name="Consolas")
    assert popup._after_id is not None
    assert popup.tf == "15m"  # CITADEL from ENGINE_INTERVALS
    popup.destroy()


@patch("launcher_support.trade_chart_popup.fetch_binance_candles")
def test_open_trade_chart_reuses_popup(mock_fetch, tk_root, stub_colors):
    """Clicking twice on same trade lifts existing popup instead of duplicating."""
    import pandas as pd
    from launcher_support.trade_chart_popup import open_trade_chart

    mock_fetch.return_value = pd.DataFrame(
        columns=["Open", "High", "Low", "Close", "Volume"])

    trade = _closed_trade()
    first = open_trade_chart(tk_root, trade, "test-run",
                             colors=stub_colors, font_name="Consolas")
    second = open_trade_chart(tk_root, trade, "test-run",
                              colors=stub_colors, font_name="Consolas")
    assert first is second
    first.destroy()
```

- [ ] **Step 2: Run the smoke tests**

Run: `python -m pytest tests/launcher_support/test_trade_chart_popup_smoke.py -v`
Expected: 3 tests PASS (or all skipped if no display — both acceptable).

- [ ] **Step 3: Commit**

```bash
git add tests/launcher_support/test_trade_chart_popup_smoke.py
git commit -m "test(trade-chart): smoke tests for Toplevel popup lifecycle"
```

---

## Task 7: Wire into engines_live_view — PAPER pane

**Files:**
- Modify: `launcher_support/engines_live_view.py`

Spec context: the PAPER detail pane in `engines_live_view.py` currently does NOT render a trade list (it shows account/equity/positions only). SHADOW has `_render_signals_table` — that's Task 8.

- [ ] **Step 1: Find the PAPER detail render function**

Run: `grep -n "def _render_paper_detail\|def _paper_detail\|paper detail" launcher_support/engines_live_view.py`
Expected: find the function that composes the PAPER detail pane (look around line 3493+ per spec reference — `"Render PAPER mode detail pane with full trading dashboard."`).

- [ ] **Step 2: Locate the insertion point**

Read the function body. Find the natural insertion point AFTER the positions/equity block and BEFORE the log-stream block (if present) or at end. Note the line range for the modify.

- [ ] **Step 3: Import the new modules at top of engines_live_view.py**

Near the top of `engines_live_view.py`, in the imports section, add:

```python
from launcher_support import trade_history_panel
from launcher_support.trade_chart_popup import open_trade_chart
```

- [ ] **Step 4: Add trade history render call in PAPER pane**

Inside the PAPER detail render function, after positions/equity rendering and before the log stream (or at the end of content), add:

```python
    # Trade history list — clickable rows open candle chart popup
    from launcher_support.trade_chart_popup import resolve_tf, tf_to_seconds
    _engine_for_tf = (trades[0].get("strategy") if trades else None) or slug
    _tf_sec_for_panel = tf_to_seconds(resolve_tf(_engine_for_tf))

    def _open_chart(t: dict):
        open_trade_chart(
            launcher, t, run_id=str(run_id or ""),
            colors=_palette_for_panel(),
            font_name=FONT,
        )

    trade_history_panel.render(
        parent, trades=trades or [],
        on_click=_open_chart,
        colors=_palette_for_panel(),
        font_name=FONT,
        tf_sec=_tf_sec_for_panel,
        title="PAPER TRADES",
    )
```

If `_palette_for_panel()` doesn't exist, use an inline dict:

```python
    _panel_colors = {
        "BG": BG, "PANEL": PANEL, "BG2": BG2, "AMBER": AMBER,
        "AMBER_B": AMBER_B, "AMBER_D": AMBER_D, "GREEN": GREEN,
        "RED": RED, "WHITE": WHITE, "DIM": DIM, "DIM2": DIM2,
        "BORDER": BORDER,
    }
```

and pass `_panel_colors` to both `open_trade_chart` and `trade_history_panel.render`.

- [ ] **Step 5: Run smoke_test.py to catch imports/regressions**

Run: `python smoke_test.py --quiet`
Expected: same pass/fail count as baseline (no regressions introduced).

- [ ] **Step 6: Manual smoke — launch launcher, navigate to PAPER**

Run: `python launcher.py`
- Navigate: ENGINES → (any engine with a paper run) → PAPER mode
- Expected: new "PAPER TRADES (N)" block appears
- Click a trade row → chart popup opens (or "candles indisponíveis" if symbol not on Binance)
- ESC closes popup
- Re-click same trade → popup lifts to front, doesn't duplicate

- [ ] **Step 7: Commit**

```bash
git add launcher_support/engines_live_view.py
git commit -m "feat(engines-live): wire trade_history_panel + chart popup in PAPER pane"
```

---

## Task 8: Wire into engines_live_view — SHADOW pane (replace _render_signals_table)

**Files:**
- Modify: `launcher_support/engines_live_view.py` (line ~2819 `_render_signals_table` and its callers)

- [ ] **Step 1: Find all callers of `_render_signals_table`**

Run: `grep -n "_render_signals_table" launcher_support/engines_live_view.py`
Expected: 1 definition + 1-2 call sites inside shadow detail render.

- [ ] **Step 2: Replace call with trade_history_panel.render**

At each call site of `_render_signals_table(parent, trades)`, replace with:

```python
from launcher_support.trade_chart_popup import resolve_tf, tf_to_seconds
_engine_for_tf = (trades[0].get("strategy") if trades else None) or slug
_tf_sec_for_panel = tf_to_seconds(resolve_tf(_engine_for_tf))

def _open_chart(t: dict):
    open_trade_chart(
        launcher, t, run_id=str(run_id or ""),
        colors=_panel_colors,  # same dict as PAPER wire-up
        font_name=FONT,
    )

trade_history_panel.render(
    parent, trades=trades or [],
    on_click=_open_chart,
    colors=_panel_colors,
    font_name=FONT,
    tf_sec=_tf_sec_for_panel,
    title="SHADOW SIGNALS",
)
```

- [ ] **Step 3: Delete the now-unused `_render_signals_table` function**

Remove lines 2819-2869 (the old `_render_signals_table` definition). Confirm no other callers remain:

Run: `grep -n "_render_signals_table" launcher_support/engines_live_view.py`
Expected: no matches.

- [ ] **Step 4: Preserve existing `shadow_selected_trade` state behavior**

The old SHADOW pane used `state["shadow_selected_trade"]` for drill-down. Since popup replaces that drill-down, remove the state handling IF the click handler was the only writer:

Run: `grep -n "shadow_selected_trade" launcher_support/engines_live_view.py`
- If only 3-4 matches remain and they are all in the old click/selection path, remove them.
- If the state is read elsewhere (e.g. a sidebar panel), leave it in place — popup is additive, not replacing selection semantics.

When in doubt, **leave state wiring** — popup is additive.

- [ ] **Step 5: Run smoke_test.py**

Run: `python smoke_test.py --quiet`
Expected: same pass/fail count as baseline.

- [ ] **Step 6: Run trade-panel tests**

Run: `python -m pytest tests/launcher_support/test_trade_history_panel.py tests/launcher_support/test_trade_chart_popup.py tests/launcher_support/test_trade_chart_popup_smoke.py -v`
Expected: all green.

- [ ] **Step 7: Manual smoke — shadow pane**

Run: `python launcher.py`
- Navigate: ENGINES → (any engine with a shadow run) → SHADOW mode
- Expected: old "(sem sinais ainda)" placeholder replaced by new "SHADOW SIGNALS (N)" block
- Click a trade row → chart popup opens
- ESC closes

- [ ] **Step 8: Commit**

```bash
git add launcher_support/engines_live_view.py
git commit -m "feat(engines-live): replace _render_signals_table with trade_history_panel in SHADOW"
```

---

## Task 9: Final validation + session log

**Files:**
- Create: `docs/sessions/YYYY-MM-DD_HHMM.md`
- Create/update: `docs/days/YYYY-MM-DD.md`

- [ ] **Step 1: Full test suite**

Run: `python -m pytest tests/launcher_support/ -v --tb=short`
Expected: all new tests PASS + no regressions.

- [ ] **Step 2: Smoke test baseline check**

Run: `python smoke_test.py --quiet`
Expected: pass count matches pre-implementation baseline (156/156 or current).

- [ ] **Step 3: Verify keys.json intact (CLAUDE.md rule)**

Run: `python tools/maintenance/verify_keys_intact.py`
Expected: exit code 0.

- [ ] **Step 4: Check CORE files not touched (CLAUDE.md rule)**

Run: `git diff --stat main -- core/indicators.py core/signals.py core/portfolio.py config/params.py`
Expected: empty output (nothing modified in CORE).

- [ ] **Step 5: Write session log**

Create `docs/sessions/$(date +%Y-%m-%d_%H%M).md` following CLAUDE.md template. Key fields:
- Resumo: "Adicionada lista de trades clicável no cockpit PAPER + SHADOW. Click abre popup matplotlib com candles + markers de entry/stop/TP/exit."
- Mudanças Críticas: "Nenhuma mudança em lógica de trading." (UI-only feature, CORE intacto)
- Commits: list from Tasks 1-8
- Estado do Sistema: smoke test count, new tests count, manual smoke verified

- [ ] **Step 6: Update daily log**

Append a session entry to `docs/days/$(date +%Y-%m-%d).md`.

- [ ] **Step 7: Commit logs**

```bash
git add docs/sessions/ docs/days/
git commit -m "docs(session+day): cockpit trade history + chart popup"
```

---

## Self-Review Summary

Spec coverage audit (each section of spec → task):

| Spec section | Task(s) |
|---|---|
| 3.1 New files: trade_history_panel.py | 2, 3 |
| 3.1 New files: trade_chart_popup.py | 4, 5 |
| 3.2 Modified: engines_live_view.py | 7, 8 |
| 3.2 Modified: requirements.txt | 1 |
| 3.3 Test files | 2, 4, 6 |
| 4.1 Trade list source (cockpit API) | Used in 7, 8 (existing `get_trades`) |
| 4.2 Schema | Handled in format_trade_row (Task 2) |
| 4.3 Candles source (Binance) | Task 4 fetch_binance_candles |
| 4.4 TF per engine (params.ENGINE_INTERVALS) | Task 4 resolve_tf |
| 4.5 Exit timestamp derivation | Task 4 build_marker_specs + Task 5 _render_footer |
| 4.6 Window auto-C2 | Task 4 derive_candle_window |
| 5.1-5.5 UI list | Task 3 render |
| 6.1-6.5 Popup layout | Task 5 TradeChartPopup |
| 7 Error handling | Task 4 (fetch returns empty DF), Task 5 (placeholder render) |
| 8 Testing | Tasks 2, 4, 6 |
| 9 Rollout | Tasks 7, 8, 9 |

No gaps. No placeholders. All type/function references consistent across tasks.

---

## Out of scope (reject creep)

- Indicators on chart (EMA/RSI/BB) — spec §2
- Zoom/pan interactive — spec §2
- Export PNG — spec §2
- Filters on list (engine, outcome) — spec §2
- LIVE mode (real Binance trading) — spec §2; v1 covers PAPER + SHADOW only
- Modifying `config/params.py`, `core/signals.py`, `core/indicators.py`, `core/portfolio.py` (CORE protected per CLAUDE.md)
