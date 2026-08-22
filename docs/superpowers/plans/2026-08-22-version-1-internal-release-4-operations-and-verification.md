# Version 1 Operations and Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Version 1 recoverable, reproducibly deployable, load-tested and independently verifiable from a named clean commit.

**Architecture:** Backup encryption uses a streaming authenticated format and restores only into an explicitly isolated target during verification. Production preflight validates real TLS material and secrets, the load harness records non-JSON failures safely, accessibility tests cover the staff-critical UI, and one Codex prompt drives the final evidence-backed GO/NO-GO review.

**Tech Stack:** Docker Compose, PostgreSQL, MinIO, Python cryptography, Nginx, k6, React/Vitest, pytest, PowerShell/Bash.

**Spec:** `docs/superpowers/specs/2026-08-22-version-1-internal-staff-release-design.md`

## Global Constraints

- Never restore into the active production database or object volume during a drill.
- Never commit certificates, private keys, backup keys, tokens or provider credentials.
- Version 1 production starts with `PUBLIC_SELF_SERVICE_ENABLED=false`.
- p95 expected-response latency is below 2 seconds and the error rate is below 1 percent for the agreed 10→50→100 VU profile.
- Browser verification covers call capture, walk-in capture, queue/search and every internal role family.
- A fresh readiness report must use a named clean commit and must preserve failed evidence.
- Use test-first changes and commit only the files listed by each task.

---

### Task 1: Streaming authenticated backup encryption

**Files:**
- Create: `backend/scripts/backup_crypto.py`
- Create: `backend/scripts/test_backup_crypto.py`
- Modify: `scripts/backup.sh`
- Modify: `scripts/restore.sh`
- Modify: `scripts/verify_backup.sh`
- Modify: `scripts/verify_backup.ps1`

**Interfaces:**
- Produces: `python scripts/backup_crypto.py encrypt INPUT OUTPUT`
- Produces: `python scripts/backup_crypto.py decrypt INPUT OUTPUT`
- Consumes: `BACKUP_ENCRYPTION_KEY` from environment
- Produces archive format: magic header, version, salt, nonce, ciphertext and AES-GCM tag

- [ ] **Step 1: Write crypto round-trip and tamper tests**

Test multi-chunk plaintext, empty plaintext, wrong key, modified header, modified
ciphertext and modified tag. Wrong or modified inputs must exit non-zero and delete
any partial plaintext output.

- [ ] **Step 2: Run the test and observe failure**

```powershell
docker compose run --rm --no-deps backend pytest scripts/test_backup_crypto.py -q
```

- [ ] **Step 3: Implement the streaming format**

Derive a 32-byte key with `Scrypt(salt=salt, length=32, n=2**15, r=8, p=1)`.
Use `Cipher(algorithms.AES(key), modes.GCM(nonce))`, authenticate the fixed header
with `authenticate_additional_data`, stream 1 MiB chunks, append the 16-byte tag,
and `fsync` before atomically renaming the output. Decryption writes to a temporary
sibling and renames only after `finalize_with_tag` succeeds.

- [ ] **Step 4: Replace unsupported OpenSSL calls**

Have backup create a plain tar archive in its protected temporary directory, invoke
the backend image with that directory mounted to run `backup_crypto.py encrypt`,
then remove plaintext through the existing temporary-directory trap. Restore uses
the same image and decrypt command before extraction.

- [ ] **Step 5: Correct verification table names and compare exact sets**

Use these database tables consistently on Bash and PowerShell:

```text
ticket
ticket_message
ticket_note
ticket_link
workflow_status
workflow_transition
workflow_transition_history
sla_instance
sla_policy
catalogue_service
catalogue_request_type
contact
org_office
auditevent
file_attachment
integrationevent
knowledge_article
```

Exclude deferred WhatsApp data from the Version 1 drill. Missing tables are errors,
not zero counts.

- [ ] **Step 6: Run crypto tests and shell syntax checks**

```powershell
docker compose run --rm --no-deps backend pytest scripts/test_backup_crypto.py -q
bash -n scripts/backup.sh scripts/restore.sh scripts/verify_backup.sh
```

- [ ] **Step 7: Commit executable backup encryption**

```powershell
git add backend/scripts/backup_crypto.py backend/scripts/test_backup_crypto.py scripts/backup.sh scripts/restore.sh scripts/verify_backup.sh scripts/verify_backup.ps1
git commit -m "fix: use authenticated streaming backup encryption"
```

### Task 2: Isolated restore drill and measured recovery evidence

**Files:**
- Modify: `scripts/verify_backup.sh`
- Modify: `scripts/verify_backup.ps1`
- Modify: `docs/pilot-runbook.md`
- Create at runtime: `artifacts/version-1-release/restore-drill/`

**Interfaces:**
- Consumes: the encrypted archive format from Task 1
- Produces: `restore-drill.json` with start/end time, duration, source/target counts, object counts, RPO and RTO

- [ ] **Step 1: Add fail-closed target validation**

Generate the side database as `mhc_verify_<UTC timestamp>`. Before restore, assert
it differs from `POSTGRES_DB`, starts with `mhc_verify_`, does not exist or was
created by this run, and is recorded in a cleanup trap. Use a new temporary Docker
volume named `mhc_verify_objects_<timestamp>` for MinIO objects; never stop or
clear the live MinIO volume.

- [ ] **Step 2: Restore database and objects into isolated targets**

Decrypt the fresh archive, restore the PostgreSQL dump into the side database and
extract objects into the temporary volume. Compare exact table row counts, object
file counts and a deterministic sample of SHA-256 object hashes.

- [ ] **Step 3: Write machine-readable evidence**

Record:

```json
{
  "result": "pass",
  "source_database": "mhc",
  "restore_database": "mhc_verify_20260822T000000Z",
  "backup_completed_at": "ISO-8601",
  "restore_completed_at": "ISO-8601",
  "rpo_seconds": 0,
  "rto_seconds": 0,
  "table_counts_match": true,
  "object_sample_hashes_match": true
}
```

Populate measured values rather than the example zeros. Keep failed evidence and
the isolated targets for diagnosis; clean successful targets.

- [ ] **Step 4: Execute the approved side-target drill**

```powershell
powershell -File scripts/verify_backup.ps1
```

Expected: exit `0`, no live target is stopped or overwritten, and evidence reports
matching database/object results with measured RPO/RTO.

- [ ] **Step 5: Update the runbook and commit scripts**

```powershell
git add scripts/verify_backup.sh scripts/verify_backup.ps1 docs/pilot-runbook.md
git commit -m "ops: verify recovery in isolated targets"
```

Do not commit runtime backup data or restore evidence containing secrets.

### Task 3: TLS and production preflight from a clean checkout

**Files:**
- Create: `infrastructure/nginx/ssl/README.md`
- Create: `scripts/check_prod_prerequisites.py`
- Create: `backend/apps/health/tests/test_prod_prerequisites.py`
- Modify: `.gitignore`
- Modify: `.env.example`
- Modify: `docker-compose.prod.yml`
- Modify: `docs/deployment.md`
- Modify: `docs/pilot-runbook.md`

**Interfaces:**
- Produces: `python scripts/check_prod_prerequisites.py --env .env --ssl-dir infrastructure/nginx/ssl`
- Requires at runtime: `fullchain.pem`, `privkey.pem`, matching keypair, unexpired certificate covering `DOMAIN`

- [ ] **Step 1: Write preflight tests using generated temporary certificates**

Generate certificates in pytest temporary directories with `cryptography.x509`.
Cover missing files, unreadable key, mismatched pair, expired certificate, wrong
hostname, weak secrets, `PUBLIC_SELF_SERVICE_ENABLED=true`, and a passing valid
configuration. Assert diagnostic messages name variables/files but never print
secret values.

- [ ] **Step 2: Run tests and observe failure**

```powershell
docker compose run --rm --no-deps backend pytest apps/health/tests/test_prod_prerequisites.py -q
```

- [ ] **Step 3: Implement the preflight**

Parse `.env` without echoing values. Reuse the production minimum-secret policy,
verify required internal variables including `MONITORING_WEBHOOK_SECRET`, reject
deferred-channel enablement, parse the certificate, verify dates/SAN and compare
public keys from certificate and private key.

Track only `infrastructure/nginx/ssl/README.md`; ignore `*.pem`, `*.key`, `*.crt`
and symlinks to secret material. Explain how operators install certificates from
the approved secret manager.

- [ ] **Step 4: Wire preflight into deployment before Compose startup**

Document this exact order:

```powershell
python scripts/check_prod_prerequisites.py --env .env --ssl-dir infrastructure/nginx/ssl
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

- [ ] **Step 5: Validate with temporary non-secret TLS material**

Run the unit tests, then run `docker compose ... config --quiet`. Do not commit the
temporary certificate. Confirm `git status --short infrastructure/nginx/ssl`
lists only `README.md`.

- [ ] **Step 6: Commit production preflight**

```powershell
git add infrastructure/nginx/ssl/README.md scripts/check_prod_prerequisites.py backend/apps/health/tests/test_prod_prerequisites.py .gitignore .env.example docker-compose.prod.yml docs/deployment.md docs/pilot-runbook.md
git commit -m "ops: add fail-closed production tls preflight"
```

### Task 4: Trustworthy load harness and queue performance gate

**Files:**
- Modify: `scripts/load_test.js`
- Create: `backend/tests/test_load_test_contract.py`
- Create at runtime: `artifacts/version-1-release/load/summary.json`

**Interfaces:**
- Consumes: `BASE_URL`, a production-equivalent `TOKEN`, optional `SUMMARY_PATH`
- Produces: k6 metrics `errors`, `non_json_errors`, `list_latency_ms`, `detail_latency_ms`, `kanban_latency_ms`
- Produces: JSON summary even when responses are HTML, empty or timed out

- [ ] **Step 1: Write a source-contract test for defensive response parsing**

Assert the script checks `Content-Type`, status and non-empty body before JSON
parsing; wraps parsing in a function returning `null`; records separate non-JSON
and 5xx failures; assigns timeouts to every request; and exports `handleSummary`
that writes `SUMMARY_PATH`.

- [ ] **Step 2: Run the test and observe failure**

```powershell
docker compose exec -T backend pytest tests/test_load_test_contract.py -q
```

- [ ] **Step 3: Harden all three request paths**

Implement:

```javascript
function jsonOrNull(response) {
  const contentType = String(response.headers["Content-Type"] || "");
  if (!contentType.includes("application/json") || !response.body) return null;
  try { return response.json(); } catch (_) { return null; }
}
```

Use it for list, detail and Kanban. Add request timeout `10s`, tag endpoints, count
every unexpected status and shape, and always produce the summary. Keep thresholds
`p(95)<2000` for expected responses and `errors rate<0.01`.

- [ ] **Step 4: Run the contract test and a 10-VU smoke**

```powershell
docker compose exec -T backend pytest tests/test_load_test_contract.py -q
docker run --rm -e BASE_URL=https://ticket.example -e TOKEN=$env:LOAD_TEST_TOKEN -e SUMMARY_PATH=/artifacts/summary.json -v ${PWD}/scripts:/scripts:ro -v ${PWD}/artifacts/version-1-release/load:/artifacts grafana/k6:0.52.0 run --stage 30s:10 --stage 30s:0 /scripts/load_test.js
```

Replace `ticket.example` with the approved staging host. Expected: summary exists
even on failure.

- [ ] **Step 5: Run the full 10→50→100 profile and enforce the gate**

```powershell
docker run --rm -e BASE_URL=$env:BASE_URL -e TOKEN=$env:LOAD_TEST_TOKEN -e SUMMARY_PATH=/artifacts/summary.json -v ${PWD}/scripts:/scripts:ro -v ${PWD}/artifacts/version-1-release/load:/artifacts grafana/k6:0.52.0 run /scripts/load_test.js
```

Expected: exit `0`, p95 below 2 seconds, error rate below 1 percent, no connection
timeout burst and no non-JSON server response. If it fails, preserve summary and
server/PostgreSQL metrics, invoke `superpowers:systematic-debugging`, fix the
measured bottleneck, rerun the focused query-budget tests from Plan 2, and repeat
this command. Do not weaken thresholds.

- [ ] **Step 6: Commit the trustworthy harness**

```powershell
git add scripts/load_test.js backend/tests/test_load_test_contract.py
git commit -m "test: make production load failures observable"
```

### Task 5: Staff-critical accessibility and browser role matrix

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/src/features/tickets/Version1Accessibility.test.tsx`
- Modify: `frontend/src/features/tickets/QueuePage.tsx`
- Modify: `frontend/src/features/tickets/ChannelIntakePage.tsx`
- Modify: `frontend/src/features/tickets/TicketDetailPage.tsx`
- Create at runtime: `artifacts/version-1-release/browser/`

**Interfaces:**
- Produces: automated axe checks for Queue, Call intake, Walk-in intake and Ticket detail
- Produces: browser evidence for every Version 1 role family

- [ ] **Step 1: Add failing accessibility checks**

Install `axe-core` and `vitest-axe` as dev dependencies. Render each critical page
with realistic data, run axe and assert no serious or critical violations. Also
assert every button, link, input, combobox and textarea has an accessible name and
the keyboard focus order reaches search, filters, result, detail actions and intake
submission.

- [ ] **Step 2: Run the tests and record failures**

```powershell
docker compose run --rm --no-deps --build frontend npm test -- --run src/features/tickets/Version1Accessibility.test.tsx
```

- [ ] **Step 3: Fix the reported staff-critical controls**

Add visible labels or `aria-label`, connect field errors with `aria-describedby`,
preserve focus after validation, ensure icon-only controls have stable names and
maintain a visible focus indicator. Do not suppress axe rules.

- [ ] **Step 4: Run frontend accessibility and regression gates**

```powershell
docker compose run --rm --no-deps --build frontend npm test -- --run
docker compose run --rm --no-deps --build frontend npm run typecheck
docker compose run --rm --no-deps --build frontend npm run lint
docker compose run --rm --no-deps --build frontend npm run build
```

- [ ] **Step 5: Execute the real-browser role matrix**

For service desk, Operational agent, Operational supervisor, Master, Deputy Master,
Assistant Master, examiner, records officer, finance, data clerk, IT agent, IT lead,
security responder, auditor, system administrator, roleless and expired-role
identities, record login result, navigation, queue visibility, direct lookup,
allowed actions and denied actions. Capture one call and one walk-in ticket and
retrieve both through queue/search. Save screenshots, console/network logs and a
machine-readable matrix under the browser artifact directory.

- [ ] **Step 6: Commit automated accessibility work**

```powershell
git add frontend/package.json frontend/package-lock.json frontend/src/features/tickets
git commit -m "test: enforce accessibility on version 1 staff workflows"
```

Do not commit browser artifacts containing requester PII or authentication tokens.

### Task 6: Final Codex verification prompt and fresh readiness decision

**Files:**
- Create: `docs/version-1-production-verification-prompt.md`
- Create: `docs/production-readiness-version-1.md`
- Modify: `docs/pilot-readiness.md`
- Modify: `docs/traceability.md`

**Interfaces:**
- Produces: one self-contained prompt the release owner can run in Codex
- Produces: a fresh GO/NO-GO report linked to a clean commit and immutable evidence

- [ ] **Step 1: Write the concise Codex execution prompt**

The prompt must instruct Codex to:

```text
Inspect AGENTS.md and the approved Version 1 design and plans. Work from a named
clean commit. Test and, where explicitly authorized, repair the authenticated
internal ticketing release: call/walk-in intake, queue/search, Operational and IT
workflows, assignment/routing/escalation/approvals, SLA, notes/messages/attachments,
sanitized IT children, knowledge, automation, dashboards/exports, audit and admin.
Exercise every role, office/service/queue boundary and critical request parameter,
including invalid, missing, duplicate, replay, concurrency and cross-scope cases.
Prove public requester, CSAT, public knowledge, email and WhatsApp paths return 404
and produce no side effects. Run static, unit, integration, production build,
Compose/preflight, TLS, backup/isolated restore, load, accessibility and real-browser
gates. Preserve evidence, never expose secrets or real PII, do not weaken tests or
thresholds, and issue GO only if every Version 1 gate passes; move only public
self-service findings to Version 1.1.
```

Add exact repository commands from these four plans and require periodic concise
status updates, root-cause fixes, reruns after changes and an independent read-only
review before sign-off.

- [ ] **Step 2: Run the complete quality gate from the release commit**

```powershell
docker compose run --rm --no-deps --volume ${PWD}:/workspace:ro backend python /workspace/scripts/check_prod_compose.py
docker compose exec -T backend python manage.py makemigrations --check --dry-run
docker compose exec -T backend pytest -q
docker compose exec -T backend ruff check .
docker compose exec -T backend mypy apps config
docker compose run --rm --no-deps --build frontend npm test -- --run
docker compose run --rm --no-deps --build frontend npm run typecheck
docker compose run --rm --no-deps --build frontend npm run lint
docker compose run --rm --no-deps --build frontend npm run build
```

Also run the preflight, isolated restore, full load and browser commands from Tasks
2–5. Record exact start/end times, versions, exit codes and artifact paths.

- [ ] **Step 3: Reconcile all acceptance criteria**

For every interface, workflow, role and production parameter, link the requirement
to test or runtime evidence. Classify unresolved public-channel findings only under
Version 1.1. Classify any internal access, privacy, integrity, recovery, TLS, load,
accessibility or reproducibility failure as Version 1 NO-GO.

- [ ] **Step 4: Obtain an independent read-only review**

Ask a separate reviewer to inspect the named commit, diff, test logs, role matrix,
route probes, backup evidence and load summary without making changes. Include its
verdict and disagreements in the readiness report.

- [ ] **Step 5: Issue the decision and commit release documentation**

The report starts with `Decision: GO` only when every Version 1 gate has passing
evidence. Otherwise it starts with `Decision: NO-GO` and lists exact blocking
commands and owners.

```powershell
git add docs/version-1-production-verification-prompt.md docs/production-readiness-version-1.md docs/pilot-readiness.md docs/traceability.md
git commit -m "docs: record version 1 production decision"
```
