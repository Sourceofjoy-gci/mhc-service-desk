"""Central attachment intake policy and bounded upload reading.

The 20 MiB file ceiling intentionally sits below Django's 25 MiB request-body
ceiling so multipart overhead cannot turn a policy-valid upload into a parser
failure. Keeping this policy in the files app makes the fail-closed defaults
explicit; a later governed configuration feature can expose these values
without coupling validation to Django's request parser.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

MAX_ATTACHMENT_SIZE_BYTES = 20 * 1024 * 1024
UPLOAD_READ_CHUNK_SIZE = 64 * 1024

ALLOWED_ATTACHMENT_TYPES: dict[str, frozenset[str]] = {
    "application/msword": frozenset({".doc"}),
    "application/pdf": frozenset({".pdf"}),
    "application/vnd.ms-excel": frozenset({".xls"}),
    "application/vnd.ms-powerpoint": frozenset({".ppt"}),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        frozenset({".pptx"})
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        frozenset({".xlsx"})
    ),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        frozenset({".docx"})
    ),
    "image/jpeg": frozenset({".jpeg", ".jpg"}),
    "image/png": frozenset({".png"}),
    "text/csv": frozenset({".csv"}),
    "text/plain": frozenset({".txt"}),
}


class AttachmentValidationError(ValueError):
    """Raised when an upload violates the attachment intake policy."""


class ChunkedUpload(Protocol):
    """The narrow part of Django's UploadedFile contract used by this app."""

    def chunks(self, chunk_size: int | None = None) -> Iterator[bytes]: ...


def validate_attachment_metadata(
    *,
    filename: str,
    content_type: str | None,
    declared_size: int,
) -> tuple[str, str]:
    """Validate metadata and return a safe basename plus normalized media type."""
    safe_filename = Path(filename).name
    normalized_type = (content_type or "").partition(";")[0].strip().lower()
    allowed_extensions = ALLOWED_ATTACHMENT_TYPES.get(normalized_type)
    extension = Path(safe_filename).suffix.lower()
    if not allowed_extensions or extension not in allowed_extensions:
        raise AttachmentValidationError("File type and extension are not allowed.")
    if declared_size > MAX_ATTACHMENT_SIZE_BYTES:
        raise AttachmentValidationError("Each file must be 20 MiB or smaller.")
    return safe_filename, normalized_type


def read_attachment_bounded(upload: ChunkedUpload) -> bytes:
    """Read through Django's chunk iterator, never accepting more than the cap."""
    parts: list[bytes] = []
    total = 0
    for chunk in upload.chunks(chunk_size=UPLOAD_READ_CHUNK_SIZE):
        total += len(chunk)
        if total > MAX_ATTACHMENT_SIZE_BYTES:
            raise AttachmentValidationError("Each file must be 20 MiB or smaller.")
        parts.append(chunk)
    return b"".join(parts)
