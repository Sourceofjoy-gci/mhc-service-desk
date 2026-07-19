"""URL configuration for the tickets app."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.register(r"tickets", views.TicketViewSet, basename="tickets")

urlpatterns = [
    path("tickets/public/intake/", views.public_intake, name="tickets-public-intake"),
    path("tickets/dashboard/operational/", views.operational_dashboard, name="tickets-dashboard-operational"),
    path("", include(router.urls)),
]
