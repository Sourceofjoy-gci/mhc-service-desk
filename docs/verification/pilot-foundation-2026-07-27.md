# Pilot foundation verification evidence

This file records the final accepted 2026-07-28 verification against the
explicitly authorized dirty `main` checkout. It contains summaries only: no
bearer tokens, requester details, raw provider payloads, or full logs.

## Environment and command equivalence

- The backend, worker, and beat images were rebuilt from the final current
  source. The backend was recreated on host port 8001 and became healthy at
  `/api/v1/health`; containers continued to use backend port 8000 internally.
- The unrelated Cognee workload continued to own host port 8000 and was not
  stopped or changed.
- The Compose frontend contains image-copied source rather than a host source
  bind. Frontend gates therefore used a freshly built one-off container, an
  isolated image-seeded `/app/node_modules` volume, `--no-deps`, and `--rm`.
- Exact UTC start times were not captured with the supplied final results, so
  none are inferred here.

## Final automatic evidence

| Gate or runtime state | Result |
|---|---|
| Backend, worker, and beat image rebuild | Passed; fresh final current-source images were produced for all three services |
| Backend runtime health | Passed on host port 8001; `/api/v1/health` became healthy |
| Live migration application | Passed; all new migrations were applied to the live pilot database |
| `python manage.py makemigrations --check --dry-run` | Exit 0; no model drift |
| `python manage.py migrate --check` | Exit 0; no unapplied migrations |
| `python manage.py check` | Exit 0; no Django system-check issues |
| `pip check` | Exit 0; no broken requirements |
| `pytest -q` on final `HEAD` | Exit 0; 541 tests passed in 255.91s |
| Focused email-channel migration verification | Exit 0; 28 tests passed, including forward, reverse, and reapply round-trip coverage |
| `mypy apps config` | Exit 0; no issues in 164 source files |
| `ruff check .` against the explicitly authorized dirty worktree | Exit 0; no findings |
| `python scripts/permission_audit.py` | Exit 0; 64 route actions across 48 API paths |
| Isolated current-source frontend tests | Exit 0; 16 test files and 229 tests passed |
| Frontend `npm run typecheck` | Exit 0 |
| Frontend `npm run lint` | Exit 0 |
| Frontend `npm run build` | Exit 0; Vite transformed 2,241 modules. Five unresolved Geist font warnings and a 718.28 kB chunk warning remain non-blocking |
| `python /app/scripts/pilot_foundation_smoke.py` in the live backend | Passed; created `OP-202607-000078`, `OP-202607-000079`, and `IT-202607-000030` |

The permission audit is route-metadata evidence, not proof that every queryset
is scoped. The permission matrix pairs it with current view logic and focused
authorization tests.

## Accepted implementation and independent review outcomes

Independent review returned PASS for each of these areas:

- **Identity:** verified-token subjects are authoritative, a new subject cannot
  relink an existing authoritative username, and inactive identities fail
  closed across authentication, scope, superuser, and matter-validation paths.
- **Tickets and frontend:** ticket content, work-state, transition, IT-child,
  and related mutations revalidate canonical scope on locked rows. Queue and
  Kanban routing is domain-aware, unavailable actions are hidden, and stale
  reloads refresh ticket and activity state.
- **Attachments:** intake validates bounded batch size, type, extension, and
  content signatures before storage. Batches are atomic, upload authority is
  rechecked on the locked ticket, and cleanup deletes only an exact owned
  object version.
- **SLA:** calendar-local business time, pause entitlement, exact-deadline
  breach behavior, legacy-row fail-closed recovery, and evaluator concurrency
  use the corrected time semantics.
- **Retention:** legal holds preserve complete ticket graphs, the database run
  is atomic, exact-version object cleanup is queued transactionally, and final
  disposal certificates reflect committed truth only after cleanup succeeds.
- **Channels:** email and WhatsApp webhooks are signed, freshness-checked,
  replay-protected, and account/domain-bound before state changes. Outbound
  WhatsApp derives recipient and account from an authorized ticket and checks
  consent and approved templates.

The inbound-email HTML sanitizer also remains covered through persisted
message content using Bleach 6.4.0.

## Migration state and SLA 0004 reconciliation

All migrations in the final source were applied to the live pilot database,
and fresh deployments and the current live rows use the corrected SLA time
semantics.

One exception must remain visible. If another environment applied an earlier
revision of `sla.0004_backfill_paused_remaining_business_seconds` during this
unshipped implementation sequence, its affected paused SLA rows need manual
reconciliation. Django already records that migration name as applied and will
not rerun the revised data operation automatically. This caveat does not apply
to fresh deployments or the current live pilot rows.

## Dirty-worktree qualification

The authorized dirty worktree is Ruff-clean because it contains pre-existing
user-owned cleanup hunks that were deliberately left unstaged. Committed
`HEAD` without those overlays still has exactly 73 findings: 32 `F401`, 23
`I001`, 12 `UP017`, 4 `F811`, and 2 `UP035`. A fresh clone is therefore not yet
Ruff-clean, and no unrelated user hunk was included in the implementation
commits.

## Manual browser and visual verification

Not performed. A supported browser-verification capability was unavailable in
the environment. No desktop/mobile route, focus, overflow, empty/error,
permission, validation, stale-conflict, or visual-quality claim is made here.

## Open release blockers

- Reproducible clean-checkout Ruff: the 73 findings itemized above remain.
- Browser, accessibility, and visual QA: unavailable and therefore not passed.
- Production WhatsApp activation: a leased idempotent dispatch/retry worker and
  API-retry deduplication are not implemented. The current synchronous dispatch
  path must not be activated for production.
- Production TLS certificates and production secret-manager integration: no
  operator evidence supplied.
- Signed DPIA/data-protection approval: no owner evidence supplied.
- Penetration test and security acceptance: no external report supplied.
- External provider approvals and production credentials, including Meta
  WhatsApp and e-Estate dependencies: no owner evidence supplied.
- Product, technical, security, operations, records, and data-protection owner
  sign-off: not supplied.
- Role-based UAT, restore drills, and representative load/concurrency evidence
  remain open.

Because these gates are open, this evidence does not label the application
pilot-ready or the Plan 4 completion gate complete.
