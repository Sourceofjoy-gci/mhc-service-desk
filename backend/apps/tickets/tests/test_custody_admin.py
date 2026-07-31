"""Authorisation boundaries for the read-only custody Django admin."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.identity_access.models import Role, User, UserRole
from apps.tickets.custody import CustodyActor, CustodyEventInput, record_custody_events
from apps.tickets.models import Ticket, TicketCustodyEvent
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db


def _ticket(basic_world, *, domain: str, confidentiality: str = "normal") -> Ticket:
    service = basic_world["gen_info"] if domain == "operational" else basic_world["it_inc"]
    return Ticket.objects.create(
        number=f"{domain[:2].upper()}-202607-{uuid4().int % 1_000_000:06d}",
        domain=domain,
        title=f"{domain} {confidentiality} custody ticket",
        status=Status.objects.get(domain=domain, code="new"),
        priority="P3",
        channel="web",
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
        confidentiality=confidentiality,
    )


def _custody_event(ticket: Ticket) -> TicketCustodyEvent:
    return record_custody_events(
        ticket=ticket,
        actor=CustodyActor.system("admin-test", "Admin test"),
        events=(CustodyEventInput.created(source_process="test.admin"),),
    )[0]


def _staff_user(
    *,
    role_name: str | None = None,
    can_view: bool = True,
    active: bool = True,
    superuser: bool = False,
) -> User:
    user = User.objects.create(
        username=f"custody-admin-{uuid4().hex}",
        keycloak_subject=f"custody-admin-subject-{uuid4().hex}",
        is_staff=True,
        is_active=active,
        is_superuser=superuser,
    )
    if can_view:
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="tickets",
                codename="view_ticketcustodyevent",
            )
        )
    if role_name:
        role, _ = Role.objects.get_or_create(
            keycloak_role=role_name,
            defaults={"name": role_name},
        )
        UserRole.objects.create(user=user, role=role)
    return user


def _change_url(event: TicketCustodyEvent) -> str:
    return reverse("admin:tickets_ticketcustodyevent_change", args=[event.pk])


def _history_url(event: TicketCustodyEvent) -> str:
    return reverse("admin:tickets_ticketcustodyevent_history", args=[event.pk])


def test_custody_admin_reuses_ticket_scope_for_list_detail_and_history(client, basic_world):
    visible = _custody_event(_ticket(basic_world, domain="operational"))
    restricted = _custody_event(
        _ticket(basic_world, domain="operational", confidentiality="restricted")
    )
    cross_domain = _custody_event(_ticket(basic_world, domain="it"))
    viewer = _staff_user(role_name="ops-agents")
    client.force_login(viewer)

    listing = client.get(reverse("admin:tickets_ticketcustodyevent_changelist"))

    assert listing.status_code == 200
    assert visible.ticket.number in listing.content.decode()
    assert restricted.ticket.number not in listing.content.decode()
    assert cross_domain.ticket.number not in listing.content.decode()
    assert client.get(_change_url(visible)).status_code == 200
    assert client.get(_history_url(visible)).status_code == 200
    for url, event in (
        (_change_url(restricted), restricted),
        (_history_url(restricted), restricted),
        (_change_url(cross_domain), cross_domain),
        (_history_url(cross_domain), cross_domain),
    ):
        hidden = client.get(url)
        assert hidden.status_code in {302, 404}
        assert event.ticket.number not in hidden.content.decode()


def test_custody_admin_allows_the_canonical_auditor_scope(client, basic_world):
    operational = _custody_event(
        _ticket(basic_world, domain="operational", confidentiality="restricted")
    )
    it = _custody_event(_ticket(basic_world, domain="it", confidentiality="restricted"))
    auditor = _staff_user(role_name="auditors")
    client.force_login(auditor)

    listing = client.get(reverse("admin:tickets_ticketcustodyevent_changelist"))

    assert listing.status_code == 200
    assert operational.ticket.number in listing.content.decode()
    assert it.ticket.number in listing.content.decode()
    assert client.get(_change_url(operational)).status_code == 200
    assert client.get(_history_url(it)).status_code == 200


def test_custody_admin_superuser_access_follows_the_canonical_admin_scope(client, basic_world):
    event = _custody_event(_ticket(basic_world, domain="it", confidentiality="restricted"))
    superuser = _staff_user(superuser=True)
    client.force_login(superuser)

    listing = client.get(reverse("admin:tickets_ticketcustodyevent_changelist"))

    assert listing.status_code == 200
    assert event.ticket.number in listing.content.decode()
    assert client.get(_change_url(event)).status_code == 200


def test_custody_admin_denies_anonymous_inactive_and_no_view_permission_users(client, basic_world):
    event = _custody_event(_ticket(basic_world, domain="operational"))
    changelist = reverse("admin:tickets_ticketcustodyevent_changelist")

    assert client.get(changelist).status_code == 302

    inactive = _staff_user(role_name="ops-agents", active=False)
    client.force_login(inactive)
    assert client.get(changelist).status_code == 302

    no_view_permission = _staff_user(role_name="ops-agents", can_view=False)
    client.force_login(no_view_permission)
    assert client.get(changelist).status_code == 403
    assert client.get(_change_url(event)).status_code == 403
    assert client.get(_history_url(event)).status_code == 403


def test_custody_admin_has_no_mutation_or_ticket_admin_link_leakage(client, basic_world):
    event = _custody_event(_ticket(basic_world, domain="operational"))
    viewer = _staff_user(role_name="ops-agents")
    client.force_login(viewer)
    ticket_admin_url = reverse("admin:tickets_ticket_change", args=[event.ticket_id])

    listing = client.get(reverse("admin:tickets_ticketcustodyevent_changelist"))
    detail = client.get(_change_url(event))

    assert ticket_admin_url not in listing.content.decode()
    assert ticket_admin_url not in detail.content.decode()
    assert client.post(reverse("admin:tickets_ticketcustodyevent_add")).status_code == 403
    assert client.post(_change_url(event), {}).status_code == 403
    delete_url = reverse("admin:tickets_ticketcustodyevent_delete", args=[event.pk])
    assert client.post(delete_url, {}).status_code == 403
