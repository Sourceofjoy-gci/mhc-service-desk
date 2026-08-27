"""Project package marker — exposes the Celery app for `celery -A config`."""

from .celery import app as celery_app

__all__ = ("celery_app",)
