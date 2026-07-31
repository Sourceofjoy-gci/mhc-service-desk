from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib.auth.models import Group
from django.utils import timezone

from apps.identity_access.models import Role, User, UserRole
from apps.identity_access.scope import get_authority_snapshot
from apps.organisations.models import Office, ServiceLocation
from apps.tickets.models import Ticket
from apps.tickets.permissions import (
    can_add_ticket_content,
    can_assign,
    can_change_confidentiality,
    can_reassign,
    can_update_work_state,
    eligible_assignee_queryset,
    user_groups,
)
from apps.workflow.models import Status

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


def _user(*, groups: list[str], active: bool = True) -> User:
    return User.objects.create(
        username=f"agent-{uuid4().hex}",
        keycloak_subject=f"subject-{uuid4().hex}",
        keycloak_groups=groups,
        is_active=active,
    )


@pytest.mark.parametrize(
    ("groups", "can_reassign_expected", "can_confidentiality_expected"),
    [
        (["ops-agents"], False, False),
        (["it-agents"], False, False),
        (["ops-supervisors"], True, True),
        (["it-leads"], True, True),
        (["system-admins"], True, True),
        (["auditors"], False, False),
        (["auditors", "ops-supervisors"], False, False),
    ],
)
def test_elevated_ticket_permissions(
    groups,
    can_reassign_expected,
    can_confidentiality_expected,
):
    user = _user(groups=groups)

    assert can_assign(user) is can_reassign_expected
    assert can_reassign(user) is can_reassign_expected
    assert can_change_confidentiality(user) is can_confidentiality_expected


def test_user_groups_combines_durable_request_and_django_groups():
    user = _user(groups=["ops-agents"])
    user._groups = ["ops-supervisors"]
    django_group = Group.objects.create(name="system-admins")
    user.groups.add(django_group)

    assert user_groups(user) == {
        "ops-agents",
        "ops-supervisors",
        "system-admins",
    }


def test_eligible_assignees_are_active_and_match_ticket_domain(basic_world):
    operational_agent = _user(groups=["ops-agents"])
    operational_supervisor = _user(groups=["ops-supervisors"])
    administrator = _user(groups=["system-admins"])
    _user(groups=["it-agents"])
    _user(groups=["ops-agents"], active=False)
    _user(groups=["auditors"])
    _user(groups=["ops-agents", "auditors"])
    persisted_auditor = _user(groups=["ops-agents"])
    auditor_role = Role.objects.create(keycloak_role="auditors", name="Auditor")
    UserRole.objects.create(user=persisted_auditor, role=auditor_role)
    status = Status.objects.get(domain="operational", code="new")
    ticket = Ticket.objects.create(
        number="OP-202607-900001",
        domain="operational",
        title="Assignment eligibility",
        status=status,
        channel="web",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
    )

    eligible_ids = set(eligible_assignee_queryset(ticket).values_list("id", flat=True))

    assert eligible_ids == {
        operational_agent.id,
        operational_supervisor.id,
    }
    assert administrator.id not in eligible_ids


def test_inactive_elevated_user_has_no_mutating_permissions(basic_world):
    user = _user(groups=["ops-supervisors"], active=False)
    status = Status.objects.get(domain="operational", code="new")
    ticket = Ticket.objects.create(
        number="OP-202607-900002",
        domain="operational",
        title="Inactive permissions",
        status=status,
        channel="web",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
    )

    assert can_reassign(user) is False
    assert can_change_confidentiality(user) is False
    assert can_update_work_state(user, ticket) is False


@pytest.mark.parametrize("role_key", DESIGNATION_KEYS)
def test_each_exact_scope_designation_can_action_but_cannot_assign(
    basic_world,
    role_key,
):
    user = _user(groups=[])
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
    UserRole.objects.create(user=user, role=role, office=basic_world["office"])
    status = Status.objects.get(domain="operational", code="new")
    ticket = Ticket.objects.create(
        number=f"OP-202607-{Ticket.objects.count() + 900100:06d}",
        domain="operational",
        title="Designation permissions",
        status=status,
        channel="internal",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
    )

    assert can_update_work_state(user, ticket) is True
    assert can_add_ticket_content(user, ticket) is True
    assert can_assign(user, ticket=ticket) is False
    assert can_reassign(user, ticket=ticket) is False


@pytest.mark.parametrize(
    ("role_key", "domain"),
    [
        ("supervisor-operational", "operational"),
        ("lead-it", "it"),
    ],
)
def test_persisted_leadership_role_can_assign_without_keycloak_groups(
    basic_world,
    role_key,
    domain,
):
    user = _user(groups=[])
    role = Role.objects.create(
        keycloak_role=role_key,
        name=role_key,
        scopes=[{"domain": domain}],
    )
    UserRole.objects.create(user=user, role=role)
    service = basic_world["gen_info"] if domain == "operational" else basic_world["it_inc"]
    ticket = Ticket.objects.create(
        number=f"{'OP' if domain == 'operational' else 'IT'}-202607-900300",
        domain=domain,
        title="Persisted assignment authority",
        status=Status.objects.get(domain=domain, code="new"),
        channel="internal",
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
    )

    assert can_assign(user, ticket=ticket) is True
    assert can_reassign(user, ticket=ticket) is True


@pytest.mark.parametrize(
    ("authority_role", "domain"),
    [
        ("supervisor-operational", "operational"),
        ("lead-it", "it"),
        ("admin", "operational"),
    ],
)
def test_assignment_authority_cannot_borrow_scope_from_matching_designation(
    basic_world,
    authority_role,
    domain,
):
    user = _user(groups=[])
    other_office = Office.objects.create(
        region=basic_world["region"],
        code=f"OTHER-{uuid4().hex[:8]}",
        name="Other office",
    )
    service = basic_world["gen_info"] if domain == "operational" else basic_world["it_inc"]
    designation = Role.objects.create(
        keycloak_role="estate-examiner",
        name="Estate Examiner",
        scopes=[
            {
                "domain": domain,
                "office": str(basic_world["office"].id),
                "service": str(service.id),
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
    UserRole.objects.create(user=user, role=designation, office=basic_world["office"])
    UserRole.objects.create(user=user, role=authority, office=other_office)
    ticket = Ticket.objects.create(
        number=f"{'OP' if domain == 'operational' else 'IT'}-202607-900400",
        domain=domain,
        title="No scope borrowing",
        status=Status.objects.get(domain=domain, code="new"),
        channel="internal",
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
    )

    assert can_update_work_state(user, ticket) is True
    assert can_assign(user, ticket=ticket) is False


def test_persisted_designation_suppresses_stale_supervisor_group_authority(
    basic_world,
):
    user = _user(groups=["ops-supervisors"])
    designation = Role.objects.create(
        keycloak_role="estate-examiner",
        name="Estate Examiner",
        scopes=[{"domain": "operational"}],
    )
    UserRole.objects.create(user=user, role=designation)
    ticket = Ticket.objects.create(
        number="OP-202607-900500",
        domain="operational",
        title="Persisted precedence",
        status=Status.objects.get(domain="operational", code="new"),
        channel="internal",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
    )

    assert can_update_work_state(user, ticket) is True
    assert can_assign(user, ticket=ticket) is False


def test_expired_role_restores_legacy_supervisor_actor_fallback(basic_world):
    user = _user(groups=["ops-supervisors"])
    expired = Role.objects.create(
        keycloak_role="estate-examiner",
        name="Estate Examiner",
        scopes=[{"domain": "it"}],
    )
    UserRole.objects.create(
        user=user,
        role=expired,
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    ticket = Ticket.objects.create(
        number="OP-202607-900600",
        domain="operational",
        title="Expired persisted role",
        status=Status.objects.get(domain="operational", code="new"),
        channel="internal",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
    )

    assert can_assign(user, ticket=ticket) is True


def test_active_invalid_role_suppresses_legacy_supervisor_actor_fallback(basic_world):
    user = _user(groups=["ops-supervisors"])
    invalid = Role.objects.create(
        keycloak_role="invalid-role",
        name="Invalid role",
        scopes={"domain": "operational"},
    )
    UserRole.objects.create(user=user, role=invalid)
    ticket = Ticket.objects.create(
        number="OP-202607-900700",
        domain="operational",
        title="Invalid persisted role",
        status=Status.objects.get(domain="operational", code="new"),
        channel="internal",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
    )

    assert can_assign(user, ticket=ticket) is False


def test_cached_auditor_snapshot_remains_a_permission_denial_after_role_removal(
    basic_world,
):
    user = _user(groups=["ops-agents"])
    auditor = Role.objects.create(
        keycloak_role="auditor",
        name="Auditor",
        scopes=[{"domain": "operational"}],
    )
    assignment = UserRole.objects.create(user=user, role=auditor)
    request = SimpleNamespace(user=user)
    get_authority_snapshot(user, request=request)
    assignment.delete()
    ticket = Ticket.objects.create(
        number="OP-202607-900800",
        domain="operational",
        title="Cached auditor boundary",
        status=Status.objects.get(domain="operational", code="new"),
        channel="internal",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
    )

    assert can_update_work_state(user, ticket, request=request) is False


@pytest.mark.parametrize(
    ("authority_role", "domain"),
    [
        ("supervisor-operational", "operational"),
        ("lead-it", "it"),
        ("admin", "operational"),
    ],
)
@pytest.mark.parametrize("mutation", ["add", "delete"])
def test_cached_snapshot_freezes_scope_bound_assignment_roles(
    basic_world,
    authority_role,
    domain,
    mutation,
):
    user = _user(groups=[])
    service = basic_world["gen_info"] if domain == "operational" else basic_world["it_inc"]
    designation = Role.objects.create(
        keycloak_role="estate-examiner",
        name="Estate Examiner",
        scopes=[
            {
                "domain": domain,
                "office": str(basic_world["office"].id),
                "service": str(service.id),
            }
        ],
    )
    UserRole.objects.create(
        user=user,
        role=designation,
        office=basic_world["office"],
    )
    authority = Role.objects.create(
        keycloak_role=authority_role,
        name=authority_role,
        scopes=[
            {
                "domain": "admin" if authority_role == "admin" else domain,
                "office": str(basic_world["office"].id),
                "service": str(service.id),
            }
        ],
    )
    authority_assignment = None
    if mutation == "delete":
        authority_assignment = UserRole.objects.create(
            user=user,
            role=authority,
            office=basic_world["office"],
        )
    request = SimpleNamespace(user=user)
    get_authority_snapshot(user, request=request)
    if mutation == "add":
        UserRole.objects.create(
            user=user,
            role=authority,
            office=basic_world["office"],
        )
    else:
        assert authority_assignment is not None
        authority_assignment.delete()
    ticket = Ticket.objects.create(
        number=f"{'OP' if domain == 'operational' else 'IT'}-202607-{uuid4().int % 1000000:06d}",
        domain=domain,
        title="Immutable assignment role snapshot",
        status=Status.objects.get(domain=domain, code="new"),
        channel="internal",
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
    )

    expected_cached = mutation == "delete"
    assert can_assign(user, ticket=ticket, request=request) is expected_cached
    assert can_assign(user, ticket=ticket) is (not expected_cached)


def test_cached_persisted_snapshot_does_not_reveal_stale_group_authority(
    basic_world,
):
    user = _user(groups=[])
    designation = Role.objects.create(
        keycloak_role="estate-examiner",
        name="Estate Examiner",
        scopes=[{"domain": "operational"}],
    )
    UserRole.objects.create(user=user, role=designation)
    request = SimpleNamespace(user=user)
    get_authority_snapshot(user, request=request)
    user.keycloak_groups = ["ops-supervisors"]
    user._groups = ["ops-supervisors"]
    user.save(update_fields=["keycloak_groups"])
    ticket = Ticket.objects.create(
        number="OP-202607-900900",
        domain="operational",
        title="No stale group reveal",
        status=Status.objects.get(domain="operational", code="new"),
        channel="internal",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
    )

    assert can_assign(user, ticket=ticket, request=request) is False


def test_cached_auditor_snapshot_denies_superuser_after_auditor_role_removal(
    basic_world,
):
    user = _user(groups=[])
    user.is_superuser = True
    user.save(update_fields=["is_superuser"])
    auditor = Role.objects.create(
        keycloak_role="auditor",
        name="Auditor",
        scopes=[{"domain": "operational"}],
    )
    assignment = UserRole.objects.create(user=user, role=auditor)
    request = SimpleNamespace(user=user)
    get_authority_snapshot(user, request=request)
    assignment.delete()
    ticket = Ticket.objects.create(
        number="OP-202607-901000",
        domain="operational",
        title="Cached auditor superuser",
        status=Status.objects.get(domain="operational", code="new"),
        channel="internal",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
    )

    assert can_assign(user, ticket=ticket, request=request) is False
    assert can_update_work_state(user, ticket, request=request) is False


@pytest.mark.parametrize("group_source", ["keycloak", "django"])
def test_reloaded_expired_role_actor_uses_durable_legacy_group_fallback(
    basic_world,
    group_source,
):
    user = _user(groups=[])
    if group_source == "keycloak":
        user.keycloak_groups = ["ops-supervisors"]
        user.save(update_fields=["keycloak_groups"])
    else:
        user.groups.add(Group.objects.create(name="ops-supervisors"))
    expired = Role.objects.create(
        keycloak_role="estate-examiner",
        name="Estate Examiner",
        scopes=[{"domain": "it"}],
    )
    UserRole.objects.create(
        user=user,
        role=expired,
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    ticket = Ticket.objects.create(
        number=f"OP-202607-{901100 if group_source == 'keycloak' else 901101}",
        domain="operational",
        title="Reloaded legacy actor",
        status=Status.objects.get(domain="operational", code="new"),
        channel="internal",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
    )

    reloaded = User.objects.get(pk=user.pk)

    assert can_assign(reloaded, ticket=ticket) is True
    assert can_update_work_state(reloaded, ticket) is True


def test_elevated_role_accepts_canonical_uuid_text_variants_for_exact_scope(
    basic_world,
):
    queue = ServiceLocation.objects.create(
        office=basic_world["office"],
        name="Canonical elevated queue",
    )
    user = _user(groups=[])
    role = Role.objects.create(
        keycloak_role="supervisor-operational",
        name="Operational Supervisor",
        scopes=[
            {
                "domain": "operational",
                "office": f"{{{str(basic_world['office'].id).upper()}}}",
                "service": str(basic_world["gen_info"].id).upper(),
                "queue": f"{{{str(queue.id).upper()}}}",
            }
        ],
    )
    UserRole.objects.create(
        user=user,
        role=role,
        office=basic_world["office"],
    )
    ticket = Ticket.objects.create(
        number="OP-202607-901400",
        domain="operational",
        title="Canonical elevated UUID scope",
        status=Status.objects.get(domain="operational", code="new"),
        channel="internal",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
        queue=queue,
    )

    assert can_assign(user, ticket=ticket) is True
    assert can_update_work_state(user, ticket) is True


@pytest.mark.parametrize(
    ("authority_role", "domain"),
    [
        ("supervisor-operational", "operational"),
        ("lead-it", "it"),
        ("admin", "operational"),
    ],
)
@pytest.mark.parametrize("ticket_office_source", ["role", "assignment"])
def test_authority_role_requires_configured_and_assignment_offices_to_match(
    basic_world,
    authority_role,
    domain,
    ticket_office_source,
):
    user = _user(groups=[])
    role_office = basic_world["office"]
    assignment_office = Office.objects.create(
        region=basic_world["region"],
        code=f"AUTH-{authority_role[:4]}-{ticket_office_source[:3]}",
        name="Crossed authority assignment office",
    )
    service = basic_world["gen_info"] if domain == "operational" else basic_world["it_inc"]
    role = Role.objects.create(
        keycloak_role=authority_role,
        name=authority_role,
        scopes=[
            {
                "domain": "admin" if authority_role == "admin" else domain,
                "office": str(role_office.id),
                "service": str(service.id),
            }
        ],
    )
    UserRole.objects.create(
        user=user,
        role=role,
        office=assignment_office,
    )
    ticket_office = (
        role_office
        if ticket_office_source == "role"
        else assignment_office
    )
    ticket = Ticket.objects.create(
        number=f"{'OP' if domain == 'operational' else 'IT'}-202607-{uuid4().int % 1000000:06d}",
        domain=domain,
        title="Independent authority office boundaries",
        status=Status.objects.get(domain=domain, code="new"),
        channel="internal",
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=ticket_office,
    )

    assert can_assign(user, ticket=ticket) is False
    assert can_update_work_state(user, ticket) is False


def test_cached_malformed_auditor_identity_survives_role_removal_for_superuser(
    basic_world,
):
    user = _user(groups=[])
    user.is_superuser = True
    user.save(update_fields=["is_superuser"])
    auditor = Role.objects.create(
        keycloak_role="auditor",
        name="Malformed auditor",
        scopes={"domain": "operational"},
    )
    assignment = UserRole.objects.create(user=user, role=auditor)
    request = SimpleNamespace(user=user)
    snapshot = get_authority_snapshot(user, request=request)
    assignment.delete()
    ticket = Ticket.objects.create(
        number="OP-202607-901200",
        domain="operational",
        title="Malformed cached auditor",
        status=Status.objects.get(domain="operational", code="new"),
        channel="internal",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
    )

    assert snapshot.role_grants == ()
    assert "auditor" not in snapshot.capabilities
    assert snapshot.auditor_identity is True
    assert can_assign(user, ticket=ticket, request=request) is False
    assert can_update_work_state(user, ticket, request=request) is False


@pytest.mark.parametrize("auditor_source", ["persisted", "django"])
def test_fresh_auditor_tightening_bypasses_prefetched_identity_caches(
    basic_world,
    auditor_source,
):
    base_user = _user(groups=[])
    base_user.is_superuser = True
    base_user.save(update_fields=["is_superuser"])
    user = User.objects.prefetch_related("user_roles__role", "groups").get(
        pk=base_user.pk,
    )
    request = SimpleNamespace(user=user)
    get_authority_snapshot(user, request=request)

    if auditor_source == "persisted":
        auditor = Role.objects.create(
            keycloak_role="auditor",
            name="Auditor",
            scopes=[{"domain": "operational"}],
        )
        UserRole.objects.create(user_id=user.pk, role=auditor)
    else:
        auditor_group = Group.objects.create(name="auditors")
        User.objects.get(pk=user.pk).groups.add(auditor_group)

    ticket = Ticket.objects.create(
        number=f"OP-202607-{901300 if auditor_source == 'persisted' else 901301}",
        domain="operational",
        title="Fresh auditor tightening",
        status=Status.objects.get(domain="operational", code="new"),
        channel="internal",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
    )

    assert can_assign(user, ticket=ticket, request=request) is False
    assert can_update_work_state(user, ticket, request=request) is False
