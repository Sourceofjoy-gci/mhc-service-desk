# Pilot Foundation Design

## Objective

Turn the current polished but partial ticketing application into a production-safe pilot foundation. This slice establishes trustworthy authentication, domain permissions, stable collection contracts, and an operable ticket lifecycle before broader requester, intake, notification, knowledge, automation, and administration work begins.

The implementation must preserve existing public intake and staff workflows while replacing development-only assumptions with explicit, testable behavior.

## Scope

This slice includes:

- Keycloak session and access-token wiring for frontend API requests.
- Protected staff routes and a separate public application shell.
- Explicit domain authorization for Operational and IT reporting.
- Stable cursor pagination for collection endpoints and compatible frontend consumers.
- A complete staff ticket workspace for assignment, routing, work state, valid transitions, resolution, reopening, SLA context, attachments, and activity.
- Audit and outbox records for material ticket changes.
- Backend, frontend, and Docker smoke-test coverage for the pilot path.
- Documentation corrections where current readiness claims exceed implemented behavior.

This slice does not include:

- A new requester portal or redesign of public intake.
- Assisted call-centre and walk-in intake expansion.
- Notification delivery channels or templates beyond producing durable outbox events.
- Knowledge management, automation-rule authoring, or administration consoles.
- Replacement of the existing visual design system.

## Guiding Decisions

1. Implement a vertical pilot slice across backend and frontend instead of treating either tier as complete in isolation.
2. Keep the transition service as the only authority for status changes.
3. Add fields and endpoints without removing existing ticket response fields during the rollout.
4. Make authorization explicit at each domain-sensitive endpoint; never infer access merely from authentication.
5. Keep development authentication available only in a development build and a backend debug environment.
6. Use non-optimistic lifecycle mutations: the UI shows progress and renders server-confirmed state only after a successful response.

## Application Structure and Authentication

### Route groups

Routes are split into two layouts:

- **Public routes:** login, public intake, requester-token views that already exist, and health pages. These routes must not render staff navigation or imply a signed-in staff identity.
- **Staff routes:** home, queues, Kanban, dashboard, ticket detail, and staff intake routes. These routes require an authenticated Keycloak session, except when the explicit development bypass is enabled in a development build.

An authentication provider owns Keycloak initialization, session state, token refresh, login, logout, and the intended return path. Staff routes wait for initialization before deciding whether to render, redirect, or show an authentication failure. This avoids both protected-content flashes and redirect loops.

### API client behavior

The frontend API client obtains the current access token from the authentication provider for every protected request. It does not embed a production token or depend on a module-level development token.

On `401 Unauthorized`, the client attempts one token refresh and retries the request once. If refresh or the retry fails, it starts login while preserving the current route as the return path. It must not retry indefinitely. A `403 Forbidden` response renders a dedicated permission state and does not trigger login.

The existing development bypass remains available only when both conditions are true:

- the frontend is running in Vite development mode with the explicit development-auth flag enabled; and
- the backend is running with debug authentication enabled.

Production builds cannot activate the bypass through runtime input alone.

## Authorization Model

Existing scope semantics remain authoritative:

- `ops-agents` and `ops-supervisors` receive Operational scope.
- `it-agents` and `it-leads` receive IT scope.
- `security-responders` receive their explicitly restricted cross-domain access.
- `system-admins` receive global administrative scope.
- `auditors` receive read-only access to both domains.

This implementation must bring code and `docs/permission-matrix.md` into agreement, including security-responder handling and consistent group names.

### Reporting

Every reporting endpoint declares a required domain or derives permitted domains from the caller's scopes before reading data:

- Operational dashboard requests require Operational or administrative/auditor read access.
- IT dashboard requests require IT or administrative/auditor read access.
- Cross-domain flow and export requests include only records inside the caller's permitted domains.

Authentication without a matching domain scope is insufficient. Cross-domain access attempts return `403` without revealing record counts or other domain data.

### Ticket changes

- Agents may self-assign an unassigned in-scope ticket and update its ordinary work-state fields.
- Agents may not assign or reassign a ticket to another user.
- `ops-supervisors`, `it-leads`, and `system-admins` may assign or reassign in-scope tickets to another eligible user and change confidentiality.
- Auditors remain read-only.
- All operations remain constrained by ticket domain, restricted-ticket visibility, and applicable service or queue scopes.

Assignment targets must be active and eligible for the ticket domain. Invalid or unauthorized targets return a field-level validation error without changing the ticket.

## Collection and Error Contracts

### Pagination

Cursor-paginated endpoints use the stable envelope:

```json
{
  "next": "opaque cursor URL or null",
  "previous": "opaque cursor URL or null",
  "results": []
}
```

Each paginated view declares an ordering field that exists on its model and has a deterministic tie-breaker. Ticket queues use a stable recent-first ordering. Cursor values remain opaque to the frontend.

During rollout, frontend collection adapters accept both the legacy array response and the pagination envelope. New backend tests treat the envelope as canonical. Compatibility code can be removed after all supported environments expose the canonical response.

Queue filters, search, selected domain, and cursor state are encoded in the URL so the view can be shared, refreshed, and restored. Changing a filter clears the current cursor.

### Error shape

New or updated pilot endpoints return a consistent error body:

```json
{
  "code": "stable_machine_code",
  "detail": "Human-readable summary",
  "fields": {
    "field_name": ["Field-specific message"]
  },
  "correlation_id": "request correlation identifier"
}
```

`fields` may be empty when an error is not tied to form input. The frontend keeps user-entered values, places field errors next to their controls, and displays the correlation ID in unexpected-error states.

## Ticket Data and API Contract

### Data model

The existing assignee, team, confidentiality, waiting reason, blocked reason, resolution, timestamp, message, note, relationship, and workflow data remains in place.

Two nullable work-planning fields are added to the ticket model:

- `next_action`: short text describing the next concrete step.
- `next_action_at`: date and time when that step is due or expected.

The migration is additive and nullable so it is safe for existing rows and supports rolling deployment. No existing ticket status is rewritten by the migration.

### Ticket detail response

The ticket detail response retains existing fields and adds normalized data needed by the workspace:

- `assignee_detail` with stable identifier and display name while retaining the legacy `assignee` value.
- team, waiting reason, blocked reason, next action, and next-action time.
- confidentiality, domain, and ticket relationships.
- `available_transitions`, each with target status, label, whether a resolution is required, and any reason requirement.
- first-response and resolution SLA clocks with state, due time, and remaining or overdue duration.
- transition-history and attachment metadata required for initial rendering.
- the current `updated_at` value used for concurrency control.

The server derives available transitions and SLA state from workflow and SLA services. The frontend does not reproduce those rules.

### Work-state update

`PATCH /api/v1/tickets/{number}/work-state/` updates only permitted operational fields:

- assignee
- team
- waiting reason
- blocked reason
- next action
- next-action time
- confidentiality when the caller has the elevated role

The request includes the last observed `updated_at`. If the ticket changed after that value, the server returns `409 Conflict` and the current timestamp without applying a partial update. The UI explains that another user updated the ticket and offers a reload action. It does not silently overwrite either operator's work.

The operation validates role, scope, target eligibility, and state-dependent requirements atomically. A successful response returns the refreshed ticket detail.

### Status transitions

`POST /api/v1/tickets/{number}/transition/` remains the only endpoint that changes ticket status. The UI renders only the server-provided available transitions.

Transition dialogs request only fields required by the selected transition. Resolution is mandatory when the workflow rule requires it. Reopen behavior is represented by an ordinary allowed transition. Reopening sets `reopened_at`, clears the ticket's active `resolution_code`, `resolution_summary`, and `resolved_at` fields, and preserves the prior resolution in audit and activity records so the historical resolution remains visible.

Transitions use the same `updated_at` concurrency precondition and `409` handling as work-state updates. A successful transition returns refreshed ticket detail.

### Activity

`GET /api/v1/tickets/{number}/activity/` returns a typed, chronological timeline assembled from durable records. Supported event types include:

- requester and agent messages
- internal notes
- status transitions and resolution
- assignment, team, work-state, and confidentiality changes
- attachments and scan-state changes
- ticket relationships

Each item includes a stable identifier, event type, timestamp, actor display data when available, visibility, and event-specific payload. Internal notes and restricted metadata are never exposed through public requester endpoints.

### Attachments

`GET /api/v1/tickets/{number}/attachments/` lists attachment metadata visible to the caller. The existing multipart `POST` behavior is retained and normalized to the common error contract. Metadata includes file name, size, media type, uploader, upload time, scan state, and download availability. Files are not presented as downloadable until the scan policy permits access.

### SLA representation

Ticket detail exposes separate first-response and resolution clocks. Each clock has a semantic state such as `not_started`, `running`, `paused`, `met`, or `breached`, plus applicable due and duration values. Backend services remain authoritative for pause conditions and targets. The frontend displays the state and timing without recalculating business deadlines.

## Audit and Outbox Guarantees

Every material ticket mutation creates audit and outbox records in the same database transaction as the ticket change. Material mutations include assignment, reassignment, team change, waiting or blocked reason, next action, confidentiality, transition, resolution, reopen, note, message, attachment creation, and relationship changes.

Audit records capture actor, action, ticket, timestamp, and structured before/after values with sensitive content minimized. Outbox records describe the domain event needed by later notification and integration work. Retried requests must not produce duplicate side effects when an idempotency key or existing integration identifier is available.

If audit or outbox persistence fails, the ticket mutation rolls back. This slice guarantees event production, not external notification delivery.

## Frontend Experience

### Staff shell

The shell shows the real authenticated user's display name and appropriate navigation. Public routes use a smaller public shell without staff navigation, development identity text, or inaccessible destinations. A development-auth badge may appear only when the explicit development bypass is active.

### Queue

The queue reads and writes filters through URL parameters, renders paginated results, and offers previous/next controls only when corresponding cursors exist. Loading, empty, permission, and error states remain visually distinct. Returning from ticket detail restores the prior queue context.

### Ticket workspace

The ticket detail page is organized around the operator's next decision:

- A prominent action bar contains only valid status transitions.
- The main column shows the unified activity timeline and message/note controls.
- An operations panel shows assignee, team, waiting/blocked reasons, next action, SLA clocks, confidentiality, relationships, and attachments.
- Elevated controls appear only when the caller has the corresponding server-confirmed capability.

Lifecycle submissions are non-optimistic. Controls become pending while a request is active, duplicate submissions are prevented, and refreshed server state replaces local form state after success. Server validation remains authoritative even when the UI hides unavailable controls.

## Testing Strategy

Implementation follows test-driven development: each behavior begins with a focused failing test, followed by the smallest implementation that makes it pass and then refactoring with the suite green.

### Backend tests

Automated tests cover at least:

- unauthenticated and authenticated access to every staff route's underlying API.
- development bypass disabled outside debug mode.
- Operational users denied IT reports and IT users denied Operational reports.
- administrator and auditor read behavior, with auditors unable to mutate.
- security-responder scope and restricted-ticket behavior.
- deterministic cursor pagination without missing or duplicated records at page boundaries.
- self-assignment, privileged reassignment, ineligible targets, and confidentiality rules.
- stale work-state and transition requests returning `409` without partial changes.
- valid/invalid transitions, required resolution, resolve, and reopen behavior.
- activity ordering and visibility.
- SLA state and due-value serialization.
- attachment visibility and scan-state metadata.
- audit and outbox atomicity for every material mutation.
- the common error format and correlation ID.

### Frontend tests

Automated component and integration tests cover at least:

- protected versus public route rendering.
- authentication initialization and preservation of the return path.
- one refresh-and-retry on `401`, no retry loop, and distinct `403` handling.
- public shell isolation and real staff identity display.
- legacy-array and canonical-envelope collection parsing during rollout.
- URL-synchronized queue filters and cursor clearing.
- available-transition rendering and conditional resolution fields.
- non-optimistic work-state updates, validation errors, and `409` reload behavior.
- loading, empty, permission, and unexpected-error states.

### End-to-end smoke path

The Docker development stack must support a repeatable smoke path for one Operational identity and one IT identity:

1. Authenticate or use the explicit development identity in a development environment.
2. Open an in-scope queue and ticket.
3. Assign the ticket as permitted.
4. Add a note or reply.
5. Set a next action.
6. Move through a valid transition and resolve with required information.
7. Confirm the activity timeline and SLA display update.
8. Confirm each identity is denied the other domain's report.

## Rollout and Compatibility

1. Add nullable database fields and backend serializers without removing legacy fields.
2. Add corrected pagination, authorization, activity, work-state, and attachment contracts with backend tests.
3. Wire the frontend authentication provider and route groups.
4. Update collection adapters and the ticket workspace while retaining temporary array-response compatibility.
5. Run the full backend and frontend verification suite and the Docker smoke path.
6. Correct pilot-readiness, roadmap, traceability, and permission documentation to reflect verified behavior only.
7. Remove temporary response compatibility only in a later, separately verified change.

The implementation must not stage, rewrite, or discard unrelated pre-existing working-tree changes. Commits should be scoped to coherent pilot-foundation tasks.

## Verification

Before calling the slice complete, run fresh commands for:

- backend formatting or lint checks configured by the repository.
- the focused backend tests added for this slice and the complete backend suite.
- frontend lint, TypeScript checking, focused tests, and the complete frontend test suite.
- a production frontend build.
- migration consistency checks.
- the permission audit script.
- the Docker Operational/IT smoke path.

Browser verification must cover desktop and mobile layouts for login, a public route, queue, ticket workspace, and both domain dashboards, including loading, populated, empty, `403`, validation, and conflict states where practical.

## Acceptance Criteria

The pilot foundation is complete when all of the following are true:

- A production frontend session sends refreshed Keycloak access tokens to protected APIs and cannot activate development authentication.
- Unauthenticated users cannot render staff routes, while public routes never render staff navigation.
- Domain report access is enforced and tested for Operational, IT, administrator, auditor, and security-responder identities.
- Canonical collection endpoints paginate deterministically and frontend consumers navigate the envelope correctly.
- An authorized operator can assign, route, plan, transition, resolve, reopen, and review a ticket without using an admin console or direct API client.
- Unauthorized assignment, confidentiality, domain, and transition operations are rejected server-side.
- Concurrent edits cannot silently overwrite newer ticket state.
- Ticket activity, attachment metadata, and both SLA clocks are visible and derived from authoritative backend data.
- Every material ticket mutation is represented in audit and outbox records atomically.
- The documented verification commands pass from a fresh run, and readiness documentation states only what those checks prove.
