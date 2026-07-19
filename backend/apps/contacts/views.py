"""Contact API views."""
from __future__ import annotations

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.identity_access.authentication import KeycloakJWTAuthentication
from apps.identity_access.scope import ScopePermission

from .api import ContactCreateSerializer, ContactSerializer
from .models import Contact


class ContactViewSet(viewsets.ModelViewSet):
    queryset = Contact.objects.all()
    serializer_class = ContactSerializer
    authentication_classes = [KeycloakJWTAuthentication]
    permission_classes = [IsAuthenticated, ScopePermission]

    def get_serializer_class(self):
        if self.action == "create":
            return ContactCreateSerializer
        return ContactSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if "search" in params:
            from django.db.models import Q
            term = params["search"]
            qs = qs.filter(
                Q(full_name__icontains=term)
                | Q(email__icontains=term)
                | Q(phone_e164__icontains=term)
            )
        return qs.order_by("full_name")[:100]

    @action(detail=False, methods=["get"], url_path="duplicates")
    def duplicates(self, request):
        """Suggest possible duplicate contacts (FR-007) without merging."""
        from django.db.models import Q
        params = request.query_params
        email = params.get("email", "").strip()
        phone = params.get("phone", "").strip()
        name = params.get("name", "").strip()
        qs = Contact.objects.none()
        if email:
            qs = qs | Contact.objects.filter(email__iexact=email)
        if phone:
            qs = qs | Contact.objects.filter(phone_e164=phone)
        if name:
            qs = qs | Contact.objects.filter(full_name__icontains=name)
        return Response({"results": ContactSerializer(qs.distinct()[:10], many=True).data})
