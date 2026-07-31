"""Atomic, server-authorised ticket ownership changes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework.request import Request

from apps.identity_access.authority_lock import (
    LockedUserAuthority,
    lock_user_authorities,
)
from apps.identity_access.models import User
from apps.identity_access.scope import (
    AuthoritySnapshot,
    get_authority_snapshot,
    scope_ticket_queryset,
)
from apps.workflow.models import Transition

from .custody import CustodyActor, CustodyEventInput, CustodyParty
from .eligibility import (
    AssigneeCandidate,
    _has_request_local_auditor_claim,
    eligible_assignee_candidate,
    matching_actor_role_aliases,
)
from .events import record_ticket_event
from .models import Ticket, TicketCustodyEvent
from .permissions import DOMAIN_GROUPS, REASSIGN_GROUPS
from .services import (
    TicketConflictError,
    TicketPermissionError,
    TicketScopeError,
    TicketValidationError,
    transition_ticket,
)


@dataclass(frozen=True)
class AssignmentParty:
    id: str
    display_name: str
    designations: tuple[str, ...]
    team_labels: tuple[str, ...]


@dataclass(frozen=True)
class AssignmentActor:
    kind: str
    subject: str
    display_name: str


@dataclass(frozen=True)
class AssignmentReceipt:
    ticket_number: str
    action: str
    previous_assignee: AssignmentParty | None
    new_assignee: AssignmentParty | None
    occurred_at: datetime
    performed_by: AssignmentActor


@dataclass(frozen=True)
class AssignmentResult:
    ticket: Ticket
    receipt: AssignmentReceipt
    changed: bool


@dataclass(frozen=True)
class _PartySnapshots:
    custody: CustodyParty
    receipt: AssignmentParty


def _party_snapshots(
    user: User,
    candidate: AssigneeCandidate | None,
) -> _PartySnapshots:
    custody = CustodyParty(
        id=str(user.id),
        subject=user.keycloak_subject,
        display_name=user.display_name or user.username,
        designations=candidate.designations if candidate else (),
        team_labels=candidate.team_labels if candidate else (),
    )
    return _PartySnapshots(
        custody=custody,
        receipt=AssignmentParty(
            id=custody.id,
            display_name=custody.display_name or user.username,
            designations=custody.designations,
            team_labels=custody.team_labels,
        ),
    )


def _target_for_assignment(
    ticket: Ticket,
    assignee_id: UUID | None,
    *,
    locked_authorities: dict[UUID, LockedUserAuthority],
) -> tuple[User | None, AssigneeCandidate | None]:
    if assignee_id is None:
        return None, None
    try:
        target_authority = locked_authorities[assignee_id]
    except KeyError as exc:
        raise TicketValidationError({"assignee_id": ["Select an eligible assignee."]}) from exc
    target = target_authority.user
    candidate = eligible_assignee_candidate(
        ticket,
        target,
        snapshot=target_authority.snapshot,
    )
    if candidate is None:
        raise TicketValidationError({"assignee_id": ["Select an eligible assignee."]})
    return target, candidate


def _assignment_party_snapshots(
    *,
    ticket: Ticket,
    target: User | None,
    target_candidate: AssigneeCandidate | None,
    locked_authorities: dict[UUID, LockedUserAuthority],
) -> tuple[_PartySnapshots | None, _PartySnapshots | None]:
    previous_snapshots: _PartySnapshots | None = None
    if ticket.assignee_id is not None:
        previous_authority = locked_authorities[ticket.assignee_id]
        previous_candidate = (
            target_candidate
            if target is not None and target.id == ticket.assignee_id
            else eligible_assignee_candidate(
                ticket,
                previous_authority.user,
                snapshot=previous_authority.snapshot,
            )
        )
        previous_snapshots = _party_snapshots(
            previous_authority.user,
            previous_candidate,
        )
    new_snapshots = _party_snapshots(target, target_candidate) if target is not None else None
    return previous_snapshots, new_snapshots


def _can_assign_from_snapshot(
    actor: User,
    ticket: Ticket,
    authority: AuthoritySnapshot,
) -> bool:
    aliases = matching_actor_role_aliases(ticket, actor, snapshot=authority)
    return bool(aliases & REASSIGN_GROUPS)


def _can_update_from_snapshot(
    actor: User,
    ticket: Ticket,
    authority: AuthoritySnapshot,
) -> bool:
    aliases = matching_actor_role_aliases(ticket, actor, snapshot=authority)
    allowed = DOMAIN_GROUPS.get(ticket.domain, set()) | {
        "admin",
        "admin-scope",
        "system-admins",
    }
    return bool(aliases & allowed)


def _action_for_change(
    previous_assignee_id: UUID | None,
    new_assignee_id: UUID | None,
) -> str:
    if previous_assignee_id is None:
        return TicketCustodyEvent.EventType.ASSIGNED
    if new_assignee_id is None:
        return TicketCustodyEvent.EventType.UNASSIGNED
    return TicketCustodyEvent.EventType.REASSIGNED


def _write_locked_assignment(
    *,
    locked: Ticket,
    target: User | None,
    previous_snapshots: _PartySnapshots | None,
    new_snapshots: _PartySnapshots | None,
    actor: AssignmentActor,
    custody_actor: CustodyActor,
    source_process: str,
    reason: str,
) -> AssignmentResult:
    occurred_at = timezone.now()

    if locked.assignee_id == (target.id if target is not None else None):
        unchanged_party = previous_snapshots.receipt if previous_snapshots else None
        return AssignmentResult(
            ticket=locked,
            receipt=AssignmentReceipt(
                ticket_number=locked.number,
                action="unchanged",
                previous_assignee=unchanged_party,
                new_assignee=unchanged_party,
                occurred_at=occurred_at,
                performed_by=actor,
            ),
            changed=False,
        )

    action = _action_for_change(
        locked.assignee_id,
        target.id if target is not None else None,
    )
    previous_id = str(locked.assignee_id) if locked.assignee_id is not None else None
    new_id = str(target.id) if target is not None else None
    locked.assignee = target
    locked.save(update_fields=["assignee", "updated_at"])
    record_ticket_event(
        ticket=locked,
        actor_subject=actor.subject,
        action="ticket.assignment.changed",
        before={"assignee": previous_id},
        after={"assignee": new_id},
        metadata={"reason": reason},
        custody_actor=custody_actor,
        custody_events=(
            CustodyEventInput(
                event_type=action,
                source_process=source_process,
                previous_owner=(previous_snapshots.custody if previous_snapshots else None),
                new_owner=new_snapshots.custody if new_snapshots else None,
                reason=reason,
                occurred_at=occurred_at,
            ),
        ),
    )
    return AssignmentResult(
        ticket=locked,
        receipt=AssignmentReceipt(
            ticket_number=locked.number,
            action=action,
            previous_assignee=(previous_snapshots.receipt if previous_snapshots else None),
            new_assignee=new_snapshots.receipt if new_snapshots else None,
            occurred_at=occurred_at,
            performed_by=actor,
        ),
        changed=True,
    )


def _has_active_assigned_transition(ticket: Ticket) -> bool:
    return Transition.objects.filter(
        domain=ticket.domain,
        from_status=ticket.status,
        to_status__code="assigned",
        is_active=True,
    ).exists()


@transaction.atomic
def assign_ticket(
    *,
    ticket_id: UUID,
    actor: User,
    assignee_id: UUID | None,
    expected_updated_at: datetime,
    reason: str = "",
    request: Request | None = None,
    snapshot: AuthoritySnapshot | None = None,
) -> AssignmentResult:
    """Assign a scoped ticket after rechecking actor and target authority."""
    request_local_auditor = _has_request_local_auditor_claim(
        actor,
        request=request,
    )
    authority = snapshot or get_authority_snapshot(actor, request=request)
    try:
        locked = (
            scope_ticket_queryset(
                actor,
                Ticket.objects.select_for_update(of=("self",)),
                snapshot=authority,
            )
            .select_related("assignee", "status")
            .get(pk=ticket_id)
        )
    except Ticket.DoesNotExist as exc:
        raise TicketScopeError from exc

    if expected_updated_at != locked.updated_at:
        raise TicketConflictError(locked.updated_at)

    authority_user_ids = {actor.id}
    if locked.assignee_id is not None:
        authority_user_ids.add(locked.assignee_id)
    if assignee_id is not None:
        authority_user_ids.add(assignee_id)
    locked_authorities = lock_user_authorities(authority_user_ids)
    locked_actor_authority = locked_authorities.get(actor.id)
    if locked_actor_authority is None or not locked_actor_authority.user.is_active:
        raise TicketPermissionError
    locked_actor = locked_actor_authority.user
    locked_actor_snapshot = locked_actor_authority.snapshot
    if (
        request_local_auditor
        or locked_actor_snapshot.auditor_identity
        or "auditor" in locked_actor_snapshot.capabilities
    ):
        raise TicketPermissionError
    if not scope_ticket_queryset(
        locked_actor,
        Ticket.objects.filter(pk=locked.pk),
        snapshot=locked_actor_snapshot,
    ).exists():
        raise TicketScopeError

    changing_owner = locked.assignee_id != assignee_id
    self_assignment = locked.assignee_id is None and assignee_id == actor.id
    if changing_owner:
        if self_assignment:
            if not _can_update_from_snapshot(
                locked_actor,
                locked,
                locked_actor_snapshot,
            ):
                raise TicketPermissionError
        elif not _can_assign_from_snapshot(
            locked_actor,
            locked,
            locked_actor_snapshot,
        ):
            raise TicketPermissionError

    target, target_candidate = _target_for_assignment(
        locked,
        assignee_id,
        locked_authorities=locked_authorities,
    )
    if self_assignment and target is None:
        raise TicketPermissionError
    if changing_owner and locked.assignee_id is not None and not reason.strip():
        raise TicketValidationError({"reason": ["This field is required."]})

    should_transition = (
        locked.assignee_id is None
        and target is not None
        and _has_active_assigned_transition(locked)
    )
    previous_snapshots, new_snapshots = _assignment_party_snapshots(
        ticket=locked,
        target=target,
        target_candidate=target_candidate,
        locked_authorities=locked_authorities,
    )
    result = _write_locked_assignment(
        locked=locked,
        target=target,
        previous_snapshots=previous_snapshots,
        new_snapshots=new_snapshots,
        actor=AssignmentActor(
            kind=TicketCustodyEvent.ActorKind.USER,
            subject=locked_actor.keycloak_subject,
            display_name=locked_actor.display_name or locked_actor.username,
        ),
        custody_actor=CustodyActor.user(
            locked_actor.keycloak_subject,
            locked_actor.display_name or locked_actor.username,
        ),
        source_process="ticket.assignment",
        reason=reason,
    )
    if should_transition and result.changed:
        transitioned = transition_ticket(
            ticket_id=locked.id,
            actor=locked_actor,
            expected_updated_at=locked.updated_at,
            to_status_code="assigned",
            reason=reason,
            request=request,
            snapshot=locked_actor_snapshot,
        )
        return AssignmentResult(
            ticket=transitioned,
            receipt=result.receipt,
            changed=True,
        )
    return result


@transaction.atomic
def assign_ticket_by_system(
    *,
    ticket_id: UUID,
    assignee_id: UUID | None,
    actor_subject: str,
    actor_display_name: str,
    source_process: str,
    reason: str,
) -> AssignmentResult:
    """Assign through a named internal process without fabricating a user."""
    required_values = {
        "actor_subject": actor_subject,
        "actor_display_name": actor_display_name,
        "source_process": source_process,
        "reason": reason,
    }
    missing = {
        field: ["This field is required."]
        for field, value in required_values.items()
        if not value.strip()
    }
    if missing:
        raise TicketValidationError(missing)

    locked = (
        Ticket.objects.select_for_update(of=("self",))
        .select_related("assignee", "status")
        .get(pk=ticket_id)
    )
    authority_user_ids: set[UUID] = set()
    if locked.assignee_id is not None:
        authority_user_ids.add(locked.assignee_id)
    if assignee_id is not None:
        authority_user_ids.add(assignee_id)
    locked_authorities = lock_user_authorities(authority_user_ids)
    target, target_candidate = _target_for_assignment(
        locked,
        assignee_id,
        locked_authorities=locked_authorities,
    )
    previous_snapshots, new_snapshots = _assignment_party_snapshots(
        ticket=locked,
        target=target,
        target_candidate=target_candidate,
        locked_authorities=locked_authorities,
    )
    return _write_locked_assignment(
        locked=locked,
        target=target,
        previous_snapshots=previous_snapshots,
        new_snapshots=new_snapshots,
        actor=AssignmentActor(
            kind=TicketCustodyEvent.ActorKind.SYSTEM,
            subject=actor_subject,
            display_name=actor_display_name,
        ),
        custody_actor=CustodyActor.system(actor_subject, actor_display_name),
        source_process=source_process,
        reason=reason,
    )
