"""Canonical error responses for the API."""
from __future__ import annotations

from rest_framework.exceptions import ValidationError
from rest_framework.views import exception_handler


def _first_code(codes) -> str:
    if isinstance(codes, dict):
        return _first_code(next(iter(codes.values()), "error"))
    if isinstance(codes, list | tuple):
        return _first_code(codes[0] if codes else "error")
    return str(getattr(codes, "code", codes))


def _messages(value) -> list[str]:
    if isinstance(value, dict):
        return [message for nested in value.values() for message in _messages(nested)]
    if isinstance(value, list | tuple):
        return [message for nested in value for message in _messages(nested)]
    return [str(value)]


def problem_details_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return response

    if isinstance(exc, ValidationError):
        detail = "Request failed validation"
        if isinstance(response.data, dict):
            fields = {name: _messages(value) for name, value in response.data.items()}
        else:
            fields = {"non_field_errors": _messages(response.data)}
    else:
        raw_detail = (
            response.data.get("detail", response.data)
            if isinstance(response.data, dict)
            else response.data
        )
        detail = " ".join(_messages(raw_detail))
        fields = {}

    codes = exc.get_codes() if hasattr(exc, "get_codes") else response.data
    response.data = {
        "code": _first_code(codes),
        "detail": detail,
        "fields": fields,
        "correlation_id": getattr(context.get("request"), "correlation_id", ""),
    }
    return response
