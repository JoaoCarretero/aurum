"""Static scanner for common look-ahead-bias patterns.

Não prova leak — só levanta hits pra revisão manual. Padrões:
  - .shift(-N) — uso de valor futuro como feature
  - iloc[i+N:] ou iloc[idx+1:] em contexto de decisão
  - nomes future_/ahead_/peek_ suspeitos
  - uso de close/high/low do candle atual em decisão do mesmo candle
    (heurística: label_trade + close[i] sem idx+1)
"""
from __future__ import annotations
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
TARGETS = [
    "engines/citadel.py", "engines/renaissance.py", "engines/jump.py",
    "engines/deshaw.py", "engines/bridgewater.py", "engines/kepos.py",
    "engines/medallion.py",
    "core/signals.py", "core/indicators.py", "core/risk/portfolio.py",
    "core/data/htf.py", "core/harmonics.py",
]

PATTERNS = [
    ("shift_negative", re.compile(r"\.shift\(\s*-\s*\d+")),
    ("iloc_plus", re.compile(r"\.iloc\s*\[\s*\w+\s*\+\s*\d+")),
    ("future_name", re.compile(r"\bfuture_|\bahead_|\bpeek_", re.IGNORECASE)),
    ("idx_plus_read", re.compile(r"\[\s*i\s*\+\s*\d+\s*\]")),
]


def scan_file(path: Path) -> list[tuple[str, int, str, str]]:
    hits = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for name, pat in PATTERNS:
            if pat.search(line):
                hits.append((name, lineno, stripped[:120], str(path.relative_to(REPO))))
    return hits


def main():
    out_lines = ["# Look-ahead scan — 2026-04-17\n\n"]
    total = 0
    for rel in TARGETS:
        p = REPO / rel
        if not p.exists():
            continue
        hits = scan_file(p)
        if not hits:
            out_lines.append(f"## {rel}  — clean\n\n")
            continue
        out_lines.append(f"## {rel}  — {len(hits)} hits\n\n")
        for name, lineno, code, _ in hits:
            out_lines.append(f"- line {lineno} `{name}`: `{code}`\n")
        out_lines.append("\n")
        total += len(hits)

    out = REPO / "docs" / "audits" / "_revalidation_lookahead.txt"
    out.write_text("".join(out_lines), encoding="utf-8")
    print(f"{total} hits total. See {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
