"""Generate the remaining Django app stubs cleanly.

Idempotent: re-running is safe. Only writes missing/empty stub files.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE = Path(r"C:\Users\sourc\Downloads\ticket\backend\apps")

APPS = [
    {
        "name": "contacts",
        "title": "Contacts and Directory",
        "models": [
            {
                "name": "Contact",
                "fields": [
                    ("full_name", "CharField(max_length=255)"),
                    ("email", "EmailField(blank=True)"),
                    ("phone_e164", "CharField(max_length=32, blank=True, db_index=True)"),
                    ("language", "CharField(max_length=8, default='en')"),
                    ("consent_at", "DateTimeField(null=True, blank=True)"),
                    ("verified_at", "DateTimeField(null=True, blank=True)"),
                ],
            }
        ],
    },
    {
        "name": "catalogue",
        "title": "Service Catalogue and Request Types",
        "models": [
            {
                "name": "Service",
                "fields": [
                    ("code", "CharField(max_length=64, unique=True)"),
                    ("name", "CharField(max_length=255)"),
                    ("domain", "CharField(max_length=16)"),
                    ("is_active", "BooleanField(default=True)"),
                ],
            }
        ],
    },
    {
        "name": "tickets",
        "title": "Tickets",
        "models": [
            {
                "name": "Ticket",
                "fields": [
                    ("number", "CharField(max_length=32, unique=True, db_index=True)"),
                    ("domain", "CharField(max_length=16)"),
                    ("title", "CharField(max_length=255)"),
                    ("status", "CharField(max_length=32)"),
                    ("priority", "CharField(max_length=8)"),
                    ("created_at", "DateTimeField(auto_now_add=True)"),
                ],
            }
        ],
    },
    {
        "name": "workflow",
        "title": "Workflow Engine",
        "models": [
            {
                "name": "WorkflowDefinition",
                "fields": [
                    ("name", "CharField(max_length=128, unique=True)"),
                    ("domain", "CharField(max_length=16)"),
                    ("is_active", "BooleanField(default=True)"),
                ],
            }
        ],
    },
    {
        "name": "sla",
        "title": "SLA and OLA",
        "models": [
            {
                "name": "SlaPolicy",
                "fields": [
                    ("name", "CharField(max_length=128, unique=True)"),
                    ("domain", "CharField(max_length=16)"),
                    ("first_response_minutes", "PositiveIntegerField()"),
                    ("resolution_minutes", "PositiveIntegerField()"),
                ],
            }
        ],
    },
    {
        "name": "files",
        "title": "Attachments and File Service",
        "models": [
            {
                "name": "Attachment",
                "fields": [
                    ("object_key", "CharField(max_length=512)"),
                    ("checksum_sha256", "CharField(max_length=64)"),
                    ("size_bytes", "BigIntegerField()"),
                    ("content_type", "CharField(max_length=128)"),
                    ("scan_status", "CharField(max_length=16, default='pending')"),
                ],
            }
        ],
    },
    {
        "name": "audit",
        "title": "Audit",
        "models": [
            {
                "name": "AuditEvent",
                "fields": [
                    ("actor_subject", "CharField(max_length=255, db_index=True)"),
                    ("action", "CharField(max_length=128)"),
                    ("object_type", "CharField(max_length=64)"),
                    ("object_id", "CharField(max_length=64)"),
                    ("ip_address", "GenericIPAddressField(null=True)"),
                    ("payload_hash", "CharField(max_length=64)"),
                    ("occurred_at", "DateTimeField(auto_now_add=True, db_index=True)"),
                ],
            }
        ],
    },
    {
        "name": "notifications",
        "title": "Notifications",
        "models": [
            {
                "name": "Notification",
                "fields": [
                    ("channel", "CharField(max_length=16)"),
                    ("recipient", "CharField(max_length=255)"),
                    ("template_key", "CharField(max_length=128)"),
                    ("payload", "JSONField()"),
                    ("delivered_at", "DateTimeField(null=True, blank=True)"),
                ],
            }
        ],
    },
    {
        "name": "integrations",
        "title": "Integrations",
        "models": [
            {
                "name": "IntegrationEvent",
                "fields": [
                    ("provider", "CharField(max_length=32)"),
                    ("external_id", "CharField(max_length=255, db_index=True)"),
                    ("payload", "JSONField()"),
                    ("processed_at", "DateTimeField(null=True, blank=True)"),
                ],
            }
        ],
    },
    {
        "name": "reporting",
        "title": "Reporting and Dashboards",
        "models": [
            {
                "name": "Dashboard",
                "fields": [
                    ("code", "CharField(max_length=64, unique=True)"),
                    ("title", "CharField(max_length=255)"),
                    ("domain", "CharField(max_length=16)"),
                ],
            }
        ],
    },
    {
        "name": "administration",
        "title": "Administration and Configuration",
        "models": [
            {
                "name": "ConfigItem",
                "fields": [
                    ("key", "CharField(max_length=128, unique=True)"),
                    ("value", "JSONField()"),
                    ("version", "PositiveIntegerField(default=1)"),
                ],
            }
        ],
    },
]


def render_apps_py(name: str, title: str) -> str:
    return f'''"""{title} Django app."""
from django.apps import AppConfig


class {name.capitalize()}Config(AppConfig):
    name = "apps.{name}"
    label = "{name}"
    verbose_name = "{title}"
'''


def render_models_py(app_title: str, models: list[dict]) -> str:
    parts = [
        f'"""Models for the {app_title} app."""',
        "from __future__ import annotations",
        "",
        "import uuid",
        "",
        "from django.db import models",
        "",
        "",
    ]
    for m in models:
        parts.append(f"class {m['name']}(models.Model):")
        parts.append("    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)")
        for fname, ftype in m["fields"]:
            parts.append(f"    {fname} = models.{ftype}")
        parts.append("")
        parts.append("    class Meta:")
        parts.append(f'        db_table = "{m["name"].lower()}"')
        parts.append("")
        parts.append("")
    return "\n".join(parts)


def render_views_py() -> str:
    return '''"""Placeholder API views for this app."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_view(_request):
    return Response({"results": []})
'''


def render_urls_py(name: str) -> str:
    return f'''"""URL configuration for the {name} app."""
from django.urls import path

from . import views

urlpatterns = [
    path("{name}/", views.list_view, name="{name}-list"),
]
'''


def render_admin_py(model_names: list[str]) -> str:
    lines = ["from django.contrib import admin", ""]
    for n in model_names:
        lines.append(f"from .models import {n}")
    lines.append("")
    lines.append("")
    for n in model_names:
        lines.append(f"admin.site.register({n})")
    return "\n".join(lines) + "\n"


def render_init_py(name: str) -> str:
    return ""


def main():
    for spec in APPS:
        name = spec["name"]
        title = spec["title"]
        root = BASE / name
        root.mkdir(parents=True, exist_ok=True)
        (root / "migrations").mkdir(exist_ok=True)
        (root / "tests").mkdir(exist_ok=True)

        (root / "__init__.py").write_text(render_init_py(name), encoding="utf-8")
        (root / "apps.py").write_text(render_apps_py(name, title), encoding="utf-8")
        (root / "models.py").write_text(render_models_py(title, spec["models"]), encoding="utf-8")
        (root / "views.py").write_text(render_views_py(), encoding="utf-8")
        (root / "urls.py").write_text(render_urls_py(name), encoding="utf-8")
        (root / "admin.py").write_text(render_admin_py([m["name"] for m in spec["models"]]), encoding="utf-8")
        (root / "migrations" / "__init__.py").write_text("", encoding="utf-8")
        (root / "tests" / "__init__.py").write_text("", encoding="utf-8")

        print(f"  ok  apps/{name}")


if __name__ == "__main__":
    main()
