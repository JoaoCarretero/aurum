"""Modal New Ticket pra criacao de issues via Paperclip API.

Fluxo:
  1. user clica NOVO TICKET (header do Research Desk) ou ATRIBUIR num card
  2. abre Toplevel modal
  3. assignee (4 radio por agent), title (min 5 chars), priority
     (low/medium/high), description textarea
  4. submit valida + POST /api/companies/:id/issues
  5. feedback inline (sucesso/erro); sucesso fecha + dispara refresh no
     painel pipeline do caller

API separada do Screen pra permitir testing sem Tk render real
(validate_ticket e uma funcao pura).
"""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Callable

from core.ui.ui_palette import (
    AMBER,
    AMBER_B,
    AMBER_D,
    BG,
    BG2,
    BG3,
    BORDER,
    DIM,
    DIM2,
    FONT,
    GREEN,
    HAZARD,
    PANEL,
    RED,
    WHITE,
)
from launcher_support.research_desk.agents import AGENTS, AgentIdentity
from launcher_support.research_desk.palette import AGENT_COLORS


_PRIORITIES = ("low", "medium", "high")
_PRIORITY_LABELS = {"low": "LOW", "medium": "MED", "high": "HIGH"}
_PRIORITY_COLORS = {"low": DIM2, "medium": AMBER, "high": RED}

_TITLE_MIN = 5
_TITLE_MAX = 120


@dataclass(frozen=True)
class TicketDraft:
    title: str
    description: str
    assignee: AgentIdentity
    priority: str  # "low" | "medium" | "high"


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: tuple[str, ...]


def validate_draft(
    *,
    title: str,
    description: str,
    assignee_key: str,
    priority: str,
) -> tuple[ValidationResult, TicketDraft | None]:
    """Valida entrada. Retorna (resultado, draft) — draft e None se invalido."""
    errors: list[str] = []

    title_clean = (title or "").strip()
    if len(title_clean) < _TITLE_MIN:
        errors.append(f"title precisa de no minimo {_TITLE_MIN} chars")
    if len(title_clean) > _TITLE_MAX:
        errors.append(f"title maximo {_TITLE_MAX} chars")

    priority_clean = (priority or "").strip().lower()
    if priority_clean not in _PRIORITIES:
        errors.append(f"priority invalida: {priority_clean!r}")

    assignee_key_clean = (assignee_key or "").strip().upper()
    from launcher_support.research_desk.agents import BY_KEY
    assignee = BY_KEY.get(assignee_key_clean)
    if assignee is None:
        errors.append(f"assignee desconhecido: {assignee_key_clean!r}")

    if errors:
        return ValidationResult(ok=False, errors=tuple(errors)), None

    assert assignee is not None  # exposed por mypy
    draft = TicketDraft(
        title=title_clean,
        description=(description or "").strip(),
        assignee=assignee,
        priority=priority_clean,
    )
    return ValidationResult(ok=True, errors=()), draft


def draft_to_api_payload(draft: TicketDraft) -> dict:
    """Converte TicketDraft em payload aceito por POST /issues."""
    return {
        "title": draft.title,
        "description": draft.description,
        "assigned_agent_id": draft.assignee.uuid,
        "priority": draft.priority,
        "status": "todo",
    }


# ── UI ───────────────────────────────────────────────────────────


class NewTicketModal:
    """Toplevel modal pra criar issue. Caller injeta submit_callback(draft)."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        submit_callback: Callable[[TicketDraft], tuple[bool, str]],
        default_assignee: AgentIdentity | None = None,
    ):
        self._submit_callback = submit_callback

        self.top = tk.Toplevel(parent)
        self.top.title("NOVO TICKET")
        self.top.configure(bg=BG)
        self.top.geometry("520x560")
        self.top.transient(parent)
        self.top.grab_set()

        # State
        self._title_var = tk.StringVar(value="")
        self._priority_var = tk.StringVar(value="medium")
        self._assignee_var = tk.StringVar(
            value=(default_assignee or AGENTS[0]).key,
        )
        self._desc_widget: tk.Text | None = None
        self._error_label: tk.Label | None = None
        self._submit_btn: tk.Label | None = None

        self._build()
        self.top.bind("<Escape>", lambda _e: self.close())

    # ── Build ─────────────────────────────────────────────────────

    def _build(self) -> None:
        wrap = tk.Frame(self.top, bg=BG, padx=20, pady=16)
        wrap.pack(fill="both", expand=True)

        tk.Label(
            wrap, text="NOVO TICKET",
            font=(FONT, 12, "bold"), fg=AMBER, bg=BG, anchor="w",
        ).pack(anchor="w")
        tk.Frame(wrap, bg=DIM, height=1).pack(fill="x", pady=(6, 12))

        # ── Assignee ─────────────────────────────
        tk.Label(
            wrap, text="ASSIGNEE",
            font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, anchor="w",
        ).pack(anchor="w")
        assignee_row = tk.Frame(wrap, bg=BG)
        assignee_row.pack(anchor="w", pady=(4, 10))
        for agent in AGENTS:
            palette = AGENT_COLORS[agent.key]
            rb = tk.Radiobutton(
                assignee_row,
                text=agent.key,
                variable=self._assignee_var, value=agent.key,
                bg=BG, fg=palette.primary,
                activebackground=BG, activeforeground=palette.primary,
                selectcolor=BG3, highlightthickness=0,
                font=(FONT, 9, "bold"),
                cursor="hand2", indicatoron=True,
            )
            rb.pack(side="left", padx=(0, 10))

        # ── Title ────────────────────────────────
        tk.Label(
            wrap, text="TITULO",
            font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, anchor="w",
        ).pack(anchor="w")
        title_entry = tk.Entry(
            wrap, textvariable=self._title_var,
            bg=BG2, fg=WHITE, insertbackground=WHITE,
            font=(FONT, 10), relief="flat",
            highlightbackground=BORDER, highlightthickness=1,
        )
        title_entry.pack(fill="x", pady=(4, 2))
        tk.Label(
            wrap, text=f"minimo {_TITLE_MIN} chars",
            font=(FONT, 7), fg=DIM, bg=BG, anchor="w",
        ).pack(anchor="w", pady=(0, 10))

        # ── Priority ─────────────────────────────
        tk.Label(
            wrap, text="PRIORITY",
            font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, anchor="w",
        ).pack(anchor="w")
        prio_row = tk.Frame(wrap, bg=BG)
        prio_row.pack(anchor="w", pady=(4, 10))
        for p in _PRIORITIES:
            color = _PRIORITY_COLORS[p]
            rb = tk.Radiobutton(
                prio_row,
                text=_PRIORITY_LABELS[p],
                variable=self._priority_var, value=p,
                bg=BG, fg=color,
                activebackground=BG, activeforeground=color,
                selectcolor=BG3, highlightthickness=0,
                font=(FONT, 9, "bold"),
                cursor="hand2", indicatoron=True,
            )
            rb.pack(side="left", padx=(0, 10))

        # ── Description ──────────────────────────
        tk.Label(
            wrap, text="DESCRICAO",
            font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, anchor="w",
        ).pack(anchor="w")
        desc = tk.Text(
            wrap, height=8,
            bg=BG2, fg=WHITE, insertbackground=WHITE,
            font=(FONT, 9), relief="flat",
            highlightbackground=BORDER, highlightthickness=1,
            wrap="word",
        )
        desc.pack(fill="both", expand=True, pady=(4, 10))
        self._desc_widget = desc

        # ── Error banner (escondido inicialmente) ─
        self._error_label = tk.Label(
            wrap, text="",
            font=(FONT, 8), fg=RED, bg=BG, anchor="w",
            wraplength=470, justify="left",
        )
        self._error_label.pack(anchor="w", pady=(0, 8))

        # ── Actions ──────────────────────────────
        actions = tk.Frame(wrap, bg=BG)
        actions.pack(fill="x", pady=(6, 0))

        self._submit_btn = tk.Label(
            actions, text="  CRIAR TICKET  ",
            font=(FONT, 9, "bold"),
            fg=BG, bg=GREEN, cursor="hand2", padx=8, pady=6,
        )
        self._submit_btn.pack(side="right")
        self._submit_btn.bind("<Button-1>", lambda _e: self._on_submit())

        cancel_btn = tk.Label(
            actions, text="  CANCELAR  ",
            font=(FONT, 9),
            fg=DIM, bg=BG3, cursor="hand2", padx=8, pady=6,
        )
        cancel_btn.pack(side="right", padx=(0, 8))
        cancel_btn.bind("<Button-1>", lambda _e: self.close())

        title_entry.focus_set()

    # ── Submit flow ───────────────────────────────────────────────

    def _on_submit(self) -> None:
        assert self._desc_widget is not None
        result, draft = validate_draft(
            title=self._title_var.get(),
            description=self._desc_widget.get("1.0", "end").rstrip(),
            assignee_key=self._assignee_var.get(),
            priority=self._priority_var.get(),
        )
        if not result.ok or draft is None:
            self._show_error(" · ".join(result.errors))
            return

        self._set_submitting(True)
        try:
            ok, msg = self._submit_callback(draft)
        except Exception as exc:  # noqa: BLE001
            ok, msg = False, f"exception: {exc}"

        if ok:
            self._show_success(msg or "ticket criado")
            self.top.after(900, self.close)
        else:
            self._set_submitting(False)
            self._show_error(msg or "falha ao criar ticket")

    def _show_error(self, text: str) -> None:
        if self._error_label is not None:
            self._error_label.configure(text=f"erro: {text}", fg=RED)

    def _show_success(self, text: str) -> None:
        if self._error_label is not None:
            self._error_label.configure(text=f"ok: {text}", fg=GREEN)

    def _set_submitting(self, is_submitting: bool) -> None:
        if self._submit_btn is None:
            return
        if is_submitting:
            self._submit_btn.configure(
                text="  ENVIANDO...  ", fg=BG, bg=HAZARD, cursor="arrow",
            )
        else:
            self._submit_btn.configure(
                text="  CRIAR TICKET  ", fg=BG, bg=GREEN, cursor="hand2",
            )

    def close(self) -> None:
        try:
            self.top.grab_release()
        except tk.TclError:
            pass
        try:
            self.top.destroy()
        except tk.TclError:
            pass
