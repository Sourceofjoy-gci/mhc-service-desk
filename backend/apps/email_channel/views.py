"""Email channel HTTP endpoints."""
from __future__ import annotations

import json
import logging
import uuid

from django.db import IntegrityError, transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import status

from apps.tickets.events import record_ticket_event

from .services import process_inbound_email
from .models import EmailDelivery, EmailWebhookEvent
from .webhook_security import authenticate_email_adapter

logger = logging.getLogger(__name__)


def _verified_payload(
    request: Request,
) -> tuple[dict[str, object] | None, str, Response | None]:
    raw_body = request.body
    authentication = authenticate_email_adapter(request, raw_body)
    if not authentication.configured:
        return None, "", Response(
            {"status": "unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if not authentication.authenticated:
        return None, "", Response(
            {"status": "unauthorized"},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    try:
        parsed: object = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "", Response(
            {"status": "invalid_payload"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not isinstance(parsed, dict):
        return None, "", Response(
            {"status": "invalid_payload"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return parsed, authentication.event_id, None


def _claim_event(*, event_id: str, event_type: str, message_id: str) -> bool:
    try:
        with transaction.atomic():
            EmailWebhookEvent.objects.create(
                event_id=event_id,
                event_type=event_type,
                message_id=message_id,
            )
    except IntegrityError:
        return False
    return True


@api_view(["POST"])
@permission_classes([AllowAny])
def inbound_email(request: Request) -> Response:
    """Provider-agnostic inbound email webhook.

    Real providers (Graph, Mailgun, etc.) translate their native format into
    this payload and POST it here. Idempotency and threading live in
    ``process_inbound_email``.
    """
    body, event_id, failure = _verified_payload(request)
    if failure is not None:
        return failure
    assert body is not None
    required = ("from", "to", "subject", "body_text", "message_id")
    missing = [k for k in required if not body.get(k)]
    if missing:
        return Response(
            {"status": "error", "detail": f"missing fields: {', '.join(missing)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if body.get("sender_verified") is not True:
        return Response(
            {"status": "error", "detail": "sender verification required"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    message_id = str(body["message_id"])
    with transaction.atomic():
        if not _claim_event(
            event_id=event_id,
            event_type="inbound",
            message_id=message_id,
        ):
            return Response({"status": "duplicate"})
        outcome = process_inbound_email(
            from_header=str(body["from"]),
            to_header=str(body["to"]),
            subject=str(body["subject"]),
            body_text=str(body["body_text"]),
            body_html=str(body.get("body_html", "")),
            message_id=message_id,
            in_reply_to=str(body.get("in_reply_to", "")),
            references=str(body.get("references", "")),
            sender_verified=body.get("sender_verified") is True,
        )
        if outcome.get("status") == "error":
            transaction.set_rollback(True)
    if outcome.get("status") == "error":
        return Response(outcome, status=status.HTTP_400_BAD_REQUEST)
    response_status = (
        status.HTTP_201_CREATED if outcome.get("status") == "created" else 200
    )
    return Response(outcome, status=response_status)


@api_view(["POST"])
@permission_classes([AllowAny])
def outbound_bounce(request: Request) -> Response:
    """Provider webhook for delivery failures (PRD §19.4)."""
    body, event_id, failure = _verified_payload(request)
    if failure is not None:
        return failure
    assert body is not None
    raw_message_id = body.get("message_id")
    message_id = raw_message_id.strip() if isinstance(raw_message_id, str) else ""
    if not message_id:
        return Response(
            {"status": "invalid_message_id"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    event_type = body.get("type")
    event_mapping = {
        "failure": (
            EmailWebhookEvent.EventType.DELIVERY_FAILURE,
            EmailDelivery.Status.FAILED,
        ),
        "bounce": (
            EmailWebhookEvent.EventType.DELIVERY_BOUNCE,
            EmailDelivery.Status.BOUNCED,
        ),
    }
    if not isinstance(event_type, str) or event_type not in event_mapping:
        return Response(
            {"status": "invalid_event_type"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    receipt_type, delivery_status = event_mapping[event_type]
    with transaction.atomic():
        try:
            delivery = (
                EmailDelivery.objects.select_for_update()
                .select_related("ticket_message__ticket")
                .get(message_id=message_id)
            )
        except EmailDelivery.DoesNotExist:
            return Response(
                {"status": "unknown_message_id"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except EmailDelivery.MultipleObjectsReturned:
            return Response(
                {"status": "ambiguous_message_id"},
                status=status.HTTP_409_CONFLICT,
            )
        if not _claim_event(
            event_id=event_id,
            event_type=receipt_type,
            message_id=message_id,
        ):
            return Response({"status": "duplicate"})
        if (
            delivery.status == EmailDelivery.Status.BOUNCED
            and delivery_status == EmailDelivery.Status.FAILED
        ):
            return Response({"status": "ignored"})
        previous_status = delivery.ticket_message.delivery_status
        delivery.status = delivery_status
        delivery.error = str(body.get("error", ""))[:2000]
        delivery.save(update_fields=["status", "error"])
        delivery.ticket_message.delivery_status = delivery_status
        delivery.ticket_message.save(update_fields=["delivery_status"])
        record_ticket_event(
            ticket=delivery.ticket_message.ticket,
            actor_subject="email:adapter",
            action="ticket.message.delivery_updated",
            before={"delivery_status": previous_status},
            after={"delivery_status": delivery_status},
            metadata={
                "channel": "email",
                "provider_message_id": message_id,
            },
        )
    return Response({"status": "recorded"})
