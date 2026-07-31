"""Ticket aggregate — the centre of the platform.

This is the source of truth for the ticket lifecycle. Cross-module writes
to this table go through `services.TicketService` so invariants are enforced
inside a single DB transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.utils import timezone


class ProtectedTicketQuerySet(models.QuerySet["Ticket"]):
    """Prevent ordinary application code from deleting ticket aggregates."""

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValidationError("Tickets may only be deleted by approved retention.")

    def _raw_delete(self, using: str) -> int:
        raise ValidationError("Tickets may only be deleted by approved retention.")


class Ticket(models.Model):
    """A unit of work tracked from intake to closure."""

    class Priority(models.TextChoices):
        P1 = "P1", "P1 Critical"
        P2 = "P2", "P2 High"
        P3 = "P3", "P3 Normal"
        P4 = "P4", "P4 Low"

    class Domain(models.TextChoices):
        OPERATIONAL = "operational", "Operational"
        IT = "it", "IT"

    class Channel(models.TextChoices):
        CALL = "call", "Call centre"
        WALK_IN = "walk_in", "Walk-in"
        WEB = "web", "Public web form"
        EMAIL = "email", "Email"
        INTERNAL = "internal", "Internal referral"
        WHATSAPP = "whatsapp", "WhatsApp"  # P1
        MONITORING = "monitoring", "Monitoring"  # P2

    class Confidentiality(models.TextChoices):
        NORMAL = "normal", "Normal"
        SENSITIVE = "sensitive", "Sensitive"
        RESTRICTED = "restricted", "Restricted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=32, unique=True, db_index=True)
    domain = models.CharField(max_length=16, choices=Domain.choices)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.ForeignKey("workflow.Status", on_delete=models.PROTECT, related_name="tickets")
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.P3)
    channel = models.CharField(max_length=16, choices=Channel.choices)
    source_account = models.CharField(max_length=255, blank=True)

    requester = models.ForeignKey(
        "contacts.Contact", on_delete=models.PROTECT, related_name="requested_tickets"
    )
    organisation = models.ForeignKey(
        "contacts.Organisation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
    )
    service = models.ForeignKey(
        "catalogue.Service", on_delete=models.PROTECT, related_name="tickets"
    )
    request_type = models.ForeignKey(
        "catalogue.RequestType", on_delete=models.PROTECT, related_name="tickets"
    )
    office = models.ForeignKey(
        "organisations.Office", on_delete=models.PROTECT, related_name="tickets"
    )
    queue = models.ForeignKey(
        "organisations.ServiceLocation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
    )

    assignee = models.ForeignKey(
        "identity_access.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assigned_tickets",
    )
    team = models.CharField(max_length=128, blank=True)

    confidentiality = models.CharField(
        max_length=16, choices=Confidentiality.choices, default=Confidentiality.NORMAL
    )

    # --- Legal hold ------------------------------------------------------
    # When set, retention disposal (apps.administration.retention) MUST skip
    # this ticket and all messages/notes attached to it. Holds are set by an
    # authorised administrator and have an optional expiry.
    legal_hold = models.BooleanField(default=False, db_index=True)
    legal_hold_expires_at = models.DateTimeField(null=True, blank=True)
    legal_hold_reason = models.CharField(max_length=255, blank=True)

    matter_reference = models.CharField(max_length=128, blank=True, db_index=True)
    external_message_id = models.CharField(max_length=255, blank=True, db_index=True)

    waiting_reason = models.CharField(max_length=64, blank=True)
    blocked_reason = models.TextField(blank=True)
    next_action = models.CharField(max_length=255, blank=True)
    next_action_at = models.DateTimeField(null=True, blank=True)

    resolution_code = models.CharField(max_length=64, blank=True)
    resolution_summary = models.TextField(blank=True)

    tags = models.JSONField(default=list, blank=True)
    custom_fields = models.JSONField(default=dict, blank=True)

    acknowledged_at = models.DateTimeField(null=True, blank=True)
    first_responded_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    reopened_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProtectedTicketQuerySet.as_manager()

    class Meta:
        base_manager_name = "objects"
        db_table = "ticket"
        indexes = [
            models.Index(fields=["domain", "status"]),
            models.Index(fields=["domain", "priority"]),
            models.Index(fields=["assignee", "status"]),
            models.Index(fields=["requester", "-created_at"]),
            models.Index(fields=["office", "status"]),
            models.Index(fields=["created_at"]),
        ]
        ordering = ("-created_at",)

    def __str__(self) -> str:  # pragma: no cover
        return self.number

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        raise ValidationError("Tickets may only be deleted by approved retention.")


class ImmutableCustodyQuerySet(models.QuerySet["TicketCustodyEvent"]):
    def update(self, **kwargs: object) -> int:
        raise ValidationError("Ticket custody events are immutable.")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValidationError("Ticket custody events are immutable.")


class TicketCustodyEvent(models.Model):
    """An append-only internal record of ticket custody changes."""

    class EventType(models.TextChoices):
        CREATED = "created", "Created"
        ASSIGNED = "assigned", "Assigned"
        REASSIGNED = "reassigned", "Transferred / reassigned"
        UNASSIGNED = "unassigned", "Unassigned"
        QUEUE_CHANGED = "queue_changed", "Queue changed"
        ESCALATED = "escalated", "Escalated"
        STATUS_CHANGED = "status_changed", "Status changed"
        REOPENED = "reopened", "Reopened"
        CLOSED = "closed", "Closed"

    class ActorKind(models.TextChoices):
        USER = "user", "User"
        SYSTEM = "system", "System"
        LEGACY_UNKNOWN = "legacy_unknown", "Legacy actor (unverified)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.DO_NOTHING,
        related_name="custody_events",
    )
    sequence = models.PositiveBigIntegerField()
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    actor_kind = models.CharField(max_length=16, choices=ActorKind.choices)
    actor_subject = models.CharField(max_length=255)
    actor_display_name = models.CharField(max_length=255)
    source_process = models.CharField(max_length=128)
    source_record_type = models.CharField(max_length=64, blank=True)
    source_record_id = models.CharField(max_length=64, blank=True)
    previous_owner = models.JSONField(null=True, blank=True)
    new_owner = models.JSONField(null=True, blank=True)
    previous_queue = models.JSONField(null=True, blank=True)
    new_queue = models.JSONField(null=True, blank=True)
    previous_status = models.JSONField(null=True, blank=True)
    new_status = models.JSONField(null=True, blank=True)
    previous_designations = models.JSONField(default=list, blank=True)
    new_designations = models.JSONField(default=list, blank=True)
    previous_team_labels = models.JSONField(default=list, blank=True)
    new_team_labels = models.JSONField(default=list, blank=True)
    reason = models.TextField(blank=True)
    previous_hash = models.CharField(max_length=64, blank=True)
    event_hash = models.CharField(max_length=64)

    objects = ImmutableCustodyQuerySet.as_manager()

    class Meta:
        base_manager_name = "objects"
        db_table = "ticket_custody_event"
        ordering = ("sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("ticket", "sequence"),
                name="uniq_ticket_custody_sequence",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"custody:{self.ticket_id} sequence:{self.sequence}"

    def save(
        self,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        if not self._state.adding:
            raise ValidationError("Ticket custody events are immutable.")
        super().save(force_insert, force_update, using, update_fields)

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        raise ValidationError("Ticket custody events are immutable.")


class TicketMessage(models.Model):
    """A requester-visible message on the ticket timeline (FR-014, FR-061)."""

    class Direction(models.TextChoices):
        INBOUND = "inbound", "Inbound"
        OUTBOUND = "outbound", "Outbound"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="messages")
    direction = models.CharField(max_length=16, choices=Direction.choices)
    author_subject = models.CharField(max_length=255, blank=True)
    author_label = models.CharField(max_length=255, blank=True)
    body_text = models.TextField()
    body_html = models.TextField(blank=True)
    body_html_sanitized = models.TextField(blank=True)
    template_key = models.CharField(max_length=128, blank=True)
    template_version = models.CharField(max_length=32, blank=True)
    external_message_id = models.CharField(max_length=255, blank=True, db_index=True)
    delivery_status = models.CharField(max_length=32, blank=True)
    legal_hold = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "ticket_message"
        ordering = ("created_at",)

    def __str__(self) -> str:
        return f"{self.direction}-message:{self.pk} ticket:{self.ticket_id}"


class TicketNote(models.Model):
    """An internal note — never visible to the requester (FR-015, FR-016)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="notes")
    author_subject = models.CharField(max_length=255)
    body = models.TextField()
    legal_hold = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "ticket_note"
        ordering = ("created_at",)

    def __str__(self) -> str:
        return f"note:{self.pk} ticket:{self.ticket_id}"


class TicketLink(models.Model):
    """Relations between tickets: parent, child, related, duplicate, blocked-by (FR-019)."""

    class Kind(models.TextChoices):
        PARENT = "parent", "Parent of"
        CHILD = "child", "Child of"
        RELATED = "related", "Related to"
        DUPLICATE_OF = "duplicate_of", "Duplicate of"
        BLOCKED_BY = "blocked_by", "Blocked by"
        BLOCKS = "blocks", "Blocks"
        MERGED_FROM = "merged_from", "Merged from"
        IT_CHILD = "it_child", "IT child of operational"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    from_ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="links_from")
    to_ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="links_to")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ticket_link"
        unique_together = [("from_ticket", "to_ticket", "kind")]

    def __str__(self) -> str:
        return f"{self.from_ticket_id} {self.kind} {self.to_ticket_id}"


class Watcher(models.Model):
    """A user who follows a ticket without being a participant (FR-018)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="watchers")
    user = models.ForeignKey(
        "identity_access.User", on_delete=models.CASCADE, related_name="watching"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ticket_watcher"
        unique_together = [("ticket", "user")]

    def __str__(self) -> str:
        return f"watcher:{self.user_id} ticket:{self.ticket_id}"


class OutboxEvent(models.Model):
    """Transactional outbox — events written in the same DB transaction as
    a business change, then published by a worker (PRD §25.3)."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    aggregate = models.CharField(max_length=64, db_index=True)
    aggregate_id = models.CharField(max_length=64, db_index=True)
    event_type = models.CharField(max_length=128, db_index=True)
    payload = models.JSONField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ticket_outbox"

    def __str__(self) -> str:
        return f"{self.event_type}:{self.aggregate}/{self.aggregate_id}"
