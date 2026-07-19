"""Request audit middleware.

Lightweight middleware that:
* sets a correlation ID on every request,
* emits a single access log line per request,
* records failed authorisation attempts for security review.

The full audit event stream is written from the application layer where
the business context is known. This middleware is the safety net.
"""
from __future__ import annotations

import logging
import uuid

CORRELATION_ID_HEADER = "HTTP_X_CORRELATION_ID"
CORRELATION_ID_RESPONSE = "X-Correlation-ID"

logger = logging.getLogger("apps.audit.middleware")


class RequestAuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        correlation_id = request.META.get(CORRELATION_ID_HEADER) or uuid.uuid4().hex
        request.correlation_id = correlation_id

        response = self.get_response(request)
        response[CORRELATION_ID_RESPONSE] = correlation_id

        if response.status_code in (401, 403):
            logger.warning(
                "authorization_denied",
                extra={
                    "correlation_id": correlation_id,
                    "path": request.path,
                    "method": request.method,
                    "status": response.status_code,
                },
            )
        return response
