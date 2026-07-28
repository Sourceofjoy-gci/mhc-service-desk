"""Placeholder API views for this app."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_view(_request: Request) -> Response:
    return Response({"results": []})
