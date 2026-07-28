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
| `/api/v1/integrations/email/events/` | POST | Public DRF route |
| `/api/v1/integrations/email/bounce/` | POST | Public DRF route |
| `/api/v1/integrations/monitoring/events/` | POST | Public DRF route |
| `/api/v1/integrations/whatsapp/webhook/` | POST | Public DRF route |
| `/api/v1/integrations/whatsapp/templates/` | GET | Public DRF route |
| `/api/v1/integrations/whatsapp/send/` | POST | Public DRF route in the current implementation |

The site root `/` is also public. `/api/v1/` is the authenticated DRF router
root and is not the same route.

## Protected ticket and file operations

Every route below requires authentication. The ticket is first selected
through `scope_ticket_queryset`; restricted and persisted dimensions therefore
apply before an object action runs.

| Path | Methods | Additional authorization |
|---|---|---|
| `/api/v1/tickets/` | GET | Scoped rows only; `domain`, `status`, `priority`, `assignee`, `office`, `channel`, `search`, `sort`, and opaque `cursor` are server-side inputs |
| `/api/v1/tickets/` | POST | Authenticated `ScopePermission`; the current viewset does not declare a route-level required domain |
| `/api/v1/tickets/{number}/` | GET, PUT, PATCH, DELETE | Object must be in the caller's scoped queryset; auditors are denied unsafe methods by `ScopePermission` |
| `/api/v1/tickets/kanban/` | GET | Same scoped ticket queryset; terminal tickets excluded |
| `/api/v1/tickets/{number}/assignees/` | GET | Scoped ticket; returns active non-auditors eligible for that ticket's domain |
| `/api/v1/tickets/{number}/work-state/` | PATCH | Scoped ticket plus active Operational/IT agent or lead group for the ticket domain, or `system-admins`; auditor and inactive users are denied |
| `/api/v1/tickets/{number}/work-state/` reassignment/confidentiality | PATCH | `ops-supervisors`, `it-leads`, or `system-admins`, after the work-state check; self-assignment uses the server-provided capability and assignee ID |
| `/api/v1/tickets/{number}/transition/` | POST | Scoped ticket, active actor, active transition from the current state, and any transition `required_role`; admin scope bypasses the transition role but not persisted scope dimensions |
| `/api/v1/tickets/{number}/activity/` | GET | Scoped ticket; relationship identifiers are included only when the counterpart is also visible |
| `/api/v1/tickets/{number}/messages/` | GET, POST | Scoped ticket; auditor writes are denied |
| `/api/v1/tickets/{number}/notes/` | GET, POST | Scoped ticket; auditor writes are denied |
| `/api/v1/tickets/{number}/it-child/` | POST | Scoped Operational parent; auditor writes are denied; the service creates a sanitized IT child |
| `/api/v1/tickets/{number}/attachments/` | GET, POST | Scoped ticket; auditor may list but may not upload |
| `/api/v1/attachments/{attachment_id}/download/` | GET | Attachment's ticket must be in scope and scan status must be `clean`; access is logged before a 60-second signed URL is returned |

Work-state and transition mutations require the caller's observed
`updated_at`. A stale value returns `409 stale_ticket` with the current
timestamp and no mutation. Ticket detail and list responses expose only
server-derived capabilities and available transitions; the frontend does not
grant lifecycle authority.

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

## Shared API contracts

- Cursor collections use `{ "next": string|null, "previous": string|null,
  "results": [...] }`. Ticket pagination is stable across ties and treats a
  malformed cursor as canonical `404`.
- DRF errors use `{ "code": string, "detail": string, "fields":
  {string: string[]}, "correlation_id": string }`. Ticket action and file
  validation paths return the same shape.
- Development bearer tokens use `dev:<username>:<comma-separated-groups>` and
  are accepted only while `settings.DEBUG` is true. Production settings set
  `DEBUG = False`; `backend/apps/identity_access/tests/test_authentication.py`
  verifies the bypass is rejected in that state.

## Verification pointers

- Route metadata: `backend/scripts/permission_audit.py`
- Scope and auditor behavior: `backend/apps/identity_access/tests/test_scope.py`
- Canonical errors: `backend/apps/identity_access/tests/test_api_contracts.py`
- Ticket scope and pagination: `backend/apps/tickets/tests/test_scope_api.py`
  and `test_api_collections.py`
- Work state and transitions: `backend/apps/tickets/tests/test_work_state_api.py`,
  `test_transition_api.py`, and `test_workflow_capabilities.py`
- Files: `backend/apps/files/tests/test_views.py`
- Reporting: `backend/apps/reporting/tests/test_permissions.py`
