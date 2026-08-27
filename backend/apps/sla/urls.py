"""URL configuration for the sla app."""

from django.urls import path

from . import views

urlpatterns = [
    path("sla/", views.list_view, name="sla-list"),
]
