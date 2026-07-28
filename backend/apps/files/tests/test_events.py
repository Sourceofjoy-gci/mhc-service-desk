"""Attachment event integration tests."""
from __future__ import annotations

import pytest

from apps.audit.models import AuditEvent
from apps.files.services import StoredObject, record_attachment
from apps.tickets import services
from apps.tickets.models import OutboxEvent

pytestmark = pytest.mark.django_db


def test_record_attachment_records_metadata_without_object_key_or_checksum(basic_world):
    ticket = services.create_ticket(
        domain="operational",
        title="Attachment event",
        description="",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.first(),
        office=basic_world["office"],
        channel="web",
        actor_subject="creator",
    )

    attachment = record_attachment(
        ticket=ticket,
        message=None,
        object_key="attachments/secret-storage-key",
        filename="evidence.pdf",
        content_type="application/pdf",
        size_bytes=4321,
        checksum_sha256="a" * 64,
        scan_status="clean",
        scan_signature="",
        actor_subject="agent-1",
        stored_object=StoredObject(
            bucket="mhc-attachments",
            key="attachments/secret-storage-key",
            etag="secret-etag",
            version_id="secret-version",
        ),
    )

    assert attachment.object_bucket == "mhc-attachments"
    assert attachment.object_version_id == "secret-version"
    assert attachment.object_etag == "secret-etag"

    audit = AuditEvent.objects.get(
        object_id=str(ticket.id),
        action="ticket.attachment.created",
    )
    outbox = OutboxEvent.objects.get(
        aggregate_id=str(ticket.id),
        event_type="ticket.attachment.created",
    )
    assert audit.payload == outbox.payload
    assert audit.payload["after"] == {
        "attachment_id": str(attachment.id),
        "filename": "evidence.pdf",
        "content_type": "application/pdf",
        "size_bytes": 4321,
        "scan_status": "clean",
    }
    assert "secret-storage-key" not in str(audit.payload)
    assert "secret-version" not in str(audit.payload)
    assert "a" * 64 not in str(audit.payload)
