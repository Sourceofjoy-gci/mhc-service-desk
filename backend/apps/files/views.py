"""Attachment upload, download (signed URL) and scan."""
from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from uuid import UUID

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.identity_access.authentication import KeycloakJWTAuthentication
from apps.identity_access.models import User
from apps.identity_access.scope import ScopePermission, scope_ticket_queryset
from apps.tickets.models import Ticket

from .models import Attachment
from .policy import (
    AttachmentValidationError,
    read_attachment_bounded,
    validate_attachment_metadata,
)
from .services import (
    delete_from_minio,
    generate_signed_url,
    log_attachment_access,
    record_attachment,
    scan_with_clamav,
    upload_to_minio,
)

logger = logging.getLogger(__name__)


def _authenticated_user(request: Request) -> User:
    if isinstance(request.user, User):
        return request.user
    raise PermissionDenied(
        detail="Authentication credentials were not provided.",
        code="not_authenticated",
    )


def _attachment_error(
    request: Request,
    *,
    code: str,
    detail: str,
    fields: Mapping[str, Sequence[str]],
    response_status: int,
) -> Response:
    return Response(
        {
            "code": code,
            "detail": detail,
            "fields": fields,
            "correlation_id": getattr(request, "correlation_id", ""),
        },
        status=response_status,
    )


def attachment_metadata(attachment: Attachment) -> dict[str, object]:
    """Return the stable attachment metadata shared by ticket read models."""
    return {
        "id": str(attachment.id),
        "filename": attachment.filename,
        "size_bytes": attachment.size_bytes,
        "content_type": attachment.content_type,
        "uploaded_by": attachment.uploaded_by_subject,
        "uploaded_at": attachment.uploaded_at.isoformat().replace("+00:00", "Z"),
        "scan_status": attachment.scan_status,
        "download_available": attachment.scan_status == Attachment.ScanStatus.CLEAN,
    }


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, ScopePermission])
def upload(request: Request, ticket_number: str) -> Response:
    """Upload one or more files for a ticket.

    Multipart form: files=...
    """
    ticket = get_object_or_404(
        scope_ticket_queryset(
            request.user,
            Ticket.objects.all(),
            request=request,
        ),
        number=ticket_number,
    )
    if request.method == "GET":
        return Response(
            {
                "results": [
                    attachment_metadata(attachment)
                    for attachment in ticket.attachments.all()
                ]
            }
        )

    files = request.FILES.getlist("files") or request.FILES.getlist("file")
    if not files:
        return _attachment_error(
            request,
            code="invalid_attachment",
            detail="Attachment upload is invalid.",
            fields={"files": ["Provide at least one file."]},
            response_status=status.HTTP_400_BAD_REQUEST,
        )

    validated_files = []
    for uploaded_file in files:
        try:
            filename, content_type = validate_attachment_metadata(
                filename=uploaded_file.name,
                content_type=uploaded_file.content_type,
                declared_size=uploaded_file.size,
            )
        except AttachmentValidationError as exc:
            return _attachment_error(
                request,
                code="invalid_attachment",
                detail="Attachment upload is invalid.",
                fields={"files": [str(exc)]},
                response_status=status.HTTP_400_BAD_REQUEST,
            )
        validated_files.append((uploaded_file, filename, content_type))

    actor = _authenticated_user(request).keycloak_subject
    created: list[dict[str, object]] = []
    for uploaded_file, filename, content_type in validated_files:
        try:
            data = read_attachment_bounded(uploaded_file)
        except AttachmentValidationError as exc:
            return _attachment_error(
                request,
                code="invalid_attachment",
                detail="Attachment upload is invalid.",
                fields={"files": [str(exc)]},
                response_status=status.HTTP_400_BAD_REQUEST,
            )
        checksum = __import__("hashlib").sha256(data).hexdigest()
        scan_status, signature = scan_with_clamav(data)
        if scan_status == "infected":
            object_key = f"quarantine/{ticket.number}/{uuid.uuid4().hex}-{filename}"
        else:
            object_key = f"attachments/{ticket.number}/{uuid.uuid4().hex}-{filename}"
        try:
            upload_to_minio(
                key=object_key,
                data=data,
                content_type=content_type,
            )
        except Exception:  # pragma: no cover
            logger.exception("minio_upload_failed")
            return _attachment_error(
                request,
                code="attachment_upload_failed",
                detail="Attachment upload failed.",
                fields={},
                response_status=status.HTTP_502_BAD_GATEWAY,
            )
        try:
            att = record_attachment(
                ticket=ticket,
                message=None,
                object_key=object_key,
                filename=filename,
                content_type=content_type,
                size_bytes=len(data),
                checksum_sha256=checksum,
                scan_status=scan_status,
                scan_signature=signature or "",
                actor_subject=actor,
            )
        except Exception:
            logger.exception("attachment_persistence_failed")
            try:
                delete_from_minio(key=object_key)
            except Exception:
                logger.exception("attachment_cleanup_failed")
            return _attachment_error(
                request,
                code="attachment_persistence_failed",
                detail="Attachment metadata could not be saved.",
                fields={},
                response_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        metadata = attachment_metadata(att)
        metadata["scan_signature"] = att.scan_signature
        created.append(metadata)
    return Response({"results": created}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated, ScopePermission])
def download(request: Request, attachment_id: UUID) -> Response:
    """Return a short-lived signed download URL (FR-095)."""
    scoped_tickets = scope_ticket_queryset(
        request.user,
        Ticket.objects.all(),
        request=request,
    )
    att = get_object_or_404(
        Attachment.objects.select_related("ticket").filter(ticket__in=scoped_tickets),
        id=attachment_id,
    )
    if att.scan_status != Attachment.ScanStatus.CLEAN:
        raise PermissionDenied(
            detail="Attachment is not available for download.",
            code="attachment_unavailable",
        )
    log_attachment_access(
        attachment=att,
        actor_subject=_authenticated_user(request).keycloak_subject,
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
