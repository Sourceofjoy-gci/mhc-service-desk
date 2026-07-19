"""Attachment upload, download (signed URL) and scan."""
from __future__ import annotations

import logging
import uuid

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.identity_access.authentication import KeycloakJWTAuthentication
from apps.identity_access.scope import ScopePermission
from apps.tickets.models import Ticket

from .models import Attachment
from .services import (
    generate_signed_url,
    log_attachment_access,
    record_attachment,
    scan_with_clamav,
    upload_to_minio,
)

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([IsAuthenticated, ScopePermission])
def upload(request, ticket_number):
    """Upload one or more files for a ticket.

    Multipart form: files=...
    """
    try:
        ticket = Ticket.objects.get(number=ticket_number)
    except Ticket.DoesNotExist:
        return Response({"detail": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)

    files = request.FILES.getlist("files") or request.FILES.getlist("file")
    if not files:
        return Response({"detail": "No files provided"}, status=status.HTTP_400_BAD_REQUEST)

    actor = request.user.keycloak_subject
    created = []
    for f in files:
        data = f.read()
        checksum = __import__("hashlib").sha256(data).hexdigest()
        scan_status, signature = scan_with_clamav(data)
        if scan_status == "infected":
            object_key = f"quarantine/{ticket.number}/{uuid.uuid4().hex}-{f.name}"
        else:
            object_key = f"attachments/{ticket.number}/{uuid.uuid4().hex}-{f.name}"
        try:
            upload_to_minio(
                key=object_key,
                data=data,
                content_type=f.content_type or "application/octet-stream",
            )
        except Exception as exc:  # pragma: no cover
            logger.exception("minio_upload_failed")
            return Response({"detail": f"Upload failed: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)
        att = record_attachment(
            ticket=ticket,
            message=None,
            object_key=object_key,
            filename=f.name,
            content_type=f.content_type or "application/octet-stream",
            size_bytes=len(data),
            checksum_sha256=checksum,
            scan_status=scan_status,
            scan_signature=signature or "",
            uploaded_by_subject=actor,
        )
        created.append({
            "id": str(att.id),
            "filename": att.filename,
            "size_bytes": att.size_bytes,
            "scan_status": att.scan_status,
            "scan_signature": att.scan_signature,
        })
    return Response({"results": created}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated, ScopePermission])
def download(request, attachment_id):
    """Return a short-lived signed download URL (FR-095)."""
    try:
        att = Attachment.objects.get(id=attachment_id)
    except Attachment.DoesNotExist:
        return Response({"detail": "Attachment not found"}, status=status.HTTP_404_NOT_FOUND)
    if att.scan_status == "infected":
        return Response({"detail": "Attachment is quarantined"}, status=status.HTTP_403_FORBIDDEN)
    log_attachment_access(
        attachment=att,
        actor_subject=request.user.keycloak_subject,
        ip=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )
    url = generate_signed_url(key=att.object_key)
    return Response({
        "url": url,
        "filename": att.filename,
        "size_bytes": att.size_bytes,
        "content_type": att.content_type,
        "expires_in": 60,
    })
