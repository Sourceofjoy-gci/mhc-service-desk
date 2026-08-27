"""Regression tests for the contacts collection API."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.identity_access.models import User

pytestmark = pytest.mark.django_db


def _staff_client() -> APIClient:
    user = User.objects.create(
        username=f"agent-{uuid4().hex}",
        keycloak_subject=f"subject-{uuid4().hex}",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_contact_list_survives_cursor_pagination_with_search():
    Contact.objects.create(full_name="Paging Tester", email="paging@example.test")
    client = _staff_client()

    response = client.get(reverse("contacts-list"), {"search": "Paging"})

    assert response.status_code == 200
    payload = response.json()
    assert [row["full_name"] for row in payload["results"]] == ["Paging Tester"]


def test_contact_list_returns_paginated_envelope_without_search():
    for index in range(3):
        Contact.objects.create(full_name=f"Contact {index}")
    client = _staff_client()

    response = client.get(reverse("contacts-list"))

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["results"]) == 3
