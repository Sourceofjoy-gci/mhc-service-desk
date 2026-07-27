# Pilot Foundation 4: Release Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the pilot foundation reproducibly testable in Docker, verify the Operational/IT workflow end to end, and align readiness documentation with fresh evidence.

**Architecture:** The development image contains the repository's declared test tools, Make targets become truthful orchestration entry points, and one idempotent API smoke script exercises the new lifecycle contract with separate identities. Final verification combines backend/frontend static and automated gates with browser inspection, then records only demonstrated readiness.

**Tech Stack:** Docker Compose, Python 3.12/requests, Django management checks, pytest, Ruff, mypy, npm, Vitest, TypeScript, Vite, repository smoke scripts.

## Global Constraints

- Complete Plans 1–3 before this plan.
- Preserve unrelated pre-existing working-tree changes and stage only current-task files.
- The listed file-level `git add` commands apply only to paths that were clean at task start. For an already-dirty path, stage only task-owned hunks after reviewing `git diff --cached`; if a hunk cannot be separated from pre-existing work, leave that path uncommitted rather than include someone else's changes.
- Never commit `.env`, credentials, generated logs, database files, `node_modules`, build artifacts, or test caches.
- Use explicit development tokens only against `config.settings.dev`; prove they fail when `DEBUG=False` in automated backend tests.
- Do not label the application pilot-ready unless every required gate passes from a fresh run.
- If an external prerequisite such as a signed DPIA, production certificates, or a penetration test is absent, document it as an external blocker rather than simulating completion.
- Use the verification-before-completion skill before any completion claim and the browser-verify skill for rendered route checks.

---

### Task 1: Make local test and quality commands runnable

**Files:**
- Modify: `backend/Dockerfile.dev`
- Modify: `Makefile`
- Modify: `README.md`
- Create: `backend/apps/health/tests/test_dev_tooling.py`

**Interfaces:**
- Produces: backend development image with `requirements/dev.txt` installed.
- Produces: truthful `make test`, `make lint`, `make type`, `make verify`, and `make pilot-smoke` targets.

- [ ] **Step 1: Write a failing development-image contract test**

Add a source-level test that reads `backend/Dockerfile.dev` and asserts both requirement files are installed:

```python
def test_development_image_installs_test_tooling():
    dockerfile = Path(__file__).resolve().parents[3] / "Dockerfile.dev"
    text = dockerfile.read_text(encoding="utf-8")
    assert "requirements/base.txt" in text
    assert "requirements/dev.txt" in text
```

- [ ] **Step 2: Run the contract test and verify failure**

Run `pytest backend/apps/health/tests/test_dev_tooling.py -q`.

Expected: FAIL because the development image installs only runtime dependencies.

- [ ] **Step 3: Install development requirements in the development image**

Change the image build layer to:

```dockerfile
RUN pip install --upgrade pip && \
    pip install -r requirements/base.txt && \
    pip install -r requirements/dev.txt
```

Do not change the production Dockerfile.

- [ ] **Step 4: Make repository commands match actual container paths**

Add a `verify` target that runs migration drift/checks, full backend tests, Ruff, frontend tests, TypeScript, ESLint, and build. Correct mypy from `mypy backend` inside `/app` to `mypy apps config`. Add:

```make
pilot-smoke:
	docker compose exec backend python /app/scripts/pilot_foundation_smoke.py

verify:
	docker compose exec backend python manage.py makemigrations --check --dry-run
	docker compose exec backend pytest -q
	docker compose exec backend ruff check .
	docker compose exec frontend npm test -- --run
	docker compose exec frontend npm run typecheck
	docker compose exec frontend npm run lint
	docker compose exec frontend npm run build
```

Document these exact targets in `README.md`, including that `pilot-smoke` mutates only development data.

- [ ] **Step 5: Build and verify tool availability**

Run:

```powershell
docker compose build backend
docker compose run --rm backend pytest --version
docker compose run --rm backend ruff --version
docker compose run --rm backend mypy --version
```

Expected: all commands exit 0 and print installed versions.

- [ ] **Step 6: Commit development tooling**

```powershell
git add backend/Dockerfile.dev Makefile README.md backend/apps/health/tests/test_dev_tooling.py
git commit -m "build(dev): make quality gates runnable"
```

---

### Task 2: Add a repeatable Operational/IT pilot smoke path

**Files:**
- Create: `backend/scripts/pilot_foundation_smoke.py`
- Create: `backend/apps/health/tests/test_pilot_smoke_contract.py`
- Modify: `scripts/m2_smoke.py`
- Modify: `scripts/m3_smoke.py`

**Interfaces:**
- Produces: `python /app/scripts/pilot_foundation_smoke.py` against `PILOT_API_BASE`, defaulting to `http://localhost:8000/api/v1`.
- Updates legacy smoke transitions to send `updated_at` after each server response.

- [ ] **Step 1: Write a failing smoke-script contract test**

Import the new module and test its helpers with mocked `requests.Session`. Assert it defines distinct headers for:

```python
OPS_HEADERS = {"Authorization": "Bearer dev:pilot-ops:ops-agents"}
IT_HEADERS = {"Authorization": "Bearer dev:pilot-it:it-agents"}
OPS_LEAD_HEADERS = {"Authorization": "Bearer dev:pilot-lead:ops-supervisors"}
```

Assert `transition(session, number, ticket, to_status, **fields)` always sends `ticket["updated_at"]` and returns the refreshed detail.

- [ ] **Step 2: Run the smoke contract and verify the module is absent**

Run `pytest backend/apps/health/tests/test_pilot_smoke_contract.py -q`.

Expected: FAIL importing `scripts.pilot_foundation_smoke`.

- [ ] **Step 3: Implement the smoke workflow**

Use unique requester email/title suffixes from `uuid.uuid4().hex[:8]`. The script must stop on the first unexpected status and print the response's correlation ID. Execute this exact sequence:

1. Call authenticated ticket lists as Operational and IT identities so their durable group snapshots exist.
2. Create an Operational ticket through public intake.
3. Fetch detail as Operational and assert IT detail returns `404`.
4. Self-assign with `self_assignee_id`, current `updated_at`, and assert refreshed assignee.
5. Set `team`, `next_action`, and `next_action_at` through work-state and retain the returned timestamp.
6. Add one requester-visible reply and one internal note.
7. Transition `new -> triage -> in_progress -> resolved`, using the timestamp returned by every call and resolution fields on the last transition.
8. Reopen, assert active resolution fields are empty and `reopened_at` is set.
9. Fetch activity and assert message, note, work-state, resolution, and reopen events exist.
10. Assert Operational identity gets `403` from IT dashboard and IT identity gets `403` from Operational dashboard.
11. Create an IT child from a second Operational ticket, assert the IT identity can read it, and the Operational identity cannot.
12. Print the created ticket numbers and a final success line.

Keep the script idempotent by creating new data only and never deleting or modifying reference data.

- [ ] **Step 4: Update legacy transition smoke requests**

In `scripts/m2_smoke.py` and `scripts/m3_smoke.py`, retain each transition response and send its `updated_at` in the next transition payload. Fetch detail before the first transition when the create response does not contain the timestamp. Authenticate the M2 Operational dashboard request because it is no longer public. Keep all existing scope and integration assertions.

- [ ] **Step 5: Run unit contract and live Docker smoke**

Run:

```powershell
Set-Location backend
pytest apps/health/tests/test_pilot_smoke_contract.py -q
Set-Location ..
docker compose up -d --build postgres redis rabbitmq minio clamav keycloak backend frontend
docker compose exec backend python /app/scripts/seed_dev.py
docker compose exec backend python /app/scripts/pilot_foundation_smoke.py
```

Expected: tests pass, required services become healthy, seed completes, and the smoke script prints success with no cross-domain leakage.

- [ ] **Step 6: Commit smoke coverage**

```powershell
git add backend/scripts/pilot_foundation_smoke.py backend/apps/health/tests/test_pilot_smoke_contract.py scripts/m2_smoke.py scripts/m3_smoke.py
git commit -m "test(pilot): cover operational and IT lifecycle"
```

---

### Task 3: Reconcile permission and readiness documentation with code

**Files:**
- Modify: `docs/permission-matrix.md`
- Modify: `docs/pilot-readiness.md`
- Modify: `docs/roadmap.md`
- Modify: `docs/traceability.md`
- Modify: `docs/agent-guide.md`
- Create: `docs/verification/pilot-foundation-2026-07-27.md`

**Interfaces:**
- Produces: documentation whose implemented/verified claims point to actual endpoints, tests, and command evidence.

- [ ] **Step 1: Generate fresh evidence before editing claims**

Run and capture summaries, not secrets or raw ticket content:

```powershell
docker compose exec backend python manage.py makemigrations --check --dry-run
docker compose exec backend python manage.py check
docker compose exec backend pytest -q
docker compose exec backend ruff check .
docker compose exec backend python scripts/permission_audit.py
docker compose exec frontend npm test -- --run
docker compose exec frontend npm run typecheck
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
docker compose exec backend python /app/scripts/pilot_foundation_smoke.py
```

Record command, UTC timestamp, exit code, and concise totals in `docs/verification/pilot-foundation-2026-07-27.md`. Do not paste access tokens, personal data, or full logs.

- [ ] **Step 2: Correct the permission matrix**

Document:

- public versus protected endpoints as implemented;
- security responders as restricted-only across both domains unless another group grants ordinary domain scope;
- auditors as read-only;
- exact work-state, assignee, activity, attachment, transition, and reporting authorization;
- canonical pagination and error shapes;
- production-disabled development authentication.

Remove claims that `ScopePermission` without a required scope provides domain authorization.

- [ ] **Step 3: Correct readiness and roadmap status**

Replace historical fixed test counts and blanket milestone-complete claims with evidence-linked statuses. Mark the pilot foundation verified only when every Task 1–2 command passed. Keep DPIA signature, production TLS/secrets, penetration test, and external provider approvals open. Distinguish “implemented”, “automatically verified”, “manually verified”, and “external sign-off required”.

- [ ] **Step 4: Correct traceability and the agent guide**

For affected requirements, link the exact new tests/endpoints. In particular update authentication, scope separation, assignment, workflow, reopen, queue filters, pagination, SLA display, attachments, audit/outbox, and frontend test coverage. Update the agent guide with the new workspace flow and conflict-reload behavior.

- [ ] **Step 5: Review documentation for unsupported claims and commit**

Run:

```powershell
rg -n "28 tests|0 failures|full ticket lifecycle|pilot-ready|cursor pagination|no auth required" docs/pilot-readiness.md docs/roadmap.md docs/traceability.md docs/permission-matrix.md
git diff --check -- docs/permission-matrix.md docs/pilot-readiness.md docs/roadmap.md docs/traceability.md docs/agent-guide.md docs/verification/pilot-foundation-2026-07-27.md
```

Every remaining readiness phrase must be supported by the evidence document or explicitly marked pending.

Commit:

```powershell
git add docs/permission-matrix.md docs/pilot-readiness.md docs/roadmap.md docs/traceability.md docs/agent-guide.md docs/verification/pilot-foundation-2026-07-27.md
git commit -m "docs: align pilot readiness with verification"
```

---

### Task 4: Perform final static, automated, and browser verification

**Files:**
- Modify only when a verification failure is traced to a Plan 1–3 change.
- Append final outcomes: `docs/verification/pilot-foundation-2026-07-27.md`

**Interfaces:**
- Produces: a fresh, reproducible release-gate record and an honest completion status.

- [ ] **Step 1: Run the complete backend gate**

Run:

```powershell
docker compose exec backend python manage.py makemigrations --check --dry-run
docker compose exec backend python manage.py migrate --check
docker compose exec backend python manage.py check
docker compose exec backend pytest -q
docker compose exec backend ruff check .
docker compose exec backend mypy apps config
docker compose exec backend python scripts/permission_audit.py
```

Expected: every command exits 0. If a command fails, use `superpowers:systematic-debugging`, add or refine a regression test, fix the root cause, and rerun the entire backend gate before continuing.

- [ ] **Step 2: Run the complete frontend gate**

Run:

```powershell
docker compose exec frontend npm test -- --run
docker compose exec frontend npm run typecheck
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
```

Expected: every command exits 0. Apply the same diagnose-test-fix-rerun discipline to failures.

- [ ] **Step 3: Run the live pilot smoke again**

Run:

```powershell
docker compose exec backend python /app/scripts/pilot_foundation_smoke.py
```

Expected: Operational and IT workflows pass, cross-domain dashboards return `403`, out-of-scope tickets return `404`, and activity contains the expected material events.

- [ ] **Step 4: Verify rendered routes with the browser skill**

Invoke `browser-verify` and inspect desktop (1440×900) and mobile (390×844) for:

- `/login`, `/public`, and `/health` without staff navigation;
- protected `/tickets` with URL filters and cursor controls;
- a populated ticket workspace with transitions, activity, operations, SLA, and attachments;
- Operational and IT dashboards under their permitted identities;
- loading, empty, `403`, validation, and stale-conflict states using controlled API fixtures where live state cannot reliably produce them.

Verify keyboard focus, labels, dialog naming, mobile overflow, and that unavailable lifecycle controls are absent.

- [ ] **Step 5: Record final evidence and run the verification-before-completion skill**

Append exact exit codes, test totals, build result, smoke ticket numbers, and browser routes/viewports to the evidence document. Then invoke `superpowers:verification-before-completion` and rerun any command it requires. A failure keeps the related readiness item open.

- [ ] **Step 6: Commit final evidence only if it changed after Task 3**

```powershell
git add docs/verification/pilot-foundation-2026-07-27.md
git commit -m "test: record pilot foundation verification"
```

Skip this commit when the evidence file has no new diff.

---

## Plan 4 Completion Gate

The implementation is complete only when backend tests/lint/type/migrations/checks, frontend tests/lint/type/build, the live Operational/IT smoke, and browser verification all pass from fresh runs. External governance and production-environment prerequisites remain explicitly open until their owners provide evidence.
