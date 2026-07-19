from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"contacts", views.ContactViewSet, basename="contacts")

urlpatterns = [
    path("", include(router.urls)),
    path("public/requester/<str:token>/", views.requester_status, name="requester-status"),
    path("public/requester/<str:token>/reply/", views.requester_reply, name="requester-reply"),
]
