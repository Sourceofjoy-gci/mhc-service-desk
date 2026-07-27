from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group
from django.test import override_settings
from rest_framework.test import APIRequestFactory

from apps.audit.models import AuditEvent
from apps.identity_access.authentication import KeycloakJWTAuthentication
from apps.identity_access.models import User
from apps.tickets import services

pytestmark = pytest.mark.django_db


def test_lifecycle_fields_are_backwards_compatible(basic_world):
    ticket = services.create_ticket(
        domain="operational",
        title="Lifecycle defaults",
        description="",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(code="HOURS"),
        office=basic_world["office"],
        channel="web",
    )

    ticket.refresh_from_db()

    assert ticket.next_action == ""
    assert ticket.next_action_at is None


def test_audit_payload_defaults_to_empty_dict():
    event = AuditEvent.objects.create(
        actor_subject="agent-1",
        action="ticket.tested",
        object_type="ticket",
        object_id="ticket-1",
        payload_hash="0" * 64,
    )

    event.refresh_from_db()

    assert event.payload == {}


def test_verified_token_groups_are_persisted_for_new_and_existing_users():
    request = APIRequestFactory().get(
        "/api/v1/tickets/",
        HTTP_AUTHORIZATION="Bearer signed-token",
    )
    payloads = [
        {
            "sub": "subject-1",
            "preferred_username": "pilot",
            "email": "pilot@example.test",
            "groups": ["ops-agents"],
        },
        {
            "sub": "subject-1",
            "preferred_username": "pilot",
            "email": "pilot@example.test",
            "groups": ["ops-supervisors"],
        },
    ]
    authenticator = KeycloakJWTAuthentication()

    with (
        patch("apps.identity_access.authentication.AccessToken"),
        patch(
            "apps.identity_access.authentication._decode_unverified_header",
            return_value={"kid": "key-1"},
        ),
        patch(
            "apps.identity_access.authentication._get_jwks",
            return_value={"keys": [{"kid": "key-1"}]},
        ),
        patch(
            "apps.identity_access.authentication._build_public_key",
            return_value=object(),
        ),
        patch(
            "apps.identity_access.authentication._verify_jwt",
            side_effect=payloads,
        ),
    ):
        new_user, _ = authenticator.authenticate(request)
        new_user.refresh_from_db()
        assert new_user.keycloak_groups == ["ops-agents"]
        assert new_user._groups == ["ops-agents"]

        existing_user, _ = authenticator.authenticate(request)
        existing_user.refresh_from_db()
        assert existing_user.pk == new_user.pk
        assert existing_user.keycloak_groups == ["ops-supervisors"]
        assert existing_user._groups == ["ops-supervisors"]


def test_debug_token_groups_are_persisted_on_every_authentication():
    authenticator = KeycloakJWTAuthentication()
    factory = APIRequestFactory()

    with override_settings(DEBUG=True):
        new_user, _ = authenticator.authenticate(
            factory.get(
                "/api/v1/tickets/",
                HTTP_AUTHORIZATION="Bearer dev:pilot:ops-agents",
            )
        )
        new_user.refresh_from_db()
        assert new_user.keycloak_groups == ["ops-agents"]
        assert new_user._groups == ["ops-agents"]

        existing_user, _ = authenticator.authenticate(
            factory.get(
                "/api/v1/tickets/",
                HTTP_AUTHORIZATION="Bearer dev:pilot:ops-supervisors",
            )
        )
        existing_user.refresh_from_db()
        assert existing_user.pk == new_user.pk
        assert existing_user.keycloak_groups == ["ops-supervisors"]
        assert existing_user._groups == ["ops-supervisors"]

    assert User.objects.filter(username="pilot").count() == 1


def test_keycloak_snapshot_preserves_django_auth_groups():
    user = User.objects.create(
        username="django-group-user",
        keycloak_subject="django-group-subject",
    )
    django_group = Group.objects.create(name="application-administrators")

    user.groups.add(django_group)

    assert list(user.groups.values_list("name", flat=True)) == [
        "application-administrators"
    ]
