from django.urls import path

from . import views

urlpatterns = [
    path("tickets/<str:ticket_number>/attachments/", views.upload, name="ticket-attachments"),
    path("attachments/<uuid:attachment_id>/download/", views.download, name="attachment-download"),
]
