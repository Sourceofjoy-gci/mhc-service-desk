"""URL configuration for the catalogue app."""
from django.urls import path

from . import views

urlpatterns = [
    path("catalogue/", views.list_view, name="catalogue-list"),
]
