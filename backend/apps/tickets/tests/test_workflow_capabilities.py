from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib.auth.models import Group
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.identity_access.models import Role, User, UserRole
from apps.identity_access.scope import get_authority_snapshot
from apps.organisations.models import Office, ServiceLocation
from apps.tickets import services
from apps.tickets.api import TicketDetailSerializer, TicketListSerializer
from apps.tickets.eligibility import matching_actor_role_aliases
from apps.tickets.models import OutboxEvent, Ticket, TicketCustodyEvent
from apps.tickets.workflow import available_transitions
from apps.workflow.models import Status, Transition, TransitionHistory

pytestmark = pytest.mark.django_db

DESIGNATION_KEYS = (
    "master",
    "deputy-master",
    "assistant-master",
    "assistant-accountant",
    "accountant",
    "senior-accountant",
    "principal-accountant",
    "financial-controller",
    "estate-examiner",
    "records-clerk",
    "data-clerk",
)


def _user(groups: list[str]) -> User:
    user = User.objects.create(
        username=f"agent-{uuid4().hex}",
        keycloak_subject=f"subject-{uuid4().hex}",
        keycloak_groups=groups,
    )
    user._groups = groups
    return user


def _ticket(basic_world, *, domain: str = "operational", status_code: str = "new"):
    service = basic_world["gen_info"] if domain == "operational" else basic_world["it_inc"]
    prefix = "OP" if domain == "operational" else "IT"
    return Ticket.objects.create(
        number=f"{prefix}-202607-{Ticket.objects.count() + 930001:06d}",
        domain=domain,
        title="Workflow capability",
        status=Status.objects.get(domain=domain, code=status_code),
        channel="web",
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
    )


def _context(user: User):
    return {"request": SimpleNamespace(user=user)}


def _assert_denied_without_side_effects(
    ticket: Ticket,
    actor: User,
    *,
    snapshot=None,
) -> None:
    previous_updated_at = ticket.updated_at
    history_count = TransitionHistory.objects.filter(ticket=ticket).count()
    audit_count = AuditEvent.objects.filter(object_id=str(ticket.id)).count()
    outbox_count = OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).count()
    custody_count = TicketCustodyEvent.objects.filter(ticket=ticket).count()

    with pytest.raises(services.TicketPermissionError):
        services.transition_ticket(
            ticket_id=ticket.id,
            actor=actor,
            snapshot=snapshot,
            expected_updated_at=ticket.updated_at,
            to_status_code="triage",
        )

    ticket.refresh_from_db()
    assert ticket.status.code == "new"
    assert ticket.updated_at == previous_updated_at
    assert TransitionHistory.objects.filter(ticket=ticket).count() == history_count
    assert AuditEvent.objects.filter(object_id=str(ticket.id)).count() == audit_count
    assert OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).count() == outbox_count
    assert TicketCustodyEvent.objects.filter(ticket=ticket).count() == custody_count


@pytest.mark.parametrize("domain", ["operational", "it"])
def test_available_transitions_only_returns_active_moves_from_current_status(
    basic_world,
    domain,
):
    actor = _user(["ops-agents"] if domain == "operational" else ["it-agents"])
    ticket = _ticket(basic_world, domain=domain)
    expected = Transition.objects.get(
        domain=domain,
        from_status=ticket.status,
        to_status__code="triage",
    )
    Transition.objects.filter(domain=domain).exclude(id=expected.id).update(is_active=False)

    result = available_transitions(ticket, actor)

    assert list(result) == [expected]
    expected.is_active = False
    expected.save(update_fields=["is_active"])
    assert not available_transitions(ticket, actor).exists()


def test_required_role_hides_transition_but_administrators_bypass_it(basic_world):
    ticket = _ticket(basic_world)
    transition = Transition.objects.get(
        domain=ticket.domain,
        from_status=ticket.status,
        to_status__code="triage",
    )
    transition.required_role = "ops-supervisors"
    transition.save(update_fields=["required_role"])

    assert not available_transitions(ticket, _user(["ops-agents"])).exists()
    assert available_transitions(ticket, _user(["ops-supervisors"])).get() == transition
    assert available_transitions(ticket, _user(["system-admins"])).get() == transition


@pytest.mark.parametrize("role_key", DESIGNATION_KEYS)
def test_exact_scope_designation_executes_ordinary_agent_transition_and_note(
    basic_world,
    role_key,
):
    actor = _user([])
    role = Role.objects.create(
        keycloak_role=role_key,
        name=role_key.replace("-", " ").title(),
        scopes=[
            {
                "domain": "operational",
                "office": str(basic_world["office"].id),
                "service": str(basic_world["gen_info"].id),
            }
        ],
    )
    UserRole.objects.create(user=actor, role=role, office=basic_world["office"])
    ticket = _ticket(basic_world)
    transition = Transition.objects.get(
        domain=ticket.domain,
        from_status=ticket.status,
        to_status__code="triage",
    )
    transition.required_role = "ops-agents"
    transition.save(update_fields=["required_role"])

    assert available_transitions(ticket, actor).get() == transition
    note = services.add_internal_note(
        ticket=ticket,
        body="Internal designation note",
        author_subject=actor.keycloak_subject,
        actor=actor,
    )
    assert note.ticket_id == ticket.id
    updated = services.transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        to_status_code="triage",
    )
    assert updated.status.code == "triage"


@pytest.mark.parametrize("dimension", ["domain", "office", "service", "queue"])
def test_designation_workflow_is_denied_for_mismatched_exact_scope(
    basic_world,
    dimension,
):
    ticket = _ticket(basic_world)
    queue = ServiceLocation.objects.create(
        office=ticket.office,
        name=f"Ticket queue {uuid4().hex}",
    )
    ticket.queue = queue
    ticket.save(update_fields=["queue"])
    scope = {
        "domain": ticket.domain,
        "office": str(ticket.office_id),
        "service": str(ticket.service_id),
        "queue": str(ticket.queue_id),
    }
    if dimension == "domain":
        scope["domain"] = "it"
    else:
        scope[dimension] = str(uuid4())
    actor = _user([])
    role = Role.objects.create(
        keycloak_role="estate-examiner",
        name="Estate Examiner",
        scopes=[scope],
    )
    UserRole.objects.create(user=actor, role=role)

    assert not available_transitions(ticket, actor).exists()
    _assert_denied_without_side_effects(ticket, actor)


def test_designation_requires_matching_restricted_visibility_for_workflow(basic_world):
    ticket = _ticket(basic_world)
    ticket.confidentiality = Ticket.Confidentiality.RESTRICTED
    ticket.save(update_fields=["confidentiality"])
    actor = _user([])
    role = Role.objects.create(
        keycloak_role="estate-examiner",
        name="Estate Examiner",
        scopes=[{"domain": "operational"}],
    )
    UserRole.objects.create(user=actor, role=role)

    assert not available_transitions(ticket, actor).exists()
    _assert_denied_without_side_effects(ticket, actor)


def test_functional_designation_with_separate_restricted_visibility_can_act(
    basic_world,
):
    ticket = _ticket(basic_world)
    ticket.confidentiality = Ticket.Confidentiality.RESTRICTED
    ticket.save(update_fields=["confidentiality"])
    actor = _user([])
    functional_role = Role.objects.create(
        keycloak_role="estate-examiner",
        name="Custom Estate Specialist",
        scopes=[
            {
                "domain": ticket.domain,
                "office": str(ticket.office_id),
                "service": str(ticket.service_id),
            }
        ],
    )
    restricted_role = Role.objects.create(
        keycloak_role="security-responders",
        name="Restricted Visibility",
        scopes=[
            {
                "domain": ticket.domain,
                "office": str(ticket.office_id),
                "service": str(ticket.service_id),
                "restricted_only": True,
            }
        ],
    )
    UserRole.objects.create(user=actor, role=functional_role, office=ticket.office)
    UserRole.objects.create(user=actor, role=restricted_role, office=ticket.office)
    transition = Transition.objects.get(
        domain=ticket.domain,
        from_status=ticket.status,
        to_status__code="triage",
    )
    transition.required_role = "ops-agents"
    transition.save(update_fields=["required_role"])

    assert available_transitions(ticket, actor).get() == transition
    note = services.add_internal_note(
        ticket=ticket,
        body="Restricted functional work note",
        author_subject=actor.keycloak_subject,
        actor=actor,
    )
    assert note.ticket_id == ticket.id
    updated = services.transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        to_status_code="triage",
    )
    assert updated.status.code == "triage"


@pytest.mark.parametrize(
    ("ticket_domain", "role_key", "required_role"),
    [
        (Ticket.Domain.OPERATIONAL, "lead-it", "it-leads"),
        (Ticket.Domain.IT, "supervisor-operational", "ops-supervisors"),
    ],
)
def test_legacy_actor_role_family_cannot_cross_domains_through_configured_scope(
    basic_world,
    ticket_domain,
    role_key,
    required_role,
):
    ticket = _ticket(basic_world, domain=ticket_domain)
    actor = _user([])
    role = Role.objects.create(
        keycloak_role=role_key,
        name=f"Mis-scoped {role_key}",
        scopes=[
            {
                "domain": ticket.domain,
                "office": str(ticket.office_id),
                "service": str(ticket.service_id),
            }
        ],
    )
    UserRole.objects.create(user=actor, role=role, office=ticket.office)
    transition = Transition.objects.get(
        domain=ticket.domain,
        from_status=ticket.status,
        to_status__code="triage",
    )
    transition.required_role = required_role
    transition.save(update_fields=["required_role"])

    assert not available_transitions(ticket, actor).exists()
    _assert_denied_without_side_effects(ticket, actor)


@pytest.mark.parametrize(
    ("authority_role", "domain", "required_role"),
    [
        ("supervisor-operational", "operational", "ops-supervisors"),
        ("lead-it", "it", "it-leads"),
        ("admin", "operational", "private-required-role"),
    ],
)
def test_privileged_transition_cannot_borrow_scope_from_designation(
    basic_world,
    authority_role,
    domain,
    required_role,
):
    actor = _user([])
    ticket = _ticket(basic_world, domain=domain)
    other_office = Office.objects.create(
        region=basic_world["region"],
        code=f"OTHER-{uuid4().hex[:8]}",
        name="Other workflow office",
    )
    designation = Role.objects.create(
        keycloak_role="estate-examiner",
        name="Estate Examiner",
        scopes=[
            {
                "domain": domain,
                "office": str(ticket.office_id),
                "service": str(ticket.service_id),
            }
        ],
    )
    authority = Role.objects.create(
        keycloak_role=authority_role,
        name=authority_role,
        scopes=[
            {
                "domain": "admin" if authority_role == "admin" else domain,
                "office": str(other_office.id),
            }
        ],
    )
    UserRole.objects.create(user=actor, role=designation, office=ticket.office)
    UserRole.objects.create(user=actor, role=authority, office=other_office)
    transition = Transition.objects.get(
        domain=domain,
        from_status=ticket.status,
        to_status__code="triage",
    )
    transition.required_role = required_role
    transition.save(update_fields=["required_role"])

    assert not available_transitions(ticket, actor).exists()


def test_persisted_designation_suppresses_stale_supervisor_transition_group(
    basic_world,
):
    actor = _user(["ops-supervisors"])
    ticket = _ticket(basic_world)
    designation = Role.objects.create(
        keycloak_role="estate-examiner",
        name="Estate Examiner",
        scopes=[{"domain": "operational"}],
    )
    UserRole.objects.create(user=actor, role=designation)
    transition = Transition.objects.get(
        domain=ticket.domain,
        from_status=ticket.status,
        to_status__code="triage",
    )
    transition.required_role = "ops-supervisors"
    transition.save(update_fields=["required_role"])

    assert not available_transitions(ticket, actor).exists()


@pytest.mark.parametrize("mutation", ["add", "delete"])
def test_cached_snapshot_freezes_supervisor_workflow_alias(
    basic_world,
    mutation,
):
    actor = _user([])
    ticket = _ticket(basic_world)
    designation = Role.objects.create(
        keycloak_role="estate-examiner",
        name="Estate Examiner",
        scopes=[{"domain": "operational"}],
    )
    UserRole.objects.create(user=actor, role=designation)
    supervisor = Role.objects.create(
        keycloak_role="supervisor-operational",
        name="Operational Supervisor",
        scopes=[{"domain": "operational"}],
    )
    assignment = None
    if mutation == "delete":
        assignment = UserRole.objects.create(user=actor, role=supervisor)
    request = SimpleNamespace(user=actor)
    get_authority_snapshot(actor, request=request)
    if mutation == "add":
        UserRole.objects.create(user=actor, role=supervisor)
    else:
        assert assignment is not None
        assignment.delete()
    transition = Transition.objects.get(
        domain=ticket.domain,
        from_status=ticket.status,
        to_status__code="triage",
    )
    transition.required_role = "ops-supervisors"
    transition.save(update_fields=["required_role"])

    expected_cached = mutation == "delete"
    assert (
        available_transitions(ticket, actor, request=request).exists()
        is expected_cached
    )
    assert available_transitions(ticket, actor).exists() is (not expected_cached)


@pytest.mark.parametrize("group_source", ["keycloak", "django"])
def test_reloaded_expired_role_actor_gets_durable_workflow_fallback(
    basic_world,
    group_source,
):
    actor = _user([])
    if group_source == "keycloak":
        actor.keycloak_groups = ["ops-agents"]
        actor.save(update_fields=["keycloak_groups"])
    else:
        from django.contrib.auth.models import Group

        actor.groups.add(Group.objects.create(name="ops-agents"))
    expired = Role.objects.create(
        keycloak_role="estate-examiner",
        name="Estate Examiner",
        scopes=[{"domain": "it"}],
    )
    UserRole.objects.create(
        user=actor,
        role=expired,
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    ticket = _ticket(basic_world)
    transition = Transition.objects.get(
        domain=ticket.domain,
        from_status=ticket.status,
        to_status__code="triage",
    )
    transition.required_role = "ops-agents"
    transition.save(update_fields=["required_role"])

    reloaded = User.objects.get(pk=actor.pk)

    assert available_transitions(ticket, reloaded).exists()


def test_persisted_auditor_has_no_transitions_despite_mutable_group_snapshot(basic_world):
    ticket = _ticket(basic_world)
    actor = _user(["ops-supervisors"])
    role = Role.objects.create(keycloak_role="auditors", name="Auditor")
    UserRole.objects.create(user=actor, role=role)

    assert not available_transitions(ticket, actor).exists()


@pytest.mark.parametrize(
    ("groups", "active"),
    [(["auditors"], True), (["it-agents"], True), (["ops-agents"], False)],
)
def test_read_only_cross_domain_and_inactive_actors_have_no_transitions(
    basic_world,
    groups,
    active,
):
    ticket = _ticket(basic_world)
    actor = _user(groups)
    actor.is_active = active
    actor.save(update_fields=["is_active"])

    assert not available_transitions(ticket, actor).exists()


def test_detail_serializes_resolution_requirements_and_list_serializes_codes(basic_world):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world, status_code="in_progress")
    Transition.objects.filter(
        domain=ticket.domain,
        from_status=ticket.status,
    ).exclude(to_status__code="resolved").update(is_active=False)

    detail = TicketDetailSerializer(ticket, context=_context(actor)).data
    listing = TicketListSerializer(ticket, context=_context(actor)).data

    assert detail["available_transitions"] == [
        {
            "to_status": "resolved",
            "label": "Resolve",
            "requires_resolution": True,
            "requires_reason": False,
        },
    ]
    assert listing["available_transition_codes"] == [
        item["to_status"] for item in detail["available_transitions"]
    ]


def test_required_fields_reason_is_exposed_as_requirement(basic_world):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    transition = Transition.objects.get(
        domain=ticket.domain,
        from_status=ticket.status,
        to_status__code="triage",
    )
    transition.required_fields = ["reason"]
    transition.save(update_fields=["required_fields"])

    detail = TicketDetailSerializer(ticket, context=_context(actor)).data

    assert detail["available_transitions"] == [
        {
            "to_status": "triage",
            "label": "Begin triage",
            "requires_resolution": False,
            "requires_reason": True,
        }
    ]


def test_persisted_operational_scope_denies_conflicting_it_group_direct_service(
    basic_world,
):
    actor = _user(["it-agents"])
    operational_role = Role.objects.get(keycloak_role="ops-agents")
    UserRole.objects.create(user=actor, role=operational_role)
    ticket = _ticket(basic_world, domain="it")
    previous_updated_at = ticket.updated_at

    assert not available_transitions(ticket, actor).exists()
    with pytest.raises(services.TicketPermissionError):
        services.transition_ticket(
            ticket_id=ticket.id,
            actor=actor,
            expected_updated_at=ticket.updated_at,
            to_status_code="triage",
        )

    ticket.refresh_from_db()
    assert ticket.status.code == "new"
    assert ticket.updated_at == previous_updated_at
    assert not TransitionHistory.objects.filter(ticket=ticket).exists()
    assert not AuditEvent.objects.filter(object_id=str(ticket.id)).exists()
    assert not OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).exists()


@pytest.mark.parametrize("dimension", ["office", "service", "queue"])
def test_persisted_ticket_dimensions_are_enforced_before_required_roles(
    basic_world,
    dimension,
):
    actor = _user(["ops-supervisors"])
    role = Role.objects.create(
        keycloak_role=f"scoped-{dimension}",
        name=f"Scoped {dimension}",
        scopes=[{"domain": "operational", dimension: str(uuid4())}],
    )
    UserRole.objects.create(user=actor, role=role)
    ticket = _ticket(basic_world)
    transition = Transition.objects.get(
        domain=ticket.domain,
        from_status=ticket.status,
        to_status__code="triage",
    )
    transition.required_role = "ops-supervisors"
    transition.save(update_fields=["required_role"])

    assert not available_transitions(ticket, actor).exists()


def test_matching_persisted_scope_and_restricted_boundaries_are_enforced(basic_world):
    regular = _user(["ops-agents"])
    regular_role = Role.objects.get(keycloak_role="ops-agents")
    UserRole.objects.create(user=regular, role=regular_role)
    restricted = _ticket(basic_world)
    restricted.confidentiality = Ticket.Confidentiality.RESTRICTED
    restricted.save(update_fields=["confidentiality"])

    assert not available_transitions(restricted, regular).exists()

    supervisor = _user(["ops-supervisors"])
    supervisor_role = Role.objects.create(
        keycloak_role="ops-supervisors",
        name="Operational supervisor",
    )
    UserRole.objects.create(user=supervisor, role=supervisor_role)
    assert available_transitions(restricted, supervisor).exists()

    responder = _user(["security-responders"])
    responder_role = Role.objects.create(
        keycloak_role="security-responders",
        name="Security responder",
    )
    UserRole.objects.create(user=responder, role=responder_role)
    normal = _ticket(basic_world)
    assert not available_transitions(normal, responder).exists()
    assert not available_transitions(restricted, responder).exists()
    _assert_denied_without_side_effects(restricted, responder)


def test_explicit_immutable_snapshot_can_be_shared_by_capability_and_execution(
    basic_world,
):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    snapshot = get_authority_snapshot(actor)

    assert available_transitions(ticket, actor, snapshot=snapshot).exists()
    updated = services.transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        snapshot=snapshot,
        expected_updated_at=ticket.updated_at,
        to_status_code="triage",
    )
    assert updated.status.code == "triage"


def test_cached_auditor_snapshot_stays_denied_after_assignment_is_removed(basic_world):
    actor = _user(["ops-agents"])
    auditor_role = Role.objects.create(keycloak_role="auditors", name="Auditor")
    assignment = UserRole.objects.create(user=actor, role=auditor_role)
    ticket = _ticket(basic_world)
    request = SimpleNamespace(user=actor)
    snapshot = get_authority_snapshot(actor, request=request)
    assignment.delete()

    listing = TicketListSerializer(ticket, context={"request": request}).data
    detail = TicketDetailSerializer(ticket, context={"request": request}).data

    assert "auditor" in snapshot.capabilities
    assert listing["available_transition_codes"] == []
    assert detail["available_transitions"] == []
    with pytest.raises(services.TicketPermissionError):
        services.transition_ticket(
            ticket_id=ticket.id,
            actor=actor,
            request=request,
            expected_updated_at=ticket.updated_at,
            to_status_code="triage",
        )


def test_new_auditor_identity_denies_even_when_operator_scope_snapshot_is_cached(
    basic_world,
):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    request = SimpleNamespace(user=actor)
    snapshot = get_authority_snapshot(actor, request=request)
    auditor_role = Role.objects.create(keycloak_role="auditors", name="Auditor")
    UserRole.objects.create(user=actor, role=auditor_role)

    listing = TicketListSerializer(ticket, context={"request": request}).data
    detail = TicketDetailSerializer(ticket, context={"request": request}).data

    assert "auditor" not in snapshot.capabilities
    assert listing["available_transition_codes"] == []
    assert detail["available_transitions"] == []
    _assert_denied_without_side_effects(ticket, actor)


@pytest.mark.parametrize(
    "auditor_source",
    ["persisted-role", "django-group", "keycloak-group", "request-group"],
)
def test_old_operator_snapshot_cannot_bypass_fresh_auditor_deny(
    basic_world,
    auditor_source,
):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    snapshot = get_authority_snapshot(actor)

    if auditor_source == "persisted-role":
        auditor_role = Role.objects.create(keycloak_role="auditors", name="Auditor")
        UserRole.objects.create(user=actor, role=auditor_role)
    elif auditor_source == "django-group":
        actor.groups.add(Group.objects.create(name="auditors"))
    elif auditor_source == "keycloak-group":
        User.objects.filter(pk=actor.pk).update(
            keycloak_groups=["ops-agents", "auditors"]
        )
    else:
        actor._groups = ["ops-agents", "auditors"]

    assert not available_transitions(ticket, actor, snapshot=snapshot).exists()
    assert not matching_actor_role_aliases(ticket, actor, snapshot=snapshot)
    _assert_denied_without_side_effects(ticket, actor, snapshot=snapshot)


def test_old_snapshot_remains_invariant_for_non_auditor_authority_changes(
    basic_world,
):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    snapshot = get_authority_snapshot(actor)
    it_role = Role.objects.create(
        keycloak_role="lead-it",
        name="IT lead",
        scopes=[{"domain": "it"}],
    )
    UserRole.objects.create(user=actor, role=it_role)

    assert available_transitions(ticket, actor, snapshot=snapshot).exists()
    updated = services.transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        snapshot=snapshot,
        expected_updated_at=ticket.updated_at,
        to_status_code="triage",
    )

    assert updated.status.code == "triage"


@pytest.mark.parametrize("dimension", ["office", "service", "queue"])
def test_persisted_admin_scope_honors_matching_and_nonmatching_dimensions(
    basic_world,
    dimension,
):
    ticket = _ticket(basic_world)
    if dimension == "queue":
        ticket.queue = ServiceLocation.objects.create(
            office=ticket.office,
            name="Workflow queue",
        )
        ticket.save(update_fields=["queue"])
    matching_id = str(getattr(ticket, f"{dimension}_id"))
    transition = Transition.objects.get(
        domain=ticket.domain,
        from_status=ticket.status,
        to_status__code="triage",
    )
    transition.required_role = "it-leads"
    transition.save(update_fields=["required_role"])

    matching_actor = _user(["ops-agents"])
    matching_role = Role.objects.create(
        keycloak_role=f"admin-matching-{dimension}",
        name=f"Matching admin {dimension}",
        scopes=[{"domain": "admin", dimension: matching_id}],
    )
    UserRole.objects.create(user=matching_actor, role=matching_role)
    assert available_transitions(ticket, matching_actor).exists()

    denied_actor = _user(["ops-agents"])
    denied_role = Role.objects.create(
        keycloak_role=f"admin-other-{dimension}",
        name=f"Other admin {dimension}",
        scopes=[{"domain": "admin", dimension: str(uuid4())}],
    )
    UserRole.objects.create(user=denied_actor, role=denied_role)
    assert not available_transitions(ticket, denied_actor).exists()
    _assert_denied_without_side_effects(ticket, denied_actor)


def test_restricted_only_admin_scope_denies_normal_and_allows_restricted_ticket(
    basic_world,
):
    actor = _user(["ops-agents"])
    role = Role.objects.create(
        keycloak_role="restricted-only-admin",
        name="Restricted-only admin",
        scopes=[{"domain": "admin", "restricted_only": True}],
    )
    UserRole.objects.create(user=actor, role=role)
    normal = _ticket(basic_world)
    restricted = _ticket(basic_world)
    restricted.confidentiality = Ticket.Confidentiality.RESTRICTED
    restricted.save(update_fields=["confidentiality"])

    assert not available_transitions(normal, actor).exists()
    _assert_denied_without_side_effects(normal, actor)
    assert available_transitions(restricted, actor).exists()


def test_restricted_admin_ticket_requires_exact_branch_restricted_grant(basic_world):
    ticket = _ticket(basic_world)
    ticket.confidentiality = Ticket.Confidentiality.RESTRICTED
    ticket.save(update_fields=["confidentiality"])
    scope = {
        "domain": "admin",
        "office": str(ticket.office_id),
        "service": str(ticket.service_id),
    }

    denied_actor = _user(["ops-agents"])
    denied_role = Role.objects.create(
        keycloak_role="unprivileged-scoped-admin",
        name="Unprivileged scoped admin",
        scopes=[scope],
    )
    UserRole.objects.create(user=denied_actor, role=denied_role)
    assert not available_transitions(ticket, denied_actor).exists()
    _assert_denied_without_side_effects(ticket, denied_actor)

    allowed_actor = _user(["ops-agents"])
    allowed_role = Role.objects.create(
        keycloak_role="admin",
        name="Canonical admin",
        scopes=[scope],
    )
    UserRole.objects.create(user=allowed_actor, role=allowed_role)
    assert available_transitions(ticket, allowed_actor).exists()
