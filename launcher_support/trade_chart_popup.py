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
from launcher_support.trade_history_panel import (
    normalize_direction,
    format_r_multiple,
)


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
        end_anchor = now_ts
        duration_sec = max(tf_sec, now_ts - entry_ts)
    else:
        end_anchor = exit_ts
        duration_sec = max(tf_sec, exit_ts - entry_ts)

    duration_candles = max(1, duration_sec // tf_sec)
    # Window target: duration × 1.6, floored at MIN, capped at MAX.
    window_candles = max(_MIN_WINDOW_CANDLES,
                         int(duration_candles * _WINDOW_PADDING_FACTOR))
    window_candles = min(_MAX_WINDOW_CANDLES, window_candles)

    pad_candles = (window_candles - duration_candles) // 2
    if pad_candles >= 0:
        pad_sec = pad_candles * tf_sec
        start = entry_ts - pad_sec
        end = end_anchor + pad_sec
    else:
        # Trade exceeds cap (>500 candles): center the cap around the trade mid.
        mid = (entry_ts + end_anchor) // 2
        half = (window_candles * tf_sec) // 2
        start = mid - half
        end = mid + half
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
        # Only render a "current" marker if we have a real last-seen price
        # distinct from entry. Falling back to entry would plot the green
        # dot on top of the yellow entry line (visual collision).
        cur_px = trade.get("exit_p")
        if cur_px and float(cur_px) != float(entry or 0):
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
            OSError, ValueError, json.JSONDecodeError,
            IndexError, KeyError, TypeError):
        # IndexError/KeyError/TypeError catch malformed kline rows if
        # Binance ever changes the schema — empty DF instead of crash.
        return parse_klines_to_df([])


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

        # Release prior Figure explicitly — matplotlib doesn't auto-GC
        # Figure() instances built without pyplot. On a live-refreshing
        # chart that's ~720 rebuilds/hour; accumulates without this.
        prior_fig = getattr(self, "_fig", None)
        if prior_fig is not None:
            try:
                prior_fig.clear()
            except Exception:
                pass
            self._fig = None
        self._canvas = None

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
            retry = tk.Label(
                self._chart_frame, text="  ↻ retry  ",
                font=(self.font_name, 8, "bold"),
                fg=self.colors["BG"], bg=self.colors["AMBER"],
                cursor="hand2", padx=10, pady=4,
            )
            retry.pack()
            retry.bind("<Button-1>", lambda _e: self._render_chart())
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
        # Null the stale after-id first: Tk already consumed it by firing
        # this callback; keeping it would mislead destroy() into cancelling
        # a non-existent timer (harmless, but invariant worth holding).
        self._after_id = None
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
            self._after_id = None
        # Release matplotlib Figure so the Axes/lines/patches graph is
        # eligible for GC. Without this each popup leaks its final Figure.
        fig = getattr(self, "_fig", None)
        if fig is not None:
            try:
                fig.clear()
            except Exception:
                pass
            self._fig = None
        self._canvas = None
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
