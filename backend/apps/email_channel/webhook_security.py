"""Authentication contract for normalized internal email-adapter webhooks.

The adapter sends three headers:

* ``X-MHC-Webhook-Timestamp``: Unix seconds.
* ``X-MHC-Webhook-Event-Id``: a stable, provider-event identifier.
* ``X-MHC-Webhook-Signature``: ``sha256=<hex>`` where the digest is HMAC-SHA256
  over ``<timestamp>.<event-id>.`` followed by the exact request-body bytes.

The shared secret comes from ``EMAIL_WEBHOOK_SECRET``. Events outside
``CHANNEL_WEBHOOK_MAX_AGE_SECONDS`` (300 seconds by default) are rejected.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass

from rest_framework.request import Request


@dataclass(frozen=True)
class WebhookAuthentication:
    authenticated: bool
    configured: bool
    event_id: str = ""


def _max_age_seconds() -> int | None:
    try:
        value = int(os.environ.get("CHANNEL_WEBHOOK_MAX_AGE_SECONDS", "300"))
    except ValueError:
        return None
    return value if value > 0 else None


def authenticate_email_adapter(
    request: Request,
    raw_body: bytes,
) -> WebhookAuthentication:
    """Authenticate exact bytes before a caller parses or mutates anything."""
    secret = os.environ.get("EMAIL_WEBHOOK_SECRET", "")
    max_age = _max_age_seconds()
    if not secret or max_age is None:
        return WebhookAuthentication(authenticated=False, configured=False)

    timestamp_header = request.META.get("HTTP_X_MHC_WEBHOOK_TIMESTAMP", "")
    event_id = request.META.get("HTTP_X_MHC_WEBHOOK_EVENT_ID", "")
    supplied = request.META.get("HTTP_X_MHC_WEBHOOK_SIGNATURE", "")
    if not event_id or len(event_id) > 255 or not supplied.startswith("sha256="):
        return WebhookAuthentication(authenticated=False, configured=True)
    try:
        timestamp = int(timestamp_header)
    except (TypeError, ValueError):
        return WebhookAuthentication(authenticated=False, configured=True)
    if abs(int(time.time()) - timestamp) > max_age:
        return WebhookAuthentication(authenticated=False, configured=True)

    canonical = f"{timestamp}.{event_id}.".encode() + raw_body
    expected = (
        "sha256="
        + hmac.new(
            secret.encode(),
            canonical,
            hashlib.sha256,
        ).hexdigest()
    )
    return WebhookAuthentication(
        authenticated=hmac.compare_digest(expected, supplied),
        configured=True,
        event_id=event_id,
    )
