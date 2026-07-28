from uuid import UUID

from apps.files.models import Attachment, AttachmentAccessLog
from apps.sla.models import BusinessCalendar, SlaInstance, SlaPauseHistory, SlaPolicy
from apps.tickets.models import OutboxEvent, TicketLink, TicketMessage, TicketNote, Watcher

ATTACHMENT_ID = UUID("10000000-0000-0000-0000-000000000001")
ACCESS_LOG_ID = UUID("10000000-0000-0000-0000-000000000002")
CALENDAR_ID = UUID("20000000-0000-0000-0000-000000000001")
POLICY_ID = UUID("20000000-0000-0000-0000-000000000002")
INSTANCE_ID = UUID("20000000-0000-0000-0000-000000000003")
PAUSE_ID = UUID("20000000-0000-0000-0000-000000000004")
TICKET_ID = UUID("30000000-0000-0000-0000-000000000001")
RELATED_TICKET_ID = UUID("30000000-0000-0000-0000-000000000002")
MESSAGE_ID = UUID("30000000-0000-0000-0000-000000000003")
NOTE_ID = UUID("30000000-0000-0000-0000-000000000004")
LINK_ID = UUID("30000000-0000-0000-0000-000000000005")
WATCHER_ID = UUID("30000000-0000-0000-0000-000000000006")
USER_ID = UUID("30000000-0000-0000-0000-000000000007")
OUTBOX_ID = UUID("30000000-0000-0000-0000-000000000008")


def test_file_model_representations_are_stable_and_do_not_expose_storage_details():
    attachment = Attachment(
        id=ATTACHMENT_ID,
        ticket_id=TICKET_ID,
        filename="private-filing.pdf",
        object_key="secret-storage-key",
    )
    access = AttachmentAccessLog(
        id=ACCESS_LOG_ID,
        attachment_id=ATTACHMENT_ID,
        actor_subject="secret-actor-token",
    )

    assert str(attachment) == f"attachment:{ATTACHMENT_ID}"
    assert str(access) == f"attachment-access:{ACCESS_LOG_ID}"
    assert "secret-storage-key" not in str(attachment)
    assert "secret-actor-token" not in str(access)


def test_sla_model_representations_use_operational_identifiers_not_private_details():
    calendar = BusinessCalendar(id=CALENDAR_ID, name="Court business hours")
    policy = SlaPolicy(
        id=POLICY_ID,
        name="Operational P2",
        domain="operational",
        priority="P2",
        calendar_id=CALENDAR_ID,
    )
    instance = SlaInstance(
        id=INSTANCE_ID,
        ticket_id=TICKET_ID,
        policy_id=POLICY_ID,
        kind="resolution",
        state=SlaInstance.State.ACTIVE,
        breach_reason="private escalation details",
    )
    pause = SlaPauseHistory(
        id=PAUSE_ID,
        instance_id=INSTANCE_ID,
        state=SlaInstance.State.PAUSED_INTERNAL,
        reason="private internal dependency",
        actor_subject="secret-actor-token",
    )

    assert str(calendar) == "Court business hours"
    assert str(policy) == "Operational P2 (operational/P2)"
    assert str(instance) == f"resolution:{TICKET_ID} (active)"
    assert str(pause) == f"sla-pause:{INSTANCE_ID} (paused_internal)"
    assert "private escalation details" not in str(instance)
    assert "private internal dependency" not in str(pause)
    assert "secret-actor-token" not in str(pause)


def test_ticket_support_representations_omit_bodies_payloads_and_actor_secrets():
    message = TicketMessage(
        id=MESSAGE_ID,
        ticket_id=TICKET_ID,
        direction=TicketMessage.Direction.INBOUND,
        body_text="private requester message",
    )
    note = TicketNote(
        id=NOTE_ID,
        ticket_id=TICKET_ID,
        author_subject="secret-actor-token",
        body="private internal note",
    )
    link = TicketLink(
        id=LINK_ID,
        from_ticket_id=TICKET_ID,
        to_ticket_id=RELATED_TICKET_ID,
        kind=TicketLink.Kind.RELATED,
    )
    watcher = Watcher(id=WATCHER_ID, ticket_id=TICKET_ID, user_id=USER_ID)
    outbox = OutboxEvent(
        id=OUTBOX_ID,
        aggregate="ticket",
        aggregate_id=str(TICKET_ID),
        event_type="ticket.updated",
        payload={"token": "secret-outbox-token", "body": "private event body"},
    )

    assert str(message) == f"inbound-message:{MESSAGE_ID} ticket:{TICKET_ID}"
    assert str(note) == f"note:{NOTE_ID} ticket:{TICKET_ID}"
    assert str(link) == f"{TICKET_ID} related {RELATED_TICKET_ID}"
    assert str(watcher) == f"watcher:{USER_ID} ticket:{TICKET_ID}"
    assert str(outbox) == f"ticket.updated:ticket/{TICKET_ID}"
    combined = " ".join(str(value) for value in (message, note, link, watcher, outbox))
    assert "private requester message" not in combined
    assert "private internal note" not in combined
    assert "secret-actor-token" not in combined
    assert "secret-outbox-token" not in combined
    assert "private event body" not in combined
