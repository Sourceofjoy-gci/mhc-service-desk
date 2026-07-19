from django.urls import path

from . import views

urlpatterns = [
    path("integrations/whatsapp/webhook/", views.inbound_webhook, name="whatsapp-webhook"),
    path("integrations/whatsapp/templates/", views.list_templates, name="whatsapp-templates"),
    path("integrations/whatsapp/send/", views.send_text, name="whatsapp-send"),
]
