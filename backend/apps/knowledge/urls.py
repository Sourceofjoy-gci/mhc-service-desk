from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"knowledge/articles", views.KnowledgeArticleViewSet, basename="knowledge-article")

urlpatterns = [
    path("public/knowledge/", views.public_search, name="public-knowledge"),
    path("", include(router.urls)),
]
