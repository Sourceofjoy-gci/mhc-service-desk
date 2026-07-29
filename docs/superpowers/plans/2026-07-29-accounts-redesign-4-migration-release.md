# Accounts Redesign 4: Migration and Release Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate only manager-approved legacy financial enquiries, prove the complete role/workflow behavior end to end, update operational guidance, and produce a release-verification record.

**Architecture:** Migration is manifest-driven, deterministic, dry-run-first, and all-or-nothing. It updates the existing ticket aggregate in place so content and history remain intact, records a manifest hash in the audit/outbox event, and never selects tickets from free text. Release verification combines the full automated quality gate, a role-based API smoke, Keycloak configuration checks, and browser workflow checks.

**Tech Stack:** Django management commands/transactions, pytest/pytest-django, requests-based API smoke, Keycloak realm JSON, Docker Compose, React/Vitest/TypeScript quality gate, Markdown runbooks.

## Global Constraints

- Complete Plans 1, 2, and 3 before this plan.
- Preserve unrelated pre-existing working-tree changes; stage only task-owned files or hunks after reviewing `git diff --cached`.
- Existing tickets never move because of title, description, message, note, attachment, or keyword matching.
- A ticket moves only when its exact number and approved destination appear in an explicit manifest.
- Dry-run performs zero writes. Apply requires a manager subject, approval timestamp, and a manifest whose SHA-256 hash is recorded.
- Manifest application is all-or-nothing; one invalid row rolls back all ticket changes.
- Migration preserves ticket ID/number, messages, notes, attachments, links, activity, existing SLA history, requester, and audit history.
- Migration never marks financial verification successful without an approved structured source.
- Production Accounts intake remains disabled until Keycloak roles/groups, catalogue routes, SLA targets, and representative access tests pass.
- Do not place credentials, tokens, private data, financial references, or transient command output in committed documentation.
- Follow test-driven development and observe each focused test fail before implementation.

## File Structure

- `backend/apps/tickets/financial_migration.py`: pure manifest parsing/validation, status mapping, and transactional apply service.
- `backend/apps/tickets/management/commands/migrate_financial_tickets.py`: command-line adapter only.
- `backend/scripts/accounts_workflow_smoke.py`: complete API role/workflow smoke using environment-supplied authentication.
- `scripts/verify_accounts_keycloak.py`: offline realm-contract validation without credentials.
- `docs/verification/accounts-redesign-2026-07-29.md`: actual final evidence and exceptions, created only after commands run.

---

### Task 1: Build a deterministic dry-run and approved migration command

**Files:**
- Create: `backend/apps/tickets/financial_migration.py`
- Create: `backend/apps/tickets/management/__init__.py`
- Create: `backend/apps/tickets/management/commands/__init__.py`
- Create: `backend/apps/tickets/management/commands/migrate_financial_tickets.py`
- Create: `backend/apps/tickets/tests/test_financial_migration.py`
- Create: `backend/apps/tickets/tests/test_financial_migration_command.py`

**Interfaces:**
- Produces: `MigrationManifest`, `MigrationRow`, and `MigrationResult` immutable data types.
- Produces: `load_manifest(raw: bytes) -> MigrationManifest`.
- Consumes: `map_status_to_domain(code, "accounts", assignee_eligible=...)` from Plan 2.
- Produces: `preview_financial_migration(manifest) -> list[MigrationResult]` with zero writes.
- Produces: `apply_financial_migration(manifest, *, actor_subject) -> list[MigrationResult]` in one transaction.
- Produces command: `python manage.py migrate_financial_tickets --manifest <path> --dry-run --output <path>` or `--apply --approved-by <subject>`.

- [ ] **Step 1: Write failing manifest parser tests**

Use this exact schema:

```json
{
  "version": 1,
  "approved_by": "manager-keycloak-subject",
  "approved_at": "2026-07-29T12:00:00Z",
  "tickets": [
    {
      "ticket_number": "OP-202607-000001",
      "service_code": "ACC-PAY",
      "request_type_code": "PAY-STATUS",
      "financial_enquiry_category": "payment",
      "financial_reference": ""
    }
  ]
}
```

Tests reject unknown top-level/row keys, duplicate ticket numbers, a version other than 1, blank/invalid approval metadata for apply, non-Accounts destinations, invalid category, and a Request Type outside the Service. Unknown fields fail closed; they are not ignored.

- [ ] **Step 2: Write failing dry-run/no-write and apply tests**

Add exact assertions:

```python
def test_preview_reports_change_without_writes(legacy_financial_ticket, manifest):
    before = model_snapshot(legacy_financial_ticket)
    result = preview_financial_migration(manifest)
    legacy_financial_ticket.refresh_from_db()
    assert model_snapshot(legacy_financial_ticket) == before
    assert result[0].outcome == "ready"
    assert result[0].destination_domain == "accounts"


def test_apply_preserves_related_history_and_clears_wrong_domain_owner(
    legacy_financial_ticket,
    manifest,
):
    related_ids = snapshot_related_ids(legacy_financial_ticket)
    result = apply_financial_migration(
        manifest,
        actor_subject=manifest.approved_by,
    )
    legacy_financial_ticket.refresh_from_db()
    assert legacy_financial_ticket.domain == "accounts"
    assert legacy_financial_ticket.assignee is None
    assert snapshot_related_ids(legacy_financial_ticket) == related_ids
    event = OutboxEvent.objects.get(
        aggregate_id=str(legacy_financial_ticket.id),
        event_type="ticket.migrated_to_accounts",
    )
    assert event.payload["metadata"]["manifest_sha256"] == manifest.sha256
    assert result[0].outcome == "migrated"
```

Create rollback-on-second-row-failure, idempotent rerun, ambiguous-not-in-manifest unchanged, and no-verification-invention tests.

- [ ] **Step 3: Run migration tests in the red state**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_financial_migration.py apps/tickets/tests/test_financial_migration_command.py -q
```

Expected: FAIL because the migration module and command do not exist.

- [ ] **Step 4: Implement strict manifest data types and parser**

Define:

```python
@dataclass(frozen=True)
class MigrationRow:
    ticket_number: str
    service_code: str
    request_type_code: str
    financial_enquiry_category: str
    financial_reference: str = ""


@dataclass(frozen=True)
class MigrationManifest:
    version: int
    approved_by: str
    approved_at: datetime | None
    tickets: tuple[MigrationRow, ...]
    sha256: str


@dataclass(frozen=True)
class MigrationResult:
    ticket_number: str
    outcome: str
    source_domain: str
    destination_domain: str
    source_status: str
    destination_status: str
    assignee_cleared: bool
    warnings: tuple[str, ...] = ()
```

Calculate SHA-256 from the original manifest bytes after strict JSON decoding. Parse a supplied ISO timestamp as an aware UTC datetime. Allow blank approval fields only for dry-run construction; apply validation requires both values. Validate with explicit key sets and raise `ManifestValidationError(fields)` carrying row-indexed errors.

- [ ] **Step 5: Implement exact semantic status mapping**

Test the shared `map_status_to_domain` against this exact table; do not duplicate it in the migration module:

```python
EXPECTED_STATUS_MAP = {
    "new": "triage",
    "triage": "triage",
    "assigned": "assigned",
    "in_progress": "in_progress",
    "diagnosing": "in_progress",
    "reopened": "in_progress",
    "waiting_requester": "waiting_requester",
    "waiting_user": "waiting_requester",
    "waiting_internal": "waiting_internal_finance",
    "waiting_it": "waiting_internal_finance",
    "waiting_vendor": "waiting_internal_finance",
    "waiting_change": "waiting_internal_finance",
    "quality_review": "supervisor_review",
    "validation": "supervisor_review",
    "resolved": "resolved",
    "closed": "closed",
    "cancelled": "cancelled",
    "rejected": "cancelled",
    "spam": "cancelled",
    "duplicate": "duplicate",
}
```

When source is Assigned and the assignee is ineligible for Accounts, map to Triage and clear the assignee. An unknown source status rejects the whole manifest; it is never guessed.

- [ ] **Step 6: Implement preview and all-or-nothing apply**

Both paths validate every ticket number, Operational source domain, destination route, category, and status mapping in sorted ticket-number order. Apply wraps all rows in one `transaction.atomic`, locks every ticket with `select_for_update`, updates the same Ticket rows, raises confidentiality from Normal to Sensitive while preserving Restricted, creates TransitionHistory only when status changes, and calls:

```python
record_ticket_event(
    ticket=ticket,
    actor_subject=actor_subject,
    action="ticket.migrated_to_accounts",
    before=before,
    after=after,
    metadata={
        "manifest_sha256": manifest.sha256,
        "approved_at": manifest.approved_at.isoformat(),
        "reason": "Approved legacy financial enquiry migration",
    },
)
```

Build the event's before/after dictionaries with route, status, assignee, confidentiality, category, and a `financial_reference_present` boolean; do not copy the reference value into audit/outbox payloads. Leave existing SLA instances untouched so SLA history and running clocks are preserved. Set verification to `pending` only when the destination Request Type requires verification by its configured policy; otherwise use `not_required`. Never set `verified`.

Idempotency checks an existing `ticket.migrated_to_accounts` AuditEvent with the same ticket and manifest hash and returns `already_migrated` without another event.

- [ ] **Step 7: Implement command behavior**

Require exactly one of `--dry-run` and `--apply`. Dry-run may accept blank approval metadata but still validates rows; apply requires `--approved-by` equal to manifest `approved_by`. Write a deterministic JSON result sorted by ticket number to `--output` or stdout. On any validation/apply failure, exit nonzero and write no ticket changes.

The command must never log descriptions, messages, notes, financial references, or requester information.

- [ ] **Step 8: Verify migration and commit**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_financial_migration.py apps/tickets/tests/test_financial_migration_command.py -q
ruff check apps/tickets/financial_migration.py apps/tickets/management/commands/migrate_financial_tickets.py apps/tickets/tests/test_financial_migration.py apps/tickets/tests/test_financial_migration_command.py
```

Expected: all commands exit 0; dry-run writes nothing; apply is atomic and idempotent.

Commit:

```powershell
git add backend/apps/tickets/financial_migration.py backend/apps/tickets/management/__init__.py backend/apps/tickets/management/commands/__init__.py backend/apps/tickets/management/commands/migrate_financial_tickets.py backend/apps/tickets/tests/test_financial_migration.py backend/apps/tickets/tests/test_financial_migration_command.py
git diff --cached --check
git commit -m "feat(accounts): add approved ticket migration"
```

---

### Task 2: Prove the complete role/domain/confidentiality matrix and workflow smoke

**Files:**
- Create: `backend/apps/tickets/tests/test_role_domain_confidentiality_matrix.py`
- Create: `backend/apps/tickets/tests/test_accounts_end_to_end.py`
- Create: `backend/scripts/accounts_workflow_smoke.py`
- Modify: `Makefile`
- Modify: `backend/apps/health/tests/test_pilot_smoke_contract.py`

**Interfaces:**
- Produces test matrix across 11 roles, 3 domains, and 3 confidentiality levels.
- Produces smoke command: `make accounts-smoke`.
- Consumes environment variables `ACCOUNTS_SMOKE_BASE_URL` and optional bearer tokens; development tokens are used only when backend `DEBUG=True`.

- [ ] **Step 1: Write the exhaustive read/mutation matrix**

Parameterise these identities:

```python
ROLE_GROUPS = {
    "staff": ["staff"],
    "ops_agent": ["ops-agents"],
    "ops_supervisor": ["ops-supervisors"],
    "it_agent": ["it-agents"],
    "it_lead": ["it-leads"],
    "accounts_agent": ["accounts-agents"],
    "accounts_supervisor": ["accounts-supervisors"],
    "manager": ["service-desk-managers"],
    "security": ["security-responders"],
    "auditor": ["auditors"],
    "system_admin": ["system-admins"],
}
```

For every role/domain/confidentiality triple assert list visibility, detail visibility, message/note/upload, transition, self-assignment, assignment, reroute, dashboard, manager overview, search, and CSV export. Encode expected results in named helper functions (`can_read_case`, `can_action_case`, `can_assign_case`, `can_reroute_case`) rather than copying production functions, so the test remains an independent policy oracle.

Add composed-role rows for manager+Accounts agent and manager+Accounts supervisor. Assert manager-only excludes Restricted and cannot action; auditor reads all and mutates none; system admin reads/mutates none.

- [ ] **Step 2: Write the end-to-end backend test**

Exercise in one database test:

1. create a public Accounts payment-status enquiry from an Accounts catalogue pair;
2. assert Sensitive and unassigned;
3. move New to Triage with an Accounts supervisor;
4. assign through a manager to an Accounts agent;
5. assert assignment status/history/audit/outbox;
6. assert manager cannot add a note;
7. assert agent sees it in My Work and moves to In Progress;
8. update verification context without credentials;
9. assert resolution without no-transaction affirmation fails;
10. resolve with code, summary, affirmation, and external finance reference;
11. close the ticket; and
12. deliver and read the assignment notification.

Also assert an Operational agent and technical administrator receive 404 for the ticket and a manager receives 404 after it becomes Restricted without a second role.

- [ ] **Step 3: Run policy tests in the red state and close gaps**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_role_domain_confidentiality_matrix.py apps/tickets/tests/test_accounts_end_to_end.py -q
```

Expected: any mismatch identifies a concrete missing permission or workflow behavior. Fix production code in the owning Plan 1/2 file, add the regression to that module's focused test, and rerun both focused and matrix tests before proceeding.

- [ ] **Step 4: Create a requests-based deployment smoke**

Implement helpers matching the existing pilot smoke's timeout and common error checks. The smoke must:

- authenticate Accounts agent, Accounts supervisor, manager, Operational agent, and System Administrator using environment-provided tokens or explicit debug tokens;
- create one uniquely suffixed Accounts enquiry;
- verify role isolation and manager monitoring;
- assign, action, resolve, and deliver notification as in Step 2;
- verify `stale_ticket` with an old timestamp; and
- print only ticket number, HTTP status, and pass/fail labels.

Never print tokens, requester details, descriptions, financial references, or response headers containing authentication data.

Add:

```make
accounts-smoke:
	docker compose exec backend python /app/scripts/accounts_workflow_smoke.py
```

and include `accounts-smoke` in `.PHONY` and help output.

- [ ] **Step 5: Verify matrix/smoke contract and commit**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_role_domain_confidentiality_matrix.py apps/tickets/tests/test_accounts_end_to_end.py apps/health/tests/test_pilot_smoke_contract.py -q
ruff check apps/tickets/tests/test_role_domain_confidentiality_matrix.py apps/tickets/tests/test_accounts_end_to_end.py scripts/accounts_workflow_smoke.py
```

Expected: all commands exit 0.

Commit:

```powershell
git add backend/apps/tickets/tests/test_role_domain_confidentiality_matrix.py backend/apps/tickets/tests/test_accounts_end_to_end.py backend/scripts/accounts_workflow_smoke.py Makefile backend/apps/health/tests/test_pilot_smoke_contract.py
git diff --cached --check
git commit -m "test(accounts): verify role workflow end to end"
```

---

### Task 3: Add Keycloak contract validation, observability, and operating guides

**Files:**
- Create: `scripts/verify_accounts_keycloak.py`
- Create: `backend/apps/health/tests/test_accounts_observability.py`
- Modify: `backend/apps/tickets/assignment.py`
- Modify: `backend/apps/tickets/routing.py`
- Modify: `backend/apps/notifications/tasks.py`
- Modify: `docs/basic-application-guide.md`
- Modify: `docs/agent-guide.md`
- Modify: `docs/permission-matrix.md`
- Modify: `docs/deployment.md`
- Modify: `docs/pilot-runbook.md`
- Modify: `docs/architecture.md`
- Modify: `docs/traceability.md`

**Interfaces:**
- Produces: offline command `python scripts/verify_accounts_keycloak.py infrastructure/keycloak/realm-mhc.json`.
- Produces: stable structured-log event names for assignment, routing, unresolved route, notification retry, and migration.
- Produces: updated staff/admin operating documentation matching implemented routes and roles.

- [ ] **Step 1: Write failing Keycloak contract tests in the validator**

The script exits 0 only when:

- realm is `mhc`;
- client `mhc-frontend` exists with the expected local redirect/web origins;
- group-membership mapper emits `groups` with `full.path=false`;
- realm roles `staff`, `agent-accounts`, `supervisor-accounts`, and `service-desk-manager` exist;
- groups `accounts-agents`, `accounts-supervisors`, and `service-desk-managers` exist with the exact role pairs from the design; and
- `system-admins` has `staff` and `admin` but no domain role.

The script emits one concise error per failed invariant and never reads `.env` or credentials.

- [ ] **Step 2: Add structured observability tests**

Use `caplog` to assert stable event names and safe fields:

```python
assert record.message == "ticket_assignment_changed"
assert record.ticket_number == ticket.number
assert record.domain == "accounts"
assert record.assignment_kind == "reassigned"
assert not hasattr(record, "financial_reference")
assert not hasattr(record, "description")
```

Cover `ticket_routing_changed`, `intake_routing_exception_created`, `assignment_notification_retry`, and `financial_migration_applied`. Logs may contain IDs, domains, reason codes, outcome, and retry counts; never requester content, ticket description, message/note bodies, financial references, or tokens.

- [ ] **Step 3: Run validator/observability tests in the red state**

Run:

```powershell
python scripts/verify_accounts_keycloak.py infrastructure/keycloak/realm-mhc.json
Set-Location backend
pytest apps/health/tests/test_accounts_observability.py -q
```

Expected: validator or tests fail until all contract checks and log events exist.

- [ ] **Step 4: Update the basic application and agent guides**

Update `basic-application-guide.md` with:

- all baseline, domain, manager, security, auditor, and technical roles;
- Accounts as a third domain;
- My Work, Accounts queue/Kanban/dashboard, Manager Overview, routing exceptions, and notification functions;
- the approved Accounts status workflow;
- exact assignment/rerouting boundaries; and
- the enquiry-only/no-transaction warning.

Update `agent-guide.md` with separate short procedures for self-assignment, manager assignment, rerouting, waiting for requester, financial verification, internal finance dependency, supervisor review, resolution, closure/reopening, and stale-update recovery.

- [ ] **Step 5: Update security/deployment/runbook documentation**

In `permission-matrix.md`, replace System Administrator business authority and add the complete three-domain/confidentiality matrix. In `deployment.md` and `pilot-runbook.md`, document this order:

1. backup and confirm restore point;
2. deploy additive migrations/backend;
3. import/update Keycloak roles and groups;
4. run offline Keycloak validator and inspect representative token claims;
5. seed/confirm Accounts catalogue, mailbox routes, offices/queues, and SLA targets;
6. deploy frontend;
7. run automated and smoke gates;
8. enable Accounts intake;
9. run migration dry-run, obtain manager-approved manifest, and apply; and
10. monitor routing exceptions, unassigned age, SLA risk, retry backlog, and denied access.

Document rollback as disabling Accounts intake and frontend navigation while retaining additive schema/data and audit history; do not reverse migrated tickets automatically.

Update architecture/traceability with capability registry, catalogue routing, explicit assignment/rerouting services, notification outbox consumer, migration command, and exact test files.

- [ ] **Step 6: Verify documentation and commit**

Run:

```powershell
python scripts/verify_accounts_keycloak.py infrastructure/keycloak/realm-mhc.json
Set-Location backend
pytest apps/health/tests/test_accounts_observability.py -q
ruff check apps/tickets/assignment.py apps/tickets/routing.py apps/notifications/tasks.py ../scripts/verify_accounts_keycloak.py
Set-Location ..
rg -n "system-admins|service-desk-managers|accounts-agents|accounts-supervisors|no financial transaction|Pending Financial Verification" docs
```

Expected: validator/tests/lint exit 0 and the search shows the new role/workflow language in each operating guide.

Commit:

```powershell
git add scripts/verify_accounts_keycloak.py backend/apps/health/tests/test_accounts_observability.py backend/apps/tickets/assignment.py backend/apps/tickets/routing.py backend/apps/notifications/tasks.py docs/basic-application-guide.md docs/agent-guide.md docs/permission-matrix.md docs/deployment.md docs/pilot-runbook.md docs/architecture.md docs/traceability.md
git diff --cached --check
git commit -m "docs(accounts): add operating and access guidance"
```

---

### Task 4: Run release gates and record evidence

**Files:**
- Create: `docs/verification/accounts-redesign-2026-07-29.md`
- Modify only if a gate exposes a defect: the owning production file and its focused regression test

**Interfaces:**
- Produces: one evidence record with commit SHA, environment versions, commands, exit results, smoke ticket numbers only, browser scenarios, and explicitly accepted residual risks.

- [ ] **Step 1: Confirm migration and repository hygiene**

Run:

```powershell
git status --short
docker compose exec backend python manage.py showmigrations
docker compose exec backend python manage.py makemigrations --check --dry-run
docker compose exec backend python manage.py check --deploy
```

Expected: all application migrations are applied; no model drift; deploy check has no unreviewed error. Record unrelated pre-existing worktree paths separately and never stage them.

- [ ] **Step 2: Run the complete automated gate**

Run:

```powershell
make verify
```

Expected: backend tests, Ruff, frontend tests, TypeScript, ESLint, and production build all exit 0. If a failure is introduced by the Accounts redesign, add one focused regression test, fix the owning file, rerun the focused command, then rerun `make verify` from the beginning.

- [ ] **Step 3: Validate Keycloak and live role workflow**

Run:

```powershell
python scripts/verify_accounts_keycloak.py infrastructure/keycloak/realm-mhc.json
make accounts-smoke
```

Expected: realm contract exits 0; smoke proves role isolation, manager allocation/no-action, Accounts My Work/action, no-transaction resolution guard, stale update, and notification delivery.

- [ ] **Step 4: Run browser verification for representative roles**

In a production-like Keycloak-enabled configuration with development bypass disabled, verify:

1. Accounts Agent signs in through Keycloak, sees My Work/Accounts Queue/Kanban/Dashboard, claims an eligible unassigned ticket, records verification, and resolves with the no-transaction confirmation.
2. Accounts Supervisor sees Restricted Accounts cases and Supervisor Review, assigns an Accounts agent, and approves resolution.
3. Service Desk Manager sees all three Normal/Sensitive domains, assigns and reroutes, and has no reply/note/upload/transition controls.
4. System Administrator signs in but sees no business queues or ticket detail.
5. Auditor sees read-only cross-domain reporting and no mutation controls.
6. Operational Agent cannot open an Accounts ticket URL.
7. Manager cannot discover a Restricted ticket by list, detail, report count, search, or notification link.
8. Reassignment moves a ticket between My Work views and creates one notification.
9. An expired access token performs the existing single refresh/retry path, a failed refresh returns to Keycloak sign-in without protected-content flash, and sign-out ends the Keycloak session.

For each scenario, record route, visible controls, API status for denied actions, and result. Do not record credentials, tokens, requester data, descriptions, or financial references.

- [ ] **Step 5: Exercise migration dry-run against a non-production copy**

Create a synthetic manifest containing one eligible, one wrong-domain-assignee, and one invalid row. Run dry-run and prove zero writes. Remove the invalid row, sign the manifest with the manager subject/approval timestamp, apply, and rerun to prove `already_migrated`. Compare counts for messages, notes, attachments, links, SLA instances, transition history, and audit history before/after.

Do not run apply against production until the service owner separately supplies the approved production manifest.

- [ ] **Step 6: Write the verification record with actual results**

Create `docs/verification/accounts-redesign-2026-07-29.md` containing:

- tested commit SHA and timestamp/timezone;
- Docker, Python, Django, Node, and Keycloak versions;
- each exact command from Steps 1–5 and its exit result;
- automated test counts;
- Accounts smoke ticket numbers only;
- the eight browser scenario results;
- migration dry-run/apply/idempotency evidence using synthetic ticket numbers;
- review of logs for absence of sensitive fields;
- confirmed Operational/IT regression status; and
- any residual risk stated as a concrete operational constraint with owner and mitigation.

Do not paste raw tokens, headers, credentials, ticket bodies, requester details, or financial references.

- [ ] **Step 7: Commit verification evidence**

Run:

```powershell
git add docs/verification/accounts-redesign-2026-07-29.md
git diff --cached --check
git diff --cached --name-only
git commit -m "docs(accounts): record release verification"
```

Expected: the staged file list contains only the verification record unless a separately reviewed regression fix was required and committed first.

---

## Plan 4 Completion Gate

The redesign is ready for controlled Accounts intake only when all of these are true:

- all four plan completion gates pass;
- Keycloak role/group mappings and representative token claims are verified;
- Keycloak login, token refresh/expiry recovery, and logout pass in the production-like browser configuration;
- manager, Accounts agent/supervisor, auditor, security, Operational/IT, and System Administrator scenarios match the approved matrix;
- unresolved routes fail closed and appear in manager triage;
- assignment/rerouting are stale-safe and audited;
- notification retry is idempotent;
- Accounts resolution cannot succeed without the no-transaction affirmation;
- the migration dry-run is write-free and apply is approved, atomic, history-preserving, and idempotent;
- production Accounts catalogue/mailbox/office/queue/SLA configuration is signed off; and
- the final verification document contains actual passing evidence without secrets or private ticket content.
