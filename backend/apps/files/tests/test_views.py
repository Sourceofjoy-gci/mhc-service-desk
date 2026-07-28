"""Scoped attachment collection and download API tests."""
from __future__ import annotations

from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient

from apps.files.models import Attachment, AttachmentAccessLog
from apps.identity_access.models import User
from apps.tickets.models import Ticket
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db


def _user(groups):
    user = User.objects.create(
        username=f"user-{uuid4().hex}",
        keycloak_subject=f"subject-{uuid4().hex}",
        display_name="Attachment User",
        keycloak_groups=groups,
    )
    user._groups = groups
    return user


def _ticket(basic_world, *, domain="operational", confidentiality="normal"):
    service = (
        basic_world["gen_info"] if domain == "operational" else basic_world["it_inc"]
    )
    return Ticket.objects.create(
        number=f"{domain[:2].upper()}-202607-{Ticket.objects.count() + 994001:06d}",
        domain=domain,
        title="Attachment scope",
        status=Status.objects.get(domain=domain, code="in_progress"),
        channel="web",
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
        confidentiality=confidentiality,
    )


def _attachment(ticket, *, scan_status="clean"):
    return Attachment.objects.create(
        ticket=ticket,
        object_key=f"attachments/{uuid4().hex}",
        filename="evidence.pdf",
        content_type="application/pdf",
        size_bytes=4321,
        checksum_sha256="c" * 64,
        scan_status=scan_status,
        uploaded_by_subject="uploader-1",
    )


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_attachment_get_returns_complete_metadata_and_clean_availability(basic_world):
    ticket = _ticket(basic_world)
    clean = _attachment(ticket, scan_status="clean")
    pending = _attachment(ticket, scan_status="pending")
    response = _client(_user(["ops-agents"])).get(
        reverse("ticket-attachments", args=[ticket.number])
    )

    assert response.status_code == 200
    by_id = {item["id"]: item for item in response.data["results"]}
    assert by_id[str(clean.id)] == {
        "id": str(clean.id),
        "filename": "evidence.pdf",
        "size_bytes": 4321,
        "content_type": "application/pdf",
        "uploaded_by": "uploader-1",
        "uploaded_at": clean.uploaded_at.isoformat().replace("+00:00", "Z"),
        "scan_status": "clean",
        "download_available": True,
    }
    assert by_id[str(pending.id)]["download_available"] is False


def test_attachment_post_returns_common_metadata_and_preserves_legacy_signature(
    basic_world,
    monkeypatch,
):
    ticket = _ticket(basic_world)
    monkeypatch.setattr(
        "apps.files.views.scan_with_clamav",
        lambda _data: ("clean", "verified-signature"),
    )
    monkeypatch.setattr("apps.files.views.upload_to_minio", lambda **_kwargs: None)

    response = _client(_user(["ops-agents"])).post(
        reverse("ticket-attachments", args=[ticket.number]),
        {
            "files": [
                SimpleUploadedFile(
                    "proof.txt",
                    b"proof",
                    content_type="text/plain",
                )
            ]
        },
        format="multipart",
    )

    assert response.status_code == 201
    metadata = response.data["results"][0]
    assert metadata["filename"] == "proof.txt"
    assert metadata["content_type"] == "text/plain"
    assert metadata["size_bytes"] == 5
    assert metadata["scan_status"] == "clean"
    assert metadata["download_available"] is True
    assert metadata["scan_signature"] == "verified-signature"
    assert Attachment.objects.filter(ticket=ticket, filename="proof.txt").exists()


def test_attachment_post_validation_uses_common_error_contract(basic_world):
    ticket = _ticket(basic_world)

    response = _client(_user(["ops-agents"])).post(
        reverse("ticket-attachments", args=[ticket.number]),
        {},
        format="multipart",
        HTTP_X_CORRELATION_ID="attachment-correlation",
    )

    assert response.status_code == 400
    assert response.data == {
        "code": "invalid_attachment",
        "detail": "Attachment upload is invalid.",
        "fields": {"files": ["Provide at least one file."]},
        "correlation_id": "attachment-correlation",
    }


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("payload.exe", "application/pdf"),
        ("evidence.pdf", "text/plain"),
        ("evidence.pdf", "application/x-msdownload"),
    ],
)
def test_attachment_post_rejects_disallowed_type_extension_pairs_before_storage(
    basic_world,
    monkeypatch,
    filename,
    content_type,
):
    ticket = _ticket(basic_world)
    monkeypatch.setattr(
        "apps.files.views.scan_with_clamav",
        lambda _data: pytest.fail("disallowed attachment was scanned"),
    )
    monkeypatch.setattr(
        "apps.files.views.upload_to_minio",
        lambda **_kwargs: pytest.fail("disallowed attachment reached storage"),
    )

    response = _client(_user(["ops-agents"])).post(
        reverse("ticket-attachments", args=[ticket.number]),
        {
            "files": [
                SimpleUploadedFile(filename, b"payload", content_type=content_type)
            ]
        },
        format="multipart",
    )

    assert response.status_code == 400
    assert response.data["code"] == "invalid_attachment"
    assert response.data["fields"] == {
        "files": ["File type and extension are not allowed."]
    }
    assert not Attachment.objects.filter(ticket=ticket).exists()


def test_attachment_post_rejects_a_file_over_twenty_mebibytes_before_storage(
    basic_world,
    monkeypatch,
):
    ticket = _ticket(basic_world)
    monkeypatch.setattr(
        "apps.files.views.scan_with_clamav",
        lambda _data: pytest.fail("oversized attachment was scanned"),
    )
    monkeypatch.setattr(
        "apps.files.views.upload_to_minio",
        lambda **_kwargs: pytest.fail("oversized attachment reached storage"),
    )
    oversized = SimpleUploadedFile(
        "evidence.pdf",
        b"x" * (20 * 1024 * 1024 + 1),
        content_type="application/pdf",
    )

    response = _client(_user(["ops-agents"])).post(
        reverse("ticket-attachments", args=[ticket.number]),
        {"files": [oversized]},
        format="multipart",
    )

    assert response.status_code == 400
    assert response.data["code"] == "invalid_attachment"
    assert response.data["fields"] == {
        "files": ["Each file must be 20 MiB or smaller."]
    }
    assert not Attachment.objects.filter(ticket=ticket).exists()


def test_attachment_post_deletes_stored_object_when_event_persistence_rolls_back(
    basic_world,
    monkeypatch,
):
    """Catch a storage orphan when the transactional DB/event write fails."""
    ticket = _ticket(basic_world)
    stored: list[str] = []
    deleted: list[str] = []
    monkeypatch.setattr(
        "apps.files.views.scan_with_clamav",
        lambda _data: ("clean", None),
    )
    monkeypatch.setattr(
        "apps.files.views.upload_to_minio",
        lambda *, key, **_kwargs: stored.append(key),
    )
    monkeypatch.setattr(
        "apps.files.views.delete_from_minio",
        lambda *, key, **_kwargs: deleted.append(key),
        raising=False,
    )
    monkeypatch.setattr(
        "apps.files.services.record_ticket_event",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("event write failed")),
    )
    client = _client(_user(["ops-agents"]))
    client.raise_request_exception = False

    response = client.post(
        reverse("ticket-attachments", args=[ticket.number]),
        {
            "files": [
                SimpleUploadedFile(
                    "evidence.pdf",
                    b"%PDF-1.7 evidence",
                    content_type="application/pdf",
                )
            ]
        },
        format="multipart",
    )

    assert response.status_code == 500
    assert response.data["code"] == "attachment_persistence_failed"
    assert len(stored) == 1
    assert deleted == stored
    assert not Attachment.objects.filter(ticket=ticket).exists()


@pytest.mark.parametrize("scan_status", ["pending", "infected", "error"])
def test_only_clean_attachments_can_be_downloaded(
    basic_world,
    scan_status,
    monkeypatch,
):
    ticket = _ticket(basic_world)
    attachment = _attachment(ticket, scan_status=scan_status)
    monkeypatch.setattr(
        "apps.files.views.generate_signed_url",
        lambda **_kwargs: pytest.fail("unsafe signed URL generated"),
    )

    response = _client(_user(["ops-agents"])).get(
        reverse("attachment-download", args=[attachment.id])
    )

    assert response.status_code == 403
    assert not AttachmentAccessLog.objects.filter(attachment=attachment).exists()


@pytest.mark.parametrize(
    ("actor_groups", "ticket_domain"),
    [
        (["ops-agents"], "it"),
        (["it-agents"], "operational"),
    ],
)
def test_cross_domain_users_cannot_list_upload_or_download(
    basic_world,
    actor_groups,
    ticket_domain,
    monkeypatch,
):
    ticket = _ticket(basic_world, domain=ticket_domain)
    attachment = _attachment(ticket)
    client = _client(_user(actor_groups))
    monkeypatch.setattr(
        "apps.files.views.generate_signed_url",
        lambda **_kwargs: pytest.fail("out-of-scope signed URL generated"),
    )
    uploaded = SimpleUploadedFile("probe.txt", b"probe", content_type="text/plain")

    listed = client.get(reverse("ticket-attachments", args=[ticket.number]))
    posted = client.post(
        reverse("ticket-attachments", args=[ticket.number]),
        {"files": [uploaded]},
        format="multipart",
    )
    downloaded = client.get(reverse("attachment-download", args=[attachment.id]))

    assert listed.status_code == 404
    assert posted.status_code == 404
    assert downloaded.status_code == 404


def test_security_responder_can_only_access_restricted_ticket_attachments(
    basic_world,
):
    restricted = _ticket(basic_world, confidentiality="restricted")
    normal = _ticket(basic_world)
    _attachment(restricted)
    _attachment(normal)
    client = _client(_user(["security-responders"]))

    allowed = client.get(reverse("ticket-attachments", args=[restricted.number]))
    denied = client.get(reverse("ticket-attachments", args=[normal.number]))

    assert allowed.status_code == 200
    assert len(allowed.data["results"]) == 1
    assert denied.status_code == 404


def test_auditor_can_list_and_download_but_cannot_upload(basic_world, monkeypatch):
    ticket = _ticket(basic_world)
    attachment = _attachment(ticket)
    client = _client(_user(["auditors"]))
    monkeypatch.setattr(
        "apps.files.views.generate_signed_url",
        lambda **_kwargs: "https://files.example.test/signed",
    )

    listed = client.get(reverse("ticket-attachments", args=[ticket.number]))
    downloaded = client.get(reverse("attachment-download", args=[attachment.id]))
    uploaded = client.post(
        reverse("ticket-attachments", args=[ticket.number]),
        {"files": [SimpleUploadedFile("probe.txt", b"probe")]},
        format="multipart",
    )

    assert listed.status_code == 200
    assert downloaded.status_code == 200
    assert downloaded.data["url"] == "https://files.example.test/signed"
    assert AttachmentAccessLog.objects.filter(attachment=attachment).count() == 1
    assert uploaded.status_code == 403
