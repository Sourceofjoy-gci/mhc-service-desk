# Permission Matrix — derived from code

This document is the authoritative source for "who can do what" in the
MHC e-Ticketing platform. It is generated from the actual permission code
(`apps.identity_access.scope` and the `Scope.matches()` check) and the
class-level `permission_classes` on each DRF view, not aspirational.

If the code changes, this matrix must change with it. The
``scripts/permission_audit.py`` script (in ``backend/scripts/``) lists
every permission-related attribute on every view in the codebase so a
reviewer can spot drift.

## Scope model

`Scope(domain, office_id=None, service_id=None, queue_id=None)` is the
unit of authority. A user has one or more scopes, derived from their
Keycloak group memberships via `get_user_scopes`:

| Keycloak group | Domain scope(s) |
|---|---|
| `ops-agents`          | `operational` |
| `ops-supervisors`     | `operational` |
| `it-agents`           | `it` |
| `it-leads`            | `it` |
| `security-responders` | `operational` + `it` (restricted only) |
| `system-admins`       | `admin` (matches all) |
| `auditors`            | `operational` + `it` (read-only) |

`admin` matches every scope, including across domains. `audit` matches
every scope but is read-only at the view level.

## Restricted tickets (FR-014.2)

A ticket with `confidentiality="restricted"` is hidden from:
* regular `ops-agents` and `it-agents`
* anyone without a privileged group membership

It is visible to:
* `ops-supervisors`, `lead-it`, `security-responders`
* `system-admins`, `auditors`

Implementation: `can_view_restricted(user)` in `apps.identity_access.scope`.

## Endpoint matrix

| Path | Method | Auth | Scope required | Restricted visible? | Notes |
|---|---|---|---|---|---|
| `/api/v1/health` | GET | none | n/a | n/a | Aggregated readiness probe |
| `/api/v1/health/live` | GET | none | n/a | n/a | Liveness probe (no deps) |
| `/api/v1/tickets/` | GET | yes | own domains | hidden if restricted | Query params: status, priority, assignee, office, channel, search |
| `/api/v1/tickets/{number}/` | GET | yes | own domains | hidden if restricted | Full detail |
| `/api/v1/tickets/{number}/transition/` | POST | yes | own domains | n/a | Validates workflow rule |
| `/api/v1/tickets/{number}/it-child/` | POST | yes | operational only | n/a | Creates sanitised child |
| `/api/v1/tickets/{number}/messages/` | GET/POST | yes | own domains | n/a | Public reply messages |
| `/api/v1/tickets/{number}/notes/` | GET/POST | yes | own domains | n/a | Internal notes (never exposed externally) |
| `/api/v1/tickets/{number}/attachments/` | POST | yes | own domains | n/a | Multipart upload, scanned before access |
| `/api/v1/tickets/kanban/` | GET | yes | own domains | hidden if restricted | Grouped by status_code |
| `/api/v1/tickets/public/intake/` | POST | **none** | n/a | n/a | Rate-limited 5/min/IP |
| `/api/v1/tickets/dashboard/operational/` | GET | none | n/a | n/a | Public aggregate |
| `/api/v1/tickets/{number}/validate-matter/` | GET | yes | own domains | n/a | e-Estate stub |
| `/api/v1/integrations/email/events/` | POST | none | n/a | n/a | Webhook; idempotent by Message-ID |
| `/api/v1/integrations/email/bounce/` | POST | none | n/a | n/a | Webhook |
| `/api/v1/integrations/whatsapp/webhook/` | POST | none | n/a | n/a | Webhook; idempotent by provider ID |
| `/api/v1/integrations/whatsapp/templates/` | GET | none | n/a | n/a | Template catalogue (no PII) |
| `/api/v1/integrations/whatsapp/send/` | POST | none | n/a | n/a | Provider abstraction; mock in dev |
| `/api/v1/integrations/monitoring/events/` | POST | none | n/a | n/a | AlertManager webhook; dedup by key |
| `/api/v1/contacts/` | CRUD | yes | own domains | n/a | Scoped; supports dedup |
| `/api/v1/contacts/duplicates/` | GET | yes | own domains | n/a | Suggest, never auto-merge |
| `/api/v1/contacts/public/requester/{token}/` | GET | **none** | token | n/a | Magic-link status, masked |
| `/api/v1/contacts/public/requester/{token}/reply/` | POST | **none** | token | n/a | Requester reply |
| `/api/v1/catalogue/services/` | CRUD | yes | own domains | n/a | Service / request type catalog |
| `/api/v1/knowledge/articles/` | CRUD | yes | admin or knowledge owner | n/a | Versioned, audience-scoped |
| `/api/v1/public/knowledge/` | GET | none | n/a | n/a | Public-audience only |
| `/api/v1/automation/rules/` | CRUD | yes | admin or `ops-supervisors` / `lead-it` | n/a | Data-driven, no eval |
| `/api/v1/reports/tickets.csv` | GET | yes | own domains | hidden if restricted | Scope-limited CSV export |
| `/api/v1/reports/dashboard/operational` | GET | yes | own domains | n/a | KPI aggregates |
| `/api/v1/reports/dashboard/it` | GET | yes | own domains | n/a | KPI aggregates |
| `/api/v1/reports/flow` | GET | yes | own domains | n/a | Lead/cycle percentiles |
| `/api/v1/audit/` | GET | yes | admin or auditor | n/a | Read-only audit log |
| `/api/v1/public/csat/{token}/` | POST | **none** | token | n/a | CSAT survey submit |

## Notes on enforcement

* All authenticated endpoints set `permission_classes = [IsAuthenticated, ScopePermission]`
  via the `scope_required()` decorator or the viewset's `permission_classes`
  attribute. The `ScopePermission.has_permission` always calls
  `attach_scopes(request)` first so `_scopes` is populated.
* `public_endpoint` decorator marks a view as bypassing authentication
  (used only for the requester magic link, the public form, the health
  endpoints, and the integration webhooks).
* The `dev:bypass` token (`dev:<user>:<groups>`) is only honoured when
  `settings.DEBUG` is True. In production the prod settings module
  unconditionally sets `DEBUG = False`, so the bypass is never reachable.
* The frontend never sees the full ticket list — every authenticated
  call passes through the same scope filter. A user with only the
  `it-agents` group cannot enumerate operational tickets.
