from __future__ import annotations

from datetime import timedelta
from threading import Event, Thread
from uuid import uuid4

import pytest
from django.contrib import admin
from django.contrib.auth.models import Group
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from apps.identity_access.models import Role, User, UserRole

pytestmark = pytest.mark.django_db(transaction=True)


def _user() -> User:
    return User.objects.create(
        username=f"authority-{uuid4().hex}",
        keycloak_subject=f"authority-subject-{uuid4().hex}",
    )


def _set_bounded_database_timeouts() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '3s'")
        cursor.execute("SET LOCAL statement_timeout = '7s'")


def _assert_admin_save_waits_for_parent_user(
    *,
    user: User,
    model: type,
    instance: object,
) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("Authority lock ordering requires PostgreSQL row locks.")
    user_locked = Event()
    release_user = Event()
    save_finished = Event()
    errors: list[BaseException] = []

    def hold_user() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                _set_bounded_database_timeouts()
                User.objects.select_for_update().get(pk=user.pk)
                user_locked.set()
                if not release_user.wait(timeout=5):
                    raise TimeoutError("admin authority lock was not released")
        except BaseException as exc:
            errors.append(exc)
        finally:
            close_old_connections()

    def save_in_admin() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                _set_bounded_database_timeouts()
                admin.site._registry[model].save_model(None, instance, None, True)
        except BaseException as exc:
            errors.append(exc)
        finally:
            save_finished.set()
            close_old_connections()

    holder = Thread(target=hold_user, daemon=True)
    saver = Thread(target=save_in_admin, daemon=True)
    try:
        holder.start()
        assert user_locked.wait(timeout=5)
        saver.start()
        assert not save_finished.wait(timeout=0.5)
    finally:
        release_user.set()
        holder.join(timeout=10)
        saver.join(timeout=10)

    assert not holder.is_alive()
    assert not saver.is_alive()
    if errors:
        raise errors[0]


def test_user_role_admin_locks_parent_user_before_authority_change() -> None:
    user = _user()
    role = Role.objects.create(
        keycloak_role="records-clerk",
        name="Records Clerk",
        scopes=[{"domain": "operational"}],
    )
    assignment = UserRole.objects.create(user=user, role=role)
    assignment.expires_at = timezone.now() + timedelta(days=1)

    _assert_admin_save_waits_for_parent_user(
        user=user,
        model=UserRole,
        instance=assignment,
    )


def test_role_admin_locks_assigned_users_before_scope_change() -> None:
    user = _user()
    role = Role.objects.create(
        keycloak_role="estate-examiner",
        name="Estate Examiner",
        scopes=[{"domain": "operational"}],
    )
    UserRole.objects.create(user=user, role=role)
    role.scopes = [{"domain": "it"}]

    _assert_admin_save_waits_for_parent_user(
        user=user,
        model=Role,
        instance=role,
    )


def test_group_admin_locks_members_before_group_name_change() -> None:
    user = _user()
    group = Group.objects.create(name="ops-agents")
    user.groups.add(group)
    group.name = "it-agents"

    _assert_admin_save_waits_for_parent_user(
        user=user,
        model=Group,
        instance=group,
    )
