"""Structured JSON log formatter for the MHC e-Ticketing platform.

The formatter redacts well-known sensitive keys before serialisation.
Never log message bodies, full contact records, or ticket content.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

REDACT_KEYS = {
    "password", "secret", "token", "authorization", "cookie",
    "id_number", "national_id", "passport", "phone", "email",
    "full_name", "address", "attachment_body",
}

_REDACT_PATTERNS = [
    (re.compile(r"Bearer\s+[A-Za-z0-9._\-]+"), "Bearer [REDACTED]"),
    (re.compile(r"eyJ[A-Za-z0-9._\-]+"), "[JWT_REDACTED]"),
]


def _scrub(value: object) -> object:
    if isinstance(value, dict):
        scrubbed: dict[object, object] = {}
        for key, item in value.items():
            should_redact = isinstance(key, str) and key.lower() in REDACT_KEYS
            scrubbed[key] = "[REDACTED]" if should_redact else _scrub(item)
        return scrubbed
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, str):
        for pat, repl in _REDACT_PATTERNS:
            value = pat.sub(repl, value)
        return value
    return value


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("correlation_id", "request_id", "actor_subject", "path", "method", "status"):
            val = record.__dict__.get(key)
            if val is not None:
                payload[key] = val
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(_scrub(payload), ensure_ascii=False)
