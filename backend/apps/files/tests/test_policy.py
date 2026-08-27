"""Adversarial attachment policy tests."""

from __future__ import annotations

import pytest

from apps.files import policy


@pytest.mark.parametrize(
    ("filename", "content_type", "data"),
    [
        ("empty.pdf", "application/pdf", b""),
        ("forged.pdf", "application/pdf", b"MZ\x90\x00not-a-pdf"),
    ],
)
def test_attachment_content_rejects_empty_and_forged_pdf_bytes(
    filename: str,
    content_type: str,
    data: bytes,
) -> None:
    """Catch trusting client metadata without verifying the uploaded bytes."""
    _, normalized_type = policy.validate_attachment_metadata(
        filename=filename,
        content_type=content_type,
        declared_size=len(data),
    )

    with pytest.raises(policy.AttachmentValidationError):
        policy.validate_attachment_content(data=data, content_type=normalized_type)


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        (
            "document.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        ("notes.txt", "text/plain"),
    ],
)
def test_attachment_metadata_fails_closed_for_types_without_strong_signatures(
    filename: str,
    content_type: str,
) -> None:
    """Catch reintroducing formats this boundary cannot identify reliably."""
    with pytest.raises(
        policy.AttachmentValidationError,
        match="File type and extension are not allowed",
    ):
        policy.validate_attachment_metadata(
            filename=filename,
            content_type=content_type,
            declared_size=100,
        )


@pytest.mark.parametrize(
    ("filename", "content_type", "data"),
    [
        ("evidence.pdf", "application/pdf", b"%PDF-1.7\n"),
        ("photo.jpg", "image/jpeg", b"\xff\xd8\xff\xe0photo"),
        (
            "capture.png",
            "image/png",
            b"\x89PNG\r\n\x1a\nimage",
        ),
    ],
)
def test_attachment_content_accepts_only_a_matching_audited_signature(
    filename: str,
    content_type: str,
    data: bytes,
) -> None:
    _, normalized_type = policy.validate_attachment_metadata(
        filename=filename,
        content_type=content_type,
        declared_size=len(data),
    )

    policy.validate_attachment_content(data=data, content_type=normalized_type)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("folder/evidence.pdf", "evidence.pdf"),
        (r"folder\evidence.pdf", "evidence.pdf"),
        (r"folder/subfolder\evidence.pdf", "evidence.pdf"),
    ],
)
def test_attachment_filename_normalizes_both_path_separator_styles(
    filename: str,
    expected: str,
) -> None:
    safe_filename, _ = policy.validate_attachment_metadata(
        filename=filename,
        content_type="application/pdf",
        declared_size=100,
    )

    assert safe_filename == expected


@pytest.mark.parametrize(
    "filename",
    ["\x00evidence.pdf", "evidence\x1f.pdf", "folder/", ".pdf"],
)
def test_attachment_filename_rejects_control_and_unsafe_names(filename: str) -> None:
    with pytest.raises(
        policy.AttachmentValidationError,
        match="File name is not allowed",
    ):
        policy.validate_attachment_metadata(
            filename=filename,
            content_type="application/pdf",
            declared_size=100,
        )
