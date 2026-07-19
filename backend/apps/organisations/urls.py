from django.urls import path

from . import views

urlpatterns = [
    path("organisations/offices", views.offices, name="organisations-offices"),
]
