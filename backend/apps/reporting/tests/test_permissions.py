from uuid import uuid4

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.identity_access.models import User
from apps.reporting.flow import flow_metrics
from apps.reporting.views import export_tickets_csv, it_dashboard, operational_dashboard
from apps.tickets.models import Ticket
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db


@pytest.fixture
def user_factory():
    def make_user(*, groups):
        user = User.objects.create(
            username=f"user-{uuid4().hex}",
            keycloak_subject=f"subject-{uuid4().hex}",
        )
        user._groups = groups
        return user

    return make_user


@pytest.fixture
def report_tickets(basic_world):
    tickets = {}
    for domain, confidentiality in (
        ("operational", "normal"),
        ("operational", "restricted"),
        ("it", "normal"),
        ("it", "restricted"),
    ):
        service = basic_world["gen_info"] if domain == "operational" else basic_world["it_inc"]
        key = f"{domain}-{confidentiality}"
        prefix = "OP" if domain == "operational" else "IT"
        sequence = 1 if confidentiality == "normal" else 2
        tickets[key] = Ticket.objects.create(
            number=f"{prefix}-202607-{sequence:06d}",
            domain=domain,
            title=key,
            status=Status.objects.get(domain=domain, code="new"),
            priority="P3",
            channel="web",
            requester=basic_world["contact"],
            service=service,
            request_type=service.request_types.get(),
            office=basic_world["office"],
            confidentiality=confidentiality,
        )
    return tickets


@pytest.mark.parametrize(
    ("groups", "view", "expected"),
    [
        (["ops-agents"], operational_dashboard, 200),
        (["ops-agents"], it_dashboard, 403),
        (["it-agents"], operational_dashboard, 403),
        (["it-agents"], it_dashboard, 200),
        (["security-responders"], operational_dashboard, 403),
        (["security-responders"], it_dashboard, 403),
        (["auditors"], operational_dashboard, 200),
        (["auditors"], it_dashboard, 200),
        (["system-admins"], operational_dashboard, 200),
        (["system-admins"], it_dashboard, 200),
    ],
)
def test_dashboard_domain_permissions(groups, view, expected, user_factory):
    request = APIRequestFactory().get("/reports/dashboard")
    user = user_factory(groups=groups)
    force_authenticate(request, user=user)
    assert view(request).status_code == expected


@pytest.mark.parametrize(
    ("groups", "expected_titles"),
    [
        (["ops-agents"], {"operational-normal"}),
        (["it-agents"], {"it-normal"}),
        (
            ["security-responders"],
            {"operational-restricted", "it-restricted"},
        ),
    ],
)
def test_csv_export_contains_only_scoped_rows(
    groups,
    expected_titles,
    report_tickets,
    user_factory,
):
    request = APIRequestFactory().get("/reports/tickets.csv")
    force_authenticate(request, user=user_factory(groups=groups))

    response = export_tickets_csv(request)
    body = b"".join(response.streaming_content).decode()

    assert response.status_code == 200
    for title in expected_titles:
        assert title in body
    for title in {ticket.title for ticket in report_tickets.values()} - expected_titles:
        assert title not in body


@pytest.mark.parametrize(
    ("groups", "domain"),
    [
        (["ops-agents"], "it"),
        (["it-agents"], "operational"),
        (["security-responders"], "operational"),
    ],
)
def test_csv_export_rejects_requested_domain_without_unrestricted_scope(
    groups,
    domain,
    user_factory,
):
    request = APIRequestFactory().get("/reports/tickets.csv", {"domain": domain})
    force_authenticate(request, user=user_factory(groups=groups))

    assert export_tickets_csv(request).status_code == 403


@pytest.mark.parametrize(
    ("groups", "expected_wip"),
    [
        (["ops-agents"], 1),
        (["it-agents"], 1),
        (["security-responders"], 2),
    ],
)
def test_flow_metrics_aggregate_only_scoped_rows(
    groups,
    expected_wip,
    report_tickets,
    user_factory,
):
    request = APIRequestFactory().get("/reports/flow")
    force_authenticate(request, user=user_factory(groups=groups))

    response = flow_metrics(request)

    assert response.status_code == 200
    assert response.data["wip"] == expected_wip


@pytest.mark.parametrize(
    ("groups", "domain"),
    [
        (["ops-agents"], "it"),
        (["it-agents"], "operational"),
        (["security-responders"], "it"),
    ],
)
def test_flow_metrics_rejects_requested_domain_without_unrestricted_scope(
    groups,
    domain,
    user_factory,
):
    request = APIRequestFactory().get("/reports/flow", {"domain": domain})
    force_authenticate(request, user=user_factory(groups=groups))

    assert flow_metrics(request).status_code == 403
