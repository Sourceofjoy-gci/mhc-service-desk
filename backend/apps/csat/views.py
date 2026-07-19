"""CSAT public survey endpoint."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from .models import CsatResponse


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@api_view(["POST"])
@permission_classes([AllowAny])
def submit_csat(request, token: str):
    h = _hash(token)
    try:
        csat = CsatResponse.objects.get(survey_token_hash=h)
    except CsatResponse.DoesNotExist:
        return Response({"detail": "invalid"}, status=status.HTTP_404_NOT_FOUND)
    if csat.submitted_at is not None:
        return Response({"detail": "already submitted"}, status=status.HTTP_409_CONFLICT)
    rating = request.data.get("rating") if request.data else None
    if not isinstance(rating, int) or not (1 <= rating <= 5):
        return Response({"detail": "rating must be 1..5"}, status=status.HTTP_400_BAD_REQUEST)
    csat.rating = rating
    csat.comment = (request.data.get("comment") or "")[:4000]
    csat.submitted_at = datetime.now(tz=timezone.utc)
    csat.save(update_fields=["rating", "comment", "submitted_at"])
    return Response({"status": "thanks"})
