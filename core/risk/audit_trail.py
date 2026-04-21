"""AURUM — immutable order audit trail.

Append-only JSONL log of every order intent and exchange response. One
file per (UTC) month at ``data/audit/orders-YYYY-MM.jsonl``. Never
rewritten, never deleted by this module. Intended to answer three
questions after any live trading day:

  1. What did the engines want to do?  (intent rows)
  2. What did the exchange actually do?  (ack / fill rows)
  3. Did reality match intent?  (reconciliation over the trail)

Design notes
------------
- **Append-only.** No seek, no truncate, no overwrite. File opened
  with mode "a" and closed per call — a crash mid-write loses at
  most the partial row, not prior rows.
- **One file per month.** Keeps individual files bounded (a busy
  engine at 30 trades/day × 30 days ≈ 900 rows ≈ <1MB). Simple
  rotation, no locks needed if the writer is single-threaded per
  engine.
- **Hash chain on by default.** Each row includes ``prev_hash`` pointing
  at the SHA-256 of the previous row's canonical JSON encoding. Makes
  the trail tamper-evident: any retroactive edit breaks the chain from
  that point forward. Pass ``hash_chain=False`` to opt out (not
  recommended for live trading).
- **Schema-lite.** Required fields are short and fixed; everything
  else goes under ``payload``. This module does not validate payloads
  — that's the caller's contract with the exchange adapter.
- **No dependencies.** stdlib only. This file is safe to import in
  any engine context, from offline backtests to live order routers.

Schema
------
Every row is a JSON object with at minimum:

    {
      "ts":            ISO-8601 UTC,
      "event":         "intent" | "ack" | "fill" | "reject" | "cancel",
      "engine":        str,                e.g., "newton"
      "strategy_ver":  str,                e.g., "v3.6"
      "client_oid":    str,                stable UUID from the engine
      "venue":         str,                "binance_futures" | ...
      "symbol":        str,                "BTCUSDT"
      "side":          "BUY" | "SELL",
      "qty":           float,
      "price":         float | None,
      "status":        str,                free-form exchange status
      "payload":       dict,               everything else
      "prev_hash":     str | None,         only if hash_chain=True
    }

Usage
-----

    from core.audit_trail import AuditTrail, OrderEvent

    trail = AuditTrail(engine="newton", strategy_ver="v3.6",
                       hash_chain=True)

    # Intent (before sending to exchange)
    trail.write(OrderEvent(
        event="intent",
        client_oid="newton-20260411-0001",
        venue="binance_futures",
        symbol="BTCUSDT",
        side="BUY",
        qty=0.01,
        price=63250.5,
        status="pending",
        payload={"score": 0.58, "reason": "zscore_entry"},
    ))

    # Ack from exchange
    trail.write(OrderEvent(
        event="ack",
        client_oid="newton-20260411-0001",
        ...
    ))
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path


AUDIT_DIR = Path("data") / "audit"


_REQUIRED_EVENTS = frozenset({"intent", "ack", "fill", "reject", "cancel"})


@dataclass
class OrderEvent:
    """One row in the audit trail. Fields map 1:1 to the on-disk schema."""

    event:       str
    client_oid:  str
    venue:       str
    symbol:      str
    side:        str
    qty:         float
    price:       float | None = None
    status:      str = ""
    payload:     dict = field(default_factory=dict)


def _canonical_json(obj: dict) -> str:
    """Deterministic JSON encoding for hashing.

    ``sort_keys=True`` + ``separators=(',',':')`` + ``ensure_ascii=False``
    gives a stable byte sequence regardless of Python dict insertion
    order — same input → same hash.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _hash(row: dict) -> str:
    """SHA-256 of the canonical JSON encoding of ``row``."""
    return hashlib.sha256(_canonical_json(row).encode("utf-8")).hexdigest()


class AuditTrail:
    """Append-only writer. Not async — use one instance per thread or
    wrap calls in your own lock if sharing. Per-month file rotation
    happens automatically based on the current UTC month."""

    def __init__(self, engine: str, strategy_ver: str,
                 hash_chain: bool = True,
                 audit_dir: Path = AUDIT_DIR) -> None:
        self.engine = engine
        self.strategy_ver = strategy_ver
        self.hash_chain = hash_chain
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_hash: str | None = None
        if hash_chain:
            self._last_hash = self._scan_last_hash()

    # ── File selection ────────────────────────────────────────────────

    def _path_for(self, dt: datetime) -> Path:
        return self.audit_dir / f"orders-{dt.year:04d}-{dt.month:02d}.jsonl"

    def current_path(self) -> Path:
        """Return the file path for the current UTC month."""
        return self._path_for(datetime.now(timezone.utc))

    # ── Hash chain ────────────────────────────────────────────────────

    def _scan_last_hash(self) -> str | None:
        """Walk backward from the newest month file, return the hash of
        the last row that had a ``prev_hash`` field (i.e., the tail of
        the existing chain). ``None`` on a fresh repo."""
        try:
            files = sorted(self.audit_dir.glob("orders-*.jsonl"),
                           reverse=True)
        except OSError:
            return None
        for f in files:
            try:
                last_line = self._read_last_nonempty_line(f)
                if last_line is None:
                    continue
                row = json.loads(last_line)
                # Compute hash of this row (the stored row IS the
                # prev_hash seed for the next write).
                return _hash(row)
            except (OSError, json.JSONDecodeError):
                continue
        return None

    @staticmethod
    def _read_last_nonempty_line(path: Path) -> str | None:
        """Read the last non-empty line without loading the whole file."""
        with path.open("rb") as fh:
            fh.seek(0, 2)
            pos = fh.tell()
            if pos <= 0:
                return None

            chunks: list[bytes] = []
            line = b""
            while pos > 0:
                read_size = min(4096, pos)
                pos -= read_size
                fh.seek(pos)
                chunk = fh.read(read_size)
                chunks.insert(0, chunk)
                data = b"".join(chunks).rstrip(b"\r\n")
                if not data:
                    continue
                parts = data.splitlines()
                if parts:
                    line = parts[-1].strip()
                    if line:
                        break

            if not line:
                return None
            return line.decode("utf-8", errors="replace")

    # ── Write ─────────────────────────────────────────────────────────

    def write(self, event: OrderEvent) -> dict:
        """Append a row. Returns the row dict as written.

        The caller gets back the exact object that hit disk (including
        ``ts``, ``engine``, ``strategy_ver``, and ``prev_hash`` if
        enabled). Handy for logging or echoing to a UI.
        """
        if event.event not in _REQUIRED_EVENTS:
            raise ValueError(
                f"OrderEvent.event must be one of {sorted(_REQUIRED_EVENTS)}, "
                f"got {event.event!r}")

        ts = datetime.now(timezone.utc).isoformat()
        row = {
            "ts":           ts,
            "event":        event.event,
            "engine":       self.engine,
            "strategy_ver": self.strategy_ver,
            "client_oid":   event.client_oid,
            "venue":        event.venue,
            "symbol":       event.symbol,
            "side":         event.side,
            "qty":          event.qty,
            "price":        event.price,
            "status":       event.status,
            "payload":      event.payload,
        }
        if self.hash_chain:
            row["prev_hash"] = self._last_hash

        with self._lock:
            path = self.current_path()
            line = _canonical_json(row) + "\n"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
            if self.hash_chain:
                self._last_hash = _hash(row)

        return row

    # ── Read helpers ──────────────────────────────────────────────────

    def iter_rows(self, path: Path | None = None):
        """Yield every row in the given month's file (default: current)."""
        p = path or self.current_path()
        if not p.exists():
            return
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def verify_chain(self, path: Path | None = None) -> tuple[bool, int]:
        """Walk the chain in ``path`` and return (all_ok, row_count).

        Reports the FIRST break if any: if row N's ``prev_hash`` does not
        match the hash of row N-1, the walk stops and returns False. A
        well-formed fresh file with no tampering returns ``(True, N)``.
        """
        p = path or self.current_path()
        if not p.exists():
            return True, 0
        prev = None
        count = 0
        for row in self.iter_rows(p):
            count += 1
            claimed = row.get("prev_hash")
            if prev is not None and claimed != prev:
                return False, count
            # Hash THIS row as stored (without mutating it)
            prev = _hash(row)
        return True, count


__all__ = ["AuditTrail", "OrderEvent", "AUDIT_DIR"]
