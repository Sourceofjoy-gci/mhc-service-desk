from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast
from uuid import UUID

from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin
from django.contrib.auth.models import Group
from django.db.models import QuerySet
from django.http import HttpRequest

from .authority_lock import lock_user_authorities
from .models import AuditLogin, Role, User, UserRole


def _lock_users(user_ids: Iterable[UUID]) -> None:
    lock_user_authorities(user_ids)


@admin.register(User)
class AuthorityUserAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    def save_model(
        self,
        request: HttpRequest,
        obj: User,
        form: Any,
        change: bool,
    ) -> None:
        if change:
            _lock_users((obj.id,))
        super().save_model(request, obj, form, change)

    def delete_model(self, request: HttpRequest, obj: User) -> None:
        _lock_users((obj.id,))
        super().delete_model(request, obj)

    def delete_queryset(
        self,
        request: HttpRequest,
        queryset: QuerySet[User],
    ) -> None:
        _lock_users(queryset.values_list("id", flat=True))
        super().delete_queryset(request, queryset)


@admin.register(UserRole)
class AuthorityUserRoleAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    def _affected_user_ids(self, obj: UserRole) -> set[UUID]:
        user_ids = {obj.user_id}
        if obj.pk:
            persisted_user_id = (
                UserRole.objects.filter(pk=obj.pk).values_list("user_id", flat=True).first()
            )
            if persisted_user_id is not None:
                user_ids.add(persisted_user_id)
        return user_ids

    def save_model(
        self,
        request: HttpRequest,
        obj: UserRole,
        form: Any,
        change: bool,
    ) -> None:
        _lock_users(self._affected_user_ids(obj))
        super().save_model(request, obj, form, change)

    def delete_model(self, request: HttpRequest, obj: UserRole) -> None:
        _lock_users((obj.user_id,))
        super().delete_model(request, obj)

    def delete_queryset(
        self,
        request: HttpRequest,
        queryset: QuerySet[UserRole],
    ) -> None:
        _lock_users(queryset.values_list("user_id", flat=True))
        super().delete_queryset(request, queryset)


@admin.register(Role)
class AuthorityRoleAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    def _affected_user_ids(self, obj: Role) -> Iterable[UUID]:
        return cast(
            Iterable[UUID],
            UserRole.objects.filter(role_id=obj.id).values_list(
                "user_id",
                flat=True,
            ),
        )

    def save_model(
        self,
        request: HttpRequest,
        obj: Role,
        form: Any,
        change: bool,
    ) -> None:
        if change:
            _lock_users(self._affected_user_ids(obj))
        super().save_model(request, obj, form, change)

    def delete_model(self, request: HttpRequest, obj: Role) -> None:
        _lock_users(self._affected_user_ids(obj))
        super().delete_model(request, obj)

    def delete_queryset(
        self,
        request: HttpRequest,
        queryset: QuerySet[Role],
    ) -> None:
        role_ids = queryset.values_list("id", flat=True)
        _lock_users(
            UserRole.objects.filter(role_id__in=role_ids).values_list(
                "user_id",
                flat=True,
            )
        )
        super().delete_queryset(request, queryset)


class AuthorityGroupAdmin(GroupAdmin):
    def _affected_user_ids(self, obj: Group) -> Iterable[UUID]:
        return cast(
            Iterable[UUID],
            User.groups.through.objects.filter(group_id=obj.id).values_list(
                "user_id",
                flat=True,
            ),
        )

    def save_model(
        self,
        request: HttpRequest,
        obj: Group,
        form: Any,
        change: bool,
    ) -> None:
        if change:
            _lock_users(self._affected_user_ids(obj))
        super().save_model(request, obj, form, change)

    def delete_model(self, request: HttpRequest, obj: Group) -> None:
        _lock_users(self._affected_user_ids(obj))
        super().delete_model(request, obj)

    def delete_queryset(
        self,
        request: HttpRequest,
        queryset: QuerySet[Group],
    ) -> None:
        group_ids = queryset.values_list("id", flat=True)
        user_ids = User.groups.through.objects.filter(group_id__in=group_ids).values_list(
            "user_id",
            flat=True,
        )
        _lock_users(cast(Iterable[UUID], user_ids))
        super().delete_queryset(request, queryset)


admin.site.unregister(Group)
admin.site.register(Group, AuthorityGroupAdmin)
admin.site.register(AuditLogin)
