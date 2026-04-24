"""Minimal markdown viewer pra Tk Text — zero deps externas.

Cobre as construcoes mais comuns em docs internas:
  # / ## / ###   — headers (3 niveis distintos)
  **bold**       — negrito
  *italic*       — italico  (heuristica simples: nao ambiguo)
  `inline code`  — mono inline
  ```lang
  block code
  ```           — code block com fundo
  - item / * item / 1. item — listas (indentacao por nivel via padding)
  [link](url)    — renderiza como link (so visual, nao abre)
  > quote        — block quote

Nao cobre tabelas, imagens embedded, HTML inline, nested lists profundas.
Se precisar Sprint 2+ adicionar markdown + pygments deps.

API:
    render_markdown(text_widget, markdown_src)
        Popula um tk.Text com tags aplicadas. Espera widget ja configurado
        com bg/fg. Nao limpa o widget antes — caller faz delete('1.0', end)
        se quiser sobrescrever.
"""
from __future__ import annotations

import re
import tkinter as tk

from core.ui.ui_palette import (
    AMBER,
    AMBER_D,
    BG,
    BG2,
    BG3,
    CYAN,
    DIM,
    FONT,
    GREEN,
    HAZARD,
    WHITE,
)


# Regex compiladas uma vez por import
_RE_FENCE = re.compile(r"^```(\w+)?\s*$")
_RE_HEADER = re.compile(r"^(#{1,6})\s+(.*)$")
_RE_LIST_ITEM = re.compile(r"^(\s*)([-*]|\d+\.)\s+(.*)$")
_RE_QUOTE = re.compile(r"^>\s?(.*)$")
_RE_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_RE_ITALIC = re.compile(r"(?<!\*)\*([^*\s][^*]*?)\*(?!\*)")
_RE_INLINE_CODE = re.compile(r"`([^`]+)`")
_RE_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_RE_HR = re.compile(r"^---+\s*$")


def configure_text_widget(widget: tk.Text, *, font_size: int = 9) -> None:
    """Registra tags no widget. Chame 1x antes do primeiro render."""
    mono = (FONT, font_size)
    widget.configure(
        bg=BG, fg=WHITE, insertbackground=WHITE,
        font=mono, padx=12, pady=10,
        wrap="word", borderwidth=0, highlightthickness=0,
    )
    # Headers
    widget.tag_configure("h1", font=(FONT, font_size + 6, "bold"), foreground=AMBER,
                          spacing1=12, spacing3=6)
    widget.tag_configure("h2", font=(FONT, font_size + 4, "bold"), foreground=AMBER,
                          spacing1=10, spacing3=4)
    widget.tag_configure("h3", font=(FONT, font_size + 2, "bold"), foreground=AMBER_D,
                          spacing1=8, spacing3=3)
    widget.tag_configure("h4", font=(FONT, font_size + 1, "bold"), foreground=AMBER_D,
                          spacing1=6, spacing3=2)
    widget.tag_configure("h5", font=(FONT, font_size, "bold"), foreground=AMBER_D)
    widget.tag_configure("h6", font=(FONT, font_size, "bold"), foreground=DIM)

    widget.tag_configure("bold", font=(FONT, font_size, "bold"), foreground=WHITE)
    widget.tag_configure("italic", font=(FONT, font_size, "italic"), foreground=WHITE)
    widget.tag_configure("inline_code", font=(FONT, font_size), background=BG2,
                          foreground=HAZARD)
    widget.tag_configure("link", font=(FONT, font_size, "underline"), foreground=CYAN)
    widget.tag_configure("list_bullet", foreground=AMBER)
    widget.tag_configure("list_item", lmargin1=20, lmargin2=36)
    widget.tag_configure("quote", foreground=DIM, background=BG2,
                          lmargin1=16, lmargin2=16, spacing1=2, spacing3=2)
    widget.tag_configure("code_block", font=(FONT, font_size), background=BG2,
                          foreground=GREEN, lmargin1=16, lmargin2=16,
                          spacing1=4, spacing3=4)
    widget.tag_configure("code_lang", font=(FONT, font_size - 1, "italic"),
                          foreground=DIM, background=BG3, lmargin1=16, lmargin2=16)
    widget.tag_configure("hr", foreground=DIM)


def render_markdown(widget: tk.Text, src: str) -> None:
    """Renderiza src (markdown) dentro do widget."""
    lines = src.splitlines()
    in_code = False
    code_lang = ""
    i = 0
    while i < len(lines):
        line = lines[i]

        # Code fence entra/sai
        fence = _RE_FENCE.match(line)
        if fence is not None:
            if in_code:
                in_code = False
                code_lang = ""
            else:
                in_code = True
                code_lang = (fence.group(1) or "").lower()
                if code_lang:
                    widget.insert("end", f"  {code_lang}\n", ("code_lang",))
            i += 1
            continue

        if in_code:
            widget.insert("end", line + "\n", ("code_block",))
            i += 1
            continue

        # Horizontal rule
        if _RE_HR.match(line):
            widget.insert("end", "─" * 40 + "\n", ("hr",))
            i += 1
            continue

        # Header
        h = _RE_HEADER.match(line)
        if h is not None:
            level = len(h.group(1))
            text = h.group(2).strip()
            tag = f"h{min(level, 6)}"
            widget.insert("end", text + "\n", (tag,))
            i += 1
            continue

        # List item (single level)
        li = _RE_LIST_ITEM.match(line)
        if li is not None:
            marker = li.group(2)
            body = li.group(3)
            widget.insert("end", f"  {marker} ", ("list_bullet",))
            _insert_inline(widget, body, extra_tags=("list_item",))
            widget.insert("end", "\n")
            i += 1
            continue

        # Quote
        q = _RE_QUOTE.match(line)
        if q is not None:
            widget.insert("end", q.group(1) + "\n", ("quote",))
            i += 1
            continue

        # Blank line
        if not line.strip():
            widget.insert("end", "\n")
            i += 1
            continue

        # Paragraph
        _insert_inline(widget, line)
        widget.insert("end", "\n")
        i += 1

    # Read-only
    widget.configure(state="disabled")


def _insert_inline(widget: tk.Text, src: str, extra_tags: tuple[str, ...] = ()) -> None:
    """Processa inline-formatting dentro de uma linha."""
    # Achamos todos os matches (tipo, start, end, text). Ordenados por start.
    spans: list[tuple[int, int, str, tuple[str, ...]]] = []
    for m in _RE_BOLD.finditer(src):
        spans.append((m.start(), m.end(), m.group(1), ("bold",) + extra_tags))
    for m in _RE_ITALIC.finditer(src):
        spans.append((m.start(), m.end(), m.group(1), ("italic",) + extra_tags))
    for m in _RE_INLINE_CODE.finditer(src):
        spans.append((m.start(), m.end(), m.group(1), ("inline_code",) + extra_tags))
    for m in _RE_LINK.finditer(src):
        spans.append((m.start(), m.end(), m.group(1), ("link",) + extra_tags))

    # Remove sobreposicoes (mantem mais cedo + mais longo)
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    filtered: list[tuple[int, int, str, tuple[str, ...]]] = []
    last_end = 0
    for sp in spans:
        if sp[0] >= last_end:
            filtered.append(sp)
            last_end = sp[1]

    # Emite: texto antes do 1o span (plain), cada span (com tag), texto apos
    cursor = 0
    for start, end, txt, tags in filtered:
        if start > cursor:
            widget.insert("end", src[cursor:start], extra_tags or ())
        widget.insert("end", txt, tags)
        cursor = end
    if cursor < len(src):
        widget.insert("end", src[cursor:], extra_tags or ())
