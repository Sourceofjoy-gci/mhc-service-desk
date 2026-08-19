"""Pytest fixtures shared across the suite.

Pytest-django creates a fresh test database for each test run. We seed the
catalogue, workflow, SLA, contacts, and organisations so individual tests
have something to operate on.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from apps.catalogue.models import RequestType, Service
from apps.contacts.models import Contact
from apps.identity_access.models import Role, User
from apps.identity_access.staff_roles import STAFF_DESIGNATION_ROLE_KEYS
from apps.organisations.models import Office, Region
from apps.sla.seed_sla import seed_sla
from apps.tickets.models import Ticket
from apps.tickets.seed_workflow import seed_workflow
from apps.workflow.models import Status


@pytest.fixture
def basic_world(db):
    """A minimal but complete world for ticket-flow tests."""
    # Production migrations install the canonical staff-role catalogue. Most
    # unit tests intentionally construct their own role scopes, so remove only
    # those bootstrap rows before building an isolated test world.
    Role.objects.filter(keycloak_role__in=STAFF_DESIGNATION_ROLE_KEYS).delete()
    seed_workflow()
    seed_sla()

    region = Region.objects.create(code="TST", name="Test Region")
    office = Office.objects.create(region=region, code="TST-1", name="Test Office")

    gen_info = Service.objects.create(code="GEN-INFO", name="General info", domain="operational")
    it_inc = Service.objects.create(code="IT-INC", name="IT incident", domain="it")
    RequestType.objects.create(service=gen_info, code="HOURS", name="Hours", default_priority="P3")
    RequestType.objects.create(service=it_inc, code="OUTAGE", name="Outage", default_priority="P2")

    contact = Contact.objects.create(full_name="Tester", email="t@example.com")
    Role.objects.create(keycloak_role="ops-agents", name="Operational agent")

    return {
        "region": region,
        "office": office,
        "gen_info": gen_info,
        "it_inc": it_inc,
        "contact": contact,
    }


@pytest.fixture
def ticket_factory(basic_world):
    """Create a minimal valid operational ticket."""
    counter = {"n": 0}

    def _make(*, office=None, confidentiality="normal", **kwargs):
        counter["n"] += 1
        service = basic_world["gen_info"]
        return Ticket.objects.create(
            number=f"OFC-{counter['n']:05d}",
            domain="operational",
            title=f"Ticket {counter['n']}",
            status=Status.objects.get(domain="operational", code="new"),
            priority="P3",
            channel="web",
            requester=basic_world["contact"],
            service=service,
            request_type=service.request_types.get(),
            office=office if office is not None else basic_world["office"],
            confidentiality=confidentiality,
            **kwargs,
        )

    return _make


@pytest.fixture
def staff_user(basic_world):
    """Build a staff user based at an office.

    Office confinement is deny-by-default: a user with no office has no
    operational or IT authority. Tests that need working authority must have an
    office, so this factory assigns the seeded one unless told otherwise. Pass
    ``office=None`` explicitly to build an unassigned officer.
    """
    _unset = object()

    def _make(*, groups=(), office=_unset, station=None, **kwargs):
        group_list = list(groups)
        user = User.objects.create(
            username=kwargs.pop("username", f"user-{uuid4().hex}"),
            keycloak_subject=kwargs.pop("keycloak_subject", f"subject-{uuid4().hex}"),
            keycloak_groups=group_list,
            office=basic_world["office"] if office is _unset else office,
            station=station,
            **kwargs,
        )
        vars(user)["_groups"] = group_list
        return user

    return _make
