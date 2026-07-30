# Ticket Custody Ledger and Activity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a tamper-evident, append-only ticket custody ledger and make creation, workflow, queue, escalation, reopening, and closure records available in the authorised staff activity stream.

**Architecture:** A focused custody module owns immutable snapshot types, canonical hashing, per-ticket sequencing, and append-only persistence. Existing ticket services continue to own business mutations and pass typed custody inputs into the existing atomic audit/outbox recorder. The activity read model consumes custody records and uses transition source IDs to avoid duplicate workflow entries.

**Tech Stack:** Python 3.12, Django 5.2, Django REST Framework, PostgreSQL, pytest, Celery SLA services, Ruff, mypy

## Global Constraints

- This is an internal staff and audit feature; do not modify or expand public intake, requester tracking, anonymous routes, or requester accounts.
- Custody writes must commit or roll back with the ticket mutation, audit event, outbox event, and transition history.
- Custody display values are immutable snapshots; later user, role, status, or queue renames must not rewrite history.
- Ordinary application code, Django admin users, API clients, and auditors cannot update or selectively delete custody records.
- The existing authorised ticket scope remains the read boundary, including Restricted-ticket handling and relationship masking.
- Write each production behaviour only after its focused test has failed for the intended reason.
- Preserve unrelated working-tree changes and stage only the files listed by each task.

## Plan Boundary and Dependencies

This is Plan 1 of 3. It produces the custody interfaces consumed by:

- Plan 2: role-derived assignment eligibility and the atomic assignment API; and
- Plan 3: the internal searchable assignment UI and categorised activity presentation.

Queue routing itself remains outside this plan. The ledger exposes and tests `queue_changed`, and any current or future canonical routing service must pass that typed event through `record_ticket_event`.

## File Structure

- `backend/apps/tickets/models.py`: owns the persisted `TicketCustodyEvent` aggregate record.
- `backend/apps/tickets/custody.py`: owns snapshot dataclasses, canonical hash calculation, event sequencing, and transition event classification.
- `backend/apps/tickets/events.py`: writes audit, outbox, and optional custody inputs in one transaction.
- `backend/apps/tickets/services.py`: emits creation and workflow custody events.
- `backend/apps/tickets/it_child.py`: emits custody events for its direct child creation and parent workflow mutations.
- `backend/apps/tickets/activity.py`: merges custody with messages, notes, attachments, and relationships without workflow duplicates.
- `backend/apps/tickets/admin.py`: exposes custody as read-only.
- `backend/apps/tickets/migrations/0005_ticketcustodyevent.py`: creates the custody table and constraints.
- `backend/apps/tickets/migrations/0006_backfill_ticket_custody.py`: reconstructs authoritative legacy history and installs PostgreSQL immutability protection.
- `backend/apps/administration/retention.py`: enables the narrow transaction-local custody-delete exception only for an approved whole-ticket disposal.
- `backend/apps/administration/tests/test_retention.py`: proves ordinary deletion is blocked while policy-approved whole-ticket disposal remains possible.
- `backend/apps/sla/services.py`: emits idempotent system escalation custody events.
- `backend/apps/tickets/tests/test_custody.py`: covers persistence, hashing, sequencing, immutability, and source mappings.
- `backend/apps/tickets/tests/test_custody_migration.py`: covers deterministic, idempotent legacy backfill.
- `backend/apps/tickets/tests/test_activity.py`: covers chronological category output, scope, and transition de-duplication.
- `backend/apps/sla/tests/test_services.py`: covers threshold crossing and idempotent system escalation.

---

### Task 1: Add the append-only custody model

**Files:**
- Modify: `backend/apps/tickets/models.py`
- Modify: `backend/apps/tickets/admin.py`
- Create: `backend/apps/tickets/migrations/0005_ticketcustodyevent.py`
- Create: `backend/apps/tickets/tests/test_custody.py`

**Interfaces:**
- Produces: `TicketCustodyEvent` with stable event choices, JSON snapshots, sequence, source reference, and hash fields.
- Produces: create-only model/queryset behaviour used by `apps.tickets.custody.record_custody_events` in Task 2.

- [ ] **Step 1: Write failing model and application-immutability tests**

Create `backend/apps/tickets/tests/test_custody.py` with a local ticket fixture and these exact behaviours:

```python
import pytest
from django.core.exceptions import ValidationError

from apps.tickets.models import TicketCustodyEvent

pytestmark = pytest.mark.django_db


def test_custody_event_is_ordered_by_ticket_sequence(ticket):
    TicketCustodyEvent.objects.create(
        ticket=ticket,
        sequence=2,
        event_type="assigned",
        actor_kind="user",
        actor_subject="supervisor-1",
        actor_display_name="Supervisor One",
        source_process="ticket.assignment",
        previous_hash="a" * 64,
        event_hash="b" * 64,
    )
    TicketCustodyEvent.objects.create(
        ticket=ticket,
        sequence=1,
        event_type="created",
        actor_kind="system",
        actor_subject="intake:web",
        actor_display_name="Web intake",
        source_process="ticket.create",
        previous_hash="",
        event_hash="a" * 64,
    )

    assert list(
        TicketCustodyEvent.objects.filter(ticket=ticket).values_list(
            "sequence", flat=True
        )
    ) == [1, 2]


def test_existing_custody_event_cannot_be_saved_or_deleted(ticket):
    event = TicketCustodyEvent.objects.create(
        ticket=ticket,
        sequence=1,
        event_type="created",
        actor_kind="system",
        actor_subject="intake:web",
        actor_display_name="Web intake",
        source_process="ticket.create",
        previous_hash="",
        event_hash="a" * 64,
    )

    event.reason = "rewritten"
    with pytest.raises(ValidationError, match="immutable"):
        event.save()
    with pytest.raises(ValidationError, match="immutable"):
        event.delete()
    with pytest.raises(ValidationError, match="immutable"):
        TicketCustodyEvent.objects.filter(pk=event.pk).update(reason="rewritten")
    with pytest.raises(ValidationError, match="immutable"):
        TicketCustodyEvent.objects.filter(pk=event.pk).delete()
```

Also add `test_ticket_custody_sequence_is_unique` and assert a duplicate `(ticket, sequence)` raises `IntegrityError`.

- [ ] **Step 2: Run the focused tests and verify the red state**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_custody.py -q
```

Expected: collection fails because `TicketCustodyEvent` does not exist.

- [ ] **Step 3: Implement the model and create-only queryset**

Add the following model shape to `backend/apps/tickets/models.py`:

```python
class ImmutableCustodyQuerySet(models.QuerySet["TicketCustodyEvent"]):
    def update(self, **kwargs: object) -> int:
        raise ValidationError("Ticket custody events are immutable.")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValidationError("Ticket custody events are immutable.")


class TicketCustodyEvent(models.Model):
    class EventType(models.TextChoices):
        CREATED = "created", "Created"
        ASSIGNED = "assigned", "Assigned"
        REASSIGNED = "reassigned", "Transferred / reassigned"
        UNASSIGNED = "unassigned", "Unassigned"
        QUEUE_CHANGED = "queue_changed", "Queue changed"
        ESCALATED = "escalated", "Escalated"
        STATUS_CHANGED = "status_changed", "Status changed"
        REOPENED = "reopened", "Reopened"
        CLOSED = "closed", "Closed"

    class ActorKind(models.TextChoices):
        USER = "user", "User"
        SYSTEM = "system", "System"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="custody_events",
    )
    sequence = models.PositiveBigIntegerField()
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    actor_kind = models.CharField(max_length=16, choices=ActorKind.choices)
    actor_subject = models.CharField(max_length=255)
    actor_display_name = models.CharField(max_length=255)
    source_process = models.CharField(max_length=128)
    source_record_type = models.CharField(max_length=64, blank=True)
    source_record_id = models.CharField(max_length=64, blank=True)
    previous_owner = models.JSONField(null=True, blank=True)
    new_owner = models.JSONField(null=True, blank=True)
    previous_queue = models.JSONField(null=True, blank=True)
    new_queue = models.JSONField(null=True, blank=True)
    previous_status = models.JSONField(null=True, blank=True)
    new_status = models.JSONField(null=True, blank=True)
    previous_designations = models.JSONField(default=list, blank=True)
    new_designations = models.JSONField(default=list, blank=True)
    previous_team_labels = models.JSONField(default=list, blank=True)
    new_team_labels = models.JSONField(default=list, blank=True)
    reason = models.TextField(blank=True)
    previous_hash = models.CharField(max_length=64, blank=True)
    event_hash = models.CharField(max_length=64)

    objects = ImmutableCustodyQuerySet.as_manager()

    class Meta:
        db_table = "ticket_custody_event"
        ordering = ("sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("ticket", "sequence"),
                name="uniq_ticket_custody_sequence",
            ),
        ]

    def save(self, *args: object, **kwargs: object) -> None:
        if not self._state.adding:
            raise ValidationError("Ticket custody events are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        raise ValidationError("Ticket custody events are immutable.")
```

Import `ValidationError` and `timezone`. Keep the model snapshots free of live display-name foreign keys.

- [ ] **Step 4: Add the schema migration and read-only admin**

Run `python manage.py makemigrations tickets --name ticketcustodyevent`, verify the generated dependency is `tickets.0004_ticket_next_action_ticket_next_action_at`, and keep the migration name `0005_ticketcustodyevent.py`.

Register a read-only admin:

```python
@admin.register(TicketCustodyEvent)
class TicketCustodyEventAdmin(admin.ModelAdmin[TicketCustodyEvent]):
    list_display = ("ticket", "sequence", "event_type", "occurred_at", "actor_display_name")
    readonly_fields = tuple(field.name for field in TicketCustodyEvent._meta.fields)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: TicketCustodyEvent | None = None
    ) -> bool:
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: TicketCustodyEvent | None = None
    ) -> bool:
        return False
```

- [ ] **Step 5: Run the focused tests and migration check**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_custody.py -q
python manage.py makemigrations --check --dry-run
ruff check apps/tickets/models.py apps/tickets/admin.py apps/tickets/tests/test_custody.py
```

Expected: custody tests pass, no migration drift, and Ruff exits 0.

- [ ] **Step 6: Commit the model increment**

```powershell
git add backend/apps/tickets/models.py backend/apps/tickets/admin.py backend/apps/tickets/migrations/0005_ticketcustodyevent.py backend/apps/tickets/tests/test_custody.py
git diff --cached --check
git commit -m "feat(tickets): add immutable custody model"
```

---

### Task 2: Add canonical custody snapshots, hashing, and atomic event recording

**Files:**
- Create: `backend/apps/tickets/custody.py`
- Modify: `backend/apps/tickets/events.py`
- Modify: `backend/apps/tickets/tests/test_custody.py`
- Modify: `backend/apps/tickets/tests/test_events.py`

**Interfaces:**
- Produces: `CustodyActor`, `CustodyParty`, `CustodyQueue`, `CustodyStatus`, and `CustodyEventInput` frozen dataclasses.
- Produces: `record_custody_events(*, ticket: Ticket, actor: CustodyActor, events: Sequence[CustodyEventInput]) -> list[TicketCustodyEvent]`.
- Produces: `custody_event_type_for_transition(code: str) -> str`.
- Extends: `record_ticket_event` with keyword-only `custody_actor: CustodyActor | None = None` and `custody_events: Sequence[CustodyEventInput] = ()`, preserving its existing `(AuditEvent, OutboxEvent)` return value.

- [ ] **Step 1: Write failing hash-chain and atomicity tests**

Add these tests to `test_custody.py` and `test_events.py`:

```python
def test_record_custody_events_builds_a_verifiable_hash_chain(ticket):
    actor = CustodyActor.user(subject="agent-1", display_name="Agent One")
    events = record_custody_events(
        ticket=ticket,
        actor=actor,
        events=(
            CustodyEventInput.created(
                source_process="ticket.create",
                new_status=CustodyStatus(code="new", label="New"),
            ),
            CustodyEventInput(
                event_type="queue_changed",
                source_process="ticket.routing",
                previous_queue=None,
                new_queue=CustodyQueue(id="queue-1", label="Estate intake"),
            ),
        ),
    )

    assert [event.sequence for event in events] == [1, 2]
    assert events[0].previous_hash == ""
    assert events[1].previous_hash == events[0].event_hash
    assert verify_custody_chain(ticket) is True


def test_record_ticket_event_rolls_back_audit_outbox_and_custody_together(ticket):
    with patch(
        "apps.tickets.custody.TicketCustodyEvent.objects.create",
        side_effect=RuntimeError("custody unavailable"),
    ):
        with pytest.raises(RuntimeError, match="custody unavailable"):
            record_ticket_event(
                ticket=ticket,
                actor_subject="agent-1",
                action="ticket.created",
                before={},
                after={"status": "new"},
                custody_actor=CustodyActor.user("agent-1", "Agent One"),
                custody_events=(
                    CustodyEventInput.created(source_process="ticket.create"),
                ),
            )

    assert not AuditEvent.objects.filter(object_id=str(ticket.id)).exists()
    assert not OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).exists()
    assert not TicketCustodyEvent.objects.filter(ticket=ticket).exists()
```

Add a third test that appends to an existing chain and verifies the next sequence/hash rather than starting again at 1.

- [ ] **Step 2: Run the focused tests in the red state**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_custody.py apps/tickets/tests/test_events.py -q
```

Expected: imports fail because `apps.tickets.custody` and the extended event-recorder arguments do not exist.

- [ ] **Step 3: Implement the typed custody module**

Create frozen dataclasses whose `as_json()` methods return only strings, lists of strings, or `None`:

```python
@dataclass(frozen=True)
class CustodyActor:
    kind: str
    subject: str
    display_name: str

    @classmethod
    def user(cls, subject: str, display_name: str) -> "CustodyActor":
        return cls(kind="user", subject=subject, display_name=display_name)

    @classmethod
    def system(cls, process: str, display_name: str) -> "CustodyActor":
        return cls(kind="system", subject=process, display_name=display_name)


@dataclass(frozen=True)
class CustodyParty:
    id: str
    subject: str
    display_name: str
    designations: tuple[str, ...] = ()
    team_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class CustodyQueue:
    id: str
    label: str


@dataclass(frozen=True)
class CustodyStatus:
    code: str
    label: str


@dataclass(frozen=True)
class CustodyEventInput:
    event_type: str
    source_process: str
    source_record_type: str = ""
    source_record_id: str = ""
    previous_owner: CustodyParty | None = None
    new_owner: CustodyParty | None = None
    previous_queue: CustodyQueue | None = None
    new_queue: CustodyQueue | None = None
    previous_status: CustodyStatus | None = None
    new_status: CustodyStatus | None = None
    reason: str = ""
    occurred_at: datetime | None = None
```

Implement `record_custody_events` by locking the ticket row, loading the last event using the unrestricted base manager, assigning consecutive sequences, serialising snapshots, hashing canonical JSON with `sort_keys=True`, `separators=(",", ":")`, and creating each event. Do not use `bulk_create`, because every hash depends on the preceding persisted event.

Serialise `previous_owner` and `new_owner` as `{id, subject, display_name}` only, and place their designation/team values in the model's dedicated `previous_designations`, `new_designations`, `previous_team_labels`, and `new_team_labels` arrays. The activity read model recombines those fields into one presentation object.

Hash exactly these keys, with no database event UUID: `ticket_id`, `sequence`, `event_type`, UTC `occurred_at` formatted to six fractional digits and `Z`, `actor_kind`, `actor_subject`, `actor_display_name`, `source_process`, `source_record_type`, `source_record_id`, `previous_owner`, `new_owner`, `previous_queue`, `new_queue`, `previous_status`, `new_status`, `previous_designations`, `new_designations`, `previous_team_labels`, `new_team_labels`, `reason`, and `previous_hash`. Encode canonical JSON as UTF-8 before SHA-256. The migration in Task 4 must copy this key set, time normalisation, and ordering byte-for-byte.

Implement:

```python
def custody_event_type_for_transition(code: str) -> str:
    if code == "reopened":
        return TicketCustodyEvent.EventType.REOPENED
    if code == "closed":
        return TicketCustodyEvent.EventType.CLOSED
    return TicketCustodyEvent.EventType.STATUS_CHANGED
```

`verify_custody_chain(ticket)` must recompute every event from sequence 1 and return `False` for a sequence gap, previous-hash mismatch, or content-hash mismatch.

- [ ] **Step 4: Extend the audit/outbox recorder**

Add keyword-only arguments to `record_ticket_event` and, after creating the audit and outbox rows, call `record_custody_events`. When an input has no source record, use `source_record_type="audit_event"` and the new audit event ID without mutating the frozen caller value (`dataclasses.replace`). Require `custody_actor` whenever `custody_events` is non-empty.

- [ ] **Step 5: Run focused and regression tests**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_custody.py apps/tickets/tests/test_events.py -q
ruff check apps/tickets/custody.py apps/tickets/events.py apps/tickets/tests/test_custody.py apps/tickets/tests/test_events.py
mypy apps/tickets/custody.py apps/tickets/events.py
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit the custody writer**

```powershell
git add backend/apps/tickets/custody.py backend/apps/tickets/events.py backend/apps/tickets/tests/test_custody.py backend/apps/tickets/tests/test_events.py
git diff --cached --check
git commit -m "feat(tickets): record custody hash chains"
```

---

### Task 3: Record ticket creation and every workflow transition

**Files:**
- Modify: `backend/apps/tickets/services.py`
- Modify: `backend/apps/tickets/it_child.py`
- Modify: `backend/apps/tickets/views.py`
- Modify: `backend/apps/tickets/tests/test_services.py`
- Modify: `backend/apps/tickets/tests/test_intake_api.py`
- Modify: `backend/apps/tickets/tests/test_it_child.py`
- Modify: `backend/apps/tickets/tests/test_it_child_integrity.py`
- Modify: `backend/apps/tickets/tests/test_custody.py`

**Interfaces:**
- Consumes: Task 2 custody dataclasses and extended `record_ticket_event`.
- Produces: creation plus `status_changed`, `reopened`, and `closed` custody records for every current canonical creation/transition path.

- [ ] **Step 1: Write failing service-path tests**

Extend the existing creation, ordinary-transition, reopening, and closure tests with these exact assertions. Reuse their fully constructed ticket/actor setup rather than introducing a second workflow fixture:

```python
def test_create_ticket_starts_custody_with_creation_snapshot(basic_world):
    ticket = create_ticket(
        domain="operational",
        title="Custody creation",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
    )
    event = ticket.custody_events.get()
    assert event.sequence == 1
    assert event.event_type == "created"
    assert event.new_status == {"code": "new", "label": "New"}
    assert event.actor_kind == "system"
    assert event.source_process == "ticket.create"


def assert_latest_transition_custody(updated, actor, expected_type):
    event = updated.custody_events.order_by("sequence").last()
    assert event is not None
    assert event.event_type == expected_type
    assert event.previous_status["code"] != event.new_status["code"]
    assert event.actor_subject == actor.keycloak_subject
```

Call `assert_latest_transition_custody(ticket, actor, "status_changed")` in the existing valid transition test, `assert_latest_transition_custody(ticket, actor, "reopened")` in the existing reopen test, and `assert_latest_transition_custody(ticket, actor, "closed")` in the existing close-after-reopen test.

Add IT-child assertions proving the child gets `created`, the parent move to `waiting_it` gets `status_changed`, and the system-driven return to `in_progress` names `it-child-sync` as its system actor. Add an authenticated staff-assisted intake test proving the creating staff member is recorded as actor kind `user` with their subject and display name.

- [ ] **Step 2: Run the focused tests and observe missing records**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_services.py apps/tickets/tests/test_it_child.py apps/tickets/tests/test_it_child_integrity.py apps/tickets/tests/test_custody.py -q
```

Expected: new custody assertions fail because the services currently create only audit/outbox/transition rows.

- [ ] **Step 3: Add creation snapshots**

Add helpers in `custody.py` with these implementations:

```python
def status_snapshot(status: Status | None) -> CustodyStatus | None:
    if status is None:
        return None
    return CustodyStatus(code=status.code, label=status.name)


def queue_snapshot(queue: ServiceLocation | None) -> CustodyQueue | None:
    if queue is None:
        return None
    return CustodyQueue(id=str(queue.id), label=queue.name)


def user_actor(user: User) -> CustodyActor:
    return CustodyActor.user(
        subject=user.keycloak_subject,
        display_name=user.display_name or user.username,
    )
```

Extend `create_ticket` with optional keyword `actor: User | None = None`. When supplied, use `user_actor(actor)`; otherwise use a system actor whose subject is the existing `actor_subject` and whose display name is `source_account` when present or `Intake: {channel}`. Pass one `created` input containing the initial status, queue, and assignee snapshots. In the authenticated staff-assisted intake view, pass its already authenticated `actor` object. Do not change email, monitoring, problem/change, or other named system callers. In `create_it_child_ticket`, use the human actor and `source_process="ticket.it_child.create"`.

- [ ] **Step 4: Add transition snapshots without visible duplication**

Capture the returned `TransitionHistory` object, then pass one custody input into the same event call:

```python
history = TransitionHistory.objects.create(
    ticket=locked,
    from_status=previous,
    to_status=target,
    actor_subject=actor.keycloak_subject,
    reason=reason,
)
record_ticket_event(
    ticket=locked,
    actor_subject=actor.keycloak_subject,
    action="ticket.transitioned",
    before=before,
    after=after,
    metadata={"reason": reason},
    custody_actor=user_actor(actor),
    custody_events=(
        CustodyEventInput(
            event_type=custody_event_type_for_transition(target.code),
            source_process="ticket.transition",
            source_record_type="workflow_transition",
            source_record_id=str(history.id),
            previous_status=status_snapshot(previous),
            new_status=status_snapshot(target),
            reason=reason,
            occurred_at=history.occurred_at,
        ),
    ),
)
```

Use `CustodyActor.system("it-child-sync", "IT child status synchronisation")` for an automatic parent status sync; use the actual staff actor for a staff-created child and its parent waiting transition.

- [ ] **Step 5: Run service, workflow, and integrity suites**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_services.py apps/tickets/tests/test_intake_api.py apps/tickets/tests/test_transition_api.py apps/tickets/tests/test_workflow_capabilities.py apps/tickets/tests/test_it_child.py apps/tickets/tests/test_it_child_integrity.py apps/tickets/tests/test_integrity_boundaries.py apps/tickets/tests/test_custody.py -q
ruff check apps/tickets/custody.py apps/tickets/services.py apps/tickets/it_child.py apps/tickets/views.py
```

Expected: every command exits 0 and existing audit/outbox assertions remain unchanged.

- [ ] **Step 6: Commit service integration**

```powershell
git add backend/apps/tickets/custody.py backend/apps/tickets/services.py backend/apps/tickets/it_child.py backend/apps/tickets/views.py backend/apps/tickets/tests/test_services.py backend/apps/tickets/tests/test_intake_api.py backend/apps/tickets/tests/test_it_child.py backend/apps/tickets/tests/test_it_child_integrity.py backend/apps/tickets/tests/test_custody.py
git diff --cached --check
git commit -m "feat(tickets): capture lifecycle custody"
```

---

### Task 4: Backfill authoritative legacy custody and install database protection

**Files:**
- Create: `backend/apps/tickets/migrations/0006_backfill_ticket_custody.py`
- Create: `backend/apps/tickets/tests/test_custody_migration.py`
- Modify: `backend/apps/tickets/tests/test_custody.py`
- Modify: `backend/apps/administration/retention.py`
- Modify: `backend/apps/administration/tests/test_retention.py`

**Interfaces:**
- Consumes: `TicketCustodyEvent` schema from Task 1.
- Produces: idempotent historical reconstruction and PostgreSQL trigger `ticket_custody_immutable`.

- [ ] **Step 1: Write failing backfill tests**

Create fixtures with one creation audit, two assignment-style audit payloads, a non-initial transition, and a queue-change audit. Invoke `backfill_ticket_custody(django_apps, None)` twice and assert:

```python
assert list(
    ticket.custody_events.values_list("event_type", flat=True)
) == ["created", "assigned", "queue_changed", "reassigned", "closed"]
assert ticket.custody_events.count() == 5
assert verify_historical_hashes(ticket) is True
```

Add a ticket with no creation audit and assert it receives one `created` event at `ticket.created_at` with actor kind `system`, actor subject `legacy-backfill`, and no invented owner/queue values.

- [ ] **Step 2: Run the migration test in the red state**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_custody_migration.py -q
```

Expected: import fails because migration `0006_backfill_ticket_custody` is absent.

- [ ] **Step 3: Implement deterministic historical reconstruction**

Inside the migration, use only historical models from `apps.get_model`. For every ticket:

1. Gather the earliest `ticket.created` audit or synthesize only the creation timestamp/known initial status.
2. Gather `ticket.work_state.changed` and `ticket.assignment.changed` audits with a changed `assignee` key.
3. Gather audits with a changed `queue` key.
4. Gather non-initial `TransitionHistory` rows.
5. Sort sources by `(occurred_at, source_type, source_id)`.
6. Map no-owner to owner as `assigned`, owner to owner as `reassigned`, and owner to no-owner as `unassigned`.
7. Map target status `reopened` and `closed` specially; all other non-initial transitions are `status_changed`.
8. Resolve current user/queue/status display values when a historical record contains a stable ID; keep absent values null.
9. Calculate sequence and canonical hashes exactly as `custody.py` does.
10. Skip a ticket that already has custody rows, making a repeated run idempotent.

Do not import live models or `custody.py` inside the migration.

- [ ] **Step 4: Add reversible PostgreSQL update/delete protection**

After `RunPython`, add vendor-gated `RunPython` that executes this SQL only when `schema_editor.connection.vendor == "postgresql"`:

```sql
CREATE OR REPLACE FUNCTION reject_ticket_custody_mutation()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE'
     AND current_setting('mhc.allow_ticket_custody_delete', true) = 'on' THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'ticket custody events are immutable';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ticket_custody_immutable
BEFORE UPDATE OR DELETE ON ticket_custody_event
FOR EACH ROW EXECUTE FUNCTION reject_ticket_custody_mutation();
```

The reverse function must drop the trigger before dropping the function. Do not block `TRUNCATE`, which Django test teardown may require. The custom PostgreSQL setting is transaction-local and is used only by the approved whole-ticket retention path; ordinary application requests never set it.

In `_delete_with_orm`, immediately before deleting approved ticket candidates and only when `table == "ticket"` on PostgreSQL, execute:

```python
with connection.cursor() as cursor:
    cursor.execute("SET LOCAL mhc.allow_ticket_custody_delete = 'on'")
```

The retention command already runs disposal inside an atomic transaction; assert that invariant and fail closed if it is not active. Do not enable the setting for message/note disposal or expose it as a general helper.

- [ ] **Step 5: Verify backfill, migration graph, and database enforcement**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_custody_migration.py apps/tickets/tests/test_custody.py apps/administration/tests/test_retention.py -q
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
ruff check apps/tickets/tests/test_custody_migration.py apps/administration/retention.py apps/administration/tests/test_retention.py
```

On PostgreSQL, add a `TransactionTestCase` that executes `UPDATE ticket_custody_event SET reason = 'tampered' WHERE id = %s` with one event ID and asserts `DatabaseError` contains `immutable`. Add a retention test proving an approved whole-ticket disposal removes its custody rows, plus a direct `Ticket.objects.filter(pk=ticket.pk).delete()` test proving it fails without the transaction-local retention setting.

- [ ] **Step 6: Commit backfill and database guard**

```powershell
git add backend/apps/tickets/migrations/0006_backfill_ticket_custody.py backend/apps/tickets/tests/test_custody_migration.py backend/apps/tickets/tests/test_custody.py backend/apps/administration/retention.py backend/apps/administration/tests/test_retention.py
git diff --cached --check
git commit -m "feat(tickets): backfill protected custody history"
```

---

### Task 5: Record idempotent SLA escalations as system custody

**Files:**
- Modify: `backend/apps/sla/services.py`
- Modify: `backend/apps/sla/tests/test_services.py`
- Modify: `backend/apps/tickets/tests/test_custody.py`

**Interfaces:**
- Consumes: Task 2 `CustodyActor`, `CustodyEventInput`, and extended `record_ticket_event`.
- Produces: one `escalated` custody event per SLA instance's first configured threshold crossing.

- [ ] **Step 1: Write failing threshold and idempotency tests**

Add a test that freezes time at the exact configured `escalation_percent` business-time threshold, runs `evaluate_open_slas()` twice, and asserts:

```python
instance.refresh_from_db()
assert instance.escalation_notified_at == threshold_time
events = ticket.custody_events.filter(event_type="escalated")
assert events.count() == 1
event = events.get()
assert event.actor_kind == "system"
assert event.actor_subject == "sla:evaluator"
assert event.source_process == "sla.escalation"
assert event.reason == "resolution SLA crossed the 90% escalation threshold"
assert AuditEvent.objects.filter(
    object_id=str(ticket.id), action="ticket.escalated"
).count() == 1
```

Add a below-threshold case and a paused-SLA case, both with zero escalation events.

- [ ] **Step 2: Run the focused SLA tests in the red state**

Run:

```powershell
Set-Location backend
pytest apps/sla/tests/test_services.py -q
```

Expected: new assertions fail because `evaluate_open_slas` only marks breaches.

- [ ] **Step 3: Implement exact business-time threshold calculation**

Use `business_seconds_between(instance.started_at, now, instance.policy.calendar)` and the policy minutes for the instance kind:

```python
def _target_seconds(instance: SlaInstance) -> int:
    minutes = {
        "acknowledgement": instance.policy.acknowledgement_minutes,
        "first_response": instance.policy.first_response_minutes,
        "update": instance.policy.update_interval_minutes,
        "resolution": instance.policy.resolution_minutes,
    }.get(instance.kind, 0)
    return minutes * 60


def _crossed_escalation_threshold(instance: SlaInstance, now: datetime) -> bool:
    target = _target_seconds(instance)
    if target <= 0 or instance.state != SlaInstance.State.ACTIVE:
        return False
    consumed = business_seconds_between(
        instance.started_at,
        now,
        instance.policy.calendar,
    )
    return consumed * 100 >= target * instance.policy.escalation_percent
```

Select related `ticket` and `policy__calendar`. When the threshold is crossed and `escalation_notified_at` is null, record one audit/outbox/custody event, set the timestamp, and include it in the same atomic evaluator transaction. Preserve existing breach semantics.

- [ ] **Step 4: Run SLA, custody, and correctness suites**

Run:

```powershell
Set-Location backend
pytest apps/sla/tests/test_services.py apps/sla/tests/test_correctness.py apps/tickets/tests/test_custody.py -q
ruff check apps/sla/services.py apps/sla/tests/test_services.py
```

Expected: all tests pass and repeated evaluator runs remain idempotent.

- [ ] **Step 5: Commit SLA custody**

```powershell
git add backend/apps/sla/services.py backend/apps/sla/tests/test_services.py backend/apps/tickets/tests/test_custody.py
git diff --cached --check
git commit -m "feat(sla): record custody escalations"
```

---

### Task 6: Expose a categorised, de-duplicated authorised activity stream

**Files:**
- Modify: `backend/apps/tickets/activity.py`
- Modify: `backend/apps/tickets/tests/test_activity.py`
- Modify: `backend/apps/tickets/views.py`

**Interfaces:**
- Consumes: `TicketCustodyEvent` and source record IDs from Tasks 1–3.
- Produces: `ActivityItem.category` with `public_reply`, `internal_note`, `workflow`, `custody`, `attachment`, or `relationship`.
- Produces: `type="custody_event"` payloads for non-status custody and custody-backed `type="status_transition"` payloads for workflow events.

- [ ] **Step 1: Write failing complete-timeline tests**

Extend the existing activity seed to include creation, assignment, queue change, escalation, status change, reopening, and closure custody. Assert:

```python
activity = build_ticket_activity(ticket, request=request)

assert [(item["occurred_at"], item["id"]) for item in activity] == sorted(
    (item["occurred_at"], item["id"]) for item in activity
)
assert {item["category"] for item in activity} >= {
    "public_reply",
    "internal_note",
    "workflow",
    "custody",
}
assert [
    item["payload"]["action"]
    for item in activity
    if item["type"] == "custody_event"
] == ["created", "assigned", "queue_changed", "escalated"]
assert len(
    [
        item
        for item in activity
        if item["type"] == "status_transition"
        and item["payload"]["to"] == "closed"
    ]
) == 1
```

Assert every custody payload contains `previous_owner`, `new_owner`, `previous_queue`, `new_queue`, `actor_kind`, `source_process`, and `reason`, using null values when not applicable. Retain the existing out-of-scope relationship and auditor scope tests.

Add a legacy mixed work-state audit containing `assignee`, `queue`, and `team`. After its assignment and queue custody records are present, assert ownership and queue render only as custody, while one workflow/work-state item still renders the remaining `team` change.

- [ ] **Step 2: Run activity tests and verify category failures**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_activity.py -q
```

Expected: tests fail because activity items lack categories and custody records are not read.

- [ ] **Step 3: Merge custody records into the activity read model**

Add `category` to `ActivityItem`. Build a set of custody `source_record_id` values where `source_record_type == "workflow_transition"` and exclude those `TransitionHistory` IDs from legacy transition output. Build a second set for `source_record_type == "audit_event"`; for each covered legacy work-state audit, remove the custody-owned `assignee` and `queue` keys from its before/after payload and omit the work-state item if no keys remain. Render custody status events as `status_transition` with category `workflow`; render all other custody types as `custody_event` with category `custody`.

Map existing records:

```python
message -> category "public_reply"
note -> category "internal_note"
legacy transition/work_state -> category "workflow"
attachment -> category "attachment"
relationship -> category "relationship"
```

Use actor snapshots directly from custody records. Keep user lookup only for legacy record types.

- [ ] **Step 4: Keep endpoint authorisation unchanged and explicit**

The existing `activity` action must continue to obtain the ticket through `self.get_object()`. Do not add a global custody endpoint. Add an API test proving an auditor sees custody for an in-scope ticket and an out-of-scope user receives 404 without event data.

- [ ] **Step 5: Run backend verification for Plan 1**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_custody.py apps/tickets/tests/test_custody_migration.py apps/tickets/tests/test_activity.py apps/tickets/tests/test_services.py apps/tickets/tests/test_transition_api.py apps/tickets/tests/test_it_child.py apps/tickets/tests/test_it_child_integrity.py apps/sla/tests/test_services.py apps/sla/tests/test_correctness.py apps/administration/tests/test_retention.py -q
ruff check apps/tickets apps/sla apps/administration/retention.py
mypy apps/tickets apps/sla apps/administration/retention.py
python manage.py makemigrations --check --dry-run
```

Expected: all commands exit 0 with no duplicate workflow activity and a valid creation-to-closure hash chain.

- [ ] **Step 6: Commit the activity read model**

```powershell
git add backend/apps/tickets/activity.py backend/apps/tickets/tests/test_activity.py backend/apps/tickets/views.py
git diff --cached --check
git commit -m "feat(tickets): expose categorised custody activity"
```

## Plan 1 Completion Gate

Before starting Plan 2, verify:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_custody.py apps/tickets/tests/test_custody_migration.py apps/tickets/tests/test_activity.py apps/tickets/tests/test_integrity_boundaries.py apps/sla/tests apps/administration/tests/test_retention.py -q
ruff check apps/tickets apps/sla apps/administration/retention.py
mypy apps/tickets apps/sla apps/administration/retention.py
python manage.py makemigrations --check --dry-run
```

Expected: all commands exit 0. Inspect `git status --short` and confirm only pre-existing unrelated user changes remain.
