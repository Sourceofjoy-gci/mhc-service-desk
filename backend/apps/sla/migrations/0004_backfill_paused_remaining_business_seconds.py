from datetime import UTC

from django.db import migrations

PAUSED_STATES = ("paused_requester", "paused_internal", "paused_it")


def _persisted_wall_seconds_between(start, end) -> int:
    """Recover only what persisted timestamps prove, independent of calendars.

    Calendar revisions are not versioned, so the current calendar cannot
    reconstruct historical business entitlement. A current pause interval's
    wall-clock remainder is deterministic; absent history fails closed to zero.
    """
    if start is None:
        return 0
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    return max(0, int((end_utc - start_utc).total_seconds()))


def backfill_paused_remaining_business_seconds(apps, schema_editor) -> None:
    """Populate the frozen entitlement for rows created before migration 0003."""
    SlaInstance = apps.get_model("sla", "SlaInstance")
    instances = (
        SlaInstance.objects.filter(
            state__in=PAUSED_STATES,
            remaining_business_seconds__isnull=True,
        )
        .iterator(chunk_size=500)
    )
    for instance in instances:
        histories = instance.pause_history.all()
        last_resumed_at = (
            histories.filter(state="active")
            .order_by("-at")
            .values_list("at", flat=True)
            .first()
        )
        current_pauses = histories.filter(state__in=PAUSED_STATES)
        if last_resumed_at is not None:
            current_pauses = current_pauses.filter(at__gt=last_resumed_at)
        paused_at = current_pauses.order_by("at").values_list("at", flat=True).first()
        remaining = _persisted_wall_seconds_between(
            paused_at,
            instance.due_at,
        )
        SlaInstance.objects.filter(pk=instance.pk).update(
            remaining_business_seconds=remaining
        )


class Migration(migrations.Migration):
    dependencies = [
        ("sla", "0003_slainstance_remaining_business_seconds"),
    ]

    operations = [
        migrations.RunPython(
            backfill_paused_remaining_business_seconds,
            migrations.RunPython.noop,
        ),
    ]
