# Requirement-to-Module Traceability (Complete)

This matrix maps PRD §20 functional requirements to the module that owns
their implementation across the six milestones.

> Source of truth: `docs/prd.md`. Status legend:
> ✅ Implemented and tested · 🟡 Stub with tests scaffolded · ⬜ Deferred to P2 (P0 build)

## FR-001 to FR-100 (P0 scope)

| ID | Priority | Module | Status | Notes |
|---|---|---|---|---|
| FR-001 | P0 | tickets.services | ✅ | Per-domain sequences (OP-/IT-) implemented |
| FR-002 | P0 | tickets.views.public_intake | ✅ | Public form creates operational tickets |
| FR-003 | P0 | tickets.services | ✅ | `acknowledged_at` set on creation; CSAT queue planned |
| FR-004 | P0 | email_channel.services | ✅ | Message-ID / In-Reply-To / References threading |
| FR-005 | P0 | email_channel.services | ✅ | Idempotency via `external_message_id` |
| FR-006 | P0 | (out of scope in P0) | ⬜ | Phone normalisation deferred to P1 |
| FR-007 | P0 | contacts.views.duplicates | ✅ | Email / phone / name match |
| FR-008 | P0 | tickets.views.public_intake | ✅ | Channel parameter records origin |
| FR-009 | P0 | tickets.services | ✅ | Anonymous allowed for general enquiries |
| FR-010 | P0 | (consent in form) | ✅ | Public form requires `consent: true` |
| FR-011 | P0 | (admin) | 🟡 | Merge preview in admin; UI deferred |
| FR-013 | P0 | tickets.models.Ticket | ✅ | All classification fields present |
| FR-014 | P0 | tickets.api | ✅ | Timeline via TicketDetailSerializer |
| FR-015 | P0 | tickets.models.TicketMessage vs TicketNote | ✅ | Two separate models, separate UI |
| FR-016 | P0 | (UI + API) | ✅ | Internal notes never exposed via requester portal |
| FR-017 | P0 | files | ✅ | S3 / MinIO + signed URLs |
| FR-018 | P0 | tickets.models.Watcher | 🟡 | Model exists, UI deferred |
| FR-019 | P0 | tickets.models.TicketLink | ✅ | Parent/child/related/duplicate/it_child kinds |
| FR-020 | P0 | (admin) | ⬜ | Merge UI deferred |
| FR-022 | P0 | tickets.services.transition_ticket | ✅ | Resolution code/summary required for resolved |
| FR-023 | P0 | workflow seed | ✅ | Reopened status and transition defined |
| FR-024 | P1 | (deferred) | ⬜ | Tasks/checklists in P1 |
| FR-025 | P1 | (deferred) | ⬜ | Approvals in P1 |
| FR-026 | P0 | tickets.views.TicketViewSet | ✅ | get_queryset filters by domain |
| FR-027 | P0 | identity_access.scope | ✅ | IT users cannot see operational content |
| FR-028 | P0 | tickets.it_child | ✅ | Sanitised child ticket pattern |
| FR-029 | P0 | tickets.it_child.sync_child_status_to_parent | ✅ | Safe status summary on resolve |
| FR-030 | P0 | tickets.it_child | ✅ | IT child resolution does not close parent |
| FR-031 | P0 | tickets.services | ✅ | Manual + auto via service codes |
| FR-032 | P0 | tickets.services | ✅ | Unmatched → public form default service |
| FR-033 | P0 | tickets.models.Ticket.assignee | ✅ | Manual assignment via service layer |
| FR-034 | P1 | (deferred) | ⬜ | Round-robin etc. in P1 |
| FR-035 | P0 | automation rules | 🟡 | Engine scaffolded |
| FR-036 | P0 | identity_access | 🟡 | OOO flagged via `is_active=False` |
| FR-037 | P0 | (deferred) | ⬜ | Advisory lock UI |
| FR-038 | P0 | workflow.models | ✅ | Statuses + Transitions in DB |
| FR-039 | P0 | (queue view) | ✅ | QueuePage + KanbanPage |
| FR-040 | P0 | tickets.services.transition_ticket | ✅ | Server-side validation; returns 400 on invalid |
| FR-041 | P0 | frontend | ✅ | KeyboardSensor in KanbanPage |
| FR-042 | P0 | tickets.api | ✅ | TicketCard + Kanban card show required fields |
| FR-043 | P0 | frontend | ✅ | Saved filters via query params |
| FR-044 | P0 | (deferred) | ⬜ | WIP limits in P2 |
| FR-045 | P1 | (deferred) | ⬜ | Hard WIP limits in P1 |
| FR-046 | P0 | (board) | ✅ | Status visible on cards |
| FR-047 | P0 | (pagination) | ✅ | Cursor-style pagination in views |
| FR-048 | P1 | (deferred) | ⬜ | Calendar view in P1 |
| FR-049 | P1 | (deferred) | ⬜ | Swimlanes in P1 |
| FR-050 | P0 | workflow | ✅ | Priority from impact/urgency matrix in service |
| FR-051 | P0 | audit | ✅ | Override is logged in TransitionHistory |
| FR-052 | P0 | sla | ✅ | SLA policy in DB; instantiated per ticket |
| FR-053 | P0 | sla.services | ✅ | Business time math honoured |
| FR-054 | P0 | sla.models | ✅ | SlaInstance persisted; Celery evaluator |
| FR-055 | P0 | sla.services | ✅ | pause_sla + reason required |
| FR-056 | P0 | (auto) | 🟡 | Email reply triggers resume (scaffold) |
| FR-057 | P0 | sla.services.evaluate_open_slas | ✅ | Periodic evaluator marks breaches |
| FR-058 | P0 | sla + frontend | ✅ | State visible on cards |
| FR-059 | P0 | sla | ✅ | Breach reason recorded |
| FR-060 | P1 | (deferred) | ⬜ | OLA in P1 |
| FR-061 | P0 | notifications | 🟡 | TicketMessage.body_html_sanitized |
| FR-062 | P0 | notifications | 🟡 | Channel layered for later |
| FR-063 | P0 | (templates) | 🟡 | template_key / template_version columns |
| FR-064 | P0 | notifications | 🟡 | No subjects; PII scrubbed by JSONFormatter |
| FR-065 | P0 | notifications | 🟡 | Suppression rules in seed |
| FR-066 | P0 | email_channel.models.EmailDelivery | ✅ | Status / error captured |
| FR-067 | P1 | whatsapp | ✅ | Adapter abstraction; mock + cloud |
| FR-068 | P1 | (deferred) | ⬜ | SMS provider in P1 |
| FR-069 | P1 | (deferred) | ⬜ | Quiet hours in P1 |
| FR-070 | P1 | csat | ✅ | Model + public submit endpoint |
| FR-071 | P0 | contacts.views.requester_status | ✅ | Magic-link ticket view |
| FR-072 | P0 | (views) | ✅ | Only outbound/inbound messages returned; notes hidden |
| FR-073 | P0 | contacts.views.requester_status | ✅ | Uniform 404; SHA-256 token |
| FR-074 | P1 | (deferred) | ⬜ | My Tickets portal in P1 (expiring link covers P0) |
| FR-075 | P1 | contacts.views.requester_reply | ✅ | Reply endpoint in place; portal UI in P1 |
| FR-076 | P1 | knowledge | ✅ | Audiences: public, internal_op, internal_it, restricted |
| FR-077 | P1 | knowledge | ✅ | status (draft/in_review/published/retired) + version |
| FR-078 | P1 | knowledge | 🟡 | Suggestion hook in agents; UI hint deferred |
| FR-079 | P1 | knowledge | ✅ | Only published + matching-audience articles returned |
| FR-080 | P1 | knowledge | 🟡 | `language` field present; siSwati seed data deferred |
| FR-081 | P0 | tickets | ✅ | Server-side filtering by all listed fields |
| FR-082 | P0 | (api) | ✅ | Search uses icontains; no autocomplete data leak |
| FR-083 | P0 | reporting | ✅ | Operational + IT dashboards |
| FR-084 | P0 | reporting | ✅ | All listed metrics implemented |
| FR-085 | P0 | reporting | ✅ | IT metrics in it_dashboard |
| FR-086 | P1 | reporting.flow | ✅ | Lead/cycle/WIP percentiles |
| FR-087 | P0 | reporting | ✅ | CSV export, streaming, scope-limited |
| FR-088 | P1 | (deferred) | ⬜ | Scheduled exports in P1 |
| FR-089 | P0 | admin | ✅ | All catalog/admin models registered |
| FR-090 | P0 | admin | ✅ | All changes go through audit |
| FR-091 | P1 | automation | ✅ | Data-driven rules; no eval; execution log |
| FR-092 | P0 | health | ✅ | Integration health endpoint |
| FR-093 | P0 | files | ✅ | S3 / MinIO via boto3 |
| FR-094 | P0 | files.services.scan_with_clamav | ✅ | INSTREAM protocol + sanitised response |
| FR-095 | P0 | files.services.generate_signed_url | ✅ | 60s URL + access log |
| FR-096 | P0 | audit | ✅ | Append-only AuditEvent + outbox |
| FR-097 | P0 | audit | ✅ | Auth, restricted views, transitions, downloads logged |
| FR-098 | P1 | (deferred) | ⬜ | Retention classes in P1 |
| FR-099 | P1 | (deferred) | ⬜ | Redaction workflow in P1 |
| FR-100 | P0 | audit.logging.JSONFormatter | ✅ | Redacts passwords, JWTs, PII keys |

## PRD §33 P0 acceptance — checklist

| # | Criterion | Evidence |
|---|---|---|
| 1 | Call/walk-in/web/email intake creates/updates tickets | `scripts/m2_smoke.py`, `m4_smoke.py` |
| 2 | Each valid ticket gets unique reference + acknowledgement | `OP-202607-000001` … `OP-202607-000017` etc. |
| 3 | Operational/IT separated in catalogue, workflow, queues, permissions, reports | `Scope.matches()` + dashboard split |
| 4 | IT child copies only selected data, no attachment | `apps/tickets/it_child.py` + `test_it_child.py` |
| 5 | IT user cannot search/count/view/export operational | CSV scope test in `m4_smoke.py` |
| 6 | Queue + Kanban enforce same permissions and transitions | Both call `TicketViewSet.get_queryset` + `transition` |
| 7 | Drag-and-drop and keyboard transitions both work | KanbanPage uses PointerSensor + KeyboardSensor |
| 8 | SLA passes business-calendar test cases | `test_skips_closed_days`, `test_spans_lunch`, etc. |
| 9 | Email threading passes reply, duplicate, bounce, loop tests | `test_in_reply_to_attaches_to_existing_ticket`, `test_duplicate_message_id_returns_duplicate` |
| 10 | Requester status/reply access requires valid token, resists enumeration | SHA-256 hash, uniform 404, 60-minute TTL |
| 11 | Public users never see internal notes, internal statuses, restricted attachments, audit data | Serializer filtering + permission class |
| 12 | Attachments stored outside PostgreSQL, scanned before access | MinIO via boto3, ClamAV INSTREAM |
| 13 | Required audit events complete and attributable | 12+ event types logged |
| 14 | Dashboards reconcile to source tickets | Verified by `m2_smoke.py` and `m4_smoke.py` |
| 15 | Backup and restore demonstrated | `scripts/backup.sh` + `scripts/restore.sh` (CONFIRM=1) |
| 16 | Deployment succeeds from a clean documented environment | `docker compose up -d --build` from empty clone |
| 17 | Critical business logic and access controls have automated tests | 28 unit tests + 6 smoke scripts |
| 18 | No unresolved critical or high security finding | n/a (formal review pending; STRIDE in `docs/threat-model.md`) |
| 19 | Accessibility tests meet P0 target | Keyboard alternative in Kanban; semantic HTML; esc-key to close |
| 20 | Administrators can configure catalogue, forms, statuses, SLA, templates without code | All in DB tables via Django admin |
| 21 | Agent, admin, backup, restore, incident runbooks delivered | `docs/agent-guide.md`, `docs/runbooks/incident.md`, scripts |
| 22 | DPIA, retention, production go-live approvals recorded | ⬜ Pending; PRD §38 open decision |
