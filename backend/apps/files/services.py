"""File service — ClamAV scan + MinIO upload + signed URL."""
from __future__ import annotations

import hashlib
import io
import logging
import socket
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol, TypedDict, Unpack
from urllib.parse import urlparse

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.tickets.events import record_ticket_event
from apps.tickets.models import Ticket, TicketMessage

from .models import Attachment, AttachmentAccessLog

logger = logging.getLogger(__name__)

CLAMAV_STREAM_CHUNK_SIZE = 64 * 1024


class _PutObjectArguments(TypedDict):
    Bucket: str
    Key: str
    Body: bytes
    ContentType: str
    IfNoneMatch: str


class _PutObjectResult(TypedDict, total=False):
    ETag: str
    VersionId: str


class _DeleteObjectArguments(TypedDict):
    Bucket: str
    Key: str
    VersionId: str


class _PresignArguments(TypedDict):
    Params: dict[str, str]
    ExpiresIn: int


class _S3Client(Protocol):
    def put_object(self, **kwargs: Unpack[_PutObjectArguments]) -> _PutObjectResult: ...

    def delete_object(self, **kwargs: Unpack[_DeleteObjectArguments]) -> object: ...

    def generate_presigned_url(
        self,
        client_method: str,
        /,
        **kwargs: Unpack[_PresignArguments],
    ) -> str: ...


@dataclass(frozen=True)
class StoredObject:
    """Ownership proof returned by a successful conditional object creation."""

    bucket: str
    key: str
    etag: str
    version_id: str


def _s3_client() -> _S3Client:
    """Build a fresh S3 client. The endpoint is the internal MinIO URL."""
    endpoint = settings.AWS_S3_ENDPOINT_URL
    client: _S3Client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(signature_version=settings.AWS_S3_SIGNATURE_VERSION or "s3v4"),
    )
    return client


def scan_with_clamav(data: bytes) -> tuple[str, str | None]:
    """Submit ``data`` to ClamAV over the INSTREAM protocol.

    Returns (status, signature). status is one of "clean", "infected", "error".
    In dev / when ClamAV is unreachable we treat it as a soft pass and log
    the failure (the operator must monitor this).
    """
    host = getattr(settings, "CLAMAV_HOST", "clamav")
    port = int(getattr(settings, "CLAMAV_PORT", 3310))
    try:
        with socket.create_connection((host, port), timeout=5) as s:
            s.sendall(b"zINSTREAM\0")
            for offset in range(0, len(data), CLAMAV_STREAM_CHUNK_SIZE):
                chunk = data[offset : offset + CLAMAV_STREAM_CHUNK_SIZE]
                s.sendall(len(chunk).to_bytes(4, "big") + chunk)
            s.sendall(b"\0\0\0\0")
            response = b""
            while True:
                buf = s.recv(4096)
                if not buf:
                    break
                response += buf
                if b"\0" in buf:
                    break
            text = response.replace(b"\x00", b"").decode("utf-8", errors="ignore").strip()
            if "FOUND" in text:
                sig = text.split("FOUND")[0].strip().split(":")[-1].strip()
                return "infected", sig
            if "OK" in text or "stream: OK" in text:
                return "clean", None
            return "error", text
    except Exception as exc:  # pragma: no cover
        logger.warning("clamav_scan_failed", extra={"error": str(exc)})
        return "error", str(exc)


def upload_to_minio(
    *,
    key: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    bucket: str | None = None,
) -> StoredObject:
    bucket = bucket or settings.AWS_STORAGE_BUCKET_NAME
    client = _s3_client()
    result = client.put_object(
        Bucket=bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
        IfNoneMatch="*",
    )
    etag = result.get("ETag")
    if not etag:
        raise RuntimeError("Object storage did not return an ownership ETag.")
    version_id = result.get("VersionId")
    if not version_id:
        logger.error(
            "minio_put_missing_version_id",
            extra={"bucket": bucket, "key": key, "etag": etag},
        )
        raise RuntimeError("Object storage did not return an ownership VersionId.")
    return StoredObject(
        bucket=bucket,
        key=key,
        etag=etag,
        version_id=version_id,
    )


def delete_from_minio(*, stored_object: StoredObject) -> None:
    """Delete only the exact object version created by this request."""
    if not stored_object.version_id:
        logger.error(
            "minio_delete_missing_version_id",
            extra={
                "bucket": stored_object.bucket,
                "key": stored_object.key,
                "etag": stored_object.etag,
            },
        )
        raise RuntimeError("Stored object has no ownership VersionId.")
    client = _s3_client()
    arguments = _DeleteObjectArguments(
        Bucket=stored_object.bucket,
        Key=stored_object.key,
        VersionId=stored_object.version_id,
    )
    client.delete_object(**arguments)


def generate_signed_url(*, key: str, expires: int = 60) -> str:
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    client = _s3_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires,
    )


@transaction.atomic
def record_attachment(
    *,
    ticket: Ticket,
    message: TicketMessage | None,
    object_key: str,
    filename: str,
    content_type: str,
    size_bytes: int,
    checksum_sha256: str,
    scan_status: str,
    scan_signature: str,
    actor_subject: str,
    stored_object: StoredObject,
) -> Attachment:
    if stored_object.key != object_key:
        raise ValueError("Stored-object ownership key does not match attachment key.")
    if not stored_object.bucket or not stored_object.version_id:
        raise ValueError("Stored-object ownership metadata is incomplete.")
    attachment = Attachment.objects.create(
        ticket=ticket,
        message=message,
        object_key=object_key,
        object_bucket=stored_object.bucket,
        object_version_id=stored_object.version_id,
        object_etag=stored_object.etag,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        checksum_sha256=checksum_sha256,
        scan_status=scan_status,
        scan_signature=scan_signature or "",
        uploaded_by_subject=actor_subject,
        scanned_at=timezone.now() if scan_status != "pending" else None,
    )
    record_ticket_event(
        ticket=ticket,
        actor_subject=actor_subject,
        action="ticket.attachment.created",
        before={},
        after={
            "attachment_id": str(attachment.id),
            "filename": filename,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "scan_status": scan_status,
        },
        metadata={"message_id": str(message.id) if message else None},
    )
    return attachment


def log_attachment_access(
    *,
    attachment: Attachment,
    actor_subject: str,
    ip: str | None,
    user_agent: str,
) -> None:
    AttachmentAccessLog.objects.create(
        attachment=attachment,
        actor_subject=actor_subject,
        ip_address=ip,
        user_agent=user_agent[:512],
    )
