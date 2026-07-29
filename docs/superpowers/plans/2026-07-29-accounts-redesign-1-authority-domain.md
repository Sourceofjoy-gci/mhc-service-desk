# Accounts Redesign 1: Authority and Domain Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Accounts domain, structured financial-enquiry data, catalogue-safe intake routing, and least-privilege Keycloak authority without yet exposing the new staff workflow UI.

**Architecture:** Domain values and financial fields are additive Django schema changes. A small capability registry converts allowlisted Keycloak memberships into explicit authority, while the existing scope engine remains responsible for row visibility. Catalogue routing derives the domain from Service and Request Type, and trusted integration failures are retained as metadata-only routing exceptions instead of being guessed into Operational.

**Tech Stack:** Django 5.2, Django REST Framework 3.15, PostgreSQL, pytest/pytest-django, Keycloak realm JSON, existing ticket/catalogue/email/SLA modules.

## Global Constraints

- Implement the approved contract in `docs/superpowers/specs/2026-07-29-accounts-domain-role-workflow-redesign.md`.
- Complete this plan before `2026-07-29-accounts-redesign-2-workflow-allocation-api.md`.
- Preserve unrelated pre-existing working-tree changes; stage only task-owned files or hunks after reviewing `git diff --cached`.
- Accounts handles enquiries only: payments, invoices, refunds, fees, receipts, and financial-status questions.
- Never add payment execution, refund execution, finance approval, card data, bank credentials, PINs, passwords, or authentication secrets.
- Accounts tickets default to Sensitive; Restricted access remains explicit.
- The `system-admins`/`admin` role grants technical administration only and no business-ticket scope.
- The `service-desk-managers`/`service-desk-manager` role grants Normal/Sensitive monitoring, assignment, and rerouting across Operational, IT, and Accounts, but no ticket action authority.
- Use allowlisted `groups` and `realm_access.roles` claims only; never trust arbitrary token strings.
- Apply test-driven development: run every new focused test in the red state before production edits.
- Migrations are additive except for the deliberate data migration that clears legacy business scopes from technical administrator roles.

## File Structure

- `backend/apps/identity_access/capabilities.py`: canonical capability names and membership-to-capability mapping only.
- `backend/apps/identity_access/scope.py`: domain/office/service/queue visibility and Restricted filtering.
- `backend/apps/tickets/routing.py`: catalogue-route validation and metadata-only routing-exception creation.
- `backend/apps/tickets/models.py`: Accounts fields and `IntakeRoutingException` persistence.
- `backend/apps/tickets/services.py`: ticket creation consumes validated routes; no duplicated route policy.
- `backend/apps/email_channel/models.py`: trusted mailbox-to-Service/Request Type mapping.
- `backend/apps/catalogue/models.py`, `backend/apps/workflow/models.py`, and `backend/apps/sla/models.py`: add the Accounts domain choice.
- `infrastructure/keycloak/realm-mhc.json`: realm roles and groups matching backend aliases.
- `backend/scripts/seed_dev.py`: idempotent Accounts catalogue and application-role seeds.

---

### Task 1: Add the Accounts domain and structured enquiry schema

**Files:**
- Modify: `backend/apps/tickets/models.py`
- Create: `backend/apps/tickets/migrations/0005_accounts_domain_fields_and_routing_exception.py`
- Modify: `backend/apps/catalogue/models.py`
- Create: `backend/apps/catalogue/migrations/0002_add_accounts_domain_and_review_policy.py`
- Modify: `backend/apps/workflow/models.py`
- Create: `backend/apps/workflow/migrations/0002_add_accounts_domain_choice.py`
- Modify: `backend/apps/sla/models.py`
- Create: `backend/apps/sla/migrations/0005_add_accounts_domain_choice.py`
- Modify: `backend/apps/email_channel/models.py`
- Create: `backend/apps/email_channel/migrations/0004_mailbox_catalogue_route_and_accounts.py`
- Modify: `backend/apps/whatsapp/models.py`
- Create: `backend/apps/whatsapp/migrations/0004_accounts_catalogue_route.py`
- Modify: `backend/apps/integrations/models.py`
- Create: `backend/apps/integrations/migrations/0002_integration_catalogue_route.py`
- Modify: `backend/apps/catalogue/api.py`
- Create: `backend/apps/tickets/tests/test_accounts_models.py`

**Interfaces:**
- Produces: `Ticket.Domain.ACCOUNTS == "accounts"`.
- Produces: `Ticket.FinancialEnquiryCategory` and `Ticket.FinancialVerificationStatus`.
- Produces: nullable/blank Accounts fields on `Ticket` and Request Type policy flags `requires_supervisor_review` and `requires_financial_verification`.
- Produces: `IntakeRoutingException` with metadata only; it must not contain message bodies or credentials.
- Produces: nullable `Mailbox.service`/`request_type` and `WhatsappAccount.service`/`request_type` route references for a compatibility deployment.
- Produces: `IntegrationRoute(provider, source, service, request_type, office)` for trusted non-message integrations such as monitoring.

- [ ] **Step 1: Write failing schema tests**

Create `backend/apps/tickets/tests/test_accounts_models.py` with explicit field and validation expectations:

```python
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.catalogue.models import RequestType, Service
from apps.email_channel.models import Mailbox
from apps.tickets.models import IntakeRoutingException, Ticket


pytestmark = pytest.mark.django_db


def test_accounts_domain_and_financial_defaults(basic_world):
    assert Ticket.Domain.ACCOUNTS == "accounts"
    assert Ticket.FinancialEnquiryCategory.PAYMENT == "payment"
    assert Ticket.FinancialVerificationStatus.NOT_REQUIRED == "not_required"
    assert Ticket._meta.get_field("enquiry_amount").null is True
    assert Ticket._meta.get_field("no_transaction_executed").default is False


def test_mailbox_route_must_match_service_domain(db):
    accounts = Service.objects.create(code="ACC-PAY", name="Payments", domain="accounts")
    request_type = RequestType.objects.create(
        service=accounts,
        code="PAY-STATUS",
        name="Payment status",
    )
    mailbox = Mailbox(
        address="finance@example.test",
        domain="operational",
        service=accounts,
        request_type=request_type,
    )
    with pytest.raises(ValidationError) as exc_info:
        mailbox.full_clean()
    assert "domain" in exc_info.value.message_dict


def test_routing_exception_stores_metadata_not_content(db):
    exception = IntakeRoutingException.objects.create(
        source="email",
        source_account="finance@example.test",
        reason_code="route_unconfigured",
        route_metadata={"service_code": "", "request_type_code": ""},
    )
    assert exception.status == "pending"
    assert not hasattr(exception, "description")
    assert "body" not in exception.route_metadata
```

- [ ] **Step 2: Run the model tests and verify the missing-schema failure**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_accounts_models.py -q
```

Expected: collection or assertions fail because the Accounts choices, financial fields, mailbox route fields, and routing-exception model do not exist.

- [ ] **Step 3: Add domain choices and financial fields**

Add these nested choices and fields to `Ticket`:

```python
class Domain(models.TextChoices):
    OPERATIONAL = "operational", "Operational"
    IT = "it", "IT"
    ACCOUNTS = "accounts", "Accounts"


class FinancialEnquiryCategory(models.TextChoices):
    PAYMENT = "payment", "Payment"
    INVOICE = "invoice", "Invoice"
    REFUND = "refund", "Refund"
    FEE = "fee", "Fee"
    RECEIPT = "receipt", "Receipt"
    FINANCIAL_STATUS = "financial_status", "Financial status"


class FinancialVerificationStatus(models.TextChoices):
    NOT_REQUIRED = "not_required", "Not required"
    PENDING = "pending", "Pending"
    VERIFIED = "verified", "Verified"
    NOT_FOUND = "not_found", "Not found"
    DISPUTED = "disputed", "Disputed"


financial_enquiry_category = models.CharField(
    max_length=32,
    choices=FinancialEnquiryCategory.choices,
    blank=True,
)
financial_reference = models.CharField(max_length=128, blank=True, db_index=True)
external_finance_reference = models.CharField(max_length=128, blank=True, db_index=True)
enquiry_amount = models.DecimalField(
    max_digits=14,
    decimal_places=2,
    null=True,
    blank=True,
)
enquiry_currency = models.CharField(max_length=3, blank=True)
financial_verification_status = models.CharField(
    max_length=32,
    choices=FinancialVerificationStatus.choices,
    default=FinancialVerificationStatus.NOT_REQUIRED,
)
no_transaction_executed = models.BooleanField(default=False)
```

Add `ACCOUNTS` to the explicit domain choices in `Service`, `Status`, `SlaPolicy`, and `Mailbox`. Add this field to `RequestType`:

```python
requires_supervisor_review = models.BooleanField(default=False)
requires_financial_verification = models.BooleanField(default=False)
```

Add nullable mailbox route fields so the schema can deploy before configuration:

```python
service = models.ForeignKey(
    "catalogue.Service",
    on_delete=models.PROTECT,
    null=True,
    blank=True,
    related_name="inbound_mailboxes",
)
request_type = models.ForeignKey(
    "catalogue.RequestType",
    on_delete=models.PROTECT,
    null=True,
    blank=True,
    related_name="inbound_mailboxes",
)
```

Implement `Mailbox.clean()` so both route fields are supplied together, the Request Type belongs to the Service, and the Service domain equals the mailbox domain.

Add the same Service/Request Type pair and validation rules to `WhatsappAccount`, including the Accounts domain choice. Add `IntegrationRoute` with `provider`, `source`, active Service, active Request Type, Office, and `is_active`; enforce a unique `(provider, source)` pair and validate that the Request Type belongs to the Service. This route is the authoritative mapping for monitoring and future trusted integrations.

Expose both Request Type policy flags in `RequestTypeSerializer` so the frontend can explain verification/review policy without inferring it.

- [ ] **Step 4: Add a metadata-only routing exception model**

Append to `backend/apps/tickets/models.py`:

```python
class IntakeRoutingException(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=32)
    source_account = models.CharField(max_length=255, blank=True)
    reason_code = models.CharField(max_length=64)
    route_metadata = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    resolved_ticket = models.ForeignKey(
        Ticket,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_routing_exceptions",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ticket_intake_routing_exception"
        ordering = ("created_at", "id")
```

Do not add raw subject, description, email body, attachment data, card data, or bank data to this model.

- [ ] **Step 5: Generate and inspect migrations**

Run:

```powershell
Set-Location backend
python manage.py makemigrations tickets catalogue workflow sla email_channel whatsapp integrations
python manage.py makemigrations --check --dry-run
```

Expected: the five named migrations contain only the described fields/model/choice-state changes, and the drift check prints `No changes detected`.

- [ ] **Step 6: Run schema tests and commit**

Run:

```powershell
pytest apps/tickets/tests/test_accounts_models.py apps/catalogue/tests apps/email_channel/tests/test_migrations.py apps/whatsapp/tests/test_migrations.py apps/integrations/tests -q
ruff check apps/tickets/models.py apps/catalogue/models.py apps/catalogue/api.py apps/workflow/models.py apps/sla/models.py apps/email_channel/models.py apps/whatsapp/models.py apps/integrations/models.py apps/tickets/tests/test_accounts_models.py
```

Expected: all commands exit 0.

Commit:

```powershell
git add backend/apps/tickets/models.py backend/apps/tickets/migrations/0005_accounts_domain_fields_and_routing_exception.py backend/apps/catalogue/models.py backend/apps/catalogue/api.py backend/apps/catalogue/migrations/0002_add_accounts_domain_and_review_policy.py backend/apps/workflow/models.py backend/apps/workflow/migrations/0002_add_accounts_domain_choice.py backend/apps/sla/models.py backend/apps/sla/migrations/0005_add_accounts_domain_choice.py backend/apps/email_channel/models.py backend/apps/email_channel/migrations/0004_mailbox_catalogue_route_and_accounts.py backend/apps/whatsapp/models.py backend/apps/whatsapp/migrations/0004_accounts_catalogue_route.py backend/apps/integrations/models.py backend/apps/integrations/migrations/0002_integration_catalogue_route.py backend/apps/tickets/tests/test_accounts_models.py
git diff --cached --check
git commit -m "feat(accounts): add financial enquiry domain schema"
```

---

### Task 2: Replace broad administrator access with explicit capabilities

**Files:**
- Create: `backend/apps/identity_access/capabilities.py`
- Modify: `backend/apps/identity_access/authentication.py`
- Modify: `backend/apps/identity_access/scope.py`
- Create: `backend/apps/identity_access/migrations/0003_reconcile_accounts_and_admin_roles.py`
- Modify: `backend/apps/tickets/permissions.py`
- Modify: `backend/apps/tickets/workflow.py`
- Modify: `backend/apps/identity_access/tests/test_authentication.py`
- Modify: `backend/apps/identity_access/tests/test_scope.py`
- Modify: `backend/apps/tickets/tests/test_permissions.py`
- Create: `backend/apps/tickets/tests/test_role_matrix_accounts.py`
- Modify: `infrastructure/keycloak/realm-mhc.json`

**Interfaces:**
- Produces: capability constants `TICKET_VIEW`, `TICKET_ACTION`, `TICKET_SELF_ASSIGN`, `TICKET_ASSIGN`, `TICKET_REROUTE`, `TICKET_MONITOR`, `TICKET_VIEW_RESTRICTED`, and `PLATFORM_ADMINISTER`.
- Produces: `capabilities_for_memberships(memberships: Iterable[str]) -> frozenset[str]`.
- Produces: `has_authority_capability(user, capability, *, request=None, snapshot=None) -> bool`.
- Updates: `AuthoritySnapshot.capabilities` contains explicit capability strings plus the existing `auditor` marker during compatibility.
- Consumes later: assignment, routing, action, reporting, and serializer capability checks.

- [ ] **Step 1: Write the failing role matrix tests**

Create a parameterised group-fallback matrix in `test_role_matrix_accounts.py`:

```python
import pytest

from apps.identity_access.capabilities import (
    PLATFORM_ADMINISTER,
    TICKET_ACTION,
    TICKET_ASSIGN,
    TICKET_MONITOR,
    TICKET_REROUTE,
    TICKET_SELF_ASSIGN,
    TICKET_VIEW,
    TICKET_VIEW_RESTRICTED,
)
from apps.identity_access.scope import get_authority_snapshot


@pytest.mark.parametrize(
    ("membership", "domains", "capabilities"),
    [
        ("staff", set(), set()),
        ("agent-operational", {"operational"}, {TICKET_VIEW, TICKET_ACTION, TICKET_SELF_ASSIGN}),
        ("supervisor-operational", {"operational"}, {TICKET_VIEW, TICKET_ACTION, TICKET_SELF_ASSIGN, TICKET_ASSIGN, TICKET_REROUTE, TICKET_VIEW_RESTRICTED}),
        ("agent-it", {"it"}, {TICKET_VIEW, TICKET_ACTION, TICKET_SELF_ASSIGN}),
        ("lead-it", {"it"}, {TICKET_VIEW, TICKET_ACTION, TICKET_SELF_ASSIGN, TICKET_ASSIGN, TICKET_REROUTE, TICKET_VIEW_RESTRICTED}),
        ("agent-accounts", {"accounts"}, {TICKET_VIEW, TICKET_ACTION, TICKET_SELF_ASSIGN}),
        ("supervisor-accounts", {"accounts"}, {TICKET_VIEW, TICKET_ACTION, TICKET_SELF_ASSIGN, TICKET_ASSIGN, TICKET_REROUTE, TICKET_VIEW_RESTRICTED}),
        ("service-desk-manager", {"operational", "it", "accounts"}, {TICKET_VIEW, TICKET_ASSIGN, TICKET_REROUTE, TICKET_MONITOR}),
        ("admin", set(), {PLATFORM_ADMINISTER}),
        ("auditor", {"operational", "it", "accounts"}, {TICKET_VIEW, TICKET_MONITOR, TICKET_VIEW_RESTRICTED}),
    ],
)
def test_role_authority_matrix(membership, domains, capabilities, user_factory):
    user = user_factory(groups=[membership])
    snapshot = get_authority_snapshot(user)
    assert {scope.domain for scope in snapshot.scopes} == domains
    assert capabilities <= snapshot.capabilities


def test_service_manager_does_not_gain_action_or_restricted(user_factory):
    snapshot = get_authority_snapshot(user_factory(groups=["service-desk-managers"]))
    assert TICKET_ACTION not in snapshot.capabilities
    assert TICKET_VIEW_RESTRICTED not in snapshot.capabilities


def test_system_admin_and_django_superuser_have_no_business_scope(user_factory):
    for user in (
        user_factory(groups=["system-admins"]),
        user_factory(groups=[], is_superuser=True),
    ):
        assert get_authority_snapshot(user).scopes == ()
```

Add authentication tests proving the three new group names and three realm-role aliases survive allowlist normalisation, while `unknown-privileged-role` is discarded.

- [ ] **Step 2: Run the role tests and verify existing broad-admin failures**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_role_matrix_accounts.py apps/identity_access/tests/test_authentication.py apps/identity_access/tests/test_scope.py -q
```

Expected: FAIL because Accounts/manager claims are discarded, capability constants do not exist, and administrators still receive the wildcard `admin` scope.

- [ ] **Step 3: Create the canonical capability registry**

Create `capabilities.py` with alias groups and no Django/model imports:

```python
from collections.abc import Iterable

TICKET_VIEW = "ticket.view"
TICKET_ACTION = "ticket.action"
TICKET_SELF_ASSIGN = "ticket.self_assign"
TICKET_ASSIGN = "ticket.assign"
TICKET_REROUTE = "ticket.reroute"
TICKET_MONITOR = "ticket.monitor"
TICKET_VIEW_RESTRICTED = "ticket.view_restricted"
PLATFORM_ADMINISTER = "platform.administer"

AGENT = frozenset({TICKET_VIEW, TICKET_ACTION, TICKET_SELF_ASSIGN})
SUPERVISOR = AGENT | {
    TICKET_ASSIGN,
    TICKET_REROUTE,
    TICKET_MONITOR,
    TICKET_VIEW_RESTRICTED,
}

ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "agent-operational": AGENT,
    "ops-agents": AGENT,
    "supervisor-operational": SUPERVISOR,
    "ops-supervisors": SUPERVISOR,
    "agent-it": AGENT,
    "it-agents": AGENT,
    "lead-it": SUPERVISOR,
    "it-leads": SUPERVISOR,
    "agent-accounts": AGENT,
    "accounts-agents": AGENT,
    "supervisor-accounts": SUPERVISOR,
    "accounts-supervisors": SUPERVISOR,
    "service-desk-manager": frozenset({TICKET_VIEW, TICKET_ASSIGN, TICKET_REROUTE, TICKET_MONITOR}),
    "service-desk-managers": frozenset({TICKET_VIEW, TICKET_ASSIGN, TICKET_REROUTE, TICKET_MONITOR}),
    "security-responders": frozenset({TICKET_VIEW, TICKET_VIEW_RESTRICTED}),
    "auditor": frozenset({TICKET_VIEW, TICKET_MONITOR, TICKET_VIEW_RESTRICTED, "auditor"}),
    "auditors": frozenset({TICKET_VIEW, TICKET_MONITOR, TICKET_VIEW_RESTRICTED, "auditor"}),
    "admin": frozenset({PLATFORM_ADMINISTER}),
    "system-admins": frozenset({PLATFORM_ADMINISTER}),
}


def capabilities_for_memberships(memberships: Iterable[str]) -> frozenset[str]:
    return frozenset(
        capability
        for membership in memberships
        for capability in ROLE_CAPABILITIES.get(membership, ())
    )
```

- [ ] **Step 4: Reconcile scopes and claim allowlists**

In `authentication.py`, add group names `accounts-agents`, `accounts-supervisors`, and `service-desk-managers`; add realm roles `agent-accounts`, `supervisor-accounts`, and `service-desk-manager`.

In `scope.py`:

- add Accounts scopes for agent/supervisor aliases;
- give managers unrestricted scopes in all three domains without Restricted keys;
- give auditors and security responders Accounts coverage;
- remove `admin` as a wildcard or valid business domain;
- stop granting business scope to `is_superuser`;
- build group and persisted capabilities with `capabilities_for_memberships`; and
- expose:

```python
def has_authority_capability(
    user: object,
    capability: str,
    *,
    request: Request | None = None,
    snapshot: AuthoritySnapshot | None = None,
) -> bool:
    authority = snapshot or get_authority_snapshot(user, request=request)
    return capability in authority.capabilities
```

Create a `RunPython` data migration that upserts `agent-accounts`, `supervisor-accounts`, and `service-desk-manager` Role rows with the approved scopes, and replaces scopes on `admin`/`system-admins` Role rows with `[]`. Use a no-op reverse so rollback never deletes assigned role records or restores wildcard administrator access.

- [ ] **Step 5: Update ticket permission helpers to consume capabilities**

Replace `ADMIN_GROUPS` mutation bypasses. Keep membership aliases only for determining domain-agent/supervisor ownership. Add exact helpers:

```python
def can_self_assign(user: User, ticket: Ticket, *, request: object | None = None) -> bool:
    return (
        ticket.assignee_id is None
        and has_authority_capability(user, TICKET_SELF_ASSIGN, request=request)
        and _has_ticket_domain_membership(user, ticket.domain)
    )


def can_assign(user: User, ticket: Ticket, *, request: object | None = None) -> bool:
    return has_authority_capability(user, TICKET_ASSIGN, request=request)


def can_reroute(user: User, ticket: Ticket, *, request: object | None = None) -> bool:
    return has_authority_capability(user, TICKET_REROUTE, request=request)
```

`eligible_assignee_queryset(ticket)` must include only active domain agents/supervisors, exclude auditors and technical-only administrators, and apply Restricted eligibility for Restricted tickets. Do not include a service-desk manager unless that user also holds a destination-domain agent/supervisor role.

Extend `_EQUIVALENT_STAFF_ROLES` in `workflow.py` with Accounts aliases and remove the `scope.domain == "admin"` transition bypass.

- [ ] **Step 6: Update the Keycloak realm**

Add realm roles:

```json
{ "name": "agent-accounts", "description": "Accounts enquiry agent" },
{ "name": "supervisor-accounts", "description": "Accounts enquiry supervisor" },
{ "name": "service-desk-manager", "description": "Cross-domain monitoring and allocation" }
```

Add groups with baseline `staff` plus their functional role:

```json
{
  "name": "accounts-agents",
  "path": "/accounts-agents",
  "realmRoles": ["staff", "agent-accounts"]
},
{
  "name": "accounts-supervisors",
  "path": "/accounts-supervisors",
  "realmRoles": ["staff", "supervisor-accounts"]
},
{
  "name": "service-desk-managers",
  "path": "/service-desk-managers",
  "realmRoles": ["staff", "service-desk-manager"]
}
```

Leave `system-admins` mapped to `staff` and `admin`; backend authority makes `admin` technical-only.

- [ ] **Step 7: Run the authority suite and commit**

Run:

```powershell
Set-Location backend
pytest apps/identity_access/tests apps/tickets/tests/test_permissions.py apps/tickets/tests/test_role_matrix_accounts.py apps/tickets/tests/test_scope_api.py apps/reporting/tests/test_permissions.py -q
ruff check apps/identity_access/capabilities.py apps/identity_access/authentication.py apps/identity_access/scope.py apps/tickets/permissions.py apps/tickets/workflow.py
python manage.py makemigrations --check --dry-run
```

Expected: all tests pass; existing tests that expected System Administrator business access are updated to expect no ticket access.

Commit:

```powershell
git add backend/apps/identity_access/capabilities.py backend/apps/identity_access/authentication.py backend/apps/identity_access/scope.py backend/apps/identity_access/migrations/0003_reconcile_accounts_and_admin_roles.py backend/apps/tickets/permissions.py backend/apps/tickets/workflow.py backend/apps/identity_access/tests/test_authentication.py backend/apps/identity_access/tests/test_scope.py backend/apps/tickets/tests/test_permissions.py backend/apps/tickets/tests/test_role_matrix_accounts.py infrastructure/keycloak/realm-mhc.json
git diff --cached --check
git commit -m "feat(auth): add accounts and manager authority"
```

---

### Task 3: Make catalogue routing authoritative for every intake path

**Files:**
- Create: `backend/apps/tickets/routing.py`
- Modify: `backend/apps/tickets/services.py`
- Modify: `backend/apps/tickets/api.py`
- Modify: `backend/apps/tickets/views.py`
- Modify: `backend/apps/email_channel/services.py`
- Modify: `backend/apps/whatsapp/services.py`
- Modify: `backend/apps/integrations/monitoring.py`
- Create: `backend/apps/tickets/tests/test_routing.py`
- Modify: `backend/apps/tickets/tests/test_services.py`
- Modify: `backend/apps/tickets/tests/test_api_collections.py`
- Modify: `backend/apps/email_channel/tests/test_services.py`
- Modify: `backend/apps/whatsapp/tests/test_services.py`
- Modify: `backend/apps/integrations/tests/test_validate_matter.py`

**Interfaces:**
- Produces: immutable `CatalogueRoute(domain, service, request_type, confidentiality)`.
- Produces: `resolve_catalogue_route(*, service_code, request_type_code, allowed_domains=None) -> CatalogueRoute`.
- Produces: `validate_catalogue_route(*, service, request_type, requested_domain=None) -> CatalogueRoute`.
- Produces: `record_routing_exception(*, source, source_account, reason_code, metadata) -> IntakeRoutingException`.
- Updates: `create_ticket` derives domain and default confidentiality from the route while accepting a matching legacy `domain` argument during compatibility.

- [ ] **Step 1: Write failing route tests**

Create exact behaviour tests:

```python
@pytest.fixture
def accounts_catalogue(basic_world):
    service = Service.objects.create(
        code="ACC-PAY",
        name="Payment enquiries",
        domain="accounts",
    )
    request_type = RequestType.objects.create(
        service=service,
        code="PAY-STATUS",
        name="Payment status",
        default_priority="P3",
        requires_financial_verification=True,
    )
    Status.objects.create(
        domain="accounts",
        code="new",
        name="New",
        public_label="Received",
        is_initial=True,
        order=10,
    )
    return {"service": service, "request_type": request_type}


def test_accounts_route_defaults_sensitive(accounts_catalogue):
    route = resolve_catalogue_route(
        service_code="ACC-PAY",
        request_type_code="PAY-STATUS",
    )
    assert route.domain == "accounts"
    assert route.confidentiality == "sensitive"


def test_request_type_cannot_be_mixed_with_another_service(accounts_catalogue, basic_world):
    with pytest.raises(RouteValidationError) as exc_info:
        resolve_catalogue_route(
            service_code="ACC-PAY",
            request_type_code="HOURS",
        )
    assert exc_info.value.fields == {
        "request_type_code": ["Select a request type for the selected service."]
    }


def test_create_ticket_rejects_caller_supplied_domain_mismatch(accounts_catalogue, basic_world):
    with pytest.raises(RouteValidationError):
        create_ticket(
            domain="operational",
            service=accounts_catalogue["service"],
            request_type=accounts_catalogue["request_type"],
            title="Payment status enquiry",
            description="Please confirm the payment status.",
            requester=basic_world["contact"],
            office=basic_world["office"],
            channel="web",
            financial_enquiry_category="payment",
        )
```

Add public-intake API tests proving an Accounts catalogue pair creates an Accounts/Sensitive ticket, an IT pair is rejected from the public endpoint, and a cross-service Request Type returns the common `invalid_route` error without creating a ticket.

Add email and WhatsApp tests proving a configured Accounts channel creates an Accounts ticket and an unmapped channel records one routing exception without an Operational fallback. Add monitoring tests proving `(provider="monitoring", source=<alert source>)` selects its configured IT route and an unknown source records an exception without selecting the first IT Service.

- [ ] **Step 2: Run route tests and verify the Operational hard-code/fallback failures**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_routing.py apps/tickets/tests/test_api_collections.py apps/email_channel/tests/test_services.py apps/whatsapp/tests/test_services.py apps/integrations/tests/test_validate_matter.py -q
```

Expected: FAIL because public intake forces Operational and email intake guesses a Service or falls back to Operational.

- [ ] **Step 3: Implement the route module**

Create `routing.py`:

```python
from dataclasses import dataclass
from typing import Any

from apps.catalogue.models import RequestType, Service

from .models import IntakeRoutingException, Ticket


class RouteValidationError(Exception):
    def __init__(self, fields: dict[str, list[str]]):
        self.fields = fields


@dataclass(frozen=True)
class CatalogueRoute:
    domain: str
    service: Service
    request_type: RequestType
    confidentiality: str


def validate_catalogue_route(
    *,
    service: Service,
    request_type: RequestType,
    requested_domain: str | None = None,
) -> CatalogueRoute:
    if not service.is_active:
        raise RouteValidationError({"service_code": ["Select an active service."]})
    if request_type.service_id != service.id or not request_type.is_active:
        raise RouteValidationError({
            "request_type_code": ["Select a request type for the selected service."]
        })
    if requested_domain is not None and requested_domain != service.domain:
        raise RouteValidationError({"domain": ["Domain is derived from the selected service."]})
    confidentiality = (
        Ticket.Confidentiality.SENSITIVE
        if service.domain == Ticket.Domain.ACCOUNTS
        else Ticket.Confidentiality.NORMAL
    )
    return CatalogueRoute(service.domain, service, request_type, confidentiality)
```

`resolve_catalogue_route` fetches an active Service and Request Type, applies an optional allowed-domain set, and returns the same validation errors without leaking object existence. `record_routing_exception` copies only allowlisted metadata keys `service_code`, `request_type_code`, `office_code`, `mailbox`, and `integration_id`.

- [ ] **Step 4: Consume validated routes in ticket creation and public intake**

Change `create_ticket` to call `validate_catalogue_route` before number/status lookup and use `route.domain`. Add optional Accounts values with these exact types:

```python
financial_enquiry_category: str = ""
financial_reference: str = ""
external_finance_reference: str = ""
enquiry_amount: Decimal | None = None
enquiry_currency: str = ""
financial_verification_status: str = Ticket.FinancialVerificationStatus.NOT_REQUIRED
```

If the route is Accounts, require a valid enquiry category, uppercase the ISO currency, require currency when amount is supplied, and apply Sensitive unless the caller explicitly supplies Restricted. Reject Normal for Accounts creation.

In `PublicIntakeSerializer`, add optional financial fields and validation bounds. In `public_intake`, replace the `domain="operational"` query with `resolve_catalogue_route(..., allowed_domains={"operational", "accounts"})`, pass the resolved objects to `create_ticket`, and fetch the SLA policy using `ticket.domain`.

Map `RouteValidationError` to the existing common envelope with `code="invalid_route"`, HTTP 400, and exact field errors.

- [ ] **Step 5: Remove guessed email routing**

For a new inbound email, require `mailbox.service_id` and `mailbox.request_type_id`. If either is missing or invalid:

```python
record_routing_exception(
    source="email",
    source_account=mailbox.address,
    reason_code="route_unconfigured",
    metadata={"mailbox": mailbox.address},
)
return {"status": "routing_required", "detail": "mailbox route is not configured"}
```

When configured, call `validate_catalogue_route` and then `create_ticket`. Do not scan all services, prefer special codes, or fall back to Operational.

Extend `process_inbound_email` with optional `service_override` and `request_type_override` used only by already-authenticated channel adapters. `process_inbound_whatsapp` passes its account's configured route through those arguments. If the WhatsApp account is unmapped, record a metadata-only exception containing its phone-number ID/integration ID and return `routing_required`; do not call the email fallback path.

In `integrations/monitoring.py`, resolve the first alert's source through the active `IntegrationRoute(provider="monitoring", source=...)`. Validate the configured route and Office, and create the IT ticket from that mapping. An unconfigured source records a routing exception with the external integration ID and returns a controlled `routing_required` result. Remove `Service.objects.filter(domain="it").first()` and every first-Service fallback.

- [ ] **Step 6: Run routing regressions and commit**

Run:

```powershell
Set-Location backend
pytest apps/tickets/tests/test_routing.py apps/tickets/tests/test_services.py apps/tickets/tests/test_api_collections.py apps/email_channel/tests/test_services.py apps/email_channel/tests/test_webhook_security.py apps/whatsapp/tests apps/integrations/tests -q
ruff check apps/tickets/routing.py apps/tickets/services.py apps/tickets/api.py apps/tickets/views.py apps/email_channel/services.py apps/whatsapp/services.py apps/integrations/monitoring.py
```

Expected: all commands exit 0 and no test observes an Operational fallback for an unresolved route.

Commit:

```powershell
git add backend/apps/tickets/routing.py backend/apps/tickets/services.py backend/apps/tickets/api.py backend/apps/tickets/views.py backend/apps/email_channel/services.py backend/apps/whatsapp/services.py backend/apps/integrations/monitoring.py backend/apps/tickets/tests/test_routing.py backend/apps/tickets/tests/test_services.py backend/apps/tickets/tests/test_api_collections.py backend/apps/email_channel/tests/test_services.py backend/apps/whatsapp/tests/test_services.py backend/apps/integrations/tests/test_validate_matter.py
git diff --cached --check
git commit -m "feat(routing): derive ticket domain from catalogue"
```

---

### Task 4: Seed Accounts roles, catalogue, mailbox route, and SLA baseline

**Files:**
- Modify: `backend/scripts/seed_dev.py`
- Modify: `backend/apps/sla/seed_sla.py`
- Modify: `backend/conftest.py`
- Modify: `scripts/seed_keycloak_user.py`
- Create: `backend/apps/health/tests/test_accounts_foundation.py`

**Interfaces:**
- Produces: idempotent Accounts Services/Request Types and Role rows.
- Produces: Accounts SLA policies using the existing Operational enquiry targets as the initial baseline.
- Produces: developer user seeding accepts `accounts-agents`, `accounts-supervisors`, and `service-desk-managers` group paths.

- [ ] **Step 1: Write the failing seed idempotency test**

Add `test_accounts_foundation.py`:

```python
from apps.catalogue.models import RequestType, Service
from apps.identity_access.models import Role
from apps.sla.models import SlaPolicy
from apps.tickets.seed_workflow import seed_workflow


def test_accounts_foundation_seed_is_idempotent(db):
    from scripts.seed_dev import main

    main()
    main()

    assert Service.objects.filter(domain="accounts", code="ACC-PAY").count() == 1
    assert RequestType.objects.filter(service__code="ACC-PAY", code="PAY-STATUS").count() == 1
    assert Role.objects.filter(keycloak_role="service-desk-manager").count() == 1
    assert SlaPolicy.objects.filter(domain="accounts", priority="P3", is_active=True).count() == 1
```

Add assertions for `ACC-INV/INVOICE-STATUS`, `ACC-REF/REFUND-STATUS`, `ACC-FEE/FEE-QUERY`, and `ACC-RCP/RECEIPT-COPY`. Refund request types set `requires_supervisor_review=True`; other initial enquiry types set it to False.

- [ ] **Step 2: Run the foundation test and verify seed omissions**

Run `pytest apps/health/tests/test_accounts_foundation.py -q` from `backend`.

Expected: FAIL because Accounts seed data and policies are absent.

- [ ] **Step 3: Add deterministic Accounts seed data**

Extend `ensure_request_type` with `requires_supervisor_review: bool = False` and `requires_financial_verification: bool = False`, and use `update_or_create` defaults so configuration corrections are idempotent. Add the five Services/Request Types named in Step 1. Payment, refund, and receipt status types require financial verification; refund also requires supervisor review. Create roles:

```python
ensure_role("agent-accounts", "Accounts agent")
ensure_role("supervisor-accounts", "Accounts supervisor")
ensure_role("service-desk-manager", "Service desk manager")
```

Ensure `admin` has `scopes=[]`; never seed an admin business scope.

Extend the root `basic_world` fixture with an Accounts Service and Request Type under keys `accounts_service` and `accounts_request_type`, without changing existing keys.

- [ ] **Step 4: Add Accounts SLA policies**

In `seed_sla.py`, use the same target tuple as Operational for the initial Accounts enquiry baseline and create names `Accounts P1` through `Accounts P4`. This is a configurable starting point, not a finance-transaction SLA. Keep the shared Eswatini business calendar.

Add a comment stating that production intake must remain disabled until service owners confirm these targets; the values still allow deterministic tests and SLA clocks.

- [ ] **Step 5: Extend Keycloak user seeding validation**

Update `scripts/seed_keycloak_user.py` with an explicit `ALLOWED_GROUPS` set containing all seven existing groups plus `accounts-agents`, `accounts-supervisors`, and `service-desk-managers`. Make `--group` required with `choices=sorted(ALLOWED_GROUPS)`. Remove the checked-in default user password and default Keycloak administrator password: accept them only from `--password`/`KEYCLOAK_SEED_USER_PASSWORD` and `--admin-password`/`KEYCLOAK_ADMIN_PASSWORD`, fail before any HTTP request when either is blank, and never print either value. Resolve the group before creating or mutating the user so an invalid or missing group causes zero external changes.

- [ ] **Step 6: Verify the complete foundation and commit**

Run:

```powershell
Set-Location backend
pytest apps/health/tests/test_accounts_foundation.py apps/identity_access/tests apps/catalogue/tests apps/sla/tests apps/email_channel/tests -q
python manage.py makemigrations --check --dry-run
ruff check apps scripts
```

Expected: all commands exit 0.

Commit:

```powershell
git add backend/scripts/seed_dev.py backend/apps/sla/seed_sla.py backend/conftest.py scripts/seed_keycloak_user.py backend/apps/health/tests/test_accounts_foundation.py
git diff --cached --check
git commit -m "feat(accounts): seed enquiry catalogue and roles"
```

---

## Plan 1 Completion Gate

Run from the repository root:

```powershell
docker compose exec backend python manage.py makemigrations --check --dry-run
docker compose exec backend pytest apps/identity_access apps/catalogue apps/email_channel apps/tickets/tests/test_accounts_models.py apps/tickets/tests/test_routing.py apps/tickets/tests/test_role_matrix_accounts.py -q
docker compose exec backend ruff check apps
```

Expected: all commands exit 0; an Accounts/Sensitive ticket can be created only from a valid Accounts catalogue pair; manager and Accounts claims are recognised; technical administrators have no business-ticket scope; and no unresolved trusted intake falls back to Operational.
