from __future__ import annotations

from datetime import timedelta
from threading import Event, Thread
from uuid import uuid4

import pytest
from django.contrib import admin
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth.models import Group
from django.db import close_old_connections, connection, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.identity_access.models import Role, User, UserRole

pytestmark = pytest.mark.django_db(transaction=True)


def _user() -> User:
    return User.objects.create(
        username=f"authority-{uuid4().hex}",
        keycloak_subject=f"authority-subject-{uuid4().hex}",
        password="not-used",
    )


def _superuser() -> User:
    return User.objects.create(
        username=f"authority-admin-{uuid4().hex}",
        keycloak_subject=f"authority-admin-subject-{uuid4().hex}",
        is_staff=True,
        is_superuser=True,
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


def _assert_admin_post_waits_for_parent_user(
    *,
    user: User,
    client: Client,
    url: str,
    data: dict[str, object],
) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("Authority lock ordering requires PostgreSQL row locks.")
    user_locked = Event()
    release_user = Event()
    post_finished = Event()
    responses = []
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

    def post_in_admin() -> None:
        close_old_connections()
        try:
            responses.append(client.post(url, data, secure=True))
        except BaseException as exc:
            errors.append(exc)
        finally:
            post_finished.set()
            close_old_connections()

    holder = Thread(target=hold_user, daemon=True)
    poster = Thread(target=post_in_admin, daemon=True)
    try:
        holder.start()
        assert user_locked.wait(timeout=5)
        poster.start()
        assert not post_finished.wait(timeout=0.5)
    finally:
        release_user.set()
        holder.join(timeout=10)
        poster.join(timeout=10)

    assert not holder.is_alive()
    assert not poster.is_alive()
    if errors:
        raise errors[0]
    assert len(responses) == 1
    response = responses[0]
    form_errors = None
    if response.status_code == 200 and response.context:
        admin_form = response.context.get("adminform")
        if admin_form is not None:
            form_errors = admin_form.form.errors
    assert response.status_code == 302, form_errors


def _delete_selected_data(pk: object) -> dict[str, object]:
    return {
        "action": "delete_selected",
        ACTION_CHECKBOX_NAME: [str(pk)],
        "post": "yes",
    }


def _user_change_data(
    user: User,
    *,
    group: Group | None = None,
    active: bool = True,
) -> dict[str, object]:
    data: dict[str, object] = {
        "password": user.password,
        "last_login_0": "",
        "last_login_1": "",
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "date_joined_0": user.date_joined.date().isoformat(),
        "date_joined_1": user.date_joined.time().replace(microsecond=0).isoformat(),
        "keycloak_subject": user.keycloak_subject,
        "display_name": user.display_name,
        "last_keycloak_sync_0": "",
        "last_keycloak_sync_1": "",
        "keycloak_groups": "[]",
        "_save": "Save",
    }
    if active:
        data["is_active"] = "on"
    if group is not None:
        data["groups"] = [str(group.pk)]
    return data


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


def test_actual_admin_user_role_add_and_change_hold_the_parent_user_lock() -> None:
    user = _user()
    role = Role.objects.create(
        keycloak_role="assistant-accountant",
        name="Assistant Accountant",
        scopes=[{"domain": "operational"}],
    )
    client = Client()
    client.force_login(_superuser())

    _assert_admin_post_waits_for_parent_user(
        user=user,
        client=client,
        url=reverse("admin:identity_access_userrole_add"),
        data={
            "user": str(user.pk),
            "role": str(role.pk),
            "office": "",
            "expires_at_0": "",
            "expires_at_1": "",
            "_save": "Save",
        },
    )
    assignment = UserRole.objects.get(user=user, role=role)
    new_expiry = timezone.now() + timedelta(days=1)

    _assert_admin_post_waits_for_parent_user(
        user=user,
        client=client,
        url=reverse("admin:identity_access_userrole_change", args=[assignment.pk]),
        data={
            "user": str(user.pk),
            "role": str(role.pk),
            "office": "",
            "expires_at_0": new_expiry.date().isoformat(),
            "expires_at_1": new_expiry.time().replace(microsecond=0).isoformat(),
            "_save": "Save",
        },
    )
    assignment.refresh_from_db()
    assert assignment.expires_at is not None


def test_actual_admin_user_group_m2m_change_holds_parent_user_lock() -> None:
    user = _user()
    group = Group.objects.create(name="ops-agents")
    client = Client()
    client.force_login(_superuser())

    _assert_admin_post_waits_for_parent_user(
        user=user,
        client=client,
        url=reverse("admin:identity_access_user_change", args=[user.pk]),
        data=_user_change_data(user, group=group),
    )

    assert user.groups.filter(pk=group.pk).exists()


def test_actual_admin_user_deactivation_remains_available_under_authority_lock() -> None:
    user = _user()
    client = Client()
    client.force_login(_superuser())

    _assert_admin_post_waits_for_parent_user(
        user=user,
        client=client,
        url=reverse("admin:identity_access_user_change", args=[user.pk]),
        data=_user_change_data(user, active=False),
    )

    user.refresh_from_db()
    assert user.is_active is False


def test_user_admin_disables_hard_delete_and_delete_selected() -> None:
    user = _user()
    client = Client()
    client.force_login(_superuser())

    delete_response = client.get(
        reverse("admin:identity_access_user_delete", args=[user.pk]),
        secure=True,
    )
    changelist_response = client.get(
        reverse("admin:identity_access_user_changelist"),
        secure=True,
    )

    assert delete_response.status_code == 403
    assert changelist_response.status_code == 200
    action_form = changelist_response.context["action_form"]
    if action_form is not None:
        action_choices = action_form.fields["action"].choices
        assert "delete_selected" not in {value for value, _label in action_choices}


def test_actual_admin_user_role_delete_selected_holds_lock_through_delete() -> None:
    user = _user()
    role = Role.objects.create(
        keycloak_role="accountant",
        name="Accountant",
        scopes=[{"domain": "operational"}],
    )
    assignment = UserRole.objects.create(user=user, role=role)
    client = Client()
    client.force_login(_superuser())

    _assert_admin_post_waits_for_parent_user(
        user=user,
        client=client,
        url=reverse("admin:identity_access_userrole_changelist"),
        data=_delete_selected_data(assignment.pk),
    )

    assert not UserRole.objects.filter(pk=assignment.pk).exists()


def test_actual_admin_group_delete_selected_holds_lock_through_delete() -> None:
    user = _user()
    group = Group.objects.create(name="ops-supervisors")
    user.groups.add(group)
    client = Client()
    client.force_login(_superuser())

    _assert_admin_post_waits_for_parent_user(
        user=user,
        client=client,
        url=reverse("admin:auth_group_changelist"),
        data=_delete_selected_data(group.pk),
    )

    assert not Group.objects.filter(pk=group.pk).exists()


def test_actual_admin_unassigned_role_delete_selected_runs_in_a_transaction() -> None:
    role = Role.objects.create(
        keycloak_role="unused-role",
        name="Unused role",
        scopes=[{"domain": "operational"}],
    )
    client = Client()
    client.force_login(_superuser())

    response = client.post(
        reverse("admin:identity_access_role_changelist"),
        _delete_selected_data(role.pk),
        secure=True,
    )

    assert response.status_code == 302
    assert not Role.objects.filter(pk=role.pk).exists()
