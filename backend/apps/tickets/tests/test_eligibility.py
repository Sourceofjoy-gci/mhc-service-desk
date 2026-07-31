from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.contrib.auth.models import Group
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.catalogue.models import Service
from apps.identity_access.models import Role, User, UserRole
from apps.organisations.models import Office, ServiceLocation
from apps.tickets.custody import CustodyParty
from apps.tickets.eligibility import (
    DESIGNATIONS,
    AssigneeCandidate,
    custody_party_for_user,
    eligible_assignees,
    is_eligible_assignee,
)
from apps.tickets.models import Ticket
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db

DESIGNATION_CASES = (
    ("master", "Master", "Office Leadership"),
    ("deputy-master", "Deputy Master", "Office Leadership"),
    ("assistant-master", "Assistant Master", "Office Leadership"),
    ("assistant-accountant", "Assistant Accountant", "Finance"),
    ("accountant", "Accountant", "Finance"),
    ("senior-accountant", "Senior Accountant", "Finance"),
    ("principal-accountant", "Principal Accountant", "Finance"),
    ("financial-controller", "Financial Controller", "Finance"),
    ("estate-examiner", "Estate Examiner", "Estate Administration"),
    ("records-clerk", "Records Clerk", "Records and Data"),
    ("data-clerk", "Data Clerk", "Records and Data"),
)


def _ticket(
    basic_world,
    *,
    domain: str = "operational",
    confidentiality: str = Ticket.Confidentiality.NORMAL,
    queue: ServiceLocation | None = None,
    office: Office | None = None,
) -> Ticket:
    service = basic_world["gen_info"] if domain == "operational" else basic_world["it_inc"]
    prefix = "OP" if domain == "operational" else "IT"
    return Ticket.objects.create(
        number=f"{prefix}-202607-{Ticket.objects.count() + 970001:06d}",
        domain=domain,
        title="Eligibility contract",
        status=Status.objects.get(domain=domain, code="new"),
        channel=Ticket.Channel.INTERNAL,
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=office or basic_world["office"],
        confidentiality=confidentiality,
        queue=queue,
    )


def _user(
    *,
    username: str | None = None,
    display_name: str = "",
    groups: list[str] | None = None,
    active: bool = True,
    user_id: UUID | None = None,
) -> User:
    resolved_username = username or f"staff-{uuid4().hex}"
    user = User.objects.create(
        id=user_id or uuid4(),
        username=resolved_username,
        keycloak_subject=f"subject-{uuid4().hex}",
        display_name=display_name,
        keycloak_groups=groups or [],
        is_active=active,
    )
    user._groups = groups or []
    return user


def _grant(
    user: User,
    *,
    role_key: str,
    role_name: str,
    scopes: list[dict[str, object]],
    office: Office | None = None,
    expired: bool = False,
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
        expires_at=timezone.now() - timedelta(seconds=1) if expired else None,
    )


def _candidate(ticket: Ticket, user: User) -> AssigneeCandidate:
    return next(item for item in eligible_assignees(ticket) if item.id == user.id)


@pytest.mark.parametrize("ticket_office_source", ["role", "assignment"])
def test_designation_requires_role_and_assignment_offices_to_both_match(
    basic_world,
    ticket_office_source,
):
    assignment_office = Office.objects.create(
        region=basic_world["region"],
        code=f"CROSSED-{ticket_office_source}",
        name="Crossed assignment office",
    )
    role_office = basic_world["office"]
    ticket = _ticket(
        basic_world,
        office=(
            role_office
            if ticket_office_source == "role"
            else assignment_office
        ),
    )
    user = _user()
    _grant(
        user,
        role_key="estate-examiner",
        role_name="Estate Examiner",
        scopes=[
            {
                "domain": "operational",
                "office": str(role_office.id),
                "service": str(ticket.service_id),
            }
        ],
        office=assignment_office,
    )

    assert is_eligible_assignee(ticket, user) is False
    assert user.id not in {candidate.id for candidate in eligible_assignees(ticket)}


@pytest.mark.parametrize(
    ("role_key", "display_name", "team_label"),
    DESIGNATION_CASES,
)
def test_each_primary_designation_is_an_explainable_exact_scope_candidate(
    basic_world,
    role_key,
    display_name,
    team_label,
):
    ticket = _ticket(basic_world)
    user = _user(username=f"{role_key}-user", display_name=f"{display_name} User")
    _grant(
        user,
        role_key=role_key,
        role_name=display_name,
        scopes=[
            {
                "domain": ticket.domain,
                "office": str(ticket.office_id),
                "service": str(ticket.service_id),
            }
        ],
        office=ticket.office,
    )

    candidate = _candidate(ticket, user)

    assert candidate == AssigneeCandidate(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        designations=(display_name,),
        team_labels=(team_label,),
    )
    assert is_eligible_assignee(ticket, user) is True


def test_designation_table_is_complete_and_stable():
    assert tuple(
        (item.role_key, item.display_name, item.team_label) for item in DESIGNATIONS
    ) == DESIGNATION_CASES


@pytest.mark.parametrize(
    "exclusion",
    [
        "inactive",
        "expired",
        "wrong_domain",
        "wrong_scope_office",
        "wrong_assignment_office",
        "wrong_service",
        "wrong_queue",
        "queue_scope_on_unqueued_ticket",
        "restricted_without_visibility",
    ],
)
def test_designation_candidates_fail_closed_at_every_boundary(basic_world, exclusion):
    queue = ServiceLocation.objects.create(
        office=basic_world["office"],
        name=f"Queue {uuid4().hex}",
    )
    ticket = _ticket(
        basic_world,
        queue=None if exclusion == "queue_scope_on_unqueued_ticket" else queue,
        confidentiality=(
            Ticket.Confidentiality.RESTRICTED
            if exclusion == "restricted_without_visibility"
            else Ticket.Confidentiality.NORMAL
        ),
    )
    other_office = Office.objects.create(
        region=basic_world["region"],
        code=f"OTHER-{uuid4().hex[:8]}",
        name="Other office",
    )
    other_service = Service.objects.create(
        code=f"OTHER-{uuid4().hex[:8]}",
        name="Other operational service",
        domain="operational",
    )
    scope: dict[str, object] = {
        "domain": ticket.domain,
        "office": str(ticket.office_id),
        "service": str(ticket.service_id),
    }
    assignment_office = ticket.office
    active = True
    expired = False
    if exclusion == "inactive":
        active = False
    elif exclusion == "expired":
        expired = True
    elif exclusion == "wrong_domain":
        scope["domain"] = "it"
    elif exclusion == "wrong_scope_office":
        scope["office"] = str(other_office.id)
    elif exclusion == "wrong_assignment_office":
        assignment_office = other_office
    elif exclusion == "wrong_service":
        scope["service"] = str(other_service.id)
    elif exclusion in {"wrong_queue", "queue_scope_on_unqueued_ticket"}:
        scope["queue"] = str(uuid4())

    user = _user(active=active)
    _grant(
        user,
        role_key="estate-examiner",
        role_name="Estate Examiner",
        scopes=[scope],
        office=assignment_office,
        expired=expired,
    )

    assert is_eligible_assignee(ticket, user) is False
    assert user.id not in {candidate.id for candidate in eligible_assignees(ticket)}


def test_omitted_optional_dimensions_are_explicit_wildcards(basic_world):
    queue = ServiceLocation.objects.create(
        office=basic_world["office"],
        name="Wildcard queue",
    )
    ticket = _ticket(basic_world, queue=queue)
    user = _user()
    _grant(
        user,
        role_key="records-clerk",
        role_name="Records Clerk",
        scopes=[{"domain": "operational"}],
    )

    assert is_eligible_assignee(ticket, user) is True


def test_restricted_scope_can_explicitly_authorise_a_designation(basic_world):
    ticket = _ticket(
        basic_world,
        confidentiality=Ticket.Confidentiality.RESTRICTED,
    )
    user = _user()
    _grant(
        user,
        role_key="master",
        role_name="Master",
        scopes=[
            {
                "domain": "operational",
                "office": str(ticket.office_id),
                "restricted_only": True,
            }
        ],
    )

    assert is_eligible_assignee(ticket, user) is True


def test_admin_auditor_and_unpersisted_designation_are_not_ownership_roles(basic_world):
    ticket = _ticket(basic_world)
    admin = _user(groups=["system-admins"])
    auditor = _user(groups=["auditors"])
    designation_group_only = _user(groups=["estate-examiner"])
    mixed_auditor = _user()
    auditor_role = Role.objects.create(
        keycloak_role="auditor",
        name="Auditor",
        scopes=[{"domain": "operational"}],
    )
    designation_role = Role.objects.create(
        keycloak_role="estate-examiner",
        name="Estate Examiner",
        scopes=[{"domain": "operational"}],
    )
    UserRole.objects.create(user=mixed_auditor, role=auditor_role)
    UserRole.objects.create(user=mixed_auditor, role=designation_role)

    candidate_ids = {candidate.id for candidate in eligible_assignees(ticket)}

    assert admin.id not in candidate_ids
    assert auditor.id not in candidate_ids
    assert designation_group_only.id not in candidate_ids
    assert mixed_auditor.id not in candidate_ids


@pytest.mark.parametrize(
    "auditor_source",
    ["persisted", "keycloak", "request", "django"],
)
def test_every_auditor_identity_source_excludes_a_functional_designation_target(
    basic_world,
    auditor_source,
):
    ticket = _ticket(basic_world)
    user = _user()
    designation = Role.objects.create(
        keycloak_role="estate-examiner",
        name="Estate Examiner",
        scopes=[{"domain": "operational"}],
    )
    UserRole.objects.create(user=user, role=designation)
    if auditor_source == "persisted":
        auditor = Role.objects.create(
            keycloak_role="auditor",
            name="Auditor",
            scopes=[{"domain": "operational"}],
        )
        UserRole.objects.create(user=user, role=auditor)
    elif auditor_source == "keycloak":
        user.keycloak_groups = ["auditors"]
        user.save(update_fields=["keycloak_groups"])
        user._groups = []
    elif auditor_source == "request":
        user._groups = ["auditors"]
    else:
        auditors = Group.objects.create(name="auditors")
        user.groups.add(auditors)

    assert is_eligible_assignee(ticket, user) is False
    if auditor_source != "request":
        assert user.id not in {
            candidate.id for candidate in eligible_assignees(ticket)
        }


def test_only_expired_persisted_rows_allow_legacy_target_fallback(basic_world):
    ticket = _ticket(basic_world)
    user = _user(groups=["ops-agents"])
    expired_role = Role.objects.create(
        keycloak_role="estate-examiner",
        name="Estate Examiner",
        scopes=[{"domain": "it"}],
    )
    UserRole.objects.create(
        user=user,
        role=expired_role,
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    assert is_eligible_assignee(ticket, User.objects.get(pk=user.pk)) is True


def test_active_invalid_persisted_row_suppresses_legacy_target_fallback(basic_world):
    ticket = _ticket(basic_world)
    user = _user(groups=["ops-agents"])
    invalid_role = Role.objects.create(
        keycloak_role="invalid-functional-role",
        name="Invalid functional role",
        scopes={"domain": "operational"},
    )
    UserRole.objects.create(user=user, role=invalid_role)

    assert is_eligible_assignee(ticket, user) is False
    assert user.id not in {candidate.id for candidate in eligible_assignees(ticket)}


@pytest.mark.parametrize(
    ("role_key", "role_name", "domain", "team_label"),
    [
        ("agent-operational", "Operational Agent", "operational", "Operational"),
        (
            "supervisor-operational",
            "Operational Supervisor",
            "operational",
            "Operational",
        ),
        ("agent-it", "IT Agent", "it", "IT"),
        ("lead-it", "IT Lead", "it", "IT"),
    ],
)
def test_active_persisted_legacy_roles_remain_candidates(
    basic_world,
    role_key,
    role_name,
    domain,
    team_label,
):
    ticket = _ticket(basic_world, domain=domain)
    user = _user()
    _grant(
        user,
        role_key=role_key,
        role_name=role_name,
        scopes=[{"domain": domain}],
    )

    candidate = _candidate(ticket, user)

    assert candidate.designations == (role_name,)
    assert candidate.team_labels == (team_label,)


@pytest.mark.parametrize(
    ("group_name", "domain", "display_name", "team_label"),
    [
        ("ops-agents", "operational", "Operational Agent", "Operational"),
        ("ops-supervisors", "operational", "Operational Supervisor", "Operational"),
        ("it-agents", "it", "IT Agent", "IT"),
        ("it-leads", "it", "IT Lead", "IT"),
    ],
)
def test_group_fallback_legacy_roles_remain_candidates(
    basic_world,
    group_name,
    domain,
    display_name,
    team_label,
):
    ticket = _ticket(basic_world, domain=domain)
    user = _user(groups=[group_name])

    candidate = _candidate(ticket, user)

    assert candidate.designations == (display_name,)
    assert candidate.team_labels == (team_label,)
    reloaded = User.objects.get(pk=user.pk)
    assert is_eligible_assignee(ticket, reloaded) is True


def test_search_matches_name_username_designation_and_team_case_insensitively(
    basic_world,
):
    ticket = _ticket(basic_world)
    finance = _user(username="ledger-user", display_name="Ada Numbers")
    _grant(
        finance,
        role_key="accountant",
        role_name="Accountant",
        scopes=[{"domain": "operational"}],
    )
    examiner = _user(username="examiner-user", display_name="Bongi Dlamini")
    _grant(
        examiner,
        role_key="estate-examiner",
        role_name="Estate Examiner",
        scopes=[{"domain": "operational"}],
    )

    assert [item.id for item in eligible_assignees(ticket, search="ADA")] == [finance.id]
    assert [item.id for item in eligible_assignees(ticket, search="LEDGER")] == [
        finance.id
    ]
    assert [item.id for item in eligible_assignees(ticket, search="estate EXAM")] == [
        examiner.id
    ]
    assert [item.id for item in eligible_assignees(ticket, search="FINANCE")] == [
        finance.id
    ]


def test_candidate_order_is_display_name_then_username_then_uuid(basic_world):
    ticket = _ticket(basic_world)
    second = _user(
        username="bravo",
        display_name="Alpha",
        user_id=UUID("00000000-0000-0000-0000-000000000002"),
    )
    first = _user(
        username="alpha",
        display_name="Alpha",
        user_id=UUID("00000000-0000-0000-0000-000000000003"),
    )
    third = _user(
        username="zulu",
        display_name="Zulu",
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
    )
    role = Role.objects.create(
        keycloak_role="data-clerk",
        name="Data Clerk",
        scopes=[{"domain": "operational"}],
    )
    for user in (second, first, third):
        UserRole.objects.create(user=user, role=role)

    assert [item.id for item in eligible_assignees(ticket)] == [
        first.id,
        second.id,
        third.id,
    ]


def test_candidate_loading_has_bounded_query_growth(basic_world):
    ticket = _ticket(basic_world)
    role = Role.objects.create(
        keycloak_role="records-clerk",
        name="Records Clerk",
        scopes=[{"domain": "operational"}],
    )
    UserRole.objects.create(user=_user(), role=role)
    with CaptureQueriesContext(connection) as one_user_queries:
        assert len(eligible_assignees(ticket)) == 1

    for _ in range(9):
        UserRole.objects.create(user=_user(), role=role)
    with CaptureQueriesContext(connection) as ten_user_queries:
        assert len(eligible_assignees(ticket)) == 10

    assert len(ten_user_queries) <= len(one_user_queries) + 1


def test_custody_party_uses_stable_explainable_candidate_snapshot(basic_world):
    ticket = _ticket(basic_world)
    user = _user(username="estate-user", display_name="Estate User")
    _grant(
        user,
        role_key="estate-examiner",
        role_name="Estate Examiner",
        scopes=[{"domain": "operational"}],
    )

    assert custody_party_for_user(ticket, user) == CustodyParty(
        id=str(user.id),
        subject=user.keycloak_subject,
        display_name="Estate User",
        designations=("Estate Examiner",),
        team_labels=("Estate Administration",),
    )
