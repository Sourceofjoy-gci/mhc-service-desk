from uuid import uuid4

import pytest
from django.http import Http404
from rest_framework.exceptions import NotAuthenticated, PermissionDenied, ValidationError
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.identity_access.exception_handlers import problem_details_handler
from apps.identity_access.models import User
from apps.identity_access.views import me
from apps.organisations.models import ServiceLocation

pytestmark = pytest.mark.django_db


def _request():
    request = APIRequestFactory().post("/tickets/")
    request.correlation_id = "corr-123"
    return request


def test_validation_error_uses_common_contract():
    response = problem_details_handler(
        ValidationError({"title": ["This field is required."]}),
        {"request": _request()},
    )

    assert response.status_code == 400
    assert response.data == {
        "code": "invalid",
        "detail": "Request failed validation",
        "fields": {"title": ["This field is required."]},
        "correlation_id": "corr-123",
    }


def test_permission_denied_uses_common_contract():
    response = problem_details_handler(
        PermissionDenied(),
        {"request": _request()},
    )

    assert response.status_code == 403
    assert response.data == {
        "code": "permission_denied",
        "detail": "You do not have permission to perform this action.",
        "fields": {},
        "correlation_id": "corr-123",
    }


def test_not_authenticated_uses_common_contract():
    response = problem_details_handler(
        NotAuthenticated(),
        {"request": _request()},
    )

    assert response.status_code == 401
    assert response.data == {
        "code": "not_authenticated",
        "detail": "Authentication credentials were not provided.",
        "fields": {},
        "correlation_id": "corr-123",
    }


def test_django_not_found_uses_common_contract():
    response = problem_details_handler(
        Http404("No ticket matches the given query."),
        {"request": _request()},
    )

    assert response.status_code == 404
    assert response.data == {
        "code": "not_found",
        "detail": "No ticket matches the given query.",
        "fields": {},
        "correlation_id": "corr-123",
    }


def test_me_returns_office_and_station(basic_world, client, settings):
    settings.DEBUG = True
    office = basic_world["office"]
    ServiceLocation.objects.create(office=office, name="Counter-9")

    response = client.get(
        "/api/v1/identity/me",
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
        "/api/v1/identity/me",
        HTTP_AUTHORIZATION="Bearer dev:unassignedofficer:ops-agents",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["office"] is None
    assert body["station"] is None


def test_me_returns_a_populated_station(basic_world):
    """Station carries id and name only — ServiceLocation has no code field."""
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
