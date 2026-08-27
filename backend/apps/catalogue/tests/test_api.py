"""Catalogue serializer contracts."""

from __future__ import annotations

from rest_framework import serializers

from apps.catalogue.api import (
    CustomFieldDefinitionSerializer,
    RequestTypeSerializer,
)


def test_request_type_fields_remain_nested_and_read_only() -> None:
    field = RequestTypeSerializer().fields["fields"]

    assert isinstance(field, serializers.ListSerializer)
    assert isinstance(field.child, CustomFieldDefinitionSerializer)
    assert field.read_only is True
