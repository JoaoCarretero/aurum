"""Tests do IssueDetailModal — API pura + shape."""
from __future__ import annotations

from unittest.mock import MagicMock

from launcher_support.research_desk.issue_detail import (
    _parse_lineage,
    _shape_comments,
    _format_header_line,
)


def test_parse_lineage_from_description():
    desc = "from: AUR-7 (REVIEW SHIP)\n\nMain body here"
    assert _parse_lineage(desc) == "AUR-7 (REVIEW SHIP)"


def test_parse_lineage_none_when_absent():
    assert _parse_lineage("no lineage in body") is None


def test_shape_comments_sorted_oldest_first():
    raw = [
        {"id": "c2", "body": "reply", "created_at": "2026-04-24T10:00:00Z",
         "author_agent_id": "uuid-a"},
        {"id": "c1", "body": "first", "created_at": "2026-04-24T09:00:00Z",
         "author_agent_id": "uuid-b"},
    ]
    shaped = _shape_comments(raw)
    assert shaped[0].id == "c1"
    assert shaped[1].id == "c2"


def test_shape_comments_empty_when_raw_none():
    assert _shape_comments(None) == []


def test_format_header_line():
    line = _format_header_line(
        issue_id="AUR-12", title="Audit CAPULA",
        status="in_progress", priority="high", assignee_key="AUDIT",
    )
    assert "AUR-12" in line
    assert "Audit CAPULA" in line
    assert "AUDIT" in line
