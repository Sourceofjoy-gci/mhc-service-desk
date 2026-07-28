from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MethodType

import pytest
from django.core.management.base import CommandError

from apps.administration import retention


def _compact(sql: str) -> str:
    return " ".join(sql.split())


class FakeCursor:
    def __init__(self, results: dict[str, int] | None = None, delete_count: int = 0):
        self.results = results or {}
        self.delete_count = delete_count
        self.executed: list[tuple[str, list[datetime]]] = []
        self._current_sql = ""
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql: str, params: list[datetime]):
        self._current_sql = _compact(sql)
        self.executed.append((self._current_sql, params))
        if self._current_sql.startswith("DELETE"):
            self.rowcount = self.delete_count

    def fetchone(self):
        return (self.results.get(self._current_sql, 0),)


def _run_without_transaction(command: retention.Command, *args, **kwargs):
    dispose = retention.Command._dispose_table.__wrapped__
    return dispose(command, *args, **kwargs)


def _use_fake_cursor(monkeypatch, cursor: FakeCursor):
    from django.db import connection

    monkeypatch.setattr(connection, "cursor", lambda: cursor)


def test_unknown_policy_table_is_rejected_without_query_or_certificate(
    monkeypatch, tmp_path
):
    malicious_table = "ticket; DROP TABLE ticket; --"
    cursor = FakeCursor()
    _use_fake_cursor(monkeypatch, cursor)
    monkeypatch.setattr(
        retention,
        "get_retention_policy",
        lambda: {malicious_table: {"days": 30, "description": "unsafe"}},
    )
    now = datetime(2026, 7, 28, 8, 0, tzinfo=UTC)
    monkeypatch.setattr(retention.djtz, "now", lambda: now)
    command = retention.Command()
    command._dispose_table = MethodType(
        retention.Command._dispose_table.__wrapped__, command
    )

    with pytest.raises(CommandError, match="unsupported retention table"):
        command.handle(dry_run=True, table=[], out=str(tmp_path / "disposal-"))

    assert cursor.executed == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("table", "held_sql", "count_sql"),
    [
        (
            "ticket_message",
            "SELECT count(*) FROM ticket_message AS candidate "
            "WHERE candidate.created_at < %s AND ("
            "candidate.legal_hold = TRUE OR EXISTS ("
            "SELECT 1 FROM ticket AS held_ticket "
            "WHERE held_ticket.id = candidate.ticket_id "
            "AND held_ticket.legal_hold = TRUE))",
            "SELECT count(*) FROM ticket_message WHERE created_at < %s",
        ),
        (
            "ticket_note",
            "SELECT count(*) FROM ticket_note AS candidate "
            "WHERE candidate.created_at < %s AND ("
            "candidate.legal_hold = TRUE OR EXISTS ("
            "SELECT 1 FROM ticket AS held_ticket "
            "WHERE held_ticket.id = candidate.ticket_id "
            "AND held_ticket.legal_hold = TRUE))",
            "SELECT count(*) FROM ticket_note WHERE created_at < %s",
        ),
    ],
)
def test_child_retention_uses_static_own_and_parent_hold_queries(
    monkeypatch, table, held_sql, count_sql
):
    del monkeypatch, held_sql, count_sql
    plan = retention.RETENTION_SQL_PLANS[table]
    assert plan.delete_sql is None
    assert plan.orm_model_label in {"tickets.TicketMessage", "tickets.TicketNote"}


@pytest.mark.parametrize(
    ("table", "count_sql", "delete_sql"),
    [
        (
            "auditevent",
            "SELECT count(*) FROM auditevent WHERE occurred_at < %s",
            "DELETE FROM auditevent WHERE occurred_at < %s",
        ),
        (
            "integrationevent",
            "SELECT count(*) FROM integrationevent WHERE processed_at < %s",
            "DELETE FROM integrationevent WHERE processed_at < %s",
        ),
    ],
)
def test_non_hold_table_uses_its_current_schema_timestamp(
    monkeypatch, table, count_sql, delete_sql
):
    cutoff = datetime(2026, 6, 1, tzinfo=UTC)
    cursor = FakeCursor({_compact(count_sql): 4}, delete_count=4)
    _use_fake_cursor(monkeypatch, cursor)

    certificate = _run_without_transaction(
        retention.Command(), table, cutoff, {"days": 2555}, False
    )

    assert [sql for sql, _ in cursor.executed] == [count_sql, delete_sql]
    assert certificate["rows_disposed"] == 4
    assert certificate["legal_hold_preserved"] == 0


def test_dry_run_reports_selected_rows_without_delete(monkeypatch):
    cutoff = datetime(2026, 6, 1, tzinfo=UTC)
    count_sql = "SELECT count(*) FROM auditevent WHERE occurred_at < %s"
    cursor = FakeCursor({count_sql: 7})
    _use_fake_cursor(monkeypatch, cursor)

    certificate = _run_without_transaction(
        retention.Command(), "auditevent", cutoff, {"days": 30}, True
    )

    assert [sql for sql, _ in cursor.executed] == [count_sql]
    assert certificate["rows_selected"] == 7
    assert "rows_disposed" not in certificate


def test_handle_writes_structured_certificate_for_every_supported_table(
    monkeypatch, tmp_path
):
    supported_tables = {
        "ticket",
        "ticket_message",
        "ticket_note",
        "auditevent",
        "whatsapp_message",
        "integrationevent",
        "email_delivery",
        "csat_response",
    }
    cursor = FakeCursor()
    _use_fake_cursor(monkeypatch, cursor)
    policy = {
        table: {"days": index + 1, "description": "test"}
        for index, table in enumerate(sorted(supported_tables))
    }
    monkeypatch.setattr(retention, "get_retention_policy", lambda: policy)
    now = datetime(2026, 7, 28, 9, 30, tzinfo=UTC)
    monkeypatch.setattr(retention.djtz, "now", lambda: now)
    command = retention.Command()
    command._dispose_table = MethodType(
        lambda self, table, cutoff, rule, dry: {
            "table": table,
            "rows_selected": 0,
            "selection_hash": "a" * 64,
        },
        command,
    )

    command.handle(dry_run=True, table=[], out=str(tmp_path / "disposal-"))

    certificate = json.loads(
        (tmp_path / "disposal-preview-20260728T093000Z.json").read_text(
            encoding="utf-8"
        )
    )
    assert {entry["table"] for entry in certificate["rows"]} == supported_tables
    assert all(entry["rows_selected"] == 0 for entry in certificate["rows"])
    assert certificate["mode"] == "preview"
    assert cursor.executed == []


def test_cutoff_uses_policy_days(monkeypatch, tmp_path):
    cursor = FakeCursor()
    _use_fake_cursor(monkeypatch, cursor)
    monkeypatch.setattr(
        retention,
        "get_retention_policy",
        lambda: {"auditevent": {"days": 14, "description": "test"}},
    )
    now = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)
    monkeypatch.setattr(retention.djtz, "now", lambda: now)
    command = retention.Command()
    command._dispose_table = MethodType(
        retention.Command._dispose_table.__wrapped__, command
    )

    command.handle(dry_run=True, table=[], out=str(tmp_path / "disposal-"))

    assert cursor.executed[0][1] == [now - timedelta(days=14)]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("table", "related_name"),
    [("ticket_message", "messages"), ("ticket_note", "notes")],
)
def test_child_retention_preserves_records_for_held_parent_ticket(
    basic_world, table, related_name
):
    from apps.catalogue.models import RequestType
    from apps.tickets.models import Ticket, TicketMessage, TicketNote
    from apps.workflow.models import Status

    status = Status.objects.get(domain="operational", is_initial=True)
    request_type = RequestType.objects.get(service=basic_world["gen_info"])
    tickets = []
    for suffix, legal_hold in (("HELD", True), ("FREE", False)):
        tickets.append(
            Ticket.objects.create(
                number=f"OP-RETENTION-{suffix}",
                domain="operational",
                title=f"Retention {suffix}",
                status=status,
                priority="P3",
                channel="web",
                requester=basic_world["contact"],
                service=basic_world["gen_info"],
                request_type=request_type,
                office=basic_world["office"],
                legal_hold=legal_hold,
            )
        )
    if table == "ticket_message":
        records = [
            TicketMessage.objects.create(
                ticket=ticket,
                direction="inbound",
                body_text=f"Message {ticket.number}",
            )
            for ticket in tickets
        ]
        model = TicketMessage
    else:
        records = [
            TicketNote.objects.create(
                ticket=ticket,
                author_subject="retention-test",
                body=f"Note {ticket.number}",
            )
            for ticket in tickets
        ]
        model = TicketNote
    old_created_at = datetime(2026, 1, 1, tzinfo=UTC)
    model.objects.filter(pk__in=[record.pk for record in records]).update(
        created_at=old_created_at
    )

    certificate = retention.Command()._dispose_table(
        table,
        datetime(2026, 7, 1, tzinfo=UTC),
        {"days": 30},
        False,
    )

    assert list(model.objects.values_list("ticket_id", flat=True)) == [tickets[0].pk]
    assert getattr(tickets[0], related_name).count() == 1
    assert getattr(tickets[1], related_name).count() == 0
    assert certificate["rows_disposed"] == 1
    assert certificate["legal_hold_preserved"] == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("table", "related_name"),
    [("ticket_message", "messages"), ("ticket_note", "notes")],
)
def test_child_retention_preserves_held_child_under_unheld_parent(
    basic_world, table, related_name
):
    from apps.catalogue.models import RequestType
    from apps.tickets.models import Ticket, TicketMessage, TicketNote
    from apps.workflow.models import Status

    ticket = Ticket.objects.create(
        number=f"OP-CHILD-HOLD-{table}",
        domain="operational",
        title="Child legal hold",
        status=Status.objects.get(domain="operational", is_initial=True),
        priority="P3",
        channel="web",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=RequestType.objects.get(service=basic_world["gen_info"]),
        office=basic_world["office"],
        legal_hold=False,
    )
    if table == "ticket_message":
        held = TicketMessage.objects.create(
            ticket=ticket,
            direction="inbound",
            body_text="Held message",
            legal_hold=True,
        )
        free = TicketMessage.objects.create(
            ticket=ticket,
            direction="inbound",
            body_text="Disposable message",
            legal_hold=False,
        )
        model = TicketMessage
    else:
        held = TicketNote.objects.create(
            ticket=ticket,
            author_subject="retention-test",
            body="Held note",
            legal_hold=True,
        )
        free = TicketNote.objects.create(
            ticket=ticket,
            author_subject="retention-test",
            body="Disposable note",
            legal_hold=False,
        )
        model = TicketNote
    model.objects.filter(pk__in=[held.pk, free.pk]).update(
        created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    certificate = retention.Command()._dispose_table(
        table,
        datetime(2026, 7, 1, tzinfo=UTC),
        {"days": 30},
        False,
    )

    assert set(getattr(ticket, related_name).values_list("pk", flat=True)) == {
        held.pk,
        free.pk,
    }
    assert certificate["rows_disposed"] == 0
    assert certificate["legal_hold_preserved"] == 2


@pytest.mark.django_db(transaction=True)
def test_message_retention_preserves_fresh_dependent_records(basic_world):
    from apps.catalogue.models import RequestType
    from apps.email_channel.models import EmailDelivery
    from apps.files.models import Attachment
    from apps.tickets.models import Ticket, TicketMessage
    from apps.workflow.models import Status

    ticket = Ticket.objects.create(
        number="OP-MESSAGE-DEPENDENCY-RETENTION",
        domain="operational",
        title="Message dependency retention",
        status=Status.objects.get(domain="operational", is_initial=True),
        priority="P3",
        channel="web",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=RequestType.objects.get(service=basic_world["gen_info"]),
        office=basic_world["office"],
    )
    message = TicketMessage.objects.create(
        ticket=ticket,
        direction="outbound",
        body_text="Dependency-aware message",
    )
    TicketMessage.objects.filter(pk=message.pk).update(
        created_at=datetime(2000, 1, 1, tzinfo=UTC)
    )
    delivery = EmailDelivery.objects.create(
        ticket_message=message,
        to_address="requester@example.test",
        from_address="service@example.test",
        subject="Retention",
        body_text="Retention",
    )
    attachment = Attachment.objects.create(
        ticket=ticket,
        message=message,
        object_key="retention/message-dependency.txt",
        filename="message-dependency.txt",
        content_type="text/plain",
        size_bytes=10,
        checksum_sha256="6" * 64,
        uploaded_by_subject="retention-test",
    )

    command = retention.Command()
    command._active_cutoffs = {
        "email_delivery": datetime(2026, 7, 1, tzinfo=UTC)
    }
    certificate = command._dispose_table(
        "ticket_message",
        datetime(2026, 7, 1, tzinfo=UTC),
        {"days": 30},
        False,
    )

    assert TicketMessage.objects.filter(pk=message.pk).exists()
    assert EmailDelivery.objects.filter(pk=delivery.pk).exists()
    attachment.refresh_from_db()
    assert attachment.message_id == message.pk
    assert certificate["rows_disposed"] == 0


@pytest.mark.django_db(transaction=True)
def test_message_retention_deletes_only_after_dependencies_are_old(basic_world):
    from apps.catalogue.models import RequestType
    from apps.email_channel.models import EmailDelivery
    from apps.files.models import Attachment
    from apps.tickets.models import Ticket, TicketMessage
    from apps.workflow.models import Status

    ticket = Ticket.objects.create(
        number="OP-MESSAGE-DEPENDENCY-OLD",
        domain="operational",
        title="Old dependencies",
        status=Status.objects.get(domain="operational", is_initial=True),
        priority="P3",
        channel="web",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=RequestType.objects.get(service=basic_world["gen_info"]),
        office=basic_world["office"],
    )
    message = TicketMessage.objects.create(
        ticket=ticket, direction="outbound", body_text="Old dependencies"
    )
    delivery = EmailDelivery.objects.create(
        ticket_message=message,
        to_address="requester@example.test",
        from_address="service@example.test",
        subject="Old",
        body_text="Old",
    )
    attachment = Attachment.objects.create(
        ticket=ticket,
        message=message,
        object_key="retention/message-old-dependency.txt",
        filename="message-old-dependency.txt",
        content_type="text/plain",
        size_bytes=10,
        checksum_sha256="7" * 64,
        uploaded_by_subject="retention-test",
    )
    old = datetime(2000, 1, 1, tzinfo=UTC)
    TicketMessage.objects.filter(pk=message.pk).update(created_at=old)
    EmailDelivery.objects.filter(pk=delivery.pk).update(created_at=old)
    Attachment.objects.filter(pk=attachment.pk).update(uploaded_at=old)
    command = retention.Command()
    command._active_cutoffs = {"email_delivery": datetime(2026, 7, 1, tzinfo=UTC)}

    certificate = command._dispose_table(
        "ticket_message",
        datetime(2026, 7, 1, tzinfo=UTC),
        {"days": 30},
        False,
    )

    assert not TicketMessage.objects.filter(pk=message.pk).exists()
    assert not EmailDelivery.objects.filter(pk=delivery.pk).exists()
    attachment.refresh_from_db()
    assert attachment.message_id is None
    assert certificate["rows_disposed"] == 1


@pytest.mark.django_db(transaction=True)
def test_ticket_disposal_commits_populated_graph_and_preserves_child_held_graph(
    basic_world, monkeypatch, tmp_path
):
    from apps.administration.models import ConfigItem, DisposalEvent
    from apps.catalogue.models import RequestType
    from apps.csat.models import CsatResponse
    from apps.email_channel.models import EmailDelivery
    from apps.files.models import Attachment, AttachmentAccessLog, ObjectDeleteJob
    from apps.identity_access.models import User
    from apps.knowledge.models import KnowledgeArticle, KnowledgeUsageLog
    from apps.sla.models import SlaInstance, SlaPauseHistory, SlaPolicy
    from apps.tickets.models import (
        Ticket,
        TicketLink,
        TicketMessage,
        TicketNote,
        Watcher,
    )
    from apps.whatsapp.models import WhatsappAccount, WhatsappMessage
    from apps.workflow.models import Status, TransitionHistory

    now = datetime(2026, 7, 28, 12, 30, tzinfo=UTC)
    monkeypatch.setattr(retention.djtz, "now", lambda: now)
    ConfigItem.objects.create(
        key="retention.policy.v1",
        value={
            "ticket": {"days": 30, "description": "approved test policy"},
            "ticket_message": {"days": 30},
            "ticket_note": {"days": 30},
            "email_delivery": {"days": 30},
            "whatsapp_message": {"days": 30},
            "csat_response": {"days": 30},
        },
    )
    status = Status.objects.get(domain="operational", is_initial=True)
    request_type = RequestType.objects.get(service=basic_world["gen_info"])

    def make_ticket(number: str) -> Ticket:
        ticket = Ticket.objects.create(
            number=number,
            domain="operational",
            title=number,
            status=status,
            priority="P3",
            channel="web",
            requester=basic_world["contact"],
            service=basic_world["gen_info"],
            request_type=request_type,
            office=basic_world["office"],
            legal_hold=False,
        )
        Ticket.objects.filter(pk=ticket.pk).update(
            created_at=datetime(2000, 1, 1, tzinfo=UTC)
        )
        return ticket

    disposable = make_ticket("OP-RETENTION-GRAPH-DISPOSE")
    preserved = make_ticket("OP-RETENTION-GRAPH-HELD")

    message = TicketMessage.objects.create(
        ticket=disposable,
        direction="inbound",
        body_text="Populated graph message",
    )
    note = TicketNote.objects.create(
        ticket=disposable,
        author_subject="retention-test",
        body="Populated graph note",
    )
    held_note = TicketNote.objects.create(
        ticket=preserved,
        author_subject="retention-test",
        body="This child keeps the whole graph",
        legal_hold=True,
    )
    delivery = EmailDelivery.objects.create(
        ticket_message=message,
        to_address="requester@example.test",
        from_address="service@example.test",
        subject="Retention",
        body_text="Retention",
    )
    attachment = Attachment.objects.create(
        ticket=disposable,
        message=message,
        object_key="retention/populated-graph.txt",
        object_bucket="attachments",
        object_version_id="populated-version",
        object_etag="populated-etag",
        filename="populated-graph.txt",
        content_type="text/plain",
        size_bytes=10,
        checksum_sha256="5" * 64,
        uploaded_by_subject="retention-test",
    )
    access_log = AttachmentAccessLog.objects.create(
        attachment=attachment,
        actor_subject="retention-test",
    )
    csat = CsatResponse.objects.create(ticket=disposable)
    transition = TransitionHistory.objects.create(
        ticket=disposable,
        from_status=None,
        to_status=status,
        actor_subject="retention-test",
    )
    policy = SlaPolicy.objects.get(domain="operational", priority="P3")
    sla = SlaInstance.objects.create(
        ticket=disposable,
        policy=policy,
        kind="resolution",
        due_at=now + timedelta(days=1),
    )
    pause = SlaPauseHistory.objects.create(
        instance=sla,
        state="paused_requester",
        reason="awaiting_requester",
    )
    held_sla = SlaInstance.objects.create(
        ticket=preserved,
        policy=policy,
        kind="resolution",
        due_at=now + timedelta(days=1),
    )
    watcher_user = User.objects.create_user(
        username="retention-watcher",
        keycloak_subject="retention-watcher-subject",
    )
    watcher = Watcher.objects.create(ticket=disposable, user=watcher_user)
    link = TicketLink.objects.create(
        from_ticket=disposable,
        to_ticket=preserved,
        kind=TicketLink.Kind.RELATED,
    )
    reverse_link = TicketLink.objects.create(
        from_ticket=preserved,
        to_ticket=disposable,
        kind=TicketLink.Kind.BLOCKED_BY,
    )
    whatsapp_account = WhatsappAccount.objects.create(
        phone_number_id="retention-phone-id",
        display_name="Retention account",
        domain="operational",
    )
    whatsapp = WhatsappMessage.objects.create(
        ticket=disposable,
        account=whatsapp_account,
        direction="inbound",
        body="Retention WhatsApp",
    )
    article = KnowledgeArticle.objects.create(
        code="RETENTION-GRAPH",
        title="Retention graph",
        body="Test article",
        audience="internal_op",
        domain="operational",
        owner_subject="retention-test",
    )
    usage = KnowledgeUsageLog.objects.create(
        article=article,
        ticket=disposable,
        actor_subject="retention-test",
    )
    old = datetime(2000, 1, 1, tzinfo=UTC)
    TicketMessage.objects.filter(pk=message.pk).update(created_at=old)
    TicketNote.objects.filter(pk=note.pk).update(created_at=old)
    EmailDelivery.objects.filter(pk=delivery.pk).update(created_at=old)
    Attachment.objects.filter(pk=attachment.pk).update(uploaded_at=old)
    AttachmentAccessLog.objects.filter(pk=access_log.pk).update(at=old)
    CsatResponse.objects.filter(pk=csat.pk).update(invited_at=old)
    TransitionHistory.objects.filter(pk=transition.pk).update(occurred_at=old)
    SlaInstance.objects.filter(pk=sla.pk).update(created_at=old, updated_at=old)
    SlaPauseHistory.objects.filter(pk=pause.pk).update(at=old)
    Watcher.objects.filter(pk=watcher.pk).update(created_at=old)
    TicketLink.objects.filter(pk__in=[link.pk, reverse_link.pk]).update(created_at=old)
    WhatsappMessage.objects.filter(pk=whatsapp.pk).update(created_at=old)
    KnowledgeUsageLog.objects.filter(pk=usage.pk).update(used_at=old)

    retention.Command().handle(
        dry_run=False,
        table=[],
        out=str(tmp_path / "populated-graph-"),
    )

    assert not Ticket.objects.filter(pk=disposable.pk).exists()
    for model, pk in (
        (TicketMessage, message.pk),
        (TicketNote, note.pk),
        (EmailDelivery, delivery.pk),
        (Attachment, attachment.pk),
        (AttachmentAccessLog, access_log.pk),
        (CsatResponse, csat.pk),
        (TransitionHistory, transition.pk),
        (SlaInstance, sla.pk),
        (SlaPauseHistory, pause.pk),
            (Watcher, watcher.pk),
            (TicketLink, link.pk),
            (TicketLink, reverse_link.pk),
            (WhatsappMessage, whatsapp.pk),
        ):
            assert not model.objects.filter(pk=pk).exists()
    usage.refresh_from_db()
    assert usage.ticket_id is None

    assert Ticket.objects.filter(pk=preserved.pk).exists()
    assert TicketNote.objects.filter(pk=held_note.pk).exists()
    assert SlaInstance.objects.filter(pk=held_sla.pk).exists()
    event = DisposalEvent.objects.get()
    assert event.summary[0]["table"] == "ticket"
    assert event.summary[0]["rows_disposed"] == 1
    assert event.summary[0]["legal_hold_preserved"] == 1
    assert ObjectDeleteJob.objects.filter(disposal_event=event).count() == 1
    assert event.certificate_exported_at is None


def test_certificate_fsyncs_parent_directory_after_atomic_link(monkeypatch, tmp_path):
    events: list[str] = []
    original_link = retention.os.link

    def record_link(source, destination):
        original_link(source, destination)
        events.append("link")

    monkeypatch.setattr(retention.os, "link", record_link)
    monkeypatch.setattr(
        retention.Command,
        "_fsync_parent_directory",
        staticmethod(lambda _path: events.append("parent-fsync")),
        raising=False,
    )

    retention.Command._write_certificate(tmp_path / "certificate.json", [])

    assert events == ["link", "parent-fsync"]


def test_parent_directory_fsync_opens_syncs_and_closes_directory(
    monkeypatch, tmp_path
):
    events: list[tuple[object, ...]] = []
    directory_fd = 321

    def record_open(path, flags):
        events.append(("open", path, flags))
        return directory_fd

    monkeypatch.setattr(retention.os, "open", record_open)
    monkeypatch.setattr(
        retention.os,
        "fsync",
        lambda fd: events.append(("fsync", fd)),
    )
    monkeypatch.setattr(
        retention.os,
        "close",
        lambda fd: events.append(("close", fd)),
    )

    retention.Command._fsync_parent_directory(tmp_path / "certificate.json")

    assert events == [
        (
            "open",
            tmp_path,
            retention.os.O_RDONLY | getattr(retention.os, "O_DIRECTORY", 0),
        ),
        ("fsync", directory_fd),
        ("close", directory_fd),
    ]


@pytest.mark.django_db
def test_default_retention_plans_execute_against_current_postgresql_schema(
    capsys, tmp_path
):
    from django.db import connection

    assert connection.vendor == "postgresql"

    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    command = retention.Command()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(retention.djtz, "now", lambda: now)
        command.handle(
            dry_run=True,
            table=[],
            out=str(tmp_path / "default-plans-"),
        )

    certificate = json.loads(
        (tmp_path / "default-plans-preview-20260728T120000Z.json").read_text(
            encoding="utf-8"
        )
    )
    assert {entry["table"] for entry in certificate["rows"]} == set(
        retention.DEFAULT_RETENTION
    )
    assert certificate["status"] == "not_executed"
    assert "unapproved preview schedule only" in capsys.readouterr().err


@pytest.mark.django_db
def test_destructive_run_requires_an_operator_configured_policy(tmp_path):
    from apps.audit.models import AuditEvent

    old_event = AuditEvent.objects.create(
        actor_subject="retention-test",
        action="retention.test",
        object_type="test",
        object_id="unconfigured-policy",
        payload={},
        payload_hash="0" * 64,
    )
    AuditEvent.objects.filter(pk=old_event.pk).update(
        occurred_at=datetime(2000, 1, 1, tzinfo=UTC)
    )

    with pytest.raises(CommandError, match="configured retention policy"):
        retention.Command().handle(
            dry_run=False,
            table=["auditevent"],
            out=str(tmp_path / "unconfigured-"),
        )

    assert AuditEvent.objects.filter(pk=old_event.pk).exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.django_db
def test_invalid_later_policy_rule_is_rejected_before_any_deletion(tmp_path):
    from apps.administration.models import ConfigItem
    from apps.audit.models import AuditEvent

    ConfigItem.objects.create(
        key="retention.policy.v1",
        value={
            "auditevent": {"days": 1, "description": "configured"},
            "invented_table": {"days": 1, "description": "invalid"},
        },
    )
    old_event = AuditEvent.objects.create(
        actor_subject="retention-test",
        action="retention.test",
        object_type="test",
        object_id="invalid-later-rule",
        payload={},
        payload_hash="1" * 64,
    )
    AuditEvent.objects.filter(pk=old_event.pk).update(
        occurred_at=datetime(2000, 1, 1, tzinfo=UTC)
    )

    with pytest.raises(CommandError, match="unsupported retention table"):
        retention.Command().handle(
            dry_run=False,
            table=[],
            out=str(tmp_path / "invalid-policy-"),
        )

    assert AuditEvent.objects.filter(pk=old_event.pk).exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.django_db
def test_later_table_failure_rolls_back_entire_run_without_certificate(
    monkeypatch, tmp_path
):
    from apps.administration.models import ConfigItem
    from apps.audit.models import AuditEvent

    ConfigItem.objects.create(
        key="retention.policy.v1",
        value={
            "auditevent": {"days": 1, "description": "configured"},
            "integrationevent": {"days": 1, "description": "configured"},
        },
    )
    old_event = AuditEvent.objects.create(
        actor_subject="retention-test",
        action="retention.test",
        object_type="test",
        object_id="later-table-failure",
        payload={},
        payload_hash="2" * 64,
    )
    AuditEvent.objects.filter(pk=old_event.pk).update(
        occurred_at=datetime(2000, 1, 1, tzinfo=UTC)
    )
    original_dispose = retention.Command._dispose_table

    def fail_on_second_table(command, table, cutoff, rule, dry):
        if table == "integrationevent":
            raise RuntimeError("simulated later-table failure")
        return original_dispose(command, table, cutoff, rule, dry)

    monkeypatch.setattr(retention.Command, "_dispose_table", fail_on_second_table)

    with pytest.raises(RuntimeError, match="simulated later-table failure"):
        retention.Command().handle(
            dry_run=False,
            table=[],
            out=str(tmp_path / "later-failure-"),
        )

    assert AuditEvent.objects.filter(pk=old_event.pk).exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.django_db(transaction=True)
def test_certificate_write_failure_keeps_committed_database_truth(tmp_path):
    from apps.administration.models import ConfigItem, DisposalEvent
    from apps.audit.models import AuditEvent

    ConfigItem.objects.create(
        key="retention.policy.v1",
        value={"auditevent": {"days": 1, "description": "configured"}},
    )
    old_event = AuditEvent.objects.create(
        actor_subject="retention-test",
        action="retention.test",
        object_type="test",
        object_id="certificate-failure",
        payload={},
        payload_hash="3" * 64,
    )
    AuditEvent.objects.filter(pk=old_event.pk).update(
        occurred_at=datetime(2000, 1, 1, tzinfo=UTC)
    )
    missing_directory = tmp_path / "missing"

    with pytest.raises(CommandError, match="retry-event"):
        retention.Command().handle(
            dry_run=False,
            table=[],
            out=str(missing_directory / "certificate-"),
        )

    assert not AuditEvent.objects.filter(pk=old_event.pk).exists()
    event = DisposalEvent.objects.get()
    assert event.certificate_exported_at is None
    assert event.export_error == "FileNotFoundError"
    assert not missing_directory.exists()


@pytest.mark.django_db
def test_all_sql_plans_are_validated_before_the_first_delete(monkeypatch, tmp_path):
    from django.db import ProgrammingError

    from apps.administration.models import ConfigItem
    from apps.audit.models import AuditEvent

    ConfigItem.objects.create(
        key="retention.policy.v1",
        value={
            "auditevent": {"days": 1, "description": "configured"},
            "integrationevent": {"days": 1, "description": "configured"},
        },
    )
    old_event = AuditEvent.objects.create(
        actor_subject="retention-test",
        action="retention.test",
        object_type="test",
        object_id="preflight-validation",
        payload={},
        payload_hash="4" * 64,
    )
    AuditEvent.objects.filter(pk=old_event.pk).update(
        occurred_at=datetime(2000, 1, 1, tzinfo=UTC)
    )
    valid_plan = retention.RETENTION_SQL_PLANS["integrationevent"]
    monkeypatch.setitem(
        retention.RETENTION_SQL_PLANS,
        "integrationevent",
        replace(
            valid_plan,
            delete_sql=(
                "DELETE FROM integrationevent WHERE nonexistent_timestamp < %s"
            ),
        ),
    )

    with pytest.raises(ProgrammingError, match="nonexistent_timestamp"):
        retention.Command().handle(
            dry_run=False,
            table=[],
            out=str(tmp_path / "preflight-"),
        )

    assert AuditEvent.objects.filter(pk=old_event.pk).exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.django_db(transaction=True)
def test_full_policy_preserves_every_record_in_a_held_ticket_graph(
    basic_world, monkeypatch, tmp_path
):
    from apps.administration.models import ConfigItem, DisposalEvent
    from apps.catalogue.models import RequestType
    from apps.csat.models import CsatResponse
    from apps.email_channel.models import EmailDelivery
    from apps.files.models import Attachment
    from apps.tickets.models import Ticket, TicketMessage
    from apps.whatsapp.models import WhatsappAccount, WhatsappMessage
    from apps.workflow.models import Status

    now = datetime(2026, 7, 28, 13, 0, tzinfo=UTC)
    monkeypatch.setattr(retention.djtz, "now", lambda: now)
    ConfigItem.objects.create(
        key="retention.policy.v1",
        value={
            "ticket": {"days": 30},
            "ticket_message": {"days": 30},
            "email_delivery": {"days": 30},
            "whatsapp_message": {"days": 30},
            "csat_response": {"days": 30},
        },
    )
    ticket = Ticket.objects.create(
        number="OP-RETENTION-HELD-FULL-GRAPH",
        domain="operational",
        title="Held graph",
        status=Status.objects.get(domain="operational", is_initial=True),
        priority="P3",
        channel="web",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=RequestType.objects.get(service=basic_world["gen_info"]),
        office=basic_world["office"],
        legal_hold=True,
    )
    message = TicketMessage.objects.create(
        ticket=ticket, direction="inbound", body_text="held graph"
    )
    delivery = EmailDelivery.objects.create(
        ticket_message=message,
        to_address="requester@example.test",
        from_address="service@example.test",
        subject="Held",
        body_text="Held",
    )
    account = WhatsappAccount.objects.create(
        phone_number_id="retention-held-full",
        display_name="Retention",
        domain="operational",
    )
    whatsapp = WhatsappMessage.objects.create(
        ticket=ticket,
        account=account,
        direction="inbound",
        body="Held",
    )
    csat = CsatResponse.objects.create(ticket=ticket)
    attachment = Attachment.objects.create(
        ticket=ticket,
        message=message,
        object_key="retention/held-full.txt",
        object_bucket="attachments",
        object_version_id="held-version",
        object_etag="held-etag",
        filename="held-full.txt",
        content_type="text/plain",
        size_bytes=4,
        checksum_sha256="a" * 64,
        uploaded_by_subject="retention-test",
    )
    old = datetime(2000, 1, 1, tzinfo=UTC)
    Ticket.objects.filter(pk=ticket.pk).update(created_at=old)
    TicketMessage.objects.filter(pk=message.pk).update(created_at=old)
    EmailDelivery.objects.filter(pk=delivery.pk).update(created_at=old)
    WhatsappMessage.objects.filter(pk=whatsapp.pk).update(created_at=old)
    CsatResponse.objects.filter(pk=csat.pk).update(invited_at=old)
    Attachment.objects.filter(pk=attachment.pk).update(uploaded_at=old)

    retention.Command().handle(
        dry_run=False,
        table=[],
        out=str(tmp_path / "held-full-"),
    )

    for model, pk in (
        (Ticket, ticket.pk),
        (TicketMessage, message.pk),
        (EmailDelivery, delivery.pk),
        (WhatsappMessage, whatsapp.pk),
        (CsatResponse, csat.pk),
        (Attachment, attachment.pk),
    ):
        assert model.objects.filter(pk=pk).exists()
    assert DisposalEvent.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_ticket_retention_does_not_cascade_a_fresh_message(
    basic_world, monkeypatch, tmp_path
):
    from apps.administration.models import ConfigItem
    from apps.catalogue.models import RequestType
    from apps.tickets.models import Ticket, TicketMessage
    from apps.workflow.models import Status

    now = datetime(2026, 7, 28, 13, 30, tzinfo=UTC)
    monkeypatch.setattr(retention.djtz, "now", lambda: now)
    ConfigItem.objects.create(
        key="retention.policy.v1",
        value={"ticket": {"days": 30}, "ticket_message": {"days": 30}},
    )
    ticket = Ticket.objects.create(
        number="OP-RETENTION-FRESH-CHILD",
        domain="operational",
        title="Fresh child",
        status=Status.objects.get(domain="operational", is_initial=True),
        priority="P3",
        channel="web",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=RequestType.objects.get(service=basic_world["gen_info"]),
        office=basic_world["office"],
    )
    Ticket.objects.filter(pk=ticket.pk).update(
        created_at=datetime(2000, 1, 1, tzinfo=UTC)
    )
    message = TicketMessage.objects.create(
        ticket=ticket, direction="inbound", body_text="Fresh child"
    )

    retention.Command().handle(
        dry_run=False,
        table=["ticket"],
        out=str(tmp_path / "fresh-child-"),
    )

    assert Ticket.objects.filter(pk=ticket.pk).exists()
    assert TicketMessage.objects.filter(pk=message.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_retention_locks_parent_and_hold_rows_then_revalidates(
    basic_world, monkeypatch
):
    from django.db import connection, transaction
    from django.test.utils import CaptureQueriesContext

    from apps.catalogue.models import RequestType
    from apps.tickets.models import Ticket, TicketMessage
    from apps.workflow.models import Status

    ticket = Ticket.objects.create(
        number="OP-RETENTION-HOLD-REVALIDATE",
        domain="operational",
        title="Hold revalidation",
        status=Status.objects.get(domain="operational", is_initial=True),
        priority="P3",
        channel="web",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=RequestType.objects.get(service=basic_world["gen_info"]),
        office=basic_world["office"],
    )
    message = TicketMessage.objects.create(
        ticket=ticket, direction="inbound", body_text="hold race"
    )
    old = datetime(2000, 1, 1, tzinfo=UTC)
    TicketMessage.objects.filter(pk=message.pk).update(created_at=old)
    command = retention.Command()
    original_lock = command._lock_hold_graph

    def apply_hold_after_locks(ticket_ids):
        original_lock(ticket_ids)
        TicketMessage.objects.filter(pk=message.pk).update(legal_hold=True)

    monkeypatch.setattr(command, "_lock_hold_graph", apply_hold_after_locks)
    with transaction.atomic(), CaptureQueriesContext(connection) as queries:
        disposed = command._delete_with_orm(
            "ticket_message",
            datetime(2026, 7, 1, tzinfo=UTC),
            "tickets.TicketMessage",
        )

    assert disposed == 0
    assert TicketMessage.objects.filter(pk=message.pk).exists()
    lock_sql = [query["sql"] for query in queries if "FOR UPDATE" in query["sql"]]
    assert any('FROM "ticket"' in sql for sql in lock_sql)
    assert any('FROM "ticket_message"' in sql for sql in lock_sql)
    assert any('FROM "ticket_note"' in sql for sql in lock_sql)


@pytest.mark.django_db(transaction=True)
def test_retention_enqueues_exact_object_delete_before_metadata_disposal(
    basic_world, monkeypatch, tmp_path
):
    from apps.administration.models import ConfigItem, DisposalEvent
    from apps.catalogue.models import RequestType
    from apps.files.models import Attachment, ObjectDeleteJob
    from apps.tickets.models import Ticket
    from apps.workflow.models import Status

    now = datetime(2026, 7, 28, 14, 0, tzinfo=UTC)
    monkeypatch.setattr(retention.djtz, "now", lambda: now)
    ConfigItem.objects.create(
        key="retention.policy.v1", value={"ticket": {"days": 30}}
    )
    ticket = Ticket.objects.create(
        number="OP-RETENTION-OBJECT-JOB",
        domain="operational",
        title="Object job",
        status=Status.objects.get(domain="operational", is_initial=True),
        priority="P3",
        channel="web",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=RequestType.objects.get(service=basic_world["gen_info"]),
        office=basic_world["office"],
    )
    attachment = Attachment.objects.create(
        ticket=ticket,
        object_key="retention/exact-version.txt",
        object_bucket="attachments",
        object_version_id="version-123",
        object_etag="etag-123",
        filename="exact-version.txt",
        content_type="text/plain",
        size_bytes=4,
        checksum_sha256="b" * 64,
        uploaded_by_subject="retention-test",
    )
    old = datetime(2000, 1, 1, tzinfo=UTC)
    Ticket.objects.filter(pk=ticket.pk).update(created_at=old)
    Attachment.objects.filter(pk=attachment.pk).update(uploaded_at=old)

    retention.Command().handle(
        dry_run=False,
        table=[],
        out=str(tmp_path / "object-job-"),
    )

    assert not Ticket.objects.filter(pk=ticket.pk).exists()
    assert not Attachment.objects.filter(pk=attachment.pk).exists()
    event = DisposalEvent.objects.get()
    job = ObjectDeleteJob.objects.get(disposal_event=event)
    assert (job.bucket, job.object_key, job.version_id, job.etag) == (
        "attachments",
        "retention/exact-version.txt",
        "version-123",
        "etag-123",
    )
    assert event.certificate_exported_at is None
    assert list(tmp_path.glob("object-job-*.json")) == []


@pytest.mark.django_db(transaction=True)
def test_legacy_attachment_without_version_fails_closed(
    basic_world, monkeypatch, tmp_path
):
    from apps.administration.models import ConfigItem, DisposalEvent
    from apps.catalogue.models import RequestType
    from apps.files.models import Attachment, ObjectDeleteJob
    from apps.tickets.models import Ticket
    from apps.workflow.models import Status

    monkeypatch.setattr(
        retention.djtz, "now", lambda: datetime(2026, 7, 28, 14, 30, tzinfo=UTC)
    )
    ConfigItem.objects.create(
        key="retention.policy.v1", value={"ticket": {"days": 30}}
    )
    ticket = Ticket.objects.create(
        number="OP-RETENTION-LEGACY-OBJECT",
        domain="operational",
        title="Legacy object",
        status=Status.objects.get(domain="operational", is_initial=True),
        priority="P3",
        channel="web",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=RequestType.objects.get(service=basic_world["gen_info"]),
        office=basic_world["office"],
    )
    attachment = Attachment.objects.create(
        ticket=ticket,
        object_key="retention/legacy.txt",
        filename="legacy.txt",
        content_type="text/plain",
        size_bytes=4,
        checksum_sha256="c" * 64,
        uploaded_by_subject="retention-test",
    )
    old = datetime(2000, 1, 1, tzinfo=UTC)
    Ticket.objects.filter(pk=ticket.pk).update(created_at=old)
    Attachment.objects.filter(pk=attachment.pk).update(uploaded_at=old)

    with pytest.raises(CommandError, match="ownership metadata"):
        retention.Command().handle(
            dry_run=False,
            table=[],
            out=str(tmp_path / "legacy-"),
        )

    assert Ticket.objects.filter(pk=ticket.pk).exists()
    assert Attachment.objects.filter(pk=attachment.pk).exists()
    assert DisposalEvent.objects.count() == 0
    assert ObjectDeleteJob.objects.count() == 0
    assert list(tmp_path.iterdir()) == []


def test_preview_artifact_is_explicit_and_cannot_be_mistaken_for_disposal(
    monkeypatch, tmp_path
):
    cursor = FakeCursor()
    _use_fake_cursor(monkeypatch, cursor)
    monkeypatch.setattr(
        retention,
        "get_retention_policy",
        lambda: {"auditevent": {"days": 14, "description": "approved"}},
    )
    monkeypatch.setattr(
        retention.djtz, "now", lambda: datetime(2026, 7, 28, 15, 0, tzinfo=UTC)
    )
    command = retention.Command()
    command._dispose_table = MethodType(
        retention.Command._dispose_table.__wrapped__, command
    )

    command.handle(dry_run=True, table=[], out=str(tmp_path / "retention-"))

    preview = json.loads(
        (tmp_path / "retention-preview-20260728T150000Z.json").read_text(
            encoding="utf-8"
        )
    )
    assert preview["schema"] == "mhc.retention.preview.v1"
    assert preview["mode"] == "preview"
    assert preview["status"] == "not_executed"
    assert preview["rows"][0]["rows_selected"] == 0
    assert "rows_disposed" not in preview["rows"][0]


@pytest.mark.django_db(transaction=True)
def test_certificate_export_failure_leaves_committed_retriable_event(
    monkeypatch, tmp_path
):
    from apps.administration.models import ConfigItem, DisposalEvent
    from apps.audit.models import AuditEvent

    ConfigItem.objects.create(
        key="retention.policy.v1", value={"auditevent": {"days": 1}}
    )
    old_event = AuditEvent.objects.create(
        actor_subject="retention-test",
        action="retention.export.failure",
        object_type="test",
        object_id="export-failure",
        payload={},
        payload_hash="d" * 64,
    )
    AuditEvent.objects.filter(pk=old_event.pk).update(
        occurred_at=datetime(2000, 1, 1, tzinfo=UTC)
    )
    monkeypatch.setattr(
        retention.Command,
        "_write_certificate",
        staticmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk"))),
    )

    with pytest.raises(CommandError, match="retry-event"):
        retention.Command().handle(
            dry_run=False,
            table=[],
            out=str(tmp_path / "export-failure-"),
        )

    assert not AuditEvent.objects.filter(pk=old_event.pk).exists()
    disposal_event = DisposalEvent.objects.get()
    assert disposal_event.certificate_exported_at is None
    assert disposal_event.export_error == "OSError"


@pytest.mark.django_db(transaction=True)
def test_retry_event_exports_committed_truth_without_repeating_deletion(tmp_path):
    from apps.administration.models import ConfigItem, DisposalEvent
    from apps.audit.models import AuditEvent

    ConfigItem.objects.create(
        key="retention.policy.v1", value={"auditevent": {"days": 1}}
    )
    old_event = AuditEvent.objects.create(
        actor_subject="retention-test",
        action="retention.retry.export",
        object_type="test",
        object_id="retry-export",
        payload={},
        payload_hash="e" * 64,
    )
    AuditEvent.objects.filter(pk=old_event.pk).update(
        occurred_at=datetime(2000, 1, 1, tzinfo=UTC)
    )
    missing_directory = tmp_path / "later-created"
    with pytest.raises(CommandError, match="retry-event"):
        retention.Command().handle(
            dry_run=False,
            table=[],
            out=str(missing_directory / "certificate-"),
        )
    event = DisposalEvent.objects.get()
    missing_directory.mkdir()

    retention.Command().handle(
        dry_run=False,
        table=[],
        out="ignored-",
        retry_event=str(event.pk),
    )

    event.refresh_from_db()
    assert event.certificate_exported_at is not None
    event_path = Path(event.certificate_path)
    payload = json.loads(event_path.read_text(encoding="utf-8"))
    assert payload["disposal_event_id"] == str(event.pk)
    assert payload["status"] == "committed"
    assert AuditEvent.objects.filter(pk=old_event.pk).count() == 0


def test_certificate_retry_rejects_mismatched_existing_file(tmp_path):
    path = tmp_path / "certificate.json"
    path.write_text("different", encoding="utf-8")

    with pytest.raises(CommandError, match="collision"):
        retention.Command._write_certificate(path, {"status": "committed"})


def test_commit_failure_never_attempts_certificate_export(monkeypatch, tmp_path):
    from django.db import OperationalError

    class FailingCommit:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            raise OperationalError("commit failed")

    monkeypatch.setattr(
        retention,
        "get_retention_policy",
        lambda: {"auditevent": {"days": 1}},
    )
    monkeypatch.setattr(
        retention.djtz, "now", lambda: datetime(2026, 7, 28, 15, 30, tzinfo=UTC)
    )
    monkeypatch.setattr(retention.transaction, "atomic", lambda: FailingCommit())
    monkeypatch.setattr(retention.Command, "_validate_sql_plans", lambda *_args: None)
    monkeypatch.setattr(retention.Command, "_apply_run_plan", lambda *_args, **_kw: [])
    monkeypatch.setattr(retention.Command, "_create_disposal_event", lambda *_args: object())
    exported: list[object] = []
    monkeypatch.setattr(
        retention.Command,
        "_export_disposal_event",
        lambda _self, event: exported.append(event),
    )

    with pytest.raises(OperationalError, match="commit failed"):
        retention.Command().handle(
            dry_run=False,
            table=[],
            out=str(tmp_path / "commit-failure-"),
        )

    assert exported == []
    assert list(tmp_path.iterdir()) == []
