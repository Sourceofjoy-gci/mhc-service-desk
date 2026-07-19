from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"catalogue/services", views.ServiceViewSet, basename="services")

urlpatterns = [path("", include(router.urls))]
