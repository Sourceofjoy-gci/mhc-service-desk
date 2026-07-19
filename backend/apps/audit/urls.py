from django.urls import path

from . import views

urlpatterns = [
    path("audit/", views.list_view, name="audit-list"),
]
