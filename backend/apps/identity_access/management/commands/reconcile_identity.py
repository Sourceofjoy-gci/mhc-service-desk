"""Relink a local user to the Keycloak subject that now represents them.

``KeycloakJWTAuthentication`` binds a local account to one Keycloak subject and
refuses to re-bind on its own: a realm user who happens to claim an existing
username would otherwise inherit that account's groups and history. When the
realm is legitimately rebuilt — ``scripts/kcclean.py`` wipes Keycloak's
database and re-imports ``realm-mhc.json``, minting new user ids — every
returning user authenticates with a subject the mirror has never seen, and
every request fails with "Local identity requires explicit reconciliation."

This command is that explicit reconciliation. It is deliberately manual, takes
the subject verbatim rather than guessing it, and leaves an audit record.

Usage::

    python manage.py reconcile_identity --username njabulo --subject <uuid>

The subject is the Keycloak user id, which is also the ``sub`` claim:

    GET /admin/realms/mhc/users?username=<username>&exact=true
"""

from __future__ import annotations

import hashlib
import json

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.audit.models import AuditEvent

from ...models import User


class Command(BaseCommand):
    help = "Bind a local user to the Keycloak subject that now identifies them."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--username",
            required=True,
            help="Local username to reconcile, e.g. njabulo.",
        )
        parser.add_argument(
            "--subject",
            required=True,
            help="Keycloak user id (the token's `sub` claim) to bind to.",
        )
        parser.add_argument(
            "--operator",
            default="cli",
            help="Who is performing the reconciliation; recorded in the audit trail.",
        )

    def handle(self, *args: object, **opts: object) -> None:
        username = str(opts["username"]).strip()
        subject = str(opts["subject"]).strip()
        operator = str(opts["operator"]).strip() or "cli"
        if not subject:
            raise CommandError("--subject must name a Keycloak subject")

        with transaction.atomic():
            user = User.objects.select_for_update().filter(username=username).first()
            if user is None:
                raise CommandError(f"No local user is named {username!r}")

            previous = user.keycloak_subject
            if previous == subject:
                self.stdout.write(f"{username} is already bound to {subject}; nothing to do.")
                return

            holder = (
                User.objects.filter(keycloak_subject=subject)
                .exclude(pk=user.pk)
                .values_list("username", flat=True)
                .first()
            )
            if holder is not None:
                raise CommandError(
                    f"Subject {subject} already belongs to {holder!r}. "
                    "Reconcile or remove that account first."
                )

            user.keycloak_subject = subject
            user.save(update_fields=["keycloak_subject"])
            _record_reconciliation(
                user=user,
                operator=operator,
                previous=previous,
                subject=subject,
            )

        self.stdout.write(
            self.style.SUCCESS(f"{username}: {previous or '(unset)'} -> {subject}")
        )


def _record_reconciliation(
    *,
    user: User,
    operator: str,
    previous: str,
    subject: str,
) -> AuditEvent:
    raw_payload = {
        "username": user.username,
        "before": {"keycloak_subject": previous},
        "after": {"keycloak_subject": subject},
    }
    canonical = json.dumps(
        raw_payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return AuditEvent.objects.create(
        actor_subject=operator,
        action="identity.subject_reconciled",
        object_type="user",
        object_id=str(user.id),
        payload=json.loads(canonical),
        payload_hash=hashlib.sha256(canonical).hexdigest(),
    )
