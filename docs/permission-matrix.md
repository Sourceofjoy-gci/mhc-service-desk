# Permission matrix - current implementation

This matrix describes the authorization that is implemented now. It is not a
go-live approval. Route metadata can be regenerated with
`docker compose exec backend python scripts/permission_audit.py`; the dated
result is in
[`verification/pilot-foundation-2026-07-27.md`](verification/pilot-foundation-2026-07-27.md).

The audit reports declared authentication and permission classes. A row that
the audit labels `ACCESS=any auth` is not proof of domain authority:
`ScopePermission` with no `required_scope` only requires authentication (and
blocks auditor writes). Ticket and reporting views must also apply a scoped
queryset or an explicit domain check.

## Authority model

| Identity or group | Effective ticket authority |
|---|---|
| `ops-agents` | Non-restricted Operational tickets |
| `ops-supervisors` | Operational tickets, including restricted tickets |
| `it-agents` | Non-restricted IT tickets |
| `it-leads` | IT tickets, including restricted tickets |
| `security-responders` | Restricted tickets in both domains; no ordinary-domain rows unless another group or persisted assignment grants them |
| `auditors` | Read-only access across both domains, including restricted tickets |
| `system-admins` | Administrative scope across domains |

Persisted `UserRole` assignments take precedence over the Keycloak group
fallback and may narrow authority by office, service, or queue. Malformed
persisted assignments fail closed. When a restricted-only grant and a broader
grant cover the same branch, the broader grant supplies ordinary rows for that
branch; the restricted-only grant does not broaden any other branch.

The verified Keycloak `sub` is the authoritative local identity binding. A
different subject cannot take over an existing authoritative username. An
inactive local user has no canonical authority, including when marked as a
superuser, and matter validation conceals denied records without provider or
outbox side effects.

Out-of-scope ticket lookups, including attachment lookups, return `404` so a
caller cannot use the response to enumerate another domain.

## Public API surface

The following `/api/v1` endpoints declare `AllowAny` in the current route
audit. Provider authenticity, throttling, or token checks performed inside a
view are separate from DRF authentication.

| Path | Methods | Implemented access |
|---|---|---|
| `/api/v1/health` and `/api/v1/health/live` | GET | Public readiness and liveness |
| `/api/v1/tickets/public/intake/` | POST | Public, anonymous rate throttle |
| `/api/v1/public/requester/{token}/` | GET | Public route; valid requester token required by the view |
| `/api/v1/public/requester/{token}/reply/` | POST | Public route; valid requester token required by the view |
| `/api/v1/public/knowledge/` | GET | Public published knowledge |
| `/api/v1/public/csat/{token}/` | POST | Public route; token handled by the view |
| `/api/v1/integrations/email/events/` | POST | Public transport route; configured HMAC signature, timestamp freshness, unique event ID, verified sender, active mailbox, and replay claim are required before state changes |
| `/api/v1/integrations/email/bounce/` | POST | Public transport route; configured HMAC signature, timestamp freshness, typed event claim, and replay protection are required before delivery changes |
| `/api/v1/integrations/monitoring/events/` | POST | Public DRF route |
| `/api/v1/integrations/whatsapp/webhook/` | GET, POST | Public transport route; GET requires the configured Meta verification token, while POST requires the native body signature, fresh message timestamps, active WABA/phone binding, and per-message replay claims |

The site root `/` is also public. `/api/v1/` is the authenticated DRF router
root and is not the same route.

## Protected integration helpers

| Path | Methods | Implemented access |
|---|---|---|
| `/api/v1/integrations/whatsapp/templates/` | GET | Keycloak authentication plus a `ticket_number`; the ticket must be in scope and the active actor must be allowed to mutate its domain before that ticket's configured account is queried |
| `/api/v1/integrations/whatsapp/send/` | POST | Keycloak authentication plus a scoped mutable ticket; inactive users and auditors are denied, and consent, opt-out, recipient, account, and approved-template checks run before provider send |

Neither WhatsApp helper declares a `required_scope`. Authentication protects
the route, while `_mutable_ticket` supplies object-level domain and mutation
authority. Route metadata alone therefore does not prove domain access. The
inbound WhatsApp webhook remains public for provider transport, but it is not
trusted without the signature and account checks documented in
[`channel-webhook-contract.md`](channel-webhook-contract.md).

## Protected ticket and file operations

Every route below requires authentication. The ticket is first selected
through `scope_ticket_queryset`; restricted and persisted dimensions therefore
apply before an object action runs.

| Path | Methods | Additional authorization |
|---|---|---|
| `/api/v1/tickets/` | GET | Scoped rows only; `domain`, `status`, `priority`, `assignee`, `office`, `channel`, `search`, `sort`, and opaque `cursor` are server-side inputs |
| `/api/v1/tickets/{number}/` | GET | Object must be in the caller's scoped queryset |
| `/api/v1/tickets/kanban/` | GET | Same scoped ticket queryset; terminal tickets excluded |
| `/api/v1/tickets/{number}/assignees/` | GET | Scoped ticket; returns active non-auditors eligible for that ticket's domain |
| `/api/v1/tickets/{number}/work-state/` | PATCH | Scoped ticket plus active Operational/IT agent or lead group for the ticket domain, or `system-admins`; auditor and inactive users are denied |
| `/api/v1/tickets/{number}/work-state/` reassignment/confidentiality | PATCH | `ops-supervisors`, `it-leads`, or `system-admins`, after the work-state check; self-assignment uses the server-provided capability and assignee ID |
| `/api/v1/tickets/{number}/transition/` | POST | Scoped ticket, active actor, active transition from the current state, and any transition `required_role`; admin scope bypasses the transition role but not persisted scope dimensions |
| `/api/v1/tickets/{number}/activity/` | GET | Scoped ticket; returns the internal chronological timeline (public reply, internal note, workflow, custody, attachment, and relationship categories). Relationship identifiers are included only when the counterpart is also visible. |
| `/api/v1/tickets/{number}/messages/` | GET, POST | Scoped ticket; POST requires active domain mutation authority and revalidates scope on the locked ticket |
| `/api/v1/tickets/{number}/notes/` | GET, POST | Scoped ticket; POST requires active domain mutation authority and revalidates scope on the locked ticket |
| `/api/v1/tickets/{number}/it-child/` | POST | Scoped mutable Operational parent; the service locks and revalidates the canonical parent before creating a sanitized IT child atomically |
| `/api/v1/tickets/{number}/attachments/` | GET, POST | Scoped ticket; POST requires active domain mutation authority, validates the whole bounded batch first, then locks and revalidates the ticket before provider calls |
| `/api/v1/attachments/{attachment_id}/download/` | GET | Attachment's ticket must be in scope and scan status must be `clean`; access is logged before a 60-second signed URL is returned |

Work-state and transition mutations require the caller's observed
`updated_at`. A stale value returns `409 stale_ticket` with the current
timestamp and no mutation. Ticket detail and list responses expose only
server-derived capabilities and available transitions; the frontend does not
grant lifecycle authority.

## Custody and audit evidence

Custody is available only inside the scoped ticket activity endpoint; there is
no public custody endpoint or requester self-service timeline. The scope lookup
applies before any timeline category is returned, including for Restricted
tickets. Auditors can read custody evidence only through their existing
read-only scope and cannot create, update, or delete ticket, message, note, or
custody data.

Custody entries are immutable and display the stored timestamp, action, actor
or named system process, source process, reason, and applicable prior/new
owner, queue, and status snapshots. Administrators and records staff must use
the approved retention/disposal process for a whole-ticket disposal after its
hold and candidate checks; there is no custody edit or selective-delete route.
The database permits its custody cascade only while that command holds an
atomic disposal transaction and has enabled the transaction-local retention
gate. Ordinary ORM deletes and direct SQL ticket deletes fail closed.
Unresolved legacy owner/queue IDs remain hashed custody snapshots with null
labels, and unresolved historical human subjects are shown as unverified
legacy actors rather than system processes.
The current custody integration covers creation, workflow, approved IT-child
workflow, and SLA escalation. Assignment/queue integration is explicitly a
Plan 2 pending change, not an authorization for current assignment writers to
bypass the future guarded assignment service.

The base ticket viewset deliberately exposes list and retrieve only. Collection
create and inherited detail update/delete methods are not routes; unsupported
base mutations return `405`. Explicit lifecycle and content actions above are
the only supported staff mutation paths.

## Reporting

| Path | Implemented authorization |
|---|---|
| `/api/v1/reports/dashboard/operational` | Authenticated plus unrestricted Operational scope; restricted-only responders receive `403` |
| `/api/v1/reports/dashboard/it` | Authenticated plus unrestricted IT scope; restricted-only responders receive `403` |
| `/api/v1/tickets/dashboard/operational/` | Same unrestricted Operational requirement |
| `/api/v1/reports/tickets.csv` | Streams only `scope_ticket_queryset` rows; an explicit `domain` parameter also requires unrestricted authority for that domain |
| `/api/v1/reports/flow` | Aggregates only scoped rows; an explicit `domain` parameter also requires unrestricted authority for that domain |

Auditors can use these read-only reporting routes across both domains.
Security responders can export or aggregate only restricted rows when no
explicit domain is requested; they cannot use either domain dashboard.

## Other protected routes and current limitations

The permission audit reports authentication on identity, organization,
catalogue, contacts, workflow, SLA, notifications, administration, audit,
knowledge, and automation routes. `ScopePermission` on catalogue, contacts,
knowledge, and automation has no declared `required_scope`, so its metadata
must not be described as domain authorization without inspecting that view's
queryset and action rules.

`GET /api/v1/audit/` is currently a placeholder returning an empty collection
to any authenticated caller; it is not currently restricted to administrators
and auditors. `GET /api/v1/administration/` is likewise an authenticated
placeholder. These facts supersede older aspirational matrix entries.

## Shared API contracts and migration gaps

- The ticket list cursor uses `{ "next": string|null, "previous":
  string|null, "results": [...] }`. Its focused collection tests prove stable
  traversal across tied rows and a standardized `404` for a malformed cursor.
  This is not a claim that every collection endpoint uses cursor pagination.
- Raised DRF exceptions handled by
  `identity_access.exception_handlers.problem_details_handler` use
  `{ "code": string, "detail": string, "fields": {string: string[]},
  "correlation_id": string }`. Transition, work-state, and attachment
  validation helpers also return that envelope on their covered paths.
- Manual `Response` branches have not all been migrated. IT-child and public-
  intake validation, requester/CSAT routes, and integration endpoints include
  legacy response shapes. Uniform error envelopes across those paths remain an
  open API-consistency gap; clients must not assume the four-field envelope on
  every endpoint.
- Development bearer tokens use `dev:<username>:<comma-separated-groups>` and
  are accepted only while `settings.DEBUG` is true. Production settings set
  `DEBUG = False`; `backend/apps/identity_access/tests/test_authentication.py`
  verifies the bypass is rejected in that state.
- Public channel transport uses the signature, freshness, replay, sender, and
  provider/account contracts in
  [`channel-webhook-contract.md`](channel-webhook-contract.md). `AllowAny` on
  those routes is not a claim that unsigned payloads are accepted.

## Verification pointers

- Route metadata: `backend/scripts/permission_audit.py`
- Scope and auditor behavior: `backend/apps/identity_access/tests/test_scope.py`
- Identity subject binding and inactive-user behavior:
  `backend/apps/identity_access/tests/test_authentication.py` and
  `backend/apps/integrations/tests/test_validate_matter.py`
- Standardized exception and covered action errors:
  `backend/apps/identity_access/tests/test_api_contracts.py`,
  `backend/apps/tickets/tests/test_transition_api.py`,
  `backend/apps/tickets/tests/test_work_state_api.py`, and
  `backend/apps/files/tests/test_views.py`
- Ticket scope and pagination: `backend/apps/tickets/tests/test_scope_api.py`
  and `test_api_collections.py`
- Work state and transitions: `backend/apps/tickets/tests/test_work_state_api.py`,
  `test_transition_api.py`, and `test_workflow_capabilities.py`
- Locked ticket mutation boundaries:
  `backend/apps/tickets/tests/test_integrity_boundaries.py` and
  `backend/apps/tickets/tests/test_it_child_integrity.py`
- Files: `backend/apps/files/tests/test_policy.py`,
  `backend/apps/files/tests/test_services.py`, and
  `backend/apps/files/tests/test_views.py`
- Reporting: `backend/apps/reporting/tests/test_permissions.py`
- WhatsApp helper authentication and auditor denial:
  `backend/apps/whatsapp/tests/test_views.py`
- Email and WhatsApp webhook trust:
  `backend/apps/email_channel/tests/test_webhook_security.py` and
  `backend/apps/whatsapp/tests/test_views.py`
