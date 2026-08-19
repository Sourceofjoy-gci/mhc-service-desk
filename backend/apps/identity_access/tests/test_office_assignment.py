"""Officers are based at an office and may be stationed at a counter."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.db.models import ProtectedError

from apps.identity_access.models import User
from apps.organisations.models import Office, ServiceLocation

pytestmark = pytest.mark.django_db


def _user(**kwargs) -> User:
    return User.objects.create(
        username=f"user-{uuid4().hex}",
        keycloak_subject=f"subject-{uuid4().hex}",
        **kwargs,
    )


def test_office_and_station_default_to_none():
    user = _user()
    assert user.office is None
    assert user.station is None


def test_user_can_be_based_at_an_office(basic_world):
    office = basic_world["office"]
    user = _user(office=office)
    user.refresh_from_db()
    assert user.office == office
    assert list(office.based_officers.all()) == [user]


def test_user_can_be_stationed_at_a_counter(basic_world):
    office = basic_world["office"]
    station = ServiceLocation.objects.create(office=office, name="Counter-1")
    user = _user(office=office, station=station)
    user.refresh_from_db()
    assert user.station == station
    assert list(station.stationed_officers.all()) == [user]


def test_office_with_officers_cannot_be_deleted(basic_world):
    region = basic_world["region"]
    office = Office.objects.create(region=region, code="DEL-1", name="Deletable")
    _user(office=office)
    with pytest.raises(ProtectedError):
        office.delete()


def test_retiring_a_station_leaves_the_officer_based_at_the_office(basic_world):
    office = basic_world["office"]
    station = ServiceLocation.objects.create(office=office, name="Counter-2")
    user = _user(office=office, station=station)
    station.delete()
    user.refresh_from_db()
    assert user.station is None
    assert user.office == office
