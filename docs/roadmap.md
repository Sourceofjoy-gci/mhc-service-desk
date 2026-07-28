# Delivery roadmap

Milestone status is evidence-linked rather than a blanket completion claim.
Exact automated totals live only in the dated
[`verification/pilot-foundation-2026-07-27.md`](verification/pilot-foundation-2026-07-27.md)
record.

| # | Milestone | Implemented | Automatically verified | Manual/external work still open |
|---|---|---|---|---|
| M0 | Service and governance baseline | Governance templates, retention model, permission documentation, and runbooks exist | Repository presence only; not a governance approval | DPIA and owner approvals remain unsigned |
| M1 | Platform foundation | Django/React stack, Keycloak integration, health routes, scoped identity model, and Docker development tooling exist | Migration drift, Django check, permission audit, and current frontend gates passed in the latest evidence | Full backend tests, Ruff, mypy, production TLS/secrets, and browser verification are open |
| M2 | Operational vertical slice | Intake, scoped queue/Kanban, ticket workspace, SLA presentation, lifecycle, activity, and Operational dashboard exist | Live Operational lifecycle smoke passed | Operational UAT and rendered desktop/mobile verification remain open |
| M3 | IT separation and cross-domain work | Scoped IT queues/reporting, sanitized IT-child flow, restricted tickets, and email-threading code exist | Live smoke demonstrated dashboard denials, out-of-domain `404`, IT-child visibility, and material activity | IT UAT, provider/integration validation, and browser verification remain open |
| M4 | P0 channels and pilot operations | Call/walk-in/web/email fields, requester link, attachments, CSV export, and operational scripts exist | Attachment/reporting focused tests are linked in traceability; the latest full backend gate did not complete | Restore drill, attachment/provider operations, accessibility review, and external go-live approvals remain open |
| M5 | P1 omnichannel | WhatsApp adapter, knowledge, CSAT, automation, and e-Estate stub are present | No current release-wide green claim | Meta/e-Estate approvals and production credentials remain external; selected features remain stubs or deferred |
| M6 | Optimization | Problem/change models, monitoring correlation, flow metrics, and guarded AI-assist code are present | No load/performance or production-operability claim | Capacity, response-time, reporting, and AI governance validation remain open |

## Implemented foundation by outcome

### Operational work

- Server-filtered queue and Kanban views use the same scoped ticket source.
- Queue state is encoded in URL parameters and uses opaque cursor links.
- Ticket detail exposes server-approved transitions and request-derived
  mutation capabilities.
- Assignment/work-state, requester replies, internal notes, activity, SLA,
  relationships, and attachments are combined in the staff workspace.
- Resolve/reopen and optimistic conflict behavior are implemented in the
  service/API layers.

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
- Audit/outbox event pairs are transactional on the tested ticket mutation
  paths.
- Retention, SAR, backup, restore, incident, and pilot runbook assets exist.

## Verification sequence to close the pilot foundation

1. Repair the backend full-test collection path and rerun all backend tests.
2. Resolve the repository-wide Ruff and strict-mypy baselines, then rerun the
   complete backend gate.
3. Preserve the passing current-source frontend test/type/lint/build gate and
   resolve or accept the documented build warnings.
4. Repeat the live Operational/IT smoke after backend repairs.
5. Perform desktop and mobile browser verification, including controlled
   loading, empty, forbidden, validation, and stale-conflict states.
6. Complete UAT, restore/load exercises, security testing, production
   TLS/secret configuration, provider approvals, and governance signatures.

No milestone in this roadmap overrides the readiness checklist. The pilot
decision remains open while any required release or external gate is open.

## Deliberately deferred scope

- Native mobile and biometric identity.
- WebSocket presence.
- Multi-region Kubernetes HA and a separate Metabase replica.
- Real e-Estate production integration and operator-approved Meta WhatsApp
  setup until their owners provide contracts and credentials.
- Remaining P1/P2 items identified as deferred in traceability.
