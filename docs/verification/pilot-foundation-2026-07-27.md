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

## Fresh automatic evidence

| UTC start | Command | Exit | Concise result |
|---|---|---:|---|
| 2026-07-28T09:39:25Z | `docker compose exec backend python manage.py makemigrations --check --dry-run` | 0 | No changes detected |
| 2026-07-28T09:39:32Z | `docker compose exec backend python manage.py check` | 0 | System check identified no issues (0 silenced) |
| 2026-07-28T09:39:38Z | `docker compose exec backend pytest -q` | 2 | Collection stopped with 1 error before tests ran. `test_pilot_smoke_contract.py` derives `/scripts/m2_smoke.py`, but the current backend container mounts only `backend` at `/app`; `/scripts/m2_smoke.py` does not exist in that container. |
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

## Automatically verified in this run

- Migration drift check and Django system check.
- Permission-audit route inventory.
- Frontend unit/component tests, TypeScript, ESLint, and production build.
- The live Operational/IT pilot smoke workflow, including cross-domain `403`
  dashboards and `404` ticket isolation asserted by the script.

The complete backend automated gate is **not** verified: full pytest did not
collect and repository-wide Ruff is red.

## Manual browser verification

Not performed. A supported browser-verification tool is unavailable in the
current environment. No desktop/mobile route, focus, overflow, empty/error,
permission, validation, or stale-conflict browser claim is made here.

## Open release blockers

- Full backend pytest: collection error described above.
- Backend Ruff: 64 violations in the fresh run above.
- Backend mypy: Task 1's fresh gate recorded 255 errors across 52 files. Mypy
  was not rerun by Task 3 because it is outside Task 3's command list; it
  remains an explicit Plan 4 completion blocker until a fresh zero-error run.
- Browser verification: unavailable and therefore not passed.
- Production TLS certificates and production secret-manager integration: no
  operator evidence supplied.
- Signed DPIA/data-protection approval: no owner evidence supplied.
- Penetration test and security acceptance: no external report supplied.
- External provider approvals and production credentials, including Meta
  WhatsApp and e-Estate dependencies: no owner evidence supplied.

Because these gates are open, this evidence does not label the application
pilot-ready or the Plan 4 completion gate complete.
