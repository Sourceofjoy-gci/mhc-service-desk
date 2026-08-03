# Escalation Supervisor Assignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require a named, eligible Assistant Master, Deputy Master, or Master whenever an operational ticket is escalated, and apply the ownership and status changes atomically.

**Architecture:** Extend the existing transition command with an escalation-only `supervisor_id`, backed by a dedicated supervisor-candidate query. Reuse the existing ticket transaction, authority locks, staff presentation contract, custody ledger, audit log, and transition dialog so the new handoff is secure without granting ordinary staff general assignment authority.

**Tech Stack:** Django 5.2, Django REST Framework, PostgreSQL row locking, pytest/pytest-django, React 18, TypeScript, TanStack Query, Base UI StaffCombobox, Vitest, Testing Library.

## Global Constraints

- The selected target must be a specific active user with an active persisted scoped `assistant-master`, `deputy-master`, or `master` `UserRole`.
- The constrained supervisor handoff applies only to operational tickets; the helper returns no candidate for an IT ticket.
- Realm-role claims alone, auditors, expired roles, legacy operational supervisors, ordinary workers, and cross-scope users are not eligible escalation supervisors.
- Escalation reason and supervisor selection are mandatory.
- Ownership and status changes, SLA synchronization, transition history, audit, custody, and outbox records must commit or roll back together.
- An ordinary scoped worker may perform only this constrained upward handoff; general assignment permissions remain unchanged.
- Non-escalation transition contracts and the existing assignment control remain unchanged.
- No database schema migration or new dependency is permitted.
- The backend and frontend must deploy together because escalation without `supervisor_id` becomes invalid.
- Preserve every unrelated working-tree change and stage only files named by the current task.

---

## File Structure

- `backend/apps/tickets/eligibility.py` — canonical supervisor candidate filtering and locked-target revalidation.
- `backend/apps/tickets/escalation.py` — escalation-specific target resolution and immutable custody snapshots; contains no HTTP logic.
- `backend/apps/tickets/services.py` — atomic status/ownership mutation and audit orchestration.
- `backend/apps/tickets/api.py` — transition request field and existing candidate search validation.
- `backend/apps/tickets/views.py` — supervisor search endpoint and transition request adapter.
- `backend/apps/tickets/tests/test_eligibility.py` — supervisor eligibility matrix.
- `backend/apps/tickets/tests/test_escalation_api.py` — candidate endpoint and transition API contract.
- `backend/apps/tickets/tests/test_escalation_service.py` — atomic mutation, rollback, and evidence tests.
- `frontend/src/lib/api.ts` — supervisor query and transition payload types.
- `frontend/src/lib/ticket-contracts.test.ts` — encoded supervisor search URL contract.
- `frontend/src/features/tickets/TransitionActions.tsx` — escalation dialog selector, query state, and submission.
- `frontend/src/features/tickets/TransitionActions.test.tsx` — user-visible escalation flow and error-state tests.

---

### Task 1: Canonical Escalation Supervisor Eligibility

**Files:**
- Modify: `backend/apps/tickets/eligibility.py`
- Test: `backend/apps/tickets/tests/test_eligibility.py`

**Interfaces:**
- Produces: `ESCALATION_SUPERVISOR_ROLE_KEYS: frozenset[str]`
- Produces: `eligible_escalation_supervisors(ticket: Ticket, *, search: str = "") -> tuple[AssigneeCandidate, ...]`
- Produces: `eligible_escalation_supervisor_candidate(ticket: Ticket, user: User, *, snapshot: AuthoritySnapshot) -> AssigneeCandidate | None`

- [ ] **Step 1: Write the failing supervisor eligibility tests**

Use the existing `_user`, `_grant`, and `_ticket` helpers to create exact
ticket-scoped Assistant Master, Deputy Master, and Master assignments plus an
Examiner, `ops-supervisors` legacy user, expired Master, cross-office Master,
inactive Master, realm-role-only Master, and mixed Master/auditor identity. Assert
only the three active, persisted, scoped canonical supervisors are returned and
that search matches display name, username, designation, team, and role summary.
Add an IT-ticket assertion that the supervisor listing is empty and single-target
resolution returns `None`.

```python
def test_escalation_supervisors_include_only_active_scoped_canonical_roles(basic_world):
    ticket = _ticket(basic_world)
    assistant = _user(display_name="Assistant Dlamini")
    deputy = _user(display_name="Deputy Nkosi")
    master = _user(display_name="Master Mabuza")
    exact_scope = [{"domain": ticket.domain, "office": str(ticket.office_id)}]
    for user, role_key, role_name in (
        (assistant, "assistant-master", "Assistant Master"),
        (deputy, "deputy-master", "Deputy Master"),
        (master, "master", "Master"),
    ):
        _grant(
            user,
            role_key=role_key,
            role_name=role_name,
            scopes=exact_scope,
            office=ticket.office,
        )

    candidates = eligible_escalation_supervisors(ticket)

    assert {candidate.id for candidate in candidates} == {
        assistant.id,
        deputy.id,
        master.id,
    }
    assert all(
        set(candidate.designations)
        <= {"Assistant Master", "Deputy Master", "Master"}
        for candidate in candidates
    )
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
docker compose exec -T backend pytest -q apps/tickets/tests/test_eligibility.py -k escalation_supervisor
```

Expected: FAIL because `eligible_escalation_supervisors` does not exist.

- [ ] **Step 3: Add role-filtered candidate resolution**

Add the exact role set near the existing designation constants:

```python
ESCALATION_SUPERVISOR_ROLE_KEYS = frozenset(
    {"assistant-master", "deputy-master", "master"}
)
```

Add this exact keyword parameter after `require_database_scope_check` in
`_candidate_for_user`:

```python
allowed_designation_role_keys: frozenset[str] | None = None,
```

Immediately after the existing `_functional_matches(...)` call, add this exact
filter. `primary_designation` makes realm/group fallback impossible, and the match
itself proves the selected persisted role covers the ticket:

```python
    if allowed_designation_role_keys is not None:
        matches = tuple(
            match
            for match in matches
            if match.primary_designation
            and match.role_key in allowed_designation_role_keys
        )
    if not matches:
        return None
```

Extract the common list/search/sort body of `eligible_assignees` into
`_eligible_candidates`. Its only behavioral difference is the keyword forwarded to
`_candidate_for_user`:

```python
def _eligible_candidates(
    ticket: Ticket,
    *,
    search: str,
    allowed_designation_role_keys: frozenset[str] | None,
) -> tuple[AssigneeCandidate, ...]:
    users = User.objects.filter(is_active=True).prefetch_related(
        "user_roles__role",
        "user_roles__office",
        "groups",
    )
    candidates = tuple(
        candidate
        for user in users
        if (
            candidate := _candidate_for_user(
                ticket,
                user,
                require_database_scope_check=False,
                allowed_designation_role_keys=allowed_designation_role_keys,
            )
        )
    )
    query = search.strip().casefold()
    if query:
        candidates = tuple(
            candidate
            for candidate in candidates
            if any(
                query in value.casefold()
                for value in (
                    candidate.display_name,
                    candidate.username,
                    *candidate.designations,
                    *candidate.team_labels,
                    *candidate.role_summaries,
                )
            )
        )
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.display_name.casefold(),
                item.username.casefold(),
                str(item.id),
            ),
        )
    )
```

Make `eligible_assignees` call `_eligible_candidates(...,
allowed_designation_role_keys=None)` and add both escalation-specific public
functions:

```python
def eligible_escalation_supervisors(
    ticket: Ticket,
    *,
    search: str = "",
) -> tuple[AssigneeCandidate, ...]:
    if ticket.domain != Ticket.Domain.OPERATIONAL:
        return ()
    return _eligible_candidates(
        ticket,
        search=search,
        allowed_designation_role_keys=ESCALATION_SUPERVISOR_ROLE_KEYS,
    )


def eligible_escalation_supervisor_candidate(
    ticket: Ticket,
    user: User,
    *,
    snapshot: AuthoritySnapshot,
) -> AssigneeCandidate | None:
    if ticket.domain != Ticket.Domain.OPERATIONAL:
        return None
    return _candidate_for_user(
        ticket,
        user,
        authority=snapshot,
        require_database_scope_check=False,
        allowed_designation_role_keys=ESCALATION_SUPERVISOR_ROLE_KEYS,
    )
```

- [ ] **Step 4: Run focused and existing eligibility tests**

Run:

```powershell
docker compose exec -T backend pytest -q apps/tickets/tests/test_eligibility.py
```

Expected: all tests PASS.

- [ ] **Step 5: Commit the eligibility unit**

```powershell
git add backend/apps/tickets/eligibility.py backend/apps/tickets/tests/test_eligibility.py
git commit -m "feat(tickets): filter escalation supervisors"
```

---

### Task 2: Escalation Supervisor Candidate API

**Files:**
- Modify: `backend/apps/tickets/views.py`
- Test: `backend/apps/tickets/tests/test_escalation_api.py`

**Interfaces:**
- Consumes: `eligible_escalation_supervisors(ticket, search=...)`
- Produces: `GET /api/v1/tickets/{number}/escalation-supervisors/?search=...`
- Produces: `{ "results": TicketAssignee[] }`

- [ ] **Step 1: Write failing candidate endpoint tests**

Create `test_escalation_api.py` with an authenticated operational worker whose
current ticket exposes the Escalated transition. Assert HTTP 200, exact supervisor
results, safe response fields, deterministic search, and HTTP 403 when the actor
cannot currently escalate.

```python
def test_escalation_supervisor_endpoint_returns_only_safe_eligible_candidates(
    basic_world,
):
    actor = _scoped_actor(basic_world, role_key="examiner")
    ticket = _ticket(basic_world, status_code="in_progress")
    supervisor = _scoped_actor(basic_world, role_key="assistant-master")

    response = _client(actor).get(
        reverse("tickets-escalation-supervisors", args=[ticket.number])
    )

    assert response.status_code == 200
    assert response.data == {
        "results": [
            {
                "id": str(supervisor.id),
                "username": supervisor.username,
                "display_name": supervisor.display_name,
                "designations": ["Assistant Master"],
                "team_labels": ["Office Leadership"],
                "role_summaries": [
                    "Supervise reviews; validate recommendations; authorise "
                    "workflow progress. Authority: Approve within delegated authority."
                ],
            }
        ]
    }
```

- [ ] **Step 2: Run the endpoint test and verify RED**

Run:

```powershell
docker compose exec -T backend pytest -q apps/tickets/tests/test_escalation_api.py -k supervisor_endpoint
```

Expected: FAIL with HTTP 404 because the action does not exist.

- [ ] **Step 3: Implement the endpoint and shared response projection**

Extract the existing assignee result dictionary in `views.py` into one helper and
reuse it from both candidate endpoints. Import `AssigneeCandidate` and
`eligible_escalation_supervisors` from `eligibility.py`, and import
`available_transitions` from `workflow.py`:

```python
def _candidate_payload(candidate: AssigneeCandidate) -> dict[str, object]:
    return {
        "id": str(candidate.id),
        "username": candidate.username,
        "display_name": candidate.display_name,
        "designations": list(candidate.designations),
        "team_labels": list(candidate.team_labels),
        "role_summaries": list(candidate.role_summaries),
    }
```

Add the action:

```python
@action(detail=True, methods=["get"], url_path="escalation-supervisors")
def escalation_supervisors(
    self,
    request: Request,
    number: str | None = None,
) -> Response:
    ticket = self.get_object()
    actor = _authenticated_user(request)
    can_escalate = available_transitions(
        ticket,
        actor,
        request=request,
    ).filter(to_status__code="escalated").exists()
    if not can_escalate:
        return _ticket_action_error(
            request,
            code="ticket_action_forbidden",
            detail="You cannot perform this ticket action.",
            fields={},
            response_status=status.HTTP_403_FORBIDDEN,
        )
    search_serializer = AssigneeSearchSerializer(data=request.query_params)
    if not search_serializer.is_valid():
        return _ticket_action_error(
            request,
            code="invalid_assignee_search",
            detail="Supervisor search is invalid.",
            fields=_serializer_error_fields(search_serializer.errors),
            response_status=status.HTTP_400_BAD_REQUEST,
        )
    candidates = eligible_escalation_supervisors(
        ticket,
        search=search_serializer.validated_data["search"],
    )
    return Response({"results": [_candidate_payload(item) for item in candidates]})
```

- [ ] **Step 4: Run candidate API and permission tests**

Run:

```powershell
docker compose exec -T backend pytest -q apps/tickets/tests/test_escalation_api.py apps/tickets/tests/test_assignment_api.py
```

Expected: all tests PASS.

- [ ] **Step 5: Commit the candidate API**

```powershell
git add backend/apps/tickets/views.py backend/apps/tickets/tests/test_escalation_api.py
git commit -m "feat(api): expose escalation supervisors"
```

---

### Task 3: Escalation Assignment Plan and Authority Locks

**Files:**
- Create: `backend/apps/tickets/escalation.py`
- Modify: `backend/apps/tickets/services.py`
- Test: `backend/apps/tickets/tests/test_escalation_service.py`

**Interfaces:**
- Consumes: `eligible_escalation_supervisor_candidate(...)`
- Produces: `EscalationAssignmentPlan`
- Produces: `prepare_escalation_assignment(ticket, supervisor_id, *, locked_authorities) -> EscalationAssignmentPlan`
- Changes: `_lock_and_revalidate_mutation_authorities(..., additional_user_ids=...)`

- [ ] **Step 1: Write failing target-resolution and lock tests**

Test exact canonical target acceptance and rejection of ordinary, legacy, inactive,
expired, cross-office, and auditor targets. Add a concurrency-oriented assertion
that actor, previous owner, and selected supervisor IDs are passed to one sorted
authority lock operation rather than locked piecemeal.

```python
def test_prepare_escalation_assignment_rejects_legacy_supervisor(basic_world):
    ticket = _ticket(basic_world, status_code="in_progress")
    legacy = _scoped_actor(basic_world, role_key="ops-supervisors")
    with transaction.atomic():
        authorities = lock_user_authorities((legacy.id,))
        with pytest.raises(IneligibleEscalationSupervisor):
            prepare_escalation_assignment(
                ticket,
                legacy.id,
                locked_authorities=authorities,
            )
```

- [ ] **Step 2: Run target tests and verify RED**

Run:

```powershell
docker compose exec -T backend pytest -q apps/tickets/tests/test_escalation_service.py -k prepare
```

Expected: FAIL because `apps.tickets.escalation` does not exist.

- [ ] **Step 3: Implement immutable escalation assignment planning**

Create the focused module:

```python
from dataclasses import dataclass
from uuid import UUID

from apps.identity_access.authority_lock import LockedUserAuthority
from apps.identity_access.models import User

from .custody import CustodyParty
from .eligibility import (
    AssigneeCandidate,
    eligible_assignee_candidate,
    eligible_escalation_supervisor_candidate,
)
from .models import Ticket


class IneligibleEscalationSupervisor(Exception):
    pass


@dataclass(frozen=True)
class EscalationAssignmentPlan:
    supervisor: User
    candidate: AssigneeCandidate
    previous_owner: CustodyParty | None
    new_owner: CustodyParty
    changed: bool


def _party(user: User, candidate: AssigneeCandidate | None) -> CustodyParty:
    return CustodyParty(
        id=str(user.id),
        subject=user.keycloak_subject,
        display_name=user.display_name or user.username,
        designations=candidate.designations if candidate else (),
        team_labels=candidate.team_labels if candidate else (),
    )


def prepare_escalation_assignment(
    ticket: Ticket,
    supervisor_id: UUID,
    *,
    locked_authorities: dict[UUID, LockedUserAuthority],
) -> EscalationAssignmentPlan:
    try:
        target_authority = locked_authorities[supervisor_id]
    except KeyError as exc:
        raise IneligibleEscalationSupervisor from exc
    target_candidate = eligible_escalation_supervisor_candidate(
        ticket,
        target_authority.user,
        snapshot=target_authority.snapshot,
    )
    if target_candidate is None:
        raise IneligibleEscalationSupervisor

    previous_owner = None
    if ticket.assignee_id is not None:
        try:
            previous_authority = locked_authorities[ticket.assignee_id]
        except KeyError as exc:
            raise RuntimeError("Current assignee authority was not locked.") from exc
        previous_candidate = (
            target_candidate
            if ticket.assignee_id == supervisor_id
            else eligible_assignee_candidate(
                ticket,
                previous_authority.user,
                snapshot=previous_authority.snapshot,
            )
        )
        previous_owner = _party(previous_authority.user, previous_candidate)

    return EscalationAssignmentPlan(
        supervisor=target_authority.user,
        candidate=target_candidate,
        previous_owner=previous_owner,
        new_owner=_party(target_authority.user, target_candidate),
        changed=ticket.assignee_id != supervisor_id,
    )
```

This reads only the already locked authority map. A previous owner who is no longer
eligible is still represented by an immutable identity snapshot with empty role
context; the new supervisor must pass the canonical escalation predicate.

- [ ] **Step 4: Refactor mutation actor locking without changing behavior**

Import `LockedUserAuthority` beside `lock_user_authorities`. Replace the body-sharing
point with `_lock_and_revalidate_mutation_authorities`, then make the existing
single-actor function a wrapper. The new helper calls `lock_user_authorities` once
for actor plus all additional IDs and repeats every current auditor and ticket-scope
check exactly:

```python
def _lock_and_revalidate_mutation_authorities(
    *,
    ticket: Ticket,
    actor: User,
    request: Request | None,
    initial_snapshot: AuthoritySnapshot,
    additional_user_ids: set[UUID],
    scope_failure_is_permission: bool = False,
) -> tuple[_LockedMutationAuthority, dict[UUID, LockedUserAuthority]]:
    request_local_auditor = _has_request_local_auditor_claim(
        actor,
        request=request,
    )
    locked_authorities = lock_user_authorities({actor.id, *additional_user_ids})
    locked_authority = locked_authorities.get(actor.id)
    if locked_authority is None or not locked_authority.user.is_active:
        raise TicketPermissionError
    locked_actor = locked_authority.user
    locked_snapshot = locked_authority.snapshot
    if (
        initial_snapshot.auditor_identity
        or "auditor" in initial_snapshot.capabilities
        or request_local_auditor
        or locked_snapshot.auditor_identity
        or "auditor" in locked_snapshot.capabilities
        or is_auditor_identity(locked_actor)
    ):
        raise TicketPermissionError
    if not scope_ticket_queryset(
        locked_actor,
        Ticket.objects.filter(pk=ticket.pk),
        snapshot=locked_snapshot,
    ).exists():
        if scope_failure_is_permission:
            raise TicketPermissionError
        raise TicketScopeError
    return (
        _LockedMutationAuthority(
            actor=locked_actor,
            snapshot=locked_snapshot,
        ),
        locked_authorities,
    )


def _lock_and_revalidate_mutation_actor(
    *,
    ticket: Ticket,
    actor: User,
    request: Request | None,
    initial_snapshot: AuthoritySnapshot,
    scope_failure_is_permission: bool = False,
) -> _LockedMutationAuthority:
    locked_actor, _ = _lock_and_revalidate_mutation_authorities(
        ticket=ticket,
        actor=actor,
        request=request,
        initial_snapshot=initial_snapshot,
        additional_user_ids=set(),
        scope_failure_is_permission=scope_failure_is_permission,
    )
    return locked_actor
```

- [ ] **Step 5: Run focused service, work-state, and authority-race tests**

Run:

```powershell
docker compose exec -T backend pytest -q apps/tickets/tests/test_escalation_service.py apps/tickets/tests/test_work_state.py apps/tickets/tests/test_mutation_authority_races.py
```

Expected: all tests PASS.

- [ ] **Step 6: Commit the escalation planning unit**

```powershell
git add backend/apps/tickets/escalation.py backend/apps/tickets/services.py backend/apps/tickets/tests/test_escalation_service.py
git commit -m "feat(tickets): validate escalation ownership"
```

---

### Task 4: Atomic Escalation Transition, Audit, and API Contract

**Files:**
- Modify: `backend/apps/tickets/services.py`
- Modify: `backend/apps/tickets/api.py`
- Modify: `backend/apps/tickets/views.py`
- Test: `backend/apps/tickets/tests/test_escalation_service.py`
- Test: `backend/apps/tickets/tests/test_escalation_api.py`
- Test: `backend/apps/tickets/tests/test_transition_api.py`

**Interfaces:**
- Changes: `transition_ticket(..., supervisor_id: UUID | None = None) -> Ticket`
- Changes: `TransitionRequestSerializer.supervisor_id`
- Consumes: `prepare_escalation_assignment(...)`

- [ ] **Step 1: Write failing atomic transition tests**

Add tests for missing and explicit-null supervisor, non-escalation rejection of both
a UUID and explicit null, successful reassignment, already-assigned supervisor,
stale timestamp, target eligibility revocation, and transaction rollback. Assert
exact ticket status/assignee plus transition history, SLA state, audit, custody, and
outbox counts.

```python
def test_escalation_assigns_supervisor_and_records_complete_evidence(basic_world):
    actor = _scoped_actor(basic_world, role_key="examiner")
    supervisor = _scoped_actor(basic_world, role_key="assistant-master")
    ticket = _ticket(basic_world, status_code="in_progress", assignee=actor)

    updated = transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        to_status_code="escalated",
        reason="Requires delegated approval",
        supervisor_id=supervisor.id,
    )

    assert updated.status.code == "escalated"
    assert updated.assignee_id == supervisor.id
    assert list(
        updated.custody_events.values_list("event_type", flat=True)
    )[-2:] == ["reassigned", "escalated"]
    assert AuditEvent.objects.filter(
        object_id=str(ticket.id),
        action__in=["ticket.assignment.changed", "ticket.transitioned"],
    ).count() == 2
    assert OutboxEvent.objects.filter(
        aggregate_id=str(ticket.id),
        event_type__in=["ticket.assignment.changed", "ticket.transitioned"],
    ).count() == 2
```

- [ ] **Step 2: Run atomic tests and verify RED**

Run:

```powershell
docker compose exec -T backend pytest -q apps/tickets/tests/test_escalation_service.py -k "transition or rollback or evidence"
```

Expected: FAIL because `transition_ticket` does not accept or apply
`supervisor_id`.

- [ ] **Step 3: Extend the service command**

Import `EscalationAssignmentPlan`, `IneligibleEscalationSupervisor`, and
`prepare_escalation_assignment` from `escalation.py`, and `TicketCustodyEvent` from
`models.py`. Add
`supervisor_id: UUID | None = None` before `request` in `transition_ticket`.

After locking the ticket and checking `updated_at`, build the complete lock set
before revalidating the actor. Only escalation needs current-owner and target
authority rows:

```python
additional_user_ids: set[UUID] = set()
if to_status_code == "escalated":
    if locked.assignee_id is not None:
        additional_user_ids.add(locked.assignee_id)
    if supervisor_id is not None:
        additional_user_ids.add(supervisor_id)
locked_authority, locked_authorities = (
    _lock_and_revalidate_mutation_authorities(
        ticket=locked,
        actor=actor,
        request=request,
        initial_snapshot=authority,
        additional_user_ids=additional_user_ids,
        scope_failure_is_permission=True,
    )
)
locked_actor = locked_authority.actor
locked_snapshot = locked_authority.snapshot
```

After resolving and authorising `workflow_transition`, merge supervisor validation
with the existing required-field validation so a request missing both values gets
both field errors. Reject `supervisor_id` on every other destination:

```python
missing = {
    field: ["This field is required."]
    for field in required
    if not str(supplied_fields.get(field, "")).strip()
}
if workflow_transition.to_status.code == "escalated":
    if supervisor_id is None:
        missing["supervisor_id"] = ["Select an escalation supervisor."]
elif supervisor_id is not None:
    missing["supervisor_id"] = [
        "This field is only valid when escalating."
    ]
if missing:
    raise TransitionError(missing)
```

Resolve the locked supervisor without exposing the submitted identity, and stage
the assignee change in the same ticket save as the status:

```python
escalation_plan: EscalationAssignmentPlan | None = None
if workflow_transition.to_status.code == "escalated":
    assert supervisor_id is not None
    try:
        escalation_plan = prepare_escalation_assignment(
            locked,
            supervisor_id,
            locked_authorities=locked_authorities,
        )
    except IneligibleEscalationSupervisor as exc:
        raise TransitionError(
            {"supervisor_id": ["Select an eligible escalation supervisor."]}
        ) from exc

previous_assignee_id = locked.assignee_id
update_fields = ["status"]
if escalation_plan is not None and escalation_plan.changed:
    locked.assignee = escalation_plan.supervisor
    update_fields.append("assignee")
```

After the single `locked.save(...)` and before `ticket.transitioned`, record an
assignment event only when ownership changed. Use the same `now`, actor, and reason
as the transition:

```python
if escalation_plan is not None and escalation_plan.changed:
    assignment_event = (
        TicketCustodyEvent.EventType.ASSIGNED
        if previous_assignee_id is None
        else TicketCustodyEvent.EventType.REASSIGNED
    )
    record_ticket_event(
        ticket=locked,
        actor_subject=locked_actor.keycloak_subject,
        action="ticket.assignment.changed",
        before={
            "assignee": (
                str(previous_assignee_id)
                if previous_assignee_id is not None
                else None
            )
        },
        after={"assignee": str(escalation_plan.supervisor.id)},
        metadata={"reason": reason, "source_process": "ticket.escalation"},
        custody_actor=user_actor(locked_actor),
        custody_events=(
            CustodyEventInput(
                event_type=assignment_event,
                source_process="ticket.escalation",
                previous_owner=escalation_plan.previous_owner,
                new_owner=escalation_plan.new_owner,
                reason=reason,
                occurred_at=now,
            ),
        ),
    )
```

Build transition metadata as `{"reason": reason}` and add
`"supervisor_id": str(escalation_plan.supervisor.id)` whenever
`escalation_plan` exists. Pass that metadata to the existing
`ticket.transitioned` event even when `changed` is false.

- [ ] **Step 4: Extend serializer and view adapter**

```python
class TransitionRequestSerializer(serializers.Serializer[dict[str, object]]):
    to_status = serializers.CharField()
    updated_at = serializers.DateTimeField()
    reason = serializers.CharField(required=False, allow_blank=True)
    resolution_code = serializers.CharField(required=False, allow_blank=True)
    resolution_summary = serializers.CharField(required=False, allow_blank=True)
    supervisor_id = serializers.UUIDField(required=False)
```

Pass `serializer.validated_data.get("supervisor_id")` to `transition_ticket` and keep
the existing `TransitionError` problem mapping so field failures remain HTTP 400.

- [ ] **Step 5: Run backend escalation and regression tests**

Run:

```powershell
docker compose exec -T backend pytest -q apps/tickets/tests/test_escalation_service.py apps/tickets/tests/test_escalation_api.py apps/tickets/tests/test_transition_api.py apps/tickets/tests/test_workflow_capabilities.py apps/tickets/tests/test_assignment.py apps/tickets/tests/test_activity.py
```

Expected: all tests PASS.

- [ ] **Step 6: Commit the atomic transition contract**

```powershell
git add backend/apps/tickets/services.py backend/apps/tickets/api.py backend/apps/tickets/views.py backend/apps/tickets/tests/test_escalation_service.py backend/apps/tickets/tests/test_escalation_api.py backend/apps/tickets/tests/test_transition_api.py
git commit -m "feat(api): assign supervisor during escalation"
```

---

### Task 5: Escalation Supervisor Dialog

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Test: `frontend/src/lib/ticket-contracts.test.ts`
- Modify: `frontend/src/features/tickets/TransitionActions.tsx`
- Test: `frontend/src/features/tickets/TransitionActions.test.tsx`

**Interfaces:**
- Produces: `TicketTransitionRequest.supervisor_id?: string`
- Produces: `ticketsApi.escalationSupervisors(number: string, search?: string) -> Promise<{ results: TicketAssignee[] }>`
- Consumes: `StaffCombobox` with `allowUnassigned={false}`

- [ ] **Step 1: Write failing escalation dialog tests**

Add `escalationSupervisors` to the API mock. Define `ESCALATABLE_TICKET` by adding an
Escalate transition with `requires_reason: true`, and let `renderActions` accept an
optional ticket argument. Test selector visibility, loading, mandatory selection,
role context, payload, field errors, query failure, pending state, and successful
ticket/activity refresh. In `ticket-contracts.test.ts`, add a test that proves search
text is URL-encoded and an empty search omits the query string.

```tsx
it("requires and submits a named escalation supervisor", async () => {
  harness.escalationSupervisors.mockResolvedValue({
    results: [ASSISTANT_MASTER],
  });
  harness.transition.mockResolvedValue({
    ...ESCALATABLE_TICKET,
    status_code: "escalated",
    status_name: "Escalated",
    assignee: ASSISTANT_MASTER.id,
    assignee_detail: {
      id: ASSISTANT_MASTER.id,
      display_name: ASSISTANT_MASTER.display_name,
    },
  });
  const user = userEvent.setup();
  renderActions(ESCALATABLE_TICKET);

  await user.click(screen.getByRole("button", { name: "Escalate" }));
  await user.type(screen.getByRole("textbox", { name: "Reason" }), "SLA risk");
  await user.click(
    screen.getByRole("combobox", { name: "Escalate to supervisor" }),
  );
  await user.click(
    await screen.findByRole("option", { name: /Assistant Master Dlamini/ }),
  );
  await user.click(screen.getByRole("button", { name: "Confirm Escalate" }));

  await waitFor(() =>
    expect(harness.transition).toHaveBeenCalledWith(TICKET.number, {
      to_status: "escalated",
      updated_at: TICKET.updated_at,
      reason: "SLA risk",
      supervisor_id: ASSISTANT_MASTER.id,
    }),
  );
});
```

- [ ] **Step 2: Run the UI test and verify RED**

Run:

```powershell
cd frontend
npm.cmd test -- src/features/tickets/TransitionActions.test.tsx src/lib/ticket-contracts.test.ts
```

Expected: FAIL because no supervisor selector or API method exists.

- [ ] **Step 3: Extend frontend API types and client**

```typescript
export interface TicketTransitionRequest {
  to_status: string;
  updated_at: string;
  reason?: string;
  resolution_code?: string;
  resolution_summary?: string;
  supervisor_id?: string;
}

escalationSupervisors: (number: string, search = "") => {
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  const query = params.toString();
  return api<{ results: TicketAssignee[] }>(
    `/tickets/${number}/escalation-supervisors/${query ? `?${query}` : ""}`,
  );
},
```

- [ ] **Step 4: Implement escalation-only selector state**

Import `useQuery` alongside `useMutation`, `useEffect` alongside the current React
hooks, and `StaffCombobox`. Add the same 250 ms `useDebouncedValue` behavior used by
`AssignmentControl`, then add exact escalation state and query wiring:

```tsx
function useDebouncedValue(value: string, delay: number) {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timeout = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timeout);
  }, [delay, value]);

  return debounced;
}

const [supervisorId, setSupervisorId] = useState<string | null>(null);
const [supervisorSearch, setSupervisorSearch] = useState("");
const debouncedSupervisorSearch = useDebouncedValue(supervisorSearch, 250);
const isEscalating = chosen?.to_status === "escalated";
const supervisorQuery = useQuery({
  queryKey: [
    "ticket",
    ticket.number,
    "escalation-supervisors",
    debouncedSupervisorSearch,
  ],
  queryFn: () =>
    ticketsApi.escalationSupervisors(
      ticket.number,
      debouncedSupervisorSearch,
    ),
  enabled: isEscalating,
});
```

Reset supervisor ID and search in both `choose` and `close`. Derive a visible load
error from `apiProblem(supervisorQuery.error)` without replacing a server
`supervisor_id` field error. Render the combobox directly because it already owns
its label and `FieldError`:

```tsx
const supervisorLoadProblem = apiProblem(supervisorQuery.error);
const supervisorError =
  fieldErrors.supervisor_id?.[0] ??
  (supervisorQuery.isError
    ? (supervisorLoadProblem?.detail ?? "Could not load eligible supervisors.")
    : undefined);

{chosen.to_status === "escalated" ? (
  <StaffCombobox
    id="transition-escalation-supervisor"
    label="Escalate to supervisor"
    value={supervisorId}
    options={supervisorQuery.data?.results ?? []}
    onValueChange={setSupervisorId}
    onSearchChange={setSupervisorSearch}
    allowUnassigned={false}
    disabled={disabled}
    loading={supervisorQuery.isLoading || supervisorQuery.isFetching}
    error={supervisorError}
  />
) : null}
```

Before mutation, set `clientErrors.supervisor_id` when no supervisor is selected.
Only for escalation, add `submitted.supervisor_id = supervisorId`. Keep the selected
ID and reason intact on server field errors and stale responses; clear them only on
cancel, selecting a different action, successful completion, or successful reload.

- [ ] **Step 5: Run transition and combobox tests**

Run:

```powershell
cd frontend
npm.cmd test -- src/features/tickets/TransitionActions.test.tsx src/lib/ticket-contracts.test.ts src/components/ui/combobox.test.tsx
```

Expected: all tests PASS.

- [ ] **Step 6: Commit the escalation dialog**

```powershell
git add frontend/src/lib/api.ts frontend/src/lib/ticket-contracts.test.ts frontend/src/features/tickets/TransitionActions.tsx frontend/src/features/tickets/TransitionActions.test.tsx
git commit -m "feat(frontend): select supervisor on escalation"
```

---

### Task 6: Full Verification and Release Evidence

**Files:**
- Modify only if a relevant verification failure identifies a defect in the files from Tasks 1-5.

**Interfaces:**
- Verifies the complete backend and frontend contract from the approved design.

- [ ] **Step 1: Run backend formatting, typing, model, and system checks**

```powershell
docker compose exec -T backend ruff check apps/tickets/eligibility.py apps/tickets/escalation.py apps/tickets/services.py apps/tickets/api.py apps/tickets/views.py apps/tickets/tests/test_eligibility.py apps/tickets/tests/test_escalation_api.py apps/tickets/tests/test_escalation_service.py apps/tickets/tests/test_transition_api.py
docker compose exec -T backend mypy apps/tickets
docker compose exec -T backend python manage.py makemigrations --check --dry-run
docker compose exec -T backend python manage.py check
```

Expected: all commands exit 0; migrations report `No changes detected`.

- [ ] **Step 2: Run the wider backend ticket suite**

```powershell
docker compose exec -T backend pytest -q --reuse-db apps/tickets/tests/test_eligibility.py apps/tickets/tests/test_escalation_api.py apps/tickets/tests/test_escalation_service.py apps/tickets/tests/test_transition_api.py apps/tickets/tests/test_workflow_capabilities.py apps/tickets/tests/test_assignment.py apps/tickets/tests/test_assignment_api.py apps/tickets/tests/test_activity.py apps/tickets/tests/test_custody.py apps/tickets/tests/test_mutation_authority_races.py
```

Expected: all tests PASS with no warnings introduced by this change.

- [ ] **Step 3: Run frontend tests and static checks serially**

```powershell
cd frontend
npm.cmd test -- src/features/tickets/TransitionActions.test.tsx src/features/tickets/TicketDetailPage.test.tsx src/lib/ticket-contracts.test.ts src/components/ui/combobox.test.tsx
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
```

Expected: all commands exit 0. Existing Vite font-resolution and chunk-size warnings
may remain, but no new warning is accepted.

- [ ] **Step 4: Verify the live escalation flow in a browser**

At a 1440×900 desktop viewport and a 390×844 mobile viewport:

1. Sign in as a scoped Examiner with an In Progress operational ticket.
2. Select Escalate and confirm Reason plus Escalate to supervisor are visible.
3. Search for Assistant Master and confirm no Examiner or legacy supervisor appears.
4. Submit after selecting a supervisor.
5. Confirm status becomes Escalated, owner becomes the selected person, and activity
   shows both the ownership handoff and escalation.
6. Repeat opening the dialog at mobile width and confirm no horizontal overflow,
   clipping, overlap, console error, or failed network request.

- [ ] **Step 5: Request independent code review**

Ask the reviewer to focus on atomicity, lock ordering, target scope, auditor denial,
information disclosure, duplicate custody/audit evidence, stale-ticket rollback,
and UI bypasses. Fix every actionable finding and rerun the smallest affected test
plus Steps 1-3.

- [ ] **Step 6: Commit verification-only fixes if required**

If verification required source changes, stage only those exact task files:

```powershell
git add backend/apps/tickets/eligibility.py backend/apps/tickets/escalation.py backend/apps/tickets/services.py backend/apps/tickets/api.py backend/apps/tickets/views.py backend/apps/tickets/tests/test_eligibility.py backend/apps/tickets/tests/test_escalation_api.py backend/apps/tickets/tests/test_escalation_service.py backend/apps/tickets/tests/test_transition_api.py frontend/src/lib/api.ts frontend/src/lib/ticket-contracts.test.ts frontend/src/features/tickets/TransitionActions.tsx frontend/src/features/tickets/TransitionActions.test.tsx
git commit -m "fix(tickets): harden escalation handoff"
```

If no source change was required, do not create an empty commit.
