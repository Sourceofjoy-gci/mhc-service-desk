from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import migrations

PAUSED_STATES = ("paused_requester", "paused_internal", "paused_it")


def _business_seconds_between(start, end, calendar) -> int:
    if start is None or end <= start:
        return 0

    calendar_timezone = ZoneInfo(calendar.timezone)
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    holiday_set = set(calendar.holidays)
    current_date = start.astimezone(calendar_timezone).date()
    end_date = end.astimezone(calendar_timezone).date()
    total = 0
    while current_date <= end_date:
        if current_date.isoformat() not in holiday_set:
            for interval in calendar.weekday_hours.get(str(current_date.isoweekday()), []):
                slot_start = datetime.combine(
                    current_date,
                    time.fromisoformat(interval["start"]),
                    tzinfo=calendar_timezone,
                ).astimezone(UTC)
                slot_end = datetime.combine(
                    current_date,
                    time.fromisoformat(interval["end"]),
                    tzinfo=calendar_timezone,
                ).astimezone(UTC)
                overlap_start = max(start_utc, slot_start)
                overlap_end = min(end_utc, slot_end)
                if overlap_end > overlap_start:
                    total += int((overlap_end - overlap_start).total_seconds())
        current_date += timedelta(days=1)
    return total


def backfill_paused_remaining_business_seconds(apps, schema_editor) -> None:
    """Populate the frozen entitlement for rows created before migration 0003."""
    SlaInstance = apps.get_model("sla", "SlaInstance")
    instances = (
        SlaInstance.objects.filter(
            state__in=PAUSED_STATES,
            remaining_business_seconds__isnull=True,
        )
        .select_related("policy__calendar")
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
        remaining = _business_seconds_between(
            paused_at,
            instance.due_at,
            instance.policy.calendar,
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
