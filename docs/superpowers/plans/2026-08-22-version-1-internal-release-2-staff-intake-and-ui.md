# Version 1 Staff Intake and UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver atomic, idempotent call and walk-in capture and an authenticated staff UI centred on read-only queue/search retrieval.

**Architecture:** Rename the existing assisted-intake contract and move orchestration into a focused service. A durable `(actor_subject, idempotency_key)` receipt owns exactly one ticket, while the React client retains one key across safe retries and uses queue/search instead of requester tracking.

**Tech Stack:** Django 5.2, Django REST Framework, PostgreSQL, React 18, TypeScript, TanStack Query, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-08-22-version-1-internal-staff-release-design.md`

## Global Constraints

- The only assisted-intake channels are exactly `call` and `walk_in`.
- Intake requires an authenticated active user with Operational authority matching the selected office and service and without a queue restriction.
- Contact, ticket, custody/audit and SLA effects commit atomically.
- `X-Idempotency-Key` is required and scoped to the authenticated actor.
- Staff queue/search GET requests must not mutate ticket state.
- The requester-style Track ticket route and navigation are absent from Version 1.
- Use test-first changes and commit only the files listed by each task.

---

### Task 1: Strict staff-intake serializer and route

**Files:**
- Modify: `backend/apps/tickets/api.py`
- Modify: `backend/apps/tickets/views.py`
- Modify: `backend/apps/tickets/urls.py`
- Modify: `backend/apps/tickets/tests/test_intake_api.py`

**Interfaces:**
- Produces: `StaffIntakeSerializer`
- Produces: `POST /api/v1/tickets/staff/intake/`, route name `tickets-staff-intake`
- Removes: `PublicIntakeSerializer`, `public_intake`, route name `tickets-public-intake`

- [ ] **Step 1: Rename tests and add channel boundary cases**

Change the helper to reverse `tickets-staff-intake`. Add parameterized tests which
post `web`, `email`, `whatsapp`, `internal`, an empty value and an omitted value.
Assert `400` and no new `Contact`, `Ticket`, `AuditEvent`, custody event or SLA
instance. Add an anonymous `401` test.

- [ ] **Step 2: Run the intake test and observe failure**

```powershell
docker compose exec -T backend pytest apps/tickets/tests/test_intake_api.py -q
```

Expected: the new route is missing and the old serializer accepts omitted, web and
email channels.

- [ ] **Step 3: Implement the strict contract**

Rename the serializer and make channel required:

```python
class StaffIntakeSerializer(serializers.Serializer[dict[str, object]]):
    channel = serializers.ChoiceField(
        choices=(Ticket.Channel.CALL, Ticket.Channel.WALK_IN),
        required=True,
    )
```

Rename the view to `staff_intake`, preserve `IsAuthenticated` and
`ScopePermission`, and register only:

```python
path("tickets/staff/intake/", views.staff_intake, name="tickets-staff-intake")
```

Remove the old public path without an alias.

- [ ] **Step 4: Run intake and URL tests**

```powershell
docker compose exec -T backend pytest apps/tickets/tests/test_intake_api.py apps/health/tests/test_version1_routes.py -q
```

Expected: both channel success cases pass, invalid channels return `400`, and the
old public path is unresolved.

- [ ] **Step 5: Commit the explicit staff contract**

```powershell
git add backend/apps/tickets/api.py backend/apps/tickets/views.py backend/apps/tickets/urls.py backend/apps/tickets/tests/test_intake_api.py
git commit -m "feat: expose strict staff-assisted intake"
```

### Task 2: Durable intake idempotency and atomic orchestration

**Files:**
- Create: `backend/apps/tickets/staff_intake.py`
- Create: `backend/apps/tickets/migrations/0014_staffintakesubmission.py`
- Create: `backend/apps/files/uploads.py`
- Modify: `backend/apps/tickets/models.py`
- Modify: `backend/apps/tickets/views.py`
- Modify: `backend/apps/files/views.py`
- Modify: `backend/apps/files/tests/test_views.py`
- Modify: `backend/apps/tickets/tests/test_intake_api.py`
- Create: `backend/apps/tickets/tests/test_staff_intake_concurrency.py`

**Interfaces:**
- Produces: `StaffIntakeSubmission(actor_subject, idempotency_key, request_hash, ticket, created_at)`
- Produces: `create_staff_intake(*, actor: User, data: Mapping[str, object], idempotency_key: str, ip_address: str) -> tuple[Ticket, bool]`
- Produces: `prepare_attachment_batch(files) -> tuple[PreparedAttachment, ...]`
- Produces: `store_attachment_batch(*, ticket: Ticket, prepared, actor_subject: str) -> tuple[Attachment, ...]`
- Consumes: `services.create_ticket`, `instantiate_slas`, custody/audit creation

- [ ] **Step 1: Write failing idempotency and rollback tests**

Cover:

```python
response = client.post(url, payload, HTTP_X_IDEMPOTENCY_KEY=str(uuid4()))
assert response.status_code == 201
```

Assert a missing or malformed key returns `400`; two identical requests with the
same actor/key return the same ticket reference and exactly one ticket, submission,
audit event, custody event and SLA set; the same actor/key with changed payload
returns `409`; two actors may reuse the same key. Patch SLA creation and audit
recording to raise and assert the whole transaction leaves no contact, ticket or
submission.

Add attachment cases for zero and five valid files, six files, a file above the
configured size limit, disallowed content, a malware result and a storage failure.
Assert valid files are linked to the one ticket and every rejected/failing batch
leaves no ticket, receipt, attachment row or stored object. A replay returns the
original attachment metadata without uploading again.

In the concurrency test, use `transaction=True`, two database connections and a
barrier to post the same key concurrently. Assert both responses identify one
ticket.

- [ ] **Step 2: Run the focused tests and observe failure**

```powershell
docker compose exec -T backend pytest apps/tickets/tests/test_intake_api.py apps/tickets/tests/test_staff_intake_concurrency.py -q
```

- [ ] **Step 3: Add the receipt model and migration**

Use this model contract:

```python
class StaffIntakeSubmission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor_subject = models.CharField(max_length=255)
    idempotency_key = models.CharField(max_length=64)
    request_hash = models.CharField(max_length=64)
    ticket = models.OneToOneField(
        Ticket,
        on_delete=models.PROTECT,
        related_name="staff_intake_submission",
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ticket_staff_intake_submission"
        constraints = [
            models.UniqueConstraint(
                fields=("actor_subject", "idempotency_key"),
                name="uniq_staff_intake_actor_key",
            ),
        ]
```

The nullable ticket permits claiming the idempotency key before creating business
records; a successful transaction always fills it.

- [ ] **Step 4: Extract one transactional intake service**

Extract attachment preparation/storage and compensating object cleanup from
`apps.files.views` into `apps.files.uploads` so ticket-detail upload and intake use
one policy implementation.

Canonicalize validated scalar input with sorted JSON and SHA-256. Include, in
original order, each prepared attachment's sanitized filename, content type, byte
size and SHA-256 content checksum. Inside
`transaction.atomic()`, claim or lock the receipt, reject a hash mismatch with a
typed conflict exception, return its ticket when already complete, then create or
update the contact, create the ticket, record custody/audit, instantiate SLA and
store the prepared attachments before attaching the ticket to the receipt. If the
database transaction fails after object storage succeeds, delete every object
written by this attempt.

The view validates a UUID-form `X-Idempotency-Key`, calls the service and returns
`201` for the first result and `200` for a replay. Do not catch an unexpected
transaction failure as success.

- [ ] **Step 5: Run migration, concurrency and integrity tests**

```powershell
docker compose exec -T backend python manage.py makemigrations --check --dry-run
docker compose exec -T backend pytest apps/tickets/tests/test_intake_api.py apps/tickets/tests/test_staff_intake_concurrency.py apps/tickets/tests/test_events.py apps/files/tests/test_views.py -q
```

Expected: no uncommitted model change and all focused tests pass.

- [ ] **Step 6: Commit atomic intake**

```powershell
git add backend/apps/tickets/models.py backend/apps/tickets/migrations/0014_staffintakesubmission.py backend/apps/tickets/staff_intake.py backend/apps/tickets/views.py backend/apps/tickets/tests/test_intake_api.py backend/apps/tickets/tests/test_staff_intake_concurrency.py backend/apps/files/uploads.py backend/apps/files/views.py backend/apps/files/tests/test_views.py
git commit -m "feat: make staff intake atomic and idempotent"
```

### Task 3: Frontend staff-intake client and retry key

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/features/tickets/ChannelIntakePage.tsx`
- Modify: `frontend/src/features/tickets/ChannelIntakePage.test.tsx`
- Modify: `frontend/src/lib/api.test.ts`

**Interfaces:**
- Produces: `StaffIntakeChannel = "call" | "walk_in"`
- Produces: `ticketsApi.staffIntake(data, files, idempotencyKey)`
- Consumes: `RequestOptions.headers`

- [ ] **Step 1: Write failing client and page tests**

Rename the harness method to `staffIntake`. Assert the API client posts to
`/tickets/staff/intake/` with:

```typescript
headers: { "X-Idempotency-Key": idempotencyKey }
```

Assert `channel` is a required `StaffIntakeChannel`. In the page test, simulate a
network failure followed by retry and assert both calls reuse one key. After a
successful capture and form reset, assert the next submission receives a new key.
Select five files and assert they are sent; select a sixth or an oversized file and
assert client validation prevents the request and moves focus to the file error.

- [ ] **Step 2: Run frontend tests and observe failure**

```powershell
docker compose run --rm --no-deps --build frontend npm test -- --run src/lib/api.test.ts src/features/tickets/ChannelIntakePage.test.tsx
```

- [ ] **Step 3: Implement the typed client and key lifecycle**

Define:

```typescript
export type StaffIntakeChannel = "call" | "walk_in";

staffIntake: (
  data: StaffIntakeRequest,
  files: readonly File[],
  idempotencyKey: string,
) =>
  api<StaffIntakeResponse>("/tickets/staff/intake/", {
    method: "POST",
    body: staffIntakeFormData(data, files),
    headers: { "X-Idempotency-Key": idempotencyKey },
  }),
```

Store the current key in a ref initialized with `crypto.randomUUID()`. Reuse it
after a transport error or unknown result; replace it only after a confirmed
success or a deliberate form reset that changes the logical request.

Build `FormData` with every scalar field and repeated `attachments` parts. Add an
accessible multi-file control whose `accept`, count and size checks mirror backend
policy; the backend remains authoritative for content and malware checks.

- [ ] **Step 4: Run tests, typecheck and lint**

```powershell
docker compose run --rm --no-deps --build frontend npm test -- --run src/lib/api.test.ts src/features/tickets/ChannelIntakePage.test.tsx
docker compose run --rm --no-deps --build frontend npm run typecheck
docker compose run --rm --no-deps --build frontend npm run lint
```

- [ ] **Step 5: Commit the staff client**

```powershell
git add frontend/src/lib/api.ts frontend/src/lib/api.test.ts frontend/src/features/tickets/ChannelIntakePage.tsx frontend/src/features/tickets/ChannelIntakePage.test.tsx
git commit -m "feat: submit idempotent staff intake from the ui"
```

### Task 4: Remove requester tracking and prove queue/search is read-only

**Files:**
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/components/app-shell.tsx`
- Create: `frontend/src/app/App.version1.test.tsx`
- Modify: `frontend/src/features/tickets/QueuePage.test.tsx`
- Modify: `backend/apps/tickets/tests/test_scope_api.py`

**Interfaces:**
- Removes: `/ticket-tracking` frontend route and **Track ticket** navigation item
- Preserves: `/tickets` queue/search and `/tickets/:number` detail

- [ ] **Step 1: Write failing Version 1 navigation tests**

Render `App` under authenticated test auth. Assert no link named `Track ticket`
exists and navigation to `/ticket-tracking` renders the not-found page. Assert
Queue, Kanban, Dashboard, Call and Walk-in links remain.

Add a backend test that records ticket timestamps, transition history, audit,
custody, notes and messages, performs list/search/sort/pagination GET requests, and
asserts every recorded value and count is unchanged.

- [ ] **Step 2: Run the focused tests and observe failure**

```powershell
docker compose exec -T backend pytest apps/tickets/tests/test_scope_api.py -q
docker compose run --rm --no-deps --build frontend npm test -- --run src/app/App.version1.test.tsx src/features/tickets/QueuePage.test.tsx
```

- [ ] **Step 3: Remove requester tracking from the Version 1 UI**

Delete the lazy import and route from `App.tsx`. Remove the `SearchCheck` import and
navigation item from `app-shell.tsx`. Do not remove queue search, filters, sorting,
pagination or ticket-detail links.

- [ ] **Step 4: Run backend and frontend tests**

Run the commands from Step 2.

Expected: the tracking route is absent, queue retrieval remains functional and no
GET request changes ticket data.

- [ ] **Step 5: Commit the internal retrieval surface**

```powershell
git add frontend/src/app/App.tsx frontend/src/components/app-shell.tsx frontend/src/app/App.version1.test.tsx frontend/src/features/tickets/QueuePage.test.tsx backend/apps/tickets/tests/test_scope_api.py
git commit -m "feat: centre version 1 on staff queue search"
```

### Task 5: Bound queue serialization queries before load testing

**Files:**
- Modify: `backend/apps/tickets/api.py`
- Modify: `backend/apps/tickets/views.py`
- Create: `backend/apps/tickets/tests/test_queue_query_budget.py`

**Interfaces:**
- Produces: queue list serialization with prefetched SLA instances
- Produces: request-local transition-code cache keyed by status and effective actor aliases

- [ ] **Step 1: Write a failing bounded-query test**

Create one and fifty visible tickets, call `TicketViewSet.list` under
`CaptureQueriesContext`, and assert the fifty-ticket request uses no more than six
queries above the one-ticket request. Assert response payloads still include
`sla_health` and `available_transition_codes`.

- [ ] **Step 2: Run the query-budget test and observe failure**

```powershell
docker compose exec -T backend pytest apps/tickets/tests/test_queue_query_budget.py -q
```

Expected: query count grows per ticket because SLA health and available transitions
query inside serializer methods.

- [ ] **Step 3: Prefetch SLA and cache transition results**

Add `prefetch_related("sla_instances")` to the list/board queryset. Make
`get_sla_health` use the prefetched collection without issuing a query.

Cache available transition codes in the serializer context using a key containing
the ticket status ID and `matching_actor_role_aliases(ticket, actor, snapshot=...)`.
The cache must remain request-local and must not combine actors or authorities.

- [ ] **Step 4: Run query, queue and workflow tests**

```powershell
docker compose exec -T backend pytest apps/tickets/tests/test_queue_query_budget.py apps/tickets/tests/test_api_collections.py apps/tickets/tests/test_workflow_capabilities.py -q
```

- [ ] **Step 5: Commit the bounded queue**

```powershell
git add backend/apps/tickets/api.py backend/apps/tickets/views.py backend/apps/tickets/tests/test_queue_query_budget.py
git commit -m "perf: bound staff queue serialization queries"
```
