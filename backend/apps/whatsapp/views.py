"""WhatsApp channel HTTP endpoints."""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.identity_access.authentication import KeycloakJWTAuthentication
from apps.identity_access.models import User
from apps.identity_access.scope import ScopePermission, scope_ticket_queryset
from apps.tickets.events import record_ticket_event
from apps.tickets.models import Ticket, TicketMessage
from apps.tickets.permissions import can_add_ticket_content
from apps.tickets.services import add_message

from .models import WhatsappAccount, WhatsappMessage
from .services import (
    ProviderTemplateDiscoveryError,
    get_provider,
    process_inbound_whatsapp,
)
from .webhook_security import authenticate_meta_request, is_recent_meta_timestamp

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _InboundMetaMessage:
    account: WhatsappAccount
    from_number: str
    to_number: str
    body: str
    external_message_id: str
    message_type: str


@dataclass(frozen=True)
class _MetaDeliveryStatus:
    account: WhatsappAccount
    external_message_id: str
    delivery_status: str
    timestamp: int


_MetaEvent = _InboundMetaMessage | _MetaDeliveryStatus
_META_DELIVERY_STATUSES = {"sent", "delivered", "read", "failed"}
_META_DELIVERY_RANK = {
    "pending": 0,
    "sent": 1,
    "failed": 2,
    "delivered": 3,
    "read": 4,
}


def _authenticated_user(request: Request) -> User:
    if isinstance(request.user, User):
        return request.user
    raise PermissionDenied(
        detail="Authentication credentials were not provided.",
        code="not_authenticated",
    )


def _mutable_ticket(request: Request, number: str) -> Ticket:
    actor = _authenticated_user(request)
    ticket = get_object_or_404(
        scope_ticket_queryset(
            actor,
            Ticket.objects.select_related("requester"),
            request=request,
        ),
        number=number,
    )
    if not can_add_ticket_content(actor, ticket, request=request):
        raise PermissionDenied(
            detail="You do not have permission to send on this ticket.",
            code="ticket_mutation_forbidden",
        )
    return ticket


def _channel_account(ticket: Ticket) -> WhatsappAccount | None:
    return (
        WhatsappAccount.objects.filter(
            domain=ticket.domain,
            is_active=True,
        )
        .exclude(access_token="")
        .exclude(business_id="")
        .order_by("created_at", "id")
        .first()
    )


def _template_body(template: Mapping[str, object]) -> str:
    direct = template.get("body")
    if isinstance(direct, str):
        return direct
    components = template.get("components")
    if not isinstance(components, list):
        return ""
    for component in components:
        if not isinstance(component, dict):
            continue
        if str(component.get("type", "")).upper() != "BODY":
            continue
        text = component.get("text")
        return text if isinstance(text, str) else ""
    return ""


def _approved_template(
    templates: list[dict[str, object]],
    *,
    name: str,
    language: str,
) -> dict[str, object] | None:
    return next(
        (
            template
            for template in templates
            if template.get("name") == name
            and template.get("language") == language
            and str(template.get("status", "")).upper() == "APPROVED"
        ),
        None,
    )


def _render_template(template: Mapping[str, object], parameters: list[str]) -> str | None:
    body = _template_body(template)
    placeholders = [int(value) for value in re.findall(r"\{\{(\d+)\}\}", body)]
    if set(placeholders) != set(range(1, len(parameters) + 1)):
        return None
    rendered = body
    for index, parameter in enumerate(parameters, start=1):
        rendered = rendered.replace(f"{{{{{index}}}}}", parameter)
    return rendered if rendered and not re.search(r"\{\{\d+\}\}", rendered) else None


def _meta_events(parsed: dict[str, object]) -> tuple[list[_MetaEvent], str | None]:
    """Validate every event before any event in the signed batch is mutated."""
    if parsed.get("object") != "whatsapp_business_account":
        return [], "invalid_payload"
    entries = parsed.get("entry")
    if not isinstance(entries, list) or not entries:
        return [], "invalid_payload"
    events: list[_MetaEvent] = []
    for entry in entries:
        if not isinstance(entry, dict):
            return [], "invalid_payload"
        business_id = entry.get("id")
        if not isinstance(business_id, str) or not business_id.strip():
            return [], "invalid_payload"
        changes = entry.get("changes")
        if not isinstance(changes, list) or not changes:
            return [], "invalid_payload"
        for change in changes:
            if (
                not isinstance(change, dict)
                or change.get("field") != "messages"
            ):
                return [], "invalid_payload"
            value = change.get("value")
            if not isinstance(value, dict):
                return [], "invalid_payload"
            metadata = value.get("metadata")
            if not isinstance(metadata, dict):
                return [], "invalid_payload"
            phone_number_id = metadata.get("phone_number_id")
            if not isinstance(phone_number_id, str) or not phone_number_id:
                return [], "invalid_payload"
            account = WhatsappAccount.objects.filter(
                phone_number_id=phone_number_id,
                business_id=business_id,
                is_active=True,
            ).first()
            if account is None:
                return [], "account_unavailable"
            to_number = str(metadata.get("display_phone_number", ""))

            messages = value.get("messages", [])
            statuses = value.get("statuses", [])
            if not isinstance(messages, list) or not isinstance(statuses, list):
                return [], "invalid_payload"
            if not messages and not statuses:
                return [], "invalid_payload"
            for message in messages:
                if not isinstance(message, dict):
                    return [], "invalid_payload"
                if not is_recent_meta_timestamp(message.get("timestamp")):
                    return [], "stale_timestamp"
                text_payload = message.get("text")
                if not isinstance(text_payload, dict):
                    return [], "invalid_payload"
                from_number = message.get("from")
                external_message_id = message.get("id")
                message_type = message.get("type")
                body = text_payload.get("body")
                if not isinstance(from_number, str) or not from_number:
                    return [], "invalid_payload"
                if not isinstance(external_message_id, str) or not external_message_id:
                    return [], "invalid_payload"
                if not isinstance(message_type, str) or not message_type:
                    return [], "invalid_payload"
                if not isinstance(body, str) or not body:
                    return [], "invalid_payload"
                event = _InboundMetaMessage(
                    account=account,
                    from_number=from_number,
                    to_number=to_number,
                    body=body,
                    external_message_id=external_message_id,
                    message_type=message_type,
                )
                events.append(event)

            for delivery in statuses:
                if not isinstance(delivery, dict):
                    return [], "invalid_payload"
                timestamp_value = delivery.get("timestamp")
                if not is_recent_meta_timestamp(timestamp_value):
                    return [], "stale_timestamp"
                external_message_id = delivery.get("id")
                raw_delivery_status = delivery.get("status")
                if (
                    not isinstance(external_message_id, str)
                    or not external_message_id
                    or not isinstance(raw_delivery_status, str)
                ):
                    return [], "invalid_payload"
                delivery_status = raw_delivery_status.lower()
                if delivery_status not in _META_DELIVERY_STATUSES:
                    return [], "invalid_payload"
                events.append(
                    _MetaDeliveryStatus(
                        account=account,
                        external_message_id=external_message_id,
                        delivery_status=delivery_status,
                        timestamp=int(str(timestamp_value)),
                    )
                )
    return events, None


def _record_meta_delivery_status(event: _MetaDeliveryStatus) -> dict[str, str]:
    with transaction.atomic():
        channel_message = (
            WhatsappMessage.objects.select_for_update()
            .filter(
                account=event.account,
                external_message_id=event.external_message_id,
                direction=WhatsappMessage.Direction.OUTBOUND,
            )
            .first()
        )
        if channel_message is None:
            return {
                "status": "unknown_message_id",
                "external_message_id": event.external_message_id,
            }
        raw_payload = (
            channel_message.raw_payload
            if isinstance(channel_message.raw_payload, dict)
            else {}
        )
        prior_timestamp = raw_payload.get("status_timestamp", 0)
        try:
            prior_timestamp_int = int(str(prior_timestamp))
        except ValueError:
            prior_timestamp_int = 0
        current_rank = _META_DELIVERY_RANK.get(
            channel_message.delivery_status,
            0,
        )
        candidate_rank = _META_DELIVERY_RANK[event.delivery_status]
        if event.timestamp < prior_timestamp_int or candidate_rank < current_rank:
            return {
                "status": "ignored",
                "external_message_id": event.external_message_id,
            }
        if channel_message.delivery_status == event.delivery_status:
            if event.timestamp > prior_timestamp_int:
                channel_message.raw_payload = {
                    **raw_payload,
                    "status_timestamp": event.timestamp,
                    "status_rank": candidate_rank,
                }
                channel_message.save(update_fields=["raw_payload"])
                return {
                    "status": "timestamp_advanced",
                    "external_message_id": event.external_message_id,
                }
            return {
                "status": "duplicate",
                "external_message_id": event.external_message_id,
            }
        if event.timestamp == prior_timestamp_int and candidate_rank <= current_rank:
            return {
                "status": "duplicate",
                "external_message_id": event.external_message_id,
            }

        previous_status = channel_message.delivery_status
        channel_message.delivery_status = event.delivery_status
        channel_message.raw_payload = {
            **raw_payload,
            "status_timestamp": event.timestamp,
            "status_rank": candidate_rank,
        }
        channel_message.save(update_fields=["delivery_status", "raw_payload"])
        if channel_message.ticket_id is not None:
            ticket = Ticket.objects.get(pk=channel_message.ticket_id)
            TicketMessage.objects.filter(
                ticket_id=channel_message.ticket_id,
                external_message_id=event.external_message_id,
                direction=TicketMessage.Direction.OUTBOUND,
            ).update(delivery_status=event.delivery_status)
            record_ticket_event(
                ticket=ticket,
                actor_subject="whatsapp:meta",
                action="ticket.message.delivery_updated",
                before={"delivery_status": previous_status},
                after={"delivery_status": event.delivery_status},
                metadata={
                    "channel": "whatsapp",
                    "provider_message_id": event.external_message_id,
                },
            )
        return {
            "status": "updated",
            "external_message_id": event.external_message_id,
            "delivery_status": event.delivery_status,
        }


def _persist_discovery_attempt(
    *,
    ticket: Ticket,
    account: WhatsappAccount,
    template_name: str,
    language: str,
    parameters: list[str],
) -> WhatsappMessage:
    with transaction.atomic():
        return WhatsappMessage.objects.create(
            ticket=ticket,
            account=account,
            from_number="",
            to_number=ticket.requester.phone_e164,
            direction=WhatsappMessage.Direction.OUTBOUND,
            body="",
            delivery_status="pending",
            raw_payload={
                "phase": "template_discovery",
                "template_name": template_name,
                "template_language": language,
                "template_parameters": parameters,
                "retryable": True,
            },
        )


def _mark_discovery_attempt(
    attempt: WhatsappMessage,
    *,
    phase: str,
    error_code: str,
    retryable: bool,
) -> None:
    with transaction.atomic():
        locked_attempt = WhatsappMessage.objects.select_for_update().get(pk=attempt.pk)
        raw_payload = (
            locked_attempt.raw_payload
            if isinstance(locked_attempt.raw_payload, dict)
            else {}
        )
        locked_attempt.delivery_status = "pending" if retryable else "failed"
        locked_attempt.raw_payload = {
            **raw_payload,
            "phase": phase,
            "error_code": error_code,
            "retryable": retryable,
        }
        locked_attempt.save(update_fields=["delivery_status", "raw_payload"])


def _persist_pending_outbound(
    *,
    ticket: Ticket,
    account: WhatsappAccount,
    channel_message: WhatsappMessage,
    rendered: str,
    template_name: str,
    language: str,
    parameters: list[str],
    actor: User,
    request: Request,
) -> tuple[TicketMessage, WhatsappMessage]:
    with transaction.atomic():
        ticket_message = add_message(
            ticket=ticket,
            direction="outbound",
            body_text=rendered,
            actor_subject=actor.keycloak_subject,
            author_subject=actor.keycloak_subject,
            author_label=actor.display_name,
            template_key=template_name,
            template_version=language,
            delivery_status="pending",
            event_metadata={
                "channel": "whatsapp",
                "template_name": template_name,
                "template_language": language,
                "delivery_status": "pending",
            },
            actor=actor,
            request=request,
        )
        channel_message = WhatsappMessage.objects.select_for_update().get(
            pk=channel_message.pk
        )
        channel_message.body = rendered
        channel_message.raw_payload = {
            "phase": "ready_to_send",
            "template_name": template_name,
            "template_language": language,
            "template_parameters": parameters,
            "retryable": True,
        }
        channel_message.save(update_fields=["body", "raw_payload"])
    return ticket_message, channel_message


def _finalize_outbound(
    *,
    ticket_message: TicketMessage,
    channel_message: WhatsappMessage,
    provider_result: dict[str, str],
) -> tuple[str, str]:
    delivery_status = provider_result.get("status", "failed")
    if delivery_status != "sent":
        delivery_status = "failed"
    external_message_id = provider_result.get("external_message_id", "")
    if delivery_status == "sent" and not external_message_id:
        delivery_status = "failed"
    if len(external_message_id) > 128:
        delivery_status = "failed"
        external_message_id = ""

    with transaction.atomic():
        locked_channel = WhatsappMessage.objects.select_for_update().get(
            pk=channel_message.pk
        )
        locked_ticket_message = TicketMessage.objects.select_for_update().get(
            pk=ticket_message.pk
        )
        locked_ticket = Ticket.objects.select_for_update().get(
            pk=locked_ticket_message.ticket_id
        )
        previous_status = locked_channel.delivery_status
        locked_channel.delivery_status = delivery_status
        locked_channel.external_message_id = external_message_id
        locked_channel.save(
            update_fields=["delivery_status", "external_message_id"]
        )
        locked_ticket_message.delivery_status = delivery_status
        locked_ticket_message.external_message_id = external_message_id
        locked_ticket_message.save(
            update_fields=["delivery_status", "external_message_id"]
        )
        record_ticket_event(
            ticket=locked_ticket,
            actor_subject="whatsapp:provider",
            action="ticket.message.delivery_updated",
            before={"delivery_status": previous_status},
            after={"delivery_status": delivery_status},
            metadata={
                "channel": "whatsapp",
                "provider_message_id": external_message_id,
            },
        )
        if delivery_status == "sent" and locked_ticket.first_responded_at is None:
            from apps.sla.services import complete_sla

            locked_ticket.first_responded_at = timezone.now()
            locked_ticket.save(update_fields=["first_responded_at", "updated_at"])
            complete_sla(
                ticket=locked_ticket,
                kind="first_response",
                at=locked_ticket.first_responded_at,
            )
    return delivery_status, external_message_id


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def inbound_webhook(request: Request) -> Response | HttpResponse:
    """Inbound WhatsApp webhook (Meta Cloud API webhook format)."""
    if request.method == "GET":
        expected = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
        supplied = request.query_params.get("hub.verify_token", "")
        challenge = request.query_params.get("hub.challenge", "")
        if not expected:
            return Response(
                {"status": "unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if (
            request.query_params.get("hub.mode") != "subscribe"
            or not hmac.compare_digest(expected, supplied)
        ):
            return Response(
                {"status": "forbidden"},
                status=status.HTTP_403_FORBIDDEN,
            )
        return HttpResponse(challenge, content_type="text/plain")

    raw_body = request.body
    authentication = authenticate_meta_request(request, raw_body)
    if not authentication.configured:
        return Response(
            {"status": "unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if not authentication.authenticated:
        return Response(
            {"status": "unauthorized"},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    try:
        parsed: object = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return Response({"status": "invalid_payload"}, status=400)
    if not isinstance(parsed, dict):
        return Response({"status": "invalid_payload"}, status=400)
    events, parse_error = _meta_events(parsed)
    if parse_error == "stale_timestamp":
        return Response(
            {"status": "unauthorized"},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    if parse_error == "account_unavailable":
        return Response(
            {"status": "account_unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if parse_error is not None:
        return Response({"status": "invalid_payload"}, status=400)
    if not events:
        return Response({"status": "no_messages"})

    results: list[dict[str, str]] = []
    with transaction.atomic():
        for event in events:
            if isinstance(event, _InboundMetaMessage):
                result = process_inbound_whatsapp(
                    account=event.account,
                    from_number=event.from_number,
                    to_number=event.to_number,
                    body=event.body,
                    external_message_id=event.external_message_id,
                    raw={
                        "provider_message_id": event.external_message_id,
                        "type": event.message_type,
                    },
                )
            else:
                result = _record_meta_delivery_status(event)
            if result.get("status") == "error":
                transaction.set_rollback(True)
                return Response(result, status=status.HTTP_400_BAD_REQUEST)
            results.append(result)

    if any(result.get("status") == "unknown_message_id" for result in results):
        return Response(
            {"status": "retry", "results": results},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    any_created = any(result.get("status") == "created" for result in results)
    response_body: Mapping[str, object]
    if len(results) == 1 and isinstance(events[0], _InboundMetaMessage):
        response_body = results[0]
    else:
        response_body = {"status": "processed", "results": results}
    return Response(
        response_body,
        status=(
            status.HTTP_201_CREATED if any_created else status.HTTP_200_OK
        ),
    )


@api_view(["GET"])
@authentication_classes([KeycloakJWTAuthentication])
@permission_classes([IsAuthenticated, ScopePermission])
def list_templates(request: Request) -> Response:
    """Return the templates known to the configured provider."""
    ticket_number = request.query_params.get("ticket_number", "")
    if not ticket_number:
        return Response(
            {"code": "ticket_number_required", "detail": "ticket_number is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    ticket = _mutable_ticket(request, ticket_number)
    account = _channel_account(ticket)
    if account is None:
        return Response(
            {"code": "whatsapp_account_unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    provider = get_provider()
    try:
        templates = provider.fetch_templates(
            account_token=account.access_token,
            business_id=account.business_id,
        )
    except ProviderTemplateDiscoveryError as exc:
        return Response(
            {
                "code": "whatsapp_template_discovery_unavailable",
                "retryable": exc.retryable,
            },
            status=(
                status.HTTP_503_SERVICE_UNAVAILABLE
                if exc.retryable
                else status.HTTP_502_BAD_GATEWAY
            ),
        )
    return Response(
        {"templates": templates}
    )


@api_view(["POST"])
@authentication_classes([KeycloakJWTAuthentication])
@permission_classes([IsAuthenticated, ScopePermission])
def send_text(request: Request) -> Response:
    """Send one approved template on an authorized ticket."""
    data = request.data or {}
    ticket_number = str(data.get("ticket_number", ""))
    template_name = str(data.get("template_name", ""))
    language = str(data.get("language", "en"))
    raw_parameters = data.get("parameters", [])
    if (
        not ticket_number
        or not template_name
        or not isinstance(raw_parameters, list)
        or not all(isinstance(value, str) for value in raw_parameters)
    ):
        return Response(
            {"code": "invalid_whatsapp_template"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    parameters = [value for value in raw_parameters if isinstance(value, str)]
    ticket = _mutable_ticket(request, ticket_number)
    if ticket.requester.consent_at is None or ticket.requester.opted_out_at is not None:
        return Response(
            {"code": "whatsapp_consent_required"},
            status=status.HTTP_409_CONFLICT,
        )
    if not ticket.requester.phone_e164:
        return Response(
            {"code": "whatsapp_recipient_unavailable"},
            status=status.HTTP_409_CONFLICT,
        )
    account = _channel_account(ticket)
    if account is None:
        return Response(
            {"code": "whatsapp_account_unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    actor = _authenticated_user(request)
    channel_message = _persist_discovery_attempt(
        ticket=ticket,
        account=account,
        template_name=template_name,
        language=language,
        parameters=parameters,
    )
    provider = get_provider()
    try:
        templates = provider.fetch_templates(
            account_token=account.access_token,
            business_id=account.business_id,
        )
    except ProviderTemplateDiscoveryError as exc:
        _mark_discovery_attempt(
            channel_message,
            phase="template_discovery_failed",
            error_code="whatsapp_template_discovery_unavailable",
            retryable=exc.retryable,
        )
        return Response(
            {
                "code": "whatsapp_template_discovery_unavailable",
                "retryable": exc.retryable,
            },
            status=(
                status.HTTP_503_SERVICE_UNAVAILABLE
                if exc.retryable
                else status.HTTP_502_BAD_GATEWAY
            ),
        )
    template = _approved_template(
        templates,
        name=template_name,
        language=language,
    )
    if template is None:
        _mark_discovery_attempt(
            channel_message,
            phase="template_rejected",
            error_code="whatsapp_template_not_approved",
            retryable=False,
        )
        return Response(
            {"code": "whatsapp_template_not_approved"},
            status=status.HTTP_409_CONFLICT,
        )
    rendered = _render_template(template, parameters)
    if rendered is None:
        _mark_discovery_attempt(
            channel_message,
            phase="template_rejected",
            error_code="whatsapp_template_parameters_invalid",
            retryable=False,
        )
        return Response(
            {"code": "whatsapp_template_parameters_invalid"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    ticket_message, channel_message = _persist_pending_outbound(
        ticket=ticket,
        account=account,
        channel_message=channel_message,
        rendered=rendered,
        template_name=template_name,
        language=language,
        parameters=parameters,
        actor=actor,
        request=request,
    )
    result = provider.send_template(
        to=ticket.requester.phone_e164,
        template_name=template_name,
        language=language,
        parameters=parameters,
        phone_number_id=account.phone_number_id,
        account_token=account.access_token,
    )
    try:
        delivery_status, external_message_id = _finalize_outbound(
            ticket_message=ticket_message,
            channel_message=channel_message,
            provider_result=result,
        )
    except IntegrityError:
        return Response(
            {"code": "whatsapp_duplicate_provider_message"},
            status=status.HTTP_409_CONFLICT,
        )
    response_status = (
        status.HTTP_200_OK
        if delivery_status == "sent"
        else status.HTTP_502_BAD_GATEWAY
    )
    return Response(
        {
            "status": delivery_status,
            "external_message_id": external_message_id,
        },
        status=response_status,
    )
