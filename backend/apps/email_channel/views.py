"""Email channel HTTP endpoints."""
from __future__ import annotations

import logging
import uuid

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from .services import process_inbound_email
from .models import EmailDelivery

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([AllowAny])
def inbound_email(request):
    """Provider-agnostic inbound email webhook.

    Real providers (Graph, Mailgun, etc.) translate their native format into
    this payload and POST it here. Idempotency and threading live in
    ``process_inbound_email``.
    """
    body = request.data or {}
    required = ("from", "to", "subject", "body_text", "message_id")
    missing = [k for k in required if not body.get(k)]
    if missing:
        return Response(
            {"status": "error", "detail": f"missing fields: {', '.join(missing)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    outcome = process_inbound_email(
        from_header=body["from"],
        to_header=body["to"],
        subject=body["subject"],
        body_text=body["body_text"],
        body_html=body.get("body_html", ""),
        message_id=body["message_id"],
        in_reply_to=body.get("in_reply_to", ""),
        references=body.get("references", ""),
    )
    if outcome.get("status") == "error":
        return Response(outcome, status=status.HTTP_400_BAD_REQUEST)
    return Response(outcome, status=status.HTTP_201_CREATED if outcome.get("status") == "created" else 200)


@api_view(["POST"])
@permission_classes([AllowAny])
def outbound_bounce(request):
    """Provider webhook for delivery failures (PRD §19.4)."""
    body = request.data or {}
    message_id = body.get("message_id", "")
    delivery = EmailDelivery.objects.filter(message_id=message_id).first()
    if not delivery:
        return Response({"status": "unknown_message_id"}, status=status.HTTP_404_NOT_FOUND)
    delivery.status = "bounced" if body.get("type") == "bounce" else "failed"
    delivery.error = body.get("error", "")[:2000]
    delivery.save(update_fields=["status", "error"])
    return Response({"status": "recorded"})
