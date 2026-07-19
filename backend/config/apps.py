"""Django app config for the project itself.

Used to wire up the dev-bypass auth in development only.
"""
from django.apps import AppConfig


class ConfigConfig(AppConfig):
    name = "config"
    label = "config"
    verbose_name = "MHC e-Ticketing config"

    def ready(self):
        from django.conf import settings
        if settings.DEBUG and getattr(settings, "ENVIRONMENT", "") == "development":
            try:
                from config.settings.dev import _patch_dev_auth
                _patch_dev_auth()
            except Exception:
                # never block startup on dev hooks
                pass
        return super().ready()
