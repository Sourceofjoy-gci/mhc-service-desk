import json

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from rest_framework.exceptions import NotFound
from rest_framework.pagination import CursorPagination


def _reverse_ordering(ordering):
    return tuple(
        field.removeprefix("-") if field.startswith("-") else f"-{field}"
        for field in ordering
    )


class SafeCursorPagination(CursorPagination):
    page_size = 50

    def paginate_queryset(self, queryset, request, view=None):
        self.request = request
        self.page_size = self.get_page_size(request)
        if not self.page_size:
            return None

        self.base_url = request.build_absolute_uri()
        self.ordering = self.get_ordering(request, queryset, view)
        self.cursor = self.decode_cursor(request)
        if self.cursor is None:
            offset, reverse, current_position = 0, False, None
        else:
            offset, reverse, current_position = self.cursor

        query_ordering = (
            _reverse_ordering(self.ordering) if reverse else self.ordering
        )
        queryset = queryset.order_by(*query_ordering)
        if current_position is not None:
            values = self._decode_position(current_position, self.ordering)
            try:
                queryset = queryset.filter(
                    self._position_filter(self.ordering, values, reverse=reverse)
                )
            except (DjangoValidationError, TypeError, ValueError) as exc:
                raise NotFound(self.invalid_cursor_message) from exc

        results = list(queryset[offset : offset + self.page_size + 1])
        self.page = list(results[: self.page_size])
        has_following_position = len(results) > len(self.page)
        following_position = (
            self._get_position_from_instance(results[-1], self.ordering)
            if has_following_position
            else None
        )

        if reverse:
            self.page = list(reversed(self.page))
            self.has_next = current_position is not None or offset > 0
            self.has_previous = has_following_position
            if self.has_next:
                self.next_position = current_position
            if self.has_previous:
                self.previous_position = following_position
        else:
            self.has_next = has_following_position
            self.has_previous = current_position is not None or offset > 0
            if self.has_next:
                self.next_position = following_position
            if self.has_previous:
                self.previous_position = current_position

        if self.has_previous or self.has_next:
            self.display_page_controls = self.template is not None
        return self.page

    def _get_position_from_instance(self, instance, ordering):
        values = []
        for field in ordering:
            name = field.removeprefix("-")
            value = instance[name] if isinstance(instance, dict) else getattr(instance, name)
            values.append(str(value))
        return json.dumps(values, separators=(",", ":"))

    def _decode_position(self, position, ordering):
        try:
            values = json.loads(position)
        except (TypeError, ValueError) as exc:
            raise NotFound(self.invalid_cursor_message) from exc
        if (
            not isinstance(values, list)
            or len(values) != len(ordering)
            or not all(isinstance(value, str) for value in values)
        ):
            raise NotFound(self.invalid_cursor_message)
        return values

    @staticmethod
    def _position_filter(ordering, values, *, reverse):
        predicate = None
        equal_prefix = Q()
        for field, value in zip(ordering, values, strict=True):
            name = field.removeprefix("-")
            descending = field.startswith("-") ^ reverse
            comparison = "lt" if descending else "gt"
            branch = equal_prefix & Q(**{f"{name}__{comparison}": value})
            predicate = branch if predicate is None else predicate | branch
            equal_prefix &= Q(**{name: value})
        return predicate

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
