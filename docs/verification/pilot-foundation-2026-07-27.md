# Pilot foundation verification evidence

Evidence file requested by the 2026-07-27 release-verification plan. The fresh
run below occurred on 2026-07-28 UTC against the explicitly authorized dirty
main checkout. It records summaries only: no bearer tokens, requester details,
raw payloads, or full logs.

## Environment and command equivalence

- Backend evidence used the running `backend` service with the current
  `./backend:/app` bind.
- The unrelated Cognee workload continued to own host port 8000. The MHC
  backend used the repository-supported `BACKEND_PORT=8001` mapping; in-
  container commands continued to use port 8000.
- The current Compose frontend contains image-copied source rather than a host
  source bind. Each frontend gate therefore used the accepted Makefile
  `run_frontend` expansion: a freshly built one-off container, an isolated
  image-seeded `/app/node_modules` volume, `--no-deps`, and `--rm`. This is the
  current-source equivalent of the plan's stale `docker compose exec frontend`
  examples.

## Earlier baseline evidence

This first run predates the backend remediation commits. Its backend pytest,
Ruff, and mypy failures are retained as historical evidence and are superseded
by the accepted remediation evidence below. The frontend and live-smoke rows
show that those workflows passed at that point. Their final closeout reruns
against the completed checkout are recorded below.

| UTC start | Command | Exit | Concise result |
|---|---|---:|---|
| 2026-07-28T09:39:25Z | `docker compose exec backend python manage.py makemigrations --check --dry-run` | 0 | No changes detected |
| 2026-07-28T09:39:32Z | `docker compose exec backend python manage.py check` | 0 | System check identified no issues (0 silenced) |
| 2026-07-28T09:39:38Z | `docker compose exec backend pytest -q` | 1 (outer Docker Compose process) | Pytest stopped with 1 collection error and returned internal exit 2. `test_pilot_smoke_contract.py` derives `/scripts/m2_smoke.py`, but the current backend container mounts only `backend` at `/app`; `/scripts/m2_smoke.py` does not exist in that container. |
| 2026-07-28T09:39:51Z | `docker compose exec backend ruff check .` | 1 | 64 repository-wide violations. Categories include line length, import placement/order, Django model `__str__`, bandit rules, and undefined names from star-imported settings. No product code was changed in this documentation task. |
| 2026-07-28T09:39:53Z | `docker compose exec backend python scripts/permission_audit.py` | 0 | Audit passed: 67 route actions across 48 API paths; required lifecycle, attachment, and reporting route families were present. |
| 2026-07-28T09:40:48Z | `docker compose run --rm --no-deps --build --volume /app/node_modules frontend env VITE_API_BASE_URL= npm test -- --run` | 0 | 16 test files passed; 216 tests passed. |
| 2026-07-28T09:42:04Z | `docker compose run --rm --no-deps --build --volume /app/node_modules frontend npm run typecheck` | 0 | TypeScript `tsc --noEmit` completed without errors. |
| 2026-07-28T09:42:32Z | `docker compose run --rm --no-deps --build --volume /app/node_modules frontend npm run lint` | 0 | ESLint completed without errors. |
| 2026-07-28T09:42:50Z | `docker compose run --rm --no-deps --build --volume /app/node_modules frontend npm run build` | 0 | Vite transformed 2,241 modules and built the production bundle. Non-fatal warnings remain for unresolved Geist font files and a JavaScript chunk above 500 kB. |
| 2026-07-28T09:43:36Z | `docker compose exec backend python /app/scripts/pilot_foundation_smoke.py` | 0 | Operational lifecycle, cross-domain denials, IT child, and material activity assertions passed. Created ticket identifiers: `OP-202607-000060`, `OP-202607-000061`, `IT-202607-000022`. |

The permission audit result is route-metadata evidence, not proof that every
queryset is scoped. The permission matrix pairs it with current view logic and
focused authorization tests.

An independent review reconciliation on 2026-07-28 UTC repeated the original
Compose pytest command twice: the outer Docker Compose process exited 1. A
bounded in-container shell probe captured pytest's own exit as 2. Both refer to
the same historical collection error above.

## Accepted backend remediation evidence

The backend fixes were then tested from a freshly built current-source image
and independently reviewed. One full-suite review used an isolated one-off
database. These results supersede the earlier backend failures without erasing
them from the record.

| Command or source state | Exit | Concise result |
|---|---:|---|
| `python manage.py makemigrations --check --dry-run` | 0 | No model changes detected |
| `python manage.py migrate --check` | 0 | No unapplied migrations detected |
| `python manage.py check` | 0 | Django system check reported no issues |
| `pytest -q` in the fresh current-source backend image | 0 | 354 tests passed |
| `mypy apps config` in the fresh current-source backend image | 0 | No issues in 160 source files |
| `ruff check .` against the explicitly authorized dirty main worktree | 0 | No findings in the current worktree |
| `ruff check .` against committed `HEAD` without the preserved user worktree overlays | 1 | 73 findings remain: 32 `F401`, 23 `I001`, 12 `UP017`, 4 `F811`, and 2 `UP035` |
| `python scripts/permission_audit.py` | 0 | 67 route actions across 48 API paths |
| Focused inbound-email sanitizer regression | 0 | Persisted HTML removed an invisible `javascript` URI scheme, `formaction`, and the embedded zero-width character |

The sanitizer evidence uses Bleach 6.4.0 and the service-level persistence
path, not only a direct library call. WhatsApp template listing and outbound
sending now require authentication; outbound sending denies auditors.
The inbound provider webhook remains public for provider delivery.

The Ruff distinction matters. The authorized dirty worktree is clean because
it contains pre-existing user-owned lint cleanup hunks that were deliberately
left unstaged. The committed checkout does not contain those hunks, so a fresh
clone is not yet Ruff-clean. No unrelated user hunk was included in the
backend remediation commits.

## Final runtime closeout evidence

Exact UTC start times were not captured with the supplied final results, so
none are inferred here.

| Command or runtime state | Recorded result |
|---|---|
| Fresh verified backend image recreated with `BACKEND_PORT=8001` | The service started on host port 8001 and `/api/v1/health` became healthy |
| `docker compose run --rm --no-deps --build --volume /app/node_modules frontend env VITE_API_BASE_URL= npm test -- --run` | Exit 0; 16 test files and 216 tests passed |
| Current-source frontend `npm run typecheck` gate | Exit 0 |
| Current-source frontend `npm run lint` gate | Exit 0 |
| Current-source frontend `npm run build` gate | Exit 0; Vite transformed 2,241 modules. Non-blocking warnings remain for unresolved Geist font files and a JavaScript chunk above 500 kB |
| `docker compose exec backend python /app/scripts/pilot_foundation_smoke.py` | Passed; created `OP-202607-000076`, `OP-202607-000077`, and `IT-202607-000029` |

## Implemented

- Debug-only development authentication and production `DEBUG=False` guard.
- Ticket domain/restricted scoping, persisted assignment dimensions, auditor
  read-only behavior, server-derived lifecycle capabilities, optimistic
  conflict detection, attachment scan/download rules, and scoped reporting.
- A staff ticket workspace with server-approved transitions, work-state and
  assignment controls, chronological activity, SLA clocks, relationships, and
  attachment scan states.
- Current-source frontend quality wrappers and the repeatable Operational/IT
  pilot smoke workflow.

Implementation is a code-state statement, not a passing release verdict.

## Automatically verified

- Migration drift, unapplied-migration, and Django system checks.
- The full backend test suite: 354 tests passed.
- Strict backend typing: no issues in 160 source files.
- Permission-audit route inventory.
- The inbound-email sanitizer regression through persisted message content.
- Ruff only for the explicitly authorized current dirty worktree.
- The fresh verified backend image was recreated on host port 8001 and its
  health endpoint became healthy.
- The final isolated current-source frontend unit/component tests, TypeScript,
  ESLint, and production build passed.
- The final live Operational/IT smoke passed, including cross-domain `403`
  dashboards and `404` ticket isolation asserted by the script.

The final release gate remains open. A clean committed checkout is not
Ruff-clean, browser verification is unavailable, and owner-controlled release
prerequisites have not been supplied.

## Manual browser verification

Not performed. A supported browser-verification tool is unavailable in the
current environment. No desktop/mobile route, focus, overflow, empty/error,
permission, validation, or stale-conflict browser claim is made here.

## Open release blockers

- Reproducible Ruff: committed `HEAD` still has the 73 findings itemized above;
  the zero-finding result currently depends on preserved, unstaged user work.
- Browser verification: unavailable and therefore not passed.
- Production TLS certificates and production secret-manager integration: no
  operator evidence supplied.
- Signed DPIA/data-protection approval: no owner evidence supplied.
- Penetration test and security acceptance: no external report supplied.
- External provider approvals and production credentials, including Meta
  WhatsApp and e-Estate dependencies: no owner evidence supplied.
- Product, technical, security, operations, records, and data-protection owner
  sign-off: not supplied.

Because these gates are open, this evidence does not label the application
pilot-ready or the Plan 4 completion gate complete.
