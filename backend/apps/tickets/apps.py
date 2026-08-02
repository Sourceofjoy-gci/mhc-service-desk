"""Tickets Django app."""
from django.apps import AppConfig


class TicketsConfig(AppConfig):
    name = "apps.tickets"
    label = "tickets"
    verbose_name = "Tickets"

    def ready(self) -> None:
        from . import checks  # noqa: F401
