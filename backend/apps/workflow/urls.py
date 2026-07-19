"""URL configuration for the workflow app."""
from django.urls import path

from . import views

urlpatterns = [
    path("workflow/", views.list_view, name="workflow-list"),
]
