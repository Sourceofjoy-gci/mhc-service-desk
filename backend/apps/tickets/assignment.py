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
from apps.organisations.models import ServiceLocation
from apps.workflow.models import Transition

from .custody import (
    CustodyActor,
    CustodyEventInput,
    CustodyParty,
    CustodyQueue,
    queue_snapshot,
)
from .eligibility import (
    AssigneeCandidate,
    _has_request_local_auditor_claim,
    eligible_assignee_candidate,
    eligible_assignee_candidate_for_queue,
    matching_actor_role_aliases,
)
from .events import record_ticket_event
from .models import Ticket, TicketCustodyEvent
from .permissions import DOMAIN_GROUPS, REASSIGN_GROUPS, can_route_ticket
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
class RoutingReceipt:
    ticket_number: str
    previous_queue: CustodyQueue | None
    new_queue: CustodyQueue | None
    previous_assignee: AssignmentParty | None
    new_assignee: AssignmentParty | None
    occurred_at: datetime
    performed_by: AssignmentActor


@dataclass(frozen=True)
class RoutingResult:
    ticket: Ticket
    receipt: RoutingReceipt


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


def _target_for_routing(
    ticket: Ticket,
    assignee_id: UUID | None,
    queue: ServiceLocation | None,
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
    candidate = eligible_assignee_candidate_for_queue(
        ticket,
        target,
        queue,
        snapshot=target_authority.snapshot,
    )
    if candidate is None:
        raise TicketValidationError({"assignee_id": ["Select an eligible assignee."]})
    return target, candidate


def _routing_party_snapshots(
    *,
    ticket: Ticket,
    target: User | None,
    target_candidate: AssigneeCandidate | None,
    locked_authorities: dict[UUID, LockedUserAuthority],
) -> tuple[_PartySnapshots | None, _PartySnapshots | None]:
    previous_snapshots: _PartySnapshots | None = None
    if ticket.assignee_id is not None:
        previous_authority = locked_authorities[ticket.assignee_id]
        previous_candidate = eligible_assignee_candidate(
            ticket,
            previous_authority.user,
            snapshot=previous_authority.snapshot,
        )
        previous_snapshots = _party_snapshots(
            previous_authority.user,
            previous_candidate,
        )
    new_snapshots = _party_snapshots(target, target_candidate) if target is not None else None
    return previous_snapshots, new_snapshots


def _resolve_destination_queue(
    ticket: Ticket,
    queue_id: UUID | None,
) -> ServiceLocation | None:
    if queue_id is None:
        return None
    destination = (
        ServiceLocation.objects.select_for_update()
        .filter(
            id=queue_id,
            office_id=ticket.office_id,
            is_active=True,
        )
        .first()
    )
    if destination is None:
        raise TicketValidationError(
            {"queue_id": ["Select an active queue in this ticket's office."]}
        )
    return destination


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


def _persist_locked_allocation(
    *,
    locked: Ticket,
    target: User | None,
    destination_queue: ServiceLocation | None,
    previous_snapshots: _PartySnapshots | None,
    new_snapshots: _PartySnapshots | None,
    actor: AssignmentActor,
    custody_actor: CustodyActor,
    source_process: str,
    reason: str,
    routing: bool,
) -> tuple[datetime, str, bool, bool, CustodyQueue | None, CustodyQueue | None]:
    occurred_at = timezone.now()
    previous_assignee_id = locked.assignee_id
    new_assignee_id = target.id if target is not None else None
    previous_queue_id = locked.queue_id
    new_queue_id = destination_queue.id if destination_queue is not None else None
    owner_changed = previous_assignee_id != new_assignee_id
    queue_changed = previous_queue_id != new_queue_id if routing else False
    previous_queue_snapshot = queue_snapshot(locked.queue)
    new_queue_snapshot = queue_snapshot(destination_queue if routing else locked.queue)

    if not owner_changed and not queue_changed:
        if routing:
            raise TicketValidationError({"routing": ["Queue and assignee must change."]})
        return (
            occurred_at,
            "unchanged",
            False,
            False,
            previous_queue_snapshot,
            new_queue_snapshot,
        )

    action = _action_for_change(previous_assignee_id, new_assignee_id)
    previous_id = str(previous_assignee_id) if previous_assignee_id is not None else None
    new_id = str(target.id) if target is not None else None
    previous_queue_value = str(previous_queue_id) if previous_queue_id is not None else None
    new_queue_value = str(new_queue_id) if new_queue_id is not None else None
    locked.assignee = target
    update_fields: list[str] = []
    if owner_changed:
        update_fields.append("assignee")
    if routing:
        locked.queue = destination_queue
        if queue_changed:
            update_fields.append("queue")
    locked.save(update_fields=[*update_fields, "updated_at"])

    custody_inputs: list[CustodyEventInput] = []
    if queue_changed:
        custody_inputs.append(
            CustodyEventInput(
                event_type=TicketCustodyEvent.EventType.QUEUE_CHANGED,
                source_process=source_process,
                previous_queue=previous_queue_snapshot,
                new_queue=new_queue_snapshot,
                reason=reason,
                occurred_at=occurred_at,
            )
        )
    if owner_changed:
        custody_inputs.append(
            CustodyEventInput(
                event_type=action,
                source_process=source_process,
                previous_owner=(previous_snapshots.custody if previous_snapshots else None),
                new_owner=new_snapshots.custody if new_snapshots else None,
                reason=reason,
                occurred_at=occurred_at,
            )
        )
    before = {"assignee": previous_id}
    after = {"assignee": new_id}
    event_action = "ticket.assignment.changed"
    if routing:
        before["queue"] = previous_queue_value
        after["queue"] = new_queue_value
        event_action = "ticket.routing.changed"
    record_ticket_event(
        ticket=locked,
        actor_subject=actor.subject,
        action=event_action,
        before=before,
        after=after,
        metadata={"reason": reason},
        custody_actor=custody_actor,
        custody_events=tuple(custody_inputs),
    )
    return (
        occurred_at,
        action,
        owner_changed,
        queue_changed,
        previous_queue_snapshot,
        new_queue_snapshot,
    )


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
    occurred_at, action, owner_changed, _, _, _ = _persist_locked_allocation(
        locked=locked,
        target=target,
        destination_queue=locked.queue,
        previous_snapshots=previous_snapshots,
        new_snapshots=new_snapshots,
        actor=actor,
        custody_actor=custody_actor,
        source_process=source_process,
        reason=reason,
        routing=False,
    )
    if not owner_changed:
        unchanged_party = previous_snapshots.receipt if previous_snapshots else None
        previous_receipt = unchanged_party
        new_receipt = unchanged_party
    else:
        previous_receipt = previous_snapshots.receipt if previous_snapshots else None
        new_receipt = new_snapshots.receipt if new_snapshots else None
    return AssignmentResult(
        ticket=locked,
        receipt=AssignmentReceipt(
            ticket_number=locked.number,
            action=action,
            previous_assignee=previous_receipt,
            new_assignee=new_receipt,
            occurred_at=occurred_at,
            performed_by=actor,
        ),
        changed=owner_changed,
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


@transaction.atomic
def route_ticket(
    *,
    ticket_id: UUID,
    actor: User,
    queue_id: UUID | None,
    assignee_id: UUID | None,
    expected_updated_at: datetime,
    reason: str,
    request: Request | None = None,
    snapshot: AuthoritySnapshot | None = None,
) -> RoutingResult:
    """Atomically change the explicit resulting queue and owner."""
    request_local_auditor = _has_request_local_auditor_claim(actor, request=request)
    authority = snapshot or get_authority_snapshot(actor, request=request)
    try:
        locked = (
            scope_ticket_queryset(
                actor,
                Ticket.objects.select_for_update(of=("self",)),
                snapshot=authority,
            )
            .select_related("assignee", "queue", "status")
            .get(pk=ticket_id)
        )
    except Ticket.DoesNotExist as exc:
        raise TicketScopeError from exc
    if expected_updated_at != locked.updated_at:
        raise TicketConflictError(locked.updated_at)

    destination = _resolve_destination_queue(locked, queue_id)
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
    if not can_route_ticket(
        locked_actor,
        locked,
        destination,
        request=request,
        snapshot=locked_actor_snapshot,
    ):
        raise TicketPermissionError
    if not reason.strip():
        raise TicketValidationError({"reason": ["This field is required."]})

    target, target_candidate = _target_for_routing(
        locked,
        assignee_id,
        destination,
        locked_authorities=locked_authorities,
    )
    previous_snapshots, new_snapshots = _routing_party_snapshots(
        ticket=locked,
        target=target,
        target_candidate=target_candidate,
        locked_authorities=locked_authorities,
    )
    assignment_actor = AssignmentActor(
        kind=TicketCustodyEvent.ActorKind.USER,
        subject=locked_actor.keycloak_subject,
        display_name=locked_actor.display_name or locked_actor.username,
    )
    (
        occurred_at,
        _,
        _,
        _,
        previous_queue,
        new_queue,
    ) = _persist_locked_allocation(
        locked=locked,
        target=target,
        destination_queue=destination,
        previous_snapshots=previous_snapshots,
        new_snapshots=new_snapshots,
        actor=assignment_actor,
        custody_actor=CustodyActor.user(
            locked_actor.keycloak_subject,
            locked_actor.display_name or locked_actor.username,
        ),
        source_process="ticket.routing",
        reason=reason,
        routing=True,
    )
    return RoutingResult(
        ticket=locked,
        receipt=RoutingReceipt(
            ticket_number=locked.number,
            previous_queue=previous_queue,
            new_queue=new_queue,
            previous_assignee=(previous_snapshots.receipt if previous_snapshots else None),
            new_assignee=new_snapshots.receipt if new_snapshots else None,
            occurred_at=occurred_at,
            performed_by=assignment_actor,
        ),
    )


@transaction.atomic
def route_ticket_by_system(
    *,
    ticket_id: UUID,
    queue_id: UUID | None,
    assignee_id: UUID | None,
    actor_subject: str,
    actor_display_name: str,
    source_process: str,
    reason: str,
) -> RoutingResult:
    """Route through a named internal process without fabricating authority."""
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
        .select_related("assignee", "queue", "status")
        .get(pk=ticket_id)
    )
    destination = _resolve_destination_queue(locked, queue_id)
    authority_user_ids: set[UUID] = set()
    if locked.assignee_id is not None:
        authority_user_ids.add(locked.assignee_id)
    if assignee_id is not None:
        authority_user_ids.add(assignee_id)
    locked_authorities = lock_user_authorities(authority_user_ids)
    target, target_candidate = _target_for_routing(
        locked,
        assignee_id,
        destination,
        locked_authorities=locked_authorities,
    )
    previous_snapshots, new_snapshots = _routing_party_snapshots(
        ticket=locked,
        target=target,
        target_candidate=target_candidate,
        locked_authorities=locked_authorities,
    )
    assignment_actor = AssignmentActor(
        kind=TicketCustodyEvent.ActorKind.SYSTEM,
        subject=actor_subject,
        display_name=actor_display_name,
    )
    (
        occurred_at,
        _,
        _,
        _,
        previous_queue,
        new_queue,
    ) = _persist_locked_allocation(
        locked=locked,
        target=target,
        destination_queue=destination,
        previous_snapshots=previous_snapshots,
        new_snapshots=new_snapshots,
        actor=assignment_actor,
        custody_actor=CustodyActor.system(actor_subject, actor_display_name),
        source_process=source_process,
        reason=reason,
        routing=True,
    )
    return RoutingResult(
        ticket=locked,
        receipt=RoutingReceipt(
            ticket_number=locked.number,
            previous_queue=previous_queue,
            new_queue=new_queue,
            previous_assignee=(previous_snapshots.receipt if previous_snapshots else None),
            new_assignee=new_snapshots.receipt if new_snapshots else None,
            occurred_at=occurred_at,
            performed_by=assignment_actor,
        ),
    )
