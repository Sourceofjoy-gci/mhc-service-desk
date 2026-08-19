"""Authorisation boundaries for the read-only custody Django admin."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth.models import Permission
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.catalogue.models import RequestType, Service
from apps.identity_access.models import Role, User, UserRole
from apps.organisations.models import Office, ServiceLocation
from apps.tickets.custody import CustodyActor, CustodyEventInput, record_custody_events
from apps.tickets.models import Ticket, TicketCustodyEvent
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db


def _ticket(
    basic_world,
    *,
    domain: str,
    confidentiality: str = "normal",
    service: Service | None = None,
    office: Office | None = None,
    queue: ServiceLocation | None = None,
) -> Ticket:
    service = service or (
        basic_world["gen_info"] if domain == "operational" else basic_world["it_inc"]
    )
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
        office=office or basic_world["office"],
        queue=queue,
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
    role_scopes: list[dict[str, object]] | None = None,
    can_view: bool = True,
    active: bool = True,
    superuser: bool = False,
) -> User:
    # Operational and IT authority is confined to the officer's office, so
    # every staff actor is based at the seeded ``basic_world`` office.
    user = User.objects.create(
        username=f"custody-admin-{uuid4().hex}",
        keycloak_subject=f"custody-admin-subject-{uuid4().hex}",
        is_staff=True,
        is_active=active,
        is_superuser=superuser,
        office=Office.objects.get(code="TST-1"),
    )
    if can_view:
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="tickets",
                codename="view_ticketcustodyevent",
            )
        )
    if role_name:
        if role_scopes is None:
            role, _ = Role.objects.get_or_create(
                keycloak_role=role_name,
                defaults={"name": role_name},
            )
        else:
            role = Role.objects.create(
                keycloak_role=f"{role_name}-{uuid4().hex}",
                name=role_name,
                scopes=role_scopes,
            )
        UserRole.objects.create(user=user, role=role)
    return user


def _change_url(event: TicketCustodyEvent) -> str:
    return reverse("admin:tickets_ticketcustodyevent_change", args=[event.pk])


def _history_url(event: TicketCustodyEvent) -> str:
    return reverse("admin:tickets_ticketcustodyevent_history", args=[event.pk])


def _get(client, url: str, data: dict[str, str] | None = None):
    return client.get(url, data, secure=True)


def _post(client, url: str, data: dict[str, str] | None = None):
    return client.post(url, data or {}, secure=True)


def test_custody_admin_reuses_ticket_scope_for_list_detail_and_history(client, basic_world):
    visible = _custody_event(_ticket(basic_world, domain="operational"))
    restricted = _custody_event(
        _ticket(basic_world, domain="operational", confidentiality="restricted")
    )
    cross_domain = _custody_event(_ticket(basic_world, domain="it"))
    viewer = _staff_user(role_name="ops-agents")
    client.force_login(viewer)

    listing = _get(client, reverse("admin:tickets_ticketcustodyevent_changelist"))

    assert listing.status_code == 200
    assert visible.ticket.number in listing.content.decode()
    assert restricted.ticket.number not in listing.content.decode()
    assert cross_domain.ticket.number not in listing.content.decode()
    assert _get(client, _change_url(visible)).status_code == 200
    assert _get(client, _history_url(visible)).status_code == 200
    for url, event in (
        (_change_url(restricted), restricted),
        (_history_url(restricted), restricted),
        (_change_url(cross_domain), cross_domain),
        (_history_url(cross_domain), cross_domain),
    ):
        hidden = _get(client, url)
        assert hidden.status_code in {302, 404}
        assert event.ticket.number not in hidden.content.decode()


def test_custody_admin_allows_the_canonical_auditor_scope(client, basic_world):
    operational = _custody_event(
        _ticket(basic_world, domain="operational", confidentiality="restricted")
    )
    it = _custody_event(_ticket(basic_world, domain="it", confidentiality="restricted"))
    auditor = _staff_user(role_name="auditors")
    client.force_login(auditor)

    listing = _get(client, reverse("admin:tickets_ticketcustodyevent_changelist"))

    assert listing.status_code == 200
    assert operational.ticket.number in listing.content.decode()
    assert it.ticket.number in listing.content.decode()
    assert _get(client, _change_url(operational)).status_code == 200
    assert _get(client, _history_url(it)).status_code == 200


def test_custody_admin_superuser_access_follows_the_canonical_admin_scope(client, basic_world):
    event = _custody_event(_ticket(basic_world, domain="it", confidentiality="restricted"))
    superuser = _staff_user(superuser=True)
    client.force_login(superuser)

    listing = _get(client, reverse("admin:tickets_ticketcustodyevent_changelist"))

    assert listing.status_code == 200
    assert event.ticket.number in listing.content.decode()
    assert _get(client, _change_url(event)).status_code == 200


def test_custody_admin_denies_anonymous_inactive_and_no_view_permission_users(client, basic_world):
    event = _custody_event(_ticket(basic_world, domain="operational"))
    changelist = reverse("admin:tickets_ticketcustodyevent_changelist")

    assert _get(client, changelist).status_code == 302

    inactive = _staff_user(role_name="ops-agents", active=False)
    client.force_login(inactive)
    assert _get(client, changelist).status_code == 302

    no_view_permission = _staff_user(role_name="ops-agents", can_view=False)
    client.force_login(no_view_permission)
    assert _get(client, changelist).status_code == 403
    assert _get(client, _change_url(event)).status_code == 403
    assert _get(client, _history_url(event)).status_code == 403


def test_custody_admin_has_no_mutation_or_ticket_admin_link_leakage(client, basic_world):
    event = _custody_event(_ticket(basic_world, domain="operational"))
    viewer = _staff_user(role_name="ops-agents")
    client.force_login(viewer)
    ticket_admin_url = reverse("admin:tickets_ticket_change", args=[event.ticket_id])

    listing = _get(client, reverse("admin:tickets_ticketcustodyevent_changelist"))
    detail = _get(client, _change_url(event))

    assert ticket_admin_url not in listing.content.decode()
    assert ticket_admin_url not in detail.content.decode()
    assert _post(client, reverse("admin:tickets_ticketcustodyevent_add")).status_code == 403
    assert _post(client, _change_url(event)).status_code == 403
    delete_url = reverse("admin:tickets_ticketcustodyevent_delete", args=[event.pk])
    assert _post(client, delete_url).status_code == 403


def test_custody_admin_model_view_permission_without_ticket_scope_is_empty(client, basic_world):
    event = _custody_event(_ticket(basic_world, domain="operational"))
    generic_staff = _staff_user()
    client.force_login(generic_staff)

    listing = _get(client, reverse("admin:tickets_ticketcustodyevent_changelist"))

    assert listing.status_code == 200
    assert listing.context["cl"].result_count == 0
    assert listing.context["cl"].full_result_count == 0
    assert event.ticket.number not in listing.content.decode()
    assert _get(client, _change_url(event)).status_code in {302, 404}


def test_custody_admin_allows_security_responder_only_restricted_tickets(client, basic_world):
    restricted = _custody_event(
        _ticket(basic_world, domain="operational", confidentiality="restricted")
    )
    normal = _custody_event(_ticket(basic_world, domain="operational"))
    responder = _staff_user(role_name="security-responders")
    client.force_login(responder)

    listing = _get(client, reverse("admin:tickets_ticketcustodyevent_changelist"))

    assert listing.status_code == 200
    assert restricted.ticket.number in listing.content.decode()
    assert normal.ticket.number not in listing.content.decode()
    assert _get(client, _change_url(restricted)).status_code == 200
    assert _get(client, _change_url(normal)).status_code in {302, 404}


def test_custody_admin_honours_persisted_office_service_and_queue_scope(client, basic_world):
    office = basic_world["office"]
    matching_queue = ServiceLocation.objects.create(office=office, name="Matching queue")
    other_queue = ServiceLocation.objects.create(office=office, name="Other queue")
    other_office = Office.objects.create(
        region=basic_world["region"], code="TST-2", name="Other office"
    )
    other_office_queue = ServiceLocation.objects.create(
        office=other_office,
        name="Other office queue",
    )
    other_service = Service.objects.create(
        code="GEN-OTHER", name="Other operational service", domain="operational"
    )
    RequestType.objects.create(
        service=other_service,
        code="OTHER",
        name="Other request",
        default_priority="P3",
    )
    allowed = _custody_event(
        _ticket(
            basic_world,
            domain="operational",
            service=basic_world["gen_info"],
            office=office,
            queue=matching_queue,
        )
    )
    wrong_office = _custody_event(
        _ticket(
            basic_world,
            domain="operational",
            service=basic_world["gen_info"],
            office=other_office,
            queue=other_office_queue,
        )
    )
    wrong_service = _custody_event(
        _ticket(
            basic_world,
            domain="operational",
            service=other_service,
            office=office,
            queue=matching_queue,
        )
    )
    wrong_queue = _custody_event(
        _ticket(
            basic_world,
            domain="operational",
            service=basic_world["gen_info"],
            office=office,
            queue=other_queue,
        )
    )
    scoped_staff = _staff_user(
        role_name="narrow-admin",
        role_scopes=[
            {
                "domain": "operational",
                "office": str(office.id),
                "service": str(basic_world["gen_info"].id),
                "queue": str(matching_queue.id),
            }
        ],
    )
    client.force_login(scoped_staff)

    listing = _get(client, reverse("admin:tickets_ticketcustodyevent_changelist"))

    assert listing.status_code == 200
    assert allowed.ticket.number in listing.content.decode()
    for event in (wrong_office, wrong_service, wrong_queue):
        assert event.ticket.number not in listing.content.decode()
        assert _get(client, _change_url(event)).status_code in {302, 404}


def test_custody_admin_changelist_counts_do_not_include_out_of_scope_rows(client, basic_world):
    ticket = _ticket(basic_world, domain="operational")
    created = _custody_event(ticket)
    record_custody_events(
        ticket=ticket,
        actor=CustodyActor.system("admin-test", "Admin test"),
        events=(
            CustodyEventInput(
                event_type="status_changed",
                source_process="test.admin",
            ),
        ),
    )[0]
    hidden = _custody_event(_ticket(basic_world, domain="it"))
    viewer = _staff_user(role_name="ops-agents")
    client.force_login(viewer)

    listing = _get(
        client,
        reverse("admin:tickets_ticketcustodyevent_changelist"),
        {"q": hidden.ticket.number, "event_type__exact": "created"},
    )
    changelist = listing.context["cl"]

    assert listing.status_code == 200
    assert changelist.result_count == 1
    assert changelist.full_result_count == 2
    assert list(changelist.queryset.values_list("pk", flat=True)) == [created.pk]


def test_custody_admin_changelist_query_count_does_not_grow_per_ticket(client, basic_world):
    viewer = _staff_user(role_name="ops-agents")
    client.force_login(viewer)
    changelist = reverse("admin:tickets_ticketcustodyevent_changelist")
    _custody_event(_ticket(basic_world, domain="operational"))

    with CaptureQueriesContext(connection) as one_row_queries:
        first_listing = _get(client, changelist)

    for _ in range(5):
        _custody_event(_ticket(basic_world, domain="operational"))
    with CaptureQueriesContext(connection) as multi_row_queries:
        multi_listing = _get(client, changelist)

    assert first_listing.status_code == 200
    assert multi_listing.status_code == 200
    assert multi_listing.context["cl"].result_count == 6
    assert len(multi_row_queries) <= 20
    assert len(multi_row_queries) <= len(one_row_queries) + 2
