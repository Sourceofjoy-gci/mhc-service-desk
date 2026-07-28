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
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import TypedDict, TypeGuard, Unpack

from django.core.management.base import BaseCommand, CommandParser
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


# --- Retention classes (operator-tunable, persisted in ConfigItem) -------

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
        count_sql="SELECT count(*) FROM auditevent WHERE created_at < %s",
        delete_sql="DELETE FROM auditevent WHERE created_at < %s",
    ),
    "whatsapp_message": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM whatsapp_message WHERE created_at < %s",
        delete_sql="DELETE FROM whatsapp_message WHERE created_at < %s",
    ),
    "integrationevent": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM integrationevent WHERE created_at < %s",
        delete_sql="DELETE FROM integrationevent WHERE created_at < %s",
    ),
    "email_delivery": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM email_delivery WHERE created_at < %s",
        delete_sql="DELETE FROM email_delivery WHERE created_at < %s",
    ),
    "csat_response": RetentionSqlPlan(
        count_sql="SELECT count(*) FROM csat_response WHERE created_at < %s",
        delete_sql="DELETE FROM csat_response WHERE created_at < %s",
    ),
}


def _is_json_value(value: object) -> TypeGuard[JSONValue]:
    if value is None or isinstance(value, bool | int | float | str):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_value(item)
            for key, item in value.items()
        )
    return False


def _is_retention_policy(value: object) -> TypeGuard[RetentionPolicy]:
    return isinstance(value, dict) and all(
        isinstance(table, str)
        and isinstance(rule, dict)
        and all(
            isinstance(key, str) and _is_json_value(item)
            for key, item in rule.items()
        )
        for table, rule in value.items()
    )


def get_retention_policy() -> RetentionPolicy:
    """Read the operator-tuned retention policy from ConfigItem, falling
    back to the defaults baked into this module."""
    item = ConfigItem.objects.filter(key="retention.policy.v1").first()
    if item:
        value: object = item.value
        if _is_retention_policy(value):
            return value
    return DEFAULT_RETENTION


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
        policy = get_retention_policy()
        now = djtz.now()
        summary: list[DisposalResult] = []
        for table, rule in policy.items():
            if only and table not in only:
                continue
            if table not in RETENTION_SQL_PLANS:
                self.stdout.write(f"[skip] {table}: unsupported retention table")
                continue
            days = rule.get("days")
            if not isinstance(days, int) or days <= 0:
                self.stdout.write(f"[skip] {table}: invalid days={days!r}")
                continue
            cutoff = now - timedelta(days=days)
            summary.append(self._dispose_table(table, cutoff, rule, dry))
        cert_path = f"{out_prefix}{now.strftime('%Y%m%dT%H%M%SZ')}.json"
        with open(cert_path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(summary, indent=2, sort_keys=True))
        self.stdout.write(self.style.SUCCESS(
            f"{'Would dispose' if dry else 'Disposed'} — certificate: {cert_path}"
        ))

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
