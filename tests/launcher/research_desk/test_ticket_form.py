"""Tests das validators + payload encoders do ticket_form.

UI (NewTicketModal) nao testada aqui — gui test deps nao ativas.
"""
from __future__ import annotations

from launcher_support.research_desk.ticket_form import (
    draft_to_api_payload,
    validate_draft,
)


def test_validate_ok_canonical() -> None:
    result, draft = validate_draft(
        title="Implement Kepos hawkes",
        description="Explore invert flag",
        assignee_key="RESEARCH",
        priority="high",
    )
    assert result.ok is True
    assert result.errors == ()
    assert draft is not None
    assert draft.title == "Implement Kepos hawkes"
    assert draft.priority == "high"
    assert draft.assignee.key == "RESEARCH"


def test_validate_trims_title() -> None:
    _, draft = validate_draft(
        title="   Implementar KEPOS   ",
        description="",
        assignee_key="RESEARCH",
        priority="medium",
    )
    assert draft is not None
    assert draft.title == "Implementar KEPOS"


def test_validate_rejects_short_title() -> None:
    result, draft = validate_draft(
        title="ab",
        description="",
        assignee_key="RESEARCH",
        priority="low",
    )
    assert result.ok is False
    assert draft is None
    assert any("minimo" in e for e in result.errors)


def test_validate_rejects_long_title() -> None:
    result, _ = validate_draft(
        title="x" * 200,
        description="",
        assignee_key="REVIEW",
        priority="medium",
    )
    assert result.ok is False
    assert any("maximo" in e for e in result.errors)


def test_validate_rejects_unknown_priority() -> None:
    result, _ = validate_draft(
        title="title ok",
        description="",
        assignee_key="RESEARCH",
        priority="urgent",
    )
    assert result.ok is False
    assert any("priority" in e for e in result.errors)


def test_validate_rejects_unknown_assignee() -> None:
    result, _ = validate_draft(
        title="title ok",
        description="",
        assignee_key="NEBULAR",
        priority="medium",
    )
    assert result.ok is False
    assert any("assignee" in e for e in result.errors)


def test_validate_case_insensitive_assignee() -> None:
    _, draft = validate_draft(
        title="title ok",
        description="",
        assignee_key="research",
        priority="low",
    )
    assert draft is not None
    assert draft.assignee.key == "RESEARCH"


def test_validate_case_insensitive_priority() -> None:
    _, draft = validate_draft(
        title="title ok",
        description="",
        assignee_key="RESEARCH",
        priority="HIGH",
    )
    assert draft is not None
    assert draft.priority == "high"


def test_validate_accumulates_multiple_errors() -> None:
    result, _ = validate_draft(
        title="x",
        description="",
        assignee_key="NOPE",
        priority="??",
    )
    assert result.ok is False
    assert len(result.errors) >= 2


def test_payload_shape_matches_paperclip_api() -> None:
    _, draft = validate_draft(
        title="Implement X",
        description="line1\nline2",
        assignee_key="BUILD",
        priority="high",
    )
    assert draft is not None
    payload = draft_to_api_payload(draft)
    assert payload == {
        "title": "Implement X",
        "description": "line1\nline2",
        "assigned_agent_id": draft.assignee.uuid,
        "priority": "high",
        "status": "todo",
    }


def test_payload_assignee_uuid_is_real_paperclip_id() -> None:
    _, draft = validate_draft(
        title="ok ok ok", description="",
        assignee_key="CURATE", priority="low",
    )
    assert draft is not None
    payload = draft_to_api_payload(draft)
    # UUID real definido em agents.py
    assert payload["assigned_agent_id"] == "a424432d-be6d-44ea-80e3-f9b2c3b9d534"


def test_validate_empty_description_ok() -> None:
    result, draft = validate_draft(
        title="title mininmo",
        description="",
        assignee_key="RESEARCH",
        priority="medium",
    )
    assert result.ok is True
    assert draft is not None
    assert draft.description == ""


def test_validate_accepts_optional_run_id():
    result, draft = validate_draft(
        title="Investigate phi overfit",
        description="",
        assignee_key="AUDIT",
        priority="medium",
        run_id="phi/2026-04-23_1403",
    )
    assert result.ok is True
    assert draft.run_id == "phi/2026-04-23_1403"


def test_validate_without_run_id_default_none():
    _, draft = validate_draft(
        title="title ok",
        description="",
        assignee_key="RESEARCH",
        priority="low",
    )
    assert draft.run_id is None


def test_validate_rejects_malformed_run_id():
    result, _ = validate_draft(
        title="title ok",
        description="",
        assignee_key="RESEARCH",
        priority="low",
        run_id="x y z",  # espaço rejeita
    )
    assert result.ok is False
    assert any("run_id" in e for e in result.errors)


def test_payload_injects_run_id_into_description_and_labels():
    _, draft = validate_draft(
        title="Audit phi",
        description="Check regime selection bias",
        assignee_key="AUDIT",
        priority="high",
        run_id="phi/2026-04-23_1403",
    )
    payload = draft_to_api_payload(draft)
    assert "**run_id:** phi/2026-04-23_1403" in payload["description"]
    assert "Check regime selection bias" in payload["description"]
    assert "run:phi/2026-04-23_1403" in payload.get("labels", [])


def test_payload_without_run_id_unchanged():
    _, draft = validate_draft(
        title="title ok",
        description="body",
        assignee_key="RESEARCH",
        priority="medium",
    )
    payload = draft_to_api_payload(draft)
    assert payload["description"] == "body"
    assert "labels" not in payload or payload["labels"] == []
