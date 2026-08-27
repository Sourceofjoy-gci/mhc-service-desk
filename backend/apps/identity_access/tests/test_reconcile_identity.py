"""Relinking a local user to a rebuilt Keycloak realm.

Wiping Keycloak's database (``scripts/kcclean.py``) re-imports the realm and
mints fresh user ids, while the local mirror keeps the subjects it learned
from the previous instance. Authentication deliberately refuses to re-link on
its own — a new realm user who happens to pick an existing username must not
inherit that account — so recovery needs an explicit operator action.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework import exceptions

from apps.audit.models import AuditEvent
from apps.identity_access.authentication import _resolve_local_user
from apps.identity_access.models import User

STALE_SUBJECT = "8bbf1550-b129-43f1-9ff1-7284110b4916"
CURRENT_SUBJECT = "93ba5b5a-4a1b-403a-82fe-77d152a41240"


@pytest.fixture
def stranded_user(db) -> User:
    return User.objects.create(
        username="njabulo",
        keycloak_subject=STALE_SUBJECT,
        keycloak_groups=["system-admins"],
    )


@pytest.mark.django_db
def test_stale_subject_blocks_authentication_until_reconciled(stranded_user):
    with pytest.raises(exceptions.AuthenticationFailed):
        _resolve_local_user(
            keycloak_subject=CURRENT_SUBJECT,
            preferred_username="njabulo",
            email="",
            mfa_enabled=False,
        )

    call_command("reconcile_identity", username="njabulo", subject=CURRENT_SUBJECT)

    resolved = _resolve_local_user(
        keycloak_subject=CURRENT_SUBJECT,
        preferred_username="njabulo",
        email="",
        mfa_enabled=False,
    )
    assert resolved.pk == stranded_user.pk
    assert resolved.keycloak_groups == ["system-admins"]


@pytest.mark.django_db
def test_reconciliation_is_recorded_in_the_audit_trail(stranded_user):
    call_command(
        "reconcile_identity",
        username="njabulo",
        subject=CURRENT_SUBJECT,
        operator="ops@mhc",
    )

    event = AuditEvent.objects.get(action="identity.subject_reconciled")
    assert event.actor_subject == "ops@mhc"
    assert event.object_id == str(stranded_user.id)
    assert event.payload["before"]["keycloak_subject"] == STALE_SUBJECT
    assert event.payload["after"]["keycloak_subject"] == CURRENT_SUBJECT
    assert event.payload_hash


@pytest.mark.django_db
def test_repeating_the_reconciliation_changes_nothing(stranded_user):
    call_command("reconcile_identity", username="njabulo", subject=CURRENT_SUBJECT)
    call_command("reconcile_identity", username="njabulo", subject=CURRENT_SUBJECT)

    stranded_user.refresh_from_db()
    assert stranded_user.keycloak_subject == CURRENT_SUBJECT
    assert AuditEvent.objects.filter(action="identity.subject_reconciled").count() == 1


@pytest.mark.django_db
def test_a_subject_held_by_another_account_is_refused(stranded_user):
    other = User.objects.create(username="someone-else", keycloak_subject=CURRENT_SUBJECT)

    with pytest.raises(CommandError, match="someone-else"):
        call_command("reconcile_identity", username="njabulo", subject=CURRENT_SUBJECT)

    stranded_user.refresh_from_db()
    other.refresh_from_db()
    assert stranded_user.keycloak_subject == STALE_SUBJECT
    assert other.keycloak_subject == CURRENT_SUBJECT


@pytest.mark.django_db
def test_an_unknown_username_is_refused(stranded_user):
    with pytest.raises(CommandError, match="nobody"):
        call_command("reconcile_identity", username="nobody", subject=CURRENT_SUBJECT)


@pytest.mark.django_db
def test_a_blank_subject_is_refused(stranded_user):
    with pytest.raises(CommandError):
        call_command("reconcile_identity", username="njabulo", subject="   ")

    stranded_user.refresh_from_db()
    assert stranded_user.keycloak_subject == STALE_SUBJECT
