"""File tail reader + log level classifier.

Pure module: no tkinter. File I/O only.

- read_tail(path, n=18, max_bytes=65536) -> list[str]
    Returns last N non-empty lines. Reads at most max_bytes from EOF so
    a huge log file doesn't load fully into memory. None path returns [].

- classify_level(line) -> str in {INFO, SIGNAL, ORDER, FILL, EXIT, WARN, ERROR}
    Heuristic match against engine logging conventions. Priority order
    (first match wins): ERROR > WARN > EXIT > FILL > ORDER > SIGNAL > INFO.
    SIGNAL also matches "novel=N" where N>=1 (non-zero novels).
"""
from __future__ import annotations

import re
from pathlib import Path


_LEVEL_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ERROR", re.compile(r"\b(ERROR|FATAL|CRITICAL|Traceback)\b")),
    ("WARN",  re.compile(r"\b(WARNING|WARN|STALE|SKIP)\b", re.IGNORECASE)),
    ("EXIT",  re.compile(r"\bEXIT\b")),
    ("FILL",  re.compile(r"\bFILL\b")),
    ("ORDER", re.compile(r"\bORDER\b")),
    ("SIGNAL", re.compile(r"\bSIGNAL\b|\bnovel=[1-9]\d*")),
]


def classify_level(line: str) -> str:
    """Return the log level for a given line. Defaults to INFO."""
    for name, pat in _LEVEL_PATTERNS:
        if pat.search(line):
            return name
    return "INFO"


def read_tail(path: Path | None, n: int = 18,
              max_bytes: int = 65536) -> list[str]:
    """Return the last `n` non-empty lines of a file.

    Silent on any error (missing file, permissions, decode failure) — returns [].
    Reads at most `max_bytes` from EOF so huge log files don't blow memory.
    If we start mid-line (read_from > 0), the partial first line is dropped.
    """
    if path is None:
        return []
    try:
        p = Path(path)
        if not p.exists() or not p.is_file():
            return []
        size = p.stat().st_size
        if size == 0:
            return []
        read_from = max(0, size - max_bytes)
        with p.open("rb") as fh:
            fh.seek(read_from)
            chunk = fh.read()
        text = chunk.decode("utf-8", errors="replace")
        lines = text.splitlines()
        # If we started mid-line (read_from > 0), drop the first partial line
        if read_from > 0 and lines:
            lines = lines[1:]
        # Drop trailing empty lines
        while lines and not lines[-1].strip():
            lines.pop()
        return lines[-n:]
    except Exception:
        return []
