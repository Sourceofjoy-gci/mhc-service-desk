# Delivery Roadmap

The PRD organises delivery into six outcome-based milestones. Each milestone
has explicit exit criteria and a definition of done. We re-validate the
milestone before moving to the next.

| # | Milestone | Status | Exit evidence |
|---|---|---|---|
| M0 | Service & Governance Baseline | ⬜ Pending | Service catalogue approved, DPIA drafted, retention classes agreed |
| M1 | Platform Foundation | ✅ Done | Auth via Keycloak, 9 containers up, health green, 7 tests |
| M2 | Operational Vertical Slice | ✅ Done | 13 smoke checks, 18 unit tests, full ticket lifecycle |
| M3 | IT Separation & Cross-Domain | ✅ Done | Sanitised IT child pattern, scope guards, email channel |
| M4 | P0 Channels & Pilot Readiness | ✅ Done | Call/walk-in intake, attachments, CSV export, requester link |
| M5 | P1 Omnichannel | ✅ Done | WhatsApp (mock+cloud), knowledge, CSAT, automation rules, e-Estate |
| M6 | Optimisation | ✅ Done | Problem/Change managers, monitoring correlation, flow metrics, AI assist guard |

## Milestone coverage map

### M2 — Operational Vertical Slice
- Contacts, catalogue, ticket model, workflow engine, basic SLA, public form
- Kanban (dnd-kit), queue, ticket detail, dashboard
- Auth (Keycloak OIDC + dev-bypass), cross-domain scope guard

### M3 — IT Separation & Cross-Domain
- `apps.tickets.it_child.create_it_child_ticket()` — sanitised child pattern
- `sync_child_status_to_parent()` — safe status sync when IT child resolves
- Restricted-ticket visibility via `can_view_restricted()`
- Inbound email channel with Message-ID idempotency + thread matching
- HTML sanitisation (bleach allow-list)

### M4 — P0 Channels
- Call-centre + walk-in intake pages
- Attachment upload to MinIO with ClamAV scan
- Signed download URLs with audit
- CSV export, scope-limited
- Requester magic-link status + reply

### M5 — P1 Omnichannel
- WhatsApp adapter (`apps.whatsapp`): mock + Meta Cloud API provider abstraction
- WhatsApp webhook → email pipeline (reuses idempotency / threading)
- Knowledge base with versioned articles, audience scoping, public search
- CSAT model and public survey endpoint
- Automation rules (data-driven, no eval): triggers, conditions, actions
- e-Estate validation stub

### M6 — Optimisation
- Problem manager (`ProblemManager.open_problem`) with related-incident links
- Change manager with risk tagging
- Monitoring webhook with alert correlation / dedup
- Flow metrics endpoint (lead/cycle time, WIP, percentiles)
- AI assist guard (`apps.automation.ai_assist`) — suggestion → human approval → application

## Out of scope (deliberately deferred)

- Native mobile applications
- Biometric identity verification
- Real-time WebSocket presence (short polling + optimistic updates used in P0)
- Metabase reporting replica (deferred to P2 production)
- Full Kubernetes HA/DR automation (Docker Compose pilot)
- Real e-Estate API integration (P1 stub only)
- Real Meta Cloud API (P1 mock only; cloud provider wired and ready)
- Real ClamAV signatures in dev (soft pass; production deployment pulls them)

## Test totals

- 28 unit tests, 0 failures
- 6 smoke scripts covering M2 through M6
- Every smoke check is idempotent and re-runnable
