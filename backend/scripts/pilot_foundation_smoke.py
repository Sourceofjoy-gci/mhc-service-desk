"""Append-only Operational/IT lifecycle smoke for the local development stack."""
from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any
from uuid import uuid4

import requests

API_BASE = os.getenv("PILOT_API_BASE", "http://localhost:8000/api/v1").rstrip("/")
REQUEST_TIMEOUT = 10

OPS_HEADERS: Mapping[str, str] = MappingProxyType(
    {"Authorization": "Bearer dev:pilot-ops:ops-agents"}
)
IT_HEADERS: Mapping[str, str] = MappingProxyType(
    {"Authorization": "Bearer dev:pilot-it:it-agents"}
)
OPS_LEAD_HEADERS: Mapping[str, str] = MappingProxyType(
    {"Authorization": "Bearer dev:pilot-lead:ops-supervisors"}
)


class SmokeError(RuntimeError):
    """A safe-to-print smoke assertion failure."""


_AWARE_ISO_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)


def _correlation_id(response: requests.Response) -> str:
    correlation_id = response.headers.get("X-Correlation-ID", "")
    if correlation_id:
        return correlation_id
    try:
        payload = response.json()
    except (requests.JSONDecodeError, ValueError):
        return "unavailable"
    if isinstance(payload, dict):
        return str(payload.get("correlation_id") or "unavailable")
    return "unavailable"


def expect_response(
    response: requests.Response,
    expected_status: int,
    label: str,
) -> requests.Response:
    """Fail fast with status and correlation context, never response content."""
    if response.status_code != expected_status:
        raise SmokeError(
            f"{label}: HTTP {response.status_code}; "
            f"correlation_id={_correlation_id(response)}"
        )
    return response


def _json_object(response: requests.Response, label: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except (requests.JSONDecodeError, ValueError) as exc:
        raise SmokeError(f"{label}: response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise SmokeError(f"{label}: response was not a JSON object")
    return payload


def _get_json(
    session: requests.Session,
    path: str,
    *,
    headers: Mapping[str, str],
    expected_status: int = 200,
    label: str,
) -> dict[str, Any]:
    response = session.get(
        f"{API_BASE}{path}",
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    expect_response(response, expected_status, label)
    return _json_object(response, label)


def _post_json(
    session: requests.Session,
    path: str,
    *,
    payload: dict[str, Any],
    headers: Mapping[str, str] | None = None,
    expected_status: int,
    label: str,
) -> dict[str, Any]:
    response = session.post(
        f"{API_BASE}{path}",
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    expect_response(response, expected_status, label)
    return _json_object(response, label)


def _patch_json(
    session: requests.Session,
    path: str,
    *,
    payload: dict[str, Any],
    headers: Mapping[str, str],
    label: str,
) -> dict[str, Any]:
    response = session.patch(
        f"{API_BASE}{path}",
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    expect_response(response, 200, label)
    return _json_object(response, label)


def _require_field(payload: dict[str, Any], field: str, label: str) -> Any:
    value = payload.get(field)
    if value is None or value == "":
        raise SmokeError(f"{label}: missing {field}")
    return value


def _require(condition: bool, label: str) -> None:
    if not condition:
        raise SmokeError(label)


def _aware_datetime(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not _AWARE_ISO_DATETIME.fullmatch(value):
        raise SmokeError(f"{label}: expected a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SmokeError(f"{label}: expected a valid ISO timestamp") from exc
    if parsed.utcoffset() is None:
        raise SmokeError(f"{label}: expected a timezone-aware ISO timestamp")
    return parsed


def validate_work_state_response(
    ticket: dict[str, Any],
    *,
    previous_updated_at: str,
    team: str,
    next_action: str,
    next_action_at: str,
) -> None:
    """Fail closed unless the response proves the requested work-state mutation."""
    _require(ticket.get("team") == team, "work-state response returned the wrong team")
    _require(
        ticket.get("next_action") == next_action,
        "work-state response returned the wrong next action",
    )
    returned_next_action_at = _aware_datetime(
        ticket.get("next_action_at"),
        "work-state next action time",
    )
    requested_next_action_at = _aware_datetime(
        next_action_at,
        "requested next action time",
    )
    _require(
        returned_next_action_at == requested_next_action_at,
        "work-state response returned the wrong next action time",
    )
    returned_updated_at = _aware_datetime(
        ticket.get("updated_at"),
        "work-state updated time",
    )
    previous_updated = _aware_datetime(previous_updated_at, "previous updated time")
    _require(
        returned_updated_at != previous_updated,
        "work-state response returned a stale updated time",
    )


def transition(
    session: requests.Session,
    number: str,
    ticket: dict[str, Any],
    to_status: str,
    **fields: Any,
) -> dict[str, Any]:
    """Transition an Operational ticket using its latest optimistic timestamp."""
    updated_at = _require_field(ticket, "updated_at", f"transition to {to_status}")
    refreshed = _post_json(
        session,
        f"/tickets/{number}/transition/",
        headers=OPS_HEADERS,
        payload={"to_status": to_status, "updated_at": updated_at, **fields},
        expected_status=200,
        label=f"transition {number} to {to_status}",
    )
    _require_field(refreshed, "updated_at", f"transition {number} to {to_status}")
    _require(
        refreshed.get("status_code") == to_status,
        f"transition {number} did not return status {to_status}",
    )
    return refreshed


def add_reply_and_note(
    session: requests.Session,
    number: str,
) -> dict[str, Any]:
    """Add both conversation records and return detail with the latest timestamp."""
    _post_json(
        session,
        f"/tickets/{number}/messages/",
        headers=OPS_HEADERS,
        payload={"body_text": "Your request is being handled by the pilot team."},
        expected_status=201,
        label="Requester-visible reply",
    )
    _post_json(
        session,
        f"/tickets/{number}/notes/",
        headers=OPS_HEADERS,
        payload={"body": "Internal pilot verification note."},
        expected_status=201,
        label="Internal note",
    )
    return _get_json(
        session,
        f"/tickets/{number}/",
        headers=OPS_HEADERS,
        label="Operational detail after conversation",
    )


def _intake_payload(suffix: str, *, child_parent: bool = False) -> dict[str, Any]:
    purpose = "IT child parent" if child_parent else "lifecycle"
    return {
        "request_type_code": "HOURS",
        "service_code": "GEN-INFO",
        "office_code": "MHC-MBA",
        "title": f"Pilot {purpose} {suffix}",
        "description": f"Append-only pilot smoke request {suffix}.",
        "requester_name": "Pilot Smoke",
        "requester_email": f"pilot-{purpose.replace(' ', '-')}-{suffix}@example.test",
        "consent": True,
    }


def run(session: requests.Session) -> tuple[str, str, str]:
    """Execute the exact append-only Operational/IT pilot workflow."""
    # Materialise durable development group snapshots before scoped operations.
    _get_json(session, "/tickets/", headers=OPS_HEADERS, label="Operational list")
    _get_json(session, "/tickets/", headers=IT_HEADERS, label="IT list")

    suffix = uuid4().hex[:8]
    intake = _post_json(
        session,
        "/tickets/public/intake/",
        payload=_intake_payload(suffix),
        expected_status=201,
        label="Operational public intake",
    )
    operational_number = str(
        _require_field(intake, "ticket_number", "Operational public intake")
    )

    ticket = _get_json(
        session,
        f"/tickets/{operational_number}/",
        headers=OPS_HEADERS,
        label="Operational detail",
    )
    hidden = session.get(
        f"{API_BASE}/tickets/{operational_number}/",
        headers=IT_HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    expect_response(hidden, 404, "IT access to Operational detail")

    capabilities = ticket.get("capabilities")
    _require(isinstance(capabilities, dict), "Operational detail missing capabilities")
    self_assignee_id = _require_field(
        capabilities,
        "self_assignee_id",
        "Operational detail capabilities",
    )
    ticket = _patch_json(
        session,
        f"/tickets/{operational_number}/work-state/",
        headers=OPS_HEADERS,
        payload={
            "updated_at": _require_field(ticket, "updated_at", "Operational detail"),
            "assignee": self_assignee_id,
        },
        label="Operational self-assignment",
    )
    _require(
        str(ticket.get("assignee")) == str(self_assignee_id),
        "Operational self-assignment did not refresh the assignee",
    )

    work_state_team = "Pilot Operations"
    work_state_next_action = "Confirm the pilot outcome with the requester"
    next_action_at = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    previous_updated_at = str(_require_field(ticket, "updated_at", "assigned detail"))
    ticket = _patch_json(
        session,
        f"/tickets/{operational_number}/work-state/",
        headers=OPS_HEADERS,
        payload={
            "updated_at": previous_updated_at,
            "team": work_state_team,
            "next_action": work_state_next_action,
            "next_action_at": next_action_at,
        },
        label="Operational work-state update",
    )
    validate_work_state_response(
        ticket,
        previous_updated_at=previous_updated_at,
        team=work_state_team,
        next_action=work_state_next_action,
        next_action_at=next_action_at,
    )

    ticket = add_reply_and_note(session, operational_number)

    ticket = transition(
        session,
        operational_number,
        ticket,
        "triage",
        reason="Pilot triage completed",
    )
    ticket = transition(session, operational_number, ticket, "in_progress")
    ticket = transition(
        session,
        operational_number,
        ticket,
        "resolved",
        resolution_code="PILOT_COMPLETED",
        resolution_summary="The Operational pilot lifecycle was verified.",
    )
    _require(bool(ticket.get("resolution_code")), "resolution code was not set")
    _require(bool(ticket.get("resolution_summary")), "resolution summary was not set")
    ticket = transition(
        session,
        operational_number,
        ticket,
        "reopened",
        reason="Verify reopen behavior",
    )
    _require(ticket.get("resolution_code") == "", "reopen retained resolution code")
    _require(ticket.get("resolution_summary") == "", "reopen retained resolution summary")
    _require(ticket.get("resolved_at") is None, "reopen retained resolved timestamp")
    _require(bool(ticket.get("reopened_at")), "reopen timestamp was not set")

    activity = _get_json(
        session,
        f"/tickets/{operational_number}/activity/",
        headers=OPS_HEADERS,
        label="Operational activity",
    )
    items = activity.get("results")
    _require(isinstance(items, list), "Operational activity missing results")
    activity_types = {
        item.get("type") for item in items if isinstance(item, dict)
    }
    _require("message" in activity_types, "Operational activity missing message")
    _require("internal_note" in activity_types, "Operational activity missing note")
    _require("work_state" in activity_types, "Operational activity missing work-state")
    transition_targets = {
        item.get("payload", {}).get("to")
        for item in items
        if isinstance(item, dict)
        and item.get("type") == "status_transition"
        and isinstance(item.get("payload"), dict)
    }
    _require("resolved" in transition_targets, "Operational activity missing resolution")
    _require("reopened" in transition_targets, "Operational activity missing reopen")

    ops_it_dashboard = session.get(
        f"{API_BASE}/reports/dashboard/it",
        headers=OPS_HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    expect_response(ops_it_dashboard, 403, "Operational access to IT dashboard")
    it_ops_dashboard = session.get(
        f"{API_BASE}/reports/dashboard/operational",
        headers=IT_HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    expect_response(it_ops_dashboard, 403, "IT access to Operational dashboard")

    parent_suffix = uuid4().hex[:8]
    parent_intake = _post_json(
        session,
        "/tickets/public/intake/",
        payload=_intake_payload(parent_suffix, child_parent=True),
        expected_status=201,
        label="IT child parent intake",
    )
    parent_number = str(
        _require_field(parent_intake, "ticket_number", "IT child parent intake")
    )
    child_result = _post_json(
        session,
        f"/tickets/{parent_number}/it-child/",
        headers=OPS_HEADERS,
        payload={
            "summary": f"Sanitised pilot IT dependency {parent_suffix}",
            "technical_priority": "P2",
            "carry_matter_reference": False,
        },
        expected_status=201,
        label="IT child creation",
    )
    child_number = str(_require_field(child_result, "child_number", "IT child creation"))
    child = _get_json(
        session,
        f"/tickets/{child_number}/",
        headers=IT_HEADERS,
        label="IT child detail",
    )
    _require(child.get("domain") == "it", "IT child detail returned the wrong domain")
    hidden_child = session.get(
        f"{API_BASE}/tickets/{child_number}/",
        headers=OPS_HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    expect_response(hidden_child, 404, "Operational access to IT child detail")

    return operational_number, parent_number, child_number


def main() -> int:
    try:
        with requests.Session() as session:
            operational_number, parent_number, child_number = run(session)
    except (requests.RequestException, SmokeError) as exc:
        print(f"Pilot foundation smoke failed: {exc}", file=sys.stderr)
        return 1

    print(f"Operational lifecycle ticket: {operational_number}")
    print(f"Operational IT-parent ticket: {parent_number}")
    print(f"IT child ticket: {child_number}")
    print("Pilot foundation smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
