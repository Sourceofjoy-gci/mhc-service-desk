from __future__ import annotations

import pytest

from apps.identity_access.models import Role, User, UserRole
from apps.tickets.models import Ticket
from apps.tickets.seed_workflow import seed_workflow
from apps.tickets.workflow import available_transitions
from apps.workflow.models import Status, Transition

pytestmark = pytest.mark.django_db


PRIVILEGED_OPERATIONAL_TRANSITIONS = {
    ("in_progress", "resolved"): "assistant-master",
    ("quality_review", "resolved"): "assistant-master",
    ("escalated", "in_progress"): "deputy-master",
    ("resolved", "reopened"): "deputy-master",
    ("resolved", "closed"): "master",
    ("cancelled", "closed"): "master",
    ("rejected", "closed"): "master",
    ("duplicate", "closed"): "master",
    ("spam", "closed"): "master",
}


def test_seed_workflow_applies_internal_staff_authority_gates_idempotently():
    seed_workflow()
    Transition.objects.filter(domain="operational").update(required_role="stale-role")

    seed_workflow()
    seeded = {
        (transition.from_status.code, transition.to_status.code): transition.required_role
        for transition in Transition.objects.filter(domain="operational").select_related(
            "from_status",
            "to_status",
        )
    }

    assert {
        key: role for key, role in seeded.items() if role
    } == PRIVILEGED_OPERATIONAL_TRANSITIONS

    escalation_moves = Transition.objects.filter(
        domain="operational",
        to_status__code="escalated",
    )
    assert escalation_moves.exists()
    assert not escalation_moves.exclude(required_role="").exists()
    assert not escalation_moves.exclude(required_fields=["reason"]).exists()


def test_seeded_workflow_enforces_resolution_escalation_and_final_authority(
    basic_world,
):
    seed_workflow()

    def actor(role_key: str) -> User:
        user = User.objects.create(
            username=f"seeded-{role_key}",
            keycloak_subject=f"seeded-{role_key}-subject",
        )
        role = Role.objects.create(
            keycloak_role=role_key,
            name=role_key.replace("-", " ").title(),
            scopes=[{"domain": "operational"}],
        )
        UserRole.objects.create(user=user, role=role, office=basic_world["office"])
        return user

    def ticket(status_code: str, sequence: int) -> Ticket:
        return Ticket.objects.create(
            number=f"R{sequence:05d}",
            domain="operational",
            title=f"Seeded authority {status_code}",
            status=Status.objects.get(domain="operational", code=status_code),
            channel="internal",
            requester=basic_world["contact"],
            service=basic_world["gen_info"],
            request_type=basic_world["gen_info"].request_types.get(),
            office=basic_world["office"],
        )

    examiner = actor("examiner")
    assistant = actor("assistant-master")
    deputy = actor("deputy-master")
    master = actor("master")

    in_progress = ticket("in_progress", 1)
    assert "resolved" not in available_transitions(
        in_progress,
        examiner,
    ).values_list("to_status__code", flat=True)
    assert "resolved" in available_transitions(
        in_progress,
        assistant,
    ).values_list("to_status__code", flat=True)

    escalated = ticket("escalated", 2)
    assert not available_transitions(escalated, assistant).exists()
    assert available_transitions(escalated, deputy).filter(
        to_status__code="in_progress"
    ).exists()

    resolved = ticket("resolved", 3)
    assert set(
        available_transitions(resolved, deputy).values_list(
            "to_status__code",
            flat=True,
        )
    ) == {"reopened"}
    assert set(
        available_transitions(resolved, master).values_list(
            "to_status__code",
            flat=True,
        )
    ) == {"reopened", "closed"}
