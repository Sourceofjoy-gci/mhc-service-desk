from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.identity_access.models import Role, User, UserRole
from apps.organisations.models import Office, ServiceLocation
from apps.tickets.models import OutboxEvent, Ticket, TicketCustodyEvent
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db

CORRELATION_ID = "assignment-api-test-correlation"


def _user(
    groups: list[str] | None = None,
    *,
    display_name: str = "",
    active: bool = True,
) -> User:
    user = User.objects.create(
        username=f"staff-{uuid4().hex}",
        keycloak_subject=f"subject-{uuid4().hex}",
        display_name=display_name,
        keycloak_groups=groups or [],
        is_active=active,
    )
    user._groups = groups or []
    return user


def _ticket(
    basic_world,
    *,
    domain: str = Ticket.Domain.OPERATIONAL,
    confidentiality: str = Ticket.Confidentiality.NORMAL,
    queue: ServiceLocation | None = None,
    assignee: User | None = None,
) -> Ticket:
    service = (
        basic_world["gen_info"]
        if domain == Ticket.Domain.OPERATIONAL
        else basic_world["it_inc"]
    )
    prefix = "OP" if domain == Ticket.Domain.OPERATIONAL else "IT"
    return Ticket.objects.create(
        number=f"{prefix}-202607-{Ticket.objects.count() + 980001:06d}",
        domain=domain,
        title="Assignment API contract",
        status=Status.objects.get(domain=domain, code="new"),
        channel=Ticket.Channel.INTERNAL,
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
        confidentiality=confidentiality,
        queue=queue,
        assignee=assignee,
    )


def _grant(
    user: User,
    *,
    role_key: str = "estate-examiner",
    role_name: str = "Estate Examiner",
    scopes: list[dict[str, object]],
    office: Office | None = None,
    expires_at=None,
) -> UserRole:
    role = Role.objects.create(
        keycloak_role=role_key,
        name=role_name,
        scopes=scopes,
    )
    return UserRole.objects.create(
        user=user,
        role=role,
        office=office,
        expires_at=expires_at,
    )


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _candidate_url(ticket: Ticket) -> str:
    return reverse("tickets-assignees", args=[ticket.number])


def _assignment_url(ticket: Ticket) -> str:
    return reverse("tickets-assignment", args=[ticket.number])


def _post_assignment(
    client: APIClient,
    ticket: Ticket,
    *,
    assignee_id: UUID | None,
    expected_updated_at=None,
    reason: str | None = None,
):
    payload: dict[str, object] = {
        "assignee_id": str(assignee_id) if assignee_id is not None else None,
        "expected_updated_at": (
            expected_updated_at or ticket.updated_at
        ).isoformat(),
    }
    if reason is not None:
        payload["reason"] = reason
    return client.post(
        _assignment_url(ticket),
        payload,
        format="json",
        HTTP_X_CORRELATION_ID=CORRELATION_ID,
    )


def _scope(ticket: Ticket, *, restricted: bool = False) -> dict[str, object]:
    return {
        "domain": ticket.domain,
        "office": str(ticket.office_id),
        "service": str(ticket.service_id),
        **({"queue": str(ticket.queue_id)} if ticket.queue_id else {}),
        **({"restricted_only": True} if restricted else {}),
    }


def _side_effect_counts(ticket: Ticket) -> tuple[int, int, int]:
    return (
        AuditEvent.objects.filter(object_id=str(ticket.id)).count(),
        OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).count(),
        TicketCustodyEvent.objects.filter(ticket=ticket).count(),
    )


def test_candidate_directory_requires_assignment_authority(basic_world):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)

    response = _client(actor).get(
        _candidate_url(ticket),
        HTTP_X_CORRELATION_ID=CORRELATION_ID,
    )

    assert response.status_code == 403
    assert response.data == {
        "code": "ticket_action_forbidden",
        "detail": "You cannot perform this ticket action.",
        "fields": {},
        "correlation_id": CORRELATION_ID,
    }


def test_candidate_directory_returns_only_exact_active_staff_with_metadata_and_search(
    basic_world,
):
    queue = ServiceLocation.objects.create(
        office=basic_world["office"],
        name="Restricted finance queue",
    )
    ticket = _ticket(
        basic_world,
        queue=queue,
        confidentiality=Ticket.Confidentiality.RESTRICTED,
    )
    actor = _user(["ops-supervisors"], display_name="Supervising User")
    eligible = _user(display_name="Naledi Exact")
    _grant(
        eligible,
        role_key="senior-accountant",
        role_name="Senior Accountant",
        scopes=[_scope(ticket, restricted=True)],
        office=ticket.office,
    )

    inactive = _user(display_name="Inactive Finance", active=False)
    _grant(
        inactive,
        role_key="accountant",
        role_name="Accountant",
        scopes=[_scope(ticket, restricted=True)],
        office=ticket.office,
    )
    wrong_office = _user(display_name="Wrong Office Finance")
    other_office = Office.objects.create(
        region=basic_world["region"],
        code=f"OTHER-{uuid4().hex[:8]}",
        name="Other office",
    )
    _grant(
        wrong_office,
        role_key="principal-accountant",
        role_name="Principal Accountant",
        scopes=[_scope(ticket, restricted=True)],
        office=other_office,
    )
    wrong_service = _user(display_name="Wrong Service Finance")
    _grant(
        wrong_service,
        role_key="financial-controller",
        role_name="Financial Controller",
        scopes=[{**_scope(ticket, restricted=True), "service": str(uuid4())}],
        office=ticket.office,
    )
    wrong_queue = _user(display_name="Wrong Queue Finance")
    _grant(
        wrong_queue,
        role_key="assistant-accountant",
        role_name="Assistant Accountant",
        scopes=[{**_scope(ticket, restricted=True), "queue": str(uuid4())}],
        office=ticket.office,
    )
    wrong_domain = _user(display_name="Wrong Domain Finance")
    _grant(
        wrong_domain,
        role_key="master",
        role_name="Master",
        scopes=[{**_scope(ticket, restricted=True), "domain": "it"}],
        office=ticket.office,
    )
    expired = _user(display_name="Expired Finance")
    _grant(
        expired,
        role_key="assistant-master",
        role_name="Assistant Master",
        scopes=[_scope(ticket, restricted=True)],
        office=ticket.office,
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    unrestricted = _user(display_name="No Restricted Finance")
    _grant(
        unrestricted,
        role_key="deputy-master",
        role_name="Deputy Master",
        scopes=[_scope(ticket)],
        office=ticket.office,
    )
    auditor = _user(display_name="Auditor Finance")
    _grant(
        auditor,
        role_key="estate-examiner",
        role_name="Estate Examiner",
        scopes=[_scope(ticket, restricted=True)],
        office=ticket.office,
    )
    _grant(
        auditor,
        role_key="auditor",
        role_name="Auditor",
        scopes=[{"domain": "audit"}],
    )

    response = _client(actor).get(
        _candidate_url(ticket),
        {"search": "FINANCE"},
        HTTP_X_CORRELATION_ID=CORRELATION_ID,
    )

    assert response.status_code == 200
    assert response.data == {
        "results": [
            {
                "id": str(eligible.id),
                "username": eligible.username,
                "display_name": "Naledi Exact",
                "designations": ["Senior Accountant"],
                "team_labels": ["Finance"],
            }
        ]
    }

    name_search = _client(actor).get(
        _candidate_url(ticket),
        {"search": "naledi"},
    )
    assert [item["id"] for item in name_search.data["results"]] == [str(eligible.id)]


def test_candidate_search_rejects_more_than_one_hundred_characters(basic_world):
    actor = _user(["ops-supervisors"])
    ticket = _ticket(basic_world)

    response = _client(actor).get(
        _candidate_url(ticket),
        {"search": "x" * 101},
        HTTP_X_CORRELATION_ID=CORRELATION_ID,
    )

    assert response.status_code == 400
    assert response.data["code"] == "invalid_assignee_search"
    assert response.data["detail"] == "Assignee search is invalid."
    assert set(response.data["fields"]) == {"search"}
    assert response.data["correlation_id"] == CORRELATION_ID


def test_assignment_returns_refreshed_ticket_and_immutable_transfer_receipt(
    basic_world,
    monkeypatch,
):
    actor = _user(["ops-supervisors"], display_name="Mpho Supervisor")
    previous = _user(["ops-agents"], display_name="Previous Officer")
    target = _user(display_name="New Estate Examiner")
    ticket = _ticket(basic_world, assignee=previous)
    role_assignment = _grant(
        target,
        scopes=[_scope(ticket)],
        office=ticket.office,
    )
    from apps.tickets.assignment import assign_ticket as real_assign_ticket

    def mutate_profiles_after_assignment(**kwargs):
        result = real_assign_ticket(**kwargs)
        User.objects.filter(pk=actor.pk).update(display_name="Changed Actor")
        User.objects.filter(pk=target.pk).update(display_name="Changed Target")
        Role.objects.filter(pk=role_assignment.role_id).update(name="Changed Role")
        return result

    monkeypatch.setattr(
        "apps.tickets.views.assign_ticket",
        mutate_profiles_after_assignment,
    )

    response = _post_assignment(
        _client(actor),
        ticket,
        assignee_id=target.id,
        reason="Transfer for examination",
    )

    assert response.status_code == 200
    assert response.data["ticket"]["number"] == ticket.number
    assert response.data["ticket"]["assignee"] == target.id
    receipt = response.data["receipt"]
    assert receipt["ticket_number"] == ticket.number
    assert receipt["action"] == "reassigned"
    assert receipt["previous_assignee"] == {
        "id": str(previous.id),
        "display_name": "Previous Officer",
        "designations": ["Operational Agent"],
        "team_labels": ["Operational"],
    }
    assert receipt["new_assignee"] == {
        "id": str(target.id),
        "display_name": "New Estate Examiner",
        "designations": ["Estate Examiner"],
        "team_labels": ["Estate Administration"],
    }
    assert receipt["performed_by"] == {
        "kind": "user",
        "subject": actor.keycloak_subject,
        "display_name": "Mpho Supervisor",
    }
    event = TicketCustodyEvent.objects.get(ticket=ticket)
    assert parse_datetime(receipt["occurred_at"]) == event.occurred_at
    ticket.refresh_from_db()
    assert ticket.assignee_id == target.id


def _ineligible_target(basic_world, ticket: Ticket, case: str) -> User:
    if case == "inactive":
        return _user(["ops-agents"], active=False)
    if case == "wrong_domain":
        return _user(["it-agents"])

    target = _user()
    scope = _scope(ticket, restricted=ticket.confidentiality == "restricted")
    office = ticket.office
    expires_at = None
    if case == "wrong_office":
        office = Office.objects.create(
            region=basic_world["region"],
            code=f"OTHER-{uuid4().hex[:8]}",
            name="Other assignment office",
        )
    elif case == "wrong_service":
        scope["service"] = str(uuid4())
    elif case == "wrong_queue":
        scope["queue"] = str(uuid4())
    elif case == "expired":
        expires_at = timezone.now() - timedelta(seconds=1)
    elif case == "restricted":
        scope.pop("restricted_only", None)
    _grant(
        target,
        scopes=[scope],
        office=office,
        expires_at=expires_at,
    )
    if case == "auditor":
        _grant(
            target,
            role_key="auditor",
            role_name="Auditor",
            scopes=[{"domain": "audit"}],
        )
    return target


@pytest.mark.parametrize(
    "case",
    [
        "inactive",
        "wrong_office",
        "wrong_service",
        "wrong_queue",
        "wrong_domain",
        "restricted",
        "auditor",
        "expired",
    ],
)
def test_assignment_api_revalidates_forged_target_ids_without_mutation(
    basic_world,
    case,
):
    queue = ServiceLocation.objects.create(
        office=basic_world["office"],
        name=f"Assignment queue {case}",
    )
    ticket = _ticket(
        basic_world,
        queue=queue,
        confidentiality=(
            Ticket.Confidentiality.RESTRICTED
            if case == "restricted"
            else Ticket.Confidentiality.NORMAL
        ),
    )
    actor = _user(["ops-supervisors"])
    target = _ineligible_target(basic_world, ticket, case)
    original_updated_at = ticket.updated_at

    response = _post_assignment(
        _client(actor),
        ticket,
        assignee_id=target.id,
    )

    assert response.status_code == 400
    assert response.data == {
        "code": "invalid_assignment",
        "detail": "Assignment is invalid.",
        "fields": {"assignee_id": ["Select an eligible assignee."]},
        "correlation_id": CORRELATION_ID,
    }
    ticket.refresh_from_db()
    assert ticket.assignee_id is None
    assert ticket.updated_at == original_updated_at
    assert _side_effect_counts(ticket) == (0, 0, 0)


@pytest.mark.parametrize("new_assignee", ["replacement", "unassigned"])
def test_reassignment_and_unassignment_require_reason(basic_world, new_assignee):
    actor = _user(["ops-supervisors"])
    previous = _user(["ops-agents"])
    replacement = _user(["ops-agents"])
    ticket = _ticket(basic_world, assignee=previous)

    response = _post_assignment(
        _client(actor),
        ticket,
        assignee_id=replacement.id if new_assignee == "replacement" else None,
    )

    assert response.status_code == 400
    assert response.data["code"] == "invalid_assignment"
    assert response.data["fields"] == {"reason": ["This field is required."]}
    ticket.refresh_from_db()
    assert ticket.assignee_id == previous.id
    assert _side_effect_counts(ticket) == (0, 0, 0)


def test_assignment_stale_timestamp_returns_current_value(basic_world):
    actor = _user(["ops-supervisors"])
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    stale = ticket.updated_at - timedelta(microseconds=1)

    response = _post_assignment(
        _client(actor),
        ticket,
        assignee_id=target.id,
        expected_updated_at=stale,
    )

    assert response.status_code == 409
    assert response.data["code"] == "stale_ticket"
    assert response.data["detail"] == "The ticket was updated by another user."
    assert parse_datetime(response.data["fields"]["updated_at"][0]) == ticket.updated_at
    assert response.data["correlation_id"] == CORRELATION_ID
    ticket.refresh_from_db()
    assert ticket.assignee_id is None
    assert _side_effect_counts(ticket) == (0, 0, 0)


def test_assignment_hides_out_of_scope_ticket(basic_world):
    actor = _user(["it-leads"])
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world)

    response = _post_assignment(_client(actor), ticket, assignee_id=target.id)

    assert response.status_code == 404
    assert response.data["code"] == "not_found"
    ticket.refresh_from_db()
    assert ticket.assignee_id is None
    assert _side_effect_counts(ticket) == (0, 0, 0)


def test_auditor_cannot_assign_readable_ticket(basic_world):
    auditor = _user(["auditors"])
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world)

    response = _post_assignment(_client(auditor), ticket, assignee_id=target.id)

    assert response.status_code == 403
    assert response.data == {
        "code": "ticket_action_forbidden",
        "detail": "You cannot perform this ticket action.",
        "fields": {},
        "correlation_id": CORRELATION_ID,
    }
    ticket.refresh_from_db()
    assert ticket.assignee_id is None
    assert _side_effect_counts(ticket) == (0, 0, 0)


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"assignee_id": None}, "expected_updated_at"),
        (
            {
                "assignee_id": "not-a-uuid",
                "expected_updated_at": "2026-07-31T10:00:00Z",
            },
            "assignee_id",
        ),
        ({"assignee_id": None, "expected_updated_at": "not-a-date"}, "expected_updated_at"),
        (
            {
                "assignee_id": None,
                "expected_updated_at": "2026-07-31T10:00:00Z",
                "reason": "x" * 1001,
            },
            "reason",
        ),
    ],
)
def test_assignment_validates_request_fields(basic_world, payload, field):
    actor = _user(["ops-supervisors"])
    ticket = _ticket(basic_world)

    response = _client(actor).post(
        _assignment_url(ticket),
        payload,
        format="json",
        HTTP_X_CORRELATION_ID=CORRELATION_ID,
    )

    assert response.status_code == 400
    assert response.data["code"] == "invalid_assignment"
    assert response.data["detail"] == "Assignment is invalid."
    assert field in response.data["fields"]
    assert response.data["correlation_id"] == CORRELATION_ID
    assert _side_effect_counts(ticket) == (0, 0, 0)
