# Secure Ticket Reference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate immutable, configurable, collision-free ticket references and give authenticated, scope-authorised helpdesk staff a focused ticket-tracking page with the required lifecycle vocabulary and auditable escalation.

**Architecture:** A row-locked `TicketReferenceCounter` allocates monthly sequences inside the ticket creation transaction, while ORM and PostgreSQL guards make `Ticket.number` write-once. A focused tracking domain service maps the richer workflow and immutable custody history to nine stable progress states; a scoped DRF collection action exposes only that summary to a protected React page.

**Tech Stack:** Python 3.12, Django, Django REST Framework, PostgreSQL, pytest/pytest-django, React 18, TypeScript, React Router, TanStack Query, Vitest, Testing Library, Tailwind/shadcn components.

## Global Constraints

- Tracking remains restricted to authenticated helpdesk staff and must use the existing ticket scope rules.
- No public ticket lookup route or unauthenticated requester-tracking API may be introduced.
- New references use `<PREFIX>-<YYYYMM>-<SEQUENCE>` with a six-digit sequence.
- `TICKET_REFERENCE_PREFIX_OPERATIONAL` defaults to `OP`; `TICKET_REFERENCE_PREFIX_IT` defaults to `IT`.
- Prefixes must match `[A-Z][A-Z0-9]{1,7}` after trimming and uppercasing.
- Existing references remain unchanged and searchable.
- Tracking output contains no requester contact details, internal notes, transition reasons, actor identifiers, or attachment metadata.
- Tracking statuses are exactly Submitted, Acknowledged, Assigned, In Progress, Awaiting Information, Escalated, Resolved, Closed, and Reopened.
- Preserve the existing richer internal workflow and scope-aware queue search.
- Preserve all pre-existing worktree changes. Relevant backend and frontend files are already modified; do not stage or commit an existing file unless its complete staged diff has been proven task-owned.
- Follow strict red-green-refactor: each production change begins with a focused failing test whose failure is observed.

## File Responsibility Map

- `backend/apps/tickets/references.py`: prefix validation, legacy sequence discovery, and locked reference allocation.
- `backend/apps/tickets/checks.py`: startup/system-check validation for both configured prefixes.
- `backend/apps/tickets/tracking.py`: stable tracking-status mapping and requester-safe progress projection.
- `backend/apps/tickets/models.py`: counter schema plus ORM immutability boundaries.
- `backend/apps/tickets/services.py`: normal ticket creation integration and creation audit payload.
- `backend/apps/tickets/it_child.py`: IT child creation integration and creation audit payload.
- `backend/apps/tickets/custody.py`: escalation custody event classification.
- `backend/apps/tickets/seed_workflow.py`: operational and IT Escalated status/transitions.
- `backend/apps/workflow/shortcuts.py`: focused workflow fixtures used by service tests.
- `backend/apps/tickets/api.py`: tracking input/output serializers.
- `backend/apps/tickets/views.py`: authenticated, scope-aware tracking collection action.
- `backend/config/settings/base.py`, `.env.example`: deploy-time prefix configuration.
- `backend/apps/tickets/migrations/0011_ticketreferencecounter.py`: counter table.
- `backend/apps/tickets/migrations/0012_ticket_reference_immutable.py`: PostgreSQL write-once trigger.
- `backend/apps/tickets/migrations/0013_escalated_workflow.py`: existing-database workflow data.
- `frontend/src/lib/api.ts`: tracking TypeScript contract and client request.
- `frontend/src/features/tickets/TicketTrackingPage.tsx`: protected lookup form and progress summary.
- `frontend/src/app/App.tsx`, `frontend/src/components/app-shell.tsx`: protected route and staff navigation.
- `frontend/src/features/tickets/ChannelIntakePage.tsx`: reference confirmation, copy, and tracking link.
- Matching `test_*.py` and `*.test.tsx` files prove each boundary through observable behavior.

---

### Task 1: Atomic, Configurable Reference Allocation

**Files:**
- Create: `backend/apps/tickets/references.py`
- Create: `backend/apps/tickets/checks.py`
- Create: `backend/apps/tickets/tests/test_references.py`
- Create: `backend/apps/tickets/migrations/0011_ticketreferencecounter.py`
- Modify: `backend/apps/tickets/models.py:15-145`
- Modify: `backend/apps/tickets/apps.py`
- Modify: `backend/apps/tickets/services.py:1-185`
- Modify: `backend/apps/tickets/it_child.py:105-160`
- Modify: `backend/config/settings/base.py:321-331`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `Ticket.Domain`, `Ticket.number`, Django settings `APP_CONFIG`, and the existing outer `transaction.atomic()` creation services.
- Produces: `validate_ticket_prefix(value: object) -> str`, `allocate_ticket_reference(*, domain: str, when: datetime | None = None) -> str`, and `create_referenced_ticket(*, domain: str, values: Mapping[str, object]) -> Ticket`; model `TicketReferenceCounter(domain, prefix, period, last_value)` with unique `(domain, prefix, period)`.

- [ ] **Step 1: Write failing prefix, legacy-seed, rollback, and concurrency tests**

Create `backend/apps/tickets/tests/test_references.py` with literal expectations. Reuse `basic_world`; for threaded creation, pass database IDs into each worker and refetch rows on that worker's connection.

```python
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connection
from django.test import override_settings

from apps.catalogue.models import RequestType, Service
from apps.contacts.models import Contact
from apps.organisations.models import Office
from apps.tickets import services
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
@override_settings(APP_CONFIG={"TICKET_REFERENCE_PREFIX_OPERATIONAL": " mhc ", "TICKET_REFERENCE_PREFIX_IT": "IT"})
def test_ticket_reference_uses_configured_prefix_and_existing_month_max(
    basic_world, monkeypatch
):
    monkeypatch.setattr(
        "apps.tickets.references.timezone.now",
        lambda: datetime(2026, 8, 2, tzinfo=UTC),
    )
    request_type = basic_world["gen_info"].request_types.get()
    Ticket.objects.create(
        number="MHC-202608-000041",
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

    assert ticket.number == "MHC-202608-000042"
    assert TicketReferenceCounter.objects.get(
        domain="operational", prefix="MHC", period="202608"
    ).last_value == 42


@pytest.mark.parametrize("value", ["", "1OP", "OP-HELP", "TOO-LONG9", "OP!"])
def test_invalid_ticket_prefix_is_rejected(value):
    with pytest.raises(ValueError, match="ticket reference prefix"):
        validate_ticket_prefix(value)


@pytest.mark.django_db
def test_exhausted_monthly_sequence_fails_without_changing_the_counter():
    TicketReferenceCounter.objects.create(
        domain="operational", prefix="OP", period="202608", last_value=999_999
    )
    with pytest.raises(OverflowError, match="sequence exhausted"):
        allocate_ticket_reference(
            domain="operational", when=datetime(2026, 8, 2, tzinfo=UTC)
        )
    assert TicketReferenceCounter.objects.get(
        domain="operational", prefix="OP", period="202608"
    ).last_value == 999_999


@pytest.mark.django_db
def test_ticket_creation_recovers_from_a_stale_counter_collision(
    basic_world, monkeypatch
):
    monkeypatch.setattr(
        "apps.tickets.references.timezone.now",
        lambda: datetime(2026, 8, 2, tzinfo=UTC),
    )
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
    Ticket.objects.create(
        number="OP-202608-000001", title="Existing collision", **base
    )
    TicketReferenceCounter.objects.create(
        domain="operational", prefix="OP", period="202608", last_value=0
    )

    created = services.create_ticket(
        title="Recovered allocation",
        description="",
        **{key: value for key, value in base.items() if key != "status"},
    )

    assert created.number == "OP-202608-000002"


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
    assert services.create_ticket(**{**create, "title": "Committed"}).number.endswith(
        "-000001"
    )


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
    assert sorted(int(number.rsplit("-", 1)[1]) for number in numbers) == [1, 2]
```

- [ ] **Step 2: Run the new tests and observe the intended failures**

Run:

```powershell
docker compose exec backend pytest apps/tickets/tests/test_references.py -q
```

Expected: collection fails because `TicketReferenceCounter`, `references.py`, and the configured allocator do not exist. After creating only import scaffolding, the behavior tests must still fail because the old allocator ignores settings and uses `count() + 1`.

- [ ] **Step 3: Add environment-backed prefix settings and the counter model**

Change `APP_CONFIG` in `backend/config/settings/base.py` to include:

```python
"TICKET_REFERENCE_PREFIX_OPERATIONAL": env(
    "TICKET_REFERENCE_PREFIX_OPERATIONAL", default="OP"
),
"TICKET_REFERENCE_PREFIX_IT": env("TICKET_REFERENCE_PREFIX_IT", default="IT"),
```

Add both variables to `.env.example`. Add this model to `backend/apps/tickets/models.py`:

```python
class TicketReferenceCounter(models.Model):
    domain = models.CharField(max_length=16, choices=Ticket.Domain.choices)
    prefix = models.CharField(max_length=8)
    period = models.CharField(max_length=6)
    last_value = models.PositiveBigIntegerField(default=0)

    class Meta:
        db_table = "ticket_reference_counter"
        constraints = [
            models.UniqueConstraint(
                fields=("domain", "prefix", "period"),
                name="uniq_ticket_reference_counter_scope",
            )
        ]
```

Generate `0011_ticketreferencecounter.py` with:

```powershell
docker compose exec backend python manage.py makemigrations tickets --name ticketreferencecounter
```

Add `backend/apps/tickets/checks.py` with `check_ticket_reference_prefixes()` registered under Django's security checks. It calls `validate_ticket_prefix()` for both configured domain keys and returns `checks.Error` IDs `tickets.E001` and `tickets.E002` respectively. Import the checks module from `TicketsConfig.ready()` so `python manage.py check` executes it. Add a test that overrides one invalid prefix, calls the check function directly, and asserts the one matching error ID.

- [ ] **Step 4: Implement the locked allocator in `references.py`**

Use one validation path and literal parsing of existing references. Import `IntegrityError` and `transaction` from `django.db`:

```python
PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]{1,7}$")


def validate_ticket_prefix(value: object) -> str:
    prefix = str(value).strip().upper()
    if not PREFIX_RE.fullmatch(prefix):
        raise ValueError("Invalid ticket reference prefix configuration.")
    return prefix


def configured_ticket_prefix(domain: str) -> str:
    if domain == Ticket.Domain.OPERATIONAL:
        key = "TICKET_REFERENCE_PREFIX_OPERATIONAL"
    elif domain == Ticket.Domain.IT:
        key = "TICKET_REFERENCE_PREFIX_IT"
    else:
        raise ValueError("Unsupported ticket reference domain.")
    return validate_ticket_prefix(settings.APP_CONFIG[key])


@transaction.atomic
def allocate_ticket_reference(*, domain: str, when: datetime | None = None) -> str:
    instant = when or timezone.now()
    prefix = configured_ticket_prefix(domain)
    period = instant.strftime("%Y%m")
    scope = {"domain": domain, "prefix": prefix, "period": period}
    try:
        counter = TicketReferenceCounter.objects.select_for_update().get(**scope)
    except TicketReferenceCounter.DoesNotExist:
        existing_pattern = re.compile(rf"^{re.escape(prefix)}-{period}-(\d{{6}})$")
        existing_max = max(
            (
                int(match.group(1))
                for number in Ticket.objects.filter(
                    domain=domain, number__startswith=f"{prefix}-{period}-"
                ).values_list("number", flat=True)
                if (match := existing_pattern.fullmatch(number))
            ),
            default=0,
        )
        try:
            with transaction.atomic():
                counter = TicketReferenceCounter.objects.create(
                    **scope, last_value=existing_max
                )
        except IntegrityError:
            counter = TicketReferenceCounter.objects.select_for_update().get(**scope)
    if counter.last_value >= 999_999:
        raise OverflowError("Ticket reference sequence exhausted for this period.")
    counter.last_value += 1
    counter.save(update_fields=["last_value"])
    return f"{prefix}-{period}-{counter.last_value:06d}"
```

Keep the unique-conflict handling inside a nested savepoint so concurrent first use waits for and refetches the winning row. Retry only that counter-row insert race; do not retry arbitrary ticket creation failures.

- [ ] **Step 5: Route every ticket creation path through the allocator**

Add this shared row-creation helper to `references.py`. It retries at most three allocations only when the failed number now exists and re-raises every other `IntegrityError`. This bounded recovery covers a stale/corrupt counter without swallowing foreign-key or other integrity failures.

```python
@transaction.atomic
def create_referenced_ticket(
    *, domain: str, values: Mapping[str, object]
) -> Ticket:
    for allocation_attempt in range(3):
        number = allocate_ticket_reference(domain=domain)
        try:
            with transaction.atomic():
                return Ticket.objects.create(number=number, domain=domain, **values)
        except IntegrityError:
            if (
                allocation_attempt == 2
                or not Ticket.objects.filter(number=number).exists()
            ):
                raise
    raise RuntimeError("Ticket reference allocation did not terminate.")
```

In `services.create_ticket`, pass its existing `Ticket.objects.create` keyword fields as the `values` mapping to `create_referenced_ticket()`. Remove `NumberingConfig` and the count-based implementation; retain a compatibility wrapper only if a remaining caller is found by `rg -n "next_ticket_number" backend/apps`.

In `create_it_child_ticket`, pass the existing child row fields to `create_referenced_ticket()` inside its outer atomic transaction. Add `"reference": ticket.number` or `"reference": child.number` to the normal and IT-child `ticket.created` `after` payloads. Do not change existing references or any serializer input.

- [ ] **Step 6: Run allocator and affected creation tests**

Run:

```powershell
docker compose exec backend pytest apps/tickets/tests/test_references.py apps/tickets/tests/test_services.py apps/tickets/tests/test_it_child.py apps/tickets/tests/test_intake_api.py -q
```

Expected: all selected tests pass; the concurrency test reports two distinct sequences on PostgreSQL.

- [ ] **Step 7: Verify the migration boundary**

Run:

```powershell
docker compose exec backend python manage.py makemigrations --check --dry-run
docker compose exec backend python manage.py migrate --plan
```

Expected: no uncommitted model changes; the plan lists `tickets.0011_ticketreferencecounter` once.

- [ ] **Step 8: Review the task diff and create a task commit only if safe**

Run `git diff -- backend/apps/tickets/references.py backend/apps/tickets/tests/test_references.py backend/apps/tickets/models.py backend/apps/tickets/services.py backend/apps/tickets/it_child.py backend/config/settings/base.py .env.example backend/apps/tickets/migrations/0011_ticketreferencecounter.py`. Because several listed files had pre-existing edits before this plan, leave the task unstaged if the complete diff contains non-task hunks. If every staged hunk is proven task-owned, use commit message `feat(tickets): allocate references atomically`.

---

### Task 2: Enforce Write-Once References

**Files:**
- Create: `backend/apps/tickets/migrations/0012_ticket_reference_immutable.py`
- Modify: `backend/apps/tickets/models.py:15-155`
- Modify: `backend/apps/tickets/tests/test_integrity_boundaries.py`

**Interfaces:**
- Consumes: `Ticket.number` assigned during Task 1.
- Produces: ORM validation for `save`, `update`, and `bulk_update`, plus PostgreSQL trigger `ticket_number_immutable`.

- [ ] **Step 1: Write failing ORM and raw-SQL mutation tests**

Import `ValidationError`, `DatabaseError`, `connection`, and `transaction`, then add tests that preserve the original reference after each attempted mutation:

```python
def test_ticket_reference_rejects_instance_and_queryset_mutation(basic_world):
    ticket = _ticket(basic_world)
    original = ticket.number
    ticket.number = "OP-209901-999999"
    with pytest.raises(ValidationError, match="reference is immutable"):
        ticket.save(update_fields=["number"])
    with pytest.raises(ValidationError, match="reference is immutable"):
        Ticket.objects.filter(pk=ticket.pk).update(number="OP-209901-999999")
    ticket.refresh_from_db()
    assert ticket.number == original


@pytest.mark.django_db(transaction=True)
def test_database_rejects_raw_ticket_reference_mutation(basic_world):
    ticket = _ticket(basic_world)
    if connection.vendor != "postgresql":
        pytest.skip("The database immutability trigger is PostgreSQL-specific.")
    original = ticket.number
    with pytest.raises(DatabaseError, match="ticket reference is immutable"):
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "UPDATE ticket SET number = %s WHERE id = %s",
                ["OP-209901-999999", ticket.pk],
            )
    ticket.refresh_from_db()
    assert ticket.number == original
```

Use the file's existing ticket fixture/helper rather than introducing a second domain world.

- [ ] **Step 2: Run the focused tests and observe mutation succeeding or reaching the database**

Run:

```powershell
docker compose exec backend pytest apps/tickets/tests/test_integrity_boundaries.py -k "reference" -q
```

Expected: failures show that current instance/queryset/raw SQL updates can change `number`.

- [ ] **Step 3: Add ORM guards without blocking unrelated updates**

Extend `ProtectedTicketQuerySet`:

```python
def update(self, **kwargs: object) -> int:
    if "number" in kwargs:
        raise ValidationError("Ticket reference is immutable.")
    return super().update(**kwargs)


def bulk_update(self, objs, fields, batch_size=None):
    if "number" in fields:
        raise ValidationError("Ticket reference is immutable.")
    return super().bulk_update(objs, fields, batch_size=batch_size)
```

Track the loaded value on `Ticket.from_db()` and reject a changed value in `Ticket.save()` before issuing SQL. After a successful initial insert, record the allocated value as the loaded value. A partially constructed existing instance without a loaded value must compare against a one-column database query.

```python
@classmethod
def from_db(cls, db, field_names, values):
    instance = super().from_db(db, field_names, values)
    if "number" in field_names:
        instance._loaded_ticket_number = instance.number
    return instance


def save(self, *args: object, **kwargs: object) -> None:
    if not self._state.adding:
        loaded = getattr(self, "_loaded_ticket_number", None)
        if loaded is None:
            loaded = type(self).objects.only("number").get(pk=self.pk).number
        if self.number != loaded:
            raise ValidationError("Ticket reference is immutable.")
    super().save(*args, **kwargs)
    self._loaded_ticket_number = self.number
```

- [ ] **Step 4: Add the PostgreSQL write-once trigger migration**

Create a vendor-aware `RunPython` migration following `0006_backfill_ticket_custody.py`:

```sql
CREATE OR REPLACE FUNCTION reject_ticket_number_mutation()
RETURNS trigger AS $$
BEGIN
  IF NEW.number IS DISTINCT FROM OLD.number THEN
    RAISE EXCEPTION 'ticket reference is immutable';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ticket_number_immutable
BEFORE UPDATE OF number ON ticket
FOR EACH ROW EXECUTE FUNCTION reject_ticket_number_mutation();
```

The reverse function drops the trigger and function with `IF EXISTS`. Return without SQL on non-PostgreSQL connections.

- [ ] **Step 5: Run integrity and creation regressions**

Run:

```powershell
docker compose exec backend pytest apps/tickets/tests/test_integrity_boundaries.py apps/tickets/tests/test_references.py apps/tickets/tests/test_services.py -q
```

Expected: mutation attempts fail, unrelated `Ticket.objects.update(created_at=...)` tests still pass, and ticket creation remains green.

- [ ] **Step 6: Review and conditionally commit**

Inspect the complete diff for the three task paths. If staging would include pre-existing changes, leave it unstaged. Otherwise commit with `feat(tickets): make references immutable`.

---

### Task 3: Stable Tracking Statuses and Audited Escalation

**Files:**
- Create: `backend/apps/tickets/tracking.py`
- Create: `backend/apps/tickets/tests/test_tracking.py`
- Create: `backend/apps/tickets/migrations/0013_escalated_workflow.py`
- Modify: `backend/apps/tickets/custody.py:399-405`
- Modify: `backend/apps/tickets/seed_workflow.py`
- Modify: `backend/apps/workflow/shortcuts.py`
- Modify: `backend/apps/tickets/tests/test_transition_api.py`

**Interfaces:**
- Consumes: `Status`, `TransitionHistory`, and `TicketCustodyEvent`.
- Produces: `TrackingStatus` string enum, `tracking_status_for(status: Status | Mapping[str, object]) -> TrackingStatus`, and `build_tracking_progress(ticket: Ticket) -> list[TrackingProgressItem]` where each item contains only `status` and `occurred_at`.

- [ ] **Step 1: Write failing mapping and collapse tests**

Use literal table cases for every requested state:

```python
@pytest.fixture
def tracking_ticket(basic_world):
    ticket = services.create_ticket(
        domain="operational",
        title="Tracking projection",
        description="",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
        channel="call",
    )
    previous = Status.objects.get(domain="operational", code="new")
    for code in ("triage", "in_progress", "quality_review"):
        target = Status.objects.get(domain="operational", code=code)
        TransitionHistory.objects.create(
            ticket=ticket,
            from_status=previous,
            to_status=target,
            actor_subject="tracking-agent",
        )
        previous = target
    return ticket


@pytest.mark.parametrize(
    ("code", "terminal", "expected"),
    [
        ("new", False, "Submitted"),
        ("triage", False, "Acknowledged"),
        ("assigned", False, "Assigned"),
        ("diagnosing", False, "In Progress"),
        ("waiting_requester", False, "Awaiting Information"),
        ("escalated", False, "Escalated"),
        ("resolved", False, "Resolved"),
        ("closed", True, "Closed"),
        ("duplicate", True, "Closed"),
        ("reopened", False, "Reopened"),
    ],
)
def test_tracking_status_mapping_is_stable(code, terminal, expected):
    assert tracking_status_for({"code": code, "is_terminal": terminal}) == expected


def test_tracking_progress_collapses_adjacent_internal_states_without_leaking_details(
    tracking_ticket,
):
    ticket = tracking_ticket
    created = ticket.custody_events.get(sequence=1)
    progress = build_tracking_progress(ticket)
    assert progress == [
        {"status": "Submitted", "occurred_at": created.occurred_at},
        {"status": "Acknowledged", "occurred_at": ticket.transition_history.get(to_status__code="triage").occurred_at},
        {"status": "In Progress", "occurred_at": ticket.transition_history.get(to_status__code="in_progress").occurred_at},
    ]
    assert all(set(item) == {"status", "occurred_at"} for item in progress)
```

Build the test ticket with New → Triage → In Progress → Quality Review so the final two internal states prove adjacent collapse to one In Progress milestone using the earliest occurrence of that run.

- [ ] **Step 2: Run the tracking tests and observe missing-module failures**

Run:

```powershell
docker compose exec backend pytest apps/tickets/tests/test_tracking.py -q
```

Expected: collection fails because `apps.tickets.tracking` does not exist.

- [ ] **Step 3: Implement the exact mapping and safe progress projection**

Define:

```python
class TrackingStatus(StrEnum):
    SUBMITTED = "Submitted"
    ACKNOWLEDGED = "Acknowledged"
    ASSIGNED = "Assigned"
    IN_PROGRESS = "In Progress"
    AWAITING_INFORMATION = "Awaiting Information"
    ESCALATED = "Escalated"
    RESOLVED = "Resolved"
    CLOSED = "Closed"
    REOPENED = "Reopened"


class TrackingProgressItem(TypedDict):
    status: TrackingStatus
    occurred_at: datetime
```

Map `new`, `triage`, `assigned`, all active work/review codes, all `waiting_*` codes, `escalated`, `resolved`, terminal outcomes, and `reopened`. Unknown terminal statuses map to Closed; unknown active statuses map to In Progress so output never escapes the nine-value contract.

Build milestones from custody events with `new_status`, merge legacy `TransitionHistory` rows not represented by a custody `source_record_id`, order by `(occurred_at, stable id)`, then collapse adjacent identical tracking statuses. Do not include actor or reason keys.

```python
TRACKING_BY_CODE = {
    "new": TrackingStatus.SUBMITTED,
    "triage": TrackingStatus.ACKNOWLEDGED,
    "assigned": TrackingStatus.ASSIGNED,
    "in_progress": TrackingStatus.IN_PROGRESS,
    "diagnosing": TrackingStatus.IN_PROGRESS,
    "quality_review": TrackingStatus.IN_PROGRESS,
    "validation": TrackingStatus.IN_PROGRESS,
    "escalated": TrackingStatus.ESCALATED,
    "resolved": TrackingStatus.RESOLVED,
    "reopened": TrackingStatus.REOPENED,
    "closed": TrackingStatus.CLOSED,
    "cancelled": TrackingStatus.CLOSED,
    "rejected": TrackingStatus.CLOSED,
    "duplicate": TrackingStatus.CLOSED,
    "spam": TrackingStatus.CLOSED,
}


def tracking_status_for(status: Status | Mapping[str, object]) -> TrackingStatus:
    code = status.code if isinstance(status, Status) else str(status.get("code", ""))
    terminal = (
        status.is_terminal
        if isinstance(status, Status)
        else bool(status.get("is_terminal", False))
    )
    if code.startswith("waiting_"):
        return TrackingStatus.AWAITING_INFORMATION
    return TRACKING_BY_CODE.get(
        code,
        TrackingStatus.CLOSED if terminal else TrackingStatus.IN_PROGRESS,
    )


def build_tracking_progress(ticket: Ticket) -> list[TrackingProgressItem]:
    status_terminal = dict(
        Status.objects.filter(domain=ticket.domain).values_list("code", "is_terminal")
    )
    represented_transition_ids: set[str] = set()
    milestones: list[tuple[datetime, str, TrackingStatus]] = []
    for event in ticket.custody_events.all():
        if event.source_record_type == "workflow_transition" and event.source_record_id:
            represented_transition_ids.add(event.source_record_id)
        if not event.new_status or not event.new_status.get("code"):
            continue
        code = str(event.new_status["code"])
        milestones.append(
            (
                event.occurred_at,
                f"custody:{event.sequence:020d}:{event.pk}",
                tracking_status_for(
                    {"code": code, "is_terminal": status_terminal.get(code, False)}
                ),
            )
        )
    for history in ticket.transition_history.select_related("to_status"):
        if str(history.pk) in represented_transition_ids:
            continue
        milestones.append(
            (
                history.occurred_at,
                f"transition:{history.pk}",
                tracking_status_for(history.to_status),
            )
        )
    if not milestones:
        milestones.append(
            (ticket.created_at, f"ticket:{ticket.pk}", tracking_status_for(ticket.status))
        )
    progress: list[TrackingProgressItem] = []
    for occurred_at, _stable_id, status in sorted(milestones):
        if progress and progress[-1]["status"] == status:
            continue
        progress.append({"status": status, "occurred_at": occurred_at})
    return progress
```

- [ ] **Step 4: Write failing escalation workflow tests**

Use the existing `_user`, `_ticket`, and `_post` helpers to test In Progress → Escalated:

```python
def test_escalation_requires_a_reason_and_records_the_responsible_actor(basic_world):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world, status_code="in_progress")

    missing = _post(
        actor,
        ticket,
        {"to_status": "escalated", "updated_at": ticket.updated_at.isoformat()},
    )
    assert missing.status_code == 400
    assert missing.data["fields"] == {"reason": ["This field is required."]}

    response = _post(
        actor,
        ticket,
        {
            "to_status": "escalated",
            "updated_at": ticket.updated_at.isoformat(),
            "reason": "SLA risk",
        },
    )

    assert response.status_code == 200
    ticket.refresh_from_db()
    event = ticket.custody_events.order_by("sequence").last()
    assert event is not None
    assert event.event_type == "escalated"
    assert event.actor_subject == actor.keycloak_subject
    assert event.occurred_at is not None
    assert event.reason == "SLA risk"
    audit = AuditEvent.objects.get(
        object_id=str(ticket.id), action="ticket.transitioned"
    )
    assert audit.actor_subject == actor.keycloak_subject
    assert audit.occurred_at is not None
```

- [ ] **Step 5: Run escalation tests and observe the unavailable transition**

Run:

```powershell
docker compose exec backend pytest apps/tickets/tests/test_transition_api.py -k "escalat" -q
```

Expected: the transition is unavailable or returns a generic status-changed custody event.

- [ ] **Step 6: Seed Escalated and classify its custody event**

Add `("escalated", "Escalated", False, False, 85, "Escalated for attention")` to both domain status lists. Add transitions to `escalated` from these exact codes:

```python
OPERATIONAL_ESCALATION_FROM = (
    "triage",
    "assigned",
    "in_progress",
    "waiting_requester",
    "waiting_internal",
    "waiting_it",
    "quality_review",
    "reopened",
)
IT_ESCALATION_FROM = (
    "triage",
    "assigned",
    "diagnosing",
    "in_progress",
    "waiting_user",
    "waiting_vendor",
    "waiting_change",
    "validation",
    "reopened",
)
```

Add `("escalated", "in_progress", "Resume escalated work")` to each domain. In `seed_workflow()`, set `required_fields=["reason"]` whenever `to_status.code == "escalated"` and `[]` otherwise.

Update the focused workflow shortcut with operational Escalated and its required-reason transitions. Change `custody_event_type_for_transition()`:

```python
if code == "escalated":
    return TicketCustodyEvent.EventType.ESCALATED
```

Create `0013_escalated_workflow.py` as an idempotent data migration using historical `Status` and `Transition` models. It creates/updates both Escalated statuses and the same transition rows with `required_fields=["reason"]`; reverse disables only those transitions and leaves historical statuses intact.

- [ ] **Step 7: Run tracking, transition, activity, and custody tests**

Run:

```powershell
docker compose exec backend pytest apps/tickets/tests/test_tracking.py apps/tickets/tests/test_transition_api.py apps/tickets/tests/test_activity.py apps/tickets/tests/test_custody.py -q
```

Expected: all selected tests pass, Escalated is a distinct hash-chained custody event, and existing Resolved/Reopened/Closed behavior remains unchanged.

- [ ] **Step 8: Review and conditionally commit**

Inspect all Task 3 paths, including generated migration contents. If task-only staging can be proven, commit with `feat(tickets): add tracking statuses and escalation`; otherwise keep the dirty worktree unstaged.

---

### Task 4: Scope-Aware Tracking API and Staff Reference Search

**Files:**
- Modify: `backend/apps/tickets/api.py`
- Modify: `backend/apps/tickets/views.py:110-195`
- Create: `backend/apps/tickets/tests/test_tracking_api.py`
- Modify: `backend/apps/tickets/tests/test_api_collections.py`

**Interfaces:**
- Consumes: `build_tracking_progress(ticket)` and `tracking_status_for(ticket.status)` from Task 3; `TicketViewSet.get_queryset()` for scope concealment.
- Produces: `GET /api/v1/tickets/tracking/?reference=<reference>` returning `TicketTrackingSerializer` data.

- [ ] **Step 1: Write failing authentication, scope, validation, and payload tests**

Create an operational ticket and an IT ticket. Authenticate an operational helpdesk actor with this concrete fixture shape:

```python
from types import SimpleNamespace

import pytest
from rest_framework import serializers
from rest_framework.test import APIClient

from apps.identity_access.models import User
from apps.tickets import services


@pytest.fixture
def tracking_world(basic_world):
    actor = User.objects.create(
        username="tracking-agent",
        keycloak_subject="tracking-agent-subject",
        keycloak_groups=["ops-agents"],
    )
    actor._groups = ["ops-agents"]
    ops_client = APIClient()
    ops_client.force_authenticate(actor)
    ops_ticket = services.create_ticket(
        domain="operational",
        title="Estate status enquiry",
        description="Requester-private description",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
        channel="call",
        actor=actor,
        actor_subject=actor.keycloak_subject,
    )
    it_ticket = services.create_ticket(
        domain="it",
        title="Internal IT issue",
        description="Internal details",
        requester=basic_world["contact"],
        service=basic_world["it_inc"],
        request_type=basic_world["it_inc"].request_types.get(),
        office=basic_world["office"],
        channel="internal",
    )
    return SimpleNamespace(
        actor=actor,
        ops_client=ops_client,
        ops_ticket=ops_ticket,
        it_ticket=it_ticket,
    )
```

Then assert the requester-safe response:

```python
def test_tracking_returns_only_requester_safe_progress_for_an_in_scope_reference(
    tracking_world,
):
    world = tracking_world
    render_datetime = serializers.DateTimeField().to_representation
    created_event = world.ops_ticket.custody_events.get()
    response = world.ops_client.get(
        reverse("tickets-tracking"), {"reference": f"  {world.ops_ticket.number.lower()}  "}
    )
    assert response.status_code == 200
    assert response.data == {
        "reference": world.ops_ticket.number,
        "title": world.ops_ticket.title,
        "tracking_status": "Submitted",
        "status_updated_at": render_datetime(created_event.occurred_at),
        "created_at": render_datetime(world.ops_ticket.created_at),
        "updated_at": render_datetime(world.ops_ticket.updated_at),
        "office": world.ops_ticket.office.name,
        "service": world.ops_ticket.service.name,
        "progress": [
            {
                "status": "Submitted",
                "occurred_at": render_datetime(created_event.occurred_at),
            }
        ],
    }
    assert "requester" not in response.data
    assert "notes" not in response.data
    assert "actor" not in response.data["progress"][0]
```

Add separate tests for unauthenticated `401`, malformed `400`, nonexistent `404`, and out-of-scope `404` with identical problem bodies for the last two.

Add a collection test proving `?search=<exact reference>` returns only the in-scope ticket and never the cross-domain ticket.

- [ ] **Step 2: Run the API tests and observe the missing route**

Run:

```powershell
docker compose exec backend pytest apps/tickets/tests/test_tracking_api.py apps/tickets/tests/test_api_collections.py -k "tracking or reference" -q
```

Expected: reverse lookup for `tickets-tracking` fails or the endpoint returns 404.

- [ ] **Step 3: Add explicit input and output serializers**

In `api.py`, add:

```python
class TicketTrackingLookupSerializer(serializers.Serializer[dict[str, str]]):
    reference = serializers.CharField(max_length=32)

    def validate_reference(self, value: str) -> str:
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9]{1,7}-\d{6}-\d{6}", normalized):
            raise serializers.ValidationError("Enter a valid ticket reference.")
        return normalized


class TrackingProgressSerializer(serializers.Serializer[dict[str, object]]):
    status = serializers.ChoiceField(choices=[status.value for status in TrackingStatus])
    occurred_at = serializers.DateTimeField()


class TicketTrackingSerializer(serializers.Serializer[dict[str, object]]):
    reference = serializers.CharField()
    title = serializers.CharField()
    tracking_status = serializers.ChoiceField(choices=[status.value for status in TrackingStatus])
    status_updated_at = serializers.DateTimeField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    office = serializers.CharField()
    service = serializers.CharField()
    progress = TrackingProgressSerializer(many=True)
```

The lower-case/whitespace normalisation test must pass before proceeding.

- [ ] **Step 4: Add the collection action using the already-scoped queryset**

In `TicketViewSet`:

```python
@action(detail=False, methods=["get"], url_path="tracking")
def tracking(self, request: Request) -> Response:
    lookup = TicketTrackingLookupSerializer(data=request.query_params)
    if not lookup.is_valid():
        return _ticket_action_error(
            request,
            code="invalid_ticket_reference",
            detail="Enter a valid ticket reference.",
            fields=_serializer_error_fields(lookup.errors),
            response_status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        ticket = self.get_queryset().select_related("status", "office", "service").get(
            number__iexact=lookup.validated_data["reference"]
        )
    except Ticket.DoesNotExist as exc:
        raise NotFound("Ticket not found.") from exc
    progress = build_tracking_progress(ticket)
    payload = {
        "reference": ticket.number,
        "title": ticket.title,
        "tracking_status": tracking_status_for(ticket.status),
        "status_updated_at": progress[-1]["occurred_at"],
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
        "office": ticket.office.name,
        "service": ticket.service.name,
        "progress": progress,
    }
    return Response(TicketTrackingSerializer(payload).data)
```

Do not call `Ticket.objects` directly for lookup. Keep `lookup_field` compatibility by widening its regex to `[A-Z][A-Z0-9]{1,7}-\d{6}-\d{6}` so configured-prefix detail links continue working.

- [ ] **Step 5: Run tracking and permission regressions**

Run:

```powershell
docker compose exec backend pytest apps/tickets/tests/test_tracking_api.py apps/tickets/tests/test_api_collections.py apps/tickets/tests/test_permissions.py apps/tickets/tests/test_scope_api.py -q
```

Expected: authorised in-scope lookup succeeds, out-of-scope/nonexistent responses are indistinguishable, and all existing scope tests pass.

- [ ] **Step 6: Review and conditionally commit**

Inspect the four task paths. Commit with `feat(api): add scoped ticket tracking` only if staged content contains no pre-existing hunks.

---

### Task 5: Tracking Client and Protected Tracking Page

**Files:**
- Modify: `frontend/src/lib/api.ts:140-230,444-510`
- Modify: `frontend/src/lib/api.test.ts`
- Create: `frontend/src/features/tickets/TicketTrackingPage.tsx`
- Create: `frontend/src/features/tickets/TicketTrackingPage.test.tsx`

**Interfaces:**
- Consumes: Task 4 tracking endpoint and the existing `ApiError`/`apiProblem()` error contract.
- Produces: TypeScript `TrackingStatus`, `TicketTrackingProgress`, `TicketTrackingResult`, `ticketsApi.track(reference)`, and default component `TicketTrackingPage`.

- [ ] **Step 1: Write the failing API client URL-contract test**

Add a test alongside existing `ticketsApi` tests:

```typescript
const TRACKING_RESULT: TicketTrackingResult = {
  reference: "OP-202608-000123",
  title: "Estate status enquiry",
  tracking_status: "In Progress",
  status_updated_at: "2026-08-02T10:15:00Z",
  created_at: "2026-08-02T09:00:00Z",
  updated_at: "2026-08-02T10:15:00Z",
  office: "Mbabane (Main)",
  service: "Estate registration or reference",
  progress: [
    { status: "Submitted", occurred_at: "2026-08-02T09:00:00Z" },
    { status: "In Progress", occurred_at: "2026-08-02T10:15:00Z" },
  ],
};


it("encodes the ticket reference for authenticated tracking lookup", async () => {
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(jsonResponse(200, TRACKING_RESULT));

  await ticketsApi.track("OP-202608-000123");

  expect(fetchMock.mock.calls[0][0]).toBe(
    "/api/v1/tickets/tracking/?reference=OP-202608-000123",
  );
  expect(requestHeaders(fetchMock.mock.calls[0]).get("Authorization")).toBe(
    "Bearer old-token",
  );
});
```

Import `TicketTrackingResult` as a type from `./api` and keep the file's real fetch/authentication harness.

- [ ] **Step 2: Run the client test and observe `ticketsApi.track` missing**

Run:

```powershell
docker compose run --rm --no-deps --build --volume /app/node_modules frontend npm test -- src/lib/api.test.ts --run
```

Expected: TypeScript/test failure because `track` does not exist.

- [ ] **Step 3: Add the exact client-side contract**

In `api.ts`:

```typescript
export type TrackingStatus =
  | "Submitted"
  | "Acknowledged"
  | "Assigned"
  | "In Progress"
  | "Awaiting Information"
  | "Escalated"
  | "Resolved"
  | "Closed"
  | "Reopened";

export interface TicketTrackingProgress {
  status: TrackingStatus;
  occurred_at: string;
}

export interface TicketTrackingResult {
  reference: string;
  title: string;
  tracking_status: TrackingStatus;
  status_updated_at: string;
  created_at: string;
  updated_at: string;
  office: string;
  service: string;
  progress: TicketTrackingProgress[];
}
```

Add:

```typescript
track: (reference: string) => {
  const query = new URLSearchParams({ reference }).toString();
  return api<TicketTrackingResult>(`/tickets/tracking/?${query}`);
},
```

Run the client test again and expect PASS.

- [ ] **Step 4: Write failing page behavior tests**

Mock only `ticketsApi.track`; render the real page. Cover:

```typescript
const harness = vi.hoisted(() => ({ track: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    ticketsApi: { ...original.ticketsApi, track: harness.track },
  };
});

const TRACKING_RESULT: TicketTrackingResult = {
  reference: "OP-202608-000123",
  title: "Estate status enquiry",
  tracking_status: "In Progress",
  status_updated_at: "2026-08-02T10:15:00Z",
  created_at: "2026-08-02T09:00:00Z",
  updated_at: "2026-08-02T10:15:00Z",
  office: "Mbabane (Main)",
  service: "Estate registration or reference",
  progress: [
    { status: "Submitted", occurred_at: "2026-08-02T09:00:00Z" },
    { status: "In Progress", occurred_at: "2026-08-02T10:15:00Z" },
  ],
};

function LocationProbe() {
  return <output data-testid="ticket-location">{useLocation().pathname}</output>;
}

function renderTracking(route: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/ticket-tracking" element={<TicketTrackingPage />} />
      <Route path="/tickets/:number" element={<LocationProbe />} />
    </Routes>,
    { route },
  );
}


it("tracks a normalised reference once and renders safe progress", async () => {
  harness.track.mockResolvedValue(TRACKING_RESULT);
  const user = userEvent.setup();
  renderTracking("/ticket-tracking");

  await user.type(screen.getByLabelText("Reference number"), " op-202608-000123 ");
  await user.click(screen.getByRole("button", { name: "Track ticket" }));

  await screen.findByRole("heading", { name: "Estate status enquiry" });
  expect(harness.track).toHaveBeenCalledWith("OP-202608-000123");
  expect(screen.getByText("In Progress")).toBeVisible();
  expect(screen.getByRole("list", { name: "Ticket progress" })).toHaveTextContent("Submitted");
  expect(screen.queryByText(/internal note/i)).not.toBeInTheDocument();
});
```

Also test: invalid local shape does not call API and focuses input; duplicate submit while pending calls once; valid `?reference=` auto-loads once; 404 says the ticket could not be found or is outside access; structured unexpected errors show the correlation reference; full-ticket link uses `encodeURIComponent(reference)`.

- [ ] **Step 5: Run the page tests and observe the missing component**

Run:

```powershell
docker compose run --rm --no-deps --build --volume /app/node_modules frontend npm test -- src/features/tickets/TicketTrackingPage.test.tsx --run
```

Expected: import failure because `TicketTrackingPage.tsx` does not exist.

- [ ] **Step 6: Implement the focused page**

Use `useSearchParams`, `useMutation`, a synchronous `useRef` submission lock, and the exact client-side reference regex. On valid query input, trigger one lookup in an effect guarded by the submitted reference. Render existing `Card`, `Input`, `Button`, `Alert`, `Badge`, `Spinner`, and Lucide icons.

The result card must render:

```tsx
<Badge>{result.tracking_status}</Badge>
<Link to={`/tickets/${encodeURIComponent(result.reference)}`}>Open full ticket</Link>
<ol aria-label="Ticket progress">
  {result.progress.map((item, index) => (
    <li key={`${item.occurred_at}:${item.status}:${index}`}>
      <span>{item.status}</span>
      <time dateTime={item.occurred_at}>{formatDateTime(item.occurred_at)}</time>
    </li>
  ))}
</ol>
```

Use `Intl.DateTimeFormat` with the same formatting convention as other ticket pages. Do not render fields absent from `TicketTrackingResult`.

- [ ] **Step 7: Run client/page tests and TypeScript checks**

Run:

```powershell
docker compose run --rm --no-deps --build --volume /app/node_modules frontend npm test -- src/lib/api.test.ts src/features/tickets/TicketTrackingPage.test.tsx --run
docker compose run --rm --no-deps --build --volume /app/node_modules frontend npm run typecheck
```

Expected: both test files pass and TypeScript reports no errors.

- [ ] **Step 8: Review and conditionally commit**

The new page/test files can be staged independently. Stage modified `api.ts`/`api.test.ts` only if their full staged diffs exclude pre-existing changes. Safe commit message: `feat(frontend): add staff ticket tracking page`.

---

### Task 6: Protected Route, Navigation, and Confirmation Handoff

**Files:**
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/app/App.test.tsx`
- Modify: `frontend/src/components/app-shell.tsx`
- Modify: `frontend/src/features/tickets/ChannelIntakePage.tsx:115-205`
- Modify: `frontend/src/features/tickets/ChannelIntakePage.test.tsx`
- Modify: `docs/basic-application-guide.md`

**Interfaces:**
- Consumes: `TicketTrackingPage` and `ticket_number` returned by existing staff-assisted intake.
- Produces: protected `/ticket-tracking` route, Track ticket navigation item, and prefilled confirmation link `/ticket-tracking?reference=<encoded reference>`.

- [ ] **Step 1: Write failing route and navigation tests**

Add App route assertions:

```typescript
it("protects ticket tracking and preserves the requested reference", async () => {
  const auth = makeAuth();
  renderApp("/ticket-tracking?reference=OP-202608-000123", auth);
  await waitFor(() =>
    expect(auth.login).toHaveBeenCalledWith(
      "/ticket-tracking?reference=OP-202608-000123",
    ),
  );
  expect(screen.queryByRole("heading", { name: "Track a ticket" })).not.toBeInTheDocument();
});
```

For authenticated AppShell rendering, assert a Ticket workspace link named Track ticket points to `/ticket-tracking`. Keep public `/health`, `/login`, and unknown-route tests asserting the link is absent.

- [ ] **Step 2: Run App tests and observe missing route/navigation failures**

Run:

```powershell
docker compose run --rm --no-deps --build --volume /app/node_modules frontend npm test -- src/app/App.test.tsx --run
```

Expected: authenticated tracking route falls through and navigation lacks the link.

- [ ] **Step 3: Register the protected route and staff navigation**

Import `TicketTrackingPage` in `App.tsx` and add `<Route path="/ticket-tracking" element={<TicketTrackingPage />} />` inside `ProtectedRoute` and `AppShell`.

Add `{ to: "/ticket-tracking", label: "Track ticket", icon: SearchCheck }` to `PRIMARY_NAV`. Adjust the mobile grid columns so seven links remain touch-safe without truncating labels. Do not add it to `PublicShell`.

- [ ] **Step 4: Write failing confirmation tests**

Extend `ChannelIntakePage.test.tsx` with a successful response and a clipboard spy:

```typescript
const writeText = vi.fn().mockResolvedValue(undefined);
Object.defineProperty(navigator, "clipboard", {
  configurable: true,
  value: { writeText },
});

harness.publicIntake.mockResolvedValue({
  ticket_number: "OP-202608-000123",
  domain: "operational",
  title: "Hours",
  priority: "P3",
  message: "Your request has been received.",
});

// Fill the three required fields and submit.
expect(await screen.findByText("Reference number")).toBeVisible();
expect(screen.getByText("OP-202608-000123")).toBeVisible();
expect(screen.getByRole("link", { name: "Track this ticket" })).toHaveAttribute(
  "href",
  "/ticket-tracking?reference=OP-202608-000123",
);
await user.click(screen.getByRole("button", { name: "Copy reference" }));
expect(writeText).toHaveBeenCalledWith("OP-202608-000123");
```

Assert the confirmation remains absent while the API promise is pending or rejected.

- [ ] **Step 5: Run the intake tests and observe missing copy/link semantics**

Run:

```powershell
docker compose run --rm --no-deps --build --volume /app/node_modules frontend npm test -- src/features/tickets/ChannelIntakePage.test.tsx --run
```

Expected: the current confirmation lacks the Reference number label, Copy reference button, and tracking link.

- [ ] **Step 6: Implement the confirmation handoff**

Change confirmation copy from “Ticket … at priority …” to a dedicated Reference number label and monospaced/tabular value. Add:

```tsx
const [copyError, setCopyError] = useState<string | null>(null);

async function copyReference(reference: string) {
  try {
    await navigator.clipboard.writeText(reference);
    setCopyError(null);
  } catch {
    setCopyError("The reference could not be copied. Select it and copy it manually.");
  }
}

<Button
  type="button"
  variant="outline"
  onClick={() => void copyReference(submitted.number)}
>
  <Copy data-icon="inline-start" />
  Copy reference
</Button>
<Button
  render={<Link to={`/ticket-tracking?reference=${encodeURIComponent(submitted.number)}`} />}
  nativeButton={false}
>
  <SearchCheck data-icon="inline-start" />
  Track this ticket
</Button>
{copyError ? <p role="alert">{copyError}</p> : null}
```

On clipboard rejection, show an accessible inline alert and keep the reference visible for manual copying. Preserve Submit another request and the synchronous intake submission lock.

- [ ] **Step 7: Document the staff workflow**

Update `docs/basic-application-guide.md` to state: staff capture the request, give the displayed immutable reference to the requester, open Track ticket, enter the exact reference, and use Open full ticket when internal audit details are needed. Explicitly state that tracking requires staff authentication and authorised scope.

- [ ] **Step 8: Run route, intake, and tracking page tests**

Run:

```powershell
docker compose run --rm --no-deps --build --volume /app/node_modules frontend npm test -- src/app/App.test.tsx src/features/tickets/ChannelIntakePage.test.tsx src/features/tickets/TicketTrackingPage.test.tsx --run
```

Expected: all selected tests pass; public route tests still show no staff navigation.

- [ ] **Step 9: Review and conditionally commit**

Inspect all Task 6 files. Commit with `feat(frontend): connect intake to ticket tracking` only when task-only staging is provable; otherwise leave existing dirty files unstaged.

---

### Task 7: Requirement Audit and Full Verification

**Files:**
- Modify only when a failing requirement-specific check identifies an in-scope defect.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: fresh test, migration, lint, typecheck, and production-build evidence plus a line-by-line acceptance checklist.

- [ ] **Step 1: Run backend migration and focused feature checks**

Run:

```powershell
docker compose exec backend python manage.py makemigrations --check --dry-run
docker compose exec backend pytest apps/tickets/tests/test_references.py apps/tickets/tests/test_integrity_boundaries.py apps/tickets/tests/test_tracking.py apps/tickets/tests/test_tracking_api.py apps/tickets/tests/test_transition_api.py apps/tickets/tests/test_intake_api.py apps/tickets/tests/test_assignment.py apps/tickets/tests/test_activity.py -q
```

Expected: no pending migrations and all focused backend tests pass.

- [ ] **Step 2: Run the complete backend quality gate**

Run:

```powershell
docker compose exec backend pytest -q
docker compose exec backend ruff check .
docker compose exec backend mypy apps config
```

Expected: full test suite, Ruff, and mypy all exit zero. Classify any pre-existing failure with its exact command and unchanged file before deciding whether it is outside scope.

- [ ] **Step 3: Run the complete frontend quality gate**

Run:

```powershell
docker compose run --rm --no-deps --build --volume /app/node_modules frontend env VITE_API_BASE_URL= npm test -- --run
docker compose run --rm --no-deps --build --volume /app/node_modules frontend npm run typecheck
docker compose run --rm --no-deps --build --volume /app/node_modules frontend npm run lint
docker compose run --rm --no-deps --build --volume /app/node_modules frontend npm run build
```

Expected: all tests, typecheck, lint, and production build exit zero.

- [ ] **Step 4: Verify each acceptance criterion against evidence**

Record evidence for:

1. PostgreSQL concurrency test returns two unique references.
2. Model/queryset/raw-SQL mutation tests preserve the original reference.
3. Successful staff intake renders Reference number immediately.
4. Tracking API in-scope succeeds and out-of-scope/nonexistent both return 404.
5. Mapping tests cover all nine exact labels.
6. Escalated transition requires a reason and writes an Escalated custody event.
7. Existing activity/assignment/transition tests plus the escalation test show actor and timestamp for required events.
8. Full verification commands exit zero.

- [ ] **Step 5: Inspect the final diff for scope and user-change preservation**

Run:

```powershell
git status --short
git diff --check
git diff --stat
git diff -- backend/apps/tickets backend/apps/workflow/shortcuts.py backend/config/settings/base.py .env.example frontend/src docs/basic-application-guide.md
```

Expected: no whitespace errors; every new hunk maps to this plan; unrelated pre-existing changes remain intact.

- [ ] **Step 6: Request an independent code review before completion**

Use the repository's required review workflow against the final diff. Fix correctness, security, concurrency, scope, or accessibility findings and rerun the smallest failing check plus the full affected quality gate.

- [ ] **Step 7: Commit only if a safe staging boundary exists**

If relevant existing files still contain pre-task changes, do not create a mixed commit; report the verified implementation as unstaged. If every staged hunk is task-owned, verify `git diff --cached --check` and commit with `feat(tickets): add secure references and staff tracking`.
