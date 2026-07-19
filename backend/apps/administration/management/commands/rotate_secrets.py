"""Rotate the Django secret key and other shared secrets.

A rotated key is published to the secrets store (the operator's vault
or secret manager) and the previous key is added to ``OLD_KEYS`` for the
duration of the overlap window so in-flight JWTs can be verified.

The command does not modify the database — Django sessions are invalidated
on key change and the JWT verifier (Keycloak) is unaffected.
"""
from __future__ import annotations

import secrets
import string

from django.core.management.base import BaseCommand, CommandParser


def _generate(length: int = 64) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
    return "".join(secrets.choice(alphabet) for _ in range(length))


class Command(BaseCommand):
    help = "Print a freshly generated secret. The operator commits it to the vault."

    def add_arguments(self, parser: CommandParser):
        parser.add_argument("--length", type=int, default=64)
        parser.add_argument(
            "--what",
            choices=("django", "postgres", "redis", "rabbit", "minio", "keycloak", "backup"),
            default="django",
        )

    def handle(self, *args, **opts):
        new = _generate(opts["length"])
        self.stdout.write(self.style.SUCCESS(
            f"New {opts['what']} secret ({len(new)} chars). Update the vault, then redeploy."
        ))
        self.stdout.write(new)
