"""Pytest fixtures shared across the suite.

Pytest-django creates a fresh test database for each test run. We seed the
catalogue, workflow, SLA, contacts, and organisations so individual tests
have something to operate on.
"""

from __future__ import annotations

import pytest

from apps.catalogue.models import RequestType, Service
from apps.contacts.models import Contact
from apps.identity_access.models import Role
from apps.identity_access.staff_roles import STAFF_DESIGNATION_ROLE_KEYS
from apps.organisations.models import Office, Region
from apps.sla.seed_sla import seed_sla
from apps.tickets.seed_workflow import seed_workflow


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
