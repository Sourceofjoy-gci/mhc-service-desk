"""URL configuration for the reporting app."""
from django.urls import path

from . import views

urlpatterns = [
    path("reporting/", views.list_view, name="reporting-list"),
]
