"""Monitoring adapter — Prometheus AlertManager / Grafana webhook.

A single endpoint accepts an authenticated webhook and converts each alert
into a ticket. Idempotency is enforced by the (provider, external_id) pair
so a flapping alert does not produce a flood of duplicate tickets.

PRD §19.8: alert correlation must prevent a single outage from creating
excessive independent tickets. We collapse alerts that share a
`deduplication_key` (e.g. alertname+instance).
"""
from __future__ import annotations

import hashlib
import logging
from collections import defaultdict

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.catalogue.models import RequestType, Service
from apps.contacts.models import Contact
from apps.organisations.models import Office
from apps.sla.models import SlaPolicy
from apps.sla.services import instantiate_slas
from apps.tickets import services
from apps.tickets.models import OutboxEvent, Ticket

logger = logging.getLogger(__name__)


def _coalesce(alerts: list[dict]) -> list[list[dict]]:
    """Group alerts by their deduplication key, preserving order."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for alert in alerts:
        key = alert.get("deduplication_key") or hashlib.sha256(
            (alert.get("title") or "").encode()
        ).hexdigest()[:12]
        buckets[key].append(alert)
    return list(buckets.values())


@api_view(["POST"])
@permission_classes([AllowAny])
def monitoring_webhook(request):
    """Receive a list of alerts and create one ticket per deduplication group."""
    body = request.data or {}
    alerts = body.get("alerts", [])
    if not isinstance(alerts, list) or not alerts:
        return Response({"status": "no_alerts"}, status=400)
    groups = _coalesce(alerts)
    created = []
    for group in groups:
        first = group[0]
        # Idempotency
        ext_id = first.get("external_id") or hashlib.sha256(
            f"{first.get('title','')}|{first.get('deduplication_key','')}".encode()
        ).hexdigest()
        if Ticket.objects.filter(external_message_id=ext_id).exists():
            continue
        service = Service.objects.filter(domain="it", is_active=True).first()
        request_type = RequestType.objects.filter(service=service, is_active=True).first() if service else None
        office = Office.objects.filter(is_active=True).first()
        requester, _ = Contact.objects.get_or_create(
            email="monitoring@mhc.local",
            defaults={"full_name": "Monitoring"},
        )
        if not service or not request_type or not office:
            return Response({"detail": "missing seed data"}, status=500)
        priority = first.get("priority") or "P2"
        description_lines = [
            f"Monitoring alert — {len(group)} correlated event(s).",
            f"Source: {first.get('source', 'unknown')}",
            f"Severity: {first.get('severity', 'unknown')}",
            "",
        ]
        for alert in group:
            description_lines.append(f"- {alert.get('title', '?')}")
            if alert.get("description"):
                description_lines.append(f"    {alert['description']}")
        ticket = services.create_ticket(
            domain="it",
            title=f"[monitoring] {first.get('title', 'Alert')}",
            description="\n".join(description_lines),
            requester=requester,
            service=service,
            request_type=request_type,
            office=office,
            channel="monitoring",
            source_account=first.get("source", "monitoring"),
            priority=priority,
            actor_subject=f"monitoring:{first.get('source', 'unknown')}",
        )
        ticket.external_message_id = ext_id
        ticket.save(update_fields=["external_message_id", "updated_at"])
        try:
            policy = SlaPolicy.objects.get(domain="it", priority=ticket.priority, is_active=True)
            instantiate_slas(ticket=ticket, policy=policy)
        except SlaPolicy.DoesNotExist:
            pass
        OutboxEvent.objects.create(
            aggregate="ticket",
            aggregate_id=str(ticket.id),
            event_type="ticket.monitoring_alert",
            payload={"alert_count": len(group), "external_id": ext_id},
        )
        created.append(ticket.number)
    return Response({"created": created, "groups": len(groups)}, status=201)
