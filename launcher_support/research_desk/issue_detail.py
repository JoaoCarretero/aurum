"""IssueDetailModal — Toplevel pra ver um ticket do Paperclip ao vivo.

Abre via open_issue_detail(parent, client, issue_id, on_close=cb).
Polling interno 5s; fecha c/ ESC ou botão FECHAR; on_close dispara
refresh no caller. Circuit breaker failure → banner offline inline.

Shape layer (_parse_lineage, _shape_comments, _format_header_line) é
testável sem Tk.
"""
from __future__ import annotations

import datetime as dt
import re
import tkinter as tk
from dataclasses import dataclass
from typing import Any, Callable

from core.ui.ui_palette import (
    AMBER, AMBER_D, BG, BG2, BG3,
    DIM, FONT, RED, WHITE,
)
from launcher_support.research_desk.agents import BY_UUID
from launcher_support.research_desk.palette import AGENT_COLORS


POLL_INTERVAL_MS = 5000
_LINEAGE_RE = re.compile(r"^from:\s*(AUR-\d+[^\n]*)", re.MULTILINE)


@dataclass(frozen=True)
class CommentView:
    id: str
    body: str
    created_at_iso: str
    age_text: str
    author_sigil: str         # agent key ou "—"
    author_color: str         # hex


def _parse_lineage(description: str | None) -> str | None:
    if not description:
        return None
    m = _LINEAGE_RE.search(description)
    if m:
        return m.group(1).strip()
    return None


def _shape_comments(raw: list[dict] | None) -> list[CommentView]:
    if not raw:
        return []
    out: list[CommentView] = []
    for c in raw:
        cid = str(c.get("id") or "")
        body = (c.get("body") or c.get("text") or "").strip()
        iso = c.get("created_at") or ""
        author_uuid = c.get("author_agent_id") or c.get("agent_id") or ""
        sigil = "—"
        color = DIM
        agent = BY_UUID.get(author_uuid) if author_uuid else None
        if agent is not None:
            sigil = agent.key
            color = AGENT_COLORS[agent.key].primary
        out.append(CommentView(
            id=cid,
            body=body,
            created_at_iso=iso,
            age_text=_iso_age(iso),
            author_sigil=sigil,
            author_color=color,
        ))
    out.sort(key=lambda v: v.created_at_iso)  # oldest first
    return out


def _iso_age(iso: str) -> str:
    if not iso:
        return "—"
    try:
        moment = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "—"
    now = dt.datetime.now(dt.timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    s = int((now - moment).total_seconds())
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}min"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


def _format_header_line(
    *, issue_id: str, title: str, status: str, priority: str, assignee_key: str,
) -> str:
    return f"{issue_id}  ·  {title}  ·  {status.upper()}  ·  {priority.upper()}  ·  {assignee_key}"


class IssueDetailModal:
    """Toplevel readonly pra detail + comments com polling."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        client: Any,
        issue_id: str,
        on_close: Callable[[], None] | None = None,
    ):
        self._client = client
        self._issue_id = issue_id
        self._on_close = on_close
        self._closing = False
        self._poll_after: str | None = None

        self.top = tk.Toplevel(parent)
        self.top.title(f"ISSUE {issue_id}")
        self.top.configure(bg=BG)
        self.top.geometry("640x560")
        self.top.transient(parent)
        self.top.bind("<Escape>", lambda _e: self.close())
        self.top.protocol("WM_DELETE_WINDOW", self.close)

        self._header_var = tk.StringVar(value=f"{issue_id}  ·  loading…")
        self._offline_label: tk.Label | None = None
        self._lineage_label: tk.Label | None = None
        self._body_widget: tk.Text | None = None
        self._comments_frame: tk.Frame | None = None
        self._comments_canvas: tk.Canvas | None = None

        self._build()
        self._tick()  # fetch inicial + agenda poll

    def _build(self) -> None:
        wrap = tk.Frame(self.top, bg=BG, padx=16, pady=12)
        wrap.pack(fill="both", expand=True)

        self._offline_label = tk.Label(
            wrap, text="", font=(FONT, 8, "bold"),
            fg=RED, bg=BG, anchor="w",
        )
        self._offline_label.pack(anchor="w")

        tk.Label(
            wrap, textvariable=self._header_var,
            font=(FONT, 10, "bold"), fg=AMBER, bg=BG, anchor="w",
        ).pack(anchor="w", pady=(4, 0))

        self._lineage_label = tk.Label(
            wrap, text="", font=(FONT, 8), fg=DIM, bg=BG, anchor="w",
        )
        self._lineage_label.pack(anchor="w", pady=(2, 8))
        tk.Frame(wrap, bg=DIM, height=1).pack(fill="x")

        tk.Label(
            wrap, text="BODY", font=(FONT, 8, "bold"),
            fg=AMBER_D, bg=BG, anchor="w",
        ).pack(anchor="w", pady=(8, 2))
        self._body_widget = tk.Text(
            wrap, height=8, bg=BG2, fg=WHITE, font=(FONT, 9),
            relief="flat", wrap="word",
        )
        self._body_widget.pack(fill="x")
        self._body_widget.configure(state="disabled")

        tk.Label(
            wrap, text="COMMENTS", font=(FONT, 8, "bold"),
            fg=AMBER_D, bg=BG, anchor="w",
        ).pack(anchor="w", pady=(12, 2))

        canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, height=220)
        canvas.pack(fill="both", expand=True)
        self._comments_frame = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=self._comments_frame, anchor="nw")
        self._comments_canvas = canvas

        footer = tk.Frame(wrap, bg=BG); footer.pack(fill="x", pady=(10, 0))
        close_btn = tk.Label(
            footer, text="  FECHAR  ", font=(FONT, 8, "bold"),
            fg=WHITE, bg=BG3, cursor="hand2", padx=10, pady=4,
        )
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda _e: self.close())

    def _tick(self) -> None:
        if self._closing:
            return
        try:
            issue = self._client.get_issue(self._issue_id)
            comments = self._client.list_comments(self._issue_id)
            self._apply(issue, comments, offline=False)
        except Exception as exc:
            self._apply(None, None, offline=True, error=str(exc))

        if not self._closing:
            self._poll_after = self.top.after(POLL_INTERVAL_MS, self._tick)

    def _apply(
        self, issue: dict | None, comments: list[dict] | None,
        *, offline: bool, error: str = "",
    ) -> None:
        if self._closing:
            return
        if offline:
            label = self._offline_label
            if label is not None:
                label.configure(text=f"⚠  PAPERCLIP OFFLINE — {error[:40]}", fg=RED)
            return
        if self._offline_label is not None:
            self._offline_label.configure(text="")

        if issue is not None:
            assignee_uuid = issue.get("assigned_agent_id") or ""
            agent = BY_UUID.get(assignee_uuid) if assignee_uuid else None
            akey = agent.key if agent else "—"
            self._header_var.set(_format_header_line(
                issue_id=self._issue_id,
                title=(issue.get("title") or "(sem título)")[:80],
                status=issue.get("status") or "unknown",
                priority=issue.get("priority") or "medium",
                assignee_key=akey,
            ))
            lineage = _parse_lineage(issue.get("description"))
            if self._lineage_label is not None:
                self._lineage_label.configure(
                    text=f"← {lineage}" if lineage else "",
                )
            body = issue.get("description") or ""
            w = self._body_widget
            if w is not None:
                w.configure(state="normal")
                w.delete("1.0", "end")
                w.insert("1.0", body[:4000])
                w.configure(state="disabled")

        self._render_comments(_shape_comments(comments))

    def _render_comments(self, views: list[CommentView]) -> None:
        frame = self._comments_frame
        if frame is None:
            return
        for child in frame.winfo_children():
            child.destroy()
        if not views:
            tk.Label(
                frame, text="(sem comments ainda)",
                font=(FONT, 9), fg=DIM, bg=BG,
            ).pack(anchor="w", padx=4, pady=2)
            return
        for v in views:
            row = tk.Frame(frame, bg=BG)
            row.pack(fill="x", anchor="w", pady=(4, 0))
            tk.Label(
                row, text=f"{v.author_sigil}  {v.age_text}",
                font=(FONT, 8, "bold"), fg=v.author_color, bg=BG,
            ).pack(anchor="w")
            tk.Label(
                row, text=v.body[:400], font=(FONT, 9), fg=WHITE, bg=BG,
                wraplength=560, justify="left", anchor="w",
            ).pack(anchor="w", padx=(12, 0))
        canvas = self._comments_canvas
        if canvas is not None:
            try:
                canvas.configure(scrollregion=canvas.bbox("all"))
            except Exception:
                pass

    def close(self) -> None:
        self._closing = True
        if self._poll_after is not None:
            try:
                self.top.after_cancel(self._poll_after)
            except Exception:
                pass
            self._poll_after = None
        try:
            self.top.destroy()
        except Exception:
            pass
        if self._on_close is not None:
            try:
                self._on_close()
            except Exception:
                pass


def open_issue_detail(
    parent: tk.Misc,
    *,
    client: Any,
    issue_id: str,
    on_close: Callable[[], None] | None = None,
) -> IssueDetailModal:
    return IssueDetailModal(parent, client=client, issue_id=issue_id, on_close=on_close)
