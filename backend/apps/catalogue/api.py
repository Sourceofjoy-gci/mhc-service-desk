"""DRF serializers for the catalogue app."""
from __future__ import annotations

from rest_framework import serializers

from .models import CustomFieldDefinition, RequestType, Service


class CustomFieldDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomFieldDefinition
        fields = ("id", "key", "label", "kind", "required", "choices", "help_text", "order")


class RequestTypeSerializer(serializers.ModelSerializer):
    fields = CustomFieldDefinitionSerializer(many=True, read_only=True)

    class Meta:
        model = RequestType
        fields = ("id", "service", "code", "name", "description", "default_priority", "is_active", "fields")


class ServiceSerializer(serializers.ModelSerializer):
    request_types = RequestTypeSerializer(many=True, read_only=True)

    class Meta:
        model = Service
        fields = ("id", "code", "name", "description", "domain", "is_active", "request_types")
