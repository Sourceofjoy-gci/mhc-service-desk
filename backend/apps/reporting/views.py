"""Reporting views — CSV export and dashboards."""
from __future__ import annotations

import csv

from django.http import StreamingHttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.identity_access.authentication import KeycloakJWTAuthentication
from apps.identity_access.scope import ScopePermission, attach_scopes
from apps.tickets.models import Ticket


class Echo:
    """File-like object that echoes writes to a stream."""

    def write(self, value):
        return value


@api_view(["GET"])
@permission_classes([IsAuthenticated, ScopePermission])
def export_tickets_csv(request):
    """Stream a CSV of the tickets visible to the caller (FR-087)."""
    # Re-use the same filter logic as the list view via attach_scopes
    class _Shim:
        pass
    shim = _Shim()
    shim.queryset = Ticket.objects.all()
    shim.request = request
    viewset_like = type("V", (), {"get_queryset": lambda self: Ticket.objects.all()})()
    viewset_like.request = request
    # Re-implement the filter inline (kept narrow to avoid coupling)
    attach_scopes(request)
    qs = Ticket.objects.select_related("status", "requester", "service", "office").all()
    scopes = request.user._scopes
    domain_filter = None
    from django.db.models import Q
    for s in scopes:
        if s.domain in ("admin", "audit"):
            domain_filter = Q()  # no domain restriction
            break
        if domain_filter is None:
            domain_filter = Q(domain=s.domain)
        else:
            domain_filter |= Q(domain=s.domain)
    if domain_filter is not None:
        qs = qs.filter(domain_filter)
    qs = qs.order_by("-created_at")

    params = request.query_params
    if "status" in params:
        qs = qs.filter(status__code=params["status"])
    if "priority" in params:
        qs = qs.filter(priority=params["priority"])
    if "domain" in params:
        qs = qs.filter(domain=params["domain"])

    def rows():
        writer = csv.writer(Echo())
        yield writer.writerow([
            "number", "domain", "title", "status", "priority",
            "requester", "office", "channel", "created_at", "updated_at",
            "resolution_code", "matter_reference",
        ])
        for t in qs.iterator(chunk_size=200):
            yield writer.writerow([
                t.number, t.domain, t.title, t.status.code, t.priority,
                t.requester.full_name, t.office.code, t.channel,
                t.created_at.isoformat(), t.updated_at.isoformat(),
                t.resolution_code, t.matter_reference,
            ])

    response = StreamingHttpResponse(rows(), content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="tickets.csv"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@api_view(["GET"])
@permission_classes([IsAuthenticated, ScopePermission])
def operational_dashboard(request):
    """Live KPIs for the operational service desk."""
    from django.db.models import Count, Q
    from django.utils import timezone
    from datetime import timedelta

    qs = Ticket.objects.filter(domain="operational")
    now = timezone.now()
    return Response({
        "totals": {
            "open": qs.exclude(status__code__in=[
                "closed", "resolved", "cancelled", "rejected", "duplicate", "spam"
            ]).count(),
            "today": qs.filter(created_at__date=now.date()).count(),
            "this_week": qs.filter(created_at__gte=now - timedelta(days=7)).count(),
        },
        "by_priority": list(qs.values("priority").annotate(count=Count("id")).order_by("priority")),
        "by_status": list(
            qs.values("status__code", "status__name").annotate(count=Count("id"))
            .order_by("status__order")
        ),
        "unassigned": qs.filter(assignee__isnull=True).exclude(
            status__code__in=["closed", "resolved", "cancelled", "rejected", "duplicate", "spam"]
        ).count(),
        "breached_sla": qs.filter(sla_instances__state="breached").distinct().count(),
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated, ScopePermission])
def it_dashboard(request):
    """Live KPIs for the IT service desk."""
    from django.db.models import Count, Q
    from django.utils import timezone
    from datetime import timedelta

    qs = Ticket.objects.filter(domain="it")
    now = timezone.now()
    return Response({
        "totals": {
            "open": qs.exclude(status__code__in=[
                "closed", "resolved", "cancelled"
            ]).count(),
            "today": qs.filter(created_at__date=now.date()).count(),
            "this_week": qs.filter(created_at__gte=now - timedelta(days=7)).count(),
        },
        "by_priority": list(qs.values("priority").annotate(count=Count("id")).order_by("priority")),
        "by_status": list(
            qs.values("status__code", "status__name").annotate(count=Count("id"))
            .order_by("status__order")
        ),
        "unassigned": qs.filter(assignee__isnull=True).exclude(
            status__code__in=["closed", "resolved", "cancelled"]
        ).count(),
        "p1p2": qs.filter(priority__in=["P1", "P2"]).exclude(
            status__code__in=["closed", "resolved", "cancelled"]
        ).count(),
    })
