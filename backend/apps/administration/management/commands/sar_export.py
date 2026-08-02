"""Subject Access Request (SAR) export.

A requester exercises their right to receive a copy of all data the
platform holds about them. The command bundles every record (contact,
tickets, messages, notes, attachments metadata, audit log) into a single
JSON file under ``backups/sar-<id>-<timestamp>.json``.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.audit.models import AuditEvent
from apps.contacts.models import Contact
from apps.tickets.models import Ticket, TicketMessage, TicketNote


class Command(BaseCommand):
    help = "Export every record linked to a contact as a Subject Access Request."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--email", required=False)
        parser.add_argument("--phone", required=False)
        parser.add_argument("--contact-id", required=False)
        parser.add_argument("--out", default="backups")

    def handle(self, *args: object, **opts: object) -> None:
        contact = self._find_contact(opts)
        if contact is None:
            raise CommandError("No matching contact found")
        tickets = list(Ticket.objects.filter(requester=contact).order_by("created_at"))
        ticket_ids = [t.id for t in tickets]
        messages = list(TicketMessage.objects.filter(ticket_id__in=ticket_ids))
        notes = list(TicketNote.objects.filter(ticket_id__in=ticket_ids))
        audit = list(
            AuditEvent.objects.filter(object_id__in=[str(t.id) for t in tickets])
            | AuditEvent.objects.filter(actor_subject=contact.email)
        )
        payload = {
            "request_id": str(uuid.uuid4()),
            "issued_at": datetime.now(tz=UTC).isoformat(),
            "contact": {
                "id": str(contact.id),
                "full_name": contact.full_name,
                "email": contact.email,
                "phone_e164": contact.phone_e164,
            },
            "tickets": [
                {
                    "number": t.number,
                    "title": t.title,
                    "description": t.description,
                    "status": t.status.code,
                    "priority": t.priority,
                    "channel": t.channel,
                    "created_at": t.created_at.isoformat(),
                    "updated_at": t.updated_at.isoformat(),
                    "messages": [
                        {
                            "direction": m.direction,
                            "body_text": m.body_text,
                            "author_subject": m.author_subject,
                            "created_at": m.created_at.isoformat(),
                        }
                        for m in messages if m.ticket_id == t.id
                    ],
                    "notes": [
                        {
                            "body": n.body,
                            "author_subject": n.author_subject,
                            "created_at": n.created_at.isoformat(),
                        }
                        for n in notes if n.ticket_id == t.id
                    ],
                }
                for t in tickets
            ],
            "audit_events": [
                {
                    "actor_subject": a.actor_subject,
                    "action": a.action,
                    "object_type": a.object_type,
                    "object_id": a.object_id,
                    "occurred_at": a.occurred_at.isoformat(),
                }
                for a in audit
            ],
        }
        output_directory = opts.get("out")
        if not isinstance(output_directory, str):
            raise CommandError("Output directory must be a string")
        Path(output_directory).mkdir(parents=True, exist_ok=True)
        out_path = Path(output_directory) / (
            f"sar-{contact.id}-"
            f"{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        out_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        self.stdout.write(self.style.SUCCESS(f"SAR export written to {out_path}"))

    def _find_contact(self, opts: Mapping[str, object]) -> Contact | None:
        cid = opts.get("contact_id")
        if isinstance(cid, str) and cid:
            try:
                return Contact.objects.get(id=cid)
            except Contact.DoesNotExist:
                return None
        email = opts.get("email")
        if isinstance(email, str) and email:
            return Contact.objects.filter(email__iexact=email).first()
        phone = opts.get("phone")
        if isinstance(phone, str) and phone:
            return Contact.objects.filter(phone_e164=phone).first()
        return None
