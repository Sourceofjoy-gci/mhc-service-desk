# Pilot Foundation 1: Secure Access and Collections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish production-safe authentication, route protection, domain-safe reporting, a consistent error contract, and deterministic paginated queues.

**Architecture:** Backend authorization is centralized in scope/query helpers and applied explicitly to reporting and ticket collections. The React application gains a single authentication provider that supplies refreshed Keycloak tokens to a retry-bounded API client, while public and staff routes render through separate shells. Collection adapters accept legacy arrays during rollout but expose one canonical page type to UI code.

**Tech Stack:** Django 5.2, Django REST Framework 3.15, pytest/pytest-django, React 18, React Router 6, TanStack Query 5, Keycloak JS 25, TypeScript 5.6, Vitest 2, Testing Library.

## Global Constraints

- Preserve all unrelated pre-existing working-tree changes; stage only files named by the current task.
- The listed file-level `git add` commands apply only to paths that were clean at task start. For an already-dirty path, stage only task-owned hunks after reviewing `git diff --cached`; if a hunk cannot be separated from pre-existing work, leave that path uncommitted rather than include someone else's changes.
- Keep development authentication available only when Vite mode is `development`, `VITE_DEV_AUTH=1`, and backend `DEBUG=True`.
- Treat auditors as read-only and security responders as restricted-ticket-only across Operational and IT unless they also hold a broader group.
- Return new and updated API errors as `{code, detail, fields, correlation_id}`.
- Use the canonical cursor envelope `{next, previous, results}` while temporarily accepting legacy arrays in frontend adapters.
- Follow test-driven development: observe each new test fail for the intended reason before writing production code.
- Do not change public intake behavior or the existing visual design system.

---

### Task 1: Enforce explicit domain scopes and restricted-only security access

**Files:**
- Modify: `backend/apps/identity_access/scope.py`
- Modify: `backend/apps/identity_access/tests/test_scope.py`
- Create: `backend/apps/identity_access/tests/test_authentication.py`
- Create: `backend/apps/reporting/tests/test_permissions.py`
- Modify: `backend/apps/reporting/views.py`
- Modify: `backend/apps/reporting/flow.py`
- Modify: `backend/apps/tickets/views.py`
- Create: `backend/apps/tickets/tests/test_scope_api.py`
- Modify: `infrastructure/keycloak/realm-mhc.json`

**Interfaces:**
- Produces: `Scope(domain, office_id=None, service_id=None, queue_id=None, restricted_only=False)`.
- Produces: `is_auditor(user) -> bool`, `has_unrestricted_domain_scope(user, domain) -> bool`, and `scope_ticket_queryset(user, queryset) -> QuerySet[Ticket]`.
- Consumes later: ticket list, attachments, activity, exports, and lifecycle endpoints all use `scope_ticket_queryset`.

- [ ] **Step 1: Write failing scope tests**

Add tests proving that security responders receive restricted-only Operational and IT scopes, that those scopes do not authorize domain dashboards, that a combined `security-responders` + `ops-agents` identity retains normal Operational access, and that auditors cannot use unsafe methods:

```python
def test_security_responder_scopes_are_restricted_only():
    user = type("U", (), {
        "is_authenticated": True,
        "is_superuser": False,
        "_groups": ["security-responders"],
    })()
    scopes = get_user_scopes(user)
    assert {(scope.domain, scope.restricted_only) for scope in scopes} == {
        ("operational", True),
        ("it", True),
    }
    assert not has_unrestricted_domain_scope(user, "operational")


def test_broader_group_wins_over_restricted_only_scope():
    user = type("U", (), {
        "is_authenticated": True,
        "is_superuser": False,
        "_groups": ["security-responders", "ops-agents"],
    })()
    assert has_unrestricted_domain_scope(user, "operational")
    assert not has_unrestricted_domain_scope(user, "it")
```

Add a queryset test with one normal and one restricted ticket per domain. Assert a security responder sees only both restricted tickets; an Operational agent sees normal Operational tickets but not restricted ones; and an Operational supervisor sees both Operational tickets.

- [ ] **Step 2: Run the focused scope tests and verify the intended failure**

Run:

```powershell
Set-Location backend
pytest apps/identity_access/tests/test_scope.py -q
```

Expected: FAIL because `Scope.restricted_only`, `has_unrestricted_domain_scope`, and `scope_ticket_queryset` do not exist.

- [ ] **Step 3: Implement the scope primitives**

Extend the immutable scope type and add explicit helpers. Normalize duplicate domain scopes so an unrestricted scope supersedes a restricted-only scope:

```python
@dataclass(frozen=True)
class Scope:
    domain: str
    office_id: str | None = None
    service_id: str | None = None
    queue_id: str | None = None
    restricted_only: bool = False

    def matches(self, other: "Scope") -> bool:
        if self.domain == "admin":
            return True
        if self.domain != other.domain:
            return False
        if self.restricted_only and not other.restricted_only:
            return False
        if self.office_id and other.office_id and self.office_id != other.office_id:
            return False
        if self.service_id and other.service_id and self.service_id != other.service_id:
            return False
        if self.queue_id and other.queue_id and self.queue_id != other.queue_id:
            return False
        return True


def is_auditor(user) -> bool:
    return "auditors" in set(getattr(user, "_groups", []) or [])


def has_unrestricted_domain_scope(user, domain: str) -> bool:
    user._scopes = get_user_scopes(user)
    return any(
        scope.domain == "admin"
        or (scope.domain == domain and not scope.restricted_only)
        for scope in user._scopes
    )
```

`get_user_scopes` must add restricted-only scopes for `security-responders`. Add `scope_ticket_queryset` using one `Q` branch per scope: constrain domain and every non-null office/service/queue identifier; restricted-only branches also require `confidentiality="restricted"`; unrestricted branches exclude restricted records unless `can_view_restricted(user)` succeeds. Return `.none()` when no ticket scope exists.

Update `ScopePermission.has_permission` to reject non-safe methods when `is_auditor(request.user)` is true.

Replace `TicketViewSet.get_queryset`'s local domain builder with `scope_ticket_queryset(self.request.user, super().get_queryset())`. In `test_scope_api.py`, assert a security responder lists only restricted Operational/IT tickets and cannot retrieve a normal ticket; an agent sees only normal in-domain tickets; and a supervisor sees normal and restricted tickets in their domain.

Add an authentication regression test proving a `Bearer dev:pilot:ops-agents` token authenticates with `DEBUG=True` but raises `AuthenticationFailed` with `DEBUG=False`; patch JWKS access in the production-mode assertion so the test cannot make a network request.

Add `security-responders` to the imported Keycloak realm's top-level groups with path `/security-responders`. Keep the group-membership mapper's `full.path=false` setting so backend and frontend receive the exact group names used by permission helpers.

- [ ] **Step 4: Write failing reporting permission tests**

In `backend/apps/reporting/tests/test_permissions.py`, use `APIRequestFactory`, `force_authenticate`, and request-local `_groups` to cover this table:

```python
@pytest.mark.parametrize(
    ("groups", "view", "expected"),
    [
        (["ops-agents"], operational_dashboard, 200),
        (["ops-agents"], it_dashboard, 403),
        (["it-agents"], operational_dashboard, 403),
        (["it-agents"], it_dashboard, 200),
        (["security-responders"], operational_dashboard, 403),
        (["security-responders"], it_dashboard, 403),
        (["auditors"], operational_dashboard, 200),
        (["auditors"], it_dashboard, 200),
        (["system-admins"], operational_dashboard, 200),
        (["system-admins"], it_dashboard, 200),
    ],
)
def test_dashboard_domain_permissions(groups, view, expected, user_factory):
    request = APIRequestFactory().get("/reports/dashboard")
    user = user_factory(groups=groups)
    force_authenticate(request, user=user)
    assert view(request).status_code == expected
```

Define `user_factory` in the same test module using `User.objects.create(username=f"user-{uuid4().hex}", keycloak_subject=f"subject-{uuid4().hex}")` and set `user._groups = groups` before returning it. Persistent group snapshots are added later in Plan 2 and are not a dependency of this authorization fix.

Add CSV tests asserting an Operational user cannot export IT rows, an IT user cannot export Operational rows, and a security responder exports restricted rows only. Add equivalent authorization tests for `flow_metrics`.

- [ ] **Step 5: Run the reporting tests and verify cross-domain failures**

Run:

```powershell
Set-Location backend
pytest apps/reporting/tests/test_permissions.py -q
```

Expected: FAIL because both dashboard functions currently accept any authenticated user and export/flow do not apply the restricted-only helper.

- [ ] **Step 6: Apply scope helpers to every report**

At the start of each domain dashboard, call `attach_scopes(request)` and return DRF `PermissionDenied(code="domain_scope_required")` unless `has_unrestricted_domain_scope(request.user, domain)` succeeds. Replace the export's inline domain builder with:

```python
qs = scope_ticket_queryset(
    request.user,
    Ticket.objects.select_related("status", "requester", "service", "office"),
).order_by("-created_at", "-id")
```

Apply the same scoped base queryset in `flow_metrics` before aggregation. A requested `domain` query parameter outside the caller's unrestricted domains returns `403`; without a domain parameter, aggregates include only the scoped queryset.

- [ ] **Step 7: Run focused tests and commit**

Run:

```powershell
Set-Location backend
pytest apps/identity_access/tests/test_scope.py apps/reporting/tests/test_permissions.py -q
pytest apps/identity_access/tests/test_authentication.py apps/tickets/tests/test_scope_api.py -q
ruff check apps/identity_access/scope.py apps/reporting/views.py apps/reporting/flow.py apps/tickets/views.py apps/identity_access/tests/test_scope.py apps/identity_access/tests/test_authentication.py apps/reporting/tests/test_permissions.py apps/tickets/tests/test_scope_api.py
```

Expected: all commands exit 0.

Commit only the five task files:

```powershell
git add backend/apps/identity_access/scope.py backend/apps/identity_access/tests/test_scope.py backend/apps/identity_access/tests/test_authentication.py backend/apps/reporting/tests/test_permissions.py backend/apps/reporting/views.py backend/apps/reporting/flow.py backend/apps/tickets/views.py backend/apps/tickets/tests/test_scope_api.py infrastructure/keycloak/realm-mhc.json
git commit -m "fix(auth): enforce domain report scopes"
```

---

### Task 2: Standardize API errors and deterministic cursor pagination

**Files:**
- Create: `backend/apps/identity_access/pagination.py`
- Modify: `backend/apps/identity_access/exception_handlers.py`
- Create: `backend/apps/identity_access/tests/test_api_contracts.py`
- Modify: `backend/config/settings/base.py`
- Modify: `backend/apps/tickets/views.py`
- Create: `backend/apps/tickets/tests/test_api_collections.py`

**Interfaces:**
- Produces: `SafeCursorPagination` choosing an existing model ordering from `created_at`, `updated_at`, then primary key, plus `TicketCursorPagination` with validated queue sort mappings.
- Produces: canonical errors `{code: str, detail: str, fields: dict[str, list[str]], correlation_id: str}`.
- Produces: `GET /api/v1/tickets/` canonical cursor envelope.

- [ ] **Step 1: Write failing error-contract tests**

Call `problem_details_handler` with DRF `ValidationError`, `PermissionDenied`, and `NotAuthenticated` contexts whose request has `correlation_id="corr-123"`. Assert exact keys and values:

```python
def test_validation_error_uses_common_contract():
    request = APIRequestFactory().post("/tickets/")
    request.correlation_id = "corr-123"
    response = problem_details_handler(
        ValidationError({"title": ["This field is required."]}),
        {"request": request},
    )
    assert response.status_code == 400
    assert response.data == {
        "code": "invalid",
        "detail": "Request failed validation",
        "fields": {"title": ["This field is required."]},
        "correlation_id": "corr-123",
    }
```

- [ ] **Step 2: Run the error tests and verify the old RFC-shaped response fails**

Run `pytest backend/apps/identity_access/tests/test_api_contracts.py -q` from the repository root.

Expected: FAIL because the handler currently returns `type`, `title`, `status`, and `errors`.

- [ ] **Step 3: Implement the common error adapter**

Preserve DRF status codes while normalizing list/dict/string details. Use `exc.get_codes()` to derive the stable code, `response.data` for field messages, and `context["request"].correlation_id` when available. Ensure all field messages are serialized as strings and `fields={}` for non-validation failures.

- [ ] **Step 4: Write failing pagination boundary tests**

Create at least 55 tickets with identical `created_at` values, request `/api/v1/tickets/`, follow `next`, and assert:

```python
assert set(first.data) == {"next", "previous", "results"}
assert len(first.data["results"]) == 50
assert len(second.data["results"]) == 5
numbers = [row["number"] for row in first.data["results"] + second.data["results"]]
assert len(numbers) == len(set(numbers)) == 55
```

Add a lightweight model/view test proving pagination does not fail when a queryset model has no `created` field. Assert the fallback ordering ends in the model primary key.

Add queue ordering tests for `sort=priority`, `sort=created`, and `sort=updated`; assert the first page follows the complete server ordering and remains stable across the next cursor. Assert an unknown sort falls back to recent-first ordering.

- [ ] **Step 5: Run pagination tests and verify the current list shape fails**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_api_collections.py apps/identity_access/tests/test_api_contracts.py -q
```

Expected: FAIL because `TicketViewSet.pagination_class=None` returns an array and the global paginator assumes DRF's default `-created` field.

- [ ] **Step 6: Implement safe cursor pagination**

Create:

```python
from rest_framework.pagination import CursorPagination


class SafeCursorPagination(CursorPagination):
    page_size = 50

    def get_ordering(self, request, queryset, view):
        names = {field.name for field in queryset.model._meta.concrete_fields}
        primary_key = queryset.model._meta.pk.name
        if "created_at" in names:
            return ("-created_at", f"-{primary_key}")
        if "updated_at" in names:
            return ("-updated_at", f"-{primary_key}")
        return (f"-{primary_key}",)


class TicketCursorPagination(SafeCursorPagination):
    SORTS = {
        "priority": ("priority", "-created_at", "-id"),
        "created": ("-created_at", "-id"),
        "updated": ("-updated_at", "-id"),
    }

    def get_ordering(self, request, queryset, view):
        return self.SORTS.get(request.query_params.get("sort", "priority"), self.SORTS["priority"])
```

Set `DEFAULT_PAGINATION_CLASS` to `SafeCursorPagination` and set `TicketViewSet.pagination_class = TicketCursorPagination`. Keep its default scoped queryset ordering aligned with the paginator.

- [ ] **Step 7: Run contract tests, migration check, and commit**

Run:

```powershell
Set-Location backend
pytest apps/identity_access/tests/test_api_contracts.py apps/tickets/tests/test_api_collections.py -q
python manage.py makemigrations --check --dry-run
ruff check apps/identity_access/pagination.py apps/identity_access/exception_handlers.py apps/identity_access/tests/test_api_contracts.py apps/tickets/views.py apps/tickets/tests/test_api_collections.py config/settings/base.py
```

Expected: tests pass, migration check reports no changes, and Ruff exits 0.

Commit:

```powershell
git add backend/apps/identity_access/pagination.py backend/apps/identity_access/exception_handlers.py backend/apps/identity_access/tests/test_api_contracts.py backend/config/settings/base.py backend/apps/tickets/views.py backend/apps/tickets/tests/test_api_collections.py
git commit -m "fix(api): stabilize errors and pagination"
```

---

### Task 3: Add the frontend test harness and authentication provider

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/vite.config.ts`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/test/render.tsx`
- Modify: `frontend/src/features/auth/keycloak.ts`
- Create: `frontend/src/features/auth/AuthProvider.tsx`
- Create: `frontend/src/features/auth/AuthProvider.test.tsx`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/api.test.ts`
- Modify: `frontend/src/main.tsx`

**Interfaces:**
- Produces: `AuthContextValue` with `state`, `user`, `isDevAuth`, `getAccessToken(forceRefresh?)`, `login(returnTo?)`, and `logout()`.
- Produces: `useAuth() -> AuthContextValue`.
- Produces: `configureApiAuth(adapter: ApiAuthAdapter) -> void` and an API client that retries one authenticated `401` after refresh.

- [ ] **Step 1: Install only the missing test runtime**

Run from `frontend`:

```powershell
npm.cmd install --save-dev jsdom@^25.0.0 @testing-library/user-event@^14.5.2
```

Update `vite.config.ts` with `test: { environment: "jsdom", setupFiles: "./src/test/setup.ts", clearMocks: true }`. In `setup.ts`, import `@testing-library/jest-dom/vitest`, restore mocks after each test, and install deterministic `matchMedia`, `ResizeObserver`, `PointerEvent`, and `Element.prototype.scrollIntoView` shims needed by the existing Base UI controls.

Create `render.tsx` with `renderWithProviders(ui, {route="/"})`: construct a new `QueryClient` with retries disabled, call `window.history.pushState({}, "", route)`, and render the element inside `QueryClientProvider` and `MemoryRouter initialEntries={[route]}`. Return the Testing Library result plus the query client so tests can assert cache updates without sharing state.

- [ ] **Step 2: Write failing API retry tests**

Define the adapter contract in the test:

```typescript
const adapter = {
  getAccessToken: vi.fn().mockResolvedValueOnce("old-token").mockResolvedValueOnce("new-token"),
  refresh: vi.fn().mockResolvedValue(true),
  login: vi.fn().mockResolvedValue(undefined),
};
configureApiAuth(adapter);
```

Mock `fetch` to return `401` then `200`. Assert two requests, the second `Authorization` header is `Bearer new-token`, and `refresh` is called once. Add tests that a second `401` calls `login(window.location.pathname + window.location.search)` once, `403` throws `ApiError` without login, and `{auth: false}` sends no authorization header.

- [ ] **Step 3: Run API tests and verify token wiring is absent**

Run `npm.cmd test -- src/lib/api.test.ts` from `frontend`.

Expected: FAIL because `configureApiAuth`, refresh retry, and public-request options do not exist.

- [ ] **Step 4: Implement retry-bounded API authentication**

Export these types and functions from `api.ts`:

```typescript
export interface ApiAuthAdapter {
  getAccessToken(forceRefresh?: boolean): Promise<string | null>;
  refresh(): Promise<boolean>;
  login(returnTo: string): Promise<void>;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  auth?: boolean;
  retry401?: boolean;
  headers?: Record<string, string>;
}
```

Keep one module-local adapter. For protected calls, await its token and add `Bearer`. On the first `401`, call `refresh`; when true, call the request once more with `retry401:false`. Otherwise call `login` with the current path and throw the original `ApiError`. Do not set JSON `Content-Type` when `body` is `FormData`.

Mark `ticketsApi.publicIntake` and every genuinely public health/requester helper with `auth:false`; protected catalogue, reporting, ticket, and attachment calls retain the default `auth:true`. The development provider returns raw token `dev:demo:ops-agents`, allowing the API client to add the sole `Bearer` prefix.

- [ ] **Step 5: Write failing authentication-provider tests**

Mock the Keycloak adapter and assert:

- initialization renders a loading state first;
- authenticated state exposes subject, username, display name, groups, and expiry from token claims/profile;
- unauthenticated state does not call login until a protected route requests it;
- `getAccessToken(true)` calls `updateToken(30)` and returns the refreshed token;
- development mode returns the explicit dev identity and token only when `DEV_AUTH_ENABLED` is true;
- importing the adapter with `MODE="production"` and `VITE_DEV_AUTH="1"` keeps development authentication disabled;
- `login("/tickets?priority=P1")` stores that return path before redirecting.

- [ ] **Step 6: Run provider tests and verify failure**

Run `npm.cmd test -- src/features/auth/AuthProvider.test.tsx`.

Expected: FAIL because the provider and hook do not exist.

- [ ] **Step 7: Implement the provider and Keycloak adapter**

Use this stable user shape:

```typescript
export interface AuthUser {
  subject: string;
  username: string;
  displayName: string;
  groups: string[];
}

export interface AuthContextValue {
  state: "loading" | "authenticated" | "unauthenticated" | "error";
  user: AuthUser | null;
  error: string | null;
  isDevAuth: boolean;
  getAccessToken(forceRefresh?: boolean): Promise<string | null>;
  login(returnTo?: string): Promise<void>;
  logout(): Promise<void>;
}
```

Move all `initKeycloak` state ownership into `AuthProvider`; `LoginPage` will consume the provider in Task 4. After a successful initialization, call `loadUserProfile()` once. Parse groups from `tokenParsed.groups`, subject from `tokenParsed.sub`, and display name from `profile.firstName`/`lastName` or username. Register the provider's token/refresh/login functions with `configureApiAuth`. After authentication, validate a stored return path begins with `/`, remove it from session storage, and navigate there with `replace:true`; otherwise remain on the current route. Wrap `App` with `AuthProvider` inside `BrowserRouter` in `main.tsx`.

- [ ] **Step 8: Run frontend tests, typecheck, and commit**

Run:

```powershell
Set-Location frontend
npm.cmd test -- src/lib/api.test.ts src/features/auth/AuthProvider.test.tsx
npm.cmd run typecheck
npm.cmd run lint
```

Expected: all commands exit 0.

Commit:

```powershell
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/src/test/setup.ts frontend/src/test/render.tsx frontend/src/features/auth/keycloak.ts frontend/src/features/auth/AuthProvider.tsx frontend/src/features/auth/AuthProvider.test.tsx frontend/src/lib/api.ts frontend/src/lib/api.test.ts frontend/src/main.tsx
git commit -m "feat(auth): wire Keycloak sessions to API requests"
```

---

### Task 4: Split public and protected route shells

**Files:**
- Create: `frontend/src/features/auth/ProtectedRoute.tsx`
- Create: `frontend/src/features/auth/PermissionPage.tsx`
- Modify: `frontend/src/features/auth/LoginPage.tsx`
- Create: `frontend/src/components/public-shell.tsx`
- Modify: `frontend/src/components/app-shell.tsx`
- Modify: `frontend/src/app/App.tsx`
- Create: `frontend/src/app/App.test.tsx`

**Interfaces:**
- Consumes: `useAuth()` from Task 3.
- Produces: public routes rendered under `PublicShell`; staff routes rendered by `ProtectedRoute` under `AppShell`.
- Produces: `/forbidden` permission state that never redirects to Keycloak.

- [ ] **Step 1: Write failing route-group tests**

Render `App` in `MemoryRouter` with mocked auth context and assert:

```typescript
it.each(["/login", "/public", "/health"])(
  "%s renders without staff navigation",
  async (path) => {
    renderApp(path, unauthenticatedAuth);
    expect(screen.queryByRole("navigation", { name: /ticket workspace/i })).not.toBeInTheDocument();
  },
);

it("protects the ticket queue and preserves its return path", async () => {
  const auth = makeAuth({ state: "unauthenticated" });
  renderApp("/tickets?priority=P1", auth);
  await waitFor(() => expect(auth.login).toHaveBeenCalledWith("/tickets?priority=P1"));
  expect(screen.queryByText("Queue")).not.toBeInTheDocument();
});
```

Add tests for loading (no protected content flash), authenticated staff shell identity, development badge visibility, logout, and `/forbidden` rendering without `login`.

- [ ] **Step 2: Run route tests and verify public routes currently inherit staff chrome**

Run `npm.cmd test -- src/app/App.test.tsx` from `frontend`.

Expected: FAIL because all routes are wrapped in `AppShell` and it hard-codes a development identity.

- [ ] **Step 3: Implement route guards and two shells**

`ProtectedRoute` behavior:

```typescript
if (state === "loading") return <AuthLoadingState />;
if (state === "error") return <AuthErrorState error={error} />;
if (state === "unauthenticated") return <LoginRedirect returnTo={location.pathname + location.search} />;
return <Outlet />;
```

Use a one-shot effect inside `LoginRedirect` so React Strict Mode cannot start duplicate logins. Arrange routes with nested layout elements: public routes under `PublicShell`; staff routes under `<ProtectedRoute />` then `AppShell`. Keep `/forbidden` in the public layout so a `403` state remains visible even if a session later expires.

Update `AppShell.UserMenu` to display `user.displayName`, derive initials, show a dev badge only when `isDevAuth`, and call `logout()`. Remove the inert search button until search has an implemented interaction. Update `LoginPage` to render provider state and call provider actions rather than initializing Keycloak itself.

- [ ] **Step 4: Run route tests, accessibility assertions, and static gates**

Run:

```powershell
Set-Location frontend
npm.cmd test -- src/app/App.test.tsx
npm.cmd run typecheck
npm.cmd run lint
```

Expected: all commands exit 0; public pages contain no staff nav and protected routes do not flash content.

- [ ] **Step 5: Commit the route boundary**

```powershell
git add frontend/src/features/auth/ProtectedRoute.tsx frontend/src/features/auth/PermissionPage.tsx frontend/src/features/auth/LoginPage.tsx frontend/src/components/public-shell.tsx frontend/src/components/app-shell.tsx frontend/src/app/App.tsx frontend/src/app/App.test.tsx
git commit -m "feat(auth): protect staff routes and isolate public pages"
```

---

### Task 5: Consume pagination and synchronize queue/report state with the URL

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/collections.ts`
- Create: `frontend/src/lib/collections.test.ts`
- Modify: `frontend/src/features/tickets/QueuePage.tsx`
- Create: `frontend/src/features/tickets/QueuePage.test.tsx`
- Modify: `frontend/src/features/reports/DashboardPage.tsx`
- Create: `frontend/src/features/reports/DashboardPage.test.tsx`

**Interfaces:**
- Produces: `Page<T> = {next: string | null; previous: string | null; results: T[]}`.
- Produces: `normalizePage<T>(value: T[] | Page<T>) -> Page<T>`.
- Produces: `ticketsApi.list(params) -> Promise<Page<TicketSummary>>` and `ticketsApi.dashboard(domain) -> Promise<DashboardData>`.

- [ ] **Step 1: Write failing collection-adapter tests**

```typescript
it("normalizes a legacy array", () => {
  expect(normalizePage([{ id: "1" }])).toEqual({
    next: null,
    previous: null,
    results: [{ id: "1" }],
  });
});

it("preserves a canonical page", () => {
  const page = { next: "/api?cursor=n", previous: null, results: [{ id: "1" }] };
  expect(normalizePage(page)).toEqual(page);
});
```

- [ ] **Step 2: Write failing queue URL tests**

Start at `/tickets?domain=operational&status=triage&priority=P1&search=estate&sort=updated&cursor=abc`. Assert controls reflect the URL, the API receives all server filters plus cursor, changing domain/priority/sort removes cursor, clearing filters preserves only the chosen sort, next/previous buttons use the cursor URLs, and ticket links retain a `returnTo` location state. Assert users with one ordinary domain cannot select the other domain, while administrators and auditors may select either.

- [ ] **Step 3: Run collection and queue tests and verify failure**

Run `npm.cmd test -- src/lib/collections.test.ts src/features/tickets/QueuePage.test.tsx`.

Expected: FAIL because the API type is an array and queue state is local-only.

- [ ] **Step 4: Implement canonical collection and URL state**

Add:

```typescript
export interface Page<T> {
  next: string | null;
  previous: string | null;
  results: T[];
}

export function normalizePage<T>(value: T[] | Page<T>): Page<T> {
  return Array.isArray(value)
    ? { next: null, previous: null, results: value }
    : value;
}
```

Make `ticketsApi.list` and `servicesApi.list` normalize their responses. Add `apiUrl<T>(absoluteOrRelativeUrl)` so the opaque `next` and `previous` URLs can be requested without interpreting the cursor value. Replace queue `useState` filters with `useSearchParams`; use `replace:true` for typing changes and clear `cursor` whenever status, priority, search, sort, or domain changes. A pagination click copies the opaque `cursor` query value from the server URL into the queue URL, and the next list request sends it unchanged. Render a domain selector only for identities with multiple ordinary domains, Previous/Next controls from the page links, and `data.results` for cards. Remove client-only sorting and the inaccurate SLA sort option; `sort` is sent to the backend so ordering is correct across page boundaries.

- [ ] **Step 5: Add domain-aware dashboard tests and implementation**

Test that an Operational identity defaults to Operational, an IT identity defaults to IT, an administrator may select either domain, and a `403 ApiError` renders `PermissionPage` content without initiating login. Change `ticketsApi.dashboard(domain)` to call `/reports/dashboard/${domain}` and drive dashboard domain selection through `?domain=` constrained by the authenticated user's groups.

- [ ] **Step 6: Run frontend verification and commit**

Run:

```powershell
Set-Location frontend
npm.cmd test -- src/lib/collections.test.ts src/features/tickets/QueuePage.test.tsx src/features/reports/DashboardPage.test.tsx
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
```

Expected: all commands exit 0.

Commit:

```powershell
git add frontend/src/lib/api.ts frontend/src/lib/collections.ts frontend/src/lib/collections.test.ts frontend/src/features/tickets/QueuePage.tsx frontend/src/features/tickets/QueuePage.test.tsx frontend/src/features/reports/DashboardPage.tsx frontend/src/features/reports/DashboardPage.test.tsx
git commit -m "feat(queue): add URL-synced cursor navigation"
```

---

## Plan 1 Completion Gate

Run fresh commands from the repository root:

```powershell
Set-Location backend
pytest apps/identity_access/tests apps/reporting/tests apps/tickets/tests/test_api_collections.py -q
ruff check apps/identity_access apps/reporting apps/tickets/tests/test_api_collections.py config/settings/base.py
Set-Location ../frontend
npm.cmd test
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
```

Expected: every command exits 0. Manually confirm `/public`, `/health`, and `/login` have no staff shell; unauthenticated `/tickets` triggers one login; and Operational/IT dashboard cross-access returns `403`.
