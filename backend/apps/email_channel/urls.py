from django.urls import path

from . import views

urlpatterns = [
    path("integrations/email/events/", views.inbound_email, name="email-inbound"),
    path("integrations/email/bounce/", views.outbound_bounce, name="email-bounce"),
]
