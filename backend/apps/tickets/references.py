"""Secure, transactional ticket-reference allocation."""

from __future__ import annotations

import re
from collections.abc import Mapping

from django.conf import settings
from django.db import IntegrityError, transaction

from .models import Ticket, TicketReferenceCounter

PREFIX_RE = re.compile(r"^[A-Z]$")
MAX_SEQUENCE = 99_999
GLOBAL_COUNTER_PERIOD = "GLOBAL"
COLLISION_RETRIES = 3


def validate_ticket_prefix(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Invalid ticket reference prefix configuration.")
    prefix = value.strip().upper()
    if not PREFIX_RE.fullmatch(prefix):
        raise ValueError("Invalid ticket reference prefix configuration.")
    return prefix


def configured_ticket_prefix(domain: str) -> str:
    if domain == Ticket.Domain.OPERATIONAL:
        setting_key = "TICKET_REFERENCE_PREFIX_OPERATIONAL"
    elif domain == Ticket.Domain.IT:
        setting_key = "TICKET_REFERENCE_PREFIX_IT"
    else:
        raise ValueError("Unsupported ticket reference domain.")
    return validate_ticket_prefix(settings.APP_CONFIG[setting_key])


def _existing_sequence_max(*, domain: str, prefix: str) -> int:
    pattern = re.compile(rf"^{re.escape(prefix)}([0-9]{{5}})$")
    return max(
        (
            int(match.group(1))
            for number in Ticket.objects.filter(
                domain=domain,
                number__startswith=prefix,
            ).values_list("number", flat=True)
            if (match := pattern.fullmatch(number))
        ),
        default=0,
    )


@transaction.atomic
def allocate_ticket_reference(*, domain: str) -> str:
    """Allocate the next global reference while holding its counter row lock."""

    prefix = configured_ticket_prefix(domain)
    scope = {
        "domain": domain,
        "prefix": prefix,
        "period": GLOBAL_COUNTER_PERIOD,
    }

    try:
        counter = TicketReferenceCounter.objects.select_for_update().get(**scope)
    except TicketReferenceCounter.DoesNotExist:
        existing_max = _existing_sequence_max(domain=domain, prefix=prefix)
        try:
            # Keep a concurrent first-use conflict inside a savepoint so the
            # surrounding ticket transaction remains usable.
            with transaction.atomic():
                counter = TicketReferenceCounter.objects.create(
                    **scope,
                    last_value=existing_max,
                )
        except IntegrityError:
            counter = TicketReferenceCounter.objects.select_for_update().get(**scope)

    if counter.last_value >= MAX_SEQUENCE:
        raise OverflowError("Ticket reference sequence exhausted.")

    counter.last_value += 1
    counter.save(update_fields=["last_value"])
    return f"{prefix}{counter.last_value:05d}"


@transaction.atomic
def create_referenced_ticket(
    *,
    domain: str,
    values: Mapping[str, object],
) -> Ticket:
    """Create a ticket, recovering only from a proven stale-counter collision."""

    for allocation_attempt in range(COLLISION_RETRIES):
        number = allocate_ticket_reference(domain=domain)
        try:
            with transaction.atomic():
                return Ticket.objects.create(
                    number=number,
                    domain=domain,
                    **dict(values),
                )
        except IntegrityError:
            number_already_exists = Ticket.objects.filter(number=number).exists()
            if allocation_attempt == COLLISION_RETRIES - 1 or not number_already_exists:
                raise
    raise RuntimeError("Ticket reference allocation did not terminate.")
