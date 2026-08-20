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


@pytest.fixture
def migrations():
    """Drive migrations inside a test and always restore the schema afterwards.

    A test that rolls an app backwards must return it to its leaf. If it does
    not, every later test in the *whole session* runs against the rolled-back
    schema — and the failures surface in unrelated packages, far from the cause.
    That is exactly how a stale hardcoded restore target once cost 55 failures.

    Naming the leaf in the test goes stale the moment a migration is added, so
    this resolves it from the migration graph and restores on teardown. No test
    needs its own ``finally``, and the teardown assertion turns a silent
    session-wide poisoning into a loud failure in the test that caused it.

    Usage::

        def test_something(migrations):
            old = migrations.migrate("sla", "0004_backfill_paused_business_seconds")
            ...
            new = migrations.migrate_to_leaf("sla")
    """
    from types import SimpleNamespace

    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    touched: set[str] = set()

    def _leaf(app_label: str) -> list[tuple[str, str]]:
        return MigrationExecutor(connection).loader.graph.leaf_nodes(app_label)

    def _apply(app_label: str, target: list[tuple[str, str]]):
        touched.add(app_label)
        # A fresh executor per call: the loader caches migration state, so a
        # reused one reports the schema as it was before the previous migrate.
        executor = MigrationExecutor(connection)
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    def migrate(app_label: str, name: str):
        """Migrate one app to a named migration; return that state's app registry."""
        return _apply(app_label, [(app_label, name)])

    def migrate_to_leaf(app_label: str):
        """Migrate one app forward to its current leaf; return its app registry."""
        return _apply(app_label, _leaf(app_label))

    yield SimpleNamespace(migrate=migrate, migrate_to_leaf=migrate_to_leaf, leaf=_leaf)

    if not touched:
        return

    # Rolling one app backwards cascades into every app that depends on it —
    # unapplying a tickets migration also unapplies workflow migrations built on
    # top of it. Restoring only the apps this test named would leave those
    # dependants stranded, so restore the whole project to its leaves.
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())

    executor = MigrationExecutor(connection)
    outstanding = executor.migration_plan(executor.loader.graph.leaf_nodes())
    assert not outstanding, (
        "The schema could not be restored to its leaf migrations after this "
        f"test. Outstanding plan: {outstanding}"
    )


@pytest.fixture(scope="session", autouse=True)
def _schema_left_at_leaf(django_db_setup, django_db_blocker):
    """Fail the run if any test left an app off its leaf migration.

    Tests that drive ``MigrationExecutor`` roll the real schema backwards. If
    one does not roll it forward again, every later test in the session runs
    against the rolled-back schema, and the failures land in unrelated packages
    with no obvious connection to the cause — 55 of them, on the occasion that
    prompted this guard.

    The ``migrations`` fixture prevents that for tests which use it. This net
    catches it however it happens, including a hand-rolled executor with a
    stale hardcoded restore target, which is the exact shape of the original
    defect. Session-scoped, so it costs one query per run rather than per test.
    """
    yield

    with django_db_blocker.unblock():
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        graph = executor.loader.graph
        stranded: dict[str, list[str]] = {}
        for app_label in sorted({node[0] for node in graph.nodes}):
            plan = executor.migration_plan(graph.leaf_nodes(app_label))
            if plan:
                stranded[app_label] = [f"{m.app_label}.{m.name}" for m, _ in plan]

    assert not stranded, (
        "The test session finished with these apps off their leaf migration, so "
        "some test rolled the schema back and did not restore it: "
        f"{stranded}. Use the 'migrations' fixture, which restores on teardown "
        "and resolves the leaf from the graph instead of hardcoding its name."
    )
