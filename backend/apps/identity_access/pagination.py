import json
from collections.abc import Mapping, Sequence
from typing import TypeVar

from django.core.exceptions import FieldDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Field, Model, Q, QuerySet
from rest_framework.exceptions import NotFound
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.views import APIView

_ModelT = TypeVar("_ModelT", bound=Model)


def _has_concrete_field(model: type[Model], name: str) -> bool:
    try:
        field = model._meta.get_field(name)
    except FieldDoesNotExist:
        return False
    return isinstance(field, Field) and field.concrete


def _reverse_ordering(ordering: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        field.removeprefix("-") if field.startswith("-") else f"-{field}" for field in ordering
    )


class SafeCursorPagination(CursorPagination):
    page_size: int | None = 50
    request: Request

    def paginate_queryset(
        self,
        queryset: QuerySet[_ModelT],
        request: Request,
        view: APIView | None = None,
    ) -> list[_ModelT] | None:
        self.request = request
        page_size = self.get_page_size(request)
        self.page_size = page_size
        if not page_size:
            return None

        self.base_url = request.build_absolute_uri()
        ordering = self.get_ordering(request, queryset, view)
        self.ordering = ordering
        self.cursor = self.decode_cursor(request)
        if self.cursor is None:
            offset, reverse, current_position = 0, False, None
        else:
            offset, reverse = self.cursor.offset, self.cursor.reverse
            raw_position: object = self.cursor.position
            if raw_position is not None and not isinstance(raw_position, str):
                raise NotFound(self.invalid_cursor_message)
            current_position = raw_position

        query_ordering = _reverse_ordering(ordering) if reverse else ordering
        queryset = queryset.order_by(*query_ordering)
        if current_position is not None:
            values = self._decode_position(current_position, ordering)
            try:
                queryset = queryset.filter(self._position_filter(ordering, values, reverse=reverse))
            except (DjangoValidationError, TypeError, ValueError) as exc:
                raise NotFound(self.invalid_cursor_message) from exc

        results = list(queryset[offset : offset + page_size + 1])
        self.page = list(results[:page_size])
        has_following_position = len(results) > len(self.page)
        following_position = (
            self._get_position_from_instance(results[-1], ordering)
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

    def _get_position_from_instance(
        self,
        instance: object,
        ordering: Sequence[str],
    ) -> str:
        values: list[str] = []
        for field in ordering:
            name = field.removeprefix("-")
            value: object = (
                instance[name] if isinstance(instance, Mapping) else getattr(instance, name)
            )
            values.append(str(value))
        return json.dumps(values, separators=(",", ":"))

    def _decode_position(
        self,
        position: str,
        ordering: Sequence[str],
    ) -> list[str]:
        try:
            values: object = json.loads(position)
        except (TypeError, ValueError) as exc:
            raise NotFound(self.invalid_cursor_message) from exc
        if (
            not isinstance(values, list)
            or len(values) != len(ordering)
            or not all(isinstance(value, str) for value in values)
        ):
            raise NotFound(self.invalid_cursor_message)
        return [value for value in values if isinstance(value, str)]

    @staticmethod
    def _position_filter(
        ordering: Sequence[str],
        values: Sequence[str],
        *,
        reverse: bool,
    ) -> Q:
        predicate: Q | None = None
        equal_prefix = Q()
        for field, value in zip(ordering, values, strict=True):
            name = field.removeprefix("-")
            descending = field.startswith("-") ^ reverse
            comparison = "lt" if descending else "gt"
            branch = equal_prefix & Q(**{f"{name}__{comparison}": value})
            if predicate is None:
                predicate = branch
            else:
                predicate |= branch
            equal_prefix &= Q(**{name: value})
        return predicate or Q()

    def get_ordering(
        self,
        request: Request,
        queryset: QuerySet[Model],
        view: APIView | None,
    ) -> tuple[str, ...]:
        primary_key = queryset.model._meta.pk.name
        if _has_concrete_field(queryset.model, "created_at"):
            return ("-created_at", f"-{primary_key}")
        if _has_concrete_field(queryset.model, "updated_at"):
            return ("-updated_at", f"-{primary_key}")
        return (f"-{primary_key}",)


class TicketCursorPagination(SafeCursorPagination):
    SORTS = {
        "priority": ("priority", "-created_at", "-id"),
        "created": ("-created_at", "-id"),
        "updated": ("-updated_at", "-id"),
    }

    def get_ordering(
        self,
        request: Request,
        queryset: QuerySet[Model],
        view: APIView | None,
    ) -> tuple[str, ...]:
        return self.SORTS.get(
            request.query_params.get("sort", "priority"),
            self.SORTS["priority"],
        )
