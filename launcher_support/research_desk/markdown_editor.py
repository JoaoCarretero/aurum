"""Markdown editor Toplevel — edita AGENTS.md / docs/agents/*.md inline.

Widget writable com syntax highlight live (headers, bold, inline code).
Save com Ctrl+S, dirty indicator no titulo, confirmacao se fechar sujo.

Design:
  - Pure functions (persona_path, is_dirty_label) testaveis sem Tk.
  - apply_highlight e pura sobre um Text widget — separado pra teste
    indireto via behavior.
  - MarkdownEditor e a Toplevel wrapper.

Nao usa pygments — stdlib-only. Highlight basico (headers, bold,
inline code, links) sufficient para persona files.
"""
from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Callable

from core.ui.ui_palette import (
    AMBER,
    AMBER_D,
    BG,
    BG2,
    BG3,
    CYAN,
    DIM,
    FONT,
    HAZARD,
    PANEL,
    WHITE,
)


_RE_HEADER = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
_RE_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
_RE_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_RE_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\n]+)\)")


# ── Pure functions ────────────────────────────────────────────────


def persona_path(agent_key: str, root: Path | str) -> Path:
    """Caminho preferido do persona file do agente.

    Tenta docs/agents/{key_lower}.md primeiro (padrao recomendado);
    fallback AGENTS.md root. Caller e quem decide criar se nao existir.
    """
    root_p = Path(root)
    candidate = root_p / "docs" / "agents" / f"{agent_key.lower()}.md"
    if candidate.exists():
        return candidate
    # Fallback: AGENTS.md root (shared)
    shared = root_p / "AGENTS.md"
    if shared.exists():
        return shared
    # Nada existe ainda — retorna o candidato preferencial pra caller criar
    return candidate


def is_dirty_label(*, path_name: str, dirty: bool) -> str:
    """Titulo da janela baseado em dirty state."""
    marker = "● " if dirty else ""
    return f"{marker}{path_name}"


# ── Widget ────────────────────────────────────────────────────────


def open_markdown_editor(
    parent: tk.Misc,
    *,
    path: Path,
    title_hint: str = "",
    on_saved: Callable[[Path], None] | None = None,
) -> "MarkdownEditor":
    """Factory — abre e retorna a instancia."""
    return MarkdownEditor(
        parent, path=path, title_hint=title_hint, on_saved=on_saved,
    )


class MarkdownEditor:
    """Editor Toplevel pra arquivos markdown.

    Cria o arquivo se nao existir (mkdir parents). Save persiste disco.
    Fecha com confirmacao se dirty.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        path: Path,
        title_hint: str = "",
        on_saved: Callable[[Path], None] | None = None,
    ):
        self.path = Path(path)
        self._on_saved = on_saved
        self._dirty = False
        self._highlight_after: str | None = None

        self.top = tk.Toplevel(parent)
        self.top.configure(bg=BG)
        self.top.geometry("840x640")
        self.top.transient(parent)

        display_name = title_hint or str(self.path.name)
        self._display_name = display_name
        self.top.title(is_dirty_label(path_name=display_name, dirty=False))

        self._build()
        self._load()
        self._apply_highlight()

        self.top.bind("<Control-s>", self._handle_save)
        self.top.bind("<Control-S>", self._handle_save)
        self.top.bind("<Escape>", lambda _e: self._handle_close())
        self.top.protocol("WM_DELETE_WINDOW", self._handle_close)
        self.top.focus_set()
        self.text.focus_set()

    def _build(self) -> None:
        # Header com path + dirty hint
        header = tk.Frame(self.top, bg=PANEL)
        header.pack(fill="x")
        tk.Label(
            header, text=f"  {self.path}  ",
            font=(FONT, 8), fg=AMBER_D, bg=PANEL, anchor="w",
        ).pack(side="left", pady=6)
        self._status_lbl = tk.Label(
            header, text="Ctrl+S salva  ·  Esc fecha",
            font=(FONT, 7), fg=DIM, bg=PANEL, anchor="e",
        )
        self._status_lbl.pack(side="right", padx=8, pady=6)

        tk.Frame(self.top, bg=BG3, height=1).pack(fill="x")

        body = tk.Frame(self.top, bg=BG)
        body.pack(fill="both", expand=True)

        self.text = tk.Text(
            body, bg=BG, fg=WHITE, insertbackground=AMBER,
            font=(FONT, 9), wrap="word", undo=True,
            padx=12, pady=10, borderwidth=0, highlightthickness=0,
        )
        scrollbar = tk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)

        # Tags de highlight
        for level, size_add in ((1, 6), (2, 4), (3, 2), (4, 1), (5, 0), (6, 0)):
            self.text.tag_configure(
                f"h{level}",
                font=(FONT, 9 + size_add, "bold"),
                foreground=AMBER if level <= 2 else AMBER_D,
            )
        self.text.tag_configure(
            "bold", font=(FONT, 9, "bold"), foreground=WHITE,
        )
        self.text.tag_configure(
            "inline_code", font=(FONT, 9),
            background=BG2, foreground=HAZARD,
        )
        self.text.tag_configure(
            "link", font=(FONT, 9, "underline"), foreground=CYAN,
        )

        # Bind modified event
        self.text.bind("<<Modified>>", self._on_modified)

    def _load(self) -> None:
        """Le conteudo do disco. Se nao existe, comeca vazio."""
        content = ""
        if self.path.exists():
            try:
                content = self.path.read_text(encoding="utf-8")
            except OSError:
                content = "# (erro lendo arquivo)\n"
        self.text.insert("1.0", content)
        # Reset dirty flag apos load inicial
        self.text.edit_modified(False)
        self._set_dirty(False)

    def _on_modified(self, _event: tk.Event) -> None:
        # <<Modified>> fires both on change AND when edit_modified(False) —
        # checar real state
        if not self.text.edit_modified():
            return
        self._set_dirty(True)
        # Debounce highlight — 250ms sem digitar
        if self._highlight_after is not None:
            try:
                self.top.after_cancel(self._highlight_after)
            except Exception:
                pass
        self._highlight_after = self.top.after(250, self._apply_highlight)
        # Reset o flag interno do widget pra proximo evento disparar
        self.text.edit_modified(False)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        try:
            self.top.title(is_dirty_label(
                path_name=self._display_name, dirty=dirty,
            ))
        except Exception:
            pass

    def _apply_highlight(self) -> None:
        """Re-aplica tags em todo o conteudo. Idempotente."""
        self._highlight_after = None
        for tag in ("h1", "h2", "h3", "h4", "h5", "h6",
                    "bold", "inline_code", "link"):
            self.text.tag_remove(tag, "1.0", "end")

        src = self.text.get("1.0", "end-1c")
        # Headers — matching em modo MULTILINE, precisamos converter
        # offsets de char pro index tkinter (line.col)
        for m in _RE_HEADER.finditer(src):
            level = len(m.group(1))
            start = self._offset_to_index(src, m.start())
            end = self._offset_to_index(src, m.end())
            self.text.tag_add(f"h{min(level, 6)}", start, end)

        for m in _RE_BOLD.finditer(src):
            start = self._offset_to_index(src, m.start())
            end = self._offset_to_index(src, m.end())
            self.text.tag_add("bold", start, end)

        for m in _RE_INLINE_CODE.finditer(src):
            start = self._offset_to_index(src, m.start())
            end = self._offset_to_index(src, m.end())
            self.text.tag_add("inline_code", start, end)

        for m in _RE_LINK.finditer(src):
            start = self._offset_to_index(src, m.start())
            end = self._offset_to_index(src, m.end())
            self.text.tag_add("link", start, end)

    @staticmethod
    def _offset_to_index(src: str, offset: int) -> str:
        """Converte offset de char em tk 'line.col' index."""
        line = src.count("\n", 0, offset) + 1
        last_nl = src.rfind("\n", 0, offset)
        col = offset - (last_nl + 1) if last_nl >= 0 else offset
        return f"{line}.{col}"

    def _handle_save(self, _event: tk.Event | None = None) -> str:
        """Grava no disco. Retorna 'break' pra cancelar default binding."""
        content = self.text.get("1.0", "end-1c")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(content, encoding="utf-8")
        except OSError as exc:
            messagebox.showerror(
                "aurum research",
                f"erro ao salvar {self.path.name}:\n{exc}",
                parent=self.top,
            )
            return "break"
        self._set_dirty(False)
        self._flash_saved()
        if self._on_saved is not None:
            try:
                self._on_saved(self.path)
            except Exception:
                pass
        return "break"

    def _flash_saved(self) -> None:
        if self._status_lbl is None:
            return
        try:
            self._status_lbl.configure(text="salvo ·  ", fg=AMBER)
            self.top.after(1800, lambda: self._status_lbl.configure(
                text="Ctrl+S salva  ·  Esc fecha", fg=DIM,
            ))
        except Exception:
            pass

    def _handle_close(self) -> None:
        if self._dirty:
            resp = messagebox.askyesnocancel(
                "aurum research",
                f"{self._display_name} tem alteracoes nao salvas.\n"
                "salvar antes de fechar?",
                parent=self.top,
            )
            if resp is None:
                return  # cancel
            if resp is True:
                self._handle_save()
                if self._dirty:
                    return  # save falhou — nao fecha
        try:
            self.top.destroy()
        except Exception:
            pass
