"""AURUM — Binance Futures WebSocket live price feed.

Keeps an in-memory map `{symbol: (last_price, observed_ms)}` updated in
real time from the combined streams endpoint. Paper runner consults
`get_last(symbol)` at signal-execution time so entry uses the live
market price, not the bar-close `open[idx+1]` the signal was produced
against (which in a 15m system can be 15min stale).

Design:
    * Uses `websocket-client` (stdlib-adjacent, simpler sync API than
      asyncio websockets for a daemon-thread worker)
    * Combined stream to avoid N open sockets for N symbols
    * Default: `markPrice@1s` — 1Hz reference price, stable, matches the
      number used for liquidation. Also supports `aggTrade` for
      tick-level flow at the cost of more noise
    * Thread-safe via Lock; feed can be polled from any thread
    * Auto-reconnect with exponential backoff, capped at 60s
    * Never raises in caller paths: `get_last` returns None when stale
      or missing, caller decides fallback

The feed is explicitly passive — it only observes. No order routing, no
network writes, no dependency on account credentials. Safe to run
everywhere the paper runner runs.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

try:
    import websocket  # websocket-client
except ImportError as _exc:  # pragma: no cover — deploy-time check
    websocket = None  # type: ignore[assignment]
    _IMPORT_ERR = _exc
else:
    _IMPORT_ERR = None

log = logging.getLogger(__name__)

_BINANCE_FUTURES_WS = "wss://fstream.binance.com/stream"
_DEFAULT_STREAM = "markPrice@1s"


def parse_message(text: str) -> tuple[str, float, int] | None:
    """Parse a single combined-stream payload. Returns (symbol, price, event_ms).

    Accepts both markPrice (`e: markPriceUpdate`, price in `p`) and
    aggTrade (`e: aggTrade`, price in `p` as well, spot path uses `a`).
    Returns None for messages we don't recognize; callers ignore those.
    """
    try:
        payload = json.loads(text)
    except Exception:  # noqa: BLE001 — any JSON error is a broken frame
        return None
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return None
    event = data.get("e")
    symbol = str(data.get("s") or "").upper()
    if not symbol:
        return None
    if event == "markPriceUpdate":
        price_raw = data.get("p")
        ts_ms = int(data.get("E") or 0)
    elif event == "aggTrade":
        price_raw = data.get("p")
        ts_ms = int(data.get("T") or data.get("E") or 0)
    else:
        return None
    try:
        price = float(price_raw)
    except (TypeError, ValueError):
        return None
    return symbol, price, ts_ms


@dataclass
class WSPriceFeed:
    """Live price feed for Binance Futures symbols.

    Typical use (inside paper runner):

        feed = WSPriceFeed(symbols=["BTCUSDT", "XRPUSDT"])
        feed.start()
        ...
        px = feed.get_last("BTCUSDT")       # float | None
        age = feed.get_freshness_sec("BTCUSDT")  # float | None
        ...
        feed.stop()
    """

    symbols: list[str]
    stream: str = _DEFAULT_STREAM
    base_url: str = _BINANCE_FUTURES_WS
    max_backoff_sec: float = 60.0

    _prices: dict[str, tuple[float, int]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _thread: threading.Thread | None = None
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _started: bool = False
    _ws: "websocket.WebSocketApp | None" = None  # type: ignore[name-defined]

    # ─── Public API ────────────────────────────────────────────────

    def start(self) -> None:
        """Idempotent; spins the background worker on first call."""
        if _IMPORT_ERR is not None:
            log.warning("websocket-client not installed: %s", _IMPORT_ERR)
            return
        if self._started:
            return
        self._started = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="aurum-ws-price-feed", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal stop, close socket, join thread (best-effort)."""
        self._stop_event.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def get_last(self, symbol: str) -> float | None:
        """Latest observed price for `symbol`, or None if never seen."""
        sym = symbol.upper()
        with self._lock:
            entry = self._prices.get(sym)
        return entry[0] if entry else None

    def get_last_update_ms(self, symbol: str) -> int | None:
        sym = symbol.upper()
        with self._lock:
            entry = self._prices.get(sym)
        return entry[1] if entry else None

    def get_freshness_sec(self, symbol: str) -> float | None:
        """Seconds since last update for `symbol`. None if never seen."""
        ms = self.get_last_update_ms(symbol)
        if ms is None or ms <= 0:
            return None
        return max(0.0, (time.time() * 1000.0 - ms) / 1000.0)

    def snapshot(self) -> dict[str, tuple[float, int]]:
        """Shallow copy of the price map — useful for diagnostics."""
        with self._lock:
            return dict(self._prices)

    # ─── Internals ─────────────────────────────────────────────────

    def _apply_update(self, symbol: str, price: float, ts_ms: int) -> None:
        sym = symbol.upper()
        if price <= 0:
            return
        with self._lock:
            self._prices[sym] = (price, ts_ms)

    def _stream_url(self) -> str:
        """Combined-stream URL: ?streams=sym1@stream/sym2@stream/..."""
        streams = "/".join(
            f"{s.lower()}@{self.stream}" for s in self.symbols if s
        )
        return f"{self.base_url}?streams={streams}"

    def _run_loop(self) -> None:
        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                ws = websocket.WebSocketApp(  # type: ignore[union-attr]
                    self._stream_url(),
                    on_message=lambda _w, msg: self._on_message(msg),
                    on_error=lambda _w, err: log.debug(
                        "ws error: %s", type(err).__name__),
                    on_close=lambda _w, code, reason: log.debug(
                        "ws closed: %s %s", code, reason),
                )
                self._ws = ws
                ws.run_forever(ping_interval=25, ping_timeout=10)
            except Exception as exc:  # noqa: BLE001
                log.debug("ws run_forever raised: %s", type(exc).__name__)
            finally:
                self._ws = None
            if self._stop_event.is_set():
                return
            # Died; back off and retry.
            if self._stop_event.wait(timeout=backoff):
                return
            backoff = min(self.max_backoff_sec, backoff * 2.0)

    def _on_message(self, msg: str) -> None:
        parsed = parse_message(msg)
        if parsed is None:
            return
        sym, price, ts_ms = parsed
        self._apply_update(sym, price, ts_ms)


def make_live_price_fn(feed: WSPriceFeed,
                       max_age_sec: float = 60.0
                       ) -> Callable[[str], float | None]:
    """Adapter: returns a callable `(symbol) -> price | None` that
    enforces a freshness cap. Too-stale quotes return None so callers
    can fall back to the signal's original entry."""
    def _fn(symbol: str) -> float | None:
        px = feed.get_last(symbol)
        if px is None:
            return None
        age = feed.get_freshness_sec(symbol)
        if age is not None and age > max_age_sec:
            return None
        return px
    return _fn
