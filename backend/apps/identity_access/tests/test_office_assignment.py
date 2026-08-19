"""Officers are based at an office and may be stationed at a counter."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.db.models import ProtectedError

from apps.identity_access.authentication import _synchronize_office
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


def _claims(**kwargs) -> dict:
    return {"sub": "subject", "groups": [], **kwargs}


def test_office_claim_is_persisted(basic_world):
    office = basic_world["office"]
    user = _user()
    _synchronize_office(user, _claims(office=office.code))
    user.refresh_from_db()
    assert user.office == office


def test_station_is_resolved_within_the_office(basic_world):
    office = basic_world["office"]
    station = ServiceLocation.objects.create(office=office, name="Counter-A")
    user = _user()
    _synchronize_office(user, _claims(office=office.code, station="Counter-A"))
    user.refresh_from_db()
    assert user.station == station


def test_station_from_another_office_is_ignored(basic_world):
    region = basic_world["region"]
    other = Office.objects.create(region=region, code="OTH-1", name="Other")
    ServiceLocation.objects.create(office=other, name="Counter-B")
    user = _user()
    _synchronize_office(user, _claims(office=basic_world["office"].code, station="Counter-B"))
    user.refresh_from_db()
    assert user.station is None
    assert user.office == basic_world["office"]


def test_unknown_office_code_resolves_to_none(basic_world):
    user = _user(office=basic_world["office"])
    _synchronize_office(user, _claims(office="NO-SUCH-OFFICE"))
    user.refresh_from_db()
    assert user.office is None


def test_inactive_office_resolves_to_none(basic_world):
    region = basic_world["region"]
    office = Office.objects.create(region=region, code="OLD-1", name="Closed", is_active=False)
    user = _user()
    _synchronize_office(user, _claims(office=office.code))
    user.refresh_from_db()
    assert user.office is None


def test_missing_office_claim_clears_a_stored_office(basic_world):
    user = _user(office=basic_world["office"])
    _synchronize_office(user, _claims())
    user.refresh_from_db()
    assert user.office is None


def test_unchanged_claim_performs_no_write(basic_world):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    office = basic_world["office"]
    user = _user(office=office)
    _synchronize_office(user, _claims(office=office.code))
    with CaptureQueriesContext(connection) as captured:
        _synchronize_office(user, _claims(office=office.code))
    updates = [q["sql"] for q in captured.captured_queries if q["sql"].startswith("UPDATE")]
    assert updates == []


def test_dev_token_fourth_segment_sets_the_office(basic_world, client, settings):
    settings.DEBUG = True
    office = basic_world["office"]
    response = client.get(
        "/api/v1/identity/me",
        HTTP_AUTHORIZATION=f"Bearer dev:deskofficer:ops-agents:{office.code}",
    )
    assert response.status_code == 200
    user = User.objects.get(username="deskofficer")
    assert user.office == office


def test_three_segment_dev_token_still_authenticates(basic_world, client, settings):
    settings.DEBUG = True
    response = client.get(
        "/api/v1/identity/me",
        HTTP_AUTHORIZATION="Bearer dev:legacyofficer:ops-agents",
    )
    assert response.status_code == 200
    assert User.objects.get(username="legacyofficer").office is None
