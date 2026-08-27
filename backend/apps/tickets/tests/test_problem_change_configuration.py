"""Problem/change catalogue precondition tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.catalogue.models import RequestType, Service
from apps.contacts.models import Contact
from apps.organisations.models import Office
from apps.tickets.models import Ticket
from apps.tickets.problem_change import ChangeManager, ProblemManager

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("basic_world")]


def _open_problem() -> Ticket:
    return ProblemManager.open_problem(
        title="Repeated outage",
        description="Investigate recurrence",
        opened_by="problem-manager",
    )


def _open_change() -> Ticket:
    return ChangeManager.open_change(
        title="Upgrade network",
        description="Apply the approved maintenance release",
        scheduled_at=datetime(2026, 8, 1, 20, 0, tzinfo=UTC),
        risk="medium",
        opened_by="change-manager",
    )


@pytest.mark.parametrize(
    ("missing", "expected_detail"),
    [
        ("service", "IT incident service IT-INC"),
        ("request_type", "OUTAGE request type"),
        ("office", "active office"),
    ],
)
@pytest.mark.parametrize(
    ("open_record", "manager_email"),
    [
        (_open_problem, "problems@mhc.local"),
        (_open_change, "changes@mhc.local"),
    ],
)
def test_manager_rejects_incomplete_catalogue_before_creating_contact(
    missing: str,
    expected_detail: str,
    open_record: Callable[[], Ticket],
    manager_email: str,
) -> None:
    """Removing a required record must fail clearly without a partial contact."""
    if missing == "service":
        Service.objects.filter(domain="it", code="IT-INC").delete()
    elif missing == "request_type":
        RequestType.objects.filter(
            service__domain="it",
            service__code="IT-INC",
            code="OUTAGE",
        ).delete()
    else:
        Office.objects.filter(is_active=True).delete()

    with pytest.raises(ImproperlyConfigured, match=expected_detail):
        open_record()

    assert not Contact.objects.filter(email=manager_email).exists()
