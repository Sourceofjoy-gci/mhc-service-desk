"""Behavioral contract for the development pilot smoke client."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import MappingProxyType
from unittest.mock import Mock, call

import pytest

from scripts import pilot_foundation_smoke as smoke

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def _load_legacy_smoke(name: str):
    path = REPOSITORY_ROOT / "scripts" / f"{name}_smoke.py"
    spec = importlib.util.spec_from_file_location(f"legacy_{name}_smoke", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m2_smoke = _load_legacy_smoke("m2")
m3_smoke = _load_legacy_smoke("m3")


def _response(*, status: int = 200, payload: dict | None = None) -> Mock:
    response = Mock(status_code=status, headers={"X-Correlation-ID": "corr-test"})
    response.json.return_value = payload or {}
    return response


def test_development_identities_are_distinct_and_immutable():
    assert smoke.OPS_HEADERS == {
        "Authorization": "Bearer dev:pilot-ops:ops-agents"
    }
    assert smoke.IT_HEADERS == {"Authorization": "Bearer dev:pilot-it:it-agents"}
    assert smoke.OPS_LEAD_HEADERS == {
        "Authorization": "Bearer dev:pilot-lead:ops-supervisors"
    }
    assert all(
        isinstance(headers, MappingProxyType)
        for headers in (smoke.OPS_HEADERS, smoke.IT_HEADERS, smoke.OPS_LEAD_HEADERS)
    )
    with pytest.raises(TypeError):
        smoke.OPS_HEADERS["Authorization"] = "replacement"


def test_transition_sends_current_timestamp_and_returns_refreshed_detail():
    refreshed = {
        "number": "OP-202607-000001",
        "status_code": "triage",
        "updated_at": "2026-07-28T08:00:01Z",
    }
    session = Mock()
    session.post.return_value = _response(payload=refreshed)
    ticket = {
        "number": "OP-202607-000001",
        "status_code": "new",
        "updated_at": "2026-07-28T08:00:00Z",
    }

    result = smoke.transition(
        session,
        ticket["number"],
        ticket,
        "triage",
        reason="Pilot assessment",
    )

    assert result == refreshed
    session.post.assert_called_once_with(
        f"{smoke.API_BASE}/tickets/{ticket['number']}/transition/",
        headers=smoke.OPS_HEADERS,
        json={
            "to_status": "triage",
            "updated_at": "2026-07-28T08:00:00Z",
            "reason": "Pilot assessment",
        },
        timeout=smoke.REQUEST_TIMEOUT,
    )


def test_conversation_refreshes_detail_after_reply_changes_ticket_timestamp():
    session = Mock()
    session.post.side_effect = [
        _response(status=201, payload={"id": "message-id"}),
        _response(status=201, payload={"id": "note-id"}),
    ]
    session.get.return_value = _response(
        payload={
            "number": "OP-202607-000001",
            "status_code": "new",
            "updated_at": "2026-07-28T08:00:02Z",
        }
    )

    refreshed = smoke.add_reply_and_note(
        session,
        "OP-202607-000001",
    )

    assert refreshed["updated_at"] == "2026-07-28T08:00:02Z"
    session.get.assert_called_once_with(
        f"{smoke.API_BASE}/tickets/OP-202607-000001/",
        headers=smoke.OPS_HEADERS,
        timeout=smoke.REQUEST_TIMEOUT,
    )
    assert session.method_calls == [
        call.post(
            f"{smoke.API_BASE}/tickets/OP-202607-000001/messages/",
            headers=smoke.OPS_HEADERS,
            json={"body_text": "Your request is being handled by the pilot team."},
            timeout=smoke.REQUEST_TIMEOUT,
        ),
        call.post(
            f"{smoke.API_BASE}/tickets/OP-202607-000001/notes/",
            headers=smoke.OPS_HEADERS,
            json={"body": "Internal pilot verification note."},
            timeout=smoke.REQUEST_TIMEOUT,
        ),
        call.get(
            f"{smoke.API_BASE}/tickets/OP-202607-000001/",
            headers=smoke.OPS_HEADERS,
            timeout=smoke.REQUEST_TIMEOUT,
        ),
    ]


def test_transition_rejects_response_without_refreshed_timestamp():
    session = Mock()
    session.post.return_value = _response(
        payload={"number": "OP-202607-000001", "status_code": "triage"}
    )

    with pytest.raises(smoke.SmokeError, match="updated_at"):
        smoke.transition(
            session,
            "OP-202607-000001",
            {"updated_at": "2026-07-28T08:00:00Z"},
            "triage",
        )


def test_validator_reports_only_safe_status_and_correlation_context():
    response = _response(status=403, payload={"private": "do not print"})

    with pytest.raises(smoke.SmokeError) as caught:
        smoke.expect_response(response, 200, "Operational dashboard")

    message = str(caught.value)
    assert "HTTP 403" in message
    assert "corr-test" in message
    assert "do not print" not in message


def test_legacy_m3_email_ids_are_unique_per_run_and_related_within_a_run():
    first = m3_smoke.email_message_ids()
    second = m3_smoke.email_message_ids()

    assert set(first) == {"initial", "reply", "subject_reply"}
    assert len(set(first.values())) == 3
    assert first["initial"] != second["initial"]
    assert all(value.startswith("<m3-") for value in first.values())
    assert all(value.endswith("@example.com>") for value in first.values())


@pytest.mark.parametrize(
    ("legacy_smoke", "headers", "json_payload"),
    [
        (m2_smoke, {"X-Correlation-ID": "corr-safe"}, {}),
        (m3_smoke, {}, {"correlation_id": "corr-safe"}),
    ],
)
def test_legacy_validators_report_only_safe_correlation_context(
    legacy_smoke,
    headers,
    json_payload,
    capsys,
):
    response = Mock(
        status_code=403,
        headers=headers,
        text="PRIVATE-TICKET-BODY",
    )
    response.json.return_value = json_payload

    with pytest.raises(SystemExit):
        legacy_smoke.must(response, 200, "safe label")

    output = capsys.readouterr().out
    assert "safe label" in output
    assert "HTTP 403" in output
    assert "corr-safe" in output
    assert "PRIVATE-TICKET-BODY" not in output


@pytest.mark.parametrize("legacy_smoke", [m2_smoke, m3_smoke])
def test_legacy_validators_handle_non_json_errors_without_body_disclosure(
    legacy_smoke,
    capsys,
):
    response = Mock(
        status_code=500,
        headers={},
        text="PRIVATE-TICKET-BODY",
    )
    response.json.side_effect = ValueError("not JSON")

    with pytest.raises(SystemExit):
        legacy_smoke.must(response, 200, "safe label")

    output = capsys.readouterr().out
    assert "HTTP 500" in output
    assert "correlation_id=unavailable" in output
    assert "PRIVATE-TICKET-BODY" not in output


def test_work_state_validation_accepts_equivalent_aware_timestamps():
    smoke.validate_work_state_response(
        {
            "team": "Pilot Operations",
            "next_action": "Confirm the pilot outcome with the requester",
            "next_action_at": "2026-07-29T10:00:00+02:00",
            "updated_at": "2026-07-28T08:00:01Z",
        },
        previous_updated_at="2026-07-28T08:00:00+00:00",
        team="Pilot Operations",
        next_action="Confirm the pilot outcome with the requester",
        next_action_at="2026-07-29T08:00:00Z",
    )


@pytest.mark.parametrize(
    "override",
    [
        {"team": "Wrong team"},
        {"next_action": "Wrong next action"},
        {"next_action_at": "2026-07-29T08:00:01Z"},
        {"updated_at": "2026-07-28T08:00:00Z"},
    ],
)
def test_work_state_validation_rejects_wrong_values_and_stale_timestamp(override):
    response = {
        "team": "Pilot Operations",
        "next_action": "Confirm the pilot outcome with the requester",
        "next_action_at": "2026-07-29T08:00:00Z",
        "updated_at": "2026-07-28T08:00:01Z",
        **override,
    }

    with pytest.raises(smoke.SmokeError):
        smoke.validate_work_state_response(
            response,
            previous_updated_at="2026-07-28T08:00:00Z",
            team="Pilot Operations",
            next_action="Confirm the pilot outcome with the requester",
            next_action_at="2026-07-29T08:00:00Z",
        )
