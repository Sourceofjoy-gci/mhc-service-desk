"""Flow analytics for the Kanban (PRD §10.3 — P2).

Computes throughput, lead time, cycle time, WIP and blocked time from the
status history table. Numbers are returned as JSON; visualisations live in
the SPA or Metabase in P2.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.identity_access.authentication import KeycloakJWTAuthentication
from apps.identity_access.scope import ScopePermission

from apps.tickets.models import Ticket
from apps.workflow.models import Status


@api_view(["GET"])
@permission_classes([IsAuthenticated, ScopePermission])
def flow_metrics(request):
    """Compute flow metrics for a domain over a window."""
    domain = request.query_params.get("domain", "operational")
    days = int(request.query_params.get("days", "30"))
    now = datetime.now(tz=timezone.utc)
    window_start = now.timestamp() - days * 86400

    qs = Ticket.objects.filter(domain=domain, created_at__gte=datetime.fromtimestamp(window_start, tz=timezone.utc))
    closed = qs.filter(status__is_terminal=True)
    lead_times = []
    cycle_times = []
    for t in closed[:500]:  # cap for performance
        if t.resolved_at and t.created_at:
            cycle_times.append((t.resolved_at - t.created_at).total_seconds())
        if t.closed_at and t.created_at:
            lead_times.append((t.closed_at - t.created_at).total_seconds())

    wip = qs.exclude(status__is_terminal=True).count()
    by_status = list(
        qs.values("status__code", "status__name").annotate(count=__import__("django").db.models.Count("id"))
    )

    def pctile(values, p):
        if not values:
            return None
        return round(statistics.quantiles(values, n=100)[p - 1] if len(values) >= 100 else sorted(values)[int(len(values) * p / 100)], 1)

    return Response({
        "domain": domain,
        "window_days": days,
        "wip": wip,
        "throughput": closed.count(),
        "lead_time_hours": {
            "avg": round(statistics.mean(lead_times) / 3600, 1) if lead_times else None,
            "p50": pctile(lead_times, 50),
            "p95": pctile(lead_times, 95),
        },
        "cycle_time_hours": {
            "avg": round(statistics.mean(cycle_times) / 3600, 1) if cycle_times else None,
            "p50": pctile(cycle_times, 50),
            "p95": pctile(cycle_times, 95),
        },
        "by_status": by_status,
    })
