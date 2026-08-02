"""Tests for the SAR (Subject Access Request) export."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.core.management import call_command

from apps.contacts.models import Contact
from apps.tickets import services

pytestmark = pytest.mark.django_db


def test_sar_export_includes_ticket_and_messages(basic_world, tmp_path, monkeypatch):
    contact = Contact.objects.create(full_name="SAR Test", email="sar@example.com")
    ticket = services.create_ticket(
        domain="operational",
        title="SAR test",
        description="Private",
        requester=contact,
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.first(),
        office=basic_world["office"],
        channel="web",
    )
    services.add_message(
        ticket=ticket,
        direction="outbound",
        body_text="Reply here",
        actor_subject="sar-test",
    )
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    out_dir = tmp_path
    call_command("sar_export", "--email", "sar@example.com", "--out", str(out_dir))
    files = list(Path(out_dir).glob("sar-*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["contact"]["email"] == "sar@example.com"
    assert any(t["number"] == ticket.number for t in payload["tickets"])
    assert any(m["body_text"] == "Reply here" for t in payload["tickets"] for m in t["messages"])
