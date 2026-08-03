# Escalation Supervisor Assignment Design

## Goal

When an authorised staff member escalates an operational ticket, they must select a
specific active supervisor. The selected supervisor must hold a scoped Assistant
Master, Deputy Master, or Master assignment that covers the ticket. The escalation
and ownership change must commit atomically so an escalated ticket is never left
without a responsible supervisor.

## Scope

This change covers escalation from the ticket detail transition dialog and the
authenticated ticket API. It applies to transitions whose destination status is
`escalated`.

The following are outside this change:

- general assignment and routing behaviour;
- automatic selection of a supervisor;
- role-only assignment without a named user;
- legacy operational-supervisor roles as escalation targets;
- public ticket tracking; and
- Kanban escalation, because the current Kanban has no Escalated destination
  column.

## Approaches Considered

### Extend the transition API

Add a supervisor identifier to the existing transition request and expose a
dedicated escalation-supervisor candidate endpoint. This keeps workflow
authorisation in one place and permits one atomic database transaction.

This is the selected approach.

### Add a separate escalation endpoint

A dedicated endpoint would make escalation explicit, but it would duplicate
transition validation, optimistic concurrency, SLA handling, response shaping,
and error handling.

### Chain assignment and transition requests

Calling assignment and then transition would reuse existing endpoints but would
not be atomic. A failure after assignment could leave a ticket transferred without
being escalated, while a failure after escalation could leave it with an ordinary
worker. This approach is rejected.

## Supervisor Eligibility

An escalation supervisor is a named active user with an active persisted
`UserRole` whose role key is one of:

- `assistant-master`;
- `deputy-master`; or
- `master`.

The role and assignment office/scope must cover the exact ticket domain, office,
service, queue, and confidentiality boundary. Expired roles, inactive users,
Keycloak realm-role claims without a persisted scoped assignment, auditors, legacy
`ops-supervisors`, and cross-scope staff are excluded.

Higher roles do not replace the selected identity: the escalating staff member
selects a specific person, and the ticket's `assignee` points to that user. A currently
assigned eligible supervisor may be selected; in that case ownership is unchanged
but the supervisor selection is still validated and recorded with the escalation.

## API Design

### Candidate endpoint

Add an authenticated endpoint:

```text
GET /api/v1/tickets/{number}/escalation-supervisors/?search={query}
```

The caller must be able to see the ticket and must currently have the transition to
`escalated` available. The endpoint returns the same safe staff fields used by the
existing assignee selector:

```json
{
  "results": [
    {
      "id": "user-uuid",
      "username": "supervisor.username",
      "display_name": "Supervisor Name",
      "designations": ["Assistant Master"],
      "team_labels": ["Office Leadership"],
      "role_summaries": ["Approve within delegated authority."]
    }
  ]
}
```

Search is server-side, bounded to the existing maximum query length, and matches
display name, username, designation, team, and role summary. Results remain sorted
deterministically.

### Transition request

Extend the existing transition request with `supervisor_id`:

```json
{
  "to_status": "escalated",
  "updated_at": "2026-08-03T12:00:00Z",
  "reason": "Requires exception decision",
  "supervisor_id": "user-uuid"
}
```

For an escalation transition:

- `reason` is required;
- `supervisor_id` is required; and
- the supervisor must remain eligible when the transaction executes.

For every other transition, `supervisor_id` is rejected as an invalid field for
that action. Existing non-escalation requests and responses remain unchanged.

Validation failures use the existing problem response with field errors under
`reason` or `supervisor_id`. Stale timestamps remain HTTP 409. Missing scope or
transition authority remains HTTP 403. A supervisor who is missing, inactive, or
ineligible returns HTTP 400 without revealing inaccessible user details.

## Transaction and Authorisation Flow

The transition service remains the authority boundary. In one database
transaction it will:

1. lock the ticket and compare `updated_at`;
2. lock and revalidate the acting user's authority;
3. confirm the requested transition is currently available;
4. require the reason and supervisor for an escalation;
5. lock the selected user's authority records;
6. revalidate the selected user's canonical designation and ticket scope;
7. update the ticket owner and status;
8. synchronise SLA state;
9. write transition history, assignment evidence when ownership changed, and
   escalation evidence; and
10. commit all changes together.

An ordinary scoped staff member may make this narrow upward handoff when they can
perform the escalation transition. This does not grant general assignment or
reassignment authority. The target restriction to the three canonical supervisory
roles is enforced on the server and cannot be bypassed by posting another user ID.

Any exception rolls back the status, assignee, SLA changes, transition history,
audit events, custody events, and outbox events.

## Audit and Custody Evidence

When ownership changes, the system records the existing assignment or reassignment
audit and custody evidence with the previous and new supervisor snapshots. It also
records the normal `ticket.transitioned` audit, transition history, and Escalated
custody event. Both records use the acting staff member, escalation reason, and the
same transaction.

The escalation audit metadata identifies the selected supervisor even when that
person was already the current assignee. This preserves evidence that the
supervisor was deliberately selected for the escalation.

## Frontend Design

Selecting **Escalate** opens the existing transition confirmation dialog with:

- a required **Reason** field;
- a required searchable **Escalate to supervisor** staff selector; and
- the existing Cancel and Confirm Escalate actions.

The selector loads only the dedicated supervisor candidates when the escalation
dialog opens. It shows each candidate's name, designation, team, and role summary.
There is no Unassigned option. Client-side validation prevents submission until a
reason and supervisor are selected, while the server remains authoritative.

During submission every transition action and dialog control remains disabled.
On success, the refreshed ticket immediately shows Escalated status and the selected
owner, and the activity timeline is refreshed. On stale-ticket errors the current
reload flow remains available. Server `supervisor_id` errors remain visible without
discarding the typed reason or selected supervisor.

## Testing

Backend tests will prove:

- only active scoped Assistant Masters, Deputy Masters, and Masters are returned;
- ordinary workers, legacy supervisors, auditors, expired roles, and cross-scope
  users are excluded;
- escalation requires `supervisor_id` and reason;
- non-escalation transitions reject `supervisor_id`;
- an eligible supervisor is assigned and the ticket is escalated atomically;
- stale tickets and supervisors who become ineligible have no side effects;
- ordinary staff can perform only the constrained upward handoff;
- assignment, transition, custody, audit, SLA, and outbox evidence is complete; and
- selecting the already assigned eligible supervisor records the escalation without
  a false reassignment event.

Frontend tests will prove:

- the supervisor selector appears only for Escalate;
- candidates load from the dedicated endpoint;
- reason and supervisor are required;
- the selected supervisor ID is sent with the observed timestamp;
- pending, stale, and field-error states preserve the existing interaction rules;
  and
- success refreshes ticket ownership, status, and activity.

Relevant backend permission, transition, assignment, audit, and workflow suites will
run after the focused tests. Relevant frontend transition tests, lint, type checking,
and a production build will complete verification. Browser verification will cover
the escalation dialog at desktop and mobile widths.

## Deployment

No database schema migration is required. The API and frontend must deploy together
because escalation requests without `supervisor_id` will become invalid. Existing
non-escalation clients remain compatible.
