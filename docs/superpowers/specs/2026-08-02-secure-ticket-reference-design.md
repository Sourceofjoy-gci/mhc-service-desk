# Secure Ticket Reference and Staff Tracking Design

Date: 2026-08-02
Status: Approved for implementation

## 1. Goal

Every successfully created ticket receives one unique, human-readable reference in the same database transaction as the rest of the ticket aggregate. The reference cannot later be changed and is shown immediately after staff-assisted intake. Authenticated helpdesk staff can use the reference to find a ticket within their authorised scope and present a concise progress view to the requester they are assisting.

This design also makes the required lifecycle states visible through a stable tracking vocabulary and retains a complete internal audit trail for creation, assignment, updates, escalation, resolution, reopening, and closure.

## 2. Existing System Context

The `Ticket.number` field is already unique and indexed, ticket reads are scope-filtered, staff queue search includes the ticket number, and intake confirmation screens already render the returned number. Ticket lifecycle actions also create transition history, immutable custody events, and audit events.

The gaps are:

- `next_ticket_number()` uses `count() + 1`, which can allocate the same number to concurrent transactions.
- prefixes are represented in application settings but are not loaded as deploy-time environment configuration by the allocator.
- ordinary model and queryset writes can change an existing ticket number.
- there is no focused staff tracking page or tracking response contract.
- the detailed internal workflows do not expose one stable set of the nine requested tracking statuses, and there is no first-class Escalated state.
- reference allocation, staff lookup, tracking status mapping, and the tracking UI lack dedicated tests.

The existing unauthenticated intake form remains unavailable. This feature does not create a public ticket lookup surface.

## 3. Chosen Approach

Use a database-backed, row-locked global counter for each domain and configured prefix. Every new reference has exactly six characters:

```text
<LETTER><FIVE-DIGIT-SEQUENCE>
O00123
```

The allocator and ticket insert run in one outer transaction. A unique counter key and row lock serialize concurrent allocations. The existing unique constraint on `Ticket.number` remains the final integrity boundary.

This is preferred to:

- one shared database sequence across both domains, which would prevent independent configured prefixes;
- a random Base32 reference, which is harder to enumerate but less convenient to communicate and unnecessary because lookup is authenticated and scope-restricted.

## 4. Reference Data Model and Allocation

Add a `TicketReferenceCounter` model with:

- `domain`: operational or IT;
- `prefix`: the validated prefix used in the rendered reference;
- `period`: retained as an internal compatibility field and set to the sentinel `GLOBAL` for new counters;
- `last_value`: the last committed positive sequence value;
- a unique constraint across `(domain, prefix, period)`.

Allocation performs these operations inside `transaction.atomic()`:

1. Read the configured prefix for the ticket domain.
2. Validate and normalise it to uppercase. A prefix must be exactly one ASCII letter matching `[A-Z]`.
3. Obtain or create the `GLOBAL` counter row for `(domain, prefix)`. A newly created row starts at the greatest five-digit sequence already present among matching six-character references, or zero when none exist.
4. Lock that row with `select_for_update()`.
5. Increment and persist `last_value`.
6. Format the reference using the letter and a zero-padded five-digit sequence. Allocation fails after `99999` rather than wrapping or reusing a reference.
7. Insert the ticket using that reference before the outer transaction commits.

The counter update rolls back if ticket creation or its required history/audit writes fail. Concurrent first use of a new prefix is resolved by the counter's unique constraint and a retry of the locked fetch inside a savepoint.

Prefix configuration is loaded from environment-backed Django settings:

- `TICKET_REFERENCE_PREFIX_OPERATIONAL`, default `O`;
- `TICKET_REFERENCE_PREFIX_IT`, default `I`.

Changing a prefix affects only newly created tickets. Existing references and their counters remain valid and searchable. Legacy references keep their current values and require no data rewrite.

## 5. Reference Immutability

`Ticket.number` is write-once:

- creation services supply it exactly once;
- `Ticket.save()` rejects a changed number on an existing row;
- `ProtectedTicketQuerySet.update()` rejects updates containing `number`;
- the database migration adds a PostgreSQL update trigger that rejects changes to `ticket.number`, covering raw SQL and code paths that bypass Django;
- the existing unique index remains in place.

No API serializer accepts the reference as writable input. Retention may delete an approved ticket aggregate but cannot detach, reuse, or reassign its reference.

## 6. Tracking Status Vocabulary

Keep the richer internal operational and IT workflows. Add a small domain service that maps internal status codes to the exact staff tracking vocabulary:

| Tracking status | Internal status codes |
| --- | --- |
| Submitted | `new` |
| Acknowledged | `triage` |
| Assigned | `assigned` |
| In Progress | `in_progress`, `diagnosing`, `quality_review`, `validation` |
| Awaiting Information | all `waiting_*` states |
| Escalated | `escalated` |
| Resolved | `resolved` |
| Closed | `closed`, `cancelled`, `rejected`, `duplicate`, `spam` |
| Reopened | `reopened` |

Add `escalated` to the operational and IT workflow seeds. Active work states may transition to Escalated with a required reason. Escalated tickets may return to In Progress or proceed through the domain's normal resolution path. Existing special outcomes such as Cancelled, Rejected, Duplicate, and Spam remain distinct internally but map to Closed in the tracking vocabulary.

The mapping is centralised and reused by the API and UI contract tests. It does not rewrite historical status rows.

## 7. Authenticated Tracking API

Add a collection action under the existing ticket viewset:

```http
GET /api/v1/tickets/tracking/?reference=O00123
```

The endpoint requires the existing Keycloak authentication and ticket scope permission. It normalises surrounding whitespace and letter case, validates the reference length/shape, and performs an exact lookup against `scope_ticket_queryset()`. An out-of-scope and nonexistent reference return the same `404` response so the endpoint does not disclose ticket existence.

The response is deliberately smaller than `TicketDetailSerializer`:

```json
{
  "reference": "O00123",
  "title": "Estate status enquiry",
  "tracking_status": "In Progress",
  "status_updated_at": "2026-08-02T10:15:00Z",
  "created_at": "2026-08-02T09:00:00Z",
  "updated_at": "2026-08-02T10:15:00Z",
  "office": "Mbabane (Main)",
  "service": "Estate registration or reference",
  "progress": [
    {
      "status": "Submitted",
      "occurred_at": "2026-08-02T09:00:00Z"
    }
  ]
}
```

The progress list is derived from canonical transition/custody history, ordered oldest first, collapsed only when adjacent internal states map to the same tracking status, and contains no internal notes, reasons, actor identifiers, requester contact details, or attachment metadata. Authorised staff can open the full ticket detail page for the internal audit view.

Malformed input returns `400`; missing or inaccessible references return `404`; unauthenticated requests follow the existing authentication response. The endpoint is read-only and does not alter the ticket.

## 8. Staff Tracking Page

Add `/ticket-tracking` inside `ProtectedRoute` and `AppShell`. The page contains:

- one labelled reference input;
- a Track ticket button with a pending state and duplicate-submission guard;
- clear invalid, inaccessible/not-found, and unexpected-error states;
- a result summary showing reference, title, current tracking status, last update time, office, and service;
- an oldest-to-newest progress timeline;
- an Open full ticket action for authorised staff.

The page accepts an optional `reference` query parameter so a confirmation screen can link directly to a populated tracking result. It does not load until the user submits or arrives with a valid reference parameter. The public shell does not link to or render this page.

Add a Track ticket item to authenticated staff navigation where the current staff workspace navigation is available.

## 9. Intake Confirmation

Keep ticket creation responses backward compatible. Both staff-assisted intake confirmations continue receiving `ticket_number`, but the UI labels it **Reference number**, displays it prominently with tabular characters, and provides:

- Copy reference;
- Track this ticket, linking to `/ticket-tracking?reference=<encoded reference>`;
- Submit another request.

The confirmation is rendered only after a successful `201 Created` response. Failed or rolled-back creation never displays a reference.

The dormant public intake component may share the clearer label when touched by shared tests, but this work does not add it to the public routes.

## 10. Authorised Staff Search

The existing queue search already filters its scope-aware queryset by ticket number. Preserve that behaviour and add regression coverage showing:

- an authorised helpdesk user can find an in-scope exact reference;
- the same search cannot return an out-of-scope ticket;
- a reference search remains indexed through the existing unique index for exact tracking lookup.

The tracking endpoint is the fastest path when staff already have the reference. Queue search remains useful when they also need surrounding queue context.

## 11. Audit Trail

Continue treating `TicketCustodyEvent`, `TransitionHistory`, and `AuditEvent` as the canonical internal record:

| Required event | Canonical record |
| --- | --- |
| Created | custody Created event plus `ticket.created` audit event |
| Assigned or reassigned | immutable custody event and assignment audit event |
| Updated | work-state or other domain audit event |
| Escalated | Escalated custody event and transition audit event |
| Resolved | status custody event, transition history, and transition audit event |
| Reopened | Reopened custody event, transition history, and transition audit event |
| Closed | Closed custody event, transition history, and transition audit event |

Every record includes an actor snapshot or actor subject and an occurrence timestamp. The existing custody hash chain preserves tamper evidence for custody and lifecycle events. Ticket creation audit payloads will include the allocated reference so allocation is visible in the audit record. The full ticket Activity view remains restricted to authorised staff and presents responsible actor and timestamp.

## 12. Error Handling and Operational Behaviour

- Invalid prefix configuration fails ticket creation loudly before allocation; startup/system checks report the configuration error.
- Counter or ticket insert failures roll back the entire creation transaction.
- Unexpected uniqueness conflicts are retried a small, bounded number of times and then surface as an operational error rather than returning a possibly incorrect reference.
- Tracking errors use the application's structured problem response and correlation identifier conventions.
- Logs use the ticket reference as a correlation value only after creation succeeds.
- Prefix changes require no maintenance job, but each prefix has a finite range of 99,999 references and must never be reused for a reset sequence.

## 13. Testing Strategy

Backend tests cover:

- global sequential allocation per domain and prefix;
- configured prefixes and invalid prefix rejection;
- concurrent transactions allocating distinct references on PostgreSQL;
- allocation rollback when ticket creation fails;
- legacy references remaining readable;
- model, queryset, and database rejection of reference mutation;
- exact authenticated tracking lookup;
- scope concealment and unauthenticated denial;
- the nine tracking mappings and progress collapse rules;
- Escalated workflow transitions and required reason;
- creation, assignment, update, escalation, resolution, reopening, and closure audit actor/timestamp coverage;
- staff queue search by reference.

Frontend tests cover:

- the protected tracking route and staff navigation;
- reference validation, loading, success, empty, 404, and unexpected-error states;
- progress timeline rendering;
- the full-ticket link;
- confirmation reference label, copy action, and prefilled tracking link;
- prevention of duplicate tracking and intake submissions.

Verification runs focused backend and frontend tests first, then the complete backend suite, frontend test suite, lint/type checks, production frontend build, and migration checks.

## 14. Rollout and Compatibility

The schema migration creates the counter table and immutability trigger without rewriting ticket numbers. Deployment may occur with existing tickets present. The first global allocation for each active one-letter prefix starts from the maximum matching six-character reference, preventing collisions when references in the new format already exist. Older long-form references remain unchanged and their monthly counter rows are not reused.

Existing ticket detail routes and immutable legacy references keep working. The hard-coded detail-route regex accepts both six-character references and the prior long form without turning the route into an unconstrained catch-all. The focused tracking input accepts only the current six-character format.

## 15. Out of Scope

- unauthenticated requester tracking;
- reference-plus-contact verification or one-time tracking tokens;
- QR codes and printable acknowledgements;
- requester notifications;
- changing retention policy;
- replacing the detailed internal workflow with the tracking vocabulary;
- unrelated ticket queue or detail redesign.

## 16. Acceptance Criteria

The work is complete when:

1. concurrent successful ticket creation cannot produce duplicate references;
2. each committed ticket has one configured, human-readable reference that cannot be changed;
3. staff-assisted confirmation displays the reference immediately;
4. authorised helpdesk staff can find an in-scope ticket by its reference and cannot discover out-of-scope tickets;
5. the tracking page presents all nine required statuses through the stable mapping;
6. escalation is a supported audited workflow state;
7. the full internal activity trail identifies the responsible actor and timestamp for every required lifecycle event;
8. focused and full verification checks pass.
