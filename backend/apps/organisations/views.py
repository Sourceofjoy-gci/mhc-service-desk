"""Placeholder views for organisations. Listing endpoints are gated by the
operational domain scope; only authorised offices are returned.
"""
from __future__ import annotations

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def offices(_request: Request) -> Response:
    return Response({"results": []})
