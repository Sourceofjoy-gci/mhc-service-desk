"""WhatsApp Business Cloud API adapter.

The adapter is provider-agnostic in shape; in production it is wired to the
official Meta Cloud API. In dev / tests a local mock provider is used so the
pipeline can be exercised without a real Meta account.

The platform NEVER uses unofficial WhatsApp automation (PRD §35, FR-067).
"""
default_app_config = "apps.whatsapp.apps.WhatsappConfig"
