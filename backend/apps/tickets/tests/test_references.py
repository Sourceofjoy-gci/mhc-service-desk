from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connection
from django.test import override_settings

from apps.catalogue.models import RequestType, Service
from apps.contacts.models import Contact
from apps.organisations.models import Office
from apps.tickets import services
from apps.tickets.checks import check_ticket_reference_prefixes
from apps.tickets.models import Ticket, TicketReferenceCounter
from apps.tickets.references import allocate_ticket_reference, validate_ticket_prefix
from apps.workflow.models import Status


def _create_from_ids(world_ids: dict[str, str], title: str) -> str:
    close_old_connections()
    try:
        return services.create_ticket(
            domain="operational",
            title=title,
            description="",
            requester=Contact.objects.get(pk=world_ids["contact"]),
            service=Service.objects.get(pk=world_ids["service"]),
            request_type=RequestType.objects.get(pk=world_ids["request_type"]),
            office=Office.objects.get(pk=world_ids["office"]),
            channel="call",
        ).number
    finally:
        close_old_connections()


@pytest.mark.django_db
@override_settings(
    APP_CONFIG={
        "TICKET_REFERENCE_PREFIX_OPERATIONAL": " o ",
        "TICKET_REFERENCE_PREFIX_IT": "I",
    }
)
def test_ticket_reference_is_one_letter_and_five_digits_with_a_global_sequence(
    basic_world,
):
    request_type = basic_world["gen_info"].request_types.get()
    Ticket.objects.create(
        number="O00041",
        domain="operational",
        title="Legacy current-month ticket",
        status=Status.objects.get(domain="operational", code="new"),
        channel="call",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=request_type,
        office=basic_world["office"],
    )

    ticket = services.create_ticket(
        domain="operational",
        title="Next ticket",
        description="",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=request_type,
        office=basic_world["office"],
        channel="call",
    )

    assert ticket.number == "O00042"
    assert len(ticket.number) == 6
    assert ticket.number[0].isalpha()
    assert ticket.number[1:].isdigit()
    assert (
        TicketReferenceCounter.objects.get(
            domain="operational", prefix="O", period="GLOBAL"
        ).last_value
        == 42
    )


@pytest.mark.parametrize(
    "value",
    ["", None, True, 123, "OP", "1", "O1", "-", "!"],
)
def test_invalid_ticket_prefix_is_rejected(value):
    with pytest.raises(ValueError, match="ticket reference prefix"):
        validate_ticket_prefix(value)


@pytest.mark.django_db
@override_settings(
    APP_CONFIG={
        "TICKET_REFERENCE_PREFIX_OPERATIONAL": "OP",
        "TICKET_REFERENCE_PREFIX_IT": "I",
    }
)
def test_invalid_configured_prefix_is_reported_by_system_check():
    errors = check_ticket_reference_prefixes(None)

    assert [error.id for error in errors] == ["tickets.E001"]


@pytest.mark.django_db
@override_settings(
    APP_CONFIG={
        "TICKET_REFERENCE_PREFIX_OPERATIONAL": "o",
        "TICKET_REFERENCE_PREFIX_IT": " O ",
    }
)
def test_duplicate_domain_prefixes_are_reported_by_system_check():
    errors = check_ticket_reference_prefixes(None)

    assert [error.id for error in errors] == ["tickets.E003"]


@pytest.mark.django_db
def test_exhausted_global_sequence_fails_without_changing_the_counter():
    TicketReferenceCounter.objects.create(
        domain="operational", prefix="O", period="GLOBAL", last_value=99_999
    )

    with pytest.raises(OverflowError, match="sequence exhausted"):
        allocate_ticket_reference(domain="operational")

    assert (
        TicketReferenceCounter.objects.get(
            domain="operational", prefix="O", period="GLOBAL"
        ).last_value
        == 99_999
    )


@pytest.mark.django_db
def test_ticket_creation_recovers_from_a_stale_counter_collision(
    basic_world,
):
    request_type = basic_world["gen_info"].request_types.get()
    base = {
        "domain": "operational",
        "status": Status.objects.get(domain="operational", code="new"),
        "channel": "call",
        "requester": basic_world["contact"],
        "service": basic_world["gen_info"],
        "request_type": request_type,
        "office": basic_world["office"],
    }
    Ticket.objects.create(number="O00001", title="Existing collision", **base)
    TicketReferenceCounter.objects.create(
        domain="operational", prefix="O", period="GLOBAL", last_value=0
    )

    created = services.create_ticket(
        title="Recovered allocation",
        description="",
        **{key: value for key, value in base.items() if key != "status"},
    )

    assert created.number == "O00002"


@pytest.mark.django_db
def test_failed_ticket_creation_rolls_back_its_reference(basic_world):
    request_type = basic_world["gen_info"].request_types.get()
    create = {
        "domain": "operational",
        "title": "Rolled back",
        "description": "",
        "requester": basic_world["contact"],
        "service": basic_world["gen_info"],
        "request_type": request_type,
        "office": basic_world["office"],
        "channel": "call",
    }
    with patch(
        "apps.tickets.services.record_ticket_event",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(RuntimeError, match="audit unavailable"):
            services.create_ticket(**create)

    assert TicketReferenceCounter.objects.count() == 0
    assert services.create_ticket(**{**create, "title": "Committed"}).number == "O00001"


@pytest.mark.django_db(transaction=True)
def test_concurrent_ticket_creation_allocates_two_distinct_references(basic_world):
    if connection.vendor != "postgresql":
        pytest.skip("This row-lock regression requires PostgreSQL.")
    request_type = basic_world["gen_info"].request_types.get()
    ids = {
        "contact": str(basic_world["contact"].pk),
        "service": str(basic_world["gen_info"].pk),
        "request_type": str(request_type.pk),
        "office": str(basic_world["office"].pk),
    }

    with ThreadPoolExecutor(max_workers=2) as pool:
        numbers = list(pool.map(lambda title: _create_from_ids(ids, title), ("One", "Two")))

    assert len(numbers) == len(set(numbers)) == 2
    assert sorted(numbers) == ["O00001", "O00002"]
