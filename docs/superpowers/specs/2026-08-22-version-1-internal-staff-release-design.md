# Version 1 Internal Staff Release Design

## Goal

Ship Version 1 as a production-ready, authenticated internal ticketing system for
staff who receive walk-in visitors and telephone calls. Preserve the complete
internal Operational and IT service-desk capability while removing every
public-facing self-service and external messaging channel from the Version 1
runtime surface.

Version 1.1 will restore public web access, requester self-service, email and
WhatsApp only after their security, provider and delivery requirements are ready.

## Approved Product Boundary

Version 1 includes:

- Keycloak-authenticated internal access and role-based authorization;
- call and walk-in ticket capture by authorized staff;
- Operational and IT tickets and their complete lifecycle;
- staff queue, search, ticket detail and Kanban views;
- assignment, routing, escalation and approvals;
- SLA calculation and tracking;
- internal notes, messages and attachments;
- the sanitized IT child-ticket workflow;
- internal knowledge, automation, dashboards, exports, audit and administration;
- production monitoring, TLS, backup and restore, retention and operational
  runbooks.

Version 1.1 contains only the public and external-channel surfaces:

- public web intake and any anonymous application access;
- requester status, replies, magic links and requester-facing ticket tracking;
- public CSAT and public knowledge search;
- inbound and outbound email channel behavior;
- inbound and outbound WhatsApp behavior;
- external provider credentials, approvals, webhook delivery, retries and
  deduplication.

The Version 1.1 boundary does not waive defects in shared or internal code. Access
control, PII isolation, audit integrity, monitoring authorization, backup/restore,
TLS, performance and reliability remain Version 1 release requirements.

## Current Codebase State

The codebase already has separate authenticated call and walk-in pages, but both
call a backend function named `public_intake` at
`POST /api/v1/tickets/public/intake/`. Despite its name, that endpoint currently
requires authentication, an Operational role and unrestricted Operational
office/service authority. Its serializer also accepts `web` and `email`, and
defaults to `web`, which is wider and less explicit than the approved release.

The authenticated frontend currently exposes a requester-style **Track ticket**
route in addition to the staff queue. Staff can already retrieve scoped tickets
through the queue and open their detail pages, so the requester-style route is not
needed for Version 1.

The backend registers public requester, CSAT and knowledge routes unconditionally.
It also registers email and WhatsApp integration routes unconditionally. Hiding
links in the frontend would therefore leave the APIs reachable.

## Approaches Considered

### Conditionally register public URL modules

Add one fail-closed release setting and omit public self-service and external
channel paths from Django's URL resolver when the setting is false. This makes an
excluded route indistinguishable from a nonexistent route and prevents view code
from running.

This is the selected primary control.

### Check a feature flag inside each public view

Each public view could reject requests when Version 1 is active. This retains the
route surface, duplicates checks and makes it easy for a newly added public view to
omit the guard.

Rejected as the primary control. A shared guard may still be used as a secondary
defence where a module mixes internal and public routes.

### Block public paths only in Nginx

The reverse proxy could deny the known paths without application changes. Direct
access to the application server, tests or a later proxy change could bypass that
policy, and misleading internal endpoint names and channel validation would remain.

Rejected as the sole control. Proxy denial is retained as defence in depth.

## Architecture

### Release capability setting

Introduce `PUBLIC_SELF_SERVICE_ENABLED`, sourced from the production environment
and defaulting to `False`. Version 1 production configuration sets it explicitly to
false. Version 1.1 may set it to true only after its own acceptance gates pass.

The flag controls public self-service and external messaging capabilities only. It
must not disable:

- the API root;
- liveness, readiness or dependency health checks;
- Keycloak login and authenticated identity endpoints;
- Prometheus metrics required by production monitoring;
- internal ticket, knowledge, automation, reporting or administration APIs.

Environment examples, production Compose validation and deployment documentation
must describe the setting. Missing configuration remains fail-closed.

### Backend route composition

Version 1 keeps the internal routers and selectively excludes the following
surfaces:

| Current route | Version 1 behavior | Version 1.1 destination |
|---|---|---|
| `/api/v1/public/requester/<token>/` | not registered | requester status |
| `/api/v1/public/requester/<token>/reply/` | not registered | requester reply |
| `/api/v1/public/csat/<token>/` | not registered | requester CSAT |
| `/api/v1/public/knowledge/` | not registered | public knowledge search |
| `/api/v1/integrations/email/events/` | not registered | inbound email |
| `/api/v1/integrations/email/bounce/` | not registered | email delivery events |
| `/api/v1/integrations/whatsapp/webhook/` | not registered | inbound WhatsApp |
| `/api/v1/integrations/whatsapp/templates/` | not registered | WhatsApp provider templates |
| `/api/v1/integrations/whatsapp/send/` | not registered | outbound WhatsApp |

Applications, models and migrations for deferred features remain installed. This
avoids destructive schema churn and preserves an incremental Version 1.1 path.
Deferred workers, scheduled jobs and outbound provider calls must not run in the
Version 1 deployment.

The Nginx production configuration denies the same route families. Django route
omission remains authoritative; the proxy rule is a second layer and not a
replacement for application tests.

### Explicit staff intake contract

Replace the misleading public intake contract with an internal one:

- endpoint: `POST /api/v1/tickets/staff/intake/`;
- view and client name: `staff_intake` / `staffIntake`;
- authentication: required;
- authorization: active internal staff with valid Operational authority for the
  selected office and service;
- allowed channels: exactly `call` and `walk_in`;
- required requester and routing fields: retain the validated fields used by the
  existing assisted-intake flow;
- consent: retain the existing recorded-consent requirement;
- attachments: retain the existing file count, size, type and malware-policy
  limits;
- side effects: contact resolution, ticket creation, custody/audit event and SLA
  instantiation happen atomically;
- response: ticket reference and the minimum data required for the staff
  confirmation screen.

There is no compatibility alias at `/tickets/public/intake/` in Version 1. Keeping
the old path would preserve a misleading public surface and make route assertions
ambiguous. `web`, `email`, `whatsapp`, missing channel values and unknown channel
values are rejected with validation errors.

The intake API needs a server-side idempotency control for accidental retry or
double submission. A repeated request with the same authorized actor and
idempotency key returns the first successful result; it must not create a second
contact, ticket, SLA or audit chain.

### Frontend surface

The authenticated application keeps:

- Queue and scoped search;
- ticket detail;
- Kanban;
- Dashboard;
- Call intake;
- Walk-in intake;
- Health and user/account controls.

Remove the **Track ticket** navigation entry and `/ticket-tracking` route from the
Version 1 build. That page is a requester-style lookup and is redundant with the
staff queue/search workflow. Direct navigation returns the normal not-found page.
The existing public form component is not registered.

Both assisted-intake pages call `staffIntake` and send their channel explicitly.
Frontend hiding is a usability measure; backend route and authorization controls
remain the security boundary.

### Internal queue and search

Staff queue/search remains read-only as a retrieval surface: searching, filtering,
sorting and pagination do not change ticket state. Opening a result transfers the
user to the authorized ticket workspace, where lifecycle actions are separately
permission-checked.

Every queue query and direct ticket lookup uses the same resolved authority scope.
A user must not discover an inaccessible ticket through counts, suggestions,
search results, exports or direct reference lookup. Restricted-ticket and office,
service and queue boundaries continue to apply.

### Roles and authorization

The release does not simplify the existing internal role model. Tests and
production verification must cover at least:

- service desk and Operational agents capturing call and walk-in tickets;
- office/service/queue restrictions;
- IT agents working only with authorized IT records;
- supervisors and managers assigning, reassigning, escalating and approving only
  within their authority;
- auditors receiving read-only visibility without mutation rights;
- administrators performing only authorized administration;
- roleless, expired-role and incorrectly grouped users being denied by default.

Group fallback must never restore authority when persisted role assignments exist
but are expired or inactive. Public channel removal does not mitigate a broken
internal role boundary.

## Data Flow

### Call or walk-in capture

1. Keycloak authenticates the staff member.
2. The SPA submits the assisted-intake payload with `call` or `walk_in` and an
   idempotency key.
3. The API resolves the actor's current roles and office/service/queue scope.
4. The serializer validates requester data, consent, routing fields, channel and
   attachments.
5. One transaction resolves or creates the contact, creates the ticket, records
   custody/audit history and instantiates the SLA.
6. The API returns the stable ticket reference.
7. The ticket becomes visible in the authorized staff queue and search.

### Queue retrieval

1. An authenticated user supplies search, filter, ordering and pagination
   parameters.
2. The server applies authority scoping before search and aggregation.
3. The response includes only authorized ticket summaries.
4. Opening a result performs a fresh server-side permission check and returns the
   ticket workspace.
5. Any mutation from that workspace uses its own role and state-transition check.

### Deferred route request

1. A client requests a public requester, CSAT, knowledge, email or WhatsApp path.
2. Nginx may reject the known path.
3. If the request reaches Django, no Version 1 route matches it.
4. The response is `404`; no token lookup, database mutation, provider call or
   asynchronous task occurs.

## Error and Security Behavior

| Condition | Required result |
|---|---|
| Anonymous request to internal intake | `401` |
| Authenticated but roleless or expired-role user | `403` |
| IT-only user attempting Operational intake | `403` |
| Actor outside selected office/service/queue authority | `403` |
| `web`, `email`, `whatsapp`, absent or unknown intake channel | `400` |
| Invalid requester, consent, routing or attachment data | field-level `400` with no partial records |
| Duplicate valid intake with same idempotency key | original success response; one ticket only |
| Deferred public/external-channel route | `404` |
| Unauthorized queue search or direct ticket access | no information disclosure; `403` or scoped `404` according to the existing API convention |
| Downstream SLA/audit failure during intake | transaction rollback and safe `5xx`; no orphan ticket |

Logs must not contain requester message bodies, tokens, credentials or unnecessary
PII. Security-relevant denials and failed state transitions must remain auditable
without recording secrets.

## Verification Strategy

### Backend contract tests

- call and walk-in intake succeed for each authorized staff role and permitted
  scope;
- both channels create the expected contact, ticket, custody/audit and SLA data;
- every critical field, enum, attachment and consent parameter is covered at its
  valid and invalid boundaries;
- unauthorized identities and out-of-scope office/service/queue combinations fail
  closed;
- `web`, `email`, `whatsapp` and missing channel values fail validation;
- duplicate idempotency keys create exactly one ticket;
- queue/search filtering, pagination, ordering and direct lookup preserve all role
  and PII boundaries;
- every deferred public, email and WhatsApp path returns `404` with the Version 1
  flag false and causes no side effects;
- a separate flag-on suite preserves the Version 1.1 route contracts without making
  them part of the Version 1 production deployment;
- root, authentication, health and metrics endpoints remain available as intended.

### Frontend tests

- Call and Walk-in forms send only their explicit channel to `staffIntake`;
- successful capture displays the returned ticket reference once;
- validation, authorization, network and retry failures are recoverable and do not
  imply a ticket was created when the result is unknown;
- Queue provides read-only search and retrieval before a ticket is opened;
- inaccessible tickets never appear in queue results or counts;
- Track ticket and all public self-service links and routes are absent;
- existing internal queue, ticket detail, Kanban, dashboard and workflow tests
  continue to pass.

### Production checks

- lint, type checks, backend and frontend test suites and production builds pass;
- production Compose explicitly disables public self-service and its validation
  script fails unsafe combinations;
- browser smoke tests capture one call and one walk-in ticket and retrieve both
  through queue/search under the correct staff roles;
- negative browser/API checks cover anonymous, roleless, wrong-domain and
  out-of-scope identities;
- route probes confirm public requester, CSAT, knowledge, email and WhatsApp
  surfaces return `404`;
- backup/restore, TLS, monitoring authorization, audit integrity, retention and
  representative load tests pass;
- deployment and rollback runbooks state that enabling public self-service is not a
  Version 1 rollback or recovery action.

## Release Acceptance

Version 1 is ready only when:

1. the complete internal role/workflow matrix passes;
2. call and walk-in intake are atomic, idempotent and correctly audited;
3. queue/search is read-only, scoped and free of cross-role or cross-office data
   leakage;
4. all public self-service, email and WhatsApp routes and jobs are absent from the
   deployed runtime;
5. shared internal security findings are fixed or explicitly accepted by the
   authorized release owner;
6. production TLS, backup/restore, monitoring, audit, retention and load gates pass;
7. Version 1.1 items are recorded separately and are not used to justify an
   internal Version 1 failure.

Passing automated tests alone is not a production approval. The final readiness
report must classify findings against this approved boundary and issue a fresh
GO/NO-GO decision.

## Version 1.1 Re-entry Conditions

Enabling public self-service later requires a separate design and release review
covering token-to-ticket binding, requester PII projections, CSAT authorization,
public knowledge publication, email and WhatsApp webhook authentication, provider
approval, outbound consent, leased/idempotent dispatch, retries, deduplication,
dead-letter handling, rate limiting, abuse protection and public accessibility.

The Version 1 flag must not be flipped merely because deferred code exists. Version
1.1 enables it only after these controls have tests, operational ownership and an
approved production configuration.
