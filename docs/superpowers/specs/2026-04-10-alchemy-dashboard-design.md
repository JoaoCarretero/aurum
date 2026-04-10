# ALCHEMY — Arbitrage Dashboard

**Date:** 2026-04-10
**Status:** Design approved, ready for implementation planning
**Scope:** New top-level menu entry in `launcher.py` with a dedicated fullscreen arbitrage cockpit

---

## Overview

ALCHEMY is a new top-level menu entry in the AURUM terminal launcher, dedicated to cross-venue arbitrage. It opens a fullscreen HEV-Terminal-themed cockpit (Half-Life 1 amber HUD + restrained hermetic/alchemical iconography) that both **reads state from** and **controls** the existing `engines/arbitrage.py` engine. It replaces the current `STRATEGIES → live → JANE STREET` entrypoint as the primary surface for arbitrage work.

The visual direction is final: pure Half-Life HEV Terminal aesthetic (dense amber cockpit, VT323 pixel font, hazard stripes, λ watermark, CRT scanlines), with planetary glyphs (☉ ☽ ☿ ♂ ♃) as venue icons and Latin panel titles (`OPVS MAGNVM`, `FLVX AVRVM`, `CORPVS APERTVM`, etc.) as restrained alchemical flavor.

Reference mockup: `.superpowers/brainstorm/2030-1775852615/content/layout-full.html`

---

## Goals

- **Single-surface arbitrage control** — dashboard + engine controls + venue connections in one fullscreen view, no tabs, no scroll
- **Zero duplication of engine logic** — the dashboard consumes state written by `engines/arbitrage.py`; it does not re-implement opportunity scanning, funding fetching, or PnL math
- **Live observability** — opportunities, positions, funding rates, venue health, and log stream update every few seconds while the engine runs
- **Control surface** — start/stop the engine in PAPER/DEMO/TESTNET/LIVE modes, edit all key parameters inline, toggle venues, trigger the kill-switch
- **Visual fidelity** — the cockpit must feel like a HEV Suit readout from 1998: amber on black, VT323/Share Tech Mono, hazard stripes, λ watermark, CRT scanlines, glow on vitals

## Non-Goals

- **Not a rewrite of `engines/arbitrage.py`.** The engine stays exactly as it is (1649 lines); we only add a small state-publisher that writes the snapshot the dashboard reads.
- **Not a new market type or exchange integration.** ALCHEMY uses the existing `ConnectionManager` and the venues already supported by `arbitrage.py` (Binance, Bybit, OKX, Hyperliquid, Gate).
- **Not a replacement for the broader launcher.** Pressing `Esc` returns to the normal launcher window at its prior geometry.
- **Not responsive.** Designed for a fullscreen window on the user's primary monitor. Minimum usable size assumed ≥ 1366×768.
- **Not a historical analytics view.** Realized-PnL curves, trade history detail, and run comparison stay under `STRATEGIES → results`. ALCHEMY is a live cockpit.

---

## User Flow

1. User launches `launcher.py` → splash → main menu now shows `ALCHEMY` as a top-level item alongside `MARKETS · CONNECTIONS · TERMINAL · STRATEGIES · RISK · COMMAND CENTER · SETTINGS`.
2. User clicks `ALCHEMY` (or presses `A`). The launcher window saves its current geometry, switches to `attributes('-fullscreen', True)`, and renders the cockpit.
3. **If the arbitrage engine is not running:** all read-only panels show last-known state from the most recent run directory (or empty placeholders if none). The bottom `ENGINE CONTROL` strip is the only fully-live region.
4. **User presses a mode button** (`▶ PAPER` / `▶ DEMO` / `▶ TESTNET` / `▶ LIVE`). The launcher spawns `python engines/arbitrage.py` as a subprocess with the appropriate mode flag, pipes stdout to the log panel, and begins polling the engine's state snapshot.
5. **Live mode button** triggers a confirm dialog with hazard-red styling: "REAL CAPITAL — type LIVE to confirm".
6. All nine panels refresh on a tick (default 2s). Opportunities, funding grid, positions, venue health, logs, and risk gauges all update from the snapshot file and the log stream.
7. User edits any parameter (`MIN_APR`, `MAX_POS`, etc.) → the new value is written to `config/alchemy_params.json` and signaled to the engine via a watched file (engine reloads on next scan cycle).
8. User presses `Esc` → kill-switch prompt if engine is running ("engine still running — stop before exit? [Y/N]"). On exit, window returns to prior geometry and launcher main menu.
9. User may press `⚠ KILL` at any time — sends SIGTERM to the engine process, which triggers its existing kill-switch path (flatten positions, save state, exit cleanly).

---

## UI Design

Reference mockup: `.superpowers/brainstorm/2030-1775852615/content/layout-full.html`

**Canvas:** fullscreen (primary monitor). Layout targets 1600×900 as the reference resolution; grid scales proportionally for larger displays.

**Theme constants** (add to the palette section of `launcher.py`):

```
BG_HEV     = "#000000"   # pure black for cockpit
PANEL_HEV  = "#030200"   # near-black panel fill
BORDER_HEV = "#3a2200"   # dim amber border
HAZARD     = "#ffcc00"   # yellow used for alerts + title highlights
BLOOD      = "#8b0000"   # live mode / kill button
AMBER_GLOW = "#ffb347"   # slightly brighter amber for vitals
# existing AMBER, AMBER_D, GREEN, RED, DIM reused
```

**Fonts:** Tkinter supports TTF loading via `tkextrafont` or direct font file registration. If loading custom fonts is nontrivial on the target Windows environment, the fallback is: `Consolas` bold for VT323 role, `Consolas` regular for Share Tech Mono role. The mockup uses VT323/Share Tech Mono/Cinzel — the implementation should attempt to load these as bundled TTFs in `server/fonts/` (new directory), falling back to `Consolas` with no crash. This is the single largest aesthetic risk and must be validated early in implementation.

**Chrome:**
- Top hazard stripe (12px) drawn via `tk.Canvas` with diagonal yellow/black pattern
- Top bar (~66px): `λ ALCHEMY` brand, UTC clock, and six HEV vitals (ACCOUNT · DRAWDOWN · POSITIONS · EXPOSURE · MODE · ENGINE)
- Grid of 9 panels (see below)
- Bottom hazard stripe (12px)
- CRT scanline overlay: faint repeating horizontal lines drawn as a full-canvas overlay frame with alternating 1-px `AMBER`-tinted rows at ~4% alpha — implemented as a tiled `PhotoImage` on a `Label` placed with `place(relwidth=1, relheight=1)` behind no interactive widgets, so clicks pass through on the sides but not the pattern itself. If this fools clicks in Tk, fall back to no scanlines and only draw them on dedicated canvas regions.
- λ watermark: a huge `Label` with `font=(SERIF, 520)` and `fg="#0a0500"` placed at `relx=0.78 rely=0.55`. Non-interactive.

**Grid layout** (grid weights, not pixels):

| col →  | 1 (26%)             | 2 (48%)                        | 3 (26%)                |
| ------ | ------------------- | ------------------------------ | ---------------------- |
| row 1  | [01] OPPORTUNITIES  | [02] FUNDING RATES             | [04] POSITIONS         |
| row 2  | [01] OPPORTUNITIES  | [03] BASIS & SPREAD            | [05] VENUE HEALTH      |
| row 3  | [08] RISK CONSOLE   | [09] LOG STREAM                | [06] CONNECTIONS       |
| row 4  | [07] ENGINE CONTROL (spans all 3 columns, ~50px)                        |

- `[01] OPPORTUNITIES` spans rows 1–2 (tall column) because it's the densest and most important panel
- `[07] ENGINE CONTROL` spans all columns at the bottom (buttons + params + motto)
- All panels share the same chrome: double corner brackets, dashed title divider, amber-on-black, Latin subtitle right-aligned in title row

---

## Panel Specifications

Each panel is a `tk.Frame` with a consistent render function. All panels subscribe to a single tick driver (`self._alch_after_id`) that fires every `ALCH_TICK_MS` (default 2000 ms) and re-renders from the current snapshot dict.

### [01] OPPORTVNITATES — `opus magnum`
Ranked list of live arbitrage candidates. Reads `snapshot.opportunities` (list of dicts).
Columns: `#`, `SYM`, `LONG` (venue glyph), `SHORT` (venue glyph), `SPRD`, `APR`, `Ω`. One horizontal amber bar under each row encoding the Omega score visually. Top 12 rows visible, sorted descending by Omega. Hover/click on a row highlights it (no action yet — future scope).

### [02] FVNDING · RATES — `flux aurum`
Funding rate heatmap. Reads `snapshot.funding` (dict: `{symbol: {venue: rate}}`).
Columns: 8 symbols × 5 venues grid. Cells colored: red-tinted for `rate > +0.02%`, green-tinted for `rate < 0`, neutral amber otherwise. Below the grid: countdown to next funding per venue (`BIN 2h14m · BYB 2h14m · ...`).

### [03] BASIS · PERP/SPOT — `differentia`
Basis over time (perp vs spot). Reads a small ring buffer `snapshot.basis_history` (list of tuples). Draws on a `tk.Canvas` — three line traces (BTC/ETH/SOL) over the last 60 minutes, with a dashed zero line. Shows `σ` and `μ` stats in the bottom row. Simple polyline rendering, no axes labels beyond "t−60m" / "now".

### [04] POSITIONES — `corpus apertum`
Open positions table. Reads `snapshot.positions`.
Columns: `SYM`, `VENUES` (long/short glyph pair), `PNL`, `ΔEDGE` (% decay from entry), `EXIT` (time remaining, colored hazard if < 2h). Below the table: total unrealized and realized PnL lines.

### [05] VENVE · HEALTH — `pulsus`
Per-venue health row. Reads `snapshot.venue_health`.
Columns: `VEN` (dot + glyph + name), `PING` (ms), `ERR` (consecutive failure count), `RL` (rate limit usage %), `KS` (kill-switch status). Dots: green / yellow (>75% rate limit) / red (disabled). Non-interactive.

### [06] CONNECTIONES — `nexus`
Connection manager surface for ALCHEMY's five venues. Reads `ConnectionManager` state directly.
Rows: `Binance · ☉ · dot · mode`, `Bybit · ☽ · dot · mode`, `OKX · ☿ · dot · mode`, `Hyperliquid · ♂ · dot · mode`, `Gate · ♃ · dot · mode`. Each row clickable to toggle mode (paper/testnet/demo/live) or reconnect. Keybinds shown at bottom: `[TAB] toggle · [K] edit keys · [R] reconnect`.

### [07] MACHINA · ENGINE CONTROL — `solve et coagula`
Bottom strip. Three groups:
- **Buttons:** `▶ PAPER` `▶ DEMO` `▶ TESTNET` `▶ LIVE` `■ STOP` `⚠ KILL`. Active mode's button shows green border/glow; `LIVE` has blood-red border always; `KILL` is always red-filled.
- **Params:** inline editable: `MIN_APR`, `MIN_SPRD`, `MAX_POS`, `POS_PCT`, `LEV`, `SCAN_S`, `EXIT_H`, `MAX_DD`. Click a value → tk.Entry replaces the Label → Enter commits → writes to `config/alchemy_params.json` and touches a watch file.
- **Motto:** `S O L V E  E T  C O A G U L A` in Cinzel, right-aligned, decorative only.

### [08] RISK · CONSOLE — `timor`
Six horizontal gauges (bar + label + value):
`EXPO`, `DD DAY`, `DD MAX`, `LOSSES` (n/3), `SORTINO`, `TRADES`.
Bar color shifts from amber → hazard → red as value approaches configured limit. Reads from snapshot + running PnL.

### [09] LOG · STREAM — `cronica`
Tail of the engine's stdout + `arb.log`, colored by severity level (`info`=amber, `ok`=green, `warn`=hazard, `err`=red). Fixed height, newest at top, ~10 rows visible. Lines are parsed with a simple regex against the engine's log formatter (`%(asctime)s %(levelname)-6s %(message)s`).

---

## Engine Integration & Data Flow

The existing `engines/arbitrage.py` already writes a partial state file at `DIR/state/positions.json`. We extend it with a single **snapshot writer** that publishes everything the dashboard needs in one file, atomically, at the end of each scan cycle.

### Snapshot file

**Path:** `data/arbitrage/<run_id>/state/snapshot.json` (alongside the existing `positions.json`)

**Written by:** `engines/arbitrage.py` — new function `_write_snapshot(self)` called at the tail of the main scan loop, writing atomically via temp-file rename.

**Schema:**

```json
{
  "ts": "2026-04-10T14:32:07Z",
  "run_id": "2026-04-10_1432",
  "mode": "paper",
  "engine_pid": 12345,
  "account": 4982.14,
  "peak": 5042.00,
  "exposure_usd": 2040.00,
  "drawdown_pct": -1.20,
  "realized_pnl": 341.82,
  "unrealized_pnl": 57.69,
  "losses_streak": 1,
  "killed": false,
  "sortino": 2.14,
  "trades_count": 17,
  "opportunities": [
    {"sym":"BTCUSDT","long":"okx","short":"binance","spread":0.00042,"apr":46.2,"omega":8.7,"fill_prob":0.94}
  ],
  "funding": {
    "BTCUSDT": {"binance":0.00012,"bybit":0.00008,"okx":-0.00004,"hyperliquid":0.00041,"gate":0.00015}
  },
  "next_funding": {"binance":1712757600,"bybit":1712757600,"okx":1712772000,"hyperliquid":1712754000,"gate":1712765000},
  "positions": [
    {"sym":"BTCUSDT","long":"okx","short":"binance","pnl":42.18,"edge_decay_pct":12,"exit_in_s":10920}
  ],
  "venue_health": {
    "binance":{"ping_ms":12,"err":0,"rate_limit_pct":18,"disabled":false},
    "hyperliquid":{"ping_ms":null,"err":3,"rate_limit_pct":null,"disabled":true}
  },
  "basis_history": {
    "BTCUSDT": [[1712754000, 0.0042], [1712754060, 0.0038], "..."]
  }
}
```

### Launcher side — snapshot reader

Add `core/alchemy_state.py`:
- `AlchemyState` class wraps snapshot reading
- Finds the **latest** `data/arbitrage/*/state/snapshot.json` on demand (newest mtime)
- If engine is running (tracked by `self.proc`), reads from that run's snapshot specifically
- Caches last successful read; returns stale data with a `stale=True` flag if file is missing or older than `ALCH_STALE_S` (default 10s)

### Parameter hot-reload

- Launcher writes `config/alchemy_params.json` with the full param dict
- Launcher touches `config/alchemy_params.json.reload` (empty file) to signal
- `engines/arbitrage.py` checks the reload flag at the top of each scan cycle — if present, reloads params and deletes the flag
- Params covered: `MIN_SPREAD`, `MIN_APR`, `MAX_POS`, `POS_PCT`, `LEV`, `SCAN_S`, `EXIT_H`, `MAX_DD_PCT`, `KILL_LOSSES`

### Process management

Reuse the existing subprocess/queue pattern from the launcher. ALCHEMY's engine control buttons:
- Build command: `python engines/arbitrage.py --mode <paper|demo|testnet|live>` (needs `--mode` arg added to `arbitrage.py`; today it's `ARB_LIVE`/`ARB_DEMO` globals)
- Capture stdout into a bounded `deque(maxlen=500)` for the log panel
- `■ STOP` sends SIGTERM (graceful shutdown via engine's existing signal handler)
- `⚠ KILL` sends SIGTERM + displays "flattening positions..." until process exits, then hazards the UI
- On launcher window close, if engine is running, confirm before killing

---

## Technical Architecture

### New files

- `core/alchemy_state.py` — snapshot reader, parameter writer, run directory discovery (~120 lines)
- `core/alchemy_ui.py` — the nine panel render functions + the fullscreen entry/exit helpers + tick driver (~600 lines, large but focused)
- `config/alchemy_params.json` — runtime parameters (created on first run)
- `server/fonts/VT323.ttf`, `ShareTechMono.ttf`, `Cinzel.ttf` — bundled fonts (downloaded from Google Fonts, open license)

### Files modified

- `launcher.py`:
  - Add `ALCHEMY` to `MAIN_MENU` (between STRATEGIES and RISK, or between RISK and COMMAND CENTER — finalize during implementation)
  - Add `_alchemy_enter()` / `_alchemy_exit()` methods that handle fullscreen toggle, palette override, binding of Esc
  - Import and wire `core/alchemy_ui.py`
  - Route `_menu("alchemy")` → `_alchemy_enter()`
  - Update `_clr()` to also cancel the `_alch_after_id` tick
- `engines/arbitrage.py`:
  - Add `--mode` argparse flag replacing the boolean globals
  - Add `_write_snapshot(self)` method
  - Add `_check_reload_params()` at top of scan loop
  - Call `_write_snapshot()` at end of scan loop
- `core/connections.py`: no changes — ALCHEMY uses the existing `ConnectionManager`

### Tick driver

A single `self.after(ALCH_TICK_MS, self._alch_tick)` loop owns all nine panel updates. The tick:
1. Reads the snapshot (cached if fresh)
2. Drains any new stdout lines from the engine subprocess queue into the log buffer
3. Re-renders each panel's dynamic content (avoids destroying widgets — updates `StringVar`s and canvas items)
4. Re-schedules itself
5. If the snapshot is stale for > 10s while the engine is supposedly running, dims all panels and shows a `SNAPSHOT STALE · engine not responding` overlay

### Fullscreen lifecycle

```python
def _alchemy_enter(self):
    self._alch_prev_geometry = self.geometry()
    self._alch_prev_minsize = self.minsize()
    self.minsize(1, 1)
    self.attributes('-fullscreen', True)
    self._clr(); self._unbind()
    # ... render cockpit ...
    self.bind('<Escape>', self._alchemy_exit)

def _alchemy_exit(self, event=None):
    if self.proc and self.proc.poll() is None:
        # confirm before leaving
        ...
    self.attributes('-fullscreen', False)
    self.geometry(self._alch_prev_geometry)
    self.minsize(*self._alch_prev_minsize)
    self._menu('main')
```

---

## Testing

- **Unit:** `core/alchemy_state.py` snapshot reader — test with fixture JSON files (fresh, stale, missing, malformed).
- **Unit:** param hot-reload — write params, touch flag, assert engine reloads (can mock the engine side).
- **Integration (manual):** launch ALCHEMY → click PAPER → verify all 9 panels populate within 5s → edit `MIN_APR` → verify change lands in running engine → press `⚠ KILL` → verify clean exit.
- **Visual regression (manual):** compare live tkinter cockpit against `layout-full.html` mockup side by side; verify font loading, color palette, hazard stripes, and λ watermark render.

No automated UI tests — Tk is painful to test headlessly and the visual fidelity is the point.

---

## Open Questions (to resolve in implementation)

1. **Font loading on Windows:** does `tkextrafont` work cleanly in the AURUM environment, or do we fall back to `Consolas`? Decide after a 30-minute spike — do not block the rest of the work.
2. **Multi-monitor fullscreen:** `attributes('-fullscreen', True)` targets the monitor the window is on. Acceptable? Or do we need explicit primary-monitor detection?
3. **Scanline overlay interaction:** does the overlay `Label` swallow clicks to panels underneath? If yes, drop scanlines or restrict them to a `Canvas` inside each panel.
4. **Engine `--mode` flag naming:** reconcile with any existing `ARB_LIVE`/`ARB_DEMO` env-var or flag handling elsewhere in the codebase.
5. **Latest-run discovery:** when the engine is not running, which previous run's snapshot do we show? Latest by mtime, or explicit "last run by this mode"? Default to latest mtime; revisit if confusing.
6. **Basis history source:** the current engine doesn't retain a basis ring buffer. Adding one is ~20 lines in `arbitrage.py` (deque per symbol in the scan loop). Included in scope; flag if it creeps.

---

## Deliverable

A single approved implementation plan (next step: writing-plans skill) that decomposes this spec into independently-reviewable tasks with clear acceptance criteria per task.
