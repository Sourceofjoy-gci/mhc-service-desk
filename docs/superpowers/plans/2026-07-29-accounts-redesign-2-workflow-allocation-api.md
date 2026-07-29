# Accounts Redesign 2: Workflow, Allocation, and Reporting API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the authoritative Accounts workflow, atomic assignment/rerouting operations, My Work API, durable in-app notifications, and permission-filtered Accounts and manager reporting.

**Architecture:** Ticket writes are explicit transactional services that acquire a row lock, re-check scoped authority, compare `updated_at`, validate destination state, write history/audit/outbox records, and commit once. Assignment and routing are separated from ordinary work-state edits. Reporting starts from `scope_ticket_queryset`, while notification delivery consumes assignment outbox events idempotently.

**Tech Stack:** Django 5.2 ORM/transactions, Django REST Framework actions, PostgreSQL row locks, Celery, pytest/pytest-django, existing audit/outbox/SLA/workflow modules.

## Global Constraints

- Complete `2026-07-29-accounts-redesign-1-authority-domain.md` first.
- Preserve unrelated pre-existing working-tree changes; stage only task-owned files or hunks after reviewing `git diff --cached`.
- Use `updated_at` optimistic concurrency on every ticket mutation; stale writes return HTTP 409 with `code="stale_ticket"`.
- Out-of-scope records return 404; visible records with a denied action return 403.
- Only eligible in-domain agents/supervisors may own a ticket; managers, auditors, inactive users, wrong-domain users, and technical-only administrators are not assignees unless they also hold an eligible domain role.
- A service-desk manager may assign and reroute visible Normal/Sensitive tickets but may not reply, note, upload, or transition without a separate domain action role.
- Accounts resolution records an enquiry outcome only and must require `no_transaction_executed=true`.
- Assignment, status/history, audit, and outbox creation are one database transaction.
- Notification delivery retries must never repeat or roll back assignment.
- Querysets, dashboard counts, workload aggregates, searches, and exports use the same visibility scope.
- Follow test-driven development and observe each focused test fail for the intended reason.

## File Structure

- `backend/apps/tickets/assignment.py`: assignment eligibility, locking, initial assignment status, and event creation.
- `backend/apps/tickets/routing.py`: extend Plan 1 route validation with audited ticket rerouting and exception resolution.
- `backend/apps/tickets/services.py`: workflow transitions and financial-context edits.
- `backend/apps/tickets/workflow.py`: action/assignment-aware transition visibility.
- `backend/apps/notifications/tasks.py`: idempotent outbox-to-in-app-notification delivery.
- `backend/apps/reporting/views.py`: generic domain dashboard and manager overview.
- `backend/apps/tickets/views.py`: thin DRF adapters for assignment, routing, My Work, and financial context.

---

### Task 1: Seed and enforce the Accounts enquiry workflow

**Files:**
- Modify: `backend/apps/tickets/seed_workflow.py`
- Modify: `backend/apps/tickets/workflow.py`
- Modify: `backend/apps/tickets/permissions.py`
- Modify: `backend/apps/tickets/services.py`
- Modify: `backend/apps/tickets/api.py`
- Modify: `backend/apps/tickets/views.py`
- Create: `backend/apps/tickets/tests/test_accounts_workflow.py`
- Modify: `backend/apps/tickets/tests/test_transition_api.py`
- Modify: `backend/apps/tickets/tests/test_workflow_capabilities.py`

**Interfaces:**
- Produces: all approved Accounts status codes and transition rows.
- Produces: `update_financial_context(*, ticket_id, actor, expected_updated_at, changes, request=None, snapshot=None) -> Ticket`.
- Updates: `transition_ticket(..., no_transaction_executed=False, external_finance_reference="") -> Ticket`.
- Produces API: `PATCH /api/v1/tickets/{number}/financial-state/`.
- Preserves API: `POST /api/v1/tickets/{number}/transition/` with additive Accounts resolution fields.

- [ ] **Step 1: Write failing status and transition tests**

Add `test_accounts_workflow.py`:

```python
import pytest

from apps.tickets.seed_workflow import seed_workflow
from apps.workflow.models import Status, Transition


pytestmark = pytest.mark.django_db

ACCOUNT_STATUSES = {
    "new",
    "triage",
    "assigned",
    "in_progress",
    "waiting_requester",
    "pending_financial_verification",
    "waiting_internal_finance",
    "supervisor_review",
    "resolved",
    "closed",
    "reopened",
    "cancelled",
    "duplicate",
}


def test_accounts_workflow_seed_is_complete_and_idempotent():
    seed_workflow()
    seed_workflow()
    assert set(Status.objects.filter(domain="accounts").values_list("code", flat=True)) == ACCOUNT_STATUSES
    assert Status.objects.get(domain="accounts", code="closed").is_terminal
    assert Status.objects.get(domain="accounts", code="cancelled").is_terminal
    assert Status.objects.get(domain="accounts", code="duplicate").is_terminal
    assert Transition.objects.filter(
        domain="accounts",
        from_status__code="supervisor_review",
        to_status__code="resolved",
        required_role="supervisor-accounts",
        sets_resolution=True,
    ).count() == 1


def test_assignment_transition_is_not_exposed_as_a_manual_action(accounts_ticket, accounts_agent):
    accounts_ticket.status = Status.objects.get(domain="accounts", code="triage")
    accounts_ticket.save(update_fields=["status"])
    assert "assigned" not in {
        transition.to_status.code
        for transition in available_transitions(accounts_ticket, accounts_agent)
    }
```

Add API cases for every diagram edge and a parameterised test that every unlisted edge returns `invalid_transition`.

- [ ] **Step 2: Run the Accounts workflow tests in the red state**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_accounts_workflow.py apps/tickets/tests/test_workflow_capabilities.py -q
```

Expected: FAIL because no Accounts workflow rows or aliases exist.

- [ ] **Step 3: Add exact Accounts seeds**

Add statuses in the approved order and public labels:

```python
ACCOUNTS_STATUSES: list[StatusSeed] = [
    ("new", "New", True, False, 10, "Received"),
    ("triage", "Triage", False, False, 20, "Being reviewed"),
    ("assigned", "Assigned", False, False, 30, "Assigned"),
    ("in_progress", "In Progress", False, False, 40, "Being worked on"),
    ("reopened", "Reopened", False, False, 45, "Being worked on"),
    ("waiting_requester", "Waiting for Requester", False, False, 50, "Waiting for your information"),
    ("pending_financial_verification", "Pending Financial Verification", False, False, 60, "Verification in progress"),
    ("waiting_internal_finance", "Waiting for Internal Finance Unit", False, False, 70, "Referred internally"),
    ("supervisor_review", "Supervisor Review", False, False, 80, "Being reviewed"),
    ("resolved", "Resolved", False, False, 90, "Response provided"),
    ("closed", "Closed", False, True, 100, "Closed"),
    ("cancelled", "Cancelled", False, True, 110, ""),
    ("duplicate", "Duplicate", False, True, 120, ""),
]
```

Seed the diagram transitions. Mark `triage -> assigned` with `required_role="assignment-service"` so it remains a workflow edge but is reachable only through the assignment service. Mark `supervisor_review -> resolved` with `required_role="supervisor-accounts"` and `sets_resolution=True`. Require `reason` for waiting, cancellation, duplicate, review return, and reopening transitions. Require the retained-ticket relationship before Duplicate in service validation.

- [ ] **Step 4: Restrict ticket actions to action-capable owners or supervisors**

Add `can_action_ticket` to `permissions.py` in Plan 1's capability model and consume it in `available_transitions`, message/note/upload paths, and `can_update_work_state`:

```python
def can_action_ticket(user: User, ticket: Ticket, *, request: object | None = None) -> bool:
    if not has_authority_capability(user, TICKET_ACTION, request=request):
        return False
    groups = user_groups(user)
    if groups & SUPERVISOR_GROUPS_BY_DOMAIN.get(ticket.domain, set()):
        return True
    return ticket.assignee_id == user.id
```

An ordinary Accounts agent sees no lifecycle actions until assigned. An Accounts supervisor may intervene in visible Accounts tickets. A manager-only, auditor, security-responder-only, or technical administrator sees no action transitions.

- [ ] **Step 5: Add financial-context validation and endpoint**

Add serializers:

```python
class FinancialStateRequestSerializer(serializers.Serializer[dict[str, object]]):
    updated_at = serializers.DateTimeField()
    financial_enquiry_category = serializers.ChoiceField(
        required=False,
        choices=Ticket.FinancialEnquiryCategory.choices,
    )
    financial_reference = serializers.CharField(required=False, allow_blank=True, max_length=128)
    external_finance_reference = serializers.CharField(required=False, allow_blank=True, max_length=128)
    enquiry_amount = serializers.DecimalField(required=False, allow_null=True, max_digits=14, decimal_places=2)
    enquiry_currency = serializers.RegexField(required=False, allow_blank=True, regex=r"^[A-Za-z]{3}$")
    financial_verification_status = serializers.ChoiceField(
        required=False,
        choices=Ticket.FinancialVerificationStatus.choices,
    )
```

`update_financial_context` must lock and scope the ticket, require `domain="accounts"` and `can_action_ticket`, compare `updated_at`, require currency exactly when amount is non-null, uppercase currency, save changed fields, and call `record_ticket_event(action="ticket.financial_context.changed")`. It must reject keys outside this allowlist and must never accept credential fields.

Expose it as a `financial-state` PATCH action with `invalid_financial_state`, `ticket_action_forbidden`, `stale_ticket`, 404 scope, and the common error envelope.

- [ ] **Step 6: Enforce Accounts resolution and review rules**

Extend `TransitionRequestSerializer`:

```python
no_transaction_executed = serializers.BooleanField(required=False, default=False)
external_finance_reference = serializers.CharField(required=False, allow_blank=True, max_length=128)
```

In `available_transitions`, suppress direct `in_progress -> resolved` when `ticket.request_type.requires_supervisor_review` is true. In `transition_ticket`, when an Accounts transition sets resolution:

- require `no_transaction_executed is True`;
- require `resolution_code` and `resolution_summary`;
- save the supplied external finance reference when present;
- preserve a previously stored reference when the request omits it;
- include all resolution values in the audit/outbox event; and
- set `no_transaction_executed=True`.

On Reopened, clear active resolution fields and set `no_transaction_executed=False`; the prior event/history remains append-only.

- [ ] **Step 7: Verify workflow and commit**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_accounts_workflow.py apps/tickets/tests/test_transition_api.py apps/tickets/tests/test_workflow_capabilities.py apps/tickets/tests/test_integrity_boundaries.py -q
ruff check apps/tickets/seed_workflow.py apps/tickets/workflow.py apps/tickets/services.py apps/tickets/api.py apps/tickets/views.py
```

Expected: all commands exit 0; manager-only and unassigned ordinary agents cannot action tickets; all approved Accounts edges work; resolution without the no-transaction affirmation fails.

Commit:

```powershell
git add backend/apps/tickets/seed_workflow.py backend/apps/tickets/workflow.py backend/apps/tickets/services.py backend/apps/tickets/api.py backend/apps/tickets/views.py backend/apps/tickets/permissions.py backend/apps/tickets/tests/test_accounts_workflow.py backend/apps/tickets/tests/test_transition_api.py backend/apps/tickets/tests/test_workflow_capabilities.py
git diff --cached --check
git commit -m "feat(accounts): enforce enquiry workflow"
```

---

### Task 2: Create an atomic assignment operation

**Files:**
- Create: `backend/apps/tickets/assignment.py`
- Modify: `backend/apps/tickets/api.py`
- Modify: `backend/apps/tickets/views.py`
- Modify: `backend/apps/tickets/services.py`
- Modify: `backend/apps/tickets/permissions.py`
- Modify: `backend/apps/tickets/tests/test_work_state.py`
- Modify: `backend/apps/tickets/tests/test_work_state_api.py`
- Create: `backend/apps/tickets/tests/test_assignment.py`
- Create: `backend/apps/tickets/tests/test_assignment_api.py`

**Interfaces:**
- Produces: `assign_ticket(*, ticket_id, actor, assignee_id, expected_updated_at, reason="", request=None, snapshot=None) -> Ticket`.
- Produces: `AssignmentRequestSerializer` with `assignee_id`, `expected_updated_at`, and `reason`.
- Produces API: `POST /api/v1/tickets/{number}/assignment/`.
- Compatibility: assignment-only `PATCH /work-state/` delegates to `assign_ticket`; mixed assignment/work-state requests fail with `assignment_must_be_separate`.

- [ ] **Step 1: Write failing service tests for authority and atomicity**

Create service cases including:

```python
def test_self_assignment_sets_owner_and_assigned_status_atomically(accounts_ticket, accounts_agent):
    accounts_ticket.status = Status.objects.get(domain="accounts", code="triage")
    accounts_ticket.save(update_fields=["status"])
    updated = assign_ticket(
        ticket_id=accounts_ticket.id,
        actor=accounts_agent,
        assignee_id=accounts_agent.id,
        expected_updated_at=accounts_ticket.updated_at,
    )
    assert updated.assignee_id == accounts_agent.id
    assert updated.status.code == "assigned"
    assert TransitionHistory.objects.filter(
        ticket=updated,
        from_status__code="triage",
        to_status__code="assigned",
    ).count() == 1
    assert OutboxEvent.objects.filter(
        aggregate_id=str(updated.id),
        event_type="ticket.assignment.changed",
    ).count() == 1


def test_manager_can_assign_but_cannot_be_assignee(accounts_ticket, manager, accounts_agent):
    updated = assign_ticket(
        ticket_id=accounts_ticket.id,
        actor=manager,
        assignee_id=accounts_agent.id,
        expected_updated_at=accounts_ticket.updated_at,
        reason="Balance Accounts workload",
    )
    assert updated.assignee_id == accounts_agent.id
    with pytest.raises(TicketValidationError) as exc_info:
        assign_ticket(
            ticket_id=updated.id,
            actor=manager,
            assignee_id=manager.id,
            expected_updated_at=updated.updated_at,
            reason="Invalid target",
        )
    assert exc_info.value.fields == {"assignee_id": ["Select an eligible assignee."]}
```

Add rollback tests by patching `record_ticket_event` to raise; stale-update tests; concurrent two-agent self-claim tests using `TransactionTestCase`; wrong-domain, inactive, auditor, technical-admin, and Restricted-target cases; and a reassignment test proving active/waiting status is preserved.

- [ ] **Step 2: Run assignment tests and verify the service is absent**

Run `pytest apps/tickets/tests/test_assignment.py apps/tickets/tests/test_assignment_api.py -q`.

Expected: FAIL on importing `assign_ticket` and the assignment endpoint returns 404.

- [ ] **Step 3: Implement the locked assignment service**

Implement this sequence inside `@transaction.atomic`:

```python
locked = (
    scope_ticket_queryset(
        actor,
        Ticket.objects.select_for_update(of=("self",)),
        snapshot=authority,
    )
    .select_related("status", "assignee")
    .get(id=ticket_id)
)
if locked.updated_at != expected_updated_at:
    raise TicketConflictError(locked.updated_at)

is_self_claim = locked.assignee_id is None and assignee_id == actor.id
if is_self_claim:
    if not can_self_assign(actor, locked, request=request):
        raise TicketPermissionError
elif not can_assign(actor, locked, request=request):
    raise TicketPermissionError
elif not reason.strip():
    raise TicketValidationError({"reason": ["Enter a reason for assignment."]})

if not eligible_assignee_queryset(locked).filter(id=assignee_id).exists():
    raise TicketValidationError({"assignee_id": ["Select an eligible assignee."]})
```

For a first assignment from Triage, change status to Assigned and create one TransitionHistory row in the same transaction. If legacy data is New, create New-to-Triage and Triage-to-Assigned history rows before the final save so the approved sequence remains visible. Reassignment from Assigned, In Progress, any waiting state, Supervisor Review, or Reopened preserves status.

Write `ticket.assignment.changed` with old/new assignee IDs and metadata containing `reason`, `recipient_subject`, `recipient_label`, and `assignment_kind` (`self`, `assigned`, or `reassigned`). Do not include requester or financial content.

- [ ] **Step 4: Expose the endpoint and compatibility adapter**

Add:

```python
class AssignmentRequestSerializer(serializers.Serializer[dict[str, object]]):
    assignee_id = serializers.UUIDField()
    expected_updated_at = serializers.DateTimeField()
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)
```

Add `@action(detail=True, methods=["post"], url_path="assignment")`. Map invalid target/reason to HTTP 400 with a specific field and code `ineligible_assignee` for target failure, denied action to 403, stale to 409, and lost scope to 404.

Remove `assignee` from ordinary `WORK_STATE_FIELDS`. During one compatibility period, `work_state` accepts an assignment-only payload and delegates to `assign_ticket`; if assignment is combined with another change, return HTTP 400 with code `assignment_must_be_separate`. New frontend code must use the explicit endpoint.

Update `TicketDetailSerializer.get_capabilities()` to return server-calculated `can_action`, `can_self_assign`, `can_assign`, `can_reroute`, `can_monitor`, `can_change_confidentiality`, `can_add_message`, `can_add_note`, and `can_upload_attachment`. Retain `can_reassign` as an alias of `can_assign` for one compatibility release. Manager-only responses must have assignment/rerouting/monitoring true as applicable and every action/content/upload flag false.

- [ ] **Step 5: Verify concurrency and commit**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_assignment.py apps/tickets/tests/test_assignment_api.py apps/tickets/tests/test_work_state.py apps/tickets/tests/test_work_state_api.py -q
ruff check apps/tickets/assignment.py apps/tickets/api.py apps/tickets/views.py apps/tickets/services.py apps/tickets/permissions.py
```

Expected: one concurrent claimant succeeds, the other receives `stale_ticket`; assignment/status/event rollback together on injected failure.

Commit:

```powershell
git add backend/apps/tickets/assignment.py backend/apps/tickets/api.py backend/apps/tickets/views.py backend/apps/tickets/services.py backend/apps/tickets/permissions.py backend/apps/tickets/tests/test_assignment.py backend/apps/tickets/tests/test_assignment_api.py backend/apps/tickets/tests/test_work_state.py backend/apps/tickets/tests/test_work_state_api.py
git diff --cached --check
git commit -m "feat(tickets): add atomic assignment operation"
```

---

### Task 3: Add audited rerouting and manager routing exceptions

**Files:**
- Modify: `backend/apps/tickets/routing.py`
- Modify: `backend/apps/tickets/api.py`
- Modify: `backend/apps/tickets/views.py`
- Modify: `backend/apps/tickets/urls.py`
- Modify: `backend/apps/organisations/views.py`
- Modify: `backend/apps/organisations/urls.py`
- Create: `backend/apps/organisations/tests/test_route_options.py`
- Create: `backend/apps/tickets/tests/test_rerouting.py`
- Create: `backend/apps/tickets/tests/test_routing_exception_api.py`

**Interfaces:**
- Produces: `reroute_ticket(*, ticket_id, actor, service, request_type, office, queue, priority, expected_updated_at, reason, request=None, snapshot=None) -> Ticket`.
- Produces: `map_status_to_domain(code: str, destination_domain: str, *, assignee_eligible: bool = True) -> str` for live rerouting and approved migration.
- Produces: `record_routing_exception_decision(*, exception, actor_subject, action, reason, after) -> AuditEvent` with canonical SHA-256 payload hashing.
- Produces API: `POST /api/v1/tickets/{number}/routing/`.
- Produces API: `GET /api/v1/tickets/routing-exceptions/` and `POST /api/v1/tickets/routing-exceptions/{id}/resolve/`.
- Produces API: `GET /api/v1/organisations/offices` with active offices and nested active Service Locations visible to the caller.
- Consumes: `validate_catalogue_route`, `eligible_assignee_queryset`, `TICKET_REROUTE`, and explicit scope helpers from Plan 1.

- [ ] **Step 1: Write failing rerouting tests**

Test exact cross-domain behavior:

```python
def test_manager_reroute_changes_catalogue_and_clears_ineligible_owner(
    operational_ticket,
    manager,
    accounts_service,
    accounts_request_type,
):
    original_assignee = operational_ticket.assignee
    updated = reroute_ticket(
        ticket_id=operational_ticket.id,
        actor=manager,
        service=accounts_service,
        request_type=accounts_request_type,
        office=operational_ticket.office,
        queue=None,
        expected_updated_at=operational_ticket.updated_at,
        reason="Financial enquiry confirmed",
    )
    assert updated.domain == "accounts"
    assert updated.confidentiality == "sensitive"
    assert updated.assignee is None
    assert original_assignee is not None
    assert OutboxEvent.objects.filter(
        aggregate_id=str(updated.id),
        event_type="ticket.routing.changed",
    ).count() == 1
```

Add tests that an Accounts supervisor can change queue/office within Accounts but cannot cross-domain route; an agent, manager on Restricted without a second role, auditor, and technical admin cannot reroute; queue must belong to office; reason is required; stale requests return 409; and an injected event failure rolls everything back.

- [ ] **Step 2: Run rerouting tests in the red state**

Run `pytest apps/tickets/tests/test_rerouting.py apps/tickets/tests/test_routing_exception_api.py -q`.

Expected: FAIL because the mutation and exception APIs do not exist.

- [ ] **Step 3: Implement transactional rerouting**

Lock through `scope_ticket_queryset`, compare `updated_at`, and call `validate_catalogue_route`. Cross-domain changes require `TICKET_REROUTE`; same-domain office/queue/service changes allow the domain supervisor/lead's approved rerouting authority. Validate active Office, active Service Location, and `queue.office_id == office.id`.

If destination domain changes:

- set domain, Service, Request Type, office, and queue together;
- clear an assignee not returned by destination `eligible_assignee_queryset`;
- set Accounts confidentiality to at least Sensitive;
- preserve Restricted rather than lowering it;
- preserve a shared status code when it exists in the destination workflow; otherwise apply the same semantic mapping later reused by Plan 4 (`diagnosing -> in_progress`, requester waits -> `waiting_requester`, internal/vendor/change/IT waits -> `waiting_internal_finance`, quality/validation -> `supervisor_review`); use Triage only when no explicit semantic mapping exists;
- preserve content, attachments, SLA history, activity, and references; and
- emit `ticket.routing.changed` with old/new route, cleared assignee, and required reason.

Do not create new SLA instances here; Task 1's existing SLA synchronization and Plan 4 migration logic handle policy changes explicitly.

- [ ] **Step 4: Expose routing and exception APIs**

Add a `RoutingRequestSerializer` with `service_code`, `request_type_code`, `office_code`, optional `queue_id`, optional validated `priority`, `expected_updated_at`, and required `reason` (max 255). A manager or destination-domain supervisor/lead may adjust priority through this audited operation; ordinary agents cannot. Include old/new priority in the same `ticket.routing.changed` event.

Add a `RoutingExceptionViewSet` limited to identities with `TICKET_REROUTE`. List returns pending metadata-only exceptions. Resolve accepts configured service/request type and reason, validates the route, calls `record_routing_exception_decision(action="routing_exception.resolved", ...)`, and marks it Resolved with `resolved_at`; trusted adapters replay the retained external event using its integration ID. Dismiss requires a reason and records `routing_exception.dismissed`. The helper stores object type `intake_routing_exception`, object ID, actor, reason, old/new status, and selected route; it hashes canonical JSON exactly as `record_ticket_event` does. Never return or reconstruct raw message content.

Replace the current empty Organisations response with an authenticated, scoped route-options response:

```json
{
  "results": [
    {
      "id": "office-uuid",
      "code": "MHC-MBA",
      "name": "Master's Office — Mbabane (Main)",
      "queues": [{"id": "queue-uuid", "name": "Accounts"}]
    }
  ]
}
```

Managers see active offices/queues across their three scopes; domain-scoped users see only permitted offices. Test that inactive offices/queues and out-of-scope offices are absent.

- [ ] **Step 5: Verify routing and commit**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_rerouting.py apps/tickets/tests/test_routing_exception_api.py apps/tickets/tests/test_routing.py apps/tickets/tests/test_scope_api.py apps/organisations/tests/test_route_options.py -q
ruff check apps/tickets/routing.py apps/tickets/api.py apps/tickets/views.py apps/tickets/urls.py apps/organisations/views.py apps/organisations/urls.py
```

Expected: all commands exit 0.

Commit:

```powershell
git add backend/apps/tickets/routing.py backend/apps/tickets/api.py backend/apps/tickets/views.py backend/apps/tickets/urls.py backend/apps/organisations/views.py backend/apps/organisations/urls.py backend/apps/organisations/tests/test_route_options.py backend/apps/tickets/tests/test_rerouting.py backend/apps/tickets/tests/test_routing_exception_api.py
git diff --cached --check
git commit -m "feat(tickets): add audited manager rerouting"
```

---

### Task 4: Deliver My Work and durable assignment notifications

**Files:**
- Modify: `backend/apps/notifications/models.py`
- Create: `backend/apps/notifications/migrations/0002_in_app_notification_state.py`
- Create: `backend/apps/notifications/tasks.py`
- Modify: `backend/apps/notifications/views.py`
- Modify: `backend/apps/notifications/urls.py`
- Modify: `backend/config/settings/base.py`
- Modify: `backend/apps/tickets/views.py`
- Modify: `backend/apps/tickets/api.py`
- Create: `backend/apps/notifications/tests/test_assignment_delivery.py`
- Create: `backend/apps/notifications/tests/test_api.py`
- Create: `backend/apps/tickets/tests/test_my_work_api.py`

**Interfaces:**
- Produces: `publish_ticket_notifications() -> dict[str, int]` and Celery task `apps.notifications.tasks.publish_ticket_notifications`.
- Produces API: `GET /api/v1/notifications/` and `POST /api/v1/notifications/{id}/read/`.
- Produces API: `GET /api/v1/tickets/my-work/` with the canonical page envelope.
- Updates: ticket list rows include `work_flags: string[]` for server-derived SLA/work groupings.

- [ ] **Step 1: Write failing notification idempotency tests**

Add:

```python
def test_assignment_outbox_becomes_one_in_app_notification(assignment_event):
    first = publish_ticket_notifications()
    second = publish_ticket_notifications()
    assert first == {"delivered": 1, "failed": 0}
    assert second == {"delivered": 0, "failed": 0}
    notification = Notification.objects.get(source_event=assignment_event)
    assert notification.channel == "in_app"
    assert notification.recipient == assignment_event.payload["metadata"]["recipient_subject"]
    assert notification.payload["ticket_number"] == assignment_event.payload["ticket_number"]


def test_delivery_failure_keeps_assignment_and_retries(assignment_event, monkeypatch):
    monkeypatch.setattr(Notification.objects, "create", Mock(side_effect=DatabaseError))
    assert publish_ticket_notifications()["failed"] == 1
    assignment_event.refresh_from_db()
    assert assignment_event.status == "pending"
    assert Ticket.objects.get(number=assignment_event.payload["ticket_number"]).assignee_id is not None
```

API tests assert a user sees only notifications whose recipient equals that user's Keycloak subject, cannot mark another user's item read, and ticket links are included only as relative authorised paths.

- [ ] **Step 2: Write failing My Work filters**

Create assigned/unassigned and cross-domain tickets, then assert:

```python
response = client.get("/api/v1/tickets/my-work/?status_group=waiting")
assert response.status_code == 200
assert {row["number"] for row in response.data["results"]} == {waiting.number}
assert all(row["assignee"] == str(agent.id) for row in response.data["results"])
```

Cover `active`, `waiting`, `due_soon`, `at_risk`, `breached`, `overdue`, and `recently_reassigned`. A manager-only identity receives an empty My Work page, not other users' work.

- [ ] **Step 3: Run notification and My Work tests in the red state**

Run:

```powershell
Set-Location backend
pytest apps/notifications/tests/test_assignment_delivery.py apps/notifications/tests/test_api.py apps/tickets/tests/test_my_work_api.py -q
```

Expected: FAIL because notification state, worker, and My Work action are absent.

- [ ] **Step 4: Add idempotent in-app notification state and worker**

Add fields:

```python
source_event = models.OneToOneField(
    "tickets.OutboxEvent",
    on_delete=models.CASCADE,
    related_name="notification",
    null=True,
    blank=True,
)
read_at = models.DateTimeField(null=True, blank=True)
created_at = models.DateTimeField(auto_now_add=True, db_index=True)
```

The worker selects pending `ticket.assignment.changed` events with `select_for_update(skip_locked=True)`, validates metadata strings, uses `get_or_create(source_event=event)`, and then marks the event Published. On failure, increment `attempts`, set `last_error`, and set exponential `next_attempt_at` without exposing payload content in logs.

Register a one-minute beat entry and rely on the existing `apps.notifications.tasks.*` queue route.

- [ ] **Step 5: Implement notification and My Work APIs**

Replace the current empty notification response with recipient-scoped pagination ordered by `-created_at, -id`; add read action that sets `read_at` idempotently. When serializing a ticket notification, re-check the referenced ticket through `scope_ticket_queryset`; include its relative `/tickets/{number}` link only while the recipient can still view that ticket, otherwise return `link=null` while retaining the audit notification.

Add `my_work` as a detail-false TicketViewSet action. Start from `get_queryset().filter(assignee=request.user)`. Define server-side group filters:

- active: non-terminal, non-waiting statuses;
- waiting: status code begins `waiting_` or equals `pending_financial_verification`;
- due soon: active SLA due within 24 hours;
- at risk: active SLA at or beyond policy warning percentage;
- breached/overdue: breached state or due date in the past;
- recently reassigned: a `ticket.assignment.changed` AuditEvent for that ticket/assignee in the last seven days.

Return `work_flags` from one serializer helper so queue and My Work use the same labels. Avoid one query per flag by prefetching SLA instances and using an audit subquery for recent reassignment.

- [ ] **Step 6: Verify notifications/My Work and commit**

Run:

```powershell
Set-Location backend
pytest apps/notifications/tests apps/tickets/tests/test_my_work_api.py apps/tickets/tests/test_assignment.py -q
ruff check apps/notifications apps/tickets/api.py apps/tickets/views.py config/settings/base.py
```

Expected: all commands exit 0; repeated worker runs do not duplicate notifications.

Commit:

```powershell
git add backend/apps/notifications/models.py backend/apps/notifications/migrations/0002_in_app_notification_state.py backend/apps/notifications/tasks.py backend/apps/notifications/views.py backend/apps/notifications/urls.py backend/config/settings/base.py backend/apps/tickets/views.py backend/apps/tickets/api.py backend/apps/notifications/tests/test_assignment_delivery.py backend/apps/notifications/tests/test_api.py backend/apps/tickets/tests/test_my_work_api.py
git diff --cached --check
git commit -m "feat(tickets): add my work and assignment notifications"
```

---

### Task 5: Add Accounts and manager oversight reporting

**Files:**
- Modify: `backend/apps/reporting/views.py`
- Modify: `backend/apps/reporting/urls.py`
- Modify: `backend/apps/reporting/tests/test_permissions.py`
- Create: `backend/apps/reporting/tests/test_accounts_dashboard.py`
- Create: `backend/apps/reporting/tests/test_manager_overview.py`
- Modify: `backend/apps/tickets/api.py`

**Interfaces:**
- Produces API: `GET /api/v1/reports/dashboard/accounts`.
- Produces API: `GET /api/v1/reports/manager-overview`.
- Produces manager payload keys `domains`, `workload`, `priority`, `status`, and `routing_exceptions`.
- Preserves Operational and IT dashboard response contracts.

- [ ] **Step 1: Write failing report-scope tests**

Add a matrix proving Accounts agent/supervisor/manager/auditor permitted behavior and Operational/IT/system-admin denial. Include one Restricted Accounts ticket and assert it is omitted from manager counts but included for Accounts supervisor and auditor.

Add exact manager payload assertions:

```python
response = client.get("/api/v1/reports/manager-overview?domain=accounts")
assert response.status_code == 200
assert response.data["domains"]["accounts"] == {
    "open": 4,
    "unassigned": 1,
    "oldest_unassigned_hours": 26.0,
    "waiting": 1,
    "due_soon": 1,
    "at_risk": 1,
    "breached": 1,
}
assert response.data["workload"][0].keys() == {
    "user_id", "display_name", "domain", "active", "waiting", "overdue"
}
```

Assert a manager-only user cannot post any ticket content even after using overview drill-down.

- [ ] **Step 2: Run reporting tests and verify missing endpoint failures**

Run:

```powershell
Set-Location backend
pytest apps/reporting/tests/test_accounts_dashboard.py apps/reporting/tests/test_manager_overview.py apps/reporting/tests/test_permissions.py -q
```

Expected: FAIL because Accounts and manager endpoints do not exist.

- [ ] **Step 3: Refactor one scoped domain-dashboard helper**

Create a private helper that accepts `domain` and terminal codes, verifies `has_unrestricted_domain_scope`, and starts from:

```python
qs = scope_ticket_queryset(
    request.user,
    Ticket.objects.select_related("status"),
    request=request,
).filter(domain=domain)
```

Reuse it from Operational, IT, and Accounts endpoints so visibility, unassigned, priority, status, SLA risk, and breach calculations cannot drift. Accounts terminal codes are `closed`, `cancelled`, and `duplicate`; Resolved remains visible as pending closure.

- [ ] **Step 4: Implement manager overview from visible rows only**

Require `TICKET_MONITOR`. Allow service-desk managers and read-only auditors; other domain agents use their domain dashboard. Apply optional validated domain, service, request type, office, queue, priority, status, and assignee filters before aggregation.

Aggregate:

- open, unassigned, oldest unassigned age, waiting, due-soon, at-risk, and breached per visible domain;
- active/waiting/overdue counts per eligible assignee and domain;
- priority and status breakdowns; and
- pending routing-exception count only for `TICKET_REROUTE` identities.

Never aggregate unscoped querysets. Restricted data is naturally excluded for managers by their AuthoritySnapshot and included for auditors only through their explicit Restricted capability.

- [ ] **Step 5: Verify reporting, query count, and commit**

Add `django_assert_num_queries` bounds for the overview with 1 and 50 assignees so workload does not issue a query per user.

Run:

```powershell
Set-Location backend
pytest apps/reporting/tests -q
ruff check apps/reporting apps/tickets/api.py
```

Expected: all commands exit 0.

Commit:

```powershell
git add backend/apps/reporting/views.py backend/apps/reporting/urls.py backend/apps/reporting/tests/test_permissions.py backend/apps/reporting/tests/test_accounts_dashboard.py backend/apps/reporting/tests/test_manager_overview.py backend/apps/tickets/api.py
git diff --cached --check
git commit -m "feat(reporting): add accounts and manager oversight"
```

---

## Plan 2 Completion Gate

Run from the repository root:

```powershell
docker compose exec backend python manage.py makemigrations --check --dry-run
docker compose exec backend pytest apps/tickets apps/notifications apps/reporting -q
docker compose exec backend ruff check apps config
docker compose exec backend mypy apps config
```

Expected: all commands exit 0; Accounts workflow edges and resolution guards are enforced; assignment and rerouting are atomic and stale-safe; assignment notifications are durable/idempotent; My Work is owner-only; and reports never leak Restricted or out-of-scope data.
