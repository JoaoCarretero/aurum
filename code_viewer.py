"""Read-only syntax-highlighted source viewer for the AURUM launcher.

Standalone module — zero dependency on launcher.py. Instantiate from any Tk
context that has a parent widget:

    from code_viewer import CodeViewer
    CodeViewer(parent_root, ["engines/citadel.py"], ("engines/citadel.py", "scan_symbol"))

Opens a modal Toplevel with ttk.Notebook tabs, one tab per source file. The
first tab is auto-scrolled near ``def <main_function>``. ESC closes. Highlight
is regex-based (5 categories: keyword / string / comment / number / def-name),
imperfect by design — it's a viewer, not a compiler.

Run the file directly (``python code_viewer.py``) to see a demo window.
"""

from __future__ import annotations

import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

# ─── Bloomberg palette (matches launcher.py) ──────────────────────────────
BG      = "#0a0a0a"
BG3     = "#181818"
AMBER   = "#ff8c00"
AMBER_D = "#7a4400"
WHITE   = "#c8c8c8"
DIM     = "#4a4a4a"
FONT    = "Consolas"

# ─── Python syntax keywords ───────────────────────────────────────────────
_KEYWORDS = frozenset({
    "def", "class", "for", "if", "elif", "else", "return",
    "import", "from", "while", "in", "not", "and", "or",
    "True", "False", "None", "try", "except", "finally",
    "with", "as", "lambda", "yield", "raise", "pass",
    "break", "continue", "global", "nonlocal", "is", "async", "await",
})

# ─── Highlight colors (VSCode-ish dark theme) ─────────────────────────────
_COLOR_KEYWORD  = "#569cd6"  # blue
_COLOR_STRING   = "#6a9955"  # green
_COLOR_COMMENT  = DIM        # grey
_COLOR_NUMBER   = "#d7ba7d"  # orange-tan
_COLOR_DEFNAME  = "#dcdcaa"  # yellow


class CodeViewer(tk.Toplevel):
    """Modal read-only source viewer.

    Parameters
    ----------
    parent : tk.Misc
        Any Tk widget — usually the app root window.
    source_files : list[str]
        Paths to the files to display, ordered by relevance. The first file
        becomes the default-selected tab. Paths can be absolute or relative
        to the current working directory (the launcher sets cwd = repo root).
    main_function : tuple[str, str]
        ``(file_path, function_name)`` — the viewer auto-scrolls the tab for
        ``file_path`` to the first occurrence of ``def function_name``.
        ``file_path`` must equal ``source_files[0]`` for the scroll to take
        effect on the default-focused tab.
    """

    def __init__(
        self,
        parent: tk.Misc,
        source_files: list,
        main_function: tuple,
    ) -> None:
        super().__init__(parent)
        self.title(f"source — {main_function[1]}")
        self.geometry("1100x750")
        self.configure(bg=BG)
        self.transient(parent)
        self.grab_set()
        self.bind("<Escape>", lambda e: self.destroy())
        self._build_ui(source_files, main_function)

    # ─── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self, files: list, main_fn: tuple) -> None:
        self._apply_notebook_style()

        nb = ttk.Notebook(self, style="Code.TNotebook")
        nb.pack(fill="both", expand=True, padx=4, pady=4)

        default_frame: ttk.Frame | None = None
        default_text: tk.Text | None = None
        default_content: str = ""

        for path in files:
            frame = ttk.Frame(nb, style="Code.TFrame")
            txt = tk.Text(
                frame,
                wrap="none",
                font=(FONT, 10),
                bg=BG, fg=WHITE,
                insertbackground=WHITE,
                selectbackground=AMBER_D,
                selectforeground=BG,
                padx=8, pady=8,
                borderwidth=0, highlightthickness=0,
            )
            sb_y = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
            sb_x = ttk.Scrollbar(frame, orient="horizontal", command=txt.xview)
            txt.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)

            content = self._read_file(path)
            txt.insert("1.0", content)
            self._highlight(txt, content)
            txt.config(state="disabled")

            sb_y.pack(side="right", fill="y")
            sb_x.pack(side="bottom", fill="x")
            txt.pack(side="left", fill="both", expand=True)

            nb.add(frame, text=Path(path).name)

            if path == main_fn[0]:
                default_frame = frame
                default_text = txt
                default_content = content

        if default_frame is not None:
            nb.select(default_frame)
            if default_text is not None:
                self._scroll_to_function(default_text, default_content, main_fn[1])

    def _apply_notebook_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("default")
        except tk.TclError:
            pass
        style.configure("Code.TNotebook", background=BG, borderwidth=0)
        style.configure(
            "Code.TNotebook.Tab",
            background=BG3, foreground=WHITE,
            padding=(12, 4), borderwidth=0, font=(FONT, 9),
        )
        style.map(
            "Code.TNotebook.Tab",
            background=[("selected", BG), ("active", BG3)],
            foreground=[("selected", AMBER), ("active", AMBER)],
        )
        style.configure("Code.TFrame", background=BG)

    # ─── File reading ──────────────────────────────────────────────────────

    def _read_file(self, path) -> str:
        p = Path(path)
        if not p.is_absolute():
            p = Path.cwd() / p
        try:
            return p.read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"# file not found: {path}\n"
        except UnicodeDecodeError:
            return f"# binary or non-utf-8 file: {path}\n"

    # ─── Syntax highlight ──────────────────────────────────────────────────

    def _highlight(self, text_widget: tk.Text, content: str) -> None:
        """Five-pass regex highlight. Imperfect by design.

        Order matters: strings first (so a ``#`` inside a string doesn't
        become a comment), then comments, then the rest.
        """
        text_widget.tag_configure("kw",      foreground=_COLOR_KEYWORD)
        text_widget.tag_configure("string",  foreground=_COLOR_STRING)
        text_widget.tag_configure("comment", foreground=_COLOR_COMMENT)
        text_widget.tag_configure("number",  foreground=_COLOR_NUMBER)
        text_widget.tag_configure("defname", foreground=_COLOR_DEFNAME)

        for m in re.finditer(r'"[^"\n]*"|\'[^\'\n]*\'', content):
            self._tag_span(text_widget, m.start(), m.end(), "string")

        for m in re.finditer(r"#.*$", content, flags=re.MULTILINE):
            self._tag_span(text_widget, m.start(), m.end(), "comment")

        kw_pattern = r"\b(" + "|".join(_KEYWORDS) + r")\b"
        for m in re.finditer(kw_pattern, content):
            self._tag_span(text_widget, m.start(), m.end(), "kw")

        for m in re.finditer(r"\b\d+\.?\d*\b", content):
            self._tag_span(text_widget, m.start(), m.end(), "number")

        for m in re.finditer(r"\b(?:def|class)\s+(\w+)", content):
            self._tag_span(text_widget, m.start(1), m.end(1), "defname")

    def _tag_span(
        self,
        text_widget: tk.Text,
        start_char: int,
        end_char: int,
        tag: str,
    ) -> None:
        start_index = f"1.0 + {start_char} chars"
        end_index = f"1.0 + {end_char} chars"
        text_widget.tag_add(tag, start_index, end_index)

    def _scroll_to_function(
        self,
        text_widget: tk.Text,
        content: str,
        fn_name: str,
    ) -> None:
        needle = f"def {fn_name}"
        idx = content.find(needle)
        if idx < 0:
            return
        line = content.count("\n", 0, idx) + 1
        text_widget.see(f"{max(1, line - 3)}.0")


# ─── Demo entry point ─────────────────────────────────────────────────────


def _demo() -> None:
    """Open a tiny launcher window with a button that opens CodeViewer on
    this file itself. Run with: ``python code_viewer.py``."""

    root = tk.Tk()
    root.title("CodeViewer demo")
    root.geometry("440x180")
    root.configure(bg=BG)

    tk.Label(
        root,
        text="CodeViewer standalone demo",
        font=(FONT, 11, "bold"),
        fg=AMBER, bg=BG,
    ).pack(pady=(24, 6))

    tk.Label(
        root,
        text="Click to open this file in the viewer",
        font=(FONT, 9),
        fg=WHITE, bg=BG,
    ).pack(pady=(0, 16))

    btn = tk.Label(
        root,
        text="  OPEN VIEWER  ",
        font=(FONT, 10, "bold"),
        fg=BG, bg=AMBER,
        padx=10, pady=6,
        cursor="hand2",
    )
    btn.pack()

    def _open_viewer(_event=None) -> None:
        here = Path(__file__).resolve()
        CodeViewer(
            root,
            source_files=[str(here)],
            main_function=(str(here), "_demo"),
        )

    btn.bind("<Button-1>", _open_viewer)
    root.bind("<Return>", _open_viewer)
    root.bind("<Escape>", lambda e: root.destroy())

    root.mainloop()


if __name__ == "__main__":
    sys.exit(_demo() or 0)
