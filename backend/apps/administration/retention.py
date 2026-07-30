"""Retention and legal hold engine (FR-098).

Retention classes drive how long records live. The ``apply_retention``
management command disposes expired rows and writes a tamper-evident
disposal certificate per the PRD §23.4 commitment.

A ticket under ``legal_hold`` is never disposed, even if its retention
window has elapsed. A held message or note also preserves its parent ticket
and required graph. Holds are set by an authorised administrator and have an
optional expiry.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, TypeGuard, Unpack, cast
from uuid import UUID, uuid4

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection, transaction
from django.db.models import Exists, OuterRef, Q
from django.db.models.deletion import Collector
from django.utils import timezone as djtz

from .models import ConfigItem, DisposalEvent

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet

logger = logging.getLogger(__name__)

type JSONScalar = None | bool | int | float | str
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]
type RetentionRule = dict[str, JSONValue]
type RetentionPolicy = dict[str, RetentionRule]


class DisposalCertificatePayload(TypedDict):
    issued_at: str
    table: str
    rows_selected: int
    rows_disposed: int
    retention_class_days: int
    cutoff: str
    legal_hold_preserved: int
    payload_hash: str


type DisposalResult = DisposalCertificatePayload | dict[str, JSONValue]


class RetentionCommandOptions(TypedDict):
    dry_run: bool
    table: list[str]
    out: str
    retry_event: str | None


# --- Preview retention classes (never used for destructive runs) --------

DEFAULT_RETENTION: RetentionPolicy = {
    "ticket": {"days": 2555, "description": "7 years (operational record)"},
    "ticket_message": {"days": 2555, "description": "tied to ticket lifecycle"},
    "ticket_note": {"days": 2555, "description": "tied to ticket lifecycle"},
    "auditevent": {"days": 2555, "description": "audit trail, 7 years"},
    "whatsapp_message": {"days": 1095, "description": "3 years (channel record)"},
    "integrationevent": {"days": 1095, "description": "3 years (integration log)"},
    "email_delivery": {"days": 1095, "description": "3 years (delivery record)"},
    "csat_response": {"days": 2555, "description": "7 years"},
}


@dataclass
class DisposalCertificate:
    issued_at: str
    table: str
    rows_selected: int
    rows_disposed: int
    retention_class_days: int
    cutoff: str
    legal_hold_preserved: int
    payload_hash: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    def to_payload(self) -> DisposalCertificatePayload:
        return {
            "issued_at": self.issued_at,
            "table": self.table,
            "rows_selected": self.rows_selected,
            "rows_disposed": self.rows_disposed,
            "retention_class_days": self.retention_class_days,
            "cutoff": self.cutoff,
            "legal_hold_preserved": self.legal_hold_preserved,
            "payload_hash": self.payload_hash,
        }


@dataclass(frozen=True)
class RetentionSqlPlan:
    count_sql: str
    delete_sql: str | None
    legal_hold_count_sql: str | None = None
    orm_model_label: str | None = None


@dataclass(frozen=True)
class OrmDisposalCounts:
    rows_selected: int
    rows_disposed: int
    legal_hold_preserved: int


RETENTION_SQL_PLANS: dict[str, RetentionSqlPlan] = {
    "ticket": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM ticket WHERE created_at < %s",
        delete_sql=None,
        legal_hold_count_sql=(
            "SELECT count(*) FROM ticket AS candidate "
            "WHERE candidate.created_at < %s AND ("
            "candidate.legal_hold = TRUE OR EXISTS ("
            "SELECT 1 FROM ticket_message AS held_message "
            "WHERE held_message.ticket_id = candidate.id "
            "AND held_message.legal_hold = TRUE) OR EXISTS ("
            "SELECT 1 FROM ticket_note AS held_note "
            "WHERE held_note.ticket_id = candidate.id "
            "AND held_note.legal_hold = TRUE))"
        ),
        orm_model_label="tickets.Ticket",
    ),
    "ticket_message": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM ticket_message WHERE created_at < %s",
        delete_sql=None,
        legal_hold_count_sql=(
            "SELECT count(*) FROM ticket_message AS candidate "
            "WHERE candidate.created_at < %s AND ("
            "candidate.legal_hold = TRUE OR EXISTS ("
            "SELECT 1 FROM ticket AS held_ticket "
            "WHERE held_ticket.id = candidate.ticket_id "
            "AND held_ticket.legal_hold = TRUE))"
        ),
        orm_model_label="tickets.TicketMessage",
    ),
    "ticket_note": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM ticket_note WHERE created_at < %s",
        delete_sql=None,
        legal_hold_count_sql=(
            "SELECT count(*) FROM ticket_note AS candidate "
            "WHERE candidate.created_at < %s AND ("
            "candidate.legal_hold = TRUE OR EXISTS ("
            "SELECT 1 FROM ticket AS held_ticket "
            "WHERE held_ticket.id = candidate.ticket_id "
            "AND held_ticket.legal_hold = TRUE))"
        ),
        orm_model_label="tickets.TicketNote",
    ),
    "auditevent": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM auditevent WHERE occurred_at < %s",
        delete_sql="DELETE FROM auditevent WHERE occurred_at < %s",
    ),
    "whatsapp_message": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM whatsapp_message WHERE created_at < %s",
        delete_sql=None,
        orm_model_label="whatsapp.WhatsappMessage",
    ),
    "integrationevent": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM integrationevent WHERE processed_at < %s",
        delete_sql="DELETE FROM integrationevent WHERE processed_at < %s",
    ),
    "email_delivery": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM email_delivery WHERE created_at < %s",
        delete_sql=None,
        orm_model_label="email_channel.EmailDelivery",
    ),
    "csat_response": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM csat_response WHERE invited_at < %s",
        delete_sql=None,
        orm_model_label="csat.CsatResponse",
    ),
}


def _is_retention_policy(value: object) -> TypeGuard[RetentionPolicy]:
    return (
        bool(value)
        and isinstance(value, dict)
        and all(
            isinstance(table, str)
            and isinstance(rule, dict)
            and type(rule.get("days")) is int
            and rule["days"] > 0
            and set(rule).issubset({"days", "description"})
            and ("description" not in rule or isinstance(rule["description"], str))
            for table, rule in value.items()
        )
    )


def get_retention_policy() -> RetentionPolicy | None:
    """Return the explicitly configured retention policy, if one exists.

    The baked-in schedule is preview-only because the PRD requires formal
    approval before production disposal.
    """
    item = ConfigItem.objects.filter(key="retention.policy.v1").first()
    if item is None:
        return None
    value: object = item.value
    if not _is_retention_policy(value):
        raise CommandError(
            "retention.policy.v1 is invalid; expected a non-empty mapping of "
            "supported table names to positive integer days"
        )
    return value


# --- Management command ----------------------------------------------------


class Command(BaseCommand):
    help = "Dispose records past their retention class. Honours legal hold."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--table", action="append", default=[])
        parser.add_argument("--out", default="backups/disposal-")
        parser.add_argument("--retry-event")

    def handle(
        self,
        *args: object,
        **options: Unpack[RetentionCommandOptions],
    ) -> None:
        retry_event = options.get("retry_event")
        if retry_event:
            self._retry_disposal_event(retry_event)
            return
        dry = options["dry_run"]
        only = set(options["table"])
        out_prefix = options["out"]
        configured_policy = get_retention_policy()
        if configured_policy is None:
            if not dry:
                raise CommandError(
                    "No configured retention policy. Create an approved "
                    "retention.policy.v1 ConfigItem before a destructive run."
                )
            policy = DEFAULT_RETENTION
            self.stderr.write(
                self.style.WARNING(
                    "No configured retention policy; showing the unapproved "
                    "preview schedule only."
                )
            )
        else:
            policy = configured_policy

        unsupported = set(policy) - set(RETENTION_SQL_PLANS)
        if unsupported:
            names = ", ".join(sorted(unsupported))
            raise CommandError(f"unsupported retention table(s): {names}")
        missing = only - set(policy)
        if missing:
            names = ", ".join(sorted(missing))
            raise CommandError(f"table(s) not present in retention policy: {names}")

        now = djtz.now()
        run_plan: list[tuple[str, RetentionRule, datetime]] = []
        for table, rule in policy.items():
            if only and table not in only:
                continue
            days = rule.get("days")
            if type(days) is not int or days <= 0:
                raise CommandError(f"invalid retention days for {table}: {days!r}")
            cutoff = now - timedelta(days=days)
            run_plan.append((table, rule, cutoff))

        self._active_cutoffs: dict[str, datetime] = {}
        for table, rule in policy.items():
            days_value = rule["days"]
            if type(days_value) is not int:
                raise CommandError(f"invalid retention days for {table}: {days_value!r}")
            self._active_cutoffs[table] = now - timedelta(days=days_value)

        if dry:
            summary = self._apply_run_plan(run_plan, dry=True)
            preview_path = Path(f"{out_prefix}preview-{now.strftime('%Y%m%dT%H%M%SZ')}.json")
            preview: dict[str, JSONValue] = {
                "schema": "mhc.retention.preview.v1",
                "mode": "preview",
                "status": "not_executed",
                "generated_at": now.isoformat(),
                "policy_source": (
                    "configured" if configured_policy is not None else "unapproved_default"
                ),
                "rows": cast(JSONValue, summary),
            }
            self._write_certificate(preview_path, preview)
            self.stdout.write(self.style.SUCCESS(f"Would dispose - preview: {preview_path}"))
            return

        event_id = uuid4()
        cert_path = Path(f"{out_prefix}{now.strftime('%Y%m%dT%H%M%SZ')}-{event_id}.json")
        with transaction.atomic():
            self._validate_sql_plans(run_plan)
            event = self._create_disposal_event(
                event_id=event_id,
                policy=policy,
                cert_path=cert_path,
            )
            self._active_event = event
            summary = self._apply_run_plan(run_plan, dry=False)
            self._finalize_disposal_event(event, summary)
        event.refresh_from_db()
        if event.object_cleanup_completed_at is not None:
            self._export_disposal_event(event)
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Database disposal committed as event {event.pk}; "
                    "certificate awaits durable object cleanup."
                )
            )

    @staticmethod
    def _canonical_json(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    def _create_disposal_event(
        self,
        *,
        event_id: UUID,
        policy: RetentionPolicy,
        cert_path: Path,
    ) -> DisposalEvent:
        policy_json = self._canonical_json(policy)
        return DisposalEvent.objects.create(
            id=event_id,
            policy_snapshot=policy,
            policy_hash=hashlib.sha256(policy_json.encode()).hexdigest(),
            summary=[],
            summary_hash=hashlib.sha256(b"[]").hexdigest(),
            certificate_path=str(cert_path),
        )

    def _finalize_disposal_event(self, event: DisposalEvent, summary: list[DisposalResult]) -> None:
        from apps.files.models import ObjectDeleteJob

        event.summary = summary
        event.summary_hash = hashlib.sha256(self._canonical_json(summary).encode()).hexdigest()
        if not ObjectDeleteJob.objects.filter(
            disposal_event=event, completed_at__isnull=True
        ).exists():
            event.object_cleanup_completed_at = djtz.now()
        event.save(
            update_fields=(
                "summary",
                "summary_hash",
                "object_cleanup_completed_at",
            )
        )

    @staticmethod
    def _certificate_payload(event: DisposalEvent) -> dict[str, JSONValue]:
        return {
            "schema": "mhc.retention.disposal-certificate.v1",
            "mode": "execute",
            "status": "committed",
            "disposal_event_id": str(event.pk),
            "committed_at": event.created_at.isoformat(),
            "policy_hash": event.policy_hash,
            "summary_hash": event.summary_hash,
            "summary": event.summary,
            "object_cleanup": "complete",
            "object_cleanup_jobs": event.object_delete_jobs.count(),
        }

    def _export_disposal_event(self, event: DisposalEvent) -> None:
        if event.object_cleanup_completed_at is None:
            raise CommandError("Object cleanup is still pending for this disposal event.")
        try:
            self._write_certificate(Path(event.certificate_path), self._certificate_payload(event))
        except Exception as exc:
            DisposalEvent.objects.filter(pk=event.pk).update(export_error=type(exc).__name__)
            raise CommandError(
                f"Certificate export failed for committed event {event.pk}; "
                f"retry with --retry-event {event.pk}."
            ) from exc
        DisposalEvent.objects.filter(pk=event.pk).update(
            certificate_exported_at=djtz.now(), export_error=""
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Disposed - committed event {event.pk}; certificate: " f"{event.certificate_path}"
            )
        )

    def _retry_disposal_event(self, event_id: str) -> None:
        try:
            event = DisposalEvent.objects.get(pk=event_id)
        except (DisposalEvent.DoesNotExist, ValueError) as exc:
            raise CommandError(f"Unknown disposal event: {event_id}") from exc
        self._export_disposal_event(event)

    def _apply_run_plan(
        self,
        run_plan: list[tuple[str, RetentionRule, datetime]],
        *,
        dry: bool,
    ) -> list[DisposalResult]:
        return [self._dispose_table(table, cutoff, rule, dry) for table, rule, cutoff in run_plan]

    def _validate_sql_plans(
        self,
        run_plan: list[tuple[str, RetentionRule, datetime]],
    ) -> None:
        """Ask PostgreSQL to plan every query before any DELETE executes."""
        from django.db import connection

        self._validate_collector_graph_contract()
        with connection.cursor() as cur:
            for table, _rule, cutoff in run_plan:
                plan = RETENTION_SQL_PLANS[table]
                statements = [plan.count_sql]
                if plan.delete_sql is not None:
                    statements.append(plan.delete_sql)
                if plan.legal_hold_count_sql is not None:
                    statements.append(plan.legal_hold_count_sql)
                for sql in statements:
                    cur.execute(f"EXPLAIN {sql}", [cutoff])
                if plan.orm_model_label is not None:
                    queryset = self._orm_disposal_queryset(table, cutoff).values("pk")
                    sql, params = queryset.query.sql_with_params()
                    cur.execute(f"EXPLAIN {sql}", params)

    @staticmethod
    def _validate_collector_graph_contract() -> None:
        """Fail closed when an unreviewed reverse relation changes a cascade graph."""
        from apps.tickets.models import Ticket, TicketMessage

        expected = {
            "tickets.Ticket": {
                ("tickets.TicketMessage", "ticket", "CASCADE"),
                ("tickets.TicketNote", "ticket", "CASCADE"),
                ("tickets.TicketLink", "from_ticket", "CASCADE"),
                ("tickets.TicketLink", "to_ticket", "CASCADE"),
                ("tickets.Watcher", "ticket", "CASCADE"),
                ("tickets.TicketCustodyEvent", "ticket", "DO_NOTHING"),
                ("workflow.TransitionHistory", "ticket", "CASCADE"),
                ("sla.SlaInstance", "ticket", "CASCADE"),
                ("files.Attachment", "ticket", "CASCADE"),
                ("whatsapp.WhatsappMessage", "ticket", "SET_NULL"),
                ("knowledge.KnowledgeUsageLog", "ticket", "SET_NULL"),
                ("csat.CsatResponse", "ticket", "CASCADE"),
            },
            "tickets.TicketMessage": {
                ("email_channel.EmailDelivery", "ticket_message", "CASCADE"),
                ("files.Attachment", "message", "SET_NULL"),
            },
        }
        for model in (Ticket, TicketMessage):
            actual = {
                (
                    relation.related_model._meta.label,
                    relation.field.name,
                    relation.on_delete.__name__,
                )
                for relation in cast("Any", model._meta).related_objects
            }
            if actual != expected[model._meta.label]:
                raise CommandError(
                    f"Retention graph contract changed for {model._meta.label}; "
                    "review dependency ages, legal holds, and object cleanup before "
                    "running disposal."
                )

    @staticmethod
    def _held_ticket_ids() -> QuerySet[Model]:
        from apps.tickets.models import Ticket

        return cast(
            "QuerySet[Model]",
            Ticket.objects.filter(
                Q(legal_hold=True) | Q(messages__legal_hold=True) | Q(notes__legal_hold=True)
            ).values("pk"),
        )

    def _relation_blocks_parent(
        self,
        queryset: QuerySet[Model],
        related_queryset: QuerySet[Model],
        *,
        cutoff_name: str | None,
        timestamp_field: str,
        fallback_cutoff: datetime,
    ) -> QuerySet[Model]:
        cutoff = (
            getattr(self, "_active_cutoffs", {}).get(cutoff_name)
            if cutoff_name is not None
            else fallback_cutoff
        )
        if cutoff is None:
            blocking = related_queryset
        else:
            blocking = related_queryset.filter(**{f"{timestamp_field}__gte": cutoff})
        return queryset.exclude(Exists(blocking))

    def _orm_disposal_queryset(self, table: str, cutoff: datetime) -> QuerySet[Model]:
        """Return graph-held and dependency-age-aware disposal candidates."""
        from apps.csat.models import CsatResponse
        from apps.email_channel.models import EmailDelivery
        from apps.files.models import Attachment, AttachmentAccessLog
        from apps.knowledge.models import KnowledgeUsageLog
        from apps.sla.models import SlaInstance, SlaPauseHistory
        from apps.tickets.models import (
            Ticket,
            TicketLink,
            TicketMessage,
            TicketNote,
            Watcher,
        )
        from apps.whatsapp.models import WhatsappMessage
        from apps.workflow.models import TransitionHistory

        held_ticket_ids = self._held_ticket_ids()
        if table == "ticket":
            queryset: QuerySet[Model] = Ticket.objects.filter(created_at__lt=cutoff).exclude(
                pk__in=held_ticket_ids
            )
            relations: tuple[tuple[QuerySet[Model], str | None, str], ...] = (
                (
                    TicketMessage.objects.filter(ticket_id=OuterRef("pk")),
                    "ticket_message",
                    "created_at",
                ),
                (
                    TicketNote.objects.filter(ticket_id=OuterRef("pk")),
                    "ticket_note",
                    "created_at",
                ),
                (
                    EmailDelivery.objects.filter(ticket_message__ticket_id=OuterRef("pk")),
                    "email_delivery",
                    "created_at",
                ),
                (
                    WhatsappMessage.objects.filter(ticket_id=OuterRef("pk")),
                    "whatsapp_message",
                    "created_at",
                ),
                (
                    CsatResponse.objects.filter(ticket_id=OuterRef("pk")),
                    "csat_response",
                    "invited_at",
                ),
                (
                    Attachment.objects.filter(ticket_id=OuterRef("pk")),
                    None,
                    "uploaded_at",
                ),
                (
                    AttachmentAccessLog.objects.filter(attachment__ticket_id=OuterRef("pk")),
                    None,
                    "at",
                ),
                (
                    TransitionHistory.objects.filter(ticket_id=OuterRef("pk")),
                    None,
                    "occurred_at",
                ),
                (
                    SlaInstance.objects.filter(ticket_id=OuterRef("pk")),
                    None,
                    "updated_at",
                ),
                (
                    SlaPauseHistory.objects.filter(instance__ticket_id=OuterRef("pk")),
                    None,
                    "at",
                ),
                (
                    Watcher.objects.filter(ticket_id=OuterRef("pk")),
                    None,
                    "created_at",
                ),
                (
                    TicketLink.objects.filter(from_ticket_id=OuterRef("pk")),
                    None,
                    "created_at",
                ),
                (
                    TicketLink.objects.filter(to_ticket_id=OuterRef("pk")),
                    None,
                    "created_at",
                ),
                (
                    KnowledgeUsageLog.objects.filter(ticket_id=OuterRef("pk")),
                    None,
                    "used_at",
                ),
            )
            for related, cutoff_name, timestamp_field in relations:
                queryset = self._relation_blocks_parent(
                    queryset,
                    related,
                    cutoff_name=cutoff_name,
                    timestamp_field=timestamp_field,
                    fallback_cutoff=cutoff,
                )
            return queryset
        if table == "ticket_message":
            queryset = TicketMessage.objects.filter(created_at__lt=cutoff).exclude(
                ticket_id__in=held_ticket_ids
            )
            for related, cutoff_name, timestamp_field in (
                (
                    EmailDelivery.objects.filter(ticket_message_id=OuterRef("pk")),
                    "email_delivery",
                    "created_at",
                ),
                (
                    Attachment.objects.filter(message_id=OuterRef("pk")),
                    None,
                    "uploaded_at",
                ),
            ):
                queryset = self._relation_blocks_parent(
                    queryset,
                    related,
                    cutoff_name=cutoff_name,
                    timestamp_field=timestamp_field,
                    fallback_cutoff=cutoff,
                )
            return queryset
        if table == "ticket_note":
            return TicketNote.objects.filter(created_at__lt=cutoff).exclude(
                ticket_id__in=held_ticket_ids
            )
        if table == "whatsapp_message":
            return WhatsappMessage.objects.filter(created_at__lt=cutoff).exclude(
                ticket_id__in=held_ticket_ids
            )
        if table == "email_delivery":
            return EmailDelivery.objects.filter(created_at__lt=cutoff).exclude(
                ticket_message__ticket_id__in=held_ticket_ids
            )
        if table == "csat_response":
            return CsatResponse.objects.filter(invited_at__lt=cutoff).exclude(
                ticket_id__in=held_ticket_ids
            )
        raise ValueError(f"No ORM retention plan for {table}")

    def _orm_base_queryset(self, table: str, cutoff: datetime) -> QuerySet[Model]:
        from apps.csat.models import CsatResponse
        from apps.email_channel.models import EmailDelivery
        from apps.tickets.models import Ticket, TicketMessage, TicketNote
        from apps.whatsapp.models import WhatsappMessage

        if table == "ticket":
            return Ticket.objects.filter(created_at__lt=cutoff)
        if table == "ticket_message":
            return TicketMessage.objects.filter(created_at__lt=cutoff)
        if table == "ticket_note":
            return TicketNote.objects.filter(created_at__lt=cutoff)
        if table == "whatsapp_message":
            return WhatsappMessage.objects.filter(created_at__lt=cutoff)
        if table == "email_delivery":
            return EmailDelivery.objects.filter(created_at__lt=cutoff)
        if table == "csat_response":
            return CsatResponse.objects.filter(invited_at__lt=cutoff)
        raise ValueError(f"No ORM retention plan for {table}")

    def _candidate_ticket_ids(self, table: str, cutoff: datetime) -> list[object]:
        queryset = self._orm_base_queryset(table, cutoff)
        if table == "ticket":
            return list(queryset.values_list("pk", flat=True))
        if table in {"ticket_message", "ticket_note", "whatsapp_message", "csat_response"}:
            return list(queryset.exclude(ticket_id=None).values_list("ticket_id", flat=True))
        if table == "email_delivery":
            return list(queryset.values_list("ticket_message__ticket_id", flat=True))
        return []

    def _lock_hold_graph(self, ticket_ids: list[object]) -> None:
        from apps.tickets.models import Ticket, TicketMessage, TicketNote

        if not ticket_ids:
            return
        list(
            Ticket.objects.select_for_update()
            .filter(pk__in=ticket_ids)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        list(
            TicketMessage.objects.select_for_update()
            .filter(ticket_id__in=ticket_ids)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        list(
            TicketNote.objects.select_for_update()
            .filter(ticket_id__in=ticket_ids)
            .order_by("pk")
            .values_list("pk", flat=True)
        )

    def _enqueue_attachment_jobs(self, ticket_ids: list[object]) -> None:
        from apps.files.models import Attachment, ObjectDeleteJob

        if not ticket_ids:
            return
        attachments = list(
            Attachment.objects.select_for_update().filter(ticket_id__in=ticket_ids).order_by("pk")
        )
        missing = [
            attachment
            for attachment in attachments
            if not attachment.object_bucket or not attachment.object_version_id
        ]
        if missing:
            raise CommandError(
                "Attachment ownership metadata is incomplete; retention failed closed."
            )
        event = getattr(self, "_active_event", None)
        if attachments and event is None:
            raise CommandError("A committed disposal event is required for object cleanup.")
        ObjectDeleteJob.objects.bulk_create(
            [
                ObjectDeleteJob(
                    disposal_event=event,
                    source_attachment_id=attachment.pk,
                    bucket=attachment.object_bucket,
                    object_key=attachment.object_key,
                    version_id=attachment.object_version_id,
                    etag=attachment.object_etag,
                    next_attempt_at=djtz.now(),
                )
                for attachment in attachments
            ]
        )

    def _delete_with_orm(self, table: str, cutoff: datetime, model_label: str) -> OrmDisposalCounts:
        if (
            table == "ticket"
            and connection.vendor == "postgresql"
            and not connection.in_atomic_block
        ):
            raise CommandError("Ticket custody disposal requires an active database transaction.")
        ticket_ids = self._candidate_ticket_ids(table, cutoff)
        self._lock_hold_graph(ticket_ids)
        rows_preserved_legal_hold = self._orm_held_count(table, cutoff)
        candidate_ids = list(
            self._orm_disposal_queryset(table, cutoff).values_list("pk", flat=True)
        )
        rows_selected = len(candidate_ids)
        if table == "ticket":
            self._enqueue_attachment_jobs(candidate_ids)
        if not candidate_ids:
            return OrmDisposalCounts(
                rows_selected=rows_selected,
                rows_disposed=0,
                legal_hold_preserved=rows_preserved_legal_hold,
            )
        queryset = self._orm_base_queryset(table, cutoff).filter(pk__in=candidate_ids)
        if table == "ticket":
            from apps.tickets.models import Ticket

            queryset = Ticket._base_manager.filter(pk__in=candidate_ids)
            collector = Collector(using=connection.alias)
            collector.collect(list(queryset))
            _total_deleted, deleted_by_model = collector.delete()
            disposed = deleted_by_model.get("tickets.Ticket", 0)
            return OrmDisposalCounts(
                rows_selected=rows_selected,
                rows_disposed=disposed,
                legal_hold_preserved=rows_preserved_legal_hold,
            )
        _total_deleted, deleted_by_model = queryset.delete()
        return OrmDisposalCounts(
            rows_selected=rows_selected,
            rows_disposed=deleted_by_model.get(model_label, 0),
            legal_hold_preserved=rows_preserved_legal_hold,
        )

    def _orm_held_count(self, table: str, cutoff: datetime) -> int:
        held_ticket_ids = self._held_ticket_ids()
        queryset = self._orm_base_queryset(table, cutoff)
        if table == "ticket":
            return queryset.filter(pk__in=held_ticket_ids).count()
        if table in {
            "ticket_message",
            "ticket_note",
            "whatsapp_message",
            "csat_response",
        }:
            return queryset.filter(ticket_id__in=held_ticket_ids).count()
        if table == "email_delivery":
            return queryset.filter(ticket_message__ticket_id__in=held_ticket_ids).count()
        return 0

    @staticmethod
    def _write_certificate(
        cert_path: Path,
        summary: JSONValue | list[DisposalResult],
    ) -> None:
        """Atomically publish canonical bytes, idempotently on exact match."""
        payload = json.dumps(summary, indent=2, sort_keys=True)
        fd, temporary_name = tempfile.mkstemp(
            dir=cert_path.parent,
            prefix=f".{cert_path.name}.",
            suffix=".tmp",
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            try:
                os.link(temporary_name, cert_path)
            except FileExistsError:
                if cert_path.read_text(encoding="utf-8") != payload:
                    raise CommandError(
                        f"Certificate path collision with different content: {cert_path}"
                    ) from None
            Command._fsync_parent_directory(cert_path)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

    @staticmethod
    def _fsync_parent_directory(cert_path: Path) -> None:
        """Make the newly linked certificate directory entry crash-durable."""
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(cert_path.parent, flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @transaction.atomic
    def _dispose_table(
        self,
        table: str,
        cutoff: datetime,
        rule: RetentionRule,
        dry: bool,
    ) -> DisposalResult:
        from django.db import connection

        plan = RETENTION_SQL_PLANS.get(table)
        if plan is None:
            self.stdout.write(f"[skip] {table}: unsupported retention table")
            return {}
        rows_preserved_legal_hold = 0
        rows_disposed = 0
        if plan.orm_model_label is not None:
            if dry:
                rows_preserved_legal_hold = self._orm_held_count(table, cutoff)
                rows_selected = self._orm_disposal_queryset(table, cutoff).count()
            else:
                counts = self._delete_with_orm(table, cutoff, plan.orm_model_label)
                rows_selected = counts.rows_selected
                rows_disposed = counts.rows_disposed
                rows_preserved_legal_hold = counts.legal_hold_preserved
        else:
            with connection.cursor() as cur:
                if plan.legal_hold_count_sql is not None:
                    cur.execute(plan.legal_hold_count_sql, [cutoff])
                    rows_preserved_legal_hold = cur.fetchone()[0]
                cur.execute(plan.count_sql, [cutoff])
                total_old = cur.fetchone()[0]
                rows_selected = total_old - rows_preserved_legal_hold
                if not dry and plan.delete_sql is not None:
                    cur.execute(plan.delete_sql, [cutoff])
                    rows_disposed = cur.rowcount
        rule_days = rule.get("days", 0)
        if dry:
            preview_hash = hashlib.sha256(
                f"preview:{table}:{cutoff}:{rows_selected}:" f"{rows_preserved_legal_hold}".encode()
            ).hexdigest()
            self.stdout.write(
                f"  {table:<32} cutoff={cutoff.date()} selected={rows_selected} "
                f"hold_kept={rows_preserved_legal_hold}"
            )
            return {
                "table": table,
                "rows_selected": rows_selected,
                "retention_class_days": (rule_days if isinstance(rule_days, int) else 0),
                "cutoff": cutoff.isoformat(),
                "legal_hold_preserved": rows_preserved_legal_hold,
                "selection_hash": preview_hash,
            }
        cert = DisposalCertificate(
            issued_at=datetime.now(tz=UTC).isoformat(),
            table=table,
            rows_selected=rows_selected,
            rows_disposed=rows_disposed,
            retention_class_days=rule_days if isinstance(rule_days, int) else 0,
            cutoff=cutoff.isoformat(),
            legal_hold_preserved=rows_preserved_legal_hold,
            payload_hash=hashlib.sha256(
                f"{table}:{cutoff}:{rows_selected}:{rows_disposed}:"
                f"{rows_preserved_legal_hold}".encode()
            ).hexdigest(),
        )
        self.stdout.write(
            f"  {table:<32} cutoff={cutoff.date()} disposed={rows_disposed} "
            f"hold_kept={rows_preserved_legal_hold}"
        )
        return cert.to_payload()
