"""WhatsApp channel HTTP endpoints."""
from __future__ import annotations

import logging

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from .services import get_provider, process_inbound_whatsapp

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([AllowAny])
def inbound_webhook(request):
    """Inbound WhatsApp webhook (Meta Cloud API webhook format)."""
    body = request.data or {}
    entry = body.get("entry", [{}])[0]
    change = entry.get("changes", [{}])[0]
    value = change.get("value", {})
    messages = value.get("messages", [])
    if not messages:
        return Response({"status": "no_messages"})
    msg = messages[0]
    from_number = msg.get("from", "")
    to_number = value.get("metadata", {}).get("display_phone_number", "")
    text = (msg.get("text") or {}).get("body", "")
    external_id = msg.get("id", "")
    r = process_inbound_whatsapp(
        from_number=from_number,
        to_number=to_number,
        body=text,
        external_message_id=external_id,
        raw=body,
    )
    return Response(r, status=status.HTTP_201_CREATED if r.get("status") == "created" else 200)


@api_view(["GET"])
@permission_classes([AllowAny])
def list_templates(request):
    """Return the templates known to the configured provider."""
    provider = get_provider()
    return Response({"templates": provider.fetch_templates()})


@api_view(["POST"])
@permission_classes([AllowAny])
def send_text(request):
    """Outbound text — used by agent replies (subject to template rules)."""
    data = request.data or {}
    to = data.get("to", "")
    body = data.get("body", "")
    if not (to and body):
        return Response({"detail": "to and body are required"}, status=status.HTTP_400_BAD_REQUEST)
    provider = get_provider()
    result = provider.send_text(to=to, body=body)
    return Response(result)
