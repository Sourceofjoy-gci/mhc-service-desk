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

## Pilot foundation verification trace

| Concern / PRD requirements | Endpoint or module | Focused automated evidence | Current verification status |
|---|---|---|---|
| Authentication and staff shell | `identity_access.authentication.KeycloakJWTAuthentication`; `GET /api/v1/identity/me`; `AuthProvider` | `backend/apps/identity_access/tests/test_authentication.py`; `frontend/src/features/auth/AuthProvider.test.tsx`; `frontend/src/app/App.test.tsx` | Frontend gate passed; full backend gate open |
| Scope separation and restricted access (FR-026, FR-027) | `identity_access.scope`; scoped ticket/file/report querysets | `identity_access/tests/test_scope.py`; `tickets/tests/test_scope_api.py`; `files/tests/test_views.py`; `reporting/tests/test_permissions.py` | Permission audit passed; full backend gate open |
| Assignment and work state (FR-033) | `PATCH /api/v1/tickets/{number}/work-state/`; `GET .../assignees/` | `tickets/tests/test_work_state_api.py`; `tickets/tests/test_permissions.py`; `frontend/src/features/tickets/OperationsPanel.test.tsx` | Frontend gate passed; full backend gate open |
| Workflow and role-gated transitions (FR-038, FR-040) | `POST /api/v1/tickets/{number}/transition/`; `tickets.workflow.available_transitions` | `tickets/tests/test_transition_api.py`; `tickets/tests/test_workflow_capabilities.py`; `frontend/src/features/tickets/TransitionActions.test.tsx` | Live smoke and frontend gate passed; full backend gate open |
| Resolution and reopen (FR-022, FR-023) | `tickets.services.transition_ticket`; chronological transition activity | `tickets/tests/test_services.py::test_resolve_reopen_and_close_record_lifecycle_and_canonical_events`; `tickets/tests/test_activity.py::test_reopen_activity_preserves_the_prior_resolution` | Live smoke passed; full backend gate open |
| Queue, Kanban, URL filters (FR-039, FR-041, FR-043, FR-081, FR-082) | `GET /api/v1/tickets/`; `GET /api/v1/tickets/kanban/`; `QueuePage`; `KanbanPage` | `tickets/tests/test_api_collections.py`; `frontend/src/features/tickets/QueuePage.test.tsx`; `KanbanPage.test.tsx` | Frontend gate passed; rendered browser checks open |
| Cursor pagination (FR-047) | `identity_access.pagination.TicketCursorPagination` | `tickets/tests/test_api_collections.py::test_ticket_list_uses_cursor_envelope_without_losing_boundary_rows`, tied-row traversal tests, tampered-cursor test; `frontend/src/lib/collections.test.ts` | Frontend gate passed; full backend gate open |
| Ticket card/detail fields (FR-014, FR-042) | `TicketListSerializer`; `TicketDetailSerializer`; `TicketDetailPage` | `tickets/tests/test_activity.py::test_ticket_detail_adds_workspace_context_without_removing_legacy_fields`; `frontend/src/features/tickets/TicketDetailPage.test.tsx` | Frontend gate passed; rendered browser checks open |
| Internal notes and requester replies (FR-015, FR-016) | `GET/POST .../messages/`; `GET/POST .../notes/`; `GET .../activity/` | `tickets/tests/test_activity.py`; `frontend/src/features/tickets/ActivityTimeline.test.tsx`; `MessageComposer.test.tsx` | Live smoke and frontend gate passed; full backend gate open |
| SLA state/display (FR-052-FR-059) | `sla.services`; `sla.serializers.serialize_sla_clocks`; ticket `sla_clocks` | `sla/tests/test_services.py`; `sla/tests/test_serializers.py`; `frontend/src/features/tickets/SlaClocks.test.tsx` | Frontend gate passed; full backend gate open |
| Attachments (FR-017, FR-093-FR-095) | `GET/POST /api/v1/tickets/{number}/attachments/`; `GET /api/v1/attachments/{id}/download/` | `files/tests/test_views.py`; `files/tests/test_events.py`; `frontend/src/features/tickets/AttachmentUploader.test.tsx` | Frontend gate passed; full backend and browser gates open |
| Ticket relationships and IT child (FR-019, FR-028-FR-030) | `POST .../it-child/`; `tickets.it_child`; scoped relationships | `tickets/tests/test_it_child.py`; relationship tests in `tickets/tests/test_activity.py` | Live smoke passed; full backend gate open |
| Dashboards and export (FR-083-FR-087) | `/api/v1/reports/dashboard/{domain}`; `/tickets.csv`; `/flow` | `reporting/tests/test_permissions.py`; live pilot-smoke dashboard assertions | Live smoke passed; full backend gate open |
| Audit and outbox (FR-096, FR-097) | `tickets.events.record_ticket_event`; `AuditEvent`; `OutboxEvent` | `tickets/tests/test_events.py`; event assertions in `test_services.py`, `test_transition_api.py`, and `test_work_state.py`; `files/tests/test_events.py` | Focused contracts exist; full backend gate open |
| Canonical errors and correlation | `identity_access.exception_handlers.problem_details_handler`; ticket/file action errors | `identity_access/tests/test_api_contracts.py`; error cases in `test_transition_api.py`, `test_work_state_api.py`, and `files/tests/test_views.py` | Focused contracts exist; full backend gate open |
| Staff ticket workspace | `frontend/src/features/tickets/TicketDetailPage.tsx` and its component panels | `TicketDetailPage.test.tsx`, `TransitionActions.test.tsx`, `OperationsPanel.test.tsx`, `ActivityTimeline.test.tsx`, `MessageComposer.test.tsx`, `SlaClocks.test.tsx`, `AttachmentUploader.test.tsx` | Frontend automatic gate passed; desktop/mobile browser verification open |

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
| FR-067 | Partial | WhatsApp mock/cloud adapter exists; production provider approval and credentials remain external |
| FR-068-FR-069 | Deferred | SMS and quiet hours |
| FR-070-FR-073, FR-075 | Implemented | CSAT model/submit, requester token status/reply, message filtering, uniform invalid-token response |
| FR-074 | Partial | Expiring requester link exists; a full My Tickets portal is deferred |
| FR-076-FR-077, FR-079 | Implemented | Knowledge audiences, lifecycle/version, and published-audience filtering |
| FR-078, FR-080 | Partial | Suggestion hook/language field exist; complete UI and operator content are open |
| FR-081-FR-087 | Implemented | Search/filtering, scoped dashboards, flow metrics, and scoped streaming CSV |
| FR-088 | Deferred | Scheduled exports |
| FR-089-FR-092 | Partial | Admin registrations, audit hooks, automation, and health endpoints exist; complete configurability/production integration is not asserted |
| FR-093-FR-097, FR-100 | Implemented | Object storage, ClamAV protocol, clean-only signed download, audit/outbox, and log redaction paths |
| FR-098-FR-099 | Partial/Deferred | Retention assets exist, but the full redaction/records workflow is not claimed complete |

## P0 acceptance trace

| # | Acceptance criterion | Repository evidence | Outstanding evidence |
|---:|---|---|---|
| 1 | Supported intake creates tickets | `public_intake`; email service; `scripts/pilot_foundation_smoke.py`; legacy smoke scripts | Full backend gate and channel-provider UAT |
| 2 | Unique reference and acknowledgement | `tickets.services`; `tickets/tests/test_services.py::test_ticket_numbering_is_per_domain_and_sequential` | Full backend gate |
| 3 | Operational/IT separation | Scope/queryset/report/file tests linked above; live pilot smoke | Full backend gate and role-based browser/UAT checks |
| 4 | Sanitized IT child | `tickets.it_child`; `tickets/tests/test_it_child.py` | Full backend gate |
| 5 | IT cannot enumerate Operational data | Scope, reporting, file, and live-smoke `404`/`403` assertions | Full backend gate |
| 6 | Queue/Kanban share server permissions/transitions | `TicketViewSet.get_queryset`; server-derived transition codes; Queue/Kanban tests | Browser keyboard/drag verification |
| 7 | Keyboard and pointer workflows | `KanbanPage` sensors and component tests | Rendered keyboard and focus verification |
| 8 | SLA business-calendar cases | `sla/tests/test_services.py` and serializer tests | Full backend gate and operator policy validation |
| 9 | Email threading/idempotency | `email_channel/tests/test_services.py`; legacy M3 smoke | Provider test and full backend gate |
| 10 | Requester token resists enumeration | `contacts.views`; token hashing/uniform response code | Full backend/security gate |
| 11 | Public users do not receive internal records | Requester serializers/views; separate notes/activity authorization | Full backend and browser security checks |
| 12 | Files are external and clean-only | File service/view tests and AttachmentUploader tests | Full backend gate and production object-store/ClamAV exercise |
| 13 | Material events are attributable | Ticket/file event tests and transition/work-state event assertions | Full backend gate; `GET /api/v1/audit/` remains a placeholder |
| 14 | Dashboard scope reconciles to tickets | Reporting permission tests and live pilot smoke | Full backend gate and UAT reconciliation |
| 15 | Backup/restore demonstrated | Backup/restore/verification scripts exist | Fresh operator restore drill |
| 16 | Clean documented deployment | Docker/README assets exist | Fresh clean-environment deployment evidence |
| 17 | Critical logic/access controls automated | Focused suites linked in this document | Full backend pytest, Ruff, and mypy must pass |
| 18 | No critical/high security finding | Threat model exists | External penetration test and security sign-off |
| 19 | Accessibility target | Semantic component tests and keyboard-capable UI code | Desktop/mobile browser accessibility verification |
| 20 | Configurable catalogue/workflow/SLA/templates | Models/admin registrations exist | Administrator UAT and configuration coverage |
| 21 | Runbooks delivered | Agent, pilot, incident, backup, and restore documentation/scripts | Operator rehearsal |
| 22 | Governance/go-live approvals | Templates and checklist exist | DPIA, TLS/secrets, provider, security, and owner approvals remain open |

The P0 acceptance set is not complete while the outstanding evidence column
contains required release or external gates.
