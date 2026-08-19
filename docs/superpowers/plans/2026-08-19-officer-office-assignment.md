# Officer Office Assignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record which office an officer is based at from a Keycloak claim, confine that officer's operational and IT authority to that office, and add a cross-office service desk role exempt from the boundary.

**Architecture:** Keycloak carries `office` and `station` as user attributes mapped into the access token. `KeycloakJWTAuthentication` persists them onto the local `User` mirror on every request. A single function, `_apply_office_boundary`, rewrites the resolved `AuthoritySnapshot` so operational and IT scopes carry the officer's office — this is the one choke point every authorisation consumer in the codebase already passes through.

**Tech Stack:** Django 5, Django REST Framework, PostgreSQL, Keycloak (OIDC), pytest / pytest-django, Docker Compose.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-19-officer-office-assignment-design.md`. It is authoritative; this plan implements it.
- Python 3.12. Ruff line-length 100. All modules use `from __future__ import annotations`.
- Ruff lint rules in force: `E, F, I, B, UP, N, S, ASYNC, PT, DJ`. Notably `PT` (pytest style) and `S` (bandit) — do not add bare asserts outside tests, and keep pytest fixtures/parametrize idiomatic.
- Tests run in Docker: `docker compose exec backend pytest -q`. Every "Run" step below assumes the stack is up (`make up`).
- The repo is mid-change with ~100 modified files on `spec/officer-office-assignment`. Only stage files each task names.
- Keycloak is the single writer for `office` and `station`. Nothing in this application may write them outside `_synchronize_office`.
- Deny by default: an officer with no valid office keeps `admin` and audit authority and loses operational and IT authority. No condition may raise an authentication failure.
- `_scope_key` includes `office_id`. Any code that rewrites a scope's office **must** remap `restricted_scope_keys` in the same operation.

## Task Order and Suite Health

Tasks are ordered so the test suite is green at every commit. Task 9 is the only task with a red window inside it, and it closes that window before its final commit.

---

### Task 1: Realm configuration — mappers and service desk role

**Files:**
- Modify: `infrastructure/keycloak/realm-mhc.json`
- Test: `backend/apps/identity_access/tests/test_realm_config.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: realm group `service-desk-agents`, realm role `agent-servicedesk`, token claims `office` and `station`. Task 3 reads the claims; Task 6 registers the role keys in code.

The backend container mounts `./infrastructure` at `/infrastructure:ro`. `Path(__file__).resolve().parents[4]` yields `/` inside Docker and the repo root locally, so the same expression finds the file in both.

- [ ] **Step 1: Write the failing test**

Create `backend/apps/identity_access/tests/test_realm_config.py`:

```python
"""The realm export is the source of truth for office claims and staff roles."""

from __future__ import annotations

import json
from pathlib import Path

REALM_PATH = Path(__file__).resolve().parents[4] / "infrastructure/keycloak/realm-mhc.json"


def _realm() -> dict:
    return json.loads(REALM_PATH.read_text(encoding="utf-8"))


def test_realm_export_is_readable():
    assert REALM_PATH.is_file(), f"realm export not found at {REALM_PATH}"


def test_office_and_station_attribute_mappers_exist():
    mappers = {m["name"]: m for m in _realm()["protocolMappers"]}
    for name, attribute in (("office", "office"), ("station", "station")):
        assert name in mappers, f"missing protocol mapper: {name}"
        mapper = mappers[name]
        assert mapper["protocolMapper"] == "oidc-usermodel-attribute-mapper"
        assert mapper["config"]["user.attribute"] == attribute
        assert mapper["config"]["claim.name"] == attribute
        assert mapper["config"]["access.token.claim"] == "true"


def test_service_desk_group_and_realm_role_exist():
    realm = _realm()
    groups = {g["name"]: g for g in realm["groups"]}
    assert "service-desk-agents" in groups
    assert set(groups["service-desk-agents"]["realmRoles"]) == {"staff", "agent-servicedesk"}
    assert "agent-servicedesk" in {r["name"] for r in realm["roles"]["realm"]}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest -q apps/identity_access/tests/test_realm_config.py`
Expected: `test_realm_export_is_readable` PASSES; the other two FAIL with `KeyError: 'office'` and `AssertionError` on the group.

- [ ] **Step 3: Add the two protocol mappers**

In `infrastructure/keycloak/realm-mhc.json`, replace the `protocolMappers` array (currently one entry, `realm-roles`) with:

```json
  "protocolMappers": [
    {
      "name": "realm-roles",
      "protocol": "openid-connect",
      "protocolMapper": "oidc-usermodel-realm-role-mapper",
      "config": {
        "id.token.claim": "true",
        "access.token.claim": "true",
        "userinfo.token.claim": "true"
      }
    },
    {
      "name": "office",
      "protocol": "openid-connect",
      "protocolMapper": "oidc-usermodel-attribute-mapper",
      "config": {
        "user.attribute": "office",
        "claim.name": "office",
        "jsonType.label": "String",
        "id.token.claim": "true",
        "access.token.claim": "true",
        "userinfo.token.claim": "true"
      }
    },
    {
      "name": "station",
      "protocol": "openid-connect",
      "protocolMapper": "oidc-usermodel-attribute-mapper",
      "config": {
        "user.attribute": "station",
        "claim.name": "station",
        "jsonType.label": "String",
        "id.token.claim": "true",
        "access.token.claim": "true",
        "userinfo.token.claim": "true"
      }
    }
  ],
```

- [ ] **Step 4: Add the service desk group and realm role**

In the same file, append to the `groups` array:

```json
    {
      "name": "service-desk-agents",
      "path": "/service-desk-agents",
      "realmRoles": [
        "staff",
        "agent-servicedesk"
      ]
    }
```

And append to `roles.realm` (the array whose entries look like `{"name": "agent-operational"}` — match the exact shape of its neighbours, including any `description` key they carry):

```json
    {
      "name": "agent-servicedesk"
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec backend pytest -q apps/identity_access/tests/test_realm_config.py`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add infrastructure/keycloak/realm-mhc.json backend/apps/identity_access/tests/test_realm_config.py
git commit -m "feat(keycloak): add office claims and service desk role to realm"
```

---

### Task 2: User office and station fields

**Files:**
- Modify: `backend/apps/identity_access/models.py`
- Create: `backend/apps/identity_access/migrations/0004_user_office_station.py`
- Test: `backend/apps/identity_access/tests/test_office_assignment.py` (create)

**Interfaces:**
- Consumes: `organisations.Office`, `organisations.ServiceLocation`.
- Produces: `User.office` (nullable FK, `PROTECT`, related name `based_officers`), `User.station` (nullable FK, `SET_NULL`, related name `stationed_officers`). Tasks 3, 4, 5, 7, 9 all read these.

- [ ] **Step 1: Write the failing test**

Create `backend/apps/identity_access/tests/test_office_assignment.py`:

```python
"""Officers are based at an office and may be stationed at a counter."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.db.models import ProtectedError

from apps.identity_access.models import User
from apps.organisations.models import Office, ServiceLocation

pytestmark = pytest.mark.django_db


def _user(**kwargs) -> User:
    return User.objects.create(
        username=f"user-{uuid4().hex}",
        keycloak_subject=f"subject-{uuid4().hex}",
        **kwargs,
    )


def test_office_and_station_default_to_none():
    user = _user()
    assert user.office is None
    assert user.station is None


def test_user_can_be_based_at_an_office(basic_world):
    office = basic_world["office"]
    user = _user(office=office)
    user.refresh_from_db()
    assert user.office == office
    assert list(office.based_officers.all()) == [user]


def test_user_can_be_stationed_at_a_counter(basic_world):
    office = basic_world["office"]
    station = ServiceLocation.objects.create(office=office, name="Counter-1")
    user = _user(office=office, station=station)
    user.refresh_from_db()
    assert user.station == station
    assert list(station.stationed_officers.all()) == [user]


def test_office_with_officers_cannot_be_deleted(basic_world):
    region = basic_world["region"]
    office = Office.objects.create(region=region, code="DEL-1", name="Deletable")
    _user(office=office)
    with pytest.raises(ProtectedError):
        office.delete()


def test_retiring_a_station_leaves_the_officer_based_at_the_office(basic_world):
    office = basic_world["office"]
    station = ServiceLocation.objects.create(office=office, name="Counter-2")
    user = _user(office=office, station=station)
    station.delete()
    user.refresh_from_db()
    assert user.station is None
    assert user.office == office
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest -q apps/identity_access/tests/test_office_assignment.py`
Expected: FAIL — `TypeError: User() got unexpected keyword arguments: 'office'`.

- [ ] **Step 3: Add the fields**

In `backend/apps/identity_access/models.py`, inside `class User(AbstractUser)`, after `keycloak_groups`:

```python
    office = models.ForeignKey(
        "organisations.Office",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="based_officers",
    )
    station = models.ForeignKey(
        "organisations.ServiceLocation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stationed_officers",
    )
```

`PROTECT` on `office` stops an office being deleted while officers are based there. `SET_NULL` on `station` lets a counter be retired without displacing the officer.

- [ ] **Step 4: Generate the migration**

Run: `docker compose exec backend python manage.py makemigrations identity_access --name user_office_station`
Expected: creates `apps/identity_access/migrations/0004_user_office_station.py` adding two nullable fields. Open it and confirm it contains only `AddField` operations — no data migration.

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec backend pytest -q apps/identity_access/tests/test_office_assignment.py`
Expected: 5 passed.

- [ ] **Step 6: Confirm no other migration drift**

Run: `docker compose exec backend python manage.py makemigrations --check --dry-run`
Expected: exit 0, "No changes detected".

- [ ] **Step 7: Commit**

```bash
git add backend/apps/identity_access/models.py backend/apps/identity_access/migrations/0004_user_office_station.py backend/apps/identity_access/tests/test_office_assignment.py
git commit -m "feat(identity): base officers at an office and station"
```

---

### Task 3: Persist office and station from the token

**Files:**
- Modify: `backend/apps/identity_access/authentication.py`
- Test: `backend/apps/identity_access/tests/test_office_assignment.py` (append)

**Interfaces:**
- Consumes: `User.office`, `User.station` from Task 2; `lock_user_authorities` from `apps/identity_access/authority_lock.py`.
- Produces: `_resolve_office_and_station(payload: JSONObject) -> tuple[Office | None, ServiceLocation | None]` and `_synchronize_office(user: User, payload: JSONObject) -> None`. The dev token gains a fourth segment: `dev:<username>:<groups>:<office-code>`.

Station names are unique only within an office (`unique_together = ("office", "name")`), so the station is always resolved inside the office the `office` claim resolved to.

- [ ] **Step 1: Write the failing test**

Append to `backend/apps/identity_access/tests/test_office_assignment.py`:

```python
from apps.identity_access.authentication import _synchronize_office


def _claims(**kwargs) -> dict:
    return {"sub": "subject", "groups": [], **kwargs}


def test_office_claim_is_persisted(basic_world):
    office = basic_world["office"]
    user = _user()
    _synchronize_office(user, _claims(office=office.code))
    user.refresh_from_db()
    assert user.office == office


def test_station_is_resolved_within_the_office(basic_world):
    office = basic_world["office"]
    station = ServiceLocation.objects.create(office=office, name="Counter-A")
    user = _user()
    _synchronize_office(user, _claims(office=office.code, station="Counter-A"))
    user.refresh_from_db()
    assert user.station == station


def test_station_from_another_office_is_ignored(basic_world):
    region = basic_world["region"]
    other = Office.objects.create(region=region, code="OTH-1", name="Other")
    ServiceLocation.objects.create(office=other, name="Counter-B")
    user = _user()
    _synchronize_office(user, _claims(office=basic_world["office"].code, station="Counter-B"))
    user.refresh_from_db()
    assert user.station is None
    assert user.office == basic_world["office"]


def test_unknown_office_code_resolves_to_none(basic_world):
    user = _user(office=basic_world["office"])
    _synchronize_office(user, _claims(office="NO-SUCH-OFFICE"))
    user.refresh_from_db()
    assert user.office is None


def test_inactive_office_resolves_to_none(basic_world):
    region = basic_world["region"]
    office = Office.objects.create(region=region, code="OLD-1", name="Closed", is_active=False)
    user = _user()
    _synchronize_office(user, _claims(office=office.code))
    user.refresh_from_db()
    assert user.office is None


def test_missing_office_claim_clears_a_stored_office(basic_world):
    user = _user(office=basic_world["office"])
    _synchronize_office(user, _claims())
    user.refresh_from_db()
    assert user.office is None


def test_unchanged_claim_performs_no_write(basic_world):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    office = basic_world["office"]
    user = _user(office=office)
    _synchronize_office(user, _claims(office=office.code))
    with CaptureQueriesContext(connection) as captured:
        _synchronize_office(user, _claims(office=office.code))
    updates = [q["sql"] for q in captured.captured_queries if q["sql"].startswith("UPDATE")]
    assert updates == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest -q apps/identity_access/tests/test_office_assignment.py -k synchronize or office_claim or station or unknown or inactive or unchanged`
Expected: FAIL with `ImportError: cannot import name '_synchronize_office'`.

- [ ] **Step 3: Add the resolver and synchroniser**

In `backend/apps/identity_access/authentication.py`, add to the imports near `from .models import User`:

```python
from apps.organisations.models import Office, ServiceLocation
```

Then add both functions to the `# --- helpers ---` section, directly after `_synchronize_groups`:

```python
def _claim_text(payload: JSONObject, name: str) -> str:
    value = payload.get(name)
    return value.strip() if isinstance(value, str) else ""


def _resolve_office_and_station(
    payload: JSONObject,
) -> tuple[Office | None, ServiceLocation | None]:
    """Resolve the office claim, then the station claim inside that office.

    A claim naming an unknown code, or an inactive row, resolves to ``None``.
    ``ServiceLocation.name`` is unique only within an office, so a station can
    only be resolved once the office is known.
    """
    office_code = _claim_text(payload, "office")
    if not office_code:
        return None, None
    office = Office.objects.filter(code=office_code, is_active=True).first()
    if office is None:
        return None, None

    station_name = _claim_text(payload, "station")
    if not station_name:
        return office, None
    station = ServiceLocation.objects.filter(
        office=office,
        name=station_name,
        is_active=True,
    ).first()
    return office, station


def _synchronize_office(user: User, payload: JSONObject) -> None:
    """Mirror the office and station claims onto the local user."""
    office, station = _resolve_office_and_station(payload)
    office_id = office.id if office is not None else None
    station_id = station.id if station is not None else None

    with transaction.atomic():
        locked = lock_user_authorities((user.id,))[user.id].user
        changed: list[str] = []
        if locked.office_id != office_id:
            locked.office = office
            changed.append("office")
        if locked.station_id != station_id:
            locked.station = station
            changed.append("station")
        if changed:
            locked.save(update_fields=changed)

    user.office = office
    user.station = station
```

- [ ] **Step 4: Call it from both authentication paths**

In `KeycloakJWTAuthentication.authenticate`, in the DEBUG dev-token branch, replace the block from `groups = _normalize_groups(groups)` through the `return dev_user, {...}` statement with:

```python
                groups = _normalize_groups(groups)
                _synchronize_groups(dev_user, groups)
                group_claims: list[JSONValue] = list(groups)
                dev_claims: JSONObject = {
                    "sub": f"dev:{username}",
                    "groups": group_claims,
                }
                if len(parts) > 3 and parts[3]:
                    dev_claims["office"] = parts[3]
                _synchronize_office(dev_user, dev_claims)
                return dev_user, dev_claims
```

Then in the verified-token path, replace the final two lines of `authenticate`:

```python
        groups = _effective_groups(payload)
        _synchronize_groups(user, groups)
        _synchronize_office(user, payload)
        return user, payload
```

- [ ] **Step 5: Add the dev-token test**

Append to `backend/apps/identity_access/tests/test_office_assignment.py`:

```python
def test_dev_token_fourth_segment_sets_the_office(basic_world, client, settings):
    settings.DEBUG = True
    office = basic_world["office"]
    response = client.get(
        "/api/v1/me",
        HTTP_AUTHORIZATION=f"Bearer dev:deskofficer:ops-agents:{office.code}",
    )
    assert response.status_code == 200
    user = User.objects.get(username="deskofficer")
    assert user.office == office


def test_three_segment_dev_token_still_authenticates(basic_world, client, settings):
    settings.DEBUG = True
    response = client.get(
        "/api/v1/me",
        HTTP_AUTHORIZATION="Bearer dev:legacyofficer:ops-agents",
    )
    assert response.status_code == 200
    assert User.objects.get(username="legacyofficer").office is None
```

If `/api/v1/me` is not the mounted path for `identity-me`, confirm the prefix with `docker compose exec backend python manage.py show_urls | grep identity-me` (or read `backend/config/urls.py`) and use the real path in both tests.

- [ ] **Step 6: Run the full identity suite**

Run: `docker compose exec backend pytest -q apps/identity_access`
Expected: all pass. The pre-existing dev-token tests in `test_authentication.py` use three segments and must still pass unchanged.

- [ ] **Step 7: Commit**

```bash
git add backend/apps/identity_access/authentication.py backend/apps/identity_access/tests/test_office_assignment.py
git commit -m "feat(identity): persist office and station from Keycloak claims"
```

---

### Task 4: Expose office and station on /me

**Files:**
- Modify: `backend/apps/identity_access/views.py`
- Test: `backend/apps/identity_access/tests/test_api_contracts.py` (append)

**Interfaces:**
- Consumes: `User.office`, `User.station`.
- Produces: `/me` response keys `office` (`{"id", "code", "name"}` or `null`) and `station` (`{"id", "name"}` or `null`). `ServiceLocation` has no `code` field — do not add one to the payload.

- [ ] **Step 1: Write the failing test**

Append to `backend/apps/identity_access/tests/test_api_contracts.py` (match the file's existing import style and authentication helper — read the top of the file first and reuse whatever it already uses to authenticate a request):

```python
def test_me_returns_office_and_station(basic_world, client, settings):
    from apps.organisations.models import ServiceLocation

    settings.DEBUG = True
    office = basic_world["office"]
    ServiceLocation.objects.create(office=office, name="Counter-9")

    response = client.get(
        "/api/v1/me",
        HTTP_AUTHORIZATION=f"Bearer dev:contractofficer:ops-agents:{office.code}",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["office"] == {
        "id": str(office.id),
        "code": office.code,
        "name": office.name,
    }
    assert body["station"] is None


def test_me_returns_null_office_when_unassigned(client, settings):
    settings.DEBUG = True
    response = client.get(
        "/api/v1/me",
        HTTP_AUTHORIZATION="Bearer dev:unassignedofficer:ops-agents",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["office"] is None
    assert body["station"] is None


def test_me_returns_a_populated_station(basic_world):
    """Station carries id and name only — ServiceLocation has no code field."""
    from uuid import uuid4

    from rest_framework.test import APIRequestFactory, force_authenticate

    from apps.identity_access.models import User
    from apps.identity_access.views import me
    from apps.organisations.models import ServiceLocation

    office = basic_world["office"]
    station = ServiceLocation.objects.create(office=office, name="Counter-7")
    user = User.objects.create(
        username=f"stationed-{uuid4().hex}",
        keycloak_subject=f"stationed-subject-{uuid4().hex}",
        office=office,
        station=station,
    )

    request = APIRequestFactory().get("/me")
    force_authenticate(request, user=user)
    response = me(request)

    assert response.status_code == 200
    assert response.data["station"] == {"id": str(station.id), "name": station.name}
    assert response.data["office"] == {
        "id": str(office.id),
        "code": office.code,
        "name": office.name,
    }
```

This test calls the view directly rather than going through the dev token, because a second authenticated request would re-run `_synchronize_office` and correctly clear a station that no claim asserts.

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest -q apps/identity_access/tests/test_api_contracts.py -k office`
Expected: FAIL with `KeyError: 'office'`.

- [ ] **Step 3: Add the fields to the response**

In `backend/apps/identity_access/views.py`, replace the body of `me` after the `isinstance` guard:

```python
    office = user.office
    station = user.station
    payload = {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "mfa_enabled": user.mfa_enabled,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "office": (
            {"id": str(office.id), "code": office.code, "name": office.name}
            if office is not None
            else None
        ),
        "station": (
            {"id": str(station.id), "name": station.name} if station is not None else None
        ),
    }
    return Response(payload)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec backend pytest -q apps/identity_access/tests/test_api_contracts.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/identity_access/views.py backend/apps/identity_access/tests/test_api_contracts.py
git commit -m "feat(identity): return office and station from /me"
```

---

### Task 5: Read-only in admin, prefetched for the boundary

**Files:**
- Modify: `backend/apps/identity_access/admin.py`
- Modify: `backend/apps/identity_access/authority_lock.py:41-43`
- Test: `backend/apps/identity_access/tests/test_office_assignment.py` (append)

**Interfaces:**
- Consumes: `User.office` from Task 2.
- Produces: `AuthorityUserAdmin.readonly_fields` includes `office` and `station`. `lock_user_authorities` returns users with `office` already selected, so Task 9 can read `office.is_active` without an extra query per user.

- [ ] **Step 1: Write the failing test**

Append to `backend/apps/identity_access/tests/test_office_assignment.py`:

```python
def test_admin_shows_office_and_station_read_only():
    from django.contrib import admin as django_admin

    from apps.identity_access.admin import AuthorityUserAdmin

    model_admin = AuthorityUserAdmin(User, django_admin.site)
    assert "office" in model_admin.readonly_fields
    assert "station" in model_admin.readonly_fields


def test_authority_lock_preloads_the_office(basic_world):
    from django.db import connection, transaction
    from django.test.utils import CaptureQueriesContext

    from apps.identity_access.authority_lock import lock_user_authorities

    user = _user(office=basic_world["office"])
    with transaction.atomic():
        locked = lock_user_authorities((user.id,))[user.id].user
        with CaptureQueriesContext(connection) as captured:
            assert locked.office.is_active is True
        assert captured.captured_queries == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest -q apps/identity_access/tests/test_office_assignment.py -k "read_only or preloads"`
Expected: both FAIL — no `readonly_fields` attribute, and reading `locked.office` issues a query.

- [ ] **Step 3: Make the admin fields read-only**

In `backend/apps/identity_access/admin.py`, inside `class AuthorityUserAdmin`, add below the docstring:

```python
    # Keycloak is the single writer for these. A local edit would be silently
    # overwritten by ``_synchronize_office`` on the officer's next request.
    readonly_fields = ("office", "station")
```

- [ ] **Step 4: Preload the office in the authority lock**

In `backend/apps/identity_access/authority_lock.py`, change the user query:

```python
    users = list(
        User.objects.select_for_update(of=("self",))
        .select_related("office")
        .filter(pk__in=ordered_ids)
        .order_by("id")
    )
```

`of=("self",)` keeps the row lock on the user table only, so joining `office` does not widen the lock.

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec backend pytest -q apps/identity_access`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/identity_access/admin.py backend/apps/identity_access/authority_lock.py backend/apps/identity_access/tests/test_office_assignment.py
git commit -m "feat(identity): make office read-only in admin and preload it under lock"
```

---

### Task 6: Register the service desk role

**Files:**
- Modify: `backend/apps/identity_access/authentication.py`
- Modify: `backend/apps/identity_access/scope.py`
- Modify: `backend/apps/tickets/eligibility.py`
- Modify: `backend/apps/tickets/permissions.py`
- Test: `backend/apps/identity_access/tests/test_service_desk_role.py` (create)

**Interfaces:**
- Consumes: realm group and role from Task 1.
- Produces: module constant `_SERVICE_DESK_ROLES = frozenset({"service-desk-agents", "agent-servicedesk"})` in `scope.py`. Task 8 imports it to build `_CROSS_OFFICE_ROLES`.

The role is operational-domain, agent-level. It is deliberately **not** added to `_RESTRICTED_ROLE_KEYS` or `REASSIGN_GROUPS` — cross-office reach must never be combined with restricted-ticket visibility.

- [ ] **Step 1: Write the failing test**

Create `backend/apps/identity_access/tests/test_service_desk_role.py`:

```python
"""The service desk is a cross-office operational agent role."""

from __future__ import annotations

from uuid import uuid4

import pytest

from apps.identity_access.models import User
from apps.identity_access.scope import Scope, get_user_scopes
from apps.tickets.permissions import DOMAIN_GROUPS

pytestmark = pytest.mark.django_db


def _desk_user(group: str) -> User:
    user = User.objects.create(
        username=f"desk-{uuid4().hex}",
        keycloak_subject=f"desk-subject-{uuid4().hex}",
        keycloak_groups=[group],
    )
    vars(user)["_groups"] = [group]
    return user


@pytest.mark.parametrize("group", ["service-desk-agents", "agent-servicedesk"])
def test_service_desk_group_grants_operational_scope(group):
    scopes = get_user_scopes(_desk_user(group))
    assert Scope(domain="operational") in scopes


def test_service_desk_is_an_operational_domain_group():
    assert "service-desk-agents" in DOMAIN_GROUPS["operational"]
    assert "agent-servicedesk" in DOMAIN_GROUPS["operational"]


def test_service_desk_is_not_in_the_it_domain():
    assert "service-desk-agents" not in DOMAIN_GROUPS["it"]


def test_service_desk_cannot_reassign():
    from apps.tickets.permissions import REASSIGN_GROUPS

    assert "service-desk-agents" not in REASSIGN_GROUPS
    assert "agent-servicedesk" not in REASSIGN_GROUPS


def test_service_desk_group_is_accepted_by_the_authenticator():
    from apps.identity_access.authentication import _KEYCLOAK_GROUPS, _KEYCLOAK_REALM_ROLES

    assert "service-desk-agents" in _KEYCLOAK_GROUPS
    assert "agent-servicedesk" in _KEYCLOAK_REALM_ROLES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest -q apps/identity_access/tests/test_service_desk_role.py`
Expected: FAIL — the scope assertions find an empty scope list, and the membership assertions fail.

- [ ] **Step 3: Allowlist the group and role in the authenticator**

In `backend/apps/identity_access/authentication.py`, add `"service-desk-agents",` to the `_KEYCLOAK_GROUPS` frozenset, and add `"agent-servicedesk",` to the explicit set inside `_KEYCLOAK_REALM_ROLES`:

```python
_KEYCLOAK_GROUPS = frozenset(
    {
        "ops-agents",
        "ops-supervisors",
        "it-agents",
        "it-leads",
        "security-responders",
        "system-admins",
        "auditors",
        "service-desk-agents",
    }
)
```

```python
_KEYCLOAK_REALM_ROLES = (
    _KEYCLOAK_GROUPS
    | {
        "agent-operational",
        "supervisor-operational",
        "agent-it",
        "lead-it",
        "admin",
        "auditor",
        "agent-servicedesk",
    }
    | STAFF_DESIGNATION_ROLE_KEYS
)
```

- [ ] **Step 4: Grant the scope in scope.py**

In `backend/apps/identity_access/scope.py`, add two entries to `_DEFAULT_ROLE_SCOPES`, next to the other operational roles:

```python
    "service-desk-agents": ({"domain": "operational"},),
    "agent-servicedesk": ({"domain": "operational"},),
```

Add the constant immediately after `_AUDITOR_ROLES` (line 45):

```python
# The national service desk answers queries before the responsible office is
# known, so it is never bound to one office.
_SERVICE_DESK_ROLES = frozenset({"service-desk-agents", "agent-servicedesk"})
```

In `_snapshot_from_groups`, add a branch alongside the other operational branches, before the `system-admins` branch:

```python
    if groups & _SERVICE_DESK_ROLES:
        add_scope(Scope(domain="operational"))
```

Do **not** pass `can_view_restricted_rows=True`, and do **not** add these keys to `_RESTRICTED_VIEW_ROLES`.

- [ ] **Step 5: Register the role in the ticket tables**

In `backend/apps/tickets/eligibility.py`:

Add to `_LEGACY_ROLE_DETAILS`:

```python
    "agent-servicedesk": ("Service Desk Agent", "Operational"),
    "service-desk-agents": ("Service Desk Agent", "Operational"),
```

Add to `_ROLE_FAMILY_DOMAIN`:

```python
    "agent-servicedesk": Ticket.Domain.OPERATIONAL,
    "service-desk-agents": Ticket.Domain.OPERATIONAL,
```

Add to `_ROLE_ALIASES` (the first literal, before the `_ACTOR_GROUP_ROLE_KEYS` assignment):

```python
    "agent-servicedesk": frozenset({"agent-servicedesk", "service-desk-agents"}),
    "service-desk-agents": frozenset({"agent-servicedesk", "service-desk-agents"}),
```

Add to `_GROUP_FALLBACK_ROLE_KEYS`:

```python
    "service-desk-agents",
```

In `backend/apps/tickets/permissions.py`, add both keys to the operational entry of `DOMAIN_GROUPS`:

```python
DOMAIN_GROUPS = {
    "operational": {
        "agent-operational",
        "ops-agents",
        "supervisor-operational",
        "ops-supervisors",
        "agent-servicedesk",
        "service-desk-agents",
    },
    "it": {"agent-it", "it-agents", "lead-it", "it-leads"},
}
```

Leave `REASSIGN_GROUPS` and `_RESTRICTED_ROLE_KEYS` untouched.

- [ ] **Step 6: Run the tests**

Run: `docker compose exec backend pytest -q apps/identity_access/tests/test_service_desk_role.py`
Expected: 6 passed.

- [ ] **Step 7: Run the full backend suite**

Run: `docker compose exec backend pytest -q`
Expected: all pass. Nothing is confined yet, so adding a role cannot change existing behaviour.

- [ ] **Step 8: Commit**

```bash
git add backend/apps/identity_access/authentication.py backend/apps/identity_access/scope.py backend/apps/tickets/eligibility.py backend/apps/tickets/permissions.py backend/apps/identity_access/tests/test_service_desk_role.py
git commit -m "feat(identity): add cross-office service desk agent role"
```

---

### Task 7: Shared staff_user fixture

**Files:**
- Modify: `backend/conftest.py`
- Test: `backend/apps/identity_access/tests/test_office_assignment.py` (append)

**Interfaces:**
- Consumes: `basic_world` (already defines `office` as the `TST-1` row).
- Produces: pytest fixture `staff_user`, a callable
  `staff_user(*, groups=(), office=<basic_world office>, station=None, **kwargs) -> User`.
  Task 9 migrates the existing per-module `_user(groups)` helpers onto it.

This task is a pure addition. No existing test changes, so the suite stays green.

- [ ] **Step 1: Write the failing test**

Append to `backend/apps/identity_access/tests/test_office_assignment.py`:

```python
def test_staff_user_fixture_defaults_to_the_seeded_office(basic_world, staff_user):
    user = staff_user(groups=["ops-agents"])
    assert user.office == basic_world["office"]
    assert user.keycloak_groups == ["ops-agents"]
    assert vars(user)["_groups"] == ["ops-agents"]


def test_staff_user_fixture_accepts_an_explicit_office(basic_world, staff_user):
    region = basic_world["region"]
    other = Office.objects.create(region=region, code="ALT-1", name="Alternate")
    assert staff_user(groups=["ops-agents"], office=other).office == other


def test_staff_user_fixture_accepts_no_office(staff_user):
    assert staff_user(groups=["ops-agents"], office=None).office is None


def test_staff_user_fixture_generates_unique_identities(staff_user):
    first = staff_user(groups=["ops-agents"])
    second = staff_user(groups=["ops-agents"])
    assert first.username != second.username
    assert first.keycloak_subject != second.keycloak_subject
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest -q apps/identity_access/tests/test_office_assignment.py -k staff_user_fixture`
Expected: FAIL with `fixture 'staff_user' not found`.

- [ ] **Step 3: Add the fixture**

In `backend/conftest.py`, add `from uuid import uuid4` to the imports, add `User` to the identity import (`from apps.identity_access.models import Role, User`), and append:

```python
@pytest.fixture
def staff_user(basic_world):
    """Build a staff user based at an office.

    Office confinement is deny-by-default: a user with no office has no
    operational or IT authority. Tests that need working authority must have an
    office, so this factory assigns the seeded one unless told otherwise. Pass
    ``office=None`` explicitly to build an unassigned officer.
    """
    _unset = object()

    def _make(*, groups=(), office=_unset, station=None, **kwargs):
        group_list = list(groups)
        user = User.objects.create(
            username=kwargs.pop("username", f"user-{uuid4().hex}"),
            keycloak_subject=kwargs.pop("keycloak_subject", f"subject-{uuid4().hex}"),
            keycloak_groups=group_list,
            office=basic_world["office"] if office is _unset else office,
            station=station,
            **kwargs,
        )
        vars(user)["_groups"] = group_list
        return user

    return _make
```

The `_unset` sentinel is required: a plain `office=None` default would make "use the seeded office" and "deliberately unassigned" indistinguishable.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec backend pytest -q apps/identity_access/tests/test_office_assignment.py`
Expected: all pass.

- [ ] **Step 5: Confirm nothing else moved**

Run: `docker compose exec backend pytest -q`
Expected: all pass — this task added a fixture and changed no behaviour.

- [ ] **Step 6: Commit**

```bash
git add backend/conftest.py backend/apps/identity_access/tests/test_office_assignment.py
git commit -m "test: add shared staff_user factory with office assignment"
```

---

### Task 8: Cross-office identity flag

**Files:**
- Modify: `backend/apps/identity_access/scope.py`
- Test: `backend/apps/identity_access/tests/test_service_desk_role.py` (append)

**Interfaces:**
- Consumes: `_SERVICE_DESK_ROLES` and `_AUDITOR_ROLES` from `scope.py`.
- Produces: `AuthoritySnapshot.cross_office_identity: bool` (default `False`) and `_CROSS_OFFICE_ROLES`. Task 9 reads the flag as its first check.

An `admin`-domain scope is deliberately **not** part of this flag. Exempting the whole identity would also exempt any operational scope the same person holds. Admin authority is protected per-scope in Task 9 instead.

- [ ] **Step 1: Write the failing test**

Append to `backend/apps/identity_access/tests/test_service_desk_role.py`:

```python
def test_service_desk_is_a_cross_office_identity():
    from apps.identity_access.scope import get_authority_snapshot

    snapshot = get_authority_snapshot(_desk_user("service-desk-agents"))
    assert snapshot.cross_office_identity is True


def test_auditor_is_a_cross_office_identity():
    from apps.identity_access.scope import get_authority_snapshot

    snapshot = get_authority_snapshot(_desk_user("auditors"))
    assert snapshot.cross_office_identity is True


def test_operational_agent_is_not_a_cross_office_identity():
    from apps.identity_access.scope import get_authority_snapshot

    snapshot = get_authority_snapshot(_desk_user("ops-agents"))
    assert snapshot.cross_office_identity is False


def test_system_admin_is_not_a_cross_office_identity():
    """Admin authority is protected per-scope, not by exempting the identity."""
    from apps.identity_access.scope import get_authority_snapshot

    snapshot = get_authority_snapshot(_desk_user("system-admins"))
    assert snapshot.cross_office_identity is False


def test_cross_office_flag_holds_on_the_persisted_path(basic_world):
    from apps.identity_access.models import Role, UserRole
    from apps.identity_access.scope import get_authority_snapshot

    user = _desk_user("ops-agents")
    role = Role.objects.create(keycloak_role="service-desk-agents", name="Service Desk")
    UserRole.objects.create(user=user, role=role)
    snapshot = get_authority_snapshot(user)
    assert snapshot.uses_persisted_roles is True
    assert snapshot.cross_office_identity is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest -q apps/identity_access/tests/test_service_desk_role.py -k cross_office`
Expected: FAIL with `AttributeError: 'AuthoritySnapshot' object has no attribute 'cross_office_identity'`.

- [ ] **Step 3: Add the constant and the field**

In `backend/apps/identity_access/scope.py`, directly below `_SERVICE_DESK_ROLES` (added in Task 6):

```python
_CROSS_OFFICE_ROLES = _AUDITOR_ROLES | _SERVICE_DESK_ROLES
```

`_AUDITOR_ROLES` is a plain `set`; `_SERVICE_DESK_ROLES` is a `frozenset`. `set | frozenset` yields a `set`, which is fine for the membership tests below.

Add the field to `AuthoritySnapshot`, after `auditor_identity`:

```python
    cross_office_identity: bool = False
```

- [ ] **Step 4: Compute it on the persisted path**

In `_snapshot_from_persisted`, next to the existing `auditor_identity` computation:

```python
    cross_office_identity = any(
        assignment.role.keycloak_role in _CROSS_OFFICE_ROLES for assignment in assignments
    )
```

and add `cross_office_identity=cross_office_identity,` to the returned `AuthoritySnapshot`.

- [ ] **Step 5: Compute it on the group path**

In `_snapshot_from_groups`, add to the returned `AuthoritySnapshot`:

```python
        cross_office_identity=bool(_CROSS_OFFICE_ROLES & groups),
```

- [ ] **Step 6: Carry it through the superuser branch**

In `_build_authority_snapshot`, add to the `AuthoritySnapshot` built in the superuser branch:

```python
        cross_office_identity=resolved.cross_office_identity,
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `docker compose exec backend pytest -q apps/identity_access/tests/test_service_desk_role.py`
Expected: all pass.

- [ ] **Step 8: Run the full backend suite**

Run: `docker compose exec backend pytest -q`
Expected: all pass — the flag is computed but nothing reads it yet.

- [ ] **Step 9: Commit**

```bash
git add backend/apps/identity_access/scope.py backend/apps/identity_access/tests/test_service_desk_role.py
git commit -m "feat(identity): flag cross-office identities on both authority paths"
```

---

### Task 9: Confine authority to the officer's office

This is the task that changes behaviour, and the only one with a red window inside it. Steps 5 and 6 close it.

**Files:**
- Modify: `backend/apps/identity_access/scope.py`
- Test: `backend/apps/identity_access/tests/test_office_boundary.py` (create)
- Modify: the test modules that Step 5 reports as failing

**Interfaces:**
- Consumes: `User.office` (Task 2), `AuthoritySnapshot.cross_office_identity` (Task 8), `staff_user` (Task 7).
- Produces: `_apply_office_boundary(snapshot: AuthoritySnapshot, user: object) -> AuthoritySnapshot`, applied on the non-superuser return path of `_build_authority_snapshot`.

- [ ] **Step 1: Write the failing test**

Create `backend/apps/identity_access/tests/test_office_boundary.py`:

```python
"""Operational and IT authority is confined to the officer's office."""

from __future__ import annotations

import pytest

from apps.identity_access.scope import (
    Scope,
    get_authority_snapshot,
    get_user_scopes,
    scope_ticket_queryset,
)
from apps.organisations.models import Office

pytestmark = pytest.mark.django_db


@pytest.fixture
def other_office(basic_world):
    return Office.objects.create(
        region=basic_world["region"],
        code="OTH-9",
        name="Other Office",
    )


def test_operational_scope_is_bound_to_the_office(basic_world, staff_user):
    user = staff_user(groups=["ops-agents"])
    scopes = get_user_scopes(user)
    assert scopes == [Scope(domain="operational", office_id=str(basic_world["office"].id))]


def test_it_scope_is_bound_to_the_office(basic_world, staff_user):
    user = staff_user(groups=["it-agents"])
    scopes = get_user_scopes(user)
    assert scopes == [Scope(domain="it", office_id=str(basic_world["office"].id))]


def test_missing_office_denies_operational_authority(staff_user):
    assert get_user_scopes(staff_user(groups=["ops-agents"], office=None)) == []


def test_inactive_office_denies_operational_authority(basic_world, staff_user):
    office = Office.objects.create(
        region=basic_world["region"],
        code="OLD-9",
        name="Closed",
        is_active=False,
    )
    assert get_user_scopes(staff_user(groups=["ops-agents"], office=office)) == []


def test_admin_scope_survives_a_missing_office(staff_user):
    assert get_user_scopes(staff_user(groups=["system-admins"], office=None)) == [
        Scope(domain="admin")
    ]


def test_admin_and_agent_are_confined_separately(basic_world, staff_user):
    user = staff_user(groups=["system-admins", "ops-agents"])
    scopes = set(get_user_scopes(user))
    assert Scope(domain="admin") in scopes
    assert Scope(domain="operational", office_id=str(basic_world["office"].id)) in scopes
    assert Scope(domain="operational") not in scopes


def test_auditor_is_unconfined(staff_user):
    scopes = get_user_scopes(staff_user(groups=["auditors"], office=None))
    assert Scope(domain="operational") in scopes
    assert Scope(domain="it") in scopes


def test_service_desk_is_unconfined(staff_user):
    scopes = get_user_scopes(staff_user(groups=["service-desk-agents"], office=None))
    assert Scope(domain="operational") in scopes


def test_superuser_is_unconfined(staff_user):
    user = staff_user(groups=[], office=None, is_superuser=True)
    assert get_user_scopes(user) == [Scope(domain="admin")]


def test_scope_bound_to_another_office_is_dropped(basic_world, other_office, staff_user):
    from apps.identity_access.models import Role, UserRole

    user = staff_user(groups=[])
    role = Role.objects.create(
        keycloak_role="ops-agents",
        name="Operational agent",
        scopes=[{"domain": "operational", "office": str(other_office.id)}],
    )
    UserRole.objects.create(user=user, role=role)
    assert get_user_scopes(user) == []


def test_supervisor_keeps_restricted_visibility_after_confinement(basic_world, staff_user):
    """Regression guard: _scope_key includes office_id, so rewriting a scope's
    office without remapping restricted_scope_keys would silently hide every
    restricted ticket from supervisors."""
    from apps.identity_access.scope import _scope_key

    user = staff_user(groups=["ops-supervisors"])
    snapshot = get_authority_snapshot(user)
    assert len(snapshot.scopes) == 1
    assert _scope_key(snapshot.scopes[0]) in snapshot.restricted_scope_keys


def test_officer_sees_own_office_tickets_only(basic_world, other_office, staff_user, ticket_factory):
    from apps.tickets.models import Ticket

    mine = ticket_factory(office=basic_world["office"])
    theirs = ticket_factory(office=other_office)

    visible = scope_ticket_queryset(
        staff_user(groups=["ops-agents"]),
        Ticket.objects.all(),
    )

    assert mine in visible
    assert theirs not in visible


def test_service_desk_sees_every_office(basic_world, other_office, staff_user, ticket_factory):
    from apps.tickets.models import Ticket

    mine = ticket_factory(office=basic_world["office"])
    theirs = ticket_factory(office=other_office)

    visible = scope_ticket_queryset(
        staff_user(groups=["service-desk-agents"], office=None),
        Ticket.objects.all(),
    )

    assert mine in visible
    assert theirs in visible


def test_service_desk_cannot_see_restricted_tickets(basic_world, staff_user, ticket_factory):
    from apps.tickets.models import Ticket

    restricted = ticket_factory(office=basic_world["office"], confidentiality="restricted")

    visible = scope_ticket_queryset(
        staff_user(groups=["service-desk-agents"], office=None),
        Ticket.objects.all(),
    )

    assert restricted not in visible


def test_station_is_recorded_but_never_confines(basic_world, staff_user, ticket_factory):
    """Ticket.queue is nullable, so confining by station would blind a counter
    officer to most of their own office. Station records, office confines."""
    from apps.organisations.models import ServiceLocation
    from apps.tickets.models import Ticket

    station = ServiceLocation.objects.create(office=basic_world["office"], name="Counter-5")
    officer = staff_user(groups=["ops-agents"], station=station)
    queueless = ticket_factory(office=basic_world["office"])
    assert queueless.queue is None

    visible = scope_ticket_queryset(officer, Ticket.objects.all())

    assert queueless in visible
    assert all(scope.queue_id is None for scope in get_user_scopes(officer))
```

The last three tests need a `ticket_factory`. Add this to `backend/conftest.py` and stage it with this task. `Ticket` requires `number`, `domain`, `title`, `status`, `priority`, `channel`, `requester`, `service`, `request_type` and `office` — `status` is a non-null FK to `workflow.Status` and `channel` has no default, so neither can be omitted. This mirrors the ticket builder already used in `apps/identity_access/tests/test_scope.py:144`:

```python
@pytest.fixture
def ticket_factory(basic_world):
    """Create a minimal valid operational ticket."""
    from apps.tickets.models import Ticket
    from apps.workflow.models import Status

    counter = {"n": 0}

    def _make(*, office=None, confidentiality="normal", **kwargs):
        counter["n"] += 1
        service = basic_world["gen_info"]
        return Ticket.objects.create(
            number=f"OFC-{counter['n']:05d}",
            domain="operational",
            title=f"Ticket {counter['n']}",
            status=Status.objects.get(domain="operational", code="new"),
            priority="P3",
            channel="web",
            requester=basic_world["contact"],
            service=service,
            request_type=service.request_types.get(),
            office=office if office is not None else basic_world["office"],
            confidentiality=confidentiality,
            **kwargs,
        )

    return _make
```

`seed_workflow()` runs inside `basic_world`, so the `new` status exists. `service.request_types.get()` works because `basic_world` creates exactly one request type per service.

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest -q apps/identity_access/tests/test_office_boundary.py`
Expected: the confinement tests FAIL — `get_user_scopes` returns `Scope(domain="operational")` with `office_id=None`. The auditor, service desk and superuser tests may already pass; that is fine.

- [ ] **Step 3: Implement the boundary**

In `backend/apps/identity_access/scope.py`, change the dataclasses import at the top of the file:

```python
from dataclasses import dataclass, replace
```

Add the constant next to `_CROSS_OFFICE_ROLES`:

```python
_OFFICE_BOUND_DOMAINS = frozenset({"operational", "it"})
```

Add the function immediately before `_build_authority_snapshot`:

```python
def _office_boundary_id(user: object) -> str | None:
    """Return the officer's active office id, or ``None`` if they have none."""
    office = getattr(user, "office", None)
    if office is None or not getattr(office, "is_active", False):
        return None
    return str(office.id)


def _apply_office_boundary(
    snapshot: AuthoritySnapshot,
    user: object,
) -> AuthoritySnapshot:
    """Confine operational and IT authority to the officer's office.

    ``admin`` scopes pass through untouched so a Keycloak misconfiguration can
    never lock out system administration. Cross-office identities — the service
    desk and auditors — are exempt entirely.

    ``_scope_key`` includes ``office_id``, so every rewritten scope must have its
    restricted-view key remapped in the same pass. Skipping that would silently
    strip restricted-ticket visibility from every supervisor.
    """
    if snapshot.cross_office_identity:
        return snapshot

    boundary = _office_boundary_id(user)
    scopes: list[Scope] = []
    restricted_scope_keys: set[ScopeKey] = set()

    for scope in snapshot.scopes:
        was_restricted = _scope_key(scope) in snapshot.restricted_scope_keys

        if scope.domain not in _OFFICE_BOUND_DOMAINS:
            scopes.append(scope)
            if was_restricted:
                restricted_scope_keys.add(_scope_key(scope))
            continue

        if boundary is None:
            continue
        if scope.office_id is not None and scope.office_id != boundary:
            continue

        bound = replace(scope, office_id=boundary)
        scopes.append(bound)
        if was_restricted:
            restricted_scope_keys.add(_scope_key(bound))

    return replace(
        snapshot,
        scopes=tuple(_normalise_scopes(scopes)),
        restricted_scope_keys=frozenset(restricted_scope_keys),
    )
```

- [ ] **Step 4: Wire it into the snapshot builder**

In `_build_authority_snapshot`, change the non-superuser return:

```python
    if not _is_superuser(user):
        return _apply_office_boundary(resolved, user)
```

Leave the superuser branch below it untouched — it builds its own `admin` snapshot and must stay unconfined.

- [ ] **Step 5: Run the boundary tests**

Run: `docker compose exec backend pytest -q apps/identity_access/tests/test_office_boundary.py`
Expected: all pass.

- [ ] **Step 6: Run the full suite and collect the fallout**

Run: `docker compose exec backend pytest -q 2>&1 | tail -60`
Expected: **failures across many modules.** Every test that builds a user with operational or IT groups and no office now resolves to zero scopes. This is the confinement working.

Get the failing modules:

Run: `docker compose exec backend pytest -q --tb=no 2>&1 | grep -E "^(FAILED|ERROR)" | cut -d: -f1 | sort -u`

- [ ] **Step 7: Migrate the failing fixtures**

For each module the previous step listed, apply this mechanical change:

1. Open the module and find its local user helper — typically `def _user(groups)` or `def _persisted_user(*, groups)` calling `User.objects.create(...)`.
2. Give the created user an office. The lowest-friction edit keeps the helper's signature and adds the office inside it, taking it from the `basic_world` fixture the module already uses:

```python
def _user(groups, *, office=None, basic_world=None):
    user = User.objects.create(
        username=f"user-{uuid4().hex}",
        keycloak_subject=f"subject-{uuid4().hex}",
        keycloak_groups=groups,
        office=office,
    )
    user._groups = groups
    return user
```

   Where the module already receives `basic_world`, prefer deleting the local helper and using the `staff_user` fixture from Task 7 instead — that is the intended end state:

```python
def test_something(basic_world, staff_user):
    user = staff_user(groups=["ops-agents"])
```

3. Where a test's subject genuinely has no office and the test asserts it can still act, that test was asserting unconfined behaviour that no longer exists. Do not paper over it with an office — read the test, decide whether its intent is still valid, and either give the user an office (if the test is about something else) or update the assertion (if the test was about scope breadth). Note any test you change in this second way in the commit message.
4. Re-run that module: `docker compose exec backend pytest -q apps/<app>/tests/<module>.py`

Work module by module. Do not batch-edit with `sed` — step 3 requires reading each failure.

- [ ] **Step 8: Run the full suite until green**

Run: `docker compose exec backend pytest -q`
Expected: all pass.

- [ ] **Step 9: Run the quality gate**

Run: `docker compose exec backend ruff check .`
Expected: clean.

Run: `docker compose exec backend python manage.py makemigrations --check --dry-run`
Expected: "No changes detected".

- [ ] **Step 10: Commit**

```bash
git add backend/apps/identity_access/scope.py backend/apps/identity_access/tests/test_office_boundary.py backend/conftest.py backend/apps
git commit -m "feat(identity): confine operational and IT authority to the officer's office"
```

---

### Task 10: Seed script office flags

**Files:**
- Modify: `scripts/seed_keycloak_user.py`

**Interfaces:**
- Consumes: the `office` and `station` Keycloak user attributes read by Task 1's mappers.
- Produces: `--office` and `--station` command-line flags.

This script talks to a live Keycloak and has no test coverage today. Verify it by running it against the local stack rather than by unit test.

- [ ] **Step 1: Add the flags**

In `scripts/seed_keycloak_user.py`, the parser variable is named `ap`. Add alongside the existing `--group` argument:

```python
    ap.add_argument("--office", default="", help="Office code, e.g. MBB")
    ap.add_argument("--station", default="", help="Station name within the office")
```

- [ ] **Step 2: Send the attributes on create**

Keycloak stores user attributes as lists of strings. Change `create_user` to accept them:

```python
def create_user(
    token: str,
    username: str,
    first: str,
    last: str,
    email: str,
    attributes: dict | None = None,
) -> dict:
    payload = {
        "username": username,
        "enabled": True,
        "firstName": first,
        "lastName": last,
        "email": email,
        "emailVerified": True,
    }
    if attributes:
        payload["attributes"] = attributes
    code, body = _http("POST", f"{KEYCLOAK_BASE}/admin/realms/{REALM}/users", token, payload)
```

The rest of `create_user` is unchanged.

- [ ] **Step 3: Add an attribute update for existing users**

The script is idempotent, but its existing-user branch only resets the password and group — there is no update helper to reuse, so add one. Keycloak's `PUT /users/{id}` replaces the representation, so merge into the representation `find_user` already returned rather than sending attributes alone. Add next to `set_password`:

```python
def update_user_attributes(token: str, user: dict, attributes: dict) -> None:
    """Merge attributes into an existing user and PUT the representation back."""
    if not attributes:
        return
    payload = dict(user)
    merged = dict(payload.get("attributes") or {})
    merged.update(attributes)
    payload["attributes"] = merged
    code, body = _http(
        "PUT",
        f"{KEYCLOAK_BASE}/admin/realms/{REALM}/users/{user['id']}",
        token,
        payload,
    )
    if code not in (204,):
        raise RuntimeError(f"update user attributes failed: HTTP {code} {body}")
```

- [ ] **Step 4: Wire both branches in main()**

Build the attribute dict after `args = ap.parse_args()`:

```python
    attributes: dict[str, list[str]] = {}
    if args.office:
        attributes["office"] = [args.office]
    if args.station:
        attributes["station"] = [args.station]
```

Then change the create/update branch:

```python
    existing = find_user(token, args.username)
    if existing:
        user = existing
        print(f"   user exists: id={user['id']} — updating password, group & attributes")
        update_user_attributes(token, user, attributes)
    else:
        user = create_user(
            token, args.username, args.first, args.last, args.email, attributes
        )
```

- [ ] **Step 5: Update the usage docstring**

Change the `Usage:` line at the top of the module:

```
    python scripts/seed_keycloak_user.py [--username alice] [--password p@ssw0rd] [--group ops-agents] [--office MBB] [--station Counter-1]
```

- [ ] **Step 6: Verify against the local stack**

Run: `make up`, then:

```bash
python scripts/seed_keycloak_user.py --username deskofficer --group service-desk-agents
```

```bash
python scripts/seed_keycloak_user.py --username manziniofficer --group ops-agents --office TST-1
```

Expected: both exit 0. Confirm in the Keycloak admin console that `manziniofficer` has an `office` attribute of `TST-1` and `deskofficer` has none. Re-run the second command with `--office OTH-1` and confirm the attribute changes, proving the update path works.

- [ ] **Step 7: Commit**

```bash
git add scripts/seed_keycloak_user.py
git commit -m "feat(scripts): seed Keycloak users with an office and station"
```

---

## Deployment Sequence

The spec requires realm configuration to precede confinement. Tasks 1 through 8 are all safe to deploy independently — they record data and add a role without confining anything. Task 9 is the cutover.

1. Deploy Tasks 1–8.
2. Import the updated realm into the running Keycloak (`infrastructure/keycloak/realm-mhc.json`).
3. Populate the `office` attribute on every existing Keycloak staff user.
4. Confirm officers have a stored office:
   `docker compose exec backend python manage.py shell -c "from apps.identity_access.models import User; print(User.objects.filter(office__isnull=True, is_active=True).values_list('username', flat=True))"`
   Expected: only service desk agents, auditors and system administrators appear.
5. Deploy Task 9.

Deploying Task 9 before step 3 leaves every officer with an empty queue.

## Out of Scope

Named in the spec as excluded; do not build these:

- an administrative user-management API or screen (PRD FR-089);
- editing an officer's office from inside this application;
- confinement by station, service or queue;
- a stored lead officer per office;
- office-aware routing, SLA calendars or reporting filters;
- frontend changes consuming the new `/me` fields.
