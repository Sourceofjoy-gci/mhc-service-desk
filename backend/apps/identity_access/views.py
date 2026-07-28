"""Identity endpoints — me, my scopes, my preferences.

The frontend only needs enough information to render role-aware navigation.
All enforcement happens on the actual data endpoints.
"""
from __future__ import annotations

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from .models import User


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request: Request) -> Response:
    user = request.user
    if not isinstance(user, User):
        raise TypeError("Authenticated identity must use the configured User model")
    payload = {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "mfa_enabled": user.mfa_enabled,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
    }
    return Response(payload)
