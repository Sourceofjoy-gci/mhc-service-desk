"""User model bound to Keycloak.

Local users mirror Keycloak subjects so the application can enforce
server-side authorization even when Keycloak is briefly unreachable.
Sensitive domain never lives in this model.
"""
from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Local mirror of a Keycloak user."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    keycloak_subject = models.CharField(max_length=255, unique=True, db_index=True)
    display_name = models.CharField(max_length=255, blank=True)
    mfa_enabled = models.BooleanField(default=False)
    last_keycloak_sync = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "identity_user"
        indexes = [
            models.Index(fields=["keycloak_subject"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return self.display_name or self.username


class Role(models.Model):
    """Reconciliation of Keycloak realm roles with application permissions."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    keycloak_role = models.CharField(max_length=128, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    # List of {"domain", "office", "service", "queue"} dictionaries.
    scopes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "identity_role"

    def __str__(self) -> str:  # pragma: no cover
        return self.name


class UserRole(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_roles")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="user_roles")
    office = models.ForeignKey(
        "organisations.Office",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="user_roles",
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "identity_user_role"
        unique_together = [("user", "role", "office")]

    def __str__(self) -> str:
        return f"{self.user}: {self.role}"


class AuditLogin(models.Model):
    """Append-only login audit. Mirrors Keycloak events for forensic review."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    keycloak_subject = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField(null=True)
    user_agent = models.CharField(max_length=512, blank=True)
    mfa_used = models.BooleanField(default=False)
    success = models.BooleanField()
    failure_reason = models.CharField(max_length=255, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "identity_login_audit"

    def __str__(self) -> str:
        outcome = "success" if self.success else "failure"
        return f"{self.keycloak_subject}: {outcome}"
