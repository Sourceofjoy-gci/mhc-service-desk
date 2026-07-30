# Internal Ticket Assignment and Chain-of-Custody Design

**Date:** 2026-07-30
**Status:** Approved design; awaiting written-spec review
**Application:** MHC Service Desk
**Primary users:** Master, Deputy Master, Assistant Master, Assistant Accountant, Accountant, Senior Accountant, Principal Accountant, Financial Controller, Estate Examiner, Records Clerk, Data Clerk, internal supervisors/leads, security responders, and auditors

## 1. Objective

Improve internal ticket allocation and accountability so an authorised staff member can assign, transfer, or unassign a ticket only to a currently eligible colleague, and every material ownership or lifecycle event remains visible in a complete chronological chain of custody.

This work is internal-first. It improves staff team operations, manager controls, audit access, and the staff ticket activity history. It does not add or redesign requester self-service, anonymous intake, public ticket tracking, or any public account experience.

Requester-visible replies remain represented in the staff activity history so staff can distinguish them from internal notes and system activity. No new public-facing feature is introduced.

## 2. Current State

The application already has:

- active local users mirrored from Keycloak;
- functional roles and persisted `UserRole` assignments;
- role scopes that can restrict domain, office, service, and queue;
- Operational and IT role aliases;
- a ticket-scoped eligible-assignee endpoint;
- assignment mixed into the general work-state mutation;
- optimistic concurrency through `updated_at`;
- audit/outbox recording for ticket mutations;
- workflow transition history; and
- one staff activity timeline containing replies, internal notes, transitions, work-state changes, attachments, and relationships.

The current implementation is insufficient because:

- candidate filtering is primarily domain/group based and does not enforce every persisted scope dimension;
- technical administrators can appear as target assignees without a functional action role;
- the eligible-user endpoint can expose staff choices to callers who cannot assign;
- assignment is mixed with unrelated work-state changes;
- the selector is not searchable and does not identify the matching role-derived team;
- there is no confirmation step or complete server-generated transfer receipt;
- custody is reconstructed from several record types rather than stored as one complete typed chain;
- generic work-state events do not clearly distinguish assignment, transfer, and unassignment; and
- custody records do not currently have create-only enforcement or a per-ticket tamper-evident hash chain.

## 3. Scope

### 3.1 In Scope

- Role-derived team eligibility for current active internal users.
- Primary internal staff designations for the full office staff complement.
- Exact target-user checks for role, domain, office, service, queue, and confidentiality.
- A searchable eligible-user selector showing name and matching role/team labels.
- Confirmation before assignment, self-assignment, transfer/reassignment, or unassignment.
- A dedicated atomic assignment API and service.
- A server-generated success receipt and immediate staff UI updates.
- A durable, typed, chronological custody ledger.
- Custody coverage for creation, assignment, reassignment/transfer, unassignment, queue change, escalation, status change, reopening, and closure.
- Explicit activity categories for requester-visible replies, internal notes, workflow events, and custody events.
- Read-only custody access for authorised ticket viewers and auditors.
- Deterministic backfill of existing authoritative history.
- Automated backend and frontend coverage for all currently supported role families and aliases.

### 3.2 Out of Scope

- New public or anonymous assignment features.
- Requester self-assignment or requester-selected staff.
- A public chain-of-custody view.
- Public ticket tracking or requester accounts.
- A new Team or TeamMembership model.
- A general redesign of ticket routing, catalogue administration, or the public intake flow.
- Adding the planned Accounts domain; this change must remain extensible to it but tests the domains currently implemented in code.

## 4. Design Decisions

1. **Teams and designations are role-derived.** A candidate's matching `Role.name` supplies the staff designation, while its recognised role family supplies the team label presented in the selector and stored in custody snapshots. No separate team-membership source is introduced.
2. **Persisted role assignments are authoritative.** If a user has persisted `UserRole` assignments, only active, unexpired, valid assignments are considered. Keycloak group fallback applies only when the existing authority model would use that fallback.
3. **The free-text `Ticket.team` field is not an authorisation source.** It remains ordinary work-state metadata. It cannot grant eligibility or broaden a role scope.
4. **Assignment becomes a dedicated operation.** New UI code uses an explicit assignment endpoint. Assignment is not submitted with unrelated work-state fields.
5. **Transfer and reassignment share one business meaning.** An owner-to-owner change is stored as `reassigned` and displayed as “Transferred / reassigned.” The application has no separate approval process that would justify two different mutation semantics.
6. **Server values are authoritative.** Candidate results, actor identity, timestamps, previous/new values, capability checks, and success receipts come from the server.
7. **The chain is stored, not heuristically reconstructed.** A dedicated append-only custody record is written in the same transaction as each material change.
8. **One semantic event appears once in activity.** Workflow transitions backed by custody records render as workflow events; ownership, queue, escalation, and creation records render as custody events. The existing transition history remains the workflow engine's durable transition record without creating duplicate visible entries.

## 5. Role-Derived Eligibility

### 5.1 Primary Office Staff Designations

The following designations are primary internal users who may action tickets when their active persisted role scope covers the ticket:

| Staff designation | Canonical role key | Role-derived team |
|---|---|---|
| Master | `master` | Office Leadership |
| Deputy Master | `deputy-master` | Office Leadership |
| Assistant Master | `assistant-master` | Office Leadership |
| Assistant Accountant | `assistant-accountant` | Finance |
| Accountant | `accountant` | Finance |
| Senior Accountant | `senior-accountant` | Finance |
| Principal Accountant | `principal-accountant` | Finance |
| Financial Controller | `financial-controller` | Finance |
| Estate Examiner | `estate-examiner` | Estate Administration |
| Records Clerk | `records-clerk` | Records and Data |
| Data Clerk | `data-clerk` | Records and Data |

These designation roles are action-capable target roles only through an active persisted `UserRole` with a valid business scope. A designation alone never implies global access, assignment authority, Restricted access, or access to every office. The configured role scope remains authoritative for domain, office, service, queue, and confidentiality.

Designation roles do not receive an unscoped Keycloak-group fallback because a job title alone does not identify a safe domain or office. If no active valid persisted assignment covers the ticket, the user is ineligible.

Finance designations are supported as internal staff roles in the current configured domains. This design does not create the planned Accounts domain; when that domain is introduced, the same roles can receive explicit Accounts scopes without changing the assignment contract.

### 5.2 Existing Functional Target Roles

The eligible target must hold an action-capable functional role for the ticket domain. Currently supported aliases are:

| Team | Functional roles/groups |
|---|---|
| Operational | `agent-operational`, `ops-agents`, `supervisor-operational`, `ops-supervisors` |
| IT | `agent-it`, `it-agents`, `lead-it`, `it-leads` |

Security-only, auditor-only, manager-only, and technical-administrator-only identities are not eligible targets. A user holding one of those roles plus a matching functional role may be eligible through the functional role only.

The current actor-authorisation rules are preserved. This design narrows target selection without silently granting a new actor the ability to assign.

The legacy functional aliases remain supported for existing identities and compatibility. New office designation roles and legacy aliases use the same final scope and confidentiality checks.

### 5.3 Exact Scope Coverage

A target role assignment covers a ticket only when:

- its domain equals the ticket domain;
- a scoped office equals the ticket office;
- a scoped service equals the ticket service;
- a scoped queue equals the ticket queue;
- a queue-scoped role is not treated as covering a ticket with no queue;
- it grants the confidentiality access required by the ticket; and
- the assignment is structurally valid and unexpired.

A null role dimension is broad for that dimension. A non-null role dimension must match exactly. Matching one dimension never compensates for a mismatch in another.

Restricted tickets require both a matching functional action role and the applicable Restricted visibility authority. Security-responder authority alone is read-only and cannot make the responder an assignee.

### 5.4 Candidate Presentation

The eligible-assignee response returns each user once with:

- immutable user ID;
- username;
- display name with username fallback;
- sorted matching staff designation labels;
- sorted matching role-derived team labels; and
- no unrelated role or scope details.

The selector searches display name, username, designation, and returned team labels. It never fetches or filters the unscoped user directory in the browser.

The existing assignee may be shown as current ticket context even when a later role change makes that person ineligible. An ineligible current owner is not offered as a new target.

## 6. Assignment API and Transaction

### 6.1 Candidate Endpoint

`GET /api/v1/tickets/{number}/assignees/`

Requirements:

- the ticket must be in the caller's current scope;
- the caller must have assignment authority for that ticket;
- inactive, expired, malformed, unauthorised, and confidentiality-ineligible targets are excluded;
- optional search input is normalised and applied only within the eligible set; and
- direct access by ordinary agents without assignment authority, auditors, or inactive users is denied.

### 6.2 Assignment Endpoint

`POST /api/v1/tickets/{number}/assignment/`

Request:

```json
{
  "assignee_id": "user-uuid-or-null",
  "expected_updated_at": "2026-07-30T10:00:00Z",
  "reason": "Required for transfer or unassignment"
}
```

Rules:

- `assignee_id` is a UUID for assignment/reassignment and `null` for unassignment.
- A reason is required when replacing or clearing an existing owner.
- Initial assignment and staff self-assignment may omit the reason.
- A no-op request returns the unchanged ticket and does not create custody, audit, or outbox records.
- A self-assignment is allowed only when the existing server capability permits it and the actor is an eligible target.
- Assignment to another user and unassignment require the current assignment authority.

The service performs the following inside one database transaction:

1. Resolve one immutable authority snapshot for the actor.
2. Lock the canonical ticket through the actor's scoped queryset.
3. Compare `expected_updated_at` with the locked ticket.
4. Recheck actor authority against the locked ticket.
5. Re-resolve and recheck target eligibility against current identity data.
6. Capture previous owner and matching role/team snapshots.
7. Apply the owner change and any approved first-assignment status change.
8. Write audit and transactional-outbox events.
9. Write required custody event or events.
10. Return the refreshed detail and server-generated receipt.

Any failure rolls back the ticket, transition history, audit, outbox, and custody writes together.

### 6.3 Response

```json
{
  "ticket": {},
  "receipt": {
    "ticket_number": "OP-260730-000001",
    "action": "reassigned",
    "previous_assignee": {
      "display_name": "Previous Agent",
      "designations": ["Estate Examiner"],
      "team_labels": ["Estate Administration"]
    },
    "new_assignee": {
      "display_name": "New Agent",
      "designations": ["Assistant Master"],
      "team_labels": ["Office Leadership"]
    },
    "occurred_at": "2026-07-30T10:05:00Z",
    "performed_by": {
      "display_name": "Assigning Supervisor"
    }
  }
}
```

The receipt contains snapshot display values and may include stable subjects internally, but it does not expose unnecessary identity or scope data.

### 6.4 Compatibility

New frontend code must use the assignment endpoint. During one compatibility period:

- an assignment-only work-state request delegates to the same assignment service; and
- a request mixing assignment with other work-state changes fails with a stable `assignment_must_be_separate` error.

This prevents old API clients from bypassing eligibility while keeping mixed mutations from producing ambiguous custody records.

## 7. Custody Ledger

### 7.1 Model

Add an append-only `TicketCustodyEvent` with:

- UUID primary key;
- ticket reference;
- per-ticket monotonic sequence;
- event type;
- occurred-at timestamp;
- actor kind (`user` or `system`);
- actor subject and display-name snapshot;
- source process identifier;
- previous and new owner snapshots;
- previous and new queue snapshots;
- previous and new status codes and labels;
- previous and new staff-designation snapshots;
- role-derived team-label snapshots;
- reason;
- previous-event hash; and
- event hash.

Owner and queue values are snapshots rather than display joins. Later user, role, or queue renaming cannot rewrite historical presentation.

Each event hash is computed from a canonical serialisation of all immutable event fields plus the previous-event hash. Ticket locking serialises concurrent custody writes and makes the sequence/hash chain deterministic.

### 7.2 Event Types

| Event | Trigger | Activity category |
|---|---|---|
| `created` | Ticket creation, including initial owner/queue/status snapshot | Custody |
| `assigned` | No owner to eligible owner | Custody |
| `reassigned` | Owner to different eligible owner | Custody; label “Transferred / reassigned” |
| `unassigned` | Owner to no owner | Custody |
| `queue_changed` | Queue changes, including system routing | Custody |
| `escalated` | Explicit escalation or first SLA escalation threshold crossing | Custody |
| `status_changed` | Ordinary workflow transition | Workflow |
| `reopened` | Workflow transition to Reopened | Workflow |
| `closed` | Workflow transition to Closed | Workflow |

If one operation changes multiple semantic dimensions, it writes separate consecutive events with one shared timestamp/source. For example, rerouting that changes the queue and clears an owner writes `queue_changed` followed by `unassigned`.

### 7.3 Event Sources

Custody writes are integrated into canonical service boundaries:

- ticket creation service;
- assignment service;
- workflow transition service;
- any existing or future queue/routing service;
- SLA escalation processing; and
- approved automation actions that assign or unassign tickets.

The SLA evaluator records `escalated` once when an open SLA first crosses its configured escalation threshold. The actor is a named system process, not a fabricated human identity. Repeated evaluator runs are idempotent.

Direct ORM mutation remains unsupported application behaviour. Public APIs cannot update custody records.

### 7.4 Immutability

Custody records are protected by:

- a create-only application service;
- model guards against updating or deleting an existing event;
- no mutation serializer or endpoint;
- a read-only admin registration;
- database protection against ordinary `UPDATE` and `DELETE`; and
- the per-ticket hash chain for tamper evidence.

Only an explicitly approved retention/disposal path may remove a ticket and its custody ledger according to platform policy. Ordinary users, administrators, integrations, and auditors cannot edit or selectively delete custody history.

### 7.5 Historical Backfill

The data migration backfills each existing ticket in chronological order from authoritative records:

1. ticket creation audit and initial transition;
2. assignment changes in work-state audits;
3. workflow transition history;
4. queue changes present in audited before/after values; and
5. reopen/closure state from transition history.

Every existing ticket receives a `created` record. Where an older source lacks an actor display name, role/team label, prior value, or reason, the migration stores the available stable subject/value and leaves the missing snapshot null. It never invents a person, queue, or reason.

Backfill ordering uses source timestamp and stable source ID. It is idempotent and can be verified before deployment.

## 8. Staff Activity and Audit Access

The ticket activity API remains one chronological stream ordered by timestamp and stable ID. Every item includes a category:

- `public_reply` for requester-visible messages;
- `internal_note` for staff-only notes;
- `workflow` for status changes, reopening, and closure; and
- `custody` for creation, owner changes, queue changes, and escalation.

Attachments and relationships retain their existing explicit types and neutral activity presentation. They do not masquerade as custody events.

The activity read model uses custody-backed workflow events when available and suppresses the corresponding visible transition-history duplicate. Legacy fallback remains only for unmigrated data during deployment.

Each custody/workflow item displays, where applicable:

- date and time;
- action;
- previous owner or queue;
- new owner or queue;
- previous and new status;
- actor or named system process; and
- reason.

The timeline is available only when the ticket is visible through the caller's current scope. Auditors retain read-only access through their existing scoped authority, including Restricted tickets only where their authority permits it. Relationship identifiers retain their existing counterpart-visibility protection.

## 9. Internal Assignment User Experience

### 9.1 Searchable Selector

The Operations panel separates assignment from general work-state editing. Assignment-capable staff receive a labelled searchable command-style selector that:

- loads only the server-provided eligible set;
- searches by name, username, staff designation, and role/team label;
- shows name as the primary line;
- shows matching staff designation and team/role labels as secondary text;
- shows loading, empty, and failure states; and
- disables submission while candidates are stale or unavailable.

Ordinary staff may retain the existing internal self-assignment action when allowed, but self-assignment also uses the confirmation flow. This is an internal staff function, not requester self-service.

### 9.2 Confirmation

Selecting Assign, Transfer, Self-assign, or Unassign opens a confirmation dialog before the API call. The dialog identifies:

- ticket number and title;
- action;
- current owner;
- proposed owner;
- proposed staff designation;
- proposed role-derived team labels; and
- required reason when transferring/reassigning or unassigning.

Cancel closes the dialog without a request. Confirm is disabled while the request is pending, and duplicate submissions are blocked.

### 9.3 Success and Immediate Update

On success the client:

1. replaces the exact ticket-detail cache with the returned ticket;
2. updates the visible assignee immediately;
3. refreshes the eligible candidate set;
4. refreshes ticket activity;
5. invalidates queue, Kanban, dashboard, and relevant assigned-work queries; and
6. displays an accessible confirmation using the server receipt.

The confirmation identifies the ticket, previous owner, new owner, server timestamp, and performing user. It remains available long enough to read and is announced to assistive technology.

## 10. Error Handling and Concurrency

| Condition | API behaviour | UI behaviour |
|---|---|---|
| Caller cannot assign | `403 ticket_action_forbidden` | Assignment control absent or permission message after authority changed |
| Ticket left caller scope | `404` | Preserve page context and offer safe return/reload |
| Target became ineligible | `400 ineligible_assignee` | Keep selection context, explain that eligibility changed, refresh candidates |
| Stale ticket | `409 stale_ticket` with current timestamp | Keep form values and offer Reload |
| Invalid/missing transfer reason | `400 invalid_assignment` with field error | Focus and announce reason error |
| Candidate lookup unavailable | Stable problem response | Disable assignment only; preserve unrelated operations |
| Duplicate confirmation | First request runs; later client submission blocked or becomes a no-op/stale response | One pending state and one confirmation |
| Custody/audit/outbox write failure | Full transaction rollback | Show failure; visible owner remains unchanged |

The service locks before checking the final version and eligibility. Two concurrent claims cannot both succeed. The winning mutation advances `updated_at`; the loser receives the stable stale-ticket response.

## 11. Automated Testing

Implementation follows test-driven development. Each production behaviour begins with a focused test that fails for the intended missing behaviour.

### 11.1 Eligibility Tests

- Active matching office-designation roles are returned only through exact persisted scopes.
- Every primary staff designation can be selected for a ticket it is explicitly scoped to action.
- Designation-only Keycloak groups without persisted scopes fail closed.
- Active matching Operational and IT legacy agents are returned.
- Supervisors/leads are returned when their functional role covers the ticket.
- Wrong domain, office, service, or queue is excluded.
- Queue-scoped roles do not cover queue-less tickets.
- Inactive users and expired assignments are excluded.
- Malformed persisted scopes fail closed.
- Auditor-only, security-only, manager-only, and technical-admin-only users are excluded.
- A multi-role user is included only through matching functional roles.
- Restricted tickets exclude ordinary agents without Restricted authority.
- Persisted assignments cannot be broadened by Keycloak group fallback.
- Candidate output contains only relevant role/team labels.
- Callers without assignment authority cannot enumerate candidates.

### 11.2 Assignment Service and API Tests

- Initial assignment succeeds atomically.
- Staff self-assignment reuses the same eligibility service.
- Owner-to-owner transfer/reassignment requires a reason.
- Unassignment requires authority and a reason.
- Direct API requests to inactive or unauthorised targets fail with no side effects.
- A target becoming ineligible between candidate lookup and submit is rejected.
- Stale and concurrent requests have one winner.
- Injected custody, audit, or outbox failure rolls back the owner and status.
- Mixed assignment/work-state requests are rejected.
- The response receipt contains exact ticket, previous/new owner, timestamp, and actor snapshots.

### 11.3 Custody Tests

- Creation begins every new chain.
- Assignment, reassignment/transfer, unassignment, queue change, escalation, status change, reopening, and closure each produce the correct event.
- Multi-event operations have deterministic consecutive sequences.
- System events name the system process.
- The timeline is oldest first with stable tie-breaking.
- Hashes validate from the first event through closure.
- Existing events cannot be updated or selectively deleted through model, admin, or API paths.
- Backfill is idempotent and preserves all available historical values.
- Authorised staff and auditors can read; out-of-scope users cannot.
- Transition history and custody do not render duplicate workflow entries.

### 11.4 Frontend Tests

- Search matches name, username, and role/team label.
- Each candidate displays the returned office staff designation.
- Only server-returned candidates are displayed.
- Assignment, transfer, self-assignment, and unassignment require confirmation.
- Cancel sends no request.
- Confirm sends exactly one request.
- Success immediately changes the visible assignee without a page refresh.
- The success confirmation renders all receipt fields.
- Candidate, activity, and queue-related caches refresh after success.
- Stale, ineligible-target, candidate-load, and permission errors remain distinct and accessible.
- Public reply, internal note, workflow, and custody activity items have explicit text labels, not colour-only distinctions.

### 11.5 Supported Role Matrix

The tests cover every primary office staff designation:

- Master;
- Deputy Master;
- Assistant Master;
- Assistant Accountant;
- Accountant;
- Senior Accountant;
- Principal Accountant;
- Financial Controller;
- Estate Examiner;
- Records Clerk; and
- Data Clerk.

They also cover both canonical and legacy aliases for:

- Operational agent;
- Operational supervisor;
- IT agent;
- IT lead;
- system administrator;
- security responder;
- auditor; and
- inactive identities.

Actor permissions and target eligibility are asserted separately. A role may be allowed to perform an assignment while still being an invalid target without a functional action role.

## 12. Acceptance Traceability

| Requirement | Design coverage |
|---|---|
| Searchable eligible team-member dropdown | Sections 5.4 and 9.1 |
| Exclude inactive/unauthorised users | Sections 5 and 11.1 |
| Confirmation before mutation | Section 9.2 |
| Complete success confirmation | Sections 6.3 and 9.3 |
| Immediate visible update | Section 9.3 |
| Direct API enforcement | Sections 5 and 6 |
| Complete creation-to-closure custody | Section 7 |
| Required event details | Sections 7.1 and 8 |
| Immutable auditor-accessible records | Sections 7.4 and 8 |
| Activity-type distinction | Section 8 |
| Automated role and behaviour coverage | Section 11 |

## 13. Delivery Boundary

Implementation should touch only the internal ticket, identity-scope, SLA escalation, audit presentation, and staff ticket UI paths needed by this design. Existing public intake and requester-facing code must not be expanded or redesigned as part of this work.
