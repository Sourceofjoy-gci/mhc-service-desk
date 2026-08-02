from django.urls import path

from . import monitoring, views

urlpatterns = [
    path(
        "tickets/<str:ticket_number>/validate-matter/",
        views.validate_matter,
        name="validate-matter",
    ),
    path(
        "integrations/monitoring/events/",
        monitoring.monitoring_webhook,
        name="monitoring-webhook",
    ),
]
