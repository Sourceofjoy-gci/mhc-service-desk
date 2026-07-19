"""URL configuration for the integrations app."""
from django.urls import path

from . import views

urlpatterns = [
    path("integrations/", views.list_view, name="integrations-list"),
]
