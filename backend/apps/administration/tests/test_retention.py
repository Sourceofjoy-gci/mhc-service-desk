from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
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
    ("table", "held_sql", "count_sql", "delete_sql"),
    [
        (
            "ticket",
            "SELECT count(*) FROM ticket "
            "WHERE created_at < %s AND legal_hold = TRUE",
            "SELECT count(*) FROM ticket WHERE created_at < %s",
            "DELETE FROM ticket WHERE created_at < %s "
            "AND legal_hold IS NOT TRUE",
        ),
        (
            "ticket_message",
            "SELECT count(*) FROM ticket_message AS candidate "
            "WHERE candidate.created_at < %s AND EXISTS ("
            "SELECT 1 FROM ticket AS held_ticket "
            "WHERE held_ticket.id = candidate.ticket_id "
            "AND held_ticket.legal_hold = TRUE)",
            "SELECT count(*) FROM ticket_message WHERE created_at < %s",
            "DELETE FROM ticket_message AS candidate "
            "WHERE candidate.created_at < %s AND NOT EXISTS ("
            "SELECT 1 FROM ticket AS held_ticket "
            "WHERE held_ticket.id = candidate.ticket_id "
            "AND held_ticket.legal_hold = TRUE)",
        ),
        (
            "ticket_note",
            "SELECT count(*) FROM ticket_note AS candidate "
            "WHERE candidate.created_at < %s AND EXISTS ("
            "SELECT 1 FROM ticket AS held_ticket "
            "WHERE held_ticket.id = candidate.ticket_id "
            "AND held_ticket.legal_hold = TRUE)",
            "SELECT count(*) FROM ticket_note WHERE created_at < %s",
            "DELETE FROM ticket_note AS candidate "
            "WHERE candidate.created_at < %s AND NOT EXISTS ("
            "SELECT 1 FROM ticket AS held_ticket "
            "WHERE held_ticket.id = candidate.ticket_id "
            "AND held_ticket.legal_hold = TRUE)",
        ),
    ],
)
def test_ticket_retention_uses_static_related_legal_hold_queries(
    monkeypatch, table, held_sql, count_sql, delete_sql
):
    cutoff = datetime(2026, 6, 1, tzinfo=UTC)
    results = {_compact(held_sql): 2, _compact(count_sql): 5}
    cursor = FakeCursor(results, delete_count=3)
    _use_fake_cursor(monkeypatch, cursor)

    certificate = _run_without_transaction(
        retention.Command(), table, cutoff, {"days": 30}, False
    )

    assert [sql for sql, _ in cursor.executed] == [
        _compact(held_sql),
        _compact(count_sql),
        _compact(delete_sql),
    ]
    assert all(params == [cutoff] for _, params in cursor.executed)
    assert certificate["rows_disposed"] == 3
    assert certificate["legal_hold_preserved"] == 2


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
        (
            "csat_response",
            "SELECT count(*) FROM csat_response WHERE invited_at < %s",
            "DELETE FROM csat_response WHERE invited_at < %s",
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


def test_dry_run_reports_disposable_rows_without_delete(monkeypatch):
    cutoff = datetime(2026, 6, 1, tzinfo=UTC)
    held_sql = (
        "SELECT count(*) FROM ticket WHERE created_at < %s AND legal_hold = TRUE"
    )
    count_sql = "SELECT count(*) FROM ticket WHERE created_at < %s"
    cursor = FakeCursor({held_sql: 2, count_sql: 7})
    _use_fake_cursor(monkeypatch, cursor)

    certificate = _run_without_transaction(
        retention.Command(), "ticket", cutoff, {"days": 30}, True
    )

    assert [sql for sql, _ in cursor.executed] == [held_sql, count_sql]
    assert certificate["rows_disposed"] == 5
    assert certificate["legal_hold_preserved"] == 2


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
        retention.Command._dispose_table.__wrapped__, command
    )

    command.handle(dry_run=True, table=[], out=str(tmp_path / "disposal-"))

    certificate = json.loads(
        (tmp_path / "disposal-20260728T093000Z.json").read_text(encoding="utf-8")
    )
    assert {entry["table"] for entry in certificate} == supported_tables
    assert all(entry["rows_disposed"] == 0 for entry in certificate)
    assert all(entry["payload_hash"] for entry in certificate)
    assert len(cursor.executed) == 11


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
        (tmp_path / "default-plans-20260728T120000Z.json").read_text(
            encoding="utf-8"
        )
    )
    assert {entry["table"] for entry in certificate} == set(
        retention.DEFAULT_RETENTION
    )
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


@pytest.mark.django_db
def test_certificate_write_failure_rolls_back_all_disposals(tmp_path):
    from apps.administration.models import ConfigItem
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

    with pytest.raises(FileNotFoundError):
        retention.Command().handle(
            dry_run=False,
            table=[],
            out=str(missing_directory / "certificate-"),
        )

    assert AuditEvent.objects.filter(pk=old_event.pk).exists()
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
