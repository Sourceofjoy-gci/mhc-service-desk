"""Regression tests for ticket mutation and API integrity boundaries."""
from __future__ import annotations

import ast
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.identity_access.models import Role, User, UserRole
from apps.organisations.models import Office
from apps.tickets import services
from apps.tickets.models import OutboxEvent, Ticket, TicketMessage, TicketNote
from apps.tickets.problem_change import ChangeManager, ProblemManager
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db


def _user(groups: list[str], *, active: bool = True) -> User:
    user = User.objects.create(
        username=f"integrity-{uuid4().hex}",
        keycloak_subject=f"integrity-subject-{uuid4().hex}",
        keycloak_groups=groups,
        is_active=active,
    )
    user._groups = groups
    return user


def _ticket(
    basic_world,
    *,
    confidentiality: str = Ticket.Confidentiality.NORMAL,
) -> Ticket:
    service = basic_world["gen_info"]
    return Ticket.objects.create(
        number=f"OP-202607-{Ticket.objects.count() + 970001:06d}",
        domain=Ticket.Domain.OPERATIONAL,
        title="Integrity boundary",
        status=Status.objects.get(domain="operational", code="new"),
        channel=Ticket.Channel.WEB,
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(code="HOURS"),
        office=basic_world["office"],
        confidentiality=confidentiality,
    )


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


_PROTECTED_ALLOCATION_NAMES = frozenset(
    {"assignee", "assignee_id", "queue", "queue_id"}
)


def _enclosing_function_name(
    node: ast.AST,
    parents: dict[ast.AST, ast.AST],
) -> str:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef):
            return current.name
        current = parents.get(current)
    return "<module>"


def _is_reviewed_escalation_assignment(
    *,
    module_name: str,
    function_name: str,
    node: ast.AST,
    target: ast.AST,
) -> bool:
    """Recognise only the reviewed atomic escalation owner mutation."""
    return (
        module_name == "tickets/services.py"
        and function_name == "transition_ticket"
        and isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and target is node.targets[0]
        and isinstance(target, ast.Attribute)
        and target.attr == "assignee"
        and isinstance(target.value, ast.Name)
        and target.value.id == "locked"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "supervisor"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "escalation_plan"
    )


def _allocation_write_violations(
    module_path: Path,
    *,
    apps_root: Path,
    source: str | None = None,
) -> tuple[list[str], int]:
    module_name = module_path.relative_to(apps_root).as_posix()
    tree = ast.parse(
        source if source is not None else module_path.read_text(encoding="utf-8"),
        filename=str(module_path),
    )
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    violations: list[str] = []
    reviewed_writes = 0

    def record(node: ast.AST, kind: str) -> None:
        function_name = _enclosing_function_name(node, parents)
        violations.append(f"{module_name}:{node.lineno}:{function_name}:{kind}")

    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets.extend(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets.append(node.target)
        elif isinstance(node, ast.AugAssign):
            targets.append(node.target)
        for target in targets:
            for nested in ast.walk(target):
                if not (
                    isinstance(nested, ast.Attribute)
                    and nested.attr in _PROTECTED_ALLOCATION_NAMES
                ):
                    continue
                function_name = _enclosing_function_name(node, parents)
                if _is_reviewed_escalation_assignment(
                    module_name=module_name,
                    function_name=function_name,
                    node=node,
                    target=nested,
                ):
                    reviewed_writes += 1
                else:
                    record(node, nested.attr)

        if not isinstance(node, ast.Call):
            continue
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in _PROTECTED_ALLOCATION_NAMES
        ):
            record(node, "setattr")
        if isinstance(node.func, ast.Attribute) and node.func.attr == "update":
            for keyword in node.keywords:
                if keyword.arg in _PROTECTED_ALLOCATION_NAMES:
                    record(node, f"update({keyword.arg})")
        if isinstance(node.func, ast.Attribute) and node.func.attr == "save":
            update_fields = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "update_fields"),
                None,
            )
            if isinstance(update_fields, ast.List | ast.Tuple | ast.Set):
                names = {
                    element.value
                    for element in update_fields.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                }
                for protected in sorted(names & _PROTECTED_ALLOCATION_NAMES):
                    record(node, f"save({protected})")

    return violations, reviewed_writes


def _update_ticket_reference_with_raw_sql(ticket: Ticket) -> None:
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE ticket SET number = %s WHERE id = %s",
                ["OP-202608-999994", ticket.pk],
            )


def test_ticket_reference_cannot_be_changed_with_model_save(basic_world) -> None:
    ticket = _ticket(basic_world)
    original = ticket.number
    ticket.number = "OP-202608-999991"

    with pytest.raises(ValidationError, match="reference is immutable"):
        ticket.save()

    assert Ticket.objects.get(pk=ticket.pk).number == original


def test_ticket_reference_cannot_be_changed_with_queryset_update(basic_world) -> None:
    ticket = _ticket(basic_world)

    with pytest.raises(ValidationError, match="reference is immutable"):
        Ticket.objects.filter(pk=ticket.pk).update(number="OP-202608-999992")


def test_ticket_reference_cannot_be_changed_with_bulk_update(basic_world) -> None:
    ticket = _ticket(basic_world)
    ticket.number = "OP-202608-999993"

    with pytest.raises(ValidationError, match="reference is immutable"):
        Ticket.objects.bulk_update([ticket], ["number"])


def test_database_rejects_raw_ticket_reference_update(basic_world) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("The immutable reference trigger is PostgreSQL-specific.")
    ticket = _ticket(basic_world)
    original = ticket.number

    with pytest.raises(DatabaseError, match="Ticket reference is immutable"):
        _update_ticket_reference_with_raw_sql(ticket)

    assert Ticket.objects.get(pk=ticket.pk).number == original


def test_ticket_reference_guard_allows_unrelated_ticket_updates(basic_world) -> None:
    ticket = _ticket(basic_world)
    ticket.title = "Still the same reference"

    ticket.save(update_fields=["title", "updated_at"])

    ticket.refresh_from_db()
    assert ticket.title == "Still the same reference"


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_ticket_detail_rejects_inherited_base_mutations_with_405(
    basic_world,
    method: str,
) -> None:
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)

    response = getattr(_client(actor), method)(
        reverse("tickets-detail", args=[ticket.number]),
        {"title": "Lifecycle bypass"},
        format="json",
    )

    assert response.status_code == 405
    ticket.refresh_from_db()
    assert ticket.title == "Integrity boundary"


def test_ticket_collection_does_not_advertise_unsupported_create_route(
    basic_world,
) -> None:
    client = _client(_user(["ops-agents"]))
    response = client.options(reverse("tickets-list"))

    assert response.status_code == 200
    assert "POST" not in response.headers["Allow"]

    create = client.post(
        reverse("tickets-list"),
        {"title": "Unsupported direct creation"},
        format="json",
    )
    assert create.status_code == 405


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {
            "team": "",
            "waiting_reason": "",
            "blocked_reason": "",
            "next_action": "",
            "next_action_at": None,
        },
        {
            "confidentiality": Ticket.Confidentiality.NORMAL,
        },
    ],
)
def test_empty_or_unchanged_work_state_is_a_true_no_op(
    basic_world,
    changes: dict[str, object],
) -> None:
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    previous_updated_at = ticket.updated_at

    updated = services.update_work_state(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        changes=changes,
    )

    assert updated.updated_at == previous_updated_at
    ticket.refresh_from_db()
    assert ticket.updated_at == previous_updated_at
    assert not AuditEvent.objects.filter(
        object_id=str(ticket.id),
        action="ticket.work_state.changed",
    ).exists()
    assert not OutboxEvent.objects.filter(
        aggregate_id=str(ticket.id),
        event_type="ticket.work_state.changed",
    ).exists()


def test_empty_work_state_patch_returns_unchanged_representation(basic_world) -> None:
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    previous_updated_at = ticket.updated_at

    response = _client(actor).patch(
        reverse("tickets-work-state", args=[ticket.number]),
        {"updated_at": ticket.updated_at.isoformat()},
        format="json",
    )

    assert response.status_code == 200
    assert parse_datetime(response.data["updated_at"]) == previous_updated_at
    ticket.refresh_from_db()
    assert ticket.updated_at == previous_updated_at
    assert not AuditEvent.objects.filter(object_id=str(ticket.id)).exists()
    assert not OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).exists()


def test_supported_ticket_boundaries_have_no_direct_post_creation_allocation_writes() -> None:
    """A direct owner/queue mutation would bypass eligibility and custody."""
    assert services.WORK_STATE_FIELDS.isdisjoint(
        {"assignee", "assignee_id", "queue", "queue_id"}
    )
    apps_root = Path(__file__).resolve().parents[2]
    module_paths = (
        apps_root / "tickets" / "services.py",
        apps_root / "tickets" / "it_child.py",
        apps_root / "tickets" / "api.py",
        apps_root / "tickets" / "views.py",
        apps_root / "tickets" / "admin.py",
        apps_root / "automation" / "views.py",
    )
    violations: list[str] = []
    reviewed_writes = 0

    for module_path in module_paths:
        module_violations, module_reviewed_writes = _allocation_write_violations(
            module_path,
            apps_root=apps_root,
        )
        violations.extend(module_violations)
        reviewed_writes += module_reviewed_writes

    assert reviewed_writes == 1
    assert violations == []


def test_allocation_write_guard_detects_unreviewed_boundary_write() -> None:
    """A second direct owner write must not inherit the escalation exception."""
    apps_root = Path(__file__).resolve().parents[2]
    module_path = apps_root / "tickets" / "services.py"
    source = module_path.read_text(encoding="utf-8")
    source += "\n\ndef bypass_allocation(ticket, target):\n    ticket.assignee = target\n"

    violations, reviewed_writes = _allocation_write_violations(
        module_path,
        apps_root=apps_root,
        source=source,
    )

    assert reviewed_writes == 1
    assert len(violations) == 1
    assert violations[0].endswith(":bypass_allocation:assignee")


def test_work_state_revalidates_canonical_scope_when_ticket_moves_after_read(
    basic_world,
) -> None:
    actor = _user(["ops-agents"])
    role = Role.objects.create(
        keycloak_role="agent-operational",
        name="Office-scoped operational agent",
        scopes=[],
    )
    UserRole.objects.create(user=actor, role=role, office=basic_world["office"])
    ticket = _ticket(basic_world)
    previous_updated_at = ticket.updated_at
    other_office = Office.objects.create(
        region=basic_world["region"],
        code="INT-OTHER",
        name="Other integrity office",
    )
    Ticket.objects.filter(id=ticket.id).update(office=other_office)

    with pytest.raises(services.TicketScopeError):
        services.update_work_state(
            ticket_id=ticket.id,
            actor=actor,
            expected_updated_at=previous_updated_at,
            changes={"team": "Must not cross scope"},
        )

    ticket.refresh_from_db()
    assert ticket.office == other_office
    assert ticket.team == ""
    assert ticket.updated_at == previous_updated_at
    assert not AuditEvent.objects.filter(object_id=str(ticket.id)).exists()
    assert not OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).exists()


@pytest.mark.parametrize("content_kind", ["message", "note"])
@pytest.mark.parametrize("scope_change", ["office", "domain", "restricted"])
def test_content_mutation_revalidates_scope_after_pre_read(
    basic_world,
    content_kind: str,
    scope_change: str,
) -> None:
    actor = _user(["ops-agents"])
    role = Role.objects.create(
        keycloak_role="agent-operational",
        name="Office-scoped content agent",
        scopes=[],
    )
    UserRole.objects.create(user=actor, role=role, office=basic_world["office"])
    ticket = _ticket(basic_world)
    if scope_change == "office":
        other_office = Office.objects.create(
            region=basic_world["region"],
            code="CONTENT-OTHER",
            name="Other content office",
        )
        Ticket.objects.filter(id=ticket.id).update(office=other_office)
    elif scope_change == "domain":
        Ticket.objects.filter(id=ticket.id).update(domain=Ticket.Domain.IT)
    else:
        Ticket.objects.filter(id=ticket.id).update(
            confidentiality=Ticket.Confidentiality.RESTRICTED
        )

    if content_kind == "message":
        def mutate() -> object:
            return services.add_message(
                ticket=ticket,
                actor=actor,
                direction=TicketMessage.Direction.OUTBOUND,
                actor_subject=actor.keycloak_subject,
                body_text="Must not cross canonical scope",
            )
    else:
        def mutate() -> object:
            return services.add_internal_note(
                ticket=ticket,
                actor=actor,
                body="Must not cross canonical scope",
                author_subject=actor.keycloak_subject,
            )

    with pytest.raises(services.TicketScopeError):
        mutate()

    assert not TicketMessage.objects.filter(ticket=ticket).exists()
    assert not TicketNote.objects.filter(ticket=ticket).exists()
    assert not AuditEvent.objects.filter(object_id=str(ticket.id)).exists()
    assert not OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).exists()


@pytest.mark.parametrize(
    ("groups", "active", "confidentiality", "allowed"),
    [
        (["ops-agents"], True, Ticket.Confidentiality.NORMAL, True),
        (["ops-supervisors"], True, Ticket.Confidentiality.NORMAL, True),
        (["system-admins"], True, Ticket.Confidentiality.NORMAL, True),
        (["auditors"], True, Ticket.Confidentiality.NORMAL, False),
        (["security-responders"], True, Ticket.Confidentiality.RESTRICTED, False),
    ],
)
def test_detail_exposes_authoritative_content_mutation_capabilities(
    basic_world,
    groups: list[str],
    active: bool,
    confidentiality: str,
    allowed: bool,
) -> None:
    actor = _user(groups, active=active)
    ticket = _ticket(basic_world, confidentiality=confidentiality)

    response = _client(actor).get(reverse("tickets-detail", args=[ticket.number]))

    assert response.status_code == 200
    capabilities = response.data["capabilities"]
    assert capabilities["can_add_message"] is allowed
    assert capabilities["can_add_note"] is allowed
    assert capabilities["can_upload_attachment"] is allowed


@pytest.mark.parametrize(
    ("groups", "active", "confidentiality", "route_name", "payload", "model"),
    [
        (
            ["ops-agents"],
            False,
            Ticket.Confidentiality.NORMAL,
            "tickets-messages",
            {"body_text": "inactive mutation"},
            TicketMessage,
        ),
        (
            ["security-responders"],
            True,
            Ticket.Confidentiality.RESTRICTED,
            "tickets-notes",
            {"body": "read-only responder mutation"},
            TicketNote,
        ),
    ],
)
def test_no_mutation_actor_cannot_add_ticket_content(
    basic_world,
    groups: list[str],
    active: bool,
    confidentiality: str,
    route_name: str,
    payload: dict[str, str],
    model: type[TicketMessage] | type[TicketNote],
) -> None:
    actor = _user(groups, active=active)
    ticket = _ticket(basic_world, confidentiality=confidentiality)

    response = _client(actor).post(
        reverse(route_name, args=[ticket.number]),
        payload,
        format="json",
    )

    assert response.status_code == 403
    assert not model.objects.filter(ticket=ticket).exists()
    assert not AuditEvent.objects.filter(object_id=str(ticket.id)).exists()
    assert not OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).exists()


@pytest.mark.parametrize(
    ("route_name", "payload", "model", "event_type"),
    [
        (
            "tickets-messages",
            {"body_text": "Scoped requester update"},
            TicketMessage,
            "ticket.message.created",
        ),
        (
            "tickets-notes",
            {"body": "Scoped internal note"},
            TicketNote,
            "ticket.note.created",
        ),
    ],
)
def test_scoped_actor_can_add_ticket_content_through_api(
    basic_world,
    route_name: str,
    payload: dict[str, str],
    model: type[TicketMessage] | type[TicketNote],
    event_type: str,
) -> None:
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)

    response = _client(actor).post(
        reverse(route_name, args=[ticket.number]),
        payload,
        format="json",
    )

    assert response.status_code == 201
    assert model.objects.filter(ticket=ticket).count() == 1
    audit = AuditEvent.objects.get(object_id=str(ticket.id), action=event_type)
    assert OutboxEvent.objects.filter(
        aggregate_id=str(ticket.id),
        event_type=event_type,
        payload=audit.payload,
    ).count() == 1


@pytest.mark.parametrize(
    ("open_record", "expected_tags", "expected_custom_fields"),
    [
        (
            lambda: ProblemManager.open_problem(
                title="Repeated outage",
                description="Investigate recurrence",
                opened_by="problem-manager",
            ),
            ["problem"],
            {},
        ),
        (
            lambda: ChangeManager.open_change(
                title="Upgrade network",
                description="Apply the approved maintenance release",
                scheduled_at=datetime(2026, 8, 1, 20, 0, tzinfo=UTC),
                risk="medium",
                opened_by="change-manager",
            ),
            ["change", "risk:medium"],
            {
                "scheduled_at": "2026-08-01T20:00:00+00:00",
                "risk": "medium",
            },
        ),
    ],
)
def test_problem_and_change_configuration_is_part_of_canonical_creation_event(
    basic_world,
    open_record: Callable[[], Ticket],
    expected_tags: list[str],
    expected_custom_fields: dict[str, str],
) -> None:
    ticket = open_record()

    audit = AuditEvent.objects.get(
        object_id=str(ticket.id),
        action="ticket.created",
    )
    outbox = OutboxEvent.objects.get(
        aggregate_id=str(ticket.id),
        event_type="ticket.created",
    )
    assert ticket.tags == expected_tags
    assert ticket.custom_fields == expected_custom_fields
    assert audit.payload == outbox.payload
    assert audit.payload["after"]["tags"] == expected_tags
    if expected_custom_fields:
        assert audit.payload["after"]["custom_fields"] == expected_custom_fields
    else:
        assert "custom_fields" not in audit.payload["after"]
