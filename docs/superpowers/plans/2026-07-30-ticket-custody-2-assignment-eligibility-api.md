# Role-Derived Assignment Eligibility API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let authorised internal staff assign, transfer, unassign, and route tickets only to eligible owners and queues whose effective domain, office, service, queue, and confidentiality authority matches the ticket.

**Architecture:** Identity access exposes effective persisted role grants without widening existing actor scope. A ticket eligibility module converts those grants into explainable candidates and role-derived team labels. A dedicated atomic allocation boundary locks and revalidates the actor, resulting owner, and destination queue, writes audit/outbox/custody records, and returns immutable assignment or routing receipts. The API delegates every assignment and post-creation queue path to that boundary, including legacy work-state requests and automation.

**Tech Stack:** Python 3.12, Django 5.2, Django REST Framework, PostgreSQL, pytest, Keycloak realm JSON, Ruff, mypy

## Global Constraints

- This is an internal staff feature. Do not add requester assignment, public self-service, or public staff discovery.
- Preserve the existing actor permission rules. Add `can_assign` as a clearer capability while retaining `can_reassign` as a compatibility alias for one release.
- Designation authority comes from an active, non-expired `UserRole`; a Keycloak designation name by itself never makes a target eligible.
- A target must match every applicable ticket boundary: role function, domain, office, service, queue, and Restricted-ticket permission.
- Revalidate target eligibility inside the same transaction that locks and changes the ticket. The browser-provided candidate ID is never trusted.
- Admin and auditor identities are not ownership roles unless they also hold a separate active functional `UserRole` that matches the ticket.
- Preserve unrelated working-tree changes and stage only the files listed by each task.

## Plan Boundary and Dependencies

This is Plan 2 of 3. It requires Plan 1's `CustodyActor`, `CustodyEventInput`, `CustodyParty`, `CustodyQueue`, and atomic `record_ticket_event` extension. It produces the candidate, assignment, and guarded queue-routing contracts consumed by Plan 3.

## Canonical Internal Designations

| Role key | Display name | Derived team |
|---|---|---|
| `master` | Master | Office Leadership |
| `deputy-master` | Deputy Master | Office Leadership |
| `assistant-master` | Assistant Master | Office Leadership |
| `assistant-accountant` | Assistant Accountant | Finance |
| `accountant` | Accountant | Finance |
| `senior-accountant` | Senior Accountant | Finance |
| `principal-accountant` | Principal Accountant | Finance |
| `financial-controller` | Financial Controller | Finance |
| `estate-examiner` | Estate Examiner | Estate Administration |
| `records-clerk` | Records Clerk | Records and Data |
| `data-clerk` | Data Clerk | Records and Data |

The Finance family is supported inside currently configured ticket domains and services. This plan does not introduce a new Accounts domain.

## File Structure

- `backend/apps/identity_access/scope.py`: exposes effective active role grants and keeps persisted-role precedence.
- `backend/apps/identity_access/tests/test_scope.py`: covers grant expiry, persisted-role precedence, and designation-only group rejection.
- `backend/apps/tickets/eligibility.py`: owns designation metadata, exact scope matching, candidate search, and owner snapshots.
- `backend/apps/tickets/assignment.py`: owns atomic human/system owner and post-creation queue mutations, their shared write boundary, and immutable receipts.
- `backend/apps/tickets/permissions.py`: exposes actor assignment, routing, and explicit queue-clearing capabilities plus the assignment compatibility alias.
- `backend/apps/tickets/workflow.py`: maps an exact-scope designation actor to ordinary domain staff workflow roles without granting supervisor/lead authority.
- `backend/apps/tickets/api.py`: validates assignment and routing requests and serialises receipts.
- `backend/apps/tickets/views.py`: exposes guarded candidate, assignment, and routing actions.
- `backend/apps/tickets/services.py`: removes direct ownership mutation from generic work-state handling and retains queue-less creation as initial-state construction, not post-creation routing.
- `backend/apps/tickets/it_child.py`: retains queue-less IT-child creation and status snapshots without becoming a post-creation queue writer.
- `backend/apps/automation/views.py`: routes automation ownership changes through the system assignment service.
- `backend/scripts/seed_dev.py`: seeds primary designation role definitions without overwriting configured scopes.
- `infrastructure/keycloak/realm-mhc.json`: declares the eleven designation realm roles.
- `backend/apps/tickets/tests/test_eligibility.py`: covers target filtering for every designation and boundary.
- `backend/apps/tickets/tests/test_workflow_capabilities.py`: proves designation staff can action in-scope tickets while actor assignment authority remains unchanged.
- `backend/apps/tickets/tests/test_assignment.py`: covers service atomicity, custody, receipts, and system assignment.
- `backend/apps/tickets/tests/test_assignment_api.py`: covers API permissions, direct-call enforcement, conflicts, and response contracts.
- `backend/apps/tickets/tests/test_routing.py`: covers guarded queue-only and paired owner/queue mutations, atomicity, source snapshots, and API enforcement.
- `backend/apps/tickets/tests/test_integrity_boundaries.py`: prevents supported services, APIs, and automation from bypassing the allocation boundary.
- `backend/apps/tickets/tests/test_assignment_role_matrix.py`: runs assignment and full lifecycle custody for every designation and legacy functional role.
- `backend/apps/automation/tests/test_ai_assist.py`: covers the existing automation rule executor and its assignment delegation.

---

### Task 1: Expose active persisted role grants and seed primary designations

**Files:**
- Modify: `backend/apps/identity_access/scope.py`
- Modify: `backend/apps/identity_access/tests/test_scope.py`
- Modify: `backend/scripts/seed_dev.py`
- Modify: `infrastructure/keycloak/realm-mhc.json`
- Create: `backend/tests/test_primary_staff_roles.py`

**Interfaces:**
- Produces: frozen `EffectiveRoleGrant` with `role_key`, `role_name`, `scopes`, `office_id`, and `expires_at`.
- Produces: `get_effective_role_grants(user: User) -> tuple[EffectiveRoleGrant, ...]`.
- Preserves: `get_authority_snapshot` and existing persisted-role precedence.

- [ ] **Step 1: Write failing identity and seed tests**

Add tests proving all eleven canonical role keys and display names exist in the development seed and Keycloak realm. Add scope tests proving:

1. an active `UserRole` produces one grant with its role key, name, configured scopes, and office constraint;
2. an expired `UserRole` produces no grant;
3. a user with `keycloak_groups=["estate-examiner"]` but no matching persisted `UserRole` produces no designation grant; and
4. existing legacy agents with no persisted roles still receive their current authority snapshot through the legacy group fallback.

Use this complete assertion table in `backend/tests/test_primary_staff_roles.py`:

```python
PRIMARY_STAFF_ROLES = {
    "master": "Master",
    "deputy-master": "Deputy Master",
    "assistant-master": "Assistant Master",
    "assistant-accountant": "Assistant Accountant",
    "accountant": "Accountant",
    "senior-accountant": "Senior Accountant",
    "principal-accountant": "Principal Accountant",
    "financial-controller": "Financial Controller",
    "estate-examiner": "Estate Examiner",
    "records-clerk": "Records Clerk",
    "data-clerk": "Data Clerk",
}
```

- [ ] **Step 2: Run the focused tests and verify the red state**

```powershell
Set-Location backend
pytest apps/identity_access/tests/test_scope.py tests/test_primary_staff_roles.py -q
```

Expected: grant imports and designation seed assertions fail.

- [ ] **Step 3: Implement effective grant extraction**

Add this public frozen type to `scope.py`:

```python
@dataclass(frozen=True)
class EffectiveRoleGrant:
    role_key: str
    role_name: str
    scopes: tuple[Scope, ...]
    office_id: UUID | None
    expires_at: datetime | None
```

Implement `get_effective_role_grants` from active, non-expired `UserRole` rows using `select_related("role", "office")`. Parse each role's validated scopes with the same strict scope parser used by `get_authority_snapshot`; discard an invalid or empty designation scope rather than widening it. Keep this function independent of request-local Keycloak groups.

Refactor shared active-role loading so the authority snapshot and grant extraction use the same expiry predicate. Do not change the legacy group fallback used when no active persisted roles exist.

- [ ] **Step 4: Seed role definitions and realm roles**

In `seed_dev.py`, define `PRIMARY_STAFF_ROLES` once and call `Role.objects.get_or_create` with the display name and a development default scope of `[{"domain": "operational"}]`. Never update the scopes of an existing row; production administrators may already have narrowed it. Add the eleven realm roles to the `roles.realm` list in `realm-mhc.json`; do not attach them to default groups or users.

- [ ] **Step 5: Verify identity access and configuration**

```powershell
Set-Location backend
pytest apps/identity_access/tests/test_scope.py tests/test_primary_staff_roles.py -q
ruff check apps/identity_access/scope.py apps/identity_access/tests/test_scope.py scripts/seed_dev.py tests/test_primary_staff_roles.py
mypy apps/identity_access/scope.py
python -m json.tool ../infrastructure/keycloak/realm-mhc.json > $null
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit the identity increment**

```powershell
git add backend/apps/identity_access/scope.py backend/apps/identity_access/tests/test_scope.py backend/scripts/seed_dev.py infrastructure/keycloak/realm-mhc.json backend/tests/test_primary_staff_roles.py
git diff --cached --check
git commit -m "feat(identity): add primary office designations"
```

---

### Task 2: Build exact, explainable assignee eligibility

**Files:**
- Create: `backend/apps/tickets/eligibility.py`
- Create: `backend/apps/tickets/tests/test_eligibility.py`
- Modify: `backend/apps/tickets/permissions.py`
- Modify: `backend/apps/tickets/tests/test_permissions.py`
- Modify: `backend/apps/tickets/workflow.py`
- Modify: `backend/apps/tickets/tests/test_workflow_capabilities.py`
- Modify: `backend/apps/tickets/api.py`
- Modify: `backend/apps/tickets/tests/test_work_state_api.py`

**Interfaces:**
- Produces: `AssigneeCandidate(id, username, display_name, designations, team_labels)`.
- Produces: `eligible_assignees(ticket: Ticket, *, search: str = "") -> tuple[AssigneeCandidate, ...]`.
- Produces: `is_eligible_assignee(ticket: Ticket, user: User) -> bool`.
- Produces: `custody_party_for_user(ticket: Ticket, user: User) -> CustodyParty`.
- Produces: `can_assign`; preserves `can_reassign` as a delegating alias.
- Extends: existing work-state, content, and ordinary workflow action checks to active exact-scope designation actors without granting them transfer/reassignment authority.
- Tightens: `can_self_assign` so it is true only when the unassigned actor is also an eligible target for that ticket, and returns a server-derived `self_assignee_detail` candidate snapshot for confirmation UI.

- [ ] **Step 1: Write the failing eligibility matrix**

Parameterise every row in the canonical designation table and prove an active user with a non-expired persisted grant for the ticket's exact functional scope is included with the correct designation and team. For each role, add exclusion cases for:

- inactive user;
- expired `UserRole`;
- wrong domain;
- wrong office;
- wrong service;
- wrong queue;
- missing Restricted permission on a Restricted ticket; and
- auditor/admin-only authority without a functional designation or legacy agent role.

Add positive cases where a wildcard is explicitly configured by an omitted optional scope dimension, and negative cases where a different explicit value is configured. Add a search test showing case-insensitive matching on display name, username, designation, and team label, with deterministic ordering by display name, username, then UUID.

Add permission/workflow tests proving each of the eleven persisted designation roles can update ordinary work state, add internal content, and execute a transition with no supervisor-only requirement when the role's scope covers the ticket. Prove the same actor is denied for a mismatched office/service/queue/domain, remains denied for Restricted work without matching Restricted visibility, and does not gain `can_assign`. Prove an active persisted `supervisor-operational` or `lead-it` role retains assignment authority even when its Keycloak group list is empty.

Extend capability tests so `can_assign` is returned explicitly, `can_reassign` has the same value during compatibility, and `can_self_assign` requires an unassigned ticket plus `is_eligible_assignee(ticket, actor)`. When true, `self_assignee_detail` contains the actor's stable ID, username, display name, matching designations, and matching team labels; otherwise it is null. This supports confirmation without exposing the wider candidate directory to ordinary staff.

- [ ] **Step 2: Run the focused tests in the red state**

```powershell
Set-Location backend
pytest apps/tickets/tests/test_eligibility.py apps/tickets/tests/test_permissions.py -q
```

Expected: `apps.tickets.eligibility` is absent and current domain/group filtering admits over-broad users.

- [ ] **Step 3: Implement candidate metadata and scope matching**

Create frozen dataclasses:

```python
@dataclass(frozen=True)
class AssigneeCandidate:
    id: UUID
    username: str
    display_name: str
    designations: tuple[str, ...]
    team_labels: tuple[str, ...]


@dataclass(frozen=True)
class Designation:
    role_key: str
    display_name: str
    team_label: str
```

Define `DESIGNATIONS` from the canonical table in this plan. A persisted grant matches when at least one of its scopes has `scope.domain == ticket.domain`; every non-null scope office/service/queue equals the ticket's corresponding stable identifier; a queue-scoped grant never matches a ticket whose queue is null; an office on `UserRole` also equals the ticket office; and a Restricted ticket passes `can_view_restricted(user, snapshot=authority)`. Confirm the ticket itself appears in `scope_ticket_queryset(user, Ticket.objects.filter(pk=ticket.pk), snapshot=authority)` so existing scope and confidentiality semantics are not weakened.

Legacy `agent-operational`, `supervisor-operational`, `agent-it`, and `lead-it` users without active persisted roles remain candidates through the existing snapshot/group rules. Give them their current role display name and role-derived team label. Do not grant this fallback to any of the eleven designation role keys. A user resolved as an auditor remains mutation-ineligible even when another role is present, preserving the platform's read-only auditor boundary.

Load active users in bounded queries using `prefetch_related("user_roles__role", "user_roles__office", "groups")`; do not run one query per candidate.

- [ ] **Step 4: Make internal action and actor assignment capabilities explicit**

Use active persisted grant keys as well as current legacy group aliases when evaluating existing agent/supervisor/lead roles. Update `can_update_work_state` so a non-auditor designation actor may action only a ticket for which `is_eligible_assignee(ticket, user)` is true; keep the existing legacy group/admin behaviour. This lets the primary office complement work on tickets in its configured scope without granting assignment authority.

In `workflow.py`, treat a matching designation actor as the ordinary agent aliases for the ticket's domain (`ops-agents`/`agent-operational` or `it-agents`/`agent-it`) when filtering `Transition.required_role`. Do not map a designation to supervisor/lead aliases. Existing empty-role transitions remain available through their current rule.

Rename the implementation of `can_reassign` to `can_assign`, preserve its current supervisor/lead/admin actor checks and ticket-scope check, and implement:

```python
def can_reassign(
    user: User,
    *,
    ticket: Ticket | None = None,
    request: object | None = None,
) -> bool:
    return can_assign(user, ticket=ticket, request=request)
```

Do not use `eligible_assignees` to decide actor authority; actor permission and target eligibility are separate checks.

- [ ] **Step 5: Run focused tests and static checks**

```powershell
Set-Location backend
pytest apps/tickets/tests/test_eligibility.py apps/tickets/tests/test_permissions.py apps/tickets/tests/test_workflow_capabilities.py apps/tickets/tests/test_work_state_api.py apps/identity_access/tests/test_scope.py -q
ruff check apps/tickets/eligibility.py apps/tickets/permissions.py apps/tickets/workflow.py apps/tickets/api.py apps/tickets/tests/test_eligibility.py apps/tickets/tests/test_permissions.py apps/tickets/tests/test_workflow_capabilities.py apps/tickets/tests/test_work_state_api.py
mypy apps/tickets/eligibility.py apps/tickets/permissions.py apps/tickets/workflow.py apps/tickets/api.py
```

Expected: all commands exit 0 with every designation covered.

- [ ] **Step 6: Commit the eligibility service**

```powershell
git add backend/apps/tickets/eligibility.py backend/apps/tickets/permissions.py backend/apps/tickets/workflow.py backend/apps/tickets/api.py backend/apps/tickets/tests/test_eligibility.py backend/apps/tickets/tests/test_permissions.py backend/apps/tickets/tests/test_workflow_capabilities.py backend/apps/tickets/tests/test_work_state_api.py
git diff --cached --check
git commit -m "feat(tickets): filter eligible internal assignees"
```

---

### Task 3: Add the atomic assignment service and immutable receipt

**Files:**
- Create: `backend/apps/tickets/assignment.py`
- Create: `backend/apps/tickets/tests/test_assignment.py`
- Modify: `backend/apps/tickets/custody.py`
- Modify: `backend/apps/tickets/events.py`

**Interfaces:**
- Produces: `AssignmentParty`, `AssignmentActor`, `AssignmentReceipt`, and `AssignmentResult` frozen dataclasses.
- Produces: `assign_ticket` for authorised human actors.
- Produces: `assign_ticket_by_system` for named internal processes.

- [ ] **Step 1: Write failing assignment service tests**

Cover these exact cases:

1. unassigned to eligible owner records `assigned`;
2. owner A to eligible owner B records `reassigned`;
3. owner A to no owner records `unassigned`;
4. same owner is a successful no-op with no new audit, outbox, or custody record;
5. stale `expected_updated_at` raises `TicketConflictError` before mutation;
6. actor without `can_assign` raises `TicketPermissionError`;
7. inactive, expired, or scope-mismatched target raises `TicketValidationError({"assignee_id": ["Select an eligible assignee."]})`;
8. forced custody failure rolls back ticket, audit, outbox, and receipt creation; and
9. a system assignment requires a non-empty process key and also revalidates target eligibility.

Assert the success receipt captures the ticket number, previous and new party snapshots, the server timestamp shared with the persisted custody event, and the complete actor snapshot. Assert a same-owner no-op returns action `unchanged`, an unchanged party snapshot, a server timestamp, and no new audit/outbox/custody row.

- [ ] **Step 2: Run the service tests and verify the red state**

```powershell
Set-Location backend
pytest apps/tickets/tests/test_assignment.py -q
```

Expected: `apps.tickets.assignment` is absent.

- [ ] **Step 3: Implement typed result contracts**

Use these complete signatures:

```python
@dataclass(frozen=True)
class AssignmentParty:
    id: str
    display_name: str
    designations: tuple[str, ...]
    team_labels: tuple[str, ...]


@dataclass(frozen=True)
class AssignmentActor:
    kind: str
    subject: str
    display_name: str


@dataclass(frozen=True)
class AssignmentReceipt:
    ticket_number: str
    action: str
    previous_assignee: AssignmentParty | None
    new_assignee: AssignmentParty | None
    occurred_at: datetime
    performed_by: AssignmentActor


@dataclass(frozen=True)
class AssignmentResult:
    ticket: Ticket
    receipt: AssignmentReceipt
    changed: bool
```

Implement `assign_ticket` as a keyword-only function accepting `ticket_id: UUID`, `actor: User`, `assignee_id: UUID | None`, `expected_updated_at: datetime`, optional `reason: str = ""`, optional `request: Request | None = None`, and optional `snapshot: AuthoritySnapshot | None = None`, returning `AssignmentResult`.

Implement `assign_ticket_by_system` as a keyword-only function accepting `ticket_id: UUID`, `assignee_id: UUID | None`, `actor_subject: str`, `actor_display_name: str`, `source_process: str`, and `reason: str`, returning `AssignmentResult`.

- [ ] **Step 4: Implement human assignment atomically**

Inside `transaction.atomic`, scope and lock the ticket and compare `expected_updated_at`. For no-owner to self, require the existing `can_self_assign` conditions (`can_update_work_state`, the actor is the requested target, and `is_eligible_assignee` is true). For assignment to another person, reassignment, or unassignment, require `can_assign`. Load the requested active target and re-run `is_eligible_assignee` after locking. Require a non-blank reason for reassignment and unassignment; initial assignment may omit it. Snapshot both parties before changing the foreign key.

Create one `occurred_at = timezone.now()` value, save only `assignee` and `updated_at`, and call `record_ticket_event` once with action `ticket.assignment.changed`, before/after stable IDs, a human `CustodyActor`, and one typed custody input using that timestamp. Use the same timestamp in the receipt. If the ticket is unassigned and its current workflow exposes an active transition to `assigned`, perform that transition through the canonical transition helper in the same transaction; otherwise leave status unchanged.

- [ ] **Step 5: Implement controlled system assignment**

The system variant locks the unscoped ticket but requires non-empty actor subject, actor display name, source process, and reason. It uses the same target eligibility predicate and write helper as human assignment, records actor kind `system`, and never bypasses target scope. It does not invent human actor authority.

- [ ] **Step 6: Run service, custody, and rollback tests**

```powershell
Set-Location backend
pytest apps/tickets/tests/test_assignment.py apps/tickets/tests/test_custody.py apps/tickets/tests/test_events.py -q
ruff check apps/tickets/assignment.py apps/tickets/custody.py apps/tickets/events.py apps/tickets/tests/test_assignment.py
mypy apps/tickets/assignment.py apps/tickets/custody.py apps/tickets/events.py
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit the assignment service**

```powershell
git add backend/apps/tickets/assignment.py backend/apps/tickets/custody.py backend/apps/tickets/events.py backend/apps/tickets/tests/test_assignment.py
git diff --cached --check
git commit -m "feat(tickets): add atomic assignment service"
```

---

### Task 4: Expose guarded candidate and assignment endpoints

**Files:**
- Modify: `backend/apps/tickets/api.py`
- Modify: `backend/apps/tickets/views.py`
- Modify: `backend/apps/tickets/tests/test_work_state_api.py`
- Create: `backend/apps/tickets/tests/test_assignment_api.py`

**Interfaces:**
- Extends: `GET /api/v1/tickets/{number}/assignees/?search={text}`.
- Produces: `POST /api/v1/tickets/{number}/assignment/`.
- Produces response: `{ticket: TicketDetail, receipt: AssignmentReceipt}`.

- [ ] **Step 1: Write failing API contract and attack tests**

Add tests proving the candidate endpoint returns 403 to a scoped user without `can_assign`, returns only active eligible candidates, includes `designations` and `team_labels`, and honours `search`.

For the assignment endpoint, assert:

- a supervisor can assign an eligible candidate and receives HTTP 200;
- the response receipt names the ticket, previous assignee, new assignee, event timestamp, and performer;
- an assignment-only API user cannot forge an inactive, wrong-office, wrong-service, wrong-queue, wrong-domain, or expired candidate UUID;
- missing reassignment/unassignment reason returns HTTP 400 with `fields.reason`;
- stale timestamp returns HTTP 409 with the current timestamp;
- an out-of-scope ticket remains HTTP 404; and
- an auditor remains HTTP 403 even when the ticket is readable.

- [ ] **Step 2: Run focused API tests in the red state**

```powershell
Set-Location backend
pytest apps/tickets/tests/test_assignment_api.py apps/tickets/tests/test_work_state_api.py -q
```

Expected: the assignment action is absent and the candidate payload is incomplete.

- [ ] **Step 3: Add request and receipt serializers**

Add:

```python
class AssignmentRequestSerializer(serializers.Serializer[dict[str, object]]):
    assignee_id = serializers.UUIDField(allow_null=True)
    expected_updated_at = serializers.DateTimeField()
    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)
```

Add plain serializers for `AssignmentParty`, `AssignmentActor`, and `AssignmentReceipt`; do not persist a separate receipt model. The response serialiser must use immutable party/actor snapshots and the timestamp shared with the custody event, not current mutable user fields.

- [ ] **Step 4: Guard and enrich the candidate endpoint**

Resolve the ticket with `self.get_object()`, require `can_assign(_authenticated_user(request), ticket=ticket, request=request)`, validate `search` as a maximum 100-character string, call `eligible_assignees`, and return stable IDs plus username, display name, designations, and team labels. Return the existing structured 403 problem shape on denial.

- [ ] **Step 5: Add the dedicated assignment action**

Add `assignment` to `get_serializer_class` and `permission_denied` action sets. The action validates the request, calls `assign_ticket`, maps validation/permission/scope/conflict exceptions to the existing structured error conventions, and returns:

```python
return Response(
    {
        "ticket": TicketDetailSerializer(
            result.ticket,
            context=self.get_serializer_context(),
        ).data,
        "receipt": AssignmentReceiptSerializer(result.receipt).data,
    }
)
```

- [ ] **Step 6: Run API and permission regression suites**

```powershell
Set-Location backend
pytest apps/tickets/tests/test_assignment_api.py apps/tickets/tests/test_work_state_api.py apps/tickets/tests/test_permissions.py apps/tickets/tests/test_scope_api.py -q
ruff check apps/tickets/api.py apps/tickets/views.py apps/tickets/tests/test_assignment_api.py apps/tickets/tests/test_work_state_api.py
mypy apps/tickets/api.py apps/tickets/views.py
```

Expected: all commands exit 0 and forged candidate IDs never mutate a ticket.

- [ ] **Step 7: Commit the API contract**

```powershell
git add backend/apps/tickets/api.py backend/apps/tickets/views.py backend/apps/tickets/tests/test_assignment_api.py backend/apps/tickets/tests/test_work_state_api.py
git diff --cached --check
git commit -m "feat(tickets): expose guarded assignment API"
```

---

### Task 5: Centralise assignment and production queue routing

**Files:**
- Modify: `backend/apps/tickets/assignment.py`
- Modify: `backend/apps/tickets/eligibility.py`
- Modify: `backend/apps/tickets/permissions.py`
- Modify: `backend/apps/tickets/services.py`
- Modify: `backend/apps/tickets/api.py`
- Modify: `backend/apps/tickets/views.py`
- Modify: `backend/apps/tickets/tests/test_assignment.py`
- Modify: `backend/apps/tickets/tests/test_assignment_api.py`
- Modify: `backend/apps/tickets/tests/test_permissions.py`
- Modify: `backend/apps/tickets/tests/test_services.py`
- Modify: `backend/apps/tickets/tests/test_work_state_api.py`
- Modify: `backend/apps/tickets/tests/test_integrity_boundaries.py`
- Modify: `backend/apps/automation/views.py`
- Modify: `backend/apps/automation/tests/test_ai_assist.py`
- Create: `backend/apps/tickets/tests/test_routing.py`
- Create: `backend/apps/tickets/tests/test_assignment_role_matrix.py`
- Modify: `docs/permission-matrix.md`

**Interfaces:**
- Generic work-state requests no longer mutate `assignee` directly.
- Assignment-only legacy requests delegate to `assign_ticket` for one release.
- Automation delegates to `assign_ticket_by_system`.
- Preserves `assign_ticket` and `assign_ticket_by_system` as the only public owner-only writers defined in Task 3.
- Produces `is_eligible_assignee_for_queue(ticket: Ticket, user: User, queue: ServiceLocation | None) -> bool`.
- Produces `can_route_ticket(user: User, ticket: Ticket, queue: ServiceLocation | None, *, request: Request | None = None, snapshot: AuthoritySnapshot | None = None) -> bool`.
- Produces `can_unqueue_ticket(user: User, ticket: Ticket, *, request: Request | None = None, snapshot: AuthoritySnapshot | None = None) -> bool`.
- Produces frozen `RoutingReceipt` and `RoutingResult` dataclasses.
- Produces `route_ticket(*, ticket_id: UUID, actor: User, queue_id: UUID | None, assignee_id: UUID | None, expected_updated_at: datetime, reason: str, request: Request | None = None, snapshot: AuthoritySnapshot | None = None) -> RoutingResult`.
- Produces `route_ticket_by_system(*, ticket_id: UUID, queue_id: UUID | None, assignee_id: UUID | None, actor_subject: str, actor_display_name: str, source_process: str, reason: str) -> RoutingResult`.
- Produces `POST /api/v1/tickets/{number}/routing/` with `{queue_id, assignee_id, updated_at, reason}` and `{ticket, receipt}`.

- [ ] **Step 1: Record the current assignment and queue mutation inventory**

Run these repository searches before writing tests:

```powershell
Set-Location backend
rg -n --glob '*.py' '\.queue\s*=|\bqueue_id\s*=|update_fields=.*queue|setattr\(.*queue' apps scripts
rg -n 'queue_snapshot|Ticket\.objects\.create' apps/tickets/services.py apps/tickets/it_child.py
rg -n '\.assignee\s*=|\bassignee_id\s*=|update_fields=.*assignee' apps/tickets apps/automation
```

The baseline inventory must state these observed results:

1. `services.create_ticket` and `it_child.create_it_child_ticket` construct queue-less tickets and capture their initial queue snapshot; they do not provide post-creation routing;
2. `it_child` status synchronisation copies an unchanged queue snapshot into lifecycle custody and does not mutate the queue;
3. no supported production API or service currently changes `Ticket.queue` after creation;
4. the only direct `.queue =` write is test setup in `backend/apps/tickets/tests/test_workflow_capabilities.py`; and
5. generic work state in `tickets/services.py` and `_apply_action` in `automation/views.py` still write ownership directly and must be delegated.

Do not add a public intake queue field or a new automation queue action. The production queue writer in this plan is the guarded routing service and staff API action. The integrity regression must make any later API, service, or automation queue bypass fail review.

- [ ] **Step 2: Write failing allocation-boundary and routing tests**

In `test_services.py`, `test_work_state_api.py`, `test_assignment_api.py`, `test_ai_assist.py`, and `test_integrity_boundaries.py`, add tests proving:

1. the work-state action rejects a mixed payload containing `assignee` plus another field with stable code `assignment_must_be_separate` and `fields.assignee` directing the client to the assignment action;
2. an assignment-only legacy work-state request delegates to the same eligibility and custody enforcement as the dedicated action;
3. automation cannot assign an ineligible target even when a rule contains its username;
4. an eligible automation assignment records a system actor and immutable custody event; and
5. an existing `assign_user` rule whose `action_params` contains only `username` remains successful and records the exact deterministic fallback reason `Automation rule {rule.id} assigned ticket to {username}.`; a non-blank configured `reason` is preserved, while missing, non-string, blank, or whitespace-only reasons use the fallback; and
6. supported ticket APIs, ticket services, IT-child handling, and automation contain no direct post-creation `queue` or `assignee` write outside `assignment.py`.

In `test_routing.py`, use real `ServiceLocation` rows and assert:

1. a permitted supervisor can route an in-scope ticket to an active queue in the same office;
2. inactive, missing, cross-office, and out-of-scope destination queues fail with no ticket, audit, outbox, or custody change;
3. an auditor, inactive actor, ordinary designation actor without `can_assign`, and a direct API caller outside ticket scope cannot route;
4. queue-only routing succeeds only when the existing owner remains eligible for the resulting queue;
5. a queue change that would make the current owner ineligible must explicitly provide `assignee_id=None` or another eligible owner;
6. an authorised supervisor/lead/admin with ticket scope and a matching non-queue-constrained effective scope can clear the queue with `queue_id=None`; a queue-constrained actor, an actor lacking `can_assign`, or an actor outside ticket scope cannot clear it, and clearing performs no active-destination lookup;
7. clearing a queue succeeds with the current owner only when that owner remains eligible for a queue-less ticket; otherwise the request must explicitly unassign or supply another owner eligible for the queue-less result;
8. paired queue change plus assignment, reassignment, or unassignment writes separate consecutive custody inputs in `queue_changed` then owner-event order with the same `occurred_at`, `source_process="ticket.routing"`, and source audit ID;
9. snapshots contain stable queue IDs/labels and owner IDs/display/designation/team values captured before the save;
10. an unchanged queue/owner pair is rejected with `TicketValidationError({"routing": ["Queue and assignee must change."]})`; the API returns HTTP 400 with code `invalid_routing` and the same `fields.routing`, with no ticket, audit, outbox, custody, or receipt side effect;
11. stale `updated_at` has one winner and returns the canonical conflict;
12. injected audit, outbox, or custody failure rolls back both queue and owner; and
13. `POST /routing/` enforces the same service rules, maps request `updated_at` to service `expected_updated_at`, and returns only the immutable routing receipt plus refreshed ticket.

Create a parameterised role-matrix test covering the eleven canonical designation keys plus `agent-operational`, `ops-agents`, `supervisor-operational`, `ops-supervisors`, `agent-it`, `it-agents`, `lead-it`, and `it-leads`. For each role, construct an exact-scope eligible target and exercise a creation-to-closure scenario that assigns the parameterised target, transfers to a backup eligible target, unassigns, assigns again, routes to an active same-office queue through `route_ticket`, crosses one SLA escalation threshold, and executes the domain's valid workflow path through ordinary status change, resolution, reopening, resolution again, and closure. Assert `created`, `assigned`, `reassigned`, `unassigned`, `queue_changed`, `escalated`, `status_changed`, `reopened`, and `closed` each appear in chronological order with no visible workflow duplicate and a valid hash chain. Add a wrong-scope owner and destination queue and assert each is rejected with no extra audit, outbox, or custody row.

- [ ] **Step 3: Run allocation tests in the red state**

```powershell
Set-Location backend
pytest apps/tickets/tests/test_assignment.py apps/tickets/tests/test_assignment_api.py apps/tickets/tests/test_routing.py apps/tickets/tests/test_services.py apps/tickets/tests/test_work_state_api.py apps/tickets/tests/test_integrity_boundaries.py apps/tickets/tests/test_assignment_role_matrix.py apps/automation/tests/test_ai_assist.py -q
```

Expected: `route_ticket`, `RoutingReceipt`, and the routing action are absent; generic work state and automation still mutate ownership directly.

- [ ] **Step 4: Implement the guarded atomic allocation boundary**

Remove `assignee` from `WORK_STATE_FIELDS` and ordinary mutation loops. In the work-state API, inspect validated keys before calling `update_work_state`: delegate an assignment-only request to `assign_ticket` by mapping legacy `updated_at` to `expected_updated_at`, reject a mixed request with code `assignment_must_be_separate` and `fields.assignee`, and keep the dedicated endpoint as the documented path. Mark this compatibility route for removal after one release.

In `eligibility.py`, implement `is_eligible_assignee_for_queue` by applying the existing exact designation/domain/office/service/confidentiality checks against the proposed queue instead of the ticket's current queue. A queue-scoped grant matches only the same stable queue ID; it never matches a null or different destination.

In `permissions.py`, implement `can_route_ticket` as existing `can_assign` authority plus exact destination authority. For a non-null destination, the queue must be active, belong to the ticket office, and be covered by a separate effective scope when the actor's current-ticket grant is queue-constrained. Admin/auditor-only authority does not qualify.

Implement `can_unqueue_ticket` as a separate, explicit authority predicate for `queue=None`. It must require `can_assign(user, ticket=...)`, canonical scope to the current ticket, and at least one effective non-auditor scope that covers the ticket's domain, office, service, and Restricted visibility without a queue constraint (`scope.queue_id is None`; admin scope qualifies only when the actor also satisfies `can_assign`). A grant constrained to the current queue is not unqueue authority because clearing would move the ticket outside that grant. `can_route_ticket(..., queue=None)` must delegate to `can_unqueue_ticket`. Queue clearing performs no destination lookup and therefore has no active-destination requirement.

In `assignment.py`, preserve owner-only behavior in `assign_ticket` and `assign_ticket_by_system`. Extract one private locked allocation writer reused by those functions and the two routing functions. `route_ticket` must:

1. scope and `select_for_update` the ticket before checking `expected_updated_at`;
2. when `queue_id` is non-null, resolve it to an active `ServiceLocation` in `ticket.office`; when it is null, represent an explicit queue clear without querying for a destination;
3. require `can_route_ticket` and a non-blank reason;
4. treat `assignee_id` as the explicit resulting owner, reload it under the transaction, and validate it with `is_eligible_assignee_for_queue`;
5. reject an unchanged queue/owner pair with `TicketValidationError({"routing": ["Queue and assignee must change."]})` before creating a receipt, audit, outbox, or custody record;
6. capture previous and new owner/queue snapshots before saving;
7. capture one `occurred_at = timezone.now()` and save queue and owner once;
8. call `record_ticket_event` once with action `ticket.routing.changed`, before/after stable queue and owner IDs, and `source_process="ticket.routing"`; and
9. pass a `queue_changed` custody input first, followed by `assigned`, `reassigned`, or `unassigned` only when ownership also changed, with the same timestamp and source metadata.

`route_ticket_by_system` uses the same locked writer and destination/resulting-owner eligibility. It requires non-empty actor subject, display name, source process, and reason, and records actor kind `system`; it does not invent human authority or bypass queue/owner eligibility.

Define the immutable result shape in `assignment.py`:

```python
@dataclass(frozen=True)
class RoutingReceipt:
    ticket_number: str
    previous_queue: CustodyQueue | None
    new_queue: CustodyQueue | None
    previous_assignee: AssignmentParty | None
    new_assignee: AssignmentParty | None
    occurred_at: datetime
    performed_by: AssignmentActor


@dataclass(frozen=True)
class RoutingResult:
    ticket: Ticket
    receipt: RoutingReceipt
```

- [ ] **Step 5: Expose the guarded routing API and delegate automation ownership**

Add `QueueRoutingRequestSerializer` to `api.py` with required `updated_at`, nullable required `queue_id`, nullable required `assignee_id`, and a non-blank `reason` capped at 1000 characters. Add plain serializers for `RoutingReceipt`; serialise its stored snapshots without reloading mutable users or queues.

Add `POST /api/v1/tickets/{number}/routing/` in `views.py`. Resolve the ticket through `self.get_object()`, validate the request, and call `route_ticket` with serializer `updated_at` passed explicitly as `expected_updated_at`. Map scope, permission, eligibility/validation, and conflict exceptions to the existing structured 404/403/400/409 ticket-action responses. Routing validation failures, including an unchanged queue/owner pair, use HTTP 400 code `invalid_routing` and preserve the service field map. Return:

```python
Response(
    {
        "ticket": TicketDetailSerializer(
            result.ticket,
            context=self.get_serializer_context(),
        ).data,
        "receipt": RoutingReceiptSerializer(result.receipt).data,
    }
)
```

Replace the direct assignee assignment in `_apply_action` with `assign_ticket_by_system`, using actor subject `automation:{rule.id}`, display name `Automation rule: {rule.name}`, and source process `automation.rule`. Normalise `action_params["reason"]` only when it is a string; strip it and preserve the resulting non-blank value. For backward compatibility with existing rules whose parameters contain only `username` (and for missing, non-string, blank, or whitespace-only values), pass the deterministic non-blank fallback `Automation rule {rule.id} assigned ticket to {username}.`. Cover both the configured and fallback branches in `backend/apps/automation/tests/test_ai_assist.py`, including the exact reason stored in custody. Treat an ineligible target as an unsuccessful action and leave the ticket unchanged.

- [ ] **Step 6: Document the assignment and queue-routing permission matrix**

Extend `docs/permission-matrix.md` with rows for operational agent, operational supervisor, IT agent, IT lead, each of the eleven designations, admin-only, auditor, inactive user, expired role, automation, and direct API caller. Columns must cover actor permission, target eligibility, domain, office, service, queue, Restricted, reassignment reason, and custody actor kind.

Document that assignment authority and queue-routing authority are server-side checks. Non-null queue changes require an active same-office destination plus destination scope. Queue clearing has no destination-active check but requires current-ticket scope, `can_assign`, and an effective matching scope with no queue constraint. Paired owner changes also require resulting-owner eligibility, including queue-less eligibility after clearing. Record that `create_ticket` and IT-child creation are initial-state constructors, while all post-creation queue mutations go through `route_ticket` or `route_ticket_by_system`.

- [ ] **Step 7: Run Plan 2 verification**

```powershell
Set-Location backend
pytest apps/identity_access/tests apps/tickets/tests apps/automation/tests -q
ruff check apps/identity_access apps/tickets apps/automation scripts/seed_dev.py tests/test_primary_staff_roles.py
mypy apps/identity_access apps/tickets apps/automation
python manage.py makemigrations --check --dry-run
```

Expected: all commands exit 0 with no supported direct assignment or post-creation queue bypass.

- [ ] **Step 8: Commit allocation centralisation and documentation**

```powershell
git add backend/apps/tickets/assignment.py backend/apps/tickets/eligibility.py backend/apps/tickets/permissions.py backend/apps/tickets/services.py backend/apps/tickets/api.py backend/apps/tickets/views.py backend/apps/tickets/tests/test_assignment.py backend/apps/tickets/tests/test_assignment_api.py backend/apps/tickets/tests/test_permissions.py backend/apps/tickets/tests/test_services.py backend/apps/tickets/tests/test_work_state_api.py backend/apps/tickets/tests/test_integrity_boundaries.py backend/apps/tickets/tests/test_routing.py backend/apps/tickets/tests/test_assignment_role_matrix.py backend/apps/automation/views.py backend/apps/automation/tests/test_ai_assist.py docs/permission-matrix.md
git diff --cached --check
git commit -m "feat(tickets): centralize assignment and queue routing"
```

## Plan 2 Completion Gate

Before starting Plan 3, verify:

```powershell
Set-Location backend
pytest apps/identity_access/tests apps/tickets/tests apps/automation/tests -q
ruff check apps/identity_access apps/tickets apps/automation scripts/seed_dev.py tests/test_primary_staff_roles.py
mypy apps/identity_access apps/tickets apps/automation
python manage.py makemigrations --check --dry-run
python manage.py check
```

Expected: all commands exit 0. Inspect `git status --short` and confirm only pre-existing unrelated user changes remain.
