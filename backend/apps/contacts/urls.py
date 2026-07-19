"""URL configuration for the contacts app."""
from django.urls import path

from . import views

urlpatterns = [
    path("contacts/", views.list_view, name="contacts-list"),
]
