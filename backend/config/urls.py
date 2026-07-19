"""Top-level URL configuration for the MHC e-Ticketing backend."""
from __future__ import annotations

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny


@api_view(["GET"])
@permission_classes([AllowAny])
def root(_request):
    return JsonResponse({
        "name": "MHC Unified e-Ticketing and Service Desk API",
        "version": "0.1.0",
        "environment": __import__("django.conf", fromlist=["settings"]).settings.ENVIRONMENT,
        "docs": "/api/v1/docs",
        "health": "/api/v1/health",
    })


urlpatterns = [
    path("", root),
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.health.urls")),
    path("api/v1/identity/", include("apps.identity_access.urls")),
    path("api/v1/", include("apps.organisations.urls")),
    path("api/v1/", include("apps.contacts.urls")),
    path("api/v1/", include("apps.catalogue.urls")),
    path("api/v1/", include("apps.tickets.urls")),
    path("api/v1/", include("apps.workflow.urls")),
    path("api/v1/", include("apps.sla.urls")),
    path("api/v1/", include("apps.files.urls")),
    path("api/v1/", include("apps.audit.urls")),
    path("api/v1/", include("apps.notifications.urls")),
    path("api/v1/", include("apps.integrations.urls")),
    path("api/v1/", include("apps.email_channel.urls")),
    path("api/v1/", include("apps.whatsapp.urls")),
    path("api/v1/", include("apps.knowledge.urls")),
    path("api/v1/", include("apps.csat.urls")),
    path("api/v1/", include("apps.automation.urls")),
    path("api/v1/", include("apps.reporting.urls")),
    path("api/v1/", include("apps.administration.urls")),
    # Prometheus exposition
    path("", include("django_prometheus.urls")),
]
