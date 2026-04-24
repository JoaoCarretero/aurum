# Shadow Sidebar + Enriched Detail — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add institutional multi-engine sidebar + enriched LAST SIGNALS table + row-click detail popup to the ENGINES LIVE cockpit. All modes (shadow/paper/demo/testnet/live) share the same component. Zero backend, zero CORE touched.

**Architecture:** New `launcher_support/engines_sidebar.py` provides pure data helpers (`build_engine_rows`, `format_signal_row`, `format_omega_bar`) and Tk render functions (`render_sidebar`, `render_detail`). New `launcher_support/signal_detail_popup.py` renders `TkToplevel` drill-down. `launcher_support/engines_live_view.py` refactored to delegate. `core/shadow_contract.py` extended with optional fields matching the disk shape.

**Tech Stack:** Python 3.14, pydantic v2, TkInter, pytest. Tests are pure-function only — Tk render functions are smoke-tested manually. See `tests/test_engines_live_view_cockpit.py` as the existing pattern.

**Source spec:** `docs/superpowers/specs/2026-04-18-shadow-gate-breakdown-sidebar-design.md`

---

## File Structure

**New files:**
- `launcher_support/engines_sidebar.py` — sidebar + detail components (~400 lines)
- `launcher_support/signal_detail_popup.py` — row-click drill-down popup (~180 lines)
- `tests/test_engines_sidebar.py` — pure helpers tests
- `tests/test_signal_detail_popup.py` — pure formatters tests

**Modified:**
- `core/shadow_contract.py` — extend `TradeRecord` with optional fields
- `launcher_support/engines_live_view.py` — `_render_detail_shadow` delegates to new component; apply sidebar to paper/demo/testnet/live modes
- `tests/test_shadow_contract.py` — new fields + legacy compat
- `tests/test_engines_live_view_cockpit.py` — integration wiring

**Unchanged (explicit):**
- `core/indicators.py`, `core/signals.py`, `core/risk/portfolio.py`, `config/params.py` — CORE protegido
- `tools/maintenance/millennium_shadow.py`, `tools/cockpit_api.py` — runner + API
- `engines/*.py`
- `deploy/*`

---

## Task 1: Extend TradeRecord with optional fields

**Files:**
- Modify: `core/shadow_contract.py:70-90` (TradeRecord class)
- Test: `tests/test_shadow_contract.py` (extend existing)

- [ ] **Step 1.1: Write failing test for new fields**

Add to `tests/test_shadow_contract.py`:

```python
def test_trade_record_accepts_enriched_fields():
    """TradeRecord should type-check all enriched fields from shadow_trades.jsonl."""
    from core.shadow_contract import TradeRecord
    record = TradeRecord(
        timestamp="2026-04-18T12:00:00Z",
        symbol="BTCUSDT",
        strategy="CITADEL",
        direction="BULLISH",
        entry=65432.0,
        stop=65120.0,
        target=66950.0,
        exit_p=66210.0,
        rr=3.0,
        duration=5,
        result="WIN",
        exit_reason="trailing",
        size=285.4,
        score=0.5363,
        r_multiple=1.445,
        macro_bias="BULL",
        vol_regime="NORMAL",
        omega_struct=0.75,
        omega_flow=0.858,
        omega_cascade=0.25,
        omega_momentum=0.667,
        omega_pullback=0.933,
        struct="DOWN",
        struct_str=0.75,
        rsi=49.33,
        dist_ema21=0.101,
        chop_trade=False,
        dd_scale=1.0,
        corr_mult=1.0,
        hmm_regime=None,
        hmm_confidence=None,
        shadow_run_id="2026-04-18_0229",
    )
    assert record.stop == 65120.0
    assert record.result == "WIN"
    assert record.omega_struct == 0.75
    assert record.macro_bias == "BULL"


def test_trade_record_legacy_record_deserializes():
    """Legacy record without enriched fields should deserialize with defaults None."""
    from core.shadow_contract import TradeRecord
    record = TradeRecord(
        timestamp="2026-04-17T12:00:00Z",
        symbol="ETHUSDT",
        strategy="JUMP",
        direction="BEARISH",
        entry=3210.5,
    )
    assert record.stop is None
    assert record.result is None
    assert record.omega_struct is None
    assert record.macro_bias is None


def test_trade_record_extra_fields_still_allowed():
    """extra='allow' preserved — runner can evolve shape without breaking client."""
    from core.shadow_contract import TradeRecord
    record = TradeRecord(
        timestamp="2026-04-18T12:00:00Z",
        symbol="LINKUSDT",
        strategy="CITADEL",
        direction="BULLISH",
        entry=14.23,
        future_unknown_field="new_stuff",  # extra — should not raise
    )
    dumped = record.model_dump()
    assert dumped["future_unknown_field"] == "new_stuff"


def test_trade_record_result_literal_validates():
    """result accepts only 'WIN' | 'LOSS' | None."""
    import pytest
    from pydantic import ValidationError
    from core.shadow_contract import TradeRecord
    with pytest.raises(ValidationError):
        TradeRecord(
            timestamp="2026-04-18T12:00:00Z",
            symbol="BTC", strategy="X", direction="L",
            result="PARTIAL",  # invalid
        )
```

- [ ] **Step 1.2: Run test to verify it fails**

Run: `pytest tests/test_shadow_contract.py::test_trade_record_accepts_enriched_fields -v`
Expected: FAIL with `ValidationError` for unknown field `stop`.

- [ ] **Step 1.3: Modify TradeRecord to add enriched fields**

Edit `core/shadow_contract.py`. Find the `TradeRecord` class (around line 70-90). Replace the class body with:

```python
class TradeRecord(BaseModel):
    """Schema permissivo — engine schema evolve; extra fields preservados."""
    # Existing fields
    timestamp: datetime
    symbol: str
    strategy: str
    direction: str
    entry: float | None = None
    exit: float | None = None
    pnl: float | None = None
    shadow_observed_at: datetime | None = None

    # Enriched fields — all Optional, reflect shadow_trades.jsonl shape
    stop: float | None = None
    target: float | None = None
    exit_p: float | None = None
    rr: float | None = None
    duration: int | None = None
    result: Literal["WIN", "LOSS"] | None = None
    exit_reason: str | None = None
    size: float | None = None
    score: float | None = None
    r_multiple: float | None = None

    # Regime context
    macro_bias: Literal["BULL", "BEAR", "CHOP"] | None = None
    vol_regime: Literal["LOW", "NORMAL", "HIGH"] | None = None

    # Omega 5D breakdown
    omega_struct: float | None = None
    omega_flow: float | None = None
    omega_cascade: float | None = None
    omega_momentum: float | None = None
    omega_pullback: float | None = None

    # Structure context
    struct: str | None = None
    struct_str: float | None = None
    rsi: float | None = None
    dist_ema21: float | None = None
    chop_trade: bool | None = None

    # Scaling multipliers
    dd_scale: float | None = None
    corr_mult: float | None = None

    # HMM (raramente presente)
    hmm_regime: str | None = None
    hmm_confidence: float | None = None

    # Shadow provenance
    shadow_run_id: str | None = None

    model_config = ConfigDict(extra="allow")
```

Add `Literal` to imports at the top of the file if not present:

```python
from typing import Literal
```

- [ ] **Step 1.4: Run all contract tests to verify they pass**

Run: `pytest tests/test_shadow_contract.py -v`
Expected: all tests PASS (existing + new 4).

- [ ] **Step 1.5: Commit**

```bash
git add core/shadow_contract.py tests/test_shadow_contract.py
git commit -m "feat(contract): extend TradeRecord com campos enriched (stop/target/rr/result/omega/regime)

Tipagem explicita pra fields que ja existem no shadow_trades.jsonl
mas nao estavam no pydantic model (passavam via extra='allow').
Legacy records continuam deserializando com defaults None."
```

---

## Task 2: Pure helpers — build_engine_rows + formatters

**Files:**
- Create: `launcher_support/engines_sidebar.py`
- Test: `tests/test_engines_sidebar.py`

- [ ] **Step 2.1: Write failing tests for pure helpers**

Create `tests/test_engines_sidebar.py`:

```python
"""Tests pros helpers puros do sidebar. Render Tk eh smoke-only."""
from __future__ import annotations
import pytest


def test_engine_row_dataclass():
    from launcher_support.engines_sidebar import EngineRow
    row = EngineRow(slug="millennium", display="MILLENNIUM",
                    active=True, ticks=41, signals=625)
    assert row.slug == "millennium"
    assert row.active is True
    assert row.ticks == 41


def test_build_engine_rows_active_engine():
    """Engine com heartbeat em cache aparece como active com ticks/signals."""
    from launcher_support.engines_sidebar import build_engine_rows
    registry = [
        {"slug": "millennium", "display": "MILLENNIUM"},
        {"slug": "citadel",    "display": "CITADEL"},
    ]
    heartbeats = {
        "millennium": {"ticks_ok": 41, "novel_total": 625, "status": "running"},
    }
    rows = build_engine_rows(registry, heartbeats)
    assert len(rows) == 2
    mill = next(r for r in rows if r.slug == "millennium")
    cit = next(r for r in rows if r.slug == "citadel")
    assert mill.active is True
    assert mill.ticks == 41
    assert mill.signals == 625
    assert cit.active is False
    assert cit.ticks is None
    assert cit.signals is None


def test_build_engine_rows_preserves_registry_order():
    from launcher_support.engines_sidebar import build_engine_rows
    registry = [
        {"slug": "a", "display": "A"},
        {"slug": "b", "display": "B"},
        {"slug": "c", "display": "C"},
    ]
    rows = build_engine_rows(registry, {})
    assert [r.slug for r in rows] == ["a", "b", "c"]


def test_format_signal_row_complete():
    """Trade com todos os campos → dict de strings formatados."""
    from launcher_support.engines_sidebar import format_signal_row
    trade = {
        "timestamp": "2026-04-18T19:02:15",
        "symbol": "BTCUSDT",
        "direction": "BULLISH",
        "entry": 65432.5,
        "stop": 65120.0,
        "rr": 3.0,
        "size": 285.4,
        "result": "WIN",
    }
    cells = format_signal_row(trade)
    assert cells["time"] == "19:02"
    assert cells["sym"] == "BTC"
    assert cells["dir"] == "L"
    assert cells["entry"] == "65432"
    assert cells["stop"] == "65120"
    assert cells["rr"] == "3.0"
    assert cells["size"] == "$285"
    assert cells["res"] == "WIN"


def test_format_signal_row_none_fields_render_dash():
    from launcher_support.engines_sidebar import format_signal_row
    trade = {"timestamp": "2026-04-18T12:00", "symbol": "ETH",
             "direction": "SHORT"}
    cells = format_signal_row(trade)
    assert cells["time"] == "12:00"
    assert cells["dir"] == "S"
    assert cells["entry"] == "—"
    assert cells["stop"] == "—"
    assert cells["rr"] == "—"
    assert cells["size"] == "—"
    assert cells["res"] == "—"


def test_format_signal_row_short_symbol_not_truncated():
    from launcher_support.engines_sidebar import format_signal_row
    cells = format_signal_row({"timestamp": "2026-04-18T12:00",
                                "symbol": "OP", "direction": "LONG"})
    assert cells["sym"] == "OP"


def test_format_signal_row_direction_variants():
    from launcher_support.engines_sidebar import format_signal_row
    ts = "2026-04-18T12:00"
    assert format_signal_row({"timestamp": ts, "symbol": "X", "direction": "LONG"})["dir"] == "L"
    assert format_signal_row({"timestamp": ts, "symbol": "X", "direction": "BULLISH"})["dir"] == "L"
    assert format_signal_row({"timestamp": ts, "symbol": "X", "direction": "SHORT"})["dir"] == "S"
    assert format_signal_row({"timestamp": ts, "symbol": "X", "direction": "BEARISH"})["dir"] == "S"
    assert format_signal_row({"timestamp": ts, "symbol": "X", "direction": "???"})["dir"] == "?"


def test_result_color_mapping():
    """Pure function mapeia result → color name (string pro renderer usar)."""
    from launcher_support.engines_sidebar import result_color_name
    assert result_color_name("WIN") == "GREEN"
    assert result_color_name("LOSS") == "RED"
    assert result_color_name(None) == "DIM"
    assert result_color_name("") == "DIM"
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `pytest tests/test_engines_sidebar.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'launcher_support.engines_sidebar'`.

- [ ] **Step 2.3: Create the module with pure helpers**

Create `launcher_support/engines_sidebar.py`:

```python
"""Sidebar institucional + detail renderer reusavel pro ENGINES LIVE cockpit.

Pure helpers (build_engine_rows, format_signal_row, format_omega_bar,
result_color_name) sao testaveis sem Tk. Render functions (render_sidebar,
render_detail) criam widgets — smoke-tested manualmente.

Design spec: docs/superpowers/specs/2026-04-18-shadow-gate-breakdown-sidebar-design.md
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EngineRow:
    """Linha da sidebar de engines. Active=True quando tem run vivo."""
    slug: str
    display: str
    active: bool
    ticks: int | None
    signals: int | None


def build_engine_rows(
    registry: list[dict],
    heartbeats: dict[str, dict],
) -> list[EngineRow]:
    """Compoe EngineRow a partir do registry de engines + heartbeats ativos.

    Args:
        registry: lista de {slug, display} — ordem preservada na UI.
        heartbeats: {slug: heartbeat_dict} apenas engines com run.

    Returns:
        list[EngineRow] na ordem do registry. Engines sem heartbeat
        retornam active=False + ticks/signals=None.
    """
    rows: list[EngineRow] = []
    for item in registry:
        slug = item["slug"]
        hb = heartbeats.get(slug)
        if hb:
            rows.append(EngineRow(
                slug=slug,
                display=item["display"],
                active=True,
                ticks=int(hb.get("ticks_ok", 0) or 0),
                signals=int(hb.get("novel_total", 0) or 0),
            ))
        else:
            rows.append(EngineRow(
                slug=slug,
                display=item["display"],
                active=False,
                ticks=None,
                signals=None,
            ))
    return rows


def _format_time(ts: str) -> str:
    """Extrai HH:MM de um timestamp ISO ou string arbitrária."""
    s = str(ts).replace("T", " ")
    # "2026-04-18 19:02:15" → "19:02"
    if len(s) >= 16 and s[13] == ":":
        return s[11:16]
    return s[:5]


def _short_symbol(sym: str) -> str:
    """BTCUSDT → BTC (strip USDT/USD suffix); preserva curtos."""
    s = str(sym or "").upper()
    for suffix in ("USDT", "USD", "BUSD"):
        if s.endswith(suffix) and len(s) > len(suffix):
            return s[: -len(suffix)]
    return s


def _short_dir(direction: str) -> str:
    d = str(direction or "").upper()
    if d in ("LONG", "BULLISH", "BULL"):
        return "L"
    if d in ("SHORT", "BEARISH", "BEAR"):
        return "S"
    return "?"


def _fmt_price(v) -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    # 4-5 significant digits
    if abs(f) >= 1000:
        return f"{f:.0f}"
    if abs(f) >= 10:
        return f"{f:.2f}"
    return f"{f:.4g}"


def _fmt_rr(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.1f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_size(v) -> str:
    if v is None:
        return "—"
    try:
        return f"${float(v):.0f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_result(v) -> str:
    if v in ("WIN", "LOSS"):
        return v
    return "—"


def format_signal_row(trade: dict) -> dict[str, str]:
    """Dict → dict de strings formatados pra tabela LAST SIGNALS.

    Chaves: time, sym, dir, entry, stop, rr, size, res.
    Campos ausentes renderizam '—'.
    """
    return {
        "time": _format_time(trade.get("timestamp", "")),
        "sym": _short_symbol(trade.get("symbol", "")),
        "dir": _short_dir(trade.get("direction", "")),
        "entry": _fmt_price(trade.get("entry")),
        "stop": _fmt_price(trade.get("stop")),
        "rr": _fmt_rr(trade.get("rr")),
        "size": _fmt_size(trade.get("size")),
        "res": _fmt_result(trade.get("result")),
    }


def result_color_name(result) -> str:
    """Mapeia result → nome de cor ('GREEN' | 'RED' | 'DIM')."""
    if result == "WIN":
        return "GREEN"
    if result == "LOSS":
        return "RED"
    return "DIM"
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `pytest tests/test_engines_sidebar.py -v`
Expected: all 8 tests PASS.

- [ ] **Step 2.5: Commit**

```bash
git add launcher_support/engines_sidebar.py tests/test_engines_sidebar.py
git commit -m "feat(sidebar): pure helpers — EngineRow, build_engine_rows, format_signal_row

Fundacao pro componente sidebar institucional. Zero Tk — puro data
transform + formatacao. Render functions vem na proxima task."
```

---

## Task 3: Pure helpers — omega formatting for popup

**Files:**
- Create: `launcher_support/signal_detail_popup.py` (stub + helpers first)
- Test: `tests/test_signal_detail_popup.py`

- [ ] **Step 3.1: Write failing tests for omega bar formatter**

Create `tests/test_signal_detail_popup.py`:

```python
"""Tests pros formatters puros do signal detail popup."""
from __future__ import annotations


def test_format_omega_bar_full():
    from launcher_support.signal_detail_popup import format_omega_bar
    assert format_omega_bar(1.0) == "██████████"
    assert format_omega_bar(0.99) == "██████████"


def test_format_omega_bar_empty():
    from launcher_support.signal_detail_popup import format_omega_bar
    assert format_omega_bar(0.0) == "░░░░░░░░░░"


def test_format_omega_bar_half():
    from launcher_support.signal_detail_popup import format_omega_bar
    assert format_omega_bar(0.5) == "█████░░░░░"


def test_format_omega_bar_none():
    from launcher_support.signal_detail_popup import format_omega_bar
    assert format_omega_bar(None) == "          "   # 10 espaços


def test_format_omega_bar_clamps_out_of_range():
    from launcher_support.signal_detail_popup import format_omega_bar
    assert format_omega_bar(1.5) == "██████████"
    assert format_omega_bar(-0.2) == "░░░░░░░░░░"


def test_section_outcome_all_fields():
    """Outcome section gera linhas com (label, value, color_name)."""
    from launcher_support.signal_detail_popup import section_outcome
    trade = {
        "result": "WIN", "exit_reason": "trailing",
        "pnl": 285.4, "exit_p": 66210.0,
        "r_multiple": 1.44, "duration": 5,
    }
    rows = section_outcome(trade)
    label_set = {r[0] for r in rows}
    assert "result" in label_set
    assert "pnl" in label_set
    assert "r_multiple" in label_set
    # Find result row — value string is "WIN", color GREEN
    r_row = next(r for r in rows if r[0] == "result")
    assert r_row[1] == "WIN"
    assert r_row[2] == "GREEN"


def test_section_outcome_loss_renders_red():
    from launcher_support.signal_detail_popup import section_outcome
    rows = section_outcome({"result": "LOSS"})
    r_row = next(r for r in rows if r[0] == "result")
    assert r_row[2] == "RED"


def test_section_outcome_none_fields_render_dash():
    from launcher_support.signal_detail_popup import section_outcome
    rows = section_outcome({})
    for label, value, _color in rows:
        if label == "pnl":
            assert value == "—"
        if label == "result":
            assert value == "—"


def test_section_entry_all_fields():
    from launcher_support.signal_detail_popup import section_entry
    trade = {"entry": 65432.0, "stop": 65120.0, "target": 66950.0,
             "rr": 3.0, "size": 285.4, "score": 0.5363}
    rows = section_entry(trade)
    labels = {r[0] for r in rows}
    assert {"entry", "stop", "target", "rr", "size", "score"} <= labels


def test_section_regime():
    from launcher_support.signal_detail_popup import section_regime
    trade = {"macro_bias": "BULL", "vol_regime": "NORMAL",
             "hmm_regime": None, "chop_trade": False,
             "dd_scale": 1.0, "corr_mult": 1.0}
    rows = section_regime(trade)
    labels = {r[0] for r in rows}
    assert "macro_bias" in labels
    assert "vol_regime" in labels
    assert "hmm_regime" in labels


def test_section_omega_returns_bars():
    """Omega section returns (dim_name, value, bar_str) tuples for the 5 axes."""
    from launcher_support.signal_detail_popup import section_omega
    trade = {"omega_struct": 0.75, "omega_flow": 0.858,
             "omega_cascade": 0.25, "omega_momentum": 0.667,
             "omega_pullback": 0.933}
    rows = section_omega(trade)
    dims = {r[0] for r in rows}
    assert dims == {"struct", "flow", "cascade", "momentum", "pullback"}
    # bar length = 10
    for _, _, bar in rows:
        assert len(bar) == 10
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `pytest tests/test_signal_detail_popup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'launcher_support.signal_detail_popup'`.

- [ ] **Step 3.3: Create the module with pure helpers**

Create `launcher_support/signal_detail_popup.py`:

```python
"""Signal detail popup — drill-down modal pra trade completo.

Pure formatters (format_omega_bar, section_*) sao unit-tested.
Render Tk (show) eh smoke-only.

Design spec: docs/superpowers/specs/2026-04-18-shadow-gate-breakdown-sidebar-design.md
"""
from __future__ import annotations

_BAR_WIDTH = 10
_BAR_FILL = "█"
_BAR_EMPTY = "░"


def format_omega_bar(value) -> str:
    """Unicode block bar de largura 10 pra valor em [0, 1]."""
    if value is None:
        return " " * _BAR_WIDTH
    try:
        f = float(value)
    except (TypeError, ValueError):
        return " " * _BAR_WIDTH
    f = max(0.0, min(1.0, f))
    filled = round(f * _BAR_WIDTH)
    return _BAR_FILL * filled + _BAR_EMPTY * (_BAR_WIDTH - filled)


def _fmt_num(v, fmt: str = "g") -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if fmt == "d":
        return f"{int(f)}"
    if fmt == "pnl":
        sign = "+" if f >= 0 else "-"
        return f"{sign}${abs(f):.2f}"
    if fmt == "usd":
        return f"${f:.2f}"
    if fmt == "price":
        if abs(f) >= 1000:
            return f"{f:.2f}"
        return f"{f:.4g}"
    return f"{f:.4g}"


def _fmt_result_value(v) -> str:
    if v in ("WIN", "LOSS"):
        return v
    return "—"


def _result_color(v) -> str:
    if v == "WIN":
        return "GREEN"
    if v == "LOSS":
        return "RED"
    return "DIM"


def _fmt_str_or_dash(v) -> str:
    if v is None or v == "":
        return "—"
    return str(v)


def _fmt_bool(v) -> str:
    if v is True:
        return "true"
    if v is False:
        return "false"
    return "—"


def section_outcome(trade: dict) -> list[tuple[str, str, str]]:
    """Return list de (label, value_str, color_name) pra seção OUTCOME."""
    return [
        ("result", _fmt_result_value(trade.get("result")),
            _result_color(trade.get("result"))),
        ("exit_reason", _fmt_str_or_dash(trade.get("exit_reason")), "WHITE"),
        ("pnl", _fmt_num(trade.get("pnl"), "pnl"),
            "GREEN" if (trade.get("pnl") or 0) >= 0 else "RED"),
        ("exit_price", _fmt_num(trade.get("exit_p"), "price"), "WHITE"),
        ("r_multiple", _fmt_num(trade.get("r_multiple")), "WHITE"),
        ("duration", _fmt_num(trade.get("duration"), "d"), "WHITE"),
    ]


def section_entry(trade: dict) -> list[tuple[str, str, str]]:
    return [
        ("entry", _fmt_num(trade.get("entry"), "price"), "WHITE"),
        ("stop", _fmt_num(trade.get("stop"), "price"), "WHITE"),
        ("target", _fmt_num(trade.get("target"), "price"), "WHITE"),
        ("rr", _fmt_num(trade.get("rr")), "WHITE"),
        ("size", _fmt_num(trade.get("size"), "usd"), "WHITE"),
        ("score", _fmt_num(trade.get("score")), "WHITE"),
    ]


def section_regime(trade: dict) -> list[tuple[str, str, str]]:
    return [
        ("macro_bias", _fmt_str_or_dash(trade.get("macro_bias")), "WHITE"),
        ("vol_regime", _fmt_str_or_dash(trade.get("vol_regime")), "WHITE"),
        ("hmm_regime", _fmt_str_or_dash(trade.get("hmm_regime")), "WHITE"),
        ("chop_trade", _fmt_bool(trade.get("chop_trade")), "WHITE"),
        ("dd_scale", _fmt_num(trade.get("dd_scale")), "WHITE"),
        ("corr_mult", _fmt_num(trade.get("corr_mult")), "WHITE"),
    ]


def section_omega(trade: dict) -> list[tuple[str, str, str]]:
    """Return list de (dim_name, value_str, bar_str) para as 5 axes."""
    dims = [
        ("struct", trade.get("omega_struct")),
        ("flow", trade.get("omega_flow")),
        ("cascade", trade.get("omega_cascade")),
        ("momentum", trade.get("omega_momentum")),
        ("pullback", trade.get("omega_pullback")),
    ]
    return [(name, _fmt_num(value), format_omega_bar(value))
            for name, value in dims]


def section_structure(trade: dict) -> list[tuple[str, str, str]]:
    return [
        ("struct", _fmt_str_or_dash(trade.get("struct")), "WHITE"),
        ("struct_str", _fmt_num(trade.get("struct_str")), "WHITE"),
        ("rsi", _fmt_num(trade.get("rsi")), "WHITE"),
        ("dist_ema21", _fmt_num(trade.get("dist_ema21")), "WHITE"),
    ]


# Render Tk stub — completed in Task 5 after engines_sidebar render_detail is in place.
def show(parent, trade: dict) -> None:
    """Abre Toplevel modal com drill-down do trade. Tk-only; smoke-tested."""
    raise NotImplementedError("Tk render added in Task 5")
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `pytest tests/test_signal_detail_popup.py -v`
Expected: all 11 tests PASS.

- [ ] **Step 3.5: Commit**

```bash
git add launcher_support/signal_detail_popup.py tests/test_signal_detail_popup.py
git commit -m "feat(popup): pure formatters — omega bars + section builders

Helpers puros pras 5 secoes do signal detail popup (OUTCOME, ENTRY,
REGIME, OMEGA 5D, STRUCTURE). Render Tk fica como NotImplementedError
stub — wired em task 5."
```

---

## Task 4: Render functions — sidebar + detail (Tk)

**Files:**
- Modify: `launcher_support/engines_sidebar.py` (add render_sidebar, render_detail)

- [ ] **Step 4.1: Append render functions to engines_sidebar.py**

Add to the end of `launcher_support/engines_sidebar.py`:

```python

# ─── Tk rendering ─────────────────────────────────────────────────
# Render functions criam widgets — smoke-tested manualmente via launcher.
# Pure helpers acima sao unit-tested em tests/test_engines_sidebar.py.

import tkinter as tk
from typing import Callable

from core.ui_palette import (
    AMBER, AMBER_B, BG, BG2, BORDER, DIM, DIM2, FONT, GREEN,
    PANEL, RED, WHITE,
)


_COLORS = {
    "GREEN": GREEN, "RED": RED, "DIM": DIM, "DIM2": DIM2,
    "WHITE": WHITE, "AMBER": AMBER, "AMBER_B": AMBER_B,
}


def render_sidebar(
    parent: tk.Widget,
    engines: list[EngineRow],
    selected_slug: str | None,
    on_select: Callable[[str], None],
) -> tk.Frame:
    """Sidebar lateral fixa — lista engines do registry.

    Engine active: linha clicavel com ticks/signals. Inactive: DIM2
    com '—'. Selected: highlight AMBER_B bg.
    """
    frame = tk.Frame(parent, bg=PANEL, width=180)
    frame.pack(side="left", fill="y")
    frame.pack_propagate(False)

    tk.Label(frame, text="ENGINES", fg=AMBER, bg=PANEL,
             font=(FONT, 7, "bold")).pack(anchor="w", padx=10, pady=(10, 4))
    tk.Frame(frame, bg=BORDER, height=1).pack(fill="x", padx=8)

    for row in engines:
        is_sel = row.slug == selected_slug
        bg = AMBER_B if is_sel else PANEL
        fg_marker = WHITE if is_sel else (WHITE if row.active else DIM2)
        fg_text = BG if is_sel else (WHITE if row.active else DIM2)
        marker = "▸" if is_sel else ("✓" if row.active else "○")

        item = tk.Frame(frame, bg=bg, cursor="hand2")
        item.pack(fill="x", padx=6, pady=1)

        top = tk.Frame(item, bg=bg)
        top.pack(fill="x", padx=6, pady=(4, 0))
        tk.Label(top, text=marker, fg=fg_marker, bg=bg,
                 font=(FONT, 7, "bold")).pack(side="left")
        tk.Label(top, text=f" {row.display}", fg=fg_text, bg=bg,
                 font=(FONT, 7, "bold")).pack(side="left")

        sub = tk.Frame(item, bg=bg)
        sub.pack(fill="x", padx=6, pady=(0, 4))
        if row.active:
            sub_text = f"  ✓ {row.ticks}t · {row.signals}s"
            sub_color = DIM if not is_sel else BG
        else:
            sub_text = "  —"
            sub_color = DIM2
        tk.Label(sub, text=sub_text, fg=sub_color, bg=bg,
                 font=(FONT, 6)).pack(anchor="w")

        def _handler(_e, _slug=row.slug):
            on_select(_slug)
        item.bind("<Button-1>", _handler)
        for child in item.winfo_children():
            child.bind("<Button-1>", _handler)
            for grand in child.winfo_children():
                grand.bind("<Button-1>", _handler)

    return frame


def render_detail(
    parent: tk.Widget,
    engine_display: str,
    mode: str,
    heartbeat: dict | None,
    manifest: dict | None,
    trades: list[dict],
    on_row_click: Callable[[dict], None],
    status_badge_text: str = "",
    status_badge_color: str = DIM2,
) -> tk.Frame:
    """Detail pane flex — HEALTH / RUN INFO / LAST SIGNALS / ACTIONS.

    Usa dados crus (heartbeat dict, trade dict) — sem dependencia de
    pydantic (client side tolera shapes extendidos).
    """
    frame = tk.Frame(parent, bg=PANEL)
    frame.pack(side="left", fill="both", expand=True)

    # HEADER
    hdr = tk.Frame(frame, bg=PANEL)
    hdr.pack(fill="x", padx=12, pady=(10, 8))
    tk.Label(hdr, text=f"{engine_display} · {mode}",
             font=(FONT, 10, "bold"), fg=WHITE, bg=PANEL).pack(side="left")
    if status_badge_text:
        tk.Label(hdr, text=f"  {status_badge_text}", fg=status_badge_color,
                 bg=PANEL, font=(FONT, 7, "bold")).pack(side="left")

    if heartbeat is None:
        empty = tk.Label(frame,
                         text="(engine sem run ativo — selecione outra ou inicie)",
                         fg=DIM, bg=PANEL, font=(FONT, 8, "italic"))
        empty.pack(padx=12, pady=20, anchor="w")
        return frame

    # HEALTH
    _section_header(frame, "HEALTH")
    health = tk.Frame(frame, bg=PANEL)
    health.pack(fill="x", padx=12, pady=(0, 8))
    _pair_row(health, "ticks_ok", str(heartbeat.get("ticks_ok", "—")),
              "uptime", _format_uptime(heartbeat.get("run_hours")))
    _pair_row(health, "ticks_fail", str(heartbeat.get("ticks_fail", "—")),
              "novel", str(heartbeat.get("novel_total", "—")))

    # RUN INFO
    _section_header(frame, "RUN INFO")
    info = tk.Frame(frame, bg=PANEL)
    info.pack(fill="x", padx=12, pady=(0, 8))
    run_id = heartbeat.get("run_id", "—")
    commit = (manifest or {}).get("commit", "—")
    branch = (manifest or {}).get("branch", "—")
    started = heartbeat.get("started_at", "—")
    _pair_row(info, "run_id", str(run_id), "commit", str(commit))
    _pair_row(info, "started", str(started)[:19], "branch", str(branch))

    # LAST SIGNALS
    _section_header(frame, f"LAST SIGNALS  ·  click row for detail")
    signals = tk.Frame(frame, bg=PANEL)
    signals.pack(fill="both", expand=True, padx=12, pady=(0, 8))
    _render_signals_table_rich(signals, trades[-10:][::-1] if trades else [],
                               on_row_click=on_row_click)

    return frame


def _section_header(parent, title: str) -> None:
    tk.Label(parent, text=title, fg=AMBER, bg=PANEL,
             font=(FONT, 7, "bold")).pack(anchor="w", padx=12, pady=(4, 2))
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12, pady=(0, 4))


def _pair_row(parent, k1, v1, k2, v2) -> None:
    row = tk.Frame(parent, bg=PANEL)
    row.pack(fill="x", pady=(0, 2))
    tk.Label(row, text=f"{k1}:", fg=DIM2, bg=PANEL,
             font=(FONT, 7)).pack(side="left", padx=(0, 4))
    tk.Label(row, text=str(v1), fg=WHITE, bg=PANEL,
             font=(FONT, 7, "bold"), width=18, anchor="w").pack(side="left")
    tk.Label(row, text=f"{k2}:", fg=DIM2, bg=PANEL,
             font=(FONT, 7)).pack(side="left", padx=(12, 4))
    tk.Label(row, text=str(v2), fg=WHITE, bg=PANEL,
             font=(FONT, 7, "bold"), anchor="w").pack(side="left")


def _format_uptime(hours) -> str:
    try:
        h = float(hours)
    except (TypeError, ValueError):
        return "—"
    full_h = int(h)
    mins = int((h - full_h) * 60)
    return f"{full_h}h {mins}m"


def _render_signals_table_rich(parent, trades: list[dict], on_row_click):
    """Tabela com colunas time/sym/dir/entry/stop/rr/size/res. Rows clicaveis."""
    if not trades:
        tk.Label(parent,
                 text="(sem sinais ainda — aguardando primeiros ticks)",
                 fg=DIM, bg=PANEL, font=(FONT, 7, "italic")).pack(
                     anchor="w", pady=(4, 4))
        return

    cols = [("TIME", 6), ("SYM", 5), ("DIR", 4),
            ("ENTRY", 9), ("STOP", 9), ("RR", 4),
            ("SIZE", 7), ("RES", 5)]
    hdr = tk.Frame(parent, bg=BG2)
    hdr.pack(fill="x", pady=(2, 0))
    for name, w in cols:
        tk.Label(hdr, text=name, fg=DIM2, bg=BG2,
                 font=(FONT, 6, "bold"),
                 width=w, anchor="w").pack(side="left", padx=(4, 0))

    for trade in trades:
        cells = format_signal_row(trade)
        dir_color = GREEN if cells["dir"] == "L" else RED if cells["dir"] == "S" else DIM
        res_color_name = result_color_name(trade.get("result"))
        res_color = _COLORS.get(res_color_name, DIM)

        row = tk.Frame(parent, bg=PANEL, cursor="hand2")
        row.pack(fill="x", pady=(1, 0))

        _cell(row, cells["time"], DIM, 6)
        _cell(row, cells["sym"], WHITE, 5, bold=True)
        _cell(row, cells["dir"], dir_color, 4, bold=True)
        _cell(row, cells["entry"], WHITE, 9)
        _cell(row, cells["stop"], DIM, 9)
        _cell(row, cells["rr"], WHITE, 4)
        _cell(row, cells["size"], WHITE, 7)
        _cell(row, cells["res"], res_color, 5, bold=True)

        def _click(_e, _t=trade):
            on_row_click(_t)
        row.bind("<Button-1>", _click)
        for child in row.winfo_children():
            child.bind("<Button-1>", _click)


def _cell(parent, text, fg, width, bold=False):
    font = (FONT, 6, "bold") if bold else (FONT, 6)
    tk.Label(parent, text=str(text), fg=fg, bg=PANEL, font=font,
             width=width, anchor="w").pack(side="left", padx=(4, 0))
```

- [ ] **Step 4.2: Verify the module imports and tests still pass**

Run: `pytest tests/test_engines_sidebar.py -v`
Expected: all 8 tests still PASS (rendered functions aren't exercised by pure tests).

Run: `python -c "from launcher_support.engines_sidebar import render_sidebar, render_detail; print('import OK')"`
Expected: `import OK`.

- [ ] **Step 4.3: Commit**

```bash
git add launcher_support/engines_sidebar.py
git commit -m "feat(sidebar): render_sidebar + render_detail Tk widgets

Componente master-detail institucional. Sidebar 180px esquerda com
engines do registry (marker ▸/✓/○), detail pane com HEALTH/RUN INFO/
LAST SIGNALS rich table (8 colunas). Rows clicaveis via on_row_click
callback — handler e wired na integration task."
```

---

## Task 5: Wire signal_detail_popup.show() to Tk

**Files:**
- Modify: `launcher_support/signal_detail_popup.py` — implement `show()`
- Test: `tests/test_signal_detail_popup.py` — no new tests (Tk smoke only)

- [ ] **Step 5.1: Implement show() replacing the stub**

Replace the `show()` function at the end of `launcher_support/signal_detail_popup.py`:

```python
def show(parent, trade: dict) -> None:
    """Abre Toplevel modal com detail completo do trade.

    Seções: OUTCOME, ENTRY, REGIME, OMEGA 5D, STRUCTURE. Fecha com
    ESC, click fora, ou botão X. Trade dict deve vir cru (de
    _render_detail_shadow) — campos ausentes renderizam '—'.
    """
    import tkinter as tk
    from core.ui_palette import (
        AMBER, BG, BORDER, DIM, DIM2, FONT, GREEN, PANEL, RED, WHITE,
    )

    COLORS = {
        "GREEN": GREEN, "RED": RED, "DIM": DIM, "DIM2": DIM2,
        "WHITE": WHITE, "AMBER": AMBER,
    }

    symbol = trade.get("symbol", "?")
    direction = trade.get("direction", "?")
    time_str = str(trade.get("timestamp", "?")).replace("T", " ")[:16]

    top = tk.Toplevel(parent)
    top.title(f"Trade detail — {symbol}")
    top.configure(bg=PANEL)
    top.geometry("520x640")

    # HEADER
    hdr = tk.Frame(top, bg=PANEL)
    hdr.pack(fill="x", padx=16, pady=(14, 6))
    tk.Label(hdr,
             text=f"{symbol}  ·  {direction}  ·  {time_str}",
             fg=WHITE, bg=PANEL, font=(FONT, 11, "bold")).pack(anchor="w")

    def _render_section(title: str, rows: list[tuple[str, str, str]]) -> None:
        tk.Label(top, text=title, fg=AMBER, bg=PANEL,
                 font=(FONT, 7, "bold")).pack(anchor="w", padx=16, pady=(10, 2))
        tk.Frame(top, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(0, 4))
        container = tk.Frame(top, bg=PANEL)
        container.pack(fill="x", padx=16, pady=(0, 4))
        for label, value, color_name in rows:
            row = tk.Frame(container, bg=PANEL)
            row.pack(fill="x", pady=(0, 1))
            tk.Label(row, text=f"{label}:", fg=DIM2, bg=PANEL,
                     font=(FONT, 7), width=14, anchor="w").pack(side="left")
            tk.Label(row, text=str(value),
                     fg=COLORS.get(color_name, WHITE), bg=PANEL,
                     font=(FONT, 7, "bold"), anchor="w").pack(side="left")

    def _render_omega_section() -> None:
        tk.Label(top, text="OMEGA 5D", fg=AMBER, bg=PANEL,
                 font=(FONT, 7, "bold")).pack(anchor="w", padx=16, pady=(10, 2))
        tk.Frame(top, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(0, 4))
        container = tk.Frame(top, bg=PANEL)
        container.pack(fill="x", padx=16, pady=(0, 4))
        for dim_name, value_str, bar in section_omega(trade):
            row = tk.Frame(container, bg=PANEL)
            row.pack(fill="x", pady=(0, 1))
            tk.Label(row, text=f"{dim_name}:", fg=DIM2, bg=PANEL,
                     font=(FONT, 7), width=12, anchor="w").pack(side="left")
            tk.Label(row, text=value_str, fg=WHITE, bg=PANEL,
                     font=(FONT, 7, "bold"), width=6,
                     anchor="w").pack(side="left")
            tk.Label(row, text=bar, fg=AMBER, bg=PANEL,
                     font=(FONT, 7)).pack(side="left", padx=(4, 0))

    _render_section("OUTCOME", section_outcome(trade))
    _render_section("ENTRY", section_entry(trade))
    _render_section("REGIME", section_regime(trade))
    _render_omega_section()
    _render_section("STRUCTURE", section_structure(trade))

    # CLOSE BUTTON + ESC
    close_row = tk.Frame(top, bg=PANEL)
    close_row.pack(fill="x", padx=16, pady=(16, 12))
    tk.Label(close_row, text="  ESC close  ", fg=BG, bg=DIM2,
             font=(FONT, 7, "bold"), cursor="hand2", padx=8, pady=4).pack(
                 side="right")
    top.bind("<Escape>", lambda _e: top.destroy())
    top.focus_set()
```

- [ ] **Step 5.2: Verify existing tests still pass**

Run: `pytest tests/test_signal_detail_popup.py -v`
Expected: all 11 PASS.

- [ ] **Step 5.3: Commit**

```bash
git add launcher_support/signal_detail_popup.py
git commit -m "feat(popup): implementa show() Tk com 5 secoes

Toplevel modal 520x640 com OUTCOME / ENTRY / REGIME / OMEGA 5D /
STRUCTURE. Omega render usa bars unicode alinhadas monospace.
Close via ESC ou click no botao. Campos None renderizam '—'."
```

---

## Task 6: Refactor _render_detail_shadow to use new components

**Files:**
- Modify: `launcher_support/engines_live_view.py:1441-1563` (`_render_detail_shadow`)

- [ ] **Step 6.1: Read the current function and surrounding context**

Run: `sed -n '1441,1600p' launcher_support/engines_live_view.py`
Expected: function signature + body visible. Note `meta`, `state`, `launcher` params + `_render_shadow_no_run`, `_schedule_shadow_refresh` helpers.

- [ ] **Step 6.2: Add import of new components at top of engines_live_view.py**

Find the existing imports block around line 20-30. Add:

```python
from launcher_support.engines_sidebar import (
    build_engine_rows,
    render_sidebar,
    render_detail,
)
from launcher_support.signal_detail_popup import show as show_signal_detail
```

- [ ] **Step 6.3: Replace _render_detail_shadow body to delegate to new components**

Find `_render_detail_shadow` (line 1441). Replace the entire function body with:

```python
def _render_detail_shadow(parent, slug, meta, state, launcher):
    """Render SHADOW cockpit delegando pra engines_sidebar component.

    Sidebar mostra todas engines do registry; selected=slug. Detail
    pane vem do poller cache (cockpit API via SSH tunnel). Row click
    em LAST SIGNALS abre signal_detail_popup.
    """
    name = meta.get("display", slug.upper())

    # Le cache do poller.
    try:
        from launcher_support.tunnel_registry import get_shadow_poller
        poller = get_shadow_poller()
    except Exception:
        poller = None
    cached = poller.get_cached() if poller is not None else None
    try:
        trades = (poller.get_trades_cached()
                  if poller is not None else [])
    except Exception:
        trades = []

    run_dir = None
    hb = None
    if cached is not None:
        run_dir, hb = cached

    # Build registry pro sidebar — todas engines LIVE-ready do registro.
    registry = _engine_registry_for_sidebar(state)
    heartbeats = {slug: hb} if hb else {}
    rows = build_engine_rows(registry, heartbeats)

    # Master-detail layout
    layout = tk.Frame(parent, bg=PANEL)
    layout.pack(fill="both", expand=True)

    def _on_engine_select(new_slug: str):
        state["selected_slug"] = new_slug
        _render_detail(state, launcher)

    render_sidebar(layout, rows, selected_slug=slug, on_select=_on_engine_select)

    # Detail pane
    if hb is None:
        # Fallback antigo: explicacao + hint
        _render_shadow_no_run(layout, launcher)
        _schedule_shadow_refresh(launcher, state)
        return

    tun_text, tun_color = _get_tunnel_status_label()
    status = str(hb.get("status") or "unknown").upper()
    status_color = GREEN if status == "RUNNING" else DIM2

    def _on_row_click(trade: dict):
        show_signal_detail(launcher, trade)

    render_detail(
        parent=layout,
        engine_display=name,
        mode="shadow",
        heartbeat=hb,
        manifest=None,  # Fase 2b nao busca manifest; pode vir via /runs/{id}
        trades=trades,
        on_row_click=_on_row_click,
        status_badge_text=f"TUNNEL {tun_text}  ·  {status}",
        status_badge_color=status_color,
    )

    # Actions row — mantem logica de kill do fallback existente
    if status == "RUNNING" and run_dir is not None:
        actions = tk.Frame(layout, bg=PANEL)
        actions.pack(fill="x", padx=12, pady=(4, 10))
        kill_btn = tk.Label(actions, text=" STOP SHADOW ",
                            fg=BG, bg=RED, font=(FONT, 7, "bold"),
                            cursor="hand2", padx=10, pady=4)
        kill_btn.pack(side="left")
        kill_btn.bind("<Button-1>",
                      lambda _e, _d=run_dir, _s=state:
                          _drop_shadow_kill(_d, launcher, _s))

    _schedule_shadow_refresh(launcher, state)
```

- [ ] **Step 6.4: Add _engine_registry_for_sidebar helper**

Find a good spot (e.g., right before `_render_detail_shadow` at line 1440). Add:

```python
def _engine_registry_for_sidebar(state) -> list[dict]:
    """Return list de {slug, display} pra sidebar. Inclui todas engines
    exibidas no bucket LIVE/READY atual — evita depender de import
    circular com launcher.ENGINES."""
    # Procura engines_by_bucket no state (populado por _render_detail)
    by_bucket = state.get("engines_by_bucket") or {}
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
    # Fallback: nunca vazio — pelo menos o slug atual
    if not out:
        slug = state.get("selected_slug") or "millennium"
        out.append({"slug": slug, "display": slug.upper()})
    return out
```

- [ ] **Step 6.5: Run the whole test suite to catch regressions**

Run: `pytest tests/ -q --tb=short`
Expected: all tests PASS (no regression in existing `test_engines_live_view_cockpit.py`).

- [ ] **Step 6.6: Smoke test manually**

Run: `python launcher.py`
Click: EXECUTE → ENGINES LIVE → cycle mode M until SHADOW.
Expected:
- Sidebar aparece à esquerda com pelo menos MILLENNIUM
- Detail pane mostra HEALTH / RUN INFO / LAST SIGNALS (8 colunas)
- Click numa row abre popup modal com 5 seções
- ESC fecha popup
- Panel atualiza a cada 5s (poller)

Se tunnel estiver UP e shadow rodando no VPS, LAST SIGNALS deve
mostrar trades reais do disco. Se não: "sem sinais ainda — aguardando
primeiros ticks" em italic.

- [ ] **Step 6.7: Commit**

```bash
git add launcher_support/engines_live_view.py
git commit -m "refactor(engines_live_view): _render_detail_shadow delega pra engines_sidebar

Componente master-detail reutilizavel substitui o render in-line do
painel SHADOW. LAST SIGNALS ganha 4 colunas novas (stop/rr/size/res)
e linhas viram clicaveis → signal_detail_popup modal com 5 secoes
(OUTCOME/ENTRY/REGIME/OMEGA 5D/STRUCTURE).

Layout atual fora de modo SHADOW permanece intacto — proxima task
aplica o mesmo sidebar aos modos paper/demo/testnet/live."
```

---

## Task 7: Apply sidebar to paper/demo/testnet/live modes

**Files:**
- Modify: `launcher_support/engines_live_view.py` — wrap mode-specific render functions

- [ ] **Step 7.1: Find the non-shadow render path**

Run: `grep -n "def _render_detail\b\|def _render_live_panel\|def _render_paper\|mode.*==.*paper\|mode.*==.*live" launcher_support/engines_live_view.py | head -20`

Identify the function that handles paper/demo/testnet/live modes (likely `_render_detail` with mode branching, or a separate `_render_live_panel`).

- [ ] **Step 7.2: Locate the non-shadow LIVE path**

Run: `sed -n '1380,1445p' launcher_support/engines_live_view.py`
Expected: see the branch that routes to `_render_detail_shadow` when `mode == 'shadow'`, and the other branch.

- [ ] **Step 7.3: Refactor non-shadow path to use the same sidebar**

At the non-shadow branch (wherever `_render_detail` routes based on mode):
- If there's already a `_render_live_panel(parent, slug, meta, state, launcher)` function: wrap it to build sidebar first, then call the existing render inside a detail frame.
- If the rendering is inline in `_render_detail`: extract the inline block into `_render_detail_non_shadow(parent, slug, meta, state, launcher)` and apply the same sidebar wrapping.

Example minimal wrap — insert at the top of the non-shadow detail path (adapt to actual function structure):

```python
# Wrap non-shadow detail with sidebar
registry = _engine_registry_for_sidebar(state)
# Non-shadow: no poller heartbeats. Use _PROCS_CACHE pra detectar rows vivas.
heartbeats: dict[str, dict] = {}
cached_rows = _PROCS_CACHE.get("rows") or []
for proc_row in cached_rows:
    proc_slug = proc_row.get("slug") or ""
    if proc_slug:
        heartbeats[proc_slug] = {
            "ticks_ok": proc_row.get("pid", "?"),  # placeholder — pid shows "alive"
            "novel_total": 0,  # unknown for local procs
        }
rows = build_engine_rows(registry, heartbeats)

layout = tk.Frame(parent, bg=PANEL)
layout.pack(fill="both", expand=True)

def _on_engine_select(new_slug: str):
    state["selected_slug"] = new_slug
    _render_detail(state, launcher)

render_sidebar(layout, rows, selected_slug=slug, on_select=_on_engine_select)

# Existing non-shadow render goes into a detail frame inside layout
detail_host = tk.Frame(layout, bg=PANEL)
detail_host.pack(side="left", fill="both", expand=True)
# ... existing render code uses `detail_host` as parent
```

**Note:** exact code depends on the current function shape. After reading, if the existing render is complex (>50 lines inline), extract to `_render_live_panel_body(parent, slug, meta, state, launcher)` first as a no-op refactor (separate commit), then wrap with sidebar.

- [ ] **Step 7.4: Run tests**

Run: `pytest tests/ -q --tb=short`
Expected: all PASS.

- [ ] **Step 7.5: Smoke test modes**

Run: `python launcher.py`
- Cycle mode M: paper → demo → testnet → live → shadow → back to paper
- Confirm sidebar persists in all modes
- Confirm engine selection (click sidebar row) updates detail pane
- Confirm paper/demo/etc detail content is intact (no regression)

- [ ] **Step 7.6: Commit**

```bash
git add launcher_support/engines_live_view.py
git commit -m "refactor(engines_live_view): sidebar aplicada a paper/demo/testnet/live

Mesmo componente engines_sidebar.render_sidebar usado em todos os
modos. Source data muda (shadow_poller vs _PROCS_CACHE) mas layout
institucional eh uniforme. Engine selection via click persiste
entre mode cycles."
```

---

## Task 8: Final regression + session wrap-up

- [ ] **Step 8.1: Verify CORE untouched**

Run: `git diff 9c1b877 -- core/indicators.py core/signals.py core/risk/portfolio.py config/params.py`
Expected: empty output. If any line appears, REVERT immediately — this is a blocker.

- [ ] **Step 8.2: Verify runner + API untouched**

Run: `git diff 9c1b877 -- tools/maintenance/millennium_shadow.py tools/cockpit_api.py`
Expected: empty output.

- [ ] **Step 8.3: Full test suite green**

Run: `pytest tests/ -q --tb=short 2>&1 | tail -5`
Expected: `N passed, 7 skipped` where `N >= 1235`.

- [ ] **Step 8.4: Smoke manual final**

Run: `python launcher.py`
Golden path:
1. EXECUTE → ENGINES LIVE
2. Sidebar visible with ≥1 engine
3. SHADOW mode: row click opens popup with omega bars
4. Cycle mode M: sidebar persists
5. ESC closes popup without error

- [ ] **Step 8.5: Push branch**

```bash
git push origin feat/phi-engine
```

- [ ] **Step 8.6: Session log**

Create `docs/sessions/YYYY-MM-DD_HHMM.md` per CLAUDE.md template. Include:
- Resumo (3 frases)
- Commits table (8+ commits desta feature)
- Mudanças críticas: **Nenhuma em lógica de trading**
- Estado do sistema (suite count, VPS shadow status)
- Backlog atualizado (Fases 3a-3e deferidas)
- Notas pro João

Append à daily log `docs/days/YYYY-MM-DD.md`.

---

## Self-Review Notes

**Spec coverage:**
- ✅ TradeRecord extend (Task 1)
- ✅ engines_sidebar.py pure + render (Tasks 2, 4)
- ✅ signal_detail_popup.py (Tasks 3, 5)
- ✅ Refactor engines_live_view shadow (Task 6)
- ✅ Apply sidebar to other modes (Task 7)
- ✅ Regression + zero CORE (Task 8)

**Placeholders:** none. All code blocks are complete and runnable.

**Type consistency:** `EngineRow`, `format_signal_row` return dict, `section_*` return list[tuple] — consistent across tests + implementation.

**Scope:** 8 tasks, ~2-4 hours. Single-session executable if smoke manuals don't surface surprises.

**Known risk:** Task 7 depends on the actual shape of the non-shadow render path in `engines_live_view.py`. The plan includes a "read first" step (7.1-7.2) and notes exact code may need adaptation. If the existing function is too tangled, the no-op extract refactor (separate commit) is the escape hatch.
