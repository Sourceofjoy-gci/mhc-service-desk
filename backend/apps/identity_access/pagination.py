from rest_framework.pagination import CursorPagination


class SafeCursorPagination(CursorPagination):
    page_size = 50

    def get_ordering(self, request, queryset, view):
        names = {field.name for field in queryset.model._meta.concrete_fields}
        primary_key = queryset.model._meta.pk.name
        if "created_at" in names:
            return ("-created_at", f"-{primary_key}")
        if "updated_at" in names:
            return ("-updated_at", f"-{primary_key}")
        return (f"-{primary_key}",)


class TicketCursorPagination(SafeCursorPagination):
    SORTS = {
        "priority": ("priority", "-created_at", "-id"),
        "created": ("-created_at", "-id"),
        "updated": ("-updated_at", "-id"),
    }

    def get_ordering(self, request, queryset, view):
        return self.SORTS.get(
            request.query_params.get("sort", "priority"),
            self.SORTS["priority"],
        )
