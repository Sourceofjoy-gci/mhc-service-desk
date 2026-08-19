# Officer Office Assignment Design

## Goal

Every officer is based at a regional office. Assistant Masters lead the office they
are based in. The system must record which office an officer belongs to at the point
the officer is created, and must confine that officer's operational and IT work to
that office.

A national service desk answers incoming queries before the responsible office is
known, so it must remain exempt from that confinement.

## Scope

This change covers:

- an `office` and `station` attribute carried from Keycloak into the access token;
- persistence of both on the local `User` mirror at authentication time;
- confinement of an officer's operational and IT authority to their office;
- a new cross-office `service-desk-agents` role; and
- the test-fixture migration the confinement requires.

The following are outside this change:

- an administrative user-management API or screen (PRD FR-089) — user creation
  remains Keycloak-driven;
- editing an officer's office from inside this application;
- confinement by station, service or queue;
- a stored lead officer per office; and
- office-aware routing, SLA calendars or reporting filters.

## Terminology

| Term | Model | Ticket field |
|---|---|---|
| Office | `organisations.Office` | `Ticket.office` (required) |
| Station | `organisations.ServiceLocation` | `Ticket.queue` (nullable) |

## Current State

`organisations.Region`, `Office` and `ServiceLocation` exist with migrations.
`identity_access.UserRole` already carries an optional `office` foreign key, and
`_validated_role_scopes` in `apps/identity_access/scope.py` already narrows a
role's scopes to it. Nothing writes that field, so no user is office-bound today.

There is no user-creation feature. Users appear through Keycloak just-in-time
provisioning in `KeycloakJWTAuthentication.authenticate`, through the Django admin,
or through `scripts/seed_keycloak_user.py`. The `organisations/offices` endpoint is
a stub returning an empty list.

`assistant-master` is a defined designation in `apps/identity_access/staff_roles.py`
and a realm role in `infrastructure/keycloak/realm-mhc.json`. Neither encodes a
location.

## Approaches Considered

### Confine inside `_build_authority_snapshot`

Resolve scopes as today, from persisted role assignments or the group fallback, then
intersect the result with the officer's office before returning the snapshot.

Every authorisation consumer in the codebase — `has_scope`, `ScopePermission`,
`scope_ticket_queryset`, `has_unrestricted_domain_scope`, `can_view_restricted`, and
their callers in `files`, `integrations`, `reporting` and `tickets` — reaches
authority through `get_authority_snapshot`. One choke point covers all of them.

This is the selected approach.

### Confine in `scope_ticket_queryset`

Filtering the ticket queryset alone is a smaller change, but it confines listing
only. `has_scope` and `has_unrestricted_domain_scope` would stay office-blind, so an
officer could still act on an out-of-office ticket addressed directly by identifier,
and reporting aggregates would count tickets across offices.

Rejected: it leaves reachable paths unconfined.

### Confine in `_snapshot_from_groups`

Applying the office where group-fallback scopes are built works while nothing writes
`UserRole` rows, and stops working silently the moment something does, because the
persisted path does not pass through it.

Rejected: correct only by accident of current data.

## Design

### Transport

The office is a Keycloak user attribute, not a group. Groups in this realm carry
authority — what an identity may do. Location is a different axis, and folding it
into `keycloak_groups` would mix it into the data that drives the authority
fallback.

Two `oidc-usermodel-attribute-mapper` protocol mappers are added to
`infrastructure/keycloak/realm-mhc.json`, emitting an `office` claim holding an
`Office.code` and a `station` claim holding a `ServiceLocation.name`.

`ServiceLocation.name` is unique only within an office (`unique_together` on
`("office", "name")`), so the station claim is always resolved **within the office
the `office` claim resolved to**. A station claim without a resolvable office
resolves to `None`.

### Persistence

`identity_access.User` gains two nullable foreign keys:

- `office` to `organisations.Office`, `on_delete=PROTECT`;
- `station` to `organisations.ServiceLocation`, `on_delete=SET_NULL`.

`PROTECT` on `office` prevents deleting an office that still has officers based in
it. `SET_NULL` on `station` is correct because a station is a counter that can be
retired without displacing the officer.

`_synchronize_office(user, payload)` in `apps/identity_access/authentication.py`
mirrors the existing `_synchronize_groups`: it takes the authority lock, compares
the resolved office and station against the stored values, and saves only when they
differ. A claim naming an unknown code, or an office with `is_active=False`,
resolves to `None`.

Keycloak is the single writer. `office` and `station` are read-only in the Django
admin, because a local edit would be overwritten on the officer's next request.

`lock_user_authorities` in `apps/identity_access/authority_lock.py` adds
`select_related("office")` to its user query so the boundary check can read
`office.is_active` without an extra query per user. The existing `of=("self",)`
keeps the row lock on the user table only.

### Confinement

`AuthoritySnapshot` gains one field:

```python
cross_office_identity: bool = False
```

It is computed on both resolution paths, exactly as `auditor_identity` already is,
so the exemption cannot hold under the group fallback and then silently fail once
`UserRole` rows exist. It is true for a service desk role or an auditor identity.

An `admin`-domain scope is deliberately **not** part of this flag. Exempting the
whole identity would also exempt any operational scope the same person holds, which
is wider than intended. Admin authority is instead protected per-scope in the table
below, so a system administrator who is also an operational agent is confined as an
agent and unconfined as an administrator.

`_apply_office_boundary(snapshot, user)` is applied to the resolved snapshot on the
non-superuser return path of `_build_authority_snapshot`. The superuser branch
constructs its own `admin` snapshot and never passes through it.

| Case | Result |
|---|---|
| `cross_office_identity` is true | snapshot returned unchanged |
| Django superuser | never reaches this function; the superuser branch builds its own snapshot |
| Valid active office, scope domain `operational` or `it` | scope rewritten with `office_id` set to the officer's office |
| Scope domain `admin` | unchanged; system administration is never office-bound |
| Scope already bound to a different office | dropped, never widened |
| Office absent, unknown, or inactive | all `operational` and `it` scopes dropped |

The last row is deny-by-default, per PRD section 14.1. An officer with no valid
office authenticates successfully and sees an empty queue rather than an error, and
retains any `admin` or audit authority they hold.

`restricted_scope_keys` must be rewritten in the same operation. `_scope_key`
includes `office_id`, and `scope_ticket_queryset` tests
`_scope_key(scope) not in authority.restricted_scope_keys` to decide whether to
exclude restricted tickets. Rewriting a scope's office without remapping its key
would silently strip restricted-ticket visibility from every supervisor.

### Station

`station` is persisted and exposed, and never confines. `Scope.queue_id` is left
untouched. `Ticket.queue` is nullable, so confining by station would hide every
ticket with no queue assigned from the officer stationed at that counter.

### Leading officers

An officer holding the `assistant-master` designation and based at an office is that
office's leading officer. This is derived, not stored. Once confinement is active,
the candidates returned by `eligible_escalation_supervisors` are already restricted
to the ticket's office, so a stored lead would be a second source of truth with
nothing to consume it.

### Service desk role

A national service desk takes operational queries before the responsible office is
known, so it is exempt from confinement.

Following the realm's existing pairing convention, the Keycloak group is
`service-desk-agents` and the realm role is `agent-servicedesk`; the two are aliases
of one another. Its scope is `{"domain": "operational"}`. IT remains office-bound
under `it-agents`.

The role is registered in:

| File | Addition |
|---|---|
| `infrastructure/keycloak/realm-mhc.json` | group `service-desk-agents` with `realmRoles: ["staff", "agent-servicedesk"]`; realm role `agent-servicedesk` |
| `apps/identity_access/authentication.py` | `_KEYCLOAK_GROUPS`, `_KEYCLOAK_REALM_ROLES` |
| `apps/identity_access/scope.py` | `_DEFAULT_ROLE_SCOPES` for both keys; a branch in `_snapshot_from_groups` |
| `apps/tickets/eligibility.py` | `_LEGACY_ROLE_DETAILS`, `_ROLE_FAMILY_DOMAIN`, `_ROLE_ALIASES`, `_GROUP_FALLBACK_ROLE_KEYS` |
| `apps/tickets/permissions.py` | `DOMAIN_GROUPS["operational"]` |

The service desk is an agent-level role. It is deliberately absent from
`_RESTRICTED_ROLE_KEYS` and `REASSIGN_GROUPS`, so restricted tickets — security,
fraud, complaint and privacy — stay invisible to it in every office including its
own, and it cannot reassign. Cross-office reach combined with restricted visibility
would be the widest exposure in the system; keeping them apart widens breadth
without widening sensitivity.

### Identity endpoint

`GET /me` returns `office` as an object with `id`, `code` and `name`, and `station`
as an object with `id` and `name`, or `null` for either. `ServiceLocation` has no
`code` field. This lets the frontend show the officer which office they are working
as.

### Development access

The DEBUG-only dev token grows a fourth segment:
`dev:<username>:<groups>:<office-code>`. Three-segment tokens remain valid and
resolve to no office, which under deny-by-default means no operational authority.

## Data Flow

```
Keycloak user attributes   office=MBB  station=Counter-3
        |  attribute protocol mappers
        v
access token claims        office, station
        |
        v
KeycloakJWTAuthentication.authenticate
        |  _synchronize_office(user, payload)
        v
User.office, User.station
        |
        v
_build_authority_snapshot
        |  resolve from persisted roles or group fallback
        |  _apply_office_boundary(snapshot, user)
        v
AuthoritySnapshot with office-bound operational and IT scopes
        |
        v
has_scope | ScopePermission | scope_ticket_queryset | reporting | files
```

## Error Handling

| Condition | Behaviour |
|---|---|
| `office` claim absent | Officer authenticates; operational and IT scopes dropped |
| `office` claim names an unknown code | Treated as absent; stored office set to `None` |
| `office` names an inactive office | Treated as absent |
| `station` claim absent, unknown, or from another office | Station set to `None`; office confinement unaffected |
| Attempt to delete an office with officers based in it | `ProtectedError` from the `PROTECT` constraint |
| Officer's office deactivated while a session is live | Next request drops operational and IT scopes |

No condition raises an authentication failure. A Keycloak configuration slip
degrades an officer to an empty queue; it never causes an outage, and never locks
out system administration.

## Test Plan

### Confinement

- An officer based at office A sees tickets from office A and not from office B.
- Confinement holds identically on the group-fallback and persisted-role paths.
- A scope already bound to office B is dropped, not widened, for an officer at A.
- `admin`-domain scope survives a missing office.
- A user holding both `system-admins` and `ops-agents` is confined on the
  operational scope and unconfined on the `admin` scope.
- An auditor identity is unconfined.
- A Django superuser is unconfined.
- An unknown office code denies operational and IT authority.
- An inactive office denies operational and IT authority.
- A supervisor retains restricted-ticket visibility after confinement, covering the
  `restricted_scope_keys` remap.

### Station

- A station is persisted and returned by `/me`.
- An officer with a station still sees office tickets whose `queue` is null.
- A station belonging to another office resolves to `None`.

### Service desk

- A service desk agent sees operational tickets from every office.
- A service desk agent cannot see restricted tickets in any office, including
  their own.
- A service desk agent cannot reassign.
- The exemption holds on both resolution paths.

### Synchronisation

- A changed `office` claim updates the stored office on the next request.
- An unchanged claim performs no write.
- Office resolution runs under the authority lock.

### Fixtures

`backend/conftest.py` gains a shared `staff_user(...)` factory that assigns an
office by default. The local `_user(groups)` helpers in the 38 test modules that
build users from group memberships are migrated to it. `basic_world` already
creates the `TST-1` office used as the default.

## Rollout

The realm mappers must be deployed and every officer's `office` attribute populated
in Keycloak before the confinement is enabled. Shipping in the other order leaves
every officer with an empty queue.

1. Add the protocol mappers and the `service-desk-agents` group and role to the
   realm; populate `office` on existing Keycloak users.
2. Ship the model, migration and `_synchronize_office`, which records offices
   without confining anything.
3. Verify officers have a stored office.
4. Ship `_apply_office_boundary`.

## Traceability

| Requirement | Source |
|---|---|
| Role plus office, service, queue and confidentiality scope | PRD section 14.1 |
| Deny by default; server-side enforcement on every endpoint | PRD section 14.1 |
| Operational Service Desk as the front door for public queries | PRD section 4 |
| Office and service location on every ticket | PRD section 15 |
