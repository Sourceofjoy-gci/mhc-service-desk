"""URL configuration for the administration app."""
from django.urls import path

from . import views

urlpatterns = [
    path("administration/", views.list_view, name="administration-list"),
]
