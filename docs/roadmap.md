# Delivery roadmap

Milestone status is evidence-linked rather than a blanket completion claim.
Exact automated totals live only in the dated
[`verification/pilot-foundation-2026-07-27.md`](verification/pilot-foundation-2026-07-27.md)
record.

| # | Milestone | Implemented | Automatically verified | Manual/external work still open |
|---|---|---|---|---|
| M0 | Service and governance baseline | Governance templates, retention model, permission documentation, and runbooks exist | Repository presence only; not a governance approval | DPIA and owner approvals remain unsigned |
| M1 | Platform foundation | Django/React stack, Keycloak integration, health routes, scoped identity model, and Docker development tooling exist | Final images built, live migrations applied, backend health, Django/dependency checks, full backend suite, strict mypy, permission audit, and frontend gates passed; Ruff passed only in the authorized dirty worktree | Clean-checkout Ruff, production TLS/secrets, and browser verification are open |
| M2 | Operational vertical slice | Intake, scoped queue/Kanban, ticket workspace, SLA presentation, lifecycle, activity, and Operational dashboard exist | Final live Operational smoke and independent ticket/frontend and SLA reviews passed | Operational UAT, conditional reconciliation for an earlier unshipped SLA `0004`, and rendered desktop/mobile verification remain open |
| M3 | IT separation and cross-domain work | Scoped IT queues/reporting, sanitized IT-child flow, restricted tickets, and email-threading code exist | Final live smoke demonstrated dashboard denials, out-of-domain `404`, IT-child visibility, and material activity; persisted email-sanitizer regression passed | IT UAT, provider/integration validation, and browser verification remain open |
| M4 | P0 channels and pilot operations | Call/walk-in/web/email fields, requester link, attachments, CSV export, graph-atomic retention, and operational scripts exist | Full backend suite and independent attachment and retention reviews passed | Restore drill, production object-store/provider operations, accessibility review, and external go-live approvals remain open |
| M5 | P1 omnichannel | Signed/replay-protected email and WhatsApp webhooks, ticket-scoped WhatsApp templates/send, knowledge, CSAT, automation, and e-Estate stub are present | Independent channel review passed; no release-wide green claim | Meta/e-Estate approvals and credentials remain external; production WhatsApp also needs a leased idempotent dispatch/retry worker and API-retry deduplication |
| M6 | Optimization | Problem/change models, monitoring correlation, flow metrics, and guarded AI-assist code are present | No load/performance or production-operability claim | Capacity, response-time, reporting, and AI governance validation remain open |

## Implemented foundation by outcome

### Operational work

- Server-filtered queue and Kanban views use the same scoped ticket source.
- Queue state is encoded in URL parameters and uses opaque cursor links.
- Ticket detail exposes server-approved transitions and request-derived
  mutation capabilities.
- Queue and Kanban domain selection is derived from the authenticated user's
  domain capabilities; invalid URL domains are removed or canonicalized.
- Assignment/work-state, requester replies, internal notes, activity, SLA,
  relationships, and attachments are combined in the staff workspace.
- Resolve/reopen and optimistic conflict behavior are implemented in the
  service/API layers.
- Content, work-state, transition, attachment, and IT-child mutations recheck
  canonical authority against locked ticket rows before committing.
- SLA clocks use corrected calendar-local business time, frozen pause
  entitlement, and exact-deadline breach semantics.

### IT separation

- Operational and IT domain scopes are separate.
- Security responders receive restricted-only rows across both domains unless
  another grant supplies ordinary-domain authority.
- Auditors are read-only across both domains.
- IT-child creation copies an intentionally limited payload, and child
  resolution does not directly close the Operational parent.
- Reporting dashboards require unrestricted authority for their domain;
  scoped exports and flow metrics cannot broaden access.

### Channels and records

- Public intake, inbound email, WhatsApp/provider abstractions, requester
  token routes, attachment scan/download, knowledge, CSAT, and automation
  surfaces exist.
- Public email and WhatsApp webhooks fail closed without valid signatures,
  freshness, replay claims, and provider/account binding.
- WhatsApp template listing and outbound sending require a scoped mutable
  ticket and derive the recipient and account from that ticket.
- Inbound email HTML sanitization uses Bleach 6.4.0 and has a persisted-content
  regression for invisible URI-scheme characters and `formaction`.
- Attachment intake is bounded and atomic; cleanup targets only an exact
  object version owned by the committed attachment row.
- Audit/outbox event pairs are transactional on the tested ticket mutation
  paths.
- Retention preserves held ticket graphs and commits disposal, exact-version
  cleanup jobs, and truthful certificate state atomically.
- SAR, backup, restore, incident, channel-contract, and pilot runbook assets
  exist.

## Remaining verification sequence to close the pilot foundation

1. Land or otherwise reconcile the preserved user-owned lint cleanup so
   `ruff check .` also passes from a clean committed checkout.
2. Perform desktop and mobile browser verification, including controlled
   loading, empty, forbidden, validation, and stale-conflict states.
3. If an environment applied an earlier revision of unshipped SLA migration
   `0004`, manually reconcile its affected paused rows. Fresh deployments and
   the current live pilot rows are correct.
4. Implement leased idempotent WhatsApp dispatch/retry and API-retry
   deduplication before production activation.
5. Complete UAT, restore/load exercises, security testing, production
   TLS/secret configuration, provider approvals, and governance signatures.

No milestone in this roadmap overrides the readiness checklist. The pilot
decision remains open while any required release or external gate is open.

## Deliberately deferred scope

- Native mobile and biometric identity.
- WebSocket presence.
- Multi-region Kubernetes HA and a separate Metabase replica.
- Real e-Estate production integration and production WhatsApp activation
  until provider approvals/credentials and the P1 dispatch/retry work exist.
- Remaining P1/P2 items identified as deferred in traceability.
