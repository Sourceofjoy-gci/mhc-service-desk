"""Retention and legal hold engine (FR-098).

Retention classes drive how long records live. The ``apply_retention``
management command disposes expired rows and writes a tamper-evident
disposal certificate per the PRD §23.4 commitment.

A ticket under ``legal_hold`` is never disposed, even if its retention
window has elapsed. Holds are set by an authorised administrator and
have an optional expiry.
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
from typing import TypedDict, TypeGuard, Unpack

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils import timezone as djtz

from .models import ConfigItem

logger = logging.getLogger(__name__)

type JSONScalar = None | bool | int | float | str
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]
type RetentionRule = dict[str, JSONValue]
type RetentionPolicy = dict[str, RetentionRule]


class DisposalCertificatePayload(TypedDict):
    issued_at: str
    table: str
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


# --- Preview retention classes (never used for destructive runs) --------

DEFAULT_RETENTION: RetentionPolicy = {
    "ticket":              {"days": 2555, "description": "7 years (operational record)"},
    "ticket_message":      {"days": 2555, "description": "tied to ticket lifecycle"},
    "ticket_note":         {"days": 2555, "description": "tied to ticket lifecycle"},
    "auditevent":          {"days": 2555, "description": "audit trail, 7 years"},
    "whatsapp_message":    {"days": 1095, "description": "3 years (channel record)"},
    "integrationevent":    {"days": 1095, "description": "3 years (integration log)"},
    "email_delivery":      {"days": 1095, "description": "3 years (delivery record)"},
    "csat_response":       {"days": 2555, "description": "7 years"},
}


@dataclass
class DisposalCertificate:
    issued_at: str
    table: str
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
            "rows_disposed": self.rows_disposed,
            "retention_class_days": self.retention_class_days,
            "cutoff": self.cutoff,
            "legal_hold_preserved": self.legal_hold_preserved,
            "payload_hash": self.payload_hash,
        }


@dataclass(frozen=True)
class RetentionSqlPlan:
    count_sql: str
    delete_sql: str
    legal_hold_count_sql: str | None = None


RETENTION_SQL_PLANS: dict[str, RetentionSqlPlan] = {
    "ticket": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM ticket WHERE created_at < %s",
        delete_sql=(
            "DELETE FROM ticket WHERE created_at < %s "
            "AND legal_hold IS NOT TRUE"
        ),
        legal_hold_count_sql=(
            "SELECT count(*) FROM ticket "
            "WHERE created_at < %s AND legal_hold = TRUE"
        ),
    ),
    "ticket_message": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM ticket_message WHERE created_at < %s",
        delete_sql=(
            "DELETE FROM ticket_message AS candidate "
            "WHERE candidate.created_at < %s AND NOT EXISTS ("
            "SELECT 1 FROM ticket AS held_ticket "
            "WHERE held_ticket.id = candidate.ticket_id "
            "AND held_ticket.legal_hold = TRUE)"
        ),
        legal_hold_count_sql=(
            "SELECT count(*) FROM ticket_message AS candidate "
            "WHERE candidate.created_at < %s AND EXISTS ("
            "SELECT 1 FROM ticket AS held_ticket "
            "WHERE held_ticket.id = candidate.ticket_id "
            "AND held_ticket.legal_hold = TRUE)"
        ),
    ),
    "ticket_note": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM ticket_note WHERE created_at < %s",
        delete_sql=(
            "DELETE FROM ticket_note AS candidate "
            "WHERE candidate.created_at < %s AND NOT EXISTS ("
            "SELECT 1 FROM ticket AS held_ticket "
            "WHERE held_ticket.id = candidate.ticket_id "
            "AND held_ticket.legal_hold = TRUE)"
        ),
        legal_hold_count_sql=(
            "SELECT count(*) FROM ticket_note AS candidate "
            "WHERE candidate.created_at < %s AND EXISTS ("
            "SELECT 1 FROM ticket AS held_ticket "
            "WHERE held_ticket.id = candidate.ticket_id "
            "AND held_ticket.legal_hold = TRUE)"
        ),
    ),
    "auditevent": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM auditevent WHERE occurred_at < %s",
        delete_sql="DELETE FROM auditevent WHERE occurred_at < %s",
    ),
    "whatsapp_message": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM whatsapp_message WHERE created_at < %s",
        delete_sql="DELETE FROM whatsapp_message WHERE created_at < %s",
    ),
    "integrationevent": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM integrationevent WHERE processed_at < %s",
        delete_sql="DELETE FROM integrationevent WHERE processed_at < %s",
    ),
    "email_delivery": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM email_delivery WHERE created_at < %s",
        delete_sql="DELETE FROM email_delivery WHERE created_at < %s",
    ),
    "csat_response": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM csat_response WHERE invited_at < %s",
        delete_sql="DELETE FROM csat_response WHERE invited_at < %s",
    ),
}


def _is_retention_policy(value: object) -> TypeGuard[RetentionPolicy]:
    return bool(value) and isinstance(value, dict) and all(
        isinstance(table, str)
        and isinstance(rule, dict)
        and type(rule.get("days")) is int
        and rule["days"] > 0
        and set(rule).issubset({"days", "description"})
        and (
            "description" not in rule or isinstance(rule["description"], str)
        )
        for table, rule in value.items()
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

    def handle(
        self,
        *args: object,
        **options: Unpack[RetentionCommandOptions],
    ) -> None:
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

        cert_path = Path(f"{out_prefix}{now.strftime('%Y%m%dT%H%M%SZ')}.json")
        if dry:
            summary = self._apply_run_plan(run_plan, dry=True)
            self._write_certificate(cert_path, summary)
        else:
            with transaction.atomic():
                self._validate_sql_plans(run_plan)
                summary = self._apply_run_plan(run_plan, dry=False)
                # Publish the complete certificate before the database commit.
                # A certificate failure therefore rolls back every deletion.
                self._write_certificate(cert_path, summary)
        self.stdout.write(self.style.SUCCESS(
            f"{'Would dispose' if dry else 'Disposed'} — certificate: {cert_path}"
        ))

    def _apply_run_plan(
        self,
        run_plan: list[tuple[str, RetentionRule, datetime]],
        *,
        dry: bool,
    ) -> list[DisposalResult]:
        return [
            self._dispose_table(table, cutoff, rule, dry)
            for table, rule, cutoff in run_plan
        ]

    def _validate_sql_plans(
        self,
        run_plan: list[tuple[str, RetentionRule, datetime]],
    ) -> None:
        """Ask PostgreSQL to plan every query before any DELETE executes."""
        from django.db import connection

        with connection.cursor() as cur:
            for table, _rule, cutoff in run_plan:
                plan = RETENTION_SQL_PLANS[table]
                statements = [plan.count_sql, plan.delete_sql]
                if plan.legal_hold_count_sql is not None:
                    statements.append(plan.legal_hold_count_sql)
                for sql in statements:
                    cur.execute(f"EXPLAIN {sql}", [cutoff])

    @staticmethod
    def _write_certificate(
        cert_path: Path,
        summary: list[DisposalResult],
    ) -> None:
        """Atomically publish a complete certificate without overwriting one."""
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
            os.link(temporary_name, cert_path)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

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
        with connection.cursor() as cur:
            if plan.legal_hold_count_sql is not None:
                cur.execute(plan.legal_hold_count_sql, [cutoff])
                rows_preserved_legal_hold = cur.fetchone()[0]
            cur.execute(plan.count_sql, [cutoff])
            total_old = cur.fetchone()[0]
            if not dry:
                cur.execute(plan.delete_sql, [cutoff])
                rows_disposed = cur.rowcount
            else:
                rows_disposed = total_old - rows_preserved_legal_hold
        rule_days = rule.get("days", 0)
        cert = DisposalCertificate(
            issued_at=datetime.now(tz=UTC).isoformat(),
            table=table,
            rows_disposed=rows_disposed,
            retention_class_days=rule_days if isinstance(rule_days, int) else 0,
            cutoff=cutoff.isoformat(),
            legal_hold_preserved=rows_preserved_legal_hold,
            payload_hash=hashlib.sha256(
                f"{table}:{cutoff}:{rows_disposed}:{rows_preserved_legal_hold}".encode()
            ).hexdigest(),
        )
        self.stdout.write(
            f"  {table:<32} cutoff={cutoff.date()} disposed={rows_disposed} "
            f"hold_kept={rows_preserved_legal_hold}"
        )
        return cert.to_payload()
