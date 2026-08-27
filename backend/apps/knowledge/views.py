"""Knowledge API — public + agent views."""

from __future__ import annotations

from rest_framework import serializers, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.identity_access.authentication import KeycloakJWTAuthentication
from apps.identity_access.scope import ScopePermission

from .models import KnowledgeArticle


class KnowledgeArticleViewSet(viewsets.ModelViewSet[KnowledgeArticle]):
    queryset = KnowledgeArticle.objects.all()
    authentication_classes = [KeycloakJWTAuthentication]
    permission_classes = [IsAuthenticated, ScopePermission]

    def get_serializer_class(
        self,
    ) -> type[serializers.ModelSerializer[KnowledgeArticle]]:
        class _S(serializers.ModelSerializer[KnowledgeArticle]):
            class Meta:
                model = KnowledgeArticle
                fields = (
                    "id",
                    "code",
                    "title",
                    "body",
                    "audience",
                    "status",
                    "domain",
                    "language",
                    "version",
                    "owner_subject",
                    "approved_by_subject",
                    "last_reviewed_at",
                    "next_review_at",
                    "created_at",
                    "updated_at",
                )
                read_only_fields = ("id", "version", "created_at", "updated_at")

        return _S


@api_view(["GET"])
@permission_classes([AllowAny])
def public_search(request: Request) -> Response:
    """Public knowledge search (FR-078). Returns published public articles only."""
    from django.db.models import Q

    term = request.query_params.get("q", "").strip()
    qs = KnowledgeArticle.objects.filter(audience="public", status="published")
    if term:
        qs = qs.filter(Q(title__icontains=term) | Q(body__icontains=term))
    items = [
        {
            "id": str(a.id),
            "code": a.code,
            "title": a.title,
            "language": a.language,
            "excerpt": a.body[:300],
        }
        for a in qs[:50]
    ]
    return Response({"results": items})
