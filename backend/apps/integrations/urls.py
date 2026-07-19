from django.urls import path

from . import views

urlpatterns = [
    path("tickets/<str:ticket_number>/validate-matter/", views.validate_matter, name="validate-matter"),
]
