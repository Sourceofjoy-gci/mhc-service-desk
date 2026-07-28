# Pilot readiness

This is an evergreen status page. Exact test totals, ticket identifiers,
timestamps, command lines, and build warnings belong in the dated
[`verification/pilot-foundation-2026-07-27.md`](verification/pilot-foundation-2026-07-27.md)
record.

Status terms are intentionally separate:

- **Implemented** means the capability exists in the repository.
- **Automatically verified** means a named gate passed in the latest dated
  evidence.
- **Manual verification required** means rendered or operational behavior has
  not been demonstrated automatically.
- **External sign-off required** means the repository cannot supply the
  approval.

Implemented is not synonymous with verified, and neither is synonymous with
pilot-ready.

## Implemented

### Runtime and security

- [x] Environment-specific Django settings, production fail-fast secret
  validation, secure cookie/HSTS settings, Gunicorn, production/dev images,
  Nginx configuration, and readiness/liveness endpoints are present.
- [x] Keycloak bearer authentication and durable group snapshots are wired;
  development bearer tokens are conditional on `DEBUG=True` and are rejected
  when `DEBUG=False`.
- [x] Ticket authority supports domain, office, service, queue, restricted-
  only grants, persisted role precedence, and read-only auditors.
- [x] The shared DRF exception handler and covered transition, work-state, and
  attachment validation paths return `code`, `detail`, `fields`, and
  `correlation_id`.
- [x] The ticket list cursor returns `next`, `previous`, and `results`; focused
  tests cover tied-row traversal and malformed cursors.
- [ ] Manual error responses on IT-child, public-intake, requester/CSAT, and
  integration paths have not all been migrated to the standardized envelope.
- [x] Ticket mutations write audit and outbox records transactionally on the
  tested service paths.
- [x] WhatsApp template listing and outbound sending require an authenticated
  identity; auditors cannot send. The inbound provider webhook remains
  public.
- [x] Inbound email HTML is sanitized with Bleach 6.4.0, with a service-level
  regression covering invisible URI-scheme characters and `formaction`.

### Pilot workflow and staff experience

- [x] Public intake and scoped Operational/IT queues are implemented.
- [x] The ticket workspace includes server-approved transitions, assignment
  and work-state controls, activity, replies/internal notes, SLA clocks,
  relationships, requester context, and attachment scan states.
- [x] Work-state and transition requests use optimistic `updated_at`; a stale
  mutation returns `409 stale_ticket` and the UI offers an explicit reload.
- [x] Resolve/reopen behavior preserves history while clearing active
  resolution fields on reopen.
- [x] Attachments are stored outside PostgreSQL, scanned, and downloadable
  through a short-lived signed URL only when scan status is clean.
- [x] Operational/IT dashboards, scoped CSV export, and flow reporting exist.
- [x] The repeatable pilot smoke creates fresh development records and checks
  lifecycle, activity, IT-child, dashboard denial, and out-of-domain hiding.

### Operations and governance assets

- [x] Retention/legal-hold, SAR export, backup/restore scripts, structured
  logging, correlation IDs, monitoring configuration, and operational runbooks
  are present in the repository.
- [x] The threat model, permission matrix, roadmap, traceability, pilot
  runbook, incident runbook, and agent guide are present.

These implementation statements do not assert that every legacy module or
operational asset passed the current release gate.

## Automatically verified

Latest evidence shows:

- [x] Migration drift check passed.
- [x] Unapplied-migration check passed.
- [x] Django system check passed.
- [x] Permission route audit passed and included the required lifecycle,
  attachment, and reporting route families.
- [x] Full backend pytest passed in a freshly built current-source image.
- [x] Strict backend mypy passed across the configured application and settings
  source set.
- [x] The inbound-email sanitizer security regression passed through the
  persisted service path.
- [x] Ruff passed against the explicitly authorized current dirty worktree.
- [ ] Reproducible clean-checkout Ruff remains open: its fixes exist only in
  preserved, unstaged user-owned hunks. Exact findings are in the dated record.
- [ ] Final current-source frontend tests, TypeScript, ESLint, and production
  build rerun against the completed checkout is pending. An earlier run passed
  all four gates and recorded non-fatal font and bundle-size warnings.
- [ ] Final live Operational/IT pilot smoke rerun is pending. An earlier run
  passed with fresh development tickets.

The open items keep the automatic release gate open. See the dated evidence
for exact totals and the dirty-worktree qualification; do not copy fixed totals
into this page.

## Manual verification required

- [ ] Desktop browser verification for public and protected shells, ticket
  queue/workspace, Operational and IT dashboards, and all controlled states.
- [ ] Mobile browser verification for layout order, overflow, dialogs, labels,
  keyboard focus, and unavailable-action behavior.
- [ ] User acceptance testing with Operational agents, IT agents, supervisors,
  auditors, security responders, and administrators.
- [ ] Restore drill against operator-owned backup media and recovery targets.
- [ ] Representative load/concurrency verification for response-time and
  session-volume objectives. Development health latency and configuration
  values are not substitutes for a load test.

A supported browser-verification tool was unavailable for the latest run, so
browser verification is open rather than passed.

## External sign-off required

- [ ] Signed DPIA/data-protection approval before real personal data is loaded.
- [ ] Production TLS certificates issued and installed by the operator.
- [ ] Production secret manager connected; development `.env` is not an
  acceptable production source.
- [ ] Penetration test completed and critical/high findings resolved or
  formally accepted.
- [ ] Production monitoring destinations and escalation contacts approved.
- [ ] Meta WhatsApp account/templates and e-Estate integration approvals,
  contracts, and credentials supplied by their owners.
- [ ] Product, technical, security, operations, records, and data-protection
  owners sign the pilot decision.

## Deliberately deferred product scope

- Native mobile application and biometric identity.
- Real-time WebSocket presence.
- Kubernetes multi-region HA and a separate Metabase reporting replica.
- SMS, quiet hours, watcher UI, merge UI, hard WIP limits, and scheduled
  exports where still marked deferred in traceability.
- Operator-supplied siSwati content.

Deferred scope is not an excuse to defer a release gate or external approval
listed above.

## Decision

**Pilot readiness is open.** The application must not be labelled pilot-ready
until clean-checkout Ruff, the final frontend gates, the final live smoke,
required browser checks, and owner-controlled prerequisites all have passing
evidence.

| Role | Name | Date | Decision/signature |
|---|---|---|---|
| Product owner | | | |
| Technical lead | | | |
| Security | | | |
| Data protection | | | |
| Operations | | | |
| Records | | | |
