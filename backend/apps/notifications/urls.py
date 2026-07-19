"""URL configuration for the notifications app."""
from django.urls import path

from . import views

urlpatterns = [
    path("notifications/", views.list_view, name="notifications-list"),
]
