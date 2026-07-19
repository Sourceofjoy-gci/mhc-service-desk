"""Knowledge base models."""
from __future__ import annotations

import uuid

from django.db import models


class KnowledgeArticle(models.Model):
    class Audience(models.TextChoices):
        PUBLIC = "public", "Public"
        INTERNAL_OPERATIONAL = "internal_op", "Internal — Operational"
        INTERNAL_IT = "internal_it", "Internal — IT"
        RESTRICTED = "restricted", "Restricted"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        IN_REVIEW = "in_review", "In review"
        PUBLISHED = "published", "Published"
        RETIRED = "retired", "Retired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=255)
    body = models.TextField()
    audience = models.CharField(max_length=24, choices=Audience.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    domain = models.CharField(max_length=16, choices=[("operational", "Operational"), ("it", "IT")])
    language = models.CharField(max_length=8, default="en")
    version = models.PositiveIntegerField(default=1)
    owner_subject = models.CharField(max_length=255)
    approved_by_subject = models.CharField(max_length=255, blank=True)
    last_reviewed_at = models.DateTimeField(null=True, blank=True)
    next_review_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "knowledge_article"
        indexes = [models.Index(fields=["audience", "status"])]


class KnowledgeUsageLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    article = models.ForeignKey(KnowledgeArticle, on_delete=models.CASCADE, related_name="usages")
    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.SET_NULL, null=True, blank=True)
    actor_subject = models.CharField(max_length=255, blank=True)
    used_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "knowledge_usage"
