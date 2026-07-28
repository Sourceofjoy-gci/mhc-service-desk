"""Meta webhook signature and delivery-age verification."""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass

from rest_framework.request import Request


@dataclass(frozen=True)
class MetaWebhookAuthentication:
    authenticated: bool
    configured: bool


def authenticate_meta_request(
    request: Request,
    raw_body: bytes,
) -> MetaWebhookAuthentication:
    secret = os.environ.get("WHATSAPP_APP_SECRET", "")
    if not secret:
        return MetaWebhookAuthentication(authenticated=False, configured=False)
    supplied = request.META.get("HTTP_X_HUB_SIGNATURE_256", "")
    expected = "sha256=" + hmac.new(
        secret.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return MetaWebhookAuthentication(
        authenticated=hmac.compare_digest(expected, supplied),
        configured=True,
    )


def is_recent_meta_timestamp(value: object) -> bool:
    if not isinstance(value, str | int):
        return False
    try:
        issued_at = int(value)
        max_age = int(os.environ.get("CHANNEL_WEBHOOK_MAX_AGE_SECONDS", "300"))
    except (TypeError, ValueError):
        return False
    return max_age > 0 and abs(int(time.time()) - issued_at) <= max_age
