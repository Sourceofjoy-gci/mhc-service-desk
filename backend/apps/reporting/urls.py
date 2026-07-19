from django.urls import path

from . import views

urlpatterns = [
    path("reports/tickets.csv", views.export_tickets_csv, name="export-tickets-csv"),
    path("reports/dashboard/operational", views.operational_dashboard, name="dashboard-operational"),
    path("reports/dashboard/it", views.it_dashboard, name="dashboard-it"),
]
