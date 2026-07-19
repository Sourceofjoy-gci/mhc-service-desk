"""Models for the Workflow Engine app."""
from __future__ import annotations

import uuid

from django.db import models


class WorkflowDefinition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128, unique=True)
    domain = models.CharField(max_length=16)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "workflowdefinition"

