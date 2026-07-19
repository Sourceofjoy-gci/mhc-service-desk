"""DRF serializers for contacts."""
from __future__ import annotations

from rest_framework import serializers

from .models import Contact, ContactMethod, Organisation


class ContactMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMethod
        fields = ("id", "method", "value", "is_primary", "verified_at")


class ContactSerializer(serializers.ModelSerializer):
    """Default serializer with conservative PII masking (PRD §23.1)."""

    methods = ContactMethodSerializer(many=True, read_only=True)
    email = serializers.SerializerMethodField()
    phone_e164 = serializers.SerializerMethodField()
    is_verified = serializers.BooleanField(read_only=True)

    class Meta:
        model = Contact
        fields = (
            "id", "full_name", "email", "phone_e164", "language",
            "verified_at", "is_verified",
            "opted_out_at", "methods", "created_at",
        )
        read_only_fields = ("id", "created_at", "is_verified")

    def get_email(self, obj: Contact):
        return obj.email or None

    def get_phone_e164(self, obj: Contact):
        return obj.phone_e164 or None


class ContactCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = ("id", "full_name", "email", "phone_e164", "language", "consent_at")
        read_only_fields = ("id",)


class OrganisationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organisation
        fields = ("id", "name", "contact", "created_at")
        read_only_fields = ("id", "created_at")
