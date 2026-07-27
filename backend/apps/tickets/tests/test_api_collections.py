from base64 import b64encode
from datetime import timedelta
from importlib import import_module
from urllib.parse import urlencode
from uuid import UUID, uuid4

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.test import APIClient, APIRequestFactory

from apps.identity_access.models import Role, User
from apps.tickets.models import Ticket
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db


def _agent():
    user = User.objects.create(
        username=f"agent-{uuid4().hex}",
        keycloak_subject=f"subject-{uuid4().hex}",
    )
    user._groups = ["ops-agents"]
    return user


@pytest.fixture
def collection_tickets(basic_world):
    status = Status.objects.get(domain="operational", code="new")
    service = basic_world["gen_info"]
    request_type = service.request_types.get()
    tickets = [
        Ticket(
            id=UUID(int=index + 1),
            number=f"OP-202607-{index + 1:06d}",
            domain="operational",
            title=f"Ticket {index + 1}",
            status=status,
            priority=("P1", "P2", "P3", "P4")[index % 4],
            channel="web",
            requester=basic_world["contact"],
            service=service,
            request_type=request_type,
            office=basic_world["office"],
        )
        for index in range(55)
    ]
    Ticket.objects.bulk_create(tickets)

    baseline = timezone.now() - timedelta(days=10)
    for index, ticket in enumerate(tickets):
        ticket.created_at = baseline + timedelta(minutes=index)
        ticket.updated_at = baseline + timedelta(minutes=(index * 7) % 55)
    Ticket.objects.bulk_update(tickets, ["created_at", "updated_at"])
    return tickets


def _client():
    client = APIClient()
    client.force_authenticate(user=_agent())
    return client


def _all_pages(client, *, sort=None):
    params = {"sort": sort} if sort else {}
    first = client.get(reverse("tickets-list"), params)
    assert first.status_code == 200

    rows = list(first.data["results"])
    next_url = first.data["next"]
    while next_url:
        response = client.get(next_url)
        assert response.status_code == 200
        rows.extend(response.data["results"])
        next_url = response.data["next"]
    return first, rows


def _traverse_pages(fetch, first_url):
    responses = []
    rows = []
    visited_links = set()
    visited_pages = set()
    url = first_url

    while url:
        assert url not in visited_links, "cursor traversal repeated a link"
        visited_links.add(url)

        response = fetch(url)
        assert response.status_code == 200
        assert set(response.data) == {"next", "previous", "results"}
        page_numbers = tuple(row["id"] for row in response.data["results"])
        assert page_numbers not in visited_pages, "cursor traversal repeated a page"
        visited_pages.add(page_numbers)

        if responses:
            assert response.data["previous"] is not None
        responses.append(response)
        rows.extend(response.data["results"])
        url = response.data["next"]

    return responses, rows


def _descending_timestamp(value):
    return -timezone.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def test_ticket_list_uses_cursor_envelope_without_losing_boundary_rows(collection_tickets):
    shared_time = timezone.now() - timedelta(days=1)
    Ticket.objects.update(created_at=shared_time, priority="P3")

    first = _client().get(reverse("tickets-list"))
    second = _client().get(first.data["next"])

    assert set(first.data) == {"next", "previous", "results"}
    assert len(first.data["results"]) == 50
    assert len(second.data["results"]) == 5
    numbers = [row["number"] for row in first.data["results"] + second.data["results"]]
    assert len(numbers) == len(set(numbers)) == 55


def test_queue_sorts_apply_complete_ordering_across_the_cursor(collection_tickets):
    key_functions = {
        "priority": lambda row: (
            row["priority"],
            _descending_timestamp(row["created_at"]),
            -UUID(row["id"]).int,
        ),
        "created": lambda row: (
            _descending_timestamp(row["created_at"]),
            -UUID(row["id"]).int,
        ),
        "updated": lambda row: (
            _descending_timestamp(row["updated_at"]),
            -UUID(row["id"]).int,
        ),
    }

    for sort, key_function in key_functions.items():
        first, rows = _all_pages(_client(), sort=sort)
        assert len(first.data["results"]) == 50
        assert len(rows) == len({row["number"] for row in rows}) == 55
        assert [key_function(row) for row in rows] == sorted(
            key_function(row) for row in rows
        )


def test_unknown_ticket_sort_falls_back_to_default_ordering(collection_tickets):
    _, default_rows = _all_pages(_client(), sort="priority")
    _, unknown_rows = _all_pages(_client(), sort="not-a-sort")

    assert [row["number"] for row in unknown_rows] == [
        row["number"] for row in default_rows
    ]


def test_safe_cursor_falls_back_to_model_primary_key():
    pagination = import_module("apps.identity_access.pagination")

    class UserSerializer(serializers.ModelSerializer):
        class Meta:
            model = User
            fields = ("id",)

    class UserViewSet(viewsets.ReadOnlyModelViewSet):
        queryset = User.objects.all()
        serializer_class = UserSerializer
        pagination_class = pagination.SafeCursorPagination
        authentication_classes = []
        permission_classes = [AllowAny]

    User.objects.bulk_create(
        [
            User(id=UUID(int=1), username="one", keycloak_subject="one"),
            User(id=UUID(int=2), username="two", keycloak_subject="two"),
        ]
    )
    request = APIRequestFactory().get("/users/")
    response = UserViewSet.as_view({"get": "list"})(request)

    assert response.status_code == 200
    assert [row["id"] for row in response.data["results"]] == [
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000001",
    ]
    assert pagination.SafeCursorPagination().get_ordering(
        request,
        User.objects.all(),
        UserViewSet(),
    )[-1] == "-id"


def test_ticket_cursors_cover_large_tied_queue_exactly_once(basic_world):
    status = Status.objects.get(domain="operational", code="new")
    service = basic_world["gen_info"]
    request_type = service.request_types.get()
    tickets = [
        Ticket(
            id=UUID(int=index + 1),
            number=f"OP-202607-{index + 1:06d}",
            domain="operational",
            title=f"Tied ticket {index + 1}",
            status=status,
            priority="P3",
            channel="web",
            requester=basic_world["contact"],
            service=service,
            request_type=request_type,
            office=basic_world["office"],
        )
        for index in range(1055)
    ]
    Ticket.objects.bulk_create(tickets, batch_size=500)
    shared_time = timezone.now() - timedelta(days=1)
    Ticket.objects.update(created_at=shared_time, updated_at=shared_time)
    expected_numbers = [ticket.number for ticket in reversed(tickets)]
    client = _client()

    for sort in ("priority", "created", "updated"):
        query = urlencode({"sort": sort})
        responses, rows = _traverse_pages(
            client.get,
            f"{reverse('tickets-list')}?{query}",
        )
        numbers = [row["number"] for row in rows]

        assert len(responses) == 22
        assert numbers == expected_numbers
        assert len(numbers) == len(set(numbers)) == 1055

        if sort == "priority":
            previous_url = responses[-1].data["previous"]
            for expected_page in reversed(responses[:-1]):
                previous = client.get(previous_url)
                assert previous.status_code == 200
                assert previous.data["results"] == expected_page.data["results"]
                previous_url = previous.data["previous"]
            assert previous_url is None


def test_safe_cursor_covers_large_tied_timestamp_exactly_once():
    pagination = import_module("apps.identity_access.pagination")

    class RoleSerializer(serializers.ModelSerializer):
        class Meta:
            model = Role
            fields = ("id",)

    class RoleViewSet(viewsets.ReadOnlyModelViewSet):
        queryset = Role.objects.all()
        serializer_class = RoleSerializer
        pagination_class = pagination.SafeCursorPagination
        authentication_classes = []
        permission_classes = [AllowAny]

    roles = [
        Role(
            id=UUID(int=index + 1),
            keycloak_role=f"role-{index + 1}",
            name=f"Role {index + 1}",
        )
        for index in range(1055)
    ]
    Role.objects.bulk_create(roles, batch_size=500)
    Role.objects.update(created_at=timezone.now() - timedelta(days=1))
    view = RoleViewSet.as_view({"get": "list"})

    responses, rows = _traverse_pages(
        lambda url: view(APIRequestFactory().get(url)),
        "/roles/",
    )

    assert len(responses) == 22
    assert [row["id"] for row in rows] == [str(role.id) for role in reversed(roles)]
    assert len(rows) == len({row["id"] for row in rows}) == 1055


def test_tampered_compound_cursor_returns_canonical_not_found():
    cursor = b64encode(b"p=not-a-compound-position").decode("ascii")

    response = _client().get(reverse("tickets-list"), {"cursor": cursor})

    assert response.status_code == 404
    assert response.data["code"] == "not_found"
    assert response.data["detail"] == "Invalid cursor"
    assert response.data["fields"] == {}
