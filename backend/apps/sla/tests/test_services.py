"""Tests for SLA business calendar and instance state."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from apps.sla.models import BusinessCalendar
from apps.sla.services import add_business_seconds

pytestmark = pytest.mark.django_db


@pytest.fixture
def calendar():
    return BusinessCalendar.objects.create(
        name="Test calendar",
        timezone="UTC",
        weekday_hours={
            "1": [{"start": "09:00", "end": "17:00"}],
            "2": [{"start": "09:00", "end": "17:00"}],
            "3": [],
            "4": [{"start": "09:00", "end": "13:00"}],
            "5": [{"start": "09:00", "end": "17:00"}],
            "6": [],
            "7": [],
        },
        holidays=[],
        is_default=True,
    )


def test_zero_seconds_returns_same_instant(calendar):
    start = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)  # Monday 10:00
    assert add_business_seconds(start, 0, calendar) == start


def test_skips_closed_days(calendar):
    # Wednesday 2026-07-22 is closed
    start = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)
    end = add_business_seconds(start, 60, calendar)
    # Should land on Thursday 2026-07-23 at 09:01
    assert end.weekday() == 3
    assert end.hour == 9
    assert end.minute == 1


def test_skips_holidays(calendar):
    calendar.holidays = ["2026-07-23"]
    calendar.save()
    start = datetime(2026, 7, 22, 16, 0, tzinfo=timezone.utc)  # Wed 16:00
    end = add_business_seconds(start, 60 * 60, calendar)  # +1h
    # Wednesday 16:00 -> 17:00 is closed; Thursday is a holiday; +1h from Friday 09:00 = Friday 10:00
    assert end.weekday() == 4
    assert (end.hour, end.minute) == (10, 0)


def test_within_day_addition(calendar):
    start = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)  # Monday 09:00
    end = add_business_seconds(start, 60 * 30, calendar)  # +30 minutes
    assert (end.hour, end.minute) == (9, 30)


def test_spans_lunch(calendar):
    # Thursday has 09:00-13:00 (4 hours). Start at 12:00, add 3h.
    start = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)  # Thursday
    end = add_business_seconds(start, 60 * 60 * 3, calendar)  # +3h
    # Only 1h remains Thursday, then 2h on Friday morning
    assert end.weekday() == 4
    assert (end.hour, end.minute) == (11, 0)
