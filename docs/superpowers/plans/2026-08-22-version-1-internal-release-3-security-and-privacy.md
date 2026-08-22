# Version 1 Internal Security and Privacy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the internal authorization, PII, monitoring and audit blockers that remain after public self-service is removed from Version 1.

**Architecture:** Authority resolution becomes deny-by-default when persisted assignments exist, even when expired. Every internal API declares an action policy, ticket access excludes system administration, contacts are projected from visible tickets, monitoring uses authenticated replay-safe receipts, IT children use a non-person sentinel requester, and audit storage is append-only outside the approved retention path.

**Tech Stack:** Django 5.2, Django REST Framework, PostgreSQL, Keycloak role claims, pytest.

**Spec:** `docs/superpowers/specs/2026-08-22-version-1-internal-staff-release-design.md`

## Global Constraints

- Anonymous, inactive, roleless and expired-only identities are denied.
- Persisted role assignments are the authority source whenever any assignment rows exist; stale group claims cannot restore expired authority.
- System administration does not grant Operational or IT ticket custody.
- Auditors are read-only.
- IT tickets and audit payloads do not receive requester PII from Operational parents.
- Monitoring ingestion remains in Version 1 but requires authentication, freshness, replay protection and atomic idempotency.
- Use test-first changes and commit only the files listed by each task.

---

### Task 1: Persisted-role revocation and ticket custody separation

**Files:**
- Modify: `backend/apps/identity_access/scope.py`
- Modify: `backend/apps/identity_access/tests/test_scope.py`
- Modify: `backend/apps/tickets/eligibility.py`
- Modify: `backend/apps/tickets/permissions.py`
- Modify: `backend/apps/tickets/views.py`
- Modify: `backend/apps/tickets/tests/test_permissions.py`
- Modify: `backend/apps/tickets/tests/test_scope_api.py`
- Modify: `backend/apps/reporting/tests/test_permissions.py`

**Interfaces:**
- Produces: `_persisted_assignments(user) -> list[_RoleAssignment] | None`, where `None` means no rows and `[]` means rows exist but none are active
- Produces: `HasTicketAuthority`, permitting only an Operational or IT scope
- Removes: admin-scope matching as a ticket wildcard

- [ ] **Step 1: Reverse the unsafe expiry regression and add negative custody tests**

Change `test_only_expired_persisted_assignments_restore_legacy_group_fallback` to
assert no visible tickets and an empty authority snapshot. Parameterize the stale
claim source across request groups, stored Keycloak groups and Django groups.

Add API assertions:

```python
@pytest.mark.parametrize("groups", [[], ["system-admins"]])
def test_non_ticket_identities_are_denied_ticket_collection(groups):
    ...
    assert response.status_code == 403
```

Assert system administrators receive `403` for Operational/IT dashboards,
assignment, transition, notes, messages and attachments. Keep administration APIs
available to them.

- [ ] **Step 2: Run the focused role tests and observe failure**

```powershell
docker compose exec -T backend pytest apps/identity_access/tests/test_scope.py apps/tickets/tests/test_permissions.py apps/tickets/tests/test_scope_api.py apps/reporting/tests/test_permissions.py -q
```

- [ ] **Step 3: Preserve expired persisted assignments as an authoritative empty set**

Refactor assignment resolution so it returns:

```python
persisted = list(assignments.select_related("role", "office").all())
if not persisted:
    return None
return [
    assignment
    for assignment in persisted
    if assignment.expires_at is None or assignment.expires_at > timezone.now()
]
```

`_build_authority_snapshot` must call `_snapshot_from_persisted([])` instead of
falling back to groups. Set `uses_persisted_roles=True` even for the empty active
set.

- [ ] **Step 4: Remove administrative wildcard access to tickets**

In `scope_ticket_queryset`, ignore `admin` scopes instead of translating them to
`Q(pk__isnull=False)`. Remove `admin`, `admin-scope` and `system-admins` from ticket
reassignment, restricted visibility, transition and mutation role sets. Remove the
superuser ticket-role shortcut; a Django superuser remains able to administer the
platform through Django admin but receives no application ticket custody without a
separate Operational or IT assignment.

Add `HasTicketAuthority` to `TicketViewSet.permission_classes`; it returns true only
when the authority snapshot contains an `operational` or `it` scope.

- [ ] **Step 5: Run the role suite**

Run the command from Step 2.

Expected: expired-only, roleless and system-admin identities fail closed; valid
Operational, IT, security and auditor identities retain their defined visibility.

- [ ] **Step 6: Commit the custody boundary**

```powershell
git add backend/apps/identity_access/scope.py backend/apps/identity_access/tests/test_scope.py backend/apps/tickets/eligibility.py backend/apps/tickets/permissions.py backend/apps/tickets/views.py backend/apps/tickets/tests/test_permissions.py backend/apps/tickets/tests/test_scope_api.py backend/apps/reporting/tests/test_permissions.py
git commit -m "fix: enforce revocation and ticket custody boundaries"
```

### Task 2: Scoped contact retrieval without generic PII mutation

**Files:**
- Create: `backend/apps/contacts/permissions.py`
- Create: `backend/apps/contacts/tests/test_permissions.py`
- Modify: `backend/apps/contacts/api.py`
- Modify: `backend/apps/contacts/views.py`

**Interfaces:**
- Produces: `visible_contacts(user, request) -> QuerySet[Contact]`
- Produces: read-only `ContactViewSet` list/retrieve/duplicates actions
- Consumes: `scope_ticket_queryset`

- [ ] **Step 1: Write the contact role, PII and pagination tests**

Create contacts attached to an in-scope normal Operational ticket, an out-of-office
ticket, a restricted ticket and an IT ticket. Assert:

- Operational agent sees only the in-scope normal contact;
- Operational supervisor also sees the in-office restricted contact;
- IT agent, roleless identity and system administrator receive `403`;
- auditor reads visible contacts but cannot mutate;
- `POST`, `PUT`, `PATCH` and `DELETE` on the generic contact endpoint return `405`;
- duplicate suggestions never return an out-of-scope contact;
- 101 visible contacts paginate without `500`, duplicates or missing rows.

- [ ] **Step 2: Run the tests and observe failure**

```powershell
docker compose exec -T backend pytest apps/contacts/tests/test_permissions.py -q
```

Expected: the current queryset slice raises during cursor pagination and roleless
or cross-domain access is too broad.

- [ ] **Step 3: Implement visibility through scoped tickets**

Build the contact queryset from requester IDs of scoped Operational tickets:

```python
visible_ticket_requesters = scope_ticket_queryset(
    user,
    Ticket.objects.filter(domain=Ticket.Domain.OPERATIONAL),
    request=request,
).values("requester_id")
return Contact.objects.filter(id__in=Subquery(visible_ticket_requesters))
```

Use a read-only viewset and retain the duplicates action as GET-only. Apply search
then `order_by("full_name", "id")`; do not slice before DRF cursor pagination.
Contact creation and refresh remain inside the atomic staff-intake service.

- [ ] **Step 4: Make the serializer projection explicit**

Expose only `id`, `full_name`, operational contact methods, language, consent and
verification status needed by staff. Keep national ID hash, notes, opt-out metadata
and unrelated methods absent. Do not claim masking while returning raw fields;
name the serializer `StaffContactSerializer` and document its authorized purpose.

- [ ] **Step 5: Run contact and intake tests**

```powershell
docker compose exec -T backend pytest apps/contacts/tests/test_permissions.py apps/tickets/tests/test_intake_api.py -q
```

- [ ] **Step 6: Commit contact scoping**

```powershell
git add backend/apps/contacts/permissions.py backend/apps/contacts/tests/test_permissions.py backend/apps/contacts/api.py backend/apps/contacts/views.py
git commit -m "fix: scope staff contact retrieval to visible tickets"
```

### Task 3: Explicit policies for knowledge, automation, audit and administration

**Files:**
- Create: `backend/apps/identity_access/api_permissions.py`
- Create: `backend/tests/test_internal_api_role_matrix.py`
- Modify: `backend/apps/knowledge/views.py`
- Modify: `backend/apps/automation/views.py`
- Modify: `backend/apps/audit/views.py`
- Modify: `backend/apps/administration/views.py`

**Interfaces:**
- Produces: `effective_role_keys(user, request=None) -> frozenset[str]`
- Produces: `HasAdminAuthority`, `HasAuditAuthority`, `HasDomainAuthority`
- Consumes: `AuthoritySnapshot.role_grants`, `group_role_keys`, `uses_persisted_roles`

- [ ] **Step 1: Write the complete internal API action matrix**

Use rollback-safe API tests for list, retrieve, create, update and delete. Assert:

| Surface | Agent | Supervisor/lead | Auditor | System admin | Roleless |
|---|---:|---:|---:|---:|---:|
| Domain knowledge read | own domain | own domain | both domains | both domains | deny |
| Domain knowledge write | deny | own domain | deny | both domains | deny |
| Automation rules | deny | deny | read only | full CRUD | deny |
| Audit API | deny | deny | read only | deny | deny |
| Administration API | deny | deny | deny | allowed | deny |

For knowledge, assert restricted articles are visible only to the existing
restricted-view roles and auditors. Assert all denied writes leave row counts and
audit counts unchanged.

- [ ] **Step 2: Run the matrix and observe failure**

```powershell
docker compose exec -T backend pytest tests/test_internal_api_role_matrix.py -q
```

- [ ] **Step 3: Add reusable deny-by-default permissions**

Resolve role keys from active persisted grants when `uses_persisted_roles` is true;
otherwise use snapshot group keys. Never merge stale group keys into persisted
authority.

Implement DRF permissions whose safe/write behavior matches the table. Use
`has_object_permission` for `KnowledgeArticle.domain` and its restricted audience.
Filter knowledge querysets before serialization so list counts cannot disclose
inaccessible rows.

- [ ] **Step 4: Apply policies to every action**

Set explicit `permission_classes` or `get_permissions()` on all four surfaces.
The current empty-result audit and administration endpoints must no longer use only
`IsAuthenticated`. Automation write actions must record actor and before/after
values in the audit stream.

- [ ] **Step 5: Run matrix, permission audit and app tests**

```powershell
docker compose exec -T backend pytest tests/test_internal_api_role_matrix.py apps/knowledge apps/automation apps/audit apps/administration tests/test_permission_audit.py -q
docker compose exec -T backend python scripts/permission_audit.py
```

Expected: the live matrix and permission audit agree; no roleless create returns
`201`.

- [ ] **Step 6: Commit the action policies**

```powershell
git add backend/apps/identity_access/api_permissions.py backend/tests/test_internal_api_role_matrix.py backend/apps/knowledge/views.py backend/apps/automation/views.py backend/apps/audit/views.py backend/apps/administration/views.py
git commit -m "fix: enforce internal api action policies"
```

### Task 4: Authenticated, replay-safe monitoring ingestion

**Files:**
- Create: `backend/apps/integrations/webhook_security.py`
- Create: `backend/apps/integrations/tests/test_monitoring_security.py`
- Create: `backend/apps/integrations/migrations/0002_monitoringreceipt.py`
- Modify: `backend/apps/integrations/models.py`
- Modify: `backend/apps/integrations/monitoring.py`
- Modify: `backend/config/settings/base.py`
- Modify: `backend/config/settings/prod.py`
- Modify: `.env.example`
- Modify: `docker-compose.prod.yml`

**Interfaces:**
- Produces: `verify_monitoring_signature(request) -> None`
- Produces: `MonitoringReceipt(source, external_id, request_digest, ticket, created_at)` with unique `(source, external_id)`
- Consumes headers: `X-MHC-Timestamp`, `X-MHC-Signature`

- [ ] **Step 1: Write negative, freshness and concurrency tests**

Assert missing, malformed and incorrect signatures return `401`; timestamps older
than `MONITORING_WEBHOOK_MAX_AGE_SECONDS` return `401`; a signed replay with the
same source/external ID returns the first ticket and does not create another;
reusing the ID with a changed digest returns `409`; two concurrent signed requests
produce one ticket and one receipt.

- [ ] **Step 2: Run the monitoring test and observe failure**

```powershell
docker compose exec -T backend pytest apps/integrations/tests/test_monitoring_security.py -q
```

- [ ] **Step 3: Implement HMAC authentication**

Require a production secret of at least 32 characters. Verify:

```python
signed = timestamp.encode() + b"." + request.body
expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
if not hmac.compare_digest(expected, supplied):
    raise AuthenticationFailed("Invalid monitoring signature")
```

Parse the timestamp as Unix seconds, reject future skew and expired requests, and
log only source, external ID and correlation ID.

- [ ] **Step 4: Add the atomic receipt model**

Claim `(source, external_id)` inside the same transaction that creates the ticket,
SLA, audit and outbox event. Store the request digest. Handle unique-constraint
races by loading the committed receipt; never use a non-atomic `.exists()` check.

- [ ] **Step 5: Run monitoring and production settings tests**

```powershell
docker compose exec -T backend python manage.py makemigrations --check --dry-run
docker compose exec -T backend pytest apps/integrations/tests/test_monitoring_security.py apps/health/tests/test_prod_settings.py -q
```

- [ ] **Step 6: Commit monitoring security**

```powershell
git add backend/apps/integrations backend/config/settings/base.py backend/config/settings/prod.py backend/apps/health/tests/test_prod_settings.py .env.example docker-compose.prod.yml
git commit -m "fix: authenticate and deduplicate monitoring ingestion"
```

### Task 5: Sanitized IT child identity boundary

**Files:**
- Modify: `backend/apps/tickets/it_child.py`
- Modify: `backend/apps/tickets/tests/test_it_child.py`
- Modify: `backend/apps/tickets/tests/test_it_child_integrity.py`

**Interfaces:**
- Produces: `IT_REFERRAL_CONTACT_ID`, a stable UUID for the non-person system contact
- Produces: `_it_referral_contact() -> Contact`
- Removes: parent requester ID and contact data from the child and its audit payload

- [ ] **Step 1: Write field-by-field privacy regressions**

Give the parent a unique name, email, phone, national-ID hash, notes, matter
reference, description and attachments. Create a child and assert none appear in
the child fields, related contact, messages, notes, attachments, audit payload,
outbox payload or serialized IT detail. Assert the child requester differs from the
parent and contains only `full_name="Internal IT referral"` with blank PII fields.

Retain tests proving the explicit sanitized summary, technical priority, office,
safe status and link are preserved. Remove the `carry_matter_reference` option from
the public service signature.

- [ ] **Step 2: Run IT-child tests and observe failure**

```powershell
docker compose exec -T backend pytest apps/tickets/tests/test_it_child.py apps/tickets/tests/test_it_child_integrity.py -q
```

- [ ] **Step 3: Use a deterministic non-person requester**

Resolve a contact by a fixed UUID:

```python
IT_REFERRAL_CONTACT_ID = UUID("00000000-0000-0000-0000-000000000017")

contact, _ = Contact.objects.get_or_create(
    id=IT_REFERRAL_CONTACT_ID,
    defaults={"full_name": "Internal IT referral"},
)
```

Set the child requester to that contact, never copy the matter reference or
attachments, and remove `requester_id` and parent requester values from event
payloads. Keep the ticket link for controlled status synchronization; serializers
must scope both linked ticket directions before returning a relationship.

- [ ] **Step 4: Run privacy and serialization tests**

```powershell
docker compose exec -T backend pytest apps/tickets/tests/test_it_child.py apps/tickets/tests/test_it_child_integrity.py apps/tickets/tests/test_tracking.py apps/tickets/tests/test_activity.py -q
```

- [ ] **Step 5: Commit IT isolation**

```powershell
git add backend/apps/tickets/it_child.py backend/apps/tickets/tests/test_it_child.py backend/apps/tickets/tests/test_it_child_integrity.py
git commit -m "fix: remove requester identity from it child tickets"
```

### Task 6: Immutable audit interfaces and scoped reporting

**Files:**
- Create: `backend/apps/audit/migrations/0003_audit_immutability.py`
- Modify: `backend/apps/audit/models.py`
- Modify: `backend/apps/audit/admin.py`
- Create: `backend/apps/audit/tests/test_immutability.py`
- Modify: `backend/apps/administration/management/commands/apply_retention.py`
- Modify: `backend/apps/reporting/views.py`
- Modify: `backend/apps/reporting/tests/test_permissions.py`

**Interfaces:**
- Produces: append-only `AuditEvent` ORM and Django admin
- Produces: PostgreSQL trigger allowing delete only when local setting `mhc.audit_retention=on`
- Produces: scoped dashboards for any actor with a matching domain scope

- [ ] **Step 1: Write immutable ORM, admin and database tests**

Assert model save, queryset update/delete, instance delete and admin change/delete
are denied. Under PostgreSQL, execute raw UPDATE and DELETE and assert the trigger
rejects both. Assert the retention command can delete expired audit rows only after
setting the transaction-local retention flag and still writes its disposal
certificate.

- [ ] **Step 2: Write dashboard reconciliation tests**

For office-bound agents, supervisors, IT leads and auditors, compare every returned
dashboard count to a separately scoped source queryset. Assert roleless and system
admin receive `403`. The dashboard must accept a matching office-bound domain scope;
it must not require a globally unrestricted scope.

- [ ] **Step 3: Run tests and observe failure**

```powershell
docker compose exec -T backend pytest apps/audit/tests/test_immutability.py apps/reporting/tests/test_permissions.py -q
```

- [ ] **Step 4: Enforce append-only audit behavior**

Use an `AuditEventQuerySet` whose `update()` and `delete()` raise
`ValidationError`, reject non-adding model saves and instance deletes, and register
a read-only `ModelAdmin` with all fields read-only and add/change/delete permissions
false.

The PostgreSQL migration installs a `BEFORE UPDATE OR DELETE` trigger. UPDATE is
always rejected. DELETE is accepted only when
`current_setting('mhc.audit_retention', true) = 'on'`. The retention command issues
`SET LOCAL mhc.audit_retention = 'on'` within its approved transaction before its
existing raw deletion.

- [ ] **Step 5: Allow scoped domain dashboards and reconcile values**

Replace the global `has_unrestricted_domain_scope` gate with a helper that accepts
at least one matching domain scope, then continue to aggregate only over
`scope_ticket_queryset`. Keep CSV export domain checks and PII projection tests.

- [ ] **Step 6: Run audit, reporting and retention suites**

```powershell
docker compose exec -T backend pytest apps/audit apps/reporting apps/administration/tests/test_retention.py -q
```

- [ ] **Step 7: Commit audit and reporting controls**

```powershell
git add backend/apps/audit backend/apps/administration/management/commands/apply_retention.py backend/apps/reporting/views.py backend/apps/reporting/tests/test_permissions.py
git commit -m "fix: enforce immutable audit and scoped reporting"
```
