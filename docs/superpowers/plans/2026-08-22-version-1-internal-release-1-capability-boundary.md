# Version 1 Capability Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Version 1 fail closed by omitting all public self-service, email and WhatsApp routes and jobs while preserving authenticated internal and infrastructure endpoints.

**Architecture:** A single `PUBLIC_SELF_SERVICE_ENABLED` Django setting defaults to `False`. Public URLs live in a separate URL module that is included only when the flag is true; the Version 1 production proxy denies the same route families as defence in depth.

**Tech Stack:** Django 5.2, Django REST Framework, django-environ, Docker Compose, Nginx, pytest.

**Spec:** `docs/superpowers/specs/2026-08-22-version-1-internal-staff-release-design.md`

## Global Constraints

- Version 1 keeps the API root, health endpoints, Keycloak, Prometheus and every authenticated internal API.
- `PUBLIC_SELF_SERVICE_ENABLED` defaults to `False`; missing configuration is fail-closed.
- Public requester, CSAT, public knowledge, email and WhatsApp routes return `404` in Version 1.
- Deferred application models and migrations remain installed.
- Do not add a compatibility alias for `/api/v1/tickets/public/intake/`.
- Use test-first changes and commit only the files listed by each task.

---

### Task 1: Release capability setting and production configuration

**Files:**
- Modify: `backend/config/settings/base.py`
- Modify: `backend/apps/health/tests/test_prod_settings.py`
- Modify: `.env.example`
- Modify: `docker-compose.prod.yml`
- Modify: `scripts/check_prod_compose.py`
- Test: `backend/apps/health/tests/test_prod_settings.py`
- Test: `scripts/check_prod_compose.py`

**Interfaces:**
- Consumes: `config.settings.base.env`
- Produces: `settings.PUBLIC_SELF_SERVICE_ENABLED: bool`
- Produces: production environment value `PUBLIC_SELF_SERVICE_ENABLED=false`

- [ ] **Step 1: Write failing settings and Compose assertions**

Add tests which import base settings with no capability variable and assert false,
then inspect the merged production Compose text and assert the backend, worker and
beat receive the exact string `"false"`. Extend the Compose checker with:

```python
required_backend_environment = {
    "DJANGO_SETTINGS_MODULE": "config.settings.prod",
    "PUBLIC_SELF_SERVICE_ENABLED": "false",
}
```

Make the checker reject missing values and truthy variants such as `true`, `1` and
`yes`.

- [ ] **Step 2: Run the focused tests and observe failure**

Run:

```powershell
docker compose exec -T backend pytest apps/health/tests/test_prod_settings.py -q
docker compose run --rm --no-deps --volume ${PWD}:/workspace:ro backend python /workspace/scripts/check_prod_compose.py
```

Expected: at least one assertion fails because the setting and Compose variable do
not exist.

- [ ] **Step 3: Add the fail-closed setting and explicit production wiring**

Add to `base.py`:

```python
PUBLIC_SELF_SERVICE_ENABLED = env.bool(
    "PUBLIC_SELF_SERVICE_ENABLED",
    default=False,
)
```

Add `PUBLIC_SELF_SERVICE_ENABLED=false` to `.env.example`. Add this environment
entry to the backend, worker and beat production services:

```yaml
PUBLIC_SELF_SERVICE_ENABLED: "false"
```

Keep email and WhatsApp secrets documented under a clearly labelled Version 1.1
section; they are not Version 1 production prerequisites.

- [ ] **Step 4: Run the focused tests**

Run the commands from Step 2.

Expected: both commands exit `0` and print no unsafe capability warning.

- [ ] **Step 5: Commit the capability setting**

```powershell
git add backend/config/settings/base.py backend/apps/health/tests/test_prod_settings.py .env.example docker-compose.prod.yml scripts/check_prod_compose.py
git commit -m "feat: add fail-closed public capability setting"
```

### Task 2: Application-level public route omission

**Files:**
- Create: `backend/config/public_urls.py`
- Create: `backend/apps/contacts/public_urls.py`
- Create: `backend/apps/csat/public_urls.py`
- Create: `backend/apps/knowledge/public_urls.py`
- Create: `backend/apps/health/tests/test_version1_routes.py`
- Modify: `backend/config/urls.py`
- Modify: `backend/apps/contacts/urls.py`
- Modify: `backend/apps/knowledge/urls.py`
- Modify: `backend/apps/csat/urls.py`
- Modify: `backend/apps/email_channel/urls.py`
- Modify: `backend/apps/whatsapp/urls.py`
- Test: `backend/apps/health/tests/test_version1_routes.py`

**Interfaces:**
- Consumes: `settings.PUBLIC_SELF_SERVICE_ENABLED`
- Produces: `config.public_urls.urlpatterns`
- Produces: `config.urls.build_urlpatterns(public_self_service_enabled: bool) -> list[URLPattern | URLResolver]`

- [ ] **Step 1: Write the Version 1 route matrix test**

Create a parameterized test for these exact paths:

```python
DEFERRED_PATHS = (
    "/api/v1/public/requester/not-a-token/",
    "/api/v1/public/requester/not-a-token/reply/",
    "/api/v1/public/csat/not-a-token/",
    "/api/v1/public/knowledge/",
    "/api/v1/integrations/email/events/",
    "/api/v1/integrations/email/bounce/",
    "/api/v1/integrations/whatsapp/webhook/",
    "/api/v1/integrations/whatsapp/templates/",
    "/api/v1/integrations/whatsapp/send/",
)
```

For the default root URL configuration, assert `resolve(path)` raises
`Resolver404`. Also assert `/api/v1/health/live`, `/api/v1/identity/me`,
`/api/v1/tickets/`, `/api/v1/knowledge/articles/` and `/metrics` still resolve.

- [ ] **Step 2: Run the route matrix and observe failure**

```powershell
docker compose exec -T backend pytest apps/health/tests/test_version1_routes.py -q
```

Expected: the deferred routes resolve under the current unconditional URL setup.

- [ ] **Step 3: Separate public routes from internal app routers**

Move only requester status/reply, public CSAT and public knowledge paths into
`config/public_urls.py`, together with includes for the complete email and WhatsApp
URL modules:

```python
urlpatterns = [
    path("api/v1/", include("apps.contacts.public_urls")),
    path("api/v1/", include("apps.csat.public_urls")),
    path("api/v1/", include("apps.knowledge.public_urls")),
    path("api/v1/", include("apps.email_channel.urls")),
    path("api/v1/", include("apps.whatsapp.urls")),
]
```

Create the three app-level `public_urls.py` modules if that keeps the existing
view modules unchanged. Their internal `urls.py` modules must contain only the
authenticated routers.

In `config/urls.py`, define and call:

```python
def build_urlpatterns(*, public_self_service_enabled: bool):
    patterns = [
        # root, admin, health, identity and all authenticated internal includes
    ]
    if public_self_service_enabled:
        patterns.append(path("", include("config.public_urls")))
    patterns.append(path("", include("django_prometheus.urls")))
    return patterns


urlpatterns = build_urlpatterns(
    public_self_service_enabled=settings.PUBLIC_SELF_SERVICE_ENABLED,
)
```

Do not remove deferred Django applications from `INSTALLED_APPS`.

- [ ] **Step 4: Add a flag-on route contract test**

Test `build_urlpatterns(public_self_service_enabled=True)` with a temporary URL
module or `URLResolver` and assert every `DEFERRED_PATHS` entry resolves. This
protects the Version 1.1 code path without enabling it in Version 1.

- [ ] **Step 5: Run route and app tests**

```powershell
docker compose exec -T backend pytest apps/health/tests/test_version1_routes.py apps/contacts apps/csat apps/knowledge apps/email_channel apps/whatsapp -q
```

Expected: Version 1 paths are `404`, flag-on contracts resolve, and internal
knowledge routes still work.

- [ ] **Step 6: Commit route composition**

```powershell
git add backend/config/urls.py backend/config/public_urls.py backend/apps/contacts backend/apps/csat backend/apps/knowledge backend/apps/email_channel/urls.py backend/apps/whatsapp/urls.py backend/apps/health/tests/test_version1_routes.py
git commit -m "feat: omit public self-service routes in version 1"
```

### Task 3: Nginx defence-in-depth and deferred worker proof

**Files:**
- Create: `backend/apps/health/tests/test_deferred_channel_jobs.py`
- Modify: `infrastructure/nginx/conf.d/app.conf`
- Modify: `scripts/check_prod_compose.py`
- Test: `backend/apps/health/tests/test_deferred_channel_jobs.py`

**Interfaces:**
- Consumes: the route families from Task 2
- Produces: Nginx `404` for deferred paths
- Produces: a test proving the Version 1 Celery beat schedule contains no email or WhatsApp task

- [ ] **Step 1: Write failing proxy and task assertions**

Add a source-contract test which asserts the Nginx template contains a higher
priority regular-expression location before the generic integration proxy:

```nginx
location ~ ^/api/v1/(?:public/|integrations/(?:email|whatsapp)/) {
    return 404;
}
```

Assert no key or task name in `settings.CELERY_BEAT_SCHEDULE` contains `email` or
`whatsapp` when `PUBLIC_SELF_SERVICE_ENABLED` is false.

- [ ] **Step 2: Run the focused tests and observe failure**

```powershell
docker compose exec -T backend pytest apps/health/tests/test_deferred_channel_jobs.py -q
docker compose run --rm --no-deps --volume ${PWD}:/workspace:ro backend python /workspace/scripts/check_prod_compose.py
```

- [ ] **Step 3: Add the proxy denial and production validation**

Add the exact Nginx location above before `location ~ ^/api/v1/integrations/`.
Replace the old public-intake location with the authenticated staff-intake location
introduced by Plan 2; do not rate-limit it with the anonymous intake zone.

Extend the Compose checker to assert the production capability remains false for
backend, worker and beat.

- [ ] **Step 4: Validate Nginx and tests**

```powershell
docker build -t mhc-ticketing-nginx:plan-check infrastructure/nginx
docker run --rm --entrypoint nginx mhc-ticketing-nginx:plan-check -t
docker compose exec -T backend pytest apps/health/tests/test_deferred_channel_jobs.py -q
```

Expected: Nginx reports configuration syntax is valid and the test passes.

- [ ] **Step 5: Commit the edge control**

```powershell
git add infrastructure/nginx/conf.d/app.conf scripts/check_prod_compose.py backend/apps/health/tests/test_deferred_channel_jobs.py
git commit -m "chore: block deferred public channels at the edge"
```

### Task 4: Scope and deployment documentation

**Files:**
- Create: `docs/version-1.1-public-self-service-backlog.md`
- Modify: `docs/deployment.md`
- Modify: `docs/pilot-runbook.md`
- Modify: `docs/production-readiness-2026-08-22.md`

**Interfaces:**
- Consumes: the approved design and implemented route matrix
- Produces: operator instructions that never enable deferred capabilities during Version 1 recovery

- [ ] **Step 1: Write the Version 1.1 backlog with explicit re-entry gates**

Record requester token binding, PII projection, public CSAT/knowledge publication,
webhook authentication, provider approvals, outbound consent, leased dispatch,
retry deduplication, dead-letter handling, rate limits, abuse protection and public
accessibility. Mark each as deferred, not accepted or complete.

- [ ] **Step 2: Update deployment and rollback instructions**

Document:

```text
PUBLIC_SELF_SERVICE_ENABLED=false
```

State that turning it on is not a Version 1 recovery, rollback or diagnostic step.
List the expected `404` probes from Task 2 and the internal endpoints that must
remain healthy.

- [ ] **Step 3: Reclassify the existing readiness report without changing evidence**

Move requester-token, public web, email and WhatsApp findings into the Version 1.1
section. Keep authorization, monitoring, IT-child PII, contacts, backup, TLS, load,
audit, reporting and accessibility as Version 1 failures until their plans pass.

- [ ] **Step 4: Review the docs for unsafe enablement instructions**

```powershell
rg -n "PUBLIC_SELF_SERVICE_ENABLED|WhatsApp|email|requester|public" docs/deployment.md docs/pilot-runbook.md docs/version-1.1-public-self-service-backlog.md docs/production-readiness-2026-08-22.md
```

Expected: every Version 1 instruction says the capability is false; public-channel
activation appears only under Version 1.1.

- [ ] **Step 5: Commit the boundary documentation**

```powershell
git add docs/deployment.md docs/pilot-runbook.md docs/production-readiness-2026-08-22.md docs/version-1.1-public-self-service-backlog.md
git commit -m "docs: record version 1 public channel boundary"
```
