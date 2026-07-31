# Requirement-to-module traceability

This document links pilot-foundation requirements to current code and focused
tests. A linked test is evidence that a contract exists, not a claim that the
complete release gate is green. Exact run totals and open gates are recorded
in
[`verification/pilot-foundation-2026-07-27.md`](verification/pilot-foundation-2026-07-27.md).

Status meanings:

- **Implemented**: a production code path exists.
- **Partial**: a model, adapter, or backend path exists but the full user or
  production workflow is not delivered.
- **Deferred**: no current pilot implementation is claimed.

The full backend pytest suite and strict mypy gate passed. Repository-wide Ruff
passed only in the explicitly authorized dirty worktree; clean-checkout Ruff
remains open because the required cleanup exists only in preserved, unstaged
user work.

## Pilot foundation verification trace

| Concern / PRD requirements | Endpoint or module | Focused automated evidence | Current verification status |
|---|---|---|---|
| Authentication and staff shell | `identity_access.authentication.KeycloakJWTAuthentication`; `GET /api/v1/identity/me`; `AuthProvider` | `backend/apps/identity_access/tests/test_authentication.py`; `backend/apps/integrations/tests/test_validate_matter.py`; `frontend/src/features/auth/AuthProvider.test.tsx`; `frontend/src/app/App.test.tsx` | Subject binding and inactive-identity fail-closed review passed; clean-checkout Ruff remains open |
| Scope separation and restricted access (FR-026, FR-027) | `identity_access.scope`; scoped ticket/file/report querysets | `identity_access/tests/test_scope.py`; `tickets/tests/test_scope_api.py`; `files/tests/test_views.py`; `reporting/tests/test_permissions.py` | Backend pytest/mypy, inactive-scope review, and permission audit passed; clean-checkout Ruff remains open |
| Assignment and work state (FR-033) | `PATCH /api/v1/tickets/{number}/work-state/`; `GET .../assignees/` | `tickets/tests/test_work_state_api.py`; `tickets/tests/test_permissions.py`; `tickets/tests/test_integrity_boundaries.py`; `frontend/src/features/tickets/OperationsPanel.test.tsx` | Locked scope revalidation and frontend gates passed; clean-checkout Ruff remains open |
| Workflow and role-gated transitions (FR-038, FR-040) | `POST /api/v1/tickets/{number}/transition/`; `tickets.workflow.available_transitions` | `tickets/tests/test_transition_api.py`; `tickets/tests/test_workflow_capabilities.py`; `tickets/tests/test_integrity_boundaries.py`; `frontend/src/features/tickets/TransitionActions.test.tsx` | Backend, live smoke, and frontend review passed; clean-checkout Ruff remains open |
| Resolution and reopen (FR-022, FR-023) | `tickets.services.transition_ticket`; chronological transition activity | `tickets/tests/test_services.py::test_resolve_reopen_and_close_record_lifecycle_and_canonical_events`; `tickets/tests/test_activity.py::test_reopen_activity_preserves_the_prior_resolution` | Backend pytest/mypy and live smoke passed; clean-checkout Ruff remains open |
| Queue, Kanban, URL filters (FR-039, FR-041, FR-043, FR-081, FR-082) | `GET /api/v1/tickets/`; `GET /api/v1/tickets/kanban/`; `QueuePage`; `KanbanPage` | `tickets/tests/test_api_collections.py`; `frontend/src/features/tickets/QueuePage.test.tsx`; `KanbanPage.test.tsx` | Domain-aware URL canonicalization and frontend gates passed; clean-checkout Ruff and rendered browser checks remain open |
| Cursor pagination (FR-047) | `identity_access.pagination.TicketCursorPagination` | `tickets/tests/test_api_collections.py::test_ticket_list_uses_cursor_envelope_without_losing_boundary_rows`, tied-row traversal tests, tampered-cursor test; `frontend/src/lib/collections.test.ts` | Backend pytest/mypy and frontend gates passed; clean-checkout Ruff remains open |
| Ticket card/detail fields (FR-014, FR-042) | `TicketListSerializer`; `TicketDetailSerializer`; `TicketDetailPage` | `tickets/tests/test_activity.py::test_ticket_detail_adds_workspace_context_without_removing_legacy_fields`; `frontend/src/features/tickets/TicketDetailPage.test.tsx` | Backend pytest/mypy and frontend gates passed; clean-checkout Ruff and rendered browser checks remain open |
| Internal notes and requester replies (FR-015, FR-016) | `GET/POST .../messages/`; `GET/POST .../notes/`; `GET .../activity/` | `tickets/tests/test_activity.py`; `tickets/tests/test_integrity_boundaries.py`; `frontend/src/features/tickets/ActivityTimeline.test.tsx`; `MessageComposer.test.tsx` | Locked content-mutation and frontend review passed; clean-checkout Ruff remains open |
| Plan 1 custody ledger and staff activity (FR-014, FR-015, FR-023, FR-054, FR-096, FR-097, FR-098) | `tickets.custody`; atomic `tickets.events.record_ticket_event`; lifecycle `tickets.services` and SLA writers; `tickets.activity`; immutable scoped `TicketCustodyEventAdmin`; transaction-gated `administration.retention`; migrations `0005`-`0008`; [ADR-0002](adr/0002-ticket-custody-hash-chain.md) | `tickets/tests/test_custody.py` (direct SQL rejection); `test_events.py`; `test_services.py`; `sla/tests/test_services.py`; `sla/tests/test_correctness.py`; `tickets/tests/test_activity.py` (custody sequence ties); `test_custody_migration.py` (authoritative creation, unresolved snapshots, actor attribution, rollback/cascade); `test_custody_admin.py`; `administration/tests/test_retention.py` (approved cascade) | Plan 1 ledger, lifecycle/SLA evidence, scoped immutable read access, audit-independent legacy snapshots, and transaction-gated retention cascade are implemented. Guarded assignment integration remains **Deferred** to Plan 2 Tasks 3-5, and production queue-routing integration remains **Deferred** to Plan 2 Task 5; this row does not claim those paths complete. |
| SLA state/display (FR-052-FR-059) | `sla.services`; `sla.serializers.serialize_sla_clocks`; ticket `sla_clocks` | `sla/tests/test_correctness.py`; `sla/tests/test_services.py`; `sla/tests/test_serializers.py`; `frontend/src/features/tickets/SlaClocks.test.tsx` | Corrected time-semantics review passed; clean-checkout Ruff, operator policy validation, and conditional earlier-`0004` reconciliation remain open |
| Attachments (FR-017, FR-093-FR-095) | `GET/POST /api/v1/tickets/{number}/attachments/`; `GET /api/v1/attachments/{id}/download/`; exact-version cleanup | `files/tests/test_policy.py`; `files/tests/test_services.py`; `files/tests/test_views.py`; `files/tests/test_events.py`; `frontend/src/features/tickets/AttachmentUploader.test.tsx` | Atomic intake, locked authority, and versioned-cleanup review passed; clean-checkout Ruff, browser checks, and production object-store/ClamAV exercise remain open |
| Ticket relationships and IT child (FR-019, FR-028-FR-030) | `POST .../it-child/`; `tickets.it_child`; scoped relationships | `tickets/tests/test_it_child.py`; `tickets/tests/test_it_child_integrity.py`; relationship tests in `tickets/tests/test_activity.py` | Locked parent/child integrity and live smoke passed; clean-checkout Ruff remains open |
| Dashboards and export (FR-083-FR-087) | `/api/v1/reports/dashboard/{domain}`; `/tickets.csv`; `/flow` | `reporting/tests/test_permissions.py`; live pilot-smoke dashboard assertions | Backend pytest/mypy and live smoke passed; clean-checkout Ruff and UAT reconciliation remain open |
| Audit and outbox (FR-096, FR-097) | `tickets.events.record_ticket_event`; `AuditEvent`; `OutboxEvent` | `tickets/tests/test_events.py`; event assertions in `test_services.py`, `test_transition_api.py`, and `test_work_state.py`; `files/tests/test_events.py` | Backend pytest/mypy passed; clean-checkout Ruff remains open and `GET /api/v1/audit/` is still a placeholder |
| Canonical errors and correlation | `identity_access.exception_handlers.problem_details_handler`; ticket/file action errors | `identity_access/tests/test_api_contracts.py`; error cases in `test_transition_api.py`, `test_work_state_api.py`, and `files/tests/test_views.py` | Backend pytest/mypy passed; clean-checkout Ruff and remaining legacy response-shape migration remain open |
| Staff ticket workspace | `frontend/src/features/tickets/TicketDetailPage.tsx` and its component panels | `TicketDetailPage.test.tsx`, `TransitionActions.test.tsx`, `OperationsPanel.test.tsx`, `ActivityTimeline.test.tsx`, `MessageComposer.test.tsx`, `SlaClocks.test.tsx`, `AttachmentUploader.test.tsx` | Frontend automatic gate passed; desktop/mobile browser verification remains open |
| Signed channel trust and delivery | Email/WhatsApp webhook verification, replay claims, account binding, ticket-scoped template send | `email_channel/tests/test_webhook_security.py`; `email_channel/tests/test_migrations.py`; `whatsapp/tests/test_views.py`; `whatsapp/tests/test_services.py`; `whatsapp/tests/test_migrations.py` | Independent channel review passed; provider approvals and P1 leased dispatch/retry plus API-retry deduplication remain open |
| Retention and legal holds (FR-098-FR-099) | `administration.retention`; `DisposalEvent`; retention side-effect worker | `administration/tests/test_retention.py`; `administration/tests/test_retention_tasks.py`; `files/tests/test_services.py` | Graph-atomic retention review passed; policy approval, restore rehearsal, and operator evidence remain open |

The route audit inventories declared metadata. It does not replace the scoped
queryset and service checks linked above.

## Functional scope index

| PRD IDs | Status | Owning modules and boundary |
|---|---|---|
| FR-001-FR-005, FR-008-FR-010 | Implemented | Ticket numbering/intake/acknowledgement and email idempotency in `tickets` and `email_channel`; public intake is Operational |
| FR-006 | Deferred | Phone normalization beyond current field validation |
| FR-007 | Implemented | `contacts` duplicate suggestions; no automatic merge |
| FR-011, FR-020 | Partial | Administrative/model support exists; complete merge UI is not delivered |
| FR-013-FR-017, FR-019, FR-022-FR-023 | Implemented | Ticket detail/activity, internal/requester separation, files, links, resolution, and reopen; exact pilot evidence linked above |
| FR-018 | Partial | Watcher model exists; user workflow is deferred |
| FR-024-FR-025 | Deferred | Tasks/checklists and approvals |
| FR-026-FR-033, FR-038-FR-043, FR-046-FR-047 | Implemented | Scope separation, IT-child, assignment, DB workflow, queue/Kanban, filters, card fields, and cursor pagination |
| FR-034-FR-037, FR-044-FR-045, FR-048-FR-049 | Deferred/Partial | Automation scaffolds or later scheduling/WIP/calendar/swimlane/advisory-lock experiences |
| FR-050-FR-055, FR-057-FR-059 | Implemented | Priority, transition history, SLA policy/instances/business time/pause/evaluation/display/breach fields |
| FR-056 | Partial | Reply-driven SLA behavior is not claimed as a verified complete workflow |
| FR-060-FR-065 | Partial/Deferred | OLA and complete notification/template/suppression operations are not pilot-complete |
| FR-066 | Implemented | Email delivery state/error capture |
| FR-067 | Partial | Signed/replay-protected WhatsApp ingress and ticket-scoped approved-template send exist; provider approval/credentials and leased idempotent dispatch/retry with API-retry deduplication remain required for production |
| FR-068-FR-069 | Deferred | SMS and quiet hours |
| FR-070-FR-073, FR-075 | Implemented | CSAT model/submit, requester token status/reply, message filtering, uniform invalid-token response |
| FR-074 | Partial | Expiring requester link exists; a full My Tickets portal is deferred |
| FR-076-FR-077, FR-079 | Implemented | Knowledge audiences, lifecycle/version, and published-audience filtering |
| FR-078, FR-080 | Partial | Suggestion hook/language field exist; complete UI and operator content are open |
| FR-081-FR-087 | Implemented | Search/filtering, scoped dashboards, flow metrics, and scoped streaming CSV |
| FR-088 | Deferred | Scheduled exports |
| FR-089-FR-092 | Partial | Admin registrations, audit hooks, automation, and health endpoints exist; complete configurability/production integration is not asserted |
| FR-093-FR-097, FR-100 | Implemented | Bounded atomic attachment intake, object-version ownership, ClamAV protocol, clean-only signed download, exact-version cleanup, audit/outbox, and log redaction paths |
| FR-098-FR-099 | Partial | Graph-atomic retention, legal-hold preservation, cleanup jobs, and truthful certificates exist; policy approval and full operator records workflow remain open |

## P0 acceptance trace

| # | Acceptance criterion | Repository evidence | Outstanding evidence |
|---:|---|---|---|
| 1 | Supported intake creates tickets | `public_intake`; email service; `scripts/pilot_foundation_smoke.py`; legacy smoke scripts | Backend pytest/mypy passed; clean-checkout Ruff and channel-provider UAT remain |
| 2 | Unique reference and acknowledgement | `tickets.services`; `tickets/tests/test_services.py::test_ticket_numbering_is_per_domain_and_sequential` | Backend pytest/mypy passed; clean-checkout Ruff remains |
| 3 | Operational/IT separation | Scope/queryset/report/file tests linked above; live pilot smoke | Backend pytest/mypy and live smoke passed; clean-checkout Ruff and role-based browser/UAT checks remain |
| 4 | Sanitized IT child | `tickets.it_child`; `tickets/tests/test_it_child.py` | Backend pytest/mypy passed; clean-checkout Ruff remains |
| 5 | IT cannot enumerate Operational data | Scope, reporting, file, and live-smoke `404`/`403` assertions | Backend pytest/mypy and live smoke passed; clean-checkout Ruff remains |
| 6 | Queue/Kanban share server permissions/transitions | `TicketViewSet.get_queryset`; server-derived transition codes; Queue/Kanban tests | Browser keyboard/drag verification |
| 7 | Keyboard and pointer workflows | `KanbanPage` sensors and component tests | Rendered keyboard and focus verification |
| 8 | SLA business-calendar cases | `sla/tests/test_correctness.py`, service tests, and serializer tests | Corrected SLA review passed; clean-checkout Ruff, operator policy validation, and conditional earlier-`0004` reconciliation remain |
| 9 | Email threading/idempotency | `email_channel/tests/test_services.py`; `email_channel/tests/test_webhook_security.py`; legacy M3 smoke | Signed/replay-protected channel review passed; clean-checkout Ruff and provider testing remain |
| 10 | Requester token resists enumeration | `contacts.views`; token hashing/uniform response code | Backend pytest/mypy passed; clean-checkout Ruff, penetration testing, and security sign-off remain |
| 11 | Public users do not receive internal records | Requester serializers/views; separate notes/activity authorization | Backend pytest/mypy passed; clean-checkout Ruff and browser security checks remain |
| 12 | Files are external and clean-only | File policy/service/view/event tests and AttachmentUploader tests | Atomic/versioned attachment review passed; clean-checkout Ruff and production object-store/ClamAV exercise remain |
| 13 | Material events are attributable | Ticket/file event tests and transition/work-state event assertions | Backend pytest/mypy passed; clean-checkout Ruff remains and `GET /api/v1/audit/` is still a placeholder |
| 14 | Dashboard scope reconciles to tickets | Reporting permission tests and live pilot smoke | Backend pytest/mypy and live smoke passed; clean-checkout Ruff and UAT reconciliation remain |
| 15 | Backup/restore demonstrated | Backup/restore/verification scripts exist | Fresh operator restore drill |
| 16 | Clean documented deployment | Docker/README assets exist | Fresh clean-environment deployment evidence |
| 17 | Critical logic/access controls automated | Focused suites linked in this document | Backend pytest and mypy passed; clean-checkout Ruff remains |
| 18 | No critical/high security finding | Threat model exists | External penetration test and security sign-off |
| 19 | Accessibility target | Semantic component tests and keyboard-capable UI code | Desktop/mobile browser accessibility verification |
| 20 | Configurable catalogue/workflow/SLA/templates | Models/admin registrations exist | Administrator UAT and configuration coverage |
| 21 | Runbooks delivered | Agent, pilot, incident, backup, and restore documentation/scripts | Operator rehearsal |
| 22 | Governance/go-live approvals | Templates and checklist exist | DPIA, TLS/secrets, provider, security, and owner approvals remain open |

The P0 acceptance set is not complete while the outstanding evidence column
contains required release or external gates.
