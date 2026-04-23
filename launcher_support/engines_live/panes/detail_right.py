"""Right column of ENGINE detail view — color log tail + controls.

Layout (top → bottom):

- Status strip: "● FOLLOWING" GREEN or "○ paused" DIM
- Log area: tk.Text (state=disabled) with per-level color tags
  (INFO/SIGNAL/ORDER/FILL/EXIT/WARN/ERROR). Each line is classified via
  ``data.log_tail.classify_level`` and inserted with the matching tag.
- Button row: [O] OPEN FULL · [F] FOLLOW · [T] TELEGRAM TEST (Label-as-button)

Tag palette:
    INFO    → DIM
    SIGNAL  → AMBER bold
    ORDER   → CYAN
    FILL    → GREEN
    EXIT    → WHITE bold
    WARN    → HAZARD
    ERROR   → RED bold

The frame stashes references (``_status_label``, ``_text``, ``_open_btn``,
``_follow_btn``, ``_telegram_btn``, ``_run_id``, ``_follow_mode``) so that
``update_detail_right`` can mutate state without rebuilding widgets.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from core.ui.ui_palette import AMBER, BG, CYAN, DIM, GREEN, HAZARD, RED, WHITE
from launcher_support.engines_live.data.log_tail import classify_level


_TAG_STYLE: dict[str, dict] = {
    "INFO":   {"foreground": DIM,    "font": ("Consolas", 9)},
    "SIGNAL": {"foreground": AMBER,  "font": ("Consolas", 9, "bold")},
    "ORDER":  {"foreground": CYAN,   "font": ("Consolas", 9)},
    "FILL":   {"foreground": GREEN,  "font": ("Consolas", 9)},
    "EXIT":   {"foreground": WHITE,  "font": ("Consolas", 9, "bold")},
    "WARN":   {"foreground": HAZARD, "font": ("Consolas", 9)},
    "ERROR":  {"foreground": RED,    "font": ("Consolas", 9, "bold")},
}


def _status_text(follow_mode: bool) -> str:
    return "● FOLLOWING" if follow_mode else "○ paused"


def _status_fg(follow_mode: bool) -> str:
    return GREEN if follow_mode else DIM


def _fill_log(
    text: tk.Text,
    run_id: str | None,
    log_lines: list[str],
    follow_mode: bool,
) -> None:
    """Replace the contents of ``text`` with ``log_lines`` classified by level.

    Honours ``state="disabled"``: flips to normal for the write, flips back.
    When ``run_id is None`` shows a single DIM placeholder line.
    When ``follow_mode`` is True, auto-scrolls to the end after insert.
    """
    text.configure(state="normal")
    text.delete("1.0", "end")
    if run_id is None:
        text.insert(
            "end",
            "(no instance selected — pick one to see live log)",
            ("INFO",),
        )
    else:
        for line in log_lines:
            level = classify_level(line)
            text.insert("end", line.rstrip("\n") + "\n", (level,))
    text.configure(state="disabled")
    if follow_mode:
        text.see("end")


def _make_btn(
    parent: tk.Widget,
    text: str,
    fg: str,
    cb: Callable[[], None] | None,
) -> tk.Label:
    lbl = tk.Label(
        parent,
        text=text,
        bg=BG,
        fg=fg,
        font=("Consolas", 9, "bold"),
        cursor="hand2",
        padx=4,
    )
    lbl.pack(side="left", padx=(0, 8))
    if cb is not None:
        lbl.bind("<Button-1>", lambda e: cb())
    return lbl


def build_detail_right(
    parent: tk.Widget,
    run_id: str | None,
    log_lines: list[str],
    follow_mode: bool,
    on_toggle_follow: Callable[[], None] | None = None,
    on_open_full: Callable[[], None] | None = None,
    on_telegram_test: Callable[[], None] | None = None,
) -> tk.Frame:
    """Build the right column of the detail view.

    Returns a ``tk.Frame`` with stashed child references for later updates.
    """
    frame = tk.Frame(parent, bg=BG)

    # Status strip ------------------------------------------------------
    status = tk.Label(
        frame,
        text=_status_text(follow_mode),
        bg=BG,
        fg=_status_fg(follow_mode),
        font=("Consolas", 9, "bold"),
        anchor="w",
    )
    status.pack(fill="x", padx=6, pady=(4, 2))

    # Log area ----------------------------------------------------------
    text = tk.Text(
        frame,
        bg=BG,
        fg=WHITE,
        font=("Consolas", 9),
        wrap="none",
        height=20,
        padx=4,
        pady=4,
        highlightthickness=0,
        bd=0,
    )
    text.pack(fill="both", expand=True, padx=4)

    for tag, cfg in _TAG_STYLE.items():
        text.tag_configure(tag, **cfg)

    _fill_log(text, run_id, log_lines, follow_mode)

    # Button row --------------------------------------------------------
    btns = tk.Frame(frame, bg=BG)
    btns.pack(fill="x", padx=4, pady=4)

    open_btn = _make_btn(btns, "[O] OPEN FULL", DIM, on_open_full)
    follow_btn = _make_btn(
        btns,
        "[F] FOLLOW",
        AMBER if follow_mode else DIM,
        on_toggle_follow,
    )
    tg_btn = _make_btn(btns, "[T] TELEGRAM TEST", DIM, on_telegram_test)

    # Stash references for update ---------------------------------------
    frame._status_label = status  # type: ignore[attr-defined]
    frame._text = text  # type: ignore[attr-defined]
    frame._open_btn = open_btn  # type: ignore[attr-defined]
    frame._follow_btn = follow_btn  # type: ignore[attr-defined]
    frame._telegram_btn = tg_btn  # type: ignore[attr-defined]
    frame._run_id = run_id  # type: ignore[attr-defined]
    frame._follow_mode = follow_mode  # type: ignore[attr-defined]
    return frame


def update_detail_right(
    frame: tk.Frame,
    run_id: str | None,
    log_lines: list[str],
    follow_mode: bool,
) -> None:
    """Re-render the right column in place.

    Mutates status label, follow button colour, and log text body. Does not
    rebuild widgets — relies on references stashed by ``build_detail_right``.
    """
    frame._run_id = run_id  # type: ignore[attr-defined]
    frame._follow_mode = follow_mode  # type: ignore[attr-defined]
    frame._status_label.configure(  # type: ignore[attr-defined]
        text=_status_text(follow_mode),
        fg=_status_fg(follow_mode),
    )
    frame._follow_btn.configure(  # type: ignore[attr-defined]
        fg=AMBER if follow_mode else DIM,
    )
    _fill_log(
        frame._text,  # type: ignore[attr-defined]
        run_id,
        log_lines,
        follow_mode,
    )
