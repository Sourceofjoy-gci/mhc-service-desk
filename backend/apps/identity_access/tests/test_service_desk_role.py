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
    """Neither spelling may reassign tickets: reassignment is a supervisory power."""
    from apps.tickets.permissions import REASSIGN_GROUPS

    assert "service-desk-agents" not in REASSIGN_GROUPS
    assert "agent-servicedesk" not in REASSIGN_GROUPS


def test_service_desk_cannot_view_restricted_scopes():
    """Cross-office reach (added later) must never combine with restricted-ticket
    visibility, so neither spelling may appear among the scope roles that are
    granted `can_view_restricted_rows=True`."""
    from apps.identity_access.scope import _RESTRICTED_VIEW_ROLES

    assert "service-desk-agents" not in _RESTRICTED_VIEW_ROLES
    assert "agent-servicedesk" not in _RESTRICTED_VIEW_ROLES


def test_service_desk_is_not_a_restricted_ticket_role():
    """Restricted tickets (security, fraud, complaint, privacy) must stay invisible
    to the service desk, so neither spelling may appear in the ticket-eligibility
    restricted role set."""
    from apps.tickets.eligibility import _RESTRICTED_ROLE_KEYS

    assert "service-desk-agents" not in _RESTRICTED_ROLE_KEYS
    assert "agent-servicedesk" not in _RESTRICTED_ROLE_KEYS


def test_service_desk_group_is_accepted_by_the_authenticator():
    from apps.identity_access.authentication import _KEYCLOAK_GROUPS, _KEYCLOAK_REALM_ROLES

    assert "service-desk-agents" in _KEYCLOAK_GROUPS
    assert "agent-servicedesk" in _KEYCLOAK_REALM_ROLES
