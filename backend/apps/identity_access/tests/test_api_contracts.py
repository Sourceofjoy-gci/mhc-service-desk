from django.http import Http404
from rest_framework.exceptions import NotAuthenticated, PermissionDenied, ValidationError
from rest_framework.test import APIRequestFactory

from apps.identity_access.exception_handlers import problem_details_handler


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
