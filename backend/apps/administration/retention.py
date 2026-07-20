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
from datetime import UTC, datetime

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone as djtz

from .models import ConfigItem

logger = logging.getLogger(__name__)


# --- Retention classes (operator-tunable, persisted in ConfigItem) -------

DEFAULT_RETENTION = {
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


def get_retention_policy() -> dict:
    """Read the operator-tuned retention policy from ConfigItem, falling
    back to the defaults baked into this module."""
    item = ConfigItem.objects.filter(key="retention.policy.v1").first()
    if item and isinstance(item.value, dict):
        return item.value
    return DEFAULT_RETENTION


# --- Management command ----------------------------------------------------


class Command(BaseCommand):
    help = "Dispose records past their retention class. Honours legal hold."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--table", action="append", default=[])
        parser.add_argument("--out", default="backups/disposal-")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        only = set(options["table"])
        out_prefix = options["out"]
        policy = get_retention_policy()
        now = djtz.now()
        summary = []
        for table, rule in policy.items():
            if only and table not in only:
                continue
            days = rule.get("days")
            if not isinstance(days, int) or days <= 0:
                self.stdout.write(f"[skip] {table}: invalid days={days!r}")
                continue
            cutoff = now - djtz.timedelta(days=days)
            summary.append(self._dispose_table(table, cutoff, rule, dry))
        cert_path = f"{out_prefix}{now.strftime('%Y%m%dT%H%M%SZ')}.json"
        with open(cert_path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(summary, indent=2, sort_keys=True))
        self.stdout.write(self.style.SUCCESS(
            f"{'Would dispose' if dry else 'Disposed'} — certificate: {cert_path}"
        ))

    @transaction.atomic
    def _dispose_table(self, table: str, cutoff, rule: dict, dry: bool) -> dict:
        from django.db import connection
        rows_preserved_legal_hold = 0
        rows_disposed = 0
        if table in ("ticket", "ticket_message", "ticket_note"):
            # Honour legal hold: skip tickets that are under hold.
            sql_hold = f"SELECT count(*) FROM {table} WHERE legal_hold = TRUE AND created_at < %s"
        else:
            sql_hold = "SELECT 0"
        with connection.cursor() as cur:
            cur.execute(sql_hold, [cutoff])
            rows_preserved_legal_hold = cur.fetchone()[0]
            sql_count = f"SELECT count(*) FROM {table} WHERE created_at < %s"
            cur.execute(sql_count, [cutoff])
            total_old = cur.fetchone()[0]
            if not dry:
                sql_delete = f"DELETE FROM {table} WHERE created_at < %s"
                if rows_preserved_legal_hold:
                    sql_delete += " AND legal_hold IS NOT TRUE"
                cur.execute(sql_delete, [cutoff])
                rows_disposed = cur.rowcount
            else:
                rows_disposed = total_old - rows_preserved_legal_hold
        cert = DisposalCertificate(
            issued_at=datetime.now(tz=UTC).isoformat(),
            table=table,
            rows_disposed=rows_disposed,
            retention_class_days=rule.get("days", 0),
            cutoff=cutoff.isoformat(),
            legal_hold_preserved=rows_preserved_legal_hold,
            payload_hash=hashlib.sha256(
                f"{table}:{cutoff}:{rows_disposed}:{rows_preserved_legal_hold}".encode()
            ).hexdigest(),
        )
        self.stdout.write(
            f"  {table:<32} cutoff={cutoff.date()} disposed={rows_disposed} hold_kept={rows_preserved_legal_hold}"
        )
        return cert.to_json()
