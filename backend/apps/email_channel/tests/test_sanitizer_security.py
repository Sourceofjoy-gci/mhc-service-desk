"""Security regressions for inbound email HTML sanitisation."""

from __future__ import annotations

import pytest

from apps.email_channel.models import Mailbox
from apps.email_channel.services import process_inbound_email
from apps.tickets.models import TicketMessage

pytestmark = pytest.mark.django_db


def test_email_html_rejects_invisible_uri_scheme_and_formaction(basic_world: object) -> None:
    Mailbox.objects.create(
        address="ops-security@mhc.local",
        domain="operational",
        is_active=True,
    )
    message_id = "<sanitizer-security@example.com>"

    result = process_inbound_email(
        from_header="Visitor <security-test@example.com>",
        to_header="ops-security@mhc.local",
        subject="Sanitizer security regression",
        body_text="Click Submit",
        body_html=(
            '<a href="javascript\u200b:alert(document.cookie)">Click</a>'
            '<form><button formaction="javascript:alert(document.cookie)">'
            "Submit</button></form>"
        ),
        message_id=message_id,
    )

    assert result["status"] == "created"
    sanitized = TicketMessage.objects.get(
        external_message_id=message_id,
    ).body_html_sanitized
    assert "javascript" not in sanitized.casefold()
    assert "formaction" not in sanitized.casefold()
    assert "\u200b" not in sanitized
