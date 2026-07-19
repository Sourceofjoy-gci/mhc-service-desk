"""RFC 7807 problem-details error responses for the API.

DRF's default error format is inconsistent across clients. We override it
to return a stable, well-documented shape that the frontend can switch on.
"""
from __future__ import annotations

from rest_framework.views import exception_handler


def problem_details_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return response
    detail = response.data
    if isinstance(detail, dict) and "detail" in detail and len(detail) == 1:
        message = str(detail["detail"])
        errors = None
    else:
        message = "Request failed validation"
        errors = detail

    response.data = {
        "type": f"about:blank#{getattr(exc, 'default_code', 'error')}",
        "title": getattr(exc, "default_detail", "Error"),
        "status": response.status_code,
        "detail": message,
        "errors": errors,
    }
    return response
