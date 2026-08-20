"""Operational and IT authority is confined to the officer's office."""

from __future__ import annotations

import pytest

from apps.identity_access.models import Role, UserRole
from apps.identity_access.scope import (
    Scope,
    _scope_key,
    get_authority_snapshot,
    get_user_scopes,
    scope_ticket_queryset,
)
from apps.organisations.models import Office, ServiceLocation
from apps.tickets.models import Ticket

pytestmark = pytest.mark.django_db


@pytest.fixture
def other_office(basic_world):
    return Office.objects.create(
        region=basic_world["region"],
        code="OTH-9",
        name="Other Office",
    )


def test_operational_scope_is_bound_to_the_office(basic_world, staff_user):
    user = staff_user(groups=["ops-agents"])
    scopes = get_user_scopes(user)
    assert scopes == [Scope(domain="operational", office_id=str(basic_world["office"].id))]


def test_it_scope_is_bound_to_the_office(basic_world, staff_user):
    user = staff_user(groups=["it-agents"])
    scopes = get_user_scopes(user)
    assert scopes == [Scope(domain="it", office_id=str(basic_world["office"].id))]


def test_missing_office_denies_operational_authority(staff_user):
    assert get_user_scopes(staff_user(groups=["ops-agents"], office=None)) == []


def test_inactive_office_denies_operational_authority(basic_world, staff_user):
    office = Office.objects.create(
        region=basic_world["region"],
        code="OLD-9",
        name="Closed",
        is_active=False,
    )
    assert get_user_scopes(staff_user(groups=["ops-agents"], office=office)) == []


def test_admin_scope_survives_a_missing_office(staff_user):
    assert get_user_scopes(staff_user(groups=["system-admins"], office=None)) == [
        Scope(domain="admin")
    ]


def test_admin_and_agent_are_confined_separately(basic_world, staff_user):
    user = staff_user(groups=["system-admins", "ops-agents"])
    scopes = set(get_user_scopes(user))
    assert Scope(domain="admin") in scopes
    assert Scope(domain="operational", office_id=str(basic_world["office"].id)) in scopes
    assert Scope(domain="operational") not in scopes


def test_auditor_is_unconfined(staff_user):
    scopes = get_user_scopes(staff_user(groups=["auditors"], office=None))
    assert Scope(domain="operational") in scopes
    assert Scope(domain="it") in scopes


def test_service_desk_is_unconfined(staff_user):
    scopes = get_user_scopes(staff_user(groups=["service-desk-agents"], office=None))
    assert Scope(domain="operational") in scopes


def test_superuser_is_unconfined(staff_user):
    user = staff_user(groups=[], office=None, is_superuser=True)
    assert get_user_scopes(user) == [Scope(domain="admin")]


def test_scope_bound_to_another_office_is_dropped(basic_world, other_office, staff_user):
    user = staff_user(groups=[])
    # ``basic_world`` already seeds the ``ops-agents`` role; bind its configured
    # scope to an office the officer is not based at.
    role = Role.objects.get(keycloak_role="ops-agents")
    role.scopes = [{"domain": "operational", "office": str(other_office.id)}]
    role.save(update_fields=["scopes"])
    UserRole.objects.create(user=user, role=role)
    assert get_user_scopes(user) == []


def test_supervisor_keeps_restricted_visibility_after_confinement(basic_world, staff_user):
    """Regression guard: _scope_key includes office_id, so rewriting a scope's
    office without remapping restricted_scope_keys would silently hide every
    restricted ticket from supervisors."""
    user = staff_user(groups=["ops-supervisors"])
    snapshot = get_authority_snapshot(user)
    assert len(snapshot.scopes) == 1
    assert _scope_key(snapshot.scopes[0]) in snapshot.restricted_scope_keys


def test_officer_sees_own_office_tickets_only(
    basic_world,
    other_office,
    staff_user,
    ticket_factory,
):
    mine = ticket_factory(office=basic_world["office"])
    theirs = ticket_factory(office=other_office)

    visible = scope_ticket_queryset(
        staff_user(groups=["ops-agents"]),
        Ticket.objects.all(),
    )

    assert mine in visible
    assert theirs not in visible


def test_service_desk_sees_every_office(basic_world, other_office, staff_user, ticket_factory):
    mine = ticket_factory(office=basic_world["office"])
    theirs = ticket_factory(office=other_office)

    visible = scope_ticket_queryset(
        staff_user(groups=["service-desk-agents"], office=None),
        Ticket.objects.all(),
    )

    assert mine in visible
    assert theirs in visible


def test_service_desk_cannot_see_restricted_tickets(basic_world, staff_user, ticket_factory):
    restricted = ticket_factory(office=basic_world["office"], confidentiality="restricted")

    visible = scope_ticket_queryset(
        staff_user(groups=["service-desk-agents"], office=None),
        Ticket.objects.all(),
    )

    assert restricted not in visible


def test_station_is_recorded_but_never_confines(basic_world, staff_user, ticket_factory):
    """Ticket.queue is nullable, so confining by station would blind a counter
    officer to most of their own office. Station records, office confines."""
    station = ServiceLocation.objects.create(office=basic_world["office"], name="Counter-5")
    officer = staff_user(groups=["ops-agents"], station=station)
    queueless = ticket_factory(office=basic_world["office"])
    assert queueless.queue is None

    visible = scope_ticket_queryset(officer, Ticket.objects.all())

    assert queueless in visible
    assert all(scope.queue_id is None for scope in get_user_scopes(officer))


def _desk_supervisor(staff_user):
    """A national service desk agent who is also a supervisor of one office."""
    return staff_user(groups=["service-desk-agents", "ops-supervisors"])


def test_service_desk_supervisor_is_confined_then_granted_a_national_desk_scope(
    basic_world,
    staff_user,
):
    """The two halves of a combined identity keep exactly their own power: the
    supervisor half stays bound to its office and keeps restricted visibility
    there, the desk half reaches every office but never restricted work."""
    office_id = str(basic_world["office"].id)
    snapshot = get_authority_snapshot(_desk_supervisor(staff_user))

    assert set(snapshot.scopes) == {
        Scope(domain="operational", office_id=office_id),
        Scope(domain="operational"),
    }
    assert snapshot.restricted_scope_keys == frozenset(
        {("operational", office_id, None, None)}
    )


def test_service_desk_supervisor_sees_restricted_work_of_own_office_only(
    basic_world,
    other_office,
    staff_user,
    ticket_factory,
):
    mine = ticket_factory(office=basic_world["office"], confidentiality="restricted")
    theirs = ticket_factory(office=other_office, confidentiality="restricted")

    visible = scope_ticket_queryset(_desk_supervisor(staff_user), Ticket.objects.all())

    assert mine in visible
    assert theirs not in visible


def test_service_desk_supervisor_still_answers_every_office(
    basic_world,
    other_office,
    staff_user,
    ticket_factory,
):
    mine = ticket_factory(office=basic_world["office"])
    theirs = ticket_factory(office=other_office)

    visible = scope_ticket_queryset(_desk_supervisor(staff_user), Ticket.objects.all())

    assert mine in visible
    assert theirs in visible


def test_auditor_stays_unconfined_including_restricted_work(
    basic_world,
    other_office,
    staff_user,
    ticket_factory,
):
    """Auditors are cross-office by mandate, restricted work included."""
    mine = ticket_factory(office=basic_world["office"], confidentiality="restricted")
    theirs = ticket_factory(office=other_office, confidentiality="restricted")

    visible = scope_ticket_queryset(
        staff_user(groups=["auditors"], office=None),
        Ticket.objects.all(),
    )

    assert mine in visible
    assert theirs in visible
