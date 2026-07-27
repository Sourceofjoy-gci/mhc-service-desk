# Pilot Foundation 2: Lifecycle API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide an authoritative, concurrent-safe ticket lifecycle API with assignment, work state, workflow actions, audit/outbox guarantees, SLA clocks, attachments, and a unified activity timeline.

**Architecture:** Ticket writes pass through atomic domain services that lock the aggregate, validate the caller's persisted Keycloak group snapshot, compare `updated_at`, then write ticket, audit, and outbox records together. Read serializers derive capabilities, transitions, SLA clocks, and activity from authoritative backend data. Existing fields and upload URLs remain compatible while responses gain additive normalized fields.

**Tech Stack:** Django 5.2 ORM/migrations, Django REST Framework 3.15, PostgreSQL row locks, pytest/pytest-django, existing workflow/SLA/files/audit applications.

## Global Constraints

- Complete Plan 1 before this plan; consume `scope_ticket_queryset`, `is_auditor`, and the common error contract.
- Preserve unrelated pre-existing working-tree changes and stage only the files named by each task.
- The listed file-level `git add` commands apply only to paths that were clean at task start. For an already-dirty path, stage only task-owned hunks after reviewing `git diff --cached`; if a hunk cannot be separated from pre-existing work, leave that path uncommitted rather than include someone else's changes.
- Keep `POST /tickets/{number}/transition/` as the only status mutation route.
- Require the last observed `updated_at` for work-state and transition mutations; stale writes return `409` without partial changes.
- Permit agents to self-assign only; permit `ops-supervisors`, `it-leads`, and `system-admins` to reassign in-scope tickets and change confidentiality.
- Add migrations as nullable/additive changes without rewriting existing ticket statuses.
- Write audit and outbox records inside the same transaction as every material ticket mutation.
- Follow test-driven development and run each focused test once in the red state before implementation.

---

### Task 1: Persist identity capabilities and additive lifecycle fields

**Files:**
- Modify: `backend/apps/identity_access/models.py`
- Modify: `backend/apps/identity_access/authentication.py`
- Create: `backend/apps/identity_access/migrations/0002_user_groups.py`
- Modify: `backend/apps/tickets/models.py`
- Create: `backend/apps/tickets/migrations/0004_ticket_next_action_ticket_next_action_at.py`
- Modify: `backend/apps/audit/models.py`
- Create: `backend/apps/audit/migrations/0002_auditevent_payload.py`
- Create: `backend/apps/tickets/tests/test_lifecycle_models.py`

**Interfaces:**
- Produces: `User.groups: list[str]`, a durable snapshot refreshed from every accepted token.
- Produces: nullable/blank `Ticket.next_action` and nullable `Ticket.next_action_at`.
- Produces: `AuditEvent.payload: dict[str, object]` while retaining `payload_hash`.

- [ ] **Step 1: Write failing model and authentication tests**

Assert model defaults and token synchronization:

```python
def test_lifecycle_fields_are_backwards_compatible(ticket):
    ticket.refresh_from_db()
    assert ticket.next_action == ""
    assert ticket.next_action_at is None


def test_audit_payload_defaults_to_empty_dict():
    event = AuditEvent.objects.create(
        actor_subject="agent-1",
        action="ticket.tested",
        object_type="ticket",
        object_id="ticket-1",
        payload_hash="0" * 64,
    )
    assert event.payload == {}
```

Patch JWT verification to return `groups=["ops-agents"]`, authenticate twice with the second payload containing `groups=["ops-supervisors"]`, and assert the saved user's `groups` changes on both existing and new-user paths.

- [ ] **Step 2: Run the model tests and verify missing-field failures**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_lifecycle_models.py -q
```

Expected: FAIL because all three fields are absent.

- [ ] **Step 3: Add fields and generate migrations**

Add:

```python
# identity_access.User
groups = models.JSONField(default=list, blank=True)

# tickets.Ticket
next_action = models.CharField(max_length=255, blank=True)
next_action_at = models.DateTimeField(null=True, blank=True)

# audit.AuditEvent
payload = models.JSONField(default=dict, blank=True)
```

When authentication succeeds, normalize the claim to strings, assign both `user.groups` and request-local `user._groups`, and save `groups` whenever it changed. The debug-token path must persist its parsed groups as well.

Generate deterministic migration files:

```powershell
python manage.py makemigrations identity_access tickets audit
```

Verify the generated operations only add the three fields and have dependencies on each app's current latest migration.

- [ ] **Step 4: Run migration and model verification**

Run:

```powershell
python manage.py migrate
python manage.py makemigrations --check --dry-run
pytest apps/tickets/tests/test_lifecycle_models.py apps/identity_access/tests -q
```

Expected: migrations apply, no model drift remains, and tests pass.

- [ ] **Step 5: Commit the additive schema**

```powershell
git add backend/apps/identity_access/models.py backend/apps/identity_access/authentication.py backend/apps/identity_access/migrations/0002_user_groups.py backend/apps/tickets/models.py backend/apps/tickets/migrations/0004_ticket_next_action_ticket_next_action_at.py backend/apps/audit/models.py backend/apps/audit/migrations/0002_auditevent_payload.py backend/apps/tickets/tests/test_lifecycle_models.py
git commit -m "feat(tickets): add lifecycle planning fields"
```

---

### Task 2: Create atomic ticket audit and outbox event recording

**Files:**
- Create: `backend/apps/tickets/events.py`
- Create: `backend/apps/tickets/tests/test_events.py`
- Modify: `backend/apps/tickets/services.py`
- Modify: `backend/apps/tickets/tests/test_services.py`
- Modify: `backend/apps/files/services.py`
- Create: `backend/apps/files/tests/test_events.py`
- Modify: `backend/apps/tickets/it_child.py`
- Modify: `backend/apps/tickets/tests/test_it_child.py`
- Modify: `backend/apps/tickets/problem_change.py`
- Modify: `backend/apps/email_channel/services.py`
- Modify: `backend/apps/email_channel/tests/test_services.py`
- Modify: `backend/apps/automation/ai_assist.py`
- Modify: `backend/apps/automation/views.py`
- Modify: `backend/apps/automation/tests/test_ai_assist.py`

**Interfaces:**
- Produces: `record_ticket_event(*, ticket, actor_subject, action, before, after, metadata=None, ip_address=None) -> tuple[AuditEvent, OutboxEvent]`.
- Produces: canonical event payload `{ticket_number, actor, before, after, metadata}` and event type equal to `action`.
- Consumes later: work-state and transition services call the same recorder.

- [ ] **Step 1: Write failing event-recorder tests**

Test exact payload/hash behavior:

```python
def test_record_ticket_event_writes_matching_audit_and_outbox(ticket):
    audit, outbox = record_ticket_event(
        ticket=ticket,
        actor_subject="agent-1",
        action="ticket.assignment.changed",
        before={"assignee": None},
        after={"assignee": "agent-1"},
        metadata={"source": "workspace"},
    )
    expected = {
        "ticket_number": ticket.number,
        "actor": "agent-1",
        "before": {"assignee": None},
        "after": {"assignee": "agent-1"},
        "metadata": {"source": "workspace"},
    }
    assert audit.payload == expected
    assert audit.payload_hash == sha256(canonical_json(expected)).hexdigest()
    assert outbox.event_type == "ticket.assignment.changed"
    assert outbox.payload == expected
```

Patch `AuditEvent.objects.create` to raise and call the recorder inside a service transaction; assert neither the ticket mutation nor an outbox row commits.

- [ ] **Step 2: Run event tests and verify the recorder is missing**

Run `pytest backend/apps/tickets/tests/test_events.py -q`.

Expected: FAIL on importing `apps.tickets.events.record_ticket_event`.

- [ ] **Step 3: Implement canonical event recording**

Serialize with `json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()` and SHA-256. Store before/after values only for changed fields. Keep bodies, attachment bytes, raw tokens, and secrets out of event payloads; message/note events store IDs and character counts rather than body text.

- [ ] **Step 4: Write failing material-mutation tests**

Extend service tests to assert these pairs are created atomically:

- `create_ticket` -> `ticket.created` audit + outbox;
- `add_message` -> `ticket.message.created` audit + outbox;
- `add_internal_note` -> `ticket.note.created` audit + outbox;
- `link_tickets` -> `ticket.relationship.created` audit + outbox;
- `record_attachment` -> `ticket.attachment.created` audit + outbox.

Update service signatures to require an actor where it is currently absent and pass the actor from all existing callers. For messages/notes, assert payload includes only record ID, direction/type, and character count.

Add regression assertions for existing direct-write paths: inbound email uses `add_message` and retains sanitised HTML/idempotency metadata; AI-approved replies use `add_message`; IT-child creation/relationship/parent waiting and child-to-parent synchronization create canonical audit/outbox pairs; Problem/Change relationship creation uses `link_tickets`; and automation assignment/priority changes record their before/after values. These paths must not create a second outbox record for the same mutation.

- [ ] **Step 5: Implement atomic material-mutation events**

Decorate each mutation service with `@transaction.atomic` and call `record_ticket_event` after the database write. Replace `create_ticket`'s direct `OutboxEvent.objects.create` with the canonical recorder. Extend `record_attachment` with `actor_subject` and record the metadata event after `Attachment.objects.create`.

Route every direct mutation named in Step 4 through the canonical ticket service or call `record_ticket_event` inside its existing transaction. Extend `add_message` with an optional `body_html_sanitized` argument so email ingestion preserves its current sanitized representation without writing `TicketMessage` directly. Preserve email provider idempotency and use its existing message ID in event metadata.

- [ ] **Step 6: Run focused tests and commit**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_events.py apps/tickets/tests/test_services.py apps/tickets/tests/test_it_child.py apps/files/tests/test_events.py apps/email_channel/tests/test_services.py apps/automation/tests/test_ai_assist.py -q
ruff check apps/tickets/events.py apps/tickets/services.py apps/tickets/it_child.py apps/tickets/problem_change.py apps/tickets/tests/test_events.py apps/tickets/tests/test_services.py apps/tickets/tests/test_it_child.py apps/files/services.py apps/files/tests/test_events.py apps/email_channel/services.py apps/email_channel/tests/test_services.py apps/automation/ai_assist.py apps/automation/views.py apps/automation/tests/test_ai_assist.py
```

Expected: all commands exit 0.

Commit:

```powershell
git add backend/apps/tickets/events.py backend/apps/tickets/tests/test_events.py backend/apps/tickets/services.py backend/apps/tickets/tests/test_services.py backend/apps/tickets/it_child.py backend/apps/tickets/tests/test_it_child.py backend/apps/tickets/problem_change.py backend/apps/files/services.py backend/apps/files/tests/test_events.py backend/apps/email_channel/services.py backend/apps/email_channel/tests/test_services.py backend/apps/automation/ai_assist.py backend/apps/automation/views.py backend/apps/automation/tests/test_ai_assist.py
git commit -m "feat(audit): record ticket mutations atomically"
```

---

### Task 3: Add assignment, assignee discovery, and work-state updates

**Files:**
- Create: `backend/apps/tickets/permissions.py`
- Create: `backend/apps/tickets/tests/test_permissions.py`
- Modify: `backend/apps/tickets/services.py`
- Create: `backend/apps/tickets/tests/test_work_state.py`
- Modify: `backend/apps/tickets/api.py`
- Modify: `backend/apps/tickets/views.py`
- Create: `backend/apps/tickets/tests/test_work_state_api.py`

**Interfaces:**
- Produces: `user_groups(user) -> set[str]`, `can_reassign(user) -> bool`, `can_change_confidentiality(user) -> bool`, and `eligible_assignee_queryset(ticket) -> QuerySet[User]`.
- Produces: `update_work_state(*, ticket_id, actor, expected_updated_at, changes) -> Ticket`.
- Produces: `GET /api/v1/tickets/{number}/assignees/` and `PATCH /api/v1/tickets/{number}/work-state/`.
- Produces: detail `capabilities` containing `can_update_work_state`, `can_self_assign`, `self_assignee_id`, `can_reassign`, and `can_change_confidentiality`.

- [ ] **Step 1: Write failing permission and eligibility tests**

Use persisted `User.groups` and assert:

```python
@pytest.mark.parametrize(
    ("groups", "can_reassign_expected", "can_confidentiality_expected"),
    [
        (["ops-agents"], False, False),
        (["it-agents"], False, False),
        (["ops-supervisors"], True, True),
        (["it-leads"], True, True),
        (["system-admins"], True, True),
        (["auditors"], False, False),
    ],
)
def test_elevated_ticket_permissions(groups, can_reassign_expected, can_confidentiality_expected, user):
    user.groups = groups
    assert can_reassign(user) is can_reassign_expected
    assert can_change_confidentiality(user) is can_confidentiality_expected
```

For an Operational ticket, `eligible_assignee_queryset` includes active users with Operational agent/supervisor/admin groups, excludes inactive and IT-only users, and never includes auditors.

- [ ] **Step 2: Run permission tests and verify missing helpers**

Run `pytest backend/apps/tickets/tests/test_permissions.py -q`.

Expected: FAIL because `apps.tickets.permissions` does not exist.

- [ ] **Step 3: Implement ticket permission helpers**

Use these group sets:

```python
DOMAIN_GROUPS = {
    "operational": {"ops-agents", "ops-supervisors"},
    "it": {"it-agents", "it-leads"},
}
REASSIGN_GROUPS = {"ops-supervisors", "it-leads", "system-admins"}
```

`user_groups` combines persisted `user.groups` with request-local `_groups`. Eligible users are active and either have a group for the ticket domain or `system-admins`.

- [ ] **Step 4: Write failing atomic work-state tests**

Cover:

- unassigned agent self-assignment succeeds;
- agent assignment to another user fails without modifying the ticket;
- supervisor assignment to an eligible same-domain user succeeds;
- cross-domain/inactive/auditor targets fail;
- agent updates team, waiting reason, blocked reason, next action, and next-action time;
- only elevated users change confidentiality;
- stale `updated_at` raises `TicketConflictError` with the current timestamp and leaves all fields unchanged;
- success creates one audit/outbox pair containing changed before/after fields.

Use `select_for_update()` in the service and compare parsed datetimes at microsecond precision.

- [ ] **Step 5: Run work-state tests and verify failures**

Run `pytest backend/apps/tickets/tests/test_work_state.py -q`.

Expected: FAIL because `update_work_state` and its domain errors do not exist.

- [ ] **Step 6: Implement the work-state service**

Define typed errors:

```python
class TicketConflictError(Exception):
    def __init__(self, current_updated_at):
        self.current_updated_at = current_updated_at


class TicketPermissionError(Exception):
    pass


class TicketValidationError(Exception):
    def __init__(self, fields: dict[str, list[str]]):
        self.fields = fields
```

Inside `@transaction.atomic`, reload with `Ticket.objects.select_for_update().select_related("assignee").get(id=ticket_id)`, compare the timestamp, validate the complete change set, apply only allowed fields, save once, and call `record_ticket_event(ticket=locked, actor_subject=actor.keycloak_subject, action="ticket.work_state.changed", before=before, after=after)`.

- [ ] **Step 7: Write failing endpoint tests**

Assert the work-state endpoint:

- requires authentication and an in-scope ticket;
- validates `updated_at` and field types;
- returns refreshed `TicketDetailSerializer` data on `200`;
- returns common-contract `400` field errors for ineligible targets;
- returns common-contract `403` for role denial;
- returns `409` with `code="stale_ticket"` and `fields.updated_at=[current_iso_timestamp]`;
- exposes assignees as `{results: [{id, username, display_name}]}` filtered by ticket domain.

Use stable endpoint codes: `invalid_work_state` for validation, `ticket_action_forbidden` for role denial, and `stale_ticket` for concurrency conflicts. Every explicit response includes `detail`, `fields`, and the request correlation ID.

- [ ] **Step 8: Implement serializers and view actions**

Add:

```python
class WorkStateRequestSerializer(serializers.Serializer):
    updated_at = serializers.DateTimeField()
    assignee = serializers.UUIDField(required=False, allow_null=True)
    team = serializers.CharField(required=False, allow_blank=True, max_length=128)
    waiting_reason = serializers.CharField(required=False, allow_blank=True, max_length=64)
    blocked_reason = serializers.CharField(required=False, allow_blank=True)
    next_action = serializers.CharField(required=False, allow_blank=True, max_length=255)
    next_action_at = serializers.DateTimeField(required=False, allow_null=True)
    confidentiality = serializers.ChoiceField(required=False, choices=Ticket.Confidentiality.choices)
```

Use `@action(detail=True, methods=["patch"], url_path="work-state")` and `@action(detail=True, methods=["get"], url_path="assignees")`. Translate service errors to DRF exceptions or explicit common-contract responses without leaking target-user details.

Add a request-aware `capabilities` serializer field. `can_update_work_state` is false for auditors; `can_self_assign` is true only when the ticket is unassigned and the caller is an eligible assignee; `self_assignee_id` is the caller's local user UUID only when self-assignment is allowed; reassignment and confidentiality booleans come from the permission helpers. This is the sole frontend authority for elevated-control visibility.

- [ ] **Step 9: Run endpoint tests and commit**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_permissions.py apps/tickets/tests/test_work_state.py apps/tickets/tests/test_work_state_api.py -q
ruff check apps/tickets/permissions.py apps/tickets/services.py apps/tickets/api.py apps/tickets/views.py apps/tickets/tests/test_permissions.py apps/tickets/tests/test_work_state.py apps/tickets/tests/test_work_state_api.py
```

Expected: all commands exit 0.

Commit:

```powershell
git add backend/apps/tickets/permissions.py backend/apps/tickets/tests/test_permissions.py backend/apps/tickets/services.py backend/apps/tickets/tests/test_work_state.py backend/apps/tickets/api.py backend/apps/tickets/views.py backend/apps/tickets/tests/test_work_state_api.py
git commit -m "feat(tickets): add concurrent-safe work state"
```

---

### Task 4: Expose capabilities and make workflow transitions concurrent-safe

**Files:**
- Create: `backend/apps/tickets/workflow.py`
- Create: `backend/apps/tickets/tests/test_workflow_capabilities.py`
- Modify: `backend/apps/tickets/services.py`
- Modify: `backend/apps/tickets/api.py`
- Modify: `backend/apps/tickets/views.py`
- Modify: `backend/apps/tickets/tests/test_services.py`
- Create: `backend/apps/tickets/tests/test_transition_api.py`

**Interfaces:**
- Produces: `available_transitions(ticket, actor) -> QuerySet[Transition]`.
- Produces detail `available_transitions: [{to_status, label, requires_resolution, requires_reason}]`.
- Produces list/Kanban `available_transition_codes: string[]`.
- Extends `transition_ticket(*, ticket_id, actor, expected_updated_at, to_status_code, reason="", resolution_code="", resolution_summary="")` with row locking, reopen semantics, and audit/outbox recording.

- [ ] **Step 1: Write failing capability tests**

For seeded Operational and IT workflows, assert only active transitions from the ticket's current status are returned. When `Transition.required_role` is set, assert actors without that group cannot see or execute it. Auditors receive an empty capability list. Serialize a resolution transition as:

```python
{
    "to_status": "resolved",
    "label": "Resolve",
    "requires_resolution": True,
    "requires_reason": False,
}
```

Treat `required_fields` containing `"reason"` as `requires_reason=True`.

- [ ] **Step 2: Run capability tests and verify failure**

Run `pytest backend/apps/tickets/tests/test_workflow_capabilities.py -q`.

Expected: FAIL because the capability module and serializer fields do not exist.

- [ ] **Step 3: Implement server-derived capabilities**

Filter `Transition` by domain, `from_status`, and `is_active=True`; then apply `required_role` against `user_groups(actor)`. Administrators bypass required-role checks; auditors get `.none()`. Add `SerializerMethodField` implementations to ticket list/detail serializers, passing `context={"request": request}` from all view responses.

- [ ] **Step 4: Write failing transition/concurrency tests**

Extend service/API tests for:

- missing `updated_at` returns `400`;
- stale timestamp returns `409` and does not create history/audit/outbox records;
- invalid or role-restricted transition returns `400`/`403` without mutation;
- resolution transition requires code and summary;
- resolving sets resolution fields and `resolved_at`;
- reopening sets `reopened_at`, clears active resolution fields, and keeps the old resolution in audit payload;
- closing sets `closed_at` while non-closing transitions leave it unchanged;
- success creates exactly one `TransitionHistory`, one audit event, and one outbox event;
- response includes refreshed detail and next capabilities.

Use stable endpoint codes: `invalid_transition` for absent/inactive/field-invalid transitions, `ticket_action_forbidden` for required-role denial, and `stale_ticket` for concurrency conflicts.

- [ ] **Step 5: Refactor transition service and endpoint**

Change the request contract:

```python
class TransitionRequestSerializer(serializers.Serializer):
    to_status = serializers.CharField()
    updated_at = serializers.DateTimeField()
    reason = serializers.CharField(required=False, allow_blank=True)
    resolution_code = serializers.CharField(required=False, allow_blank=True)
    resolution_summary = serializers.CharField(required=False, allow_blank=True)
```

Within the service transaction, reload/lock the ticket, compare timestamps, fetch the allowed transition through `available_transitions`, validate required fields, record before values, and apply the target. For `to_status.code == "reopened"`, clear resolution fields and set `reopened_at=timezone.now()`; for `to_status.code == "closed"`, set `closed_at=timezone.now()`. Replace the direct outbox write with `record_ticket_event(ticket=locked, actor_subject=actor.keycloak_subject, action="ticket.transitioned", before=before, after=after, metadata={"reason": reason})` while retaining `TransitionHistory`.

- [ ] **Step 6: Run transition tests and commit**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_workflow_capabilities.py apps/tickets/tests/test_services.py apps/tickets/tests/test_transition_api.py -q
ruff check apps/tickets/workflow.py apps/tickets/services.py apps/tickets/api.py apps/tickets/views.py apps/tickets/tests/test_workflow_capabilities.py apps/tickets/tests/test_services.py apps/tickets/tests/test_transition_api.py
```

Expected: all commands exit 0.

Commit:

```powershell
git add backend/apps/tickets/workflow.py backend/apps/tickets/tests/test_workflow_capabilities.py backend/apps/tickets/services.py backend/apps/tickets/api.py backend/apps/tickets/views.py backend/apps/tickets/tests/test_services.py backend/apps/tickets/tests/test_transition_api.py
git commit -m "feat(workflow): expose safe ticket transitions"
```

---

### Task 5: Add SLA clocks, scoped attachments, and unified activity

**Files:**
- Create: `backend/apps/tickets/activity.py`
- Create: `backend/apps/tickets/tests/test_activity.py`
- Create: `backend/apps/sla/serializers.py`
- Create: `backend/apps/sla/tests/test_serializers.py`
- Modify: `backend/apps/sla/services.py`
- Modify: `backend/apps/sla/tests/test_services.py`
- Modify: `backend/apps/tickets/services.py`
- Modify: `backend/apps/tickets/api.py`
- Modify: `backend/apps/tickets/views.py`
- Modify: `backend/apps/files/views.py`
- Create: `backend/apps/files/tests/test_views.py`

**Interfaces:**
- Produces: `serialize_sla_clocks(ticket, now=None) -> {first_response, resolution}`.
- Produces: `complete_sla`, `sync_slas_for_transition`, and `restart_resolution_sla` so persisted clocks match lifecycle events.
- Produces: `build_ticket_activity(ticket) -> list[dict[str, object]]`, oldest first with stable IDs.
- Produces: `GET /api/v1/tickets/{number}/activity/` and GET/POST attachment metadata at the existing attachment URL.

- [ ] **Step 1: Write failing SLA serialization tests**

Assert an absent instance serializes to `not_started`. Assert active/future is `running`, paused states map to `paused`, met maps to `met`, and breached or active/past-due maps to `breached`. Use this exact shape:

```python
{
    "state": "running",
    "due_at": "2026-07-27T10:00:00Z",
    "remaining_seconds": 3600,
    "overdue_seconds": 0,
}
```

For met/not-started clocks, duration values may be zero and `due_at` may be `None`; never return a negative duration.

- [ ] **Step 2: Write failing SLA lifecycle tests**

Assert the first outbound agent message completes the active `first_response` instance at `ticket.first_responded_at`. Assert Operational transitions to `waiting_requester`, `waiting_internal`, and `waiting_it` pause active clocks as `paused_requester`, `paused_internal`, and `paused_it`; IT transitions to `waiting_user`, `waiting_vendor`, and `waiting_change` map to `paused_requester`, `paused_internal`, and `paused_internal`. Leaving those states resumes clocks and records `SlaPauseHistory`.

Assert resolution marks the resolution instance `met` with `completed_at` unless it was already breached. Reopening starts a fresh resolution measurement from `reopened_at`: set `started_at=reopened_at`, recompute `due_at` with the existing policy's resolution target/calendar, set `state="active"`, and clear completion/breach timestamps. This keeps a reopened ticket from displaying a completed SLA.

- [ ] **Step 3: Implement SLA lifecycle synchronization**

Add transaction-safe `complete_sla(ticket, kind, at)`, `sync_slas_for_transition(ticket, from_code, to_code, actor_subject)`, and `restart_resolution_sla(ticket, at)` helpers. Call `complete_sla(ticket=ticket, kind="first_response", at=ticket.first_responded_at)` from the first outbound staff-message path and call transition synchronization from `transition_ticket` after saving the new status. Preserve existing `SlaPauseHistory` behavior and never create a second instance for the same ticket/kind.

- [ ] **Step 4: Implement and test SLA clock serialization**

Run the new tests red, implement `serialize_sla_clock(instance, now)` and `serialize_sla_clocks(ticket, now)`, then run:

```powershell
pytest backend/apps/sla/tests/test_serializers.py -q
```

Expected: PASS.

- [ ] **Step 5: Write failing activity tests**

Create a ticket with a message, internal note, transition, work-state audit event, attachment, and relationship. Assert ascending `(occurred_at, id)` ordering, unique stable IDs prefixed by source type, correct visibility, and typed payloads. Assert message/note bodies appear only for authenticated staff activity and internal notes are not imported by any public serializer.

- [ ] **Step 6: Implement activity assembly**

Use source IDs such as `message:<uuid>`, `note:<uuid>`, `transition:<uuid>`, `audit:<uuid>`, `attachment:<uuid>`, and `relationship:<uuid>`. Normalize every item to:

```python
{
    "id": "transition:uuid",
    "type": "status_transition",
    "occurred_at": datetime,
    "actor": {"subject": "agent-1", "display_name": "Agent One"},
    "visibility": "internal",
    "payload": {"from": "triage", "to": "in_progress", "reason": "Started"},
}
```

Resolve display names in one query keyed by `keycloak_subject`. Avoid duplicate timeline entries by using `TransitionHistory` for transitions, attachment rows for uploads, and audit rows only for work-state/confidentiality changes.

- [ ] **Step 7: Write failing attachment scope and metadata tests**

Assert `GET /tickets/{number}/attachments/` returns filename, size, media type, uploader, upload time, scan state, and `download_available = scan_status == "clean"`. Assert pending/infected/error files are unavailable. Test that Operational and IT users cannot list, upload, or download the other domain's attachment, security responders can access restricted tickets only, and auditors can list/download but cannot upload.

- [ ] **Step 8: Implement scoped attachment GET/POST/download**

Resolve tickets using:

```python
ticket = get_object_or_404(
    scope_ticket_queryset(request.user, Ticket.objects.all()),
    number=ticket_number,
)
```

Allow GET and POST on `files.views.upload` without changing its URL. Use a serializer or a pure `attachment_metadata` helper for a consistent response. Reject downloads unless the attachment's ticket appears in the scoped queryset and scan status is `clean`. Keep the existing short-lived signed URL and access log.

- [ ] **Step 9: Add detail fields and activity endpoint**

Extend ticket detail additively with `assignee_detail`, `team`, waiting/blocked reasons, next-action fields, confidentiality, domain, relationships, `sla_clocks`, attachment metadata, `reopened_at`, and current `updated_at`. Add a read-only `@action(detail=True, methods=["get"], url_path="activity")` returning `{results: build_ticket_activity(ticket)}`.

- [ ] **Step 10: Run focused and cross-app tests, then commit**

Run:

```powershell
Set-Location backend
pytest apps/sla/tests/test_serializers.py apps/sla/tests/test_services.py apps/tickets/tests/test_activity.py apps/files/tests/test_views.py -q
pytest apps/tickets/tests apps/files/tests apps/sla/tests -q
ruff check apps/tickets/activity.py apps/tickets/api.py apps/tickets/views.py apps/tickets/services.py apps/tickets/tests/test_activity.py apps/sla/serializers.py apps/sla/services.py apps/sla/tests/test_serializers.py apps/sla/tests/test_services.py apps/files/views.py apps/files/tests/test_views.py
```

Expected: all commands exit 0.

Commit:

```powershell
git add backend/apps/tickets/activity.py backend/apps/tickets/tests/test_activity.py backend/apps/sla/serializers.py backend/apps/sla/tests/test_serializers.py backend/apps/sla/services.py backend/apps/sla/tests/test_services.py backend/apps/tickets/services.py backend/apps/tickets/api.py backend/apps/tickets/views.py backend/apps/files/views.py backend/apps/files/tests/test_views.py
git commit -m "feat(tickets): expose activity SLA and attachments"
```

---

## Plan 2 Completion Gate

Run fresh commands:

```powershell
Set-Location backend
python manage.py makemigrations --check --dry-run
python manage.py migrate --check
pytest apps/identity_access/tests apps/tickets/tests apps/files/tests apps/sla/tests apps/reporting/tests -q
ruff check apps/identity_access apps/tickets apps/files apps/sla apps/reporting
python scripts/permission_audit.py
```

Expected: every command exits 0; migrations show no drift; permission audit lists explicit scope enforcement for lifecycle, attachment, and reporting endpoints.
