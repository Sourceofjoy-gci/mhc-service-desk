"""Attachment upload, download (signed URL) and scan."""
from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.identity_access.authentication import KeycloakJWTAuthentication
from apps.identity_access.models import User
from apps.identity_access.scope import (
    ScopePermission,
    get_authority_snapshot,
    scope_ticket_queryset,
)
from apps.tickets.models import Ticket
from apps.tickets.permissions import can_add_ticket_content

from .models import Attachment
from .policy import (
    MAX_ATTACHMENT_BATCH_SIZE_BYTES,
    MAX_ATTACHMENT_COUNT,
    AttachmentValidationError,
    read_attachment_bounded,
    validate_attachment_content,
    validate_attachment_metadata,
)
from .services import (
    StoredObject,
    delete_from_minio,
    generate_signed_url,
    log_attachment_access,
    record_attachment,
    scan_with_clamav,
    upload_to_minio,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PreparedAttachment:
    filename: str
    content_type: str
    data: bytes
    checksum_sha256: str
    scan_status: str
    scan_signature: str
    object_key: str


class _AttachmentStorageError(Exception):
    """Raised so storage failures exit and roll back the locked DB transaction."""


def _cleanup_stored_objects(stored_objects: Sequence[StoredObject]) -> None:
    for stored_object in reversed(stored_objects):
        try:
            delete_from_minio(stored_object=stored_object)
        except Exception:
            logger.exception("attachment_cleanup_failed")


def _authenticated_user(request: Request) -> User:
    if isinstance(request.user, User):
        return request.user
    raise PermissionDenied(
        detail="Authentication credentials were not provided.",
        code="not_authenticated",
    )


def _reload_actor_authority(actor: User) -> User:
    """Reload durable authority so the locked write does not trust stale claims."""
    fresh_actor = User.objects.get(pk=actor.pk)
    durable_groups = [
        group
        for group in (fresh_actor.keycloak_groups or [])
        if isinstance(group, str)
    ]
    durable_groups.extend(fresh_actor.groups.values_list("name", flat=True))
    vars(fresh_actor)["_groups"] = durable_groups
    return fresh_actor


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

    actor = _authenticated_user(request)
    if not can_add_ticket_content(actor, ticket, request=request):
        raise PermissionDenied(
            detail="You cannot perform this ticket action.",
            code="ticket_action_forbidden",
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
    if len(files) > MAX_ATTACHMENT_COUNT:
        return _attachment_error(
            request,
            code="invalid_attachment",
            detail="Attachment upload is invalid.",
            fields={"files": ["Upload at most 10 files at a time."]},
            response_status=status.HTTP_400_BAD_REQUEST,
        )

    validated_files = []
    declared_batch_size = 0
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
        declared_batch_size += uploaded_file.size
        if declared_batch_size > MAX_ATTACHMENT_BATCH_SIZE_BYTES:
            return _attachment_error(
                request,
                code="invalid_attachment",
                detail="Attachment upload is invalid.",
                fields={"files": ["Combined files must be 20 MiB or smaller."]},
                response_status=status.HTTP_400_BAD_REQUEST,
            )
        validated_files.append((uploaded_file, filename, content_type))

    validated_content: list[tuple[str, str, bytes]] = []
    actual_batch_size = 0
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
        actual_batch_size += len(data)
        if actual_batch_size > MAX_ATTACHMENT_BATCH_SIZE_BYTES:
            return _attachment_error(
                request,
                code="invalid_attachment",
                detail="Attachment upload is invalid.",
                fields={"files": ["Combined files must be 20 MiB or smaller."]},
                response_status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            validate_attachment_content(data=data, content_type=content_type)
        except AttachmentValidationError as exc:
            return _attachment_error(
                request,
                code="invalid_attachment",
                detail="Attachment upload is invalid.",
                fields={"files": [str(exc)]},
                response_status=status.HTTP_400_BAD_REQUEST,
            )
        validated_content.append((filename, content_type, data))

    stored_objects: list[StoredObject] = []
    attachments: list[Attachment] = []
    try:
        with transaction.atomic():
            fresh_actor = _reload_actor_authority(actor)
            fresh_authority = get_authority_snapshot(fresh_actor, request=request)
            locked_ticket = get_object_or_404(
                scope_ticket_queryset(
                    fresh_actor,
                    Ticket.objects.select_for_update(of=("self",)),
                    request=request,
                    snapshot=fresh_authority,
                ),
                id=ticket.id,
            )
            if not can_add_ticket_content(
                fresh_actor,
                locked_ticket,
                request=request,
            ):
                raise PermissionDenied(
                    detail="You cannot perform this ticket action.",
                    code="ticket_action_forbidden",
                )

            prepared: list[_PreparedAttachment] = []
            for filename, content_type, data in validated_content:
                scan_status, signature = scan_with_clamav(data)
                if scan_status == "infected":
                    object_key = (
                        f"quarantine/{locked_ticket.number}/{uuid.uuid4().hex}"
                    )
                else:
                    object_key = (
                        f"attachments/{locked_ticket.number}/{uuid.uuid4().hex}"
                    )
                prepared.append(
                    _PreparedAttachment(
                        filename=filename,
                        content_type=content_type,
                        data=data,
                        checksum_sha256=__import__("hashlib")
                        .sha256(data)
                        .hexdigest(),
                        scan_status=scan_status,
                        scan_signature=signature or "",
                        object_key=object_key,
                    )
                )

            try:
                for item in prepared:
                    stored_objects.append(
                        upload_to_minio(
                            key=item.object_key,
                            data=item.data,
                            content_type=item.content_type,
                        )
                    )
            except Exception as exc:
                raise _AttachmentStorageError from exc

            for item, stored_object in zip(prepared, stored_objects, strict=True):
                attachments.append(
                    record_attachment(
                        ticket=locked_ticket,
                        message=None,
                        object_key=item.object_key,
                        filename=item.filename,
                        content_type=item.content_type,
                        size_bytes=len(item.data),
                        checksum_sha256=item.checksum_sha256,
                        scan_status=item.scan_status,
                        scan_signature=item.scan_signature,
                        actor_subject=fresh_actor.keycloak_subject,
                        stored_object=stored_object,
                    )
                )
    except _AttachmentStorageError:
        logger.exception("minio_upload_failed")
        _cleanup_stored_objects(stored_objects)
        return _attachment_error(
            request,
            code="attachment_upload_failed",
            detail="Attachment upload failed.",
            fields={},
            response_status=status.HTTP_502_BAD_GATEWAY,
        )
    except (Http404, PermissionDenied):
        raise
    except Exception:
        logger.exception("attachment_persistence_failed")
        _cleanup_stored_objects(stored_objects)
        return _attachment_error(
            request,
            code="attachment_persistence_failed",
            detail="Attachment metadata could not be saved.",
            fields={},
            response_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    created: list[dict[str, object]] = []
    for attachment in attachments:
        metadata = attachment_metadata(attachment)
        metadata["scan_signature"] = attachment.scan_signature
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
