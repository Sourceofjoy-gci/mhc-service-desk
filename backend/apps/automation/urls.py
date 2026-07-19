from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"automation/rules", views.AutomationRuleViewSet, basename="automation-rule")

urlpatterns = [path("", include(router.urls))]
