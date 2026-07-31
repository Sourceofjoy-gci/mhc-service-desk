"""Deterministic row locks for mutable user-authority facts.

Ticket mutations lock their aggregate first, then call this module. Identity-only
mutations start here. In both cases the suffix order is users, user-role rows,
roles, user/group membership rows, then groups, with UUIDs sorted at each level.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.models import Group
from django.db import connection

from .models import Role, User, UserRole

if TYPE_CHECKING:
    from .scope import AuthoritySnapshot


@dataclass(frozen=True)
class LockedUserAuthority:
    user: User
    snapshot: AuthoritySnapshot


def lock_user_authorities(
    user_ids: Iterable[UUID],
) -> dict[UUID, LockedUserAuthority]:
    """Lock and snapshot current authority for users in deterministic order."""
    if not connection.in_atomic_block:
        raise RuntimeError("Authority rows can only be locked inside a transaction.")

    from .scope import get_authority_snapshot

    ordered_ids = tuple(sorted(set(user_ids), key=str))
    if not ordered_ids:
        return {}

    users = list(
        User.objects.select_for_update(of=("self",)).filter(pk__in=ordered_ids).order_by("id")
    )
    assignments = list(
        UserRole.objects.select_for_update(of=("self",))
        .filter(user_id__in=ordered_ids)
        .order_by("user_id", "id")
    )
    role_ids = tuple(sorted({assignment.role_id for assignment in assignments}, key=str))
    roles = list(
        Role.objects.select_for_update(of=("self",)).filter(pk__in=role_ids).order_by("id")
    )
    roles_by_id = {role.id: role for role in roles}
    for assignment in assignments:
        assignment._state.fields_cache["role"] = roles_by_id[assignment.role_id]

    membership_model = User.groups.through
    memberships = list(
        membership_model.objects.select_for_update(of=("self",))
        .filter(user_id__in=ordered_ids)
        .order_by("user_id", "group_id")
    )
    group_ids = tuple(sorted({row.group_id for row in memberships}, key=str))
    groups = list(
        Group.objects.select_for_update(of=("self",)).filter(pk__in=group_ids).order_by("id")
    )
    groups_by_id = {group.id: group for group in groups}

    assignments_by_user: dict[UUID, list[UserRole]] = {user_id: [] for user_id in ordered_ids}
    for assignment in assignments:
        assignments_by_user[assignment.user_id].append(assignment)
    groups_by_user: dict[UUID, list[Group]] = {user_id: [] for user_id in ordered_ids}
    for membership in memberships:
        groups_by_user[membership.user_id].append(groups_by_id[membership.group_id])

    locked: dict[UUID, LockedUserAuthority] = {}
    for user in users:
        vars(user)["_prefetched_objects_cache"] = {
            "user_roles": assignments_by_user[user.id],
            "groups": groups_by_user[user.id],
        }
        locked[user.id] = LockedUserAuthority(
            user=user,
            snapshot=get_authority_snapshot(user),
        )
    return locked
