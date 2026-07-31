from typing import TYPE_CHECKING

from django.contrib import admin
from django.http import HttpRequest

from .models import Office, Region, ServiceLocation

admin.site.register(Region)
admin.site.register(Office)


if TYPE_CHECKING:

    class _ServiceLocationAdminBase(admin.ModelAdmin[ServiceLocation]):
        pass

else:
    _ServiceLocationAdminBase = admin.ModelAdmin


@admin.register(ServiceLocation)
class ServiceLocationAdmin(_ServiceLocationAdminBase):
    """Queues are retired by deactivation; ordinary admin hard delete is disabled."""

    list_display = ("name", "office", "is_active")
    list_filter = ("is_active", "office")

    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: ServiceLocation | None = None,
    ) -> tuple[str, ...]:
        if obj is None:
            return ()
        return ("office", "name")

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: ServiceLocation | None = None,
    ) -> bool:
        return False
