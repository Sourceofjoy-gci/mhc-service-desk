"""URL configuration for the tickets app."""
from django.urls import path

from . import views

urlpatterns = [
    path("tickets/", views.list_view, name="tickets-list"),
]
