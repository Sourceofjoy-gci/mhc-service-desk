"""Django system checks for ticket-reference configuration."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core import checks

from .references import validate_ticket_prefix


@checks.register(checks.Tags.security)
def check_ticket_reference_prefixes(
    app_configs: Any,
    **kwargs: Any,
) -> list[checks.CheckMessage]:
    del app_configs, kwargs
    errors: list[checks.CheckMessage] = []
    configured_prefixes = (
        ("TICKET_REFERENCE_PREFIX_OPERATIONAL", "tickets.E001"),
        ("TICKET_REFERENCE_PREFIX_IT", "tickets.E002"),
    )
    valid_prefixes: list[str] = []
    for setting_key, error_id in configured_prefixes:
        try:
            valid_prefixes.append(
                validate_ticket_prefix(settings.APP_CONFIG.get(setting_key))
            )
        except ValueError:
            errors.append(
                checks.Error(
                    f"{setting_key} must be exactly one letter from A to Z.",
                    id=error_id,
                )
            )
    if len(valid_prefixes) == 2 and valid_prefixes[0] == valid_prefixes[1]:
        errors.append(
            checks.Error(
                "Operational and IT ticket reference prefixes must be distinct.",
                id="tickets.E003",
            )
        )
    return errors
