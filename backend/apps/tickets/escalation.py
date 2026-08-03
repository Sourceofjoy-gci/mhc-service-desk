from dataclasses import dataclass
from uuid import UUID

from apps.identity_access.authority_lock import LockedUserAuthority
from apps.identity_access.models import User

from .custody import CustodyParty
from .eligibility import (
    AssigneeCandidate,
    eligible_assignee_candidate,
    eligible_escalation_supervisor_candidate,
)
from .models import Ticket


class IneligibleEscalationSupervisor(Exception):  # noqa: N818
    pass


@dataclass(frozen=True)
class EscalationAssignmentPlan:
    supervisor: User
    candidate: AssigneeCandidate
    previous_owner: CustodyParty | None
    new_owner: CustodyParty
    changed: bool


def _party(user: User, candidate: AssigneeCandidate | None) -> CustodyParty:
    return CustodyParty(
        id=str(user.id),
        subject=user.keycloak_subject,
        display_name=user.display_name or user.username,
        designations=candidate.designations if candidate else (),
        team_labels=candidate.team_labels if candidate else (),
    )


def prepare_escalation_assignment(
    ticket: Ticket,
    supervisor_id: UUID,
    *,
    locked_authorities: dict[UUID, LockedUserAuthority],
) -> EscalationAssignmentPlan:
    try:
        target_authority = locked_authorities[supervisor_id]
    except KeyError as exc:
        raise IneligibleEscalationSupervisor from exc
    target_candidate = eligible_escalation_supervisor_candidate(
        ticket,
        target_authority.user,
        snapshot=target_authority.snapshot,
    )
    if target_candidate is None:
        raise IneligibleEscalationSupervisor

    previous_owner = None
    if ticket.assignee_id is not None:
        try:
            previous_authority = locked_authorities[ticket.assignee_id]
        except KeyError as exc:
            raise RuntimeError("Current assignee authority was not locked.") from exc
        previous_candidate = (
            target_candidate
            if ticket.assignee_id == supervisor_id
            else eligible_assignee_candidate(
                ticket,
                previous_authority.user,
                snapshot=previous_authority.snapshot,
            )
        )
        previous_owner = _party(previous_authority.user, previous_candidate)

    return EscalationAssignmentPlan(
        supervisor=target_authority.user,
        candidate=target_candidate,
        previous_owner=previous_owner,
        new_owner=_party(target_authority.user, target_candidate),
        changed=ticket.assignee_id != supervisor_id,
    )
