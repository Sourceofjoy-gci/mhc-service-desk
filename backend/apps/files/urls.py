"""URL configuration for the files app."""
from django.urls import path

from . import views

urlpatterns = [
    path("files/", views.list_view, name="files-list"),
]
